"""Utilitários de URLs do YouTube.

Valida o domínio informado no item da Ordem de Serviço, obtém (via yt-dlp)
o título e a duração do vídeo e baixa o vídeo para uma pasta temporária.
Usado pelo editor do aplicativo e pelo controle remoto.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
from urllib.parse import urlparse

from navepro.core.ambiente import _ambiente_sem_appimage, _eh_flatpak
from navepro.core.log import get_logger
from navepro.core.paths import DATA_USER_DIR
from navepro.core.player import localizar_executavel
from navepro.core.ssl_context import _baixar

log = get_logger("youtube")

# Domínios oficiais usados para hospedar vídeos do YouTube.
_DOMINIOS_YOUTUBE = ("youtube.com", "youtube-nocookie.com")

# Vídeos baixados nesta sessão (URL normalizada -> caminho local). O arquivo
# fica em uma pasta temporária e é apagado quando o NavePro é fechado.
_VIDEOS_BAIXADOS: dict[str, str] = {}
_VIDEOS_LOCK = threading.Lock()


def _normalizar_url_youtube(url: str) -> str:
    """Devolve a URL com esquema https:// (aceita link colado sem esquema).

    Quem cola ``youtu.be/ID`` ou ``www.youtube.com/watch?v=ID`` no celular
    espera que funcione; sem isso a validação recusa e o item não salva.
    URLs que já têm esquema são mantidas como estão.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if not url.lower().startswith(("http://", "https://")):
        return "https://" + url
    return url


def _eh_url_youtube(url: str) -> bool:
    """True se `url` for uma URL http(s) de um domínio do YouTube."""
    try:
        partes = urlparse((url or "").strip())
    except ValueError:
        return False
    if partes.scheme.lower() not in ("http", "https"):
        return False
    host = (partes.hostname or "").strip(".").lower()
    if not host:
        return False
    if host == "youtu.be":
        return True
    return any(host == dominio or host.endswith("." + dominio)
               for dominio in _DOMINIOS_YOUTUBE)


def _comando_info_youtube(executavel: str, url: str) -> list[str]:
    """Monta o comando que consulta os metadados do vídeo.

    Dentro do Flatpak o yt-dlp do host não roda direito no sandbox: o pacote
    da distro importa módulos de /usr/lib/python3/dist-packages (invisível
    aqui) e o venv do pipx costuma ter sido criado com outra versão do
    Python. Por isso o yt-dlp é executado no HOST com `flatpak-spawn --host`,
    do mesmo jeito que os wrappers de mpv/smplayer já fazem. O caminho
    /run/host/... é traduzido para o caminho equivalente do sistema.
    """
    caminho = executavel
    if _eh_flatpak():
        if caminho.startswith("/run/host/"):
            caminho = caminho[len("/run/host"):]
        elif caminho.startswith("/app/"):
            # /app só existe no sandbox; no host vale o nome no PATH.
            caminho = os.path.basename(caminho)
        return ["flatpak-spawn", "--host", caminho,
                "--no-playlist", "--skip-download", "--no-warnings",
                "--dump-single-json", url]
    return [caminho, "--no-playlist", "--skip-download", "--no-warnings",
            "--dump-single-json", url]


def _obter_info_youtube(url: str, timeout: float = 15.0) -> dict | None:
    """Obtém título e duração de um vídeo do YouTube via yt-dlp.

    Devolve ``{"titulo": str, "duracao": float}`` ou ``None`` quando o
    yt-dlp não está instalado, a URL não é do YouTube, a rede falha ou o
    vídeo não expõe metadados. Nunca baixa o vídeo.
    """
    url = (url or "").strip()
    if not _eh_url_youtube(url):
        return None
    executavel = (localizar_executavel("yt-dlp")
                  or localizar_executavel("youtube-dl"))
    if not executavel:
        log.warning("⚠️ yt-dlp não encontrado para obter informações do YouTube.")
        return None
    try:
        resultado = subprocess.run(
            _comando_info_youtube(executavel, url),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_ambiente_sem_appimage())
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("⚠️ Falha ao consultar o YouTube (%s): %s", url, exc)
        return None
    if resultado.returncode != 0:
        log.warning("⚠️ yt-dlp não obteve informações de %s: %s",
                    url, (resultado.stderr or "").strip()[:300])
        return None
    try:
        dados = json.loads(resultado.stdout or "{}")
    except ValueError:
        log.warning("⚠️ Resposta inválida do yt-dlp para %s.", url)
        return None
    if not isinstance(dados, dict):
        return None
    titulo = str(dados.get("title") or dados.get("fulltitle") or "").strip()
    if not titulo:
        return None
    try:
        duracao = float(dados.get("duration") or 0)
    except (TypeError, ValueError):
        duracao = 0.0
    return {"titulo": titulo, "duracao": max(0.0, duracao)}


