#!/usr/bin/env python3
"""Couche R de la référence de non-régression (issue #31, critère 3) : tests/reference_couche_r.py sans moteur.

Tables fabriquées, écrites à la main : chaque valeur attendue est calculée dans le
commentaire du test. Les cas sur le jeu versionné (lot = la table figée de chaque
position répétée, K = 1) ne s'exécutent que si le jeu porte son résumé
(tests/reference/repetee.json) ; tant qu'il est absent ils sont sautés, et la dernière
ligne de la sortie le dit. COUCHE_R_JEU=<dossier> les fait porter sur une copie du jeu.
Ni pile, ni Claude, ni GPU.

Usage : python3 tests/test_reference_couche_r.py
"""
import contextlib
import copy
import io
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Avant tout chargement : ni __pycache__ dans tests/, ni .pyc sous cicero/overlay (#27).
sys.dont_write_bytecode = True

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tests"))
import reference_couche_d as couche_d  # noqa: E402  (état du dépôt, doublé pour `resumer`)
import reference_couche_r as couche_r  # noqa: E402
import reference_jeu  # noqa: E402

JEU = Path(os.environ.get("COUCHE_R_JEU", str(reference_jeu.DOSSIER)))
SHA = "0123456789abcdef0123456789abcdef01234567"
BUR, PIC, MAO = "A PAR - BUR", "A PAR - PIC", "F BRE - MAO"
TETE, AUTRE = [BUR, MAO], [PIC, MAO]
# Planchers du cas fabriqué (ln lambda, valeur de tête, S_ov, S_G).
PLANCHERS = {"ln_lambda": 0.05, "v_tete": 0.005, "S_ov": 0.005, "S_G": 0.005}
# Référence de 5 tirages, puis lot de base de 3 : valeur de l'action (BUR, MAO), de l'action (PIC, MAO), lambda.
REFERENCE = ((0.30, 0.25, 0.010), (0.31, 0.27, 0.012), (0.29, 0.24, 0.011), (0.30, 0.26, 0.009), (0.30, 0.23, 0.010))
BASE = ((0.30, 0.25, 0.010), (0.31, 0.24, 0.011), (0.30, 0.26, 0.010))
_ORDER_LOC = []


def order_loc():
    """_order_loc du bot, chargé une fois."""
    if not _ORDER_LOC:
        _ORDER_LOC.append(couche_r.bruit_valeurs.charger_regle()[1])
    return _ORDER_LOC[0]


def table(bur, pic, lam, tete="BUR", boost=3.0):
    """Une table exportée à deux actions ; order_values est la valeur de la première action qui porte l'ordre."""
    candidats = [{"orders": TETE, "value": bur, "prob": 0.5}, {"orders": AUTRE, "value": pic, "prob": 0.5}]
    if tete == "PIC":
        candidats.reverse()
    valeurs = {}
    for candidat in candidats:
        for ordre in candidat["orders"]:
            valeurs.setdefault(ordre, candidat["value"])
    return {
        "plans": [{"rank": i + 1, "orders": c["orders"], "value": c["value"], "cost_vs_best": 0.0} for i, c in enumerate(candidats)],
        "order_values": valeurs, "candidates": candidats, "search": {"lambda": lam, "boost": boost, "max_prob": 0.4},
    }


def tirages(tables):
    return [couche_r.tirage(t) for t in tables]


def reference():
    return couche_r.resumer_position(tirages(table(*ligne) for ligne in REFERENCE), order_loc())


def comparer(lot, **cles):
    return couche_r.comparer_position(reference(), tirages(lot), order_loc(), PLANCHERS, **cles)


class Resume(unittest.TestCase):
    def test_resume_du_cas_fabrique(self):
        r = reference()
        # ln lambda : moyenne des logarithmes de 0,010 0,012 0,011 0,009 0,010 = -4,570716 ; écart type 0,108962.
        self.assertEqual(r["n"], 5)
        self.assertAlmostEqual(r["ln_lambda"][0], -4.570716, places=6)
        self.assertAlmostEqual(r["ln_lambda"][1], 0.108962, places=6)
        # Valeur de tête (BUR) : moyenne 0,30 ; écarts 0, +0,01, -0,01, 0, 0 -> variance 2e-4 / 4 = 5e-5.
        self.assertAlmostEqual(r["v_tete"][0], 0.30, places=12)
        self.assertAlmostEqual(r["v_tete"][1], math.sqrt(5e-5), places=12)  # 0,007071
        self.assertEqual(r["tetes"], [{"orders": TETE, "n": 5}])
        # Trois ordres stables. MAO vaut l'action de tête, comme BUR (variance 5e-5). PIC : moyenne 0,25,
        # écarts 0, +0,02, -0,01, +0,01, -0,02 -> variance 1e-3 / 4 = 2,5e-4.
        self.assertEqual(sorted(r["order_values"]), [BUR, PIC, MAO])
        self.assertEqual([r["order_values"][o][2] for o in (BUR, PIC, MAO)], [5, 5, 5])
        self.assertAlmostEqual(r["order_values"][PIC][0], 0.25, places=12)
        self.assertAlmostEqual(r["order_values"][PIC][1], math.sqrt(2.5e-4), places=12)
        # S_ov = racine((5e-5 + 5e-5 + 2,5e-4) / 3) = 0,010801.
        self.assertAlmostEqual(r["S_ov"], math.sqrt(3.5e-4 / 3), places=12)
        # S_G, un seul couple (BUR, PIC) sur l'unité PAR : G = -0,05 -0,04 -0,05 -0,04 -0,07, moyenne -0,05,
        # écarts 0, +0,01, 0, +0,01, -0,02 -> variance 6e-4 / 4 = 1,5e-4 -> 0,012247.
        self.assertAlmostEqual(r["S_G"], math.sqrt(1.5e-4), places=12)
        self.assertEqual((r["boost"], r["max_prob"]), (3.0, 0.4))

    def test_ordre_stable_a_la_majorite_stricte(self):
        # GAS dans 2 tirages sur 5 : pas stable ; dans 3 sur 5 : stable, écart type sur ses 3 valeurs.
        def avec(n):
            lot = []
            for i, ligne in enumerate(REFERENCE):
                t = table(*ligne)
                if i < n:
                    t["order_values"]["A MAR - GAS"] = 0.10 + i / 100.0
                lot.append(t)
            return couche_r.resumer_position(tirages(lot), order_loc())["order_values"]

        self.assertNotIn("A MAR - GAS", avec(2))
        moyenne, ecart, effectif = avec(3)["A MAR - GAS"]
        self.assertEqual(effectif, 3)
        self.assertAlmostEqual(moyenne, 0.11, places=12)
        self.assertAlmostEqual(ecart, 0.01, places=12)

    def test_tete_modale_en_premier(self):
        lot = [table(*ligne, tete="PIC" if i in (1, 3) else "BUR") for i, ligne in enumerate(REFERENCE)]
        r = couche_r.resumer_position(tirages(lot), order_loc())
        self.assertEqual(r["tetes"], [{"orders": TETE, "n": 3}, {"orders": AUTRE, "n": 2}])

    def test_les_moyennes_s_ecrivent_telles_quelles(self):
        # Dispersions à cinq décimales, moyennes exactes : le lot fait des tirages de la référence reste « identique »
        # une fois le résumé passé par son écriture.
        r = reference()
        ecrit = json.loads(json.dumps(couche_r.arrondir(r)))
        self.assertEqual(ecrit["ln_lambda"], [r["ln_lambda"][0], 0.10896])
        self.assertEqual(ecrit["order_values"][PIC], [r["order_values"][PIC][0], 0.01581, 5])
        self.assertEqual((ecrit["S_ov"], ecrit["S_G"]), (0.0108, 0.01225))
        c = couche_r.comparer_position(ecrit, tirages(table(*ligne) for ligne in REFERENCE), order_loc(), PLANCHERS)
        self.assertEqual(c["verdict"], "identique")

    def test_valeur_non_finie(self):
        # nan > tau est faux : une valeur non finie ne doit jamais atteindre une comparaison.
        for casse, motif in (
            (lambda t: t["candidates"][0].update(value=float("nan")), "valeur de tête non finie"),
            (lambda t: t["candidates"][0].update(value=float("inf")), "valeur de tête non finie"),
            (lambda t: t["order_values"].update({PIC: float("nan")}), "order_values non fini pour 1 ordre(s), dont A PAR - PIC"),
            (lambda t: t["search"].update({"lambda": float("nan")}), "un lambda fini, strictement positif"),
            (lambda t: t["search"].update({"lambda": float("inf")}), "un lambda fini, strictement positif"),
        ):
            t = table(0.30, 0.25, 0.010)
            casse(t)
            with self.assertRaises(couche_r.ErreurLot) as refus:
                couche_r.tirage(t)
            self.assertIn(motif, str(refus.exception))

    def test_un_t_non_fini_est_hors_tolerance(self):
        # Par ceinture : un résumé dont une moyenne ne serait pas finie rend un T nan, donc hors tolérance et grossier.
        r = reference()
        r["ln_lambda"][0] = float("nan")
        r["order_values"][BUR][0] = float("nan")
        c = couche_r.comparer_position(r, tirages(table(*ligne) for ligne in BASE), order_loc(), PLANCHERS)
        self.assertTrue(math.isnan(c["T_lambda"]) and math.isnan(c["T_ov"]))
        self.assertEqual((c["verdict"], c["hors"][:2], c["grossier"]), ("hors tolérance", ["lambda", "ov"], True))
        self.assertEqual(couche_r.decider({("S1901M", "FRANCE"): c})["decision"], "régression")

    def test_table_illisible(self):
        for casse in ({"order_values": {BUR: 0.3}}, dict(table(0.3, 0.2, 0.0)), dict(table(0.3, 0.2, 0.01), candidates=[])):
            with self.assertRaises(couche_r.ErreurLot):
                couche_r.tirage(casse)


class Comparaison(unittest.TestCase):
    """Les six lots de la spécification (§ 2.6) : T à 1e-3, verdict. f = racine(1 / 3 + 1 / 5) = 0,730297."""

    def controle(self, c, t_lambda, t_v, t_ov, t_g, tete, verdict, hors):
        for cle, attendu in (("T_lambda", t_lambda), ("T_v_tete", t_v), ("T_ov", t_ov), ("T_G", t_g)):
            self.assertAlmostEqual(c[cle], attendu, delta=1e-3, msg=cle)
        self.assertEqual((c["tete_lot"], c["K"], c["verdict"], c["hors"]), tete + (verdict, hors))

    def test_a_lot_de_base(self):
        # T_lambda : (2 ln 0,010 + ln 0,011) / 3 = -4,573400 ; écart -0,002684 / (0,108962 x 0,730297) = 0,034.
        # T_v : 0,303333 - 0,30 = 0,003333 / (0,007071 x 0,730297) = 0,645.
        # T_ov : écarts BUR 0,003333, MAO 0,003333, PIC 0 -> médiane 0,003333 / (0,010801 x 0,730297) = 0,423.
        # T_G : G du lot 0,25 - 0,303333 = -0,053333, de référence -0,05 -> 0,003333 / (0,012247 x 0,730297) = 0,373.
        c = comparer(table(*ligne) for ligne in BASE)
        self.controle(c, 0.034, 0.645, 0.423, 0.373, (3, 3), "dans la tolérance", [])
        self.assertAlmostEqual(c["f"], math.sqrt(1 / 3 + 1 / 5), places=12)
        self.assertEqual((c["couverture"], c["ordres_stables"], c["couples"], c["structure"]), (1.0, 3, 1, []))
        self.assertTrue(c["tete_jugee"])

    def test_b_lambda_fois_0_3(self):
        # ln 0,3 = -1,203973 s'ajoute à l'écart : 1,206657 / 0,079575 = 15,164 ; au-delà de 2 x tau : grossier.
        c = comparer(table(b, p, lam * 0.3) for b, p, lam in BASE)
        self.controle(c, 15.164, 0.645, 0.423, 0.373, (3, 3), "hors tolérance", ["lambda"])
        self.assertTrue(c["grossier"])

    def test_c_valeurs_plus_0_05(self):
        # T_v : 0,053333 / 0,005164 = 10,328 ; T_ov : médiane de 0,053333 0,053333 0,05 = 0,053333 / 0,007888 = 6,761 ;
        # G ne bouge pas (les deux ordres montent ensemble).
        c = comparer(table(b + 0.05, p + 0.05, lam) for b, p, lam in BASE)
        self.controle(c, 0.034, 10.328, 6.761, 0.373, (3, 3), "hors tolérance", ["v_tete", "ov"])

    def test_d_tete_pic_et_pic_plus_0_10(self):
        # La tête est (PIC, MAO), à 0,35 0,34 0,36 : valeur de tête 0,35, écart 0,05 / 0,005164 = 9,682.
        # order_values : BUR +0,003333, PIC +0,10, MAO vaut maintenant l'action PIC, 0,35 contre 0,30 : +0,05 ;
        # médiane 0,05 / 0,007888 = 6,339. G = 0,35 - 0,303333 = 0,046667 contre -0,05 : 0,096667 / 0,008944 = 10,808.
        # La tête de référence, unanime sur 5 tirages, n'est dans aucun des 3 du lot.
        c = comparer(table(b, p + 0.10, lam, tete="PIC") for b, p, lam in BASE)
        self.controle(c, 0.034, 9.682, 6.339, 10.808, (0, 3), "hors tolérance", ["v_tete", "ov", "G", "tete"])

    def test_e_boost_2_dans_un_tirage(self):
        lot = [table(*ligne) for ligne in BASE]
        lot[0]["search"]["boost"] = 2.0
        c = comparer(lot)
        self.controle(c, 0.034, 0.645, 0.423, 0.373, (3, 3), "hors tolérance", ["structure"])
        self.assertEqual(c["structure"], ["search.boost = 2.0 (référence : 3.0)"])

    def test_f_les_cinq_tirages_de_la_reference(self):
        c = comparer(table(*ligne) for ligne in REFERENCE)
        self.controle(c, 0.0, 0.0, 0.0, 0.0, (5, 5), "identique", [])
        self.assertEqual((c["d_ln_lambda"], c["d_v_tete"], c["ov_max"], c["G_max"]), (0.0, 0.0, 0.0, 0.0))

    def test_lot_d_une_autre_position(self):
        # Aucun ordre stable de la référence dans le lot : couverture nulle, « lot invalide », sans exception.
        autre = {
            "plans": [], "order_values": {"A MUN - RUH": 0.2, "F KIE - HOL": 0.2},
            "candidates": [{"orders": ["A MUN - RUH", "F KIE - HOL"], "value": 0.2, "prob": 1.0}],
            "search": {"lambda": 0.01, "boost": 3.0, "max_prob": 0.4},
        }
        c = comparer([autre] * 3)
        self.assertEqual((c["verdict"], c["couverture"], c["hors"], c["T_ov"]), ("lot invalide", 0.0, ["couverture"], None))
        decision = couche_r.decider({("S1901M", "FRANCE"): c})
        self.assertEqual((decision["decision"], decision["invalides"]), ("lot invalide", ["S1901M FRANCE"]))
        self.assertIn("couverture nulle", decision["motifs"][0])
        self.assertEqual(couche_r.CODES[decision["decision"]], 2)

    def test_couverture_sous_le_seuil(self):
        # Deux ordres stables sur trois dans le lot : 0,67 < 0,75.
        lot = [table(*ligne) for ligne in BASE]
        for t in lot:
            del t["order_values"][PIC]
        c = comparer(lot)
        self.assertAlmostEqual(c["couverture"], 2 / 3)
        self.assertEqual((c["verdict"], c["hors"], c["couples"], c["T_G"]), ("hors tolérance", ["couverture"], 0, 0.0))

    def test_tete_non_jugee(self):
        # Tête de référence non unanime (4 sur 5), ou lot de moins de 3 recherches : affichée, non jugée.
        partagee = [table(*ligne, tete="PIC" if i == 4 else "BUR") for i, ligne in enumerate(REFERENCE)]
        r = couche_r.resumer_position(tirages(partagee), order_loc())
        larges = dict(PLANCHERS, v_tete=1.0, S_ov=1.0, S_G=1.0)
        lot = tirages(table(b, p, lam, tete="PIC") for b, p, lam in BASE)
        c = couche_r.comparer_position(r, lot, order_loc(), larges)
        self.assertEqual((c["tete_jugee"], c["tete_lot"], c["tete_reference_effectif"], c["hors"]), (False, 0, 4, []))
        court = couche_r.comparer_position(reference(), lot[:2], order_loc(), larges)
        self.assertEqual((court["tete_jugee"], court["tete_lot"], court["hors"]), (False, 0, []))
        self.assertEqual(couche_r.comparer_position(reference(), lot, order_loc(), larges)["hors"], ["tete"])

    def test_echelle_nulle(self):
        # Dispersion et plancher nuls : un écart nul reste dans la tolérance, le moindre écart en sort, sans division par zéro.
        r = couche_r.resumer_position(tirages(table(0.30, 0.25, 0.010) for _ in range(5)), order_loc())
        nuls = {cle: 0.0 for cle in PLANCHERS}
        self.assertEqual((r["ln_lambda"][1], r["S_ov"], r["S_G"]), (0.0, 0.0, 0.0))
        meme = couche_r.comparer_position(r, tirages(table(0.30, 0.25, 0.010) for _ in range(3)), order_loc(), nuls)
        self.assertEqual((meme["verdict"], meme["T_lambda"], meme["T_G"]), ("identique", 0.0, 0.0))
        autre = couche_r.comparer_position(r, tirages(table(0.30, 0.25, 0.011) for _ in range(3)), order_loc(), nuls)
        self.assertEqual((autre["verdict"], autre["hors"], autre["T_lambda"]), ("hors tolérance", ["lambda"], float("inf")))

    def test_structure_d_une_ligne_de_releve(self):
        bonne = releve(table(*BASE[0]), "FRANCE", 0)
        self.assertEqual(couche_r.echecs_des_controles(bonne), [])
        self.assertEqual(couche_r.echecs_des_controles(dict(bonne, appels_export=2)), ["appels_export = 2"])
        self.assertEqual(couche_r.echecs_des_controles({"appels_export": 1}), ["controles absents"])
        for cle, valeur in (("tete_recalculee_egale_rendue", False), ("table_dans_politique_avant", None),
                            ("avertissement_table_inutilisable", True), ("actions_hors_politique_avant", [TETE])):
            mauvaise = dict(bonne, controles=dict(bonne["controles"], **{cle: valeur}))
            self.assertEqual(couche_r.echecs_des_controles(mauvaise), [cle])
        sans = dict(bonne, controles={c: v for c, v in bonne["controles"].items() if c != "search_present"})
        self.assertEqual(couche_r.echecs_des_controles(sans), ["search_present"])
        # Les douze contrôles de rejeu_moteur.controler que la spécification nomme, et pas un de plus.
        self.assertEqual(len(couche_r.CONTROLES_VRAIS + couche_r.CONTROLES_FAUX + couche_r.CONTROLES_VIDES), 12)


def position(verdict="dans la tolérance", hors=(), k=5, signe=1.0, grossier=False, structure=()):
    """Une sortie de comparer_position, réduite à ce que lit decider."""
    return {"verdict": verdict, "hors": list(hors), "K": k, "grossier": grossier, "structure": list(structure),
            "d_ln_lambda": signe, "d_v_tete": -signe, "d_ov_mediane_signee": 0.0}


def execution(n=21, **particulieres):
    """n positions dans la tolérance, signes alternés ; `particulieres` : {rang: position}."""
    par_position = {("S19%02dM" % (1 + i // 7), reference_jeu.POWERS[i % 7]): position(signe=1.0 if i % 2 else -1.0)
                    for i in range(n)}
    for rang, p in particulieres.items():
        par_position[sorted(par_position)[int(rang[1:])]] = p
    return par_position


class Decision(unittest.TestCase):
    def test_seuil_du_test_des_signes(self):
        # 2 x P(Bin(21, 1/2) >= 17) = 2 x (5985 + 1330 + 210 + 21 + 1) / 2^21 = 15094 / 2097152 = 0,0072 ;
        # à 16 : + 2 x 20349 -> 0,0266 > 0,01.
        k, p = couche_r.seuil_signes(21)
        self.assertEqual(k, 17)
        self.assertAlmostEqual(p, 15094 / 2097152, places=12)
        # 8 positions : 2 / 256 = 0,0078 ; 7 positions : 2 / 128 = 0,0156 > 0,01, aucun seuil.
        self.assertEqual(couche_r.seuil_signes(8), (8, 2 / 256))
        self.assertEqual(couche_r.seuil_signes(7), (None, None))
        self.assertEqual(couche_r.seuil_signes(0), (None, None))

    def test_pas_de_regression(self):
        d = couche_r.decider(execution())
        self.assertEqual((d["decision"], d["motifs"], d["hors_tolerance"]), ("pas de régression", [], []))
        self.assertEqual(d["signes"]["grandeurs"]["d_ln_lambda"], {"plus": 10, "moins": 11, "declenche": False})
        self.assertEqual((d["signes"]["seuil"], d["signes"]["positions"]), (17, 21))

    def test_une_position_hors_tolerance_non_concluant(self):
        d = couche_r.decider(execution(p3=position("hors tolérance", ["ov"])))
        self.assertEqual((d["decision"], len(d["hors_tolerance"])), ("non concluant", 1))
        self.assertIn("la relancer seule, une fois", d["motifs"][0])

    def test_deux_positions_hors_tolerance_regression(self):
        d = couche_r.decider(execution(p3=position("hors tolérance", ["ov"]), p9=position("hors tolérance", ["lambda"])))
        self.assertEqual((d["decision"], d["motifs"]), ("régression", ["2 positions hors tolérance"]))

    def test_un_t_au_dela_de_deux_tau_regression(self):
        d = couche_r.decider(execution(p3=position("hors tolérance", ["lambda"], grossier=True)))
        self.assertEqual(d["decision"], "régression")
        self.assertIn("un T au-delà de 10", d["motifs"][0])

    def test_structure_regression(self):
        d = couche_r.decider(execution(p0=position("hors tolérance", ["structure"], structure=["appels_export = 2"])))
        self.assertEqual(d["decision"], "régression")
        self.assertIn("contrôle structurel en échec (S1901M AUSTRIA)", d["motifs"][0])

    def test_signes_regression(self):
        # 17 positions sur 21 dans le même sens sur ln lambda : déclenché ; 16 : non.
        def avec(n):
            par_position = execution()
            for i, cle in enumerate(sorted(par_position)):
                par_position[cle] = dict(position(signe=1.0 if i < n else -1.0), d_v_tete=1.0 if i % 2 else -1.0)
            return couche_r.decider(par_position)

        self.assertEqual(avec(16)["decision"], "pas de régression")
        d = avec(17)
        self.assertEqual(d["decision"], "régression")
        self.assertEqual(d["motifs"], ["test des signes sur ln lambda : 17 contre 4, seuil 17 sur 21 positions"])
        self.assertEqual(avec(4)["decision"], "régression")  # 17 dans l'autre sens

    def test_signes_inapplicables_a_moins_de_8_positions(self):
        par_position = {p: position(signe=1.0) for p in list(execution())[:7]}
        d = couche_r.decider(par_position)
        self.assertEqual((d["decision"], d["signes"]["seuil"]), ("pas de régression", None))
        par_position = {p: position(signe=1.0) for p in list(execution())[:8]}
        self.assertEqual(couche_r.decider(par_position)["decision"], "régression")

    def test_lot_incomplet(self):
        par_position = execution()
        attendues = sorted(par_position)
        del par_position[attendues[5]]
        d = couche_r.decider(par_position, attendues)
        self.assertEqual((d["decision"], d["manquantes"]), ("non concluant", [couche_r.nom_position(attendues[5])]))
        d = couche_r.decider(execution(p2=position(k=2)))
        self.assertEqual((d["decision"], len(d["moins_de_k_min"])), ("non concluant", 1))
        self.assertIn("moins de 3 recherches A", d["motifs"][0])
        self.assertEqual(couche_r.decider(execution(p2=position(k=2)), k_min=1)["decision"], "pas de régression")

    def test_la_regression_l_emporte_sur_le_lot_incomplet(self):
        d = couche_r.decider(execution(p2=position(k=2), p3=position("hors tolérance", ["ov"]),
                                       p4=position("hors tolérance", ["ov"])))
        self.assertEqual(d["decision"], "régression")

    def test_codes_de_retour(self):
        self.assertEqual(couche_r.CODES, {"pas de régression": 0, "régression": 1, "non concluant": 2, "lot invalide": 2})


# ---------------------------------------------------------------------------
# Commandes, sur des relevés et un jeu fabriqués
# ---------------------------------------------------------------------------

CONTROLES = dict(
    {cle: True for cle in couche_r.CONTROLES_VRAIS},
    avertissement_table_inutilisable=False, actions_hors_politique_avant=[], probabilites_differentes_de_la_politique_avant=[],
)
PUISSANCES = ("ENGLAND", "FRANCE")
DECALAGES = {"ENGLAND": 0.10, "FRANCE": 0.0}  # deux positions aux valeurs distinctes


def releve(entree, puissance, tirage, recherche="A", game_id=9, engagements=()):
    """Une ligne de relevé de rejeu_moteur.py, réduite à ce que lisent bruit_valeurs.lire_releves et la couche R."""
    return {
        "mesure": "M1", "a_sec": False, "game_id": game_id, "phase": "S1901M", "puissance": puissance, "tirage": tirage,
        "recherche": recherche, "engagements_retenus_par_le_moteur": list(engagements), "entree": entree,
        "appels_export": 1, "controles": copy.deepcopy(CONTROLES),
    }


def lignes_du_lot(puissance, valeurs=REFERENCE, avec_b=True, **cles):
    """Les lignes d'un fichier de relevés : par tirage, une recherche A et, si `avec_b`, une recherche B."""
    lignes = []
    for i, (bur, pic, lam) in enumerate(valeurs):
        decale = DECALAGES[puissance]
        lignes.append(releve(table(bur + decale, pic + decale, lam), puissance, i, **cles))
        if avec_b:
            lignes.append(releve(table(bur + decale, pic + decale, lam), puissance, i, recherche="B", engagements=[BUR], **cles))
    return lignes


class AvecDossiers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.jeu = self.racine / "jeu"
        self.releves = self.ecrire("reference", {p: lignes_du_lot(p) for p in PUISSANCES})
        reference_jeu.construire_jeu(
            self.jeu, {"phases": [{"name": "S1901M", "orders": {"FRANCE": TETE}}]},
            {"S1901M": {p: reference_jeu.reduire_table(self.lignes(self.releves, p)[0]["entree"]) for p in PUISSANCES}},
            {"partie": {"numero": 9, "creee_le": "2026-01-01", "nature": reference_jeu.NATURE},
             "capture": {"date": "2026-01-02", "sha_code": SHA, "image": "sha256:" + "0" * 64, "commande": "essai"}})

    def ecrire(self, nom, par_puissance):
        dossier = self.racine / nom
        dossier.mkdir()
        for puissance, lignes in par_puissance.items():
            (dossier / ("m1_9_S1901M_%s_engagements_0.jsonl" % puissance)).write_text(
                "".join(json.dumps(ligne) + "\n" for ligne in lignes), encoding="utf-8")
        return dossier

    def lignes(self, dossier, puissance):
        fichier = dossier / ("m1_9_S1901M_%s_engagements_0.jsonl" % puissance)
        return [json.loads(ligne) for ligne in fichier.read_text(encoding="utf-8").splitlines()]

    def lancer(self, *arguments):
        """(code, sortie standard, sortie d'erreur) ; l'état du dépôt est doublé : arbre propre."""
        sortie, erreur = io.StringIO(), io.StringIO()
        with mock.patch.object(couche_d, "arbre_modifie", lambda: []), \
                contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            code = couche_r.main([str(a) for a in arguments])
        return code, sortie.getvalue(), erreur.getvalue()

    def resumer(self, releves=None, *options):
        return self.lancer("resumer", releves or self.releves, "--vers", self.jeu, "--sha", SHA, "--date", "2026-01-03", *options)

    def comparer(self, lot, *options):
        return self.lancer("comparer", lot, "--jeu", self.jeu, *options)


class Commandes(AvecDossiers):
    def test_resumer_ecrit_le_resume_et_son_bloc(self):
        avant = reference_jeu.fichiers_du_jeu(self.jeu)
        code, sortie, erreur = self.resumer()
        self.assertEqual((code, erreur), (0, ""))
        self.assertEqual(sorted(set(reference_jeu.fichiers_du_jeu(self.jeu)) - set(avant)), [reference_jeu.REPETEE])
        self.assertEqual(reference_jeu.controler(self.jeu), [])
        resume = reference_jeu.lire_repetee(self.jeu)
        self.assertEqual(sorted(resume), ["planchers", "positions"])
        self.assertEqual(list(resume["positions"]["S1901M"]), ["ENGLAND", "FRANCE"])
        france = resume["positions"]["S1901M"]["FRANCE"]
        self.assertEqual(sorted(france), sorted(reference_jeu.CLES_RESUME))
        self.assertEqual((france["n"], france["tetes"], france["S_G"]), (5, [{"orders": TETE, "n": 5}], 0.01225))
        # Deux positions aux mêmes dispersions : chaque plancher, leur médiane, est cette dispersion.
        self.assertEqual(resume["planchers"], {"ln_lambda": 0.10896, "v_tete": 0.00707, "S_ov": 0.0108, "S_G": 0.01225})
        bloc = reference_jeu.charger_json((self.jeu / "manifeste.json").read_text(encoding="utf-8"))["repetee"]
        self.assertEqual((bloc["date"], bloc["sha_code"], bloc["commande"]), ("2026-01-03", SHA, couche_r.COMMANDE_RESUMER))
        # 2 fichiers, 10 recherches A résumées (les B n'y entrent pas) ; l'empreinte est celle des fichiers lus.
        self.assertEqual((bloc["releves"]["fichiers"], bloc["releves"]["recherches"]), (2, 10))
        noms = [f.name for f in sorted(self.releves.iterdir())]
        self.assertEqual(bloc["releves"]["sha256"], couche_r.empreinte_des_releves(self.releves, noms))
        self.assertIn("Résumé de 2 position(s) écrit", sortie)
        self.assertIn("tirage 0 égal à la table figée du jeu : 2 position(s) sur 2", sortie)

    def test_resumer_refuse(self):
        # Un résumé déjà là.
        self.assertEqual(self.resumer()[0], 0)
        code, sortie, erreur = self.resumer()
        self.assertEqual((code, sortie), (2, ""))
        self.assertIn("un résumé ne s'écrit pas par-dessus un autre", erreur)

    def test_resumer_refuse_des_releves_qui_ne_sont_pas_ceux_du_jeu(self):
        autres = {p: lignes_du_lot(p, valeurs=[(b + 0.01, pic, lam) for b, pic, lam in REFERENCE]) for p in PUISSANCES}
        code, _sortie, erreur = self.resumer(self.ecrire("autres", autres))
        self.assertEqual(code, 2)
        self.assertIn("n'est pas la table figée du jeu pour 2 position(s) sur 2", erreur)
        self.assertIsNone(reference_jeu.lire_repetee(self.jeu))
        self.assertEqual(reference_jeu.controler(self.jeu), [])  # rien n'a été écrit

    def test_resumer_refuse_un_arbre_modifie_et_un_jeu_non_conforme(self):
        sortie, erreur = io.StringIO(), io.StringIO()
        with mock.patch.object(couche_d, "arbre_modifie", lambda: [" M tests/x.py"]), \
                contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            code = couche_r.main(["resumer", str(self.releves), "--vers", str(self.jeu), "--sha", SHA])
            self.assertEqual(code, 2)
            self.assertIn("arbre de travail modifié", erreur.getvalue())
            self.assertIsNone(reference_jeu.lire_repetee(self.jeu))
            code = couche_r.main(["resumer", str(self.releves), "--vers", str(self.jeu), "--sha", SHA, "--arbre-modifie"])
        self.assertEqual(code, 0)
        bloc = reference_jeu.charger_json((self.jeu / "manifeste.json").read_text(encoding="utf-8"))["repetee"]
        self.assertEqual(bloc["sha_code"], SHA + "-modifie")
        # Un jeu retouché à la main : refus, rien n'est entériné.
        (self.jeu / reference_jeu.REPETEE).unlink()
        code, _sortie, erreur = self.resumer()
        self.assertEqual(code, 2)
        self.assertIn("ne passe pas son contrôle", erreur)

    def test_resumer_refuse_deux_fichiers_pour_une_position(self):
        double = self.releves / "m1_9_S1901M_FRANCE_engagements-passe2_0.jsonl"
        double.write_text((self.releves / "m1_9_S1901M_FRANCE_engagements_0.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        code, _sortie, erreur = self.resumer()
        self.assertEqual(code, 2)
        self.assertIn("deux fichiers pour la position S1901M FRANCE", erreur)
        self.assertEqual(self.resumer(None, "--sauf", "*passe2*")[0], 0)

    def test_comparer_sans_resume(self):
        code, sortie, erreur = self.comparer(self.releves)
        self.assertEqual((code, sortie), (2, ""))
        self.assertIn("n'a pas de résumé des positions répétées (repetee.json)", erreur)

    def test_la_reference_contre_elle_meme_est_identique(self):
        self.resumer()
        detail = self.racine / "detail.json"
        code, sortie, erreur = self.comparer(self.releves, "--sortie", detail)
        self.assertEqual((code, erreur), (0, ""))
        self.assertRegex(sortie, r"\n  S1901M ENGLAND +identique +5 +0\.00 +0\.00 +0\.00 +0\.00 .* 5/5 ; 5/5 +1\.00  satisfaite\n")
        self.assertRegex(sortie, r"\n  S1901M FRANCE +identique ")
        self.assertIn("Décision : PAS DE RÉGRESSION", sortie)
        self.assertIn("20 ligne(s), 10 recherche(s) A, 10 recherche(s) B", sortie)
        # La sortie nomme ses limites (spécification, § 2.4), et le détail les porte.
        self.assertIn("Limites :", sortie)
        self.assertIn("un changement limité à une position et inférieur à sa tolérance n'est pas vu", sortie)
        self.assertIn("+ 0,005 ne l'a pas été", sortie)
        self.assertIn("test des signes : inapplicable à 2 position(s)", sortie)
        self.assertNotIn("renfort non contrôlé", sortie)
        ecrit = json.loads(detail.read_text(encoding="utf-8"))
        self.assertEqual(ecrit["decision"]["decision"], "pas de régression")
        self.assertEqual(sorted(ecrit["positions"]), ["S1901M ENGLAND", "S1901M FRANCE"])
        self.assertEqual(len(ecrit["limites"]), 6)
        self.assertEqual(ecrit["parametres"]["tau"], 5.0)

    def test_lot_de_base_dans_la_tolerance(self):
        # Le lot de base (3 tirages) pour les deux positions. Planchers = dispersions de la référence : les T sont
        # ceux du lot A de la spécification, aux arrondis des dispersions près.
        self.resumer()
        lot = self.ecrire("lot", {p: lignes_du_lot(p, BASE, avec_b=False) for p in PUISSANCES})
        code, sortie, _erreur = self.comparer(lot)
        self.assertEqual(code, 0)
        self.assertRegex(sortie, r"\n  S1901M FRANCE +dans la tolérance +3 +0\.03 +0\.65 +0\.42 +0\.37 ")
        self.assertIn("lot sans recherche B : renfort non contrôlé", sortie)

    def test_une_position_hors_tolerance_puis_deux(self):
        self.resumer()
        mute = [(b, p, lam * 1.9) for b, p, lam in BASE]  # ln 1,9 = 0,642 : T_lambda = 0,639 / 0,0796 = 8,0, entre tau et 2 tau
        lot = self.ecrire("un", {"ENGLAND": lignes_du_lot("ENGLAND", BASE), "FRANCE": lignes_du_lot("FRANCE", mute)})
        code, sortie, _erreur = self.comparer(lot)
        self.assertEqual(code, 2)
        self.assertIn("Décision : NON CONCLUANT", sortie)
        self.assertIn("hors tolérance sur : lambda", sortie)
        lot = self.ecrire("deux", {p: lignes_du_lot(p, mute) for p in PUISSANCES})
        code, sortie, _erreur = self.comparer(lot)
        self.assertEqual(code, 1)
        self.assertIn("Décision : RÉGRESSION\n  2 positions hors tolérance", sortie)

    def test_structure_sur_une_recherche_b(self):
        # Un contrôle en échec sur une ligne B, que la tolérance ne lit pas : régression.
        self.resumer()
        lignes = lignes_du_lot("FRANCE", BASE)
        lignes[1]["controles"]["tete_recalculee_egale_rendue"] = False
        lot = self.ecrire("lot", {"ENGLAND": lignes_du_lot("ENGLAND", BASE), "FRANCE": lignes})
        code, sortie, _erreur = self.comparer(lot)
        self.assertEqual(code, 1)
        self.assertIn("ÉCHEC : tete_recalculee_egale_rendue", sortie)
        self.assertIn("contrôle structurel en échec (S1901M FRANCE)", sortie)

    def test_recherche_sans_table_exportee(self):
        # Les recherches A d'une position n'exportent plus rien : rien à mesurer, la structure suffit.
        self.resumer()
        lignes = lignes_du_lot("FRANCE", BASE, avec_b=False)
        for ligne in lignes:
            ligne["entree"] = None
            ligne["controles"]["entree_exportee"] = False
        lot = self.ecrire("lot", {"ENGLAND": lignes_du_lot("ENGLAND", BASE), "FRANCE": lignes})
        code, sortie, erreur = self.comparer(lot)
        self.assertEqual((code, erreur), (1, ""))
        self.assertRegex(sortie, r"\n  S1901M FRANCE +hors tolérance +0 +- +- +- +- .*ÉCHEC : entree_exportee")

    def test_valeur_de_tete_non_finie_dans_un_lot(self):
        # Les recherches A d'une position rendent une valeur de tête NaN : régression (structure), jamais « dans la tolérance ».
        self.resumer()
        lignes = lignes_du_lot("FRANCE", BASE, avec_b=False)
        for ligne in lignes:
            ligne["entree"]["candidates"][0]["value"] = float("nan")
        lot = self.ecrire("lot", {"ENGLAND": lignes_du_lot("ENGLAND", BASE), "FRANCE": lignes})
        code, sortie, erreur = self.comparer(lot)
        self.assertEqual((code, erreur), (1, ""))
        self.assertRegex(sortie, r"\n  S1901M FRANCE +hors tolérance +0 .*ÉCHEC : .*valeur de tête non finie")
        self.assertIn("Décision : RÉGRESSION", sortie)
        # Une seule des trois : la position garde deux recherches A lisibles, et reste en échec de structure.
        lignes = lignes_du_lot("FRANCE", BASE, avec_b=False)
        lignes[1]["entree"]["candidates"][0]["value"] = float("nan")
        lot = self.ecrire("une", {"ENGLAND": lignes_du_lot("ENGLAND", BASE), "FRANCE": lignes})
        code, sortie, _erreur = self.comparer(lot)
        self.assertEqual(code, 1)
        self.assertRegex(sortie, r"\n  S1901M FRANCE +hors tolérance +2 .*valeur de tête non finie")

    def test_resumer_refuse_une_valeur_non_finie_avant_toute_ecriture(self):
        lignes = self.lignes(self.releves, "FRANCE")
        lignes[2]["entree"]["candidates"][0]["value"] = float("nan")  # la recherche A du tirage 1
        manifeste = (self.jeu / "manifeste.json").read_bytes()
        code, sortie, erreur = self.resumer(self.ecrire("nan", {"ENGLAND": self.lignes(self.releves, "ENGLAND"), "FRANCE": lignes}))
        self.assertEqual((code, sortie), (2, ""))
        self.assertIn("relevés en échec de structure pour 1 position(s), rien n'est écrit : S1901M FRANCE", erreur)
        self.assertIn("valeur de tête non finie", erreur)
        self.assertIsNone(reference_jeu.lire_repetee(self.jeu))
        self.assertEqual((self.jeu / "manifeste.json").read_bytes(), manifeste)
        # De même pour un contrôle de relevé en échec dans les relevés de référence.
        lignes = self.lignes(self.releves, "FRANCE")
        lignes[0]["appels_export"] = 2
        code, _sortie, erreur = self.resumer(self.ecrire("deux", {"ENGLAND": self.lignes(self.releves, "ENGLAND"), "FRANCE": lignes}))
        self.assertEqual(code, 2)
        self.assertIn("S1901M FRANCE (appels_export = 2)", erreur)
        self.assertIsNone(reference_jeu.lire_repetee(self.jeu))

    def test_un_fichier_ecarte_n_est_pas_lu(self):
        # --sauf et --seulement s'appliquent avant la lecture : un relevé illisible qu'ils écartent ne gêne pas.
        self.resumer()
        casse = self.releves / "m1_9_S1901M_FRANCE_engagements-casse_0.jsonl"
        casse.write_text("ceci n'est pas du JSON\n", encoding="utf-8")
        code, _sortie, erreur = self.comparer(self.releves)
        self.assertEqual(code, 2)
        self.assertIn("%s:1 : ligne qui n'est pas du JSON" % casse, erreur)  # le chemin du dossier donné, pas celui d'une vue
        code, sortie, erreur = self.comparer(self.releves, "--sauf", "*casse*")
        self.assertEqual((code, erreur), (0, ""))
        self.assertIn("2 fichier(s), 20 ligne(s)", sortie)
        self.assertEqual(self.comparer(self.releves, "--seulement", "*_engagements_0.jsonl")[0], 0)

    def test_lot_incomplet(self):
        self.resumer()
        lot = self.ecrire("lot", {"FRANCE": lignes_du_lot("FRANCE", BASE)})
        code, sortie, _erreur = self.comparer(lot)
        self.assertEqual(code, 2)
        self.assertIn("lot incomplet : 1 position(s) attendue(s) absente(s) (S1901M ENGLAND)", sortie)
        # Exécution réduite, annoncée : la position absente n'est pas attendue.
        self.assertEqual(self.comparer(lot, "--positions", "S1901M:france")[0], 0)
        code, _sortie, erreur = self.comparer(lot, "--positions", "F1901M")
        self.assertEqual(code, 2)
        self.assertIn("aucune position du résumé de référence", erreur)
        court = self.ecrire("court", {p: lignes_du_lot(p, BASE[:2]) for p in PUISSANCES})
        code, sortie, _erreur = self.comparer(court)
        self.assertEqual(code, 2)
        self.assertIn("lot incomplet : moins de 3 recherches A (S1901M ENGLAND, S1901M FRANCE)", sortie)

    def test_lot_invalide(self):
        self.resumer()
        # Une autre position sous le nom de FRANCE : couverture nulle, code 2, sans trace.
        autre = {
            "plans": [], "order_values": {"A MUN - RUH": 0.2, "F KIE - HOL": 0.2},
            "candidates": [{"orders": ["A MUN - RUH", "F KIE - HOL"], "value": 0.2, "prob": 1.0}],
            "search": {"lambda": 0.01, "boost": 3.0, "max_prob": 0.4},
        }
        lot = self.ecrire("autre", {"ENGLAND": lignes_du_lot("ENGLAND", BASE),
                                    "FRANCE": [releve(autre, "FRANCE", i) for i in range(3)]})
        code, sortie, erreur = self.comparer(lot)
        self.assertEqual((code, erreur), (2, ""))
        self.assertRegex(sortie, r"\n  S1901M FRANCE +lot invalide ")
        self.assertIn("Décision : LOT INVALIDE", sortie)
        # Une autre partie, un essai à sec, un dossier sans relevé, un jeu retouché : un message, code 2.
        for nom, cles, motif in (("partie", {"game_id": 8}, "lot de la partie 8, référence de la partie 9"),):
            lot = self.ecrire(nom, {p: lignes_du_lot(p, BASE, **cles) for p in PUISSANCES})
            code, sortie, erreur = self.comparer(lot)
            self.assertEqual((code, sortie), (2, ""))
            self.assertIn(motif, erreur)
        sec = {p: [dict(ligne, a_sec=True) for ligne in lignes_du_lot(p, BASE)] for p in PUISSANCES}
        self.assertIn("essai à sec", self.comparer(self.ecrire("sec", sec))[2])
        self.assertEqual(self.comparer(self.racine / "nulle_part")[0], 2)
        self.assertIn("aucun relevé m1_*.jsonl retenu", self.comparer(self.releves, "--seulement", "rien*")[2])
        (self.jeu / reference_jeu.REPETEE).write_text("{}\n", encoding="utf-8")
        code, _sortie, erreur = self.comparer(self.releves)
        self.assertEqual(code, 2)
        self.assertIn("ne passe pas son contrôle", erreur)

    def test_sans_commande(self):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.assertEqual(couche_r.main([]), 2)


class ControleDuJeu(AvecDossiers):
    """tests/reference_jeu.py : le résumé et son bloc au manifeste sont admis, et rien d'autre avec eux."""

    def setUp(self):
        super().setUp()
        self.assertEqual(reference_jeu.controler(self.jeu), [])  # sans résumé, le jeu est conforme
        self.assertEqual(self.resumer()[0], 0)
        self.resume = (self.jeu / reference_jeu.REPETEE).read_text(encoding="utf-8")
        self.manifeste = (self.jeu / "manifeste.json").read_text(encoding="utf-8")

    def violations(self, modifier=None, manifeste=None, sans_fichier=False):
        """Violations du jeu après une modification du résumé ou du manifeste, chacune partant du jeu conforme."""
        fichier = self.jeu / reference_jeu.REPETEE
        resume, donnees = json.loads(self.resume), json.loads(self.manifeste)
        if modifier is not None:
            modifier(resume)
        if manifeste is not None:
            manifeste(donnees)
        if sans_fichier:
            if fichier.exists():
                fichier.unlink()
        else:
            reference_jeu.ecrire_json(fichier, resume)
        reference_jeu.ecrire_manifeste(self.jeu, donnees)  # empreintes refaites : seule la forme est jugée
        return reference_jeu.controler(self.jeu)

    def une(self, motif, modifier=None, manifeste=None, sans_fichier=False):
        violations = self.violations(modifier, manifeste, sans_fichier)
        self.assertTrue(violations and all(motif in v for v in violations), violations)

    def test_conforme_avec_le_resume(self):
        self.assertEqual(self.violations(), [])
        self.assertIn(reference_jeu.REPETEE, reference_jeu.fichiers_du_jeu(self.jeu))

    def test_cle_hors_liste_blanche(self):
        self.une("clé hors liste blanche : 'journal' (exclue par l'ADR 0006)", lambda r: r.update(journal=[]))

    def test_cle_inconnue_dans_un_resume(self):
        self.une("clé hors liste blanche : 'tirages'", lambda r: r["positions"]["S1901M"]["FRANCE"].update(tirages=[]))

    def test_cle_absente(self):
        self.une("clé absente : 'S_G'", lambda r: r["positions"]["S1901M"]["FRANCE"].pop("S_G"))
        self.une("clé absente : 'S_ov'", lambda r: r["planchers"].pop("S_ov"))

    def test_texte_a_la_place_d_un_ordre(self):
        def texte(r):
            r["positions"]["S1901M"]["FRANCE"]["order_values"]["bonjour"] = [0.1, 0.0, 5]

        self.une("chaîne qui n'est pas un ordre en notation du moteur : 'bonjour'", texte)
        self.une("chaîne qui n'est pas un ordre",
                 lambda r: r["positions"]["S1901M"]["FRANCE"]["tetes"][0].update(orders=["A PAR - XXX"]))

    def test_valeur_qui_n_est_pas_un_nombre(self):
        self.une("nombre fini attendu", lambda r: r["positions"]["S1901M"]["FRANCE"].update(S_ov="grand"))
        self.une("[moyenne, écart type] attendu", lambda r: r["positions"]["S1901M"]["FRANCE"].update(ln_lambda=[1.0]))
        self.une("[moyenne, écart type, effectif] attendu",
                 lambda r: r["positions"]["S1901M"]["FRANCE"]["order_values"].update({BUR: [0.3, "x"]}))

    def test_position_sans_table(self):
        def deplacer(r):
            r["positions"]["S1901M"]["TURKEY"] = r["positions"]["S1901M"]["FRANCE"]

        self.une("positions.S1901M.TURKEY : résumé d'une position sans table dans tables/", deplacer)
        violations = self.violations(lambda r: r["positions"].update(printemps=r["positions"].pop("S1901M")))
        self.assertIn("repetee.json : positions (clé) : chaîne qui n'est pas une phase : 'printemps'", violations)

    def test_le_resume_et_son_bloc_vont_ensemble(self):
        self.une("repetee.json est dans le dossier sans son bloc", manifeste=lambda m: m.pop("repetee"))
        self.une("bloc sans repetee.json dans le dossier", sans_fichier=True)
        # Ni l'un ni l'autre : le jeu d'avant le résumé, conforme.
        self.assertEqual(self.violations(manifeste=lambda m: m.pop("repetee"), sans_fichier=True), [])

    def test_bloc_du_manifeste(self):
        self.une("clé absente : 'releves'", manifeste=lambda m: m["repetee"].pop("releves"))
        self.une("SHA-256 attendu", manifeste=lambda m: m["repetee"]["releves"].update(sha256="abc"))
        self.une("entier positif attendu", manifeste=lambda m: m["repetee"]["releves"].update(fichiers="21"))
        self.une("clé hors liste blanche : 'noms'", manifeste=lambda m: m["repetee"]["releves"].update(noms=[]))
        self.une("SHA complet", manifeste=lambda m: m["repetee"].update(sha_code="abc"))

    def test_resume_retouche_sans_refaire_le_manifeste(self):
        fichier = self.jeu / reference_jeu.REPETEE
        fichier.write_text(fichier.read_text(encoding="utf-8").replace('"n":5', '"n":4'), encoding="utf-8")
        violations = reference_jeu.controler(self.jeu)
        self.assertEqual(len(violations), 1)
        self.assertIn("repetee.json %s" % reference_jeu.NE_CORRESPOND_PLUS, violations[0])

    def test_generer_ne_conseille_pas_d_enteriner_un_resume_retouche(self):
        # Le refus de --generer (couche D) devant une violation portée par le résumé : le restaurer ou le refaire
        # par `resumer`, jamais les trois temps qui referaient ses empreintes.
        fichier = self.jeu / reference_jeu.REPETEE
        fichier.write_text(self.resume.replace('"n":5', '"n":4'), encoding="utf-8")
        retouche = reference_jeu.controler(self.jeu)
        sans_bloc = self.violations(manifeste=lambda m: m.pop("repetee"))
        cle_en_trop = self.violations(lambda r: r.update(journal=[]))
        for violations in (retouche, sans_bloc, cle_en_trop):
            self.assertEqual([couche_d._resume_en_cause(v) for v in violations], [True] * len(violations), violations)
            message = couche_d.refus_du_jeu(Path("D"), violations)
            self.assertIn("(%d violation(s), dont : %s)" % (len(violations), violations[0]), message)
            self.assertIn("Le restaurer depuis git avec le manifeste", message)
            self.assertIn("1) supprimer D/repetee.json et le bloc « repetee » du manifeste ; 2) python3 tests/reference_jeu.py "
                          "manifeste --dossier D ; 3) python3 tests/reference_couche_r.py resumer <relevés> --vers D", message)
            self.assertNotIn("supprimer D/attendus", message)
            self.assertNotIn("Si la modification est voulue", message)
        # Avec une autre violation : le résumé d'abord, le reste est annoncé.
        table_retouchee = "manifeste.json : fichiers : tables/S1901M.json %s (taille ou empreinte)" % reference_jeu.NE_CORRESPOND_PLUS
        self.assertFalse(couche_d._resume_en_cause(table_retouchee))
        self.assertFalse(couche_d._resume_en_cause("manifeste.json : fichiers : notes.txt est dans le dossier mais pas dans le manifeste"))
        message = couche_d.refus_du_jeu(Path("D"), [table_retouchee] + retouche)
        self.assertIn("dont : %s" % retouche[0], message)
        self.assertIn("Les 1 autre(s) violation(s) se traitent ensuite.", message)
        # Et --generer lui-même refuse, sans rien écrire.
        fichier.write_text(self.resume.replace('"n":5', '"n":4'), encoding="utf-8")
        reference_jeu.ecrire_json(self.jeu / "manifeste.json", json.loads(self.manifeste))
        (self.jeu / "manifeste.json").write_text(self.manifeste, encoding="utf-8")
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = couche_d.main(["--jeu", str(self.jeu), "--generer", "--sha", SHA])
        self.assertEqual(code, 2)
        self.assertIn("python3 tests/reference_couche_r.py resumer", sortie.getvalue())
        self.assertFalse((self.jeu / "attendus").exists())

    def test_forme_inattendue(self):
        (self.jeu / reference_jeu.REPETEE).write_text('{"planchers":[],"positions":[[]]}\n', encoding="utf-8")
        violations = reference_jeu.controler(self.jeu)
        self.assertTrue(any("repetee.json : planchers : objet attendu" in v for v in violations), violations)
        self.assertTrue(any("repetee.json : positions : objet attendu" in v for v in violations), violations)

    def test_la_couche_d_et_le_manifeste_gardent_le_bloc(self):
        # `reference_jeu.py manifeste` refait les empreintes sans perdre le bloc du résumé.
        avant = json.loads((self.jeu / "manifeste.json").read_text(encoding="utf-8"))["repetee"]
        self.assertEqual(reference_jeu.main(["manifeste", "--dossier", str(self.jeu)]), 0)
        self.assertEqual(json.loads((self.jeu / "manifeste.json").read_text(encoding="utf-8"))["repetee"], avant)
        self.assertEqual(reference_jeu.controler(self.jeu), [])
        self.assertEqual(sorted(reference_jeu.lire_jeu(self.jeu)), ["attendus", "historique", "manifeste", "tables"])


# ---------------------------------------------------------------------------
# Jeu versionné : lot = la table figée de chaque position répétée (K = 1)
# ---------------------------------------------------------------------------

RESUME_ABSENT = (
    "%s absent de %s : les cas de la couche R sur le jeu versionné sont sautés ; il se pose par la session principale, "
    "après visa (%s)" % (reference_jeu.REPETEE, JEU, couche_r.COMMANDE_RESUMER))


def resume_du_jeu():
    try:
        return reference_jeu.lire_repetee(JEU)
    except (OSError, ValueError):
        return None


@unittest.skipIf(resume_du_jeu() is None, RESUME_ABSENT)
class JeuVersionne(unittest.TestCase):
    """Valeurs figées sur le résumé des 21 positions répétées (relevés du 2026-10-10, première passe).

    Une table n'est pas un lot : K = 1 rend toute exécution « non concluant » ; ces cas ne jugent que le
    comparateur, k_min ramené à 1."""

    @classmethod
    def setUpClass(cls):
        cls.jeu = reference_jeu.lire_jeu(JEU)
        cls.resume = reference_jeu.lire_repetee(JEU)
        cls.references = couche_r.references_du_resume(cls.resume)

    def lot(self, mutation=None):
        tables = {}
        for phase, puissance in self.references:
            t = copy.deepcopy(self.jeu["tables"][phase][puissance])
            if mutation:
                mutation(t)
            tables.setdefault(phase, {})[puissance] = t
        return couche_r.lot_des_tables(tables)

    def juger(self, mutation=None, **cles):
        par_position, decision, hors_couche = couche_r.comparer_lot(self.lot(mutation), self.resume, order_loc(), **cles)
        self.assertEqual((len(par_position), hors_couche), (21, []))
        return par_position, decision

    def t_max(self, par_position):
        return max(o[cle] for o in par_position.values() for cle in ("T_lambda", "T_v_tete", "T_ov", "T_G"))

    def test_le_resume_du_jeu(self):
        self.assertEqual(reference_jeu.controler(JEU), [])
        self.assertEqual(len(self.references), 21)
        self.assertEqual({r["n"] for r in self.references.values()}, {5})
        self.assertEqual({(r["boost"], r["max_prob"]) for r in self.references.values()}, {(3.0, 0.4)})
        self.assertEqual(self.resume["planchers"], {"ln_lambda": 0.06936, "v_tete": 0.00918, "S_ov": 0.0074, "S_G": 0.00483})
        # Têtes unanimes dans 16 positions ; dans les 5 autres la tête est affichée, non jugée.
        partagees = sorted(couche_r.nom_position(p) for p, r in self.references.items() if r["tetes"][0]["n"] < r["n"])
        self.assertEqual(partagees, ["F1902M GERMANY", "F1902M RUSSIA", "S1902M FRANCE", "S1902M RUSSIA", "S1902M TURKEY"])

    def test_tel_quel(self):
        par_position, decision = self.juger(k_min=1)
        self.assertEqual({o["verdict"] for o in par_position.values()}, {"dans la tolérance"})
        self.assertEqual((decision["decision"], decision["hors_tolerance"]), ("pas de régression", []))
        self.assertAlmostEqual(self.t_max(par_position), 1.61, delta=0.005)
        self.assertEqual({o["tete_lot"] for o in par_position.values()} <= {0, 1}, True)
        # Au réglage d'une exécution, une table par position est un lot incomplet.
        _par_position, decision = self.juger()
        self.assertEqual((decision["decision"], len(decision["moins_de_k_min"])), ("non concluant", 21))

    def test_lambda_fois_0_3(self):
        def mutation(t):
            t["search"]["lambda"] *= 0.3

        par_position, decision = self.juger(mutation, k_min=1)
        self.assertEqual(decision["decision"], "régression")
        self.assertEqual(len(decision["hors_tolerance"]), 20)
        self.assertEqual({tuple(o["hors"]) for o in par_position.values()}, {("lambda",), ()})
        signes = decision["signes"]["grandeurs"]["d_ln_lambda"]
        self.assertEqual((signes["plus"], signes["moins"], signes["declenche"]), (0, 21, True))

    def test_valeurs_plus_0_05(self):
        def mutation(t):
            for candidat in t["candidates"]:
                candidat["value"] += 0.05
            t["order_values"] = {ordre: valeur + 0.05 for ordre, valeur in t["order_values"].items()}

        _par_position, decision = self.juger(mutation, k_min=1)
        self.assertEqual(decision["decision"], "régression")
        self.assertEqual(len(decision["hors_tolerance"]), 11)
        for cle in ("d_v_tete", "d_ov_mediane_signee"):
            signes = decision["signes"]["grandeurs"][cle]
            self.assertEqual((signes["plus"], signes["moins"], signes["declenche"]), (21, 0, True))

    def test_boost_2(self):
        def mutation(t):
            t["search"]["boost"] = 2.0

        par_position, decision = self.juger(mutation, k_min=1)
        self.assertEqual(decision["decision"], "régression")
        self.assertEqual(len(decision["hors_tolerance"]), 21)
        self.assertEqual({tuple(o["hors"]) for o in par_position.values()}, {("structure",)})
        self.assertIn("contrôle structurel en échec", decision["motifs"][0])


if __name__ == "__main__":
    programme = unittest.main(exit=False)
    if resume_du_jeu() is None:
        # La dernière ligne de la sortie : tests/verifier.sh n'en affiche que la fin.
        print("Couche R : %s." % RESUME_ABSENT)
    sys.exit(0 if programme.result.wasSuccessful() else 1)
