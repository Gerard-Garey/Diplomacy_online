#!/usr/bin/env python3
"""Logique des promesses : comportement cible des issues #2, #3, #4 et #17.

Règles décidées par le mainteneur le 2026-10-03 (spécification d'expert-cicero).
Appels directs de _reject_contradictions, export_plans / load_plans,
apply_commitments_to_policy et, quand la règle se lit sur ce que le bot écrit,
de run_cycle : ni pile, ni Claude, ni GPU (tests/banc_promesses.py).

Un cas que le code ne satisfait pas encore porte @echec_attendu(numéro
d'issue) : il décrit la cible et échoue aujourd'hui sur une assertion. Quand
l'issue est corrigée, le test réussit, la batterie échoue (succès inattendu) et
la marque est retirée. Les autres cas passent déjà et doivent continuer de
passer. La sortie actuelle de chaque cas s'obtient par tests/mesure_promesses.py.

Usage : python3 tests/test_promesses.py
"""
import contextlib
import functools
import io
import json
import math
import os
import sys
import tempfile
import traceback
import unittest

from unittest import mock

# Avant tout chargement : ni __pycache__ dans tests/, ni .pyc sous cicero/overlay, que
# outils/exporter_patchs.sh --verifier et install.sh prendraient pour des fichiers d'overlay (#27).
sys.dont_write_bytecode = True

import banc_promesses as banc
import faux_site
import mesure_promesses
from banc_promesses import A1, A1_BIS, A2, A3, BUR, GAS, PIC
from mesure_promesses import (
    BRE_H, ENG, MAO, MAR_H, MUN, PIE, PLANS_SOUS_MARGE, SPA, TABLE_6BIS, TABLE_AUDIT, TABLE_EXPERT,
    TABLE_PLANCHER,
)


def levee_par_ce_fichier(trace):
    """Vrai si l'exception a été levée par une ligne de ce fichier.

    Les cadres de unittest (assertEqual et ses semblables) sont ignorés : ils
    lèvent pour le compte de la ligne qui les appelle.
    """
    cadres = [c for c, _ in traceback.walk_tb(trace) if "__unittest" not in c.f_globals]
    return bool(cadres) and os.path.abspath(cadres[-1].f_code.co_filename) == os.path.abspath(__file__)


def echec_attendu(issue):
    """Échec attendu, renvoyant à son issue.

    Seule une assertion fausse écrite dans ce fichier est un échec attendu.
    Toute autre exception (signature changée, clé absente, cycle interrompu,
    assertion levée par le banc ou par le code testé) est affichée et rendue
    en succès inattendu, pour que la batterie échoue au lieu de la confondre
    avec le défaut de l'issue. Pas de subTest dans un test ainsi marqué : unittest y
    remplace l'assertion par une exception interne. MONTRER_ECHECS=1 affiche
    la raison de chaque échec attendu (valeur obtenue contre valeur attendue).
    """

    def decorer(test):
        @functools.wraps(test)
        def enveloppe(self):
            try:
                test(self)
            except Exception as e:
                if isinstance(e, AssertionError) and levee_par_ce_fichier(e.__traceback__):
                    if os.environ.get("MONTRER_ECHECS"):
                        raison = " | ".join(str(e).split("\n")[:1])
                        sys.stderr.write("\n#%d %s : %s\n" % (issue, test.__name__, raison))
                    raise
                sys.stderr.write(
                    "\n%s : erreur qui n'est pas l'échec attendu de #%d\n%s"
                    % (self.id(), issue, traceback.format_exc())
                )

        enveloppe.issue = issue
        return unittest.expectedFailure(enveloppe)

    return decorer


# Entrées de #2 : (liste sincere, promesses antérieures par destinataire).
ENTREES_2 = [
    ([PIC, BUR], {}),
    ([BUR, PIC], {}),
    ([PIC, BUR], {"GERMANY": [PIC]}),
    ([BUR, PIC], {"GERMANY": [PIC]}),
    ([BUR, BUR], {}),
    (["A PAR-PIC", BUR], {}),
    ([PIC, BUR, "F BRE - MAO"], {}),
]


class Banc(unittest.TestCase):
    def test_doublure_de_normalisation_conforme_au_patch(self):
        patch = (banc.RACINE / "cicero" / "patches" / "0001-cicero.patch").read_text()
        self.assertIn("+    " + banc.LIGNE_NORMALISATION, patch)
        self.assertEqual(banc.normalize_order_spacing(" A PAR-PIC "), PIC)

    def test_position_du_banc(self):
        # legal_commitments, la vraie, écarte ce que la position ne permet pas.
        legaux = banc.pseudo_commitments.legal_commitments(
            banc.FauxJeu(), "FRANCE", [PIC, "A PAR-BUR", "A PAR - MUN", "A MUN - RUH"]
        )
        self.assertEqual(legaux, [PIC, BUR])

    def test_mesure_avant_stable(self):
        # Le script de mesure s'exécute et rend deux fois la même sortie.
        sorties = []
        for _ in range(2):
            sortie = io.StringIO()
            with contextlib.redirect_stdout(sortie):
                mesure_promesses.main()
            sorties.append(sortie.getvalue())
        self.assertEqual(sorties[0], sorties[1])
        self.assertIn("#2", sorties[0])


class DeuxOrdresDansUneListe(unittest.TestCase):
    """#2 : deux ordres distincts pour une même unité dans une même liste sincere.

    Figé : les trois premiers retours (accepted, demoted, superseded) et le fait
    que les promesses antérieures ne changent pas. Le signalement est le
    quatrième retour et une ligne [double-deal] du journal.
    """

    def test_aucun_des_deux_n_est_retenu(self):
        for sincere in ([PIC, BUR], [BUR, PIC]):
            acceptes, _, remplaces, _ = banc.rejet(sincere, {}, banc.PLANS_2)
            self.assertEqual(acceptes, [])
            self.assertEqual(remplaces, [])

    def test_resultat_independant_de_l_ordre_de_la_liste(self):
        a = banc.rejet([PIC, BUR], {}, banc.PLANS_2)
        b = banc.rejet([BUR, PIC], {}, banc.PLANS_2)
        self.assertEqual((a[0], a[2]), (b[0], b[2]))

    # lecture confirmée par expert-cicero le 2026-10-03 : un message contradictoire ne vaut redite de rien
    def test_la_promesse_anterieure_reste(self):
        for sincere in ([PIC, BUR], [BUR, PIC]):
            acceptes, _, remplaces, anterieurs = banc.rejet(
                sincere, {"GERMANY": [PIC]}, banc.PLANS_2
            )
            self.assertEqual(remplaces, [])
            self.assertEqual(acceptes, [])
            self.assertEqual(anterieurs, {"GERMANY": [PIC]})

    def test_ordre_repete_accepte_une_fois(self):
        acceptes, retrogrades, remplaces, _ = banc.rejet([BUR, BUR], {}, banc.PLANS_2)
        self.assertEqual((acceptes, retrogrades, remplaces), ([BUR], [], []))

    def test_les_autres_unites_de_la_liste_sont_acceptees(self):
        acceptes, _, remplaces, _ = banc.rejet([PIC, BUR, "F BRE - MAO"], {}, banc.PLANS_2)
        self.assertEqual((acceptes, remplaces), (["F BRE - MAO"], []))

    def test_aucun_remplacement_sans_destinataire(self):
        for sincere, anterieurs in ENTREES_2:
            remplaces = banc.rejet(sincere, anterieurs, banc.PLANS_2)[2]
            self.assertEqual([t for t in remplaces if t[0] is None], [])

    def test_cycle_rien_d_enregistre_ni_cle_null(self):
        # BUR puis PIC, PIC valant 0,8 de plus : rien n'est promis à l'Angleterre.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.message("ENGLAND", [BUR, PIC])
            par_destinataire = essai.by_recipient()
            self.assertNotIn("null", par_destinataire)
            self.assertEqual(par_destinataire.get("ENGLAND", []), [])
            self.assertEqual(essai.engagements(), [])

    def test_ordre_seul_accepte(self):
        self.assertEqual(banc.rejet([PIC], {}, banc.PLANS_2)[:3], ([PIC], [], []))

    def test_promesse_redite_acceptee(self):
        acceptes, retrogrades, remplaces, _ = banc.rejet(
            ["A PAR-PIC"], {"GERMANY": [PIC]}, banc.PLANS_2
        )
        self.assertEqual((acceptes, retrogrades, remplaces), ([PIC], [], []))

    def test_ordres_d_unites_differentes_acceptes(self):
        acceptes = banc.rejet([PIC, "F BRE - MAO"], {}, banc.PLANS_2)[0]
        self.assertEqual(acceptes, [PIC, "F BRE - MAO"])

    def test_les_deux_ordres_ecartes_sont_signales(self):
        # Quatrième retour : les ordres écartés, groupés par unité.
        retour = banc.bot._reject_contradictions(["A PAR-PIC", BUR, "F BRE - MAO"], {}, banc.PLANS_2)
        self.assertEqual(retour[3], [(PIC, BUR)])
        self.assertEqual(banc.bot._reject_contradictions([BUR, BUR], {}, banc.PLANS_2)[3], [])

    def test_cycle_signalement_au_journal(self):
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            journal = essai.message("ENGLAND", [BUR, PIC])
        lignes = [l for l in journal.splitlines() if "[double-deal]" in l]
        self.assertEqual(len(lignes), 1)
        self.assertIn(repr(BUR), lignes[0])
        self.assertIn(repr(PIC), lignes[0])
        self.assertNotIn("[betrayal", journal)

    def test_cycle_la_promesse_anterieure_reste(self):
        # BUR promis à l'Angleterre ; [BUR, PIC] à l'Allemagne ne redit ni ne remplace rien.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.message("ENGLAND", [BUR])
            essai.message("GERMANY", [BUR, PIC])
            self.assertEqual(essai.retours[-1][2], [])
            par_destinataire = essai.by_recipient()
            self.assertEqual(par_destinataire.get("ENGLAND"), [BUR])
            self.assertEqual(par_destinataire.get("GERMANY", []), [])
            self.assertEqual(essai.engagements(), [BUR])


class TrahisonMultiDestinataires(unittest.TestCase):
    """R-B : au plus un ordre sincère par unité, tous destinataires confondus."""

    def test_un_tuple_par_destinataire(self):
        acceptes, retrogrades, remplaces, _ = banc.rejet(
            [PIC], {"ENGLAND": [BUR], "GERMANY": ["A PAR-BUR"]}, banc.PLANS_CONNUS, betray=[BUR]
        )
        self.assertEqual((acceptes, retrogrades), ([PIC], []))
        self.assertEqual([t[:3] for t in remplaces], [("ENGLAND", BUR, PIC), ("GERMANY", BUR, PIC)])
        for t in remplaces:
            self.assertAlmostEqual(t[3], 0.8, places=6)

    def test_sans_label_aucun_tuple(self):
        # Jumeau du précédent, sans label : rétrogradé, rien n'est retiré.
        acceptes, retrogrades, remplaces, anterieurs = banc.rejet(
            [PIC], {"ENGLAND": [BUR], "GERMANY": ["A PAR-BUR"]}, banc.PLANS_CONNUS
        )
        self.assertEqual((acceptes, retrogrades, remplaces), ([], [(PIC, BUR, "undeclared", None)], []))
        self.assertEqual(anterieurs, {"ENGLAND": [BUR], "GERMANY": ["A PAR-BUR"]})

    def test_sous_la_marge_rien_n_est_retire(self):
        for betray, raison in ((None, "undeclared"), ([BUR], "below_margin")):
            with self.subTest(betray=betray):
                acceptes, retrogrades, remplaces, anterieurs = banc.rejet(
                    [PIC], {"ENGLAND": [BUR], "GERMANY": [BUR]}, PLANS_SOUS_MARGE,
                    betray=betray,
                )
                self.assertEqual((acceptes, remplaces), ([], []))
                self.assertEqual([t[:3] for t in retrogrades], [(PIC, BUR, raison)])
                self.assertEqual(anterieurs, {"ENGLAND": [BUR], "GERMANY": [BUR]})

    def test_cycle_retrait_chez_tous_les_destinataires(self):
        # L'Angleterre est trahie ; l'Allemagne, destinataire du message, est révisée.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            for message in mesure_promesses.CAS_D:
                journal = essai.message(*message)
            self.assertEqual(banc.balises(journal), {"[betrayal]": 1, "[revision]": 1})
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [], "GERMANY": [PIC]})
            self.assertEqual(essai.engagements(), [PIC])

    def test_cycle_sans_label_rien_n_est_retire(self):
        # Jumeau du précédent, sans label : BUR reste promis aux deux.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            for message in mesure_promesses.CAS_D_SANS_LABEL:
                journal = essai.message(*message)
            self.assertEqual(essai.retours[-1][:3], ([], [(PIC, BUR, "undeclared", None)], []))
            self.assertEqual(banc.balises(journal), {"[double-deal]": 1})
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [BUR], "GERMANY": [BUR]})
            self.assertEqual(essai.engagements(), [BUR])

    def test_cycle_redite_ulterieure_retrogradee(self):
        # Après la trahison, redire BUR est une promesse contraire à PIC (0,1 contre 0,9).
        for expediteur in ("ENGLAND", "GERMANY"):
            with self.subTest(expediteur=expediteur):
                with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
                    for message in mesure_promesses.CAS_D + [(expediteur, [BUR])]:
                        journal = essai.message(*message)
                    self.assertEqual(essai.retours[-1][:3], ([], [(BUR, PIC, "undeclared", None)], []))
                    self.assertEqual(banc.balises(journal), {"[double-deal]": 1})
                    self.assertEqual(essai.by_recipient(), {"ENGLAND": [], "GERMANY": [PIC]})
                    self.assertEqual(essai.engagements(), [PIC])

    def etat_herite(self, essai):
        """État hérité : « A PAR-BUR », sans espaces, dans les deux fichiers."""
        cle = "bot1:%d" % banc.PARTIE
        essai.fichier_etat.write_text(json.dumps({cle: {
            "replied_ts": [],
            "exchange_counts": {},
            "sincere_by_recipient": {
                "phase": banc.PHASE, "by_recipient": {"ENGLAND": ["A PAR-BUR"]},
            },
        }}))
        essai.fichier_engagements.write_text(
            json.dumps({str(banc.PARTIE): {banc.PHASE: {"FRANCE": ["A PAR-BUR"]}}})
        )

    def test_cycle_retrait_d_un_engagement_herite_sans_espaces(self):
        # Le retrait compare la forme normalisée, sinon le moteur reçoit deux
        # ordres pour PAR. Le label se compare de même à la promesse héritée.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            self.etat_herite(essai)
            essai.message("GERMANY", [PIC], [BUR])
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [], "GERMANY": [PIC]})
            self.assertEqual(essai.engagements(), [PIC])

    def test_cycle_engagement_herite_sans_label_conserve(self):
        # Jumeau du précédent, sans label : la promesse héritée reste, telle qu'elle est écrite.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            self.etat_herite(essai)
            essai.message("GERMANY", [PIC])
            self.assertEqual(essai.retours[-1][:3], ([], [(PIC, BUR, "undeclared", None)], []))
            self.assertEqual(essai.by_recipient(), {"ENGLAND": ["A PAR-BUR"]})
            self.assertEqual(essai.engagements(), ["A PAR-BUR"])


