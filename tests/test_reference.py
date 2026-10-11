#!/usr/bin/env python3
"""Référence de non-régression (issue #31, ADR 0006) : format, réducteur, contrôle, couche D, capture.

Aucune donnée de partie ici : le jeu d'essai est fabriqué par le banc
(tests/banc_promesses.py : vraies fonctions classer et export_plans sur des
tables tirées à graine fixe), écrit dans un dossier temporaire sous la forme de
relevés de tests/mesure/rejeu_moteur.py, puis réduit. Ni pile, ni Claude, ni GPU.

Usage : python3 tests/test_reference.py
"""
import atexit
import contextlib
import copy
import io
import itertools
import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

# Avant tout chargement : ni __pycache__ dans tests/, ni .pyc sous cicero/overlay (#27).
sys.dont_write_bytecode = True

import banc_promesses as banc
import reference_couche_d as couche_d
import reference_jeu

sys.path.insert(0, str(Path(__file__).resolve().parent / "mesure"))
import capture_reference  # noqa: E402
import rejeu_moteur  # noqa: E402

PHASES = ("S1901M", "F1901M")
PUISSANCES = ("ENGLAND", "FRANCE", "TURKEY")
MESSAGE = "Hello, what are your plans for this turn?"


def releves_fabriques(dossier, graine=31, engagements=False):
    """Relevés fabriqués, au format de rejeu_moteur.py, clés exclues comprises ; rend (lignes, historique).

    Par position : huit à seize actions des trois unités du banc, valeurs de 0 à
    0,30 à cinq décimales (à deux, l'arrondi du gain ne se verrait pas), probabilités tirées puis normalisées, la dernière action à 1e-5 (sous
    tout plancher essayé) ; classement et export par les fonctions du dépôt. Les
    recherches sont sans engagement, comme les recherches A du jeu versionné : le
    contrôle n'admet qu'elles (I3, #40). `engagements` : une table sur deux vient
    d'une recherche avec engagement -- la probabilité d'`action_values` y est
    renforcée, celle de `prior_policy` ne l'est pas -- pour le test de ce refus.
    """
    tirage = random.Random(graine)
    toutes = list(itertools.product(*banc.ORDRES_LEGAUX.values()))
    lignes, joues = [], {}
    for numero, (phase, puissance) in enumerate(itertools.product(PHASES, PUISSANCES)):
        actions = tirage.sample(toutes, tirage.randint(8, 16))
        poids = [tirage.random() ** 3 for _ in actions]
        table = [
            (action, round(0.3 * tirage.random(), 5), float("%.6g" % (p / sum(poids))))
            for action, p in zip(actions, poids)
        ]
        table[-1] = (table[-1][0], table[-1][1], 1e-5)
        regularize_lambda = tirage.choice((0.01, 0.1))
        promesses = [table[1][0][0]] if engagements and numero % 2 else []
        action_values, avant = banc.classer(table, regularize_lambda, promesses)
        recherche = dict(banc.RECHERCHE, **{"lambda": regularize_lambda})
        entree = banc.exporter(action_values, dossier, avant, recherche)
        joues.setdefault(phase, {})[puissance] = entree["plans"][0]["orders"]
        lignes.append({
            "mesure": "M1", "mode": "engagements", "a_sec": False, "game_id": 9, "phase": phase,
            "puissance": puissance, "tirage": 0, "recherche": "A",
            "engagements_du_fichier": promesses, "engagements_retenus_par_le_moteur": promesses,
            "message_declencheur": {"sender": "GERMANY", "recipient": puissance, "message": MESSAGE},
            "statut": {"gameID": 9, "processStatus": "Paused"}, "duree_s": 41.3,
            "gpu": {"max_utilise_mio": 4617, "total_mio": 8192, "erreur": None},
            "action_rendue": entree["plans"][0]["orders"], "politique_avant_renfort": [[list(a), p] for a, p in avant.items()],
            "entree": entree, "controles": {"entree_exportee": True},
            "journal": ["INFO plan_export: wrote 6 candidate plans for %s %s (game 9)" % (puissance, phase)],
            "arguments_export": {
                "action_values": [[list(a), v, p, s] for a, v, p, s in action_values],
                "prior_policy": [[list(a), p] for a, p in avant.items()],
                "regularize_lambda": regularize_lambda, "boost": recherche["boost"], "max_prob": recherche["max_prob"],
            },
        })
    historique = {"phases": [{"name": phase, "orders": joues[phase]} for phase in PHASES]}
    historique["phases"].append({"name": "W1901A", "orders": {"FRANCE": ["A PAR B"]}})
    return lignes, historique


SHA = "0" * 40  # aucun commit : le jeu est fabriqué
MANIFESTE = {
    "partie": {"numero": 9, "creee_le": "2026-01-01", "nature": reference_jeu.NATURE},
    "capture": {"date": "2026-01-01", "sha_code": SHA, "image": "aucune", "commande": "tests/test_reference.py"},
}


def generer(dossier, *options):
    """(code, sortie) de --generer, l'état du dépôt étant doublé : arbre propre, SHA factice."""
    sortie = io.StringIO()
    with mock.patch.object(couche_d, "arbre_modifie", lambda: []), mock.patch.object(couche_d, "sha_du_depot", lambda: SHA), \
            contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
        code = couche_d.main(["--jeu", str(dossier), "--generer", "--date", "2026-01-01"] + list(options))
    return code, sortie.getvalue()


def depot_git(racine):
    """Fait de `racine` un dépôt git commité (un harnais, un fichier d'overlay, ce qui s'y trouve déjà) ; rend l'appel git.

    Dépôt temporaire, sans rapport avec celui du projet : la configuration et les
    variables GIT_* de l'appelant sont écartées, pour que le test dise la même chose partout.
    Son fichier d'ignorés global aussi (git/ignore sous XDG_CONFIG_HOME, à défaut sous
    ~/.config), que GIT_CONFIG_GLOBAL ne neutralise pas : HOME et XDG_CONFIG_HOME
    désignent un dossier vide, à côté du dépôt.
    """
    foyer = racine.parent / "foyer_git"
    foyer.mkdir(exist_ok=True)
    env = {cle: valeur for cle, valeur in os.environ.items() if not cle.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", HOME=str(foyer), XDG_CONFIG_HOME=str(foyer / "config"))

    def git(*arguments):
        return subprocess.run(
            ["git", "-C", str(racine), "-c", "user.name=essai", "-c", "user.email=essai@example.invalid"] + list(arguments),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, check=True).stdout.decode("utf-8", "replace")
    (racine / "tests").mkdir(exist_ok=True)
    (racine / "tests" / "harnais.py").write_text("harnais = 1\n", encoding="utf-8")
    (racine / "cicero" / "overlay").mkdir(parents=True)
    (racine / "cicero" / "overlay" / "bot.py").write_text("bot = 1\n", encoding="utf-8")
    (racine / "ailleurs.md").write_text("hors des mesures\n", encoding="utf-8")
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "depot d'essai")
    git.env = env
    return git


_GABARITS = {}


def gabarit():
    """Le jeu fabriqué, construit une fois par lancement des tests : (dossier sans attendus, avec, lignes, historique).

    Chaque test en reçoit une copie (AvecJeu.setUp) : le construire et générer ses
    attendus à chaque test coûtait l'essentiel du temps de la batterie.
    """
    if not _GABARITS:
        racine = Path(tempfile.mkdtemp(prefix="gabarit_reference_"))
        atexit.register(shutil.rmtree, str(racine), True)
        lignes, historique = releves_fabriques(racine)
        (racine / "current_plans.json").unlink()
        releves = racine / "releves.jsonl"
        releves.write_text("".join(json.dumps(ligne) + "\n" for ligne in lignes), encoding="utf-8")
        tables, _ = reference_jeu.reduire_fichiers([releves])
        releves.unlink()
        reference_jeu.construire_jeu(racine / "sans" / "tests" / "reference", historique, tables, MANIFESTE)
        shutil.copytree(str(racine / "sans"), str(racine / "avec"))
        code, sortie = generer(racine / "avec" / "tests" / "reference")
        assert code == 0, sortie
        _GABARITS.update(sans=racine / "sans", avec=racine / "avec", lignes=lignes, historique=historique)
    return _GABARITS


class AvecJeu(unittest.TestCase):
    """Un jeu d'essai fabriqué, avec ses attendus, dans un dossier temporaire propre à chaque test."""

    attendus = True

    def setUp(self):
        modele = gabarit()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name) / "depot"
        shutil.copytree(str(modele["avec" if self.attendus else "sans"]), str(self.racine))
        self.dossier = self.racine / "tests" / "reference"
        self.lignes, self.historique = copy.deepcopy(modele["lignes"]), copy.deepcopy(modele["historique"])

    def lancer(self, *options):
        """(code de retour, sortie) de la couche D sur le jeu du test."""
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = couche_d.main(["--jeu", str(self.dossier)] + list(options))
        return code, sortie.getvalue()

    def generer(self, *options):
        return generer(self.dossier, *options)

    def arbre(self, git):
        """arbre_modifie, git non doublé, sur le dépôt du test (voir depot_git)."""
        with mock.patch.object(couche_d, "RACINE", self.racine), mock.patch.dict(os.environ, git.env, clear=True):
            return couche_d.arbre_modifie()

    def modifier(self, relatif, changement, manifeste=True):
        """Applique `changement` au JSON d'un fichier du jeu, puis refait le manifeste (sauf `manifeste` faux)."""
        fichier = self.dossier / relatif
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
        changement(donnees)
        fichier.write_text(json.dumps(donnees), encoding="utf-8")
        if manifeste:
            self.refaire_manifeste()

    def refaire_manifeste(self):
        reference_jeu.ecrire_manifeste(
            self.dossier, json.loads((self.dossier / reference_jeu.MANIFESTE).read_text(encoding="utf-8"))
        )

    def violations(self):
        return reference_jeu.controler(self.dossier)

    def une_violation(self, *fragments):
        """Le contrôle échoue, et l'une de ses lignes porte tous les fragments."""
        violations = self.violations()
        self.assertTrue(violations, "le contrôle passe")
        self.assertTrue(
            any(all(f in v for f in fragments) for v in violations),
            "aucune violation ne porte %r :\n%s" % (fragments, "\n".join(violations)),
        )

    def table(self, phase="S1901M", puissance="FRANCE"):
        return json.loads((self.dossier / "tables" / (phase + ".json")).read_text(encoding="utf-8"))["tables"][puissance]


def _cles(valeur, trouvees=None):
    trouvees = set() if trouvees is None else trouvees
    if isinstance(valeur, dict):
        trouvees.update(valeur)
        for contenu in valeur.values():
            _cles(contenu, trouvees)
    elif isinstance(valeur, list):
        for contenu in valeur:
            _cles(contenu, trouvees)
    return trouvees


# ---------------------------------------------------------------------------
# Réducteur
# ---------------------------------------------------------------------------

