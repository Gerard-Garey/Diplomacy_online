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

git -C "$C" diff --ignore-submodules=all            > "$TMP/c/0001-cicero.patch"
git -C "$P/pybind11" diff                           > "$TMP/c/0002-pybind11-cxx17.patch"
git -C "$P/grpc/third_party/googletest" diff        > "$TMP/c/0003-googletest-gcc11.patch"
git -C "$W" diff -- . ':!composer.lock'             > "$TMP/w/0001-webdiplomacy.patch"

if [ "${1:-}" = "--verifier" ]; then
  diff -r "$TMP/c" "$RACINE/cicero/patches" && diff -r "$TMP/w" "$RACINE/webdiplomacy/patches" \
    && echo "Patchs à jour." || { echo "Patchs périmés : relancer outils/exporter_patchs.sh" >&2; exit 1; }
else
  cp "$TMP"/c/*.patch "$RACINE/cicero/patches/"; cp "$TMP"/w/*.patch "$RACINE/webdiplomacy/patches/"
  echo "Patchs régénérés. Fichiers nouveaux éventuels (à copier dans overlay/) :"
  git -C "$C" status --porcelain | grep '^??' || true
  git -C "$W" status --porcelain | grep '^??' || true
fi
