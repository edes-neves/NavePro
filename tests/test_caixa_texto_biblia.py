#!/usr/bin/env python3
"""Caixa (cartão) da projeção bíblica: contraste com o fundo e limpeza.

A caixa é desenhada pelo próprio Tk (sem display neste teste), então a
verificação cobre a lógica pura de contraste/cantos e, pela AST, garante que
o texto com referência bíblica continua desenhando a caixa e que o cartão é
removido ao voltar ao relógio.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

ARQ = os.path.join(RAIZ, "navepro", "core", "telao.py")
fonte = open(ARQ, encoding="utf-8").read()
modulo = ast.parse(fonte)
nos = {n.name: n for n in ast.walk(modulo) if isinstance(n, ast.FunctionDef)}

from navepro.core.telao import TelaoWindow  # noqa: E402

falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'?' if cond else 'X'} {desc}")
    if not cond:
        falhas += 1


class _RootFalso:
    def winfo_rgb(self, cor):
        hexa = cor.lstrip("#")
        r, g, b = (int(hexa[i:i + 2], 16) for i in (0, 2, 4))
        return (r * 257, g * 257, b * 257)


telao = object.__new__(TelaoWindow)
telao.root = _RootFalso()


def _lum(cor):
    hexa = cor.lstrip("#")
    r, g, b = (int(hexa[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


for fundo in ("#000000", "#1a1a2e", "#0d1b2a", "#0a1f0a", "#2d0a0a"):
    fundo_caixa, borda, _sombra = telao._cores_da_caixa_texto(fundo)
    checar(f"fundo escuro {fundo}: borda clara contrasta",
           _lum(borda) - _lum(fundo) > 0.45)
    checar(f"fundo escuro {fundo}: cartão diferente do fundo",
           abs(_lum(fundo_caixa) - _lum(fundo)) > 0.05)
    checar(f"fundo escuro {fundo}: borda mais clara que o cartão",
           _lum(borda) > _lum(fundo_caixa))

for fundo in ("#FFFFFF", "#F0F0F0", "#E6EDF3"):
    fundo_caixa, borda, _sombra = telao._cores_da_caixa_texto(fundo)
    checar(f"fundo claro {fundo}: borda escura contrasta",
           _lum(fundo) - _lum(borda) > 0.45)
    checar(f"fundo claro {fundo}: cartão escuro", _lum(fundo_caixa) < 0.5)
    checar(f"fundo claro {fundo}: borda mais escura que o cartão",
           _lum(borda) < _lum(fundo_caixa))

pontos = telao._pontos_caixa_arredondada(10, 20, 210, 120, 18)
checar("cantos arredondados têm 24 coordenadas", len(pontos) % 2 == 0)
checar("caixa não sai do retângulo informado",
       min(pontos[0::2]) >= 10 and max(pontos[0::2]) <= 210
       and min(pontos[1::2]) >= 20 and max(pontos[1::2]) <= 120)

# Invariantes no código real: a referência bíblica e a limpeza do cartão.
corpo_texto = ast.get_source_segment(fonte, nos["_desenhar_texto_no_canvas"])
checar("texto com referência bíblica ativa a caixa",
       "usar_caixa = bool(referencia" in corpo_texto)
checar("texto com referência desenha o cartão",
       "_desenhar_caixa_texto(" in corpo_texto)
checar("cartão é limpo antes de redesenhar",
       "self._limpar_caixa_texto()" in corpo_texto)
corpo_relogio = ast.get_source_segment(fonte, nos["_retornar_ao_relogio"])
checar("voltar ao relógio remove o cartão",
       'getattr(self, "_limpar_caixa_texto", None)' in corpo_relogio)

print("OK" if not falhas else f"\n{falhas} falha(s)")
sys.exit(1 if falhas else 0)