class Reducteur(AvecJeu):
    attendus = False

    def test_le_jeu_ne_garde_rien_de_ce_que_l_adr_exclut(self):
        """Ni clé exclue, ni texte de message, ni ligne de journal, ni numéro de partie hors manifeste."""
        for relatif in reference_jeu.fichiers_du_jeu(self.dossier):
            texte = (self.dossier / relatif).read_text(encoding="utf-8")
            if relatif == reference_jeu.MANIFESTE:
                continue
            with self.subTest(fichier=relatif):
                self.assertEqual(_cles(json.loads(texte)) & set(reference_jeu.CLES_EXCLUES), set())
                for interdit in ("Hello", "plan_export:", "4617", "41.3", "Paused", "controles", "politique_avant_renfort"):
                    self.assertNotIn(interdit, texte)

    def test_une_table_n_a_que_ses_quatre_cles_et_ses_arguments(self):
        table = self.table()
        self.assertEqual(sorted(table), sorted(reference_jeu.CLES_TABLE + ("export_plans",)))
        self.assertEqual(sorted(table["plans"][0]), sorted(reference_jeu.CLES_PLAN))
        self.assertEqual(sorted(table["candidates"][0]), sorted(reference_jeu.CLES_CANDIDAT))
        self.assertEqual(sorted(table["search"]), sorted(reference_jeu.CLES_RECHERCHE))

    def test_la_table_reduite_est_l_entree_exportee(self):
        """Valeurs et probabilités recopiées telles quelles, sans arrondi de plus."""
        for ligne in self.lignes:
            table = self.table(ligne["phase"], ligne["puissance"])
            for cle in reference_jeu.CLES_TABLE:
                self.assertEqual(table[cle], ligne["entree"][cle])

    def test_une_action_n_est_pas_ecrite_deux_fois(self):
        """Arguments bruts : les ordres d'une action sont ceux du candidat de même rang, et ne sont pas répétés."""
        arguments = self.table()["export_plans"]
        self.assertTrue(all("orders" not in a for a in arguments["action_values"]))
        self.assertTrue(all("action" in ligne for ligne in arguments["prior_policy"]))

    def test_une_action_hors_des_candidats_garde_ses_ordres(self):
        brut = {
            "action_values": [[["A PAR H"], 0.1, 0.5, 0.09], [["A PAR - BUR"], 0.2, 0.5, 0.19]],
            "prior_policy": [[["A PAR - BUR"], 0.4], [["A PAR - PIC"], 0.6]],
            "regularize_lambda": 0.01, "boost": 3.0, "max_prob": 0.4,
        }
        reduit = reference_jeu.reduire_arguments(brut, [{"orders": ["A PAR H"]}, {"orders": ["A PAR - GAS"]}])
        self.assertEqual(reduit["action_values"], [
            {"value": 0.1, "prob": 0.5, "score": 0.09},
            {"value": 0.2, "prob": 0.5, "score": 0.19, "orders": ["A PAR - BUR"]},
        ])
        self.assertEqual(reduit["prior_policy"], [{"action": 1, "prob": 0.4}, {"orders": ["A PAR - PIC"], "prob": 0.6}])

    def test_arguments_sans_politique_d_avant_renfort(self):
        """Un export sans `prior_policy` (ou sans un paramètre) ne se rejoue pas : refusé, pas de trace."""
        brut = self.lignes[0]["arguments_export"]
        for cle in ("prior_policy", "action_values", "regularize_lambda", "boost", "max_prob"):
            with self.subTest(cle=cle), self.assertRaises(reference_jeu.Refus):
                reference_jeu.reduire_arguments(dict(brut, **{cle: None}))
        with self.assertRaises(reference_jeu.Refus):
            reference_jeu.reduire_releve(dict(self.lignes[0], arguments_export=dict(brut, prior_policy=None)))

    def test_seule_la_recherche_demandee_est_retenue(self):
        ligne = self.lignes[0]
        self.assertIsNone(reference_jeu.reduire_releve(dict(ligne, recherche="B"))[0])
        self.assertIsNone(reference_jeu.reduire_releve(dict(ligne, tirage=1))[0])
        self.assertIsNone(reference_jeu.reduire_releve({"mesure": "M1", "comparaison": {}})[0])
        self.assertEqual(reference_jeu.reduire_releve(dict(ligne, recherche="B"), recherche="B")[:2], ("S1901M", "ENGLAND"))

    def test_un_releve_d_essai_a_sec_est_refuse(self):
        with self.assertRaises(reference_jeu.Refus):
            reference_jeu.reduire_releve(dict(self.lignes[0], a_sec=True))

    def test_une_entree_incomplete_est_refusee(self):
        for entree in (None, {"plans": [], "order_values": {}}):
            with self.subTest(entree=entree), self.assertRaises(reference_jeu.Refus):
                reference_jeu.reduire_releve(dict(self.lignes[0], entree=entree))

    def test_deux_releves_d_une_position_aucun_ne_l_emporte(self):
        fichier = self.racine / "deux.jsonl"
        seconde = json.loads(json.dumps(self.lignes[0]))
        seconde["entree"]["plans"][0]["value"] = 9.0
        fichier.write_text(json.dumps(self.lignes[0]) + "\n" + json.dumps(seconde) + "\n", encoding="utf-8")
        with self.assertRaises(reference_jeu.Refus) as refus:
            reference_jeu.reduire_fichiers([fichier])
        self.assertIn("deux relevés pour la position S1901M ENGLAND (deux.jsonl:1, deux.jsonl:2)", str(refus.exception))

    def test_un_jeu_ne_s_ecrit_pas_par_dessus_un_autre(self):
        with self.assertRaises(reference_jeu.Refus):
            reference_jeu.construire_jeu(self.dossier, self.historique, {}, MANIFESTE)

    def test_un_jeu_inadmissible_est_refuse_a_l_ecriture(self):
        tables, _ = reference_jeu.reduire_fichiers([self._releves()])
        tables["S1901M"]["FRANCE"]["plans"][0]["orders"][0] = MESSAGE
        with self.assertRaises(reference_jeu.Refus):
            reference_jeu.construire_jeu(self.racine / "autre", self.historique, tables, MANIFESTE)

    def _releves(self):
        fichier = self.racine / "encore.jsonl"
        fichier.write_text("".join(json.dumps(ligne) + "\n" for ligne in self.lignes), encoding="utf-8")
        return fichier

    def test_la_commande_reduire_ecrit_le_jeu_et_son_manifeste(self):
        historique = self.racine / "historique.json"
        historique.write_text(json.dumps(self.historique), encoding="utf-8")
        vers = self.racine / "par_commande"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(sys.stdout):
            code = reference_jeu.main([
                "reduire", str(self._releves()), "--historique", str(historique), "--vers", str(vers),
                "--partie", "9", "--creee-le", "2026-01-01", "--date", "2026-01-02", "--sha", SHA, "--image", "x", "--commande", "x",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(reference_jeu.controler(vers), [])
        manifeste = json.loads((vers / "manifeste.json").read_text(encoding="utf-8"))
        self.assertEqual(manifeste["phases"], list(PHASES))
        self.assertEqual(manifeste["puissances"], list(PUISSANCES))
        self.assertEqual(manifeste["partie"], {"numero": 9, "creee_le": "2026-01-01", "nature": "100 % bots"})
        self.assertEqual([f["chemin"] for f in manifeste["fichiers"]], ["historique.json", "tables/F1901M.json", "tables/S1901M.json"])

    def reduire(self, *options):
        historique = self.racine / "historique.json"
        historique.write_text(json.dumps(self.historique), encoding="utf-8")
        vers = self.racine / "par_identite"
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = reference_jeu.main([
                "reduire", str(self._releves()), "--historique", str(historique), "--vers", str(vers),
                "--partie", "9", "--creee-le", "2026-01-01", "--commande", "x",
            ] + list(options))
        return code, sortie.getvalue(), vers

    def test_le_manifeste_reprend_l_identite_de_la_capture(self):
        fichier, identite = capture_reference.ecrire_identite(self.racine / "campagne", "ab" * 20, "sha256:" + "c" * 64, "2026-02-03")
        code, sortie, vers = self.reduire("--identite", str(fichier))
        self.assertEqual(code, 0, sortie)
        capture = json.loads((vers / "manifeste.json").read_text(encoding="utf-8"))["capture"]
        self.assertEqual(capture, {"date": "2026-02-03", "sha_code": "ab" * 20, "image": "sha256:" + "c" * 64, "commande": "x"})

    def test_reduire_sans_identite_ni_sha(self):
        code, sortie, vers = self.reduire("--date", "2026-01-01")
        self.assertEqual(code, 2)
        self.assertIn("--identite, ou bien --date, --sha et --image", sortie)
        self.assertFalse(vers.exists())

    # -- Refus de `reduire` (#38) : code 2, un message qui nomme le fichier et la cause, rien d'écrit --------------

    def refus(self, releves, *options, historique=None, partie=9):
        """Sortie de `reduire` sur ces relevés (texte d'un fichier, ou chemins) ; vérifie le code 2 et que --vers n'existe pas."""
        if isinstance(releves, (str, bytes)):
            fichier = self.racine / "m1_9_releves.jsonl"
            fichier.write_bytes(releves if isinstance(releves, bytes) else releves.encode("utf-8"))
            releves = [fichier]
        if historique is None:
            historique = self.racine / "historique.json"
            historique.write_text(json.dumps(self.historique), encoding="utf-8")
        vers = self.racine / "refuse"
        code, sortie = self.commande(releves, vers, historique, partie, *options)
        self.assertEqual(code, 2, sortie)
        self.assertNotIn("Traceback", sortie)
        self.assertTrue(sortie.startswith("REFUS : "), sortie)
        self.assertEqual(len(sortie.splitlines()), 1, sortie)
        self.assertFalse(vers.exists(), "écrit malgré le refus : %s" % sorted(str(f) for f in vers.rglob("*")))
        return sortie

    def commande(self, releves, vers, historique, partie, *options):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = reference_jeu.main(
                ["reduire"] + [str(r) for r in releves] + ["--historique", str(historique), "--vers", str(vers),
                 "--partie", str(partie), "--creee-le", "2026-01-01", "--date", "2026-01-02", "--sha", SHA, "--image", "x",
                 "--commande", "x"] + list(options))
        return code, sortie.getvalue()

    def texte(self, *lignes):
        return "".join(json.dumps(ligne) + "\n" for ligne in lignes or self.lignes)

    def test_refus_d_un_releve_tronque_ou_d_une_ligne_invalide(self):
        entier = self.texte()
        for nom, texte, ligne in (
            ("tronqué", entier[:len(entier) - 40], len(self.lignes)),
            ("ligne invalide", self.texte(self.lignes[0]) + "{pas du JSON}\n" + self.texte(self.lignes[1]), 2),
            ("clé en double", self.texte(self.lignes[0]) + '{"phase": 1, "phase": 2}\n', 2),
        ):
            with self.subTest(nom):
                sortie = self.refus(texte)
                self.assertIn("m1_9_releves.jsonl:%d : ligne JSON invalide ou tronquée" % ligne, sortie)

    def test_refus_d_une_ligne_qui_est_une_liste(self):
        for ligne, type_trouve in (("[1, 2]", "list"), ('"texte"', "str"), ("null", "NoneType")):
            with self.subTest(ligne):
                sortie = self.refus(self.texte(self.lignes[0]) + ligne + "\n")
                self.assertIn("m1_9_releves.jsonl:2 : objet attendu, %s trouvé" % type_trouve, sortie)

    def test_refus_d_un_fichier_qui_n_est_pas_de_l_utf8(self):
        sortie = self.refus(self.texte().encode("utf-8") + b"\xff\xfe\n")
        self.assertIn("m1_9_releves.jsonl : relevé qui n'est pas de l'UTF-8", sortie)

    def test_refus_d_un_releve_absent(self):
        self.assertIn("nulle_part.jsonl : relevé absent ou illisible", self.refus([self.racine / "nulle_part.jsonl"]))

    def test_refus_d_un_historique_absent_ou_invalide(self):
        fichier = self.racine / "historique_9.json"
        sortie = self.refus(self.texte(), historique=fichier)
        self.assertIn("historique_9.json : historique des ordres absent ou illisible", sortie)
        for nom, contenu, cause in (
            ("tronqué", json.dumps(self.historique)[:-20], "JSON invalide"),
            ("non UTF-8", b"\xff{}", "qui n'est pas de l'UTF-8"),
            ("liste", "[]", "objet attendu, list trouvé"),
            ("sans phases", "{}", "clé(s) absente(s) ['phases']"),
            ("phases qui n'en sont pas", '{"phases": 3}', "forme inattendue de l'historique des ordres (TypeError)"),
            ("ordres en liste", '{"phases": [{"name": "S1901M", "orders": []}]}', "forme inattendue de l'historique des ordres (AttributeError)"),
            ("nombre non fini", '{"phases": [{"name": "S1901M", "orders": {"FRANCE": [NaN]}}]}', "nombre non fini dans l'historique"),
        ):
            with self.subTest(nom):
                fichier.write_bytes(contenu if isinstance(contenu, bytes) else contenu.encode("utf-8"))
                sortie = self.refus(self.texte(), historique=fichier)
                self.assertIn("historique_9.json : ", sortie)
                self.assertIn(cause, sortie)

    def test_refus_d_un_nombre_non_fini_dans_une_table(self):
        """`NaN`, `Infinity` et `1e999` se lisent (json.loads) ; ils étaient refusés en cours d'écriture, historique déjà écrit."""
        modele = self.texte(self.lignes[0], dict(self.lignes[1], entree=dict(self.lignes[1]["entree"], search="ICI")))
        for nombre in ("NaN", "Infinity", "-Infinity", "1e999", "1" + "0" * 400):
            with self.subTest(nombre):
                sortie = self.refus(modele.replace('"ICI"', '{"lambda": %s, "boost": 1, "max_prob": 1}' % nombre))
                self.assertIn("m1_9_releves.jsonl:2 : nombre non fini dans la table de S1901M FRANCE (search.lambda)", sortie)
        brut = json.loads(json.dumps(self.lignes[1]))
        brut["arguments_export"]["action_values"][0][3] = float("inf")
        self.assertIn("(export_plans.action_values[0].score)", self.refus(self.texte(self.lignes[0], brut)))

    def test_un_nombre_non_fini_hors_de_la_table_n_entre_pas(self):
        """Ce que le réducteur ne recopie pas (`duree_s`, une recherche non retenue) n'est pas jugé."""
        fichier = self.racine / "m1_9_releves.jsonl"
        autre = dict(self.lignes[0], recherche="B", entree=dict(self.lignes[0]["entree"], search={"lambda": float("nan")}))
        fichier.write_text(self.texte(*([dict(l, duree_s=float("nan")) for l in self.lignes] + [autre])), encoding="utf-8")
        historique = self.racine / "historique.json"
        historique.write_text(json.dumps(self.historique), encoding="utf-8")
        code, sortie = self.commande([fichier], self.racine / "admis", historique, 9)
        self.assertEqual(code, 0, sortie)
        self.assertEqual(reference_jeu.controler(self.racine / "admis"), [])

    def test_refus_d_un_fichier_vide(self):
        for texte in ("", "\n  \n"):
            with self.subTest(texte=texte):
                self.assertIn("m1_9_releves.jsonl : relevé vide (aucune ligne)", self.refus(texte))
        plein = self.racine / "m1_9_plein.jsonl"
        plein.write_text(self.texte(), encoding="utf-8")
        (self.racine / "m1_9_vide.jsonl").write_text("", encoding="utf-8")
        self.assertIn("m1_9_vide.jsonl : relevé vide", self.refus([plein, self.racine / "m1_9_vide.jsonl"]))

    def test_refus_de_zero_table(self):
        sortie = self.refus(self.texte(*(dict(ligne, recherche="B") for ligne in self.lignes)))
        self.assertIn("aucune table retenue (recherche A, tirage 0) dans 1 fichier(s) de relevés : m1_9_releves.jsonl", sortie)
        sortie = self.refus(self.texte(), "--tirage", "4")
        self.assertIn("aucune table retenue (recherche A, tirage 4)", sortie)

    def test_refus_des_releves_d_une_autre_partie(self):
        sortie = self.refus(self.texte(), partie=3)
        self.assertIn("m1_9_releves.jsonl:1 : relevé de la partie 9 (game_id), pas de la partie 3 demandée (--partie)", sortie)
        for nom, game_id in (("absent", None), ("chaîne", "9"), ("booléen", True), ("flottant", 9.5)):
            with self.subTest(nom):
                lignes = [dict(self.lignes[0], game_id=game_id)] + self.lignes[1:]
                if game_id is None:
                    del lignes[0]["game_id"]
                self.assertIn("m1_9_releves.jsonl:1 : relevé de la partie %r (game_id)" % (game_id,), self.refus(self.texte(*lignes)))
        mele = self.texte(*(self.lignes[:-1] + [dict(self.lignes[-1], game_id=99)]))
        self.assertIn("m1_9_releves.jsonl:%d : relevé de la partie 99" % len(self.lignes), self.refus(mele))

    def deux_passes(self):
        """Dossier de relevés où une position a deux fichiers, comme S1903M FRANCE le 2026-10-10 ; rend (dossier, valeur de la première passe)."""
        dossier = self.racine / "resultats"
        dossier.mkdir()
        for ligne in self.lignes:
            nom = "m1_9_%s_%s_engagements_20260101-000000.jsonl" % (ligne["phase"], ligne["puissance"])
            (dossier / nom).write_text(self.texte(ligne, dict(ligne, recherche="B")), encoding="utf-8")
        seconde = json.loads(json.dumps(self.lignes[0]))
        seconde["entree"]["plans"][0]["value"] = 9.0
        (dossier / "m1_9_S1901M_ENGLAND_engagements-passe2_20260101-010000.jsonl").write_text(self.texte(seconde), encoding="utf-8")
        (dossier / "historique_9.json").write_text(json.dumps(self.historique), encoding="utf-8")
        return dossier, self.lignes[0]["entree"]["plans"][0]["value"]

    def test_refus_d_une_position_en_double(self):
        """Le motif large (m1_*.jsonl, ou le dossier) prenait la seconde passe, classée avant la première : 139 différences de couche D
        contre les attendus versionnés (D1r 5, D2 20, D3 91, D4 13, D5 4, D6 6)."""
        dossier, _ = self.deux_passes()
        for nom, releves in (("motif large", sorted(dossier.glob("m1_*.jsonl"))), ("dossier", [dossier])):
            with self.subTest(nom):
                sortie = self.refus(releves, historique=dossier / "historique_9.json")
                self.assertIn("deux relevés pour la position S1901M ENGLAND (m1_9_S1901M_ENGLAND_engagements-passe2_20260101-010000.jsonl:1, "
                              "m1_9_S1901M_ENGLAND_engagements_20260101-000000.jsonl:1)", sortie)
                self.assertIn("--sauf", sortie)

    def test_sauf_ecarte_la_seconde_passe(self):
        dossier, premiere = self.deux_passes()
        for nom, releves in (("motif large", sorted(dossier.glob("m1_*.jsonl"))), ("dossier", [dossier])):
            with self.subTest(nom):
                vers = self.racine / ("sauf_" + nom.replace(" ", "_"))
                code, sortie = self.commande(releves, vers, dossier / "historique_9.json", 9, "--sauf", "*passe2*")
                self.assertEqual(code, 0, sortie)
                self.assertIn("écarté (--sauf) : m1_9_S1901M_ENGLAND_engagements-passe2_20260101-010000.jsonl", sortie)
                table = json.loads((vers / "tables" / "S1901M.json").read_text(encoding="utf-8"))["tables"]["ENGLAND"]
                self.assertEqual(table["plans"][0]["value"], premiere)
                self.assertEqual(reference_jeu.controler(vers), [])

    def test_un_fichier_ecarte_par_sauf_n_est_pas_lu(self):
        dossier, _ = self.deux_passes()
        (dossier / "m1_9_S1901M_ENGLAND_engagements-passe2_20260101-010000.jsonl").write_bytes(b"\xff{")
        code, sortie = self.commande([dossier], self.racine / "non_lu", dossier / "historique_9.json", 9, "--sauf", "*passe2*")
        self.assertEqual(code, 0, sortie)

    def test_sauf_a_le_vocabulaire_de_resumer(self):
        """Même motif de dossier que la couche R (bruit_valeurs.MOTIF), mêmes motifs de nom (fnmatch) : --sauf '*passe2*'."""
        import bruit_valeurs
        self.assertEqual(reference_jeu.MOTIF_RELEVES, bruit_valeurs.MOTIF)
        dossier, _ = self.deux_passes()
        retenus, ecartes = reference_jeu.fichiers_de_releves([dossier], ("*passe2*", "*_FRANCE_*"))
        self.assertEqual(len(retenus), len(self.lignes) - len(PHASES))
        self.assertEqual(len(ecartes), 1 + len(PHASES))

    def test_refus_quand_rien_n_est_retenu(self):
        dossier, _ = self.deux_passes()
        self.assertIn("aucun fichier de relevés retenu (--sauf m1_*)", self.refus([dossier], "--sauf", "m1_*", historique=dossier / "historique_9.json"))
        (self.racine / "sans_releve").mkdir()
        self.assertIn("sans_releve : aucun relevé m1_*.jsonl dans ce dossier", self.refus([self.racine / "sans_releve"]))

    def test_refus_d_un_releve_d_une_forme_inattendue(self):
        modele = self.lignes[0]
        for nom, ligne, cause in (
            ("plans qui n'en sont pas", dict(modele, entree=dict(modele["entree"], plans=3)), "forme inattendue du relevé (TypeError)"),
            ("sans phase", {c: v for c, v in modele.items() if c != "phase"}, "forme inattendue du relevé (KeyError)"),
            ("action à trois termes", dict(modele, arguments_export=dict(modele["arguments_export"], action_values=[[["A PAR H"], 1, 2]])),
             "forme inattendue du relevé (ValueError)"),
            ("phase qui sort du dossier", dict(modele, phase="../../S1901M"), "position qui n'est pas une phase et une puissance"),
            ("puissance en liste", dict(modele, puissance=["FRANCE"]), "position qui n'est pas une phase et une puissance"),
            ("entrée absente", dict(modele, entree=None), "entrée exportée : objet attendu, NoneType trouvé"),
        ):
            with self.subTest(nom):
                sortie = self.refus(self.texte(ligne))
                self.assertIn("m1_9_releves.jsonl:1 : ", sortie)
                self.assertIn(cause, sortie)

    def test_refus_d_une_identite_absente(self):
        sortie = self.refus(self.texte(), "--identite", str(self.racine / "identite_capture.json"))
        self.assertIn("identite_capture.json : identité de la capture absent", sortie)

    def identite(self, *options):
        """Sortie de `reduire --identite` sans --date, --sha ni --image (que `refus` passe toujours) ; code 2 et rien d'écrit."""
        code, sortie, vers = self.reduire("--identite", str(self.racine / "identite_capture.json"), *options)
        self.assertEqual(code, 2, sortie)
        self.assertNotIn("Traceback", sortie)
        self.assertEqual(len(sortie.splitlines()), 1, sortie)
        self.assertFalse(vers.exists(), "écrit malgré le refus : %s" % sorted(str(f) for f in vers.rglob("*")))
        return sortie

    def test_refus_d_une_identite_dont_un_champ_n_est_pas_une_chaine(self):
        """`"date": NaN` se lit (json.loads) ; il n'était refusé qu'à l'écriture du manifeste, historique et tables déjà écrits."""
        fichier = self.racine / "identite_capture.json"
        modele = {"date": "2026-02-03", "sha_depot": "ab" * 20, "image": "sha256:" + "c" * 64}
        for cle, valeur, type_trouve in (("date", "NaN", "float"), ("date", "20260203", "int"), ("sha_depot", "null", "NoneType"),
                                         ("image", '["x"]', "list")):
            with self.subTest(cle=cle, valeur=valeur):
                fichier.write_text(json.dumps(dict(modele, **{cle: "ICI"})).replace('"ICI"', valeur), encoding="utf-8")
                sortie = self.identite()
                self.assertIn("identite_capture.json : identité de la capture, %s : chaîne attendue, %s trouvé" % (cle, type_trouve), sortie)

    def test_refus_d_une_phase_nulle(self):
        """Une ligne retenue dont `phase` vaut `null` passait pour non retenue : code 0, une table de moins (#38)."""
        nulle = dict(self.lignes[0], phase=None)
        for nom, lignes, numero in (("seule", [nulle], 1), ("parmi d'autres", self.lignes[1:] + [nulle], len(self.lignes))):
            with self.subTest(nom):
                sortie = self.refus(self.texte(*lignes))
                self.assertIn("m1_9_releves.jsonl:%d : position qui n'est pas une phase et une puissance (NoneType, 'ENGLAND')" % numero, sortie)
        self.assertIn("(NoneType, NoneType)", self.refus(self.texte(dict(nulle, puissance=None))))

    def test_refus_de_deux_fichiers_de_meme_nom(self):
        """`x/m1_meme.jsonl` et `y/m1_meme.jsonl` : le message de la position en double citait deux fois le même nom, et --sauf ne les départage pas."""
        chemins = []
        for sous_dossier in ("x", "y"):
            (self.racine / sous_dossier).mkdir()
            chemins.append(self.racine / sous_dossier / "m1_meme.jsonl")
            chemins[-1].write_text(self.texte(), encoding="utf-8")
        attendu = "deux fichiers de relevés de même nom : %s et %s" % tuple(chemins)
        self.assertIn(attendu, self.refus(chemins))
        self.assertIn(attendu, self.refus([self.racine / "x", self.racine / "y"]))
        self.assertIn("aucun fichier de relevés retenu", self.refus(chemins, "--sauf", "m1_meme*"))  # écartés : pas lus, pas comparés

    def test_refus_d_un_fichier_donne_deux_fois(self):
        """Deux écritures du même chemin, ou un dossier et l'un de ses fichiers : refusé d'emblée, chemins complets cités."""
        dossier, _ = self.deux_passes()
        fichier = sorted(dossier.glob("m1_*.jsonl"))[-1]
        historique = dossier / "historique_9.json"
        for nom, releves in (
            ("deux fois", [fichier, fichier]),
            ("deux écritures", [fichier, dossier / "." / fichier.name]),
            ("dossier et fichier", [dossier, fichier]),
            ("fichier et dossier", [fichier, dossier]),
            ("dossier deux fois", [dossier, dossier]),
        ):
            with self.subTest(nom):
                sortie = self.refus(releves, "--sauf", "*passe2*", historique=historique)
                self.assertIn("fichier de relevés donné deux fois, ou un lien vers lui : ", sortie)
                self.assertIn(str(dossier), sortie)

    def test_refus_d_un_lien_vers_un_fichier_du_meme_dossier(self):
        """`m1_lien.jsonl -> m1_un.jsonl` dans un dossier : le fichier est donné deux fois, et --sauf ne lève pas ce refus, jugé avant lui."""
        dossier = self.racine / "liens"
        dossier.mkdir()
        (dossier / "m1_un.jsonl").write_text(self.texte(), encoding="utf-8")
        os.symlink("m1_un.jsonl", str(dossier / "m1_lien.jsonl"))
        attendu = "fichier de relevés donné deux fois, ou un lien vers lui : %s et %s" % (dossier / "m1_lien.jsonl", dossier / "m1_un.jsonl")
        self.assertIn(attendu, self.refus([dossier]))
        self.assertIn(attendu, self.refus([dossier], "--sauf", "m1_lien*"))

    def test_refus_d_une_boucle_de_liens(self):
        """`boucle1.jsonl -> boucle2.jsonl -> boucle1.jsonl` : avant Python 3.13, resolve() levait RuntimeError, que main ne rattrapait pas (trace, code 1)."""
        for un, autre in (("boucle1.jsonl", "boucle2.jsonl"), ("boucle2.jsonl", "boucle1.jsonl")):
            os.symlink(autre, str(self.racine / un))
        sortie = self.refus([self.racine / "boucle1.jsonl"])
        self.assertIn("%s : relevé absent ou illisible (" % (self.racine / "boucle1.jsonl"), sortie)

    def test_refus_d_un_numero_de_partie_negatif(self):
        """« relevé de la partie -1, pas de la partie -1 demandée » ne disait rien : --partie est un entier positif ou nul (argparse, code 2)."""
        for partie in ("-1", "1.5", "neuf", "1_0", " 3 ", "٣"):
            sortie = io.StringIO()
            with self.subTest(partie), contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie), self.assertRaises(SystemExit) as fin:
                reference_jeu.main(["reduire", str(self._releves()), "--historique", "h", "--vers", str(self.racine / "refuse"),
                                    "--creee-le", "2026-01-01", "--commande", "x", "--partie=" + partie])
            self.assertEqual(fin.exception.code, 2)
            self.assertIn("--partie: entier positif ou nul attendu, %r trouvé" % partie, sortie.getvalue())
            self.assertFalse((self.racine / "refuse").exists())
        self.assertEqual(reference_jeu._numero_de_partie("0"), 0)


# ---------------------------------------------------------------------------
# Contrôle (ADR 0006, décision 3) : un test par violation
# ---------------------------------------------------------------------------

class Controle(AvecJeu):
    def test_dossier_absent(self):
        self.assertEqual(reference_jeu.controler(self.racine / "nulle_part"), [])

    def test_dossier_vide(self):
        (self.racine / "vide").mkdir()
        self.assertEqual(reference_jeu.controler(self.racine / "vide"), [])

    def test_jeu_fabrique_conforme(self):
        self.assertEqual(self.violations(), [])

    def test_la_commande_rend_0_puis_1(self):
        arguments = ["controler", "--dossier", str(self.dossier), "--sans-emplacement"]
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.assertEqual(reference_jeu.main(arguments), 0)
            self.modifier("historique.json", lambda d: d.update(game_id=3))
            self.assertEqual(reference_jeu.main(arguments), 1)
        self.assertIn("conforme", sortie.getvalue())
        self.assertIn("ÉCHEC : historique.json", sortie.getvalue())

    # --- liste blanche des clés

    def test_cle_exclue_dans_une_table(self):
        for cle, valeur in (("computed_at", 1759400000), ("gpu", {"total_mio": 8192}), ("duree_s", 41.3),
                            ("journal", ["INFO"]), ("statut", {"gameID": 3}), ("game_id", 3)):
            with self.subTest(cle=cle):
                self.setUp()
                self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"].update({cle: valeur}))
                self.une_violation("tables/S1901M.json", "clé hors liste blanche", repr(cle), "exclue par l'ADR 0006")

    def test_cle_inconnue_dans_un_plan(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["plans"][0].update(commentaire=1))
        self.une_violation("tables.FRANCE.plans[0]", "clé hors liste blanche", "'commentaire'")

    def test_cle_inconnue_dans_l_historique(self):
        self.modifier("historique.json", lambda d: d["phases"][0].update(messages=[]))
        self.une_violation("historique.json", "phases[0]", "clé hors liste blanche", "'messages'")

    def test_cle_inconnue_dans_les_attendus(self):
        self.modifier("attendus/S1901M.json", lambda d: d["attendus"]["FRANCE"]["D2"].update(reply="x"))
        self.une_violation("attendus/S1901M.json", "clé hors liste blanche", "'reply'")

    def test_cle_inconnue_dans_le_manifeste(self):
        self.modifier("manifeste.json", lambda d: d.update(poste="x"), manifeste=False)
        self.une_violation("manifeste.json", "clé hors liste blanche", "'poste'")

    def test_cle_manquante(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"].pop("search"))
        self.une_violation("tables.FRANCE", "clé absente", "'search'")

    def test_puissance_inconnue(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"].update(NARNIA=d["tables"]["FRANCE"]))
        self.une_violation("tables (clé)", "n'est pas une puissance")

    # --- aucun texte de message

    def test_chaine_plus_longue_qu_un_ordre(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["plans"][0]["orders"].append("A" * 25))
        self.une_violation("plans[0].orders", "chaîne de 25 caractères")

    def test_ponctuation_de_phrase(self):
        for texte in ("A PAR - BUR.", "Bonjour, ça va ?", "ok!", "d'accord"):
            with self.subTest(texte=texte):
                self.setUp()
                self.modifier("historique.json", lambda d: d["phases"][0]["orders"]["FRANCE"].append(texte))
                self.une_violation("historique.json", "ponctuation de phrase", repr(texte))

    def test_chaine_courte_qui_n_est_pas_un_ordre(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["candidates"][0]["orders"].append("HELLO THERE"))
        self.une_violation("candidates[0].orders", "n'est pas un ordre en notation du moteur", "'HELLO THERE'")

    def test_texte_de_message_dans_les_attendus(self):
        self.modifier("attendus/S1901M.json", lambda d: d["attendus"]["FRANCE"]["D5"].update(retour=MESSAGE))
        self.une_violation("attendus/S1901M.json", "D5.retour", "chaîne de %d caractères" % len(MESSAGE))

    def test_texte_court_dans_les_attendus(self):
        self.modifier("attendus/S1901M.json", lambda d: d["attendus"]["FRANCE"]["D5"].update(retour="entendu"))
        self.une_violation("attendus/S1901M.json", "D5.retour", "'entendu'")

    def test_ordre_en_cle_qui_n_en_est_pas_un(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["order_values"].update({"je promets Paris": 0.1}))
        self.une_violation("order_values (clé)", "n'est pas un ordre")

    def test_nombre_non_fini(self):
        fichier = self.dossier / "tables" / "S1901M.json"
        fichier.write_text(fichier.read_text(encoding="utf-8").replace('"lambda":0.1', '"lambda":NaN').replace('"lambda":0.01', '"lambda":NaN'), encoding="utf-8")
        self.refaire_manifeste()
        self.une_violation("search.lambda", "nombre fini attendu")

    def test_les_ordres_du_moteur_sont_admis(self):
        for ordre in ("A PAR H", "A PAR - BUR", "A BUR S A PAR", "A BUR S A PAR - PIC", "F ION C A TUN - APU",
                      "A TUN - APU VIA", "F POR S F MAO - SPA/SC", "F SPA/SC - MAO", "F STP/NC B", "A PAR D", "F SPA/SC R MAO"):
            self.assertTrue(reference_jeu.est_ordre(ordre), ordre)
        for texte in ("", "PAR", "A PAR", "a par h", "A PAR - BUR - PIC", "A PAR H\nA MAR H", "A PARIS H",
                      "A PAR H\n", "A PAR  H", " A PAR H", "A PAR H ", "A ZZZ H", "A PAR - XYZ", "A HEY S A YOU - OUT",
                      "F PAR/SC H", "F SPA/WC H", "A PAR R", 7, None, ["A PAR H"]):
            self.assertFalse(reference_jeu.est_ordre(texte), texte)

    def test_lieu_qui_n_est_pas_de_la_carte(self):
        """Trois majuscules ne font pas un lieu : « A HEY S A YOU - OUT » avait la forme d'un ordre."""
        self.modifier("historique.json", lambda d: d["phases"][0]["orders"]["FRANCE"].append("A HEY S A YOU - OUT"))
        self.une_violation("historique.json", "n'est pas un ordre en notation du moteur", "A HEY S A YOU - OUT")

    def test_les_lieux_sont_ceux_de_l_amont(self):
        """La copie de la liste des lieux contre sa source, quand amont/ est là (absent en CI)."""
        source = reference_jeu.RACINE / "amont" / "cicero" / "dipcc" / "dipcc" / "cc" / "loc.cc"
        if not source.exists():
            self.skipTest("amont/ absent : la liste n'est pas comparée à dipcc/dipcc/cc/loc.cc")
        bloc = re.search(r"VALID_LOC_STRS\{(.*?)\};", source.read_text(encoding="utf-8"), re.S).group(1)
        self.assertEqual(reference_jeu.LIEUX, frozenset(re.findall(r'"([^"]+)"', bloc)))
        self.assertEqual(len(reference_jeu.LIEUX), 81)

    def test_phase_mal_formee(self):
        self.assertTrue(reference_jeu.est_phase("S1901M"))
        for texte in ("S1901M\n", "S19\u0660\u0661M", "S19\uff10\uff11M", "X1901M", "S1901", "S1801M", 1901):
            self.assertFalse(reference_jeu.est_phase(texte), repr(texte))
        self.modifier("historique.json", lambda d: d["phases"][0].update(name="S19\u0660\u0661M"))
        self.une_violation("historique.json", "phases[0].name", "n'est pas une phase")

    def test_cle_json_en_double(self):
        """La seconde occurrence d'une clé masquerait la première : un `game_id` passerait derrière un autre."""
        fichier = self.dossier / "historique.json"
        texte = fichier.read_text(encoding="utf-8")
        fichier.write_text(texte[:-2] + ',"phases":[]}\n', encoding="utf-8")
        self.assertEqual(json.loads(fichier.read_text(encoding="utf-8"))["phases"], [])
        self.refaire_manifeste()
        self.une_violation("historique.json", "JSON illisible", "clé JSON en double", "phases")

    # --- le manifeste ne soustrait rien à la couche D

    def test_manifeste_aux_phases_raccourcies(self):
        for phases in ([], ["S1901M"], ["S1901M", "F1901M", "S1902M"], ["F1901M", "S1901M"]):
            with self.subTest(phases=phases):
                self.setUp()
                self.modifier("manifeste.json", lambda d: d.update(phases=phases), manifeste=False)
                self.une_violation("manifeste.json", "phases", "ne sont pas exactement celles des fichiers de tables/ (S1901M F1901M)")

    def test_manifeste_aux_puissances_raccourcies(self):
        for puissances in ([], ["ENGLAND"], ["ENGLAND", "FRANCE", "TURKEY", "ITALY"]):
            with self.subTest(puissances=puissances):
                self.setUp()
                self.modifier("manifeste.json", lambda d: d.update(puissances=puissances), manifeste=False)
                self.une_violation("manifeste.json", "puissances", "ne sont pas exactement celles des tables (ENGLAND FRANCE TURKEY)")

    def test_attendus_sans_table(self):
        shutil.copy(str(self.dossier / "attendus" / "S1901M.json"), str(self.dossier / "attendus" / "S1902M.json"))
        self.modifier("attendus/S1902M.json", lambda d: d.update(phase="S1902M"))
        self.une_violation("manifeste.json", "attendus sans table pour S1902M")

    # --- valeurs du manifeste

    def test_valeurs_du_manifeste(self):
        cas = [
            (lambda d: d.update(format=2), "format"),
            (lambda d: d.update(format=True), "format"),
            (lambda d: d["partie"].update(numero="3"), "partie.numero"),
            (lambda d: d["partie"].update(numero=True), "partie.numero"),
            (lambda d: d["partie"].update(numero=-1), "partie.numero"),
            (lambda d: d["partie"].update(numero=10 ** 400), "partie.numero"),
            (lambda d: d["partie"].update(creee_le="hier, vers midi"), "partie.creee_le"),
            (lambda d: d["partie"].update(creee_le={"jour": 1}), "partie.creee_le"),
            (lambda d: d["capture"].update(date="2026-10-03T17:36:22"), "capture.date"),
            (lambda d: d["capture"].update(sha_code="5656d25"), "capture.sha_code"),
            (lambda d: d["capture"].update(sha_code=["0" * 40]), "capture.sha_code"),
            (lambda d: d["capture"].update(image="une image locale"), "capture.image"),
            (lambda d: d["capture"].update(image={"Id": "x"}), "capture.image"),
            (lambda d: d["capture"].update(commande=["docker", "run"]), "capture.commande"),
            (lambda d: d["capture"].update(commande="x" * 401), "capture.commande"),
            (lambda d: d["capture"].update(commande="docker run\nBonjour à tous"), "capture.commande"),
            (lambda d: d["attendus"].update(sha_code="inconnu"), "attendus.sha_code"),
            (lambda d: d["attendus"].update(date=20260101), "attendus.date"),
            (lambda d: d.update(taille_octets="beaucoup"), "taille_octets"),
            (lambda d: d["fichiers"][0].update(chemin=["historique.json"]), "fichiers[0].chemin"),
            (lambda d: d["fichiers"][0].update(chemin={"a": 1}), "fichiers[0].chemin"),
            (lambda d: d["fichiers"][0].update(octets="4046"), "fichiers[0].octets"),
            (lambda d: d["fichiers"][0].update(sha256="abc"), "fichiers[0].sha256"),
            (lambda d: d["fichiers"].append(dict(d["fichiers"][0])), "est listé deux fois"),
            (lambda d: d.update(fichiers={"historique.json": 1}), "fichiers"),
            (lambda d: d.update(phases="S1901M"), "phases"),
        ]
        for numero, (changement, fragment) in enumerate(cas):
            with self.subTest(cas=numero, fragment=fragment):
                self.setUp()
                self.modifier("manifeste.json", changement, manifeste=False)
                self.une_violation("manifeste.json", fragment)

    def test_sha_d_un_arbre_modifie_admis(self):
        self.modifier("manifeste.json", lambda d: d["attendus"].update(sha_code=SHA + "-modifie"), manifeste=False)
        self.assertEqual(self.violations(), [])

    # --- formes hostiles : une violation, jamais une trace

    def test_entier_de_400_chiffres(self):
        fichier = self.dossier / "tables" / "S1901M.json"
        fichier.write_text(fichier.read_text(encoding="utf-8").replace('"boost":3.0', '"boost":' + "9" * 400), encoding="utf-8")
        self.refaire_manifeste()
        self.une_violation("search.boost", "nombre fini attendu")

    def test_cinq_mille_listes_imbriquees(self):
        for relatif in ("historique.json", "tables/S1901M.json", "attendus/S1901M.json", "manifeste.json"):
            with self.subTest(fichier=relatif):
                self.setUp()
                (self.dossier / relatif).write_text("[" * 5000 + "]" * 5000, encoding="utf-8")
                if relatif != "manifeste.json":
                    self.refaire_manifeste()
                self.une_violation(relatif)

    def test_listes_imbriquees_dans_les_attendus(self):
        """Assez profond pour épuiser la pile du contrôle, pas celle du lecteur JSON."""
        profond = "[" * 900 + "]" * 900
        fichier = self.dossier / "attendus" / "S1901M.json"
        fichier.write_text('{"phase":"S1901M","attendus":{"FRANCE":{"D2":%s}}}' % profond, encoding="utf-8")
        self.refaire_manifeste()
        self.violations()  # ne lève pas

    def test_fichier_qui_n_est_pas_un_objet(self):
        for texte in ("[]", "3", '"S1901M"', "null", '{"phase":"S1901M","tables":[]}', '{"phase":"S1901M","tables":{"FRANCE":[]}}'):
            with self.subTest(texte=texte):
                self.setUp()
                (self.dossier / "tables" / "S1901M.json").write_text(texte, encoding="utf-8")
                self.refaire_manifeste()
                self.une_violation("tables/S1901M.json")

    def test_la_commande_ne_leve_pas_sur_une_forme_hostile(self):
        (self.dossier / "manifeste.json").write_text('{"fichiers":[{"chemin":[1],"octets":%s,"sha256":{}}]}' % ("9" * 400), encoding="utf-8")
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.assertEqual(reference_jeu.main(["controler", "--dossier", str(self.dossier), "--sans-emplacement"]), 1)
        self.assertIn("ÉCHEC : manifeste.json", sortie.getvalue())

    # --- liens symboliques

    def test_lien_symbolique_vers_un_fichier(self):
        ailleurs = self.racine / "ailleurs.json"
        shutil.move(str(self.dossier / "tables" / "S1901M.json"), str(ailleurs))
        os.symlink(str(ailleurs), str(self.dossier / "tables" / "S1901M.json"))
        self.une_violation("tables/S1901M.json", "lien symbolique")

    def test_lien_symbolique_vers_un_dossier(self):
        ailleurs = self.racine / "ailleurs"
        shutil.move(str(self.dossier / "tables"), str(ailleurs))
        os.symlink(str(ailleurs), str(self.dossier / "tables"))
        self.une_violation("tables", "lien symbolique")
        self.assertEqual([f for f in reference_jeu.fichiers_du_jeu(self.dossier) if f.startswith("tables/")], [])

    def test_dossier_qui_est_un_lien(self):
        lien = self.racine / "lien"
        os.symlink(str(self.dossier), str(lien))
        violations = reference_jeu.controler(lien)
        self.assertEqual(len(violations), 1)
        self.assertIn("lien symbolique", violations[0])
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.assertEqual(couche_d.main(["--jeu", str(lien)]), 1)
        self.assertIn("liens symboliques", sortie.getvalue())

    # --- plafond de taille

    def test_plafond_de_taille(self):
        lignes = [{"orders": ["A PAR - BUR", "A MAR - SPA", "F BRE - MAO"], "value": 0.123456, "prob": 0.01}] * 9000

        def gonfler(donnees):
            donnees["tables"]["FRANCE"]["candidates"] = lignes
        self.modifier("tables/S1901M.json", gonfler)
        self.assertGreater(sum(f.stat().st_size for f in self.dossier.rglob("*") if f.is_file()), 512 * 1024)
        self.une_violation("plafond 524288")

    def test_le_plafond_est_de_512_kio(self):
        self.assertEqual(reference_jeu.PLAFOND_OCTETS, 524288)

    # --- emplacement unique et forme du dossier

    def test_fichier_d_un_autre_type(self):
        for nom in ("notes.txt", "releve.jsonl", "tables/S1901M.jsonl", "tables/france.json", "autre/S1901M.json", "current_plans.json"):
            with self.subTest(nom=nom):
                self.setUp()
                (self.dossier / nom).parent.mkdir(exist_ok=True)
                (self.dossier / nom).write_text("{}", encoding="utf-8")
                self.refaire_manifeste()
                self.une_violation(nom, "n'est pas du format du jeu d'essai")

    def test_manifeste_absent(self):
        (self.dossier / "manifeste.json").unlink()
        self.une_violation("manifeste absent")

    def test_historique_absent(self):
        (self.dossier / "historique.json").unlink()
        self.refaire_manifeste()
        self.une_violation("historique des ordres absent")

    def test_fichier_modifie_sans_refaire_le_manifeste(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["search"].update(boost=2.0), manifeste=False)
        self.une_violation("tables/S1901M.json ne correspond plus au manifeste")

    def test_fichier_absent_du_manifeste(self):
        (self.dossier / "tables" / "S1902M.json").write_text(json.dumps({"phase": "S1902M", "tables": {}}), encoding="utf-8")
        self.une_violation("tables/S1902M.json est dans le dossier mais pas dans le manifeste")

    def test_partie_qui_n_est_pas_100_pour_cent_bots(self):
        self.modifier("manifeste.json", lambda d: d["partie"].update(nature="un humain, six bots"), manifeste=False)
        self.une_violation("partie.nature", "100 % bots")

    def test_phase_du_fichier(self):
        self.modifier("tables/S1901M.json", lambda d: d.update(phase="F1901M"))
        self.une_violation("n'est pas la phase du nom de fichier")

    def test_json_illisible(self):
        (self.dossier / "historique.json").write_text("{", encoding="utf-8")
        self.refaire_manifeste()
        self.une_violation("historique.json", "JSON illisible")


class Coherence(AvecJeu):
    """I1 à I3 (#40) : trois liens entre les arguments bruts d'export_plans, que la couche D ne rejoue pas.

    Chaque retouche est suivie de la commande `manifeste` (empreintes refaites) : seul le contenu est jugé.
    Les retouches sont celles du critère d'acceptation de l'issue ; elles sont rejouées sur une copie du jeu
    versionné par des essais en ligne de commande, hors batterie."""

    FICHIER, ICI = "tables/S1901M.json", "tables.FRANCE.export_plans"

    def retoucher(self, changement):
        """Applique `changement` aux arguments bruts de S1901M FRANCE, refait le manifeste ; rend les violations."""
        self.modifier(self.FICHIER, lambda d: changement(d["tables"]["FRANCE"]["export_plans"]))
        return self.violations()

    def invariants(self, violations):
        """Les invariants que nomment les violations, toutes portées par la table retouchée."""
        for violation in violations:
            self.assertTrue(violation.startswith("%s : %s." % (self.FICHIER, self.ICI)), violation)
        return sorted({violation.split(" : ")[2] for violation in violations})

    def test_le_jeu_fabrique_passe_et_ses_scores_sont_ceux_de_la_formule(self):
        self.assertEqual(self.violations(), [])
        arguments = self.table()["export_plans"]
        self.assertEqual(len(arguments["action_values"]), 11)
        self.assertEqual(len(arguments["prior_policy"]), 11)
        self.assertEqual((reference_jeu.TOLERANCE_SCORE, reference_jeu.PLANCHER_PROB_SCORE), (1e-12, 1e-6))

    def test_i1_score_plus_0_5(self):
        violations = self.retoucher(lambda e: e["action_values"][0].update(score=e["action_values"][0]["score"] + 0.5))
        self.assertEqual(len(violations), 1, violations)
        self.une_violation(self.FICHIER, self.ICI + ".action_values[0].score", "I1", "écart 0.5, tolérance 1e-12")

    def test_i1_tous_les_scores_a_zero(self):
        def a_zero(e):
            for action in e["action_values"]:
                action["score"] = 0.0

        violations = self.retoucher(a_zero)
        # Des scores tous égaux ne croissent pas : I2 passe, I1 refuse chacune des onze actions.
        self.assertEqual((len(violations), self.invariants(violations)), (11, ["I1"]))

    def test_i1_et_i2_scores_inverses_dans_l_ordre_de_la_liste(self):
        def inverser(e):
            scores = [action["score"] for action in e["action_values"]]
            for action, score in zip(e["action_values"], reversed(scores)):
                action["score"] = score

        violations = self.retoucher(inverser)
        self.assertEqual(self.invariants(violations), ["I1", "I2"])
        # Onze scores distincts : chacun, sauf le premier, dépasse le précédent ; celui du milieu garde sa place.
        self.assertEqual(sum(" : I2 : " in v for v in violations), 10)
        self.assertEqual(sum(" : I1 : " in v for v in violations), 10)
        self.une_violation(self.ICI + ".action_values[1].score", "I2", "dépasse le score de l'action précédente")

    def test_i1_et_i3_probabilite_d_une_action_fois_0_5(self):
        violations = self.retoucher(lambda e: e["action_values"][3].update(prob=e["action_values"][3]["prob"] * 0.5))
        self.assertEqual((len(violations), self.invariants(violations)), (2, ["I1", "I3"]))
        self.une_violation(self.ICI + ".action_values[3].score", "I1")
        self.une_violation(self.ICI + ".action_values[3].prob", "I3", "n'est pas la probabilité de prior_policy[")

    def test_i1_residu_d_une_valeur_sous_l_arrondi_de_l_export(self):
        violations = self.retoucher(lambda e: e["action_values"][3].update(value=e["action_values"][3]["value"] + 1e-7))
        self.assertEqual((len(violations), self.invariants(violations)), (1, ["I1"]))
        self.une_violation(self.ICI + ".action_values[3].score", "I1", "écart 1e-07")

    def test_i1_tolerance(self):
        score = self.table()["export_plans"]["action_values"][5]["score"]
        self.assertEqual(self.retoucher(lambda e: e["action_values"][5].update(score=score + 5e-13)), [])
        self.assertEqual(self.invariants(self.retoucher(lambda e: e["action_values"][5].update(score=score + 2e-12))), ["I1"])

    def test_i3_residu_d_une_probabilite_de_la_politique_d_avant(self):
        rang = self.table()["export_plans"]["prior_policy"][-1]["action"]
        violations = self.retoucher(lambda e: e["prior_policy"][-1].update(prob=e["prior_policy"][-1]["prob"] * 1.0000001))
        self.assertEqual((len(violations), self.invariants(violations)), (1, ["I3"]))
        # Le refus dit sa portée : l'égalité est celle d'une recherche sans engagement.
        self.une_violation("%s.action_values[%d].prob" % (self.ICI, rang), "I3", "prior_policy[10]",
                           "ne vaut que pour une table de recherche sans engagement (recherche A)")

    def test_i3_action_que_la_politique_d_avant_ne_designe_plus(self):
        rang = self.table()["export_plans"]["prior_policy"][-1]["action"]
        violations = self.retoucher(lambda e: e["prior_policy"].pop())
        self.assertEqual((len(violations), self.invariants(violations)), (1, ["I3"]))
        self.une_violation("%s.action_values[%d].prob" % (self.ICI, rang), "aucune ligne de prior_policy ne désigne cette action")

    def test_i3_refuse_un_jeu_de_recherches_avec_engagement(self):
        # Une table sur deux vient d'une recherche avec engagement : le renfort y a déplacé la probabilité
        # d'action_values, celle de prior_policy est d'avant renfort. Le jeu est refusé à l'écriture (reduire).
        lignes, historique = releves_fabriques(self.racine / "avec_engagement", engagements=True)
        releves = self.racine / "avec_engagement.jsonl"
        releves.write_text("".join(json.dumps(ligne) + "\n" for ligne in lignes), encoding="utf-8")
        tables, _ = reference_jeu.reduire_fichiers([releves])
        with self.assertRaises(reference_jeu.Refus) as refus:
            reference_jeu.construire_jeu(self.racine / "jeu_avec_engagement", historique, tables, MANIFESTE)
        violations = str(refus.exception).split("\n  ")[1:]
        self.assertTrue(violations and all(" : I3 : " in v and reference_jeu.SANS_ENGAGEMENT in v for v in violations), violations)
        # Les trois tables de rang impair (S1901M FRANCE, F1901M ENGLAND et TURKEY), et elles seules.
        self.assertEqual(sorted({" ".join(v.split(".export_plans")[0].split(" : ")) for v in violations}),
                         ["tables/F1901M.json tables.ENGLAND", "tables/F1901M.json tables.TURKEY", "tables/S1901M.json tables.FRANCE"])

    def test_des_arguments_mal_formes_ne_sont_pas_juges_sur_leur_coherence(self):
        # Une forme que le contrôle refuse déjà : sa violation, et ni trace ni I1 calculé sur une chaîne.
        violations = self.retoucher(lambda e: e["action_values"][0].update(prob="0.5"))
        self.assertEqual(len(violations), 1, violations)
        self.une_violation(self.ICI + ".action_values[0].prob", "nombre fini attendu")

    def test_i3_rang_hors_bornes(self):
        # Le rang ne désigne plus rien : l'action qu'il désignait n'a plus de ligne. Pas d'IndexError.
        rang = self.table()["export_plans"]["prior_policy"][0]["action"]
        violations = self.retoucher(lambda e: e["prior_policy"][0].update(action=99))
        self.assertEqual((len(violations), self.invariants(violations)), (1, ["I3"]))
        self.une_violation("%s.action_values[%d].prob" % (self.ICI, rang), "aucune ligne de prior_policy")

    def test_generer_refuse_une_table_incoherente(self):
        self.retoucher(lambda e: e["action_values"][0].update(score=e["action_values"][0]["score"] + 0.5))
        avant = {f: (self.dossier / f).read_bytes() for f in reference_jeu.fichiers_du_jeu(self.dossier)}
        code, sortie = self.generer()
        self.assertEqual(code, 2, sortie)
        self.assertIn("export_plans.action_values[0].score : I1", sortie)
        self.assertEqual({f: (self.dossier / f).read_bytes() for f in reference_jeu.fichiers_du_jeu(self.dossier)}, avant)


class Emplacement(AvecJeu):
    """Emplacement unique : une table de recherche hors de tests/reference/ est refusée."""

    attendus = False

    def emplacement(self, *fichiers):
        return reference_jeu.controler_emplacement(self.racine, list(fichiers))

    def ecrire(self, relatif, texte):
        (self.racine / relatif).parent.mkdir(parents=True, exist_ok=True)
        (self.racine / relatif).write_text(texte, encoding="utf-8")
        return relatif

    def test_le_jeu_a_sa_place_passe(self):
        self.assertEqual(self.emplacement(*("tests/reference/" + f for f in reference_jeu.fichiers_du_jeu(self.dossier))), [])

    def test_table_hors_du_dossier(self):
        copie = self.ecrire("tests/donnees/S1901M.json", (self.dossier / "tables" / "S1901M.json").read_text(encoding="utf-8"))
        violations = self.emplacement(copie)
        self.assertEqual(len(violations), 1)
        self.assertIn("tests/donnees/S1901M.json", violations[0])
        self.assertIn("emplacement unique", violations[0])

    def test_nom_non_imprimable_sur_une_seule_ligne(self):
        copie = self.ecrire("tests/donnees/S19\n01M.json", (self.dossier / "tables" / "S1901M.json").read_text(encoding="utf-8"))
        violations = self.emplacement(copie)
        self.assertEqual(len(violations), 1)
        self.assertNotIn("\n", violations[0])
        self.assertTrue(violations[0].startswith("'tests/donnees/S19\\n01M.json' : porte les clés"), violations[0])

    def test_dossier_au_nom_voisin(self):
        copie = self.ecrire("tests/reference2/tables/S1901M.json", (self.dossier / "tables" / "S1901M.json").read_text(encoding="utf-8"))
        self.assertEqual(len(self.emplacement(copie)), 1)

    def test_releve_brut(self):
        self.assertEqual(len(self.emplacement(self.ecrire("tests/mesure/m1.jsonl", json.dumps(self.lignes[0]) + "\n"))), 1)

    def test_current_plans(self):
        etat = {"3": {"S1901M": {"FRANCE": self.lignes[0]["entree"]}}}
        self.assertEqual(len(self.emplacement(self.ecrire("cicero/overlay/current_plans.json", json.dumps(etat)))), 1)

    def test_json_illisible_qui_nomme_les_quatre_cles(self):
        texte = '{"plans": [], "order_values": {}, "candidates": [], "search": {'
        self.assertEqual(len(self.emplacement(self.ecrire("a.json", texte))), 1)

    def test_json_sans_table(self):
        self.assertEqual(self.emplacement(
            self.ecrire(".claude/settings.json", json.dumps({"permissions": {"allow": ["search"]}, "plans": 1})),
            self.ecrire("a.jsonl", '{"plans": []}\n{"candidates": []}\n'),
            self.ecrire("table.py", "plans, order_values, candidates, search = 1, 2, 3, 4\n"),
        ), [])

    def test_la_commande_controler_appelle_le_controle_d_emplacement(self):
        """`controler` (celle de tests/verifier.sh) échoue sur une table hors du dossier, jeu conforme ou absent."""
        copie = self.ecrire("tests/donnees/S1901M.json", (self.dossier / "tables" / "S1901M.json").read_text(encoding="utf-8"))
        for dossier in (self.dossier, self.racine / "nulle_part"):
            arguments = ["controler", "--dossier", str(dossier), "--racine", str(self.racine)]
            sortie = io.StringIO()
            with mock.patch.object(reference_jeu, "fichiers_du_depot", lambda racine: [copie]) as _, contextlib.redirect_stdout(sortie):
                self.assertEqual(reference_jeu.main(arguments), 1)
                self.assertEqual(reference_jeu.main(arguments + ["--sans-emplacement"]), 0)
            self.assertIn("ÉCHEC : tests/donnees/S1901M.json", sortie.getvalue())
            self.assertIn("emplacement unique", sortie.getvalue())

    def test_la_commande_interroge_git_sur_la_racine_donnee(self):
        vus = []
        with mock.patch.object(reference_jeu, "fichiers_du_depot", lambda racine: vus.append(Path(racine)) or []), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(reference_jeu.main(["controler", "--dossier", str(self.dossier), "--racine", str(self.racine)]), 0)
        self.assertEqual(vus, [self.racine])

    def test_la_commande_hors_d_un_depot_git_rend_un_message(self):
        """`controler --racine` hors d'un dépôt git levait CalledProcessError (#38) : code 2, une ligne, pas de trace."""
        sortie = io.StringIO()
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.racine.parent)}), \
                contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = reference_jeu.main(["controler", "--dossier", str(self.dossier), "--racine", str(self.racine)])
            sans = reference_jeu.main(["controler", "--dossier", str(self.dossier), "--racine", str(self.racine), "--sans-emplacement"])
        lignes = sortie.getvalue().splitlines()
        self.assertEqual((code, sans), (2, 0), sortie.getvalue())
        self.assertTrue(lignes[0].startswith("REFUS : --racine %s : git n'y liste aucun fichier (" % self.racine), lignes[0])
        self.assertEqual(len(lignes), 2, lignes)  # le refus, puis la ligne du contrôle du seul dossier

    def test_le_depot_n_a_aucune_table_hors_de_tests_reference(self):
        self.assertEqual(reference_jeu.controler_emplacement(reference_jeu.RACINE), [])

    def test_le_depot_passe_le_controle(self):
        self.assertEqual(reference_jeu.controler(reference_jeu.DOSSIER), [])


