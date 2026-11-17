"""Utilitários de URLs do YouTube.

Valida o domínio informado no item da Ordem de Serviço, obtém (via yt-dlp)
o título e a duração do vídeo e baixa o vídeo para uma pasta temporária.
Usado pelo editor do aplicativo e pelo controle remoto.
"""

from __future__ import annotations

import glob
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
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

# Runtimes JavaScript aceitos pelo yt-dlp para resolver o desafio do YouTube.
# O Deno vem primeiro por ser o recomendado e habilitado por padrão.
_RUNTIMES_JS_YOUTUBE = ("deno", "node", "qjs", "bun")

# Capacidades do yt-dlp instalado (saída de --help) e opções extras de JS,
# cacheadas por caminho do executável. O yt-dlp do Ubuntu 24.04 (2024.04.09)
# não conhece --js-runtimes/--remote-components; passar essas opções sempre
# faria um yt-dlp antigo (que ainda funciona) recusar o comando inteiro.
_AJUDA_YTDLP: dict[str, str] = {}
_CACHE_OPCOES_JS: dict[str, list[str]] = {}
_CACHE_YTDLP_LOCK = threading.Lock()

# Runtime JavaScript baixado pelo próprio NavePro (uma vez) quando o sistema
# não tem nenhum. Fica em ~/.navepro/bin e é usado pelo yt-dlp do host também
# no Flatpak (o home é compartilhado com o host pelo manifesto).
_DENO_URL = ("https://github.com/denoland/deno/releases/latest/download/"
             "{asset}")
_DENO_LOCK = threading.Lock()

# yt-dlp oficial baixado pelo NavePro. O pacote do Ubuntu 26.04 (2026.03.17)
# é velho demais para o YouTube atual; o binário oficial é usado quando
# disponível (com fallback para o yt-dlp do sistema).
_YTDLP_URL = ("https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
              "{asset}")
_YTDLP_LOCK = threading.Lock()
_YTDLP_VALIDADE_DIAS = 120

# Marcadores das linhas de progresso do yt-dlp (ver _executar_ytdlp_stream).
_MARCA_TOTAL = "NPINFO "
_RE_PROGRESSO = re.compile(
    r"^NAVEPRO (\S+)\|(\S+)\|(\S+)\|(\S+)\|(\S+)\s*$")


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


def _caminho_no_host(caminho: str) -> str:
    """Traduz um caminho visto no sandbox Flatpak para o caminho do host."""
    if caminho.startswith("/run/host/"):
        return caminho[len("/run/host"):]
    if caminho.startswith("/app/"):
        # /app só existe no sandbox; no host vale o nome no PATH.
        return os.path.basename(caminho)
    return caminho


def _prefixo_ytdlp(executavel: str) -> list[str]:
    """Prefixo para executar o yt-dlp (no host, quando dentro do Flatpak).

    Dentro do sandbox o yt-dlp do host não roda: o pacote da distro importa
    módulos de /usr/lib/python3/dist-packages (invisível aqui) e o venv do
    pipx costuma ter sido criado com outra versão do Python. Por isso ele é
    executado no HOST com `flatpak-spawn --host`, do mesmo jeito que os
    wrappers de mpv/smplayer já fazem.
    """
    if _eh_flatpak():
        return ["flatpak-spawn", "--host", _caminho_no_host(executavel)]
    return [executavel]


