#!/usr/bin/env python3
"""Mesure du bruit des valeurs (issue #26) : tests/mesure/bruit_valeurs.py sur des tables fabriquées.

Aucun relevé réel ici (exigence 4.3) : les tables sont écrites à la main, au
format des relevés de tests/mesure/rejeu_moteur.py, et chaque valeur attendue
est calculée à la main dans le commentaire du test. Ni pile, ni Claude, ni GPU.

Usage : python3 tests/test_bruit_valeurs.py
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Avant tout chargement : ni __pycache__ dans tests/, ni .pyc sous cicero/overlay, que
# outils/exporter_patchs.sh --verifier et install.sh prendraient pour des fichiers d'overlay (#27).
sys.dont_write_bytecode = True

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tests" / "mesure"))
import bruit_valeurs as bruit  # noqa: E402

BOT = RACINE / "cicero" / "overlay" / "claude_dialogue_bot.py"
BUR, PIC, MAO, ENG, GAS = "A PAR - BUR", "A PAR - PIC", "F BRE - MAO", "F BRE - ENG", "A PAR - GAS"

# Trois tables, deux unités de deux ordres. order_values est la valeur de la première
# action qui contient l'ordre :
#   T1 : BUR 0,30  MAO 0,30  ENG 0,20  PIC 0,30    G(BUR, PIC) =  0,00   G(ENG, MAO) = 0,10
#   T2 : la même, (PIC, MAO) à 0,38                G(BUR, PIC) =  0,08   G(ENG, MAO) = 0,10
#   T3 : comme T2, mais PIC vient de (PIC, ENG)    G(BUR, PIC) =  0,08   G(ENG, MAO) = 0,10
T1 = [((BUR, MAO), 0.30), ((BUR, ENG), 0.20), ((PIC, MAO), 0.30)]
T2 = [((BUR, MAO), 0.30), ((BUR, ENG), 0.20), ((PIC, MAO), 0.38)]
T3 = [((BUR, MAO), 0.30), ((BUR, ENG), 0.20), ((PIC, ENG), 0.38), ((PIC, MAO), 0.30)]
VALEURS = {
    "T1": {BUR: 0.30, MAO: 0.30, ENG: 0.20, PIC: 0.30},
    "T2": {BUR: 0.30, MAO: 0.30, ENG: 0.20, PIC: 0.38},
}


def releve(actions, order_values, recherche="A", tirage=0, engagements=(), phase="S1901M", puissance="FRANCE"):
    """Une ligne de relevé, réduite aux clés que lit bruit_valeurs."""
    return {
        "mesure": "M1", "game_id": 9, "phase": phase, "puissance": puissance, "tirage": tirage,
        "recherche": recherche, "engagements_retenus_par_le_moteur": list(engagements),
        "entree": {
            "order_values": order_values,
            "candidates": [{"orders": list(a), "value": v, "prob": 0.1} for a, v in actions],
        },
    }


class Dossier:
    """Dossier temporaire de relevés ; lance le script dessus."""

    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.chemin = Path(tmp.name)

    def ecrire(self, nom, lignes):
        texte = "".join((ligne if isinstance(ligne, str) else json.dumps(ligne)) + "\n" for ligne in lignes)
        (self.chemin / nom).write_text(texte, encoding="utf-8")

    def lancer(self, *options):
        """(code de retour, sortie standard, sortie d'erreur, JSON écrit ou None)."""
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreur):
            code = bruit.main([str(self.chemin)] + list(options))
        fichier = self.chemin / "bruit_valeurs.json"
        detail = json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else None
        return code, sortie.getvalue(), erreur.getvalue(), detail


class Regle(unittest.TestCase):
    """La marge et l'unité d'un ordre viennent du bot, pas d'une copie."""

    def test_marge_lue_dans_le_bot(self):
        marge, order_loc, chemin = bruit.charger_regle()
        ecrite = re.search(r"^COMMITMENT_SWITCH_MARGIN = ([0-9.]+)$", BOT.read_text(encoding="utf-8"), re.M)
        self.assertEqual(chemin, BOT)
        self.assertEqual(marge, float(ecrite.group(1)))
        self.assertNotIn(ecrite.group(0), Path(bruit.__file__).read_text(encoding="utf-8"))
        self.assertEqual(order_loc("A PAR-BUR"), "PAR")  # la normalisation du bot

    def test_bot_introuvable(self):
        with self.assertRaises(bruit.ErreurReleve):
            bruit.charger_regle("/nulle/part/claude_dialogue_bot.py")

    def test_script_a_la_racine_d_un_conteneur(self):
        # Dans /mesure (tests/mesure/preparer.sh), le dossier du script n'a qu'un parent : pas de
        # dépôt à chercher, seul reste le bot de l'image -- absent du poste, d'où le message.
        image = Path("/opt/cicero/claude_dialogue_bot.py")
        with mock.patch.object(bruit.commun, "ICI", Path("/mesure")):
            if image.is_file():
                self.assertEqual(bruit.trouver_bot(), image)
            else:
                with self.assertRaises(bruit.ErreurReleve) as refus:
                    bruit.trouver_bot()
                self.assertIn("introuvable (%s)" % image, str(refus.exception))


