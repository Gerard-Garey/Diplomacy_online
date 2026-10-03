#
# Exports each bot's current piKL plan (its best action plus the near-optimal
# runner-ups) to a JSON file on the volume shared with the cicero-dialogue
# container, so the dialogue LLM can negotiate from the plan the search actually
# produced instead of inventing intentions.
#
# This is the direction real CICERO works in: planning -> intents -> dialogue.
# The runner-ups matter as much as the best action: they are what makes a
# negotiated change of plan possible and honest. If the counterpart asks for
# something that happens to be plan #3 at a cost of 0.01, the bot can agree
# knowing it gives up almost nothing.
#
# Written atomically (temp + os.replace) because cicero-dialogue reads this file
# on its own poll cycle while cicero-orders is writing it.
#
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fairdiplomacy.typedefs import Action, Power

DEFAULT_PLANS_FILE = (
    Path(__file__).resolve().parents[2] / "webdip_logs_test" / "current_plans.json"
)
PLANS_FILE = Path(os.environ.get("CICERO_PLANS_FILE", str(DEFAULT_PLANS_FILE)))

# How many candidate actions to expose. Enough to negotiate around, few enough
# that the dialogue prompt stays small and the bot can't dump its whole search.
TOP_K = 6


def export_plans(
    game_id: str,
    phase: str,
    power: Power,
    action_values: List[Tuple[Action, float, float, float]],
    top_k: int = TOP_K,
) -> None:
    """Write `power`'s ranked candidate plans for (game_id, phase).

    action_values is the list returned by
    compute_best_action_against_reweighted_opponent_joint_actions: tuples of
    (action, value, bp_prob, pice_value), already sorted best-first.

    `cost` is the value given up relative to the best action, which is the
    number that actually matters when deciding whether a concession is cheap.
    Never raises: a failure here must not take down order computation.
    """
    if not game_id or not action_values:
        return
    try:
        best_value = action_values[0][1]
        plans = [
            {
                "rank": i + 1,
                "orders": list(action),
                "value": round(float(value), 5),
                "cost_vs_best": round(float(best_value - value), 5),
            }
            for i, (action, value, _prob, _pice) in enumerate(action_values[:top_k])
        ]

        data: Dict[str, Any] = {}
        if PLANS_FILE.exists():
            try:
                data = json.loads(PLANS_FILE.read_text())
            except json.JSONDecodeError:
                data = {}

        data.setdefault(str(game_id), {}).setdefault(phase, {})[power] = {
            "computed_at": int(time.time()),
            "plans": plans,
        }

        PLANS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PLANS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, PLANS_FILE)
        logging.info(
            f"plan_export: wrote {len(plans)} candidate plans for {power} {phase} (game {game_id})"
        )
    except Exception as e:
        logging.warning(f"plan_export: failed to export plans for {power}: {e}")


def load_plans(game_id: str, phase: str, power: Power) -> Optional[Dict[str, Any]]:
    """Read back `power`'s exported plans, or None if not available yet."""
    if not game_id:
        return None
    try:
        data = json.loads(PLANS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data.get(str(game_id), {}).get(phase, {}).get(power)
