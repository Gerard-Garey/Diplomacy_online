import sys
import json
import subprocess

sys.path.insert(0, ".")
from fairdiplomacy_external.webdip_api import (
    get_status_json,
    webdip_state_to_game,
    post_req,
    Context,
    SEND_MESSAGE_ROUTE,
)
from parlai_diplomacy.utils.game2seq.format_helpers.state import StateFlattener

WORKDIR = "/opt/claude_dialogue_workdir"

SYSTEM_PROMPT_TEMPLATE = """You are playing {power} in a game of Diplomacy (the classic strategy board game), communicating with other players via in-game chat messages on webDiplomacy.

Style guide, based on real negotiation transcripts from played games:
- Casual, terse, human tone -- not formal or robotic. Real players write things like "okay what's the plan", "i'm going lows", "delightful".
- Use standard Diplomacy province abbreviations (e.g. Bur, Bel, Den, Mun, Tyr) and order shorthand when discussing moves.
- Keep messages short -- a few sentences at most, sometimes just a few words.
- You may negotiate strategically: you don't have to reveal your true orders. It's fine to be vague, propose deals, or mislead if it serves your position -- this is normal and expected in Diplomacy.
- Never break character or mention that you are an AI, a language model, or that you are "playing a role.\""""

def generate_reply(power: str, sender: str, board_state_text: str, phase: str, incoming_message: str) -> str:
    user_prompt = f"""Current phase: {phase}.

Board state:
{board_state_text}

Incoming message from {sender}:
"{incoming_message}"

Write your reply to {sender} as {power}. Output ONLY the message text, nothing else -- no preamble, no explanation."""

    result = subprocess.run(
        [
            "claude", "-p", user_prompt,
            "--model", "sonnet",
            "--system-prompt", SYSTEM_PROMPT_TEMPLATE.format(power=power),
            "--output-format", "json",
            "--allowedTools", "",
            "--max-budget-usd", "0.20",
        ],
        cwd=WORKDIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    parsed = json.loads(result.stdout)
    return parsed["result"]


def main():
    api_key = "bot1"
    country_id = 5
    game_id = 14
    api_url = "http://localhost:43000/api.php"

    ctx = Context(gameID=game_id, countryID=country_id, api_url=api_url, api_key=api_key)
    status_json = get_status_json(ctx)
    game = webdip_state_to_game(status_json)
    my_power = "AUSTRIA"

    phase = game.get_current_phase()
    flattener = StateFlattener(version=2)
    board_state_text = flattener.flatten_state(game.get_state(), phase)

    id_to_power = {v: k for k, v in {
        "ENGLAND": 1, "FRANCE": 2, "ITALY": 3, "GERMANY": 4, "AUSTRIA": 5, "TURKEY": 6, "RUSSIA": 7,
    }.items()}
    power_to_id = {v: k for k, v in id_to_power.items()}

    pending = [
        (ts, m) for ts, m in game.messages.items()
        if m["recipient"] == my_power and m["sender"] != my_power
    ]
    print(f"Found {len(pending)} pending message(s) for {my_power}")

    for ts, m in pending:
        print(f"Replying to {m['sender']}: {m['message']!r}")
        reply_text = generate_reply(my_power, m["sender"], board_state_text, phase, m["message"])
        print(f"Generated reply: {reply_text!r}")

        msg_json = {
            "gameID": game_id,
            "countryID": country_id,
            "toCountryID": power_to_id[m["sender"]],
            "message": reply_text,
        }
        resp = post_req(api_url, {"route": SEND_MESSAGE_ROUTE}, msg_json, api_key)
        print(f"Send response: {resp.status_code} {resp.content}")


if __name__ == "__main__":
    main()
