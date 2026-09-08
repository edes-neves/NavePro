#!/usr/bin/env bash
# build.sh — Gera o AppImage do NavePro (PyInstaller + appimagetool)
#
# Uso:  ./build.sh [VERSÃO]
#   ./build.sh           → usa a versão do tag git mais próximo (sem o 'v')
#   ./build.sh 1.9.0     → usa a versão informada
#   VERSION=1.9.0 ./build.sh
#
# Saída: NavePro-<VERSÃO>.AppImage (ex.: NavePro-1.9.0.AppImage)
#
# IMPORTANTE: a VERSÃO também é gravada em APP_VERSION no NavePro.py
# (fonte único de verdade). Assim o AppImage baixado sempre mostra a
# versão do seu release no GitHub — evita o problema de subir um release
# 1.9.0 com um binário que ainda dizia 1.8.0.
#
# Requisitos:
#   - Python com Tk **8.6** (ex.: /usr/sbin/python) — Tk 9.0 quebra as fontes.
#   - PyInstaller instalado neste python.
#   - appimagetool (e arquivos do AppDir/).
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="NavePro"
#PYTHON_BIN="${PYTHON_BIN:-/usr/sbin/python}"
PYTHON_BIN="${PYTHON_BIN:-python}"
APPIMAGE_TOOL="${APPIMAGE_TOOL:-appimagetool}"
ARCH="${ARCH:-$(uname -m)}"

# ────────────────────────────────────────────────────────────────────
# 0. Determinando a versão do release
# ────────────────────────────────────────────────────────────────────
VERSION=""
if [ -n "${1:-}" ]; then
    VERSION="$1"
elif [ -n "${VERSION:-}" ]; then
    VERSION="${VERSION}${1:+}"
elif VERSION_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"; then
    VERSION="${VERSION_TAG#v}"
fi

if [ -z "$VERSION" ]; then
    echo "❌ Não foi possível determinar a versão."
    echo "   Use:  ./build.sh 1.9.0      (ou VERSION=1.9.0, ou crie um tag git v1.9.0)"
    exit 1
fi

# Valida formato X.Y.Z (ou X.Y)
if ! [[ "$VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}([-+][0-9A-Za-z.]+)?$ ]]; then
    echo "❌ Versão '$VERSION' em formato inválido (esperado algo como 1.9.0)."
    exit 1
fi

# Sincroniza APP_VERSION no fonte (single source of truth) — só quando difere.
if ! grep -q "^APP_VERSION: str = \"$VERSION\"$" "$APP_NAME.py"; then
    echo "🔄 Gravando APP_VERSION = $VERSION em $APP_NAME.py"
    sed -i "s/^APP_VERSION: str = \".*\"/APP_VERSION: str = \"$VERSION\"/" "$APP_NAME.py"
    grep -q "^APP_VERSION: str = \"$VERSION\"$" "$APP_NAME.py" \
        || { echo "❌ Não consegui atualizar APP_VERSION em $APP_NAME.py"; exit 1; }
fi
echo "✅ Versão do build: $VERSION (APP_VERSION = $VERSION em $APP_NAME.py)"

# ────────────────────────────────────────────────────────────────────
# 1. Pré-verificações
# ────────────────────────────────────────────────────────────────────
if ! command -v "$APPIMAGE_TOOL" >/dev/null 2>&1; then
    echo "❌ appimagetool não encontrado (procurei: $APPIMAGE_TOOL)."
    echo "   Instale ou ajuste APPIMAGE_TOOL=...<./appimagetool>"
    exit 1 
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "❌ Python não existe: $PYTHON_BIN"
    exit 1
fi

TK_VERSION="$("$PYTHON_BIN" -c 'import tkinter; print(tkinter.TkVersion)' 2>/dev/null || echo 'erro')"
if [ "$TK_VERSION" != "8.6" ]; then
    echo "⚠️  $PYTHON_BIN usa Tk $TK_VERSION (esperado 8.6)."
    echo "   O Tk 9.0 NÃO resolve aliases de fonte e gera fontes minúsculas/"
    echo "   quadradinhos. Defina PYTHON_BIN=<python com Tk 8.6> para continuar."
    exit 1
fi
echo "✅ Python: $PYTHON_BIN (Tk $TK_VERSION)"

if ! "$PYTHON_BIN" -c 'import PyInstaller' >/dev/null 2>&1; then
    echo "❌ PyInstaller não está instalado no $PYTHON_BIN."
    echo "   Rode: $PYTHON_BIN -m pip install pyinstaller"
    exit 1
fi
echo "✅ PyInstaller: $("$PYTHON_BIN" -m PyInstaller --version)"

# Dependências obrigatórias do app
for mod in PIL screeninfo; do
    if ! "$PYTHON_BIN" -c "import $mod" >/dev/null 2>&1; then
        echo "⚠️  Módulo '$mod' não encontrado — instalando..."
        "$PYTHON_BIN" -m pip install --user "$mod" 2>/dev/null \
            || "$PYTHON_BIN" -m pip install --user --break-system-packages "$mod" 2>/dev/null \
            || { echo "❌ Falha ao instalar $mod (tente: $PYTHON_BIN -m pip install $mod)"; exit 1; }
    fi
done
echo "✅ Dependências: PIL/Pillow e screeninfo OK"

# ────────────────────────────────────────────────────────────────────
# 2. Empacotar com PyInstaller (onefile)
# ────────────────────────────────────────────────────────────────────
echo "📦 Empacotando com PyInstaller..."
"$PYTHON_BIN" -m PyInstaller --noconfirm --clean --onefile \
    --name "$APP_NAME" \
    --hidden-import "PIL._tkinter_finder" \
    --add-data "Icon.xbm:." \
    --add-data "Icon.png:." \
    "$APP_NAME.py"
echo "✅ Binário gerado: dist/$APP_NAME"

# ────────────────────────────────────────────────────────────────────
# 3. Montar o AppDir
# ────────────────────────────────────────────────────────────────────
echo "📁 Atualizando AppDir/usr/bin/$APP_NAME..."
cp dist/"$APP_NAME" "AppDir/usr/bin/$APP_NAME"
chmod 755 "AppDir/usr/bin/$APP_NAME"

# ────────────────────────────────────────────────────────────────────
# 4. Gerar o AppImage (perm. de execução só para o dono)
# ────────────────────────────────────────────────────────────────────
APPIMAGE_FINAL="${APP_NAME}-${VERSION}.AppImage"
echo "📀 Gerando ${APPIMAGE_FINAL}..."
rm -f "${APPIMAGE_FINAL}"
chmod +x AppDir/AppRun
"$APPIMAGE_TOOL" AppDir "${APPIMAGE_FINAL}"

# Permissão de execução somente para o usuário (700)
chmod 700 "${APPIMAGE_FINAL}"
echo "✅ AppImage gerenciado: $(pwd)/${APPIMAGE_FINAL}"
ls -l "${APPIMAGE_FINAL}"

echo ""
echo "🎉 Pronto! Para executar:  ./${APPIMAGE_FINAL}"
echo "   Publique o release com:  gh release create v${VERSION} ${APPIMAGE_FINAL} --title \"NavePro ${VERSION}\" --notes \"...\" (ou anexe o arquivo no GitHub)"
