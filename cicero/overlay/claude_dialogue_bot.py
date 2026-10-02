import os
import json
import subprocess
import time
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
from fairdiplomacy.utils.pseudo_commitments import legal_commitments

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
# before the bot abandons a promise already made to someone else this phase.
# Sized above the noise in the value estimates so it takes a real strategic gain
# to break a given word -- roughly the same scale as the lambda*log(prob)
# tiebreaker (~0.03) that decides ties inside the search itself.
COMMITMENT_SWITCH_MARGIN = 0.02

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
    parsed = json.loads(result.stdout)
    if "result" not in parsed:
        raise RuntimeError(f"Claude call failed: {parsed}")
    text = parsed["result"].strip()
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
            lines.append(f"    - cost {p['cost_vs_best']:+.3f}: {', '.join(p['orders'])}")
        lines.append(
            "  A cost near 0 means that alternative is essentially free: you can genuinely agree to it "
            "if the deal is worth it. A large cost means giving it up would really hurt -- resist, or "
            "extract something substantial in exchange."
        )
    lines.append(
        "  You are not bound by this plan and may still bluff about it. But it is what you currently "
        "intend, so let it inform which deals you accept, refuse, or counter-propose."
    )
    return "\n".join(lines) + "\n\n"


def _order_loc(order: str):
    parts = normalize_order_spacing(order).split()
    return parts[1] if len(parts) > 1 else None


def _best_plan_value(plans: list, order: str):
    """Value of the best exported plan that plays `order`, or None if none does.

    Plan orders are already canonical (they come straight from the search).
    `order` may not be (older persisted state, or a caller that didn't
    normalize) -- normalized here so the comparison can't silently miss.
    """
    order = normalize_order_spacing(order)
    values = [p["value"] for p in plans if order in p["orders"]]
    return max(values) if values else None


def _reject_contradictions(sincere: list, by_recipient: dict, plans: list = None, margin: float = None):
    """Reconcile new sincere orders with what was already promised this phase.

    Returns (accepted, demoted, superseded):
      - demoted:    [(new_order, earlier_order)] -- new promise not recorded, so
                    the message that carried it is a bluff.
      - superseded: [(recipient, earlier_order, new_order, gain)] -- the EARLIER
                    promise is abandoned instead, a deliberate betrayal.

    A later promise only wins when the search values the plan realising it more
    than the best plan honouring the earlier one, by more than `margin`. The
    margin matters: rollout values are noisy estimates, and without it the bot
    would flip-flop between counterparts on estimation noise alone. With no plan
    data (or no valued plan for the new order) we keep the earlier promise --
    we have no evidence the switch is worth a broken word.
    """
    plans = plans or []
    margin = COMMITMENT_SWITCH_MARGIN if margin is None else margin

    # Normalized once here rather than trusting callers/stored state: by_recipient
    # can hold entries persisted before a normalization fix landed (this has
    # happened in practice -- a promise recorded pre-fix must not look like a
    # fresh contradiction against the same promise restated post-fix).
    prior_by_loc = {}
    for recipient, orders in by_recipient.items():
        for o in orders:
            o = normalize_order_spacing(o)
            prior_by_loc.setdefault(_order_loc(o), (o, recipient))

    accepted, demoted, superseded, seen_locs = [], [], [], {}
    for o in sincere:
        o = normalize_order_spacing(o)
        loc = _order_loc(o)
        earlier, recipient = prior_by_loc.get(loc, (None, None))
        if earlier is None:
            earlier, recipient = seen_locs.get(loc, (None, None))

        if earlier is None or earlier == o:
            seen_locs.setdefault(loc, (o, None))
            accepted.append(o)
            continue

        v_new, v_old = _best_plan_value(plans, o), _best_plan_value(plans, earlier)
        if v_new is not None and (v_old is None or v_new - v_old > margin):
            gain = None if v_old is None else v_new - v_old
            superseded.append((recipient, earlier, o, gain))
            prior_by_loc[loc] = (o, recipient)
            seen_locs[loc] = (o, None)
            accepted.append(o)
        else:
            demoted.append((o, earlier))
    return accepted, demoted, superseded


def remove_commitment(game_id: int, phase: str, power: str, order: str) -> None:
    """Drop a superseded promise so the engine stops trying to honour it."""
    data = load_commitments_file()
    orders = data.get(str(game_id), {}).get(phase, {}).get(power)
    if orders and order in orders:
        data[str(game_id)][phase][power] = [o for o in orders if o != order]
        save_commitments_file(data)


