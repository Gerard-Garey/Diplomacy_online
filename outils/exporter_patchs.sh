#!/usr/bin/env bash
# Sens inverse d'install.sh : reporte dans le dépôt le travail fait dans amont/.
# On développe dans amont/cicero et amont/webdiplomacy (arbres complets, testables),
# puis ce script régénère les patchs. Les fichiers NOUVEAUX ne sont pas devinés :
# les copier à la main dans cicero/overlay ou webdiplomacy/overlay.
#
# Usage : outils/exporter_patchs.sh            (régénère les patchs)
#         outils/exporter_patchs.sh --verifier (échoue si un patch n'est pas à jour ; pour la CI locale)
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
C="$RACINE/amont/cicero"; W="$RACINE/amont/webdiplomacy"
P="$C/thirdparty/github/fairinternal/postman/third_party"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/c" "$TMP/w"
# La forme d'un diff dépend de la configuration git de l'utilisateur : on la fixe.
DIFF="git -c diff.noprefix=false -c diff.mnemonicPrefix=false -c core.abbrev=auto -c color.ui=false --no-pager"

$DIFF -C "$C" diff --no-ext-diff --ignore-submodules=all            > "$TMP/c/0001-cicero.patch"
$DIFF -C "$P/pybind11" diff --no-ext-diff                           > "$TMP/c/0002-pybind11-cxx17.patch"
$DIFF -C "$P/grpc/third_party/googletest" diff --no-ext-diff        > "$TMP/c/0003-googletest-gcc11.patch"
$DIFF -C "$W" diff --no-ext-diff -- . ':!composer.lock'             > "$TMP/w/0001-webdiplomacy.patch"

if [ "${1:-}" = "--verifier" ]; then
  # Les fichiers nouveaux ne passent pas par les patchs : un overlay en retard sur amont/
  # serait écrasé par la prochaine exécution d'install.sh.
  for paire in "cicero:$C" "webdiplomacy:$W"; do
    o="$RACINE/${paire%%:*}/overlay"; a="${paire#*:}"
    (cd "$o" && find . -type f) | while read -r f; do
      cmp -s "$o/$f" "$a/$f" || { echo "Overlay en retard sur amont/ : ${paire%%:*}/overlay/${f#./}" >&2; exit 1; }
    done || exit 1
  done
  diff -r "$TMP/c" "$RACINE/cicero/patches" && diff -r "$TMP/w" "$RACINE/webdiplomacy/patches" \
    && echo "Patchs à jour." || { echo "Patchs périmés : relancer outils/exporter_patchs.sh" >&2; exit 1; }
else
  cp "$TMP"/c/*.patch "$RACINE/cicero/patches/"; cp "$TMP"/w/*.patch "$RACINE/webdiplomacy/patches/"
  echo "Patchs régénérés. Fichiers nouveaux éventuels (à copier dans overlay/) :"
  git -C "$C" status --porcelain | grep '^??' || true
  git -C "$W" status --porcelain | grep '^??' || true
fi
