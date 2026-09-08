#!/usr/bin/env bash
# build.sh — Gera o NavPro.AppImage (PyInstaller + appimagetool)
#
# Uso:  ./build.sh
# Saída: NavPro.AppImage (executável, pronto para distribuir)
#
# Requisitos:
#   - Python com Tk **8.6** (ex.: /usr/sbin/python) — Tk 9.0 quebra as fontes.
#   - PyInstaller instalado neste python.
#   - appimagetool (e arquivos do AppDir/).
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="NavePro"
PYTHON_BIN="${PYTHON_BIN:-/usr/sbin/python}"
APPIMAGE_TOOL="${APPIMAGE_TOOL:-appimagetool}"
ARCH="${ARCH:-$(uname -m)}"

# ────────────────────────────────────────────────────────────────────
# 0. Pré-verificações
# ────────────────────────────────────────────────────────────────────
if ! command -v "$APPIMAGE_TOOL" >/dev/null 2>&1; then
    echo "❌ appimagetool não encontrado (procurei: $APPIMAGE_TOOL)."
    echo "   Instale ou ajuste APPIMAGE_TOOL=...</caminho>"
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
# 1. Empacotar com PyInstaller (onefile)
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
# 2. Montar o AppDir
# ────────────────────────────────────────────────────────────────────
echo "📁 Atualizando AppDir/usr/bin/$APP_NAME..."
cp dist/"$APP_NAME" "AppDir/usr/bin/$APP_NAME"
chmod 755 "AppDir/usr/bin/$APP_NAME"

# ────────────────────────────────────────────────────────────────────
# 3. Gerar o AppImage (perm. de execução só para o dono)
# ────────────────────────────────────────────────────────────────────
echo "📀 Gerando ${APP_NAME}.AppImage..."
rm -f "${APP_NAME}.AppImage"
"$APPIMAGE_TOOL" AppDir "${APP_NAME}.AppImage"

# Permissão de execução somente para o usuário (700)
chmod 700 "${APP_NAME}.AppImage"
echo "✅ AppImage gerenciado: $(pwd)/${APP_NAME}.AppImage"
ls -l "${APP_NAME}.AppImage"

echo ""
echo "🎉 Pronto! Para executar:  ./${APP_NAME}.AppImage"