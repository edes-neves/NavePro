#!/usr/bin/env python3
"""Abertura da Bíblia em grade sem bloquear a janela.

A janela é aberta e fechada várias vezes durante o culto. O teste garante que:

- o índice (versões/livros/capítulos) fica em cache e é invalidado na importação;
- a carga da grade é agendada com ``after_idle`` (a janela aparece primeiro);
- o ``<Configure>`` só é ligado depois da carga inicial e ignora eventos sem
  mudança real de tamanho (o fullscreen dispara vários e redesenha tudo);
- timers pendentes são cancelados ao fechar (evita ``invalid command name``).
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.ui import biblia_grade  # noqa: E402

falhas = []


def checar(desc, cond, extra=""):
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(desc)


# ── 1. Cache do índice ───────────────────────────────────────────────
biblia_grade._CACHE_BIBLIA['versoes'] = ['ARC']
biblia_grade._CACHE_BIBLIA['livros']['ARC'] = ['Gênesis']
biblia_grade._CACHE_BIBLIA['capitulos'][('ARC', 'Gênesis')] = [1, 2]
biblia_grade._invalidar_cache_biblia()
checar("importação invalida a lista de versões",
       biblia_grade._CACHE_BIBLIA['versoes'] is None)
checar("importação invalida os livros por versão",
       biblia_grade._CACHE_BIBLIA['livros'] == {})
checar("importação invalida os capítulos por livro",
       biblia_grade._CACHE_BIBLIA['capitulos'] == {})

# ── 2. Carga inicial adiada e Configure só depois ────────────────────
_CAMINHO = os.path.join(RAIZ, "navepro", "ui", "biblia_grade.py")
_SRC = open(_CAMINHO, encoding="utf-8").read()
_TREE = ast.parse(_SRC)

_classe = next(n for n in ast.walk(_TREE)
               if isinstance(n, ast.ClassDef)
               and n.name == "JanelaBibliaGradeMixin")
_metodo = next(n for n in _classe.body
               if isinstance(n, ast.FunctionDef) and n.name == "janela_biblia")
_funcoes = {n.name: n for n in ast.walk(_metodo)
            if isinstance(n, ast.FunctionDef)}


def _chamadas(no, nome_attr):
    for sub in ast.walk(no):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == nome_attr:
            yield sub


checar("carga inicial virou função separada", "_carga_inicial" in _funcoes)
checar("carga inicial é agendada com after_idle",
       any(c.args and isinstance(c.args[0], ast.Name)
           and c.args[0].id == "_carga_inicial"
           for c in _chamadas(_metodo, "after_idle")))
checar("carga inicial NÃO roda direto na abertura",
       not any(isinstance(c.func, ast.Name) and c.func.id == "_carga_inicial"
               for c in ast.walk(_metodo) if isinstance(c, ast.Call)))

_seg_carga = ast.get_source_segment(_SRC, _funcoes["_carga_inicial"])
checar("Configure é ligado só ao fim da carga inicial",
       "'<Configure>'" in _seg_carga)
checar("redesenho por Configure compara o tamanho",
       "_tamanho_renderizado" in ast.get_source_segment(
           _SRC, _funcoes["_ao_redimensionar_janela"]))

_seg_destruir = ast.get_source_segment(_SRC, _funcoes["_ao_destruir"])
checar("fechar cancela os timers pendentes",
       "_id_carga" in _seg_destruir and "_id_resize" in _seg_destruir)

# ── 3. Abre maximizada no monitor, sem tela cheia ────────────────────
checar("maximizar no monitor virou função separada",
       "_maximizar_no_monitor" in _funcoes)
_seg_abertura = ast.get_source_segment(_SRC, _metodo)
checar("abertura NÃO entra em tela cheia",
       "'-fullscreen'" not in _seg_abertura.split(
           "def _toggle_fullscreen", 1)[0])
checar("abertura ocupa a área do monitor (maximizada)",
       "-zoomed" in ast.get_source_segment(
           _SRC, _funcoes["_maximizar_no_monitor"]))

print()
if falhas:
    print(f"X {len(falhas)} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes da Bíblia em grade passaram.")
