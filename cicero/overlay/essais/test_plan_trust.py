"""End-to-end check of plan export -> prompt grounding -> trust ledger.

Uses real game-15 data. Does not touch any live game or call Claude.
"""
import sys

sys.path.insert(0, "/opt/cicero")

import claude_dialogue_bot as bot
from fairdiplomacy.utils.plan_export import export_plans, load_plans
from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game, Context

print("=" * 78)
print("1) export_plans / load_plans round-trip")
print("=" * 78)
# Shaped exactly like compute_best_action_against_reweighted_opponent_joint_actions
# returns: (action, value, bp_prob, pice_value), sorted best-first.
action_values = [
    (("A SIL - WAR", "A PRU S A SIL - WAR"), 0.4210, 0.31, 0.4098),
    (("A SIL H", "A PRU S A SIL"), 0.4185, 0.22, 0.4020),
    (("A SIL - BOH", "A PRU H"), 0.3600, 0.08, 0.3320),
]
export_plans("15", "F1910M", "GERMANY", action_values)
print("loaded:", load_plans("15", "F1910M", "GERMANY"))

print()
print("=" * 78)
print("2) plan section injected into the system prompt")
print("=" * 78)
plan_section = bot.build_plan_section(15, "F1910M", "GERMANY")
print(plan_section)

print("=" * 78)
print("3) trust ledger against the REAL France broken promise (F1910M)")
print("=" * 78)
# France really did promise "A BUR S A TYR - MUN" and play "A BUR - BEL".
# bot2 == GERMANY == countryID 4; resolved orders of every power are public.
ctx = Context(gameID=15, countryID=4, api_url="http://webserver/api.php", api_key="bot2")
game = webdip_state_to_game(get_status_json(ctx))

bot_state = {
    "pending_promises": {
        # kept: Russia really did hold Moscow
        "F1910M:RUSSIA": ["A MOS H"],
        # broken: France promised support on Munich, played BUR->BEL
        "F1910M:FRANCE": ["A BUR S A TYR - MUN"],
        # hallucinated: no such unit -> must NOT count against them
        "F1910M:ENGLAND": ["A PAR - BUR"],
    }
}
trust = bot.verify_promises(game, 15, "AUSTRIA", bot_state)
print("trust ledger:", trust)
print("leftover pending (unresolved):", bot_state["pending_promises"])
print()
for cp in ("FRANCE", "RUSSIA", "ENGLAND"):
    section = bot.build_trust_section(trust, cp)
    print(f"--- trust section for {cp} ---")
    print(section if section else "(empty -- nothing recorded)\n")

print("=" * 78)
print("4) coast-notation leniency (must NOT be scored as a broken promise)")
print("=" * 78)
st2 = {"pending_promises": {"F1910M:FRANCE": ["F SPA S F NAF - MAO"]}}  # real order: F SPA/SC S ...
t2 = bot.verify_promises(game, 15, "AUSTRIA", st2)
print("FRANCE record:", t2.get("FRANCE"))
