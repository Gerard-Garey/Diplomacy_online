#!/usr/bin/env bash
###############################################################################
#  .claude/outils/fiches_jumelles.sh  --  fiches d'agents « -approfondi »
#
#  Genere, pour chaque role de ROLES, la fiche .claude/agents/<role>-approfondi.md
#  a partir de la fiche de base .claude/agents/<role>.md : meme corps, memes
#  outils, meme modele ; seuls changent le nom, la description, l'effort et
#  maxTurns. Politique : docs/agents/routage.md, § 2 ; decision : ADR 0001.
#
#  Usage :
#    bash .claude/outils/fiches_jumelles.sh             # (re)genere les fiches
#    bash .claude/outils/fiches_jumelles.sh --verifier  # controle (CI) : code 1
#        si une fiche differe de sa generation ou si une fiche de base est
#        mal formee
#  Toute autre option : usage, code 2 (aucune fiche n'est ecrite).
#  Les fiches generees ne se modifient jamais a la main : modifier la fiche de
#  base, puis relancer le script.
###############################################################################
set -euo pipefail

# A ADAPTER : roles dedoubles (un expert duplique s'ajoute ici), effort et
# plafond de tours des fiches de jugement.
ROLES="architect expert"
EFFORT_APPROFONDI="high"
TOURS_APPROFONDI="80"

racine="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
agents="$racine/.claude/agents"
mode="${1:-generer}"
case "$mode" in
  generer|--verifier) ;;
  *) echo "usage : $0 [--verifier]" >&2; exit 2 ;;
esac

# Champs admis dans une fiche de base : tout autre champ ne serait pas reporte
# dans la fiche -approfondi.
CHAMPS_ADMIS="name description tools model effort maxTurns"

# Valeur d'un champ du frontmatter (premiere occurrence, entre les deux ---)
champ() {
  awk -v c="$2" 'NR==1 && $0=="---" {f=1; next} f && $0=="---" {exit}
                 f && index($0, c ": ")==1 {print substr($0, length(c)+3); exit}' "$1"
}

# Corps : tout ce qui suit le second ---
corps() {
  awk 'n>=2 {print; next} $0=="---" {n++}' "$1"
}

# Fiche de base bien formee : champs admis seulement, effort et maxTurns
# presents, une seule mention « Fiche de routine » dans la description
# (le suffixe retire par generer).
controler_base() {
  local src="$agents/$1.md" c ok=0
  [ -f "$src" ] || { echo "::error file=.claude/agents/$1.md::fiche de base absente"; return 1; }
  for c in $(awk 'NR==1 && $0=="---" {f=1; next} f && $0=="---" {exit}
                  f && match($0, /^[A-Za-z_]+:/) {print substr($0, 1, RLENGTH-1)}' "$src"); do
    case " $CHAMPS_ADMIS " in *" $c "*) ;; *)
      echo "::error file=.claude/agents/$1.md::champ « $c » non reporte dans la fiche -approfondi (ajouter le champ a CHAMPS_ADMIS et a generer)"; ok=1 ;;
    esac
  done
  for c in effort maxTurns; do
    [ -n "$(champ "$src" "$c")" ] || { echo "::error file=.claude/agents/$1.md::champ $c absent"; ok=1; }
  done
  [ "$(champ "$src" description | grep -o 'Fiche de routine' | wc -l)" -eq 1 ] \
    || { echo "::error file=.claude/agents/$1.md::la description doit contenir une fois « Fiche de routine »"; ok=1; }
  return $ok
}

generer() {
  local role="$1" src="$agents/$1.md"
  [ -f "$src" ] || { echo "fiche de base absente : $src" >&2; return 1; }
  local desc outils modele
  desc="$(champ "$src" description)"
  desc="${desc%% Fiche de routine*}"
  outils="$(champ "$src" tools)"
  modele="$(champ "$src" model)"
  [ -n "$desc" ] && [ -n "$outils" ] && [ -n "$modele" ] \
    || { echo "frontmatter incomplet : $src" >&2; return 1; }
  printf -- '---\n'
  printf 'name: %s-approfondi\n' "$role"
  printf 'description: Variante approfondie de `%s` (mêmes consignes, effort %s, %s tours au plus), pour les missions de jugement de `docs/agents/routage.md` (§ 3) ; appelée avec le modèle Fable (paramètre model de l'"'"'appel) dans les seuls cas du § 4.1 ou sur accord du mainteneur ; pour la routine, invoquer `%s`. %s\n' \
    "$role" "$EFFORT_APPROFONDI" "$TOURS_APPROFONDI" "$role" "$desc"
  printf 'tools: %s\n' "$outils"
  printf 'model: %s\n' "$modele"
  printf 'effort: %s\n' "$EFFORT_APPROFONDI"
  printf 'maxTurns: %s\n' "$TOURS_APPROFONDI"
  printf -- '---\n'
  printf '<!-- Fiche générée par .claude/outils/fiches_jumelles.sh depuis %s.md : ne pas modifier à la main. -->\n' "$role"
  corps "$src"
}

statut=0
for role in $ROLES; do
  cible="$agents/$role-approfondi.md"
  if ! controler_base "$role"; then
    statut=1
    continue
  fi
  if [ "$mode" = "--verifier" ]; then
    if ! diff -q <(generer "$role") "$cible" >/dev/null 2>&1; then
      echo "::error file=.claude/agents/$role-approfondi.md::fiche absente ou differente de sa generation depuis $role.md (relancer bash .claude/outils/fiches_jumelles.sh)"
      statut=1
    fi
  else
    if generer "$role" > "$cible.tmp"; then
      mv "$cible.tmp" "$cible"
      echo "genere : .claude/agents/$role-approfondi.md"
    else
      rm -f "$cible.tmp"
      echo "::error file=.claude/agents/$role-approfondi.md::fiche non generee (fiche de base incomplete)"
      statut=1
    fi
  fi
done

# Fiche -approfondi orpheline (role retire de ROLES)
for f in "$agents"/*-approfondi.md; do
  [ -e "$f" ] || continue
  role="$(basename "$f" -approfondi.md)"
  case " $ROLES " in *" $role "*) ;; *)
    echo "::error file=.claude/agents/$(basename "$f")::fiche -approfondi sans role dans ROLES"; statut=1 ;;
  esac
done

[ "$mode" = "--verifier" ] && [ $statut -eq 0 ] && echo "Fiches -approfondi conformes a leur fiche de base."
exit $statut