def _obter_info_youtube_oembed(url: str, timeout: float = 8.0) -> dict | None:
    """Obtém só o título do vídeo pelo oEmbed público do YouTube.

    É a reserva para quando o yt-dlp não está instalado ou falha (vídeo
    ao vivo, restrição de idade, bloqueio temporário). O oEmbed costuma
    responder mesmo nesses casos, mas não informa a duração — por isso
    devolve ``duracao`` 0.0. Nunca baixa o vídeo.
    """
    url = _normalizar_url_youtube(url)
    if not _eh_url_youtube(url):
        return None
    consulta = ("https://www.youtube.com/oembed?format=json&url="
                + urllib.parse.quote(url, safe=""))
    try:
        pedido = urllib.request.Request(
            consulta, headers={"User-Agent": "NavePro"})
        with _baixar(pedido, timeout=timeout) as resposta:
            dados = json.loads(
                (resposta.read() or b"{}").decode("utf-8", "replace"))
    except (OSError, ValueError) as exc:
        log.warning("⚠️ oEmbed não obteve informações de %s: %s", url, exc)
        return None
    if not isinstance(dados, dict):
        return None
    titulo = str(dados.get("title") or "").strip()
    if not titulo:
        return None
    return {"titulo": titulo, "duracao": 0.0}


def _pasta_videos_youtube() -> str:
    """Pasta temporária onde os vídeos ficam durante a sessão.

    Fora do Flatpak usa a pasta temporária do sistema (``/tmp`` no Linux),
    que é limpa no desligamento. Dentro do Flatpak o ``/tmp`` é privado do
    sandbox e o yt-dlp roda no host, então usa ``~/.navepro/tmp_youtube``
    (o home é compartilhado com o host pelo manifesto).
    """
    if _eh_flatpak():
        return os.path.join(DATA_USER_DIR, "tmp_youtube")
    return os.path.join(tempfile.gettempdir(), "navepro_youtube")


def _remover_arquivos_parciais(pasta: str, base: str) -> None:
    """Apaga restos de um download que falhou (``base.ext``/``base.part``)."""
    padrao = os.path.join(glob.escape(pasta), glob.escape(base) + ".*")
    for caminho in glob.glob(padrao):
        try:
            os.remove(caminho)
        except OSError:
            pass


def _comando_baixar_youtube(executavel: str, url: str, pasta: str,
                            base: str) -> list[str]:
    """Monta o comando do yt-dlp que baixa o vídeo para ``pasta``.

    O nome de saída é único por download; depois o arquivo é localizado pelo
    prefixo (a extensão pode ser mp4, mkv ou webm, conforme o formato).
    """
    caminho = executavel
    if _eh_flatpak():
        if caminho.startswith("/run/host/"):
            caminho = caminho[len("/run/host"):]
        elif caminho.startswith("/app/"):
            caminho = os.path.basename(caminho)
        prefixo = ["flatpak-spawn", "--host", caminho]
    else:
        prefixo = [caminho]

    nome = os.path.basename(executavel).lower()
    if "youtube-dl" in nome and "yt-dlp" not in nome:
        formato = ["-f", "best[ext=mp4]/best"]
    elif localizar_executavel("ffmpeg"):
        formato = [
            "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "--merge-output-format", "mp4",
        ]
    else:
        # Sem ffmpeg não há como juntar vídeo+áudio: pega o melhor arquivo
        # único (normalmente 720p), que ainda é reproduzível pelo player.
        formato = ["-f", "b[ext=mp4]/b"]

    return [
        *prefixo,
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--socket-timeout", "30",
        "--retries", "3",
        "-o", os.path.join(pasta, base + ".%(ext)s"),
        *formato,
        url,
    ]


