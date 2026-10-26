#!/usr/bin/env python3
"""Regressão: avisos do editor da Ordem de Serviço aparecem por cima dele.

Bug relatado: ao fazer algo errado no editor de item, o ``messagebox`` usava a
janela "Ordem de Serviço" como ``parent``. O editor é um ``Toplevel`` filho
dela e ficava na frente, então o aviso aparecia por baixo do editor e o
operador não via o que fazer.

Os avisos disparados de dentro do editor (salvar item, ver letra do hino)
precisam usar o próprio editor (``add_win``) como ``parent`` para serem
transientes dele e aparecerem por cima.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_TREE = ast.parse(_SRC)

_AVISOS = {
    "showwarning", "showerror", "showinfo",
    "askyesno", "askokcancel", "askquestion",
}

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


def _funcao(nome):
    encontradas = [
        n for n in ast.walk(_TREE)
        if isinstance(n, ast.FunctionDef) and n.name == nome
    ]
    check(f"encontrou a função {nome}", len(encontradas) == 1,
          str(len(encontradas)))
    return encontradas[0] if encontradas else None


def _parent_dos_avisos(no):
    """Lista (linha, parent) de todo messagebox dentro de `no`."""
    resultado = []
    for sub in ast.walk(no):
        if not isinstance(sub, ast.Call):
            continue
        if not isinstance(sub.func, ast.Attribute):
            continue
        if sub.func.attr not in _AVISOS:
            continue
        parent = next(
            (k.value for k in sub.keywords if k.arg == "parent"), None)
        resultado.append(
            (sub.lineno, ast.unparse(parent) if parent is not None else None))
    return resultado


for nome in ("_salvar_item", "_ver_letra_hino"):
    funcao = _funcao(nome)
    if funcao is None:
        continue
    avisos = _parent_dos_avisos(funcao)
    check(f"{nome} tem avisos", bool(avisos), str(avisos))
    for linha, parent in avisos:
        check(
            f"{nome}: aviso da linha {linha} é filho do editor (add_win)",
            parent == "add_win", str(parent),
        )

# O aviso de "nenhum serviço selecionado" acontece ANTES de o editor existir,
# então continua usando a janela da Ordem de Serviço (comportamento correto).
_abrir = _funcao("_abrir_editor_item")
if _abrir is not None:
    iniciais = [
        (linha, parent) for linha, parent in _parent_dos_avisos(_abrir)
        if parent == "janela"
    ]
    check("aviso sem editor aberto continua na janela da Ordem de Serviço",
          len(iniciais) == 1, str(iniciais))

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
