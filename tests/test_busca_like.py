#!/usr/bin/env python3
"""Testes da busca por termo: curingas de LIKE não podem vir do usuário.

Antes, buscar "100%" ou "a_b" usava os curingas do SQLite e encontrava
qualquer coisa. Agora `_termo_like` escapa %/_/\\ e as consultas usam
`ESCAPE '\\'`. Também cobre os helpers de fallback para id (`_ou_id`) e a
busca de versículos compartilhada entre a janela Bíblia e o controle remoto.
"""

import ast
import os
import sqlite3
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
sys.path.insert(0, _AQUI)

from navepro.core.textos import _termo_like  # noqa: E402

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


# ── 1. _termo_like ───────────────────────────────────────────────────
checar("escapa % do termo", _termo_like("100%") == "100\\%")
checar("escapa _ do termo", _termo_like("a_b") == "a\\_b")
checar("escapa \\ do termo", _termo_like("a\\b") == "a\\\\b")
checar("termo comum fica igual", _termo_like("aleluia") == "aleluia")
checar("termo vazio fica vazio", _termo_like("") == "")

# ── 2. Extração das buscas do slides.py com SQLite real temporário ──
_SRC = open(os.path.join(RAIZ, "navepro", "core", "slides.py"),
            encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _extrair(nome: str):
    for no in ast.walk(_TREE):
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            return ast.get_source_segment(_SRC, no)
    raise AssertionError(f"{nome} não encontrada em slides.py")


conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.execute("""
    CREATE TABLE letras (id INTEGER PRIMARY KEY, titulo TEXT, artista TEXT,
                         letra_completa TEXT, ativo INTEGER DEFAULT 1)
""")
conn.execute("""
    CREATE TABLE midia (id INTEGER PRIMARY KEY, nome_exibicao TEXT,
                        nome_original TEXT, tipo TEXT, ativo INTEGER DEFAULT 1)
""")
conn.execute("""
    CREATE TABLE versiculos (id INTEGER PRIMARY KEY, versao TEXT, livro TEXT,
                             capitulo INTEGER, versiculo INTEGER, texto TEXT)
""")
conn.execute(
    "INSERT INTO letras (id, titulo, artista, letra_completa) VALUES "
    "(1, '100% Amor', '', 'x'), (2, '100 por cento', '', 'y'), "
    "(3, 'a_b nome', '', 'z'), (4, 'ab nome', '', 'w'), "
    "(5, 'Amor 100%', '', 'q5'), (6, 'Amor 100 por cento', '', 'q6')")
conn.execute(
    "INSERT INTO midia (id, nome_exibicao, nome_original, tipo) VALUES "
    "(1, '50% graça', '50% graça.mp4', 'video'), "
    "(2, '50 por cento', '50.mp4', 'video'), "
    "(3, '50 - Louvor', '50-louvor.mp4', 'video'), "
    "(42, 'Completamente outro', 'outro.mp4', 'video')")
conn.execute(
    "INSERT INTO versiculos (versao, livro, capitulo, versiculo, texto) VALUES "
    "('ARC', 'João', 3, 16, 'Deus amou o mundo'), "
    "('ARC', 'João', 3, 17, 'com 100% do amor'), "
    "('ARC', 'João', 3, 18, 'com todo o amor')")
conn.commit()


def db_query(query, params=()):
    return [dict(r) for r in conn.execute(query, params).fetchall()]


ns = {"db_query": db_query, "_termo_like": _termo_like, "re": __import__("re"),
      "unicodedata": __import__("unicodedata")}
from navepro.core.textos import _numero_do_titulo  # noqa: E402

ns["_numero_do_titulo"] = _numero_do_titulo
for nome in ("_buscar_hino_por_termo", "_buscar_hino_por_termo_ou_id",
             "_buscar_midia_por_termo", "_buscar_midia_por_termo_ou_id",
             "_buscar_versiculos_por_texto"):
    exec(compile(_extrair(nome), f"<{nome}>", "exec"), ns)  # noqa: S102

# ── 3. hino: % e _ viram texto literal ───────────────────────────────
rows = ns["_buscar_hino_por_termo"]("amor 100%")
checar("busca 'amor 100%' acha só o texto literal (não '100 por cento')",
       [r["id"] for r in rows] == [5], str([r["id"] for r in rows]))
rows = ns["_buscar_hino_por_termo"]("a_b")
checar("busca 'a_b' acha só o nome literal (não 'ab nome')",
       [r["id"] for r in rows] == [3], str([r["id"] for r in rows]))
rows = ns["_buscar_hino_por_termo"]("100")
checar("busca '100' continua achando por número no título",
       [r["id"] for r in rows] == [2, 1], str([r["id"] for r in rows]))

# ── 4. mídia: curingas viram texto literal ───────────────────────────
rows = ns["_buscar_midia_por_termo"]("50%", tipo="video")
checar("mídia '50%' acha só o nome literal",
       [r["id"] for r in rows] == [1], str([r["id"] for r in rows]))

# ── 5. fallback para id ─────────────────────────────────────────────
conn.execute("INSERT INTO letras (id, titulo, artista, letra_completa) "
             "VALUES (9, 'Outro nome', '', 'q')")
conn.commit()
rows = ns["_buscar_hino_por_termo_ou_id"]("9")
checar("_ou_id: número sem título correspondente cai no id",
       [r["id"] for r in rows] == [9], str([r["id"] for r in rows]))
rows = ns["_buscar_midia_por_termo_ou_id"]("50", tipo="video")
checar("mídia _ou_id: termo numérico acha pelo prefixo do nome",
       [r["id"] for r in rows] == [3], str([r["id"] for r in rows]))
rows = ns["_buscar_midia_por_termo_ou_id"]("42", tipo="video")
checar("mídia _ou_id: número sem nome correspondente cai no id",
       [r["id"] for r in rows] == [42], str([r["id"] for r in rows]))

# ── 6. versículos: escape + limite 50 ────────────────────────────────
rows = ns["_buscar_versiculos_por_texto"]("ARC", "100%")
checar("versículos '100%' acha só o texto literal",
       [r["versiculo"] for r in rows] == [17],
       str([r["versiculo"] for r in rows]))
rows = ns["_buscar_versiculos_por_texto"]("ARC", "")
checar("termo vazio não busca versículos", rows == [])

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes de busca passaram.")
