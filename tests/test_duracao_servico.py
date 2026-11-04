#!/usr/bin/env python3
"""Testes da formatação de duração usada na Ordem de Serviço."""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from navepro.core.servicos import _formatar_duracao_segundos as fmt  # noqa: E402


def _rodar() -> int:
    falhas = 0

    def checar(desc, obtido, esperado):
        nonlocal falhas
        ok = obtido == esperado
        print(f"{'OK ' if ok else 'X  '} {desc}: {obtido!r}")
        if not ok:
            falhas += 1

    checar("None vira travessão", fmt(None), "—")
    checar("texto inválido vira travessão", fmt("abc"), "—")
    checar("zero", fmt(0), "0:00")
    checar("segundos", fmt(59), "0:59")
    checar("minuto cheio", fmt(60), "1:00")
    checar("arredonda", fmt(90.6), "1:31")
    checar("quase uma hora", fmt(3599), "59:59")
    checar("uma hora", fmt(3600), "1:00:00")
    checar("hora completa", fmt(3661), "1:01:01")
    checar("negativo vira zero", fmt(-5), "0:00")

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
