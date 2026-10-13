"""Sorteio Profissional — sistema de sorteio para eventos presenciais.

Código original do projeto ``sorteio-profissional`` (customtkinter),
vendorado neste subpacote e portado para **tkinter puro** (Tk 8.6), de forma
que o NavePro possa embutir a janela do sorteio sem dependências extras.

O ``customtkinter`` é substituído pelo shim local ``navepro.sorteio.ctk``.
A integração com o NavePro fica em ``navepro.sorteio.integracao``.
"""

APP_NAME = "Sorteio Profissional"
APP_VERSION = "1.0.2"
APP_DEVELOPER = "José Edes Neves"
APP_YEAR = "2026"
APP_LICENSE = "GPL"

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "APP_DEVELOPER",
    "APP_YEAR",
    "APP_LICENSE",
]
