#!/usr/bin/env bash
# Installation clef en main : clone les deux amonts aux commits épinglés, applique
# les patchs et fichiers de ce dépôt, télécharge les poids de modèle nécessaires
# et construit l'image Cicero. Relançable : chaque étape déjà faite est sautée.
#
# Usage : ./install.sh [--sans-build] [--sans-modeles]
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RACINE"
# shellcheck source=versions.env
source versions.env
AMONT="$RACINE/amont"
BUILD=1; MODELES_DL=1
for a in "$@"; do case "$a" in
  --sans-build) BUILD=0 ;; --sans-modeles) MODELES_DL=0 ;;
  *) echo "Option inconnue : $a" >&2; exit 2 ;; esac; done

etape() { printf '\n== %s ==\n' "$*"; }
echec() { echo "ERREUR : $*" >&2; exit 1; }

etape "Prérequis"
for c in git docker wget gpg; do command -v "$c" >/dev/null || echec "commande manquante : $c"; done
docker compose version >/dev/null 2>&1 || echec "plugin « docker compose » manquant"
docker info >/dev/null 2>&1 || echec "le démon Docker ne répond pas (droits ? service démarré ?)"
if ! docker run --rm --gpus all ubuntu:26.04 nvidia-smi >/dev/null 2>&1; then
  echec "Docker n'accède pas au GPU NVIDIA. Installer le pilote et nvidia-container-toolkit, puis vérifier : docker run --rm --gpus all ubuntu:26.04 nvidia-smi"
fi
echo "ok"

etape "Fichier .env"
if [ ! -f .env ]; then cp env.exemple .env; echo "Créé depuis env.exemple."; fi
grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.\+' .env || echo "ATTENTION : CLAUDE_CODE_OAUTH_TOKEN est vide dans .env — les bots joueront mais ne répondront pas aux messages."

cloner() { # nom dépôt commit [recursif]
  local dir="$AMONT/$1"
  [ -d "$dir/.git" ] || git clone "$2" "$dir"
  # Hors du test ci-dessus : un clonage interrompu se reprend à la relance.
  [ "$(git -C "$dir" rev-parse HEAD)" = "$3" ] || git -C "$dir" checkout --quiet "$3"
  if [ "${4:-}" = recursif ]; then git -C "$dir" submodule update --init --recursive; fi
  [ "$(git -C "$dir" rev-parse HEAD)" = "$3" ] || echec "$dir n'est pas au commit épinglé $3"
}
appliquer() { # dossier-git patch
  # Dans un sous-module resté vide, git applique « avec succès » un patch dont il ignore tous les chemins.
  [ "$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)" = "$(cd "$1" && pwd -P)" ] || echec "$1 n'est pas la racine d'un dépôt git (clonage incomplet ?)"
  if git -C "$1" apply --reverse --check "$2" 2>/dev/null; then echo "déjà appliqué : $(basename "$2")"
  else git -C "$1" apply --check "$2" || echec "le patch $(basename "$2") ne s'applique pas sur $1"
       git -C "$1" apply "$2"; echo "appliqué : $(basename "$2")"; fi
}

etape "Amont Cicero ($CICERO_COMMIT)"
mkdir -p "$AMONT"
cloner cicero "$CICERO_DEPOT" "$CICERO_COMMIT" recursif
C="$AMONT/cicero"; P="$C/thirdparty/github/fairinternal/postman/third_party"
appliquer "$C" "$RACINE/cicero/patches/0001-cicero.patch"
appliquer "$P/pybind11" "$RACINE/cicero/patches/0002-pybind11-cxx17.patch"
appliquer "$P/grpc/third_party/googletest" "$RACINE/cicero/patches/0003-googletest-gcc11.patch"
cp -a "$RACINE/cicero/overlay/." "$C/"
chmod +x "$C/docker-entrypoint.sh" "$C/check_orders.sh"
mkdir -p "$C/webdip_logs_test" "$C/journaux_moteur"

