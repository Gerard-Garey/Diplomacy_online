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
import math
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


def exported_boost(commitments_enabled: bool, boost: float) -> float:
    """The boost multiplier to write in `search`: the one the engine applies.

    With enable_pseudo_commitments off the engine boosts nothing, whatever
    pseudo_commitment_boost says: 1.0 is then what makes the exported table true
    (the engine plays a promised order only if it plays it already).
    """
    return float(boost) if commitments_enabled else 1.0


def export_plans(
    game_id: str,
    phase: str,
    power: Power,
    action_values: List[Tuple[Action, float, float, float]],
    top_k: int = TOP_K,
    prior_policy: Optional[Dict[Action, float]] = None,
    regularize_lambda: Optional[float] = None,
    boost: Optional[float] = None,
    max_prob: Optional[float] = None,
) -> None:
    """Write `power`'s ranked candidate plans for (game_id, phase).

    action_values is the list returned by
    compute_best_action_against_reweighted_opponent_joint_actions: tuples of
    (action, value, bp_prob, pice_value), already sorted best-first -- by
    pice_value, the search's score, not by value.

    `cost` is the value given up relative to the best action, which is the
    number that actually matters when deciding whether a concession is cheap.

    Three more keys are written next to `plans`, which they leave as they were:

    `order_values`: for each order, the value of the FIRST action of
    action_values that contains it, over all of action_values and not only the
    top_k plans -- what the engine would play if it were held to that order. Not
    the best raw value of the order: that one can come from an action the engine
    would never play. An order whose value is not a finite number is left out.

    `candidates`: every action of action_values, in the same order, with its
    value and its probability BEFORE the commitment boost. bp_prob is the
    probability after apply_commitments_to_policy(); the unboosted one is read
    from `prior_policy`, the agent's policy as copied before that call.

    `search`: the effective regularisation lambda of this search, the boost
    multiplier (exported_boost: 1.0 when the engine boosts nothing) and the
    probability cap. With `candidates`, what the dialogue bot
    needs to recompute the ranking under another set of promises
    (pseudo_commitments.engine_head_action).

    `candidates` and `search` are written together or not at all: without
    prior_policy or one of the three parameters, or if a value or a probability
    is missing, not a number or not finite, neither is -- the dialogue bot then
    takes the ranking as unknown instead of working on half a table. `plans` and
    `order_values` are written all the same. The score itself is not exported.
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
        order_values: Dict[str, Optional[float]] = {}
        for action, value, _prob, _pice in action_values:
            value = round(float(value), 5)
            for order in action:
                order_values.setdefault(order, value if math.isfinite(value) else None)
        order_values = {order: value for order, value in order_values.items() if value is not None}

        entry: Dict[str, Any] = {
            "computed_at": int(time.time()),
            "plans": plans,
            "order_values": order_values,
        }
        # On its own: a table that cannot even be read (a probability that is None,
        # a lambda that is not a number) must not cost the entry its plans.
        try:
            search, why = _search_table(action_values, prior_policy, regularize_lambda, boost, max_prob), ""
        except Exception as e:
            search, why = None, f" ({type(e).__name__}: {e})"
        if search is None:
            logging.warning(
                f"plan_export: no usable candidate table for {power} {phase}{why}: "
                f"`candidates` and `search` not written"
            )
        else:
            entry.update(search)

        data: Dict[str, Any] = {}
        if PLANS_FILE.exists():
            try:
                data = json.loads(PLANS_FILE.read_text())
            except json.JSONDecodeError:
                data = {}

        data.setdefault(str(game_id), {}).setdefault(phase, {})[power] = entry

        PLANS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PLANS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, PLANS_FILE)
        logging.info(
            f"plan_export: wrote {len(plans)} candidate plans for {power} {phase} (game {game_id})"
        )
    except Exception as e:
        logging.warning(f"plan_export: failed to export plans for {power}: {e}")


def _search_table(
    action_values: List[Tuple[Action, float, float, float]],
    prior_policy: Optional[Dict[Action, float]],
    regularize_lambda: Optional[float],
    boost: Optional[float],
    max_prob: Optional[float],
) -> Optional[Dict[str, Any]]:
    """The `candidates` and `search` keys of an entry, or None if they cannot be trusted."""
    if prior_policy is None or None in (regularize_lambda, boost, max_prob):
        return None
    search = {"lambda": float(regularize_lambda), "boost": float(boost), "max_prob": float(max_prob)}
    if not all(math.isfinite(x) for x in search.values()):
        return None
    candidates = []
    for action, value, _prob, _pice in action_values:
        if action not in prior_policy:
            return None
        value, prob = round(float(value), 5), float("%.6g" % float(prior_policy[action]))
        if not (math.isfinite(value) and math.isfinite(prob)):
            return None
        candidates.append({"orders": list(action), "value": value, "prob": prob})
    return {"candidates": candidates, "search": search}


def load_plans(game_id: str, phase: str, power: Power) -> Optional[Dict[str, Any]]:
    """Read back `power`'s exported plans, or None if not available yet."""
    if not game_id:
        return None
    try:
        data = json.loads(PLANS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data.get(str(game_id), {}).get(phase, {}).get(power)
