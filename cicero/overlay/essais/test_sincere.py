"""Live check of the sincere-commitment channel.

Calls Claude for real, with an exported plan in the prompt, on a genuine
game-15 board state. Verifies that: the reply/sincere JSON contract holds, that
sincere orders come from the plan, and that a bluff-inviting prompt does not
leak into the sincere list.
"""
import sys

sys.path.insert(0, "/opt/cicero")

import claude_dialogue_bot as bot
from fairdiplomacy.utils.plan_export import export_plans
from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game, Context
from parlai_diplomacy.utils.game2seq.format_helpers.state import StateFlattener

PHASE = "F1910M"
POWER = "GERMANY"

ctx = Context(gameID=15, countryID=4, api_url="http://webserver/api.php", api_key="bot2")
game = webdip_state_to_game(get_status_json(ctx)).rolled_back_to_phase_start(PHASE)
board = StateFlattener(version=2).flatten_state(game.get_state(), PHASE)

# Germany's real F1910M orders, plus plausible near-optimal variants, shaped
# like compute_best_action_against_reweighted_opponent_joint_actions output.
attack = ("A SIL - WAR", "A PRU S A SIL - WAR", "A LVN S A SIL - WAR", "A MUN H")
hold = ("A SIL H", "A PRU S A SIL", "A LVN S A SIL", "A MUN H")
west = ("A SIL - WAR", "A PRU S A SIL - WAR", "A LVN H", "A MUN - BOH")
export_plans("15", PHASE, POWER, [
    (attack, 0.5120, 0.34, 0.4900),
    (hold, 0.5085, 0.19, 0.4700),   # cost 0.0035 -> a cheap concession
    (west, 0.4400, 0.07, 0.4100),   # cost 0.072  -> expensive
])

plan_section = bot.build_plan_section(15, PHASE, POWER)
print("=" * 78)
print("PLAN SECTION GIVEN TO CLAUDE")
print("=" * 78)
print(plan_section)

SCENARIOS = [
    ("Austria asks for the cheap concession (Silesia hold)",
     "Ecoute, je vois bien tes armees massees en Silesie. Si tu jures de ne pas "
     "attaquer Varsovie ce tour, je te laisse le nord tranquille. Tu t'engages ?"),
    ("Austria asks for the expensive one (give up Warsaw push AND move on Bohemia)",
     "Je veux que tu abandonnes completement Varsovie et que tu envoies Mun vers "
     "Boh pour me le prouver. Sinon c'est la guerre entre nous."),
]

for title, message in SCENARIOS:
    print("=" * 78)
    print("SCENARIO:", title)
    print("AUSTRIA:", message)
    print("-" * 78)
    reply, sincere = bot.generate_reply(
        POWER, "AUSTRIA", board, PHASE, message, plan_section=plan_section, trust_section=""
    )
    print("REPLY  :", reply)
    print("SINCERE:", sincere)

    plan_orders = {o for p in (attack, hold, west) for o in p}
    for o in sincere:
        status = "in plan" if o in plan_orders else "NOT IN PLAN -> would be dropped"
        print(f"   {o!r}: {status}")
    print()
