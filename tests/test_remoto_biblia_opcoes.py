#!/usr/bin/env python3
"""Teste do endpoint de opções Cap:/V: do controle remoto (Bíblia).

Trava a ação GET /api/remoto/biblia_opcoes: os mesmos SELECT DISTINCT dos
combos da janela Bíblia, expostos para o celular preencher as listas dos
campos "Cap:" e "V:", além do wiring (rota no servidor → despacho no
NavePro).
"""

import ast
import os
import sqlite3
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from fixture_biblia import (  # noqa: E402
    CAPITULO,
    LIVRO,
    TOTAL_VERSICULOS,
    VERSAO,
    criar_biblia,
)

_raiz, DB = criar_biblia()


def db_query(sql, params=()):
    # Mesmo retorno do db_query real (list[dict], ver navepro/core/banco.py).
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


src = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
tree = ast.parse(src)

no = next(n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef)
          and n.name == '_remoto_biblia_opcoes')
ns: dict = {'db_query': db_query}
exec(ast.get_source_segment(src, no), ns)  # noqa: S102
opcoes = ns['_remoto_biblia_opcoes']


class SelfFake:
    def _versoes_biblia(self):
        return [VERSAO]


def checar(nome, cond):
    if not cond:
        raise AssertionError("FALHOU: " + nome)
    print("ok -", nome)


self = SelfFake()

# Capítulos do livro/versão: o fixture semeia só João 3.
r = opcoes(self, {'versao': VERSAO, 'livro': LIVRO, 'cap': ''})
checar("capítulos de João = ['3']", r['ok'] and r['capitulos'] == ['3'])
checar("sem capítulo digitado não há opções de versículo",
       r['versiculos'] == [])

# Versículos do capítulo existente (1..TOTAL_VERSICULOS como strings).
r = opcoes(self, {'versao': VERSAO, 'livro': LIVRO, 'cap': str(CAPITULO)})
checar(f"versículos de {LIVRO} {CAPITULO} = 1..{TOTAL_VERSICULOS}",
       r['versiculos'] == [str(n) for n in range(1, TOTAL_VERSICULOS + 1)])

# Capítulo inexistente no livro: listas vazias (não inventa números).
r = opcoes(self, {'versao': VERSAO, 'livro': LIVRO, 'cap': '99'})
checar("capítulo sem versículos devolve lista vazia", r['versiculos'] == [])

# Capítulo não numérico (faixa "1-7", vazio, texto): sem opções de V:,
# igual ao combo do app que só popula com dígito.
for cap in ('1-7', 'abc', '  '):
    r = opcoes(self, {'versao': VERSAO, 'livro': LIVRO, 'cap': cap})
    checar(f"cap '{cap}' não numérico → sem versículos", r['versiculos'] == [])

# Livro inexistente/versão vazia: nada é inventado.
r = opcoes(self, {'versao': VERSAO, 'livro': 'Nada Aqui', 'cap': '1'})
checar("livro desconhecido → sem capítulos",
       r['ok'] and r['capitulos'] == [] and r['versiculos'] == [])
r = opcoes(self, {'versao': '', 'livro': '', 'cap': ''})
checar("sem versão/livro → listas vazias (não quebra)",
       r['ok'] and r['capitulos'] == [] and r['versiculos'] == [])

# Versão vazia cai na primeira versão existente (como os demais handlers).
r = opcoes(self, {'versao': '', 'livro': LIVRO, 'cap': str(CAPITULO)})
checar("versão vazia usa a primeira do banco",
       r['capitulos'] == ['3'] and len(r['versiculos']) == TOTAL_VERSICULOS)

# ── Wiring: rota no servidor → ação → despacho no NavePro ──
src_srv = open(os.path.join(RAIZ, 'navepro', 'core', 'servidor_http.py'),
               encoding='utf-8').read()
checar("servidor registra a rota /api/remoto/biblia_opcoes",
       "'/api/remoto/biblia_opcoes'" in src_srv
       and "'biblia_opcoes'" in src_srv)

despacho = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == '_remoto_despacho')
fonte_despacho = ast.get_source_segment(src, despacho) or ''
checar("despacho roteia a ação biblia_opcoes",
       "'biblia_opcoes'" in fonte_despacho
       and '_remoto_biblia_opcoes' in fonte_despacho)

# A página declara os datalists, liga-os aos inputs e os preenche no JS
# (o invariante genérico do test_remoto_web não vê ids passados por variável).
src_web = open(os.path.join(RAIZ, 'navepro', 'remoto_web.py'),
               encoding='utf-8').read()
for _id in ('bib_cap_opcoes', 'bib_vers_opcoes'):
    checar(f"página declara o datalist {_id}",
           f'id="{_id}"' in src_web and f'list="{_id}"' in src_web)
    checar(f"JS preenche o datalist {_id}",
           f"preencherOpcoes('{_id}'" in src_web)

print("Todos os testes passaram.")
