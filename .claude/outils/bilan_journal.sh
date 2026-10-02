#!/usr/bin/env bash
###############################################################################
#  .claude/outils/bilan_journal.sh  --  bilan du journal des sous-agents
#
#  Agrege .claude/journal-agents.jsonl (hook SubagentStop) par agent et par
#  modele servi : nombre de sous-agents, reprises, appels au modele, contexte
#  au dernier appel (moyenne et maximum), duree. Une reprise (SendMessage)
#  ajoute une ligne cumulative pour le meme (session, id) : seule la derniere
#  est retenue, les precedentes sont comptees comme reprises ; sa duree
#  inclut l'attente entre les executions. Sert a la calibration de
#  docs/agents/routage.md, § 8. Aucune donnee de consommation n'est estimee :
#  seules les grandeurs lues dans les transcripts sont restituees.
#
#  Usage : bash .claude/outils/bilan_journal.sh [journal]
###############################################################################
set -euo pipefail
racine="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
journal="${1:-$racine/.claude/journal-agents.jsonl}"
[ -s "$journal" ] || { echo "Journal vide ou absent : $journal"; exit 0; }
py=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import json" >/dev/null 2>&1; then py="$c"; break; fi
done
[ -n "$py" ] || { echo "Python introuvable : bilan impossible."; exit 1; }
"$py" - "$journal" <<'PY'
import json, sys
from collections import defaultdict
der, nb = {}, defaultdict(int)
for l in open(sys.argv[1], encoding="utf-8"):
    try:
        d = json.loads(l)
    except Exception:
        continue
    k = (d.get("session"), d.get("id")) if d.get("id") else (None, len(der))
    der[k] = d
    nb[k] += 1
g = defaultdict(list)
for k, d in der.items():
    d["_reprises"] = nb[k] - 1
    g[(d.get("agent") or "?", ",".join(d.get("modeles") or ["?"]))].append(d)
print("%-24s %-28s %5s %8s %7s %12s %12s %9s" % ("agent", "modele(s) servi(s)", "n", "reprises", "appels", "ctx moyen", "ctx max", "duree moy"))
for (a, m), v in sorted(g.items()):
    ctx = [x["contexte_final"] for x in v if x.get("contexte_final") is not None]
    du = [x["duree_s"] for x in v if x.get("duree_s") is not None]
    print("%-24s %-28s %5d %8d %7d %12s %12s %9s" % (a, m[:28], len(v), sum(x["_reprises"] for x in v),
          sum(x.get("appels") or 0 for x in v),
          round(sum(ctx)/len(ctx)) if ctx else "-", max(ctx) if ctx else "-", "%ds" % round(sum(du)/len(du)) if du else "-"))
PY
