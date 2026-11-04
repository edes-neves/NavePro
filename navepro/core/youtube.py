"""Utilitários de URLs do YouTube.

Valida o domínio informado no item da Ordem de Serviço e obtém (via yt-dlp)
o título e a duração do vídeo sem baixá-lo. Usado pelo editor do aplicativo
e pelo controle remoto.
"""

from __future__ import annotations

import json
import subprocess
from urllib.parse import urlparse

from navepro.core.ambiente import _ambiente_sem_appimage
from navepro.core.log import get_logger
from navepro.core.player import localizar_executavel

log = get_logger("youtube")

# Domínios oficiais usados para hospedar vídeos do YouTube.
_DOMINIOS_YOUTUBE = ("youtube.com", "youtube-nocookie.com")


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
            [executavel, "--no-playlist", "--skip-download",
             "--no-warnings", "--dump-single-json", url],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
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
