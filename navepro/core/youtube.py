"""Utilitários de URLs do YouTube.

Valida o domínio informado no item da Ordem de Serviço e obtém (via yt-dlp)
o título e a duração do vídeo sem baixá-lo. Usado pelo editor do aplicativo
e pelo controle remoto.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from navepro.core.ambiente import _ambiente_sem_appimage, _eh_flatpak
from navepro.core.log import get_logger
from navepro.core.player import localizar_executavel
from navepro.core.ssl_context import _baixar

log = get_logger("youtube")

# Domínios oficiais usados para hospedar vídeos do YouTube.
_DOMINIOS_YOUTUBE = ("youtube.com", "youtube-nocookie.com")


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