def _resumo_erro_ytdlp(resultado: subprocess.CompletedProcess) -> str:
    """Última linha útil do erro do yt-dlp (sem despejar o log inteiro)."""
    saida = (resultado.stderr or resultado.stdout or "").strip()
    if not saida:
        return f"yt-dlp terminou com código {resultado.returncode}."
    linhas = [linha.strip() for linha in saida.splitlines() if linha.strip()]
    return linhas[-1][:500] if linhas else saida[:500]


def baixar_video_youtube(url: str, timeout: float | None = 1800) -> str:
    """Baixa o vídeo do YouTube e devolve o caminho do arquivo local.

    Levanta ``ValueError`` para URL inválida e ``RuntimeError`` quando o
    yt-dlp não existe, a rede falha ou o download não gera um arquivo.
    """
    url = _normalizar_url_youtube(url)
    if not _eh_url_youtube(url):
        raise ValueError("URL inválida! Insira uma URL do YouTube")

    executavel = (localizar_executavel("yt-dlp")
                  or localizar_executavel("youtube-dl"))
    if not executavel:
        raise RuntimeError(
            "yt-dlp não encontrado. Instale com 'sudo apt install yt-dlp' "
            "(ou 'pipx install yt-dlp').")

    pasta = _pasta_videos_youtube()
    os.makedirs(pasta, exist_ok=True)
    base = "video_" + uuid.uuid4().hex
    comando = _comando_baixar_youtube(executavel, url, pasta, base)

    try:
        resultado = subprocess.run(
            comando, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_ambiente_sem_appimage())
    except subprocess.TimeoutExpired as exc:
        _remover_arquivos_parciais(pasta, base)
        raise RuntimeError("Tempo esgotado ao baixar o vídeo do YouTube.") from exc
    except OSError as exc:
        _remover_arquivos_parciais(pasta, base)
        raise RuntimeError(f"Falha ao executar o yt-dlp: {exc}") from exc

    if resultado.returncode != 0:
        detalhe = _resumo_erro_ytdlp(resultado)
        _remover_arquivos_parciais(pasta, base)
        raise RuntimeError(f"Falha ao baixar o vídeo do YouTube: {detalhe}")

    padrao = os.path.join(glob.escape(pasta), glob.escape(base) + ".*")
    candidatos = [caminho for caminho in glob.glob(padrao)
                  if os.path.isfile(caminho) and os.path.getsize(caminho) > 0]
    if not candidatos:
        _remover_arquivos_parciais(pasta, base)
        raise RuntimeError("O yt-dlp não gerou o arquivo do vídeo baixado.")

    # Se sobrar mais de um arquivo (ex.: vídeo + capa), o maior é o vídeo.
    caminho = max(candidatos, key=os.path.getsize)
    log.info("📥 Vídeo do YouTube baixado para %s", caminho)
    return caminho


def obter_video_youtube(url: str) -> str:
    """Devolve o vídeo local, baixando-o na primeira vez nesta sessão."""
    url = _normalizar_url_youtube(url)
    with _VIDEOS_LOCK:
        caminho = _VIDEOS_BAIXADOS.get(url)
    if caminho and os.path.isfile(caminho):
        return caminho
    caminho = baixar_video_youtube(url)
    with _VIDEOS_LOCK:
        _VIDEOS_BAIXADOS[url] = caminho
    return caminho


def limpar_videos_youtube() -> None:
    """Apaga os vídeos temporários do YouTube e limpa o cache da sessão."""
    pasta = _pasta_videos_youtube()
    with _VIDEOS_LOCK:
        _VIDEOS_BAIXADOS.clear()
    if not os.path.isdir(pasta):
        return
    try:
        shutil.rmtree(pasta)
        log.info("🧹 Vídeos temporários do YouTube removidos.")
    except OSError as exc:
        log.warning("⚠️ Não foi possível remover os vídeos temporários: %s", exc)