class ValeurInconnue(unittest.TestCase):
    """#3 : promesse antérieure absente des plans exportés, index order_values."""

    def test_valeur_inconnue_la_premiere_promesse_tient(self):
        # Avec le label, la raison est la valeur inconnue ; sans label, l'absence de label.
        for betray, raison in (([GAS], "unknown_value"), (None, "undeclared")):
            with self.subTest(betray=betray):
                acceptes, retrogrades, remplaces, anterieurs = banc.rejet(
                    [PIC], {"GERMANY": [GAS]}, banc.PLANS_3, betray=betray
                )
                self.assertEqual((acceptes, retrogrades, remplaces), ([], [(PIC, GAS, raison, None)], []))
                self.assertEqual(anterieurs, {"GERMANY": [GAS]})

    def test_cycle_valeur_inconnue_la_premiere_promesse_tient(self):
        # GAS hors des plans et de l'index, à l'ancien format comme au format complet :
        # GAS reste promis, que la trahison soit déclarée ou non.
        for betray, entree_plans in (
            ([GAS], banc.entree_ancienne(banc.PLANS_3)), (None, banc.entree_ancienne(banc.PLANS_3)),
            ([GAS], banc.entree(banc.PLANS_3)), (None, banc.entree(banc.PLANS_3)),
        ):
            with self.subTest(betray=betray, cles=sorted(entree_plans)):
                retour, par_destinataire, engagements = banc.trahison(entree_plans, GAS, PIC, betray)
                self.assertEqual(retour[2], [])
                self.assertEqual(par_destinataire.get("ENGLAND"), [GAS])
                self.assertEqual(par_destinataire.get("GERMANY", []), [])
                self.assertEqual(engagements, [GAS])

    def test_cycle_index_gain_au_dessus_de_la_marge(self):
        # GAS n'est dans aucun plan exporté, mais l'index donne sa valeur : gain de 0,10.
        retour, par_destinataire, engagements = banc.trahison(
            banc.entree(banc.PLANS_3, {GAS: 0.20, PIC: 0.30}), GAS, PIC, [GAS]
        )
        self.assertEqual([t[:3] for t in retour[2]], [("ENGLAND", GAS, PIC)])
        self.assertIsNotNone(retour[2][0][3])
        self.assertAlmostEqual(retour[2][0][3], 0.10, places=6)
        self.assertEqual(par_destinataire, {"ENGLAND": [], "GERMANY": [PIC]})
        self.assertEqual(engagements, [PIC])

    def test_cycle_index_sans_label_la_premiere_promesse_tient(self):
        # Jumeau du précédent, sans label : le gain connu de 0,10 ne suffit pas.
        retour, par_destinataire, engagements = banc.trahison(
            banc.entree(banc.PLANS_3, {GAS: 0.20, PIC: 0.30}), GAS, PIC
        )
        self.assertEqual(retour[:3], ([], [(PIC, GAS, "undeclared", None)], []))
        self.assertEqual(par_destinataire, {"ENGLAND": [GAS]})
        self.assertEqual(engagements, [GAS])

    def test_cycle_index_gain_sous_la_marge(self):
        self.assertLess(0.21 - 0.20, banc.bot.COMMITMENT_SWITCH_MARGIN)
        for betray, raison in (([GAS], "below_margin"), (None, "undeclared")):
            with self.subTest(betray=betray):
                retour, par_destinataire, engagements = banc.trahison(
                    banc.entree(banc.plans((PIC, 0.21)), {GAS: 0.20, PIC: 0.21}), GAS, PIC, betray
                )
                self.assertEqual(([t[:3] for t in retour[1]], retour[2]), ([(PIC, GAS, raison)], []))
                self.assertEqual(par_destinataire.get("ENGLAND"), [GAS])
                self.assertEqual(engagements, [GAS])

    def test_index_prioritaire_sur_les_plans(self):
        # L'index, quand il existe, fait foi : il donne pour BUR 0,89, là où les
        # plans exportés donneraient 0,1.
        retour = banc.rejet(
            [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR],
            order_values={PIC: 0.9, BUR: 0.89},
        )
        self.assertEqual(retour[2], [])
        self.assertEqual([t[:3] for t in retour[1]], [(PIC, BUR, "below_margin")])
        self.assertAlmostEqual(retour[1][0][3], 0.01, places=6)

    def test_export_index_des_14_candidats(self):
        candidats = banc.candidats_14()
        with tempfile.TemporaryDirectory() as dossier:
            ecrit = banc.exporter(candidats, dossier)
        self.assertIn("order_values", ecrit)
        # Valeur de la première action (la liste est triée par score) qui contient l'ordre.
        attendu = {}
        for action, valeur, _, _ in candidats:
            for ordre in action:
                attendu.setdefault(ordre, valeur)
        self.assertEqual(len({action for action, _, _, _ in candidats}), 14)
        index = ecrit["order_values"]
        self.assertEqual(sorted(index), sorted(attendu))
        for ordre, valeur in attendu.items():
            self.assertAlmostEqual(index[ordre], valeur, places=5, msg=ordre)
        # GAS n'est joué que par le candidat de rang 12, hors des six plans exportés.
        self.assertAlmostEqual(index[GAS], candidats[11][1], places=5)

    def test_de_l_export_a_la_comparaison(self):
        # Bout en bout : l'index écrit par export_plans donne la valeur de GAS (0,28),
        # PIC vaut 0,50 : la trahison déclarée est décidée sur un gain connu de 0,22.
        with tempfile.TemporaryDirectory() as dossier:
            ecrit = banc.exporter(banc.candidats_14(), dossier)
        retour, _, _ = banc.trahison(ecrit, GAS, PIC, [GAS])
        self.assertEqual([t[:3] for t in retour[2]], [("ENGLAND", GAS, PIC)])
        self.assertIsNotNone(retour[2][0][3])
        self.assertAlmostEqual(retour[2][0][3], 0.22, places=4)

    def test_export_lisible_par_un_ancien_lecteur(self):
        # L'entrée reste un objet JSON dont « plans » et « computed_at » n'ont pas
        # changé de forme ; l'index est une clé de plus, de l'ordre vers un nombre.
        with tempfile.TemporaryDirectory() as dossier:
            ecrit = banc.exporter(banc.candidats_14(), dossier)
        self.assertEqual(sorted(ecrit), ["candidates", "computed_at", "order_values", "plans", "search"])
        self.assertEqual(list(ecrit)[:3], ["computed_at", "plans", "order_values"])
        self.assertEqual(json.loads(json.dumps(ecrit)), ecrit)
        self.assertTrue(all(isinstance(v, float) for v in ecrit["order_values"].values()))

    def test_export_plans_inchange(self):
        candidats = banc.candidats_14()
        with tempfile.TemporaryDirectory() as dossier:
            ecrit = banc.exporter(candidats, dossier)
        self.assertEqual(len(ecrit["plans"]), banc.plan_export.TOP_K)
        self.assertEqual(
            ecrit["plans"][0],
            {"rank": 1, "orders": list(candidats[0][0]), "value": 0.5, "cost_vs_best": 0.0},
        )
        self.assertEqual(
            [(p["rank"], p["value"], p["cost_vs_best"]) for p in ecrit["plans"]],
            [(i + 1, round(0.50 - 0.02 * i, 5), round(0.02 * i, 5)) for i in range(6)],
        )
        self.assertFalse(any(GAS in p["orders"] for p in ecrit["plans"]))

    def test_ancien_format_la_premiere_promesse_tient(self):
        # Entrée écrite avant #17 (ni candidates ni search), avec ou sans index : le
        # gain de 0,8 se lit, mais rien ne dit que le moteur jouerait PIC (ligne 5).
        for index in (None, {PIC: 0.9, BUR: 0.1}):
            with self.subTest(index=index):
                retour, par_destinataire, engagements = banc.trahison(
                    banc.entree_ancienne(banc.PLANS_CONNUS, index), BUR, PIC, [BUR]
                )
                self.assertEqual(retour[:3], ([], [(PIC, BUR, "unknown_value", None)], []))
                self.assertEqual(par_destinataire, {"ENGLAND": [BUR]})
                self.assertEqual(engagements, [BUR])

    def test_sans_index_repli_sur_le_premier_plan(self):
        # Sans order_values, la valeur d'un ordre est celle du PREMIER plan qui le
        # contient (les plans sont classés par score), pas la meilleure : PIC vaut
        # 0,30 et non 0,90, le gain n'est que de 0,01.
        exportes = [
            {"orders": [BUR, MAO], "value": 0.29}, {"orders": [PIC, MAO], "value": 0.30},
            {"orders": [PIC, ENG], "value": 0.90},
        ]
        valeur = lambda ordre: banc.bot._order_value(ordre, exportes)
        self.assertEqual((valeur(PIC), valeur(BUR), valeur(MAO), valeur(GAS)), (0.30, 0.29, 0.29, None))
        retour, _ = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR]}, exportes, betray=[BUR], margin=0.02,
            candidates=banc.candidats(*((p["orders"], p["value"]) for p in exportes)),
        )
        self.assertEqual(retour[:3], ([], [(PIC, BUR, "below_margin", 0.01)], []))

    def test_valeur_non_finie_inconnue(self):
        # NaN ou infini, dans l'index comme dans les plans : valeur inconnue (ligne 5).
        for mauvaise in (float("nan"), float("inf"), float("-inf"), True, "0.9", None):
            with self.subTest(valeur=mauvaise):
                self.assertIsNone(banc.bot._order_value(PIC, [], {PIC: mauvaise}))
                self.assertIsNone(banc.bot._order_value(PIC, [{"orders": [PIC], "value": mauvaise}]))
                retour, _ = banc.rejet_complet(
                    [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR],
                    order_values={PIC: mauvaise, BUR: 0.1},
                    candidates=banc.candidats_du_banc(banc.PLANS_CONNUS),
                )
                self.assertEqual(retour[:3], ([], [(PIC, BUR, "unknown_value", None)], []))

    def test_export_valeur_non_finie_hors_de_l_index(self):
        # La première action qui contient GAS a une valeur non finie : GAS n'entre
        # pas dans l'index, et la table des candidats n'est pas écrite.
        for mauvaise in (float("nan"), float("inf")):
            with self.subTest(valeur=mauvaise):
                actions = [((PIC, MAO), 0.5, 0.6, 0.0), ((GAS, MAO), mauvaise, 0.3, 0.0), ((GAS, ENG), 0.2, 0.1, 0.0)]
                with tempfile.TemporaryDirectory() as dossier, self.assertLogs(level="WARNING"):
                    ecrit = banc.exporter(actions, dossier)
                self.assertEqual(ecrit["order_values"], {PIC: 0.5, MAO: 0.5, ENG: 0.2})
                self.assertEqual(sorted(ecrit), ["computed_at", "order_values", "plans"])

    def test_ancien_format_sans_label_la_premiere_promesse_tient(self):
        # Jumeau du précédent, sans label : la raison est l'absence de label.
        retour, par_destinataire, engagements = banc.trahison(
            banc.entree_ancienne(banc.PLANS_CONNUS), BUR, PIC
        )
        self.assertEqual(retour[:3], ([], [(PIC, BUR, "undeclared", None)], []))
        self.assertEqual(par_destinataire, {"ENGLAND": [BUR]})
        self.assertEqual(engagements, [BUR])

    def test_ancien_format_gain_sous_la_marge(self):
        # À l'ancien format, la table manquante passe avant la marge (ligne 5 avant ligne 6).
        for betray, raison in ((None, "undeclared"), ([BUR], "unknown_value")):
            with self.subTest(betray=betray):
                retour, par_destinataire, engagements = banc.trahison(
                    banc.entree_ancienne(PLANS_SOUS_MARGE), BUR, PIC, betray
                )
                self.assertEqual((retour[0], retour[2]), ([], []))
                self.assertEqual([t[:3] for t in retour[1]], [(PIC, BUR, raison)])
                self.assertEqual(par_destinataire, {"ENGLAND": [BUR]})
                self.assertEqual(engagements, [BUR])

    def test_nouvelle_promesse_sans_valeur_retrogradee(self):
        # Rien ne dit que le changement vaut une parole rompue : la première tient.
        for betray, raison in ((None, "undeclared"), ([PIC], "unknown_value")):
            with self.subTest(betray=betray):
                acceptes, retrogrades, remplaces, _ = banc.rejet(
                    [GAS], {"GERMANY": [PIC]}, banc.PLANS_3, betray=betray
                )
                self.assertEqual((acceptes, retrogrades, remplaces), ([], [(GAS, PIC, raison, None)], []))


def cycle(messages, entree_plans=None):
    """Joue `messages` ; rend (dernier retour, balises du dernier journal, by_recipient, engagements)."""
    entree_plans = banc.entree(banc.PLANS_CONNUS) if entree_plans is None else entree_plans
    with banc.Banc(entree_plans) as essai:
        for message in messages:
            journal = essai.message(*message)
        return essai.retours[-1], banc.balises(journal), essai.by_recipient(), essai.engagements()


