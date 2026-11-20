#!/usr/bin/env python3
"""Extração das notas da versão para o corpo da Release (notas_release.py)."""

import importlib.util
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
_CAMINHO = os.path.join(RAIZ, "packaging", "linux", "notas_release.py")

_spec = importlib.util.spec_from_file_location("notas_release", _CAMINHO)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}")
    if not cond:
        falhas += 1


README = """
## 📜 Histórico recente

### 2.4.4

- **Espaço em campos**: não repete mais a última mídia.
- **PR/PA**: estados não se confundem.

### 2.4.3

- **Tema automático**: segue o sistema.
"""

notas = _mod.extrair_notas("2.4.4", README)
checar("extrai a versão pedida", "Espaço em campos" in notas)
checar("inclui todas as melhorias da versão", "PR/PA" in notas)
checar("não vaza a versão anterior", "Tema automático" not in notas)
checar("remove o cabeçalho ### do README", "###" not in notas)

checar("versão inexistente devolve texto vazio",
       _mod.extrair_notas("9.9.9", README) == "")

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes das notas da release passaram.")
