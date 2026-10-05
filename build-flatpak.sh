#!/usr/bin/env bash
# Gera o Flatpak do NavePro em uma única arquitetura (nativa) localmente.
#
# Pré-requisitos (Debian/Ubuntu):
#   sudo apt install flatpak flatpak-builder
#   flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
#   flatpak install flathub org.freedesktop.Platform//24.08 org.freedesktop.Sdk//24.08
#
# Uso:
#   ./build-flatpak.sh            # gera io.github.edesneves.NavePro.<arch>.flatpak
#   ./build-flatpak.sh --install  # também instala no usuário (flatpak --user install)

set -euo pipefail

APP_ID="io.github.edesneves.NavePro"
MANIFEST="flatpak/${APP_ID}.yaml"
ARCH="$(flatpak --default-arch)"
BUILD_DIR="flatpak/build"
REPO_DIR="flatpak/repo"
OUT_BUNDLE="${APP_ID}.${ARCH}.flatpak"

mkdir -p "${BUILD_DIR}" "${REPO_DIR}"

echo "=== Gerando ${OUT_BUNDLE} (arquitetura ${ARCH}) ==="
# Limpa módulos em cache (flatpak-builder não tem --clean-cache em todas as versões)
rm -rf "${BUILD_DIR}" .flatpak-builder
flatpak-builder --repo="${REPO_DIR}" --force-clean --disable-rofiles-fuse "${BUILD_DIR}" "${MANIFEST}"

echo "=== Criando bundle ${OUT_BUNDLE} ==="
flatpak build-bundle "${REPO_DIR}" "${OUT_BUNDLE}" "${APP_ID}"

echo "=== OK: ${OUT_BUNDLE} ==="

if [ "${1:-}" = "--install" ]; then
    flatpak --user install --assumeyes "${OUT_BUNDLE}"
    echo "=== Instalado. Execute com: flatpak run ${APP_ID} ==="
fi