"""Testes headless de ``_aplicar_tema_widget`` (NavePro.py).

Cobre o bug de tema claro: alguns widgets (``tk.Menu``) devolvem ``Tcl_Obj``
no ``cget`` e quebravam ``_cor_clara`` (``AttributeError: no attribute
'upper'``). Também garante que menus (tratados em ``_aplicar_tema_menu``) são
ignorados na recolorização genérica, para não brigar com ela.
"""

import ast
import os
import sys
import textwrap
import tkinter as tk
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.core.tema import _OPCOES_COR_TK, _OPCOES_TEXTO, _cor_clara  # noqa: E402

_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_NOS = {
    n.name: n for n in ast.walk(ast.parse(_SRC)) if isinstance(n, ast.FunctionDef)
}
_CORPO = textwrap.dedent(ast.get_source_segment(_SRC, _NOS["_aplicar_tema_widget"]))


class _Ttk:
    class Widget:  # nenhum fake abaixo é instância disto
        pass


_ns = {
    "tk": tk,
    "ttk": _Ttk,
    "_OPCOES_COR_TK": _OPCOES_COR_TK,
    "_OPCOES_TEXTO": _OPCOES_TEXTO,
    "_cor_clara": _cor_clara,
}
exec(compile(_CORPO, "<aplicar_tema_widget>", "exec"), _ns)
_APLICAR = _ns["_aplicar_tema_widget"]

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


class _TclObj:
    """Imita ``_tkinter.Tcl_Obj``: tem ``.string`` mas não ``.upper``."""

    def __init__(self, valor):
        self.string = valor

    def __str__(self):
        return self.string


class _FakeMenu:
    def __init__(self):
        self.configure_chamado = False

    def winfo_exists(self):
        return 1

    def winfo_class(self):
        return "Menu"

    def keys(self):
        return ["background", "foreground", "activebackground"]

    def cget(self, _op):
        return _TclObj("#161b22")

    def configure(self, **_kw):  # pragma: no cover - não deve ser chamado
        self.configure_chamado = True


class _FakeWidget:
    def __init__(self, obj=False):
        self.cfg = {}
        self._obj = obj

    def winfo_exists(self):
        return 1

    def winfo_class(self):
        return "Button"

    def keys(self):
        return ["background", "foreground"]

    def cget(self, op):
        valor = "#161b22" if op == "background" else "#f0c040"
        return _TclObj(valor) if self._obj else valor

    def configure(self, **kw):
        self.cfg.update(kw)


_host = types.SimpleNamespace(tema="claro")

# --- Menu não é recolorido aqui (tem tratamento próprio) ---
_menu = _FakeMenu()
_APLICAR(_host, _menu)
check("menu ignorado na recolorização genérica", not _menu.configure_chamado)

# --- Tcl_Obj não derruba _cor_clara (tema claro) ---
_w = _FakeWidget(obj=True)
try:
    _APLICAR(_host, _w)
    erro = ""
except Exception as exc:  # pragma: no cover
    erro = f"{type(exc).__name__}: {exc}"
check("cget Tcl_Obj convertido (sem AttributeError)", not erro, erro)
check(
    "tema claro aplicou cores de fundo/texto",
    _w.cfg.get("background") == _cor_clara("#161b22")
    and _w.cfg.get("foreground") == _cor_clara("#f0c040", "#ffffff"),
    str(_w.cfg),
)

# --- Volta ao escuro restaura a origem gravada ---
_host.tema = "escuro"
_APLICAR(_host, _w)
check(
    "tema escuro restaura as cores originais",
    _w.cfg.get("background") == "#161b22" and _w.cfg.get("foreground") == "#f0c040",
    str(_w.cfg),
)

# --- Faixas de seção: carvão no claro, cor do cartão no escuro ---
class _FakeFaixa:
    _navepro_faixa_secao = True

    def __init__(self):
        self.cfg = {}

    def winfo_exists(self):
        return 1

    def configure(self, **kw):
        self.cfg.update(kw)


_faixa = _FakeFaixa()
_host.tema = "claro"
_APLICAR(_host, _faixa)
check("faixa de seção fica carvão no tema claro", _faixa.cfg.get("bg") == "#30363d", str(_faixa.cfg))

_faixa2 = _FakeFaixa()
_host.tema = "escuro"
_APLICAR(_host, _faixa2)
check(
    "faixa de seção fica invisível (cor do cartão) no tema escuro",
    _faixa2.cfg.get("bg") == "#161b22",
    str(_faixa2.cfg),
)

# --- Área de controles: cinza no claro, cor original no escuro ---
class _FakeArea:
    _navepro_area_cinza_clara = True
    _navepro_area_cinza_escuro = "#21262d"

    def __init__(self):
        self.cfg = {}

    def winfo_exists(self):
        return 1

    def configure(self, **kw):
        self.cfg.update(kw)


_area = _FakeArea()
_host.tema = "claro"
_APLICAR(_host, _area)
check("área de controles fica cinza no tema claro", _area.cfg.get("bg") == "#8b949e", str(_area.cfg))

_area2 = _FakeArea()
_host.tema = "escuro"
_APLICAR(_host, _area2)
check(
    "área de controles volta à cor original no tema escuro",
    _area2.cfg.get("bg") == "#21262d",
    str(_area2.cfg),
)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