class TrahisonDeclaree(unittest.TestCase):
    """#17 : table de décision, une ligne par test (L0 à L8), par appel direct et par cycle.

    E est la promesse antérieure de la phase sur l'unité, N l'ordre nouveau de
    sincere, le label un ordre de la liste betray. Sauf mention, PIC vaut 0,9 et
    BUR 0,1 : le gain de 0,8 dépasse la marge.
    """

    PROMIS = [("ENGLAND", [BUR])]

    def assert_etat_inchange(self, messages, entree_plans=None):
        """Le dernier message ne change ni by_recipient ni un octet de pseudo_commitments.json."""
        entree_plans = banc.entree(banc.PLANS_CONNUS) if entree_plans is None else entree_plans
        with banc.Banc(entree_plans) as essai:
            for message in messages[:-1]:
                essai.message(*message)
            avant = (essai.by_recipient(), essai.fichier_engagements.read_text())
            essai.message(*messages[-1])
            self.assertEqual((essai.by_recipient(), essai.fichier_engagements.read_text()), avant)

    def test_ligne_0_reply_nul_rien_n_est_retenu(self):
        messages = self.PROMIS + [("GERMANY", [PIC, "F BRE - MAO"], [BUR], None)]
        retour, balises, par_destinataire, engagements = cycle(messages)
        # Ni sincere ni betray n'atteignent la comparaison.
        self.assertEqual(tuple(retour), ([], [], [], [], []))
        self.assertEqual(balises, {})
        self.assertEqual(par_destinataire, {"ENGLAND": [BUR]})
        self.assertEqual(engagements, [BUR])
        self.assert_etat_inchange(messages)

    def test_ligne_0_reply_nul_sans_promesse_anterieure(self):
        # Avant #17, une liste sincere sans réponse était enregistrée.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.message("GERMANY", [PIC], None, None)
            self.assertEqual(essai.by_recipient(), {})
            self.assertFalse(essai.fichier_engagements.exists())

    def test_ligne_1_deux_ordres_le_label_est_ignore(self):
        retour, anterieurs = banc.rejet_complet(
            [PIC, GAS], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR]
        )
        # Le label ne rompt rien, mais laisse une trace (décompte du critère (d)).
        self.assertEqual(retour, ([], [], [], [(PIC, GAS)], [(BUR, "conflicting")]))
        self.assertEqual(anterieurs, {"ENGLAND": [BUR]})
        messages = self.PROMIS + [("GERMANY", [PIC, GAS], [BUR])]
        retour, balises, par_destinataire, engagements = cycle(messages)
        self.assertEqual(balises, {"[double-deal]": 1, "[betrayal-ignored]": 1})
        self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [BUR]}, [BUR]))
        self.assert_etat_inchange(messages)

    def test_ligne_2_sans_promesse_anterieure_accepte(self):
        retour, _ = banc.rejet_complet([PIC], {}, banc.PLANS_CONNUS, betray=[])
        self.assertEqual(retour, ([PIC], [], [], [], []))
        retour, balises, par_destinataire, engagements = cycle([("ENGLAND", [PIC], [])])
        self.assertEqual(balises, {})
        self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [PIC]}, [PIC]))

    def test_ligne_3_redite_acceptee_label_ignore(self):
        retour, anterieurs = banc.rejet_complet(
            ["A PAR-BUR"], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR]
        )
        self.assertEqual(retour, ([BUR], [], [], [], [(BUR, "restated")]))
        self.assertEqual(anterieurs, {"ENGLAND": [BUR]})
        retour, balises, par_destinataire, engagements = cycle(self.PROMIS + [("GERMANY", [BUR], [BUR])])
        self.assertEqual(balises, {"[betrayal-ignored]": 1})
        self.assertEqual(par_destinataire, {"ENGLAND": [BUR], "GERMANY": [BUR]})
        self.assertEqual(engagements, [BUR])

    def test_ligne_4_sans_label_retrograde(self):
        for betray in (None, []):
            with self.subTest(betray=betray):
                retour, anterieurs = banc.rejet_complet(
                    [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=betray
                )
                self.assertEqual(retour, ([], [(PIC, BUR, "undeclared", None)], [], [], []))
                self.assertEqual(anterieurs, {"ENGLAND": [BUR]})
                messages = self.PROMIS + [("GERMANY", [PIC], betray)]
                retour, balises, par_destinataire, engagements = cycle(messages)
                self.assertEqual(balises, {"[double-deal]": 1})
                self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [BUR]}, [BUR]))
                self.assert_etat_inchange(messages)

    def test_ligne_5_valeur_de_n_inconnue(self):
        retour, anterieurs = banc.rejet_complet([GAS], {"ENGLAND": [PIC]}, banc.PLANS_3, betray=[PIC])
        self.assertEqual(retour, ([], [(GAS, PIC, "unknown_value", None)], [], [], []))
        self.assertEqual(anterieurs, {"ENGLAND": [PIC]})
        messages = [("ENGLAND", [PIC]), ("GERMANY", [GAS], [PIC])]
        retour, balises, par_destinataire, engagements = cycle(messages, banc.entree(banc.PLANS_3))
        self.assertEqual(balises, {"[betrayal-refused]": 1})
        self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [PIC]}, [PIC]))
        self.assert_etat_inchange(messages, banc.entree(banc.PLANS_3))

    def test_ligne_5_valeur_de_e_inconnue(self):
        retour, anterieurs = banc.rejet_complet([PIC], {"ENGLAND": [GAS]}, banc.PLANS_3, betray=[GAS])
        self.assertEqual(retour, ([], [(PIC, GAS, "unknown_value", None)], [], [], []))
        self.assertEqual(anterieurs, {"ENGLAND": [GAS]})
        messages = [("ENGLAND", [GAS]), ("GERMANY", [PIC], [GAS])]
        retour, balises, par_destinataire, engagements = cycle(messages, banc.entree(banc.PLANS_3))
        self.assertEqual(balises, {"[betrayal-refused]": 1})
        self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [GAS]}, [GAS]))
        self.assert_etat_inchange(messages, banc.entree(banc.PLANS_3))

    def test_ligne_5_valeur_absente_de_l_index(self):
        # Un index présent fait foi seul : GAS n'y est pas, sa valeur est inconnue.
        retour, _ = banc.rejet_complet(
            [PIC], {"ENGLAND": [GAS]}, banc.plans((PIC, 0.9), (GAS, 0.1)), betray=[GAS],
            order_values={PIC: 0.9},
        )
        self.assertEqual(retour[:3], ([], [(PIC, GAS, "unknown_value", None)], []))

    def test_ligne_6_gain_sous_la_marge(self):
        retour, anterieurs = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR]}, PLANS_SOUS_MARGE, betray=[BUR]
        )
        self.assertEqual((retour[0], retour[2], retour[3], retour[4]), ([], [], [], []))
        self.assertEqual([t[:3] for t in retour[1]], [(PIC, BUR, "below_margin")])
        self.assertAlmostEqual(retour[1][0][3], 0.01, places=6)
        self.assertEqual(anterieurs, {"ENGLAND": [BUR]})
        messages = self.PROMIS + [("GERMANY", [PIC], [BUR])]
        with banc.Banc(banc.entree(PLANS_SOUS_MARGE)) as essai:
            for message in messages:
                journal = essai.message(*message)
            self.assertEqual(banc.balises(journal), {"[betrayal-refused]": 1})
            refus = [l for l in journal.splitlines() if "[betrayal-refused]" in l][0]
            self.assertIn("+0.0100", refus)
            self.assertEqual((essai.by_recipient(), essai.engagements()), ({"ENGLAND": [BUR]}, [BUR]))
        self.assert_etat_inchange(messages, banc.entree(PLANS_SOUS_MARGE))

    def test_ligne_6_gain_egal_a_la_marge(self):
        # La marge est stricte : un gain égal à la marge ne suffit pas.
        retour, _ = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR]}, banc.plans((PIC, 0.75), (BUR, 0.5)), betray=[BUR], margin=0.25
        )
        self.assertEqual(retour[1], [(PIC, BUR, "below_margin", 0.25)])
        self.assertEqual(retour[2], [])

    def test_ligne_6_marge_comparee_apres_arrondi(self):
        # En flottants, 0,32 - 0,30 et 0,40 - 0,35 dépassent 0,02 et 0,05 d'un cheveu :
        # le gain est arrondi à 1e-5 avant la comparaison, et n'est pas au-dessus de la marge.
        self.assertGreater(0.32 - 0.30, 0.02)
        self.assertGreater(0.40 - 0.35, 0.05)
        for v_n, v_e, marge in ((0.32, 0.30, 0.02), (0.40, 0.35, 0.05)):
            with self.subTest(marge=marge):
                retour, _ = banc.rejet_complet(
                    [PIC], {"ENGLAND": [BUR]}, banc.plans((PIC, v_n), (BUR, v_e)), betray=[BUR], margin=marge
                )
                self.assertEqual(retour[:3], ([], [(PIC, BUR, "below_margin", marge)], []))
        # Un cran au-dessus (1e-5), le remplacement passe.
        retour, _ = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR]}, banc.plans((PIC, 0.40001), (BUR, 0.35)), betray=[BUR], margin=0.05
        )
        self.assertEqual((retour[0], retour[1]), ([PIC], []))

    def test_marge_de_la_branche(self):
        self.assertEqual(banc.bot.COMMITMENT_SWITCH_MARGIN, 0.05)

    def test_ligne_7_trahison(self):
        retour, anterieurs = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=["A PAR-BUR"]
        )
        self.assertEqual((retour[0], retour[1], retour[3], retour[4]), ([PIC], [], [], []))
        self.assertEqual([t[:3] for t in retour[2]], [("ENGLAND", BUR, PIC)])
        self.assertAlmostEqual(retour[2][0][3], 0.8, places=6)
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.message("ENGLAND", [BUR])
            journal = essai.message("GERMANY", [PIC], ["A PAR-BUR"])
            self.assertEqual(banc.balises(journal), {"[betrayal]": 1})
            trahison = [l for l in journal.splitlines() if "[betrayal]" in l][0]
            self.assertIn("ENGLAND", trahison)
            self.assertIn("+0.8000", trahison)
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [], "GERMANY": [PIC]})
            self.assertEqual(essai.engagements(), [PIC])

    def test_ligne_7_revision(self):
        # Le détenteur est le destinataire du message : même règle, autre libellé.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.message("ENGLAND", [BUR])
            journal = essai.message("ENGLAND", [PIC], [BUR])
            self.assertEqual([t[:3] for t in essai.retours[-1][2]], [("ENGLAND", BUR, PIC)])
            self.assertEqual(banc.balises(journal), {"[revision]": 1})
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [PIC]})
            self.assertEqual(essai.engagements(), [PIC])

    def test_ligne_7_revision_meme_regle(self):
        # Sans label, ou sous la marge, la révision est refusée comme une trahison.
        for betray, plans_exportes, balise in (
            (None, banc.PLANS_CONNUS, "[double-deal]"),
            ([BUR], PLANS_SOUS_MARGE, "[betrayal-refused]"),
        ):
            with self.subTest(betray=betray):
                messages = self.PROMIS + [("ENGLAND", [PIC], betray)]
                retour, balises, par_destinataire, engagements = cycle(messages, banc.entree(plans_exportes))
                self.assertEqual(balises, {balise: 1})
                self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [BUR]}, [BUR]))

    def test_ligne_8_label_sans_ordre_de_remplacement(self):
        retour, anterieurs = banc.rejet_complet([], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR])
        self.assertEqual(retour, ([], [], [], [], [(BUR, "no_replacement")]))
        self.assertEqual(anterieurs, {"ENGLAND": [BUR]})
        # Un ordre pour une autre unité ne remplace rien.
        messages = self.PROMIS + [("GERMANY", ["F BRE - MAO"], [BUR])]
        retour, balises, par_destinataire, engagements = cycle(messages)
        self.assertEqual(retour[4], [(BUR, "no_replacement")])
        self.assertEqual(balises, {"[betrayal-ignored]": 1})
        self.assertEqual(par_destinataire, {"ENGLAND": [BUR], "GERMANY": ["F BRE - MAO"]})
        self.assertEqual(engagements, [BUR, "F BRE - MAO"])

    def test_ligne_8_label_qui_n_est_aucune_promesse(self):
        # Le label est l'ordre promis exact, pas l'unité : GAS n'a pas été promis.
        retour, anterieurs = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[GAS]
        )
        self.assertEqual(
            retour, ([], [(PIC, BUR, "undeclared", None)], [], [], [(GAS, "no_such_promise")])
        )
        self.assertEqual(anterieurs, {"ENGLAND": [BUR]})
        messages = self.PROMIS + [("GERMANY", [PIC], [GAS])]
        retour, balises, par_destinataire, engagements = cycle(messages)
        self.assertEqual(balises, {"[betrayal-ignored]": 1, "[double-deal]": 1})
        self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [BUR]}, [BUR]))
        self.assert_etat_inchange(messages)

    def test_ligne_8_label_sans_promesse_sur_l_unite(self):
        # Rien n'est promis pour PAR : N est accepté (ligne 2), le label, répété, est ignoré une fois.
        retour, _ = banc.rejet_complet([PIC], {}, banc.PLANS_CONNUS, betray=[BUR, "A PAR-BUR"])
        self.assertEqual(retour, ([PIC], [], [], [], [(BUR, "no_such_promise")]))

    def test_ordre_illegal_le_label_reste_sans_remplacement(self):
        # MUN est écarté par legal_commitments avant la comparaison.
        messages = self.PROMIS + [("GERMANY", [MUN], [BUR])]
        retour, balises, par_destinataire, engagements = cycle(messages)
        self.assertEqual(tuple(retour), ([], [], [], [], [(BUR, "no_replacement")]))
        self.assertEqual(balises, {"[betrayal-ignored]": 1})
        self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [BUR]}, [BUR]))
        self.assert_etat_inchange(messages)

    def test_betray_mal_forme_vaut_liste_vide(self):
        # Ni liste, ni liste de chaînes : aucun label, donc ligne 4.
        for betray in (BUR, {"order": BUR}, [BUR, 1], [[BUR]], 0, True):
            with self.subTest(betray=betray):
                retour, balises, par_destinataire, engagements = cycle(
                    self.PROMIS + [("GERMANY", [PIC], betray)]
                )
                self.assertEqual(retour[:3], ([], [(PIC, BUR, "undeclared", None)], []))
                self.assertEqual(retour[4], [])
                self.assertEqual(balises, {"[double-deal]": 1})
                self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [BUR]}, [BUR]))

    def test_generate_reply_rend_trois_valeurs(self):
        silence = banc.bot.NO_REPLY_TOKEN
        cas = [
            ({"reply": "ok", "sincere": ["A PAR-PIC"], "betray": ["A PAR-BUR"]}, ("ok", [PIC], [BUR])),
            ({"reply": "ok", "sincere": [PIC]}, ("ok", [PIC], [])),
            ({"reply": "ok", "sincere": [PIC], "betray": None}, ("ok", [PIC], [])),
            ({"reply": "ok", "sincere": [PIC], "betray": BUR}, ("ok", [PIC], [])),
            ({"reply": "ok", "sincere": [PIC], "betray": [BUR, 3]}, ("ok", [PIC], [])),
            ({"reply": None, "sincere": [PIC], "betray": [BUR]}, (silence, [], [])),
            ({"reply": "  ", "sincere": [PIC], "betray": [BUR]}, (silence, [], [])),
            ("pas du JSON", (silence, [], [])),
        ]
        for objet, attendu in cas:
            with self.subTest(objet=objet):
                texte = objet if isinstance(objet, str) else json.dumps(objet)
                sortie = mock.Mock(stdout=json.dumps({"result": texte}))
                with mock.patch.object(banc.bot.subprocess, "run", lambda *a, **k: sortie), \
                        mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing), \
                        contextlib.redirect_stdout(io.StringIO()):
                    rendu = banc.bot.generate_reply("FRANCE", "GERMANY", "", banc.PHASE, "bonjour")
                self.assertEqual(rendu, attendu)

    def test_tout_label_sans_effet_laisse_une_trace(self):
        # Un label est soit suivi d'effet (lignes 5 à 7 : rétrogradé ou remplacé), soit
        # dans `ignored`, jamais ni l'un ni l'autre ; le journal porte une ligne par label ignoré.
        for cas, entree_plans, messages in mesure_promesses.CAS_17:
            label = messages[-1][2] if len(messages[-1]) > 2 else None
            reply = messages[-1][3] if len(messages[-1]) > 3 else "entendu"
            if not isinstance(label, list) or not all(isinstance(o, str) for o in label) or not reply:
                continue
            with self.subTest(cas=cas):
                with banc.Banc(entree_plans) as essai:
                    for message in messages:
                        journal = essai.message(*message)
                    _, retrogrades, remplaces, _, ignores = essai.retours[-1]
                suivis = {t[1] for t in retrogrades if t[2] != "undeclared"} | {t[1] for t in remplaces}
                emis = {banc.normalize_order_spacing(o) for o in label}
                self.assertEqual(suivis | {o for o, _ in ignores}, emis)
                self.assertEqual(suivis & {o for o, _ in ignores}, set())
                self.assertEqual(banc.balises(journal).get("[betrayal-ignored]", 0), len(ignores))

    def test_consigne_annonce_le_champ_betray(self):
        consigne = mesure_promesses.consigne()
        self.assertIn(
            '{"reply": "<your message, or null if no reply is needed>", "sincere": ["<order>", ...], '
            '"betray": ["<earlier promised order>", ...]}',
            consigne,
        )

    def test_g_au_plus_un_ordre_par_unite(self):
        # (g) : après chaque message de chaque scénario du banc, pseudo_commitments.json
        # porte au plus un ordre par unité (Banc.message le contrôle aussi et lève sinon),
        # et ces ordres sont ceux de by_recipient.
        scenarios = list(mesure_promesses.CAS_17) + [
            ("D", banc.entree(banc.PLANS_CONNUS), mesure_promesses.CAS_D + [("ENGLAND", [BUR])]),
            ("D sans label", banc.entree(banc.PLANS_CONNUS),
             mesure_promesses.CAS_D_SANS_LABEL + [("ENGLAND", [BUR])]),
        ]
        for cas, entree_plans, messages in scenarios:
            with self.subTest(cas=cas):
                with banc.Banc(entree_plans) as essai:
                    for message in messages:
                        essai.message(*message)
                        self.assertEqual(banc.unites_en_double(essai.engagements()), [])
                        tous = [o for ordres in essai.by_recipient().values() for o in ordres]
                        self.assertEqual(sorted(set(tous)), sorted(essai.engagements()))

    def test_g_le_controle_du_banc_leve(self):
        # Un fichier qui porte deux ordres pour PAR fait lever le banc.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.fichier_engagements.write_text(
                json.dumps({str(banc.PARTIE): {banc.PHASE: {"FRANCE": [BUR, "A PAR-PIC"]}}})
            )
            with self.assertRaises(banc.InvariantRompu):
                essai.message("GERMANY", [])

    def test_betray_ne_quitte_pas_le_bot(self):
        # Ce qui atteint le moteur reste une liste d'ordres par puissance : ni label, ni raison.
        partie = str(banc.PARTIE)
        for cas, entree_plans, messages in mesure_promesses.CAS_17:
            with self.subTest(cas=cas):
                with banc.Banc(entree_plans) as essai:
                    for message in messages:
                        essai.message(*message)
                    if not essai.fichier_engagements.exists():
                        continue
                    donnees = json.loads(essai.fichier_engagements.read_text())
                    self.assertEqual(list(donnees), [partie])
                    self.assertEqual(list(donnees[partie]), [banc.PHASE])
                    self.assertEqual(list(donnees[partie][banc.PHASE]), ["FRANCE"])
                    legaux = [o for ordres in banc.ORDRES_LEGAUX.values() for o in ordres]
                    for ordre in donnees[partie][banc.PHASE]["FRANCE"]:
                        self.assertIn(ordre, legaux)


def entree_expert(regularize_lambda):
    return mesure_promesses.entree_exportee(TABLE_EXPERT, regularize_lambda)


def rejet_sur(ecrit, sincere, anterieurs, betray, **options):
    """_reject_contradictions sur une entrée exportée (plans, index, table)."""
    return banc.rejet_complet(
        sincere, anterieurs, ecrit["plans"], betray=betray, order_values=ecrit["order_values"],
        candidates=ecrit["candidates"], search=ecrit["search"], **options
    )


