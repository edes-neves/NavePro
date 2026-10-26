#!/usr/bin/env python3
"""Testes do Gerenciador de Banco de Mídia (NavePro.py).

A janela consultava a API HTTP local na thread do Tk. Na primeira abertura o
servidor ainda estava subindo (e o contexto SSL era inicializado), então a
interface congelava e a lista só aparecia na segunda tentativa. Agora a
consulta vai direto ao SQLite, em background, e a árvore é atualizada pela
thread do Tk via `after`.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_TREE = ast.parse(_SRC)

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


def _fonte(nome: str):
    for no in ast.walk(_TREE):
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            return no, ast.get_source_segment(_SRC, no)
    raise AssertionError(f"função {nome} não encontrada em NavePro.py")


# ── 1) A janela não pode voltar a depender do servidor HTTP ──
_no_janela, _src_janela = _fonte("_janela_gerenciar_midias")
check(
    "gerenciador não usa a API HTTP local",
    "_baixar" not in _src_janela
    and "urllib" not in _src_janela
    and "api/midia" not in _src_janela,
)
check(
    "gerenciador consulta o SQLite diretamente",
    "_listar_midias_ativas" in _src_janela,
)
check(
    "consulta roda fora da thread do Tk",
    "threading.Thread" in _src_janela and "daemon=True" in _src_janela,
)
check(
    "árvore é atualizada de volta na thread do Tk",
    "self.root.after(0" in _src_janela and "_preencher_lista" in _src_janela,
)


# ── 2) A consulta mantém filtro e ordenação da API ──
_no_lista, _ = _fonte("_listar_midias_ativas")
_mod = ast.Module(body=[_no_lista], type_ignores=[])
ast.fix_missing_locations(_mod)

chamadas = []


def _db_fake(query, params=()):
    chamadas.append((query, params))
    return [{"id": 1, "nome_exibicao": "1 - Teste", "tipo": "video"}]


_ns = {"db_query": _db_fake}
exec(compile(_mod, "<_listar_midias_ativas>", "exec"), _ns)  # noqa: S102
_listar = _ns["_listar_midias_ativas"]

resultado = _listar()
query, params = chamadas[-1]
check("consulta sem filtro não adiciona cláusula de tipo",
      "tipo = ?" not in query and params == ())
check("consulta filtra apenas mídias ativas",
      "FROM midia WHERE ativo = 1" in query)
check("consulta usa a ordenação natural da API",
      "ORDER BY" in query and "GLOB '[0-9]*'" in query)
check("resultado do banco é devolvido", resultado == [{"id": 1,
      "nome_exibicao": "1 - Teste", "tipo": "video"}])

_listar("audio")
query, params = chamadas[-1]
check("filtro por tipo é parametrizado",
      "tipo = ?" in query and params == ("audio",))

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
