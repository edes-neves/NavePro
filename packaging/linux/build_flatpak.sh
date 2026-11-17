#!/usr/bin/env bash
# packaging/linux/build_flatpak.sh — gera o bundle .flatpak localmente.
#
# O Flatpak é compilado do código-fonte pelo manifest (como no Flathub), sem
# PyArmor: a política do Flathub não aceita código ofuscado. O build
# protegido (PyArmor + PyInstaller) vale para o .exe e o AppImage.
#
# Uso:  packaging/linux/build_flatpak.sh [--install]
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ"

if ! command -v flatpak-builder >/dev/null 2>&1; then
    echo "❌ flatpak-builder não encontrado (instale flatpak-builder)." >&2
    exit 1
fi

exec ./build-flatpak.sh "$@"
