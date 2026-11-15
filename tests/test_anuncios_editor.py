#!/usr/bin/env python3
"""Testes headless do editor de anúncios (navepro/ui/janela_anuncios.py).

Cobre os dois recursos novos, extraídos do arquivo via AST:
  * menu de clique direito (colar/copiar/recortar) na caixa de texto;
  * arrastar-e-soltar dos slides na lista (reordenação).
"""

import ast
import os
import sys
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)

_SRC = open(os.path.join(RAIZ, "navepro", "ui", "janela_anuncios.py"),
            encoding="utf-8").read()
_NOS = {n.name: n for n in ast.walk(ast.parse(_SRC))
        if isinstance(n, ast.FunctionDef)}

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


class _TclError(Exception):
    pass


# ── menu de contexto da caixa de texto ──────────────────────────────
class _FakeMenu:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.comandos = []
        self.popup = None
        self.liberou = False

    def add_command(self, label=None, command=None):
        self.comandos.append((label, command))

    def add_separator(self):
        pass

    def tk_popup(self, x, y, entry=None):
        self.popup = (x, y, entry)

    def grab_release(self):
        self.liberou = True


class _FakeWidget:
    def __init__(self, clip="", sel=None):
        self._clip = clip
        self._sel = sel
        self.binds = {}
        self.focado = False
        self.deletado = None
        self.inserido = None
        self.see_usado = False
        self.insert_marcado = None

    def bind(self, sequencia, func):
        self.binds[sequencia] = func

    def focus_set(self):
        self.focado = True

    def index(self, indice):
        return indice

    def mark_set(self, marca, indice):
        if marca == "insert":
            self.insert_marcado = indice

    def clipboard_get(self):
        if self._clip is None:
            raise _TclError("vazia")
        return self._clip

    def tag_ranges(self, tag):
        return self._sel or ()

    def delete(self, first, last=None):
        self.deletado = (first, last)

    def insert(self, index, texto):
        self.inserido = (index, texto)

    def see(self, index):
        self.see_usado = True

    def clipboard_clear(self):
        self._clip = None

    def clipboard_append(self, texto):
        self._clip = texto


_fake_tk = types.SimpleNamespace(Menu=_FakeMenu, TclError=_TclError)
_ns_menu = {"tk": _fake_tk}
exec(compile(ast.get_source_segment(_SRC, _NOS["_adicionar_menu_texto"]),
             "<menu_texto>", "exec"), _ns_menu)
_menu_texto = _ns_menu["_adicionar_menu_texto"]

widget = _FakeWidget(clip="texto copiado")
_menu_texto(widget)
check("menu: liga o clique direito (<Button-3>)", "<Button-3>" in widget.binds)
check("menu: guarda referência viva no widget",
      isinstance(getattr(widget, "_navepro_menu_texto", None), _FakeMenu))
menu = widget._navepro_menu_texto
check("menu: tem a ação Colar", len(menu.comandos) >= 1)
check("menu: primeira ação é Colar", menu.comandos[0][0].endswith("Colar"),
      str(menu.comandos[0][0]))
menu.comandos[0][1]()
check("colar: insere no cursor", widget.inserido == ("insert", "texto copiado"),
      str(widget.inserido))
check("colar: rola até o texto", widget.see_usado is True)

widget_sel = _FakeWidget(clip="novo", sel=("1.0", "1.4"))
_menu_texto(widget_sel)
widget_sel._navepro_menu_texto.comandos[0][1]()
check("colar: substitui a seleção", widget_sel.deletado == ("sel.first", "sel.last"),
      str(widget_sel.deletado))
check("colar: insere depois de apagar a seleção",
      widget_sel.inserido == ("insert", "novo"), str(widget_sel.inserido))

widget_vazio = _FakeWidget(clip=None)
_menu_texto(widget_vazio)
widget_vazio._navepro_menu_texto.comandos[0][1]()
check("colar: área de transferência vazia não altera o texto",
      widget_vazio.inserido is None and widget_vazio.deletado is None)

widget_abrir = _FakeWidget()
_menu_texto(widget_abrir)
menu_abrir = widget_abrir._navepro_menu_texto
_menu_texto(widget_abrir)
check("menu: não é criado duas vezes para o mesmo widget",
      widget_abrir._navepro_menu_texto is menu_abrir)
widget_abrir.binds["<Button-3>"](
    types.SimpleNamespace(x_root=10, y_root=20, x=30, y=40))
check("menu: abre no ponteiro", widget_abrir._navepro_menu_texto.popup ==
      (10, 20, None), str(widget_abrir._navepro_menu_texto.popup))
check("menu: libera o grab", widget_abrir._navepro_menu_texto.liberou is True)
check("menu: dá foco à caixa de texto", widget_abrir.focado is True)
check("menu: coloca o cursor no ponto do clique",
      widget_abrir.insert_marcado == "@30,40", str(widget_abrir.insert_marcado))


