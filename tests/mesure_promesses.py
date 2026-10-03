#!/usr/bin/env python3
"""Mesure de la logique des promesses : sortie actuelle des fonctions (#2, #3, #4).

Imprime, pour chaque cas de tests/banc_promesses.py, ce que rend le code du
dépôt, une ligne par grandeur : c'est la colonne « avant » du tableau
avant / après tant que les issues ne sont pas corrigées, la colonne « après »
ensuite (comparer les deux sorties par diff). Tout est déterministe et mesuré
une fois : ni pile, ni Claude, ni GPU.

Usage : python3 tests/mesure_promesses.py
"""
import tempfile

import banc_promesses as banc
from banc_promesses import A1, A1_BIS, A2, A3, BUR, GAS, PIC

NOMS = {A1: "A1", A2: "A2", A3: "A3", A1_BIS: "A1bis"}


def nombre(x):
    return "None" if x is None else "%.4f" % x


def tuples(liste):
    """Liste de tuples, les flottants arrondis à 1e-4."""
    return "[" + ", ".join(
        "(" + ", ".join(nombre(x) if isinstance(x, float) else repr(x) for x in t) + ")"
        for t in liste
    ) + "]"


def ligne(cas, grandeur, valeur):
    print("%-34s %-22s %s" % (cas, grandeur, valeur))


def mesurer_rejet(cas, sincere, anterieurs, plans):
    try:
        acceptes, retrogrades, remplaces, apres = banc.rejet(sincere, anterieurs, plans)
    except Exception as e:  # la mesure d'un cas ne doit pas empêcher les suivantes
        ligne(cas, "erreur", "%s: %s" % (type(e).__name__, e))
        return
    ligne(cas, "accepted", acceptes)
    ligne(cas, "demoted", tuples(retrogrades))
    ligne(cas, "superseded", tuples(remplaces))
    ligne(cas, "antérieurs après", apres)


def mesurer_cycle(cas, entree_plans, messages):
    """`messages` : suite de (expéditeur, liste sincere de la France)."""
    try:
        with banc.Banc(entree_plans) as essai:
            for expediteur, sincere in messages:
                essai.message(expediteur, sincere)
            retour = essai.retours[-1]
            par_destinataire, engagements = essai.by_recipient(), essai.engagements()
    except Exception as e:
        ligne(cas, "erreur", "%s: %s" % (type(e).__name__, e))
        return
    ligne(cas, "demoted (dernier)", tuples(retour[1]))
    ligne(cas, "superseded (dernier)", tuples(retour[2]))
    ligne(cas, "by_recipient", par_destinataire)
    ligne(cas, "pseudo_commitments", engagements)


def mesurer_renfort(cas, politique):
    for ordre in banc.permutations(politique):
        tete = "tête %s,%s" % (NOMS[ordre[0]], NOMS[ordre[1]])
        try:
            apres = banc.renfort(politique, ordre)["FRANCE"]
        except Exception as e:
            ligne(cas, tete, "erreur %s: %s" % (type(e).__name__, e))
            continue
        reference = apres[A3] / politique[A3]
        ligne(cas, tete, " / ".join("%s %.4f" % (NOMS[a], apres[a]) for a in politique))
        ligne(cas, tete + " p'/p", " / ".join(
            "%s %.4f" % (NOMS[a], apres[a] / politique[a] / reference) for a in politique
        ))
    cible = banc.cible_r3(politique)
    ligne(cas, "cible R3", " / ".join("%s %.4f" % (NOMS[a], cible[a]) for a in politique))