def _ajuda_ytdlp(executavel: str) -> str:
    """Saída de `yt-dlp --help` (cacheada por executável; "" se falhar).

    Serve só para saber quais opções esta versão conhece. É preferível a
    comparar versões: o yt-dlp pode vir do apt, pipx ou binário oficial, e
    cada um tem um conjunto diferente de flags.
    """
    with _CACHE_YTDLP_LOCK:
        if executavel in _AJUDA_YTDLP:
            return _AJUDA_YTDLP[executavel]
    texto = ""
    try:
        resultado = subprocess.run(
            [*_prefixo_ytdlp(executavel), "--help"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_ambiente_sem_appimage())
        if resultado.returncode == 0:
            texto = (resultado.stdout or "") + (resultado.stderr or "")
    except (subprocess.SubprocessError, OSError, ValueError):
        texto = ""
    with _CACHE_YTDLP_LOCK:
        _AJUDA_YTDLP[executavel] = texto
    return texto


def _pasta_bin_navepro() -> str:
    """Pasta de executáveis baixados pelo próprio NavePro."""
    return os.path.join(DATA_USER_DIR, "bin")


def _nome_executavel_deno() -> str:
    return "deno.exe" if sys.platform.startswith("win") else "deno"


def _deno_instalado() -> str | None:
    caminho = os.path.join(_pasta_bin_navepro(), _nome_executavel_deno())
    return caminho if os.path.isfile(caminho) else None


def _asset_deno(plataforma: str | None = None,
                maquina: str | None = None) -> str | None:
    """Nome do ZIP oficial do Deno para a plataforma/arquitetura atual."""
    plataforma = plataforma or sys.platform
    maquina = (maquina or platform.machine()).lower()
    if plataforma.startswith("win"):
        if maquina in ("amd64", "x86_64"):
            return "deno-x86_64-pc-windows-msvc.zip"
        if maquina in ("arm64", "aarch64"):
            return "deno-aarch64-pc-windows-msvc.zip"
    elif plataforma.startswith("linux"):
        if maquina in ("x86_64", "amd64"):
            return "deno-x86_64-unknown-linux-gnu.zip"
        if maquina in ("aarch64", "arm64"):
            return "deno-aarch64-unknown-linux-gnu.zip"
    elif plataforma == "darwin":
        if maquina in ("x86_64", "amd64"):
            return "deno-x86_64-apple-darwin.zip"
        if maquina in ("aarch64", "arm64"):
            return "deno-aarch64-apple-darwin.zip"
    return None


def _validar_deno(caminho: str) -> None:
    try:
        resultado = subprocess.run(
            [caminho, "--version"], capture_output=True, text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_ambiente_sem_appimage())
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"o Deno baixado não executou: {exc}") from exc
    if resultado.returncode != 0:
        raise RuntimeError("o Deno baixado não executou corretamente.")


def _baixar_deno(ao_progresso=None) -> str:
    """Baixa o Deno para ~/.navepro/bin (sem sudo) e devolve o caminho.

    É o que permite o YouTube voltar a funcionar no Ubuntu 26.04 sem o
    usuário instalar pacote nenhum: o yt-dlp do sistema exige um runtime
    JavaScript, mas o Ubuntu sugere (não instala) o Node/Deno.
    """
    asset = _asset_deno()
    if not asset:
        raise RuntimeError(
            "não há runtime Deno para esta plataforma/arquitetura.")
    pasta = _pasta_bin_navepro()
    os.makedirs(pasta, exist_ok=True)
    alvo = os.path.join(pasta, _nome_executavel_deno())
    if os.path.isfile(alvo):
        return alvo
    with _DENO_LOCK:
        if os.path.isfile(alvo):
            return alvo
        zip_path = os.path.join(pasta, "deno.zip.part")
        tmp_exe = os.path.join(
            pasta, "deno.novo" + (".exe" if sys.platform.startswith("win")
                                  else ""))
        try:
            if ao_progresso is not None:
                ao_progresso(0.0, "Preparando o YouTube "
                                  "(baixando o runtime JS, uma vez só)...")
            pedido = urllib.request.Request(
                _DENO_URL.format(asset=asset),
                headers={"User-Agent": "NavePro"})
            with _baixar(pedido, timeout=120) as resposta, \
                    open(zip_path, "wb") as saida:
                try:
                    total = int(resposta.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                baixado = 0
                while True:
                    bloco = resposta.read(256 * 1024)
                    if not bloco:
                        break
                    saida.write(bloco)
                    baixado += len(bloco)
                    if ao_progresso is not None and total > 0:
                        ao_progresso(
                            min(99.0, baixado * 100.0 / total),
                            "Preparando o YouTube (runtime JS)...")
            with zipfile.ZipFile(zip_path) as pacote:
                membro = next(
                    (nome for nome in pacote.namelist()
                     if os.path.basename(nome) == _nome_executavel_deno()),
                    None)
                if not membro:
                    raise RuntimeError(
                        "o pacote baixado do Deno não contém o executável.")
                with pacote.open(membro) as origem, \
                        open(tmp_exe, "wb") as destino:
                    shutil.copyfileobj(origem, destino)
            if not sys.platform.startswith("win"):
                os.chmod(tmp_exe, 0o755)
            _validar_deno(tmp_exe)
            os.replace(tmp_exe, alvo)
            with _CACHE_YTDLP_LOCK:
                _CACHE_OPCOES_JS.clear()
            log.info("⬇️ Runtime JavaScript (Deno) instalado em %s", alvo)
            if ao_progresso is not None:
                ao_progresso(100.0, "Runtime JS pronto.")
            return alvo
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"não foi possível preparar o runtime JS: {exc}") from exc
        finally:
            for caminho in (zip_path, tmp_exe):
                try:
                    os.remove(caminho)
                except OSError:
                    pass