class Calculs(unittest.TestCase):
    def test_centile_valeur_observee_de_rang_superieur(self):
        self.assertIsNone(bruit.centile([], 0.5))
        self.assertEqual(bruit.centile([7], 0.99), 7)
        self.assertEqual(bruit.centile([4, 1, 3, 2], 0.5), 3)  # rang ceil(1,5) = 2
        self.assertEqual(bruit.centile([1, 2, 3, 4], 0.9), 4)  # rang ceil(2,7) = 3
        self.assertEqual(bruit.centile([1, 2, 3], 0.5), 2)  # rang 1, entier : pas de rang au-dessus
        self.assertEqual(bruit.centile(list(range(101)), 0.99), 99)  # rang 99, entier
        self.assertEqual(bruit.centile(list(range(100)), 0.99), 99)  # rang ceil(98,01) : le maximum

    def test_marge_effective_sur_le_99e_centile(self):
        # 21 observations, |d| de 0,000 à 0,020 : c95 = rang 19 = 0,019 ; c99 = rang ceil(19,8) = 20 = 0,020.
        # Marge effective = 0,05 - 0,020 = 0,030. Références : 0 pour 5 observations, 0,2 pour les autres ;
        # G = 0,06 > marge partout : 21 acceptations, dont 5 sur bruit -- 5 / 5 des observations sans gain.
        obs = [
            {"groupe": ("g",), "position": ("p",), "couple": ("E%d" % i, "N"), "table": "t", "g": 0.06,
             "reference": 0.0 if i < 5 else 0.2, "d": i / 1000.0, "porteuse_changee": False}
            for i in range(21)
        ]
        bloc = bruit.bloc_bruit(obs, (0.05,), couples_seuls=7)
        self.assertEqual((bloc["abs_d"]["c95"], bloc["abs_d"]["c99"], bloc["abs_d"]["max"]), (0.019, 0.02, 0.02))
        self.assertEqual((bloc["couples_dans_une_seule_table"], bloc["observations_sans_gain"]), (7, 5))
        m = bloc["par_marge"]["0.05"]
        self.assertAlmostEqual(m["marge_effective"], 0.03)
        self.assertEqual((m["acceptations"], m["acceptations_sur_bruit"]), (21, 5))
        self.assertEqual(m["part_sur_bruit_des_observations_sans_gain"], 1.0)
        self.assertAlmostEqual(m["part_sur_bruit_des_observations"], 5 / 21)

    def test_gains_par_unite(self):
        _marge, order_loc, _chemin = bruit.charger_regle()
        g = bruit.gains(dict(VALEURS["T2"], **{"A MAR H": 0.5}), order_loc)
        # Deux unités de deux ordres : quatre couples ordonnés ; A MAR H, seul sur son unité, n'en fait aucun.
        self.assertEqual(g, {(BUR, PIC): 0.08, (PIC, BUR): -0.08, (MAO, ENG): -0.1, (ENG, MAO): 0.1})

    def test_porteuse_premiere_action_qui_contient_l_ordre(self):
        candidates = [{"orders": list(a), "value": v} for a, v in T3]
        p = bruit.porteuses(VALEURS["T2"], candidates)
        self.assertEqual(p[PIC], (PIC, ENG))
        self.assertEqual(p[ENG], (BUR, ENG))
        self.assertIsNone(bruit.porteuses(VALEURS["T2"], None))
        self.assertIsNone(bruit.porteuses(VALEURS["T2"], candidates[:1]))  # PIC et ENG n'y sont pas