def main():
    print("# #2 _reject_contradictions : deux ordres pour une unité dans une liste (BUR 0,30 ; PIC 0,20)")
    mesurer_rejet("2a [PIC,BUR] sans antérieur", [PIC, BUR], {}, banc.PLANS_2)
    mesurer_rejet("2a [BUR,PIC] sans antérieur", [BUR, PIC], {}, banc.PLANS_2)
    mesurer_rejet("2b [PIC,BUR] antérieur PIC", [PIC, BUR], {"GERMANY": [PIC]}, banc.PLANS_2)
    mesurer_rejet("2b [BUR,PIC] antérieur PIC", [BUR, PIC], {"GERMANY": [PIC]}, banc.PLANS_2)
    mesurer_rejet("2c [BUR,BUR]", [BUR, BUR], {}, banc.PLANS_2)
    mesurer_rejet("2e [PIC,BUR,F BRE - MAO]", [PIC, BUR, "F BRE - MAO"], {}, banc.PLANS_2)
    mesurer_cycle("2f cycle [BUR,PIC] (PIC 0,9)", banc.entree(banc.PLANS_CONNUS), [("ENGLAND", [BUR, PIC])])

    print("# #3 valeur inconnue de la promesse antérieure, index order_values")
    mesurer_rejet("3a [PIC] antérieur GAS inconnu", [PIC], {"GERMANY": [GAS]}, banc.PLANS_3)
    trahison = [("ENGLAND", [GAS]), ("GERMANY", [PIC])]
    mesurer_cycle("3a cycle GAS puis PIC, sans index", banc.entree(banc.PLANS_3), trahison)
    mesurer_cycle("3b cycle index GAS 0,20 PIC 0,30", banc.entree(banc.PLANS_3, {GAS: 0.20, PIC: 0.30}), trahison)
    mesurer_cycle(
        "3b cycle index GAS 0,20 PIC 0,21",
        banc.entree(banc.plans((PIC, 0.21)), {GAS: 0.20, PIC: 0.21}), trahison,
    )
    with tempfile.TemporaryDirectory() as dossier:
        ecrit = banc.exporter(banc.candidats_14(), dossier)
    index = ecrit.get("order_values")
    ligne("3c export 14 candidats", "plans écrits", len(ecrit["plans"]))
    ligne("3c export 14 candidats", "order_values", "absent" if index is None else "%d ordres" % len(index))
    if index is not None:
        for ordre in sorted(index):
            ligne("3c export 14 candidats", "order_values[%s]" % ordre, nombre(index[ordre]))
    mesurer_cycle("3c cycle export puis GAS, PIC", ecrit, trahison)
    mesurer_cycle("3d cycle ancien format BUR, PIC", banc.entree(banc.PLANS_CONNUS), [("ENGLAND", [BUR]), ("GERMANY", [PIC])])

    print("# #4 apply_commitments_to_policy : promesses A MAR - SPA et F BRE - ENG, k = 3, plafond %.1f"
          % banc.pseudo_commitments.MAX_COMMITMENT_PROB)
    print("#    A1 tient un ordre, A2 les deux, A3 aucun, A1bis un ordre ; p'/p : avant renormalisation")
    mesurer_renfort("4a issue A3 0,5 / A1 0,3 / A2 0,2", banc.POLITIQUE_ISSUE_4)
    mesurer_renfort("4b 0,05 / 0,02 / 0,93", {A1: 0.05, A2: 0.02, A3: 0.93})
    mesurer_renfort("4b 0,5 / 0,3 / 0,2", {A1: 0.5, A2: 0.3, A3: 0.2})
    mesurer_renfort("4d A1 0,04 / A1bis 0,08 / A3 0,88", {A1: 0.04, A1_BIS: 0.08, A3: 0.88})
    mesurer_renfort("4f A2 0,6 / A1 0,1 / A3 0,3", {A2: 0.6, A1: 0.1, A3: 0.3})

    print("# Défaut préexistant (hors périmètre) : BUR promis à deux destinataires, puis trahison pour PIC")
    mesurer_cycle(
        "D  BUR à ENG et GER, puis PIC",
        banc.entree(banc.PLANS_CONNUS),
        [("ENGLAND", [BUR]), ("GERMANY", [BUR]), ("GERMANY", [PIC])],
    )


if __name__ == "__main__":
    main()