class ConditionMoteur(unittest.TestCase):
    """#17, lignes 5 étendue, 6 bis et 7 : le moteur jouerait-il l'ordre de remplacement ?

    Exemple de contrôle d'expert-cicero (TABLE_EXPERT) : a1 = (BUR, MAO), valeur
    0,10, p 0,600 ; a2 = (PIC, MAO), 0,17, 0,001 ; a3 = (PIC, ENG), 0,13, 0,399.
    BUR est promis, PIC le remplace ; k = 3, plafond 0,4. Les chiffres attendus
    sont recalculés ici par la formule, puis comparés aux arrondis annoncés.
    """

    A1, A2, A3 = (action for action, _, _ in TABLE_EXPERT)

    def scores_attendus(self, regularize_lambda):
        # S' = {PIC}, n = 1 : a1 inchangée (0,6) ; a2 0,001 x 3 ; a3 min(0,399 x 3, 0,4).
        brut = {self.A1: 0.600, self.A2: 0.003, self.A3: 0.4}
        total = sum(brut.values())
        valeurs = {action: valeur for action, valeur, _ in TABLE_EXPERT}
        return {a: valeurs[a] + regularize_lambda * math.log(brut[a] / total) for a in brut}

    def test_a_export_de_l_exemple(self):
        ecrit = entree_expert(0.1)
        # Classement par score (lambda 0,1) : a1, a3, a2. PIC vaut 0,13 (a3), pas 0,17 (a2).
        self.assertEqual([c["orders"] for c in ecrit["candidates"]], [list(self.A1), list(self.A3), list(self.A2)])
        self.assertEqual(ecrit["order_values"], {BUR: 0.10, MAO: 0.10, PIC: 0.13, ENG: 0.13})
        self.assertEqual(ecrit["candidates"], [
            {"orders": list(self.A1), "value": 0.10, "prob": 0.6},
            {"orders": list(self.A3), "value": 0.13, "prob": 0.399},
            {"orders": list(self.A2), "value": 0.17, "prob": 0.001},
        ])
        self.assertEqual(ecrit["search"], {"lambda": 0.1, "boost": 3.0, "max_prob": 0.4})
        self.assertNotIn("score", json.dumps(ecrit))
        # plans : les mêmes octets qu'un export sans table (appel d'avant #17).
        action_values, _ = banc.classer(TABLE_EXPERT, 0.1, [BUR])
        with tempfile.TemporaryDirectory() as dossier:
            sans_table = banc.exporter(action_values, dossier, table=False)
        self.assertEqual(json.dumps(ecrit["plans"]), json.dumps(sans_table["plans"]))
        self.assertEqual(sorted(sans_table), ["computed_at", "order_values", "plans"])
        self.assertEqual(sans_table["order_values"], ecrit["order_values"])

    def test_export_probabilite_avant_renfort(self):
        # MAO promis : le moteur classe avec les probabilités renforcées, l'export
        # écrit celles d'avant le renfort, à 6 chiffres significatifs.
        table = [(self.A1, 0.10, 0.2), (self.A2, 0.17, 1 / 3), (self.A3, 0.13, 1 - 0.2 - 1 / 3)]
        action_values, avant = banc.classer(table, 0.1, [MAO])
        self.assertNotAlmostEqual(dict((a, p) for a, _, p, _ in action_values)[self.A2], 1 / 3, places=3)
        with tempfile.TemporaryDirectory() as dossier:
            ecrit = banc.exporter(action_values, dossier, avant)
        self.assertEqual(
            {tuple(c["orders"]): c["prob"] for c in ecrit["candidates"]},
            {self.A1: 0.2, self.A2: 0.333333, self.A3: 0.466667},
        )
        # Une action absente de la politique d'avant renfort : pas de table du tout.
        with tempfile.TemporaryDirectory() as dossier, self.assertLogs(level="WARNING"):
            ecrit = banc.exporter(action_values, dossier, {self.A1: 0.2})
        self.assertEqual(sorted(ecrit), ["computed_at", "order_values", "plans"])

    def test_d_gain_sur_la_nouvelle_grandeur(self):
        # +0,03 (0,13 - 0,10) ; l'ancienne grandeur, la meilleure valeur brute, donnait 0,07.
        for regularize_lambda in (0.1, 0.01):
            index = entree_expert(regularize_lambda)["order_values"]
            self.assertAlmostEqual(index[PIC] - index[BUR], 0.03, places=9)
        brute = max(valeur for action, valeur, _ in TABLE_EXPERT if PIC in action)
        self.assertAlmostEqual(brute - 0.10, 0.07, places=9)

    def test_scores_recalcules(self):
        for regularize_lambda, annonces in ((0.1, (0.0486, -0.4112, 0.0381)), (0.01, (0.0949, 0.1119, 0.1208))):
            with self.subTest(regularize_lambda=regularize_lambda):
                ecrit = entree_expert(regularize_lambda)
                lignes = banc.pseudo_commitments.rescored_candidates(ecrit["candidates"], ecrit["search"], [PIC])
                obtenus = {action: score for action, _, _, score in lignes}
                attendus = self.scores_attendus(regularize_lambda)
                for action, annonce in zip((self.A1, self.A2, self.A3), annonces):
                    self.assertAlmostEqual(obtenus[action], attendus[action], places=12)
                    self.assertAlmostEqual(obtenus[action], annonce, places=4)

    def test_ligne_6_bis_le_moteur_ne_jouerait_pas_n(self):
        # lambda 0,1 : a1 garde la tête après renfort. Marge 0,02 : le gain passe, pas la condition.
        ecrit = entree_expert(0.1)
        tete = banc.pseudo_commitments.engine_head_action(ecrit["candidates"], ecrit["search"], [PIC])
        self.assertEqual(tete, self.A1)
        retour, anterieurs = rejet_sur(ecrit, [PIC], {"ENGLAND": [BUR]}, [BUR], margin=0.02)
        self.assertEqual(retour, ([], [(PIC, BUR, "not_played", 0.03)], [], [], []))
        self.assertEqual(anterieurs, {"ENGLAND": [BUR]})

    def test_ligne_7_accepte_a_0_02_refuse_a_0_05(self):
        # lambda 0,01 : a3, qui porte PIC, prend la tête.
        ecrit = entree_expert(0.01)
        tete = banc.pseudo_commitments.engine_head_action(ecrit["candidates"], ecrit["search"], [PIC])
        self.assertEqual(tete, self.A3)
        retour, _ = rejet_sur(ecrit, [PIC], {"ENGLAND": [BUR]}, [BUR], margin=0.02)
        self.assertEqual(retour, ([PIC], [], [("ENGLAND", BUR, PIC, 0.03)], [], []))
        retour, _ = rejet_sur(ecrit, [PIC], {"ENGLAND": [BUR]}, [BUR], margin=0.05)
        self.assertEqual(retour, ([], [(PIC, BUR, "below_margin", 0.03)], [], [], []))
        # Sans paramètre, la marge est celle de la branche : refusé.
        retour, _ = rejet_sur(ecrit, [PIC], {"ENGLAND": [BUR]}, [BUR])
        self.assertEqual(retour[1], [(PIC, BUR, "below_margin", 0.03)])

    def test_cycle_ligne_6_bis_etat_inchange(self):
        # À la marge de 0,05 : gain de 0,07, mais (BUR, MAO) garde la tête (lambda 0,1).
        ecrit = mesure_promesses.entree_exportee(TABLE_6BIS, 0.1)
        self.assertAlmostEqual(ecrit["order_values"][PIC] - ecrit["order_values"][BUR], 0.07, places=9)
        with banc.Banc(ecrit) as essai:
            essai.message("ENGLAND", [BUR])
            avant = (essai.by_recipient(), essai.fichier_engagements.read_text(), essai.promesses_du_bot())
            journal = essai.message("GERMANY", [PIC], [BUR])
            self.assertEqual(essai.retours[-1][:3], ([], [(PIC, BUR, "not_played", 0.07)], []))
            self.assertEqual(banc.balises(journal), {"[betrayal-refused]": 1})
            refus = [l for l in journal.splitlines() if "[betrayal-refused]" in l][0]
            self.assertIn(
                "value gain +0.0700 is above the margin but the engine would still not play "
                "'A PAR - PIC' once it replaces the promise (not_played)", refus,
            )
            self.assertEqual(
                (essai.by_recipient(), essai.fichier_engagements.read_text(), essai.promesses_du_bot()), avant
            )
        # La même table, lambda 0,01 : le moteur jouerait PIC, la trahison est acceptée (ligne 7).
        retour, balises, par_destinataire, engagements = cycle(
            [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])], mesure_promesses.entree_exportee(TABLE_6BIS, 0.01)
        )
        self.assertEqual(balises, {"[betrayal]": 1})
        self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [], "GERMANY": [PIC]}, [PIC]))

    def test_ligne_5_table_absente_ou_illisible(self):
        # Sans candidates ou sans search, ou avec une table mal formée : unknown_value,
        # jamais une acceptation, même avec un gain de 0,8.
        bons = banc.candidats_du_banc(banc.PLANS_CONNUS)
        ligne_pic, ligne_bur = bons
        mauvaises_tables = [
            None, [], {}, "table", [ligne_pic, "action"], [ligne_pic, ligne_pic],
            [ligne_pic, {"orders": [BUR], "value": float("nan"), "prob": 0.5}],
            [ligne_pic, {"orders": [BUR], "value": 0.1, "prob": float("inf")}],
            [ligne_pic, {"orders": [BUR], "value": 0.1, "prob": -0.1}],
            [ligne_pic, {"orders": [BUR], "value": 0.1}],
            [ligne_pic, {"orders": BUR, "value": 0.1, "prob": 0.5}],
        ]
        mauvaises_recherches = [
            None, {}, [], {"lambda": 0.01, "boost": 3.0}, {"lambda": None, "boost": 3.0, "max_prob": 0.4},
            {"lambda": float("nan"), "boost": 3.0, "max_prob": 0.4},
            {"lambda": 0.01, "boost": 0, "max_prob": 0.4}, {"lambda": -1, "boost": 3.0, "max_prob": 0.4},
            {"lambda": 0.01, "boost": 3.0, "max_prob": "0.4"},
        ]
        appels = [dict(candidates=t, search=banc.RECHERCHE) for t in mauvaises_tables]
        appels += [dict(candidates=bons, search=r) for r in mauvaises_recherches]
        for options in appels:
            with self.subTest(**options):
                with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing):
                    retour = banc.bot._reject_contradictions(
                        [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR], **options
                    )
                self.assertEqual(retour[:3], ([], [(PIC, BUR, "unknown_value", None)], []))
        # Témoin : la même entrée avec la table du banc est acceptée.
        retour, _ = banc.rejet_complet([PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR])
        self.assertEqual(retour[0], [PIC])

    def test_ligne_5_n_absent_des_candidats(self):
        # PIC a une valeur dans l'index mais aucune action candidate ne le joue.
        retour, _ = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR],
            order_values={PIC: 0.9, BUR: 0.1}, candidates=banc.candidats(((BUR,), 0.1), ((GAS,), 0.05)),
        )
        self.assertEqual(retour[:3], ([], [(PIC, BUR, "unknown_value", None)], []))

    def test_cycle_ligne_5_entree_sans_table(self):
        for entree_plans in (
            banc.entree_ancienne(banc.PLANS_CONNUS), banc.entree_ancienne(banc.PLANS_CONNUS, {PIC: 0.9, BUR: 0.1}),
            {k: v for k, v in banc.entree(banc.PLANS_CONNUS).items() if k != "search"},
            {k: v for k, v in banc.entree(banc.PLANS_CONNUS).items() if k != "candidates"},
        ):
            with self.subTest(cles=sorted(entree_plans)):
                retour, balises, par_destinataire, engagements = cycle(
                    [("ENGLAND", [BUR]), ("GERMANY", [PIC], [BUR])], entree_plans
                )
                self.assertEqual(retour[:3], ([], [(PIC, BUR, "unknown_value", None)], []))
                self.assertEqual(balises, {"[betrayal-refused]": 1})
                self.assertEqual((par_destinataire, engagements), ({"ENGLAND": [BUR]}, [BUR]))

    def test_meme_renfort_que_le_moteur(self):
        # Sur une même table, les probabilités que le bot recalcule (rescored_candidates)
        # sont celles que apply_commitments_to_policy donne au moteur, exactement.
        tables = (TABLE_EXPERT, TABLE_6BIS, [(A3, 0.2, 0.5), (A1, 0.3, 0.3), (A2, 0.1, 0.2)])
        for table in tables:
            for promesses in ([PIC], [BUR], [MAO, PIC], banc.PROMESSES_4, []):
                with self.subTest(table=table[0], promesses=promesses):
                    avant = {action: p for action, _, p in table}
                    table_exportee = [{"orders": list(a), "value": v, "prob": p} for a, v, p in table]
                    lignes = banc.pseudo_commitments.rescored_candidates(table_exportee, banc.RECHERCHE, promesses)
                    moteur = banc.pseudo_commitments.apply_commitments_to_policy(
                        {"FRANCE": dict(avant)}, banc.FauxJeu(), {"FRANCE": list(promesses)}, "FRANCE",
                        banc.RECHERCHE["boost"],
                    )["FRANCE"]
                    self.assertEqual({action: q for action, _, q, _ in lignes}, moteur)
                    self.assertEqual(banc.RECHERCHE["max_prob"], banc.pseudo_commitments.MAX_COMMITMENT_PROB)

    def test_tete_premiere_en_cas_d_egalite(self):
        table = banc.candidats(((BUR,), 0.5), ((PIC,), 0.5), ((GAS,), 0.5))
        self.assertEqual(banc.pseudo_commitments.engine_head_action(table, banc.RECHERCHE, []), (BUR,))
        self.assertEqual(banc.pseudo_commitments.engine_head_action(table, banc.RECHERCHE, [GAS]), (GAS,))

    def test_s_prime_tous_destinataires(self):
        # S' réunit les engagements de tous les destinataires. Seul, PIC porterait
        # (PIC, PIE, ENG) en tête ; avec MAO et SPA promis à l'Allemagne, n = 3 et
        # (BUR, SPA, MAO), qui en tient deux, reste en tête : le moteur ne jouerait pas PIC.
        table = [
            {"orders": [BUR, SPA, MAO], "value": 0.30, "prob": 0.2},
            {"orders": [PIC, PIE, ENG], "value": 0.40, "prob": 0.2},
            {"orders": [GAS, PIE, ENG], "value": 0.0, "prob": 0.6},
        ]
        recherche = {"lambda": 0.5, "boost": 3.0, "max_prob": 1.0}
        index = {BUR: 0.30, SPA: 0.30, MAO: 0.30, PIC: 0.40, PIE: 0.40, ENG: 0.40, GAS: 0.0}
        tete = lambda promis: banc.pseudo_commitments.engine_head_action(table, recherche, promis)
        self.assertEqual(tete([PIC]), (PIC, PIE, ENG))
        self.assertEqual(tete([PIC, MAO, SPA]), (BUR, SPA, MAO))
        # Recalcul de la tête conjointe : facteurs 3^(2/3), 3^(1/3) et 1.
        brut = [0.2 * 3 ** (2 / 3), 0.2 * 3 ** (1 / 3), 0.6]
        scores = [v + 0.5 * math.log(p / sum(brut)) for v, p in zip((0.30, 0.40, 0.0), brut)]
        self.assertEqual(scores.index(max(scores)), 0)
        options = dict(betray=[BUR], order_values=index, candidates=table, search=recherche)
        retour, _ = banc.rejet_complet([PIC], {"ENGLAND": [BUR]}, [], **options)
        self.assertEqual(retour[:3], ([PIC], [], [("ENGLAND", BUR, PIC, 0.1)]))
        retour, anterieurs = banc.rejet_complet(
            [PIC], {"ENGLAND": [BUR], "GERMANY": [MAO, SPA]}, [], **options
        )
        self.assertEqual(retour[:3], ([], [(PIC, BUR, "not_played", 0.1)], []))
        self.assertEqual(anterieurs, {"ENGLAND": [BUR], "GERMANY": [MAO, SPA]})

    def test_plusieurs_trahisons_l_une_refusee_l_autre_rejugee(self):
        # Deux remplacements déclarés dans un message : S' conjoint {PIC, PIE}, tête
        # (PIC, SPA), PIE refusé. SPA revenu, S' = {PIC, SPA} : PIC, rejugé, reste en tête.
        table = [
            {"orders": [PIC, SPA], "value": 0.50, "prob": 0.4},
            {"orders": [BUR, SPA], "value": 0.20, "prob": 0.3},
            {"orders": [BUR, PIE], "value": 0.45, "prob": 0.2},
            {"orders": [PIC, PIE], "value": 0.10, "prob": 0.1},
        ]
        index = {PIC: 0.50, SPA: 0.20, BUR: 0.20, PIE: 0.45}
        retour, anterieurs = banc.rejet_complet(
            [PIC, PIE], {"ENGLAND": [BUR, SPA]}, [], betray=[BUR, SPA],
            order_values=index, candidates=table,
        )
        tete = lambda promis: banc.pseudo_commitments.engine_head_action(table, banc.RECHERCHE, promis)
        self.assertEqual((tete([PIC, PIE]), tete([PIC, SPA])), ((PIC, SPA), (PIC, SPA)))
        self.assertEqual(retour, (
            [PIC], [(PIE, SPA, "not_played", 0.25)], [("ENGLAND", BUR, PIC, 0.3)], [], [],
        ))

    def test_plusieurs_trahisons_exemple_de_l_audit(self):
        # Avec SPA et F BRE H, (BUR, PIE, F BRE H) est en tête : SPA est refusé, F BRE H
        # passerait. A MAR H revenu, (BUR, A MAR H, MAO) prend la tête : F BRE H, rejugé,
        # est refusé à son tour, et l'engagement ENG reste.
        ecrit = mesure_promesses.entree_exportee(TABLE_AUDIT, 0.1, [MAR_H, ENG])
        tete = lambda promis: banc.pseudo_commitments.engine_head_action(
            ecrit["candidates"], ecrit["search"], promis
        )
        self.assertEqual(tete([SPA, BRE_H]), (BUR, PIE, BRE_H))
        self.assertEqual(tete([MAR_H, BRE_H]), (BUR, MAR_H, MAO))
        self.assertAlmostEqual(ecrit["order_values"][BRE_H] - ecrit["order_values"][ENG], 0.12, places=9)
        retour, tete_finale = mesure_promesses.rejet_audit()
        self.assertEqual(retour, (
            [], [(SPA, MAR_H, "not_played", 0.1), (BRE_H, ENG, "not_played", 0.12)], [], [], [],
        ))
        self.assertEqual(tete_finale, (BUR, MAR_H, MAO))

    def test_tout_remplacement_accepte_est_dans_la_tete_de_l_etat_final(self):
        # Tables engendrées, trois trahisons déclarées par message : aucun ordre accepté
        # en remplacement n'est hors de l'action de tête des promesses finales.
        cas = list(banc.tables_engendrees(mesure_promesses.TABLES_ENGENDREES))
        acceptes, fautifs, premier = banc.remplacements_hors_tete(cas)
        self.assertEqual(fautifs, 0, premier)
        self.assertGreater(acceptes, 1000)
        # L'échantillon mesure quelque chose : une seule passe, sans rejuger après un
        # refus (le code d'avant), y laisse des remplacements hors tête.
        self.assertGreater(banc.remplacements_hors_tete(cas, une_seule_passe)[1], 0)

    def test_une_seule_trahison_meme_resultat_qu_en_une_passe(self):
        # Avec au plus un remplacement en attente du verdict du moteur, rejuger ne change rien.
        seuls = 0
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing):
            for ecrit, anterieurs, sincere, betray in banc.tables_engendrees(mesure_promesses.TABLES_ENGENDREES):
                options = dict(
                    betray=betray, order_values=ecrit["order_values"],
                    candidates=ecrit["candidates"], search=ecrit["search"],
                )
                reference = une_seule_passe(sincere, anterieurs, [], **options)
                if len(reference[2]) + sum(1 for r in reference[1] if r[2] == "not_played") > 1:
                    continue
                seuls += 1
                self.assertEqual(banc.bot._reject_contradictions(sincere, anterieurs, [], **options), reference)
        self.assertGreater(seuls, 500)

    def test_plancher_du_score(self):
        # (PIC,) : 0,25 à la probabilité 1e-8, sous le plancher. Au plancher de 1e-6, son
        # score dépasse celui de (BUR,) ; avec ln(1e-8) il resterait derrière.
        rescore = banc.pseudo_commitments.rescored_candidates
        self.assertEqual(banc.pseudo_commitments.SCORE_PROB_FLOOR, 1e-6)
        scores = [score for _, _, _, score in rescore(TABLE_PLANCHER, banc.RECHERCHE, [])]
        self.assertAlmostEqual(scores[0], 0.10, places=12)
        self.assertAlmostEqual(scores[1], 0.25 + 0.01 * math.log(1e-6), places=12)
        self.assertLess(0.25 + 0.01 * math.log(1e-8), scores[0])
        self.assertEqual(
            banc.pseudo_commitments.engine_head_action(TABLE_PLANCHER, banc.RECHERCHE, []), (PIC,)
        )
        # Témoin : à 1e-6 juste, la même table donne le même score ; le plancher seul décide.
        au_plancher = [TABLE_PLANCHER[0], dict(TABLE_PLANCHER[1], prob=1e-6)]
        self.assertEqual([s for _, _, _, s in rescore(au_plancher, banc.RECHERCHE, [])][1], scores[1])
        # Un plancher plus bas (1e-9) rend la tête à (BUR,).
        with mock.patch.object(banc.pseudo_commitments, "SCORE_PROB_FLOOR", 1e-9):
            self.assertEqual(
                banc.pseudo_commitments.engine_head_action(TABLE_PLANCHER, banc.RECHERCHE, []), (BUR,)
            )
        # Le même plancher que le classement du moteur (banc.classer, 1e-6 en dur).
        action_values, _ = banc.classer([((BUR,), 0.10, 1.0), ((PIC,), 0.25, 1e-8)], 0.01)
        self.assertEqual([(a, s) for a, _, _, s in action_values], [((PIC,), scores[1]), ((BUR,), scores[0])])

    def test_export_table_illisible_les_plans_sont_ecrits(self):
        # Probabilité None, lambda non numérique : float() lève dans _search_table. Ni
        # candidates ni search, un avertissement, mais plans et order_values sont écrits.
        action_values, _ = banc.classer(TABLE_EXPERT, 0.1, [BUR])
        with tempfile.TemporaryDirectory() as dossier:
            sans_table = banc.exporter(action_values, dossier, table=False)
        for cas, options in mesure_promesses.EXPORTS_ILLISIBLES:
            with self.subTest(cas=cas):
                ecrit, avertissements = mesure_promesses.exporter_illisible(options)
                self.assertIsNotNone(ecrit)
                self.assertEqual(sorted(ecrit), ["computed_at", "order_values", "plans"])
                self.assertEqual(ecrit["plans"], sans_table["plans"])
                self.assertEqual(ecrit["order_values"], sans_table["order_values"])
                self.assertEqual(len(avertissements), 1)
                self.assertIn("no usable candidate table for FRANCE S1901M (", avertissements[0])
                self.assertIn("`candidates` and `search` not written", avertissements[0])


def une_seule_passe(sincere, by_recipient, plans=None, **options):
    """_reject_contradictions tel qu'il jugeait la condition moteur avant la correction :
    une tête pour tous les remplacements du message, sans rejuger après un refus.

    Obtenu du code du dépôt en ne laissant qu'un tour à sa boucle : la première
    tête sert à tous, et le remplacement que le premier tour laisse passer est accepté.
    """
    tetes = []

    def premiere_tete(candidates, search, promis):
        promis = list(promis)
        if not promis:  # contrôle de lisibilité de la table
            return banc.pseudo_commitments.engine_head_action(candidates, search, promis)
        if not tetes:
            tetes.append(banc.pseudo_commitments.engine_head_action(candidates, search, promis))
            return tetes[0]
        # Tours suivants : une tête qui contient tout, donc plus aucun refus.
        return tuple(o for c in candidates for o in c["orders"])

    with mock.patch.object(banc.bot, "engine_head_action", premiere_tete):
        return banc.bot._reject_contradictions(list(sincere), by_recipient, plans, **options)