def _nome_executavel_ytdlp() -> str:
    return "yt-dlp.exe" if sys.platform.startswith("win") else "yt-dlp"


def _asset_ytdlp(plataforma: str | None = None,
                 maquina: str | None = None) -> str | None:
    """Nome do binário oficial do yt-dlp para a plataforma atual."""
    plataforma = plataforma or sys.platform
    maquina = (maquina or platform.machine()).lower()
    if plataforma.startswith("win"):
        if maquina in ("amd64", "x86_64"):
            return "yt-dlp.exe"
        if maquina in ("arm64", "aarch64"):
            return "yt-dlp_arm64.exe"
        if maquina in ("x86", "i386", "i686"):
            return "yt-dlp_x86.exe"
    elif plataforma.startswith("linux"):
        # Zipapp oficial: pequeno e usa o Python já presente no sistema/host.
        return "yt-dlp"
    elif plataforma == "darwin":
        return "yt-dlp_macos"
    return None


def _ytdlp_gerenciado() -> str | None:
    caminho = os.path.join(_pasta_bin_navepro(), _nome_executavel_ytdlp())
    return caminho if os.path.isfile(caminho) else None


def _validar_ytdlp(caminho: str) -> None:
    try:
        resultado = subprocess.run(
            [caminho, "--version"], capture_output=True, text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_ambiente_sem_appimage())
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"o yt-dlp baixado não executou: {exc}") from exc
    if resultado.returncode != 0:
        raise RuntimeError("o yt-dlp baixado não executou corretamente.")


def _baixar_ytdlp(ao_progresso=None) -> str:
    """Baixa o yt-dlp oficial atual para ~/.navepro/bin (sem sudo).

    O pacote do Ubuntu 26.04 é de março/2026 e o YouTube já mudou desde
    então; o binário oficial do projeto acompanha essas mudanças e evita o
    erro "Requested format is not available"/403 sem o usuário atualizar
    nada manualmente.
    """
    asset = _asset_ytdlp()
    if not asset:
        raise RuntimeError("não há yt-dlp para esta plataforma/arquitetura.")
    pasta = _pasta_bin_navepro()
    os.makedirs(pasta, exist_ok=True)
    alvo = os.path.join(pasta, _nome_executavel_ytdlp())
    with _YTDLP_LOCK:
        if os.path.isfile(alvo):
            try:
                idade = time.time() - os.path.getmtime(alvo)
            except OSError:
                idade = 0
            if idade <= _YTDLP_VALIDADE_DIAS * 86400:
                return alvo
        tmp = os.path.join(
            pasta,
            "yt-dlp.novo" + (".exe" if sys.platform.startswith("win")
                             else ""))
        try:
            if ao_progresso is not None:
                ao_progresso(0.0, "Preparando o YouTube "
                                  "(baixando yt-dlp atualizado)...")
            pedido = urllib.request.Request(
                _YTDLP_URL.format(asset=asset),
                headers={"User-Agent": "NavePro"})
            with _baixar(pedido, timeout=120) as resposta, \
                    open(tmp, "wb") as saida:
                try:
                    total = int(resposta.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                baixado = 0
                while True:
                    bloco = resposta.read(256 * 1024)
                    if not bloco:
                        break
                    saida.write(bloco)
                    baixado += len(bloco)
                    if ao_progresso is not None and total > 0:
                        ao_progresso(
                            min(99.0, baixado * 100.0 / total),
                            "Preparando o YouTube (yt-dlp atualizado)...")
            if not sys.platform.startswith("win"):
                os.chmod(tmp, 0o755)
            _validar_ytdlp(tmp)
            os.replace(tmp, alvo)
            with _CACHE_YTDLP_LOCK:
                _AJUDA_YTDLP.pop(alvo, None)
                _CACHE_OPCOES_JS.pop(alvo, None)
            log.info("⬇️ yt-dlp oficial instalado em %s", alvo)
            if ao_progresso is not None:
                ao_progresso(100.0, "yt-dlp atualizado pronto.")
            return alvo
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"não foi possível preparar o yt-dlp: {exc}") from exc
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _garantir_ytdlp(ao_progresso=None) -> str | None:
    """Usa/baixa o yt-dlp oficial atual sem exigir ação do usuário."""
    alvo = _ytdlp_gerenciado()
    if alvo is not None:
        try:
            idade = time.time() - os.path.getmtime(alvo)
        except OSError:
            idade = 0
        if idade <= _YTDLP_VALIDADE_DIAS * 86400:
            return alvo
    try:
        return _baixar_ytdlp(ao_progresso)
    except RuntimeError as exc:
        log.warning("⚠️ Não foi possível baixar o yt-dlp atualizado: %s", exc)
        return _ytdlp_gerenciado()


