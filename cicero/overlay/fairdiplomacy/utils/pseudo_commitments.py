#
# Externally-extracted negotiation commitments, injected as a soft nudge into
# each opponent's own plausible-order policy before the BR-correlated
# bilateral search (see fairdiplomacy/agents/bqre1p_agent.py).
#
# Source of the commitments: claude_dialogue_bot.py (running in the
# cicero-dialogue container) reads each bot's negotiation transcript with the
# human player and asks Claude to extract, per power, the orders that power
# itself said/implied it will submit this phase. That gets written to
# PSEUDO_COMMITMENTS_FILE, a JSON file on the volume shared with cicero-orders:
#   {"<gameID>": {"<phase>": {"<POWER>": ["A SIL - WAR", ...]}}}
#
# This module only ever biases a power's OWN order distribution using that
# same power's OWN stated commitments -- never the human player's orders, and
# never cross-power. The bias is capped (MAX_COMMITMENT_PROB) and only ever
# acts as a prior/weight nudge feeding into the real value-based best-response
# computation downstream, so a promise that's genuinely bad for the power
# still won't be picked (see compute_best_action_against_reweighted_opponent_joint_actions,
# which weighs value against this prior, not instead of it).
#
# NOTE on faithfulness to Cicero: this is an augmentation, not a reproduction.
# Real Cicero runs planning -> intents -> dialogue, so its messages are honest
# by construction (generated *from* the plan it currently intends). Here the
# dialogue is written first, by a separate LLM with no access to the piKL
# policy, so this module bends orders towards words -- the reverse direction.
# Keep the coefficients small: the words are not grounded in the search, and
# extraction is known to hallucinate commitments the bot never really made.
#
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from fairdiplomacy import pydipcc
from fairdiplomacy.typedefs import Action, Order, Power, PowerPolicies
from fairdiplomacy.utils.orders import get_unit_location, normalize_order_spacing

DEFAULT_COMMITMENTS_FILE = (
    Path(__file__).resolve().parents[2] / "webdip_logs_test" / "pseudo_commitments.json"
)
COMMITMENTS_FILE = Path(os.environ.get("PSEUDO_COMMITMENTS_FILE", str(DEFAULT_COMMITMENTS_FILE)))

# Hard cap: whatever the config's prior/boost, a promised action can never be
# pushed past this probability by this mechanism alone.
MAX_COMMITMENT_PROB = 0.4