class Noms(AvecJeu):
    """Deux tests sur les seuls noms : fichiers d'état d'une instance, extensions en liste fermée."""

    attendus = False

    def noms(self, *fichiers):
        return reference_jeu.controler_noms(self.racine, list(fichiers))

    def test_fichiers_d_etat_refuses(self):
        for relatif in ("logs/current_plans.json", "x/pseudo_commitments.json.bak", "claude_dialogue_state_3.json",
                        "current_plans_copie.json", "a/b/current_plans.jsonl", "pseudo_commitments.json.gz",
                        "claude_dialogue_state.json.tmp", "tests/reference/current_plans.json",
                        "tests/reference/tables/pseudo_commitments.json", "Current_Plans.JSON",
                        # Le nom d'état où qu'il soit dans le nom de base (décision du mainteneur, 2026-10-10).
                        "old_current_plans.json", "logs/2026-10-10_claude_dialogue_state.json",
                        "sauvegarde_pseudo_commitments.json.bak", " current_plans.json", "a/ current_plans.json",
                        "tests/test_current_plans.json", "x.json.current_plans"):
            violations = [v for v in self.noms(relatif) if "fichier d'état" in v]
            self.assertEqual(len(violations), 1, relatif)
            self.assertTrue(violations[0].startswith(relatif + " : "), violations[0])
            self.assertIn("décision 1", violations[0])

    def test_un_nom_d_etat_en_json_n_est_refuse_qu_a_ce_titre(self):
        self.assertEqual(len(self.noms("logs/current_plans.json")), 1)
        self.assertEqual(len(self.noms("x/pseudo_commitments.json.bak")), 2)  # le nom, et l'extension .bak

    def test_noms_voisins_admis(self):
        self.assertEqual(self.noms(
            "pseudo_commitments.py", "cicero/overlay/fairdiplomacy/utils/pseudo_commitments.py", "current_plans.md",
            "tests/test_pseudo_commitments.py", "plans.json", "current_plans/notes.md", "claude_dialogue_state.py",
        ), [])

    def test_hors_de_portee_d_un_test_sur_le_nom_de_base(self):
        """Limite écrite à côté de NOMS_D_ETAT : une autre graphie, ou le nom porté par le dossier, passent."""
        self.assertEqual(self.noms("claude-dialogue-state.json", "current_plans/3.json", "currentplans.json"), [])

    def test_le_depot_n_a_aucun_nom_d_etat_parmi_ses_fichiers_suivis(self):
        suivis = reference_jeu.fichiers_du_depot(reference_jeu.RACINE, suivis_seuls=True)
        self.assertTrue(suivis)
        self.assertEqual([f for f in suivis if reference_jeu.nom_d_etat(f)], [])

    def test_nom_non_imprimable_sur_une_seule_ligne(self):
        """Un retour à la ligne dans un nom ne coupe pas la ligne d'échec : le nom est rendu par son repr."""
        for relatif, titre in (("logs/a\nb.log", "extension .log"), ("a\ncurrent_plans.json", "fichier d'état"),
                               ("x/sans\textension", "nom sans extension"), ("a.l\nog", "extension '.l\\nog'")):
            violations = self.noms(relatif)
            self.assertEqual(len(violations), 1, relatif)
            self.assertNotIn("\n", violations[0])
            self.assertNotIn("\t", violations[0])
            self.assertTrue(violations[0].startswith(repr(relatif) + " : "), violations[0])
            self.assertIn(titre, violations[0])
        # Par la commande : une ligne « ÉCHEC » par violation, pas une de plus.
        sortie = io.StringIO()
        with mock.patch.object(reference_jeu, "fichiers_du_depot", lambda racine: ["logs/a\nb.log", "essai.log"]), \
                contextlib.redirect_stdout(sortie):
            self.assertEqual(reference_jeu.main(["controler", "--dossier", str(self.racine / "nulle_part"),
                                                 "--racine", str(self.racine)]), 1)
        self.assertEqual(sortie.getvalue().splitlines(), [
            "ÉCHEC : essai.log : " + self.noms("essai.log")[0].split(" : ", 1)[1],
            "ÉCHEC : 'logs/a\\nb.log' : " + self.noms("logs/a\nb.log")[0].split(" : ", 1)[1]])
        # Un nom imprimable s'écrit tel quel, espaces et accents compris.
        self.assertEqual(reference_jeu.nom_lisible("a b/é.log"), "a b/é.log")

    def test_extensions_refusees(self):
        for relatif, suffixe in (("releve.jsonl.gz", ".gz"), ("essai.log", ".log"), ("table.pkl", ".pkl"),
                                 ("tests/mesure/m1.jsonl", ".jsonl"), ("a/table.json.bak", ".bak"), ("base.sqlite", ".sqlite"),
                                 ("tests/reference/tables/S1901M.jsonl", ".jsonl"), ("table.JSON", ".JSON"),
                                 ("x.tar.gz", ".gz"), (".cache.bin", ".bin")):
            violations = self.noms(relatif)
            self.assertEqual(len(violations), 1, relatif)
            self.assertIn("%s : extension %s hors de la liste fermée" % (relatif, suffixe), violations[0])
            # Le message dit quoi faire d'une extension légitime.
            self.assertIn("ajouter son extension à EXTENSIONS_ADMISES (tests/reference_jeu.py) dans le commit qui l'introduit",
                          violations[0])

    def test_noms_sans_extension(self):
        self.assertEqual(self.noms("Dockerfile", "cicero/overlay/Dockerfile", "LICENSE", "NOTICE", ".gitignore",
                                   "a/.gitattributes", ".dockerignore"), [])
        for relatif in ("releve", "tests/mesure/table", ".env", "a/.secret", "Makefile"):
            violations = self.noms(relatif)
            self.assertEqual(len(violations), 1, relatif)
            self.assertIn("nom sans extension hors de la liste fermée", violations[0])
            self.assertIn("ajouter son nom à NOMS_SANS_EXTENSION", violations[0])

    def test_extension_d_un_nom(self):
        for nom, suffixe in (("a/b.c/d", ""), ("a.json", ".json"), ("a.json.bak", ".bak"), (".gitignore", ""),
                             (".a.b", ".b"), ("a.", "."), ("x/Dockerfile", "")):
            self.assertEqual(reference_jeu.extension(nom), suffixe, nom)
        self.assertEqual(len(self.noms("a.")), 1)

    def test_les_listes_sont_celles_du_depot(self):
        """Listes fermées : rien n'y figure qu'un fichier du dépôt ne porte (une entrée morte élargirait le contrôle).

        Sur les seuls fichiers suivis : un fichier de travail non suivi donnerait ici un écart d'ensembles qui ne
        le nomme pas ; c'est test_le_depot_n_a_aucun_nom_refuse qui le voit, et le nomme.
        """
        fichiers = reference_jeu.fichiers_du_depot(reference_jeu.RACINE, suivis_seuls=True)
        self.assertEqual({reference_jeu.extension(f) for f in fichiers} - {""}, set(reference_jeu.EXTENSIONS_ADMISES))
        self.assertEqual({f.rsplit("/", 1)[-1] for f in fichiers if not reference_jeu.extension(f)},
                         set(reference_jeu.NOMS_SANS_EXTENSION))

    def test_le_depot_n_a_aucun_nom_refuse(self):
        self.assertEqual(reference_jeu.controler_noms(reference_jeu.RACINE), [])

    def test_le_jeu_a_sa_place_passe(self):
        self.assertEqual(self.noms(*("tests/reference/" + f for f in reference_jeu.fichiers_du_jeu(self.dossier))), [])

    def test_fichier_non_suivi_non_ignore(self):
        """La liste contrôlée est celle du contrôle d'emplacement : suivis, et non suivis non ignorés."""
        git = depot_git(self.racine)
        (self.racine / "logs").mkdir()
        (self.racine / "logs" / "current_plans.json").write_text("{}\n", encoding="utf-8")
        (self.racine / "essai.log").write_text("", encoding="utf-8")
        (self.racine / "ignore.log").write_text("", encoding="utf-8")
        (self.racine / ".gitignore").write_text("ignore.log\n", encoding="utf-8")
        with mock.patch.dict(os.environ, git.env, clear=True):
            violations = reference_jeu.controler_noms(self.racine)
        self.assertEqual([v.split(" : ")[0] for v in violations], ["essai.log", "logs/current_plans.json"])

    def test_fichiers_suivis_seuls(self):
        """`suivis_seuls` écarte le fichier de travail non suivi, que la liste par défaut garde."""
        git = depot_git(self.racine)
        (self.racine / "essai.log").write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, git.env, clear=True):
            tous = reference_jeu.fichiers_du_depot(self.racine)
            suivis = reference_jeu.fichiers_du_depot(self.racine, suivis_seuls=True)
        self.assertEqual(set(tous) - set(suivis), {"essai.log"})
        self.assertIn("tests/harnais.py", suivis)

    def test_la_commande_controler_appelle_le_controle_des_noms(self):
        """`controler` (celle de tests/verifier.sh) échoue sur un nom refusé, jeu conforme ou absent ; git interrogé une fois."""
        for dossier in (self.dossier, self.racine / "nulle_part"):
            arguments = ["controler", "--dossier", str(dossier), "--racine", str(self.racine)]
            sortie, vus = io.StringIO(), []
            with mock.patch.object(reference_jeu, "fichiers_du_depot",
                                   lambda racine: vus.append(racine) or ["essai.log", "x/pseudo_commitments.json.bak"]), \
                    contextlib.redirect_stdout(sortie):
                self.assertEqual(reference_jeu.main(arguments), 1)
                self.assertEqual(len(vus), 1)
                self.assertEqual(reference_jeu.main(arguments + ["--sans-emplacement"]), 0)
            self.assertIn("ÉCHEC : essai.log : extension .log", sortie.getvalue())
            self.assertIn("ÉCHEC : x/pseudo_commitments.json.bak : nom d'un fichier d'état", sortie.getvalue())


