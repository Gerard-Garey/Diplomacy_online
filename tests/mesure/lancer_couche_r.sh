#!/usr/bin/env bash
# Enchaîne un lot de la couche R (#33) : la suite qu'imprime
# « capture_reference.py commandes GAMEID --couche-r », exécutée ligne à ligne, avec un
# journal par lancement, l'arrêt au premier échec, un décompte final, puis comparer.
#
#   bash tests/mesure/lancer_couche_r.sh GAMEID [options de « commandes … --couche-r »]
#   bash tests/mesure/lancer_couche_r.sh 3
#   bash tests/mesure/lancer_couche_r.sh 3 --repetees S1903M:FRANCE --dossier amont/couche-r-relance
#
# À la main, sur le poste, après annonce ; jamais en CI ni dans un workflow. Plusieurs
# heures de GPU : la durée estimée est en tête de campagne.log.
#
# Ce script n'arrête ni ne relance rien : si cicero-orders tourne (running, restarting,
# paused), il refuse ; l'arrêter est une décision de qui lance. Les trois lignes d'état
# de la suite (dont « docker stop ») ne sont donc pas exécutées.
#
# Journaux, dans <dossier du lot>/journaux : campagne.log (une ligne par lancement, la
# mémoire de la carte relevée avant chacun), lancement_NN.log, comparer.txt.
#
# Code de retour :
#   0, 1, 2  celui de « reference_couche_r.py comparer », rendu tel quel
#            (0 : pas de régression, 1 : régression, 2 : non concluant ou lot invalide) ;
#   3        refus avant tout lancement : rien n'est créé (les contrôles précèdent toute
#            écriture ; si la préparation échoue, le dossier que le script vient de créer
#            est supprimé ; si cette suppression échoue, le message dit qu'il reste) ;
#   4        un lancement en échec : arrêt immédiat, comparer n'est pas lancé ;
#   5        décompte final faux (fichiers de relevés, recherches) : comparer n'est pas lancé ;
#   6        comparer est sorti par un autre code que 0, 1 ou 2 (il n'a pas rendu de verdict) :
#            ce code est cité, la sortie est dans comparer.txt ;
#   129, 130, 143  interrompu (SIGHUP, SIGINT, SIGTERM) : la ligne « fin » le dit et nomme
#            l'étape en cours. Un signal adressé au script seul n'est traité qu'à la fin de
#            la commande en cours (bash) ; Ctrl-C atteint aussi le lancement.
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 3
LOG=""
ETAT="non relevé"
SIGNAL=""
EN_COURS=""
CREE=""

noter() { echo "$*" | tee -a "$LOG"; }

fin() {
  local code=$? ligne interruption=""
  if [ -n "$SIGNAL" ]; then
    interruption="interrompu (SIG$SIGNAL)${EN_COURS:+ pendant $EN_COURS} ; "
  fi
  ligne="fin $(date -Is) code=$code ; ${interruption}cicero-orders : état initial $ETAT, à restaurer à la main (ce script ne relance rien)"
  echo "$ligne"
  if [ -n "$LOG" ] && [ -f "$LOG" ]; then echo "$ligne" >> "$LOG"; fi
}
trap 'SIGNAL=HUP; exit 129' HUP
trap 'SIGNAL=INT; exit 130' INT
trap 'SIGNAL=TERM; exit 143' TERM
trap fin EXIT

# Code 3 : rien n'est créé. Le dossier du lot n'est supprimé que si ce script l'a créé (CREE).
refuser() {
  if [ -n "$CREE" ]; then
    if rm -rf -- "$CREE"; then
      echo "dossier $CREE supprimé (créé par ce script, préparation en échec)" >&2
    else
      echo "dossier $CREE NON supprimé, à retirer à la main (créé par ce script, préparation en échec, « rm -rf » en échec)" >&2
    fi
    CREE=""
    LOG=""
  fi
  echo "REFUS : $*" >&2
  exit 3
}

carte() {
  local memoire
  if ! command -v nvidia-smi > /dev/null 2>&1; then
    echo "carte : non relevée"
  elif memoire=$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null) \
      && [ -n "$memoire" ]; then
    echo "carte : $(echo "$memoire" | tr '\n' ';' | sed 's/;$//') (Mio utilisés, total)"
  else
    echo "carte : non relevée (nvidia-smi en échec)"
  fi
}