TITRE_ENGAGEMENTS = (
    "Promises you have already made this phase (real intentions -- your engine is acting on them; "
    "costs are relative to your preferred plan):"
)
REGLES_ENGAGEMENTS = (
    "  Your word is an asset. Each of these powers sees at the end of the turn whether you did "
    "what you said; a broken promise costs you their trust for the rest of the game.\n"
    '  Default: keep them. If what is asked now conflicts with one, decline, or bluff (a bluff '
    'never goes in "sincere").\n'
    "  You MAY deliberately break one -- that is Diplomacy -- but only as a declared decision: put "
    'the earlier order, exactly as written above, in "betray", and the order replacing it in '
    '"sincere". Your engine honours the switch only if what it would play when held to the replacing '
    "order is worth clearly more (by more than 0.05) than what it would play when held to the promise, "
    "and only if it would then actually play the replacing order. Otherwise the earlier promise stands "
    "and what you just said is a bluff.\n\n"
)


def section_engagements(*lignes):
    return "\n".join((TITRE_ENGAGEMENTS,) + lignes) + "\n" + REGLES_ENGAGEMENTS


class ConsigneDesPromesses(unittest.TestCase):
    """#17 : texte exact de la section des engagements et du bilan du bot."""

    def section(self, promis, courant="GERMANY", plans=mesure_promesses.PLANS_SECTION,
                index=mesure_promesses.INDEX_SECTION, table=True):
        # `table` faux : entrée sans candidates ni search (ancien format).
        options = mesure_promesses.TABLE_SECTION if table else {}
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing):
            return banc.bot.build_commitments_section(promis, courant, plans, index, **options)

    def test_engagements_cout_positif_nul_negatif_inconnu(self):
        # Plan préféré à 0,500 ; BUR 0,448, MAO 0,500, SPA 0,530, GAS hors de l'index.
        self.assertEqual(
            self.section(mesure_promesses.PROMIS_SECTION),
            section_engagements(
                "  - to ENGLAND: A PAR - BUR  [keeping it costs 0.052]",
                "  - to GERMANY (this conversation): F BRE - MAO  [keeping it is free]",
                "  - to GERMANY (this conversation): A MAR - SPA  [keeping it is free]",
                "  - to ITALY: A PAR - GAS  [value unknown: cannot be replaced this phase]",
            ),
        )

    def test_engagements_le_cout_est_celui_que_compare_la_table(self):
        # Coût affiché = valeur du plan préféré - _order_value : le même nombre que la table.
        valeur = banc.bot._order_value(BUR, mesure_promesses.PLANS_SECTION, mesure_promesses.INDEX_SECTION)
        self.assertIn("%s  [keeping it costs %.3f]" % (BUR, 0.5 - valeur), self.section({"ENGLAND": [BUR]}))

    def test_engagements_reference_dite_une_fois_dans_l_en_tete(self):
        section = self.section({"ITALY": [GAS], "ENGLAND": [BUR, MAO]})
        self.assertEqual(
            section,
            section_engagements(
                "  - to ITALY: A PAR - GAS  [value unknown: cannot be replaced this phase]",
                "  - to ENGLAND: A PAR - BUR  [keeping it costs 0.052]",
                "  - to ENGLAND: F BRE - MAO  [keeping it is free]",
            ),
        )
        self.assertEqual(section.count("preferred plan"), 1)

    def test_bornage_free_dans_les_deux_sections(self):
        # Coûts de 0,0004, -0,010 et 0,012 : « free » pour les deux premiers, le
        # troisième sans signe ; l'export de cost_vs_best, lui, garde son signe.
        section = self.section(
            mesure_promesses.PROMIS_BORNAGE, index=mesure_promesses.INDEX_BORNAGE
        )
        self.assertEqual(section, section_engagements(
            "  - to ENGLAND: F BRE - MAO  [keeping it is free]",
            "  - to ENGLAND: A MAR - SPA  [keeping it is free]",
            "  - to ENGLAND: A PAR - BUR  [keeping it costs 0.012]",
        ))
        plans = mesure_promesses.section_des_plans(mesure_promesses.PLANS_BORNAGE)
        self.assertIn(
            "    - free: F BRE - MAO\n    - free: A MAR - SPA\n    - cost 0.012: A PAR - BUR\n"
            '  "free" means that alternative costs you nothing, and a cost near 0 almost nothing: you can '
            "genuinely agree to either if the deal is worth it. A large cost means giving it up would "
            "really hurt -- resist, or extract something substantial in exchange.\n",
            plans,
        )
        for texte in (section, plans):
            for mot in ("-0.0", "+0.0", "0.000", "nan"):
                self.assertNotIn(mot, texte)
        self.assertEqual(mesure_promesses.PLANS_BORNAGE[2]["cost_vs_best"], -0.01)

    def test_bornage_seuil_et_valeurs_non_finies(self):
        montre = banc.bot._shown_cost
        self.assertEqual(
            [montre(c) for c in (0.0, -0.0, 0.0005, 0.5 - 0.4995, 0.00051, 0.012, -3.0)],
            ["free", "free", "free", "free", "0.001", "0.012", "free"],
        )
        for mauvais in (float("nan"), float("inf"), float("-inf"), None, "0.1", True):
            self.assertIsNone(montre(mauvais))
        # Coût non numérique dans la liste des plans : dit inconnu, ni nan ni inf.
        plans = mesure_promesses.section_des_plans([
            {"orders": [PIC], "value": 0.5, "cost_vs_best": 0.0},
            {"orders": [BUR], "value": float("nan"), "cost_vs_best": float("nan")},
            {"orders": [GAS], "value": 0.1},
        ])
        self.assertIn("    - cost unknown: A PAR - BUR\n    - cost unknown: A PAR - GAS\n", plans)
        self.assertNotIn("nan", plans)

    def test_engagements_reference_manquante_cout_inconnu(self):
        # La valeur de l'ordre est connue, pas celle du plan préféré (plans vides ou
        # valeur non numérique) : le coût est dit inconnu, sans nan ni inf.
        for plans_exportes in ([], None, [{"orders": [PIC]}], [{"orders": [PIC], "value": float("nan")}],
                               [{"orders": [PIC], "value": "0.5"}], ["plan"]):
            with self.subTest(plans=plans_exportes):
                section = self.section({"ENGLAND": [BUR]}, plans=plans_exportes)
                self.assertEqual(section, section_engagements("  - to ENGLAND: A PAR - BUR  [cost unknown]"))

    def test_engagements_ancien_format_repli_sur_les_plans(self):
        # Sans index : valeur lue dans les plans (PIC 0,9, BUR 0,1) ; GAS, hors des plans, inconnu.
        # Sans table non plus : le coût se lit, mais aucune promesse n'est remplaçable.
        section = self.section({"ENGLAND": [BUR, PIC, GAS]}, plans=banc.PLANS_CONNUS, index=None, table=False)
        self.assertEqual(
            section,
            section_engagements(
                "  - to ENGLAND: A PAR - BUR  [keeping it costs 0.800; cannot be replaced this phase]",
                "  - to ENGLAND: A PAR - PIC  [keeping it is free; cannot be replaced this phase]",
                "  - to ENGLAND: A PAR - GAS  [value unknown: cannot be replaced this phase]",
            ),
        )

    def test_engagements_sans_table_irremplacable(self):
        # Entrée avec index mais sans table, ou dont la table est illisible : ce que la
        # section annonce est ce que fait _reject_contradictions (ligne 5), gain de 0,8 compris.
        index = {PIC: 0.9, BUR: 0.1}
        lisible = dict(candidates=banc.candidats_du_banc(banc.PLANS_CONNUS, index), search=banc.RECHERCHE)
        for options in ({}, dict(lisible, search=None), dict(lisible, candidates=[]),
                        dict(lisible, search={"lambda": None, "boost": 3.0, "max_prob": 0.4})):
            with self.subTest(**options):
                with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing):
                    section = banc.bot.build_commitments_section(
                        {"ENGLAND": [BUR, PIC]}, "GERMANY", banc.PLANS_CONNUS, index, **options
                    )
                    retour = banc.bot._reject_contradictions(
                        [PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR], order_values=index, **options
                    )
                self.assertEqual(section, section_engagements(
                    "  - to ENGLAND: A PAR - BUR  [keeping it costs 0.800; cannot be replaced this phase]",
                    "  - to ENGLAND: A PAR - PIC  [keeping it is free; cannot be replaced this phase]",
                ))
                self.assertEqual(retour[1], [(PIC, BUR, "unknown_value", None)])
        # Témoin : avec la table, ni suffixe ni refus.
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing):
            section = banc.bot.build_commitments_section(
                {"ENGLAND": [BUR]}, "GERMANY", banc.PLANS_CONNUS, index, **lisible
            )
        self.assertEqual(section, section_engagements("  - to ENGLAND: A PAR - BUR  [keeping it costs 0.800]"))
        retour, _ = banc.rejet_complet([PIC], {"ENGLAND": [BUR]}, banc.PLANS_CONNUS, betray=[BUR], order_values=index)
        self.assertEqual(retour[2], [("ENGLAND", BUR, PIC, 0.8)])

    def test_cycle_consigne_d_une_entree_sans_table(self):
        # Par le cycle du bot : la table de l'entrée arrive jusqu'à la section.
        for entree_plans, attendu in (
            (banc.entree(banc.PLANS_CONNUS), "A PAR - BUR  [keeping it costs 0.800]\n"),
            (banc.entree_ancienne(banc.PLANS_CONNUS, {PIC: 0.9, BUR: 0.1}),
             "A PAR - BUR  [keeping it costs 0.800; cannot be replaced this phase]\n"),
        ):
            with self.subTest(cles=sorted(entree_plans)), banc.Banc(entree_plans) as essai:
                essai.message("ENGLAND", [BUR])
                essai.message("GERMANY", [])
                self.assertIn(attendu, essai.consignes[-1])

    def test_engagements_cout_negatif_quand_le_plan_prefere_n_est_pas_le_mieux_valorise(self):
        # Plans triés par score : le préféré vaut 0,10, le second 0,90. Un coût négatif est « free ».
        plans_exportes = banc.plans((BUR, 0.10), (PIC, 0.90))
        section = self.section({"ENGLAND": [PIC]}, plans=plans_exportes, index=None)
        self.assertIn("A PAR - PIC  [keeping it is free]", section)

    def test_engagements_sans_plan_valeur_inconnue(self):
        for plans_exportes in (None, []):
            section = self.section({"ENGLAND": [BUR]}, plans=plans_exportes, index=None)
            self.assertEqual(
                section,
                section_engagements("  - to ENGLAND: A PAR - BUR  [value unknown: cannot be replaced this phase]"),
            )

    def test_engagements_valeur_inconnue_veut_dire_remplacement_refuse(self):
        # Ce que la section annonce (« cannot be replaced ») est ce que fait la table (ligne 5).
        retour, _ = banc.rejet_complet(
            [PIC], {"ITALY": [GAS]}, mesure_promesses.PLANS_SECTION, betray=[GAS],
            order_values=mesure_promesses.INDEX_SECTION,
        )
        self.assertEqual(retour[1], [(PIC, GAS, "unknown_value", None)])

    def test_engagements_aucune_section_sans_promesse(self):
        self.assertEqual(self.section({}), "")
        self.assertEqual(self.section({"ENGLAND": [], "GERMANY": []}), "")

    def test_engagements_marge_affichee(self):
        self.assertIn("(by more than %s)" % banc.bot.COMMITMENT_SWITCH_MARGIN, self.section({"ENGLAND": [BUR]}))
        with mock.patch.object(banc.bot, "COMMITMENT_SWITCH_MARGIN", 0.08):
            self.assertIn("(by more than 0.08)", self.section({"ENGLAND": [BUR]}))

    def test_condition_dite_aux_deux_endroits(self):
        # Section des engagements et paragraphe « betray » : marge et condition moteur.
        condition = (
            "Your engine honours the switch only if what it would play when held to the replacing order "
            "is worth clearly more (by more than 0.05) than what it would play when held to the promise, "
            "and only if it would then actually play the replacing order"
        )
        # L'ancienne formulation (« belongs to a plan », « best plan keeping ») n'y est plus.
        for perime in ("belongs to a plan", "best plan keeping the promise"):
            self.assertNotIn(perime, mesure_promesses.consigne(commitments_section=self.section({"ENGLAND": [BUR]})))
        self.assertIn(condition + ". Otherwise", self.section({"ENGLAND": [BUR]}))
        self.assertIn(condition + "; otherwise the earlier promise stands.", mesure_promesses.consigne())
        self.assertEqual(
            mesure_promesses.consigne(commitments_section=self.section({"ENGLAND": [BUR]})).count(condition), 2
        )

    def test_bilan_texte_exact(self):
        attendus = {
            "aucune promesse": "",
            "tout tenu": (
                "Your own record with ENGLAND: 3 promise(s) kept, 0 broken.\n"
                "  ENGLAND has seen you keep your word every time. That credit is worth protecting.\n\n"
            ),
            "une rupture": (
                "Your own record with ENGLAND: 3 promise(s) kept, 1 broken.\n"
                "  - F1902M: you promised 'F ENG - NTH' and played 'F ENG S F NWG - NTH'\n"
                "  ENGLAND saw this. Expect less trust from them; do not pretend it did not happen.\n\n"
            ),
            # Trois exemples au plus, les plus récents.
            "quatre ruptures": (
                "Your own record with ENGLAND: 0 promise(s) kept, 4 broken.\n"
                "  - S1902M: you promised 'A PAR - BUR' and played 'A PAR - PIC'\n"
                "  - S1903M: you promised 'A PAR - BUR' and played 'A PAR - PIC'\n"
                "  - S1904M: you promised 'A PAR - BUR' and played 'A PAR - PIC'\n"
                "  ENGLAND saw this. Expect less trust from them; do not pretend it did not happen.\n\n"
            ),
        }
        self.assertEqual(sorted(attendus), sorted(cas for cas, _ in mesure_promesses.BILANS))
        for cas, bilan in mesure_promesses.BILANS:
            with self.subTest(cas=cas):
                self.assertEqual(banc.bot.build_own_record_section(bilan, "ENGLAND"), attendus[cas])

    def test_bilan_vide_sans_promesse_resolue(self):
        vide = {"ENGLAND": {"kept": 0, "broken": 0, "examples": []}}
        self.assertEqual(banc.bot.build_own_record_section(vide, "ENGLAND"), "")

    def test_bilan_rien_sur_un_tiers(self):
        # Parcimonie : la section d'un interlocuteur ne dit rien du bilan envers un autre.
        bilan = dict(mesure_promesses.BILANS[2][1])
        bilan["GERMANY"] = {"kept": 0, "broken": 1, "examples": [
            {"phase": "S1903M", "promised": PIE, "actual": "A MAR H"},
        ]}
        section = banc.bot.build_own_record_section(bilan, "ENGLAND")
        self.assertEqual(section, banc.bot.build_own_record_section(mesure_promesses.BILANS[2][1], "ENGLAND"))
        for mot in ("GERMANY", PIE, "S1903M"):
            self.assertNotIn(mot, section)
        self.assertEqual(banc.bot.build_own_record_section(bilan, "ITALY"), "")

    def test_consigne_sans_phrase_contradictoire(self):
        complete = mesure_promesses.consigne(
            commitments_section=self.section(mesure_promesses.PROMIS_SECTION),
            own_record_section=banc.bot.build_own_record_section(mesure_promesses.BILANS[2][1], "GERMANY"),
        )
        for phrase in ("must not contradict", "must either decline", "Already committed", "Stay consistent"):
            self.assertNotIn(phrase, complete)
        # Le format de sortie renvoie au titre de la section, tel qu'elle l'écrit.
        self.assertIn('a promise listed under "Promises you have already made this phase" above', complete)
        self.assertEqual(complete.count("Promises you have already made this phase"), 2)
        self.assertIn(
            "- Never reveal what you promised to another power, nor that you are breaking a promise "
            "made to someone else.\n",
            complete,
        )

    def test_consigne_ordre_des_sections(self):
        complete = mesure_promesses.consigne(
            plan_section="<PLAN>", commitments_section="<ENGAGEMENTS>",
            own_record_section="<BILAN>", trust_section="<CONFIANCE>",
        )
        self.assertIn("<PLAN><ENGAGEMENTS><BILAN><CONFIANCE>Not every incoming message", complete)

    def test_extraction_des_promesses_du_joueur_non_touchee(self):
        # COMMITMENT_SYSTEM_PROMPT ne parle ni de betray ni du bilan du bot.
        extraction = banc.bot.COMMITMENT_SYSTEM_PROMPT
        for mot in ("betray", "own record", "Promises you have already made"):
            self.assertNotIn(mot, extraction)


