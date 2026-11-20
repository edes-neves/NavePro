#!/usr/bin/env python3
"""Extrai do README as notas da versão para o corpo da Release do GitHub.

O ``generate_release_notes`` do GitHub só lista Pull Requests; como o NavePro
publica commits direto na main, a Release ficava apenas com o link do
changelog. Este script usa a seção ``### <versão>`` do "Histórico recente".
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def extrair_notas(versao: str, texto: str) -> str:
    """Devolve o conteúdo da seção ``### <versão>`` (sem o cabeçalho)."""
    padrao = re.compile(
        rf"^### {re.escape(versao)}\s*$\n(.*?)(?=^### |^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    achado = padrao.search(texto)
    return achado.group(1).strip() if achado else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("versao", help="versão sem o prefixo v (ex.: 2.4.4)")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--anterior", default="",
                        help="tag anterior para o link de changelog")
    args = parser.parse_args()

    versao = args.versao.lstrip("v")
    texto = Path(args.readme).read_text(encoding="utf-8")
    notas = extrair_notas(versao, texto)
    if not notas:
        notas = f"Notas da versão {versao} não encontradas no README."

    print(f"## Novidades da versão {versao}")
    print()
    print(notas)
    if args.anterior:
        repositorio = os.environ.get("GITHUB_REPOSITORY", "edes-neves/NavePro")
        print()
        print(f"**Changelog completo**: https://github.com/{repositorio}/compare/"
              f"{args.anterior}...v{versao}")


if __name__ == "__main__":
    main()
