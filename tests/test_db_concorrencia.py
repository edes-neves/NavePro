#!/usr/bin/env python3
"""Concorrência do DatabaseManager (NavePro.py).

A MESMA conexão SQLite atende três threads ao mesmo tempo: a do Tk (interface e
ações do controle remoto), a do servidor HTTP (upload/download/mídia) e a do
worker de busca. Estes testes travam a serialização dessa conexão (RLock) e a
troca atômica do cache em memória.

Regressões cobertas:

1. `query`/`execute`/`search` concorrentes não estouram nem perdem escritas.
2. `reload_cache` invalida o LRU de `search` — um upload/remoção de mídia não
   pode continuar devolvendo resultados velhos.
3. `DatabaseManager()` sob corrida continua sendo um singleton e a conexão
   preguiçosa é criada uma única vez.
"""

import ast
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
from collections import OrderedDict
from typing import Any

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from fixture_log import log  # noqa: E402

_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _fonte_classe(nome: str) -> str:
    """Pega a classe do NavePro.py via AST, sem importar o app inteiro."""
    for no in _TREE.body:
        if isinstance(no, ast.ClassDef) and no.name == nome:
            return ast.get_source_segment(_SRC, no)
    raise AssertionError(f"classe {nome} não encontrada em NavePro.py")


def _carregar_classe(db_path: str):
    """Executa a classe extraída num namespace mínimo (sem Tk)."""
    ns: dict = {
        "sqlite3": sqlite3,
        "threading": threading,
        "OrderedDict": OrderedDict,
        "Any": Any,
        "re": __import__("re"),
        "os": os,
        "DB_PATH": db_path,
        "SQLITE_TIMEOUT": 10,
        "CACHE_LRU_MAXSIZE": 64,
        # Normalização simplificada: estes testes não dependem de acento.
        "normalizar_texto": lambda s: (s or "").casefold(),
        "log": log,
    }
    exec(compile(_fonte_classe("DatabaseManager"), "<DatabaseManager>", "exec"), ns)
    return ns["DatabaseManager"]


def _novo_manager(DatabaseManager):
    """Recria o singleton para reler o banco de teste."""
    DatabaseManager._instance = None
    return DatabaseManager()


def _criar_banco(pasta: str) -> tuple[str, list[str]]:
    """Banco `midia.db` temporário com o schema mínimo usado pelo cache."""
    db = os.path.join(pasta, "midia.db")
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE midia (
            id INTEGER PRIMARY KEY,
            nome_exibicao TEXT,
            nome_original TEXT,
            caminho_arquivo TEXT,
            tipo TEXT,
            ativo INTEGER DEFAULT 1
        )
    """)
    # _load_cache só inclui caminhos que existem no disco.
    caminhos = []
    for i in range(5):
        p = os.path.join(pasta, f"m{i}.mp4")
        open(p, "w").close()
        caminhos.append(p)
    for i, p in enumerate(caminhos, start=1):
        conn.execute(
            "INSERT INTO midia (nome_exibicao, nome_original, caminho_arquivo, tipo) "
            "VALUES (?, ?, ?, ?)",
            (f"{i} - Hino", f"{i} - Hino", p, "video"),
        )
    conn.commit()
    conn.close()
    return db, caminhos


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    pasta = tempfile.mkdtemp(prefix="navepro-db-")
    try:
        db, caminhos = _criar_banco(pasta)
        DatabaseManager = _carregar_classe(db)
        mgr = _novo_manager(DatabaseManager)

        # ── 1. Acesso concorrente à conexão/cache ────────────────────
        erros: list[tuple[str, str]] = []
        n_pares, n_it = 4, 150  # 4 escritores + 4 leitores

        def escritor():
            try:
                for i in range(n_it):
                    mgr.execute(
                        "INSERT INTO midia (nome_exibicao, nome_original, "
                        "caminho_arquivo, tipo) VALUES (?, ?, ?, ?)",
                        (f"x{i}", f"x{i}", caminhos[i % len(caminhos)], "audio"),
                    )
            except Exception as e:
                erros.append(("escritor", repr(e)))

        def leitor():
            try:
                for _ in range(n_it):
                    mgr.query("SELECT id FROM midia")
                    mgr.search("Hino")
                    mgr.search("1")
                    mgr.get_all_ids()
                    mgr.get_by_id(1)
            except Exception as e:
                erros.append(("leitor", repr(e)))

        def recarregador():
            try:
                for _ in range(n_it // 5):
                    mgr.reload_cache()
            except Exception as e:
                erros.append(("reload", repr(e)))

        threads = ([threading.Thread(target=escritor) for _ in range(n_pares)]
                   + [threading.Thread(target=leitor) for _ in range(n_pares)]
                   + [threading.Thread(target=recarregador) for _ in range(2)])
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        checar("query/execute/search concorrentes não estouram", not erros)
        for quem, erro in erros[:5]:
            print("    ", quem, erro)

        total = mgr.query("SELECT COUNT(*) AS n FROM midia")[0]["n"]
        esperado = 5 + n_pares * n_it
        checar(f"todas as escritas concorrentes chegaram ({total}/{esperado})",
               total == esperado)

        # ── 2. reload_cache invalida o LRU de buscas ─────────────────
        mgr2 = _novo_manager(DatabaseManager)
        mgr2.search("Hino")
        tinha_lru = bool(mgr2._result_cache)
        mgr2.reload_cache()
        checar("reload_cache esvazia o LRU de buscas",
               tinha_lru and not mgr2._result_cache)
        checar("search segue funcionando após o reload",
               isinstance(mgr2.search("Hino"), list)
               and len(mgr2.search("Hino")) >= 5)

        # ── 3. Singleton e conexão única sob corrida ─────────────────
        DatabaseManager._instance = None
        obtidos: list = []
        trava = threading.Lock()

        def construtor():
            obj = DatabaseManager()
            with trava:
                obtidos.append(obj)

        construtores = [threading.Thread(target=construtor) for _ in range(20)]
        for t in construtores:
            t.start()
        for t in construtores:
            t.join()

        checar("DatabaseManager() é sempre o mesmo objeto",
               len({id(o) for o in obtidos}) == 1)
        checar("conexão preguiçosa criada e única após corrida",
               isinstance(obtidos[0]._conn, sqlite3.Connection))
    finally:
        shutil.rmtree(pasta, ignore_errors=True)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print()
    if f:
        print(f"X {f} teste(s) falharam.")
        sys.exit(1)
    print("TODOS OS CASOS PASSARAM")