def verify_promises_d_origine(bot, game, game_id, my_power, bot_state):
    """verify_promises telle qu'elle était avant la factorisation (0fdb5bf), recopiée.

    Référence du test avant / après : le registre de confiance du joueur ne doit
    pas changer d'un octet, journal compris.
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
        actual_norm = {bot._normalize_order(o) for o in actual}
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
            if bot._normalize_order(promised) in actual_norm:
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


class JeuResolu(banc.FauxJeu):
    """Deux phases résolues et la phase courante ; `legaux` : unités ordonnables par puissance."""

    def __init__(self, legaux=None, retour_arriere=True):
        super().__init__()
        self.legaux, self.retour_arriere = legaux, retour_arriere
        self.resoudre({
            "FRANCE": ["A PAR - BUR", "F BRE - MAO", "F SPA/SC - MAO"],
            "GERMANY": ["A MUN - RUH"],
            "ENGLAND": [],
        })
        self.resoudre({"FRANCE": ["A PAR H"], "GERMANY": ["A MUN H"]}, "S1902M")

    def get_orderable_locations(self):
        if self.legaux is None:
            return super().get_orderable_locations()
        return self.legaux

    def rolled_back_to_phase_start(self, phase):
        if not self.retour_arriere:
            raise RuntimeError("pas de retour arrière")
        return self


# Promesses du joueur en attente : tenue, rompue, tenue à la côte près, sans espaces,
# unité non ordonnable, mot seul, puissance sans ordre, phase courante, phase inconnue.
PROMESSES_DU_JOUEUR = {
    "S1901M:FRANCE": ["A PAR - BUR", "F BRE - ENG", "F SPA - MAO", "A PAR-BUR", "A MUN - RUH", "été"],
    "S1901M:GERMANY": ["A MUN - BUR", "A MUN - RUH"],
    "S1901M:ENGLAND": ["F LON - NTH"],
    "F1901M:FRANCE": ["A PAR - PIC", "A PAR H"],
    "F1901M:GERMANY": ["A MUN H"],
    "S1902M:FRANCE": ["A PAR - GAS"],
    "W1905A:FRANCE": ["A PAR - GAS"],
}
JEUX_RESOLUS = [
    ("unités de la France seules", {}),
    ("toutes les unités", {"legaux": {"FRANCE": ["PAR", "BRE", "SPA"], "GERMANY": ["MUN"], "ENGLAND": ["LON"]}}),
    ("sans retour arrière", {"retour_arriere": False}),
]


class RegistreDeConfianceInchange(unittest.TestCase):
    """La factorisation de verify_promises ne change rien aux promesses du joueur."""

    def mesurer(self, fonction, etat, **options):
        etat = json.loads(json.dumps(etat))
        sortie = io.StringIO()
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing), \
                contextlib.redirect_stdout(sortie):
            rendu = fonction(JeuResolu(**options), banc.PARTIE, "ITALY", etat)
        return json.dumps(rendu, sort_keys=True), json.dumps(etat, sort_keys=True), sortie.getvalue()

    def origine(self, *args):
        return verify_promises_d_origine(banc.bot, *args)

    def test_avant_apres_identiques(self):
        etats = [
            {"pending_promises": PROMESSES_DU_JOUEUR},
            {"pending_promises": PROMESSES_DU_JOUEUR, "trust": {
                "FRANCE": {"kept": 2, "broken": 1, "examples": [
                    {"phase": "S1900M", "promised": "A PAR H", "actual": "A PAR - BUR"},
                ]},
            }},
            {"pending_promises": {}, "trust": {"FRANCE": {"kept": 1, "broken": 0, "examples": []}}},
            {},
            # Les promesses du bot, dans le même état, ne changent rien à celles du joueur.
            {"pending_promises": PROMESSES_DU_JOUEUR, "own_promises": {
                "pending": {"S1901M:FRANCE": ["A VEN H"]}, "record": {},
            }},
        ]
        for cas, options in JEUX_RESOLUS:
            for i, etat in enumerate(etats):
                with self.subTest(jeu=cas, etat=i):
                    avant = self.mesurer(self.origine, etat, **options)
                    apres = self.mesurer(banc.bot.verify_promises, etat, **options)
                    self.assertEqual(apres, avant)

    def test_la_reference_mesure_quelque_chose(self):
        # Le cas principal exerce les deux verdicts, le journal et les promesses laissées en attente.
        confiance, etat, journal = self.mesurer(
            self.origine, {"pending_promises": PROMESSES_DU_JOUEUR}, **JEUX_RESOLUS[1][1]
        )
        confiance, etat = json.loads(confiance), json.loads(etat)
        # France : BUR, SPA (à la côte près) et H tenues ; ENG et PIC rompues ; le reste écarté.
        self.assertEqual((confiance["FRANCE"]["kept"], confiance["FRANCE"]["broken"]), (3, 2))
        self.assertEqual((confiance["GERMANY"]["kept"], confiance["GERMANY"]["broken"]), (2, 1))
        self.assertEqual(journal.count("[trust]"), 3)
        # L'Angleterre n'a pas d'ordre visible en S1901M : sa promesse reste en attente.
        self.assertEqual(
            sorted(etat["pending_promises"]), ["S1901M:ENGLAND", "S1902M:FRANCE", "W1905A:FRANCE"]
        )
        self.assertNotIn("own_promises", etat)

    def test_cycle_registre_du_joueur_et_bilan_du_bot_separes(self):
        # Dans un cycle, une promesse de l'Allemagne en attente est jugée comme avant,
        # et rien des promesses du bot n'entre dans le registre de confiance.
        with banc.Banc(mesure_promesses.ENTREE_BILAN) as essai:
            for message in mesure_promesses.CAS_BILAN:
                essai.message(*message)
            etat = json.loads(essai.fichier_etat.read_text())
            etat["bot1:%d" % banc.PARTIE]["pending_promises"] = {
                banc.PHASE + ":GERMANY": ["A MUN - RUH", "A MUN - BUR"],
            }
            essai.fichier_etat.write_text(json.dumps(etat))
            essai.recharger()
            essai.jeu.resoudre(mesure_promesses.JOUES_BILAN)
            with mock.patch.object(
                banc.FauxJeu, "get_orderable_locations",
                lambda jeu: {"FRANCE": list(banc.ORDRES_LEGAUX), "GERMANY": ["MUN"]},
            ):
                journal = essai.cycle_sans_message()
            etat = essai.etat_du_bot()
        self.assertEqual(etat["trust"], {"GERMANY": {"kept": 1, "broken": 1, "examples": [
            {"phase": banc.PHASE, "promised": "A MUN - BUR", "actual": "A MUN - RUH"},
        ]}})
        self.assertEqual(etat["pending_promises"], {})
        self.assertEqual(journal.count("[trust]"), 1)
        self.assertEqual(sorted(etat["own_promises"]["record"]), ["ENGLAND", "GERMANY"])


class MemoireDesPromessesDuBot(unittest.TestCase):
    """#17 : own_promises (pending, record), écrit avec by_recipient, résolu contre les ordres joués."""

    CLE = "bot1:%d" % banc.PARTIE
    ANGLETERRE, ALLEMAGNE = banc.PHASE + ":ENGLAND", banc.PHASE + ":GERMANY"

    def essai(self):
        return banc.Banc(mesure_promesses.ENTREE_BILAN)

    def test_promesse_ecrite_avec_by_recipient(self):
        with self.essai() as essai:
            essai.message("ENGLAND", [MAO])
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [MAO]})
            self.assertEqual(essai.promesses_du_bot(), {"pending": {self.ANGLETERRE: [MAO]}, "record": {}})
            # Une redite n'est pas comptée deux fois.
            essai.message("ENGLAND", [MAO])
            self.assertEqual(essai.promesses_du_bot()["pending"], {self.ANGLETERRE: [MAO]})

    def test_rien_n_est_ecrit_dans_les_cas_refuses(self):
        # Sans label, sous la marge, deux ordres, reply nul : own_promises ne bouge pas.
        refus = [
            ("GERMANY", [PIC]),
            ("GERMANY", [PIC, GAS], [BUR]),
            ("GERMANY", [PIC], [BUR], None),
            ("GERMANY", [], [BUR]),
        ]
        for message in refus:
            with self.subTest(message=message):
                with self.essai() as essai:
                    essai.message("ENGLAND", [BUR])
                    avant = essai.promesses_du_bot()
                    essai.message(*message)
                    self.assertEqual(essai.promesses_du_bot(), avant)
                    self.assertEqual(avant["pending"], {self.ANGLETERRE: [BUR]})

    def test_promesse_trahie_reste_en_attente_pour_la_puissance_trahie(self):
        with self.essai() as essai:
            essai.message("ENGLAND", [BUR])
            journal = essai.message("GERMANY", [PIC], [BUR])
            self.assertEqual(banc.balises(journal), {"[betrayal]": 1})
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [], "GERMANY": [PIC]})
            self.assertEqual(
                essai.promesses_du_bot()["pending"], {self.ANGLETERRE: [BUR], self.ALLEMAGNE: [PIC]}
            )

    def test_promesse_revisee_remplacee_pour_le_destinataire(self):
        with self.essai() as essai:
            essai.message("GERMANY", [SPA])
            journal = essai.message("GERMANY", [PIE], [SPA])
            self.assertEqual(banc.balises(journal), {"[revision]": 1})
            self.assertEqual(essai.promesses_du_bot()["pending"], {self.ALLEMAGNE: [PIE]})

    def test_trahison_chez_deux_detenteurs_revision_pour_le_destinataire_seul(self):
        # Cas D : BUR promis aux deux ; l'Allemagne est révisée, l'Angleterre trahie.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            for message in mesure_promesses.CAS_D:
                essai.message(*message)
            self.assertEqual(
                essai.promesses_du_bot()["pending"], {self.ANGLETERRE: [BUR], self.ALLEMAGNE: [PIC]}
            )

    def test_revision_d_une_promesse_heritee_sans_espaces(self):
        with self.essai() as essai:
            essai.fichier_etat.write_text(json.dumps({self.CLE: {
                "replied_ts": [], "exchange_counts": {},
                "sincere_by_recipient": {"phase": banc.PHASE, "by_recipient": {"GERMANY": ["A MAR-SPA"]}},
                "own_promises": {"pending": {self.ALLEMAGNE: ["A MAR-SPA"]}, "record": {}},
            }}))
            essai.fichier_engagements.write_text(
                json.dumps({str(banc.PARTIE): {banc.PHASE: {"FRANCE": ["A MAR-SPA"]}}})
            )
            essai.message("GERMANY", [PIE], [SPA])
            self.assertEqual(essai.promesses_du_bot()["pending"], {self.ALLEMAGNE: [PIE]})

    def test_cycle_sur_deux_phases(self):
        for recharger in (True, False):
            with self.subTest(recharger=recharger):
                avant, apres, journal, consigne = mesure_promesses.cycle_bilan(recharger)
                # SPA, révisée en PIE, a quitté la liste ; BUR, trahie, y est restée.
                self.assertEqual(
                    avant, {"pending": {self.ANGLETERRE: [MAO, BUR], self.ALLEMAGNE: [PIC, PIE]}, "record": {}}
                )
                self.assertEqual(apres, {"pending": {}, "record": {
                    # MAO tenue ; BUR trahie par label : la France a joué PIC.
                    "ENGLAND": {"kept": 1, "broken": 1, "examples": [
                        {"phase": banc.PHASE, "promised": BUR, "actual": PIC},
                    ]},
                    # PIC tenue ; PIE rompue (A MAR H joué) ; SPA, révisée, n'est pas comptée.
                    "GERMANY": {"kept": 1, "broken": 1, "examples": [
                        {"phase": banc.PHASE, "promised": PIE, "actual": "A MAR H"},
                    ]},
                }})
                lignes = [l for l in journal.splitlines() if "[own-record]" in l]
                self.assertEqual(len(lignes), 2)
                self.assertEqual(journal.count("[trust]"), 0)
                # Phase suivante, réponse à l'Angleterre : son bilan, rien sur l'Allemagne.
                self.assertIn(
                    "Your own record with ENGLAND: 1 promise(s) kept, 1 broken.\n"
                    "  - S1901M: you promised 'A PAR - BUR' and played 'A PAR - PIC'\n"
                    "  ENGLAND saw this. Expect less trust from them; do not pretend it did not happen.\n\n",
                    consigne,
                )
                for mot in ("GERMANY", PIE, "A MAR H", "Your own record with GERMANY"):
                    self.assertNotIn(mot, consigne)
                # Nouvelle phase : plus aucun engagement de phase à rappeler.
                self.assertNotIn("Promises you have already made this phase (", consigne)

    def test_la_phase_courante_n_est_pas_jugee(self):
        # Tant que la phase n'est pas résolue, rien n'est jugé, cycle après cycle.
        with self.essai() as essai:
            essai.message("ENGLAND", [BUR])
            essai.cycle_sans_message()
            self.assertEqual(essai.promesses_du_bot(), {"pending": {self.ANGLETERRE: [BUR]}, "record": {}})

    def test_phase_resolue_sans_ordre_du_bot(self):
        # La France n'a aucun ordre dans la phase résolue : sa promesse est jugée
        # (rompue) au lieu de rester en attente à jamais ; celle du joueur, elle, attend.
        with self.essai() as essai:
            essai.message("ENGLAND", [BUR])
            etat = json.loads(essai.fichier_etat.read_text())
            etat[self.CLE]["pending_promises"] = {self.ANGLETERRE: ["F LON - NTH"]}
            essai.fichier_etat.write_text(json.dumps(etat))
            essai.recharger()
            essai.jeu.resoudre({})
            essai.cycle_sans_message()
            etat = essai.etat_du_bot()
        self.assertEqual(etat["own_promises"], {"pending": {}, "record": {"ENGLAND": {
            "kept": 0, "broken": 1,
            "examples": [{
                "phase": banc.PHASE, "promised": BUR, "actual": "no order submitted for PAR (unit held)",
            }],
        }}})
        self.assertEqual(etat["pending_promises"], {self.ANGLETERRE: ["F LON - NTH"]})

    def test_tenir_promis_sur_une_unite_sans_ordre(self):
        # Une unité sans ordre tient : « A PAR H » promis est tenu, tout autre ordre rompu.
        self.assertEqual(
            mesure_promesses.cycle_unite_sans_ordre("A PAR H")["record"],
            {"ENGLAND": {"kept": 1, "broken": 0, "examples": []}},
        )
        self.assertEqual(
            mesure_promesses.cycle_unite_sans_ordre(BUR)["record"]["ENGLAND"]["broken"], 1
        )
        # L'unité a reçu un autre ordre : « A PAR H » promis est rompu, comme avant.
        etat = {"own_promises": {"pending": {"S1901M:ENGLAND": ["A PAR H", "F BRE H"]}, "record": {}}}
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing), \
                contextlib.redirect_stdout(io.StringIO()):
            bilan = banc.bot.verify_own_promises(
                JeuResolu(legaux={"FRANCE": ["PAR", "BRE", "SPA"]}), "FRANCE", "S1902M", etat
            )
        self.assertEqual(bilan["ENGLAND"]["kept"], 0)
        self.assertEqual([e["actual"] for e in bilan["ENGLAND"]["examples"]], ["A PAR - BUR", "F BRE - MAO"])

    def test_unite_sans_ordre_registre_du_joueur_inchange(self):
        # Le joueur promet « A PAR H » et n'ordonne rien à PAR : rompu, « nothing at PAR », comme avant.
        etat = {"pending_promises": {"S1901M:FRANCE": ["A PAR H"]}}
        jeu = banc.FauxJeu()
        jeu.resoudre({"FRANCE": ["F BRE - MAO"]})
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing), \
                contextlib.redirect_stdout(io.StringIO()):
            confiance = banc.bot.verify_promises(jeu, banc.PARTIE, "ITALY", etat)
        self.assertEqual(confiance, {"FRANCE": {"kept": 0, "broken": 1, "examples": [
            {"phase": "S1901M", "promised": "A PAR H", "actual": "nothing at PAR"},
        ]}})

    def test_revision_sequentielle(self):
        # BUR promis à l'Angleterre, trahi dans un message à l'Allemagne, puis PIC promis
        # à l'Angleterre : c'est une révision, BUR sort du bilan envers elle.
        avant, apres, marques = mesure_promesses.cycle_revision_sequentielle({"FRANCE": [PIC]})
        self.assertEqual(marques, {"[revision]": 1})
        self.assertEqual(avant["pending"], {self.ANGLETERRE: [PIC], self.ALLEMAGNE: [PIC]})
        self.assertEqual(apres["record"]["ENGLAND"], {"kept": 1, "broken": 0, "examples": []})
        # Si la France joue quand même BUR, c'est PIC, le dernier ordre dit, qui est rompu.
        _, apres, _ = mesure_promesses.cycle_revision_sequentielle({"FRANCE": [BUR]})
        self.assertEqual(
            apres["record"]["ENGLAND"],
            {"kept": 0, "broken": 1, "examples": [{"phase": banc.PHASE, "promised": PIC, "actual": BUR}]},
        )

    def test_au_plus_un_ordre_par_unite_et_par_destinataire(self):
        # Invariant de pending, après chaque message de chaque scénario du banc.
        scenarios = [(c, e, m) for c, e, m in mesure_promesses.CAS_17] + [
            ("bilan", mesure_promesses.ENTREE_BILAN, mesure_promesses.CAS_BILAN),
            ("D", banc.entree(banc.PLANS_CONNUS), mesure_promesses.CAS_D + [("ENGLAND", [PIC])]),
        ]
        for cas, entree_plans, messages in scenarios:
            with self.subTest(cas=cas):
                with banc.Banc(entree_plans) as essai:
                    for message in messages:
                        essai.message(*message)
                        if not essai.fichier_etat.exists():
                            continue
                        for cle, ordres in essai.promesses_du_bot().get("pending", {}).items():
                            self.assertEqual(banc.unites_en_double(ordres), [], cle)
                            self.assertEqual(len(ordres), len({o.split()[1] for o in ordres}), cle)

    def test_pas_d_entree_vide_creee(self):
        # Une révision envers un destinataire qui n'a rien en mémoire (état d'avant #17)
        # n'y crée pas d'entrée vide : seule la nouvelle promesse est écrite.
        with self.essai() as essai:
            essai.fichier_etat.write_text(json.dumps({self.CLE: {
                "replied_ts": [], "exchange_counts": {},
                "sincere_by_recipient": {"phase": banc.PHASE, "by_recipient": {
                    "GERMANY": [SPA], "ENGLAND": [SPA],
                }},
            }}))
            essai.fichier_engagements.write_text(
                json.dumps({str(banc.PARTIE): {banc.PHASE: {"FRANCE": [SPA]}}})
            )
            journal = essai.message("GERMANY", [PIE], [SPA])
            self.assertEqual(banc.balises(journal), {"[betrayal]": 1, "[revision]": 1})
            self.assertEqual(essai.promesses_du_bot()["pending"], {self.ALLEMAGNE: [PIE]})

    def test_etat_malforme_remplace_par_un_vide(self):
        # Ce qui n'est pas un dictionnaire (ou une liste d'ordres) est remplacé par un
        # vide, avec une ligne de journal ; le bot répond et enregistre la promesse.
        cas = [
            ([], {"pending": {self.ANGLETERRE: [MAO]}, "record": {}}),
            ("x", {"pending": {self.ANGLETERRE: [MAO]}, "record": {}}),
            ({"pending": [], "record": None}, {"pending": {self.ANGLETERRE: [MAO]}, "record": {}}),
            ({"pending": {self.ALLEMAGNE: "A PAR H", "sans-phase": [], self.ANGLETERRE: [1]}, "record": {
                "GERMANY": [], "ITALY": {"kept": "2", "examples": {"a": 1}},
            }}, {"pending": {self.ANGLETERRE: [MAO]}, "record": {
                "GERMANY": {"kept": 0, "broken": 0, "examples": []},
                "ITALY": {"kept": 0, "broken": 0, "examples": []},
            }}),
        ]
        for mauvais, attendu in cas:
            with self.subTest(own_promises=mauvais):
                with self.essai() as essai:
                    essai.fichier_etat.write_text(json.dumps({self.CLE: {
                        "replied_ts": [], "exchange_counts": {}, "own_promises": mauvais,
                    }}))
                    journal = essai.message("ENGLAND", [MAO])
                    self.assertIn("[own-record] malformed own_promises", journal)
                    self.assertEqual(essai.promesses_du_bot(), attendu)
                    # Une fois remis en forme, plus aucune ligne au cycle suivant.
                    self.assertNotIn("malformed", essai.cycle_sans_message())

    def test_etat_bien_forme_non_touche(self):
        bilan = {"ENGLAND": {"kept": 2, "broken": 1, "examples": [
            {"phase": "S1900M", "promised": BUR, "actual": PIC},
        ]}}
        etat = {"own_promises": {"pending": {self.ANGLETERRE: [MAO]}, "record": json.loads(json.dumps(bilan))}}
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            en_attente, rendu = banc.bot._own_promises(etat)
        self.assertEqual((en_attente, rendu, sortie.getvalue()), ({self.ANGLETERRE: [MAO]}, bilan, ""))
        self.assertIs(rendu, etat["own_promises"]["record"])

    def test_exemples_bornes(self):
        # Seuls les MAX_OWN_RECORD_EXAMPLES derniers exemples de rupture sont conservés.
        n = banc.bot.MAX_OWN_RECORD_EXAMPLES
        self.assertEqual(n, 10)
        ancien = [{"phase": "S19%02dM" % i, "promised": BUR, "actual": PIC} for i in range(n)]
        etat = {"own_promises": {
            "pending": {"S1901M:ENGLAND": ["A PAR - PIC", "F BRE - ENG"]},
            "record": {"ENGLAND": {"kept": 0, "broken": n, "examples": list(ancien)}},
        }}
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing), \
                contextlib.redirect_stdout(io.StringIO()):
            bilan = banc.bot.verify_own_promises(
                JeuResolu(legaux={"FRANCE": ["PAR", "BRE", "SPA"]}), "FRANCE", "S1902M", etat
            )["ENGLAND"]
        self.assertEqual((bilan["broken"], len(bilan["examples"])), (n + 2, n))
        self.assertEqual(bilan["examples"][:-2], ancien[2:])
        self.assertEqual([e["promised"] for e in bilan["examples"][-2:]], ["A PAR - PIC", "F BRE - ENG"])
        # Le registre du joueur, lui, n'est pas borné.
        confiance = {"pending_promises": {"S1901M:FRANCE": ["A PAR - PIC"]}, "trust": {
            "FRANCE": {"kept": 0, "broken": n, "examples": list(ancien)},
        }}
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing), \
                contextlib.redirect_stdout(io.StringIO()):
            rendu = banc.bot.verify_promises(JeuResolu(), banc.PARTIE, "ITALY", confiance)
        self.assertEqual(len(rendu["FRANCE"]["examples"]), n + 1)

    def test_comparaison_a_la_cote_pres(self):
        # Même normalisation que le registre de confiance : la côte est ignorée.
        etat = {"own_promises": {"pending": {"S1901M:ENGLAND": ["F SPA - MAO", "A PAR - BUR"]}, "record": {}}}
        with mock.patch.object(banc.bot, "normalize_order_spacing", banc.normalize_order_spacing):
            bilan = banc.bot.verify_own_promises(
                JeuResolu(legaux={"FRANCE": ["PAR", "BRE", "SPA"]}), "FRANCE", "S1902M", etat
            )
        self.assertEqual(bilan, {"ENGLAND": {"kept": 2, "broken": 0, "examples": []}})
        self.assertIs(bilan, etat["own_promises"]["record"])

    def test_etat_a_l_ancien_format(self):
        # Un état écrit avant #17 n'a pas la clé own_promises : lu comme vide, puis complété.
        with self.essai() as essai:
            essai.fichier_etat.write_text(json.dumps({self.CLE: {
                "replied_ts": [], "exchange_counts": {},
                "pending_promises": {}, "trust": {},
                "sincere_by_recipient": {"phase": banc.PHASE, "by_recipient": {"ENGLAND": [BUR]}},
            }}))
            essai.fichier_engagements.write_text(
                json.dumps({str(banc.PARTIE): {banc.PHASE: {"FRANCE": [BUR]}}})
            )
            essai.message("GERMANY", [MAO])
            self.assertNotIn("Your own record", essai.consignes[-1])
            # La promesse d'avant #17 n'est pas dans la mémoire : elle ne sera pas jugée.
            self.assertEqual(essai.promesses_du_bot(), {"pending": {self.ALLEMAGNE: [MAO]}, "record": {}})
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [BUR], "GERMANY": [MAO]})

    def test_cloisonnement_par_bot_et_par_partie(self):
        # La mémoire vit sous la clé du bot et de la partie ; un autre bot ou une autre
        # partie du même fichier d'état n'y entre pas et n'en est pas modifié.
        autres = {
            "bot2:%d" % banc.PARTIE: {"replied_ts": [], "exchange_counts": {}, "own_promises": {
                "pending": {}, "record": {"ENGLAND": {"kept": 0, "broken": 9, "examples": []}},
            }},
            "bot1:8": {"replied_ts": [], "exchange_counts": {}, "own_promises": {
                "pending": {self.ANGLETERRE: ["A PAR - GAS"]},
                "record": {"ENGLAND": {"kept": 0, "broken": 7, "examples": []}},
            }},
        }
        with self.essai() as essai:
            essai.fichier_etat.write_text(json.dumps(autres))
            essai.message("ENGLAND", [BUR])
            essai.jeu.resoudre(mesure_promesses.JOUES_BILAN)
            essai.message("ENGLAND", [])
            etat = json.loads(essai.fichier_etat.read_text())
            self.assertEqual({cle: etat[cle] for cle in autres}, autres)
            self.assertEqual(etat[self.CLE]["own_promises"]["record"], {"ENGLAND": {
                "kept": 0, "broken": 1,
                "examples": [{"phase": banc.PHASE, "promised": BUR, "actual": PIC}],
            }})
            self.assertIn("Your own record with ENGLAND: 0 promise(s) kept, 1 broken.", essai.consignes[-1])

    def test_memoire_hors_du_fichier_du_moteur(self):
        # own_promises ne quitte pas l'état du bot de dialogue.
        with self.essai() as essai:
            for message in mesure_promesses.CAS_BILAN:
                essai.message(*message)
            texte = essai.fichier_engagements.read_text()
        self.assertNotIn("own_promises", texte)
        self.assertNotIn("ENGLAND", texte)


