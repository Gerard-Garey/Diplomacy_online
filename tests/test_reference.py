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
import shutil
import subprocess
import sys
import tempfile
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


def releves_fabriques(dossier, graine=31):
    """Relevés fabriqués, au format de rejeu_moteur.py, clés exclues comprises ; rend (lignes, historique).

    Par position : huit à seize actions des trois unités du banc, valeurs de 0 à
    0,30 à cinq décimales (à deux, l'arrondi du gain ne se verrait pas), probabilités tirées puis normalisées, la dernière action à 1e-5 (sous
    tout plancher essayé) ; classement et export par les fonctions du dépôt. Une
    table sur deux vient d'une recherche avec engagement : la probabilité
    d'`action_values` y est renforcée, celle de `prior_policy` ne l'est pas.
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
        promesses = [table[1][0][0]] if numero % 2 else []
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

    def test_le_premier_releve_d_une_position_l_emporte(self):
        fichier = self.racine / "deux.jsonl"
        seconde = json.loads(json.dumps(self.lignes[0]))
        seconde["entree"]["plans"][0]["value"] = 9.0
        fichier.write_text(json.dumps(self.lignes[0]) + "\n" + json.dumps(seconde) + "\n", encoding="utf-8")
        tables, doublons = reference_jeu.reduire_fichiers([fichier])
        self.assertEqual(tables["S1901M"]["ENGLAND"]["plans"][0]["value"], self.lignes[0]["entree"]["plans"][0]["value"])
        self.assertEqual(doublons, ["deux.jsonl:2 (S1901M ENGLAND)"])

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
        self.modifier("tables/S1901M.json", lambda d: d["tables"].update(jerem=d["tables"]["FRANCE"]))
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
                        "tests/reference/tables/pseudo_commitments.json", "Current_Plans.JSON"):
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
            "tests/test_current_plans.json", "plans.json", "current_plans/notes.md", "claude_dialogue_state.py",
        ), [])

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
        """Listes fermées : rien n'y figure qu'un fichier du dépôt ne porte (une entrée morte élargirait le contrôle)."""
        fichiers = reference_jeu.fichiers_du_depot(reference_jeu.RACINE)
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
            self.assertIn("reference_jeu.py manifeste", sortie)
            self.assertEqual(self.etat_du_jeu(), avant)
        self.assertTrue(reference_jeu.controler(self.dossier))
        # La modification voulue passe par la commande nommée : elle se voit alors dans le diff du manifeste.
        self.assertEqual(reference_jeu.main(["manifeste", "--dossier", str(self.dossier)]), 0)
        code, sortie = self.generer()
        self.assertEqual(code, 0, sortie)

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
        """La mutation change des grandeurs de chacune de ces couches (et d'aucune autre si `seules`) ; jamais D6."""
        decompte = self.decompte(nom)
        for couche in couches:
            self.assertIn(couche, decompte, decompte)
        if seules:
            self.assertEqual(sorted(decompte), sorted(couches), decompte)
        self.assertNotIn("D6", decompte)

    def test_sept_mutations(self):
        self.assertEqual(len(couche_d.MUTATIONS), 7)

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
        self.assertEqual(sortie.count("| oui"), 7)

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
        self.assertIn("docker start cicero-orders", sortie)
        self.assertIn("capture_reference.py identite --dossier amont/capture-reference", sortie)
        self.assertLess(sortie.index("capture_reference.py identite"), sortie.index("docker stop"))
        self.assertIn("--identite amont/capture-reference/resultats/identite_capture.json", sortie)
        self.assertIn("cp -a amont/capture-reference/resultats <dossier de conservation hors du dépôt>/", sortie)
        self.assertIn("43 lancements, 241 recherches ; durée estimée des recherches : 2 h 22", sortie)

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
        """Par lancement 23 s, par tirage 41,3 s (A) et 19,3 s de plus avec engagement (B)."""
        self.assertAlmostEqual(capture_reference.duree_estimee([("S1901M", "FRANCE", 5, "auto:prefere", None)]), 23 + 5 * 60.6)
        self.assertAlmostEqual(capture_reference.duree_estimee([("F1901M", "FRANCE", 1, "aucun", None)]), 23 + 41.3)
        plan = capture_reference.plan_de_campagne(capture_reference.PHASES_DE_MOUVEMENT, capture_reference.POSITIONS_REPETEES, 5)
        self.assertAlmostEqual(capture_reference.duree_estimee(plan), 43 * 23 + 110 * 60.6 + 21 * 41.3)

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


class EssaiASec(unittest.TestCase):
    """Le mode à sec de rejeu_moteur.py : table de la doublure, arguments d'export relevés, rejeu de l'historique.

    Sur la table fabriquée, que tests/reference/ soit rempli ou non : ces tests ne dépendent pas du jeu d'essai.
    """

    def lancer(self, *options):
        with tempfile.TemporaryDirectory() as tmp:
            historique = Path(tmp) / "historique.json"
            historique.write_text(json.dumps(capture_reference.HISTORIQUE_DOUBLURE), encoding="utf-8")
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
        """Rien à promettre au tirage 0 : c'est figé aussi, aucun tirage ne fait de recherche B."""
        with mock.patch.object(rejeu_moteur.commun, "choisir_engagements", lambda entree, mode: ([], "aucune alternative")):
            _sortie, releves = self.lancer("3", "S1902M", "ITALY", "2", "--engagements", "auto:alternative")
        self.assertEqual([(r["tirage"], r["recherche"]) for r in releves], [(0, "A"), (1, "A")])
        self.assertEqual(releves[1]["engagement_fige"], [])

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


class Hygiene(unittest.TestCase):
    def test_bytecode_interdit_dans_les_scripts_nouveaux(self):
        tests = Path(__file__).resolve().parent
        for script in (tests / "reference_jeu.py", tests / "reference_couche_d.py", Path(__file__),
                       tests / "mesure" / "capture_reference.py"):
            self.assertIn("sys.dont_write_bytecode = True", script.read_text(encoding="utf-8"), script.name)


if __name__ == "__main__":
    unittest.main()
