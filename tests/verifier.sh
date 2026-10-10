#!/usr/bin/env bash
# Batterie statique : s'exécute partout (poste local, CI), sans amont/ ni GPU.
# Ne remplace pas la validation fonctionnelle, qui demande la pile démarrée
# (cicero/overlay/essais/, à lancer dans le conteneur cicero-dialogue).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Rien ici ne doit écrire de __pycache__ : un .pyc contient le chemin absolu du dépôt, que
# le contrôle « chemin personnel » retrouverait. Les scripts de tests/ s'en gardent
# eux-mêmes (sys.dont_write_bytecode) et sont lancés plus bas sans cette variable, pour
# que le contrôle du bytecode porte sur eux (#27).
export PYTHONDONTWRITEBYTECODE=1
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
# Un défaut connu y est un échec attendu (« expected failures ») ; un succès inattendu
# fait sortir unittest en erreur : la marque est alors à retirer du test.
for t in tests/test_etat_dialogue.py tests/test_promesses.py tests/test_bruit_valeurs.py tests/test_reference.py; do
  if sortie=$(env -u PYTHONDONTWRITEBYTECODE python3 "$t" 2>&1); then
    echo "$sortie" | tail -n 3
  else
    echo "$sortie"
    ko "$t (voir ci-dessus)"
  fi
done
# Lancé seul, comme le mainteneur le lance pour la colonne « avant » d'un tableau.
if ! sortie=$(env -u PYTHONDONTWRITEBYTECODE python3 tests/mesure_promesses.py 2>&1); then
  echo "$sortie"
  ko "tests/mesure_promesses.py ne s'exécute pas (voir ci-dessus)"
fi

# Jeu d'essai figé (ADR 0006, décision 3), contrôlé par script : emplacement unique (aucune table
# de recherche dans un .json ou .jsonl hors de tests/reference/), clés en liste blanche, aucune
# chaîne qui ne soit un ordre, une puissance, une phase ou un mot du format, plafond de 512 Kio.
# Passe sur un dossier absent ou vide. Avec lui, deux tests sur les seuls noms des fichiers du dépôt
# (ADR 0006, annotation, point D) : aucun fichier d'état d'une instance ni aucune de ses copies
# (nom de base qui contient current_plans, pseudo_commitments ou claude_dialogue_state, et .json),
# extensions en liste fermée
# (EXTENSIONS_ADMISES de tests/reference_jeu.py : une extension nouvelle s'y ajoute dans le commit
# qui introduit le fichier). Les contrôles de plus bas (chemin personnel, jeton,
# donnée d'exécution) s'appliquent aussi à ce dossier.
if sortie=$(env -u PYTHONDONTWRITEBYTECODE python3 tests/reference_jeu.py controler 2>&1); then
  echo "$sortie" | tail -n 1
else
  echo "$sortie"
  ko "tests/reference/, une table hors de ce dossier ou un nom de fichier non admis (voir ci-dessus ; ADR 0006)"
fi
# Couche D de la référence de non-régression (#31) : fonctions pures rejouées sur le jeu d'essai,
# comparées à l'identique à ses attendus. Ne compare rien, et le dit, tant que le jeu est vide.
# Une différence n'appelle pas une régénération : elle s'explique, ligne par ligne, ou se corrige.
if sortie=$(env -u PYTHONDONTWRITEBYTECODE python3 tests/reference_couche_d.py 2>&1); then
  echo "$sortie"
else
  echo "$sortie"
  ko "couche D de la référence de non-régression (voir ci-dessus)"
fi

# Un .pyc laissé dans un overlay par un script lancé à la main (python3 tests/..., sans la
# variable ci-dessus) y est un fichier local : aucun ne doit s'y trouver après les tests (#27).
if find cicero/overlay webdiplomacy/overlay \( -name __pycache__ -o -name '*.pyc' \) -print | grep . ; then
  ko "bytecode Python dans un overlay (voir ci-dessus) : le supprimer ; s'il revient, un script de tests/ ne pose pas sys.dont_write_bytecode avant de charger l'overlay"
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

if grep -rnE '/home/[A-Za-z0-9._-]+/' --exclude-dir=.git --exclude-dir=amont --exclude-dir=docs --exclude-dir=__pycache__ --exclude=verifier.sh . ; then
  ko "chemin personnel codé en dur (voir ci-dessus)"
fi
# .env est ignoré par git et contient le jeton par construction ; -l : ne jamais afficher un jeton.
if grep -rlE 'sk-ant-[A-Za-z0-9_-]{10,}|CLAUDE_CODE_OAUTH_TOKEN="?[A-Za-z0-9_-]{10,}' --exclude-dir=.git --exclude-dir=amont --exclude-dir=__pycache__ --exclude=.env . ; then
  ko "jeton versionné (voir ci-dessus)"
fi
if git ls-files | grep -E '\.(sql\.gz|sqlite|dump)$|claude_dialogue_state\.json|(^|/)config\.php$'; then
  ko "donnée d'exécution versionnée (base, état, configuration locale)"
fi

[ "$statut" = 0 ] && echo "Batterie statique : tout est conforme."
exit "$statut"
