#!/usr/bin/env python3
"""Invariantes de empacotamento (Flatpak e AppImage do CI).

O Flatpak 2.4.0 saiu sem ``license_manager.py`` e sem as dependências de
licenciamento, então o app instalado quebrava no import. O AppImage do CI
também passou a ser compilado com o Python 3.14 do runner (x86-64-v3 + Tk 9),
que não abre em CPUs sem AVX2. Este teste trava as duas correções.
"""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


def _ler(caminho: str) -> str:
    with open(os.path.join(RAIZ, caminho), encoding="utf-8") as fh:
        return fh.read()


def _rodar() -> int:
    manifest = _ler("flatpak/io.github.edes_neves.NavePro.yaml")
    requisitos = _ler("flatpak/requirements-flatpak.txt")
    workflow = _ler(".github/workflows/build.yml")

    checar("manifest instala license_manager.py",
           "install -Dm644 NavePro.py license_manager.py" in manifest)
    checar("manifest declara license_manager.py como source",
           "path: ../license_manager.py" in manifest)
    checar("Flatpak instala cryptography (licenciamento)",
           "cryptography" in requisitos)
    checar("Flatpak instala requests (lista negra)",
           "requests" in requisitos)

    inicio = workflow.find("  appimage:")
    fim = workflow.find("  flatpak:", inicio)
    bloco_appimage = workflow[inicio:fim] if inicio >= 0 and fim > inicio else ""
    checar("AppImage do CI usa Ubuntu 22.04 (Tk 8.6, sem x86-64-v3)",
           "runs-on: ubuntu-22.04" in bloco_appimage)
    checar("repositório Flatpak publica índices de delta",
           'build-update-repo --generate-static-deltas' in workflow)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