POLITIQUE_FAIBLE = {A1: 0.05, A2: 0.02, A3: 0.93}
POLITIQUE_FORTE = {A1: 0.5, A2: 0.3, A3: 0.2}
# Deux actions qui tiennent un ordre sur deux, une qui n'en tient aucun ; rien n'atteint le plafond.
POLITIQUE_MEME_M = {A1: 0.04, A1_BIS: 0.08, A3: 0.88}
# L'action favorite (au-dessus du plafond de 0,4) tient les deux ordres promis.
POLITIQUE_FAVORITE = {A2: 0.6, A1: 0.1, A3: 0.3}
# n = 3 : PIC promis en plus. A3 tient 0 ordre promis, A1 un, A2 deux, A_TROIS les trois ;
# rien n'atteint le plafond.
PROMESSES_3 = banc.PROMESSES_4 + [PIC]
A_TROIS = ("A MAR - SPA", "A PAR - PIC", "F BRE - ENG")
POLITIQUE_N3 = {A3: 0.85, A1: 0.06, A2: 0.05, A_TROIS: 0.04}


class PromesseDontLeMessageNEstPasParti(unittest.TestCase):
    """#5 : une promesse n'est jugée, et rappelée à Claude, que si son message est parti."""

    def derouler(self, comportements, cycles_apres_resolution=2):
        """BUR promis à l'Angleterre, PIC joué. Rend (own_promises avant la résolution de
        l'envoi, own_promises après, consigne de la réponse suivante à l'Angleterre)."""
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.site.comportements = list(comportements)
            essai.recevoir("ENGLAND", [BUR])
            essai.cycle()
            essai.jeu.resoudre({"FRANCE": [PIC]})
            avant = None
            for _ in range(cycles_apres_resolution):
                avant = avant or essai.promesses_du_bot()
                essai.cycle()
            apres = essai.promesses_du_bot()
            self.assertNotIn("pending_send", essai.etat_du_bot())
            essai.message("ENGLAND", [])
            return avant, apres, essai.consignes[-1]

    def test_envoi_abandonne_la_promesse_n_est_pas_jugee(self):
        avant, apres, consigne = self.derouler([faux_site.ERREUR_500])
        self.assertEqual(apres, {"pending": {}, "record": {}})
        self.assertNotIn("Your own record", consigne)
        self.assertNotIn("saw this", consigne)

    def test_envoi_incertain_rien_n_est_juge_avant_d_etre_fixe(self):
        # Phase résolue, envoi encore incertain (une relecture négative) : la promesse
        # attend, elle n'est ni jugée ni retirée.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.site.comportements = [faux_site.ERREUR_500]
            essai.recevoir("ENGLAND", [BUR])
            essai.cycle()
            essai.jeu.resoudre({"FRANCE": [PIC]})
            journal = essai.cycle()
            self.assertEqual(banc.balises(journal), {"[send-pending]": 1})
            self.assertNotIn("[own-record]", journal)
            self.assertEqual(
                essai.promesses_du_bot(), {"pending": {"S1901M:ENGLAND": [BUR]}, "record": {}}
            )

    def test_sourdine_la_promesse_n_est_pas_jugee(self):
        avant, apres, consigne = self.derouler([faux_site.SOURDINE])
        self.assertEqual(apres, {"pending": {}, "record": {}})
        self.assertNotIn("saw this", consigne)

    def test_envoi_confirme_la_promesse_est_jugee(self):
        # Confirmé d'emblée, ou par relecture après un échec en apparence : rompue, et dite.
        rompue = {"ENGLAND": {"kept": 0, "broken": 1, "examples": [
            {"phase": banc.PHASE, "promised": BUR, "actual": PIC},
        ]}}
        for comportements in ([], [faux_site.ERREUR_500_STOCKE]):
            with self.subTest(comportements=comportements):
                avant, apres, consigne = self.derouler(comportements)
                self.assertEqual(apres, {"pending": {}, "record": rompue})
                self.assertIn("ENGLAND saw this", consigne)

    def test_promesse_anterieure_gardee_quand_la_revision_n_est_pas_partie(self):
        # BUR promis et parti ; sa révision en PIC (acceptée) est mise en sourdine : BUR
        # reste la promesse faite à l'Angleterre, et c'est elle qui est jugée.
        with banc.Banc(banc.entree(banc.PLANS_CONNUS)) as essai:
            essai.message("ENGLAND", [BUR])
            essai.site.comportements = [faux_site.SOURDINE]
            essai.recevoir("ENGLAND", [PIC], [BUR])
            journal = essai.cycle()
            # La révision n'est pas annoncée : son message n'est pas parti.
            self.assertEqual(banc.balises(journal), {"[send-muted]": 1})
            self.assertNotIn("sincere commitments", journal)
            self.assertEqual(essai.by_recipient(), {"ENGLAND": [BUR]})
            self.assertEqual(essai.engagements(), [BUR])
            self.assertEqual(essai.promesses_du_bot()["pending"], {"S1901M:ENGLAND": [BUR]})
            essai.jeu.resoudre({"FRANCE": [BUR]})
            essai.cycle()
            self.assertEqual(
                essai.promesses_du_bot()["record"], {"ENGLAND": {"kept": 1, "broken": 0, "examples": []}}
            )

    def test_mesure_du_journal_d_envoi(self):
        # Les cas de tests/mesure_promesses.py s'exécutent sans erreur.
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            mesure_promesses.mesurer_envois()
        self.assertNotIn(" erreur ", sortie.getvalue())
        self.assertIn("W  sourdine", sortie.getvalue())


def facteurs(politique, ordre=None):
    """Facteur p'/p de chaque action avant renormalisation.

    A3 ne tient aucun ordre promis : son facteur avant renormalisation vaut 1,
    et la renormalisation divise tout par la même somme.
    """
    apres = banc.renfort(politique, ordre)["FRANCE"]
    reference = apres[A3] / politique[A3]
    return {a: apres[a] / politique[a] / reference for a in politique}


