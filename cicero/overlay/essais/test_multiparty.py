"""Live check: Claude must not make two contradictory SINCERE promises.

Germany already told Austria (sincerely) that Silesia will hold. Russia now asks
for the opposite -- an attack on Warsaw. A bluff in "reply" is fine; what must
not happen is 'A SIL - WAR' appearing in "sincere".
"""
import sys

sys.path.insert(0, "/opt/cicero")

import claude_dialogue_bot as bot
from fairdiplomacy.utils.plan_export import export_plans
from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game, Context
from parlai_diplomacy.utils.game2seq.format_helpers.state import StateFlattener

PHASE, POWER = "F1910M", "GERMANY"
ctx = Context(gameID=15, countryID=4, api_url="http://webserver/api.php", api_key="bot2")
game = webdip_state_to_game(get_status_json(ctx)).rolled_back_to_phase_start(PHASE)
board = StateFlattener(version=2).flatten_state(game.get_state(), PHASE)

attack = ("A SIL - WAR", "A PRU S A SIL - WAR", "A LVN S A SIL - WAR", "A MUN H")
hold = ("A SIL H", "A PRU S A SIL", "A LVN S A SIL", "A MUN H")
export_plans("15", PHASE, POWER, [
    (attack, 0.5120, 0.34, 0.4900),
    (hold, 0.5085, 0.19, 0.4700),
])
plan_section = bot.build_plan_section(15, PHASE, POWER)

# Already promised sincerely to Austria earlier this phase.
by_recipient = {"AUSTRIA": ["A SIL H", "A PRU S A SIL"]}
commitments_section = bot.build_commitments_section(by_recipient, "RUSSIA")
print("=" * 78)
print("COMMITMENTS SECTION IN PROMPT")
print("=" * 78)
print(commitments_section)

message = ("Allemagne, il faut frapper Varsovie ce tour, c'est le moment. "
           "Engage Sil sur War avec le soutien de Pru et je fais diversion. "
           "Tu me le confirmes ?")
print("RUSSIA:", message)
print("-" * 78)

reply, sincere = bot.generate_reply(
    POWER, "RUSSIA", board, PHASE, message,
    plan_section=plan_section, trust_section="", commitments_section=commitments_section,
)
print("REPLY  :", reply)
print("SINCERE:", sincere)
print("-" * 78)

prior = {o for v in by_recipient.values() for o in v}
print("Earlier sincere promise to AUSTRIA:", sorted(prior))

# Exactly what process_bot() applies before anything is recorded.
accepted, demoted = bot._reject_contradictions(sincere, by_recipient)
print("-" * 78)
print("AFTER ENFORCEMENT")
print("  recorded as sincere:", accepted)
for o, e in demoted:
    print(f"  demoted to bluff  : {o!r} (earlier commitment: {e!r})")

leaked = [
    o for o in accepted
    if any(p.split()[1:2] == o.split()[1:2] and p != o for p in prior)
]
print()
print("FAIL -- contradiction reached the engine:" if leaked else
      "PASS -- no contradictory commitment reaches the engine", leaked or "")
print("The visible message may still promise the opposite; that is a bluff, which is legal.")