# ---------------------------------------------------------------------------
# Couche D
# ---------------------------------------------------------------------------

class CoucheD(AvecJeu):
    def jeu(self):
        return reference_jeu.lire_jeu(self.dossier)

    def test_reference_absente_ou_vide(self):
        """Rien n'est comparé, la commande le dit et n'échoue pas."""
        (self.racine / "vide").mkdir()
        for dossier in (self.racine / "nulle_part", self.racine / "vide"):
            sortie = io.StringIO()
            with contextlib.redirect_stdout(sortie):
                self.assertEqual(couche_d.main(["--jeu", str(dossier)]), 0)
            self.assertIn("absent ou vide, rien n'est comparé", sortie.getvalue())

    def test_le_jeu_fabrique_concorde_avec_ses_attendus(self):
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("6 table(s)", sortie)
        self.assertIn("0 différence(s) (aucune)", sortie)
        self.assertNotIn("D1 inactive", sortie)

    def test_les_attendus_passent_le_controle(self):
        self.assertEqual(self.violations(), [])

    def test_toutes_les_couches_sont_calculees(self):
        obtenu = couche_d.calculer(self.jeu())
        for phase, puissance in itertools.product(PHASES, PUISSANCES):
            self.assertEqual(sorted(obtenu[phase][puissance]), sorted(couche_d.COUCHES))
            self.assertNotIn("erreur", json.dumps(obtenu[phase][puissance]))

    def test_les_scenarios_couvrent_les_cas_annonces(self):
        """Sur le jeu fabriqué : chaque verdict de D3, une trahison acceptée et une refusée en D5, D6 résolue."""
        obtenu = couche_d.calculer(self.jeu())
        verdicts, balises, resolues = set(), set(), set()
        for tables in obtenu.values():
            for grandeurs in tables.values():
                verdicts.update(v[0] for nouveaux in grandeurs["D3"]["label"].values() for v in nouveaux.values())
                verdicts.update(grandeurs["D3"]["sans_label"])
                verdicts.update(grandeurs["D3"]["sans_table"])
                for message in grandeurs["D5"]["cycle"]["messages"]:
                    balises.update(message["balises"])
                resolues.update(grandeurs["D6"][sens]["resolue"] for sens in ("recus", "propres"))
                self.assertGreater(grandeurs["D6"]["recus"]["kept"], 0)
                self.assertGreater(grandeurs["D6"]["propres"]["broken"], 0)
        self.assertEqual(verdicts, {"superseded", "below_margin", "not_played", "undeclared", "unknown_value"})
        self.assertLessEqual({"double-deal", "betrayal", "betrayal-refused", "betrayal-ignored", "revision"}, balises)
        self.assertEqual(resolues, {True})

    def test_d3_le_gain_d_une_trahison_acceptee_est_enregistre(self):
        """Un verdict `superseded` porte son gain, celui de _reject_contradictions, au-dessus de la marge."""
        table = self.table()
        label = couche_d.calculer(self.jeu())["S1901M"]["FRANCE"]["D3"]["label"]
        acceptes = [(a, n, v[1]) for a, nouveaux in label.items() for n, v in nouveaux.items() if v[0] == "superseded"]
        self.assertTrue(acceptes)
        for ancien, nouveau, gain in acceptes:
            self.assertEqual(gain, round(table["order_values"][nouveau] - table["order_values"][ancien], 5))
            self.assertGreater(gain, banc.bot.COMMITMENT_SWITCH_MARGIN)
        # Et il est comparé : le changer dans les attendus est une différence de D3.
        enregistres = json.loads((self.dossier / "attendus" / "S1901M.json").read_text(encoding="utf-8"))["attendus"]["FRANCE"]["D3"]["label"]
        unite = next(i for i, u in enumerate(enregistres) if "superseded" in u)
        rang = enregistres[unite]["superseded"][0]
        self.assertGreater(enregistres[unite]["gains"][rang], banc.bot.COMMITMENT_SWITCH_MARGIN)

        def changer(donnees):
            donnees["attendus"]["FRANCE"]["D3"]["label"][unite]["gains"][rang] += 0.001
        self.modifier("attendus/S1901M.json", changer)
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn("1 différence(s) (D3 : 1)", sortie)

    def test_d5_deux_detenteurs_deux_trahisons_au_journal(self):
        """La même promesse faite à deux puissances puis trahie : une ligne [betrayal] par détenteur."""
        obtenu = couche_d.calculer(self.jeu())
        vus = 0
        for phase, puissance in itertools.product(PHASES, PUISSANCES):
            cycle = obtenu[phase][puissance]["D5"]["deux_detenteurs"]
            premier, second, troisieme = couche_d.interlocuteurs(puissance, 3)
            self.assertEqual([m["expediteur"] for m in cycle["messages"]], [premier, second, troisieme])
            self.assertEqual(cycle["messages"][0]["sincere"], cycle["messages"][1]["sincere"])
            dernier = cycle["messages"][2]
            if "superseded" in dernier["retour"]:
                vus += 1
                self.assertEqual(dernier["balises"]["betrayal"], 2)
                self.assertEqual([ligne[0] for ligne in dernier["retour"]["superseded"]], [premier, second])
                self.assertEqual(cycle["by_recipient"], {premier: [], second: [], troisieme: dernier["sincere"]})
                self.assertEqual(cycle["fichier"], dernier["sincere"])
        self.assertGreater(vus, 0)

    def test_d3_deux_trahisons_dans_un_message(self):
        """Deux unités, deux labels dans le même message : jugées ensemble (rejugement), et le retour est enregistré."""
        obtenu = couche_d.calculer(self.jeu())
        verdicts = set()
        for phase, puissance in itertools.product(PHASES, PUISSANCES):
            deux = obtenu[phase][puissance]["D3"]["deux_trahisons"]
            self.assertEqual(len(deux["sincere"]), 2)
            self.assertEqual(len({banc.get_unit_location(o) for o in deux["sincere"]}), 2)
            self.assertEqual([banc.get_unit_location(o) for o in deux["betray"]], [banc.get_unit_location(o) for o in deux["sincere"]])
            juges = sum(len(lignes) for cle, lignes in deux["retour"].items() if cle != "accepted")
            self.assertEqual(juges, 2, deux["retour"])
            verdicts.update(cle for cle in deux["retour"] if cle != "accepted")
        self.assertIn("superseded", verdicts)

    def test_les_scenarios_sont_relus_des_attendus(self):
        """Une mutation qui change les verdicts de D3 ne change pas la suite jouée par D5 : seul le comportement bouge."""
        jeu = self.jeu()
        marge = next(m for m in couche_d.MUTATIONS if m[0].startswith("marge"))
        mutant = couche_d.charger_modules([("bot", marge[2], "COMMITMENT_SWITCH_MARGIN = 0.5\n")])
        obtenu = couche_d.calculer(jeu, mutant)
        for phase, puissance in itertools.product(PHASES, PUISSANCES):
            enregistre = couche_d.scenarios_enregistres(jeu["attendus"][phase][puissance])
            self.assertEqual(sorted(enregistre), ["cycle", "deux_detenteurs", "deux_trahisons"])
            rejoue = couche_d.scenarios_enregistres(obtenu[phase][puissance])
            self.assertEqual(rejoue, enregistre)
            # À la génération, en revanche, les scénarios se choisissent sur les verdicts du moment.
        neuf = couche_d.calculer(jeu, mutant, scenarios_fixes=False)
        self.assertNotEqual(
            [couche_d.scenarios_enregistres(neuf[ph][p]) for ph, p in itertools.product(PHASES, PUISSANCES)],
            [couche_d.scenarios_enregistres(jeu["attendus"][ph][p]) for ph, p in itertools.product(PHASES, PUISSANCES)],
        )
        lignes, _, _ = couche_d.comparer(couche_d.attendus_complets(jeu), obtenu)
        entrees = [l for l in lignes if l[3].endswith(("/expediteur", "/sincere", "/betray")) or "/sincere/" in l[3] or "/betray/" in l[3]]
        self.assertEqual(entrees, [])
        self.assertTrue(any(l[0] == "D5" for l in lignes))

    def test_jeu_non_vide_sans_table(self):
        """Un jeu dont aucune table n'est comparée fait échouer la couche D : elle ne se tait que sur un dossier vide."""
        shutil.rmtree(str(self.dossier / "tables"))
        shutil.rmtree(str(self.dossier / "attendus"))
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn("n'est pas vide mais aucune table n'y est comparée", sortie)

    def test_un_manifeste_raccourci_ne_retire_aucune_table(self):
        for changement in (lambda d: d.update(phases=[]), lambda d: d.update(puissances=["ENGLAND"])):
            self.setUp()
            self.modifier("manifeste.json", changement, manifeste=False)
            code, sortie = self.lancer()
            self.assertEqual(code, 0, sortie)
            self.assertIn("Couche D : 6 table(s)", sortie)
            self.assertTrue(self.violations())

    def test_jeu_illisible(self):
        (self.dossier / "manifeste.json").unlink()
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn("jeu d'essai illisible", sortie)

    def test_d2_les_cinq_jeux_de_promesses(self):
        table = self.table()
        jeux = couche_d.jeux_de_promesses(table)
        tete = table["plans"][0]["orders"]
        joues = {o for c in table["candidates"] for o in c["orders"]}
        self.assertEqual(list(jeux), ["aucune", "prefere", "alternative", "deux", "absent"])
        self.assertEqual(jeux["aucune"], [])
        self.assertEqual(len(jeux["prefere"]), 1)
        self.assertIn(jeux["prefere"][0], tete)
        self.assertEqual(len(jeux["alternative"]), 1)
        self.assertNotIn(jeux["alternative"][0], tete)
        self.assertIn(jeux["alternative"][0], joues)
        self.assertEqual(len(jeux["deux"]), 2)
        self.assertEqual(len({banc.get_unit_location(o) for o in jeux["deux"]}), 2)
        self.assertNotIn(jeux["absent"][0], joues)

    def test_d1_inactive_sans_arguments(self):
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"].pop("export_plans"))
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("D1 inactive pour 1 table(s) sur 6", sortie)
        self.assertNotIn("D1", couche_d.calculer(self.jeu())["S1901M"]["FRANCE"])

    def test_d1_rejoue_l_export_sur_ses_arguments(self):
        """Un argument brut modifié : l'export rejoué n'est plus la table, et D1 le dit."""
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["export_plans"]["action_values"][0].update(value=0.9))
        code, sortie = self.lancer("--tout")
        self.assertEqual(code, 1)
        self.assertRegex(sortie, r"D1 \| S1901M \| FRANCE \| plans/0/value \| [0-9.]+ \| 0\.9\n")
        self.assertRegex(sortie, r"D1 : \d+\)")
        self.assertNotIn("D2 :", sortie)

    def test_jeu_sans_attendus(self):
        (self.dossier / "attendus" / "S1901M.json").unlink()
        self.refaire_manifeste()
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn("attendus absents pour 3 table(s)", sortie)

    def test_une_difference_s_affiche_grandeur_par_grandeur(self):
        """Avant et après, une ligne par grandeur : ici un gain et un verdict de D3 changés dans les attendus."""
        def changer(donnees):
            unite = donnees["attendus"]["FRANCE"]["D3"]["label"][0]
            unite["gains"][0] = 0.77777
            donnees["attendus"]["FRANCE"]["D6"]["recus"]["kept"] += 1
        self.modifier("attendus/S1901M.json", changer)
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn("2 différence(s) (D3 : 1, D6 : 1)", sortie)
        self.assertIn("couche | phase | puissance | grandeur | avant | après", sortie)
        self.assertRegex(sortie, r"D3 \| S1901M \| FRANCE \| label/[AF] [A-Z]{3} [^/]+/[AF] [A-Z]{3} [^/]+/1 \| 0\.77777 \| -?[0-9.e-]+\n")
        self.assertRegex(sortie, r"D6 \| S1901M \| FRANCE \| recus/kept \| \d+ \| \d+\n")
        self.assertIn("ne se régénère qu'après visa", sortie)

    def test_sortie_json_des_differences(self):
        self.modifier("attendus/S1901M.json", lambda d: d["attendus"]["FRANCE"]["D4"]["consigne"].update(empreinte="0" * 16))
        fichier = self.racine / "differences.json"
        self.assertEqual(self.lancer("--sortie", str(fichier))[0], 1)
        lignes = json.loads(fichier.read_text(encoding="utf-8"))
        self.assertEqual([(l["couche"], l["grandeur"], l["avant"]) for l in lignes], [("D4", "consigne/empreinte", "0" * 16)])

    def test_tolerance_des_flottants(self):
        self.assertEqual(couche_d.differences({"a": [0.1, 1]}, {"a": [0.1 * (1 + 1e-13), 1.0]}), [])
        self.assertEqual(couche_d.differences(0.1, 0.1 * (1 + 1e-9)), [("", 0.1, 0.1 * (1 + 1e-9))])
        self.assertEqual(couche_d.differences(0.0, 1e-300), [("", 0.0, 1e-300)])
        self.assertEqual(couche_d.differences({"a": 1}, {"a": True}), [("a", 1, True)])
        self.assertEqual(couche_d.differences({"a": 1}, {"b": 2}), [("a", 1, couche_d.ABSENT), ("b", couche_d.ABSENT, 2)])
        self.assertEqual(couche_d.differences([1, 2], [1]), [("", [1, 2], [1])])
        self.assertEqual(couche_d.differences(None, None), [])

    def test_d3_range_puis_deplie_sans_perte(self):
        obtenu = couche_d.calculer(self.jeu())["S1901M"]["FRANCE"]["D3"]["label"]
        self.assertEqual(couche_d._desserrer_d3(couche_d._serrer_d3(obtenu)), obtenu)

    def test_generer_refuse_d_ecrire_une_erreur(self):
        with mock.patch.object(couche_d, "d2", side_effect=ValueError("panne")):
            code, sortie = self.generer()
        self.assertEqual(code, 2)
        self.assertIn("D2 S1901M ENGLAND : ValueError: panne", sortie)
        self.assertEqual(self.lancer()[0], 0)  # les attendus d'avant sont intacts

    def test_generer_montre_ce_qu_il_ecrase(self):
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("Attendus écrasés : aucune grandeur ne change.", sortie)
        self.modifier("attendus/S1901M.json", lambda d: d["attendus"]["FRANCE"]["D6"]["recus"].update(kept=99))
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("Attendus écrasés : 1 grandeur(s) changent (D6 : 1).", sortie)
        self.assertRegex(sortie, r"D6 \| S1901M \| FRANCE \| recus/kept \| 99 \| \d+\n")
        self.assertEqual(self.lancer()[0], 0)

    def test_generer_refuse_un_arbre_modifie(self):
        avant = (self.dossier / "manifeste.json").read_bytes()
        sortie = io.StringIO()
        with mock.patch.object(couche_d, "arbre_modifie", lambda: [" M cicero/overlay/claude_dialogue_bot.py", "?? tests/x.py"]), \
                mock.patch.object(couche_d, "sha_du_depot", lambda: "ab" * 20), \
                contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            self.assertEqual(couche_d.main(["--jeu", str(self.dossier), "--generer"]), 2)
            self.assertIn("arbre de travail modifié", sortie.getvalue())
            self.assertIn("M cicero/overlay/claude_dialogue_bot.py", sortie.getvalue())
            self.assertEqual((self.dossier / "manifeste.json").read_bytes(), avant)
            self.assertEqual(couche_d.main(["--jeu", str(self.dossier), "--generer", "--arbre-modifie"]), 0)
        manifeste = json.loads((self.dossier / "manifeste.json").read_text(encoding="utf-8"))
        self.assertEqual(manifeste["attendus"]["sha_code"], "ab" * 20 + "-modifie")
        self.assertEqual(self.violations(), [])

    def test_generer_sans_git_demande_le_sha(self):
        sortie = io.StringIO()
        with mock.patch.object(couche_d, "arbre_modifie", lambda: None), mock.patch.object(couche_d, "sha_du_depot", lambda: None), \
                contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            self.assertEqual(couche_d.main(["--jeu", str(self.dossier), "--generer"]), 2)
            self.assertIn("donner --sha", sortie.getvalue())
            self.assertEqual(couche_d.main(["--jeu", str(self.dossier), "--generer", "--sha", "cd" * 20]), 0)
        manifeste = json.loads((self.dossier / "manifeste.json").read_text(encoding="utf-8"))
        self.assertEqual(manifeste["attendus"]["sha_code"], "cd" * 20)

    def test_l_etat_du_depot_se_lit_sans_y_ecrire(self):
        """git n'est appelé qu'en lecture, sans verrou facultatif ; jamais par la comparaison."""
        appels = []

        def git(commande, **options):
            appels.append(commande)
            return mock.Mock(returncode=0, stdout=b" M tests/verifier.sh\n")
        with mock.patch.object(couche_d.subprocess, "run", git):
            self.assertEqual(couche_d.arbre_modifie(), [" M tests/verifier.sh"])
            couche_d.sha_du_depot()
            self.lancer()
        self.assertEqual(len(appels), 2)
        for commande in appels:
            self.assertEqual(commande[:2], ["git", "--no-optional-locks"])
            self.assertIn(commande[4], ("status", "rev-parse"))
        with mock.patch.object(couche_d.subprocess, "run", side_effect=OSError("pas de git")):
            self.assertIsNone(couche_d.arbre_modifie())
            self.assertIsNone(couche_d.sha_du_depot())

    def test_l_arbre_controle_exclut_le_jeu_d_essai(self):
        """Les quatre cas, sur un vrai dépôt : seul ce qui est hors de tests/reference/ compte."""
        git = depot_git(self.racine)
        self.assertEqual(self.arbre(git), [])
        (self.dossier / "non_suivi.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(self.arbre(git), [])
        with (self.dossier / "manifeste.json").open("a", encoding="utf-8") as f:
            f.write("\n")
        self.assertEqual(self.arbre(git), [])
        (self.racine / "tests" / "reference_voisin.py").write_text("", encoding="utf-8")
        self.assertEqual(self.arbre(git), ["?? tests/reference_voisin.py"])
        (self.racine / "tests" / "reference_voisin.py").unlink()
        (self.racine / "tests" / "harnais.py").write_text("harnais = 2\n", encoding="utf-8")
        (self.racine / "cicero" / "overlay" / "bot.py").write_text("bot = 2\n", encoding="utf-8")
        (self.racine / "ailleurs.md").write_text("hors des mesures\n", encoding="utf-8")
        self.assertEqual(self.arbre(git), [" M cicero/overlay/bot.py", " M tests/harnais.py"])
        (self.racine / "tests" / "harnais.py").write_text("harnais = 1\n", encoding="utf-8")
        (self.racine / "cicero" / "overlay" / "bot.py").write_text("bot = 1\n", encoding="utf-8")
        self.assertEqual(self.arbre(git), [])
        # Renommage à cheval, dans un sens puis dans l'autre : vu par son côté contrôlé.
        git("mv", "tests/harnais.py", "tests/reference/harnais.py")
        self.assertEqual(self.arbre(git), ["D  tests/harnais.py"])
        git("mv", "tests/reference/harnais.py", "tests/harnais.py")
        git("mv", "tests/reference/manifeste.json", "tests/manifeste.json")
        self.assertEqual(self.arbre(git), ["AM tests/manifeste.json"])

    def test_un_fichier_non_suivi_est_vu_malgre_le_reglage_de_l_appelant(self):
        """status.showUntrackedFiles=no, dans la configuration de l'appelant, ne cache pas un harnais non suivi."""
        git = depot_git(self.racine)
        reglages = self.racine.parent / "gitconfig"
        reglages.write_text("[status]\n\tshowUntrackedFiles = no\n", encoding="utf-8")
        git.env["GIT_CONFIG_GLOBAL"] = str(reglages)
        (self.racine / "tests" / "nouveau.py").write_text("", encoding="utf-8")
        self.assertEqual(git("status", "--porcelain"), "")  # le réglage est bien lu : git, sans l'argument, ne dit rien
        self.assertEqual(self.arbre(git), ["?? tests/nouveau.py"])

    def test_le_depot_d_essai_ignore_les_ignores_de_l_appelant(self):
        """Un git/ignore global (XDG_CONFIG_HOME ou ~/.config) qui nomme un fichier du test ne le cache pas."""
        foyer = self.racine.parent / "appelant"
        for dossier in (foyer / "xdg" / "git", foyer / ".config" / "git"):
            dossier.mkdir(parents=True)
            (dossier / "ignore").write_text("nouveau.py\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HOME": str(foyer), "XDG_CONFIG_HOME": str(foyer / "xdg")}):
            git = depot_git(self.racine)
        (self.racine / "tests" / "nouveau.py").write_text("", encoding="utf-8")
        self.assertEqual(self.arbre(git), ["?? tests/nouveau.py"])

    def test_les_textes_de_d4(self):
        code, sortie = self.lancer("--textes", "S1901M", "france")
        self.assertEqual(code, 0)
        self.assertIn("=== plan (", sortie)
        self.assertIn("Your current plan (PRIVATE", sortie)
        self.assertIn("Promises you have already made this phase", sortie)
        self.assertIn("You are playing FRANCE in a game of Diplomacy", sortie)

    def test_aucun_texte_dans_les_attendus(self):
        for fichier in (self.dossier / "attendus").iterdir():
            texte = fichier.read_text(encoding="utf-8")
            for interdit in ("Your current plan", "Promises you", "You are playing", "entendu", "bonjour"):
                self.assertNotIn(interdit, texte)


