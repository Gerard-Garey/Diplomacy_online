#!/usr/bin/env python3
"""Mesure de la logique des promesses : sortie actuelle des fonctions (#2, #3, #4, #5, #17).

Imprime, pour chaque cas de tests/banc_promesses.py, ce que rend le code du
dépôt, une ligne par grandeur : c'est la colonne « avant » du tableau
avant / après tant que les issues ne sont pas corrigées, la colonne « après »
ensuite (comparer les deux sorties par diff). Tout est déterministe et mesuré
une fois : ni pile, ni Claude, ni GPU.

Usage : python3 tests/mesure_promesses.py
"""
import logging
import tempfile
from unittest import mock

import banc_promesses as banc
import faux_site
from banc_promesses import A1, A1_BIS, A2, A3, BUR, GAS, PIC

NOMS = {A1: "A1", A2: "A2", A3: "A3", A1_BIS: "A1bis"}
# Un message : (expéditeur, liste sincere de la France[, label betray[, reply]]).
# Cas D : BUR promis à l'Angleterre et à l'Allemagne, puis PIC (0,9 contre 0,1) à
# l'Allemagne, trahison déclarée par le label BUR ; le même sans label.
CAS_D = [("ENGLAND", [BUR]), ("GERMANY", [BUR]), ("GERMANY", [PIC], [BUR])]
CAS_D_SANS_LABEL = [("ENGLAND", [BUR]), ("GERMANY", [BUR]), ("GERMANY", [PIC])]
MUN = "A PAR - MUN"  # illégal dans la position du banc
PLANS_SOUS_MARGE = banc.plans((PIC, 0.21), (BUR, 0.20))

MAO, ENG, SPA, PIE = "F BRE - MAO", "F BRE - ENG", "A MAR - SPA", "A MAR - PIE"

# Exemple de contrôle d'expert-cicero (#17, condition moteur) : (action, valeur,
# probabilité avant renfort). BUR est promis ; PIC est l'ordre de remplacement.
TABLE_EXPERT = [((BUR, MAO), 0.10, 0.600), ((PIC, MAO), 0.17, 0.001), ((PIC, ENG), 0.13, 0.399)]
# Ligne 6 bis à la marge de 0,05 : PIC vaut 0,07 de plus que BUR (action de
# meilleur score : 0,17 contre 0,10), mais (BUR, MAO) garde la tête après renfort.
TABLE_6BIS = [((BUR, MAO), 0.10, 0.9), ((PIC, MAO), 0.30, 0.0001), ((PIC, ENG), 0.17, 0.0999)]
# Deux trahisons dans un message (exemple de l'audit, lambda 0,1) : A MAR H et ENG
# promis à l'Angleterre, remplacés par SPA et F BRE H. Avec les deux remplacements,
# (BUR, PIE, F BRE H) est en tête : SPA est refusé. A MAR H revenu, (BUR, A MAR H,
# MAO) reprend la tête : F BRE H n'est pas joué non plus.
MAR_H, BRE_H = "A MAR H", "F BRE H"
TABLES_ENGENDREES = 3000  # banc.tables_engendrees : trois trahisons déclarées par message
TABLE_AUDIT = [
    ((BUR, MAR_H, MAO), 0.21, 0.30), ((BUR, PIE, BRE_H), 0.20, 0.20),
    ((PIC, SPA, MAO), 0.31, 0.05), ((BUR, MAR_H, ENG), 0.08, 0.45),
]
ANTERIEURS_AUDIT = {"ENGLAND": [MAR_H, ENG]}
# Plancher du score (1e-6) : (PIC,) vaut 0,25 avec une probabilité de 1e-8. Au
# plancher, son score est 0,25 + 0,01 x ln(1e-6) = 0,112 et il prend la tête à
# (BUR,) (0,10) ; sans plancher il vaudrait 0,066.
TABLE_PLANCHER = [
    {"orders": [BUR], "value": 0.10, "prob": 1.0}, {"orders": [PIC], "value": 0.25, "prob": 1e-8},
]
# Table illisible à l'export : probabilité None, lambda non numérique.
EXPORTS_ILLISIBLES = [
    ("probabilité None", dict(avant_renfort={a: None for a, _, _ in TABLE_EXPERT})),
    ("lambda non numérique", dict(recherche=dict(banc.RECHERCHE, **{"lambda": "x"}))),
]