class Verdict(unittest.TestCase):
    """Les trois issues du critère, à leurs bornes ; aucun verdict sans les effectifs pour conclure."""

    def rendu(self, c95, c99, c99_pire, sur_bruit, observations=1000, sans_gain=1000, positions=10, tables=3,
              reunis=False, marge=0.05, nom="groupe"):
        par_position = {"p%d" % i: {"abs_d": {"c99": 0.0}} for i in range(positions - 1)}
        par_position["pire"] = {"abs_d": {"c99": c99_pire}}
        niveau = {
            "groupes": 10, "groupes_d_au_moins_deux_tables": 10, "tables_par_groupe_min": tables,
            "types_de_recherche_reunis": reunis, "par_position": par_position,
            "total": {
                "observations": observations, "observations_sans_gain": sans_gain,
                "abs_d": {"c95": c95, "c99": c99},
                "par_marge": {bruit.cle_marge(marge): {
                    "acceptations_sur_bruit": sur_bruit, "marge_effective": marge - c99,
                    "part_sur_bruit_des_observations_sans_gain": sur_bruit / sans_gain if sans_gain else None,
                }},
            },
        }
        return bruit.verdict(niveau, marge, nom)

    def test_protege(self):
        # Bornes comprises : c99 = marge / 2 au total, = marge dans la pire position.
        v = self.rendu(c95=0.01, c99=0.025, c99_pire=0.05, sur_bruit=0)
        self.assertEqual((v["verdict"], v["concluant"], v["pire_position"]), ("protège", True, "pire"))
        self.assertEqual((v["lecture_indicative"], v["avertissements"]), (None, []))

    def test_protege_partiellement(self):
        self.assertEqual(self.rendu(0.01, 0.0251, 0.05, 0)["verdict"], "protège partiellement")
        self.assertEqual(self.rendu(0.01, 0.025, 0.0501, 0)["verdict"], "protège partiellement")
        self.assertEqual(self.rendu(0.01, 0.025, 0.05, 1)["verdict"], "protège partiellement")
        self.assertEqual(self.rendu(0.0499, 0.06, 0.06, 10)["verdict"], "protège partiellement")  # 1 % tout juste

    def test_ne_protege_pas(self):
        self.assertEqual(self.rendu(0.05, 0.06, 0.06, 0)["verdict"], "ne protège pas")
        self.assertEqual(self.rendu(0.01, 0.02, 0.02, 11)["verdict"], "ne protège pas")  # 1,1 %

    def test_part_rapportee_aux_observations_sans_gain(self):
        # 3 acceptations sur bruit : 0,3 % des 1 000 observations, mais 1,5 % des 200 sans gain.
        self.assertEqual(self.rendu(0.01, 0.02, 0.02, 3, sans_gain=200)["verdict"], "ne protège pas")
        self.assertEqual(self.rendu(0.01, 0.02, 0.02, 2, sans_gain=200)["verdict"], "protège partiellement")  # 1 %
        self.assertEqual(self.rendu(0.01, 0.02, 0.02, 0, sans_gain=0)["verdict"], "protège")

    def test_seuils_relatifs_a_la_marge(self):
        # Les mêmes centiles, à la marge de 0,10 : 0,05 = marge / 2, 0,10 = marge.
        self.assertEqual(self.rendu(0.05, 0.05, 0.10, 0, marge=0.10)["verdict"], "protège")
        self.assertEqual(self.rendu(0.05, 0.0501, 0.10, 0, marge=0.10)["verdict"], "protège partiellement")
        self.assertEqual(self.rendu(0.10, 0.12, 0.12, 0, marge=0.10)["verdict"], "ne protège pas")
        self.assertEqual(self.rendu(0.02, 0.03, 0.03, 0, marge=0.02)["verdict"], "ne protège pas")

    def non_concluant(self, motif, **effectifs):
        v = self.rendu(0.01, 0.02, 0.02, 0, **effectifs)
        self.assertEqual((v["verdict"], v["lecture_indicative"], v["concluant"]), ("non concluant", "protège", False))
        self.assertEqual(len(v["avertissements"]), 1)
        self.assertIn(motif, v["avertissements"][0])

    def test_effectifs_aux_bornes(self):
        self.assertEqual((bruit.MIN_OBSERVATIONS, bruit.MIN_TABLES_PAR_GROUPE, bruit.MIN_POSITIONS), (100, 3, 10))
        self.assertTrue(self.rendu(0.01, 0.02, 0.02, 0, observations=100, positions=10, tables=3)["concluant"])
        self.non_concluant("99 observation(s), moins de 100", observations=99)
        self.non_concluant("9 position(s) mesurée(s), moins de 10", positions=9)
        self.non_concluant("des groupes de 2 tables, moins de 3", tables=2)
        self.non_concluant("minorant du bruit", reunis=True)

    def test_niveau_engagements_jamais_concluant(self):
        self.non_concluant("à titre indicatif", nom="engagements")