def _runtime_js_youtube() -> tuple[str, str] | None:
    """Runtime JavaScript disponível para o yt-dlp resolver o challenge."""
    for nome in _RUNTIMES_JS_YOUTUBE:
        caminho = localizar_executavel(nome)
        if caminho:
            return nome, _caminho_no_host(caminho)
    deno = _deno_instalado()
    if deno is not None:
        return "deno", _caminho_no_host(deno)
    return None


def _garantir_runtime_js(executavel: str, ao_progresso=None
                         ) -> tuple[str, str] | None:
    """Instala sob demanda o Deno quando o yt-dlp exige runtime JS."""
    runtime = _runtime_js_youtube()
    if runtime is not None:
        return runtime
    if "--js-runtimes" not in _ajuda_ytdlp(executavel).lower():
        # yt-dlp antigo (ex.: Ubuntu 24.04): não precisa e recusaria a opção.
        return None
    try:
        caminho = _baixar_deno(ao_progresso)
    except RuntimeError as exc:
        log.warning("⚠️ Não foi possível baixar o runtime JS do YouTube: %s",
                    exc)
        return None
    return ("deno", _caminho_no_host(caminho))


def _opcoes_js_youtube(executavel: str) -> list[str]:
    """Opções de runtime JS/EJS que o yt-dlp instalado entende.

    Desde o yt-dlp 2025.11 o YouTube exige resolver um desafio JavaScript
    com um runtime externo (Deno/Node/QuickJS) e os scripts do yt-dlp-ejs.
    O pacote do Ubuntu 26.04 (2026.03.17) já tem essa exigência, mas nem o
    runtime nem os scripts são instalados por padrão — sem eles o download
    termina em "HTTP Error 403: Forbidden", enquanto o yt-dlp antigo do
    Ubuntu 24.04 (2024.04.09) ainda funciona com o solver interno.

    Devolve lista vazia quando a versão não conhece as opções (para não
    quebrar o yt-dlp antigo) ou quando não há runtime instalado.
    """
    with _CACHE_YTDLP_LOCK:
        if executavel in _CACHE_OPCOES_JS:
            return list(_CACHE_OPCOES_JS[executavel])
    ajuda = _ajuda_ytdlp(executavel).lower()
    opcoes: list[str] = []
    if "--js-runtimes" in ajuda:
        runtime = _runtime_js_youtube()
        if runtime is not None:
            opcoes += ["--js-runtimes", f"{runtime[0]}:{runtime[1]}"]
            if "--remote-components" in ajuda:
                # O pacote da distro não traz o yt-dlp-ejs; o GitHub supre.
                opcoes += ["--remote-components", "ejs:github"]
    with _CACHE_YTDLP_LOCK:
        _CACHE_OPCOES_JS[executavel] = list(opcoes)
    return opcoes


