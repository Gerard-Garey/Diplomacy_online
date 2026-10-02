"""Offline check of the commitment-extraction prompt against real game-15 negotiations.

Rebuilds the authentic board state for each phase, pulls the real transcript from
the game's message history, and runs the same extract_commitments() the dialogue
bot uses. No game is touched; nothing is written to pseudo_commitments.json.
"""
import sys

sys.path.insert(0, "/opt/cicero")

from claude_dialogue_bot import extract_commitments
from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game, Context
from parlai_diplomacy.utils.game2seq.format_helpers.state import StateFlattener

# Each API key only sees its own power's messages (fog of war), so fetch the
# game separately per power we want a transcript for.
CASES = [
    ("F1910M", "FRANCE", "AUSTRIA", 2, "bot5"),
    ("S1905M", "GERMANY", "AUSTRIA", 4, "bot2"),
    ("F1904M", "RUSSIA", "AUSTRIA", 7, "bot3"),
]

for phase, power, other, country_id, api_key in CASES:
    ctx = Context(
        gameID=15, countryID=country_id, api_url="http://webserver/api.php", api_key=api_key
    )
    full_game = webdip_state_to_game(get_status_json(ctx))

    by_phase = {}
    for pd in full_game.get_all_phases():
        for msg in pd.messages.values():
            by_phase.setdefault(msg["phase"], []).append(msg)

    game = full_game.rolled_back_to_phase_start(phase)
    board = StateFlattener(version=2).flatten_state(game.get_state(), phase)

    convo = [
        m
        for m in sorted(by_phase.get(phase, []), key=lambda m: m["time_sent"])
        if {m["sender"], m["recipient"]} == {power, other}
    ]

    print("=" * 78)
    print(f"CASE  {phase}  {power} <-> {other}")
    print(f"units({power}) = {game.get_state()['units'].get(power)}")
    print("-" * 78)
    if not convo:
        print("  (no messages found for this pair/phase)\n")
        continue
    transcript = "\n".join(f"{m['sender']}: {m['message']}" for m in convo)
    print(transcript)
    print("-" * 78)
    try:
        orders = extract_commitments(power, other, board, phase, transcript)
        print(f"EXTRACTED -> {orders}")
    except Exception as e:
        print(f"EXTRACTION FAILED: {type(e).__name__}: {e}")

    # Legality check: exactly the filter apply_commitments_to_policy() applies.
    orderable = set(game.get_orderable_locations().get(power, []))
    all_possible = game.get_all_possible_orders()
    for o in orders:
        loc = o.split()[1] if len(o.split()) > 1 else "?"
        if loc not in orderable:
            verdict = f"REJECTED (no orderable unit at {loc})"
        elif o not in all_possible.get(loc, []):
            verdict = "REJECTED (not a legal order)"
        else:
            verdict = "ACCEPTED"
        print(f"   {o!r}: {verdict}")
    print()