class Script(unittest.TestCase):
    def test_deux_tables_identiques(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"], tirage=0), releve(T1, VALEURS["T1"], tirage=1)])
        code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, erreur), (0, ""))
        total = detail["bruit"]["groupe"]["total"]
        self.assertEqual((total["tables"], total["couples"], total["observations"]), (2, 4, 8))
        self.assertEqual(total["abs_d"], {"n": 8, "mediane": 0.0, "c90": 0.0, "c95": 0.0, "c99": 0.0, "max": 0.0})
        for marge in total["par_marge"].values():
            self.assertEqual((marge["couples_non_unanimes"], marge["acceptations_sur_bruit"]), (0, 0))
        self.assertEqual(total["par_marge"]["0.05"]["marge_effective"], 0.05)
        # Critère rempli, mais 8 observations, 2 tables et 1 position : rien à conclure.
        verdict = detail["verdict"]["groupe"]
        self.assertEqual(
            (verdict["verdict"], verdict["lecture_indicative"], verdict["concluant"]),
            ("non concluant", "protège", False))
        self.assertEqual(len(verdict["avertissements"]), 3)
        self.assertEqual(detail["verdict"]["engagements"]["verdict"], "non concluant")
        self.assertIn(
            "niveau « groupe » : NON CONCLUANT -- lecture indicative : le critère donnerait « protège »\n", sortie)
        self.assertNotRegex(sortie, r"niveau « \w+ » : (PROTÈGE|NE PROTÈGE)")
        self.assertIn("exigence 2.10", sortie)
        self.assertIn("Reporté : instabilité de la règle entière", sortie)
        self.assertEqual(len(detail["reporte"]), 3)

    def test_un_seul_gain_differe(self):
        # T1 et T2 dans le même groupe. G(BUR, PIC) : 0,00 et 0,08 ; G(PIC, BUR) : 0,00 et -0,08 ;
        # G(MAO, ENG) = -0,10 et G(ENG, MAO) = 0,10 dans les deux.
        # |d| : 0,08 quatre fois (deux couples x deux tables), 0 quatre fois.
        #   médiane = rang ceil(3,5) = 4 = 0,08 ; c90 (rang 7), c95, c99 et maximum = 0,08.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"], tirage=0), releve(T2, VALEURS["T2"], tirage=1)])
        code, _sortie, erreur, detail = d.lancer()
        self.assertEqual((code, erreur), (0, ""))
        total = detail["bruit"]["groupe"]["total"]
        self.assertEqual(total["abs_d"], {"n": 8, "mediane": 0.08, "c90": 0.08, "c95": 0.08, "c99": 0.08, "max": 0.08})
        self.assertEqual(total["couples_dans_une_seule_table"], 0)
        # Aucune action porteuse ne change : seule la valeur de (PIC, MAO) a bougé.
        self.assertEqual([total["par_porteuse"][cas]["n"] for cas in bruit.PORTEUSES], [8, 0, 0])
        # Marge 0,05. « G > marge » : (BUR, PIC) non puis oui -> non unanime ; (PIC, BUR) et (MAO, ENG) non
        # deux fois, (ENG, MAO) oui deux fois -> unanimes. 1 couple sur 4.
        # Acceptations (G > 0,05) : T2 (BUR, PIC), T1 et T2 (ENG, MAO) = 3 ; sur bruit, la seule dont
        # l'autre table donne G <= 0 : T2 (BUR, PIC). 1 observation sur 8, 1 acceptation sur 3.
        # Observations sans gain (l'autre table donne G <= 0) : T2 (BUR, PIC), T1 et T2 (PIC, BUR),
        # T1 et T2 (MAO, ENG) = 5 ; une seule est acceptée : 1 sur 5.
        m = total["par_marge"]["0.05"]
        self.assertEqual((total["observations_sans_gain"], m["part_sur_bruit_des_observations_sans_gain"]), (5, 0.2))
        self.assertEqual((m["couples_non_unanimes"], m["part_couples_non_unanimes"]), (1, 0.25))
        self.assertEqual((m["acceptations"], m["acceptations_sur_bruit"]), (3, 1))
        self.assertEqual(m["part_sur_bruit_des_observations"], 0.125)
        self.assertAlmostEqual(m["part_sur_bruit_des_acceptations"], 1 / 3)
        self.assertAlmostEqual(m["marge_effective"], -0.03)  # 0,05 - 0,08
        # Balayage : 0,02 et 0,03 comme 0,05 ; à 0,08, G = 0,08 ne dépasse plus la marge ; à 0,10, plus rien.
        attendu = {"0.02": (1, 3, 1), "0.03": (1, 3, 1), "0.05": (1, 3, 1), "0.08": (0, 2, 0), "0.10": (0, 0, 0)}
        self.assertEqual(
            {k: (v["couples_non_unanimes"], v["acceptations"], v["acceptations_sur_bruit"])
             for k, v in total["par_marge"].items()}, attendu)
        # Par position et par groupe : un seul de chaque, égal au total.
        self.assertEqual(detail["bruit"]["groupe"]["par_position"], {"9 S1901M FRANCE": total})
        self.assertEqual(detail["bruit"]["groupe"]["par_groupe"], {"9 S1901M FRANCE | sans engagement | A": total})
        # 95e centile 0,08 >= marge : le critère donnerait « ne protège pas », sans pouvoir conclure.
        self.assertEqual(detail["verdict"]["groupe"]["verdict"], "non concluant")
        self.assertEqual(detail["verdict"]["groupe"]["lecture_indicative"], "ne protège pas")
        self.assertFalse(detail["verdict"]["groupe"]["concluant"])
        # La même paire, vue comme écart entre deux tables : 4 couples, 0 ; 0 ; 0,08 ; 0,08.
        paires = detail["paires"]["memes_engagements"]["total"]
        self.assertEqual((paires["paires"], paires["paires_de_meme_type"], paires["couples"]), (1, 1, 4))
        self.assertEqual((paires["ecart"]["mediane"], paires["ecart"]["max"]), (0.08, 0.08))  # rang ceil(1,5) = 2
        # Verdict changé : (BUR, PIC) seul. Sur bruit : le même (0,08 > marge, 0,00 <= 0).
        # À la marge de 0,08, G = 0,08 ne la dépasse plus : ni verdict changé ni acceptation.
        self.assertEqual(
            {k: (v["verdicts_changes"], v["acceptations_sur_bruit"]) for k, v in paires["par_marge"].items()},
            {"0.02": (1, 1), "0.03": (1, 1), "0.05": (1, 1), "0.08": (0, 0), "0.10": (0, 0)})
        self.assertEqual(detail["paires"]["engagements_differents"]["total"]["paires"], 0)

    def test_moyenne_des_autres_tables(self):
        # Trois tables d'un groupe, un ordre par unité sauf PAR : G(BUR, PIC) = 0,00 ; 0,03 ; 0,09.
        #   d = 0,00 - 0,06 = -0,06 ; 0,03 - 0,045 = -0,015 ; 0,09 - 0,015 = 0,075 (et l'opposé pour (PIC, BUR)).
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve([((BUR,), 0.30), ((PIC,), 0.30 + g)], {BUR: 0.30, PIC: round(0.30 + g, 5)}, tirage=i)
            for i, g in enumerate((0.0, 0.03, 0.09))
        ])
        code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        total = detail["bruit"]["groupe"]["total"]
        self.assertEqual((total["tables"], total["couples"], total["observations"]), (3, 2, 6))
        # |d| triés : 0,015 ; 0,015 ; 0,06 ; 0,06 ; 0,075 ; 0,075 -> médiane 0,06, maximum 0,075.
        self.assertAlmostEqual(total["abs_d"]["mediane"], 0.06)
        self.assertAlmostEqual(total["abs_d"]["max"], 0.075)
        # (BUR, PIC) : non, non, oui -> non unanime ; l'acceptation (0,09) a une référence de 0,015 > 0 :
        # pas sur bruit. (PIC, BUR) : jamais au-dessus de la marge.
        m = total["par_marge"]["0.05"]
        self.assertEqual((m["couples_non_unanimes"], m["acceptations"], m["acceptations_sur_bruit"]), (1, 1, 0))
        # Trois tables : l'avertissement « écart d'une paire » ne s'applique plus.
        self.assertEqual(len(detail["verdict"]["groupe"]["avertissements"]), 2)

    def test_action_porteuse_changee(self):
        # T1 et T3 : PIC passe de (PIC, MAO) à (PIC, ENG), les trois autres ordres gardent leur action.
        # Couples de PAR (porteuse de PIC changée) : |d| = 0,08, quatre observations ;
        # couples de BRE (porteuses inchangées) : |d| = 0, quatre observations.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"], tirage=0), releve(T3, VALEURS["T2"], tirage=1)])
        code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        par_porteuse = detail["bruit"]["groupe"]["total"]["par_porteuse"]
        self.assertEqual((par_porteuse["changee"]["n"], par_porteuse["changee"]["mediane"]), (4, 0.08))
        self.assertEqual((par_porteuse["inchangee"]["n"], par_porteuse["inchangee"]["max"]), (4, 0.0))
        self.assertEqual(par_porteuse["inconnue"]["n"], 0)
        paires = detail["paires"]["memes_engagements"]["total"]["par_porteuse"]
        self.assertEqual((paires["changee"]["n"], paires["inchangee"]["n"]), (2, 2))

    def test_table_sans_actions_candidates(self):
        sans = releve(T2, VALEURS["T2"], tirage=1)
        del sans["entree"]["candidates"]
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"], tirage=0), sans])
        code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(detail["bruit"]["groupe"]["total"]["par_porteuse"]["inconnue"]["n"], 8)

    def test_engagements_differents_et_effet_de_l_engagement(self):
        # A sans engagement (T1), B avec PIC engagé (T2), et une ligne « comparaison » à laisser de côté.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve(T1, VALEURS["T1"], recherche="A"),
            releve(T2, VALEURS["T2"], recherche="B", engagements=[PIC]),
            {"mesure": "M1", "comparaison": {"recherches": ["A", "B"]}},
        ])
        code, sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(detail["lecture"]["lignes_comparaison_ignorees"], 1)
        # Deux groupes d'une table : aucun bruit mesurable, à aucun des deux niveaux.
        for niveau in ("groupe", "engagements"):
            self.assertEqual(detail["bruit"][niveau]["total"]["observations"], 0)
            self.assertEqual(detail["verdict"][niveau]["verdict"], "indéterminé")
            self.assertFalse(detail["verdict"][niveau]["concluant"])
        self.assertIn("INDÉTERMINÉ", sortie)
        # La paire est à engagements différents : 1 verdict changé sur 4 couples.
        self.assertEqual(detail["paires"]["memes_engagements"]["total"]["paires"], 0)
        differents = detail["paires"]["engagements_differents"]["total"]
        self.assertEqual((differents["paires"], differents["paires_de_meme_type"], differents["couples"]), (1, 0, 4))
        self.assertEqual(differents["par_marge"]["0.05"]["verdicts_changes"], 1)
        # Effet = G en B - G en A : +0,08 pour (BUR, PIC), le seul couple tourné vers l'ordre engagé ;
        # -0,08 pour (PIC, BUR) ; 0 pour BRE. |effet| : 0 ; 0 ; 0,08 ; 0,08.
        effet = detail["effet_engagement"]
        self.assertEqual(effet["total"]["groupes"], 1)
        self.assertEqual((effet["total"]["abs_effet"]["n"], effet["total"]["abs_effet"]["max"]), (4, 0.08))
        self.assertEqual(effet["total"]["couples_vers_l_ordre_engage"], 1)
        self.assertEqual(effet["total"]["effet_moyen_vers_l_ordre_engage"], 0.08)
        self.assertEqual(effet["par_groupe"][0]["groupe"], "9 S1901M FRANCE | A PAR - PIC | B")

    def test_b_et_c_reunis_au_niveau_engagements_seulement(self):
        # Rejeu incrémental : B et C ont les mêmes engagements, pas le même type.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve(T1, VALEURS["T1"], recherche="B", engagements=[BUR]),
            releve(T2, VALEURS["T2"], recherche="C", engagements=[BUR]),
        ])
        code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(detail["bruit"]["groupe"]["total"]["observations"], 0)
        self.assertEqual(detail["bruit"]["engagements"]["total"]["observations"], 8)
        avertissements = " ".join(detail["verdict"]["engagements"]["avertissements"])
        self.assertIn("minorant", avertissements)
        self.assertEqual(detail["verdict"]["engagements"]["verdict"], "non concluant")
        self.assertEqual(detail["verdict"]["engagements"]["lecture_indicative"], "ne protège pas")
        self.assertIn("NON CONCLUANT -- lecture indicative : le critère donnerait « ne protège pas » ; minorant du bruit",
                      _sortie)
        paires = detail["paires"]["memes_engagements"]["total"]
        self.assertEqual((paires["paires"], paires["paires_de_meme_type"]), (1, 0))

    def test_couples_dans_une_seule_table_comptes(self):
        # T1, et T1 augmentée d'un troisième ordre pour PAR (GAS) : (BUR, GAS), (GAS, BUR), (PIC, GAS) et
        # (GAS, PIC) ne sont que dans la seconde table -- 4 couples écartés, 4 couples communs sans écart.
        avec_gas = T1 + [((GAS, MAO), 0.25)]
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve(T1, VALEURS["T1"], tirage=0), releve(avec_gas, dict(VALEURS["T1"], **{GAS: 0.25}), tirage=1)])
        code, sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        total = detail["bruit"]["groupe"]["total"]
        self.assertEqual((total["couples"], total["couples_dans_une_seule_table"], total["abs_d"]["max"]), (4, 4, 0.0))
        self.assertEqual(detail["bruit"]["groupe"]["par_position"]["9 S1901M FRANCE"]["couples_dans_une_seule_table"], 4)
        paires = detail["paires"]["memes_engagements"]["total"]
        self.assertEqual((paires["couples"], paires["couples_dans_une_seule_table"]), (4, 4))
        self.assertIn("1 table", sortie)

    def test_groupe_sans_couple_commun(self):
        # Deux tables du même groupe, l'une avec les seuls ordres de PAR, l'autre avec ceux de BRE.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve([((BUR,), 0.3), ((PIC,), 0.2)], {BUR: 0.3, PIC: 0.2}, tirage=0),
            releve([((MAO,), 0.3), ((ENG,), 0.2)], {MAO: 0.3, ENG: 0.2}, tirage=1)])
        code, sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        niveau = detail["bruit"]["groupe"]
        self.assertEqual((niveau["groupes_d_au_moins_deux_tables"], niveau["groupes_sans_couple_commun"]), (1, 1))
        self.assertEqual((niveau["total"]["observations"], niveau["total"]["couples_dans_une_seule_table"]), (0, 4))
        self.assertEqual(detail["verdict"]["groupe"]["verdict"], "indéterminé")
        self.assertIn("aucun couple d'ordres commun", detail["verdict"]["groupe"]["avertissements"][0])
        self.assertIn("1 groupe(s) d'au moins deux tables, mais aucun couple d'ordres commun", sortie)
        self.assertNotIn("ne compte deux tables", sortie)
        self.assertIn("4 couple(s) écarté(s)", sortie)

    def test_pas_de_paire_entre_deux_positions(self):
        # Même partie, même phase, deux puissances ; puis même puissance, deux phases : jamais une paire.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve(T1, VALEURS["T1"], puissance="FRANCE"), releve(T2, VALEURS["T2"], puissance="ENGLAND"),
            releve(T2, VALEURS["T2"], phase="F1901M")])
        code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(detail["lecture"]["positions"], 3)
        self.assertEqual(detail["paires"]["toutes"]["total"]["paires"], 0)
        self.assertEqual(detail["bruit"]["engagements"]["total"]["observations"], 0)

    def test_engagements_compares_sans_egard_a_leur_ordre(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve(T1, VALEURS["T1"], recherche="B", tirage=0, engagements=[BUR, MAO]),
            releve(T2, VALEURS["T2"], recherche="B", tirage=1, engagements=[MAO, BUR])])
        code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(detail["bruit"]["groupe"]["groupes"], 1)
        self.assertEqual(detail["bruit"]["groupe"]["total"]["observations"], 8)
        self.assertEqual(detail["paires"]["memes_engagements"]["total"]["paires"], 1)

    def test_portee_lue_dans_les_releves(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"], phase="S1901M"), releve(T1, VALEURS["T1"], phase="F1903M")])
        _code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(
            detail["portee"],
            "1 partie (9), 1901 à 1903 : mesuré sur une partie, ce qui ne fonde pas une statistique (exigence 2.10)")


class RelevesIllisibles(unittest.TestCase):
    """Un message clair sur la sortie d'erreur, le code 2, ni trace ni fichier de résultat."""

    def refuse(self, d, motif):
        code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, sortie, detail), (2, "", None))
        self.assertRegex(erreur, r"^bruit_valeurs : .*%s" % motif)
        self.assertEqual(erreur.count("\n"), 1)
        self.assertNotIn("Traceback", erreur)

    def test_dossier_sans_releve(self):
        self.refuse(Dossier(self), "aucun relevé m1_")

    def test_dossier_absent(self):
        d = Dossier(self)
        d.chemin = d.chemin / "absent"
        self.refuse(d, "n'est pas un dossier")

    def test_fichier_vide(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"])])
        d.ecrire("m1_9_b.jsonl", ["", "  "])
        self.refuse(d, r"m1_9_b\.jsonl : relevé vide")

    def test_ligne_qui_n_est_pas_du_json(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"]), '{"mesure": "M1", "phase": '])
        self.refuse(d, r"m1_9_a\.jsonl:2 : ligne qui n'est pas du JSON")

    def test_ligne_qui_n_est_pas_un_objet(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", ["[1, 2]"])
        self.refuse(d, r"m1_9_a\.jsonl:1 : ligne qui n'est pas un objet JSON")

    def test_releve_sans_ses_cles(self):
        tronque = releve(T1, VALEURS["T1"])
        del tronque["puissance"], tronque["recherche"]
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [tronque])
        self.refuse(d, r"m1_9_a\.jsonl:1 : relevé de recherche sans puissance, recherche")

    def test_valeur_qui_n_est_pas_un_nombre(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, dict(VALEURS["T1"], **{PIC: "0.3"}))])
        self.refuse(d, r"m1_9_a\.jsonl:1 : order_values")

    def test_ordre_qui_n_est_pas_une_chaine(self):
        tordu = releve(T1, VALEURS["T1"])
        tordu["entree"]["candidates"][0]["orders"] = [["A PAR - BUR"], MAO]
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [tordu])
        self.refuse(d, r"m1_9_a\.jsonl:1 : candidates porte une action qui n'est pas une liste d'ordres")

    def test_candidates_qui_n_est_pas_une_liste(self):
        tordu = releve(T1, VALEURS["T1"])
        tordu["entree"]["candidates"] = {"orders": [BUR]}
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [tordu])
        self.refuse(d, r"m1_9_a\.jsonl:1 : candidates n'est pas une liste d'actions")

    def test_entier_trop_grand_pour_un_flottant(self):
        ligne = json.dumps(releve(T1, VALEURS["T1"])).replace('"A PAR - PIC": 0.3', '"A PAR - PIC": 1' + "0" * 400)
        self.assertIn("0" * 400, ligne)
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [ligne])
        self.refuse(d, r"m1_9_a\.jsonl:1 : order_values")

    def test_json_trop_imbrique(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", ["[" * 100000 + "]" * 100000])
        self.refuse(d, r"m1_9_a\.jsonl:1 : ligne qui n'est pas ")

    def test_aucune_table_exportee(self):
        sans_entree = releve(T1, VALEURS["T1"])
        sans_entree["entree"] = None
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [sans_entree])
        self.refuse(d, "aucune table exportée")

    def test_recherche_sans_table_ecartee_et_nommee(self):
        sans_entree = releve(T1, VALEURS["T1"], tirage=2)
        sans_entree["entree"] = None
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"], tirage=0), releve(T1, VALEURS["T1"], tirage=1), sans_entree])
        code, sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(len(detail["lecture"]["recherches_sans_table"]), 1)
        self.assertIn("m1_9_a.jsonl:3", sortie)
        self.assertEqual(detail["bruit"]["groupe"]["total"]["tables"], 2)