def build_commitments_section(sincere_by_recipient: dict, current: str) -> str:
    """Remind the bot what it has already sincerely committed to, and to whom.

    Without this, every reply is a fresh Claude call that cannot know it already
    promised the same unit elsewhere this phase -- the one way it could sincerely
    double-deal by accident rather than by choice.
    """
    if not sincere_by_recipient:
        return ""
    lines = ["Already committed this phase (your real intentions, per counterpart):"]
    for recipient, orders in sincere_by_recipient.items():
        if not orders:
            continue
        who = f"{recipient} (this conversation)" if recipient == current else recipient
        lines.append(f"  - to {who}: {', '.join(orders)}")
    if len(lines) == 1:
        return ""
    lines.append(
        "  Stay consistent with these. If what is being asked now conflicts with one of them, "
        "you must either decline, or deliberately bluff -- and a bluff never goes in \"sincere\"."
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

    resolved = {pd.name: pd for pd in game.get_all_phases()}

    for key in list(pending.keys()):
        phase, counterpart = key.split(":", 1)
        pd = resolved.get(phase)
        if pd is None or not pd.orders.get(counterpart):
            continue  # not resolved yet (or orders not visible) -- check again later

        actual = pd.orders[counterpart]
        actual_norm = {_normalize_order(o) for o in actual}
        try:
            past_game = game.rolled_back_to_phase_start(phase)
            legal_locs = set(past_game.get_orderable_locations().get(counterpart, []))
        except Exception:
            legal_locs = None

        record = trust.setdefault(counterpart, {"kept": 0, "broken": 0, "examples": []})
        for promised in pending.pop(key):
            loc = promised.split()[1] if len(promised.split()) > 1 else None
            if legal_locs is not None and (loc is None or loc not in legal_locs):
                continue  # promise was never actionable; don't hold it against them
            if _normalize_order(promised) in actual_norm:
                record["kept"] += 1
            else:
                record["broken"] += 1
                played = [o for o in actual if len(o.split()) > 1 and o.split()[1] == loc]
                record["examples"].append({
                    "phase": phase,
                    "promised": promised,
                    "actual": played[0] if played else "nothing at " + str(loc),
                })
                print(
                    f"  [trust] {counterpart} broke a promise in {phase}: said {promised!r}, "
                    f"played {played[0] if played else '(nothing there)'}",
                    flush=True,
                )
    return trust


def load_commitments_file():
    if COMMITMENTS_FILE.exists():
        try:
            return json.loads(COMMITMENTS_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_commitments_file(data):
    COMMITMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMMITMENTS_FILE.write_text(json.dumps(data))

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

{plan_section}{commitments_section}{trust_section}Not every incoming message needs a reply. Real players don't reply to every single message -- simple acknowledgments, farewells, "sounds good", "will do", "talk later" type messages usually don't need a further response, especially if nothing new needs to be said. Be willing to end a conversation -- do not manufacture a response just to keep talking.

OUTPUT FORMAT -- output ONLY a JSON object, no other text and no markdown fences:
{{"reply": "<your message, or null if no reply is needed>", "sincere": ["<order>", ...]}}

"sincere" is PRIVATE -- it is never shown to anyone and never sent as a message. It is read by your own strategic engine. List the orders you have just genuinely committed to and actually intend to play this turn, and nothing else:
- Every entry MUST be an order taken from your plan above, in the exact notation shown there. Never invent an order that does not appear there.
- Include an order only if you both stated/implied it to the counterpart AND truly mean to play it.
- If you bluffed, stayed vague, promised nothing concrete, or said something you do not intend to honour, leave it out. An empty list is the correct and common answer.
- Never include the counterpart's orders. Only your own.
- It must not contradict anything already listed under "Already committed this phase" above. You have ONE set of units and can only play one order per unit. Telling two powers different stories is fine -- that is Diplomacy -- but only one of those can be sincere, and the other must be left out of this list. A contradiction here is discarded by your engine and you end up honouring neither.

Bluffing in "reply" is entirely legitimate. What must never happen is a bluff appearing in "sincere" -- that list is your real intention, and acting against your own interest because of it is the one outcome to avoid."""


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


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
                plan_section=plan_section,
                trust_section=trust_section,
                commitments_section=commitments_section,
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
    parsed = json.loads(result.stdout)
    if "result" not in parsed:
        raise RuntimeError(f"Claude call failed: {parsed}")
    text = parsed["result"].strip()

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
        return NO_REPLY_TOKEN, []

    reply = obj.get("reply")
    sincere = [
        normalize_order_spacing(o) for o in (obj.get("sincere") or []) if isinstance(o, str)
    ]
    if not reply or not str(reply).strip():
        return NO_REPLY_TOKEN, sincere
    return str(reply).strip(), sincere


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
            bot_state["replied_ts"] = list(replied_ts)
            bot_state["exchange_counts"] = exchange_counts
            save_state(state)

        ctx = Context(gameID=game_id, countryID=country_id, api_url=API_URL, api_key=api_key)
        status_json = get_status_json(ctx)
        if status_json is None:
            continue
        game = webdip_state_to_game(status_json)
        my_power = COUNTRY_ID_TO_POWER_OR_ALL[country_id]
        phase = game.get_current_phase()
        board_state_text = StateFlattener(version=2).flatten_state(game.get_state(), phase)

        # Score any promises made to us in phases that have since resolved, and
        # load the plan our own search engine currently intends for this phase.
        trust = verify_promises(game, game_id, my_power, bot_state)
        checkpoint()  # persists trust/pending_promises before any further processing can be interrupted
        plan_section = build_plan_section(game_id, phase, my_power)
        plan_entry = load_plans(str(game_id), phase, my_power)
        plans = (plan_entry or {}).get("plans", [])

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

        for ts, m in pending:
            pair_key = f"{phase}:{my_power}<->{m['sender']}"
            count = exchange_counts.get(pair_key, 0)
            if count >= MAX_EXCHANGES_PER_PAIR_PER_PHASE:
                print(f"[{api_key}/{my_power}] game {game_id}: skipping reply to {m['sender']} (max exchanges reached for {phase})", flush=True)
                replied_ts.add(str(ts))
                checkpoint()
                continue

            print(f"[{api_key}/{my_power}] game {game_id}: replying to {m['sender']}: {m['message']!r}", flush=True)
            try:
                reply_text, sincere = generate_reply(
                    my_power, m["sender"], board_state_text, phase, m["message"],
                    plan_section=plan_section,
                    trust_section=build_trust_section(trust, m["sender"]),
                    commitments_section=build_commitments_section(by_recipient, m["sender"]),
                )
            except Exception as e:
                print(f"  Claude generation failed: {e}", flush=True)
                continue

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
            # bluff -- the message still goes out, the engine just never sees it.
            sincere, demoted, superseded = _reject_contradictions(sincere, by_recipient, plans)
            for order, earlier in demoted:
                print(
                    f"  [double-deal] {my_power} told {m['sender']} {order!r} but already "
                    f"committed {earlier!r} earlier this phase -- keeping the earlier one, "
                    f"treating this as a bluff",
                    flush=True,
                )
            # A clearly better plan justifies going back on an earlier promise:
            # drop it everywhere so the engine stops trying to honour both.
            for recipient, earlier, order, gain in superseded:
                by_recipient[recipient] = [o for o in by_recipient.get(recipient, []) if o != earlier]
                remove_commitment(game_id, phase, my_power, earlier)
                print(
                    f"  [betrayal] {my_power} drops {earlier!r} promised to {recipient} in favour "
                    f"of {order!r} for {m['sender']} (value gain "
                    f"{'unknown' if gain is None else f'+{gain:.4f}'})",
                    flush=True,
                )

            if sincere:
                print(f"  sincere commitments -> {sincere}", flush=True)
                by_recipient.setdefault(m["sender"], [])
                by_recipient[m["sender"]] = list(
                    dict.fromkeys(by_recipient[m["sender"]] + sincere)
                )
                commitments_data = load_commitments_file()
                phase_data = commitments_data.setdefault(str(game_id), {}).setdefault(phase, {})
                existing = phase_data.get(my_power, [])
                phase_data[my_power] = list(dict.fromkeys(existing + sincere))
                save_commitments_file(commitments_data)
                checkpoint()  # by_recipient/sincere_state already mutated in place above

            if reply_text == NO_REPLY_TOKEN:
                print(f"  -> no reply needed", flush=True)
                replied_ts.add(str(ts))
                checkpoint()
                continue

            msg_json = {
                "gameID": game_id,
                "countryID": country_id,
                "toCountryID": POWER_TO_ID[m["sender"]],
                "message": reply_text,
            }
            resp = post_req(API_URL, {"route": SEND_MESSAGE_ROUTE}, msg_json, api_key)
            print(f"  sent (status={resp.status_code}): {reply_text!r}", flush=True)
            replied_ts.add(str(ts))
            exchange_counts[pair_key] = count + 1
            checkpoint()

        # Extract both sides' commitments from each conversation this phase:
        #  - ours   -> pseudo_commitments.json, for the (currently disabled)
        #              order-side bias in fairdiplomacy/utils/pseudo_commitments.py
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


def main():
    state = load_state()
    print(f"Claude dialogue bot loop starting. Polling every {POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.", flush=True)
    while True:
        for api_key in API_KEYS:
            try:
                process_bot(api_key, state)
            except Exception as e:
                print(f"[{api_key}] unexpected error: {e}", flush=True)
        save_state(state)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
