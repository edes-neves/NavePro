#!/usr/bin/env python3
"""Testes do esquema e das migrações do banco (navepro/core/inicializacao.py).

O `init_db` é o único lugar que mexe na estrutura do SQLite do usuário.
Uma migração errada aqui = perda de dados, por isso cada caminho é coberto:
criação do esquema, idempotência e as duas migrações de `anuncios`
(remoção do AUTOINCREMENT e inclusão da coluna `config_midia`).
"""

import ast
import mimetypes
import os
import sqlite3
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

from fixture_log import log  # noqa: E402

from navepro.core.textos import detectar_tipo_arquivo  # noqa: E402

_MOD = os.path.join(RAIZ, "navepro", "core", "inicializacao.py")
_SRC = open(_MOD, encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _extrair(nome: str):
    for no in ast.walk(_TREE):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and no.name == nome:
            return ast.get_source_segment(_SRC, no)
    raise AssertionError(f"função {nome} não encontrada em inicializacao.py")


def _ns(db: str, uploads: str) -> dict:
    return {
        "os": os,
        "sqlite3": sqlite3,
        "mimetypes": mimetypes,
        "log": log,
        "DB_PATH": db,
        "UPLOAD_FOLDER": uploads,
        "detectar_tipo_arquivo": detectar_tipo_arquivo,
    }


def _init_db(db: str, uploads: str) -> None:
    ns = _ns(db, uploads)
    exec(compile(_extrair("init_db"), "<init_db>", "exec"), ns)  # noqa: S102
    ns["init_db"]()


def _tabelas(db: str) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _sql_da_tabela(db: str, tabela: str) -> str:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (tabela,)).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def _colunas(db: str, tabela: str) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
    finally:
        conn.close()


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    def novo_db():
        raiz = tempfile.mkdtemp(prefix="navepro-init-")
        return raiz, os.path.join(raiz, "midia.db"), os.path.join(raiz, "uploads")

    # ── 1. Criação do esquema em banco novo ─────────────────────────
    raiz, db, uploads = novo_db()
    _init_db(db, uploads)
    esperadas = {"midia", "letras", "versiculos", "servicos",
                 "itens_servico", "anuncios"}
    checar("cria todas as tabelas do app", esperadas <= _tabelas(db))
    checar("cria a pasta de uploads", os.path.isdir(uploads))
    checar("anuncios sem AUTOINCREMENT (IDs reaproveitáveis)",
           "AUTOINCREMENT" not in _sql_da_tabela(db, "anuncios"))
    checar("anuncios tem a coluna config_midia",
           "config_midia" in _colunas(db, "anuncios"))

    # índices essenciais
    conn = sqlite3.connect(db)
    indices = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    checar("cria os índices de midia e anuncios",
           {"idx_midia_tipo", "idx_midia_ativo", "idx_anuncios_ativo"}
           <= indices)

    # ── 2. Idempotência: rodar de novo não quebra nem perde dados ───
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO anuncios (id, titulo) VALUES (1, 'Aviso')")
    conn.commit()
    conn.close()
    _init_db(db, uploads)
    conn = sqlite3.connect(db)
    linha = conn.execute("SELECT titulo FROM anuncios WHERE id = 1").fetchone()
    conn.close()
    checar("init_db repetido preserva os dados", linha == ("Aviso",))

    # ── 3. Migração: remove AUTOINCREMENT de banco antigo ───────────
    raiz, db, uploads = novo_db()
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE anuncios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            categoria TEXT DEFAULT '',
            texto TEXT DEFAULT '',
            tipo_midia TEXT NOT NULL DEFAULT 'slide',
            arquivo_midia TEXT DEFAULT '',
            nome_arquivo_midia TEXT DEFAULT '',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ativo INTEGER DEFAULT 1
        )
    """)
    conn.execute(
        "INSERT INTO anuncios (id, titulo, categoria, texto) "
        "VALUES (5, 'Antigo', 'Cat', 'texto')")
    conn.commit()
    conn.close()
    old_sql = _sql_da_tabela(db, "anuncios")
    checar("pré-condição: banco antigo tinha AUTOINCREMENT",
           "AUTOINCREMENT" in old_sql)

    _init_db(db, uploads)
    checar("migração remove AUTOINCREMENT",
           "AUTOINCREMENT" not in _sql_da_tabela(db, "anuncios"))
    conn = sqlite3.connect(db)
    linha = conn.execute(
        "SELECT id, titulo, categoria, texto FROM anuncios").fetchone()
    conn.close()
    checar("migração do AUTOINCREMENT preserva id e conteúdo",
           linha == (5, "Antigo", "Cat", "texto"))
    checar("migração adiciona config_midia junto",
           "config_midia" in _colunas(db, "anuncios"))

    # ── 4. Migração: adiciona config_midia a banco sem a coluna ─────
    raiz, db, uploads = novo_db()
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE anuncios (
            id INTEGER PRIMARY KEY,
            titulo TEXT NOT NULL,
            categoria TEXT DEFAULT '',
            texto TEXT DEFAULT '',
            tipo_midia TEXT NOT NULL DEFAULT 'slide',
            arquivo_midia TEXT DEFAULT '',
            nome_arquivo_midia TEXT DEFAULT '',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ativo INTEGER DEFAULT 1
        )
    """)
    conn.execute("INSERT INTO anuncios (id, titulo) VALUES (7, 'Sem coluna')")
    conn.commit()
    conn.close()
    checar("pré-condição: banco sem config_midia",
           "config_midia" not in _colunas(db, "anuncios"))
    _init_db(db, uploads)
    checar("migração adiciona config_midia", "config_midia" in _colunas(db, "anuncios"))
    conn = sqlite3.connect(db)
    linha = conn.execute(
        "SELECT titulo, config_midia FROM anuncios WHERE id = 7").fetchone()
    conn.close()
    checar("coluna nova entra com default '' e dado antigo intacto",
           linha == ("Sem coluna", ""))

    # ── 5. `_sincronizar_uploads_midia` ─────────────────────────────
    raiz, db, uploads = novo_db()
    _init_db(db, uploads)
    # schema real já criado; grava arquivos de tipos variados
    for nome in ("hino.mp3", "clipe.mp4", "notas.txt", "ignorado.xyz"):
        open(os.path.join(uploads, nome), "w").close()
    os.makedirs(os.path.join(uploads, "subpasta"), exist_ok=True)

    ns = _ns(db, uploads)

    def db_query(q, p=()):
        c = sqlite3.connect(db)
        try:
            return [dict(r) for r in c.execute(q, p).fetchall()]
        finally:
            c.close()

    ns["db_query"] = db_query
    ns["DatabaseManager"] = lambda: type(
        "DM", (), {"reload_cache": staticmethod(lambda: None)})()

    def db_execute(q, p=()):
        c = sqlite3.connect(db)
        try:
            cur = c.execute(q, p)
            c.commit()
            return cur.lastrowid
        finally:
            c.close()
    ns["db_execute"] = db_execute
    for nome in ("_sincronizar_uploads_midia",):
        exec(compile(_extrair(nome), f"<{nome}>", "exec"), ns)

    novos = ns["_sincronizar_uploads_midia"]()
    checar("sincroniza 3 mídias (mp3+mp4+txt) e ignora .xyz/pasta",
           novos == 3)
    conn = sqlite3.connect(db)
    nomes = {r[0] for r in conn.execute(
        "SELECT nome_original FROM midia")}
    conn.close()
    checar("só os arquivos suportados entram em midia",
           nomes == {"hino.mp3", "clipe.mp4", "notas.txt"})
    checar("2ª sincronização não duplica (nada novo)",
           ns["_sincronizar_uploads_midia"]() == 0)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
