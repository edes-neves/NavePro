#!/usr/bin/env bash
# build.sh — Gera o NavePro.AppImage (PyInstaller + appimagetool)
#
# Uso:  ./build.sh <versão>        ex.: ./build.sh 2.1.4
# Saída: NavePro-<versão>.AppImage (executável, pronto para distribuir)
#
# Empacota com o NavePro.spec — a MESMA configuração usada no Windows
# (build-windows.bat). Assim Linux e Windows embutem os mesmos recursos e
# hiddenimports, e não há separador "--add-data" (":" no Linux, ";" no
# Windows) para divergir entre os dois.
#
# Requisitos:
#   - Python com Tk **8.6** (o .venv do projeto serve) — Tk 9.0 quebra as fontes.
#   - PyInstaller instalado neste python (as dependências faltantes ele instala).
#   - appimagetool (o ./appimagetool da raiz é usado automaticamente).
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="NavePro"
VERSION="${1:-1.0.0}"
#PYTHON_BIN="${PYTHON_BIN:-/usr/sbin/python}"
# Python do build: o que PYTHON_BIN indicar, senão o .venv do projeto (já tem
# PyInstaller e as dependências), senão o python do PATH (precisa de Tk 8.6).
if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "./.venv/bin/python" ]; then
        PYTHON_BIN="./.venv/bin/python"
    else
        PYTHON_BIN="$(command -v python)"
    fi
fi
# appimagetool costuma estar na raiz do projeto (./appimagetool), fora do
# PATH — sem este fallback o build parava em "appimagetool não encontrado".
if [ -z "${APPIMAGE_TOOL:-}" ]; then
    if [ -x "./appimagetool" ]; then
        APPIMAGE_TOOL="./appimagetool"
    else
        APPIMAGE_TOOL="appimagetool"
    fi
fi
ARCH="${ARCH:-$(uname -m)}"

# ────────────────────────────────────────────────────────────────────
# 0. Pré-verificações
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

# Dependências obrigatórias do app (as mesmas que o NavePro.spec embute)
for mod in PIL screeninfo pypdf; do
    if ! "$PYTHON_BIN" -c "import $mod" >/dev/null 2>&1; then
        # Nome do pacote no pip (PIL é importado como Pillow)
        pkg="$mod"; [ "$mod" = "PIL" ] && pkg="Pillow"
        echo "⚠️  Módulo '$mod' não encontrado — instalando $pkg..."
        if "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)' >/dev/null 2>&1; then
            # Virtualenv: instala direto (--user é rejeitado dentro de venv)
            "$PYTHON_BIN" -m pip install "$pkg" 2>/dev/null \
                || { echo "❌ Falha ao instalar $pkg (tente: $PYTHON_BIN -m pip install $pkg)"; exit 1; }
        else
            "$PYTHON_BIN" -m pip install --user "$pkg" 2>/dev/null \
                || "$PYTHON_BIN" -m pip install --user --break-system-packages "$pkg" 2>/dev/null \
                || { echo "❌ Falha ao instalar $pkg (tente: $PYTHON_BIN -m pip install $pkg)"; exit 1; }
        fi
    fi
done
echo "✅ Dependências: PIL/Pillow, screeninfo e pypdf OK"

# ────────────────────────────────────────────────────────────────────
# 1. Empacotar com PyInstaller (NavePro.spec — binário único)
# ────────────────────────────────────────────────────────────────────
echo "📦 Empacotando com PyInstaller (NavePro.spec)..."
"$PYTHON_BIN" -m PyInstaller --noconfirm --clean NavePro.spec
echo "✅ Binário gerado: dist/$APP_NAME"

# ────────────────────────────────────────────────────────────────────
# 2. Montar o AppDir
# ────────────────────────────────────────────────────────────────────
echo "📁 Atualizando AppDir/usr/bin/$APP_NAME..."
# O AppDir versionado só traz AppRun/ícone/desktop (usr/ é ignorado no git),
# então numa clonagem limpa a pasta usr/bin não existe e o cp falhava.
mkdir -p AppDir/usr/bin
cp dist/"$APP_NAME" "AppDir/usr/bin/$APP_NAME"
chmod 755 "AppDir/usr/bin/$APP_NAME"

# ────────────────────────────────────────────────────────────────────
# 3. Gerar o AppImage (perm. de execução só para o dono)
# ────────────────────────────────────────────────────────────────────
echo "📀 Gerando ${APP_NAME}.AppImage..."
#rm -f "${APP_NAME}.AppImage"
OUTPUT_APPIMAGE="${APP_NAME}-${VERSION}.AppImage"
rm -f "$OUTPUT_APPIMAGE"

chmod +x AppDir/AppRun
#"$APPIMAGE_TOOL" AppDir "${APP_NAME}.AppImage"
"$APPIMAGE_TOOL" AppDir "$OUTPUT_APPIMAGE"

# Permissão de execução somente para o usuário (700)
#chmod 700 "${APP_NAME}.AppImage"
#echo "✅ AppImage gerenciado: $(pwd)/${APP_NAME}.AppImage"
#ls -l "${APP_NAME}.AppImage"
chmod 700 "$OUTPUT_APPIMAGE"
echo "✅ AppImage gerenciado: $(pwd)/$OUTPUT_APPIMAGE"
ls -l "$OUTPUT_APPIMAGE"

echo ""
echo "🎉 Pronto! Para executar:  ./${OUTPUT_APPIMAGE}"
