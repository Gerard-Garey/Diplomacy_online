#!/usr/bin/env bash
# Démarre webDiplomacy puis les deux conteneurs Cicero (ordres + dialogue).
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$RACINE/amont/webdiplomacy"; C="$RACINE/amont/cicero"
[ -d "$W" ] && [ -d "$C" ] || { echo "Lancer d'abord ./install.sh" >&2; exit 1; }

# -p webdiplomacy : fixe le nom du réseau (webdiplomacy_default) que rejoint Cicero.
docker compose -p webdiplomacy --project-directory "$W" -f "$W/docker-compose.yml" --profile core --profile dev up -d

echo "Attente de l'initialisation de webDiplomacy (base créée au premier démarrage)…"
for _ in $(seq 1 120); do
  grep -q "READY" "$W/gamemaster-entrypoint.txt" 2>/dev/null && break; sleep 2
done
grep -q "READY" "$W/gamemaster-entrypoint.txt" 2>/dev/null || { echo "webDiplomacy n'est pas prêt : voir $W/gamemaster-entrypoint.txt" >&2; exit 1; }

# Redis n'est pas persistant : Cicero refuse de démarrer sans cette clé (base n°1).
docker exec webdiplomacy-redis redis-cli -n 1 set message_review_version 1 >/dev/null

docker compose --project-directory "$C" -f "$C/docker-compose.yml" --env-file "$RACINE/.env" up -d
echo "Prêt : http://localhost:43000 — ordres des bots : amont/cicero/check_orders.sh <gameID>"