class RenfortDeProbabilite(unittest.TestCase):
    """#4 : règle R3, mu(a) = k^(m/n), plafond et multiplicateur inchangés."""

    def assert_politique(self, obtenue, attendue, places=4):
        self.assertEqual(set(obtenue), set(attendue))
        for action in attendue:
            self.assertAlmostEqual(obtenue[action], attendue[action], places=places, msg=action)

    def test_formule_cible_recalculee(self):
        # Les chiffres de la spécification, recalculés ici par la formule (non recopiés).
        cible = banc.cible_r3(POLITIQUE_FAIBLE)
        racine = 3 ** 0.5
        total = 0.05 * racine + 0.02 * 3 + 0.93
        self.assert_politique(
            cible, {A1: 0.05 * racine / total, A2: 0.06 / total, A3: 0.93 / total}, places=12
        )
        self.assert_politique(cible, {A1: 0.0804, A2: 0.0557, A3: 0.8638})

    def test_independant_de_l_ordre_du_dictionnaire(self):
        reference = banc.renfort(POLITIQUE_FAIBLE)["FRANCE"]
        for ordre in banc.permutations(POLITIQUE_FAIBLE):
            self.assert_politique(banc.renfort(POLITIQUE_FAIBLE, ordre)["FRANCE"], reference, 12)

    def test_valeurs_cibles_politique_faible(self):
        for ordre in banc.permutations(POLITIQUE_FAIBLE):
            self.assert_politique(
                banc.renfort(POLITIQUE_FAIBLE, ordre)["FRANCE"],
                {A1: 0.0804, A2: 0.0557, A3: 0.8638},
            )

    def test_valeurs_cibles_politique_forte(self):
        # Variante de l'exemple de l'issue #4, les probabilités rangées à l'envers (0,5 à
        # l'action qui tient un ordre) : le plafond borne A2 à 0,4 et laisse A1 à 0,5.
        # La cible R3 est ici égale au résultat actuel, dans tout ordre du dictionnaire.
        cible = banc.cible_r3(POLITIQUE_FORTE)
        self.assert_politique(cible, {A1: 0.5 / 1.1, A2: 0.4 / 1.1, A3: 0.2 / 1.1}, places=12)
        for ordre in banc.permutations(POLITIQUE_FORTE):
            with self.subTest(tete=ordre[0]):
                self.assert_politique(banc.renfort(POLITIQUE_FORTE, ordre)["FRANCE"], cible)

    def test_exemple_de_l_issue_cible_recalculee(self):
        # Exemple de l'issue #4 : A3 (aucun ordre tenu) 0,5 ; A1 (un) 0,3 ; A2 (les deux) 0,2.
        # 0,3 x racine de 3 et 0,2 x 3 dépassent le plafond : 0,4 chacun, somme 1,3.
        self.assertGreater(0.3 * 3 ** 0.5, banc.pseudo_commitments.MAX_COMMITMENT_PROB)
        cible = banc.cible_r3(banc.POLITIQUE_ISSUE_4)
        self.assert_politique(cible, {A1: 0.4 / 1.3, A2: 0.4 / 1.3, A3: 0.5 / 1.3}, places=12)
        self.assert_politique(cible, {A1: 0.3077, A2: 0.3077, A3: 0.3846})

    def test_exemple_de_l_issue_valeurs_cibles(self):
        for ordre in banc.permutations(banc.POLITIQUE_ISSUE_4):
            self.assert_politique(
                banc.renfort(banc.POLITIQUE_ISSUE_4, ordre)["FRANCE"],
                {A1: 0.3077, A2: 0.3077, A3: 0.3846},
            )

    def test_exemple_de_l_issue_independant_de_l_ordre_du_dictionnaire(self):
        reference = banc.renfort(banc.POLITIQUE_ISSUE_4)["FRANCE"]
        for ordre in banc.permutations(banc.POLITIQUE_ISSUE_4):
            self.assert_politique(banc.renfort(banc.POLITIQUE_ISSUE_4, ordre)["FRANCE"], reference, 12)

    def test_facteur_entre_1_et_k(self):
        for politique in (POLITIQUE_FAIBLE, POLITIQUE_MEME_M):
            for ordre in banc.permutations(politique):
                for action, facteur in facteurs(politique, ordre).items():
                    self.assertGreaterEqual(facteur, 1 - 1e-9)
                    self.assertLessEqual(facteur, banc.MULTIPLICATEUR + 1e-9)

    def test_meme_m_meme_rapport(self):
        for ordre in banc.permutations(POLITIQUE_MEME_M):
            apres = banc.renfort(POLITIQUE_MEME_M, ordre)["FRANCE"]
            self.assertAlmostEqual(apres[A1_BIS] / apres[A1], 0.08 / 0.04, places=9)

    def test_cles_et_autres_puissances_inchangees(self):
        politiques = (
            POLITIQUE_FAIBLE, POLITIQUE_FORTE, POLITIQUE_MEME_M, POLITIQUE_FAVORITE,
            banc.POLITIQUE_ISSUE_4,
        )
        for politique in politiques:
            for ordre in banc.permutations(politique):
                with self.subTest(politique=politique, tete=ordre[0]):
                    apres = banc.renfort(politique, ordre)
                    self.assertEqual(set(apres), {"FRANCE", "GERMANY"})
                    self.assertEqual(apres["GERMANY"], banc.AUTRES["GERMANY"])
                    self.assertEqual(set(apres["FRANCE"]), set(politique))
                    self.assertAlmostEqual(sum(apres["FRANCE"].values()), 1.0, places=12)

    def test_action_favorite_promise_ne_baisse_pas(self):
        for ordre in banc.permutations(POLITIQUE_FAVORITE):
            with self.subTest(tete=ordre[0]):
                self.assertGreaterEqual(facteurs(POLITIQUE_FAVORITE, ordre)[A2], 1 - 1e-9)

    def test_sans_promesse_politique_inchangee(self):
        apres = banc.renfort(POLITIQUE_FAIBLE, promesses=[])
        self.assertEqual(apres["FRANCE"], POLITIQUE_FAIBLE)
        # Promesse qu'aucun candidat ne joue : rien n'est ajouté ni renforcé.
        apres = banc.renfort(POLITIQUE_FAIBLE, promesses=["A PAR - GAS"])
        self.assert_politique(apres["FRANCE"], POLITIQUE_FAIBLE, places=12)

    def test_sans_promesse_meme_objet(self):
        # Aucun engagement, ou aucun engagement légal : la politique est rendue telle
        # quelle (le même objet, sans renormalisation), même si sa somme n'est pas 1.
        for promesses in ({}, {"FRANCE": []}, {"GERMANY": [SPA]}, {"FRANCE": [MUN]}):
            with self.subTest(promesses=promesses):
                france = {A1: 0.2, A3: 0.2}
                entree = {"FRANCE": france, "GERMANY": dict(banc.AUTRES["GERMANY"])}
                apres = banc.pseudo_commitments.apply_commitments_to_policy(
                    entree, banc.FauxJeu(), promesses, "FRANCE", banc.MULTIPLICATEUR
                )
                self.assertIs(apres, entree)
                self.assertIs(apres["FRANCE"], france)
                self.assertEqual(france, {A1: 0.2, A3: 0.2})

    def test_engagement_qu_aucune_action_ne_contient(self):
        # GAS est légal mais aucun candidat ne le joue : m = 0 partout, seule la
        # renormalisation agit (ici sur une somme de 0,5).
        apres = banc.renfort({A1: 0.2, A2: 0.1, A3: 0.2}, promesses=[GAS])["FRANCE"]
        self.assert_politique(apres, {A1: 0.4, A2: 0.2, A3: 0.4}, places=12)

    def test_un_seul_ordre_promis(self):
        # n = 1 : A1 et A2 jouent SPA (facteur k), A3 non.
        total = 0.05 * 3 + 0.02 * 3 + 0.93
        for ordre in banc.permutations(POLITIQUE_FAIBLE):
            with self.subTest(tete=ordre[0]):
                apres = banc.renfort(POLITIQUE_FAIBLE, ordre, promesses=[SPA])["FRANCE"]
                self.assert_politique(
                    apres, {A1: 0.15 / total, A2: 0.06 / total, A3: 0.93 / total}, places=12
                )

    def test_trois_ordres_promis(self):
        # n = 3, m = 0, 1, 2, 3 : facteurs 1, k^(1/3), k^(2/3), k avant renormalisation.
        k = banc.MULTIPLICATEUR
        brut = {A3: 0.85, A1: 0.06 * k ** (1 / 3), A2: 0.05 * k ** (2 / 3), A_TROIS: 0.04 * k}
        total = sum(brut.values())
        cible = {a: p / total for a, p in brut.items()}
        self.assert_politique(cible, {A3: 0.7324, A1: 0.0746, A2: 0.0896, A_TROIS: 0.1034})
        for ordre in banc.permutations(POLITIQUE_N3):
            with self.subTest(tete=ordre[:2]):
                apres = banc.renfort(POLITIQUE_N3, ordre, promesses=PROMESSES_3)["FRANCE"]
                self.assert_politique(apres, cible, places=12)
                self.assertAlmostEqual(sum(apres.values()), 1.0, places=12)

    def test_multiplicateur_passe_en_parametre(self):
        # apply_commitments_to_policy applique le multiplicateur qu'on lui passe, non 3 :
        # résultat égal à la cible R3 recalculée avec ce k, et différent de celui de k = 3.
        reference = banc.renfort(POLITIQUE_FAIBLE)["FRANCE"]
        for k in (1.5, 2.0, 5.0):
            with self.subTest(k=k):
                entree = {"FRANCE": dict(POLITIQUE_FAIBLE)}
                apres = banc.pseudo_commitments.apply_commitments_to_policy(
                    entree, banc.FauxJeu(), {"FRANCE": list(banc.PROMESSES_4)}, "FRANCE", k
                )["FRANCE"]
                self.assert_politique(apres, banc.cible_r3(POLITIQUE_FAIBLE, k=k), places=12)
                total = 0.05 * k ** 0.5 + 0.02 * k + 0.93
                self.assert_politique(
                    apres, {A1: 0.05 * k ** 0.5 / total, A2: 0.02 * k / total, A3: 0.93 / total}, places=12
                )
                self.assertGreater(abs(apres[A2] - reference[A2]), 1e-3)

    def test_journal_renfort_seulement_si_un_candidat_tient_un_ordre(self):
        with self.assertLogs(level="INFO") as journal:
            banc.renfort(POLITIQUE_FAIBLE)
        self.assertEqual(len(journal.output), 1)
        self.assertIn("boosted FRANCE policy towards", journal.output[0])
        self.assertIn("promised orders held per candidate: [2, 1, 0]", journal.output[0])
        # GAS est légal mais aucun candidat ne le joue : rien n'est renforcé, et le journal le dit.
        with self.assertLogs(level="INFO") as journal:
            banc.renfort(POLITIQUE_FAIBLE, promesses=[GAS])
        self.assertEqual(len(journal.output), 1)
        self.assertNotIn("boosted", journal.output[0].replace("nothing boosted", ""))
        self.assertIn("no candidate holds any of ['A PAR - GAS'] for FRANCE", journal.output[0])

    def test_action_favorite_promise_peut_baisser_apres_renormalisation(self):
        # Chiffres cités dans la docstring de boosted_policy : avant renormalisation le
        # poids de A2 ne baisse pas (0,6), après elle sa probabilité passe sous 0,6.
        apres = banc.renfort(POLITIQUE_FAVORITE)["FRANCE"]
        total = 0.6 + 0.1 * 3 ** 0.5 + 0.3
        self.assert_politique(apres, {A2: 0.6 / total, A1: 0.1 * 3 ** 0.5 / total, A3: 0.3 / total}, places=12)
        self.assertEqual({a: round(p, 3) for a, p in apres.items()}, {A2: 0.559, A1: 0.161, A3: 0.280})
        self.assertLess(apres[A2], POLITIQUE_FAVORITE[A2])

    def test_politique_a_une_seule_action(self):
        for action in (A2, A1, A3):
            with self.subTest(action=action):
                self.assertEqual(banc.renfort({action: 1.0})["FRANCE"], {action: 1.0})
        # Puissance sans unité à ordonner : l'action vide, politique rendue telle quelle.
        entree = {"FRANCE": {(): 1.0}}
        apres = banc.pseudo_commitments.apply_commitments_to_policy(
            entree, banc.FauxJeu(), {"FRANCE": [SPA]}, "FRANCE", banc.MULTIPLICATEUR
        )
        self.assertIs(apres, entree)
        self.assertEqual(apres, {"FRANCE": {(): 1.0}})

    def test_promesses_contradictoires_ecartees(self):
        # Deux ordres pour MAR : resolve_commitment_conflicts les écarte, reste ENG (n = 1).
        with self.assertLogs(level="WARNING") as journal:
            apres = banc.renfort(POLITIQUE_FAIBLE, promesses=[SPA, PIE, "F BRE - ENG"])["FRANCE"]
        self.assertIn("CONTRADICTORY commitments for MAR", journal.output[0])
        total = 0.05 + 0.02 * 3 + 0.93
        self.assert_politique(apres, {A1: 0.05 / total, A2: 0.06 / total, A3: 0.93 / total}, places=12)


class FonctionPureDuRenfort(unittest.TestCase):
    """#4 : boosted_policy, appelée sans jeu ni moteur."""

    def renforcer(self, politique, promesses=banc.PROMESSES_4, k=banc.MULTIPLICATEUR, **options):
        return banc.pseudo_commitments.boosted_policy(politique, promesses, k, **options)

    def test_valeurs_cibles(self):
        cas = (
            (POLITIQUE_FAIBLE, {A1: 0.0804, A2: 0.0557, A3: 0.8638}),
            (banc.POLITIQUE_ISSUE_4, {A1: 0.3077, A2: 0.3077, A3: 0.3846}),
        )
        for politique, cible in cas:
            with self.subTest(politique=politique):
                apres = self.renforcer(politique)
                self.assertEqual(set(apres), set(politique))
                for action in politique:
                    self.assertAlmostEqual(apres[action], cible[action], places=4)
                    self.assertAlmostEqual(apres[action], banc.cible_r3(politique)[action], places=12)
                self.assertAlmostEqual(sum(apres.values()), 1.0, places=12)

    def test_resultat_exactement_identique_dans_tout_ordre(self):
        # Égalité exacte des flottants, pas à une tolérance près (somme par math.fsum).
        for politique, promesses in (
            (POLITIQUE_FAIBLE, banc.PROMESSES_4), (banc.POLITIQUE_ISSUE_4, banc.PROMESSES_4),
            (POLITIQUE_MEME_M, banc.PROMESSES_4), (POLITIQUE_N3, PROMESSES_3),
        ):
            reference = self.renforcer(politique, promesses)
            for ordre in banc.permutations(politique):
                apres = self.renforcer({a: politique[a] for a in ordre}, promesses)
                self.assertEqual(apres, reference)
                self.assertEqual(list(apres), ordre)  # les clés gardent l'ordre de l'entrée
            for ordre in banc.permutations(promesses):
                self.assertEqual(self.renforcer(politique, ordre), reference)

    def test_entree_non_modifiee_et_nouvel_objet(self):
        politique = dict(POLITIQUE_FAIBLE)
        apres = self.renforcer(politique)
        self.assertEqual(politique, POLITIQUE_FAIBLE)
        self.assertIsNot(apres, politique)
        # Sans promesse : une copie égale, non renormalisée.
        sans = self.renforcer({A1: 0.2, A3: 0.2}, [])
        self.assertEqual(sans, {A1: 0.2, A3: 0.2})

    def test_ordre_promis_repete_compte_une_fois(self):
        self.assertEqual(
            self.renforcer(POLITIQUE_FAIBLE, banc.PROMESSES_4 + banc.PROMESSES_4),
            self.renforcer(POLITIQUE_FAIBLE),
        )

    def test_multiplicateur_et_plafond_passes_en_parametre(self):
        # k = 1, ou k < 1 : rien ne monte et rien ne baisse.
        for k in (1.0, 0.5):
            apres = self.renforcer(POLITIQUE_FAIBLE, k=k)
            for action, p in POLITIQUE_FAIBLE.items():
                self.assertAlmostEqual(apres[action], p, places=12)
        # Plafond à 0,03 : A1 (0,05, déjà au-dessus) garde sa valeur, A2 (0,02) est borné à 0,03.
        apres = self.renforcer(POLITIQUE_FAIBLE, max_prob=0.03)
        total = 0.05 + 0.03 + 0.93
        for action, p in ((A1, 0.05), (A2, 0.03), (A3, 0.93)):
            self.assertAlmostEqual(apres[action], p / total, places=12)

    def test_politique_vide_ou_nulle(self):
        self.assertEqual(self.renforcer({}), {})
        self.assertEqual(self.renforcer({A1: 0.0, A3: 0.0}), {A1: 0.0, A3: 0.0})

    def test_multiplicateur_configure(self):
        # Le multiplicateur du banc est celui de cicero_no_dialogue.prototxt et la valeur par
        # défaut du champ dans conf/agents.proto (patch). Le bot de dialogue ne le lit plus
        # dans le prototxt : il le reçoit du moteur, par l'export (search.boost).
        module = banc.pseudo_commitments
        self.assertEqual(module.MAX_COMMITMENT_PROB, 0.4)
        prototxt = banc.OVERLAY / "conf/common/agents/cicero_no_dialogue.prototxt"
        self.assertIn("pseudo_commitment_boost: %.1f" % banc.MULTIPLICATEUR, prototxt.read_text())
        patch = (banc.RACINE / "cicero" / "patches" / "0001-cicero.patch").read_text()
        self.assertIn("pseudo_commitment_boost = 13 [ default = %.1f ]" % banc.MULTIPLICATEUR, patch)
        self.assertEqual(banc.RECHERCHE["boost"], banc.MULTIPLICATEUR)
        for nom in ("commitment_boost", "AGENT_CONFIG_FILE", "DEFAULT_COMMITMENT_BOOST"):
            self.assertFalse(hasattr(module, nom), nom)

    def test_multiplicateur_exporte_selon_l_option(self):
        # enable_pseudo_commitments faux : le moteur ne renforce rien, l'export dit 1,0 ;
        # la table recalculée par le bot ne bouge alors pas, quelle que soit la promesse.
        exporte = banc.plan_export.exported_boost
        self.assertEqual((exporte(True, 3.0), exporte(False, 3.0)), (3.0, 1.0))
        self.assertIsInstance(exporte(True, 3), float)
        # BUR vaut 0,01 de plus mais part de 0,1 contre 0,8 ; lambda 0,008 : il ne passe
        # en tête que renforcé (0,1 -> 0,3 avant normalisation).
        action_values = [((PIC,), 0.49, 0.8, 0.0), ((BUR,), 0.5, 0.1, 0.0)]
        tetes = {}
        for active in (True, False):
            recherche = dict(banc.RECHERCHE, boost=exporte(active, banc.MULTIPLICATEUR))
            recherche["lambda"] = 0.008
            with tempfile.TemporaryDirectory() as dossier:
                ecrit = banc.exporter(action_values, dossier, recherche=recherche)
            self.assertEqual(ecrit["search"]["boost"], banc.MULTIPLICATEUR if active else 1.0)
            tetes[active] = [
                banc.pseudo_commitments.engine_head_action(ecrit["candidates"], ecrit["search"], promis)
                for promis in ([], [BUR])
            ]
        self.assertEqual(tetes[False], [(PIC,), (PIC,)])
        self.assertEqual(tetes[True], [(PIC,), (BUR,)])

    def test_multiplicateur_exporte_et_politique_remise_dans_le_patch(self):
        # Contrôle statique du patch moteur (bqre1p_agent.py ne se charge pas hors conteneur) :
        # l'export passe par exported_boost avec l'option lue une fois, et la politique
        # d'avant renfort est remise dans le dictionnaire gardé par le résultat de recherche,
        # avant chacun des deux retours qui suivent le renfort.
        patch = (banc.RACINE / "cicero" / "patches" / "0001-cicero.patch").read_text()
        ajoutees = [l[1:].strip() for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++")]
        self.assertIn("commitments_enabled = self.br_corr_bilateral_search_cfg.enable_pseudo_commitments", ajoutees)
        self.assertIn("if commitments_enabled:", ajoutees)
        self.assertIn("boost=exported_boost(", ajoutees)
        self.assertNotIn("boost=self.br_corr_bilateral_search_cfg.pseudo_commitment_boost,", ajoutees)
        remises = [l for l in ajoutees if l.startswith("bp_policy[agent_power] = prior_agent_policy")]
        self.assertEqual(len(remises), 2)


class LecteurDesEngagementsCoteMoteur(unittest.TestCase):
    """#5 : load_commitments ne fait jamais échouer le calcul des ordres, quel que soit
    le contenu de pseudo_commitments.json (le bot de dialogue, lui, se tait)."""

    class Jeu:
        def get_orderable_locations(self):
            return {"FRANCE": ["PAR"]}

        def get_all_possible_orders(self):
            return {"PAR": [BUR, PIC]}

    def lire(self, contenu):
        """(engagements lus, politique après renfort, actions injectées) pour la France."""
        module = banc.pseudo_commitments
        with tempfile.TemporaryDirectory() as dossier:
            fichier = os.path.join(dossier, "pseudo_commitments.json")
            if contenu is None:
                os.mkdir(fichier)  # un répertoire à la place du fichier
            else:
                with open(fichier, "wb") as f:
                    f.write(contenu)
            with mock.patch.object(module, "COMMITMENTS_FILE", module.Path(fichier)), \
                    mock.patch.object(module.logging, "warning"), mock.patch.object(module.logging, "info"):
                lus = module.load_commitments("7", "S1901M")
                politique = module.apply_commitments_to_policy(
                    {"FRANCE": {(BUR,): 0.1, (PIC,): 0.9}}, self.Jeu(), lus, "FRANCE", 3.0
                )
                injectees = module.build_extra_plausible_actions(self.Jeu(), "FRANCE", (PIC,), lus, 1)
        return lus, politique["FRANCE"], injectees

    def test_forme_attendue_inchangee(self):
        lus, politique, injectees = self.lire(b'{"7": {"S1901M": {"FRANCE": ["A PAR - BUR"], "GERMANY": []}}}')
        self.assertEqual(lus, {"FRANCE": [BUR], "GERMANY": []})
        self.assertGreater(politique[(BUR,)], 0.1)
        self.assertEqual(injectees, {"FRANCE": [(BUR,)]})

    def test_forme_inattendue_ou_fichier_illisible_aucun_engagement(self):
        sans_renfort = {(BUR,): 0.1, (PIC,): 0.9}
        for contenu in (
            b"[]", b'{"7": []}', b'{"7": {"S1901M": []}}', b'{"7": {"S1901M": {"FRANCE": "A PAR - BUR"}}}',
            b'{"7": {"S1901M": {"FRANCE": [1, "A PAR - BUR"]}}}', b"\xff\xfe", b'{"7": {"S19', None,
        ):
            with self.subTest(contenu=contenu):
                self.assertEqual(self.lire(contenu), ({}, sans_renfort, {}))

    def test_racine_qui_n_est_pas_un_objet_avertissement(self):
        module = banc.pseudo_commitments
        for contenu, attendus in ((b"[]", 1), (b'"texte"', 1), (b"3", 1), (b"{}", 0), (b'{"8": {}}', 0)):
            with self.subTest(contenu=contenu), tempfile.TemporaryDirectory() as dossier:
                fichier = module.Path(dossier) / "pseudo_commitments.json"
                fichier.write_bytes(contenu)
                with mock.patch.object(module, "COMMITMENTS_FILE", fichier), \
                        mock.patch.object(module.logging, "warning") as avertir:
                    self.assertEqual(module.load_commitments("7", "S1901M"), {})
                self.assertEqual(avertir.call_count, attendus)
                if attendus:
                    self.assertIn("does not hold an object", avertir.call_args[0][0])

    def test_entree_d_une_autre_puissance_gardee(self):
        lus, politique, injectees = self.lire(
            b'{"7": {"S1901M": {"GERMANY": [["x"]], "FRANCE": ["A PAR - BUR"]}}}'
        )
        self.assertEqual(lus, {"FRANCE": [BUR]})
        self.assertEqual(injectees, {"FRANCE": [(BUR,)]})


if __name__ == "__main__":
    unittest.main()
