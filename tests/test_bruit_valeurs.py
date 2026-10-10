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


def releve(actions, order_values, recherche="A", tirage=0, engagements=(), phase="S1901M", puissance="FRANCE",
           search=None, prob=0.1, choix=None):
    """Une ligne de relevé, réduite aux clés que lit bruit_valeurs."""
    ligne = {
        "mesure": "M1", "game_id": 9, "phase": phase, "puissance": puissance, "tirage": tirage,
        "recherche": recherche, "engagements_retenus_par_le_moteur": list(engagements),
        "entree": {
            "order_values": order_values,
            "candidates": [{"orders": list(a), "value": v, "prob": prob} for a, v in actions],
        },
    }
    if search is not None:
        ligne["entree"]["search"] = search
    if choix is not None:
        ligne["engagement_choisi_au_tirage"] = choix
    return ligne


def deux_ordres(g, **cles):
    """Une table à une unité et deux ordres, G(BUR, PIC) = g."""
    return releve([((BUR,), 0.30), ((PIC,), round(0.30 + g, 5))], {BUR: 0.30, PIC: round(0.30 + g, 5)}, **cles)


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

    def test_bot_sans_sa_regle(self):
        # Un fichier qui a la marge et _order_loc, pas _reject_contradictions : le message nomme les trois.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        faux = Path(tmp.name) / "claude_dialogue_bot.py"
        faux.write_text("COMMITMENT_SWITCH_MARGIN = 0.05\n\n\ndef _order_loc(ordre):\n    return None\n", encoding="utf-8")
        with self.assertRaises(bruit.ErreurReleve) as refus:
            bruit.charger_bot(str(faux))
        self.assertIn("COMMITMENT_SWITCH_MARGIN, _order_loc ou _reject_contradictions illisible (AttributeError",
                      str(refus.exception))

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
              reunis=False, marge=0.05, nom="recherches_a", independance=(), porteurs=(0, 0, 0)):
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
                    "tables_sur_bruit": porteurs[0], "ordres_sur_bruit": porteurs[1], "positions_sur_bruit": porteurs[2],
                    "part_sur_bruit_des_observations_sans_gain": sur_bruit / sans_gain if sans_gain else None,
                }},
            },
        }
        return bruit.verdict(niveau, marge, nom, independance)

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

    def test_critere_lu_sur_les_recherches_a_seules(self):
        # Décision du mainteneur (2026-10-10) : seul le niveau « recherches_a » peut conclure ; le cumul
        # A + B et les recherches B, qui ne sont pas indépendantes de A, restent indicatifs.
        self.assertEqual(bruit.NIVEAU_DE_LA_SPECIFICATION, "recherches_a")
        self.assertEqual([nom for nom, _ in bruit.NIVEAUX], ["recherches_a", "recherches_b", "groupe", "engagements"])
        self.non_concluant("cumul des recherches A et B", nom="groupe")
        self.non_concluant("mise à jour incrémentale", nom="recherches_b")

    def test_porteurs_des_acceptations_sans_effet_sur_l_issue(self):
        # Trois acceptations sur bruit dans une table ou dans trois : le même « protège partiellement »,
        # les trois décomptes sont recopiés tels quels.
        une, trois = self.rendu(0.01, 0.02, 0.02, 3, porteurs=(1, 1, 1)), self.rendu(0.01, 0.02, 0.02, 3, porteurs=(3, 3, 3))
        self.assertEqual((une["verdict"], trois["verdict"]), ("protège partiellement", "protège partiellement"))
        self.assertEqual((une["tables_sur_bruit"], une["ordres_sur_bruit"], une["positions_sur_bruit"]), (1, 1, 1))
        self.assertEqual((trois["tables_sur_bruit"], trois["ordres_sur_bruit"], trois["positions_sur_bruit"]), (3, 3, 3))

    def test_independance_rejetee_ou_tables_jumelles(self):
        # Une mise en garde de la dispersion suffit à ne pas conclure, effectifs remplis.
        self.non_concluant("rejetée", independance=("indépendance des tirages d'un lancement rejetée",))
        sans_observation = dict(groupes=1, groupes_d_au_moins_deux_tables=0, total={"observations": 0})
        v = bruit.verdict(sans_observation, 0.05, independance=("tables jumelles",))
        self.assertEqual((v["verdict"], v["avertissements"][1:]), ("indéterminé", ["tables jumelles"]))


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
        # Critère rempli, mais 8 observations, 2 tables et 1 position : rien à conclure. Et deux tables
        # identiques d'un même fichier sont des tables jumelles : quatrième avertissement.
        verdict = detail["verdict"]["recherches_a"]
        self.assertEqual(
            (verdict["verdict"], verdict["lecture_indicative"], verdict["concluant"]),
            ("non concluant", "protège", False))
        self.assertEqual(len(verdict["avertissements"]), 4)
        self.assertIn("1 paire(s) de tables jumelles", verdict["avertissements"][3])
        self.assertEqual(detail["mises_en_garde"], verdict["avertissements"][3:])
        self.assertIn("  MISE EN GARDE : 1 paire(s) de tables jumelles", sortie)
        self.assertIn("  niveau « recherches_a » : NON CONCLUANT -- lecture indicative : le critère donnerait « protège »\n",
                      sortie)
        self.assertEqual(detail["verdict"]["engagements"]["verdict"], "non concluant")
        self.assertIn(
            "niveau « groupe » : NON CONCLUANT -- lecture indicative : le critère donnerait « protège »\n", sortie)
        self.assertNotRegex(sortie, r"niveau « \w+ » : (PROTÈGE|NE PROTÈGE)")
        self.assertIn("exigence 2.10", sortie)
        # Les trois compléments reportés sont faits : plus rien d'annoncé, chacun a sa clé.
        self.assertNotIn("Reporté", sortie)
        self.assertEqual(detail["reporte"], [])
        for cle in ("regle_entiere", "dispersion"):
            self.assertIn(cle, detail)
        self.assertIn("apparie", detail["effet_engagement"])

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
        self.assertEqual(len(detail["verdict"]["recherches_a"]["avertissements"]), 2)

    def test_porteurs_des_acceptations_sur_bruit(self):
        # Deux positions, cinq tables chacune, trois ordres pour PAR. FRANCE : BUR 0,30, PIC 0,30, GAS 0,30
        # dans quatre tables ; dans la cinquième BUR tombe à 0,20 -- G(BUR, PIC) = G(BUR, GAS) = 0,10 > marge
        # alors que la moyenne des quatre autres est 0 : 2 acceptations sur bruit, dans 1 table, pour 1 ordre E
        # (BUR), 1 position. ENGLAND : la même, et une seconde table où c'est PIC qui tombe à 0,20 --
        # G(PIC, BUR) = G(PIC, GAS) = 0,10, moyenne des autres (0 ; 0 ; 0 ; -0,10) / 4 < 0. La table où BUR
        # tombe garde G(BUR, GAS) = 0,10 sur bruit (les autres : 0), et G(BUR, PIC) = 0,10 contre
        # (0 ; 0 ; 0 ; -0,10) / 4 : sur bruit aussi. 4 acceptations, 2 tables, 2 couples (table, ordre E).
        # Total : 6 acceptations sur bruit, dans 3 tables, 3 ordres, 2 positions.
        def table(bur=0.30, pic=0.30, **cles):
            return releve([((BUR,), bur), ((PIC,), pic), ((GAS,), 0.30)], {BUR: bur, PIC: pic, GAS: 0.30}, **cles)

        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [table(tirage=i) for i in range(4)] + [table(bur=0.20, tirage=4)])
        d.ecrire("m1_9_b.jsonl", [table(tirage=i, puissance="ENGLAND") for i in range(3)] + [
            table(bur=0.20, tirage=3, puissance="ENGLAND"), table(pic=0.20, tirage=4, puissance="ENGLAND")])
        code, sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        niveau = detail["bruit"]["recherches_a"]

        def porteurs(bloc):
            m = bloc["par_marge"]["0.05"]
            return m["acceptations_sur_bruit"], m["tables_sur_bruit"], m["ordres_sur_bruit"], m["positions_sur_bruit"]

        self.assertEqual(porteurs(niveau["par_position"]["9 S1901M FRANCE"]), (2, 1, 1, 1))
        self.assertEqual(porteurs(niveau["par_position"]["9 S1901M ENGLAND"]), (4, 2, 2, 1))
        self.assertEqual(porteurs(niveau["total"]), (6, 3, 3, 2))
        # À la marge de 0,10, G = 0,10 ne la dépasse plus : rien, nulle part.
        m = niveau["total"]["par_marge"]["0.10"]
        self.assertEqual((m["acceptations_sur_bruit"], m["tables_sur_bruit"], m["ordres_sur_bruit"],
                          m["positions_sur_bruit"]), (0, 0, 0, 0))
        verdict = detail["verdict"]["recherches_a"]
        self.assertEqual((verdict["acceptations_sur_bruit"], verdict["tables_sur_bruit"], verdict["ordres_sur_bruit"],
                          verdict["positions_sur_bruit"]), (6, 3, 3, 2))
        self.assertIn(", 6 acceptation(s) sur bruit, dans 3 tables, 3 ordres, 2 positions (", sortie)
        self.assertIn("  les 6 acceptation(s) sur bruit sont dans 3 tables, 3 ordres, 2 positions (ordre : couple (table, "
                      "ordre E)).", sortie)

    def test_une_table_deux_ordres_et_une_acceptation_hors_bruit(self):
        # Trois unités, cinq tables. MAR : G(A MAR H, A MAR - SPA) = 0,20 dans les cinq tables -- cinq
        # acceptations, aucune sur bruit (la moyenne des autres est 0,20). PAR et BRE : tout à 0,30, sauf la
        # cinquième table où BUR et MAO tombent à 0,20 -- G(BUR, PIC) = G(MAO, ENG) = 0,10 contre 0 ailleurs.
        # 7 acceptations, dont 2 sur bruit : dans 1 table, pour 2 ordres E (BUR, MAO), 1 position.
        tient, spa = "A MAR H", "A MAR - SPA"

        def table(tirage, bas=0.30):
            valeurs = {BUR: bas, PIC: 0.30, MAO: bas, ENG: 0.30, tient: 0.30, spa: 0.50}
            return releve([((ordre,), v) for ordre, v in valeurs.items()], valeurs, tirage=tirage)

        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [table(i) for i in range(4)] + [table(4, bas=0.20)])
        _code, sortie, _erreur, detail = d.lancer()
        m = detail["bruit"]["recherches_a"]["total"]["par_marge"]["0.05"]
        self.assertEqual((m["acceptations"], m["acceptations_sur_bruit"]), (7, 2))
        self.assertEqual((m["tables_sur_bruit"], m["ordres_sur_bruit"], m["positions_sur_bruit"]), (1, 2, 1))
        verdict = detail["verdict"]["recherches_a"]
        self.assertEqual((verdict["acceptations_sur_bruit"], verdict["tables_sur_bruit"], verdict["ordres_sur_bruit"],
                          verdict["positions_sur_bruit"]), (2, 1, 2, 1))
        self.assertIn(", 2 acceptation(s) sur bruit, dans 1 table, 2 ordres, 1 position (", sortie)
        self.assertIn("  les 2 acceptation(s) sur bruit sont dans 1 table, 2 ordres, 1 position (", sortie)

    def test_porteurs_au_singulier(self):
        # La seule position FRANCE du cas précédent : « dans 1 table, 1 ordre, 1 position ».
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            releve([((BUR,), bur), ((PIC,), 0.30), ((GAS,), 0.30)], {BUR: bur, PIC: 0.30, GAS: 0.30}, tirage=i)
            for i, bur in enumerate((0.30, 0.30, 0.30, 0.30, 0.20))])
        _code, sortie, _erreur, detail = d.lancer()
        self.assertEqual(detail["verdict"]["recherches_a"]["acceptations_sur_bruit"], 2)
        self.assertIn(", 2 acceptation(s) sur bruit, dans 1 table, 1 ordre, 1 position (", sortie)
        # Sans acceptation sur bruit, rien à situer : la ligne du verdict s'en tient au décompte.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(g, tirage=i) for i, g in enumerate((0.0, 0.001, 0.002))])
        _code, sortie, _erreur, _detail = d.lancer()
        self.assertIn(", 0 acceptation(s) sur bruit (0.0 % des ", sortie)
        self.assertNotIn("acceptation(s) sur bruit sont dans", sortie)

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


