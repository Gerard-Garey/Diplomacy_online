#!/usr/bin/env bash
# Démarre webDiplomacy puis les deux conteneurs Cicero (ordres + dialogue).
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$RACINE/amont/webdiplomacy"; C="$RACINE/amont/cicero"
[ -d "$W" ] && [ -d "$C" ] || { echo "Lancer d'abord ./install.sh" >&2; exit 1; }

# Le journal d'initialisation d'un démarrage précédent ferait croire que le site est prêt.
docker ps --format '{{.Names}}' | grep -q '^webdiplomacy-php-fpm' || rm -f "$W/gamemaster-entrypoint.txt"

# -p webdiplomacy : fixe le nom du réseau (webdiplomacy_default) que rejoint Cicero.
docker compose -p webdiplomacy --project-directory "$W" -f "$W/docker-compose.yml" --profile core --profile dev up -d

echo "Attente de l'initialisation de webDiplomacy (base créée au premier démarrage)…"
for _ in $(seq 1 120); do
  grep -q "^READY" "$W/gamemaster-entrypoint.txt" 2>/dev/null && break; sleep 2
done
grep -q "^READY" "$W/gamemaster-entrypoint.txt" 2>/dev/null || { echo "webDiplomacy n'est pas prêt : voir $W/gamemaster-entrypoint.txt" >&2; exit 1; }

# « READY » ne dit rien de nginx, qui s'arrête si l'un de ses hôtes amont manque.
for _ in $(seq 1 30); do
  wget -q -O /dev/null http://localhost:43000/ 2>/dev/null && break; sleep 2
done
wget -q -O /dev/null http://localhost:43000/ || { echo "Le site ne répond pas sur http://localhost:43000 : voir « docker logs webdiplomacy-webserver-1 »" >&2; exit 1; }

# Après plus de 12 min d'arrêt, webDiplomacy suspend le traitement des parties jusqu'à
# une remise à zéro par un administrateur : c'est le cas à chaque redémarrage de la pile.
docker exec webdiplomacy-db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" webdiplomacy -e "UPDATE wD_Misc SET value=UNIX_TIMESTAMP() WHERE name=\"LastProcessTime\""'

# Redis n'est pas persistant : Cicero refuse de démarrer sans cette clé (base n°1).
docker exec webdiplomacy-redis redis-cli -n 1 set message_review_version 1 >/dev/null

docker compose --project-directory "$C" -f "$C/docker-compose.yml" --env-file "$RACINE/.env" up -d
echo "Prêt : http://localhost:43000 — ordres des bots : amont/cicero/check_orders.sh <gameID>"
