#!/usr/bin/env bash
# publicar.sh — Release completo do NavePro em um único comando.
#
# Uso:  ./publicar.sh <versão> [-y]
#       ./publicar.sh 1.9.4          (ou v1.9.4)
#       ./publicar.sh 1.9.4 -y       (sem pedir confirmação)
#
# Faz, em sequência:
#   1. Atualiza APP_VERSION em navepro/config.py para <versão>
#   2. ./build.sh <versão>            → gera NavePro-<versão>.AppImage
#   3. git commit (todas as mudanças)
#   4. git tag v<versão>
#   5. git push origin <branch> v<versão>
#   6. gh release create v<versão> com o AppImage anexado
#
# Depois disso, a CI (.github/workflows/flatpak.yml) anexa os Flatpaks
# (x86_64/aarch64) à mesma release automaticamente.
#
# Variáveis de ambiente respeitadas (opcionais):
#   PYTHON_BIN   — Python usado no build (precisa ser Tk 8.6).
#   APPIMAGE_TOOL— caminho do appimagetool (default: ./appimagetool).
set -euo pipefail
cd "$(dirname "$0")"

AUTO=0
VERSION=""
for arg in "$@"; do
  case "$arg" in
    -y|--yes|--auto) AUTO=1 ;;
    *) VERSION="${arg#v}" ;;
  esac
done

if [ -z "$VERSION" ]; then
  echo "Uso:  ./publicar.sh <versão> [-y]"
  echo "      versão no formato X.Y.Z (aceita também vX.Y.Z)"
  exit 1
fi
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "❌ Versão inválida: '$VERSION' (use X.Y.Z, ex.: 1.9.4)."
  exit 1
fi

TAG="v$VERSION"
APPIMAGE="NavePro-$VERSION.AppImage"
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo '')"

# ────────────────────────────────────────────────────────────────────
# 0. Pré-verificações
# ────────────────────────────────────────────────────────────────────
[ -n "$BRANCH" ] || { echo "❌ Não está em uma branch (HEAD destacado)."; exit 1; }

export APPIMAGE_TOOL="${APPIMAGE_TOOL:-./appimagetool}"
if ! command -v "$APPIMAGE_TOOL" >/dev/null 2>&1 && [ ! -x "$APPIMAGE_TOOL" ]; then
  echo "❌ appimagetool não encontrado (procurei: $APPIMAGE_TOOL)."
  echo "   Dica: ./appimagetool já está no projeto."
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "❌ 'gh' (GitHub CLI) não encontrado. Instale com: sudo apt install gh"
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "❌ 'gh' não está autenticado. Rode: gh auth login"
  exit 1
fi

PREV="$(git describe --tags --abbrev=0 2>/dev/null || echo '')"

echo "Versão  : $VERSION"
echo "Tag     : $TAG"
echo "Branch  : $BRANCH"
echo "AppImage: $APPIMAGE"
echo "Anterior: ${PREV:-nenhuma tag anterior}"
echo
echo "📋 Será feito:"
echo "  1. Atualizar APP_VERSION → $VERSION em navepro/config.py"
echo "  2. ./build.sh $VERSION"
echo "  3. git commit (todas as mudanças pendentes)"
echo "  4. git tag $TAG"
echo "  5. git push origin $BRANCH $TAG"
echo "  6. gh release create $TAG com $APPIMAGE"
echo "     (a CI anexa os Flatpaks na sequência)"
echo
if [ "$AUTO" -eq 0 ]; then
  read -r -p "Confirmar? [y/N] " resp
  case "$resp" in y|Y|s|S) ;; *) echo "Cancelado."; exit 1 ;; esac
fi

# ────────────────────────────────────────────────────────────────────
# 1. Versão no fonte
# ────────────────────────────────────────────────────────────────────
sed -i "s/^\(APP_VERSION: str = \"\)[^\"]*/\1$VERSION/" navepro/config.py
grep -q "^APP_VERSION: str = \"$VERSION\"" navepro/config.py \
  || { echo "❌ Não consegui atualizar APP_VERSION em navepro/config.py."; exit 1; }
echo "✅ APP_VERSION = $VERSION"

# ────────────────────────────────────────────────────────────────────
# 2. AppImage
# ────────────────────────────────────────────────────────────────────
echo "📦 Gerando o AppImage (pode demorar)..."
./build.sh "$VERSION"
[ -f "$APPIMAGE" ] || { echo "❌ $APPIMAGE não foi gerado."; exit 1; }
echo "✅ $APPIMAGE criado"

# ────────────────────────────────────────────────────────────────────
# 3. Commit
# ────────────────────────────────────────────────────────────────────
git add -A
if git diff --cached --quiet; then
  echo "ℹ️  Nada novo para commitar (árvore já estava limpa)."
else
  git commit -m "NavePro $VERSION" --quiet
  echo "✅ Commit criado"
fi

# ────────────────────────────────────────────────────────────────────
# 4. Tag
# ────────────────────────────────────────────────────────────────────
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "⚠️  Tag $TAG já existe; reutilizando."
else
  git tag "$TAG"
  echo "✅ Tag $TAG criada"
fi

# ────────────────────────────────────────────────────────────────────
# 5. Push
# ────────────────────────────────────────────────────────────────────
echo "⏫ Enviando para o GitHub..."
git push origin "$BRANCH"
git push origin "$TAG"
echo "✅ Push concluído"

# ────────────────────────────────────────────────────────────────────
# 6. Release
# ────────────────────────────────────────────────────────────────────
if [ -n "$PREV" ]; then
  NOTAS="Novidades desta versão:

$(git log --oneline --no-decorate "$PREV..HEAD" | sed 's/^/• /')"
else
  NOTAS="NavePro $VERSION."
fi

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
if gh release view "$TAG" >/dev/null 2>&1; then
  echo "⚠️  Release $TAG já existe; apenas anexando o AppImage."
  gh release upload "$TAG" "$APPIMAGE" --clobber >/dev/null
else
  gh release create "$TAG" "$APPIMAGE" --title "NavePro $VERSION" --notes "$NOTAS"
fi
echo "✅ Release criada"

echo
echo "🎉 Pronto! https://github.com/$REPO/releases/tag/$TAG"