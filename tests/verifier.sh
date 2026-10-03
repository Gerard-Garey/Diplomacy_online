#!/usr/bin/env bash
# Batterie statique : s'exécute partout (poste local, CI), sans amont/ ni GPU.
# Ne remplace pas la validation fonctionnelle, qui demande la pile démarrée
# (cicero/overlay/essais/, à lancer dans le conteneur cicero-dialogue).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
statut=0
ko() { echo "ÉCHEC : $*"; statut=1; }

for f in install.sh demarrer.sh arreter.sh outils/*.sh tests/*.sh cicero/overlay/*.sh webdiplomacy/overlay/**/*.sh; do
  [ -f "$f" ] || continue
  bash -n "$f" || ko "syntaxe shell : $f"
done

while IFS= read -r f; do
  python3 - "$f" <<'PY' || ko "syntaxe Python : $f"
import ast, sys
ast.parse(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1])
PY
done < <(find cicero/overlay webdiplomacy/overlay tests -name '*.py')

# Tests par appel direct, sans amont/ ni conteneur (modules de Cicero remplacés par des doublures).
# En cas d'échec, la sortie entière est affichée : elle nomme les tests en cause.
if sortie=$(python3 tests/test_etat_dialogue.py 2>&1); then
  echo "$sortie" | tail -n 3
else
  echo "$sortie"
  ko "tests/test_etat_dialogue.py (voir ci-dessus)"
fi

for p in cicero/patches/*.patch webdiplomacy/patches/*.patch; do
  [ -s "$p" ] || ko "patch vide : $p"
  grep -q '^diff --git ' "$p" || ko "patch mal formé : $p"
done

# shellcheck source=../versions.env
source versions.env
for v in CICERO_COMMIT WEBDIP_COMMIT; do
  [[ "${!v}" =~ ^[0-9a-f]{40}$ ]] || ko "$v n'est pas un SHA complet"
done
[ -n "${MODELES:-}" ] || ko "MODELES vide dans versions.env"

if grep -rnE '/home/[A-Za-z0-9._-]+/' --exclude-dir=.git --exclude-dir=amont --exclude-dir=docs --exclude=verifier.sh . ; then
  ko "chemin personnel codé en dur (voir ci-dessus)"
fi
# .env est ignoré par git et contient le jeton par construction ; -l : ne jamais afficher un jeton.
if grep -rlE 'sk-ant-[A-Za-z0-9_-]{10,}|CLAUDE_CODE_OAUTH_TOKEN="?[A-Za-z0-9_-]{10,}' --exclude-dir=.git --exclude-dir=amont --exclude=.env . ; then
  ko "jeton versionné (voir ci-dessus)"
fi
if git ls-files | grep -E '\.(sql\.gz|sqlite|dump)$|claude_dialogue_state\.json|(^|/)config\.php$'; then
  ko "donnée d'exécution versionnée (base, état, configuration locale)"
fi

[ "$statut" = 0 ] && echo "Batterie statique : tout est conforme."
exit "$statut"
