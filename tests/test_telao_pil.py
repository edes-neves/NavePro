#!/usr/bin/env python3
"""Regressão: o telão precisa do PIL (Image/ImageTk) no escopo do módulo.

A extração de `TelaoWindow` para `navepro/core/telao.py` deixou de importar
o PIL no topo do módulo: `_renderizar_imagem_projetada`,
`_aplicar_fundo_projecao` e `_aplicar_cores_relogio` usam `Image`/`ImageTk`
como se fossem globais, mas os `from PIL import ...` locais de outros métodos
(herdados do monólito) não os enxergavam. Resultado: projeção de imagem e
imagem de fundo falhavam com "name 'Image' is not defined".

Este teste trava a correção sem depender do Pillow instalado: confere, pela
AST, que `Image` e `ImageTk` estão ligados no nível do módulo.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
ARQ = os.path.join(RAIZ, "navepro", "core", "telao.py")

falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'?' if cond else 'X'} {desc}")
    if not cond:
        falhas += 1


def _nomes_de_topo(corpo):
    """Nomes ligados no nível do módulo (inclusive dentro de try do topo)."""
    nomes = set()
    for no in corpo:
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            for alias in no.names:
                nomes.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(no, ast.Assign):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name):
                    nomes.add(alvo.id)
        elif isinstance(no, ast.Try):
            nomes |= _nomes_de_topo(no.body)
            nomes |= _nomes_de_topo(no.handlers)
            nomes |= _nomes_de_topo(no.orelse)
            nomes |= _nomes_de_topo(no.finalbody)
    return nomes


fonte = open(ARQ, encoding="utf-8").read()
modulo = ast.parse(fonte)
topo = _nomes_de_topo(modulo.body)

checar("telao.py liga 'Image' no escopo do módulo", "Image" in topo)
checar("telao.py liga 'ImageTk' no escopo do módulo", "ImageTk" in topo)


def _metodos_da_classe(nome_classe):
    for no in ast.walk(modulo):
        if isinstance(no, ast.ClassDef) and no.name == nome_classe:
            return {sub.name for sub in no.body
                    if isinstance(sub, ast.FunctionDef)}
    return set()


metodos = _metodos_da_classe("TelaoWindow")
checar("_renderizar_imagem_projetada existe", "_renderizar_imagem_projetada" in metodos)
checar("_aplicar_fundo_projecao existe", "_aplicar_fundo_projecao" in metodos)
checar("_aplicar_cores_relogio existe", "_aplicar_cores_relogio" in metodos)

print("OK" if not falhas else f"\n{falhas} falha(s)")
sys.exit(1 if falhas else 0)