def load_commitments(game_id: str, phase: str) -> Dict[Power, List[Order]]:
    """Load extracted per-power order commitments for (game_id, phase).

    Returns {} on any missing file/key -- this feature is opt-in and must
    never hard-fail order computation just because the dialogue-side
    extraction hasn't produced anything yet (e.g. no negotiation this phase).
    """
    if not game_id:
        return {}
    try:
        data = json.loads(COMMITMENTS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data.get(str(game_id), {}).get(phase, {})


def legal_commitments(
    game: pydipcc.Game, power: Power, orders: List[Order]
) -> List[Order]:
    """Keep only promised orders that are actually playable by `power` right now.

    Drops stale references (unit gone/moved) and anything not in the legal order
    set -- both routinely produced by LLM extraction, and both would otherwise
    corrupt the candidate action we build.

    Also re-normalizes spacing defensively: this should already be canonical by
    the time it reaches here (claude_dialogue_bot.py normalizes at every LLM
    output boundary), but doing it again here too is what lets an entry written
    before that fix, or by anything else that writes this file directly, self-heal
    instead of being silently and permanently dropped as "illegal".
    """
    orderable = set(game.get_orderable_locations().get(power, []))
    all_possible = game.get_all_possible_orders()
    kept = []
    for order in orders:
        order = normalize_order_spacing(order)
        try:
            loc = get_unit_location(order)
        except (AssertionError, IndexError):
            logging.warning(f"pseudo_commitments: malformed order {order!r} for {power}")
            continue
        if loc not in orderable:
            logging.info(f"pseudo_commitments: {power} promised {order!r}, no orderable unit at {loc}")
            continue
        if order not in all_possible.get(loc, []):
            logging.info(f"pseudo_commitments: {power} promised illegal order {order!r}")
            continue
        kept.append(order)
    return kept


def resolve_commitment_conflicts(orders: List[Order]) -> List[Order]:
    """Drop any unit with two contradictory promises made this phase.

    Happens when the bot promises one thing to one power and something else to
    another for the same unit. We cannot honour both, and picking one silently
    would mean honouring whoever happened to message last while betraying the
    other. Falling back to the engine's own plan for that unit is the fail-safe
    choice, and the warning makes the double-dealing visible in the logs.

    Normalizes spacing before grouping by location: two promises that differ
    only by a missing space around "-" are the same promise, not a conflict,
    and un-normalized input would group under different bogus location keys
    (get_unit_location("VIE-BOH") != "VIE") and silently miss a real conflict.
    """
    orders = [normalize_order_spacing(o) for o in orders]
    by_loc: Dict[str, List[Order]] = {}
    for order in orders:
        by_loc.setdefault(get_unit_location(order), []).append(order)

    kept = []
    for loc, loc_orders in by_loc.items():
        distinct = list(dict.fromkeys(loc_orders))
        if len(distinct) > 1:
            logging.warning(
                f"pseudo_commitments: CONTRADICTORY commitments for {loc}: {distinct} -- "
                f"dropping all of them and deferring to the plan for that unit"
            )
            continue
        kept.append(distinct[0])
    return kept


def build_extra_plausible_actions(
    game: pydipcc.Game,
    agent_power: Power,
    base_action: Action,
    commitments: Dict[Power, List[Order]],
    max_injected: int,
) -> Dict[Power, List[Action]]:
    """Build candidate actions realising this power's own promises.

    All promised orders are spliced into a single base action, so the whole
    promise costs ONE extra candidate rather than one per order -- this is the
    main lever keeping the added rollout cost bounded.

    Returned in the shape maybe_get_incremental_bp()/run_search() expect for
    extra_plausible_orders. Those paths add the action AFTER the plausible-order
    cutoff (so it cannot be evicted) and then rescore it with the parlai model,
    which is what gives it a real, dialogue-conditioned probability instead of a
    prior we made up.
    """
    if max_injected <= 0 or not base_action:
        return {}
    promised = resolve_commitment_conflicts(
        legal_commitments(game, agent_power, commitments.get(agent_power, []))
    )
    if not promised:
        return {}

    by_loc = {get_unit_location(o): o for o in promised}
    spliced = tuple(by_loc.get(get_unit_location(o), o) for o in base_action)
    if spliced == base_action:
        return {}  # the plan already does everything we promised

    logging.info(
        f"pseudo_commitments: injecting committed action for {agent_power}: {spliced} "
        f"(from promises {promised})"
    )
    return {agent_power: [spliced][:max_injected]}


def apply_commitments_to_policy(
    policy: PowerPolicies,
    game: pydipcc.Game,
    commitments: Dict[Power, List[Order]],
    agent_power: Power,
    boost_multiplier: float,
) -> PowerPolicies:
    """Nudge agent_power's own plausible-order policy towards what it promised.

    Only ever reads commitments[agent_power] and only ever modifies
    policy[agent_power]: a power is nudged towards honouring its own word, and
    never learns what another power privately promised someone else (that would
    both miss the point and leak information across the fog of war).

    policy[agent_power] is the distribution that later feeds
    compute_best_action_against_reweighted_opponent_joint_actions(), which
    scores each candidate as `value + br_regularize_lambda * log(prob)`. So
    raising a promised action's `prob` raises its score, but the rollout-derived
    `value` term is untouched -- a promise that is genuinely bad for this power
    still loses. Being in the dict at all is also what makes an action a
    candidate -- but getting it into the dict is build_extra_plausible_actions()'s
    job, not this one's. This function only nudges what is already there, so it
    can never drag the agent onto an action its own search never produced.

    For each promised order present in some candidate action, that action's
    probability is multiplied by `boost_multiplier` (capped at
    MAX_COMMITMENT_PROB). Promises the candidate set doesn't contain are left
    alone. Illegal/stale orders are ignored (both routinely produced by LLM
    extraction).
    """
    promised_orders = commitments.get(agent_power)
    if not promised_orders or agent_power not in policy:
        return policy

    power_policy = policy[agent_power]
    if len(power_policy) == 1 and next(iter(power_policy)) == ():
        return policy  # eliminated / no orderable units this phase

    for order in resolve_commitment_conflicts(
        legal_commitments(game, agent_power, promised_orders)
    ):
        matched = next((a for a in power_policy if order in a), None)
        if matched is None:
            continue
        # max(orig, ...) so the cap can only ever withhold a boost, never demote
        # an action that was already above it -- promising the action you already
        # favour must not penalise it.
        original = power_policy[matched]
        power_policy[matched] = max(
            original, min(original * boost_multiplier, MAX_COMMITMENT_PROB)
        )
        logging.info(f"pseudo_commitments: boosted {agent_power} candidate matching {order!r}")

    total = sum(power_policy.values())
    if total > 0:
        policy[agent_power] = {a: p / total for a, p in power_policy.items()}

    return policy
