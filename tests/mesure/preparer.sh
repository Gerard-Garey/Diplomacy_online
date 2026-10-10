#!/bin/bash
# Prépare les deux versions comparées par M2 et M3 (à lancer sur le poste, depuis n'importe où).
#   bash amont/mesure/preparer.sh             extrait avant/ (commit 7b7ce70) et apres/ (arbre de travail)
#   bash amont/mesure/preparer.sh --dialogue  en plus : copie le dossier de mesure dans le conteneur
#                                             cicero-dialogue (/mesure, et /tmp/mesure/{avant,apres})
#   bash amont/mesure/preparer.sh --rapatrier ramène /mesure/resultats du conteneur cicero-dialogue
# N'écrit que dans amont/mesure (et, avec --dialogue, dans /mesure et /tmp/mesure du conteneur).
set -euo pipefail

MESURE="$(cd "$(dirname "$0")" && pwd)"
DEPOT="$(cd "$MESURE/../.." && pwd)"
AVANT_SHA=7b7ce70
FICHIERS=(
  "cicero/overlay/claude_dialogue_bot.py"
  "cicero/overlay/fairdiplomacy/utils/pseudo_commitments.py"
  "cicero/overlay/fairdiplomacy/utils/plan_export.py"
)

if [ "${1:-}" = "--rapatrier" ]; then
  docker cp cicero-dialogue:/mesure/resultats/. "$MESURE/resultats/"
  ls -l "$MESURE/resultats/"
  exit 0
fi

mkdir -p "$MESURE/avant" "$MESURE/apres" "$MESURE/resultats" "$MESURE/travail"
for f in "${FICHIERS[@]}"; do
  git -C "$DEPOT" show "$AVANT_SHA:$f" > "$MESURE/avant/$(basename "$f")"
  cp "$DEPOT/$f" "$MESURE/apres/$(basename "$f")"
done
{
  echo "avant : git show $AVANT_SHA ; apres : arbre de travail (HEAD $(git -C "$DEPOT" rev-parse --short HEAD), $(date -Iseconds))"
  (cd "$MESURE" && sha256sum avant/*.py apres/*.py)
} | tee "$MESURE/versions.txt"

if [ "${1:-}" = "--dialogue" ]; then
  docker exec cicero-dialogue mkdir -p /mesure /tmp/mesure
  # Le compteur d'appels déjà présent dans le conteneur ne doit pas être écrasé par une copie plus ancienne.
  if docker exec cicero-dialogue test -f /mesure/resultats/m3_compteur_appels.json; then
    docker cp cicero-dialogue:/mesure/resultats/. "$MESURE/resultats/"
  fi
  docker cp "$MESURE/." cicero-dialogue:/mesure/
  docker cp "$MESURE/avant" cicero-dialogue:/tmp/mesure/
  docker cp "$MESURE/apres" cicero-dialogue:/tmp/mesure/
  docker exec cicero-dialogue sh -c 'ls /mesure /tmp/mesure/avant /tmp/mesure/apres; claude --version'
fi
