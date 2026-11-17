#!/usr/bin/env bash
# packaging/linux/build_appimage.sh — gera o AppImage protegido (PyArmor).
#
# Uso:  packaging/linux/build_appimage.sh [versão]
#   Sem versão, usa APP_VERSION de navepro/config.py.
#
# Variáveis:
#   PYTHON_BIN      Python com Tk 8.6 + PyInstaller/PyArmor (padrão: .venv)
#   APPIMAGE_TOOL   caminho do appimagetool (padrão: ./appimagetool ou PATH)
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"

if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "./.venv/bin/python" ]; then
        PYTHON_BIN="./.venv/bin/python"
    else
        PYTHON_BIN="$(command -v python3)"
    fi
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "❌ Python não encontrado: $PYTHON_BIN" >&2
    exit 1
fi

TK_VERSION="$("$PYTHON_BIN" -c 'import tkinter; print(tkinter.TkVersion)' 2>/dev/null || echo erro)"
if [ "$TK_VERSION" != "8.6" ]; then
    echo "❌ $PYTHON_BIN usa Tk $TK_VERSION (o NavePro exige 8.6)." >&2
    exit 1
fi

VERSAO="${1:-$("$PYTHON_BIN" -c 'from navepro.config import APP_VERSION; print(APP_VERSION)')}"
exec "$PYTHON_BIN" build_release.py --target linux --version "$VERSAO"