class SortieParDefaut(unittest.TestCase):
    """Sans --sortie, le détail (de l'état de partie) ne s'écrit pas dans un dépôt hors de son amont/."""

    def depot(self, sous_dossier):
        d = Dossier(self)
        (d.chemin / ".git").mkdir()
        d.chemin = d.chemin / sous_dossier
        d.chemin.mkdir(parents=True, exist_ok=True)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"], tirage=0), releve(T1, VALEURS["T1"], tirage=1)])
        return d

    def test_refus_dans_le_depot(self):
        d = self.depot("tests/releves")
        code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, sortie, detail), (2, "", None))
        self.assertRegex(erreur, r"^bruit_valeurs : .*hors de amont/ : donner --sortie")
        self.assertEqual(list(d.chemin.glob("*.json")), [])

    def test_refus_a_la_racine_du_depot(self):
        self.assertEqual(self.depot(".").lancer()[0], 2)

    def test_amont_du_depot_accepte(self):
        code, _sortie, _erreur, detail = self.depot("amont/mesure/resultats").lancer()
        self.assertEqual(code, 0)
        self.assertIsNotNone(detail)

    def test_sortie_explicite_acceptee(self):
        d = self.depot("tests/releves")
        ailleurs = Dossier(self).chemin / "detail.json"
        code, sortie, _erreur, _detail = d.lancer("--sortie", str(ailleurs))
        self.assertEqual(code, 0)
        self.assertTrue(ailleurs.is_file())
        self.assertIn(str(ailleurs), sortie)
        self.assertEqual(list(d.chemin.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