class Sequence(AvecJeu):
    """La séquence de la campagne sur un vrai dépôt git : jeu posé (non suivi), puis --generer, sans rien commiter entre."""

    attendus = False

    def setUp(self):
        super().setUp()
        shutil.rmtree(str(self.dossier))  # le dépôt est commité sans jeu d'essai, comme avant la campagne
        self.git = depot_git(self.racine)
        self.sha = self.git("rev-parse", "HEAD").strip()
        shutil.copytree(str(gabarit()["sans"] / "tests" / "reference"), str(self.dossier))

    def generer(self, *options):
        """(code, sortie) de --generer, git non doublé : seule la racine du dépôt est déplacée."""
        sortie = io.StringIO()
        with mock.patch.object(couche_d, "RACINE", self.racine), mock.patch.dict(os.environ, self.git.env, clear=True), \
                contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = couche_d.main(["--jeu", str(self.dossier), "--generer", "--date", "2026-01-01"] + list(options))
        return code, sortie.getvalue()

    def test_generer_apres_reduire_sans_rien_commiter(self):
        self.assertIn("?? tests/reference/", self.git("status", "--porcelain"))
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)
        manifeste = json.loads((self.dossier / "manifeste.json").read_text(encoding="utf-8"))
        self.assertEqual(manifeste["attendus"]["sha_code"], self.sha)
        self.assertEqual(reference_jeu.controler(self.dossier), [])
        self.assertEqual(self.lancer()[0], 0)
        # Une seconde génération, attendus déjà posés et toujours non suivis : même réponse.
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)
        self.assertIn("Attendus écrasés : aucune grandeur ne change.", sortie)

    def etat_du_jeu(self):
        return {f: (self.dossier / f).read_bytes() for f in reference_jeu.fichiers_du_jeu(self.dossier)}

    def test_generer_accepte_un_jeu_fraichement_reduit(self):
        """Cas (i) : sans attendus, le manifeste ne liste que l'historique et les tables ; le contrôle du jeu passe."""
        self.assertFalse((self.dossier / "attendus").exists())
        self.assertEqual(reference_jeu.controler(self.dossier), [])
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)
        self.assertNotIn("REFUS", sortie)

    def test_generer_accepte_une_seconde_generation(self):
        """Cas (ii) : le manifeste porte l'empreinte des attendus, et --generer l'a refait : il leur est fidèle."""
        self.assertEqual(self.generer()[0], 0)
        manifeste = json.loads((self.dossier / "manifeste.json").read_text(encoding="utf-8"))
        self.assertTrue([f for f in manifeste["fichiers"] if f["chemin"].startswith("attendus/")])
        avant = self.etat_du_jeu()
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(self.etat_du_jeu(), avant)

    def test_generer_refuse_une_table_modifiee_a_la_main(self):
        """Cas (iii) : après génération, une table retouchée n'est pas entérinée par de nouvelles empreintes."""
        self.assertEqual(self.generer()[0], 0)
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["plans"][0].update(value=0.123456), manifeste=False)
        avant = self.etat_du_jeu()
        for options in ((), ("--arbre-modifie",)):
            code, sortie = self.generer(*options)
            self.assertEqual(code, 2, sortie)
            self.assertIn("REFUS : le jeu d'essai", sortie)
            self.assertIn("tables/S1901M.json ne correspond plus au manifeste", sortie)
            self.assertIn("Si la modification est voulue, refaire d'abord le manifeste : python3 tests/reference_jeu.py "
                          "manifeste --dossier %s (session principale, après visa), puis relancer --generer." % self.dossier,
                          sortie)
            self.assertNotIn("supprimer", sortie)
            self.assertEqual(self.etat_du_jeu(), avant)
        self.assertTrue(reference_jeu.controler(self.dossier))
        # La modification voulue passe par la commande nommée : elle se voit alors dans le diff du manifeste.
        self.assertEqual(reference_jeu.main(["manifeste", "--dossier", str(self.dossier)]), 0)
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)

    def test_generer_refuse_des_attendus_modifies_a_la_main(self):
        """Des attendus retouchés : le refus donne le chemin en trois temps, et ce chemin aboutit."""
        self.assertEqual(self.generer()[0], 0)
        fichier = self.dossier / "attendus" / "S1901M.json"
        fichier.write_text(fichier.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        avant = self.etat_du_jeu()
        code, sortie = self.generer()
        self.assertEqual(code, 2, sortie)
        self.assertIn("REFUS : le jeu d'essai", sortie)
        self.assertIn("attendus/S1901M.json ne correspond plus au manifeste", sortie)
        self.assertIn("en trois temps (session principale, après visa) : 1) supprimer %s ; 2) python3 tests/reference_jeu.py "
                      "manifeste --dossier %s ; 3) relancer --generer." % (self.dossier / "attendus", self.dossier), sortie)
        self.assertNotIn("Si la modification est voulue", sortie)
        self.assertEqual(self.etat_du_jeu(), avant)
        # Le chemin annoncé, pas à pas.
        shutil.rmtree(str(self.dossier / "attendus"))
        self.assertEqual(reference_jeu.main(["manifeste", "--dossier", str(self.dossier)]), 0)
        self.assertEqual(reference_jeu.controler(self.dossier), [])
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(reference_jeu.controler(self.dossier), [])
        self.assertEqual(self.lancer()[0], 0)
        # Le manifeste seul, lui, n'aurait pas suffi pour une clé non admise dans les attendus.
        self.modifier("attendus/S1901M.json", lambda d: d["attendus"]["FRANCE"].update(bavardage=1))
        code, sortie = self.generer()
        self.assertEqual(code, 2, sortie)
        self.assertIn("clé hors liste blanche : 'bavardage'", sortie)
        self.assertIn("1) supprimer", sortie)

    def trois_temps(self):
        """Le chemin du second message, exécuté ; rend (code de --generer, violations restantes)."""
        if (self.dossier / "attendus").exists():
            shutil.rmtree(str(self.dossier / "attendus"))
        self.assertEqual(reference_jeu.main(["manifeste", "--dossier", str(self.dossier)]), 0)
        return self.generer()[0], reference_jeu.controler(self.dossier)

    def test_les_trois_temps_ne_levent_pas_un_fichier_en_trop_ni_manquant(self):
        """La réserve du second message, mesurée : fichier hors format à la racine du jeu, puis table supprimée."""
        self.assertEqual(self.generer()[0], 0)
        (self.dossier / "notes.txt").write_text("a\n", encoding="utf-8")
        code, sortie = self.generer()
        self.assertEqual(code, 2, sortie)
        self.assertIn("notes.txt", sortie)
        self.assertIn("un fichier en trop ou manquant, ou le contenu d'une table ou de l'historique, se corrige d'abord "
                      "dans le dossier", sortie)
        code, violations = self.trois_temps()
        self.assertEqual(code, 2)
        self.assertTrue(any("notes.txt" in v and "pas du format" in v for v in violations), violations)
        # Corrigé dans le dossier, le même chemin aboutit.
        (self.dossier / "notes.txt").unlink()
        self.assertEqual(self.trois_temps(), (0, []))
        # Une table supprimée : le manifeste refait nomme encore sa phase, et rien ne la recrée.
        (self.dossier / "tables" / "F1901M.json").unlink()
        code, sortie = self.generer()
        self.assertEqual(code, 2, sortie)
        self.assertIn("1) supprimer", sortie)
        code, violations = self.trois_temps()
        self.assertEqual(code, 2)
        self.assertEqual(violations, ["manifeste.json : phases : ne sont pas exactement celles des fichiers de tables/ (S1901M)"])

    def test_les_deux_messages_du_refus(self):
        """Une table ou l'historique retouchés seuls : la commande `manifeste` ; tout autre cas : les trois temps."""
        perime = "manifeste.json : fichiers : %s ne correspond plus au manifeste (taille ou empreinte) : refaire le manifeste"
        d = Path("D")
        for violations in ([perime % "tables/S1901M.json"], [perime % "historique.json"],
                           [perime % "historique.json", perime % "tables/F1901M.json"]):
            message = couche_d.refus_du_jeu(d, violations)
            self.assertIn("(%d violation(s), dont : %s)" % (len(violations), violations[0]), message)
            self.assertIn("Si la modification est voulue", message)
            self.assertNotIn("supprimer", message)
        autre = "tables/S1901M.json : tables.FRANCE : clé hors liste blanche : 'bavardage'"
        for violations, citee in (
            ([perime % "attendus/S1901M.json"], perime % "attendus/S1901M.json"),
            # Table et attendus retouchés ensemble : la violation citée est celle qui fait changer de cas.
            ([perime % "tables/S1901M.json", perime % "attendus/S1901M.json"], perime % "attendus/S1901M.json"),
            ([autre], autre),
            (["manifeste.json : fichiers : notes.txt est dans le dossier mais pas dans le manifeste"],
             "manifeste.json : fichiers : notes.txt est dans le dossier mais pas dans le manifeste"),
        ):
            message = couche_d.refus_du_jeu(d, violations)
            self.assertIn("(%d violation(s), dont : %s)" % (len(violations), citee), message)
            self.assertIn("1) supprimer D/attendus ; 2) python3 tests/reference_jeu.py manifeste --dossier D ; "
                          "3) relancer --generer.", message)
            self.assertIn("Ce chemin ne lève que les violations portées par attendus/ ou par le manifeste ; un fichier en "
                          "trop ou manquant, ou le contenu d'une table ou de l'historique, se corrige d'abord dans le "
                          "dossier.", message)
            self.assertNotIn("Si la modification est voulue", message)
        # La phrase que le message relit est celle que le contrôle écrit.
        self.modifier("tables/S1901M.json", lambda d: d["tables"]["FRANCE"]["plans"][0].update(value=0.123456), manifeste=False)
        self.assertEqual([couche_d._table_ou_historique_retouche(v) for v in reference_jeu.controler(self.dossier)], [True])

    def test_un_harnais_modifie_fait_toujours_refuser(self):
        for relatif, ligne in (("tests/harnais.py", " M tests/harnais.py"), ("cicero/overlay/bot.py", " M cicero/overlay/bot.py"),
                               ("tests/nouveau.py", "?? tests/nouveau.py")):
            fichier = self.racine / relatif
            avant = fichier.read_bytes() if fichier.exists() else None
            fichier.write_text("modifie = True\n", encoding="utf-8")
            code, sortie = self.generer()
            self.assertEqual(code, 2, sortie)
            self.assertIn("arbre de travail modifié sous cicero/overlay et tests, hors tests/reference (1 fichier(s), dont %s)"
                          % ligne.strip(), sortie)
            self.assertFalse((self.dossier / "attendus").exists())
            self.assertNotIn("attendus", json.loads((self.dossier / "manifeste.json").read_text(encoding="utf-8")))
            if avant is None:
                fichier.unlink()
            else:
                fichier.write_bytes(avant)
        code, sortie = self.generer("--arbre-modifie")  # arbre redevenu propre : le SHA n'est pas marqué
        self.assertEqual(code, 0, sortie)
        (self.racine / "tests" / "harnais.py").write_text("modifie = True\n", encoding="utf-8")
        code, sortie = self.generer("--arbre-modifie")
        self.assertEqual(code, 0, sortie)
        manifeste = json.loads((self.dossier / "manifeste.json").read_text(encoding="utf-8"))
        self.assertEqual(manifeste["attendus"]["sha_code"], self.sha + "-modifie")


class Mutations(AvecJeu):
    """Critère d'acceptation (a) de #31, sur le jeu fabriqué : chaque modification volontaire est vue."""

    def decompte(self, nom):
        jeu = reference_jeu.lire_jeu(self.dossier)
        mutation = next(m for m in couche_d.MUTATIONS if m[0].startswith(nom))
        lignes, _, _ = couche_d.comparer(
            couche_d.attendus_complets(jeu), couche_d.calculer(jeu, couche_d.charger_modules([mutation[1:]]))
        )
        return {couche: n for couche, n in couche_d.par_couche(lignes).items() if n}

    def vue_par(self, nom, *couches, seules=False):
        """La mutation change des grandeurs de chacune de ces couches (et d'aucune autre si `seules`) ; D6 n'est
        changée que par celle qui la vise."""
        decompte = self.decompte(nom)
        for couche in couches:
            self.assertIn(couche, decompte, decompte)
        if seules:
            self.assertEqual(sorted(decompte), sorted(couches), decompte)
        if "D6" not in couches:
            self.assertNotIn("D6", decompte)

    def test_huit_mutations(self):
        self.assertEqual(len(couche_d.MUTATIONS), 8)
        self.assertEqual(len({mutation[0] for mutation in couche_d.MUTATIONS}), 8)

    def test_verdict_du_registre(self):
        # La seule mutation qui vise D6 (#40), et elle ne change rien d'autre.
        self.vue_par("verdict du registre", "D6", seules=True)
        self.assertEqual([m[0] for m in couche_d.MUTATIONS if "D6" in self.decompte(m[0])],
                         ["verdict du registre : tenue dès que l'unité a reçu un ordre"])

    def test_le_texte_de_la_mutation_du_verdict_est_celui_du_bot(self):
        ancien = next(m[2] for m in couche_d.MUTATIONS if m[0].startswith("verdict du registre"))
        self.assertEqual(couche_d.FICHIERS["bot"].read_text(encoding="utf-8").count(ancien), 1)

    def test_marge(self):
        self.vue_par("marge", "D3", "D4")

    def test_arrondi_du_gain(self):
        self.vue_par("arrondi du gain", "D3")

    def test_definition_d_order_values(self):
        self.vue_par("order_values", "D1", "D1r", seules=True)

    def test_multiplicateur(self):
        self.vue_par("multiplicateur", "D2")

    def test_plafond(self):
        self.vue_par("plafond", "D2", seules=True)

    def test_plancher(self):
        self.vue_par("plancher", "D2")

    def test_lambda(self):
        self.vue_par("lambda", "D2")

    def test_la_commande_rend_0_quand_tout_est_vu(self):
        code, sortie = self.lancer("--mutations")
        self.assertEqual(code, 0, sortie)
        self.assertIn("Sans mutation : 0 différence(s)", sortie)
        self.assertEqual(sortie.count("| oui"), 8)
        # Colonnes : nom, D1, D1r, D2, D3, D4, D5, D6, total, vue. Une seule ligne a une colonne D6 non nulle.
        lignes = [ligne.split(" | ") for ligne in sortie.splitlines() if ligne.endswith("| oui")]
        self.assertEqual([ligne[0] for ligne in lignes if ligne[7] != "0"], ["verdict du registre : tenue dès que l'unité a reçu un ordre"])

    def test_la_commande_rend_1_si_une_mutation_n_est_pas_vue(self):
        sans_effet = (("sans effet", "bot", "MAX_SEND_ATTEMPTS = 3\n", "MAX_SEND_ATTEMPTS = 4\n"),)
        with mock.patch.object(couche_d, "MUTATIONS", sans_effet):
            code, sortie = self.lancer("--mutations")
        self.assertEqual(code, 1)
        self.assertIn("| NON", sortie)

    def test_mutation_perimee(self):
        with self.assertRaises(couche_d.MutationPerimee):
            couche_d.charger_modules([("bot", "ce texte n'est pas dans le fichier", "x")])
        perimee = (("périmée", "bot", "ce texte n'est pas dans le fichier", "x"),)
        with mock.patch.object(couche_d, "MUTATIONS", perimee):
            code, sortie = self.lancer("--mutations")
        self.assertEqual(code, 1)
        self.assertIn("mutation périmée", sortie)

    def test_une_mutation_ne_touche_ni_le_depot_ni_les_modules_du_banc(self):
        avant = {nom: chemin.read_bytes() for nom, chemin in couche_d.FICHIERS.items()}
        mutant = couche_d.charger_modules([couche_d.MUTATIONS[0][1:]])[0]
        self.assertEqual(mutant.COMMITMENT_SWITCH_MARGIN, 0.03)
        self.assertEqual(banc.bot.COMMITMENT_SWITCH_MARGIN, 0.05)
        self.assertIs(couche_d.charger_modules()[0], banc.bot)
        self.assertEqual({nom: chemin.read_bytes() for nom, chemin in couche_d.FICHIERS.items()}, avant)


# ---------------------------------------------------------------------------
# Capture (tests/mesure/capture_reference.py, tests/mesure/rejeu_moteur.py)
# ---------------------------------------------------------------------------

class Capture(unittest.TestCase):
    def test_historique_extrait_puis_rejoue(self):
        classe, game = capture_reference.partie_doublure_jouee()
        historique = capture_reference.extraire_historique(game)
        self.assertEqual(historique, capture_reference.HISTORIQUE_DOUBLURE)
        rejouee, n = capture_reference.partie_depuis_historique(classe, historique, "F1901M", score="dss", minutes_de_phase=1440)
        self.assertEqual((rejouee.current_short_phase, n), ("F1901M", 1))
        self.assertEqual(rejouee.jouees[0].orders["FRANCE"], ("A PAR - BUR", "A MAR - SPA", "F BRE - MAO"))
        self.assertEqual((rejouee.score, rejouee.metadonnees), (classe.SCORING_DSS, {"phase_minutes": "1440"}))
        self.assertEqual(capture_reference.partie_depuis_historique(classe, historique, "S1901M")[1], 0)

    def test_l_historique_extrait_passe_le_controle_du_jeu(self):
        _classe, game = capture_reference.partie_doublure_jouee()
        with tempfile.TemporaryDirectory() as tmp:
            reference_jeu.construire_jeu(Path(tmp) / "jeu", capture_reference.extraire_historique(game), {}, MANIFESTE)

    def test_phase_hors_de_l_historique(self):
        classe, _game = capture_reference.partie_doublure_jouee()
        with self.assertRaises(SystemExit) as refus:
            capture_reference.partie_depuis_historique(classe, capture_reference.HISTORIQUE_DOUBLURE, "S1903M")
        self.assertIn("S1903M n'est pas atteinte", str(refus.exception))

    def test_historique_qui_ne_suit_pas_la_partie(self):
        classe, _game = capture_reference.partie_doublure_jouee()
        decale = {"phases": list(reversed(capture_reference.HISTORIQUE_DOUBLURE["phases"]))}
        with self.assertRaises(SystemExit) as refus:
            capture_reference.partie_depuis_historique(classe, decale, "W1901A")
        self.assertIn("la partie rejouée est en S1901M, l'historique donne F1901M", str(refus.exception))

    def test_positions_comparees(self):
        classe, game = capture_reference.partie_doublure_jouee()
        historique = capture_reference.extraire_historique(game)
        self.assertEqual(capture_reference.comparer_positions(classe, game, historique),
                         [("S1901M", True, True), ("F1901M", True, True)])
        historique["phases"][0]["orders"]["FRANCE"][0] = "A PAR - PIC"
        self.assertEqual(capture_reference.comparer_positions(classe, game, historique),
                         [("S1901M", True, True), ("F1901M", False, False)])

    def test_l_appel_a_export_plans_est_double_sans_etre_change(self):
        recus = []
        module = types.SimpleNamespace(export_plans=lambda *a, **k: recus.append((a, k)) or "rendu")
        origine, puits = module.export_plans, []
        self.assertIs(capture_reference.doubler_export(module, puits), origine)
        action_values = [(("A PAR - BUR",), 0.2, 0.75, 0.19), (("A PAR H",), 0.1, 0.25, 0.08)]
        avant = {("A PAR H",): 0.5, ("A PAR - BUR",): 0.5}
        rendu = module.export_plans("3", "S1901M", "FRANCE", action_values, prior_policy=avant,
                                    regularize_lambda=0.01, boost=3.0, max_prob=0.4)
        self.assertEqual(rendu, "rendu")
        self.assertEqual(recus, [(("3", "S1901M", "FRANCE", action_values),
                                  dict(prior_policy=avant, regularize_lambda=0.01, boost=3.0, max_prob=0.4))])
        arguments, appels = capture_reference.arguments_de_la_recherche(puits, "S1901M", "FRANCE")
        self.assertEqual(appels, 1)
        self.assertEqual(arguments, {
            "action_values": [[["A PAR - BUR"], 0.2, 0.75, 0.19], [["A PAR H"], 0.1, 0.25, 0.08]],
            "prior_policy": [[["A PAR H"], 0.5], [["A PAR - BUR"], 0.5]],
            "regularize_lambda": 0.01, "boost": 3.0, "max_prob": 0.4,
        })
        self.assertEqual(capture_reference.arguments_de_la_recherche(puits, "S1901M", "ITALY"), (None, 1))

    def test_une_erreur_de_releve_n_empeche_pas_l_export(self):
        module = types.SimpleNamespace(export_plans=lambda *a, **k: "rendu")
        puits = []
        capture_reference.doubler_export(module, puits)
        self.assertEqual(module.export_plans("3", "S1901M", "FRANCE", [("pas un quadruplet",)]), "rendu")
        self.assertIn("erreur", puits[0])

    def commandes(self, *options):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.assertEqual(capture_reference.main(["commandes", "3"] + list(options)), 0)
        return sortie.getvalue()

    def test_commandes_de_la_campagne(self):
        """21 positions à 5 tirages A + B, 21 à un tirage A seul, et la seconde passe de FRANCE S1903M."""
        sortie = self.commandes()
        recherches = [l.split() for l in sortie.splitlines() if "rejeu_moteur.py" in l]
        self.assertEqual(len(recherches), 43)
        repetees = {(l[3], l[4]) for l in recherches if l[5] == "5" and l[-1] == "auto:prefere"}
        seules = {(l[3], l[4]) for l in recherches if l[5] == "1" and l[-1] == "aucun"}
        passe = [(l[3], l[4], l[5]) for l in recherches if l[-2:] == ["--etiquette", "passe2"]]
        toutes = set(itertools.product(capture_reference.PHASES_DE_MOUVEMENT, capture_reference.commun.POWERS))
        sept = capture_reference.commun.POWERS
        self.assertEqual(repetees, set(
            [("S1901M", p) for p in sept] + [("S1902M", p) for p in sept]
            + [("F1902M", p) for p in ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "RUSSIA")]
            + [("S1903M", p) for p in ("FRANCE", "TURKEY")]
        ))
        self.assertEqual(seules, set(
            [("F1901M", p) for p in sept] + [("F1902M", p) for p in ("ITALY", "TURKEY")]
            + [("S1903M", p) for p in ("AUSTRIA", "ENGLAND", "GERMANY", "ITALY", "RUSSIA")] + [("F1903M", p) for p in sept]
        ))
        self.assertEqual((len(repetees), len(seules)), (21, 21))
        self.assertEqual(repetees | seules, toutes)
        self.assertEqual(passe, [("S1903M", "FRANCE", "5")])
        for ligne in recherches:
            self.assertIn("--score sos --minutes-de-phase 4320", " ".join(ligne))
        self.assertLess(sortie.index("docker stop cicero-orders"), sortie.index("rejeu_moteur.py"))
        self.assertIn("capture_reference.py identite --dossier amont/capture-reference", sortie)
        self.assertLess(sortie.index("capture_reference.py identite"), sortie.index("docker stop"))
        self.assertIn("--identite amont/capture-reference/resultats/identite_capture.json", sortie)
        self.assertIn("cp -a amont/capture-reference/resultats <dossier de conservation hors du dépôt>/", sortie)
        self.assertIn("43 lancements, 241 recherches ; durée estimée des recherches : de 3 h 07 (campagne du 2026-10-10) à 5 h 11", sortie)
        # La campagne lit le site : elle garde le réseau de la pile et ses variables, et dit ce prérequis en tête.
        self.assertEqual(sortie.count("docker run --rm"), 45)
        self.assertEqual(sortie.count(" --network webdiplomacy_default "), 45)
        self.assertEqual(sortie.count("-e WEBDIP_API_URL=http://webserver/api.php -e CICERO_REDIS_IP=redis -e CICERO_REDIS_PORT=6379"), 45)
        self.assertIn("Prérequis : pile démarrée (réseau webdiplomacy_default", sortie[:sortie.index("mkdir")])

    def test_la_suite_de_capture_ne_relance_pas_cicero_orders(self):
        """Comme la suite de la couche R : rien n'est relancé, l'état initial de cicero-orders est relevé avant
        l'arrêt et son rappel suit les recherches (le 2026-10-10, le redémarrage imprimé a produit 7 envois
        d'ordres sur une partie en pause)."""
        sortie = self.commandes()
        self.assertEqual([ligne for ligne in sortie.splitlines() if "docker start" in ligne], [])
        self.assertIn("docker inspect --format '{{.State.Status}}' cicero-orders", sortie)
        self.assertLess(sortie.index("docker inspect --format '{{.State.Status}}' cicero-orders"), sortie.index("docker stop cicero-orders"))
        self.assertIn("le remettre à la main dans l'état noté", sortie[sortie.rindex("rejeu_moteur.py"):])

    def test_les_deux_suites_relevent_l_etat_de_cicero_orders_sans_rien_relancer(self):
        """Les trois mêmes lignes dans les deux suites, avant la première recherche ; aucune ligne ne lance
        « docker start ». Exécutées avec la doublure de docker : conteneur absent (après ./arreter.sh), aucune
        ligne n'échoue et rien n'est arrêté ; conteneur en marche, il est arrêté, et son état affiché."""
        etat = list(capture_reference.ETAT_DE_CICERO_ORDERS)
        self.assertEqual(etat, [
            "ETAT=$(docker inspect --format '{{.State.Status}}' cicero-orders 2>/dev/null) || ETAT=absent",
            'echo "cicero-orders : état initial $ETAT (à restaurer à la main, cette suite ne relance rien)"',
            '[ "$ETAT" = absent ] || docker stop cicero-orders',
        ])
        for options in ((), ("--couche-r",), ("--couche-r", "--reseau", "webdiplomacy_default")):
            lignes = self.commandes(*options).splitlines()
            debut = lignes.index(etat[0])
            self.assertEqual(lignes[debut:debut + 3], etat, options)
            self.assertLess(debut + 2, min(i for i, ligne in enumerate(lignes) if "rejeu_moteur.py" in ligne))
            self.assertEqual([ligne for ligne in lignes if "docker start" in ligne], [], options)
            self.assertEqual([ligne for ligne in lignes if "cicero-orders" in ligne and not ligne.startswith("#")], etat, options)
            self.assertEqual(sum("le remettre à la main dans l'état noté" in ligne for ligne in lignes), 1, options)
        for etat_du_conteneur, appels in (
                ("absent", ["inspect --format {{.State.Status}} cicero-orders"]),
                ("running", ["inspect --format {{.State.Status}} cicero-orders", "stop cicero-orders"]),
                ("exited", ["inspect --format {{.State.Status}} cicero-orders", "stop cicero-orders"])):
            with tempfile.TemporaryDirectory() as tmp:
                doublures = Doublures(Path(tmp), etat=etat_du_conteneur)
                rendu = doublures.lancer(["bash", "-e", "-c", "\n".join(etat)], cwd=tmp)
                self.assertEqual(rendu.returncode, 0, rendu.stdout)
                self.assertEqual(rendu.stdout.splitlines()[0], "cicero-orders : état initial %s (à restaurer à la main, cette suite ne relance rien)" % etat_du_conteneur)
                self.assertEqual(doublures.appels(), appels)

    def test_commandes_de_la_couche_r(self):
        """Les 21 positions répétées, 5 tirages A + B, sans seconde passe, dans un dossier à part ; rien n'est relancé (#33)."""
        sortie = self.commandes("--couche-r")
        recherches = [l.split() for l in sortie.splitlines() if "rejeu_moteur.py" in l]
        self.assertEqual([(l[3], l[4]) for l in recherches], list(capture_reference.POSITIONS_REPETEES))
        self.assertEqual(len(recherches), 21)
        for ligne in recherches:
            self.assertEqual((ligne[5], ligne[-2:]), ("5", ["--engagements", "auto:prefere"]))
            self.assertIn("--historique /mesure/resultats/historique_3.json --score sos --minutes-de-phase 4320", " ".join(ligne))
        self.assertNotIn("--etiquette", sortie)
        self.assertNotIn("docker start", sortie)
        self.assertNotIn("capture-reference", sortie)
        self.assertNotIn("reference_jeu.py reduire", sortie)
        self.assertEqual(sortie.count('-v "$PWD/amont/couche-r:/mesure"'), 21)
        # L'état initial de cicero-orders est relevé avant l'arrêt, et son rappel clôt la suite.
        self.assertLess(sortie.index("docker inspect --format '{{.State.Status}}' cicero-orders"), sortie.index("docker stop cicero-orders"))
        self.assertLess(sortie.index("docker stop cicero-orders"), sortie.index("rejeu_moteur.py"))
        self.assertIn("le remettre à la main dans l'état noté", sortie.splitlines()[-1])
        self.assertIn("cp tests/reference/historique.json amont/couche-r/resultats/historique_3.json", sortie)
        self.assertIn("python3 tests/reference_couche_r.py comparer amont/couche-r/resultats --sortie amont/couche-r/couche_r.json", sortie)
        # 21 x (46 + 5 x (50,5 + 24,1)) = 8 799 s = 2 h 26 ; x 1,66 = 14 606 s = 4 h 03.
        self.assertIn("# 21 lancements, 210 recherches ; durée estimée : de 2 h 26 (campagne du 2026-10-10) à 4 h 03 (× 1,66, "
                      "observé sur les 21 lancements du lot du 2026-10-11, carte graphique occupée par ailleurs pendant près "
                      "de deux heures).", sortie.splitlines())
        trois = self.commandes("--couche-r", "--tirages", "3", "--repetees", "S1902M")
        self.assertEqual([l.split()[3:6] for l in trois.splitlines() if "rejeu_moteur.py" in l],
                         [["S1902M", p, "3"] for p in capture_reference.commun.POWERS])
        # Exécution réduite ou relance d'une position : la comparaison nomme ce qu'elle attend, dans un autre dossier.
        self.assertIn("--positions S1902M:AUSTRIA S1902M:ENGLAND", trois)
        self.assertNotIn("--positions", sortie)
        une = self.commandes("--couche-r", "--repetees", "S1903M:FRANCE", "--dossier", "amont/couche-r-relance")
        self.assertIn("comparer amont/couche-r-relance/resultats --sortie amont/couche-r-relance/couche_r.json "
                      "--positions S1903M:FRANCE", une)
        self.assertIn("mkdir amont/couche-r-relance && ", une)

    LANCEMENT_SANS_RESEAU = (
        'docker run --rm --gpus all \\\n'
        '  -v "$PWD/amont/couche-r:/mesure" -v "$PWD/amont/cicero/models:/opt/cicero/models:ro" \\\n'
        '  cicero-webdip:latest \\\n'
        '  python /mesure/rejeu_moteur.py 3 S1903M TURKEY 5 --historique /mesure/resultats/historique_3.json '
        '--score sos --minutes-de-phase 4320 --engagements auto:prefere\n'
    )
    # La forme d'avant #33, celle des lancements du 2026-10-11 (pile démarrée pour le seul réseau).
    LANCEMENT_AVEC_RESEAU = (
        'docker run --rm --gpus all --network webdiplomacy_default \\\n'
        '  -v "$PWD/amont/couche-r:/mesure" -v "$PWD/amont/cicero/models:/opt/cicero/models:ro" \\\n'
        '  -e WEBDIP_API_URL=http://webserver/api.php -e CICERO_REDIS_IP=redis -e CICERO_REDIS_PORT=6379 \\\n'
        '  cicero-webdip:latest \\\n'
        '  python /mesure/rejeu_moteur.py 3 S1903M TURKEY 5 --historique /mesure/resultats/historique_3.json '
        '--score sos --minutes-de-phase 4320 --engagements auto:prefere\n'
    )

    def test_la_suite_de_la_couche_r_part_sans_le_reseau_de_la_pile(self):
        """Pile arrêtée, webdiplomacy_default n'existe pas : ni --network ni les trois -e, et le prérequis est dit
        en tête ; --reseau NOM rétablit l'ancienne forme. Plus de « aucun accès au site » : Internet est requis."""
        sortie = self.commandes("--couche-r")
        self.assertNotIn("--network", sortie)
        for variable in ("WEBDIP_API_URL", "CICERO_REDIS_IP", "CICERO_REDIS_PORT", " -e "):
            self.assertNotIn(variable, sortie)
        self.assertIn(self.LANCEMENT_SANS_RESEAU, sortie)
        self.assertEqual(sortie.count("docker run --rm --gpus all \\\n"), 21)
        tete = sortie[:sortie.index("mkdir")]
        self.assertIn("Prérequis : image cicero-webdip:latest, modèles sous amont/cicero/models ; la pile peut être arrêtée", tete)
        self.assertIn("Aucun accès à webDiplomacy ; accès sortant à Internet requis au démarrage de chaque lancement", tete)
        self.assertIn("(vocabulaire GPT-2 téléchargé depuis dl.fbaipublicfiles.com)", tete)
        self.assertNotIn("aucun accès au site", sortie)
        avec = self.commandes("--couche-r", "--reseau", "webdiplomacy_default")
        self.assertIn(self.LANCEMENT_AVEC_RESEAU, avec)
        self.assertEqual(avec.count(" --network webdiplomacy_default "), 21)
        self.assertIn("; le réseau Docker webdiplomacy_default existe (celui de la pile : il n'existe que pile démarrée).\n",
                      avec[:avec.index("mkdir")])
        self.assertEqual(avec[:avec.index("mkdir")].count("webdiplomacy_default"), 1)
        self.assertNotIn("la pile peut être arrêtée", avec)
        autre = self.commandes("--couche-r", "--reseau", "autre-reseau_2.x")
        self.assertEqual(autre.count(" --network autre-reseau_2.x "), 21)
        self.assertIn("; le réseau Docker autre-reseau_2.x existe (celui de la pile, webdiplomacy_default, n'existe que pile démarrée).\n", autre)

    def refus(self, *options, partie="3"):
        """Le code de sortie de `commandes 3 <options>`, refusé ; rien n'est imprimé sur la sortie standard."""
        sortie, erreurs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(erreurs), self.assertRaises(SystemExit) as arret:
            capture_reference.main(["commandes", partie] + list(options))
        self.assertEqual(sortie.getvalue(), "", options)
        self.message = erreurs.getvalue() + str(arret.exception)
        return arret.exception.code

    def test_phases_dossier_et_reseau_valides_avant_d_etre_imprimes(self):
        """Ces valeurs sont écrites dans des lignes de shell : une valeur qui n'est pas une phase, un chemin relatif
        sans « .. » ou un nom de réseau est refusée, code 2, sortie standard vide (#33)."""
        for options in (
                ("--phases", "S1901M;id"), ("--phases", "S1901M", "$(id)"), ("--phases", "s1901m"), ("--phases", "S1901M ", "--couche-r"),
                ("--couche-r", "--dossier", "/tmp/x y;rm"), ("--couche-r", "--dossier", "/tmp/x"), ("--couche-r", "--dossier", "../x"),
                ("--couche-r", "--dossier", "amont/../x"), ("--couche-r", "--dossier", "amont/x y"), ("--couche-r", "--dossier=-x"),
                ("--couche-r", "--dossier", "amont/.."), ("--couche-r", "--dossier", "amont/"), ("--couche-r", "--dossier", ""),
                ("--dossier", "amont/x;id"), ("--couche-r", "--dossier", "amont/x\nid"),
                ("--couche-r", "--reseau", "a b"), ("--couche-r", "--reseau", "x;id"), ("--couche-r", "--reseau", ""),
                ("--couche-r", "--reseau", "$(id)"),
                # Un tiret initial faisait imprimer « --network --privileged » ; « none » coupe l'accès sortant (#34).
                ("--couche-r", "--reseau=--privileged"), ("--couche-r", "--reseau=-x"), ("--couche-r", "--reseau=.x"),
                ("--couche-r", "--reseau", "none"),
                # Un lot ne s'écrit que sous amont/ : ni dans le jeu d'essai, ni ailleurs dans le dépôt versionné.
                ("--couche-r", "--dossier", "lot"), ("--couche-r", "--dossier", "tests/reference/lot"), ("--couche-r", "--dossier", "tests/mesure/lot"),
                ("--couche-r", "--dossier", "amont"), ("--couche-r", "--dossier", "amont/.x"), ("--couche-r", "--dossier", "amont/-x"),
                ("--couche-r", "--dossier", "amontx/lot"), ("--couche-r", "--dossier", "./amont/lot"),
                # Ni dans un clone d'amont : outils/exporter_patchs.sh en parcourt les fichiers non suivis.
                ("--couche-r", "--dossier", "amont/cicero/x"), ("--couche-r", "--dossier", "amont/webdiplomacy/x"),
                ("--couche-r", "--dossier", "amont/cicero"), ("--couche-r", "--dossier", "amont/webdiplomacy"),
                ("--couche-r", "--dossier", "amont/cicero/x/y"),
                # Entiers bornés.
                ("--tirages", "0"), ("--couche-r", "--tirages", "0"), ("--tirages=-1",), ("--tirages", "deux"), ("--tirages", "1.5"),
                ("--minutes-de-phase=-1",), ("--couche-r", "--minutes-de-phase=-4320")):
            self.assertEqual(self.refus(*options), 2, options)
            self.assertIn("invalide", self.message, options)
        self.refus("--couche-r", "--reseau", "none")
        self.assertIn("accès sortant à Internet est requis au démarrage de chaque lancement, #34", self.message)
        self.refus("--couche-r", "--dossier", "lot")
        self.assertIn("sous amont/, relatif à la racine du dépôt, sans « .. », aucune composante ne commençant par un point ou un tiret",
                      self.message)
        self.refus("--couche-r", "--dossier", "amont/cicero/x")
        self.assertIn("hors des clones d'amont (ni amont/cicero ni amont/webdiplomacy)", self.message)
        for partie in ("0", "-3", "trois", ""):
            self.assertEqual(self.refus(partie=partie), 2, partie)
            self.assertEqual(self.refus("--couche-r", partie=partie), 2, partie)
        for dossier in ("amont/couche-r", "amont/couche-r-2026.10.12_b", "amont/lots/a", "amont/cicerone/x", "amont/x/cicero",
                        "amont/webdiplomacy2"):
            self.assertIn("mkdir %s && mkdir %s/resultats" % (dossier, dossier), self.commandes("--couche-r", "--dossier", dossier))
        self.assertIn(" 3 S1901M AUSTRIA 1 --historique /mesure/resultats/historique_3.json --score sos --minutes-de-phase 0 ",
                      self.commandes("--couche-r", "--tirages", "1", "--minutes-de-phase", "0"))
        self.assertEqual(len([l for l in self.commandes("--phases", "W1901A", "S2001M").splitlines() if "rejeu_moteur.py" in l]), 15)

    def test_dossier_et_reseau_sans_couche_r_sont_refuses(self):
        """--dossier et --reseau ne valent que pour un lot de la couche R : donnés sans --couche-r, ils étaient
        ignorés sans le dire ; code 2, rien d'imprimé."""
        for options in (("--dossier", "amont/x"), ("--reseau", "webdiplomacy_default"), ("--phases", "S1901M", "--reseau", "r")):
            self.assertEqual(self.refus(*options), 2, options)
            self.assertIn("%s ne vaut qu'avec --couche-r" % ("--dossier" if "--dossier" in options else "--reseau"), self.message)

    def test_la_phase_d_une_position_repetee_est_validee(self):
        """--repetees porte aussi une phase, imprimée dans les lancements et dans --positions : même refus de
        lire_positions que pour une puissance inconnue, rien d'imprimé."""
        for options in (("--repetees", "S1901M;id:FRANCE"), ("--couche-r", "--repetees", "S1902M;id"), ("--couche-r", "--repetees", ":FRANCE")):
            self.assertEqual(self.refus(*options), "position inconnue : %r" % options[-1], options)

    def test_le_releve_du_site_ne_porte_plus_processstatus(self):
        """game/status n'expose pas processStatus : le relevé le donnait toujours nul. Il n'y est plus, ni dans le
        relevé de l'historique ni dans celui d'un lancement, même si un statut le portait."""
        statut = {"gameID": 3, "turn": 4, "phase": "Diplomacy", "gameOver": "No", "processStatus": "Paused",
                  "potType": "Unranked", "phaseLengthInMinutes": 4320, "phases": [{"messages": [1, 2]}, {}]}
        copie = types.SimpleNamespace(messages={}, get_metadata=lambda cle: "3", set_metadata=lambda cle, valeur: None)
        courante = types.SimpleNamespace(current_short_phase="S1903M", rolled_back_to_phase_start=lambda phase: copie)
        api = types.ModuleType("fairdiplomacy_external.webdip_api")
        api.get_status_json, api.webdip_state_to_game = (lambda contexte: statut), (lambda lu: courante)
        joueur = types.ModuleType("fairdiplomacy.agents.player")
        joueur.Player = lambda agent, puissance: (agent, puissance)
        modules = {"fairdiplomacy_external": types.ModuleType("fairdiplomacy_external"), "fairdiplomacy_external.webdip_api": api,
                   "fairdiplomacy": types.ModuleType("fairdiplomacy"), "fairdiplomacy.agents": types.ModuleType("fairdiplomacy.agents"),
                   "fairdiplomacy.agents.player": joueur}
        with mock.patch.dict(sys.modules, modules), mock.patch.object(capture_reference.commun, "trouver_contexte", return_value="contexte"):
            _game, releve = capture_reference.lire_partie_du_site(3)
            moteur = object.__new__(rejeu_moteur.MoteurReel)
            moteur.ctx, moteur.game_id, moteur.phase, moteur.puissance, moteur.agent = "contexte", 3, "S1901M", "FRANCE", None
            du_lancement = moteur.nouvelle_partie()
        self.assertEqual(releve, {"gameID": 3, "turn": 4, "phase": "Diplomacy", "gameOver": "No", "potType": "Unranked",
                                  "phaseLengthInMinutes": 4320, "messages": 2, "phase_courante": "S1903M"})
        self.assertEqual(du_lancement, {"gameID": 3, "turn": 4, "phase": "Diplomacy", "gameOver": "No", "phase_courante": "S1903M",
                                        "game_id_conserve_par_le_retour_arriere": True, "messages_dans_la_copie": 0})

    def test_unranked_est_note_en_sos(self):
        """Le potType de la partie 3, « Unranked » : SCORING_SOS dans webdip_state_to_game, d'où --score sos par défaut."""
        self.assertEqual(capture_reference.SCORE_DU_POT["Unranked"], "sos")
        source = reference_jeu.RACINE / "amont" / "cicero" / "fairdiplomacy_external" / "webdip_api.py"
        if source.exists():
            self.assertRegex(
                source.read_text(encoding="utf-8"),
                r'pot_type == "Unranked" or pot_type == "Sum-of-squares":\s+game\.set_scoring_system\(Game\.SCORING_SOS\)',
            )

    def test_duree_estimee(self):
        """Par lancement 46 s, par tirage 50,5 s (A) et 24,1 s de plus avec engagement (B) : mesures du 2026-10-10."""
        self.assertEqual(capture_reference.DUREES, {"A": 50.5, "B": 24.1, "lancement": 46.0})
        self.assertAlmostEqual(capture_reference.duree_estimee([("S1901M", "FRANCE", 5, "auto:prefere", None)]), 46 + 5 * 74.6)
        self.assertAlmostEqual(capture_reference.duree_estimee([("F1901M", "FRANCE", 1, "aucun", None)]), 46 + 50.5)
        plan = capture_reference.plan_de_campagne(capture_reference.PHASES_DE_MOUVEMENT, capture_reference.POSITIONS_REPETEES, 5)
        # 11 244,5 s, soit 3 h 07 ; la campagne du 2026-10-10 a duré 11 314 s (son journal).
        self.assertAlmostEqual(capture_reference.duree_estimee(plan), 43 * 46 + 110 * 74.6 + 21 * 50.5)

    def test_la_fourchette_de_duree_couvre_les_deux_campagnes(self):
        """Les 21 lancements des positions répétées ont duré 8 999 s le 2026-10-10 et 14 548 s le 2026-10-11 (journaux
        des deux campagnes) : la borne basse est l'estimation de DUREES, la haute la majore de ce qui a été observé."""
        self.assertEqual(capture_reference.MAJORATION_OBSERVEE, 1.66)
        lot = [(phase, puissance, 5, "auto:prefere", None) for phase, puissance in capture_reference.POSITIONS_REPETEES]
        basse, haute = capture_reference.fourchette_de_duree(lot)
        self.assertAlmostEqual(basse, 8799.0)
        self.assertEqual((int(basse), int(haute)), (8799, 14606))
        self.assertLessEqual(basse, 8999)
        self.assertGreaterEqual(haute, 14548)
        self.assertLess(14548 / basse, capture_reference.MAJORATION_OBSERVEE)  # 1,653, arrondi au-dessus
        observe = "(× 1,66, observé sur les 21 lancements du lot du 2026-10-11, carte graphique occupée par ailleurs pendant près de deux heures)"
        self.assertEqual(capture_reference.texte_de_duree(lot), "de 2 h 26 (campagne du 2026-10-10) à 4 h 03 " + observe)
        # Toute autre suite : la borne haute est le même rapport appliqué à l'estimation, pas une durée que le lot du
        # 2026-10-11 aurait eue (43 lancements : 11 244,5 s x 1,66 = 18 665 s, soit 5 h 11).
        plan = capture_reference.plan_de_campagne(capture_reference.PHASES_DE_MOUVEMENT, capture_reference.POSITIONS_REPETEES, 5)
        self.assertEqual(capture_reference.texte_de_duree(plan), "de 3 h 07 (campagne du 2026-10-10) à 5 h 11 " + observe)
        for texte in (capture_reference.texte_de_duree(plan), capture_reference.texte_de_duree(lot[:1])):
            self.assertNotIn("(lot du 2026-10-11", texte)

    def test_positions_repetees_donnees_en_couples(self):
        self.assertEqual(capture_reference.lire_positions(["S1902M:france", "F1901M", "S1902M:FRANCE"]),
                         [("S1902M", "FRANCE")] + [("F1901M", p) for p in capture_reference.commun.POWERS])
        with self.assertRaises(SystemExit):
            capture_reference.lire_positions(["S1902M:PARIS"])
        sortie = self.commandes("--phases", "S1902M", "--repetees", "S1902M:ITALY", "--tirages", "3")
        recherches = [l.split() for l in sortie.splitlines() if "rejeu_moteur.py" in l]
        self.assertEqual([(l[4], l[5], l[-1]) for l in recherches if l[5] != "1"], [("ITALY", "3", "auto:prefere"), ("FRANCE", "3", "passe2")])
        self.assertEqual(len(recherches), 8)

    def test_identite_de_la_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            sortie = io.StringIO()
            arguments = ["identite", "--dossier", tmp, "--sha", "ab" * 20, "--image", "sha256:" + "c" * 64, "--date", "2026-02-03"]
            with contextlib.redirect_stdout(sortie):
                self.assertEqual(capture_reference.main(arguments), 0)
            fichier = Path(tmp) / "resultats" / "identite_capture.json"
            self.assertEqual(json.loads(fichier.read_text(encoding="utf-8")),
                             {"sha_depot": "ab" * 20, "image": "sha256:" + "c" * 64, "date": "2026-02-03"})
            with self.assertRaises(SystemExit) as refus:  # une campagne, une identité
                capture_reference.main(arguments)
            self.assertIn("existe déjà", str(refus.exception))
        with tempfile.TemporaryDirectory() as tmp:
            for sha, image in (("5656d25", "x"), ("ab" * 20, "une image"), (None, "x"), ("ab" * 20, "")):
                with self.assertRaises(SystemExit):
                    capture_reference.ecrire_identite(tmp, sha, image)
            self.assertFalse((Path(tmp) / "resultats").exists())


