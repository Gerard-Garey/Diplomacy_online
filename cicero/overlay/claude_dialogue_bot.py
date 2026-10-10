import os
import hashlib
import html
import json
import math
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from fairdiplomacy_external.webdip_api import (
    get_req,
    get_status_json,
    webdip_state_to_game,
    post_req,
    Context,
    SEND_MESSAGE_ROUTE,
    ACTIVE_GAMES_ROUTE,
)
from parlai_diplomacy.utils.game2seq.format_helpers.state import StateFlattener
from fairdiplomacy.data.build_dataset import COUNTRY_ID_TO_POWER_OR_ALL
from fairdiplomacy.utils.plan_export import load_plans
from fairdiplomacy.utils.orders import normalize_order_spacing
from fairdiplomacy.utils.pseudo_commitments import engine_head_action, legal_commitments

API_URL = os.getenv("WEBDIP_API_URL", "http://localhost:43000/api.php")
API_KEYS = ["bot1", "bot2", "bot3", "bot4", "bot5", "bot6", "bot7"]
CLAUDE_WORKDIR = os.getenv("CLAUDE_DIALOGUE_WORKDIR", "/opt/claude_dialogue_workdir")
STATE_FILE = Path(__file__).parent / "webdip_logs_test" / "claude_dialogue_state.json"
COMMITMENTS_FILE = Path(os.getenv(
    "PSEUDO_COMMITMENTS_FILE", str(Path(__file__).parent / "webdip_logs_test" / "pseudo_commitments.json")
))
POLL_INTERVAL_SECONDS = 60
MODEL = "sonnet"
NO_REPLY_TOKEN = "NO_REPLY_NEEDED"
MAX_EXCHANGES_PER_PAIR_PER_PHASE = 10
# How much better (in rollout value) the plan realising a NEW promise must be
# before the bot abandons a promise already made this phase. Breaking a given
# word must have a cost: 0.05 is about the spread of values within one search
# table. It is NOT well above the noise of the compared gain: from one search
# of a position to the next the gain moves by 0.003 (median), 0.030 (95th
# centile), 0.068 (99th), 0.150 at most -- 0.0225 (99th) for the pairs whose
# two orders are carried by the same action in every search compared, 0.0772
# for the others (half of the observations). Measured 2026-10-10 on one game,
# 1901-1903: tests/mesure/bruit_valeurs.py, issue #26, ADR 0004 ("Limites
# connues").
COMMITMENT_SWITCH_MARGIN = 0.05
# A cost at or below this is shown to Claude as "free": exported plans are ranked
# by score, not by value, so a cost can be nil or negative.
FREE_COST = 0.0005
# How many broken-promise examples are kept per recipient in the bot's own record.
MAX_OWN_RECORD_EXAMPLES = 10
# A reply whose send could not be confirmed (see pending_send in process_bot) is
# posted at most this many times in all, always with the same text.
MAX_SEND_ATTEMPTS = 3
# How many polling cycles in a row the reply must be missing from the game's
# messages before it is taken as not stored: nothing on the site bounds how late
# a request that looked failed can still write its message.
SEND_REREADS_BEFORE_RETRY = 2

COMMITMENT_SYSTEM_PROMPT = """You extract concrete order commitments from a Diplomacy negotiation transcript between {power} and {other}. Extract BOTH sides separately.

Be conservative. Only extract what was actually stated or unambiguously implied about orders for THIS phase. Never extract vague intentions ("I'll think about it", "let's stay friendly"), never anything about a future phase, and never invent orders to represent a promise you cannot express (a demilitarized-zone promise -- "I won't enter Boh" -- is NOT a list of orders; if that is all that was promised, return an empty list for that side).

Use exact Diplomacy order notation:
- Hold: "A PAR H"
- Move: "A PAR - BUR"
- Support hold: "A BUR S A PAR" (no trailing H)
- Support move: "A BUR S A PAR - PIC"
Use "A"/"F" matching the unit's ACTUAL type in the board state (do not write "A" for a fleet). Include the coast when the board state shows one, e.g. "F SPA/SC - MAO".

Output ONLY a JSON object with exactly two keys, e.g.
{{"mine": ["A SIL H"], "theirs": ["A BUR S A TYR - MUN"]}}
where "mine" = orders {power} committed to playing, and "theirs" = orders {other} committed to playing. Use [] for a side that promised nothing concrete. No other text, no markdown fences."""



def _claude_result_text(stdout: str) -> str:
    """Text of a `claude -p --output-format json` call, or raise.

    A failed call (network, TLS, quota) still returns JSON with a "result"
    field -- holding the error text -- and "is_error": true. Reading that as
    the model's answer made the bot treat an API failure as a deliberate
    silence and mark the incoming message as handled, so it was never
    answered. Raising instead leaves the message pending: the polling loop
    logs the error and retries on the next cycle.
    """
    parsed = json.loads(stdout)
    if "result" not in parsed or parsed.get("is_error"):
        raise RuntimeError(f"Claude call failed: {str(parsed.get('result', parsed))[:300]}")
    return parsed["result"].strip()

