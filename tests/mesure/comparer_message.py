"""M4 -- essai d'envoi réel (#5) sur une partie JETABLE : envoi d'un message par l'API,
relecture du statut, comparaison du texte envoyé et du texte relu par _message_key.

Dans un conteneur éphémère de l'image (voir envoi_reel.md) :

    python /mesure/comparer_message.py envoyer GAMEID EXPEDITEUR DESTINATAIRE --confirmer-envoi
    python /mesure/comparer_message.py comparer GAMEID EXPEDITEUR

`envoyer` poste le texte fixe ci-dessous par la route game/sendmessage, avec le
même appel que le bot (post_req), et garde le texte et la réponse du site dans
resultats/m4_envoi_<GAMEID>.json. `comparer` relit le statut (GET) et compare.
La clé du compte est trouvée par le script dans la configuration de l'image ;
elle n'est ni imprimée ni écrite. Les fonctions comparées (_message_key,
_messages_sent_by, _send_outcome) sont celles de l'arbre de travail (apres/).
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import commun  # noqa: E402
from claude_avant_apres import charger_version  # noqa: E402

PARTIE_DE_MESURE = 3  # jamais d'envoi dans la partie qui sert aux mesures
# Accent, esperluette, chevron, saut de ligne, émoji (au-delà de U+FFFF), point d'interrogation.
TEXTE = "Essai d'envoi réel #5 : été à Brest & Kiel, 1 < 2 ?\nseconde ligne \U0001F642 fin"


def fixer_fichiers_de_travail():
    """Les modules du bot lisent ces variables à l'import : jamais le volume de production."""
    os.environ["CICERO_PLANS_FILE"] = str(commun.TRAVAIL / "m4_current_plans.json")
    os.environ["PSEUDO_COMMITMENTS_FILE"] = str(commun.TRAVAIL / "m4_pseudo_commitments.json")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=("envoyer", "comparer"))
    p.add_argument("game_id", type=int)
    p.add_argument("expediteur")
    p.add_argument("destinataire", nargs="?", help="puissance, ou ALL (envoyer seulement)")
    p.add_argument("--confirmer-envoi", action="store_true")
    args = p.parse_args()
    if args.game_id == PARTIE_DE_MESURE:
        raise SystemExit("REFUS : la partie %d est la partie de mesure, pas une partie jetable" % PARTIE_DE_MESURE)
    if not commun.cicero_present():
        raise SystemExit("REFUS : à lancer dans un conteneur de l'image cicero-webdip")

    fixer_fichiers_de_travail()
    racine = Path("/tmp/mesure") if Path("/tmp/mesure/apres").is_dir() else commun.ICI
    bot, _pc, _pe = charger_version("apres", racine / "apres")
    from fairdiplomacy_external.webdip_api import SEND_MESSAGE_ROUTE, get_status_json, post_req

    expediteur = args.expediteur.upper()
    ctx = commun.trouver_contexte(args.game_id, expediteur)
    trace = commun.RESULTATS / ("m4_envoi_%d.json" % args.game_id)

    if args.action == "envoyer":
        if not args.confirmer_envoi or not args.destinataire:
            raise SystemExit("REFUS : `envoyer` écrit dans la partie %d ; donner le destinataire et --confirmer-envoi" % args.game_id)
        vers = bot.POWER_TO_ID[args.destinataire.upper()]
        corps = {"gameID": args.game_id, "countryID": ctx.countryID, "toCountryID": vers, "message": TEXTE}
        reponse = post_req(ctx.api_url, {"route": SEND_MESSAGE_ROUTE}, corps, ctx.api_key)
        issue, detail = bot._send_outcome(reponse)
        commun.ecrire_json(trace, {
            "game_id": args.game_id, "expediteur": expediteur, "countryID": ctx.countryID, "toCountryID": vers,
            "texte": TEXTE, "statut_http": reponse.status_code, "reponse": reponse.text[:2000],
            "issue_selon_send_outcome": issue, "detail": str(detail),
        })
        print("texte envoyé       : %r" % TEXTE)
        print("statut HTTP        : %s" % reponse.status_code)
        print("réponse du site    : %s" % reponse.text[:500])
        print("_send_outcome      : %s (%s)" % (issue, detail))
        print("trace              : %s" % trace)
        return

    envoye = json.loads(trace.read_text())["texte"] if trace.exists() else TEXTE
    statut = get_status_json(ctx)
    brut = [
        m.get("message") for ph in statut.get("phases", []) for m in ph.get("messages", [])
        if m.get("fromCountryID") == ctx.countryID
    ]
    relus = bot._messages_sent_by(statut, ctx.countryID)  # [(timeSent, toCountryID, texte décodé)]
    cle = bot._message_key(envoye)
    print("texte envoyé       : %r" % envoye)
    print("clé du texte envoyé: %r" % cle)
    print("messages de %s dans le statut : %d" % (expediteur, len(relus)))
    for texte_brut in brut:
        print("  tel que rendu par le site : %r" % texte_brut)
    egaux = 0
    for time_sent, vers, texte in relus:
        meme_cle, meme_texte = bot._message_key(texte) == cle, texte == envoye
        egaux += 1 if meme_cle else 0
        perdus = sorted(set(envoye) - set(texte))
        print("  timeSent %s vers %s : décodé %r" % (time_sent, vers, texte))
        print("    même clé (_message_key) : %s ; texte décodé identique : %s ; caractères envoyés absents du texte relu : %r"
              % (meme_cle, meme_texte, perdus))
    verdict = "RETROUVÉ une fois" if egaux == 1 else ("NON RETROUVÉ" if egaux == 0 else "RETROUVÉ %d FOIS (doublon)" % egaux)
    print("verdict : message envoyé %s par _message_key" % verdict)
    commun.ecrire_json(commun.RESULTATS / ("m4_comparaison_%d.json" % args.game_id), {
        "envoye": envoye, "cle": cle, "bruts": brut, "relus": [list(r) for r in relus],
        "retrouves_par_cle": egaux, "verdict": verdict,
    })
    sys.exit(0 if egaux == 1 else 1)


if __name__ == "__main__":
    main()
