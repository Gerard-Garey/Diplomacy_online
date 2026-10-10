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
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    Same for a file that cannot be read or is not {game: {phase: {power:
    [orders]}}}: a power whose entry is not a list of strings gets no
    commitment, the entries of the other powers are kept.
    """
    if not game_id:
        return {}
    try:
        data = json.loads(COMMITMENTS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except (OSError, ValueError) as e:  # access rights, a directory in its place, bytes that are not UTF-8
        logging.warning(f"pseudo_commitments: {COMMITMENTS_FILE} cannot be read ({type(e).__name__}), no commitment used")
        return {}
    # Valid JSON in an unexpected shape (hand-edited or damaged file): same rule,
    # the orders are computed without the promises that cannot be read. The
    # dialogue bot goes silent on such a file (check_state_files).
    if not isinstance(data, dict):
        logging.warning(
            f"pseudo_commitments: {COMMITMENTS_FILE} does not hold an object "
            f"({type(data).__name__}): no commitment used"
        )
        return {}
    phases = data.get(str(game_id), {})
    powers = phases.get(phase, {}) if isinstance(phases, dict) else None
    if not isinstance(powers, dict):
        logging.warning(
            f"pseudo_commitments: unexpected shape in {COMMITMENTS_FILE} for game {game_id}, "
            f"phase {phase}: no commitment used"
        )
        return {}
    commitments = {}
    for power, orders in powers.items():
        if isinstance(orders, list) and all(isinstance(o, str) for o in orders):
            commitments[power] = orders
        else:
            logging.warning(
                f"pseudo_commitments: commitments of {power} in {COMMITMENTS_FILE} are not a list "
                f"of orders: ignored"
            )
    return commitments


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


def boosted_policy(
    power_policy: Dict[Action, float],
    promised_orders: Iterable[Order],
    boost_multiplier: float,
    max_prob: float = MAX_COMMITMENT_PROB,
) -> Dict[Action, float]:
    """Graded boost of one power's policy towards its own promises (pure function).

    With S the promised orders, n = |S| and, for each candidate action a,
    m(a) = |S & a| the number of promised orders it honours:

        p'(a) = max(p(a), min(p(a) * boost_multiplier ** (m(a) / n), max_prob))
        q(a)  = p'(a) / sum(p')

    So an action honouring every promise gets the full multiplier, one honouring
    half of them its square root, one honouring none is left alone -- every
    candidate is treated by what it honours, whichever comes first in the dict.
    max(p, ...) so the cap can only ever withhold a boost, never demote an
    action that was already above it: before renormalisation, promising the
    action you already favour does not lower its weight p'. Its probability q
    can still go down, when the renormalisation spreads over it the boost given
    to other candidates: with promises {x, y}, multiplier 3 and cap 0.4, the
    policy 0.6 (holds x and y) / 0.1 (holds x) / 0.3 (holds neither) becomes
    0.559 / 0.161 / 0.280.

    `promised_orders` must already be legal and conflict-free (legal_commitments
    then resolve_commitment_conflicts). Returns a new dict with the same keys in
    the same order; the input is not modified. No promise, or a policy whose
    probabilities sum to 0: returned as is (copied, not renormalised).

    Only probabilities are read and written, never a value. Depends on nothing
    but the standard library, so the dialogue bot can call it to ask what the
    engine's prior becomes once a promise is recorded.
    """
    promised = frozenset(promised_orders)
    if not promised:
        return dict(power_policy)
    boosted = {}
    for action, prob in power_policy.items():
        held = len(promised.intersection(action))
        factor = boost_multiplier ** (held / len(promised))
        boosted[action] = max(prob, min(prob * factor, max_prob))
    # fsum: exactly rounded, so the result does not depend on the dict order.
    total = math.fsum(boosted.values())
    if total <= 0:
        return dict(power_policy)
    return {action: prob / total for action, prob in boosted.items()}


# Floor under the probability in the search's score, value + lambda * log(prob):
# the one of compute_best_action_against_reweighted_opponent_joint_actions
# (fairdiplomacy/agents/br_corr_bilateral_search.py).
SCORE_PROB_FLOOR = 1e-6


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def rescored_candidates(
    candidates: Any, search: Any, promised_orders: Iterable[Order]
) -> Optional[List[Tuple[Action, float, float, float]]]:
    """What the search's ranking becomes once `promised_orders` are the promises (pure function).

    `candidates` and `search` are the entries plan_export writes under those
    names: every candidate action of the last search with its value and its
    probability BEFORE any boost, and the search's effective lambda, boost
    multiplier and cap. Each candidate is boosted by boosted_policy() -- the
    very function the engine applies -- then scored as the search scores it:

        q      = boosted_policy({orders: prob}, promised_orders, boost, max_prob)
        s'(a)  = value(a) + lambda * log(max(q(a), SCORE_PROB_FLOOR))

    Returns [(action, value, q, s')] in the order of `candidates`, or None when
    the table cannot be trusted: missing or malformed entry, a value, a
    probability or a parameter that is not a finite number, or the same action
    listed twice. None must never be read as "the engine would play it".

    Exact on the exported table. The next search adds the action injected by
    build_extra_plausible_actions() and re-estimates every value; neither is
    known here.
    """
    if not isinstance(candidates, list) or not candidates or not isinstance(search, dict):
        return None
    regularize_lambda, boost, max_prob = (
        search.get("lambda"), search.get("boost"), search.get("max_prob")
    )
    if not (_finite(regularize_lambda) and _finite(boost) and _finite(max_prob)):
        return None
    if regularize_lambda < 0 or boost <= 0:
        return None

    policy: Dict[Action, float] = {}
    values: Dict[Action, float] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return None
        orders, value, prob = candidate.get("orders"), candidate.get("value"), candidate.get("prob")
        if not isinstance(orders, list) or not all(isinstance(o, str) for o in orders):
            return None
        if not (_finite(value) and _finite(prob)) or prob < 0:
            return None
        action = tuple(orders)
        if action in policy:
            return None
        policy[action], values[action] = prob, value

    boosted = boosted_policy(policy, promised_orders, boost, max_prob)
    return [
        (
            action,
            values[action],
            boosted[action],
            values[action] + regularize_lambda * math.log(max(boosted[action], SCORE_PROB_FLOOR)),
        )
        for action in policy
    ]


def engine_head_action(
    candidates: Any, search: Any, promised_orders: Iterable[Order]
) -> Optional[Action]:
    """The action the search would rank first once `promised_orders` are the promises.

    The candidate of highest s' in rescored_candidates(), the first one listed
    when several tie; None when the table cannot be trusted. Lets the dialogue
    bot ask, before it swaps a promise for another, whether the engine would
    then actually play the replacing order. Reads the engine's table, writes
    nothing to it.
    """
    rows = rescored_candidates(candidates, search, promised_orders)
    if rows is None:
        return None
    head = rows[0]
    for row in rows[1:]:
        if row[3] > head[3]:
            head = row
    return head[0]


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

    Every candidate action is boosted according to the share of the promised
    orders it contains, up to `boost_multiplier` when it contains them all
    (capped at MAX_COMMITMENT_PROB): see boosted_policy(). Promises the
    candidate set doesn't contain are left alone. Illegal/stale orders are
    ignored (both routinely produced by LLM extraction); if none is left, the
    policy is returned untouched.
    """
    promised_orders = commitments.get(agent_power)
    if not promised_orders or agent_power not in policy:
        return policy

    power_policy = policy[agent_power]
    if len(power_policy) == 1 and next(iter(power_policy)) == ():
        return policy  # eliminated / no orderable units this phase

    promised = resolve_commitment_conflicts(legal_commitments(game, agent_power, promised_orders))
    if not promised:
        return policy

    policy[agent_power] = boosted_policy(power_policy, promised, boost_multiplier)
    held = sorted((sum(1 for o in promised if o in a) for a in power_policy), reverse=True)
    if held and held[0] > 0:
        logging.info(
            f"pseudo_commitments: boosted {agent_power} policy towards {promised}; "
            f"promised orders held per candidate: {held}"
        )
    else:
        logging.info(
            f"pseudo_commitments: no candidate holds any of {promised} for {agent_power}: "
            f"nothing boosted (policy renormalised only)"
        )
    return policy