# Cas du complément 1 (spécification d'expert-cicero, § 1.6) : une unité, lambda nul -- le score est la
# valeur, donc l'action de tête est celle de plus grande valeur parmi celles qui tiennent les promesses
# renforcées ; ici la plus grande valeur tout court. order_values se déduit des actions.
#   T1 : PIC 0,40  BUR 0,30            T2 : PIC 0,33  BUR 0,30
#   T3 : BUR 0,30                      T4 : GAS 0,90  PIC 0,40  BUR 0,30
LAMBDA_NUL = {"lambda": 0.0, "boost": 3.0, "max_prob": 0.4}
TABLES_REGLE = (
    [((PIC,), 0.40), ((BUR,), 0.30)], [((PIC,), 0.33), ((BUR,), 0.30)], [((BUR,), 0.30)],
    [((GAS,), 0.90), ((PIC,), 0.40), ((BUR,), 0.30)],
)


def table_regle(actions, **cles):
    return releve(actions, {a[0]: v for a, v in actions}, search=LAMBDA_NUL, prob=0.25, **cles)


class RegleChargee(unittest.TestCase):
    """T0 : la vraie _reject_contradictions, avec le vrai engine_head_action, contrôlée par un témoin."""

    def test_vraie_fonction_de_tete(self):
        module, chemin = bruit.charger_bot()
        self.assertEqual(chemin, BOT)
        self.assertNotIsInstance(module.engine_head_action, mock.Mock)
        self.assertEqual(module.engine_head_action.__name__, "engine_head_action")
        entree = bruit.TEMOIN["entree"]
        self.assertEqual(bruit.issue_de_la_regle(module._reject_contradictions, BUR, PIC, (), entree), ("remplace", 0.1))

    @unittest.skipIf(Path("/opt/cicero/fairdiplomacy").is_dir(), "dans l'image, engine_head_action n'est pas une doublure")
    def test_temoin_sous_doublure(self):
        # engine_head_action laissé en doublure : la règle rend not_played sur le témoin, le chargement lève.
        with mock.patch.object(bruit, "brancher_tete", lambda module, bot: None):
            with self.assertRaises(bruit.ErreurReleve) as refus:
                bruit.charger_regle()
        self.assertIn("règle mal chargée", str(refus.exception))
        self.assertIn("« not_played » au lieu de « remplace »", str(refus.exception))
        # Et le script s'arrête sur ce message, code 2, sans rien écrire.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [releve(T1, VALEURS["T1"])])
        with mock.patch.object(bruit, "brancher_tete", lambda module, bot: None):
            code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, sortie, detail), (2, "", None))
        self.assertRegex(erreur, r"^bruit_valeurs : .*règle mal chargée")

    def test_fichier_et_entree_gardes_par_table(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [table_regle(TABLES_REGLE[0], tirage=3, choix=0)])
        _marge, order_loc, _chemin = bruit.charger_regle()
        tables, _lecture = bruit.lire_releves(d.chemin, order_loc)
        self.assertEqual((tables[0]["fichier"], tables[0]["tirage"], tables[0]["tirage_du_choix"]), ("m1_9_a.jsonl", 3, 0))
        self.assertEqual(sorted(tables[0]["entree"]), ["candidates", "order_values", "plans", "search"])
        self.assertEqual(tables[0]["entree"]["order_values"], {PIC: 0.40, BUR: 0.30})
        self.assertEqual((tables[0]["entree"]["search"], tables[0]["entree"]["plans"]), (LAMBDA_NUL, None))

    def test_retour_inattendu_de_la_regle(self):
        entree = bruit.TEMOIN["entree"]

        def rend(retour):
            return lambda *a, **k: retour

        for retour, motif in (
            (([], [(PIC, BUR, "undeclared", None)], [], [], []), "motif inattendu « undeclared »"),
            (([], [(PIC, BUR, "below_margin", 0.01)], [], [], [(BUR, "restated")]), "retour inattendu"),
            (([PIC], [], [], [], []), "retour inattendu"),
            (([], [], [], [(BUR, PIC)], []), "retour inattendu"),
            (([], []), "ValueError"),
        ):
            with self.assertRaises(bruit.ErreurReleve) as refus:
                bruit.issue_de_la_regle(rend(retour), BUR, PIC, (), entree)
            self.assertIn(motif, str(refus.exception))


