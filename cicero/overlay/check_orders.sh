#!/bin/bash
# Affiche les ordres actuellement en cache pour tous les bots d'une partie, pour la phase en cours.
# Le mapping bot -> countryID -> puissance est decouvert dynamiquement depuis le
# contexte stocke dans chaque checkpoint (il change d'une partie a l'autre, et le
# countryID doit etre exact : l'API rejette une requete si la cle ne correspond
# pas au countryID demande).
# Usage: ./check_orders.sh <gameID>

set -eo pipefail

GAME_ID="$1"
if [ -z "$GAME_ID" ]; then
  echo "Usage: ./check_orders.sh <gameID>" >&2
  exit 1
fi

docker exec cicero-orders bash -c "
cd /opt/cicero
python3 -c \"
import torch, os, glob
from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game, Context
from fairdiplomacy.data.build_dataset import COUNTRY_ID_TO_POWER_OR_ALL

GAME_ID = $GAME_ID

exp_dirs = sorted(glob.glob('/root/diplomacy_experiments/results/diplomacy/adhoc/*'))
exp_dir = exp_dirs[-1]
# Le nom des dossiers intermediaires derive d'un hash de la config : on cherche par motif.
def _ckpt(bot):
    found = glob.glob(exp_dir + '/**/checkpoints/*__' + bot + '.pt', recursive=True)
    return found[0] if found else ''
class _Base:
    format = staticmethod(_ckpt)
base = _Base()

# 1) Decouvrir, pour chaque bot, son (countryID, state) reel dans cette partie
# -- lu depuis le contexte stocke au moment ou ce bot a vraiment appele l'API,
# donc forcement exact (pas de supposition de notre part).
entries = []  # (bot, countryID, state)
for bot in ['bot1','bot2','bot3','bot4','bot5','bot6','bot7']:
    path = base.format(bot)
    if not os.path.exists(path):
        continue
    ckpt = torch.load(path, map_location='cpu')
    for c, d in ckpt['PLAYER_STATE_DICTS'].items():
        if c.gameID == GAME_ID:
            entries.append((bot, c.countryID, d['state']))

if not entries:
    print('Aucun checkpoint trouve pour la partie', GAME_ID, '(pas encore de calcul d ordres, ou mauvais gameID).')
    raise SystemExit(1)

# 2) Phase actuelle, via un des bots reellement dans cette partie (countryID exact requis).
bot0, country0, _ = entries[0]
ctx = Context(gameID=GAME_ID, countryID=country0, api_url='http://webserver/api.php', api_key=bot0)
status = get_status_json(ctx)
game = webdip_state_to_game(status)
phase = game.get_current_phase()
print('Phase actuelle:', phase)
print()

# 3) Ordres en cache pour chaque bot.
for bot, country_id, state in entries:
    power = COUNTRY_ID_TO_POWER_OR_ALL.get(country_id, f'countryID={country_id}')
    res = state._last_search_result.get((phase, phase))
    if res is None:
        print(power, '(', bot, '): pas encore de resultat en cache pour', phase)
        continue
    print('===', power, '(', bot, ') ===')
    for a, p in sorted(res.get_agent_policy()[power].items(), key=lambda x: -x[1]):
        print(f'  {p:.3f}', a)
\"
" 2>&1 | grep -v "libtinfo"