def entree_exportee(table, regularize_lambda, promesses=(BUR,)):
    """Entrée écrite par export_plans pour `table`, classée par le moteur avec `promesses` renforcées."""
    action_values, avant = banc.classer(table, regularize_lambda, promesses)
    recherche = dict(banc.RECHERCHE, **{"lambda": regularize_lambda})
    with tempfile.TemporaryDirectory() as dossier:
        return banc.exporter(action_values, dossier, avant, recherche)


# Table de décision de #17 : (libellé, entrée de current_plans.json, messages).
# Sauf mention, PIC vaut 0,9 et BUR 0,1 (PLANS_CONNUS).
CAS_17 = [
    ("L0 BUR, puis PIC+label, reply nul", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR], None)]),
    ("L1 BUR, puis [PIC,GAS]+label", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC, GAS], [BUR])]),
    ("L2 PIC sans antérieur", banc.entree(banc.PLANS_CONNUS), [("ENGLAND", [PIC], [])]),
    ("L3 BUR, puis redite BUR+label", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [BUR], [BUR])]),
    ("L4 BUR, puis PIC sans label", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [])]),
    ("L5 PIC, puis GAS inconnu+label", banc.entree(banc.PLANS_3),
     [("ENGLAND", [PIC]), ("GERMANY", [GAS], [PIC])]),
    ("L5 GAS inconnu, puis PIC+label", banc.entree(banc.PLANS_3),
     [("ENGLAND", [GAS]), ("GERMANY", [PIC], [GAS])]),
    ("L6 BUR 0,20, puis PIC 0,21+label", banc.entree(PLANS_SOUS_MARGE),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])]),
    ("L6bis table 6 bis, lambda 0,1", entree_exportee(TABLE_6BIS, 0.1),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])]),
    ("L7 table 6 bis, lambda 0,01", entree_exportee(TABLE_6BIS, 0.01),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])]),
    ("L7 BUR, puis PIC+label (trahison)", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])]),
    ("L7 BUR, puis PIC+label (révision)", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("ENGLAND", [PIC], [BUR])]),
    ("L7 label écrit A PAR-BUR", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], ["A PAR-BUR"])]),
    ("L8 BUR, puis label sans ordre", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [], [BUR])]),
    ("L8 BUR, puis PIC+label GAS", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [GAS])]),
    ("L8 PIC sans antérieur+label BUR", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [PIC], [BUR])]),
    ("N illégal MUN+label BUR", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [MUN], [BUR])]),
    ("betray mal formé (chaîne)", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], BUR)]),
    ("betray mal formé ([BUR, 1])", banc.entree(banc.PLANS_CONNUS),
     [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR, 1])]),
]