class RegleEntiere(unittest.TestCase):
    """Complément 1 : les deux groupes du cas fabriqué, sur la vraie fonction."""

    def lancer(self, recherche, engagements):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            table_regle(actions, recherche=recherche, engagements=engagements, tirage=i)
            for i, actions in enumerate(TABLES_REGLE)])
        code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, erreur), (0, ""))
        return sortie, detail["regle_entiere"]

    def issues(self, classe):
        return {(x["ancien"], x["nouveau"]): x["issues"] for x in classe["scenarios"]}

    def test_groupe_b_table_a_jour(self):
        sortie, regle = self.lancer("B", [BUR])
        # BUR est engagé : PIC et GAS comme promesse rompue seraient une seconde parole sur PAR --
        # 4 états impossibles (PIC -> BUR, PIC -> GAS, GAS -> BUR, GAS -> PIC), 2 scénarios à jour.
        self.assertEqual(regle["etats_impossibles_ecartes"], 4)
        self.assertEqual(regle["classes"]["table_anterieure"]["total"]["scenarios"], 0)
        classe = regle["classes"]["table_a_jour"]
        # BUR -> PIC : gain 0,10 > marge et PIC en tête (T1) ; 0,03 sous la marge (T2) ; PIC absent (T3) ;
        # gain 0,10 mais GAS en tête (T4). BUR -> GAS : GAS n'est que dans T4, gain 0,60.
        self.assertEqual(self.issues(classe), {
            (BUR, PIC): ["remplace", "below_margin", "unknown_value", "not_played"],
            (BUR, GAS): ["unknown_value", "unknown_value", "unknown_value", "remplace"],
        })
        par_couple = {(x["ancien"], x["nouveau"]): x for x in classe["scenarios"]}
        self.assertEqual(par_couple[(BUR, PIC)]["gains"], [0.1, 0.03, None, 0.1])
        self.assertEqual(par_couple[(BUR, GAS)]["gains"], [None, None, None, 0.6])
        # Sans marge : la condition (e) seule.
        self.assertEqual(par_couple[(BUR, PIC)]["sans_marge"], ["remplace", "remplace", "unknown_value", "not_played"])
        self.assertEqual(par_couple[(BUR, GAS)]["sans_marge"], ["unknown_value"] * 3 + ["remplace"])
        total = classe["total"]
        self.assertEqual((total["scenarios"], total["scenarios_disputes"]), (2, 2))
        self.assertEqual((total["scenarios_a_decision_non_unanime"], total["scenarios_a_motif_non_unanime"]), (2, 2))
        self.assertEqual(total["part_scenarios_a_decision_non_unanime"], 1.0)
        # Désaccords : k (n - k) = 1 x 3 par scénario, sur 6 paires chacun.
        self.assertEqual(total["desaccord"]["tous"], {"desaccords": 6, "paires": 12, "taux": 0.5})
        self.assertEqual(total["desaccord"]["disputes"], total["desaccord"]["tous"])
        self.assertEqual(total["attribution"], {"unknown_value": 4, "below_margin": 1, "not_played": 1})
        self.assertEqual(sum(total["attribution"].values()), total["desaccord"]["tous"]["desaccords"])
        # Instabilités propres. Valeur connue : u = 3 puis 1 -> 3 x 1 + 1 x 3 = 6 sur 12. Marge : sur les
        # 3 tables connues de BUR -> PIC, 2 hors below_margin -> 2 x 1 sur 3 paires ; BUR -> GAS, u = 1 : 0 sur 0.
        # Condition (e) : 2 « remplace » sans marge sur 3 connues -> 2 sur 3.
        propre = total["instabilite_propre"]
        self.assertEqual((propre["unknown_value"]["desaccords"], propre["unknown_value"]["paires"]), (6, 12))
        self.assertEqual((propre["marge"]["desaccords"], propre["marge"]["paires"]), (2, 3))
        self.assertEqual((propre["condition_e"]["desaccords"], propre["condition_e"]["paires"]), (2, 3))
        self.assertEqual(total["issues"], {"remplace": 2, "unknown_value": 4, "below_margin": 1, "not_played": 1})
        # Sur bruit : T1 remplace BUR -> PIC, les autres tables donnent G = 0,03 et 0,10 -> non ;
        # T4 remplace BUR -> GAS, aucune autre table ne porte le couple : compté à part, pas sur bruit.
        self.assertEqual((total["acceptations_sur_bruit_effectives"], total["acceptations_sans_autre_table"]), (0, 1))
        self.assertNotIn("dont_sans_autre_table", total)
        self.assertEqual((par_couple[(BUR, GAS)]["sur_bruit"], par_couple[(BUR, GAS)]["sans_autre_table"]),
                         ([False] * 4, [False, False, False, True]))
        self.assertEqual(par_couple[(BUR, PIC)]["sans_autre_table"], [False] * 4)
        self.assertIn("ne porte le couple : 1, compté à part", sortie)
        self.assertRegex(sortie, r"\n    total +2 +2 +2 +2 +6/12 \(50\.0 %\) +6/12 \(50\.0 %\) +2 +0 +1\n")
        # Balayage. BUR -> PIC : à 0,02, T2 (0,03) remplace aussi : k = 2, 2 x 2 = 4 ; à 0,03 et au-delà T2
        # est sous la marge : 3 ; à 0,10, 0,10 ne dépasse plus : k = 0. BUR -> GAS : 3 partout.
        self.assertEqual(
            {m: (b["scenarios_disputes"], b["desaccord"]["tous"]["desaccords"], b["desaccord"]["disputes"]["paires"])
             for m, b in total["par_marge"].items()},
            {"0.02": (2, 7, 12), "0.03": (2, 6, 12), "0.05": (2, 6, 12), "0.08": (2, 6, 12), "0.10": (1, 3, 6)})
        self.assertEqual(classe["par_groupe"], {"9 S1901M FRANCE | A PAR - BUR | B": total})
        self.assertEqual(classe["par_position"], {"9 S1901M FRANCE": total})
        self.assertIn("Règle entière : _reject_contradictions rejouée", sortie)
        self.assertIn("6/12 (50.0 %)", sortie)
        self.assertIn("unknown_value 4, below_margin 1, not_played 1", sortie)

    def test_groupe_a_table_anterieure(self):
        _sortie, regle = self.lancer("A", [])
        self.assertEqual(regle["etats_impossibles_ecartes"], 0)
        self.assertEqual(regle["classes"]["table_a_jour"]["total"]["scenarios"], 0)
        classe = regle["classes"]["table_anterieure"]
        inconnu = ["unknown_value"] * 3
        self.assertEqual(self.issues(classe), {
            (BUR, PIC): ["remplace", "below_margin", "unknown_value", "not_played"],
            (BUR, GAS): inconnu + ["remplace"],
            (PIC, BUR): ["below_margin", "below_margin", "unknown_value", "below_margin"],
            (PIC, GAS): inconnu + ["remplace"],
            (GAS, BUR): inconnu + ["below_margin"],
            (GAS, PIC): inconnu + ["below_margin"],
        })
        total = classe["total"]
        self.assertEqual((total["scenarios"], total["scenarios_a_decision_non_unanime"]), (6, 3))
        self.assertEqual(total["desaccord"]["tous"], {"desaccords": 9, "paires": 36, "taux": 0.25})
        self.assertEqual(total["desaccord"]["disputes"], {"desaccords": 9, "paires": 18, "taux": 0.5})
        self.assertEqual(total["attribution"], {"unknown_value": 7, "below_margin": 1, "not_played": 1})
        propre = total["instabilite_propre"]
        self.assertEqual(
            [(propre[c]["desaccords"], propre[c]["paires"]) for c in ("unknown_value", "marge", "condition_e")],
            [(18, 36), (2, 6), (2, 6)])
        # BUR -> GAS et PIC -> GAS, remplacés dans T4, seule table à porter GAS : deux acceptations sans
        # autre table, aucune sur bruit.
        self.assertEqual((total["acceptations_sur_bruit_effectives"], total["acceptations_sans_autre_table"]), (0, 2))

    def test_sur_bruit_quand_la_moyenne_des_autres_tables_est_nulle(self):
        # Deux tables : PIC 0,40 / BUR 0,30 (gain 0,10, PIC en tête : remplace) et PIC 0,30 / BUR 0,30
        # (G = 0, sous la marge). La moyenne des autres tables vaut exactement 0 : borne comprise, sur bruit.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            table_regle([((PIC,), 0.40), ((BUR,), 0.30)], recherche="B", engagements=[BUR], tirage=0),
            table_regle([((PIC,), 0.30), ((BUR,), 0.30)], recherche="B", engagements=[BUR], tirage=1)])
        _code, _sortie, _erreur, detail = d.lancer()
        classe = detail["regle_entiere"]["classes"]["table_a_jour"]
        self.assertEqual([(x["issues"], x["gains"], x["sur_bruit"]) for x in classe["scenarios"]],
                         [(["remplace", "below_margin"], [0.1, 0.0], [True, False])])
        total = classe["total"]
        self.assertEqual((total["acceptations_sur_bruit_effectives"], total["acceptations_sans_autre_table"]), (1, 0))

    def test_sur_bruit_et_sans_autre_table_ne_s_additionnent_pas(self):
        # Trois tables, engagement BUR. BUR -> PIC : remplacé dans T1 (0,10), G = -0,05 et -0,01 ailleurs :
        # moyenne -0,03 <= 0, sur bruit. BUR -> GAS : remplacé dans T3 (0,60, GAS en tête), GAS nulle part
        # ailleurs : sans autre table. Un de chaque, jamais deux du même.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [
            table_regle([((PIC,), 0.40), ((BUR,), 0.30)], recherche="B", engagements=[BUR], tirage=0),
            table_regle([((BUR,), 0.30), ((PIC,), 0.25)], recherche="B", engagements=[BUR], tirage=1),
            table_regle([((GAS,), 0.90), ((BUR,), 0.30), ((PIC,), 0.29)], recherche="B", engagements=[BUR], tirage=2)])
        _code, _sortie, _erreur, detail = d.lancer()
        classe = detail["regle_entiere"]["classes"]["table_a_jour"]
        par_couple = {(x["ancien"], x["nouveau"]): x for x in classe["scenarios"]}
        self.assertEqual((par_couple[(BUR, PIC)]["sur_bruit"], par_couple[(BUR, PIC)]["sans_autre_table"]),
                         ([True, False, False], [False] * 3))
        self.assertEqual((par_couple[(BUR, GAS)]["sur_bruit"], par_couple[(BUR, GAS)]["sans_autre_table"]),
                         ([False] * 3, [False, False, True]))
        total = classe["total"]
        self.assertEqual((total["acceptations_sur_bruit_effectives"], total["acceptations_sans_autre_table"]), (1, 1))

    def test_groupe_d_une_seule_table_non_rejoue(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [table_regle(TABLES_REGLE[0])])
        _code, _sortie, _erreur, detail = d.lancer()
        regle = detail["regle_entiere"]
        self.assertEqual(regle["groupes_d_une_seule_table_non_rejoues"], 1)
        self.assertEqual([regle["classes"][c]["total"]["scenarios"] for c, _t, _d in bruit.CLASSES_REGLE], [0, 0])

    def test_regle_qui_change_arrete_le_script(self):
        # Un retour que le script ne connaît pas, sur une table : message, code 2, pas de résultat.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [table_regle(a, tirage=i) for i, a in enumerate(TABLES_REGLE[:2])])
        with mock.patch.object(bruit, "MOTIFS", ("unknown_value", "not_played")):
            code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, sortie, detail), (2, "", None))
        self.assertRegex(erreur, r"^bruit_valeurs : .*motif inattendu « below_margin »")