# ── arrastar-e-soltar dos slides ────────────────────────────────────
class _FakeListbox:
    def __init__(self, total):
        self.total = total
        self.sel = ()
        self.cursor = None

    def size(self):
        return self.total

    def winfo_height(self):
        return self.total * 20 if self.total else 20

    def yview_scroll(self, passo, unidade):
        self.scroll = (passo, unidade)

    def nearest(self, y):
        return min(self.total - 1, max(0, int(y) // 20))

    def selection_clear(self, first, last):
        self.sel = ()

    def selection_set(self, idx):
        self.sel = (idx,)

    def curselection(self):
        return self.sel

    def activate(self, idx):
        pass

    def configure(self, **kwargs):
        self.cursor = kwargs.get("cursor", self.cursor)

    def see(self, idx):
        pass


def _montar_drag(lista, idx=0, total=None):
    chamadas = []
    estado = {"lista": [{"texto": t} for t in lista], "idx": idx}
    drag = {"ativo": False, "origem": None, "alvo": None}
    box = _FakeListbox(total if total is not None else len(lista))
    ns = {
        "tk": types.SimpleNamespace(END="end", TclError=_TclError),
        "_slides_estado": estado,
        "_drag_slide": drag,
        "lista_box": box,
        "_commit_slide": lambda: chamadas.append("commit"),
        "_carregar_slide": lambda: chamadas.append("carregar"),
        "_atualizar_lista": lambda: chamadas.append(
            ("lista", drag["ativo"])),
    }
    corpo = "\n\n".join(
        ast.get_source_segment(_SRC, _NOS[n])
        for n in ("_drag_inicio", "_drag_mover", "_drag_soltar",
                  "_escolher_slide"))
    exec(compile(corpo, "<drag>", "exec"), ns)
    return ns, estado, drag, box, chamadas


def _ev(y):
    return types.SimpleNamespace(y=y)


ns, estado, drag, box, chamadas = _montar_drag(["A", "B", "C"])
ns["_drag_inicio"](_ev(5))
check("drag: inicia no slide sob o cursor", drag["origem"] == 0 and
      drag["ativo"] is True, str(drag))
check("drag: salva o texto antes de arrastar", "commit" in chamadas)
check("drag: cursor de movimento", box.cursor == "fleur", str(box.cursor))
ns["_escolher_slide"]()
check("drag: seleção automática não recarrega o texto durante o arrasto",
      chamadas.count("carregar") == 0 and chamadas.count("commit") == 1)
ns["_drag_mover"](_ev(45))
check("drag: alvo acompanha o cursor", drag["alvo"] == 2, str(drag))
ns["_drag_mover"](_ev(59))
check("drag: rola a lista perto da borda",
      getattr(box, "scroll", None) == (1, "units"), str(getattr(box, "scroll", None)))
ns["_drag_soltar"](_ev(45))
check("drag: ordem alterada (A vai para o fim)",
      [s["texto"] for s in estado["lista"]] == ["B", "C", "A"],
      str([s["texto"] for s in estado["lista"]]))
check("drag: índice passa a apontar para o slide movido", estado["idx"] == 2,
      str(estado["idx"]))
check("drag: lista é atualizada com a guarda ativa",
      ("lista", True) in chamadas, str(chamadas))
check("drag: recarrega o slide solto depois de atualizar a lista",
      chamadas[-1] == "carregar", str(chamadas[-1]))
check("drag: guarda desligada ao terminar", drag["ativo"] is False)
check("drag: cursor normal restaurado", box.cursor == "hand2")

ns, estado, drag, box, chamadas = _montar_drag(["A", "B", "C"])
ns["_drag_inicio"](_ev(25))
ns["_drag_soltar"](_ev(25))
check("click: sem arrastar não muda a ordem",
      [s["texto"] for s in estado["lista"]] == ["A", "B", "C"])
check("click: seleciona o slide clicado", estado["idx"] == 1,
      str(estado["idx"]))
check("click: recarrega o slide clicado",
      chamadas[-1] == "carregar", str(chamadas[-1]))

ns, estado, drag, box, chamadas = _montar_drag(["A", "B", "C"], idx=0)
ns["_drag_inicio"](_ev(45))
ns["_drag_soltar"](_ev(5))
check("drag: move um slide não selecionado para o topo",
      [s["texto"] for s in estado["lista"]] == ["C", "A", "B"],
      str([s["texto"] for s in estado["lista"]]))
check("drag: índice acompanha o slide movido", estado["idx"] == 0,
      str(estado["idx"]))

ns, estado, drag, box, chamadas = _montar_drag(["A"], idx=0)
ns["_drag_inicio"](_ev(5))
ns["_drag_soltar"](_ev(5))
check("drag: lista de um slide continua estável",
      [s["texto"] for s in estado["lista"]] == ["A"])


print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas
              else f"FALHAS: {len(falhas)}"))
sys.exit(1 if falhas else 0)
