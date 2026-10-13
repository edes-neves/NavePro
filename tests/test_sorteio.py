"""Testes headless da integração do Sorteio Profissional com o NavePro.

Não abre janelas: valida o shim ``customtkinter``→``tkinter``, a
vendorização (sem resquícios de ``customtkinter``/``from src``), os caminhos
de dados e a lógica pura do sorteio.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

_DIR_SORTEIO = os.path.join(RAIZ, "navepro", "sorteio")

# --- O shim deve expor toda a API usada pelos módulos do sorteio ---
from navepro.sorteio import ctk  # noqa: E402

_API_ESPERADA = [
    "CTk", "CTkToplevel", "CTkFrame", "CTkLabel", "CTkButton", "CTkEntry",
    "CTkTextbox", "CTkScrollableFrame", "CTkCheckBox", "CTkSegmentedButton",
    "CTkProgressBar", "CTkBaseClass", "ThemeManager",
    "set_appearance_mode", "set_default_color_theme",
    "set_widget_scaling", "set_window_scaling",
]
for _nome in _API_ESPERADA:
    assert hasattr(ctk, _nome), f"shim ctk sem {_nome}"


# --- Vendorização: nenhum módulo pode importar customtkinter/from src ---
def _modulos_importados(caminho):
    with open(caminho, encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    modulos = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos.extend(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom):
            modulos.append(no.module or "")
    return modulos


for _arq in sorted(os.listdir(_DIR_SORTEIO)):
    if not _arq.endswith(".py"):
        continue
    for _mod in _modulos_importados(os.path.join(_DIR_SORTEIO, _arq)):
        assert _mod.split(".")[0] != "customtkinter", f"{_arq} importa customtkinter"
        assert _mod != "src" and not _mod.startswith("src."), (
            f"{_arq} importa de src ({_mod})"
        )


# --- Todos os módulos importam sem display ---
import navepro.sorteio.app  # noqa: E402,F401
import navepro.sorteio.integracao  # noqa: E402,F401
import navepro.sorteio.main_window  # noqa: E402,F401
import navepro.sorteio.public_window  # noqa: E402,F401

# --- Caminhos de dados sob ~/.navepro/sorteio ---
from navepro.sorteio import history_manager, settings_manager  # noqa: E402

assert settings_manager.CONFIG_FILE.endswith(
    os.path.join("sorteio", "config", "settings.json")
), settings_manager.CONFIG_FILE
assert os.sep + ".navepro" in settings_manager.CONFIG_FILE
assert history_manager.BASE_DIR.endswith(os.path.join(".navepro", "sorteio")), (
    history_manager.BASE_DIR
)
assert history_manager.BASE_DIR == settings_manager.DATA_DIR

# --- Assets de som dentro do pacote ---
from navepro.sorteio import sound_manager  # noqa: E402

assert sound_manager.SOUNDS_DIR.endswith(
    os.path.join("sorteio", "assets", "sounds")
), sound_manager.SOUNDS_DIR

# --- Lógica pura do motor de sorteio ---
from navepro.sorteio.lottery_engine import LotteryEngine  # noqa: E402

_engine = LotteryEngine()
_engine.configure(1, 3)
assert _engine.total_numbers == 3
assert _engine.is_ready()
_sorteados = _engine.draw_many(3)
assert sorted(_sorteados) == [1, 2, 3]
assert _engine.drawn_count == 3
assert _engine.is_completed()
assert _engine.draw_many(1) == []

_engine.configure_names(["ana", "josé"])
assert _engine.mode == "names"
assert sorted(_engine.all_items) == ["ANA", "JOSÉ"]

# --- Validator: faixa válida e inválida ---
from navepro.sorteio.validator import Validator  # noqa: E402

_inicio, _fim = Validator.validate_range("2", "10")
assert (_inicio, _fim) == (2, 10)

# --- CTkEntry com cantos arredondados (Frame + Canvas, não tk.Entry) ---
import tkinter as tk  # noqa: E402

assert issubclass(ctk.CTkEntry, tk.Frame), "CTkEntry deve ser um Frame"
assert not issubclass(ctk.CTkEntry, tk.Entry), "CTkEntry não deve ser tk.Entry"
assert hasattr(ctk.CTkEntry, "_redraw"), "CTkEntry sem desenho arredondado"
assert hasattr(ctk, "_round_rect"), "shim sem helper de canto arredondado"

# --- Largura da janela do operador (1200px) ---
from navepro.sorteio import integracao  # noqa: E402

assert integracao._TAMANHO_JANELA == (1200, 880), integracao._TAMANHO_JANELA

# --- Atalho de aparência do telão no painel do operador ---
import inspect  # noqa: E402

from navepro.sorteio.app import App  # noqa: E402
from navepro.sorteio.main_window import MainWindow  # noqa: E402

assert hasattr(App, "_show_telao_dialog"), "App sem diálogo do telão"
assert hasattr(App, "_telao_aplicar"), "App sem aplicação da aparência do telão"
assert len(App._TELAO_CORES_FUNDO) >= 1, "sem opções de cor de fundo"
_assinatura = inspect.signature(MainWindow.__init__).parameters
assert "on_telao" in _assinatura, "MainWindow sem callback on_telao"
assert hasattr(MainWindow, "_on_telao_click"), "MainWindow sem handler do telão"

print("OK test_sorteio")
