#!/usr/bin/env bash
###############################################################################
#  .claude/hooks/journal_agents.sh  --  HOOK SubagentStop DE CLAUDE CODE
#
#  Ajoute une ligne JSON par sous-agent termine a
#  .claude/journal-agents.jsonl (non versionne) : date, agent, identifiant,
#  modeles servis, nombre d'appels au modele, contexte au dernier appel
#  (tokens d'entree, cache compris) et duree, lus dans le transcript du
#  sous-agent. Sert a calibrer la politique de routage
#  (docs/agents/routage.md, § 7 et § 8) et a relever le modele servi, que la
#  session principale compare au modele demande (non visible du hook, § 5.3).
#
#  Ne mesure ni l'effort (non expose dans le transcript) ni les tokens de
#  sortie (valeurs partielles de streaming dans le transcript). Le transcript
#  est ecrit de facon asynchrone : appels et contexte sont des minorants
#  possibles.
#  N'echoue jamais et n'ecrit rien sur la sortie standard : une session sans
#  Python, ou un transcript illisible, se poursuit sans journal.
###############################################################################

entree="$(cat)"
racine="${CLAUDE_PROJECT_DIR:-$(pwd)}"

py=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import json" >/dev/null 2>&1; then py="$c"; break; fi
done
[ -n "$py" ] || exit 0

ENTREE="$entree" JOURNAL="$racine/.claude/journal-agents.jsonl" "$py" - <<'PY' >/dev/null 2>&1 || true
import json, os
from datetime import datetime, timezone

e = json.loads(os.environ.get("ENTREE") or "{}")
aid = e.get("agent_id") or ""
chemin = e.get("agent_transcript_path") or ""
if not chemin and aid and e.get("transcript_path"):
    base = e["transcript_path"][:-len(".jsonl")] if e["transcript_path"].endswith(".jsonl") else e["transcript_path"]
    chemin = os.path.join(base, "subagents", "agent-%s.jsonl" % aid)

agent = e.get("agent_type") or ""
if not agent and chemin:
    try:
        agent = json.load(open(chemin[:-len(".jsonl")] + ".meta.json", encoding="utf-8")).get("agentType", "")
    except Exception:
        pass

modeles, ids, contexte, debut, fin = [], set(), None, None, None
if chemin and os.path.exists(chemin):
    for ligne in open(chemin, encoding="utf-8"):
        try:
            d = json.loads(ligne)
        except Exception:
            continue
        t = d.get("timestamp")
        if t:
            debut = debut or t
            fin = t
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        if (m.get("model") or "").startswith("<"):
            continue  # message <synthetic> : aucun appel au modele
        if m.get("model") and m["model"] not in modeles:
            modeles.append(m["model"])
        if m.get("id"):
            ids.add(m["id"])
        u = m.get("usage") or {}
        if u:
            contexte = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))

def iso(x):
    return datetime.fromisoformat(x.replace("Z", "+00:00"))

duree = None
if debut and fin:
    try:
        duree = round((iso(fin) - iso(debut)).total_seconds())
    except Exception:
        pass

ligne = {
    "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "session": e.get("session_id", ""),
    "agent": agent,
    "id": aid,
    "modeles": modeles,
    "appels": len(ids),
    "contexte_final": contexte,
    "duree_s": duree,
}
with open(os.environ["JOURNAL"], "a", encoding="utf-8") as f:
    f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
PY
exit 0
