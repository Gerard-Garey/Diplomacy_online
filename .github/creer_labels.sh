#!/usr/bin/env bash
###############################################################################
#  .github/creer_labels.sh  --  cree ou met a jour les libelles d'issues
#
#  Usage : bash .github/creer_labels.sh OWNER/REPO
#  « Use this template » ne copie pas les libelles : a lancer une fois sur
#  chaque depot cree depuis le modele. Idempotent (--force met a jour).
#  Libelles de tri : docs/agents/triage-labels.md ; bug et enhancement :
#  modeles d'issue de .github/ISSUE_TEMPLATE/.
###############################################################################
set -euo pipefail
R="${1:?usage : bash .github/creer_labels.sh OWNER/REPO}"

while IFS='|' read -r nom couleur description; do
  gh label create "$nom" -R "$R" --color "$couleur" --description "$description" --force
done <<'LISTE'
needs-triage|FBCA04|Le mainteneur doit évaluer cette issue
needs-info|D876E3|En attente d'informations complémentaires
ready-for-agent|0E8A16|Entièrement spécifiée, prête pour un agent autonome
ready-for-human|1D76DB|Nécessite une implémentation humaine
wontfix|FFFFFF|Ne sera pas traitée
bug|D73A4A|Résultat faux, erreur, ou incohérence entre code et documentation
enhancement|A2EEEF|Nouvelle fonctionnalité ou amélioration
documentation|0075CA|Documentation seule
LISTE