class Student(unittest.TestCase):
    def test_table_recalculee_par_integration(self):
        # La table codée, contre la dichotomie sur l'intégrale de la densité, et contre les valeurs
        # publiées à 3 décimales (1, 2, 4, 10 et 20 degrés de liberté).
        self.assertEqual(len(bruit.STUDENT_975), 20)
        for ddl, code in enumerate(bruit.STUDENT_975, 1):
            self.assertAlmostEqual(bruit.student_quantile(0.975, ddl), code, places=5)
        publiees = {1: 12.706, 2: 4.303, 4: 2.776, 10: 2.228, 20: 2.086}
        for ddl, valeur in publiees.items():
            self.assertEqual(round(bruit.STUDENT_975[ddl - 1], 3), valeur)
        self.assertEqual(bruit.quantile_975(20), (2.085963, False))
        self.assertEqual(bruit.quantile_975(21), (1.96, True))
        self.assertAlmostEqual(bruit.student_cdf(-1.0, 1), 0.25, places=9)  # loi de Cauchy : 1/2 - atan(1) / pi

    def test_puissance_indicative(self):
        # Les quatre chiffres de la spécification (§ 3.4), deux fichiers de 5 tables.
        self.assertEqual(bruit.puissance_indicative([5, 5]), {"0.2": 0.16, "0.5": 0.37, "0.8": 0.63, "0.9": 0.74})
        self.assertIsNone(bruit.puissance_indicative([5, 4]))
        self.assertIsNone(bruit.puissance_indicative([4, 4, 4]))


