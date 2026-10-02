#!/usr/bin/env bash
# Arrête Cicero puis webDiplomacy. Les données (base, parties) sont conservées.
set -euo pipefail
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$RACINE/amont/webdiplomacy"; C="$RACINE/amont/cicero"
docker compose --project-directory "$C" -f "$C/docker-compose.yml" --env-file "$RACINE/.env" down
docker compose -p webdiplomacy --project-directory "$W" -f "$W/docker-compose.yml" --profile core --profile dev down
