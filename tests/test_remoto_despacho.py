#!/usr/bin/env python3
"""Testes do despacho do controle remoto (navepro/ui/remoto.py).

O `_remoto_despacho` trocou a cadeia if/elif por uma tabela de handlers.
Estes testes travam o comportamento: ação conhecida chama o handler certo,
ação desconhecida devolve o erro padrão e exceção de handler vira JSON de
erro em vez de derrubar o servidor.
"""

import ast
import os
import sys
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
sys.path.insert(0, _AQUI)

from fixture_log import log  # noqa: E402

_SRC = open(os.path.join(RAIZ, "navepro", "ui", "remoto.py"),
            encoding="utf-8").read()
_TREE = ast.parse(_SRC)

falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}")
    if not cond:
        falhas += 1


def _extrair(nome: str):
    for no in _TREE.body:
        if isinstance(no, ast.ClassDef):
            for m in no.body:
                if isinstance(m, ast.FunctionDef) and m.name == nome:
                    return ast.get_source_segment(_SRC, m)
    raise AssertionError(f"{nome} não encontrada em remoto.py")


chamadas = []
self_fake = types.SimpleNamespace(
    LIVROS_BIBLIA=["ARC", "NVI"],
    _remoto_estado=lambda: chamadas.append("estado") or {"ok": True},
    _remoto_slide=lambda acao: chamadas.append(f"slide:{acao}")
    or {"ok": True},
    _remoto_buscar_hino=lambda busca: chamadas.append(f"hino:{busca}")
    or {"ok": True, "hinos": []},
    _remoto_medidor=lambda d: chamadas.append("medidor") or {"ok": True},
)

ns = {"log": log, "Any": __import__("typing").Any,
      "_listar_anuncios_db": lambda: [],
      "_carregar_servicos_json": lambda: {"servicos": []}}
exec(compile(_extrair("_remoto_despacho"), "<_remoto_despacho>", "exec"),
     ns)  # noqa: S102
despacho = ns["_remoto_despacho"].__get__(self_fake)

# ── 1. ação conhecida chama o handler certo ──────────────────────────
r = despacho("estado", {})
checar("estado chama _remoto_estado", r == {"ok": True}
       and chamadas[-1] == "estado")
r = despacho("slide", {"acao": "prox"})
checar("slide repassa a subação", r == {"ok": True}
       and chamadas[-1] == "slide:prox")
r = despacho("buscar_hino", {"busca": "46"})
checar("buscar_hino repassa o termo", chamadas[-1] == "hino:46")
r = despacho("livros_biblia", {})
checar("livros_biblia devolve os livros", r == {"ok": True,
                                                "livros": ["ARC", "NVI"]})
r = despacho("medidor", {"acao": "iniciar"})
checar("medidor chama o handler", chamadas[-1] == "medidor")

# ── 2. dados não-dict viram {} ───────────────────────────────────────
chamadas.clear()
despacho("estado", None)
checar("dados None não quebra o despacho", chamadas == ["estado"])

# ── 3. ação desconhecida ─────────────────────────────────────────────
r = despacho("nao_existe", {})
checar("ação desconhecida devolve erro padrão",
       r == {"ok": False, "erro": "Ação desconhecida: nao_existe"})

# ── 4. exceção no handler vira JSON de erro ──────────────────────────
self_err = types.SimpleNamespace(
    LIVROS_BIBLIA=[],
    _remoto_estado=lambda: (_ for _ in ()).throw(
        RuntimeError("boom interno")),
)
despacho_err = ns["_remoto_despacho"].__get__(self_err)
r = despacho_err("estado", {})
checar("exceção do handler vira {'ok': False, 'erro': ...}",
       r == {"ok": False, "erro": "boom interno"})

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes do despacho remoto passaram.")
