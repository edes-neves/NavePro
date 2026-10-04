#!/usr/bin/env bash
# Atalho para o fluxo de release automatizado:
# grava a versão no APP_VERSION, gera o AppImage, faz commit, tag,
# push e cria a release no GitHub.
#
# Uso:  ./versao.sh 2.1.0        # ou ./publicar.sh 2.1.0
set -euo pipefail
cd "$(dirname "$0")"

if [ $# -lt 1 ]; then
  echo "Uso:  ./versao.sh <versão> [-y]"
  echo "      ex.: ./versao.sh 2.1.0"
  echo
  echo "      O mesmo que ./publicar.sh <versão> (o 'publicar.sh' é quem faz o trabalho)."
  exit 1
fi

exec ./publicar.sh "$@"