def _comando_info_youtube(executavel: str, url: str) -> list[str]:
    """Monta o comando que consulta os metadados do vídeo."""
    return [
        *_prefixo_ytdlp(executavel),
        *_opcoes_js_youtube(executavel),
        "--no-playlist", "--skip-download", "--no-warnings",
        "--dump-single-json", url,
    ]


def _obter_info_youtube(url: str, timeout: float = 15.0) -> dict | None:
    """Obtém título e duração de um vídeo do YouTube via yt-dlp.

    Devolve ``{"titulo": str, "duracao": float}`` ou ``None`` quando o
    yt-dlp não está instalado, a URL não é do YouTube, a rede falha ou o
    vídeo não expõe metadados. Nunca baixa o vídeo.
    """
    url = (url or "").strip()
    if not _eh_url_youtube(url):
        return None
    executavel = (_ytdlp_gerenciado()
                  or localizar_executavel("yt-dlp")
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


def _eh_ytdlp(executavel: str) -> bool:
    nome = os.path.basename(executavel).lower()
    return "youtube-dl" not in nome or "yt-dlp" in nome


def _comando_baixar_youtube(executavel: str, url: str, pasta: str,
                            base: str, cliente_youtube: str = "",
                            com_progresso: bool = False) -> list[str]:
    """Monta o comando do yt-dlp que baixa o vídeo para ``pasta``.

    O nome de saída é único por download; depois o arquivo é localizado pelo
    prefixo (a extensão pode ser mp4, mkv ou webm, conforme o formato).
    `cliente_youtube` força o cliente do extrator (ex.: ``tv,web_safari``) e
    só é usado nas novas tentativas depois de um 403. `com_progresso` emite
    linhas ``NAVEPRO ...``/``NPINFO ...`` em vez de suprimir a barra.
    """
    prefixo = _prefixo_ytdlp(executavel)
    eh_ytdlp = _eh_ytdlp(executavel)
    ajuda = _ajuda_ytdlp(executavel).lower() if eh_ytdlp else ""

    if not eh_ytdlp:
        formato = ["-f", "best[ext=mp4]/best"]
    elif localizar_executavel("ffmpeg"):
        formato = [
            # 1080p é o suficiente para projeção e evita baixar 4K (muito
            # maior e mais lento). O último fallback mantém o melhor formato
            # quando o vídeo só oferece resoluções acima disso.
            "-f",
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
            "b[height<=1080][ext=mp4]/"
            "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
            "--merge-output-format", "mp4",
        ]
    else:
        # Sem ffmpeg não há como juntar vídeo+áudio: pega o melhor arquivo
        # único (normalmente 720p), que ainda é reproduzível pelo player.
        formato = ["-f", "b[height<=1080][ext=mp4]/b[ext=mp4]/b"]

    opcoes_cliente = (["--extractor-args",
                       f"youtube:player_client={cliente_youtube}"]
                      if cliente_youtube else [])

    # Fragmentos em paralelo são o maior ganho de velocidade em vídeos DASH
    # (o padrão do yt-dlp é um por vez). Só é passado se a versão conhece.
    opcoes_velocidade = []
    if "--concurrent-fragments" in ajuda:
        opcoes_velocidade = ["--concurrent-fragments", "4"]

    opcoes_progresso = []
    if com_progresso and eh_ytdlp:
        # O --print (que implica --quiet) precisa vir antes do --no-quiet.
        opcoes_progresso = [
            "--newline",
            "--print", "before_dl:NPINFO %(filesize_approx)s",
            "--no-quiet",
            "--progress-template",
            "download:NAVEPRO %(progress.percent)s|"
            "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
            "%(progress.eta)s|%(progress.speed)s",
        ]

    return [
        *prefixo,
        *_opcoes_js_youtube(executavel),
        *opcoes_cliente,
        *opcoes_velocidade,
        *opcoes_progresso,
        "--no-playlist",
        "--no-warnings",
        *([] if com_progresso else ["--no-progress"]),
        "--socket-timeout", "30",
        "--retries", "3",
        "-o", os.path.join(pasta, base + ".%(ext)s"),
        *formato,
        url,
    ]


def _precisa_retentar(resultado: subprocess.CompletedProcess) -> bool:
    """Erros que podem sumir ao trocar o cliente do extrator do YouTube."""
    texto = (resultado.stderr or resultado.stdout or "").lower()
    return ("403" in texto or "forbidden" in texto
            or "requested format is not available" in texto)


def _dica_erro_youtube(resultado: subprocess.CompletedProcess,
                       executavel: str) -> str:
    texto = (resultado.stderr or resultado.stdout or "").lower()
    if "403" in texto or "forbidden" in texto:
        return _dica_erro_403(executavel)
    if "requested format is not available" in texto:
        return ("\n\nO YouTube não ofereceu formatos baixáveis. O NavePro "
                "tenta baixar o yt-dlp oficial atual; se isso falhou, "
                "verifique a internet ou atualize o yt-dlp.")
    return ""


def _dica_erro_403(executavel: str) -> str:
    """Explica o 403 e o que instalar/atualizar (texto para a interface)."""
    if "--js-runtimes" in _ajuda_ytdlp(executavel).lower() \
            and _runtime_js_youtube() is None:
        return ("\n\nO yt-dlp desta versão precisa de um runtime JavaScript "
                "para o YouTube e nenhum foi encontrado. Instale o Node.js "
                "('sudo apt install nodejs') ou o Deno e tente novamente.")
    return ("\n\nO YouTube recusou o download (HTTP 403). Atualize o yt-dlp "
            "('pipx upgrade yt-dlp') ou instale o binário oficial com "
            "'pipx install \"yt-dlp[default]\"'.")


def _resumo_erro_ytdlp(resultado: subprocess.CompletedProcess) -> str:
    """Última linha útil do erro do yt-dlp (sem despejar o log inteiro)."""
    saida = (resultado.stderr or resultado.stdout or "").strip()
    if not saida:
        return f"yt-dlp terminou com código {resultado.returncode}."
    linhas = [linha.strip() for linha in saida.splitlines() if linha.strip()]
    return linhas[-1][:500] if linhas else saida[:500]


def _formatar_velocidade(bytes_por_segundo: float) -> str:
    if not bytes_por_segundo or bytes_por_segundo <= 0:
        return ""
    valor = float(bytes_por_segundo)
    for unidade in ("B/s", "KB/s", "MB/s", "GB/s"):
        if valor < 1024 or unidade == "GB/s":
            return f"{valor:.1f} {unidade}"
        valor /= 1024
    return ""


def _formatar_eta(segundos: float) -> str:
    if not segundos or segundos <= 0:
        return ""
    total = int(segundos)
    if total >= 3600:
        return f"{total // 3600}h{(total % 3600) // 60:02d}min"
    return f"{total // 60}:{total % 60:02d}"


def _float_ou_zero(texto: str) -> float:
    try:
        return float(texto)
    except (TypeError, ValueError):
        return 0.0


def _executar_ytdlp_stream(comando: list[str], timeout: float | None,
                           ao_progresso) -> subprocess.CompletedProcess:
    """Executa o yt-dlp lendo a saída linha a linha e informa o progresso.

    O yt-dlp imprime o progresso no stdout. Aqui traduzimos as linhas
    ``NAVEPRO`` para uma porcentagem global (somando vídeo+áudio) e
    devolvemos um ``CompletedProcess`` compatível com o caminho sem
    progresso (stdout = log sem as linhas de progresso).
    """
    fila: queue.Queue[str | None] = queue.Queue()
    processo = subprocess.Popen(
        comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=_ambiente_sem_appimage())

    def _ler_saida() -> None:
        try:
            if processo.stdout is not None:
                for linha in processo.stdout:
                    fila.put(linha)
        finally:
            fila.put(None)

    threading.Thread(target=_ler_saida, daemon=True,
                     name="navepro-ytdlp-saida").start()

    limite = time.monotonic() + timeout if timeout else None
    base_bytes = 0.0
    ultimo_total = 0.0
    ultimo_baixado = 0.0
    total_esperado = 0.0
    ultimo_pct = -1.0
    log_linhas: list[str] = []

    while True:
        try:
            item = fila.get(timeout=0.5)
        except queue.Empty:
            if limite is not None and time.monotonic() >= limite:
                try:
                    processo.kill()
                except OSError:
                    pass
                processo.wait()
                raise subprocess.TimeoutExpired(comando, timeout) from None
            continue
        if item is None:
            break
        linha = item.rstrip()
        if not linha:
            continue
        if linha.startswith(_MARCA_TOTAL):
            total_esperado = _float_ou_zero(
                linha[len(_MARCA_TOTAL):].strip())
            continue
        encontrado = _RE_PROGRESSO.match(linha)
        if encontrado:
            pct_str, baixado_s, total_s, eta_s, velocidade_s = \
                encontrado.groups()
            baixado = _float_ou_zero(baixado_s)
            total = _float_ou_zero(total_s)
            if baixado < ultimo_baixado and ultimo_total > 0:
                base_bytes += ultimo_total
            ultimo_baixado = baixado
            ultimo_total = total
            if total_esperado > 0:
                pct = (base_bytes + baixado) * 100.0 / total_esperado
            elif total > 0:
                pct = baixado * 100.0 / total
            else:
                pct = _float_ou_zero(pct_str)
            pct = max(0.0, min(100.0, pct))
            # Evita encher a fila da interface em downloads muito rápidos.
            if pct - ultimo_pct < 1.0 and pct < 100.0:
                continue
            ultimo_pct = pct
            partes = []
            velocidade = _formatar_velocidade(
                _float_ou_zero(velocidade_s))
            if velocidade:
                partes.append(velocidade)
            eta = _formatar_eta(_float_ou_zero(eta_s))
            if eta:
                partes.append(f"faltam {eta}")
            ao_progresso(pct, " · ".join(partes) or "Baixando...")
            continue
        if linha.startswith("[download] Destination:"):
            if ultimo_total > 0 and ultimo_baixado >= ultimo_total * 0.99:
                base_bytes += ultimo_total
            ultimo_baixado = 0.0
            ultimo_total = 0.0
            continue
        if "[Merger]" in linha or "[ffmpeg]" in linha \
                or "Merging formats" in linha:
            ao_progresso(100.0, "Finalizando o vídeo...")
        log_linhas.append(linha)
        if len(log_linhas) > 400:
            del log_linhas[:200]

    codigo = processo.wait()
    if processo.stdout is not None:
        try:
            processo.stdout.close()
        except OSError:
            pass
    return subprocess.CompletedProcess(
        comando, codigo, "\n".join(log_linhas), "")


def _executar_ytdlp(comando: list[str], timeout: float | None,
                    ao_progresso) -> subprocess.CompletedProcess:
    if ao_progresso is None:
        return subprocess.run(
            comando, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_ambiente_sem_appimage())
    return _executar_ytdlp_stream(comando, timeout, ao_progresso)


def baixar_video_youtube(url: str, timeout: float | None = 1800,
                         ao_progresso=None) -> str:
    """Baixa o vídeo do YouTube e devolve o caminho do arquivo local.

    Levanta ``ValueError`` para URL inválida e ``RuntimeError`` quando o
    yt-dlp não existe, a rede falha ou o download não gera um arquivo.
    `ao_progresso(porcentagem, texto)` é chamado durante o download (e
    enquanto o runtime JS é preparado), sempre em thread de trabalho.
    """
    url = _normalizar_url_youtube(url)
    if not _eh_url_youtube(url):
        raise ValueError("URL inválida! Insira uma URL do YouTube")

    if ao_progresso is not None:
        ao_progresso(0.0, "Preparando o YouTube...")
    # Usa o yt-dlp oficial atual (baixado uma vez, sem sudo). O pacote do
    # Ubuntu 26.04 é antigo demais para o YouTube de hoje.
    gerenciado = _garantir_ytdlp(ao_progresso)
    executavel = (gerenciado
                  or localizar_executavel("yt-dlp")
                  or localizar_executavel("youtube-dl"))
    if not executavel:
        raise RuntimeError(
            "yt-dlp não encontrado. Instale com 'sudo apt install yt-dlp' "
            "(ou 'pipx install yt-dlp').")

    # Ubuntu 26.04: o yt-dlp exige runtime JS e o sistema não o instala.
    # Baixa o Deno para ~/.navepro/bin na primeira vez, sem sudo.
    _garantir_runtime_js(executavel, ao_progresso)
    if ao_progresso is not None:
        ao_progresso(0.0, "Iniciando download...")

    pasta = _pasta_videos_youtube()
    os.makedirs(pasta, exist_ok=True)
    base = "video_" + uuid.uuid4().hex

    # Primeira tentativa com o cliente padrão do yt-dlp. Se o YouTube
    # responder 403, tenta clientes alternativos: o yt-dlp de algumas
    # distros (ex.: Ubuntu 26.04, 2026.03.17) ainda usa o "android_vr",
    # cujos formatos passaram a ser recusados pelo YouTube; o yt-dlp
    # oficial removeu esse cliente. O "tv,web_safari" é a alternativa
    # atual. O yt-dlp antigo do Ubuntu 24.04 funciona no primeiro try.
    clientes = [""]
    if _eh_ytdlp(executavel):
        clientes += ["default,-android_vr", "tv,web_safari"]

    resultado = None
    primeiro_resultado = None
    for indice, cliente in enumerate(clientes):
        comando = _comando_baixar_youtube(
            executavel, url, pasta, base, cliente_youtube=cliente,
            com_progresso=ao_progresso is not None)
        _remover_arquivos_parciais(pasta, base)
        try:
            resultado = _executar_ytdlp(comando, timeout, ao_progresso)
        except subprocess.TimeoutExpired as exc:
            _remover_arquivos_parciais(pasta, base)
            raise RuntimeError(
                "Tempo esgotado ao baixar o vídeo do YouTube.") from exc
        except OSError as exc:
            _remover_arquivos_parciais(pasta, base)
            raise RuntimeError(
                f"Falha ao executar o yt-dlp: {exc}") from exc
        if resultado.returncode == 0:
            break
        if primeiro_resultado is None:
            primeiro_resultado = resultado
        if not _precisa_retentar(resultado) or indice + 1 >= len(clientes):
            break
        log.info("↩️ YouTube recusou o cliente padrão; "
                 "tentando novamente com o cliente %s.",
                 clientes[indice + 1])
        if ao_progresso is not None:
            ao_progresso(0.0, "Tentando novamente com outro cliente...")

    if resultado.returncode != 0:
        # Mostra o PRIMEIRO erro: se a tentativa inicial deu 403, os retries
        # com outros clientes podem terminar em "format not available", que
        # esconde a causa real (yt-dlp antigo sem formato baixável).
        base_erro = primeiro_resultado or resultado
        detalhe = _resumo_erro_ytdlp(base_erro)
        _remover_arquivos_parciais(pasta, base)
        dica = _dica_erro_youtube(base_erro, executavel)
        raise RuntimeError(
            f"Falha ao baixar o vídeo do YouTube: {detalhe}{dica}")

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


def video_youtube_baixado(url: str) -> str | None:
    """Caminho local do vídeo se ele já foi baixado nesta sessão.

    Não baixa nada: serve para a interface decidir se mostra ou não o
    diálogo de progresso. Devolve ``None`` quando o arquivo não existe mais.
    """
    url = _normalizar_url_youtube(url)
    with _VIDEOS_LOCK:
        caminho = _VIDEOS_BAIXADOS.get(url)
    if caminho and os.path.isfile(caminho):
        return caminho
    return None


def obter_video_youtube(url: str, ao_progresso=None) -> str:
    """Devolve o vídeo local, baixando-o na primeira vez nesta sessão."""
    url = _normalizar_url_youtube(url)
    caminho = video_youtube_baixado(url)
    if caminho:
        if ao_progresso is not None:
            ao_progresso(100.0, "Vídeo já estava baixado.")
        return caminho
    caminho = baixar_video_youtube(url, ao_progresso=ao_progresso)
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