class EffetApparie(unittest.TestCase):
    """Complément 2 : l'effet de la recherche B, apparié par tirage."""

    def lancer(self, g_a, g_b, choix=None):
        d = Dossier(self)
        lignes = []
        for i, (a, b) in enumerate(zip(g_a, g_b)):
            lignes.append(releve([((BUR,), 0.50), ((PIC,), round(0.50 + a, 5))],
                                 {BUR: 0.50, PIC: round(0.50 + a, 5)}, tirage=i))
            lignes.append(releve([((BUR,), 0.50), ((PIC,), round(0.50 + b, 5))],
                                 {BUR: 0.50, PIC: round(0.50 + b, 5)}, tirage=i, recherche="B", engagements=[BUR],
                                 choix=choix))
        d.ecrire("m1_9_a.jsonl", lignes)
        code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, erreur), (0, ""))
        return sortie, detail["effet_engagement"]

    def test_cas_fabrique(self):
        # G_A(BUR, PIC) = -0,02 ; -0,03 ; -0,01 et G_B = -0,05 ; -0,07 ; -0,03 :
        #   delta = -0,03 ; -0,04 ; -0,02 -> effet -0,03, s = 0,01, ET = 0,01 / racine(3) = 0,0057735,
        #   t = -5,196, IC = -0,03 -/+ 4,302653 x 0,0057735 = [-0,054841 ; -0,005159].
        #   Non apparié : s_A = 0,01, s_B = 0,02 -> racine((0,0001 + 0,0004) / 3) = 0,012910, t = -2,324.
        #   G_B = 2 G_A - 0,01 : corrélation 1.
        sortie, effet = self.lancer((-0.02, -0.03, -0.01), (-0.05, -0.07, -0.03))
        apparie = effet["apparie"]
        self.assertEqual(apparie["libelle"], "effet de la recherche B (message, mise à jour incrémentale, engagement)")
        groupe = apparie["par_groupe"][0]
        self.assertEqual((groupe["groupe"], groupe["tirages_apparies"], groupe["tables_sans_tirage_apparie"]),
                         ("9 S1901M FRANCE | A PAR - BUR | B", 3, 0))
        # Un seul couple principal : celui qui part de l'ordre engagé. (PIC, BUR) est un « autre ».
        self.assertEqual([(c["ancien"], c["nouveau"]) for c in groupe["principaux"]], [(BUR, PIC)])
        self.assertEqual(groupe["autres"]["couples"], 1)
        c = groupe["principaux"][0]
        self.assertEqual(c["n"], 3)
        for cle, attendu in (("effet", -0.03), ("ecart_type", 0.01), ("erreur_type", 0.0057735), ("t", -5.196152),
                             ("erreur_type_non_appariee", 0.012910), ("t_non_apparie", -2.323790),
                             ("correlation_a_b", 1.0)):
            self.assertAlmostEqual(c[cle], attendu, delta=1e-6, msg=cle)
        self.assertAlmostEqual(c["ic95"][0], -0.054841, delta=1e-6)
        self.assertAlmostEqual(c["ic95"][1], -0.005159, delta=1e-6)
        self.assertEqual((c["quantile"], c["quantile_approche"]), (4.302653, False))
        # L'intervalle exclut 0, et déborde de -0,025 : distinguable, pas négligeable devant 0,05.
        self.assertEqual(c["lecture"], "distinguable du bruit")
        self.assertEqual(apparie["lectures_des_couples_principaux"]["distinguable du bruit"], 1)
        # Une seule position : pas d'erreur type entre positions.
        self.assertEqual((apparie["entre_positions"]["positions"], apparie["entre_positions"]["effet"]), (1, -0.03))
        self.assertIsNone(apparie["entre_positions"]["ic95"])
        # L'estimateur non apparié reste sous ses clés : moyenne de G_B - moyenne de G_A = -0,03 pour (BUR, PIC),
        # +0,03 pour (PIC, BUR), le seul tourné vers l'ordre engagé.
        self.assertEqual(effet["total"]["effet_moyen_vers_l_ordre_engage"], 0.03)
        self.assertEqual(effet["par_groupe"][0]["tables_avec"], 3)
        self.assertIn("Effet de la recherche B (message, mise à jour incrémentale, engagement), apparié par tirage", sortie)
        self.assertIn("[-0.05484 ; -0.00516]", sortie)
        self.assertNotIn("Effet de l'engagement", sortie)

    def test_moins_de_trois_tirages(self):
        _sortie, effet = self.lancer((-0.02, -0.03), (-0.05, -0.07))
        c = effet["apparie"]["par_groupe"][0]["principaux"][0]
        self.assertEqual((c["n"], c["effet"], c["lecture"]), (2, -0.035, "sans erreur type"))
        self.assertEqual((c["erreur_type"], c["t"], c["ic95"], c["erreur_type_non_appariee"]), (None, None, None, None))
        # Les deux couples du groupe, le principal et l'autre.
        self.assertEqual(effet["apparie"]["couples_sans_erreur_type"], 2)

    def test_dispersion_nulle_sans_division(self):
        # Trois delta égaux à -0,03 : s = 0 exactement, pas de t ; l'effet n'est pas nul -> distinguable.
        _sortie, effet = self.lancer((-0.02, -0.03, -0.01), (-0.05, -0.06, -0.04))
        c = effet["apparie"]["par_groupe"][0]["principaux"][0]
        self.assertEqual((c["effet"], c["ecart_type"], c["erreur_type"], c["t"]), (-0.03, 0.0, 0.0, None))
        self.assertEqual((c["ic95"], c["lecture"]), ([-0.03, -0.03], "distinguable du bruit"))
        # Trois delta nuls : « nul ».
        _sortie, effet = self.lancer((-0.02, -0.03, -0.01), (-0.02, -0.03, -0.01))
        c = effet["apparie"]["par_groupe"][0]["principaux"][0]
        self.assertEqual((c["effet"], c["erreur_type"], c["t"], c["lecture"]), (0.0, 0.0, None, "nul"))

    def test_negligeable_devant_la_marge(self):
        # delta = -0,001 ; 0,000 ; +0,001 : effet 0, s = 0,001, ET = 0,00057735, IC = +/- 0,002484 :
        # contient 0 et tient dans +/- 0,025.
        _sortie, effet = self.lancer((0.0, 0.0, 0.0), (-0.001, 0.0, 0.001))
        c = effet["apparie"]["par_groupe"][0]["principaux"][0]
        self.assertAlmostEqual(c["ic95"][1], 0.002484, delta=1e-6)
        self.assertEqual(c["lecture"], "négligeable devant la marge")
        # delta = -0,03 ; 0 ; +0,03 : IC = +/- 4,302653 x 0,03 / racine(3) = +/- 0,074524 : non conclusif.
        _sortie, effet = self.lancer((0.0, 0.0, 0.0), (-0.03, 0.0, 0.03))
        self.assertEqual(effet["apparie"]["par_groupe"][0]["principaux"][0]["lecture"], "non conclusif")

    def test_sensibilite_sans_le_tirage_du_choix(self):
        # L'engagement a été choisi sur la table A du tirage 0. Avec lui, delta = -0,06 ; -0,04 ; -0,02 ; -0,02 :
        # -0,035 sur 4 tirages ; sans lui, -0,04 ; -0,02 ; -0,02 : -0,08 / 3 sur 3 tirages.
        _sortie, effet = self.lancer((-0.02, -0.03, -0.01, -0.01), (-0.08, -0.07, -0.03, -0.03), choix=0)
        apparie = effet["apparie"]
        self.assertAlmostEqual(apparie["entre_positions"]["effet"], -0.035)
        sans = apparie["sensibilite_sans_le_tirage_du_choix"]
        self.assertEqual((sans["tirages_du_choix_ecartes"], sans["positions"]), (1, 1))
        self.assertAlmostEqual(sans["effet"], -0.08 / 3)
        self.assertEqual((sans["couples_principaux_ecartes"], sans["positions_sans_couple_retenu"]), (0, 0))

    def test_sensibilite_a_moins_de_trois_tirages_restants(self):
        # Trois tirages dont celui du choix : il n'en reste que deux, le couple principal n'a plus d'erreur
        # type et n'entre plus dans la synthèse -- la position n'a aucun couple retenu, et c'est dit.
        sortie, effet = self.lancer((-0.02, -0.03, -0.01), (-0.08, -0.07, -0.03), choix=0)
        apparie = effet["apparie"]
        self.assertAlmostEqual(apparie["entre_positions"]["effet"], -0.04)  # (-0,06 - 0,04 - 0,02) / 3
        self.assertEqual((apparie["entre_positions"]["couples_principaux_ecartes"],
                          apparie["entre_positions"]["positions_sans_couple_retenu"]), (0, 0))
        sans = apparie["sensibilite_sans_le_tirage_du_choix"]
        self.assertEqual((sans["tirages_du_choix_ecartes"], sans["positions"], sans["effet"], sans["par_position"]),
                         (1, 0, None, {}))
        self.assertEqual((sans["couples_principaux_ecartes"], sans["positions_sans_couple_retenu"]), (1, 1))
        self.assertIn("1 couple(s) principal(aux) écarté(s), estimé(s) sur moins de 3 tirages ; 1 position(s) sans aucun "
                      "couple retenu", sortie)

    def test_synthese_sur_les_couples_d_au_moins_trois_tirages(self):
        # Cinq tirages, engagement BUR. (BUR, PIC) est dans les dix tables : delta = -0,01 cinq fois. (BUR, GAS)
        # n'est que dans le tirage 0, en A (G = 0,10) et en B (G = 0,30) : delta = +0,20 sur un seul tirage.
        # La moyenne de la position est celle du premier couple seul, -0,01 ; avec les deux, elle vaudrait +0,095.
        d = Dossier(self)
        lignes = []
        for i in range(5):
            for recherche, pic, gas in (("A", 0.50, 0.60), ("B", 0.49, 0.80)):
                actions = [((BUR,), 0.50), ((PIC,), pic)] + ([((GAS,), gas)] if i == 0 else [])
                lignes.append(releve(actions, {a[0]: v for a, v in actions}, tirage=i, recherche=recherche,
                                     engagements=[BUR] if recherche == "B" else []))
        d.ecrire("m1_9_a.jsonl", lignes)
        _code, sortie, _erreur, detail = d.lancer()
        apparie = detail["effet_engagement"]["apparie"]
        self.assertEqual([(c["nouveau"], c["n"], c["effet"]) for c in apparie["par_groupe"][0]["principaux"]],
                         [(GAS, 1, 0.2), (PIC, 5, -0.01)])
        synthese = apparie["entre_positions"]
        self.assertEqual((synthese["positions"], synthese["effet"]), (1, -0.01))
        self.assertEqual((synthese["couples_principaux_ecartes"], synthese["positions_sans_couple_retenu"]), (1, 0))
        self.assertNotIn("couples_principaux_du_seul_tirage_du_choix", synthese)
        self.assertEqual(synthese["par_position"], {"9 S1901M FRANCE": {
            "couples_principaux": 1, "couples_principaux_ecartes": 1, "effet": -0.01}})
        self.assertEqual(synthese["tirages_min_par_couple"], bruit.MIN_TIRAGES_ERREUR_TYPE)
        self.assertIn("1 couple(s) principal(aux) écarté(s), estimé(s) sur moins de 3 tirages ; 0 position(s) sans aucun "
                      "couple retenu", sortie)

    def test_couple_du_seul_tirage_du_choix(self):
        # Le même cas, l'engagement ayant été choisi au tirage 0, le seul à porter GAS. Sans ce tirage,
        # (BUR, GAS) n'a plus aucun tirage : il n'est pas « écarté pour moins de 3 tirages », il est sorti avec
        # le tirage, et compté à part. (BUR, PIC) garde 4 tirages : -0,01.
        d = Dossier(self)
        lignes = []
        for i in range(5):
            for recherche, pic, gas in (("A", 0.50, 0.60), ("B", 0.49, 0.80)):
                actions = [((BUR,), 0.50), ((PIC,), pic)] + ([((GAS,), gas)] if i == 0 else [])
                lignes.append(releve(actions, {a[0]: v for a, v in actions}, tirage=i, recherche=recherche,
                                     engagements=[BUR] if recherche == "B" else [], choix=0 if recherche == "B" else None))
        d.ecrire("m1_9_a.jsonl", lignes)
        _code, sortie, _erreur, detail = d.lancer()
        apparie = detail["effet_engagement"]["apparie"]
        self.assertEqual(apparie["entre_positions"]["couples_principaux_ecartes"], 1)
        sans = apparie["sensibilite_sans_le_tirage_du_choix"]
        self.assertEqual((sans["tirages_du_choix_ecartes"], sans["positions"], sans["effet"]), (1, 1, -0.01))
        self.assertEqual((sans["couples_principaux_ecartes"], sans["couples_principaux_du_seul_tirage_du_choix"]), (0, 1))
        self.assertIn("0 position(s) sans aucun couple retenu ; 1 couple(s) principal(aux) du seul tirage du choix, "
                      "sorti(s) avec lui", sortie)

    def test_synthese_entre_positions(self):
        # Trois positions, cinq tirages chacune. ENGLAND : un couple principal, effet 0,01. FRANCE : deux,
        # 0,02 et 0,04 -> moyenne 0,03 (leur somme serait 0,06). GERMANY : un, 0,05.
        #   moyennes 0,01 ; 0,03 ; 0,05 -> moyenne 0,03, s = racine((0,02^2 + 0 + 0,02^2) / 2) = 0,02,
        #   ET = 0,02 / racine(3) = 0,0115470, t = 2,598076,
        #   IC = 0,03 -/+ 4,302653 x 0,0115470 = [-0,019683 ; 0,079683].
        def groupe(position, *effets):
            return {"position": position, "principaux": [{"effet": e, "n": 5} for e in effets]}

        synthese = bruit._entre_positions([
            groupe("9 S1901M ENGLAND", 0.01), groupe("9 S1901M FRANCE", 0.02, 0.04), groupe("9 S1901M GERMANY", 0.05)])
        self.assertEqual({q: (x["couples_principaux"], x["effet"]) for q, x in synthese["par_position"].items()},
                         {"9 S1901M ENGLAND": (1, 0.01), "9 S1901M FRANCE": (2, 0.03), "9 S1901M GERMANY": (1, 0.05)})
        self.assertEqual((synthese["positions"], synthese["effet"], synthese["quantile"]), (3, 0.03, 4.302653))
        for cle, attendu in (("ecart_type", 0.02), ("erreur_type", 0.0115470), ("t", 2.598076)):
            self.assertAlmostEqual(synthese[cle], attendu, delta=1e-6, msg=cle)
        self.assertAlmostEqual(synthese["ic95"][0], -0.019683, delta=1e-6)
        self.assertAlmostEqual(synthese["ic95"][1], 0.079683, delta=1e-6)
        self.assertEqual((synthese["couples_principaux_ecartes"], synthese["positions_sans_couple_retenu"]), (0, 0))

    def test_table_sans_tirage_apparie(self):
        # Une table B sans recherche A de même tirage dans le même fichier n'entre pas dans l'estimateur.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(-0.02, tirage=0)])
        d.ecrire("m1_9_b.jsonl", [deux_ordres(-0.05, tirage=0, recherche="B", engagements=[BUR])])
        _code, _sortie, _erreur, detail = d.lancer()
        groupe = detail["effet_engagement"]["apparie"]["par_groupe"][0]
        self.assertEqual((groupe["tirages_apparies"], groupe["tables_sans_tirage_apparie"], groupe["principaux"]), (0, 1, []))
        self.assertEqual(detail["effet_engagement"]["total"]["groupes"], 1)  # le non apparié, lui, les réunit