# ---------------------------------------------------------------------------
# Enchaînement d'un lot de la couche R (tests/mesure/lancer_couche_r.sh)
# ---------------------------------------------------------------------------

DOUBLURE_DE_DOCKER = r"""#!/bin/bash
# Doublure de docker (tests/test_reference.py) : journalise chaque appel, ne lance rien.
echo "$*" >> "$DOUBLURE/journal_docker"
{ printf '%s\x1f' "$@"; echo; } >> "$DOUBLURE/journal_arguments"
case "$1 $2" in
  "inspect --format")
    etat=$(cat "$DOUBLURE/etat")
    if [ "$etat" = absent ]; then echo; echo "Error: No such object: cicero-orders" >&2; exit 1; fi
    echo "$etat" ;;
  "image inspect")
    [ ! -f "$DOUBLURE/sans_image" ] || { echo "Error: No such image" >&2; exit 1; }
    echo "sha256:doublure" ;;
  "stop cicero-orders") echo cicero-orders ;;
  "run --rm")
    # Un signal reçu pendant une substitution de commande dont l'enfant sort de lui-même ne tue pas bash : sans ce
    # trap, la doublure survivait parfois à un signal adressé au groupe.
    trap 'exit 130' INT HUP TERM
    numero=$(grep -c '^run ' "$DOUBLURE/journal_docker")
    if [ "$numero" = "$(cat "$DOUBLURE/echec_au" 2>/dev/null)" ]; then echo "échec doublé du lancement $numero" >&2; exit 7; fi
    if [ -f "$DOUBLURE/dort" ]; then
      duree=$(cat "$DOUBLURE/dort")
      echo "$numero" > "$DOUBLURE/va_dormir"  # témoin : plus rien ne sépare la doublure de son sommeil
      { sleep "$duree"; } 2> /dev/null  # bash écrirait « Hangup … sleep » dans le journal du lancement
    fi
    dossier="" ; suivant=""
    for a in "$@"; do
      case "$a" in *:/mesure) dossier="${a%:/mesure}" ;; esac
      case "$suivant" in
        script) partie="$a"; suivant=phase ;;
        phase) phase="$a"; suivant=puissance ;;
        puissance) puissance="$a"; suivant=tirages ;;
        tirages) tirages="$a"; suivant="" ;;
      esac
      [ "$a" != /mesure/rejeu_moteur.py ] || suivant=script
    done
    lignes=$((2 * tirages - $(cat "$DOUBLURE/lignes_en_moins" 2>/dev/null || echo 0)))
    if [ ! -f "$DOUBLURE/sans_releve" ]; then
      for ((i = 0; i < lignes; i++)); do echo '{"doublure": true}'; done \
        > "$dossier/resultats/m1_${partie}_${phase}_${puissance}_engagements_doublure.jsonl"
    fi
    echo "lancement doublé $numero : $phase $puissance, $lignes ligne(s)" ;;
  *) echo "doublure de docker : appel imprévu : $*" >&2; exit 99 ;;
esac
"""
DOUBLURE_DE_NVIDIA_SMI = """#!/bin/bash
echo "$*" >> "$DOUBLURE/journal_nvidia_smi"
echo "4605, 8192"
"""
# Ce dont le script et les doublures se servent, et rien d'autre : le PATH des essais ne contient que ces liens et
# les doublures, le vrai docker et le vrai nvidia-smi du poste n'y sont pas.
OUTILS_DES_ESSAIS = ("bash", "python3", "mkdir", "cp", "rm", "date", "grep", "tee", "tail", "tr", "sed", "dirname", "cat", "sleep")


