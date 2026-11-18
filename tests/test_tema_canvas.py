#!/usr/bin/env python3
"""Tema CLARO: itens de Canvas e janelas aninhadas.

Cobre os dois pontos que deixavam conteúdo escuro no tema claro:

- as cores desenhadas em ``Canvas`` (Bíblia em grade, prévia de anúncio) não
  são opções de widget e passavam ilesas pela recoloração;
- janelas abertas a partir de outra janela (editor, prévia) não são filhas
  diretas do root e não eram encontradas pela varredura de Toplevels.

O teste é headless: usa objetos falsos no lugar de widgets Tk.
"""

import os
import sys
import tkinter as tk
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.core.tema import (  # noqa: E402
    _cor_item_canvas,
    aplicar_tema_janela,
    definir_aplicador_janela,
    definir_tema_ativo,
    tema_ativo,
)
from navepro.core.widgets_arredondados import (  # noqa: E402
    CanvasTematico,
    TkArredondado,
    ToplevelTematico,
)
from navepro.ui.tema_painel import _toplevels_do_tema  # noqa: E402

falhas = []


def checar(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── 1. Fachada troca o Canvas pelo ciente do tema ───────────────────
checar("fachada tk expõe CanvasTematico",
       TkArredondado(tk).Canvas is CanvasTematico)
checar("fachada tk expõe ToplevelTematico",
       TkArredondado(tk).Toplevel is ToplevelTematico)

# ── 1b. Janela nova avisa a interface antes de ser pintada ──────────
_aplicadas = []
definir_aplicador_janela(_aplicadas.append)
checar("aplicador de janela recebe a janela nova",
       aplicar_tema_janela("janela") and _aplicadas == ["janela"],
       str(_aplicadas))


def _aplicador_com_erro(_janela):
    raise RuntimeError("falha simulada")


definir_aplicador_janela(_aplicador_com_erro)
checar("erro no aplicador não propaga para o Toplevel",
       aplicar_tema_janela("janela") is False)
definir_aplicador_janela(None)

# ── 2. Cores escuras usadas no app têm equivalente claro ────────────
for escura, clara in (
    ("#2d1114", "#ffebe9"),
    ("#5c4304", "#f6e3a1"),
    ("#9e6a03", "#9a6700"),
    ("#c77b04", "#bf8700"),
    ("#2f6f47", "#1a7f37"),
    ("#3f8f57", "#2ea043"),
    ("#484f58", "#7d8a96"),
    ("#f0f6fc", "#1f2328"),
):
    checar(f"{escura} vira {clara} no tema claro",
           _cor_item_canvas(escura, "claro") == clara)
    checar(f"{escura} permanece igual no tema escuro",
           _cor_item_canvas(escura, "escuro") == escura)

checar("cor fora do mapa não é alterada",
       _cor_item_canvas("#123456", "claro") == "#123456")
checar("cor vazia continua vazia",
       _cor_item_canvas("", "claro") == ""
       and _cor_item_canvas(None, "claro") is None)

# ── 3. Mapeamento dos itens (sem criar Canvas real) ─────────────────
_canvas_falso = types.SimpleNamespace(
    _navepro_cores_origem={},
    _navepro_tema_canvas_ignorar=False,
)


definir_tema_ativo("claro")
checar("tema ativo é registrado", tema_ativo() == "claro")

_opcoes = {"fill": "#21262d", "outline": "", "width": 2}
CanvasTematico._navepro_mapear(_canvas_falso, _opcoes)
checar("fill do item é convertido no claro",
       _opcoes["fill"] == "#bcc6d0", str(_opcoes))
checar("outline vazio continua vazio", _opcoes["outline"] == "")
checar("opções que não são cor são preservadas", _opcoes["width"] == 2)

CanvasTematico._navepro_guardar(
    _canvas_falso, "1", {"fill": "#21262d", "outline": ""})
checar("cor escura original do item fica guardada",
       _canvas_falso._navepro_cores_origem["1"] == {"fill": "#21262d"},
       str(_canvas_falso._navepro_cores_origem))

_canvas_ignorado = types.SimpleNamespace(
    _navepro_cores_origem={}, _navepro_tema_canvas_ignorar=True)
_opcoes_ignoradas = {"fill": "#21262d"}
CanvasTematico._navepro_mapear(_canvas_ignorado, _opcoes_ignoradas)
checar("Canvas marcado para ignorar o tema não é alterado",
       _opcoes_ignoradas["fill"] == "#21262d")

definir_tema_ativo("escuro")
checar("tema volta ao escuro", tema_ativo() == "escuro")

# ── 4. Toplevels aninhados são encontrados ──────────────────────────
class _No:
    def __init__(self, classe="Frame", filhos=None, tema_proprio=False):
        self._classe = classe
        self._filhos = filhos or []
        self._navepro_tema_proprio = tema_proprio

    def winfo_children(self):
        return self._filhos

    def winfo_class(self):
        return self._classe


_aninhado = _No("Toplevel")
_janela = _No("Toplevel", [_No("Frame", [_aninhado])])
_direto = _No("Toplevel")
_propria = _No("Toplevel", tema_proprio=True)
_filho_proprio = _No("Toplevel")
_propria._filhos = [_filho_proprio]
_raiz = _No("Tk", [_janela, _direto, _No("Frame"), _propria])

_encontrados = _toplevels_do_tema(_raiz)
checar("Toplevel direto é encontrado", _direto in _encontrados)
checar("Toplevel aninhado é encontrado", _aninhado in _encontrados)
checar("frame comum não entra na lista",
       all(n.winfo_class() == "Toplevel" for n in _encontrados))
checar("janela com tema próprio fica de fora", _propria not in _encontrados)
checar("subárvore da janela com tema próprio fica de fora",
       _filho_proprio not in _encontrados)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
