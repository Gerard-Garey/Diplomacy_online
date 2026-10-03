#!/usr/bin/env python3
"""Logique des promesses : comportement cible des issues #2, #3 et #4.

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
import os
import sys
import tempfile
import traceback
import unittest

import banc_promesses as banc
import mesure_promesses
from banc_promesses import A1, A1_BIS, A2, A3, BUR, GAS, PIC


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
    que les promesses antérieures ne changent pas. La forme du signalement
    (quatrième retour ou journal) ne l'est pas.
    """

    @echec_attendu(2)
    def test_aucun_des_deux_n_est_retenu(self):
        for sincere in ([PIC, BUR], [BUR, PIC]):
            acceptes, _, remplaces, _ = banc.rejet(sincere, {}, banc.PLANS_2)
            self.assertEqual(acceptes, [])
            self.assertEqual(remplaces, [])

    @echec_attendu(2)
    def test_resultat_independant_de_l_ordre_de_la_liste(self):
        a = banc.rejet([PIC, BUR], {}, banc.PLANS_2)
        b = banc.rejet([BUR, PIC], {}, banc.PLANS_2)
        self.assertEqual((a[0], a[2]), (b[0], b[2]))

    # lecture confirmée par expert-cicero le 2026-10-03 : un message contradictoire ne vaut redite de rien
    @echec_attendu(2)
    def test_la_promesse_anterieure_reste(self):
        for sincere in ([PIC, BUR], [BUR, PIC]):
            acceptes, _, remplaces, anterieurs = banc.rejet(
                sincere, {"GERMANY": [PIC]}, banc.PLANS_2
            )
            self.assertEqual(remplaces, [])
            self.assertEqual(acceptes, [])
            self.assertEqual(anterieurs, {"GERMANY": [PIC]})

    @echec_attendu(2)
    def test_ordre_repete_accepte_une_fois(self):
        acceptes, retrogrades, remplaces, _ = banc.rejet([BUR, BUR], {}, banc.PLANS_2)
        self.assertEqual((acceptes, retrogrades, remplaces), ([BUR], [], []))

    @echec_attendu(2)
    def test_les_autres_unites_de_la_liste_sont_acceptees(self):
        acceptes, _, remplaces, _ = banc.rejet([PIC, BUR, "F BRE - MAO"], {}, banc.PLANS_2)
        self.assertEqual((acceptes, remplaces), (["F BRE - MAO"], []))

    @echec_attendu(2)
    def test_aucun_remplacement_sans_destinataire(self):
        for sincere, anterieurs in ENTREES_2:
            remplaces = banc.rejet(sincere, anterieurs, banc.PLANS_2)[2]
            self.assertEqual([t for t in remplaces if t[0] is None], [])

    @echec_attendu(2)
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