class Doublures:
    """Un dossier `bin` qui est tout le PATH d'un essai : doublure de docker, liens vers les outils, et, sur demande,
    doublure de nvidia-smi. `etat` : ce que rend `docker inspect` pour cicero-orders (« absent » : code 1)."""

    def __init__(self, tmp, etat="absent", nvidia_smi=False, docker=True):
        self.dossier, self.bin = tmp / "doublure", tmp / "bin"
        self.dossier.mkdir()
        self.bin.mkdir()
        for outil in OUTILS_DES_ESSAIS:
            (self.bin / outil).symlink_to(sys.executable if outil == "python3" else shutil.which(outil))
        if docker:
            self.poser("docker", DOUBLURE_DE_DOCKER)
        if nvidia_smi:
            self.poser("nvidia-smi", DOUBLURE_DE_NVIDIA_SMI)
        self.regler(etat=etat)
        self.env = {"PATH": str(self.bin), "DOUBLURE": str(self.dossier), "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8"}

    def poser(self, nom, texte):
        if (self.bin / nom).is_symlink():  # un lien vers l'outil du poste : on le remplace, on n'écrit pas à travers
            (self.bin / nom).unlink()
        (self.bin / nom).write_text(texte, encoding="utf-8")
        (self.bin / nom).chmod(0o755)

    def regler(self, **reglages):
        for nom, valeur in reglages.items():
            (self.dossier / nom).write_text(str(valeur), encoding="utf-8")

    def verifier(self):
        """Avant chaque essai : le docker et le nvidia-smi qui répondraient sont les doublures, ou aucun."""
        for outil in ("docker", "nvidia-smi"):
            trouve = shutil.which(outil, path=self.env["PATH"])
            if trouve is not None and (Path(trouve).parent != self.bin or Path(trouve).is_symlink()):
                raise AssertionError("%s du poste atteint par l'essai : %s" % (outil, trouve))

    def lancer(self, commande, cwd):
        """Lance `commande` avec le PATH des doublures ; contrôle d'abord que le docker qui répondra est la doublure."""
        self.verifier()
        return subprocess.run(commande, cwd=str(cwd), env=self.env, universal_newlines=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def demarrer(self, commande, cwd):
        """Comme `lancer`, sans attendre la fin, dans une session à part : un signal s'adresse au script ou à son groupe."""
        self.verifier()
        return subprocess.Popen(commande, cwd=str(cwd), env=self.env, universal_newlines=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)

    def appels(self, outil="docker"):
        journal = self.dossier / ("journal_" + outil.replace("-", "_"))
        return journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []

    def arguments(self):
        """Les appels à la doublure de docker, argument par argument (les espaces d'un chemin n'y séparent rien)."""
        journal = self.dossier / "journal_arguments"
        return [ligne.split("\x1f")[:-1] for ligne in journal.read_text(encoding="utf-8").splitlines()] if journal.exists() else []


COMPARER_DOUBLE = """import sys
from pathlib import Path
ici = Path(__file__).resolve().parent
(ici / "appel_de_comparer.txt").write_text(" ".join(sys.argv[1:]), encoding="utf-8")
print("comparaison doublée")
sys.exit(int((ici / "code_de_comparer.txt").read_text()))
"""


class Enchainement(unittest.TestCase):
    """tests/mesure/lancer_couche_r.sh, par appel direct, dans une copie réduite du dépôt et avec une doublure de
    docker : aucun conteneur, aucun GPU. La suite exécutée est celle que le vrai capture_reference.py imprime ; la
    comparaison est doublée (son code de retour se règle), les relevés sont des fichiers vides de sens que la doublure
    de docker écrit là où un lancement les écrirait. Ce que la doublure ne voit pas : un lancement réel."""

    SCRIPT = Path(__file__).resolve().parent / "mesure" / "lancer_couche_r.sh"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Une espace dans le chemin de la racine : les lignes de la suite citent "$PWD/…" entre guillemets.
        self.racine = Path(tmp.name) / "un depot"
        mesure, tests = self.racine / "tests" / "mesure", Path(__file__).resolve().parent
        mesure.mkdir(parents=True)
        for nom in ("lancer_couche_r.sh", "capture_reference.py", "commun.py"):
            shutil.copy(str(tests / "mesure" / nom), str(mesure / nom))
        shutil.copy(str(tests / "reference_jeu.py"), str(self.racine / "tests" / "reference_jeu.py"))
        (self.racine / "tests" / "reference").mkdir()
        (self.racine / "tests" / "reference" / "historique.json").write_text('{"phases": []}', encoding="utf-8")
        (self.racine / "tests" / "reference_couche_r.py").write_text(COMPARER_DOUBLE, encoding="utf-8")
        (self.racine / "amont").mkdir()
        self.comparer(0)
        self.doublures = Doublures(Path(tmp.name))
        self.addCleanup(self.rien_n_est_arrete_ni_relance)
        self.lot = self.racine / "amont" / "couche-r"

    def rien_n_est_arrete_ni_relance(self):
        """(h) de l'expert, après chaque test de la classe : la doublure de docker n'a reçu que des « inspect », des
        « image inspect » et des « run » ; ni stop, ni start, ni restart, ni rm, ni kill, dans aucun scénario."""
        for appel in self.doublures.appels():
            self.assertIn((appel.split() or [""])[0], ("inspect", "image", "run"), "appel à docker : %r" % appel)

    def lancements_imprimes(self, *arguments):
        """Les « docker run » qu'imprime `commandes <arguments> --couche-r`, chacun en liste d'arguments comme un
        shell les passerait depuis la racine de la copie : continuations jointes, $PWD remplacé, shlex.split."""
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.assertEqual(capture_reference.main(["commandes"] + list(arguments) + ["--couche-r"]), 0)
        lignes = sortie.getvalue().replace("\\\n", "").splitlines()
        return [[mot.replace("$PWD", str(self.racine)) for mot in shlex.split(ligne)][1:]
                for ligne in lignes if ligne.startswith("docker run ")]

    def lancements_recus(self):
        return [appel for appel in self.doublures.arguments() if appel[:1] == ["run"]]

    def comparer(self, code):
        (self.racine / "tests" / "code_de_comparer.txt").write_text(str(code), encoding="utf-8")

    def arbre(self):
        return sorted(str(f.relative_to(self.racine)) for f in self.racine.rglob("*"))

    def lancer(self, *arguments, depuis=None):
        """(code, sortie) du script de la copie, lancé comme on le lance : par son chemin, d'un autre dossier."""
        rendu = self.doublures.lancer(["bash", str(self.racine / "tests" / "mesure" / "lancer_couche_r.sh")] + list(arguments),
                                      cwd=depuis or self.doublures.dossier)
        return rendu.returncode, rendu.stdout

    def journal(self, nom="campagne.log", lot=None):
        return ((lot or self.lot) / "journaux" / nom).read_text(encoding="utf-8")

    def lancements(self):
        return [appel for appel in self.doublures.appels() if appel.startswith("run ")]

    def refus(self, *arguments, message):
        """Code 3, rien de créé, aucun lancement ; la dernière ligne dit le code."""
        avant = self.arbre()
        code, sortie = self.lancer(*arguments)
        self.assertEqual(code, 3, sortie)
        self.assertIn(message, sortie)
        self.assertEqual(self.arbre(), avant, sortie)
        self.assertEqual(self.lancements(), [])
        self.assertEqual([a for a in self.doublures.appels() if a.split()[0] not in ("inspect", "image")], [])
        self.assertRegex(sortie.splitlines()[-1], r"^fin \S+ code=3 ; cicero-orders : état initial ")
        return sortie

    def test_le_script_est_versionne_executable_et_sans_chemin_personnel(self):
        self.assertTrue(os.access(str(self.SCRIPT), os.X_OK))
        texte = self.SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(subprocess.run(["bash", "-n", str(self.SCRIPT)]).returncode, 0)
        self.assertNotRegex(texte, r"/home/|/Users/|~/")
        self.assertIn('RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"', texte)
        # Il n'arrête ni ne relance rien : aucune ligne de commande « docker stop » ni « docker start ».
        commandes = [ligne for ligne in texte.splitlines() if not ligne.lstrip().startswith("#")]
        self.assertEqual([ligne for ligne in commandes if re.search(r"docker (start|restart|compose|rm|kill)", ligne)], [])
        self.assertEqual([ligne for ligne in commandes if "docker stop" in ligne and "refuser" not in ligne and "|" not in ligne], [])

    def test_a_lot_entier_pile_arretee(self):
        """(a) cicero-orders absent : 21 lancements sans réseau, un journal chacun, le décompte, puis comparer ; code 0."""
        code, sortie = self.lancer("3")
        self.assertEqual(code, 0, sortie)
        appels = self.doublures.appels()
        self.assertEqual(appels[:2], ["inspect --format {{.State.Status}} cicero-orders", "image inspect --format {{.Id}} cicero-webdip:latest"])
        self.assertEqual(len(appels), 23)
        self.assertEqual(len(self.lancements()), 21)
        self.assertEqual(self.lancements()[0], (
            "run --rm --gpus all -v %s/amont/couche-r:/mesure -v %s/amont/cicero/models:/opt/cicero/models:ro cicero-webdip:latest "
            "python /mesure/rejeu_moteur.py 3 S1901M AUSTRIA 5 --historique /mesure/resultats/historique_3.json --score sos "
            "--minutes-de-phase 4320 --engagements auto:prefere" % (self.racine, self.racine)))
        self.assertEqual([re.search(r"rejeu_moteur\.py 3 (\S+) (\S+) (\S+) ", a).groups() for a in self.lancements()],
                         [(phase, puissance, "5") for phase, puissance in capture_reference.POSITIONS_REPETEES])
        self.assertEqual(sorted(f.name for f in (self.lot / "journaux").iterdir()),
                         ["campagne.log", "comparer.txt"] + ["lancement_%02d.log" % n for n in range(1, 22)])
        self.assertEqual(self.journal("lancement_21.log"), "lancement doublé 21 : S1903M TURKEY, 10 ligne(s)\n")
        self.assertEqual(self.journal("comparer.txt"), "comparaison doublée\n")
        self.assertEqual((self.racine / "tests" / "appel_de_comparer.txt").read_text(encoding="utf-8"),
                         "comparer amont/couche-r/resultats --sortie amont/couche-r/couche_r.json")
        self.assertEqual((self.lot / "resultats" / "historique_3.json").read_text(encoding="utf-8"), '{"phases": []}')
        campagne = self.journal().splitlines()
        self.assertRegex(campagne[0], r"^début \S+ tête inconnue image sha256:doublure$")
        self.assertEqual(campagne[1], "cicero-orders : état initial absent (à restaurer à la main, ce script n'arrête ni ne relance rien)")
        self.assertIn("durée estimée : de 2 h 26 (campagne du 2026-10-10) à 4 h 03", campagne[2])
        self.assertEqual(campagne[3], "1/21 rejeu_moteur.py 3 S1901M AUSTRIA : carte : non relevée")
        self.assertRegex(campagne[4], r"^1/21 rejeu_moteur.py 3 S1901M AUSTRIA code=0 durée=\d+s \S+$")
        self.assertEqual(sum(" : carte : non relevée" in ligne for ligne in campagne), 21)
        self.assertEqual(campagne[-3], "décompte : 21 fichier(s) de relevés pour 21 lancement(s), 210 recherche(s) pour 210 attendue(s)")
        self.assertRegex(campagne[-2], r"^comparer code=0 ")
        self.assertRegex(campagne[-1], r"^fin \S+ code=0 ; cicero-orders : état initial absent, à restaurer à la main \(ce script ne relance rien\)$")
        self.assertEqual(sortie.splitlines()[-1], campagne[-1])
        self.assertEqual(self.doublures.appels("nvidia-smi"), [])
        # (g) de l'expert : les 21 « run » reçus sont exactement les 21 lancements imprimés, argument par argument.
        imprimes = self.lancements_imprimes("3")
        self.assertEqual(len(imprimes), 21)
        self.assertEqual(imprimes[0][:6], ["run", "--rm", "--gpus", "all", "-v", "%s/amont/couche-r:/mesure" % self.racine])
        self.assertEqual(self.lancements_recus(), imprimes)

    def test_a_lot_entier_sur_le_reseau_de_la_pile(self):
        """(g) de l'expert, avec --reseau : les 21 « run » reçus sont ceux qu'imprime `commandes 3 --couche-r --reseau …`."""
        code, sortie = self.lancer("3", "--reseau", "webdiplomacy_default")
        self.assertEqual(code, 0, sortie)
        imprimes = self.lancements_imprimes("3", "--reseau", "webdiplomacy_default")
        self.assertEqual(len(imprimes), 21)
        self.assertEqual(imprimes[0][:6], ["run", "--rm", "--gpus", "all", "--network", "webdiplomacy_default"])
        self.assertEqual(imprimes[0][10:16], ["-e", "WEBDIP_API_URL=http://webserver/api.php", "-e", "CICERO_REDIS_IP=redis",
                                              "-e", "CICERO_REDIS_PORT=6379"])
        self.assertEqual(self.lancements_recus(), imprimes)
        self.assertNotEqual(imprimes, self.lancements_imprimes("3"))

    def test_b_le_code_de_comparer_est_rendu_tel_quel(self):
        """(b) 1 : régression, 2 : non concluant ou lot invalide ; le script ne les transforme pas."""
        for code_de_comparer in (1, 2):
            self.comparer(code_de_comparer)
            lot = "amont/lot-%d" % code_de_comparer
            code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", "--dossier", lot)
            self.assertEqual(code, code_de_comparer, sortie)
            campagne = self.journal(lot=self.racine / lot).splitlines()
            self.assertEqual(campagne[-3], "décompte : 1 fichier(s) de relevés pour 1 lancement(s), 10 recherche(s) pour 10 attendue(s)")
            self.assertRegex(campagne[-1], r"^fin \S+ code=%d ; " % code_de_comparer)
            self.assertEqual((self.racine / "tests" / "appel_de_comparer.txt").read_text(encoding="utf-8"),
                             "comparer %s/resultats --sortie %s/couche_r.json --positions S1903M:FRANCE" % (lot, lot))
            self.assertIn("comparaison doublée", sortie)

    def test_b_un_autre_code_de_comparer_n_est_pas_un_verdict(self):
        """Hors 0, 1, 2 (erreur d'usage, exception, processus tué), le code de comparer se confondrait avec 3, 4, 5 :
        le script rend 6, cite le code reçu et renvoie à comparer.txt."""
        for code_de_comparer in (3, 4, 5, 137):
            self.comparer(code_de_comparer)
            lot = "amont/lot-%d" % code_de_comparer
            code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", "--dossier", lot)
            self.assertEqual(code, 6, sortie)
            campagne = self.journal(lot=self.racine / lot).splitlines()
            self.assertRegex(campagne[-3], r"^comparer code=%d " % code_de_comparer)
            self.assertEqual(campagne[-2], "ARRÊT : comparer est sorti en code %d, qui n'est pas un verdict (0, 1, 2) ; "
                             "voir %s/journaux/comparer.txt" % (code_de_comparer, lot))
            self.assertRegex(campagne[-1], r"^fin \S+ code=6 ; cicero-orders : ")
            self.assertEqual(sortie.splitlines()[-1], campagne[-1])
            self.assertEqual(self.journal("comparer.txt", lot=self.racine / lot), "comparaison doublée\n")

    def test_c_refus_si_cicero_orders_tourne(self):
        """(c) running, restarting, paused : le script n'arrête rien ; code 3, rien de créé, aucun lancement."""
        for etat in ("running", "restarting", "paused"):
            self.doublures.regler(etat=etat)
            sortie = self.refus("3", message="REFUS : cicero-orders est « %s » : ce script n'arrête rien" % etat)
            self.assertIn("état initial %s, à restaurer à la main" % etat, sortie.splitlines()[-1])
        self.assertEqual(self.doublures.appels(), ["inspect --format {{.State.Status}} cicero-orders"] * 3)

    def test_d_conteneur_arrete_rien_n_est_arrete_ni_relance(self):
        """(d) cicero-orders existe, arrêté (exited, created) : le lot se fait, sans « docker stop » ni « docker start »."""
        for etat in ("exited", "created"):
            self.doublures.regler(etat=etat)
            lot = "amont/lot-" + etat
            code, sortie = self.lancer("3", "--repetees", "S1903M", "--tirages", "2", "--dossier", lot)
            self.assertEqual(code, 0, sortie)
            self.assertIn("cicero-orders : état initial %s (à restaurer à la main" % etat, self.journal(lot=self.racine / lot))
        self.assertEqual(len(self.lancements()), 14)
        self.assertEqual(sorted({appel.split()[0] for appel in self.doublures.appels()}), ["image", "inspect", "run"])

    def test_e_arret_au_premier_lancement_en_echec(self):
        """(e) le deuxième lancement échoue : code 4, pas de troisième, comparer n'est pas lancé, le journal garde la sortie."""
        self.doublures.regler(echec_au=2)
        code, sortie = self.lancer("3")
        self.assertEqual(code, 4, sortie)
        self.assertEqual(len(self.lancements()), 2)
        self.assertFalse((self.racine / "tests" / "appel_de_comparer.txt").exists())
        self.assertEqual(sorted(f.name for f in (self.lot / "journaux").iterdir()), ["campagne.log", "lancement_01.log", "lancement_02.log"])
        self.assertEqual(self.journal("lancement_02.log"), "échec doublé du lancement 2\n")
        campagne = self.journal().splitlines()
        self.assertRegex(campagne[-3], r"^2/21 rejeu_moteur.py 3 S1901M ENGLAND code=7 durée=\d+s ")
        self.assertRegex(campagne[-2], r"^ARRÊT : lancement 2 en échec \(code 7\), voir amont/couche-r/journaux/lancement_02.log")
        self.assertRegex(campagne[-1], r"^fin \S+ code=4 ; ")
        self.assertEqual(sortie.splitlines()[-1], campagne[-1])

    def test_f_decompte_final_faux(self):
        """(f) une recherche manque dans chaque fichier, ou aucun fichier n'est écrit : code 5, comparer n'est pas lancé."""
        for reglage, decompte in ((dict(lignes_en_moins=1), "2 fichier(s) de relevés pour 2 lancement(s), 18 recherche(s) pour 20 attendue(s)"),
                                  (dict(sans_releve=1), "0 fichier(s) de relevés pour 2 lancement(s), 0 recherche(s) pour 20 attendue(s)")):
            self.doublures.regler(**reglage)
            lot = "amont/lot-" + next(iter(reglage))
            code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", "S1903M:TURKEY", "--dossier", lot)
            self.assertEqual(code, 5, sortie)
            campagne = self.journal(lot=self.racine / lot).splitlines()
            self.assertEqual(campagne[-3], "décompte : " + decompte)
            self.assertEqual(campagne[-2], "ARRÊT : décompte faux ; comparer n'est pas lancé")
            self.assertRegex(campagne[-1], r"^fin \S+ code=5 ; ")
            self.assertFalse((self.racine / "tests" / "appel_de_comparer.txt").exists())
            self.assertFalse((self.racine / lot / "journaux" / "comparer.txt").exists())

    def test_g_refus_avant_toute_ecriture(self):
        """(g) arguments refusés par capture_reference.py, dossier déjà là, image ou docker absents, aucun argument :
        code 3, l'arbre est inchangé, aucun lancement."""
        self.refus(message="REFUS : usage : lancer_couche_r.sh GAMEID")
        self.refus("3", "--dossier", "/tmp/x y;rm", message="REFUS : capture_reference.py commandes a refusé les arguments")
        self.refus("3", "--phases", "S1901M;id", message="phase invalide : 'S1901M;id'")
        self.refus("3", "--repetees", "S1901M;id:FRANCE", message="position inconnue : 'S1901M;id:FRANCE'")
        self.refus("trois", message="REFUS : capture_reference.py commandes a refusé les arguments")
        self.assertEqual(self.doublures.appels(), [])  # refusés avant tout appel à docker
        (self.racine / "amont" / "deja-la").mkdir()
        self.refus("3", "--dossier", "amont/deja-la", message="REFUS : amont/deja-la existe déjà")
        self.assertEqual(self.doublures.appels(), [])
        self.doublures.regler(sans_image=1)
        self.refus("3", message="REFUS : image cicero-webdip:latest absente, ou Docker ne répond pas")
        (self.racine / "tests" / "reference" / "historique.json").unlink()
        self.refus("3", message="REFUS : tests/reference/historique.json absent")
        (self.doublures.bin / "docker").unlink()
        self.refus("3", message="REFUS : docker introuvable")

    def test_h_memoire_de_la_carte_et_reseau(self):
        """(h) nvidia-smi présent : la mémoire utilisée de la carte est écrite avant chaque lancement, sans seuil ni
        verdict ; --reseau passe aux lancements avec les variables de la pile."""
        self.doublures.poser("nvidia-smi", DOUBLURE_DE_NVIDIA_SMI)
        code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", "S1903M:TURKEY", "--reseau", "webdiplomacy_default")
        self.assertEqual(code, 0, sortie)
        campagne = self.journal().splitlines()
        self.assertEqual(campagne[3], "1/2 rejeu_moteur.py 3 S1903M FRANCE : carte : 4605, 8192 (Mio utilisés, total)")
        self.assertEqual(campagne[5], "2/2 rejeu_moteur.py 3 S1903M TURKEY : carte : 4605, 8192 (Mio utilisés, total)")
        self.assertEqual(self.doublures.appels("nvidia-smi"), ["--query-gpu=memory.used,memory.total --format=csv,noheader,nounits"] * 2)
        for appel in self.lancements():
            self.assertIn("run --rm --gpus all --network webdiplomacy_default -v ", appel)
            self.assertIn(" -e WEBDIP_API_URL=http://webserver/api.php -e CICERO_REDIS_IP=redis -e CICERO_REDIS_PORT=6379 cicero-webdip:latest ", appel)
        self.doublures.poser("nvidia-smi", "#!/bin/bash\nexit 9\n")
        code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", "--dossier", "amont/lot-sans-carte")
        self.assertEqual(code, 0, sortie)
        self.assertIn(" : carte : non relevée (nvidia-smi en échec)", self.journal(lot=self.racine / "amont" / "lot-sans-carte"))

    def test_i_rien_n_est_cree_si_la_preparation_ne_peut_pas_aboutir(self):
        """Code 3 = rien de créé. Un dossier dans tests/mesure (« cp tests/mesure/* » sortirait en erreur après avoir
        créé le dossier du lot) : refus avant toute écriture, et la relance passe une fois le dossier retiré. Une
        préparation qui échoue quand même (cp doublé) : le dossier du lot, créé par le script, est supprimé. Un
        dossier que le script n'a pas créé (mkdir en échec) n'est pas supprimé. Si la suppression échoue (rm doublé),
        le message dit que le dossier reste."""
        intrus = self.racine / "tests" / "mesure" / "__pycache__"
        intrus.mkdir()
        self.refus("3", message="REFUS : tests/mesure/__pycache__ n'est pas un fichier ordinaire")
        intrus.rmdir()
        vrai_cp, vrai_mkdir = shutil.which("cp"), shutil.which("mkdir")
        self.doublures.poser("cp", "#!/bin/bash\necho 'cp doublé : en échec' >&2\nexit 1\n")
        sortie = self.refus("3", "--dossier", "amont/lot-cp", message="REFUS : préparation en échec : cp tests/mesure/* amont/lot-cp/")
        self.assertIn("dossier amont/lot-cp supprimé (créé par ce script, préparation en échec)", sortie)
        # La suppression échoue aussi (rm doublé) : code 3 toujours, et le message dit que le dossier reste.
        vrai_rm = shutil.which("rm")
        self.doublures.poser("rm", "#!/bin/bash\necho 'rm doublé : en échec' >&2\nexit 1\n")
        code, sortie = self.lancer("3", "--dossier", "amont/lot-rm")
        self.assertEqual(code, 3, sortie)
        self.assertIn("dossier amont/lot-rm NON supprimé, à retirer à la main", sortie)
        self.assertNotIn("dossier amont/lot-rm supprimé", sortie)
        self.assertIn("REFUS : préparation en échec : cp tests/mesure/* amont/lot-rm/", sortie)
        self.assertRegex(sortie.splitlines()[-1], r"^fin \S+ code=3 ; ")
        self.assertTrue((self.racine / "amont" / "lot-rm").is_dir())
        self.assertEqual(self.lancements(), [])
        self.doublures.poser("rm", '#!/bin/bash\nexec %s "$@"\n' % vrai_rm)
        self.doublures.poser("cp", '#!/bin/bash\nexec %s "$@"\n' % vrai_cp)
        # Un autre que le script crée le dossier entre le contrôle et la préparation : « mkdir » échoue, le dossier reste.
        self.doublures.poser("mkdir", '#!/bin/bash\n%s "$@"\nexit 1\n' % vrai_mkdir)
        code, sortie = self.lancer("3", "--dossier", "amont/lot-d-un-autre")
        self.assertEqual(code, 3, sortie)
        self.assertIn("REFUS : préparation en échec : mkdir amont/lot-d-un-autre", sortie)
        self.assertNotIn("supprimé", sortie)
        self.assertTrue((self.racine / "amont" / "lot-d-un-autre").is_dir())
        self.assertEqual(self.lancements(), [])
        # Relance possible : après les deux refus, le dossier par défaut et celui du lot refusé sont libres.
        self.doublures.poser("mkdir", '#!/bin/bash\nexec %s "$@"\n' % vrai_mkdir)
        for options in ((), ("--dossier", "amont/lot-cp")):
            code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", *options)
            self.assertEqual(code, 0, sortie)

    def interrompre(self, signal_recu, au_groupe, lot):
        """Lance deux lancements dont la doublure dort, attend que la première écrive son témoin (elle n'a plus qu'à
        dormir : la ligne « run » de son journal précède encore des substitutions de commande), envoie le signal ;
        rend (code, sortie). Aucune échéance n'est une mesure : elles ne bornent qu'un essai bloqué."""
        self.doublures.regler(dort=2)
        temoin = self.doublures.dossier / "va_dormir"
        if temoin.exists():
            temoin.unlink()
        processus = self.doublures.demarrer(
            ["bash", str(self.racine / "tests" / "mesure" / "lancer_couche_r.sh"), "3", "--repetees", "S1903M:FRANCE", "S1903M:TURKEY",
             "--dossier", lot], cwd=self.doublures.dossier)

        def nettoyer():  # la doublure qui dort, si elle a survécu au script
            try:
                os.killpg(processus.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            processus.stdout.close()
            processus.wait()

        self.addCleanup(nettoyer)
        deja = len(self.lancements())
        echeance = time.time() + 120
        while not temoin.exists() and time.time() < echeance:
            time.sleep(0.02)
        self.assertTrue(temoin.exists(), "le premier lancement n'a pas commencé")
        self.assertEqual(len(self.lancements()), deja + 1)
        if au_groupe:
            os.killpg(processus.pid, signal_recu)
        else:
            os.kill(processus.pid, signal_recu)
        sortie, _ = processus.communicate(timeout=120)
        self.assertEqual(len(self.lancements()), deja + 1, sortie)  # pas de second lancement
        self.assertFalse((self.racine / "tests" / "appel_de_comparer.txt").exists())
        return processus.returncode, sortie

    def test_j_interruption(self):
        """SIGINT, SIGTERM, SIGHUP : la ligne « fin » porte 130, 143 ou 129 (elle écrivait code=0), dit « interrompu »
        et nomme le lancement en cours ; ni second lancement ni comparaison. Signal au groupe (Ctrl-C, terminal
        fermé) : la doublure qui dort meurt aussi, son journal est vide et elle n'a pas écrit son relevé. Signal au
        script seul : bash ne le traite qu'à la fin du lancement en cours, dont le journal et le relevé sont complets."""
        for nom, code_attendu, au_groupe in (("INT", 130, True), ("HUP", 129, True), ("TERM", 143, False), ("INT", 130, False)):
            lot = "amont/lot-%s-%s" % (nom.lower(), "groupe" if au_groupe else "seul")
            debut = time.time()
            code, sortie = self.interrompre(getattr(signal, "SIG" + nom), au_groupe, lot)
            duree = time.time() - debut
            self.assertEqual(code, code_attendu, sortie)
            campagne = self.journal(lot=self.racine / lot).splitlines()
            self.assertRegex(campagne[-1], r"^fin \S+ code=%d ; interrompu \(SIG%s\) pendant le lancement 1/2 rejeu_moteur.py 3 S1903M FRANCE ; "
                             r"cicero-orders : état initial absent, à restaurer à la main \(ce script ne relance rien\)$" % (code_attendu, nom))
            self.assertEqual(sortie.splitlines()[-1], campagne[-1])
            self.assertEqual(campagne[-2], "1/2 rejeu_moteur.py 3 S1903M FRANCE : carte : non relevée")
            journal = self.journal("lancement_01.log", lot=self.racine / lot)
            releves = sorted(f.name for f in (self.racine / lot / "resultats").glob("m1_*.jsonl"))
            if au_groupe:
                self.assertEqual(journal, "")
                self.assertEqual(releves, [], sortie)
            else:
                self.assertEqual(journal, "lancement doublé %d : S1903M FRANCE, 10 ligne(s)\n" % len(self.lancements()))
                self.assertEqual(releves, ["m1_3_S1903M_FRANCE_engagements_doublure.jsonl"], sortie)
                self.assertGreaterEqual(duree, 1.9, sortie)  # le sommeil de la doublure, entier : borne basse, sans risque sous charge

    def test_k_une_ligne_reconnue_a_son_seul_debut_n_est_pas_executee(self):
        """« mkdir », « cp », la comparaison et un lancement n'étaient reconnus qu'à leur préfixe : une ligne
        « mkdir x; mkdir PWNED » de la suite était exécutée. Chaque ligne est reconnue à sa forme entière ; sinon
        code 3, rien d'exécuté, rien de créé."""
        capture = self.racine / "tests" / "mesure" / "capture_reference.py"
        texte = capture.read_text(encoding="utf-8")
        ancre = '        "# 1. Historique des ordres : celui du jeu d\'essai.",\n'
        premiere = 'cp tests/mesure/* %s/" % (dossier, dossier, dossier),'
        gabarit_de_docker = "    '  {commande}'\n)"
        comparaison = "python3 tests/reference_couche_r.py comparer amont/couche-r/resultats --sortie amont/couche-r/couche_r.json"
        for motif in (ancre, premiere, gabarit_de_docker):
            self.assertEqual(texte.count(motif), 1, motif)
        injectee = lambda ligne: texte.replace(ancre, ancre + "        %r,\n" % ligne)  # noqa: E731
        for modifie, refusee in (
                (injectee("mkdir x; mkdir PWNED"), "mkdir x; mkdir PWNED"),
                (injectee("mkdir amont/couche-r/x && mkdir PWNED"), "mkdir amont/couche-r/x && mkdir PWNED"),
                (injectee("cp tests/mesure/commun.py PWNED"), "cp tests/mesure/commun.py PWNED"),
                (injectee("cp tests/reference/historique.json amont/couche-r/resultats/historique_3.json; mkdir PWNED"), "; mkdir PWNED"),
                (injectee(comparaison + "; mkdir PWNED"), comparaison + "; mkdir PWNED"),
                (injectee(comparaison + " --positions S1903M:FRANCE $(mkdir PWNED)"), "$(mkdir PWNED)"),
                (injectee("docker run --rm --privileged cicero-webdip:latest id"), "docker run --rm --privileged cicero-webdip:latest id"),
                (texte.replace(premiere, premiere.replace('/"', '/; mkdir PWNED"')), "amont/couche-r/; mkdir PWNED"),
                (texte.replace(gabarit_de_docker, "    '  {commande}; mkdir PWNED'\n)"), "--engagements auto:prefere; mkdir PWNED"),
                (texte.replace("docker run --rm{gpu}{reseau}", "docker run --rm --privileged{gpu}{reseau}"), "docker run --rm --privileged --gpus all")):
            self.assertNotEqual(modifie, texte, refusee)
            capture.write_text(modifie, encoding="utf-8")
            sortie = self.refus("3", message="REFUS : ligne de la suite non reconnue : ")
            self.assertIn(refusee, sortie)
            self.assertEqual(self.doublures.appels(), [])
            self.assertEqual([f for f in self.arbre() if "PWNED" in f], [])
        # Une dernière ligne terminée par « \\ » n'a pas de suite : elle n'était ni exécutée ni refusée (code 0).
        derniere = '        "# 4. cicero-orders est resté arrêté : le remettre à la main dans l\'état noté à l\'étape 2.",\n'
        self.assertEqual(texte.count(derniere), 1)
        for inachevee in ("mkdir PWNED \\", comparaison + " \\"):
            capture.write_text(texte.replace(derniere, derniere + "        %r,\n" % inachevee), encoding="utf-8")
            sortie = self.refus("3", message="REFUS : ligne de la suite inachevée (terminée par « \\ ») : " + inachevee[:-1])
            self.assertEqual(self.doublures.appels(), [])
            self.assertEqual([f for f in self.arbre() if "PWNED" in f], [])
        capture.write_text(texte, encoding="utf-8")
        code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", "--reseau", "un.reseau-2")
        self.assertEqual(code, 0, sortie)

    def test_l_le_dossier_du_lot_n_est_pas_dans_un_clone_d_amont(self):
        """amont/cicero et amont/webdiplomacy sont les clones d'amont, dont outils/exporter_patchs.sh parcourt les
        fichiers non suivis : capture_reference.py refuse d'y placer un lot, et le script aussi, de lui-même (ici
        avec un capture_reference.py qui l'accepterait encore). Un nom voisin (amont/cicerone) reste admis."""
        capture = self.racine / "tests" / "mesure" / "capture_reference.py"
        texte = capture.read_text(encoding="utf-8")
        for nom in ("cicero", "webdiplomacy", "cicerone"):
            (self.racine / "amont" / nom).mkdir()
        for dossier in ("amont/cicero/x", "amont/webdiplomacy/x", "amont/cicero", "amont/cicero/x/y"):
            self.refus("3", "--dossier", dossier, message="REFUS : capture_reference.py commandes a refusé les arguments")
        self.assertIn("ni amont/cicero ni amont/webdiplomacy", self.refus(
            "3", "--dossier", "amont/cicero/x", message="dossier (sous amont/"))
        permissif, remplacements = re.subn(r"(?m)^DOSSIER = re\.compile\(.*$",
                                           'DOSSIER = re.compile(r"amont(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)+")', texte)
        self.assertEqual(remplacements, 1)
        capture.write_text(permissif, encoding="utf-8")
        for dossier in ("amont/cicero/x", "amont/webdiplomacy/x", "amont/cicero", "amont/cicero/x/y"):
            self.refus("3", "--dossier", dossier, message="REFUS : dossier du lot dans un clone d'amont "
                       "(amont/cicero, amont/webdiplomacy) : %s\n" % dossier)
        self.assertEqual(self.doublures.appels(), [])
        for capture_du_depot in (permissif, texte):
            capture.write_text(capture_du_depot, encoding="utf-8")
            lot = "amont/cicerone/%s" % ("x" if capture_du_depot is texte else "y")
            code, sortie = self.lancer("3", "--repetees", "S1903M:FRANCE", "--dossier", lot)
            self.assertEqual(code, 0, sortie)
            self.assertTrue((self.racine / lot / "journaux" / "campagne.log").is_file())

    def test_une_ligne_inconnue_de_la_suite_arrete_tout(self):
        """Le script reconnaît chaque ligne de la suite à sa forme : si capture_reference.py en imprime une autre
        (ici « docker start cicero-orders »), il refuse au lieu de l'exécuter."""
        capture = self.racine / "tests" / "mesure" / "capture_reference.py"
        texte = capture.read_text(encoding="utf-8")
        ancre = '        "# 4. cicero-orders est resté arrêté'
        self.assertEqual(texte.count(ancre), 1)
        capture.write_text(texte.replace(ancre, '        "docker start cicero-orders",\n' + ancre), encoding="utf-8")
        self.refus("3", message="REFUS : ligne de la suite non reconnue : docker start cicero-orders")
        self.assertEqual(self.doublures.appels(), [])


class EssaiASec(unittest.TestCase):
    """Le mode à sec de rejeu_moteur.py : table de la doublure, arguments d'export relevés, rejeu de l'historique.

    Sur la table fabriquée, que tests/reference/ soit rempli ou non : ces tests ne dépendent pas du jeu d'essai.
    """

    def lancer(self, *options, arret_attendu=False, plans=None):
        """(sortie, relevés) d'un lancement à sec. `arret_attendu` : la sortie en erreur du lancement (SystemExit) est
        gardée dans self.arret au lieu d'être levée, les relevés écrits avant elle sont rendus. `plans` : les plans
        d'une table S1902M / ITALY posée comme référence de la doublure (sinon aucune : table fabriquée)."""
        self.arret = None
        with tempfile.TemporaryDirectory() as tmp:
            historique = Path(tmp) / "historique.json"
            historique.write_text(json.dumps(capture_reference.HISTORIQUE_DOUBLURE), encoding="utf-8")
            if plans is not None:
                reference_jeu.ecrire_json(Path(tmp) / "sans_reference" / "tables" / "S1902M.json",
                                          {"phase": "S1902M", "tables": {"ITALY": {"plans": plans}}})
            options = [str(historique) if o == "HISTORIQUE" else o for o in options]
            sortie = io.StringIO()
            # main() règle le journal racine (niveau INFO, un gestionnaire de plus) : l'essai tourne sans les
            # gestionnaires déjà là, qui afficheraient chaque export, et le niveau est remis après lui.
            racine = rejeu_moteur.logging.getLogger()
            niveau = racine.level
            # MESURE_DIR est lu à l'import de commun : le dossier de mesure se règle sur le module.
            with mock.patch.object(rejeu_moteur.commun, "MESURE_DIR", Path(tmp)), \
                    mock.patch.object(sys, "argv", ["rejeu_moteur.py"] + options + ["--dry-run"]), \
                    mock.patch.object(rejeu_moteur.SondeGPU, "COMMANDE", ["false"]), \
                    mock.patch.object(racine, "handlers", []), \
                    mock.patch.object(rejeu_moteur, "REFERENCE", Path(tmp) / "sans_reference"), \
                    mock.patch.dict("os.environ"), contextlib.redirect_stdout(sortie):
                try:
                    rejeu_moteur.main()
                except SystemExit as e:
                    if not arret_attendu:
                        raise
                    self.arret = e
                finally:
                    racine.setLevel(niveau)
            releves = [
                json.loads(ligne) for fichier in sorted((Path(tmp) / "resultats_sec").glob("*.jsonl"))
                for ligne in fichier.read_text(encoding="utf-8").splitlines()
            ]
        return sortie.getvalue(), releves

    def test_reference_vide_table_fabriquee(self):
        with tempfile.TemporaryDirectory() as vide:
            table, provenance = rejeu_moteur.table_de_la_doublure(vide)
        self.assertEqual(table, rejeu_moteur.TABLE_FABRIQUEE)
        self.assertIn("table fabriquée", provenance)

    def test_la_table_fabriquee_n_est_pas_tiree_d_une_partie(self):
        """Aucun extrait de partie dans le script (ADR 0006, décision 5) : tout ordre qui y est écrit porte sur
        une unité du banc de tests, et toute valeur de la table fabriquée a trois décimales au plus (une valeur
        exportée en a cinq)."""
        source = Path(rejeu_moteur.__file__).read_text(encoding="utf-8")
        ordres = [o for o in re.findall(r'"([AF] [A-Z]{3}[^"\n]*)"', source) if reference_jeu.est_ordre(o)]
        self.assertEqual(len(ordres), 4 * len(rejeu_moteur.TABLE_FABRIQUEE))
        self.assertLessEqual({banc.get_unit_location(o) for o in ordres}, set(banc.ORDRES_LEGAUX) | {"PIC"})
        self.assertEqual([v for _a, v, _p in rejeu_moteur.TABLE_FABRIQUEE if round(v, 3) != v], [])
        self.assertEqual(re.findall(r"\b0\.[0-9]{5,}\b", source), [])

    def test_la_table_vient_de_la_reference_quand_elle_y_est(self):
        with tempfile.TemporaryDirectory() as tmp:
            plans = [{"rank": i + 1, "orders": ["A VEN H", "F NAP - ION" if i else "F NAP H"], "value": 0.2 - i / 100, "cost_vs_best": i / 100}
                     for i in range(3)]
            reference_jeu.ecrire_json(Path(tmp) / "tables" / "S1902M.json", {"phase": "S1902M", "tables": {"ITALY": {"plans": plans}}})
            table, provenance = rejeu_moteur.table_de_la_doublure(tmp)
        self.assertEqual([(a, v) for a, v, _p in table], [(tuple(p["orders"]), p["value"]) for p in plans])
        self.assertAlmostEqual(sum(p for _a, _v, p in table), 1.0)
        self.assertIn("S1902M ITALY", provenance)

    def test_engagements_et_arguments_d_export(self):
        sortie, releves = self.lancer("3", "S1902M", "ITALY", "1")
        self.assertEqual([r["recherche"] for r in releves], ["A", "B"])
        for releve in releves:
            self.assertTrue(releve["a_sec"])
            self.assertEqual(releve["appels_export"], 1)
            c = releve["controles"]
            self.assertTrue(c["table_dans_politique_avant"] and c["tete_recalculee_egale_exportee"] and c["tete_recalculee_egale_rendue"])
            # Les arguments relevés, réduits puis rejoués par D1, redonnent l'entrée exportée.
            _phase, _puissance, table = reference_jeu.reduire_releve(releve, releve["recherche"], a_sec=True)
            with tempfile.TemporaryDirectory() as tmp:
                rejouee = couche_d.d1(couche_d.charger_modules(), "S1902M", "ITALY", table, tmp)
            self.assertEqual(couche_d.differences({c: table[c] for c in reference_jeu.CLES_TABLE}, rejouee), [])
        self.assertTrue(releves[1]["engagements_retenus_par_le_moteur"])
        self.assertNotEqual(
            [a[2] for a in releves[1]["arguments_export"]["action_values"]],
            [dict((tuple(o), p) for o, p in releves[1]["arguments_export"]["prior_policy"])[tuple(a[0])]
             for a in releves[1]["arguments_export"]["action_values"]],
        )

    def test_l_engagement_est_fige_au_tirage_0(self):
        """auto:prefere : choisi une fois, sur la recherche A du tirage 0, gardé pour tous les tirages, relevé avec sa raison."""
        choix = iter([(["A PIC H"], "premier choix"), (["A MAR - SPA"], "deuxième choix"), (["F BRE - MAO"], "troisième choix")])
        appels = []

        def choisir(entree, mode):
            appels.append(mode)
            return next(choix)
        with mock.patch.object(rejeu_moteur.commun, "choisir_engagements", choisir):
            sortie, releves = self.lancer("3", "S1902M", "ITALY", "3")
        self.assertEqual(appels, ["prefere"])
        self.assertEqual([(r["tirage"], r["recherche"]) for r in releves], [(0, "A"), (0, "B"), (1, "A"), (1, "B"), (2, "A"), (2, "B")])
        self.assertEqual([r["engagements_du_fichier"] for r in releves if r["recherche"] == "B"], [["A PIC H"]] * 3)
        premiere, suivantes = releves[0], releves[1:]
        self.assertEqual((premiere["engagement_fige"], premiere["raison_de_l_engagement"], premiere["engagement_choisi_au_tirage"]),
                         (None, None, None))  # la seule ligne écrite avant le choix
        for releve in suivantes:
            self.assertEqual((releve["engagement_fige"], releve["raison_de_l_engagement"], releve["engagement_choisi_au_tirage"]),
                             (["A PIC H"], "premier choix", 0))
        self.assertIn("tirage 2 engagements fabriqués : ['A PIC H'] (premier choix ; figé au tirage 0)", sortie)

    def test_sans_engagement_possible_au_tirage_0_aucune_recherche_b(self):
        """Rien à promettre au tirage 0 : c'est figé aussi, aucun tirage ne fait de recherche B ; les recherches A sont
        relevées, puis le lancement le dit et sort en erreur (une position sans recherche B ne passe pas inaperçue)."""
        with mock.patch.object(rejeu_moteur.commun, "choisir_engagements", lambda entree, mode: ([], "aucune alternative")):
            sortie, releves = self.lancer("3", "S1902M", "ITALY", "2", "--engagements", "auto:alternative", arret_attendu=True)
        self.assertEqual([(r["tirage"], r["recherche"]) for r in releves], [(0, "A"), (1, "A")])
        self.assertEqual(releves[1]["engagement_fige"], [])
        self.assertEqual(sortie.count("recherche B non faite"), 2)
        self.assertIn("M1 terminé : ", sortie)  # les relevés sont écrits avant la sortie en erreur
        self.assertIsNotNone(self.arret, "le lancement sort en code 0")
        # Un message en guise de code : l'interpréteur l'écrit sur la sortie d'erreur et rend 1.
        self.assertIsInstance(self.arret.code, str)
        self.assertRegex(self.arret.code, r"^ÉCHEC : --engagements auto:alternative n'a trouvé aucun engagement à fabriquer sur "
                                          r"la recherche A du tirage 0 \(aucune alternative\) : engagement figé vide, aucune "
                                          r"recherche B pour S1902M ITALY sur 2 tirage\(s\)\. Les recherches A sont relevées "
                                          r"dans .*/m1_3_S1902M_ITALY_engagements_[0-9-]+\.jsonl\.$")

    def test_table_qui_n_offre_pas_d_alternative(self):
        """Le même cas sans doubler le choix : une table de référence dont les plans jouent tous les mêmes ordres
        n'exporte qu'une action, auto:alternative n'y trouve rien, auto:prefere y trouve encore un ordre."""
        plans = [{"rank": i + 1, "orders": ["A VEN H", "F NAP H"], "value": 0.2 - i / 100, "cost_vs_best": i / 100} for i in range(2)]
        _sortie, releves = self.lancer("3", "S1902M", "ITALY", "2", "--engagements", "auto:alternative", arret_attendu=True, plans=plans)
        self.assertEqual([(r["tirage"], r["recherche"]) for r in releves], [(0, "A"), (1, "A")])
        self.assertEqual(len(releves[0]["entree"]["plans"]), 1)
        self.assertIn("(aucune alternative ne s'écarte du plan préféré) : engagement figé vide", self.arret.code)
        _sortie, releves = self.lancer("3", "S1902M", "ITALY", "2", "--engagements", "auto:prefere", arret_attendu=True, plans=plans)
        self.assertEqual([(r["tirage"], r["recherche"]) for r in releves], [(0, "A"), (0, "B"), (1, "A"), (1, "B")])
        self.assertIsNone(self.arret)

    def test_les_autres_modes_ne_sortent_pas_en_erreur_sans_recherche_b(self):
        """Le signal ne porte que sur l'engagement figé (auto:*) : --engagements aucun ne fait pas de recherche B par
        construction, et un fichier d'engagements vide reste un choix de l'appelant."""
        _sortie, releves = self.lancer("3", "S1902M", "ITALY", "2", "--engagements", "aucun", arret_attendu=True)
        self.assertEqual(([r["recherche"] for r in releves], self.arret), (["A", "A"], None))
        with tempfile.TemporaryDirectory() as tmp:
            fichier = Path(tmp) / "engagements.json"
            fichier.write_text("[]", encoding="utf-8")
            _sortie, releves = self.lancer("3", "S1902M", "ITALY", "1", "--engagements", str(fichier), arret_attendu=True)
        self.assertEqual(([r["recherche"] for r in releves], self.arret), (["A"], None))

    def test_etiquette_dans_le_nom_du_fichier(self):
        """La seconde passe écrit un fichier que le motif de la réduction (m1_*_engagements_*.jsonl) ne prend pas."""
        sortie, _releves = self.lancer("3", "S1902M", "ITALY", "1", "--etiquette", "passe2")
        nom = re.search(r"M1 terminé : .*/(m1_[^/]+\.jsonl)", sortie).group(1)
        self.assertRegex(nom, r"^m1_3_S1902M_ITALY_engagements-passe2_[0-9-]+\.jsonl$")
        self.assertNotRegex(nom, r"_engagements_")
        with self.assertRaises(SystemExit):
            self.lancer("3", "S1902M", "ITALY", "1", "--etiquette", "../ailleurs")

    def test_recherche_a_seule(self):
        _sortie, releves = self.lancer("3", "S1902M", "ITALY", "2", "--engagements", "aucun")
        self.assertEqual([(r["tirage"], r["recherche"]) for r in releves], [(0, "A"), (1, "A")])

    def test_position_depuis_l_historique(self):
        _sortie, releves = self.lancer("3", "F1901M", "FRANCE", "1", "--historique", "HISTORIQUE", "--engagements", "aucun")
        self.assertEqual(releves[0]["statut"]["source"], "historique")
        self.assertEqual(releves[0]["statut"]["phases_rejouees"], 1)

    def test_renfort_compose_toujours_vu(self):
        sortie, _releves = self.lancer("3", "S1902M", "ITALY", "1", "--incremental", "--doublure-compose")
        self.assertIn("renfort non composé B -> C : probabilités égales : False ; croissantes : True", sortie)
        sortie, _releves = self.lancer("3", "S1902M", "ITALY", "1", "--incremental")
        self.assertIn("renfort non composé B -> C : probabilités égales : True ; croissantes : False", sortie)


# Contenu du jeu d'essai versionné (tests/reference/, posé le 2026-10-10 et résumé le 2026-10-11). Le test exige
# l'égalité sur tout ce qui suit, sauf le nombre de grandeurs de la couche D, seul plancher (une grandeur peut
# s'ajouter) : le jeu ne peut ni grandir, ni s'amenuiser, ni disparaître sans qu'une de ces constantes change,
# dans le même commit, après visa.
PHASES_DU_JEU = ("S1901M", "F1901M", "S1902M", "F1902M", "S1903M", "F1903M")
TABLES_DU_JEU = 42  # 6 phases x 7 puissances
POSITIONS_REPETEES_DU_JEU = 21
GRANDEURS_DU_JEU = 24770  # comparées par la couche D
# Ce qu'aucune couche ne rejoue (#40), remesuré le 2026-10-11 sur tests/reference/. Le résumé : un ordre ou une
# tête qui en sort ne change aucune grandeur jugée. L'historique : la couche D ne lit que les ordres des phases de
# mouvement (D6) ; les quatre premières phases hors mouvement servent au rejeu des positions sur le moteur
# (couche R, hors batterie) et W1903A n'est lue par rien. Leurs ordres sont donc écrits ici en clair, 21 ordres
# (11 + 2 + 3 + 1 + 4). Ces constantes ne jugent que le jeu du dépôt : sur une copie, rien ne garde ces ordres.
ORDRES_RESUMES_DU_JEU = 328  # clés d'`order_values` du résumé, sur les 21 positions
TETES_RESUMEES_DU_JEU = 28
PHASES_DE_L_HISTORIQUE = ("S1901M", "F1901M", "W1901A", "S1902M", "F1902M", "F1902R", "W1902A", "S1903M", "S1903R",
                          "F1903M", "W1903A")
ORDRES_HORS_MOUVEMENT = {
    "W1901A": {"AUSTRIA": ["A VIE B", "A BUD B"], "ENGLAND": ["F LON B"], "FRANCE": ["F BRE B", "A PAR B", "F MAR B"],
               "GERMANY": ["F KIE B", "A BER B"], "ITALY": ["F NAP B"], "RUSSIA": ["A WAR B"], "TURKEY": ["A SMY B"]},
    "F1902R": {"RUSSIA": ["F SEV D"], "TURKEY": ["A BUL D"]},
    "W1902A": {"AUSTRIA": ["F TRI B"], "ENGLAND": ["A LON B"], "TURKEY": ["F SMY B"]},
    "S1903R": {"RUSSIA": ["F BAL R BOT"]},
    "W1903A": {"ENGLAND": ["A EDI B"], "FRANCE": ["A PAR B"], "GERMANY": ["A SIL D"], "ITALY": ["F ION D"]},
}


class JeuDuDepot(unittest.TestCase):
    """Le jeu d'essai du dépôt est exigé par la batterie : absent, vide ou amenuisé, il la fait échouer.

    Les fonctions (`controler`, la couche D) passent sur un dossier absent ou vide, et un manifeste refait
    sur un jeu raccourci est fidèle à son dossier : sans ces planchers, une référence qui disparaît ou perd
    une phase laissait la batterie verte, la couche D rendant 0 différence sur ce qui restait."""

    def test_planchers_du_jeu_versionne(self):
        dossier = reference_jeu.DOSSIER
        self.assertTrue((dossier / reference_jeu.MANIFESTE).is_file(), "%s absent : la référence de non-régression "
                        "est exigée (la restaurer depuis git)" % (dossier / reference_jeu.MANIFESTE))
        jeu = reference_jeu.lire_jeu(dossier)
        self.assertEqual(tuple(jeu["tables"]), PHASES_DU_JEU)
        self.assertEqual({phase: list(tables) for phase, tables in jeu["tables"].items()},
                         {phase: reference_jeu.POWERS for phase in PHASES_DU_JEU})
        self.assertEqual(sum(len(tables) for tables in jeu["tables"].values()), TABLES_DU_JEU)
        resume = reference_jeu.lire_repetee(dossier)
        self.assertIsNotNone(resume, "%s absent : le résumé des positions répétées (couche R) est exigé" % reference_jeu.REPETEE)
        self.assertEqual(sum(len(par_puissance) for par_puissance in resume["positions"].values()), POSITIONS_REPETEES_DU_JEU)
        _lignes, grandeurs, sans_attendus = couche_d.comparer(couche_d.attendus_complets(jeu), couche_d.calculer(jeu))
        self.assertEqual(sans_attendus, [])
        self.assertGreaterEqual(grandeurs, GRANDEURS_DU_JEU)

    def test_contenu_du_resume_versionne(self):
        resume = reference_jeu.lire_repetee(reference_jeu.DOSSIER)
        self.assertIsNotNone(resume, "%s absent : le résumé des positions répétées (couche R) est exigé" % reference_jeu.REPETEE)
        resumes = [r for par_puissance in resume["positions"].values() for r in par_puissance.values()]
        self.assertEqual(len(resumes), POSITIONS_REPETEES_DU_JEU)
        self.assertEqual(sum(len(r["order_values"]) for r in resumes), ORDRES_RESUMES_DU_JEU)
        self.assertEqual(sum(len(r["tetes"]) for r in resumes), TETES_RESUMEES_DU_JEU)

    def test_historique_versionne(self):
        phases = reference_jeu.lire_jeu(reference_jeu.DOSSIER)["historique"]["phases"]
        self.assertEqual(tuple(phase["name"] for phase in phases), PHASES_DE_L_HISTORIQUE)
        hors_mouvement = {phase["name"]: phase["orders"] for phase in phases if not phase["name"].endswith("M")}
        self.assertEqual(hors_mouvement, ORDRES_HORS_MOUVEMENT)
        self.assertEqual({phase: sum(len(ordres) for ordres in par_puissance.values()) for phase, par_puissance in hors_mouvement.items()},
                         {"W1901A": 11, "F1902R": 2, "W1902A": 3, "S1903R": 1, "W1903A": 4})

    def test_les_tables_versionnees_sont_coherentes(self):
        # I1 à I3 (#40), remesurés sur le jeu du dépôt : 42 tables, 628 actions, écart de I1 nul avec math.log,
        # aucune table non triée, 628 probabilités égales à celles de prior_policy.
        self.assertEqual([v for v in reference_jeu.controler(reference_jeu.DOSSIER) if " : I" in v], [])
        jeu = reference_jeu.lire_jeu(reference_jeu.DOSSIER)
        arguments = [table["export_plans"] for tables in jeu["tables"].values() for table in tables.values()]
        self.assertEqual((len(arguments), sum(len(a["action_values"]) for a in arguments)), (TABLES_DU_JEU, 628))
        self.assertEqual(sum(len(a["prior_policy"]) for a in arguments), 628)


class Hygiene(unittest.TestCase):
    def test_bytecode_interdit_dans_les_scripts_nouveaux(self):
        tests = Path(__file__).resolve().parent
        for script in (tests / "reference_jeu.py", tests / "reference_couche_d.py", Path(__file__),
                       tests / "mesure" / "capture_reference.py", tests / "echecs_attendus.py"):
            self.assertIn("sys.dont_write_bytecode = True", script.read_text(encoding="utf-8"), script.name)


if __name__ == "__main__":
    unittest.main()