def extract_commitments(power: str, other: str, board_state_text: str, phase: str, transcript: str) -> dict:
    """Return {"mine": [orders], "theirs": [orders]} extracted from the transcript."""
    user_prompt = f"""Current phase: {phase}.

Board state:
{board_state_text}

Transcript of messages between {power} and {other} this phase (chronological):
{transcript}

Extract the order commitments of both sides as instructed."""

    result = subprocess.run(
        [
            "claude", "-p", user_prompt,
            "--model", MODEL,
            "--system-prompt", COMMITMENT_SYSTEM_PROMPT.format(power=power, other=other),
            "--output-format", "json",
            "--allowedTools", "",
            "--max-budget-usd", "0.20",
        ],
        cwd=CLAUDE_WORKDIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = _claude_result_text(result.stdout)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        print(f"  commitment extraction: could not parse {text!r} as JSON, ignoring", flush=True)
        return {"mine": [], "theirs": []}
    if not isinstance(obj, dict):
        return {"mine": [], "theirs": []}
    return {
        side: [normalize_order_spacing(o) for o in obj.get(side, []) if isinstance(o, str)]
        for side in ("mine", "theirs")
    }


def build_plan_section(game_id: int, phase: str, power: str) -> str:
    """Describe this power's own piKL plan (best action + near-optimal alternatives).

    The alternatives are the point: they tell the bot which concessions are
    actually cheap, so a negotiation can genuinely change what it plays instead
    of every deal being a bluff over a single fixed action.
    """
    entry = load_plans(str(game_id), phase, power)
    if not entry or not entry.get("plans"):
        return ""

    plans = entry["plans"]
    lines = [
        "Your current plan (PRIVATE -- computed by your own strategic engine, never quote it wholesale):",
        f"  Preferred: {', '.join(plans[0]['orders'])}",
    ]
    alts = plans[1:]
    if alts:
        lines.append("  Near-equivalent alternatives, with what each costs you versus the preferred plan:")
        for p in alts:
            shown = _shown_cost(p.get("cost_vs_best"))
            cost = "cost unknown" if shown is None else shown if shown == "free" else f"cost {shown}"
            lines.append(f"    - {cost}: {', '.join(p['orders'])}")
        lines.append(
            "  \"free\" means that alternative costs you nothing, and a cost near 0 almost nothing: "
            "you can genuinely agree to either if the deal is worth it. A large cost means giving it up "
            "would really hurt -- resist, or extract something substantial in exchange."
        )
    lines.append(
        "  You are not bound by this plan and may still bluff about it. But it is what you currently "
        "intend, so let it inform which deals you accept, refuse, or counter-propose."
    )
    return "\n".join(lines) + "\n\n"


def _finite(value) -> bool:
    """A real, finite number: neither a bool, nor NaN, nor an infinity."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _shown_cost(cost):
    """How a cost is shown to Claude: "free" at or below FREE_COST, else the
    unsigned figure ("0.012"); None when it is not a finite number.

    Display only: the exported cost_vs_best keeps its sign. Never "-0.000",
    "nan" nor "inf". Compared rounded to 5 decimals, the precision of the export.
    """
    if not _finite(cost):
        return None
    if round(cost, 5) <= FREE_COST:
        return "free"
    return f"{cost:.3f}"


def _order_loc(order: str):
    parts = normalize_order_spacing(order).split()
    return parts[1] if len(parts) > 1 else None


def _first_plan_value(plans: list, order: str):
    """Value of the first exported plan that plays `order`, or None if none does.

    Plans are exported in the search's own ranking (by score): the first one
    playing the order is what the engine would play if held to it.
    Plan orders are already canonical (they come straight from the search).
    `order` may not be (older persisted state, or a caller that didn't
    normalize) -- normalized here so the comparison can't silently miss.
    """
    order = normalize_order_spacing(order)
    for p in plans:
        if order in p["orders"]:
            return p["value"] if _finite(p["value"]) else None
    return None


def _order_value(order: str, plans: list, order_values: dict = None):
    """Value of what the engine would play if held to `order`, or None if unknown.

    `order_values` is the index plan_export writes next to the plans: for each
    order, the value of the best-SCORED action containing it, over ALL candidate
    actions of the search. When it is there it alone decides, since the exported
    plans are only its top few. A plans entry written before the index existed
    has none: fall back on the first exported plan playing the order, an order
    outside the top few being simply unknown. A value that is not a finite
    number is unknown.
    """
    if isinstance(order_values, dict):
        value = order_values.get(normalize_order_spacing(order))
        return value if _finite(value) else None
    return _first_plan_value(plans, order)


def _reject_contradictions(
    sincere: list,
    by_recipient: dict,
    plans: list = None,
    margin: float = None,
    betray: list = None,
    order_values: dict = None,
    candidates: list = None,
    search: dict = None,
):
    """Reconcile new sincere orders with what was already promised this phase.

    `betray` lists the earlier promises (exact orders) the bot declares it is
    breaking; `order_values`, `candidates` and `search` are the keys of the
    plans entry written by plan_export, if any.

    Returns (accepted, demoted, superseded, conflicting, ignored):
      - demoted:    [(new_order, earlier_order, reason, gain)] -- new promise not
                    recorded, so the message that carried it is a bluff. reason
                    is "undeclared" (no label for the earlier promise),
                    "unknown_value" (a value, or the engine's candidate table,
                    is missing), "below_margin" or "not_played" (the engine
                    would not play it); gain is None for the first two.
      - superseded: [(recipient, earlier_order, new_order, gain)] -- the EARLIER
                    promise is abandoned instead, a deliberate betrayal. One
                    tuple per recipient holding it, never a None recipient.
      - conflicting: [(order, other_order, ...)] -- distinct orders given to one
                    unit within `sincere` itself; none of them is recorded.
      - ignored:    [(label, reason)] -- labels of `betray` that break nothing:
                    "no_such_promise" (not an order promised this phase),
                    "no_replacement" (no order for that unit in `sincere`),
                    "conflicting" (`sincere` orders that unit two ways) or
                    "restated" (`sincere` repeats the promise itself). Every
                    label that is not acted upon is listed here, once.

    Invariant kept here and by the caller: at most one sincere order per unit,
    all recipients together. A list that orders one unit two ways says nothing
    about that unit: its orders are set aside before any comparison, so they
    neither restate nor challenge an earlier promise, which stays as it was,
    label or not. The same order repeated in the list counts once.

    A later promise only wins when three things hold: the bot declared the
    earlier one broken (its exact order is in `betray`); the search values what
    the engine would play if held to the new order more than what it would play
    if held to the earlier one, by more than `margin` (_order_value, compared
    rounded to 5 decimals, the precision of the export); and the engine would
    then actually play the new order -- it belongs to the action its ranking
    puts first once the promises are swapped (engine_head_action, on the
    exported candidate table). Without the label a contrary order is a slip of
    the model, not a decision. The margin matters: rollout values are noisy
    estimates, and without it the bot would flip-flop between counterparts on
    estimation noise alone. Without the third condition the engine can end up
    playing neither order: two promises broken for one. With a value or the
    candidate table unknown we keep the earlier promise -- we have no evidence
    the switch is worth a broken word.

    The third condition is judged on the promises as the message leaves them.
    Every replacement that passed the label and the margin is put in the
    promises together and checked against the head action; those the engine
    would not play are taken out, their earlier promises put back, and the
    remaining ones judged again on that new set, until none is taken out. So
    every replacement that is accepted belongs to the head action of the
    promises finally recorded.
    """
    plans = plans or []
    margin = COMMITMENT_SWITCH_MARGIN if margin is None else margin

    # Normalized once here rather than trusting callers/stored state: by_recipient
    # can hold entries persisted before a normalization fix landed (this has
    # happened in practice -- a promise recorded pre-fix must not look like a
    # fresh contradiction against the same promise restated post-fix).
    # The earlier promise for a unit is the first one found; every recipient
    # holding that same order is remembered, so a betrayal drops it for all.
    prior_by_loc = {}
    for recipient, orders in by_recipient.items():
        for o in orders:
            o = normalize_order_spacing(o)
            earlier, holders = prior_by_loc.setdefault(_order_loc(o), (o, []))
            if earlier == o and recipient not in holders:
                holders.append(recipient)

    # Incoming orders per unit, identical repeats collapsed.
    incoming_by_loc = {}
    for o in sincere:
        o = normalize_order_spacing(o)
        orders = incoming_by_loc.setdefault(_order_loc(o), [])
        if o not in orders:
            orders.append(o)

    # A label counts only if it is the exact order promised for its unit AND the
    # list brings an order for that unit: dropping a promise with nothing to
    # replace it is not supported, the promise stands.
    declared, ignored = set(), []
    for label in dict.fromkeys(normalize_order_spacing(o) for o in betray or []):
        loc = _order_loc(label)
        if prior_by_loc.get(loc, (None, []))[0] != label:
            ignored.append((label, "no_such_promise"))
        elif loc not in incoming_by_loc:
            ignored.append((label, "no_replacement"))
        elif len(incoming_by_loc[loc]) > 1:
            ignored.append((label, "conflicting"))
        elif incoming_by_loc[loc][0] == label:
            ignored.append((label, "restated"))
        else:
            declared.add(loc)

    # Is the engine's candidate table there and readable at all (whatever the promises)?
    table_known = engine_head_action(candidates, search, ()) is not None

    # First pass, per unit: everything but the third condition. `outcomes` keeps
    # the order of the incoming list; a replacement that passed the label and
    # the margin waits there for the engine's verdict.
    outcomes, conflicting = [], []
    for loc, orders in incoming_by_loc.items():
        if len(orders) > 1:
            conflicting.append(tuple(orders))
            continue
        o = orders[0]
        earlier, _holders = prior_by_loc.get(loc, (None, []))

        if earlier is None or earlier == o:
            outcomes.append(("accepted", o, earlier, None))
            continue
        if loc not in declared:
            outcomes.append(("undeclared", o, earlier, None))
            continue

        v_new = _order_value(o, plans, order_values)
        v_old = _order_value(earlier, plans, order_values)
        if v_new is None or v_old is None or not table_known or not any(
            o in candidate["orders"] for candidate in candidates
        ):
            outcomes.append(("unknown_value", o, earlier, None))
            continue
        # Rounded like the exported values: 0.32 - 0.30 is 0.020000000000000018 in
        # floats, and must not pass a margin of 0.02.
        gain = round(v_new - v_old, 5)
        outcomes.append(("pending" if gain > margin else "below_margin", o, earlier, gain))

    # The promises as they would stand after this message, one order per unit,
    # all recipients together: the earlier ones, minus those being replaced,
    # plus the incoming orders that were not demoted. A replacement the engine
    # would not play leaves that set and its earlier promise comes back, which
    # can change the head action the others were judged on: judged again until
    # no replacement is taken out. Each round but the last takes out at least
    # one, hence the bound.
    pending = [o for status, o, _e, _g in outcomes if status == "pending"]
    not_played = set()
    for _ in range(len(pending) + 1):
        standing = [o for o in pending if o not in not_played]
        if not standing:
            break
        after = {loc: earlier for loc, (earlier, _holders) in prior_by_loc.items()}
        after.update({_order_loc(o): o for status, o, _e, _g in outcomes if status == "accepted"})
        after.update({_order_loc(o): o for o in standing})
        head = engine_head_action(candidates, search, list(after.values()))
        refused = [o for o in standing if head is None or o not in head]
        if not refused:
            break
        not_played.update(refused)
    else:
        # Not reachable (see the bound); if it ever were, every earlier promise stands.
        not_played.update(pending)

    accepted, demoted, superseded = [], [], []
    for status, o, earlier, gain in outcomes:
        if status == "accepted":
            accepted.append(o)
        elif status != "pending":
            demoted.append((o, earlier, status, gain))
        elif o not in not_played:
            holders = prior_by_loc[_order_loc(o)][1]
            superseded.extend((recipient, earlier, o, gain) for recipient in holders)
            accepted.append(o)
        else:
            demoted.append((o, earlier, "not_played", gain))
    return accepted, demoted, superseded, conflicting, ignored


def build_commitments_section(
    sincere_by_recipient: dict,
    current: str,
    plans: list = None,
    order_values: dict = None,
    margin: float = None,
    candidates: list = None,
    search: dict = None,
) -> str:
    """Remind the bot what it has already sincerely promised this phase, and to whom.

    Without this, every reply is a fresh Claude call that cannot know it already
    promised the same unit elsewhere this phase -- the one way it could sincerely
    double-deal by accident rather than by choice.

    Each promise comes with what keeping it costs: value of the preferred plan
    (plans[0]) minus the value of what the engine would play if held to the
    promised order (_order_value, the very number _reject_contradictions
    compares). It is the only figure given beyond the plan section. Exported
    plans are ranked by score, not by value, so the preferred plan is not always
    the most valuable one and a cost can be nil or negative: at or below
    FREE_COST it is shown as "free" (_shown_cost), never with a sign.

    `candidates` and `search` are the engine's candidate table of the plans
    entry. An entry written before the table existed has none, and without it
    _reject_contradictions refuses every replacement ("unknown_value"): the
    cost is then followed by "cannot be replaced this phase".
    """
    plans = plans or []
    margin = COMMITMENT_SWITCH_MARGIN if margin is None else margin
    preferred = plans[0].get("value") if plans and isinstance(plans[0], dict) else None
    # Same test as _reject_contradictions (table_known).
    locked = "" if engine_head_action(candidates, search, ()) is not None else "; cannot be replaced this phase"

    promises = []
    for recipient, orders in sincere_by_recipient.items():
        who = f"{recipient} (this conversation)" if recipient == current else recipient
        for order in orders:
            value = _order_value(order, plans, order_values)
            if value is None:
                cost = "[value unknown: cannot be replaced this phase]"
            elif not _finite(preferred):
                cost = "[cost unknown]"
            else:
                shown = _shown_cost(preferred - value)
                cost = f"[keeping it is free{locked}]" if shown == "free" else f"[keeping it costs {shown}{locked}]"
            promises.append(f"  - to {who}: {order}  {cost}")
    if not promises:
        return ""
    lines = [
        "Promises you have already made this phase (real intentions -- your engine is acting on them; "
        "costs are relative to your preferred plan):",
        *promises,
        "  Your word is an asset. Each of these powers sees at the end of the turn whether you did "
        "what you said; a broken promise costs you their trust for the rest of the game.",
        "  Default: keep them. If what is asked now conflicts with one, decline, or bluff "
        "(a bluff never goes in \"sincere\").",
        "  You MAY deliberately break one -- that is Diplomacy -- but only as a declared decision: "
        "put the earlier order, exactly as written above, in \"betray\", and the order replacing it "
        "in \"sincere\". Your engine honours the switch only if what it would play when held to the "
        f"replacing order is worth clearly more (by more than {margin}) than what it would play when "
        "held to the promise, and only if it would then actually play the replacing order. "
        "Otherwise the earlier promise stands and what you just said is a bluff.",
    ]
    return "\n".join(lines) + "\n\n"


def build_own_record_section(record: dict, counterpart: str) -> str:
    """Summarize how the bot itself has kept its promises to this counterpart.

    Only the counterpart being answered: what was promised to another power
    must not be able to leak into this conversation.
    """
    entry = record.get(counterpart)
    if not entry or not (entry.get("kept") or entry.get("broken")):
        return ""

    kept, broken = entry.get("kept", 0), entry.get("broken", 0)
    lines = [f"Your own record with {counterpart}: {kept} promise(s) kept, {broken} broken."]
    if broken:
        for ex in entry.get("examples", [])[-3:]:
            lines.append(
                f"  - {ex['phase']}: you promised {ex['promised']!r} and played {ex['actual']!r}"
            )
        lines.append(
            f"  {counterpart} saw this. Expect less trust from them; do not pretend it did not happen."
        )
    else:
        lines.append(
            f"  {counterpart} has seen you keep your word every time. That credit is worth protecting."
        )
    return "\n".join(lines) + "\n\n"


def build_trust_section(trust: dict, counterpart: str) -> str:
    """Summarize how reliably this counterpart has honoured past promises."""
    record = trust.get(counterpart)
    if not record or not (record.get("kept") or record.get("broken")):
        return ""

    kept, broken = record.get("kept", 0), record.get("broken", 0)
    lines = [f"Track record of {counterpart} with you: {kept} promise(s) kept, {broken} broken."]
    for ex in record.get("examples", [])[-3:]:
        lines.append(
            f"  - {ex['phase']}: promised {ex['promised']!r} but played {ex['actual']!r}"
        )
    if broken > kept:
        lines.append(
            f"  {counterpart} has broken more promises than they kept. Treat their assurances with "
            "open suspicion, demand verifiable moves this turn rather than future ones, and do not "
            "expose your units on the strength of their word alone."
        )
    elif broken:
        lines.append(
            f"  {counterpart} has broken promises before. Stay guarded and prefer deals that do not "
            "leave you vulnerable if they defect again."
        )
    else:
        lines.append(f"  {counterpart} has honoured everything so far. Cautious trust is reasonable.")
    return "\n".join(lines) + "\n\n"


def _normalize_order(order: str) -> str:
    """Loose comparison key: uppercase, single-spaced, coasts stripped.

    Extraction routinely gets coast qualifiers wrong ("F SPA" vs "F SPA/SC"),
    and sometimes drops the spacing around "-" ("F TRI-ALB" vs "F TRI - ALB")
    -- neither must be scored as a broken promise.
    """
    o = " ".join(normalize_order_spacing(order).upper().split())
    for coast in ("/SC", "/NC", "/EC", "/WC"):
        o = o.replace(coast, "")
    return o


def _score_promises(game, pending: dict, records: dict, promiser: str = None, current_phase: str = None) -> None:
    """Score the promises of `pending` ({"<phase>:<power>": [orders]}) against the
    orders actually played, into `records` ({"<power>": {kept, broken, examples}}).

    Two uses, one comparison (_normalize_order, promises that were legal only):
      - promiser None: promises made TO the bot. The power of the key made them;
        they are scored against its orders, into its record. A phase counts as
        resolved once that power's orders are visible.
      - promiser given (the bot itself): promises made BY the bot. The power of
        the key received them; they are scored against the bot's own orders,
        into the record kept for that recipient. A phase counts as resolved
        once it exists in the game and is no longer `current_phase` -- not on
        visible orders, or a phase where the bot ordered nothing would leave
        its promises pending forever. A unit left without an order held: a
        promised hold is then kept, anything else broken. Only the last
        MAX_OWN_RECORD_EXAMPLES examples are kept per recipient.
    The last two rules are the bot's own only: promises made TO the bot are
    scored exactly as before.
    """
    resolved = {pd.name: pd for pd in game.get_all_phases()}

    for key in list(pending.keys()):
        phase, counterpart = key.split(":", 1)
        player = counterpart if promiser is None else promiser
        pd = resolved.get(phase)
        if promiser is None:
            if pd is None or not pd.orders.get(counterpart):
                continue  # not resolved yet (or orders not visible) -- check again later
        elif pd is None or phase == current_phase:
            continue  # still being played

        actual = pd.orders.get(player) or []
        actual_norm = {_normalize_order(o) for o in actual}
        try:
            past_game = game.rolled_back_to_phase_start(phase)
            legal_locs = set(past_game.get_orderable_locations().get(player, []))
        except Exception:
            legal_locs = None

        record = records.setdefault(counterpart, {"kept": 0, "broken": 0, "examples": []})
        for promised in pending.pop(key):
            loc = promised.split()[1] if len(promised.split()) > 1 else None
            if legal_locs is not None and (loc is None or loc not in legal_locs):
                continue  # promise was never actionable; don't hold it against them
            played = [o for o in actual if len(o.split()) > 1 and o.split()[1] == loc]
            # Our own unit left without an order held: a promised hold was kept.
            held_as_promised = (
                promiser is not None and not played and _normalize_order(promised).split()[2:] == ["H"]
            )
            if _normalize_order(promised) in actual_norm or held_as_promised:
                record["kept"] += 1
            elif promiser is None:
                record["broken"] += 1
                record["examples"].append({
                    "phase": phase,
                    "promised": promised,
                    "actual": played[0] if played else "nothing at " + str(loc),
                })
                what = f"said {promised!r}, played {played[0] if played else '(nothing there)'}"
                print(f"  [trust] {counterpart} broke a promise in {phase}: {what}", flush=True)
            else:
                record["broken"] += 1
                did = played[0] if played else f"no order submitted for {loc} (unit held)"
                record["examples"].append({"phase": phase, "promised": promised, "actual": did})
                del record["examples"][:-MAX_OWN_RECORD_EXAMPLES]
                print(
                    f"  [own-record] {promiser} broke a promise to {counterpart} in {phase}: "
                    f"said {promised!r}, played {did}",
                    flush=True,
                )


def verify_promises(game, game_id: int, my_power: str, bot_state: dict) -> dict:
    """Score previously-recorded counterpart promises against what they actually played.

    Only checks phases that have since resolved, and only promises that were
    legal when made -- otherwise a hallucinated extraction would be recorded as
    the player lying.
    """
    pending = bot_state.setdefault("pending_promises", {})
    trust = bot_state.setdefault("trust", {})
    if not pending:
        return trust
    _score_promises(game, pending, trust)
    return trust


def _own_promises(bot_state: dict):
    """(pending, record) of the bot's own promises; a state without them is empty.

    Mirror of pending_promises / trust, the other way round: what this bot
    promised, per recipient, and how it turned out.
      pending: {"<phase>:<recipient>": [orders]} -- sincere promises not scored yet
      record:  {"<recipient>": {"kept": n, "broken": n, "examples": [...]}}

    Invariant of pending: at most one order per unit and per recipient, the last
    one said sincerely (see the revision rule in process_bot).

    Whatever does not have that shape (hand-edited or damaged state) is replaced
    by an empty one, with a log line: this memory only feeds a section of the
    prompt, and a malformed entry must not raise on every cycle and leave the
    bot silent.
    """
    def reset(what, found):
        print(f"  [own-record] malformed {what} in the state ({type(found).__name__}), reset to empty", flush=True)

    own = bot_state.get("own_promises")
    if not isinstance(own, dict):
        if own is not None:
            reset("own_promises", own)
        own = bot_state["own_promises"] = {}
    for key in ("pending", "record"):
        if not isinstance(own.get(key), dict):
            if key in own:
                reset(f"own_promises.{key}", own[key])
            own[key] = {}
    pending, record = own["pending"], own["record"]

    for key in list(pending):
        orders = pending[key]
        if ":" not in key or not isinstance(orders, list) or not all(isinstance(o, str) for o in orders):
            reset(f"own_promises.pending[{key!r}]", orders)
            del pending[key]
    for recipient in list(record):
        entry = record[recipient]
        if not isinstance(entry, dict):
            reset(f"own_promises.record[{recipient!r}]", entry)
            record[recipient] = entry = {}
        for count in ("kept", "broken"):
            if not isinstance(entry.get(count), int) or isinstance(entry.get(count), bool):
                if count in entry:
                    reset(f"own_promises.record[{recipient!r}].{count}", entry[count])
                entry[count] = 0
        examples = entry.get("examples")
        if not isinstance(examples, list):
            if "examples" in entry:
                reset(f"own_promises.record[{recipient!r}].examples", examples)
            examples = []
        entry["examples"] = [
            ex for ex in examples
            if isinstance(ex, dict) and all(isinstance(ex.get(k), str) for k in ("phase", "promised", "actual"))
        ][-MAX_OWN_RECORD_EXAMPLES:]
    return pending, record


def verify_own_promises(game, my_power: str, phase: str, bot_state: dict) -> dict:
    """Score the bot's own promises of past phases against the orders it played.

    A promise dropped by a declared betrayal is still pending for the powers
    betrayed: what counts is the order actually played.
    """
    pending, record = _own_promises(bot_state)
    if pending:
        _score_promises(game, pending, record, promiser=my_power, current_phase=phase)
    return record


class UnreadableStateFile(RuntimeError):
    """A state file is there but cannot be read as a JSON object, or cannot be written."""


def _unusable(path: Path, problem: str, remedy: str) -> UnreadableStateFile:
    return UnreadableStateFile(
        f"{path} {problem}. It has been left "
        f"untouched. The dialogue bot stays silent (no message read, no reply "
        f"sent, nothing written) until you {remedy}; no "
        f"restart is needed, it resumes by itself from the files on disk. A "
        f"missing file means an empty state: without the state file, messages "
        f"already answered would be answered again."
    )


def _read_json_file(path: Path) -> dict:
    """Read a JSON object from `path`. A missing file is an empty state.

    A file that is there but unreadable (truncated, empty, not a JSON object)
    raises instead of returning {}: starting again from an empty state would
    look fine and silently lose replied_ts (every message already answered gets
    answered again) or the promises of the current phase, and the next save
    would then overwrite whatever was still recoverable in the file.

    Any OSError other than a missing file (access rights, a directory in place
    of the file, an I/O error) is the same case: the file may well be there and
    hold a state, it must not be taken for an empty one.
    """
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise _unusable(
            path, f"cannot be read ({type(e).__name__}: {e})",
            "fix what prevents reading it (access rights, a directory in its place) or move it aside",
        )
    except ValueError as e:  # JSONDecodeError, or bytes that are not UTF-8
        data, reason = None, str(e)
    else:
        reason = f"expected a JSON object, found {type(data).__name__}"
    if not isinstance(data, dict):
        raise _unusable(
            path, f"exists but is not readable JSON ({reason})", "repair the file or move it aside"
        )
    return data


def _write_json_file(path: Path, data) -> None:
    """Write atomically (temp in the same directory + os.replace, as plan_export
    does): a container killed mid-write leaves the previous file intact instead
    of a truncated one.

    Never replaces a file that is there but unreadable: raises UnreadableStateFile
    like a read would, so what is still recoverable in it stays on disk. A write
    that fails (access rights, disk full, a directory in the way) raises it too:
    the bot must not go on answering with a state it cannot record."""
    _read_json_file(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)
    except OSError as e:
        raise _unusable(
            path, f"cannot be written ({type(e).__name__}: {e})",
            "fix what prevents writing it (access rights, disk space, a directory in its "
            "place) or move it aside",
        )


def load_commitments_file():
    return _read_json_file(COMMITMENTS_FILE)


def save_commitments_file(data):
    _write_json_file(COMMITMENTS_FILE, data)


def _check_commitments_shape(data: dict) -> None:
    """Raise UnreadableStateFile unless `data` is {game: {phase: {power: [orders]}}}.

    A file that is valid JSON in another shape (a list where the phases of a
    game should be, an order that is not a string) is the same case as one that
    cannot be read: the bot would call Claude and record promises in its state
    without ever being able to write them for the engine.
    """
    def unexpected(where, found, wanted):
        return _unusable(
            COMMITMENTS_FILE,
            f"is JSON but not in the expected shape ({where} is {type(found).__name__}, "
            f"expected {wanted})",
            "repair the file or move it aside",
        )

    for game_id, phases in data.items():
        if not isinstance(phases, dict):
            raise unexpected(f"game {game_id!r}", phases, "an object of phases")
        for phase, powers in phases.items():
            if not isinstance(powers, dict):
                raise unexpected(f"phase {phase!r} of game {game_id!r}", powers, "an object of powers")
            for power, orders in powers.items():
                where = f"{power!r} in phase {phase!r} of game {game_id!r}"
                if not isinstance(orders, list):
                    raise unexpected(where, orders, "a list of orders")
                for order in orders:
                    if not isinstance(order, str):
                        raise unexpected(f"an order of {where}", order, "a string")


def check_state_files() -> dict:
    """Raise UnreadableStateFile if either state file is there but unreadable,
    or if the commitments file does not have the expected shape.
    Returns the state as it is on disk."""
    _check_commitments_shape(load_commitments_file())
    return _read_json_file(STATE_FILE)


# ---------------------------------------------------------------------------
# Send journal. The site gives no idempotence key and a request can look failed
# although its message was stored (the INSERT is final as soon as it runs; what
# can fail comes after it). So a reply is never posted again on the strength of
# an error: what was about to be sent is written to the state first
# (pending_send), and an unconfirmed send is settled by reading the game's
# messages back. See process_bot.
# ---------------------------------------------------------------------------
def _decode_stored_message(text: str) -> str:
    """A message as the site returns it, back to what was posted: the site stores
    line breaks as "<br />" and the rest through htmlentities. Same two steps as
    webdip_state_to_game (fairdiplomacy_external/webdip_api.py)."""
    return html.unescape(str(text).replace("<br />", "\n"))


def _message_key(text: str) -> str:
    """Comparison key of a message text, for "is this the reply I posted?".

    Both sides get it, the posted text as it is and the stored one once decoded:
    line breaks in one form ("\r\n", "\r" and "<br />" are all "\n" -- the site
    stores a literal "<br />" as a line break too), entities unescaped, outer
    blanks stripped. Characters beyond U+FFFF (emoji) and "?" are dropped from
    both: the site's table may store such a character as "?" (not verified), and
    a reply must not look lost for that.
    """
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("<br />", "\n")
    text = html.unescape(text)
    return "".join(c for c in text if ord(c) <= 0xFFFF and c != "?").strip()


def _sent_mark(time_sent: int, recipient: str, text: str) -> str:
    """Entry of sent_ts for one message this bot knows it sent: the site's
    timeSent (seconds), the recipient, and a digest of the text's key. timeSent
    alone would not do: it has a resolution of one second."""
    digest = hashlib.sha1(_message_key(text).encode("utf-8")).hexdigest()[:16]
    return f"{int(time_sent)}:{recipient}:{digest}"


def _sent_ts(bot_state: dict) -> list:
    """sent_ts of the state, without what is not a mark (_sent_mark is a string).

    As in _own_promises: a hand-edited or damaged entry is removed from the
    state with a log line instead of raising on every cycle. A state without
    sent_ts is left without it.
    """
    sent = bot_state.get("sent_ts")
    if sent is None:
        return []
    if not isinstance(sent, list):
        print(f"  [sent-ts] malformed sent_ts in the state ({type(sent).__name__}), reset to empty", flush=True)
        sent = bot_state["sent_ts"] = []
        return sent
    kept = [mark for mark in sent if isinstance(mark, str)]
    if len(kept) != len(sent):
        print(
            f"  [sent-ts] {len(sent) - len(kept)} malformed entry(ies) of sent_ts removed from the state",
            flush=True,
        )
        bot_state["sent_ts"] = kept
    return kept


def _messages_sent_by(status_json, country_id: int) -> list:
    """[(timeSent, toCountryID, decoded text)] of every message `country_id` sent,
    over ALL phases of the status JSON (the site files a message under the
    "Diplomacy" phase of its turn, whatever the phase it was written in).

    To be called before webdip_state_to_game, which deletes the messages from
    the status JSON. Entries that do not have the expected shape are skipped.
    """
    found = []
    phases = status_json.get("phases") if isinstance(status_json, dict) else None
    for p in phases if isinstance(phases, list) else []:
        messages = p.get("messages") if isinstance(p, dict) else None
        for m in messages if isinstance(messages, list) else []:
            if not isinstance(m, dict) or m.get("fromCountryID") != country_id:
                continue
            time_sent, to_id, text = m.get("timeSent"), m.get("toCountryID"), m.get("message")
            if _whole(time_sent) and _whole(to_id) and isinstance(text, str):
                found.append((time_sent, to_id, _decode_stored_message(text)))
    return found


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _find_pending_send(pending_send: dict, sent_messages: list, recipient_id: int, sent_ts: list):
    """timeSent of the message that is the pending reply, or None if it is not there.

    It is one sent to the same recipient, with the same text (_message_key), not
    before the message it answers was received (game.messages keys are in
    centiseconds, timeSent in seconds), and that is not already accounted for in
    `sent_ts`: an identical reply sent earlier must not confirm this one.
    """
    since = int(pending_send["ts"]) // 100
    key = _message_key(pending_send["text"])
    known = Counter(sent_ts)
    for time_sent, to_id, text in sorted(sent_messages):
        if to_id != recipient_id or time_sent < since or _message_key(text) != key:
            continue
        mark = _sent_mark(time_sent, pending_send["recipient"], pending_send["text"])
        if known[mark]:
            known[mark] -= 1
            continue
        return time_sent
    return None


def _send_outcome(resp):
    """Classify the answer to a send: ("sent", timeSent), ("muted", None) or
    ("uncertain", reason).

    Sent: status 200 and a body that is JSON from end to end, holding a
    non-empty "messages" list -- the stored message, read back by the site.
    Muted: the same with an empty list: the recipient muted this country and
    nothing was stored. Anything else (another status, a body that is not JSON,
    JSON followed by an HTML error page) says nothing either way.
    """
    status = getattr(resp, "status_code", None)
    if status != 200:
        return "uncertain", f"status={status}"
    try:
        body = json.loads(resp.content)
    except (TypeError, ValueError):
        return "uncertain", "status=200, body is not JSON"
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list):
        return "uncertain", "status=200, no \"messages\" list in the body"
    if not messages:
        return "muted", None
    time_sent = messages[0].get("timeSent") if isinstance(messages[0], dict) else None
    if not _whole(time_sent):
        return "uncertain", "status=200, no timeSent in the body"
    return "sent", time_sent


def _valid_pending_send(ps) -> bool:
    """Is `ps` a pending_send as process_bot writes it?"""
    if not isinstance(ps, dict):
        return False
    strings = lambda v: isinstance(v, list) and all(isinstance(o, str) for o in v)
    added, own = ps.get("added"), ps.get("own_pending")
    return (
        all(isinstance(ps.get(k), str) for k in ("ts", "recipient", "text", "phase"))
        and ps["ts"].isdigit()
        and ps["recipient"] in POWER_TO_ID
        and all(_whole(ps.get(k)) and ps[k] >= 0 for k in ("attempts", "rereads"))
        and isinstance(added, dict)
        and strings(added.get("by_recipient")) and strings(added.get("commitments"))
        and isinstance(ps.get("removed"), list)
        and all(
            isinstance(e, dict) and isinstance(e.get("order"), str) and strings(e.get("holders"))
            for e in ps["removed"]
        )
        and (own is None or (
            isinstance(own, dict) and isinstance(own.get("key"), str)
            and (own.get("before") is None or strings(own.get("before")))
        ))
        # Absent from a pending_send written before the key existed.
        and ("journal" not in ps or strings(ps["journal"]))
    )


def _apply_send_to_commitments(game_id: int, power: str, ps: dict) -> None:
    """Write the commitments of the pending reply `ps` for the engine: the
    promises it drops are removed, those it makes are added. Idempotent.

    Compared in normalized spacing for a removal, as in by_recipient: an entry
    written as "A PAR-BUR" is the same promise. The entries that stay are not
    rewritten.
    """
    added, dropped = ps["added"]["commitments"], {e["order"] for e in ps["removed"]}
    if not added and not dropped:
        return
    data = load_commitments_file()
    phase_data = data.setdefault(str(game_id), {}).setdefault(ps["phase"], {})
    kept = [o for o in phase_data.get(power, []) if normalize_order_spacing(o) not in dropped]
    phase_data[power] = list(dict.fromkeys(kept + added))
    save_commitments_file(data)


def _undo_send_in_commitments(game_id: int, power: str, ps: dict) -> None:
    """The reverse: the reply did not go out, so the engine gets back the
    promises as they stood before it. Idempotent."""
    added, removed = set(ps["added"]["commitments"]), [e["order"] for e in ps["removed"]]
    if not added and not removed:
        return
    data = load_commitments_file()
    phase_data = data.setdefault(str(game_id), {}).setdefault(ps["phase"], {})
    kept = [o for o in phase_data.get(power, []) if o not in added]
    for order in removed:
        if all(normalize_order_spacing(o) != order for o in kept):
            kept.append(order)
    phase_data[power] = kept
    save_commitments_file(data)


def _undo_send_in_state(bot_state: dict, ps: dict) -> None:
    """The reverse of what the pending reply `ps` did to by_recipient and to
    own_promises.pending: what it added goes, what it dropped (betrayal or
    revision) is given back to every recipient that held it."""
    sincere_state = bot_state.get("sincere_by_recipient")
    # by_recipient only ever holds one phase: past it, there is nothing to undo there.
    if isinstance(sincere_state, dict) and sincere_state.get("phase") == ps["phase"]:
        by_recipient = sincere_state.setdefault("by_recipient", {})
        added = set(ps["added"]["by_recipient"])
        if ps["recipient"] in by_recipient:
            by_recipient[ps["recipient"]] = [o for o in by_recipient[ps["recipient"]] if o not in added]
        for entry in ps["removed"]:
            for holder in entry["holders"]:
                held = by_recipient.setdefault(holder, [])
                if all(normalize_order_spacing(o) != entry["order"] for o in held):
                    held.append(entry["order"])
    own = ps.get("own_pending")
    if own is not None:
        pending, _ = _own_promises(bot_state)
        if own["before"] is None:
            pending.pop(own["key"], None)
        else:
            pending[own["key"]] = list(own["before"])

POWER_TO_ID = {v: k for k, v in COUNTRY_ID_TO_POWER_OR_ALL.items()}

SYSTEM_PROMPT_TEMPLATE = """You are playing {power} in a game of Diplomacy (the classic strategy board game), communicating with other players via in-game chat messages on webDiplomacy.

Style guide, based on real negotiation transcripts from played games:
- Casual, terse, human tone -- not formal or robotic. Real players write things like "okay what's the plan", "i'm going lows", "delightful".
- Use standard Diplomacy province abbreviations (e.g. Bur, Bel, Den, Mun, Tyr) and order shorthand when discussing moves.
- Keep messages short -- a few sentences at most, sometimes just a few words.
- You may negotiate strategically: you don't have to reveal your true orders. It's fine to be vague, propose deals, or mislead if it serves your position -- this is normal and expected in Diplomacy.
- Never break character or mention that you are an AI, a language model, or that you are "playing a role."
- Always reply in the same language as the incoming message (e.g. if it's written in French, reply in French).

Parsimony -- this matters as much as the style guide:
- Your plan below is private. Disclose only the specific piece needed to make the deal under discussion credible, and nothing more.
- Never list your full set of orders, never enumerate all your units, and never volunteer what you intend anywhere the counterpart did not ask about.
- Say nothing about the units or fronts that are not part of the deal being discussed. Silence and vagueness are normal answers.
- Never reveal what you believe another power intends to do, or what another power told you.
- Never reveal what you promised to another power, nor that you are breaking a promise made to someone else.

{plan_section}{commitments_section}{own_record_section}{trust_section}Not every incoming message needs a reply. Real players don't reply to every single message -- simple acknowledgments, farewells, "sounds good", "will do", "talk later" type messages usually don't need a further response, especially if nothing new needs to be said. Be willing to end a conversation -- do not manufacture a response just to keep talking.

OUTPUT FORMAT -- output ONLY a JSON object, no other text and no markdown fences:
{{"reply": "<your message, or null if no reply is needed>", "sincere": ["<order>", ...], "betray": ["<earlier promised order>", ...]}}

"sincere" is PRIVATE -- it is never shown to anyone and never sent as a message. It is read by your own strategic engine. List the orders you have just genuinely committed to and actually intend to play this turn, and nothing else:
- Every entry MUST be an order taken from your plan above, in the exact notation shown there. Never invent an order that does not appear there.
- Include an order only if you both stated/implied it to the counterpart AND truly mean to play it.
- If you bluffed, stayed vague, promised nothing concrete, or said something you do not intend to honour, leave it out. An empty list is the correct and common answer.
- Never include the counterpart's orders. Only your own.
- One order per unit. If an order here differs from a promise listed under "Promises you have already made this phase" above, you are breaking that promise: list the earlier order in "betray". Without it your engine treats the new order as a slip, ignores it, and keeps the earlier promise.

"betray" is PRIVATE too and almost always []. List there only an earlier promise from this phase (exact notation, from the list above) that you have decided to break, and only when "sincere" contains the order replacing it for the same unit. Your engine honours the switch only if what it would play when held to the replacing order is worth clearly more (by more than {margin}) than what it would play when held to the promise, and only if it would then actually play the replacing order; otherwise the earlier promise stands. Never use it for a bluff: if you merely told someone a different story without meaning it, leave both lists alone. If "reply" is null, both lists are ignored.

Bluffing in "reply" is entirely legitimate. What must never happen is a bluff appearing in "sincere" -- that list is your real intention, and acting against your own interest because of it is the one outcome to avoid."""


def load_state():
    return _read_json_file(STATE_FILE)


def save_state(state):
    _write_json_file(STATE_FILE, state)


def _extract_json_object(text: str) -> Optional[str]:
    """Best-effort slice of the outermost {...} substring, or None if there isn't one."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _parse_reply_json(text: str) -> Optional[dict]:
    """Parse the model's reply JSON, tolerating stray prose around the object.

    Claude occasionally prefixes its JSON with meta-commentary (observed in
    practice: "This isn't an agent-messaging task -- I just need to produce
    the JSON reply..."), which breaks a strict json.loads(text). Recovers by
    locating the outermost {...} substring and parsing just that. Returns None
    if no valid JSON object can be recovered at all -- callers must never fall
    back to sending `text` itself in that case (see generate_reply).
    """
    for candidate in (text, _extract_json_object(text)):
        if candidate is None:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def generate_reply(
    power: str,
    sender: str,
    board_state_text: str,
    phase: str,
    incoming_message: str,
    plan_section: str = "",
    trust_section: str = "",
    commitments_section: str = "",
    own_record_section: str = "",
):
    user_prompt = f"""Current phase: {phase}.

Board state:
{board_state_text}

Incoming message from {sender}:
"{incoming_message}"

Decide whether to reply to {sender} as {power}, following the instructions in your system prompt."""

    result = subprocess.run(
        [
            "claude", "-p", user_prompt,
            "--model", MODEL,
            "--system-prompt", SYSTEM_PROMPT_TEMPLATE.format(
                power=power,
                margin=COMMITMENT_SWITCH_MARGIN,
                plan_section=plan_section,
                trust_section=trust_section,
                commitments_section=commitments_section,
                own_record_section=own_record_section,
            ),
            "--output-format", "json",
            "--allowedTools", "",
            "--max-budget-usd", "0.20",
        ],
        cwd=CLAUDE_WORKDIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = _claude_result_text(result.stdout)

    obj = _parse_reply_json(text)
    if obj is None:
        # Fail-safe: never send unparsed text to the player. It was observed
        # sending raw model chatter verbatim ("This isn't an agent-messaging
        # task -- I just need to produce the JSON reply...") as if it were the
        # bot's in-character message -- both breaking character and leaking
        # the "sincere" field's contents/schema. Silence is always a valid,
        # safe answer (the system prompt says as much), so degrade to that
        # instead of to whatever garbage came out.
        print(f"  reply JSON unparsable, staying silent this cycle: {text!r}", flush=True)
        return NO_REPLY_TOKEN, [], []

    reply = obj.get("reply")
    sincere = [
        normalize_order_spacing(o) for o in (obj.get("sincere") or []) if isinstance(o, str)
    ]
    # "betray" absent or malformed (not a list, or an entry that is not a
    # string) is no label at all: a half-read list must never break a promise.
    betray = obj.get("betray")
    if not isinstance(betray, list) or not all(isinstance(o, str) for o in betray):
        betray = []
    betray = [normalize_order_spacing(o) for o in betray]
    if not reply or not str(reply).strip():
        # Nothing was said to the counterpart, so nothing was promised and
        # nothing broken: neither list is kept.
        if sincere or betray:
            print(f"  no reply: sincere {sincere} and betray {betray} ignored", flush=True)
        return NO_REPLY_TOKEN, [], []
    return str(reply).strip(), sincere, betray


def get_active_games(api_key: str):
    resp = get_req(API_URL, {"route": ACTIVE_GAMES_ROUTE}, api_key)
    return json.loads(resp.content).get("games", [])


def process_bot(api_key: str, state: dict):
    for g in get_active_games(api_key):
        game_id = g["gameID"]
        country_id = g["countryID"]
        if g.get("variantID") != 1:
            continue  # classic only for now

        state_key = f"{api_key}:{game_id}"
        bot_state = state.setdefault(state_key, {"replied_ts": [], "exchange_counts": {}})
        replied_ts = set(bot_state["replied_ts"])
        exchange_counts = bot_state["exchange_counts"]

        def checkpoint():
            # Flush to disk after every state-changing step, not once per full
            # 7-bot cycle. main() previously only called save_state() after the
            # whole cycle, so killing the container mid-cycle (e.g. for a
            # redeploy) silently lost that cycle's replied_ts -- on restart,
            # already-answered messages looked unanswered again and got
            # re-replied-to, duplicating the whole conversation for the player.
            # save_state() is a small JSON write; calling it this often is cheap.
            #
            # Both files are checked first: if the commitments file has become
            # unreadable since the head of the cycle, the state is not written
            # either and the cycle stops there (UnreadableStateFile).
            check_state_files()
            bot_state["replied_ts"] = list(replied_ts)
            bot_state["exchange_counts"] = exchange_counts
            save_state(state)

        ctx = Context(gameID=game_id, countryID=country_id, api_url=API_URL, api_key=api_key)
        status_json = get_status_json(ctx)
        if status_json is None:
            continue
        # Read before webdip_state_to_game, which deletes the messages from the JSON.
        sent_on_site = _messages_sent_by(status_json, country_id) if "pending_send" in bot_state else []
        game = webdip_state_to_game(status_json)
        my_power = COUNTRY_ID_TO_POWER_OR_ALL[country_id]
        phase = game.get_current_phase()
        board_state_text = StateFlattener(version=2).flatten_state(game.get_state(), phase)

        # ------------------------------------------------------------------
        # Send journal (one pending_send per bot and per game). A reply goes out
        # in this order: the state first -- by_recipient and own_promises as the
        # reply leaves them, plus pending_send, which says what is being sent and
        # how to undo it --, then the commitments file, then the attempt counted
        # in the state, then the request (post_pending_send). An attempt is thus
        # counted only when the request is made: if the commitments file cannot
        # be written, the bot goes silent (UnreadableStateFile) with pending_send
        # at 0 attempt, and posts the reply once the file can be written again.
        # The request is then classified (_send_outcome):
        #   sent      -> the message is marked answered, the exchange counted, its
        #                timeSent noted in sent_ts, pending_send cleared;
        #   muted     -> nothing was stored: the commitments are undone, the
        #                message marked answered, the exchange not counted;
        #   uncertain -> pending_send stays. Nothing is posted again on the spot,
        #                and no other message of this game is handled by this bot
        #                until it is settled, at the head of a later cycle, by
        #                reading the game's messages back (settle_pending_send).
        # pending_send is on disk before the request: a process killed between
        # the request and its confirmation finds it at the next start, and reads
        # the messages back before it posts anything.
        # The lines that announce a change of commitment ([betrayal], [revision],
        # "sincere commitments ->") are kept in pending_send["journal"] and printed
        # by confirm_send only, once the send is confirmed and the state written:
        # a reply that is muted or given up prints none of them, one confirmed at
        # a later cycle prints them at that cycle. The refusals ([double-deal],
        # [betrayal-refused], [betrayal-ignored]) change nothing and are printed
        # as the reply is read.
        # ------------------------------------------------------------------
        def confirm_send(ps, time_sent):
            journal = ps.get("journal", [])
            replied_ts.add(ps["ts"])
            pair = f"{ps['phase']}:{my_power}<->{ps['recipient']}"
            exchange_counts[pair] = exchange_counts.get(pair, 0) + 1
            _sent_ts(bot_state)  # a damaged sent_ts is cleaned before it is appended to
            bot_state.setdefault("sent_ts", []).append(_sent_mark(time_sent, ps["recipient"], ps["text"]))
            del bot_state["pending_send"]
            checkpoint()
            for line in journal:
                print(line, flush=True)

        def drop_send(ps):
            # The commitments file first, the state (which still holds pending_send)
            # last: if either write fails, pending_send is still on disk and the
            # undoing is done again, to the same result.
            _undo_send_in_commitments(game_id, my_power, ps)
            _undo_send_in_state(bot_state, ps)
            replied_ts.add(ps["ts"])
            del bot_state["pending_send"]
            checkpoint()

        def post_pending_send(ps, note=None) -> bool:
            """Post the pending reply and classify the answer. False: still uncertain.

            `note` is printed once the request is about to be made, not before:
            a cycle stopped by a file that cannot be written prints nothing.
            """
            _apply_send_to_commitments(game_id, my_power, ps)
            ps["attempts"] += 1
            checkpoint()
            if note:
                print(note, flush=True)
            msg_json = {
                "gameID": game_id,
                "countryID": country_id,
                "toCountryID": POWER_TO_ID[ps["recipient"]],
                "message": ps["text"],
            }
            try:
                resp = post_req(API_URL, {"route": SEND_MESSAGE_ROUTE}, msg_json, api_key)
                outcome, detail = _send_outcome(resp)
            except Exception as e:
                outcome, detail = "uncertain", f"{type(e).__name__}: {e}"
            if outcome == "sent":
                # After the journal, and like it once the state is written: if that
                # write fails, the reply is reported at a later cycle ([send-confirmed]).
                confirm_send(ps, detail)
                print(f"  sent (status=200): {ps['text']!r}", flush=True)
                return True
            if outcome == "muted":
                # Printed once the undoing is written, as [send-failed] below.
                drop_send(ps)
                print(
                    f"  [send-muted] {ps['recipient']} has muted {my_power}: nothing was stored "
                    f"(status=200, no message returned). Not sent, not counted as an exchange, "
                    f"commitments of this reply undone: {ps['text']!r}",
                    flush=True,
                )
                return True
            print(
                f"  [send-uncertain] reply to {ps['recipient']} not confirmed ({detail}), attempt "
                f"{ps['attempts']}/{MAX_SEND_ATTEMPTS}. Not posted again now: the game's messages "
                f"are read back at the next cycles; no other message of game {game_id} is handled "
                f"by {my_power} meanwhile: {ps['text']!r}",
                flush=True,
            )
            return False

        def settle_pending_send(ps) -> bool:
            """Settle an unconfirmed send from the messages of the game. False: still pending."""
            who = f"[{api_key}/{my_power}] game {game_id}:"
            if not _valid_pending_send(ps):
                # Hand-edited or damaged state: it can be neither confirmed nor
                # undone. Its reply may have been stored: if the message it answers
                # can still be told, it is marked answered, never answered again
                # blindly. Nothing else is undone.
                ts_answered = ps.get("ts") if isinstance(ps, dict) else None
                if _whole(ts_answered) and ts_answered >= 0:
                    ts_answered = str(ts_answered)  # written as a number: the same message
                if isinstance(ts_answered, str) and ts_answered.isdigit():
                    replied_ts.add(ts_answered)
                    outcome = (
                        f"message {ts_answered} marked answered and not answered again, "
                        f"nothing else undone"
                    )
                else:
                    outcome = (
                        "WARNING: the message it answered cannot be told, it may be answered "
                        "a second time; nothing undone"
                    )
                del bot_state["pending_send"]
                checkpoint()
                print(f"{who} [send-failed] malformed pending_send dropped ({outcome}): {ps!r}", flush=True)
                return True
            if ps["attempts"] == 0:
                # Written to the state but never posted (the commitments file could
                # not be written, or the process stopped before the request): there
                # is nothing to look for in the game's messages.
                if ps["phase"] != phase:
                    drop_send(ps)
                    print(
                        f"{who} [send-failed] reply to {ps['recipient']} was never posted and the "
                        f"phase has moved on from {ps['phase']} to {phase}. Given up, not counted "
                        f"as an exchange, commitments of this reply undone: {ps['text']!r}",
                        flush=True,
                    )
                    return True
                return post_pending_send(ps, note=(
                    f"{who} [send-resume] reply to {ps['recipient']} was recorded but never "
                    f"posted: posting it now"
                ))
            time_sent = _find_pending_send(
                ps, sent_on_site, POWER_TO_ID[ps["recipient"]], _sent_ts(bot_state)
            )
            if time_sent is not None:
                print(
                    f"{who} [send-confirmed] reply to {ps['recipient']} found in the game's "
                    f"messages (timeSent={time_sent}): {ps['text']!r}",
                    flush=True,
                )
                _apply_send_to_commitments(game_id, my_power, ps)
                confirm_send(ps, time_sent)
                return True
            ps["rereads"] += 1
            if ps["rereads"] < SEND_REREADS_BEFORE_RETRY:
                print(
                    f"{who} [send-pending] reply to {ps['recipient']} not in the game's messages "
                    f"(reread {ps['rereads']}/{SEND_REREADS_BEFORE_RETRY}), waiting",
                    flush=True,
                )
                checkpoint()
                return False
            if ps["phase"] == phase and ps["attempts"] < MAX_SEND_ATTEMPTS:
                ps["rereads"] = 0
                return post_pending_send(ps, note=(
                    f"{who} [send-retry] reply to {ps['recipient']} still not in the game's "
                    f"messages after {SEND_REREADS_BEFORE_RETRY} rereads: posting the same text again"
                ))
            why = (
                f"the phase has moved on from {ps['phase']} to {phase}" if ps["phase"] != phase
                else f"{ps['attempts']} attempts"
            )
            # Printed once, when the undoing is written: if a file cannot be
            # written, nothing is undone yet and the cycle stops in drop_send.
            drop_send(ps)
            print(
                f"{who} [send-failed] reply to {ps['recipient']} never reached the game's messages "
                f"({why}). Given up, not counted as an exchange, commitments of this reply "
                f"undone: {ps['text']!r}",
                flush=True,
            )
            return True

        # Before anything else is read or scored: a promise whose message is not
        # known to have gone out must be neither judged nor built upon.
        if "pending_send" in bot_state and not settle_pending_send(bot_state["pending_send"]):
            continue

        # Score any promises made to us in phases that have since resolved, and
        # load the plan our own search engine currently intends for this phase.
        trust = verify_promises(game, game_id, my_power, bot_state)
        # Same for the promises we made ourselves: our own record, per recipient.
        own_record = verify_own_promises(game, my_power, phase, bot_state)
        own_pending, _ = _own_promises(bot_state)
        checkpoint()  # persists trust/pending_promises/own_promises before any further processing can be interrupted
        plan_section = build_plan_section(game_id, phase, my_power)
        plan_entry = load_plans(str(game_id), phase, my_power)
        plans = (plan_entry or {}).get("plans", [])
        order_values = (plan_entry or {}).get("order_values")
        # The engine's candidate table and search parameters, for the third
        # condition of a declared betrayal (would the engine play the new order?).
        candidates = (plan_entry or {}).get("candidates")
        search = (plan_entry or {}).get("search")

        # What we have already sincerely committed to, per counterpart, THIS phase.
        # Reset on phase change so last turn's promises don't constrain this one.
        sincere_state = bot_state.setdefault("sincere_by_recipient", {})
        if sincere_state.get("phase") != phase:
            sincere_state.clear()
            sincere_state["phase"] = phase
        by_recipient = sincere_state.setdefault("by_recipient", {})

        pending = [
            (ts, m) for ts, m in game.messages.items()
            if m["recipient"] == my_power and m["sender"] != my_power and str(ts) not in replied_ts
        ]

        unsettled = False  # a send of this cycle is not confirmed
        for ts, m in pending:
            pair_key = f"{phase}:{my_power}<->{m['sender']}"
            count = exchange_counts.get(pair_key, 0)
            if count >= MAX_EXCHANGES_PER_PAIR_PER_PHASE:
                print(f"[{api_key}/{my_power}] game {game_id}: skipping reply to {m['sender']} (max exchanges reached for {phase})", flush=True)
                replied_ts.add(str(ts))
                checkpoint()
                continue

            print(f"[{api_key}/{my_power}] game {game_id}: replying to {m['sender']}: {m['message']!r}", flush=True)
            # Claude is not called for a reply that could not be recorded.
            check_state_files()
            try:
                reply_text, sincere, betray = generate_reply(
                    my_power, m["sender"], board_state_text, phase, m["message"],
                    plan_section=plan_section,
                    trust_section=build_trust_section(trust, m["sender"]),
                    commitments_section=build_commitments_section(
                        by_recipient, m["sender"], plans, order_values,
                        candidates=candidates, search=search,
                    ),
                    own_record_section=build_own_record_section(own_record, m["sender"]),
                )
            except Exception as e:
                print(f"  Claude generation failed: {e}", flush=True)
                continue

            # The Claude call can last two minutes: check again before anything is
            # recorded or sent. If a file has become unreadable meanwhile, the
            # cycle stops here with nothing mutated and the message still pending.
            check_state_files()

            # Never record an impossible/illegal order as a commitment -- neither
            # a unit we don't control nor a move that isn't legal for it. Applied
            # here, upstream of everything (contradiction-checking, by_recipient,
            # pseudo_commitments.json), so nothing downstream ever has to know
            # this class of bug exists. legal_commitments() is the exact same
            # check the orders container applies before using a commitment, kept
            # in one place so both sides agree on what "legal" means.
            illegal_sincere = [o for o in sincere if o not in legal_commitments(game, my_power, [o])]
            if illegal_sincere:
                print(f"  [filtered] illegal/impossible sincere order(s) dropped: {illegal_sincere}", flush=True)
            sincere = legal_commitments(game, my_power, sincere)

            # Sincere intentions only -- bluffs stay out, so the order-side bias
            # can never make a lie self-fulfilling.
            # Enforce single-mindedness mechanically: telling the prompt not to
            # double-deal is not enough (observed doing it anyway). First sincere
            # promise for a unit wins; a later contradicting one is demoted to a
            # bluff -- the message still goes out, the engine just never sees it --
            # unless the bot declared the betrayal ("betray"), the plan is
            # clearly better and the engine would then play the new order. Two
            # different orders for one unit in the same list are both bluffs.
            # "betray" stops here: only the reconciled sincere orders are written
            # for the engine.
            sincere, demoted, superseded, conflicting, ignored = _reject_contradictions(
                sincere, by_recipient, plans, betray=betray, order_values=order_values,
                candidates=candidates, search=search,
            )
            for orders in conflicting:
                print(
                    f"  [double-deal] {my_power} told {m['sender']} {' and '.join(repr(o) for o in orders)} "
                    f"for the same unit in one message -- recording none of them, "
                    f"treating them as bluffs",
                    flush=True,
                )
            for label, reason in ignored:
                why = {
                    "no_such_promise": "is not a promise made this phase",
                    "no_replacement": "comes with no sincere order replacing it",
                    "conflicting": "comes with more than one sincere order for that unit",
                    "restated": "is restated as sincere in the same reply",
                }[reason]
                print(
                    f"  [betrayal-ignored] {my_power} listed {label!r} as broken (to {m['sender']}) "
                    f"but it {why} ({reason}) -- label ignored",
                    flush=True,
                )
            for order, earlier, reason, gain in demoted:
                if reason == "undeclared":
                    print(
                        f"  [double-deal] {my_power} told {m['sender']} {order!r} but already "
                        f"committed {earlier!r} earlier this phase -- keeping the earlier one, "
                        f"treating this as a bluff",
                        flush=True,
                    )
                else:
                    why = {
                        "unknown_value": "the value of one of the two, or the engine's candidate "
                                         "table, is unknown",
                        "below_margin": f"value gain {gain:+.4f} is not above the margin "
                                        f"{COMMITMENT_SWITCH_MARGIN}" if gain is not None else "",
                        "not_played": f"value gain {gain:+.4f} is above the margin but the engine "
                                      f"would still not play {order!r} once it replaces the promise"
                                      if gain is not None else "",
                    }[reason]
                    print(
                        f"  [betrayal-refused] {my_power} declared {earlier!r} broken in favour of "
                        f"{order!r} for {m['sender']}, but {why} ({reason}) -- keeping the "
                        f"earlier one, treating this as a bluff",
                        flush=True,
                    )
            # A declared betrayal backed by a clearly better plan the engine would
            # play: drop the earlier promise everywhere (one tuple per recipient
            # who was promised it) so the engine stops trying to honour both.
            # Replacing a promise made to the very counterpart being answered
            # follows the same rule but is a revision, not a word broken behind
            # someone's back.
            # The file itself is written after the state (see the send journal).
            journal = []  # lines printed once the send is confirmed (see the send journal)
            revised = set()  # earlier orders already reported as revised for this counterpart
            removed = {}  # earlier order -> the recipients it is dropped for
            for recipient, earlier, order, gain in superseded:
                by_recipient[recipient] = [
                    o for o in by_recipient.get(recipient, []) if normalize_order_spacing(o) != earlier
                ]
                removed.setdefault(earlier, []).append(recipient)
                if recipient == m["sender"]:
                    # Revised with the recipient itself: it no longer counts as
                    # promised to them (dropped from own_pending below, where the
                    # new order is recorded). For a power betrayed it stays in
                    # own_pending -- what they will see is the order played.
                    revised.add(earlier)
                    journal.append(
                        f"  [revision] {my_power} replaces {earlier!r} promised to {recipient} "
                        f"with {order!r} in the same conversation (value gain {gain:+.4f})"
                    )
                else:
                    journal.append(
                        f"  [betrayal] {my_power} drops {earlier!r} promised to {recipient} in favour "
                        f"of {order!r} for {m['sender']} (value gain {gain:+.4f})"
                    )

            added_to_recipient, own_before = [], None
            if sincere:
                journal.append(f"  sincere commitments -> {sincere}")
                by_recipient.setdefault(m["sender"], [])
                added_to_recipient = [o for o in sincere if o not in by_recipient[m["sender"]]]
                by_recipient[m["sender"]] = list(
                    dict.fromkeys(by_recipient[m["sender"]] + sincere)
                )
                # Revision: what is now sincerely said to this counterpart replaces
                # anything else promised to it for the same unit this phase -- in
                # this conversation, or after the earlier order was betrayed in a
                # message to someone else. own_pending keeps at most one order per
                # unit and per recipient, the last one said sincerely.
                own_key = f"{phase}:{m['sender']}"
                own_before = {
                    "key": own_key,
                    "before": list(own_pending[own_key]) if own_key in own_pending else None,
                }
                units = {_order_loc(o): o for o in sincere}
                kept_before = []
                for o in own_pending.get(own_key, []):
                    replacing = units.get(_order_loc(o))
                    if replacing is None or normalize_order_spacing(o) == replacing:
                        kept_before.append(o)
                    elif normalize_order_spacing(o) not in revised:
                        journal.append(
                            f"  [revision] {my_power} now promises {replacing!r} to {m['sender']}: "
                            f"{o!r}, promised to them earlier this phase and dropped since, no "
                            f"longer counts as a promise to them"
                        )
                own_pending[own_key] = list(dict.fromkeys(kept_before + sincere))

            if reply_text == NO_REPLY_TOKEN:
                # generate_reply keeps neither list of a reply that says nothing:
                # nothing was mutated above, nothing is written for the engine.
                print(f"  -> no reply needed", flush=True)
                replied_ts.add(str(ts))
                checkpoint()
                continue

            # What the engine holds for this power once the promises dropped are
            # out: only the orders it does not hold yet are this reply's to undo.
            in_file = [
                o for o in load_commitments_file().get(str(game_id), {}).get(phase, {}).get(my_power, [])
                if normalize_order_spacing(o) not in removed
            ]
            pending_send = bot_state["pending_send"] = {
                "ts": str(ts),
                "recipient": m["sender"],
                "text": reply_text,
                "phase": phase,
                "added": {
                    "by_recipient": added_to_recipient,
                    "commitments": [o for o in sincere if o not in in_file],
                },
                "removed": [{"order": o, "holders": holders} for o, holders in removed.items()],
                "own_pending": own_before,
                "journal": journal,
                "attempts": 0,
                "rereads": 0,
            }
            # The state first: if this write fails, nothing is written for the
            # engine and nothing is sent. Then the commitments file: if that one
            # fails, the reply is not sent either, no attempt is counted, and it
            # is posted once the file can be written (settle_pending_send).
            checkpoint()
            if not post_pending_send(pending_send):
                unsettled = True
                break

        # An unconfirmed send stops everything for this bot in this game until
        # it is settled, the extraction of the counterparts' promises included.
        if unsettled:
            continue

        # Extract both sides' commitments from each conversation this phase:
        #  - ours   -> not used: what is written to pseudo_commitments.json for the
        #              order-side bias (fairdiplomacy/utils/pseudo_commitments.py) is
        #              the sincere channel of generate_reply, see below
        #  - theirs -> pending_promises, scored against their real orders once the
        #              phase resolves, feeding the trust section of the prompt.
        # Only re-run per (phase, opponent) when the transcript has grown since
        # the last extraction, to avoid redundant Claude calls every poll cycle.
        commitment_counts = bot_state.setdefault("commitment_counts", {})
        phase_messages = [
            (ts, m) for ts, m in game.messages.items()
            if m["phase"] == phase and (m["sender"] == my_power or m["recipient"] == my_power)
        ]
        opponents = {m["sender"] if m["sender"] != my_power else m["recipient"] for _, m in phase_messages}
        for opponent in opponents:
            convo = sorted(
                [(ts, m) for ts, m in phase_messages if m["sender"] == opponent or m["recipient"] == opponent],
                key=lambda x: x[0],
            )
            commit_key = f"{phase}:{my_power}<->{opponent}"
            if commitment_counts.get(commit_key, 0) >= len(convo):
                continue

            transcript = "\n".join(f"{m['sender']}: {m['message']}" for _, m in convo)
            try:
                extracted = extract_commitments(my_power, opponent, board_state_text, phase, transcript)
            except Exception as e:
                print(f"  commitment extraction failed for {my_power}<->{opponent}: {e}", flush=True)
                continue
            commitment_counts[commit_key] = len(convo)

            # Only "theirs" is used: our own commitments come from the sincere
            # channel of generate_reply, which knows what was a bluff. A separate
            # extraction pass cannot -- it is a fresh call that never saw the
            # intent behind the message.
            #
            # Filter to what `opponent` could actually legally order -- extraction
            # sometimes attributes one side's own stated move to the other side
            # (observed: Austria said "F TRI - ALB" about its own unit, and the
            # extractor recorded it as ITALY's promise, a unit Italy doesn't even
            # control). Left unfiltered, that becomes an un-keepable "promise"
            # purely from a bookkeeping error, unfairly tanking trust once it's
            # (correctly) never seen in the promiser's actual orders.
            theirs_raw = extracted["theirs"]
            theirs = legal_commitments(game, opponent, theirs_raw)
            if set(theirs_raw) - set(theirs):
                print(f"  [filtered] illegal/impossible promise(s) from {opponent} dropped: {sorted(set(theirs_raw) - set(theirs))}", flush=True)
            if theirs:
                print(
                    f"[{api_key}/{my_power}] game {game_id}: {opponent} promised {theirs}",
                    flush=True,
                )
                pending = bot_state.setdefault("pending_promises", {})
                key = f"{phase}:{opponent}"
                pending[key] = list(dict.fromkeys(pending.get(key, []) + theirs))

            checkpoint()  # persists commitment_counts/pending_promises, mutated in place above

        bot_state["commitment_counts"] = commitment_counts


def run_cycle(state: Optional[dict]) -> Optional[dict]:
    """One polling cycle. Returns the state to carry into the next cycle.

    Both state files are read before any bot is processed. If either is there
    but unreadable, the bot stays alive and silent: no message is read, Claude
    is not called, nothing is sent and nothing is written, so the file is never
    overwritten. The in-memory state is dropped (None is returned) and loaded
    again from disk on the first cycle where both files are readable -- exiting
    instead would only make the container restart in a loop.

    While the files are readable the in-memory state is kept from one cycle to
    the next, as before: the state file is read here only to check it.
    """
    try:
        on_disk = check_state_files()
        if state is None:
            state = on_disk
        for api_key in API_KEYS:
            try:
                process_bot(api_key, state)
            except UnreadableStateFile:
                raise  # not a per-bot error: stop the whole cycle, see below
            except Exception as e:
                print(f"[{api_key}] unexpected error: {e}", flush=True)
        save_state(state)
    except UnreadableStateFile as e:
        print(f"[silent] {e}", flush=True)
        return None
    return state


def main():
    print(f"Claude dialogue bot loop starting. Polling every {POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.", flush=True)
    state = None
    while True:
        state = run_cycle(state)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