class Dispersion(unittest.TestCase):
    """Complément 3 : dispersion dans un fichier et entre fichiers, test par permutation exacte."""

    def lancer(self, fichier_1, fichier_2, **cles):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(g, tirage=i, **cles) for i, g in enumerate(fichier_1)])
        d.ecrire("m1_9_b.jsonl", [deux_ordres(g, tirage=i, **cles) for i, g in enumerate(fichier_2)])
        code, sortie, erreur, detail = d.lancer()
        self.assertEqual((code, erreur), (0, ""))
        return sortie, detail

    def decomposition(self, detail):
        groupes = detail["dispersion"]["par_groupe"]
        self.assertEqual(len(groupes), 1)
        self.assertEqual(groupes[0]["couples"], 2)  # (BUR, PIC) et (PIC, BUR) : mêmes SCE
        return groupes[0], groupes[0]["decomposition"]

    def test_deux_fichiers_de_cinq_separes(self):
        # Fichier 1 : 0,10 à 0,14 (moyenne 0,12) ; fichier 2 : 0,30 à 0,34 (0,32) ; moyenne générale 0,22.
        #   SCE intra = 2 x (0,02^2 + 0,01^2 + 0 + 0,01^2 + 0,02^2) = 0,002 ; SCE inter = 10 x 0,1^2 = 0,1 ;
        #   CM intra = 0,002 / 8, CM inter = 0,1 / 1 : R = 400 ; rho = (0,1 - 0,00025) / (0,1 + 4 x 0,00025) = 0,98762.
        #   Seules les deux répartitions d'origine (les fichiers échangés) atteignent R : p = 2/252.
        sortie, detail = self.lancer((0.10, 0.11, 0.12, 0.13, 0.14), (0.30, 0.31, 0.32, 0.33, 0.34))
        groupe, d = self.decomposition(detail)
        self.assertEqual((groupe["tables_par_fichier"], groupe["ddl_intra"], d["ddl_inter"]), ([5, 5], 8, 1))
        self.assertAlmostEqual(d["sce_inter_par_couple"], 0.1)
        self.assertAlmostEqual(d["sce_intra_par_couple"], 0.002)
        self.assertEqual(d["r"], 400.0)
        self.assertAlmostEqual(groupe["ecart_type_intra"], 0.0158114, places=7)  # racine(0,00025)
        self.assertEqual((d["repartitions"], d["p"]["fraction"], d["p"]["numerateur"], d["p"]["denominateur"]),
                         (252, "2/252", 2, 252))
        self.assertAlmostEqual(d["p"]["valeur"], 2 / 252)
        self.assertEqual(d["p_minimal"]["fraction"], "2/252")
        self.assertEqual(d["p_queue_inferieure"]["fraction"], "252/252")
        self.assertAlmostEqual(d["correlation_intra_fichier"], 0.98762, places=5)
        self.assertEqual((d["rejet"], d["lecture"]), (True, "indépendance des tirages d'un lancement rejetée"))
        self.assertEqual(d["reperes_sous_h0"], {"mediane": 0.499, "c95": 5.318})
        self.assertEqual(d["puissance_indicative"], {"0.2": 0.16, "0.5": 0.37, "0.8": 0.63, "0.9": 0.74})
        self.assertIn("p = 2/252 = 0.0079", sortie)
        self.assertIn("0.2 : 16 sur 100 ; 0.5 : 37 sur 100 ; 0.8 : 63 sur 100 ; 0.9 : 74 sur 100", sortie)
        # Le rejet est une mise en garde en tête du tableau, et entre dans les avertissements du niveau
        # sur lequel le verdict est lu (décision du mainteneur, 2026-10-10) : non concluant.
        self.assertEqual(len(detail["mises_en_garde"]), 1)
        self.assertIn("indépendance des tirages d'un lancement rejetée", detail["mises_en_garde"][0])
        self.assertIn("  MISE EN GARDE : indépendance des tirages d'un lancement rejetée", sortie)
        verdict = detail["verdict"]["recherches_a"]
        self.assertEqual((verdict["verdict"], verdict["concluant"]), ("non concluant", False))
        self.assertIn(detail["mises_en_garde"][0], verdict["avertissements"])
        self.assertEqual(detail["dispersion"]["tables_jumelles"]["paires_jumelles"], 0)

    def test_deux_fichiers_de_cinq_identiques(self):
        # Mêmes valeurs dans les deux fichiers : SCE inter = 0, R = 0, toute répartition fait au moins autant
        # (252/252) ; rho = (0 - 0,00025) / (0 + 4 x 0,00025) = -0,25, sans troncature.
        sortie, detail = self.lancer((0.10, 0.11, 0.12, 0.13, 0.14), (0.10, 0.11, 0.12, 0.13, 0.14))
        _groupe, d = self.decomposition(detail)
        self.assertEqual((d["sce_inter"], d["r"], d["p"]["fraction"], d["p"]["valeur"]), (0.0, 0.0, "252/252", 1.0))
        self.assertAlmostEqual(d["sce_intra_par_couple"], 0.002)
        self.assertEqual(d["correlation_intra_fichier"], -0.25)
        self.assertEqual((d["rejet"], d["lecture"]), (False, "indépendance des tirages d'un lancement non rejetée"))
        self.assertIn("non rejetée (non rejetée n'est pas établie)", sortie)
        # Ni mise en garde ni avertissement d'indépendance : les tables jumelles se cherchent dans un même fichier.
        self.assertEqual(detail["mises_en_garde"], [])
        self.assertNotIn("MISE EN GARDE", sortie)
        avertissements = " ".join(detail["verdict"]["recherches_a"]["avertissements"])
        self.assertNotIn("indépendance", avertissements)
        self.assertNotIn("jumelles", avertissements)
        self.assertEqual(len(detail["verdict"]["recherches_a"]["avertissements"]), 2)  # 20 observations, 1 position

    def test_deux_fichiers_de_deux(self):
        # 0,10 ; 0,12 et 0,20 ; 0,22 : SCE intra = 4 x 0,01^2 = 0,0004, SCE inter = 4 x 0,05^2 = 0,01,
        # R = 0,01 / (0,0004 / 2) = 50 ; 6 répartitions, 2 atteignent R : p = 2/6, le plus petit possible --
        # un R énorme reste non rejeté quand l'échantillon est trop petit.
        _sortie, detail = self.lancer((0.10, 0.12), (0.20, 0.22))
        _groupe, d = self.decomposition(detail)
        self.assertAlmostEqual(d["sce_inter_par_couple"], 0.01)
        self.assertAlmostEqual(d["sce_intra_par_couple"], 0.0004)
        self.assertEqual((d["r"], d["p"]["fraction"], d["p_minimal"]["fraction"], d["rejet"]), (50.0, "2/6", "2/6", False))
        self.assertAlmostEqual(d["correlation_intra_fichier"], 0.96078, places=5)
        self.assertEqual(detail["mises_en_garde"], [])

    def test_type_b_decompose_a_part(self):
        # Le type B a son propre groupe ; son rejet est signalé, sans valoir confirmation de celui de A.
        sortie, detail = self.lancer((0.10, 0.11, 0.12, 0.13, 0.14), (0.30, 0.31, 0.32, 0.33, 0.34),
                                     recherche="B", engagements=[BUR])
        groupe, d = self.decomposition(detail)
        self.assertEqual((groupe["recherche"], d["rejet"]), ("B", True))
        self.assertIn("type B : pas une confirmation indépendante du test sur le type A", sortie)

    def test_un_seul_fichier_pas_de_decomposition(self):
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(g, tirage=i) for i, g in enumerate((0.10, 0.11, 0.12, 0.13, 0.14))])
        _code, sortie, _erreur, detail = d.lancer()
        groupe = detail["dispersion"]["par_groupe"][0]
        self.assertIsNone(groupe["decomposition"])
        self.assertAlmostEqual(groupe["ecart_type_intra"], 0.0158114, places=7)  # racine(0,001 / 4)
        self.assertEqual(detail["dispersion"]["groupes_decomposes"], 0)
        self.assertIn("aucun groupe réparti sur au moins deux fichiers", sortie)

    def test_trop_de_repartitions_pas_de_test(self):
        self.assertEqual(bruit.nombre_de_repartitions([5, 5]), 252)
        self.assertEqual(bruit.nombre_de_repartitions([2, 2, 2]), 90)
        self.assertEqual(len(list(bruit.repartitions(list(range(6)), [2, 2, 2]))), 90)
        with mock.patch.object(bruit, "MAX_REPARTITIONS", 5):
            _sortie, detail = self.lancer((0.10, 0.12), (0.20, 0.22))
        d = detail["dispersion"]["par_groupe"][0]["decomposition"]
        self.assertEqual((d["p"], d["rejet"], d["lecture"]), (None, False, "pas de test : 6 répartitions, plus de 5"))

    def test_tables_jumelles(self):
        # Deux lignes d'un même fichier aux order_values identiques : 1 paire. Deux autres au même lambda,
        # valeurs différentes : 1 paire de plus. D'un fichier à l'autre, ou d'un type à l'autre : aucune.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(0.10, tirage=0), deux_ordres(0.10, tirage=1),
                                  deux_ordres(0.10, tirage=1, recherche="B", engagements=[BUR])])
        d.ecrire("m1_9_b.jsonl", [deux_ordres(0.10, tirage=0, search={"lambda": 0.12}),
                                  deux_ordres(0.11, tirage=1, search={"lambda": 0.12}),
                                  deux_ordres(0.12, tirage=2, search={"lambda": 0.13})])
        _code, sortie, _erreur, detail = d.lancer()
        jumelles = detail["dispersion"]["tables_jumelles"]
        self.assertEqual(jumelles["order_values_identiques"], [["m1_9_a.jsonl:1", "m1_9_a.jsonl:2"]])
        self.assertEqual(jumelles["lambda_identique"], [["m1_9_b.jsonl:1", "m1_9_b.jsonl:2"]])
        self.assertEqual((jumelles["paires_jumelles"], jumelles["paires_examinees"]), (2, 4))
        self.assertIn("  MISE EN GARDE : 2 paire(s) de tables jumelles", sortie)
        self.assertIn("2 paire(s) de tables jumelles", " ".join(detail["verdict"]["recherches_a"]["avertissements"]))
        # Le fichier b a deux lambda distincts (0,12 et 0,13) : il n'est pas jumeau d'un bout à l'autre.
        self.assertEqual(jumelles["fichiers_entierement_jumeaux_par_lambda"], [])
        self.assertNotIn("lambda_constant", jumelles)
        self.assertIn("le contrôle par search.lambda suppose un lambda dynamique, différent d'un tirage à l'autre.", sortie)
        self.assertNotIn("ont le même search.lambda", sortie)

    def test_lambda_constant_et_valeurs_differentes(self):
        # Trois tables d'un fichier aux valeurs toutes différentes, au même lambda : le lambda dynamique est
        # mis en cache par état d'agent, un état réutilisé d'un tirage à l'autre donne exactement cela. Les
        # trois paires sont jumelles, la mise en garde nomme le fichier et les deux causes possibles, et le
        # verdict n'est pas concluant.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(g, tirage=i, search={"lambda": 0.12}) for i, g in enumerate((0.10, 0.11, 0.12))])
        _code, sortie, _erreur, detail = d.lancer()
        jumelles = detail["dispersion"]["tables_jumelles"]
        self.assertEqual((jumelles["paires_jumelles"], jumelles["paires_examinees"]), (3, 3))
        self.assertEqual((jumelles["order_values_identiques"], len(jumelles["lambda_identique"])), ([], 3))
        self.assertEqual(jumelles["fichiers_entierement_jumeaux_par_lambda"], ["m1_9_a.jsonl"])
        self.assertEqual(len(detail["mises_en_garde"]), 1)
        self.assertIn("3 paire(s) de tables jumelles (même fichier, même type ; order_values identiques : 0, search.lambda "
                      "identique : 3)", detail["mises_en_garde"][0])
        self.assertTrue(detail["mises_en_garde"][0].endswith(
            " ; toutes les paires de m1_9_a.jsonl ont le même search.lambda : état partagé entre tirages, ou lambda non "
            "dynamique dans la configuration"), detail["mises_en_garde"][0])
        self.assertIn("  MISE EN GARDE : 3 paire(s) de tables jumelles", sortie)
        verdict = detail["verdict"]["recherches_a"]
        self.assertEqual((verdict["verdict"], verdict["concluant"]), ("non concluant", False))
        self.assertIn(detail["mises_en_garde"][0], verdict["avertissements"])
        self.assertEqual(len(verdict["avertissements"]), 3)  # 6 observations, 1 position, et les jumelles

    def test_lambda_constant_par_type(self):
        # Les recherches A ont un lambda, les B un autre, chacun constant d'un tirage à l'autre : les paires
        # se font dans un type, toutes sont jumelles -- 3 en A, 3 en B --, et le fichier est nommé.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(g, tirage=i, search={"lambda": 0.12}) for i, g in enumerate((0.10, 0.11, 0.12))] + [
            deux_ordres(g, tirage=i, recherche="B", engagements=[BUR], search={"lambda": 0.15})
            for i, g in enumerate((0.20, 0.21, 0.22))])
        _code, sortie, _erreur, detail = d.lancer()
        jumelles = detail["dispersion"]["tables_jumelles"]
        self.assertEqual((jumelles["paires_jumelles"], jumelles["paires_examinees"], len(jumelles["lambda_identique"])),
                         (6, 6, 6))
        self.assertEqual(jumelles["fichiers_entierement_jumeaux_par_lambda"], ["m1_9_a.jsonl"])
        self.assertIn("  MISE EN GARDE : 6 paire(s) de tables jumelles", sortie)
        self.assertEqual(detail["verdict"]["recherches_a"]["verdict"], "non concluant")

    def test_engagements_differents_d_un_fichier_a_l_autre(self):
        # La même position dans deux fichiers : les recherches B du premier ont figé BUR, celles du second PIC.
        # Deux groupes B de deux tables, aucun réparti sur deux fichiers : pas de décomposition du type B ;
        # le constat est rendu, une ligne pour la position, avec les deux engagements.
        d = Dossier(self)
        for nom, engagement in (("m1_9_a.jsonl", BUR), ("m1_9_b.jsonl", PIC)):
            d.ecrire(nom, [deux_ordres(g, tirage=i) for i, g in enumerate((0.10, 0.12))] + [
                deux_ordres(g, tirage=i, recherche="B", engagements=[engagement]) for i, g in enumerate((0.11, 0.13))])
        _code, sortie, _erreur, detail = d.lancer()
        dispersions = detail["dispersion"]
        self.assertEqual(dispersions["engagements_differents_entre_fichiers"], [{
            "position": "9 S1901M FRANCE", "recherche": "B",
            "par_fichier": [{"fichier": "m1_9_a.jsonl", "engagements": [BUR], "tables": 2},
                            {"fichier": "m1_9_b.jsonl", "engagements": [PIC], "tables": 2}]}])
        self.assertEqual([(g["recherche"], bool(g["decomposition"])) for g in dispersions["par_groupe"]],
                         [("A", True), ("B", False), ("B", False)])
        self.assertEqual(sortie.count("aux engagements différents d'un fichier à l'autre"), 1)
        self.assertIn("  position 9 S1901M FRANCE : recherches B aux engagements différents d'un fichier à l'autre -- "
                      "A PAR - BUR (m1_9_a.jsonl, 2 tables) ; A PAR - PIC (m1_9_b.jsonl, 2 tables) ; elles forment des "
                      "groupes distincts, pas de test d'indépendance sur le type B", sortie)
        # Un constat, pas une mise en garde : le verdict n'en reçoit aucun avertissement.
        self.assertEqual(detail["mises_en_garde"], [])
        self.assertNotIn("engagements différents", " ".join(detail["verdict"]["recherches_a"]["avertissements"]))

    def test_memes_engagements_dans_les_deux_fichiers(self):
        # Le même engagement figé par les deux lancements : rien à signaler, et le type B est décomposé.
        _sortie, detail = self.lancer((0.10, 0.12), (0.20, 0.22), recherche="B", engagements=[BUR])
        self.assertEqual(detail["dispersion"]["engagements_differents_entre_fichiers"], [])
        self.assertNotIn("aux engagements différents", _sortie)


