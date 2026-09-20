"""Caminhos de recursos, dados do usuário e ícones de janela.

A raiz do projeto (onde fica o monolito NavePro.py) é derivada da
localização deste arquivo: navepro/core/... sobe 3 níveis até a raiz.
Os recursos de dev (Icon.png, Icon.xbm, configuração, DB embutido,
uploads) continuam resolvidos em relação à raiz, como antes.
"""

import os
import sys

from navepro.core.ambiente import _eh_windows

_RAIZ_PROJETO: str = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _caminho_base() -> str:
    """Diretório do executável/script (compatível PyInstaller)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return _RAIZ_PROJETO


def _caminho_recurso(nome: str) -> str:
    """Caminho de recurso embutido (PyInstaller) ou local (dev)."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, nome)
    return os.path.join(_RAIZ_PROJETO, nome)


def _aplicar_icone_janela(janela) -> None:
    """Define o ícone da janela: XBM no Linux, ICO no Windows."""
    try:
        if _eh_windows():
            ico = _caminho_recurso("Icon.ico")
            if os.path.exists(ico):
                janela.wm_iconbitmap(ico)
        else:
            xbm = _caminho_recurso("Icon.xbm")
            if os.path.exists(xbm):
                janela.wm_iconbitmap("@" + xbm)
    except Exception:
        pass


def _obter_dados_usuario() -> str:
    """Diretório persistente do usuário (~/.navepro)."""
    data_dir = os.path.join(os.path.expanduser("~"), ".navepro")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


DATA_USER_DIR: str = _obter_dados_usuario()
CONFIG_FILE: str = os.path.join(DATA_USER_DIR, "config.json")
DB_PATH: str = os.path.join(DATA_USER_DIR, "midia.db")
UPLOAD_FOLDER: str = os.path.join(DATA_USER_DIR, "uploads")
DIR_BASE: str = _caminho_base()
DB_EMBUTIDO: str = _caminho_recurso("midia.db")
UPLOADS_EMBUTIDO: str = _caminho_recurso("uploads")
ANUNCIOS_FILE: str = os.path.join(DATA_USER_DIR, "anuncios.json")
SERVICOS_FILE: str = os.path.join(DATA_USER_DIR, "servicos.json")