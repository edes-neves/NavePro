"""Testes headless do menu de clique direito em campos de texto.

Cobre `_menu_contexto_campo` (clique direito -> copiar/colar) e
`_colar_texto_campo` (colar substituindo a seleção) extraídos de
`NavePro.py` via AST, com fakes de `tk.Menu`, do campo e da área de
transferência.
"""

import ast
import os
import sys
import textwrap
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)

_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_NOS = {
    n.name: n for n in ast.walk(ast.parse(_SRC)) if isinstance(n, ast.FunctionDef)
}


class _FakeMenu:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.comandos = []
        self.popup = None
        self.liberou = False

    def add_command(self, label=None, command=None):
        self.comandos.append((label, command))

    def tk_popup(self, x, y, entry):
        self.popup = (x, y, entry)

    def grab_release(self):
        self.liberou = True


class _FakeTk:
    Menu = _FakeMenu

    class TclError(Exception):
        pass


_ns = {"tk": _FakeTk}
for _nome in ("_menu_contexto_campo", "_colar_texto_campo"):
    _corpo = textwrap.dedent(ast.get_source_segment(_SRC, _NOS[_nome]))
    exec(compile(_corpo, f"<{_nome}>", "exec"), _ns)

_MENU = _ns["_menu_contexto_campo"]
_COLAR = _ns["_colar_texto_campo"]

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


class _FakeCampoMenu:
    def __init__(self):
        self.binds = {}

    def bind(self, sequencia, func, add=None):
        self.binds[sequencia] = func


# ── _menu_contexto_campo ──
campo = _FakeCampoMenu()
acionados = []
menu = _MENU(campo, [("📋 Copiar", lambda: acionados.append("copiar")),
                     ("📋 Colar", lambda: acionados.append("colar"))])

check("menu: bind no <Button-3>", "<Button-3>" in campo.binds,
      str(list(campo.binds)))
check("menu: tearoff desligado", menu.kwargs.get("tearoff") == 0)
check("menu: duas ações registradas", len(menu.comandos) == 2,
      str([rot for rot, _ in menu.comandos]))
check("menu: rótulos preservados",
      [rot for rot, _ in menu.comandos] == ["📋 Copiar", "📋 Colar"])
menu.comandos[0][1]()
check("menu: ação 'Copiar' dispara", acionados == ["copiar"], str(acionados))

campo.binds["<Button-3>"](types.SimpleNamespace(x_root=100, y_root=200))
check("menu: abre no ponteiro", menu.popup == (100, 200, 0), str(menu.popup))
check("menu: libera o grab ao fechar", menu.liberou is True)


# ── _colar_texto_campo ──
class _FakeCampoTexto:
    def __init__(self, selecao=None, clip="https://youtu.be/xyz"):
        self._sel = selecao
        self._clip = clip
        self.deletado = None
        self.inserido = None

    def clipboard_get(self):
        if self._clip is None:
            raise _FakeTk.TclError("área de transferência vazia")
        return self._clip

    def selection_present(self):
        return self._sel is not None

    def delete(self, first, last=None):
        self.deletado = (first, last)

    def insert(self, index, texto):
        self.inserido = (index, texto)


campo_txt = _FakeCampoTexto(selecao=("sel.first", "sel.last"))
_COLAR(campo_txt)
check("colar: insere no cursor", campo_txt.inserido == ("insert", "https://youtu.be/xyz"),
      str(campo_txt.inserido))
check("colar: substitui a seleção", campo_txt.deletado == ("sel.first", "sel.last"),
      str(campo_txt.deletado))

campo_sem_sel = _FakeCampoTexto()
_COLAR(campo_sem_sel)
check("colar: sem seleção não apaga nada", campo_sem_sel.deletado is None)
check("colar: texto entra no cursor mesmo sem seleção",
      campo_sem_sel.inserido == ("insert", "https://youtu.be/xyz"))

campo_vazio = _FakeCampoTexto(clip=None)
_COLAR(campo_vazio)
check("colar: área de transferência vazia não faz nada",
      campo_vazio.inserido is None and campo_vazio.deletado is None)


print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
