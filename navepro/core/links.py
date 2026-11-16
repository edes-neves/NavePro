"""Abertura de URLs no navegador/cliente padrão do sistema.

Não usar :mod:`webbrowser` diretamente: ele herda o ambiente do NavePro.
O ``GDK_BACKEND=x11`` definido pelo Tk e as variáveis do AppImage/PyInstaller
fazem o Firefox iniciar uma segunda instância sem conseguir falar com a que
já está aberta, exibindo "Firefox is already running, but is not responding".

Aqui o processo externo recebe um ambiente limpo (sem ``GDK_BACKEND`` e sem as
variáveis do AppImage) e, no Flatpak, a URL é entregue ao ``xdg-open`` do host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from navepro.core.ambiente import (
    _ambiente_sem_appimage,
    _eh_flatpak,
    _eh_windows,
)
from navepro.core.log import get_logger

log = get_logger("links")


def _ambiente_externo() -> dict[str, str]:
    env = _ambiente_sem_appimage()
    env.pop("GDK_BACKEND", None)
    return env


def _comando_url(url: str) -> list[str]:
    if _eh_flatpak():
        return ["flatpak-spawn", "--host", "xdg-open", url]
    if sys.platform == "darwin":
        return ["open", url]
    if shutil.which("xdg-open"):
        return ["xdg-open", url]
    if shutil.which("gio"):
        return ["gio", "open", "--", url]
    return []


def abrir_url_externa(url: str) -> bool:
    """Abre ``url`` no aplicativo padrão do sistema. Retorna se conseguiu."""
    if not url:
        return False
    try:
        if _eh_windows():
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        comando = _comando_url(url)
        if not comando:
            log.warning("Nenhum abridor de URL encontrado para: %s", url)
            return False
        subprocess.Popen(
            comando,
            env=_ambiente_externo(),
            cwd="/",
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — falha de abertura não é fatal
        log.warning("Não foi possível abrir %s: %s", url, exc)
        return False