cd "$RACINE" || refuser "racine du dépôt inaccessible"
[ $# -ge 1 ] || refuser "usage : lancer_couche_r.sh GAMEID [options de « capture_reference.py commandes … --couche-r »]"
command -v docker > /dev/null 2>&1 || refuser "docker introuvable"

# 1. La suite, telle que capture_reference.py l'imprime : il valide les arguments (code 2, rien d'imprimé).
SUITE=$(python3 tests/mesure/capture_reference.py commandes "$@" --couche-r) \
  || refuser "capture_reference.py commandes a refusé les arguments"

# Une commande par ligne, les lignes de continuation jointes, les commentaires écartés.
COMMANDES=()
courante=""
while IFS= read -r ligne; do
  if [ -z "$courante" ] && [[ "$ligne" == '#'* || -z "$ligne" ]]; then continue; fi
  if [[ "$ligne" == *\\ ]]; then
    courante+="${ligne%\\}"
  else
    COMMANDES+=("$courante$ligne")
    courante=""
  fi
done <<< "$SUITE"
# Une dernière ligne terminée par « \ » n'a pas de suite : elle ne serait ni exécutée ni refusée.
[ -z "$courante" ] || refuser "ligne de la suite inachevée (terminée par « \ ») : $courante"

# Chaque commande est reconnue à sa forme entière, jamais à son seul début : une ligne qui n'est pas exactement
# une de celles que capture_reference.py imprime (la suite a changé) arrête tout avant d'écrire, rien n'est exécuté.
COMPOSANTE='[A-Za-z0-9_][A-Za-z0-9_.-]*'
[ "${#COMMANDES[@]}" -ge 1 ] && [[ "${COMMANDES[0]}" =~ ^mkdir\ (amont(/$COMPOSANTE)+)\ \&\&\  ]] \
  || refuser "dossier du lot introuvable dans la suite (attendu sous amont/) : ${COMMANDES[0]:-}"
D="${BASH_REMATCH[1]}"
# Pas dans un clone d'amont : outils/exporter_patchs.sh en parcourt les fichiers non suivis.
[[ ! "$D" =~ ^amont/(cicero|webdiplomacy)(/|$) ]] \
  || refuser "dossier du lot dans un clone d'amont (amont/cicero, amont/webdiplomacy) : $D"
D_RE="${D//./\\.}"
CREER="mkdir $D"
PREPARER=("mkdir $D/resultats" "cp tests/mesure/* $D/")
FORME_HISTORIQUE="^cp tests/reference/historique\\.json $D_RE/resultats/historique_([0-9]+)\\.json\$"
FORME_LANCEMENT='^docker run --rm --gpus all( --network [A-Za-z0-9][A-Za-z0-9_.-]*)? +'
FORME_LANCEMENT+='-v "\$PWD/'"$D_RE"':/mesure" -v "\$PWD/amont/cicero/models:/opt/cicero/models:ro" +'
FORME_LANCEMENT+='(-e WEBDIP_API_URL=http://webserver/api\.php -e CICERO_REDIS_IP=redis -e CICERO_REDIS_PORT=6379 +)?'
FORME_LANCEMENT+='cicero-webdip:latest +python /mesure/rejeu_moteur\.py ([0-9]+) [A-Z0-9]+ [A-Z]+ ([0-9]+) '
FORME_LANCEMENT+='--historique /mesure/resultats/historique_([0-9]+)\.json --score (sos|dss)( --minutes-de-phase [0-9]+)? '
FORME_LANCEMENT+='--engagements auto:prefere$'
FORME_COMPARER="^python3 tests/reference_couche_r\\.py comparer $D_RE/resultats --sortie $D_RE/couche_r\\.json( --positions( [A-Z0-9]+:[A-Z]+)+)?\$"

# Recherches attendues : par lancement, ses tirages, A + B (--engagements auto:prefere, la seule forme admise).
PARTIE=""
HISTORIQUE=""
LANCEMENTS=()
COMPARER=""
ATTENDUES=0
rang=0
for c in "${COMMANDES[@]}"; do
  rang=$((rang + 1))
  if [ "$rang" -eq 1 ]; then
    [ "$c" = "$CREER && ${PREPARER[0]} && ${PREPARER[1]}" ] || refuser "ligne de la suite non reconnue : $c"
  elif [[ "$c" =~ $FORME_HISTORIQUE ]]; then
    [ -z "$HISTORIQUE" ] || refuser "deux copies de l'historique dans la suite : $c"
    HISTORIQUE="$c"
    PARTIE="${BASH_REMATCH[1]}"
  elif [ "$c" = "ETAT=\$(docker inspect --format '{{.State.Status}}' cicero-orders 2>/dev/null) || ETAT=absent" ] \
      || [ "$c" = 'echo "cicero-orders : état initial $ETAT (à restaurer à la main, cette suite ne relance rien)"' ] \
      || [ "$c" = '[ "$ETAT" = absent ] || docker stop cicero-orders' ]; then
    :  # état : contrôlé plus bas, rien n'est arrêté
  elif [[ "$c" =~ $FORME_LANCEMENT ]]; then
    # --network et les variables de la pile vont ensemble ; la partie est celle de l'historique copié.
    [ -n "${BASH_REMATCH[1]}" ] && [ -n "${BASH_REMATCH[2]}" ] || [ -z "${BASH_REMATCH[1]}${BASH_REMATCH[2]}" ] \
      || refuser "lancement non reconnu : $c"
    [ -n "$PARTIE" ] && [ "${BASH_REMATCH[3]}" = "$PARTIE" ] && [ "${BASH_REMATCH[5]}" = "$PARTIE" ] \
      || refuser "lancement non reconnu (partie) : $c"
    [ -z "$COMPARER" ] || refuser "lancement après la comparaison : $c"
    LANCEMENTS+=("$c")
    ATTENDUES=$((ATTENDUES + 2 * 10#${BASH_REMATCH[4]}))
  elif [[ "$c" =~ $FORME_COMPARER ]]; then
    [ -z "$COMPARER" ] || refuser "deux comparaisons dans la suite : $c"
    COMPARER="$c"
  else
    refuser "ligne de la suite non reconnue : $c"
  fi
done
[ -n "$HISTORIQUE" ] || refuser "pas de copie de l'historique dans la suite"
[ "${#LANCEMENTS[@]}" -ge 1 ] || refuser "aucun lancement dans la suite"
[ -n "$COMPARER" ] || refuser "pas de comparaison dans la suite"

# 2. Contrôles, avant toute écriture.
[ ! -e "$D" ] || refuser "$D existe déjà : un lot se fait dans un dossier neuf (--dossier)"
[ -f tests/reference/historique.json ] || refuser "tests/reference/historique.json absent"
ETAT=$(docker inspect --format '{{.State.Status}}' cicero-orders 2>/dev/null) || ETAT=absent
case "$ETAT" in
  running | restarting | paused)
    refuser "cicero-orders est « $ETAT » : ce script n'arrête rien. L'arrêter à la main, après annonce (docker stop cicero-orders), puis relancer." ;;
esac
IMAGE=$(docker image inspect --format '{{.Id}}' cicero-webdip:latest 2>/dev/null) \
  || refuser "image cicero-webdip:latest absente, ou Docker ne répond pas"
# Ce qui ferait échouer la préparation à mi-chemin : « cp tests/mesure/* » sort en erreur sur un dossier.
for f in tests/mesure/*; do
  [ -f "$f" ] || refuser "$f n'est pas un fichier ordinaire : « cp tests/mesure/* » échouerait, le retirer de tests/mesure"
done

# 3. Préparation du dossier du lot : la première ligne de la suite, membre à membre (le dossier créé par ce
#    script, et lui seul, est supprimé si la suite de la préparation échoue), puis la copie de l'historique.
EN_COURS="la préparation de $D"
bash -c "$CREER" || refuser "préparation en échec : $CREER"
CREE="$D"
JOURNAUX="$D/journaux"
for c in "${PREPARER[@]}" "$HISTORIQUE" "mkdir $JOURNAUX"; do
  bash -c "$c" || refuser "préparation en échec : $c"
done
CREE=""
LOG="$JOURNAUX/campagne.log"
noter "début $(date -Is) tête $(git rev-parse HEAD 2>/dev/null || echo inconnue) image $IMAGE"
noter "cicero-orders : état initial $ETAT (à restaurer à la main, ce script n'arrête ni ne relance rien)"
printf '%s\n' "$SUITE" | grep -m1 'durée estimée' | tee -a "$LOG"

# 4. Lancements : un journal chacun, arrêt au premier échec.
total=${#LANCEMENTS[@]}
n=0
for c in "${LANCEMENTS[@]}"; do
  n=$((n + 1))
  journal=$(printf '%s/lancement_%02d.log' "$JOURNAUX" "$n")
  cible=$(echo "$c" | grep -o 'rejeu_moteur\.py [0-9]* [A-Z0-9]* [A-Z]*')
  noter "$n/$total $cible : $(carte)"
  EN_COURS="le lancement $n/$total $cible"
  debut=$(date +%s)
  bash -c "$c" > "$journal" 2>&1
  code=$?
  noter "$n/$total $cible code=$code durée=$(($(date +%s) - debut))s $(date -Is)"
  EN_COURS=""
  if [ "$code" -ne 0 ]; then
    noter "ARRÊT : lancement $n en échec (code $code), voir $journal ; comparer n'est pas lancé"
    exit 4
  fi
done

# 5. Décompte final : un fichier de relevés par lancement, une ligne par recherche.
fichiers=0
recherches=0
for f in "$D"/resultats/m1_*.jsonl; do
  [ -f "$f" ] || continue
  fichiers=$((fichiers + 1))
  recherches=$((recherches + $(grep -c '' "$f")))
done
noter "décompte : $fichiers fichier(s) de relevés pour $total lancement(s), $recherches recherche(s) pour $ATTENDUES attendue(s)"
if [ "$fichiers" -ne "$total" ] || [ "$recherches" -ne "$ATTENDUES" ]; then
  noter "ARRÊT : décompte faux ; comparer n'est pas lancé"
  exit 5
fi

# 6. Comparaison au résumé de la référence : son code (0, 1, 2) est celui du script ; un autre n'est pas un verdict.
EN_COURS="la comparaison"
bash -c "$COMPARER" > "$JOURNAUX/comparer.txt" 2>&1
code=$?
EN_COURS=""
noter "comparer code=$code $(date -Is), voir $JOURNAUX/comparer.txt"
tail -30 "$JOURNAUX/comparer.txt"
case "$code" in
  0 | 1 | 2) exit "$code" ;;
esac
noter "ARRÊT : comparer est sorti en code $code, qui n'est pas un verdict (0, 1, 2) ; voir $JOURNAUX/comparer.txt"
exit 6
