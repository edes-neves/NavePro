#!/usr/bin/env python3
"""Contagem regressiva de vídeos por URL na janela da Ordem de Projeção.

O player não consegue medir a duração de uma URL (o ffprobe só lê arquivo
local), então `duracao_total` fica vazio. A contagem deve usar a duração já
capturada/estimada do item. Itens de texto (sem player) continuam sem
contagem regressiva.
"""

import ast
import os
import sys
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from navepro.core.servicos import _formatar_duracao_segundos  # noqa: E402

_MOD = os.path.join(RAIZ, "navepro", "ui", "janela_ordem_servico.py")
_SRC = open(_MOD, encoding="utf-8").read()
_TREE = ast.parse(_SRC)
_JANELA = next(
    no for no in ast.walk(_TREE)
    if isinstance(no, ast.FunctionDef) and no.name == "janela_ordem_servico")
_FUNCS = {
    no.name: no for no in ast.walk(_JANELA)
    if isinstance(no, ast.FunctionDef)
}

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


class _Player:
    def __init__(self, duracao_total=None, decorrido=0.0):
        self.duracao_total = duracao_total
        self.is_playing = True
        self.is_paused = False
        self._decorrido = decorrido

    def obter_tempo_decorrido(self):
        return self._decorrido


def _contagem(player, item, iid, caminho, cache=None):
    """Executa a função aninhada `_atualizar_contagem` com dublês."""
    aplicados = []
    ns = {
        "self": types.SimpleNamespace(player=player),
        "_item_em_reproducao": lambda: (item, iid, caminho),
        "_restaurar_duracao": lambda _iid: None,
        "_card_existe": lambda _iid: True,
        "_definir_duracao_card": lambda i, t: aplicados.append((i, t)),
        "_contagem": {"iid": None},
        "_duracao_cache": dict(cache or {}),
        "_textos_base": {iid: "1:00"} if iid else {},
        "_linhas_path": {iid: caminho} if iid else {},
        "_persistir_duracao": lambda *a: None,
        "_formatar_duracao_segundos": _formatar_duracao_segundos,
    }
    codigo = ast.get_source_segment(_SRC, _FUNCS["_atualizar_contagem"])
    exec(compile(ast.parse(codigo), "<_atualizar_contagem>", "exec"), ns)  # noqa: S102
    ns["_atualizar_contagem"]()
    return ns, aplicados


def _rodar() -> int:
    url = "https://www.youtube.com/watch?v=abc"
    item = {"id": "1", "tipo": "youtube",
            "duracao_estimada_segundos": 60}
    ns, aplicados = _contagem(_Player(None, 10.0), item, "1", url)
    checar("URL usa a duração estimada do item",
           aplicados and aplicados[-1][1] == "⏳ 0:50",
           repr(aplicados[-1][1] if aplicados else None))
    checar("URL vira a duração conhecida do cache",
           ns["_duracao_cache"].get(url) == 60.0,
           repr(ns["_duracao_cache"].get(url)))
    checar("item fica marcado como em contagem",
           ns["_contagem"]["iid"] == "1")

    ns, aplicados = _contagem(_Player(120.0, 20.0), item, "1", url)
    checar("duração do player continua tendo prioridade",
           aplicados and aplicados[-1][1] == "⏳ 1:40",
           repr(aplicados[-1][1] if aplicados else None))

    ns, aplicados = _contagem(_Player(None, 10.0), None, None, None)
    checar("item de texto (sem player) não inicia contagem",
           not aplicados and ns["_contagem"]["iid"] is None)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
