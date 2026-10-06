"""Banco de Bíblia temporário para as suítes de lógica e de projeção.

As suítes de bíblia/projeção consultam a tabela `versiculos` (João 3) por um
stub de `db_query`. Antes elas apontavam para `~/.navepro/midia.db` — o banco
real do usuário — e quebravam em máquina limpa (CI ou outra estação), onde
esse arquivo não existe. A fixture monta um banco num diretório temporário
com o MESMO schema do app (extraído do `init_db` real do NavePro.py, não
copiado) e semeia João 3 com os 36 versículos que os testes percorrem.

Nada no `~/.navepro` do usuário é lido nem escrito.
"""

import ast
import atexit
import contextlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# Referência que as suítes usam; o texto é de prova — os testes conferem
# números e rótulos ("João 3:9"), nunca o conteúdo dos versículos.
VERSAO = 'Almeida Revista e Corrigida'
LIVRO = 'João'
CAPITULO = 3
TOTAL_VERSICULOS = 36


def criar_biblia() -> tuple[str, str]:
    """Cria o banco temporário e devolve (raiz, caminho do banco)."""
    raiz = tempfile.mkdtemp(prefix='navepro-biblia-')
    atexit.register(limpar_biblia, raiz)
    db = os.path.join(raiz, 'midia.db')
    uploads = os.path.join(raiz, 'uploads')
    _criar_schema(db, uploads)
    _semear(db)
    return raiz, db


def limpar_biblia(raiz: str) -> None:
    """Remove a raiz temporária criada por `criar_biblia`."""
    shutil.rmtree(raiz, ignore_errors=True)


def _criar_schema(db: str, uploads: str) -> None:
    """Executa o `init_db` real do NavePro.py apontando para o banco temporário."""
    src = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
    no = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == 'init_db'][0]
    ns = {'os': os, 'sqlite3': sqlite3, 'DB_PATH': db, 'UPLOAD_FOLDER': uploads}
    # as mensagens de migração do init_db poluem a saída da suíte
    with contextlib.redirect_stdout(io.StringIO()):
        exec(ast.get_source_segment(src, no), ns)
        ns['init_db']()


def _semear(db: str) -> None:
    """Grava João 3 (1..TOTAL_VERSICULOS) na versão usada pelos testes."""
    conn = sqlite3.connect(db)
    linhas = [
        (VERSAO, LIVRO, CAPITULO, n,
         f'Versículo {n} de {LIVRO} {CAPITULO} (texto de prova).')
        for n in range(1, TOTAL_VERSICULOS + 1)
    ]
    conn.executemany(
        'INSERT INTO versiculos (versao, livro, capitulo, versiculo, texto) '
        'VALUES (?, ?, ?, ?, ?)', linhas)
    conn.commit()
    conn.close()