# #17, consigne et mémoire des promesses du bot. Section des engagements : plan
# préféré à 0,500 ; coût positif, nul, négatif, inconnu (GAS hors de l'index).
PLANS_SECTION = banc.plans((PIC, 0.5))
INDEX_SECTION = {PIC: 0.5, BUR: 0.448, MAO: 0.5, SPA: 0.53}
PROMIS_SECTION = {"ENGLAND": [BUR], "GERMANY": [MAO, SPA], "ITALY": [GAS]}
# La table du moteur d'une entrée au format de #17 ; sans elle (entrée d'ancien
# format), la section dit chaque promesse irremplaçable.
TABLE_SECTION = dict(candidates=banc.candidats(((PIC,), 0.5)), search=banc.RECHERCHE)
# Bornage « free » (décision 14) : coûts de 0,0004, -0,010 et 0,012 face au plan
# préféré (0,500), dans la section des engagements puis dans la liste des plans.
INDEX_BORNAGE = {PIC: 0.5, MAO: 0.4996, SPA: 0.51, BUR: 0.488}
PROMIS_BORNAGE = {"ENGLAND": [MAO, SPA, BUR]}
PLANS_BORNAGE = [
    {"rank": 1, "orders": [PIC], "value": 0.5, "cost_vs_best": 0.0},
    {"rank": 2, "orders": [MAO], "value": 0.4996, "cost_vs_best": 0.0004},
    {"rank": 3, "orders": [SPA], "value": 0.51, "cost_vs_best": -0.01},
    {"rank": 4, "orders": [BUR], "value": 0.488, "cost_vs_best": 0.012},
]
# Cycle sur deux phases. À l'Angleterre : MAO (tenue), BUR (trahie par label au
# profit de l'Allemagne). À l'Allemagne : PIC (tenue), SPA révisée en PIE, PIE
# rompue (la France joue A MAR H).
INDEX_BILAN = {PIC: 0.9, BUR: 0.1, PIE: 0.9, SPA: 0.1, MAO: 0.9}
# Trois unités en jeu : la table des candidats est donnée (actions entières). La
# première vaut 0,9 et porte PIC, PIE et MAO ; INDEX_BILAN en est l'index.
ENTREE_BILAN = banc.entree(banc.PLANS_CONNUS, INDEX_BILAN, banc.candidats(
    ((PIC, PIE, MAO), 0.9), ((PIC, SPA, MAO), 0.1), ((BUR, PIE, MAO), 0.1),
))
CAS_BILAN = [
    ("ENGLAND", [MAO]), ("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR]),
    ("GERMANY", [SPA]), ("GERMANY", [PIE], [SPA]),
]
JOUES_BILAN = {"FRANCE": [PIC, "A MAR H", MAO], "GERMANY": ["A MUN - RUH"]}
BILANS = [
    ("aucune promesse", {}),
    ("tout tenu", {"ENGLAND": {"kept": 3, "broken": 0, "examples": []}}),
    ("une rupture", {"ENGLAND": {"kept": 3, "broken": 1, "examples": [
        {"phase": "F1902M", "promised": "F ENG - NTH", "actual": "F ENG S F NWG - NTH"},
    ]}}),
    ("quatre ruptures", {"ENGLAND": {"kept": 0, "broken": 4, "examples": [
        {"phase": "S190%dM" % i, "promised": BUR, "actual": PIC} for i in range(1, 5)
    ]}}),
]


def cycle_bilan(recharger=True):
    """Joue CAS_BILAN, résout la phase, puis un message de l'Angleterre en phase suivante.

    Rend (own_promises avant la résolution, own_promises après, journal de la
    résolution, consigne du dernier appel). `recharger` : l'état en mémoire est
    oublié avant la résolution, qui repart du fichier.
    """
    with banc.Banc(ENTREE_BILAN) as essai:
        for message in CAS_BILAN:
            essai.message(*message)
        avant = essai.promesses_du_bot()
        if recharger:
            essai.recharger()
        essai.jeu.resoudre(JOUES_BILAN)
        journal = essai.cycle_sans_message()
        apres = essai.promesses_du_bot()
        essai.message("ENGLAND", [])
        return avant, apres, journal, essai.consignes[-1]


def rejet_audit(rejeter=None):
    """_reject_contradictions sur l'exemple de l'audit : (retour, tête pour l'état final)."""
    ecrit = entree_exportee(TABLE_AUDIT, 0.1, ANTERIEURS_AUDIT["ENGLAND"])
    retour, _ = banc.rejet_complet(
        [SPA, BRE_H], ANTERIEURS_AUDIT, ecrit["plans"], betray=[MAR_H, ENG],
        order_values=ecrit["order_values"], candidates=ecrit["candidates"], search=ecrit["search"],
    )
    finales = {banc.get_unit_location(o): o for o in ANTERIEURS_AUDIT["ENGLAND"] + retour[0]}
    tete = banc.pseudo_commitments.engine_head_action(
        ecrit["candidates"], ecrit["search"], list(finales.values())
    )
    return retour, tete


def exporter_illisible(options):
    """Entrée écrite pour TABLE_EXPERT quand la table ne peut pas être lue ; (entrée, avertissements)."""
    action_values, avant = banc.classer(TABLE_EXPERT, 0.1, [BUR])
    options = dict(dict(avant_renfort=avant), **options)
    with tempfile.TemporaryDirectory() as dossier, mock.patch.object(logging, "warning") as avertir:
        ecrit = banc.exporter(action_values, dossier, **options)
    return ecrit, [appel[0][0] for appel in avertir.call_args_list]


def consigne(**sections):
    """La consigne système entière pour la France, les sections absentes vides."""
    champs = dict(plan_section="", commitments_section="", own_record_section="", trust_section="")
    champs.update(sections)
    return banc.bot.SYSTEM_PROMPT_TEMPLATE.format(
        power="FRANCE", margin=banc.bot.COMMITMENT_SWITCH_MARGIN, **champs
    )


def section_des_plans(plans_exportes):
    """build_plan_section pour une entrée dont les plans sont `plans_exportes`."""
    with mock.patch.object(banc.bot, "load_plans", lambda *a: {"plans": plans_exportes}):
        return banc.bot.build_plan_section(banc.PARTIE, banc.PHASE, "FRANCE")


def cycle_revision_sequentielle(joues):
    """BUR promis à l'Angleterre, trahi pour PIC dans un message à l'Allemagne, puis PIC
    promis à l'Angleterre ; la phase est résolue avec `joues`.

    Rend (own_promises avant la résolution, après, balises du troisième message).
    """
    with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
        essai.message("ENGLAND", [BUR])
        essai.message("GERMANY", [PIC], [BUR])
        journal = essai.message("ENGLAND", [PIC])
        avant = essai.promesses_du_bot()
        essai.jeu.resoudre(joues)
        essai.cycle_sans_message()
        return avant, essai.promesses_du_bot(), banc.balises(journal)


def cycle_unite_sans_ordre(promis):
    """`promis` à l'Angleterre, puis la phase est résolue sans aucun ordre de la France."""
    with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
        essai.message("ENGLAND", [promis])
        essai.jeu.resoudre({})
        essai.cycle_sans_message()
        return essai.promesses_du_bot()


# #5, journal d'envoi : (libellé, comportements des envois successifs, nombre de cycles).
# Un seul message, de l'Angleterre ; la France répond et promet BUR.
CAS_ENVOI = [
    ("V  envoi confirmé", [], 1),
    ("V  500 non stocké, cycle 1", [faux_site.ERREUR_500], 1),
    ("V  500 non stocké, cycle 2", [faux_site.ERREUR_500], 2),
    ("V  500 non stocké, cycle 3", [faux_site.ERREUR_500], 3),
    ("V  500 trois fois, cycle 7", [faux_site.ERREUR_500] * 3, 7),
    ("V  500 mais stocké, cycle 1", [faux_site.ERREUR_500_STOCKE], 1),
    ("V  500 mais stocké, cycle 2", [faux_site.ERREUR_500_STOCKE], 2),
    ("V  exception, cycle 1", [faux_site.EXCEPTION], 1),
    ("V  200 non JSON, cycle 1", [faux_site.HTML], 1),
    ("V  sourdine, cycle 1", [faux_site.SOURDINE], 1),
    ("V  sourdine, cycle 2", [faux_site.SOURDINE], 2),
]
# Promesse dont le message n'est pas parti : BUR promis à l'Angleterre, la phase est
# résolue (la France joue PIC), puis l'Angleterre écrit de nouveau.
CAS_NON_PARTIE = [
    ("W  envoi confirmé", []),
    ("W  500 non stocké", [faux_site.ERREUR_500]),
    ("W  500 mais stocké", [faux_site.ERREUR_500_STOCKE]),
    ("W  sourdine", [faux_site.SOURDINE]),
]


def mesurer_envoi(cas, comportements, cycles):
    """Un message de l'Angleterre, réponse « entendu » qui promet BUR, puis `cycles` cycles."""
    try:
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.site.comportements = list(comportements)
            essai.recevoir("ENGLAND", [BUR])
            journal = "".join(essai.cycle() for _ in range(cycles))
            etat = essai.etat_du_bot()
            en_attente = etat.get("pending_send")
            ligne(cas, "post_req (appels)", essai.envoi.call_count)
            ligne(cas, "textes distincts", sorted(set(essai.site.textes_envoyes())))
            ligne(cas, "réponses de Claude", len(essai.consignes))
            ligne(cas, "messages sur le site", len(essai.site.messages))
            ligne(cas, "message marqué répondu", str(essai.horloge) in etat["replied_ts"])
            ligne(cas, "exchange_counts", etat["exchange_counts"])
            ligne(cas, "by_recipient", essai.by_recipient())
            ligne(cas, "pseudo_commitments", essai.engagements())
            ligne(cas, "own_promises pending", essai.promesses_du_bot().get("pending"))
            ligne(cas, "pending_send", "absent" if en_attente is None else "tentatives %d, relectures %d" % (
                en_attente["attempts"], en_attente["rereads"]))
            ligne(cas, "journal", banc.balises(journal))
    except Exception as e:
        ligne(cas, "erreur", "%s: %s" % (type(e).__name__, e))


def mesurer_promesse_non_partie(cas, comportements):
    try:
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.site.comportements = list(comportements)
            essai.recevoir("ENGLAND", [BUR])
            essai.cycle()
            essai.jeu.resoudre({"FRANCE": [PIC]})
            for _ in range(2):
                essai.cycle()
            bilan = essai.promesses_du_bot().get("record")
            essai.message("ENGLAND", [])
            ligne(cas, "record", bilan)
            ligne(cas, "consigne « saw this »", "ENGLAND saw this" in essai.consignes[-1])
    except Exception as e:
        ligne(cas, "erreur", "%s: %s" % (type(e).__name__, e))


def mesurer_envois():
    print("# #5 journal d'envoi : un message de l'Angleterre, la réponse promet BUR ; état après n cycles")
    for cas in CAS_ENVOI:
        mesurer_envoi(*cas)
    print("# #5 promesse dont le message n'est pas parti : BUR promis, PIC joué, phase résolue")
    for cas in CAS_NON_PARTIE:
        mesurer_promesse_non_partie(*cas)


def mesurer_corrections():
    print("# #17 plusieurs trahisons dans un message : A MAR H et ENG promis, SPA et F BRE H en remplacement")
    try:
        retour, tete = rejet_audit()
        ligne("P  exemple de l'audit", "demoted", tuples(retour[1]))
        ligne("P  exemple de l'audit", "superseded", tuples(retour[2]))
        ligne("P  exemple de l'audit", "tête, état final", tete)
        acceptes, fautifs, _ = banc.remplacements_hors_tete(banc.tables_engendrees(TABLES_ENGENDREES))
        ligne("P  %d tables engendrées" % TABLES_ENGENDREES, "remplacements acceptés", acceptes)
        ligne("P  %d tables engendrées" % TABLES_ENGENDREES, "dont hors tête", fautifs)
    except Exception as e:
        ligne("P  plusieurs trahisons", "erreur", "%s: %s" % (type(e).__name__, e))
    print("# #17 plancher du score : (BUR,) 0,10 p 1 ; (PIC,) 0,25 p 1e-8 ; lambda 0,01")
    lignes = banc.pseudo_commitments.rescored_candidates(TABLE_PLANCHER, banc.RECHERCHE, [])
    ligne("K  plancher", "scores", " / ".join("%.4f" % score for _, _, _, score in lignes))
    ligne("K  plancher", "tête", banc.pseudo_commitments.engine_head_action(TABLE_PLANCHER, banc.RECHERCHE, []))
    print("# #17 export d'une table illisible : clés de l'entrée écrite")
    for cas, options in EXPORTS_ILLISIBLES:
        try:
            ecrit, avertissements = exporter_illisible(options)
            ligne("X  " + cas, "clés écrites", "aucune entrée" if ecrit is None else sorted(ecrit))
            ligne("X  " + cas, "avertissements", len(avertissements))
        except Exception as e:
            ligne("X  " + cas, "erreur", "%s: %s" % (type(e).__name__, e))
    print("# #17 consigne : section des engagements d'une entrée sans table (ancien format)")
    section = banc.bot.build_commitments_section(PROMIS_SECTION, "GERMANY", PLANS_SECTION, INDEX_SECTION)
    for texte in section.splitlines()[1:5]:
        ligne("S- engagements sans table", "ligne", repr(texte))


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


def mesurer_cycle(cas, entree_plans, messages, label=False):
    """`messages` : suite de messages (voir CAS_D).

    `label` ajoute les grandeurs propres à #17 : labels ignorés et balises du
    journal du dernier message.
    """
    try:
        with banc.Banc(entree_plans) as essai:
            for message in messages:
                journal = essai.message(*message)
            retour = essai.retours[-1]
            par_destinataire, engagements = essai.by_recipient(), essai.engagements()
    except Exception as e:
        ligne(cas, "erreur", "%s: %s" % (type(e).__name__, e))
        return
    ligne(cas, "demoted (dernier)", tuples(retour[1]))
    ligne(cas, "superseded (dernier)", tuples(retour[2]))
    if label:
        ligne(cas, "ignored (dernier)", tuples(retour[4]) if len(retour) > 4 else "absent")
        ligne(cas, "journal (dernier)", banc.balises(journal))
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
    mesurer_cycle("3a cycle GAS puis PIC, sans index", banc.entree_ancienne(banc.PLANS_3), trahison)
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
    mesurer_cycle("3d cycle ancien format BUR, PIC", banc.entree_ancienne(banc.PLANS_CONNUS), [("ENGLAND", [BUR]), ("GERMANY", [PIC])])
    print("# #3 avec le label de #17 : les mêmes cas, la trahison déclarée")
    declaree = [("ENGLAND", [GAS]), ("GERMANY", [PIC], [GAS])]
    mesurer_cycle("3a+ cycle GAS puis PIC, sans index", banc.entree_ancienne(banc.PLANS_3), declaree, label=True)
    mesurer_cycle("3b+ cycle index GAS 0,20 PIC 0,30", banc.entree(banc.PLANS_3, {GAS: 0.20, PIC: 0.30}), declaree, label=True)
    mesurer_cycle(
        "3b+ cycle index GAS 0,20 PIC 0,21",
        banc.entree(banc.plans((PIC, 0.21)), {GAS: 0.20, PIC: 0.21}), declaree, label=True,
    )
    mesurer_cycle("3c+ cycle export puis GAS, PIC", ecrit, declaree, label=True)
    mesurer_cycle(
        "3d+ cycle ancien format BUR, PIC", banc.entree_ancienne(banc.PLANS_CONNUS),
        [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])], label=True,
    )
    mesurer_cycle(
        "3e+ cycle index sans table BUR, PIC",
        banc.entree_ancienne(banc.PLANS_CONNUS, {PIC: 0.9, BUR: 0.1}),
        [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])], label=True,
    )

    print("# #4 apply_commitments_to_policy : promesses A MAR - SPA et F BRE - ENG, k = 3, plafond %.1f"
          % banc.pseudo_commitments.MAX_COMMITMENT_PROB)
    print("#    A1 tient un ordre, A2 les deux, A3 aucun, A1bis un ordre ; p'/p : avant renormalisation")
    mesurer_renfort("4a issue A3 0,5 / A1 0,3 / A2 0,2", banc.POLITIQUE_ISSUE_4)
    mesurer_renfort("4b 0,05 / 0,02 / 0,93", {A1: 0.05, A2: 0.02, A3: 0.93})
    mesurer_renfort("4b 0,5 / 0,3 / 0,2", {A1: 0.5, A2: 0.3, A3: 0.2})
    mesurer_renfort("4d A1 0,04 / A1bis 0,08 / A3 0,88", {A1: 0.04, A1_BIS: 0.08, A3: 0.88})
    mesurer_renfort("4f A2 0,6 / A1 0,1 / A3 0,3", {A2: 0.6, A1: 0.1, A3: 0.3})

    print("# Trahison multi-destinataires : BUR promis à deux destinataires, puis trahison pour PIC")
    mesurer_cycle("D  BUR à ENG et GER, puis PIC", banc.entree(banc.PLANS_CONNUS), CAS_D_SANS_LABEL)
    mesurer_cycle(
        "D  puis redite de BUR à ENG", banc.entree(banc.PLANS_CONNUS),
        CAS_D_SANS_LABEL + [("ENGLAND", [BUR])],
    )
    mesurer_cycle("D+ BUR à ENG et GER, PIC+label", banc.entree(banc.PLANS_CONNUS), CAS_D, label=True)
    mesurer_cycle(
        "D+ puis redite de BUR à ENG", banc.entree(banc.PLANS_CONNUS),
        CAS_D + [("ENGLAND", [BUR])], label=True,
    )

    print("# #17 table de décision (L0 à L8), par cycle : PIC 0,9 et BUR 0,1 sauf mention")
    for cas, entree_plans, messages in CAS_17:
        mesurer_cycle(cas, entree_plans, messages, label=True)

    print("# #17 condition moteur : exemple de contrôle (BUR promis, PIC en remplacement, k = 3, plafond 0,4)")
    for regularize_lambda in (0.1, 0.01):
        cas = "E  lambda %s" % regularize_lambda
        ecrit = entree_exportee(TABLE_EXPERT, regularize_lambda)
        index = ecrit["order_values"]
        ligne(cas, "order_values", " / ".join("%s %.2f" % (o, index[o]) for o in (BUR, PIC, MAO, ENG)))
        ligne(cas, "gain PIC - BUR", "%+.4f" % (index[PIC] - index[BUR]))
        lignes = banc.pseudo_commitments.rescored_candidates(ecrit["candidates"], ecrit["search"], [PIC])
        scores = {action: score for action, _, _, score in lignes}
        ligne(cas, "scores après renfort", " / ".join("%.4f" % scores[a] for a, _, _ in TABLE_EXPERT))
        tete = banc.pseudo_commitments.engine_head_action(ecrit["candidates"], ecrit["search"], [PIC])
        ligne(cas, "tête après renfort", tete)
        for marge in (0.02, 0.05):
            retour, _ = banc.rejet_complet(
                [PIC], {"ENGLAND": [BUR]}, ecrit["plans"], betray=[BUR],
                order_values=index, candidates=ecrit["candidates"], search=ecrit["search"], margin=marge,
            )
            ligne(cas, "marge %s demoted" % marge, tuples(retour[1]))
            ligne(cas, "marge %s superseded" % marge, tuples(retour[2]))

    print("# #17 consigne : section des engagements (plan préféré 0,500 ; interlocuteur : GERMANY)")
    section = banc.bot.build_commitments_section(
        PROMIS_SECTION, "GERMANY", PLANS_SECTION, INDEX_SECTION, **TABLE_SECTION
    )
    for texte in section.splitlines():
        ligne("S  engagements", "ligne", repr(texte))
    print("# #17 consigne : bornage « free » (coûts 0,0004 / -0,010 / 0,012), engagements puis plans")
    section = banc.bot.build_commitments_section(
        PROMIS_BORNAGE, "GERMANY", PLANS_SECTION, INDEX_BORNAGE, **TABLE_SECTION
    )
    for texte in section.splitlines()[:4]:
        ligne("F  engagements", "ligne", repr(texte))
    for texte in section_des_plans(PLANS_BORNAGE).splitlines():
        ligne("F  plans", "ligne", repr(texte))
    print("# #17 consigne : bilan des promesses du bot envers ENGLAND")
    for cas, bilan in BILANS:
        section = banc.bot.build_own_record_section(bilan, "ENGLAND")
        for texte in section.splitlines() or [""]:
            ligne("B  " + cas, "ligne", repr(texte))
    print("# #17 mémoire own_promises : cycle sur deux phases, état relu du disque avant la résolution")
    try:
        avant, apres, journal, derniere = cycle_bilan()
    except Exception as e:
        ligne("M  cycle", "erreur", "%s: %s" % (type(e).__name__, e))
    else:
        ligne("M  avant la résolution", "pending", avant.get("pending"))
        ligne("M  avant la résolution", "record", avant.get("record"))
        ligne("M  après la résolution", "pending", apres.get("pending"))
        for puissance, bilan in sorted(apres.get("record", {}).items()):
            ligne("M  après la résolution", "record[%s]" % puissance, bilan)
        ligne("M  après la résolution", "journal [own-record]", journal.count("[own-record]"))
        for texte in banc.bot.build_own_record_section(apres.get("record", {}), "ENGLAND").splitlines():
            ligne("M  consigne à ENGLAND", "ligne", repr(texte))
        ligne("M  consigne à ENGLAND", "cite GERMANY ou PIE", "GERMANY" in derniere or PIE in derniere)
    print("# #17 mémoire own_promises : révision séquentielle, unité sans ordre")
    for cas, joues in (("R  PIC joué", {"FRANCE": [PIC]}), ("R  BUR joué", {"FRANCE": [BUR]})):
        try:
            avant, apres, marques = cycle_revision_sequentielle(joues)
        except Exception as e:
            ligne(cas, "erreur", "%s: %s" % (type(e).__name__, e))
            continue
        ligne(cas, "journal (3e message)", marques)
        ligne(cas, "pending avant", avant.get("pending"))
        ligne(cas, "record après", apres.get("record"))
    for cas, promis in (("U  A PAR H promis, aucun ordre", "A PAR H"), ("U  BUR promis, aucun ordre", BUR)):
        try:
            ligne(cas, "record", cycle_unite_sans_ordre(promis).get("record"))
        except Exception as e:
            ligne(cas, "erreur", "%s: %s" % (type(e).__name__, e))
    print("# #17 taille de la consigne système (caractères), cas du banc")
    ligne("T  consigne", "sans section", len(consigne()))
    ligne("T  consigne", "section engagements", len(
        banc.bot.build_commitments_section(
            PROMIS_SECTION, "GERMANY", PLANS_SECTION, INDEX_SECTION, **TABLE_SECTION
        )
    ))
    ligne("T  consigne", "section bilan (1 rupture)", len(
        banc.bot.build_own_record_section(BILANS[2][1], "ENGLAND")
    ))
    ligne("T  consigne", "section plans (bornage)", len(section_des_plans(PLANS_BORNAGE)))
    mesurer_envois()
    mesurer_corrections()


if __name__ == "__main__":
    main()
