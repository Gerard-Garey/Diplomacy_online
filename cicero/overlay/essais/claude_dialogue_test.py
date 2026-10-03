import json
import subprocess

SYSTEM_PROMPT = """You are playing FRANCE in a game of Diplomacy (the classic strategy board game), communicating with other players via in-game chat messages on webDiplomacy.

Style guide, based on real negotiation transcripts from played games:
- Casual, terse, human tone -- not formal or robotic. Real players write things like "okay what's the plan", "i'm going lows", "delightful".
- Use standard Diplomacy province abbreviations (e.g. Bur, Bel, Den, Mun, Tyr) and order shorthand (e.g. "NWS NTH Edi" for Fleet North Sea, Fleet Edinburgh) when discussing moves.
- Keep messages short -- a few sentences at most, sometimes just a few words.
- You may negotiate strategically: you don't have to reveal your true orders. It's fine to be vague, propose deals, or mislead if it serves your position -- this is normal and expected in Diplomacy.
- Never break character or mention that you are an AI, a language model, or that you are "playing a role."

Example real messages from past games (for tone/style calibration only, not content to copy):
- "Hi Austria, just reaching out to establish early comms. I know we don't interact super early, but our fates are pretty intertwined in the endgame. Let's keep in touch and share intel where we can!"
- "Hey Germany! Do you wanna open to Den and then bounce Russia in Swe? I think it is the best way for us to slow down Russia's growth."
- "okay what's the plan"
- "you should go aggressive against russia\""""

USER_PROMPT = """Current phase: Spring 1901, Movement.

Board state:
units: Austria: A BUD, A VIE, F TRI; England: F EDI, F LON, A LVP; France: A PAR, A MAR, F BRE; Germany: A BER, A MUN, F KIE; Italy: A ROM, A VEN, F NAP; Russia: A MOS, A WAR, F SEV, F STP/SC; Turkey: A CON, A SMY, F ANK
centers: Austria: BUD, VIE, TRI; England: EDI, LON, LVP; France: PAR, MAR, BRE; Germany: BER, MUN, KIE; Italy: ROM, VEN, NAP; Russia: MOS, WAR, SEV, STP; Turkey: CON, SMY, ANK

Your real intended orders this phase (private -- do not necessarily reveal): F BRE - MAO, A PAR - PIC, A MAR - SPA

Message history with England (most recent last):
England: "Hi France, want to work together against Germany this game? I'm thinking I open north, you take the west coast."

Write your reply to England as France. Output ONLY the message text, nothing else -- no preamble, no explanation."""

WORKDIR = "/opt/claude_dialogue_workdir"

result = subprocess.run(
    [
        "claude", "-p", USER_PROMPT,
        "--model", "sonnet",
        "--system-prompt", SYSTEM_PROMPT,
        "--output-format", "json",
        "--allowedTools", "",
        "--max-budget-usd", "0.20",
    ],
    cwd=WORKDIR,
    capture_output=True,
    text=True,
    timeout=120,
)

print("=== stderr ===")
print(result.stderr)
print("=== stdout (raw) ===")
print(result.stdout)

try:
    parsed = json.loads(result.stdout)
    print("=== parsed message ===")
    print(parsed.get("result", "<no 'result' field>"))
    print("=== cost/tokens ===")
    print("cache_creation_input_tokens:", parsed["usage"]["cache_creation_input_tokens"])
    print("cost:", parsed["total_cost_usd"])
except json.JSONDecodeError as e:
    print("Could not parse JSON:", e)