class ValeurInconnue(unittest.TestCase):
    """#3 : promesse antérieure absente des plans exportés, index order_values."""

    @echec_attendu(3)
    def test_valeur_inconnue_la_premiere_promesse_tient(self):
        acceptes, retrogrades, remplaces, anterieurs = banc.rejet(
            [PIC], {"GERMANY": [GAS]}, banc.PLANS_3
        )
        self.assertEqual((acceptes, retrogrades, remplaces), ([], [(PIC, GAS)], []))
        self.assertEqual(anterieurs, {"GERMANY": [GAS]})

    @echec_attendu(3)
    def test_cycle_valeur_inconnue_la_premiere_promesse_tient(self):
        # Ancien format (pas d'order_values) et GAS hors des plans : GAS reste promis.
        retour, par_destinataire, engagements = banc.trahison(banc.entree(banc.PLANS_3), GAS, PIC)
        self.assertEqual(retour[2], [])
        self.assertEqual(par_destinataire.get("ENGLAND"), [GAS])
        self.assertEqual(par_destinataire.get("GERMANY", []), [])
        self.assertEqual(engagements, [GAS])

    @echec_attendu(3)
    def test_cycle_index_gain_au_dessus_de_la_marge(self):
        # GAS n'est dans aucun plan exporté, mais l'index donne sa valeur : gain de 0,10.
        retour, par_destinataire, engagements = banc.trahison(
            banc.entree(banc.PLANS_3, {GAS: 0.20, PIC: 0.30}), GAS, PIC
        )
        self.assertEqual([t[:3] for t in retour[2]], [("ENGLAND", GAS, PIC)])
        self.assertIsNotNone(retour[2][0][3])
        self.assertAlmostEqual(retour[2][0][3], 0.10, places=6)
        self.assertEqual(par_destinataire, {"ENGLAND": [], "GERMANY": [PIC]})
        self.assertEqual(engagements, [PIC])

    @echec_attendu(3)
    def test_cycle_index_gain_sous_la_marge(self):
        self.assertLess(0.21 - 0.20, banc.bot.COMMITMENT_SWITCH_MARGIN)
        retour, par_destinataire, engagements = banc.trahison(
            banc.entree(banc.plans((PIC, 0.21)), {GAS: 0.20, PIC: 0.21}), GAS, PIC
        )
        self.assertEqual((retour[1], retour[2]), ([(PIC, GAS)], []))
        self.assertEqual(par_destinataire.get("ENGLAND"), [GAS])
        self.assertEqual(engagements, [GAS])

    @echec_attendu(3)
    def test_export_index_des_14_candidats(self):
        candidats = banc.candidats_14()
        with tempfile.TemporaryDirectory() as dossier:
            ecrit = banc.exporter(candidats, dossier)
        self.assertIn("order_values", ecrit)
        attendu = {}
        for action, valeur, _, _ in candidats:
            for ordre in action:
                attendu[ordre] = max(valeur, attendu.get(ordre, valeur))
        index = ecrit["order_values"]
        self.assertEqual(sorted(index), sorted(attendu))
        for ordre, valeur in attendu.items():
            self.assertAlmostEqual(index[ordre], valeur, places=5, msg=ordre)
        # GAS n'est joué que par le candidat de rang 12, hors des six plans exportés.
        self.assertAlmostEqual(index[GAS], candidats[11][1], places=5)

    @echec_attendu(3)
    def test_de_l_export_a_la_comparaison(self):
        # Bout en bout : l'index écrit par export_plans donne la valeur de GAS (0,28),
        # PIC vaut 0,50 : la trahison est décidée sur un gain connu de 0,22.
        with tempfile.TemporaryDirectory() as dossier:
            ecrit = banc.exporter(banc.candidats_14(), dossier)
        retour, _, _ = banc.trahison(ecrit, GAS, PIC)
        self.assertEqual([t[:3] for t in retour[2]], [("ENGLAND", GAS, PIC)])
        self.assertIsNotNone(retour[2][0][3])
        self.assertAlmostEqual(retour[2][0][3], 0.22, places=4)

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

    def test_ancien_format_repli_sur_les_plans(self):
        # Sans order_values, les deux valeurs se lisent dans plans : gain de 0,8, trahison.
        retour, par_destinataire, engagements = banc.trahison(
            banc.entree(banc.PLANS_CONNUS), BUR, PIC
        )
        self.assertEqual([t[:3] for t in retour[2]], [("ENGLAND", BUR, PIC)])
        self.assertAlmostEqual(retour[2][0][3], 0.8, places=6)
        self.assertEqual(par_destinataire, {"ENGLAND": [], "GERMANY": [PIC]})
        self.assertEqual(engagements, [PIC])

    def test_ancien_format_gain_sous_la_marge(self):
        retour, par_destinataire, engagements = banc.trahison(
            banc.entree(banc.plans((PIC, 0.21), (BUR, 0.20))), BUR, PIC
        )
        self.assertEqual((retour[0], retour[1], retour[2]), ([], [(PIC, BUR)], []))
        self.assertEqual(par_destinataire, {"ENGLAND": [BUR]})
        self.assertEqual(engagements, [BUR])

    def test_nouvelle_promesse_sans_valeur_retrogradee(self):
        # Rien ne dit que le changement vaut une parole rompue : la première tient.
        acceptes, retrogrades, remplaces, _ = banc.rejet([GAS], {"GERMANY": [PIC]}, banc.PLANS_3)
        self.assertEqual((acceptes, retrogrades, remplaces), ([], [(GAS, PIC)], []))


POLITIQUE_FAIBLE = {A1: 0.05, A2: 0.02, A3: 0.93}
POLITIQUE_FORTE = {A1: 0.5, A2: 0.3, A3: 0.2}
# Deux actions qui tiennent un ordre sur deux, une qui n'en tient aucun ; rien n'atteint le plafond.
POLITIQUE_MEME_M = {A1: 0.04, A1_BIS: 0.08, A3: 0.88}
# L'action favorite (au-dessus du plafond de 0,4) tient les deux ordres promis.
POLITIQUE_FAVORITE = {A2: 0.6, A1: 0.1, A3: 0.3}


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

    @echec_attendu(4)
    def test_independant_de_l_ordre_du_dictionnaire(self):
        reference = banc.renfort(POLITIQUE_FAIBLE)["FRANCE"]
        for ordre in banc.permutations(POLITIQUE_FAIBLE):
            self.assert_politique(banc.renfort(POLITIQUE_FAIBLE, ordre)["FRANCE"], reference, 12)

    @echec_attendu(4)
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

    @echec_attendu(4)
    def test_exemple_de_l_issue_valeurs_cibles(self):
        for ordre in banc.permutations(banc.POLITIQUE_ISSUE_4):
            self.assert_politique(
                banc.renfort(banc.POLITIQUE_ISSUE_4, ordre)["FRANCE"],
                {A1: 0.3077, A2: 0.3077, A3: 0.3846},
            )

    @echec_attendu(4)
    def test_exemple_de_l_issue_independant_de_l_ordre_du_dictionnaire(self):
        reference = banc.renfort(banc.POLITIQUE_ISSUE_4)["FRANCE"]
        for ordre in banc.permutations(banc.POLITIQUE_ISSUE_4):
            self.assert_politique(banc.renfort(banc.POLITIQUE_ISSUE_4, ordre)["FRANCE"], reference, 12)

    @echec_attendu(4)
    def test_facteur_entre_1_et_k(self):
        for politique in (POLITIQUE_FAIBLE, POLITIQUE_MEME_M):
            for ordre in banc.permutations(politique):
                for action, facteur in facteurs(politique, ordre).items():
                    self.assertGreaterEqual(facteur, 1 - 1e-9)
                    self.assertLessEqual(facteur, banc.MULTIPLICATEUR + 1e-9)

    @echec_attendu(4)
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


if __name__ == "__main__":
    unittest.main()