class CritereSurLesRecherchesA(unittest.TestCase):
    def test_les_recherches_b_n_entrent_pas_dans_le_verdict(self):
        # A : G(BUR, PIC) = 0,000 ; 0,001 ; 0,002 -- |d| <= 0,0015. B : 0,00 ; 0,03 ; 0,09 -- |d| jusqu'à 0,075.
        # Le critère, lu sur A seul, donnerait « protège » ; le cumul A + B donnerait « ne protège pas ».
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(g, tirage=i) for i, g in enumerate((0.0, 0.001, 0.002))] + [
            deux_ordres(g, tirage=i, recherche="B", engagements=[BUR]) for i, g in enumerate((0.0, 0.03, 0.09))])
        code, sortie, _erreur, detail = d.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(detail["niveau_du_critere"], "recherches_a")
        self.assertEqual([detail["bruit"][n]["total"]["observations"] for n, _ in bruit.NIVEAUX], [6, 6, 12, 12])
        self.assertAlmostEqual(detail["bruit"]["recherches_a"]["total"]["abs_d"]["max"], 0.0015)
        self.assertAlmostEqual(detail["bruit"]["recherches_b"]["total"]["abs_d"]["max"], 0.075)
        lectures = {n: detail["verdict"][n]["lecture_indicative"] for n, _ in bruit.NIVEAUX}
        self.assertEqual(lectures, {"recherches_a": "protège", "recherches_b": "ne protège pas",
                                    "groupe": "ne protège pas", "engagements": "ne protège pas"})
        # Seuls les effectifs retiennent le niveau du critère ; les trois autres portent en plus leur mention.
        self.assertEqual(len(detail["verdict"]["recherches_a"]["avertissements"]), 2)
        for nom in ("recherches_b", "groupe", "engagements"):
            self.assertIn("à titre indicatif seulement", detail["verdict"][nom]["avertissements"][0])
        self.assertIn("ses observations ne sont pas indépendantes de celles de A", sortie)
        self.assertLess(sortie.index("Critère lu sur les recherches A sans engagement, seules :"),
                        sortie.index("À titre informatif, hors verdict"))

    def test_recherche_a_avec_engagements_hors_du_critere(self):
        # Une recherche A lancée avec des engagements n'est pas la recherche de référence.
        d = Dossier(self)
        d.ecrire("m1_9_a.jsonl", [deux_ordres(g, tirage=i, engagements=[BUR]) for i, g in enumerate((0.0, 0.03))])
        _code, _sortie, _erreur, detail = d.lancer()
        self.assertEqual(detail["bruit"]["recherches_a"]["groupes"], 0)
        self.assertEqual(detail["verdict"]["recherches_a"]["verdict"], "indéterminé")
        self.assertIn("aucune table à ce niveau", detail["verdict"]["recherches_a"]["avertissements"][0])
        self.assertEqual(detail["bruit"]["groupe"]["total"]["observations"], 4)


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