etape "Amont webDiplomacy ($WEBDIP_COMMIT)"
cloner webdiplomacy "$WEBDIP_DEPOT" "$WEBDIP_COMMIT"
W="$AMONT/webdiplomacy"
appliquer "$W" "$RACINE/webdiplomacy/patches/0001-webdiplomacy.patch"
cp -a "$RACINE/webdiplomacy/overlay/." "$W/"
if [ ! -f "$W/config.php" ]; then
  # Secret du gamemaster : valeur de développement local, la même que dans
  # install/gamemaster-entrypoint.sh patché. Les ports ne sont publiés que sur 127.0.0.1.
  sed -e "s|\$gameMasterSecret='';|\$gameMasterSecret='local-gamemaster-dev-secret';|" \
      -e "s|\$botsLogFile=false;|\$botsLogFile='/tmp/webdip-bots.log';|" \
      "$W/config.sample.php" > "$W/config.php"
  grep -q "local-gamemaster-dev-secret" "$W/config.php" || echec "config.sample.php a changé : secret gamemaster non posé"
  echo "config.php créé"
fi
# Ignoré par l'amont, donc absent d'un clone neuf ; PHP (www-data) ne peut pas le créer
# dans un arbre qui appartient à l'utilisateur, et la création de partie échoue sans lui.
mkdir -p "$W/cache" && chmod a+rwx "$W/cache"
if [ ! -d "$W/vendor" ]; then
  docker run --rm -u "$(id -u):$(id -g)" -v "$W:/app" -w /app composer:2 install --no-interaction --ignore-platform-reqs
fi
if [ ! -d "$W/sse-server/node_modules" ]; then
  # Sans le serveur SSE, nginx ne résout pas l'hôte « sse » et le site ne démarre pas.
  # Versions figées par le package-lock.json de webdiplomacy/overlay.
  docker run --rm -u "$(id -u):$(id -g)" -e npm_config_cache=/tmp/.npm -v "$W/sse-server:/app" -w /app \
    node:16.15.1-alpine3.14 npm ci --no-audit --no-fund
fi
if [ ! -f "$W/beta/index.html" ]; then
  # Interface cliquable (React) : c'est celle qu'ouvre par défaut un compte neuf.
  # --ignore-scripts : le script « prepare » d'amont installerait des hooks git dans amont/.
  # Mémoire bridée, sans cartes de source : la compilation est gourmande.
  docker run --rm --memory=4g -u "$(id -u):$(id -g)" -e npm_config_cache=/tmp/.npm \
    -e GENERATE_SOURCEMAP=false -e CI=false -e NODE_OPTIONS=--max-old-space-size=3072 \
    -v "$W:/app" -w /app/beta-src node:20-alpine \
    sh -c 'npm ci --ignore-scripts --no-audit --no-fund && npm run build'
  [ -f "$W/beta/index.html" ] || echec "l'interface cliquable n'a pas été construite"
  rm -rf "$W/beta-src/node_modules"   # ~640 Mo, inutiles une fois beta/ construit
fi

if [ "$MODELES_DL" = 1 ]; then
  etape "Poids de modèle (sélection utile, quelques Go)"
  MDP="$(grep -oP 'model files is the following: `\K[^`]+' "$C/README.md")" || echec "mot de passe des modèles introuvable dans le README d'amont"
  mkdir -p "$C/models" "$C/models_encrypted"
  for f in $MODELES; do
    [ -s "$C/models/$f" ] && { echo "présent : $f"; continue; }
    wget -c "https://dl.fbaipublicfiles.com/diplomacy_cicero/models/$f.gpg" -O "$C/models_encrypted/$f.gpg"
    # Vers un nom provisoire : un déchiffrement interrompu laisse un fichier partiel,
    # que la relance prendrait pour un modèle présent.
    gpg --batch --yes --passphrase "$MDP" --output "$C/models/$f.partiel" -d "$C/models_encrypted/$f.gpg"
    mv "$C/models/$f.partiel" "$C/models/$f"
    rm -f "$C/models_encrypted/$f.gpg"
  done
fi

if [ "$BUILD" = 1 ]; then
  etape "Image Docker Cicero (compilation C++ en -j1 : compter 20 à 30 min)"
  docker build -t cicero-webdip:latest "$C"
fi

etape "Terminé"
echo "Démarrer : ./demarrer.sh    — site : http://localhost:43000"
