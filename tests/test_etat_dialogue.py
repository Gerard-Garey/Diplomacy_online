#!/usr/bin/env python3
"""Persistance de l'état du bot de dialogue (issue #5, volet technique).

Appelle directement load_state / save_state, load_commitments_file /
save_commitments_file, puis run_cycle et main, de
cicero/overlay/claude_dialogue_bot.py, dans un dossier temporaire : ni pile, ni
Claude, ni GPU. Les modules de Cicero que le bot importe sont remplacés par des
doublures, ce qui permet de lancer le test hors du conteneur (CI comprise) ;
l'appel à Claude (subprocess.run) et l'envoi (post_req) sont des doublures
comptées.

Usage : python3 tests/test_etat_dialogue.py
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
BOT = RACINE / "cicero" / "overlay" / "claude_dialogue_bot.py"

# Modules de Cicero importés par le bot, absents hors du conteneur.
DOUBLURES = [
    "fairdiplomacy_external.webdip_api",
    "parlai_diplomacy.utils.game2seq.format_helpers.state",
    "fairdiplomacy.data.build_dataset",
    "fairdiplomacy.utils.plan_export",
    "fairdiplomacy.utils.orders",
    "fairdiplomacy.utils.pseudo_commitments",
]


def charger_bot():
    for nom in DOUBLURES:
        parties = nom.split(".")
        for i in range(1, len(parties) + 1):
            sys.modules[".".join(parties[:i])] = mock.MagicMock()
    spec = importlib.util.spec_from_file_location("claude_dialogue_bot", str(BOT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bot = charger_bot()

# Même forme que l'état réel ; un caractère non ASCII pour la comparaison d'octets.
ETAT = {
    "bot1:7": {
        "replied_ts": [1759400000, 1759400060],
        "exchange_counts": {"S1901M:FRANCE": 2},
        "pending_promises": {"S1901M:FRANCE": ["A PAR - BUR", "été"]},
    }
}
ETAT_SUIVANT = {"bot1:7": {"replied_ts": [1759400000, 1759400060, 1759400120], "exchange_counts": {}}}


class Cas:
    """Les mêmes cas pour les deux fichiers : sous-classes ci-dessous."""

    constante = None  # nom de la constante du module qui désigne le fichier
    nom_fichier = None

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.fichier = Path(self.dossier.name) / "webdip_logs_test" / self.nom_fichier
        patch = mock.patch.object(bot, self.constante, self.fichier)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.dossier.cleanup)

    def lire(self):
        raise NotImplementedError

    def ecrire(self, donnees):
        raise NotImplementedError

    def test_fichier_absent_etat_vide(self):
        self.assertFalse(self.fichier.exists())
        self.assertEqual(self.lire(), {})
        self.assertFalse(self.fichier.exists())

    def test_aller_retour(self):
        self.ecrire(ETAT)
        self.assertEqual(self.lire(), ETAT)
        self.assertEqual(os.listdir(str(self.fichier.parent)), [self.nom_fichier])

    def test_octets_identiques_a_l_ecriture_directe(self):
        # Écriture d'avant #5 : Path.write_text(json.dumps(data)).
        temoin = Path(self.dossier.name) / "temoin.json"
        temoin.write_text(json.dumps(ETAT))
        self.ecrire(ETAT)
        self.assertEqual(self.fichier.read_bytes(), temoin.read_bytes())

    def test_interruption_avant_le_remplacement(self):
        self.ecrire(ETAT)
        avant = self.fichier.read_bytes()
        with mock.patch.object(bot.os, "replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.ecrire(ETAT_SUIVANT)
        self.assertEqual(self.fichier.read_bytes(), avant)
        self.assertEqual(self.lire(), ETAT)
        # Le temporaire abandonné ne gêne pas l'écriture suivante.
        self.ecrire(ETAT_SUIVANT)
        self.assertEqual(self.lire(), ETAT_SUIVANT)
        self.assertEqual(os.listdir(str(self.fichier.parent)), [self.nom_fichier])

    def test_interruption_pendant_l_ecriture_du_temporaire(self):
        self.ecrire(ETAT)
        avant = self.fichier.read_bytes()

        def ecriture_coupee(chemin, texte, *args, **kwargs):
            with open(str(chemin), "w") as f:
                f.write(texte[: len(texte) // 2])
            raise KeyboardInterrupt

        with mock.patch.object(Path, "write_text", ecriture_coupee):
            with self.assertRaises(KeyboardInterrupt):
                self.ecrire(ETAT_SUIVANT)
        self.assertEqual(self.fichier.read_bytes(), avant)
        self.assertEqual(self.lire(), ETAT)

    def verifier_illisible(self, contenu):
        self.fichier.parent.mkdir(parents=True)
        self.fichier.write_bytes(contenu)
        with self.assertRaises(bot.UnreadableStateFile) as capture:
            self.lire()
        message = str(capture.exception)
        self.assertIn(str(self.fichier), message)
        self.assertIn("move it aside", message)
        self.assertEqual(self.fichier.read_bytes(), contenu)

    def test_ecriture_refusee_sur_un_fichier_illisible(self):
        self.fichier.parent.mkdir(parents=True)
        self.fichier.write_bytes(b'{"bot1:7": {"repl')
        with self.assertRaises(bot.UnreadableStateFile):
            self.ecrire(ETAT)
        self.assertEqual(self.fichier.read_bytes(), b'{"bot1:7": {"repl')
        self.assertEqual(os.listdir(str(self.fichier.parent)), [self.nom_fichier])

    def test_fichier_tronque(self):
        complet = json.dumps(ETAT).encode()
        self.verifier_illisible(complet[: len(complet) // 2])

    def test_fichier_vide(self):
        self.verifier_illisible(b"")

    def test_utf8_coupe(self):
        self.verifier_illisible('{"a": "é'.encode()[:-1])

    def test_json_qui_n_est_pas_un_objet(self):
        self.verifier_illisible(b"[]")


class EtatDuBot(Cas, unittest.TestCase):
    constante = "STATE_FILE"
    nom_fichier = "claude_dialogue_state.json"

    def lire(self):
        return bot.load_state()

    def ecrire(self, donnees):
        bot.save_state(donnees)


class FichierDEngagements(Cas, unittest.TestCase):
    constante = "COMMITMENTS_FILE"
    nom_fichier = "pseudo_commitments.json"

    def lire(self):
        return bot.load_commitments_file()

    def ecrire(self, donnees):
        bot.save_commitments_file(donnees)

    def test_retrait_sans_ecraser_un_fichier_illisible(self):
        # remove_commitment lit puis réécrit : sur un fichier illisible, il s'arrête à la lecture.
        self.fichier.parent.mkdir(parents=True)
        self.fichier.write_bytes(b'{"7": {"S1901M": {"FRA')
        with self.assertRaises(bot.UnreadableStateFile):
            bot.remove_commitment(7, "S1901M", "FRANCE", "A PAR - BUR")
        self.assertEqual(self.fichier.read_bytes(), b'{"7": {"S1901M": {"FRA')


class FauxJeu:
    """Ce que process_bot lit d'une partie : la phase, l'état, les messages."""

    def __init__(self):
        self.messages = {}

    def get_current_phase(self):
        return "S1901M"

    def get_state(self):
        return {}

    def get_all_phases(self):
        return []

    def recevoir(self, ts, expediteur, destinataire):
        self.messages[ts] = {
            "sender": expediteur, "recipient": destinataire,
            "message": "bonjour", "phase": "S1901M",
        }


class FinDEssai(BaseException):
    """Arrête la boucle sans fin de main ; main ne l'intercepte pas."""


PUISSANCES = {1: "FRANCE", 2: "GERMANY", 3: "ENGLAND"}
PLANS_FRANCE = {"plans": [
    {"orders": ["A PAR - PIC"], "value": 0.9, "cost_vs_best": 0.0},
    {"orders": ["A PAR - BUR"], "value": 0.1, "cost_vs_best": -0.8},
]}


class Cycles(unittest.TestCase):
    """run_cycle et main : bot1 joue la France, bot2 l'Allemagne, partie 7."""

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.logs = Path(self.dossier.name) / "webdip_logs_test"
        self.logs.mkdir()
        self.etat = self.logs / "claude_dialogue_state.json"
        self.engagements = self.logs / "pseudo_commitments.json"
        self.jeu = FauxJeu()
        self.sinceres = {"FRANCE": ["A PAR - BUR"], "GERMANY": ["A MUN - RUH"]}
        self.pendant_claude = None  # appelée au premier appel à Claude qui suit

        def claude(commande, **kwargs):
            if self.pendant_claude:
                action, self.pendant_claude = self.pendant_claude, None
                action()
            consigne = commande[commande.index("--system-prompt") + 1]
            reponse = {"mine": [], "theirs": []}
            for puissance, ordres in self.sinceres.items():
                if consigne.startswith("You are playing " + puissance):
                    reponse = {"reply": "entendu", "sincere": ordres}
            return mock.Mock(stdout=json.dumps({"result": json.dumps(reponse)}))

        self.claude = mock.Mock(side_effect=claude)
        self.envoi = mock.Mock(return_value=mock.Mock(status_code=200))
        self.parties = mock.Mock(side_effect=lambda cle: [
            {"gameID": 7, "countryID": int(cle[3:]), "variantID": 1}
        ])
        doublures = {
            "STATE_FILE": self.etat,
            "COMMITMENTS_FILE": self.engagements,
            "API_KEYS": ["bot1", "bot2"],
            "COUNTRY_ID_TO_POWER_OR_ALL": PUISSANCES,
            "POWER_TO_ID": {v: k for k, v in PUISSANCES.items()},
            "get_active_games": self.parties,
            "get_status_json": lambda ctx: {},
            "webdip_state_to_game": lambda status: self.jeu,
            "normalize_order_spacing": lambda ordre: ordre,
            "legal_commitments": lambda jeu, puissance, ordres: list(ordres),
            "load_plans": lambda partie, phase, puissance: PLANS_FRANCE if puissance == "FRANCE" else None,
            "post_req": self.envoi,
        }
        for nom, valeur in doublures.items():
            patch = mock.patch.object(bot, nom, valeur)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(bot.subprocess, "run", self.claude)
        patch.start()
        self.addCleanup(patch.stop)

    def cycle(self, etat):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            etat = bot.run_cycle(etat)
        return etat, sortie.getvalue()

    def instantane(self):
        """Tout le dossier, octet pour octet (un temporaire oublié s'y verrait)."""
        return {f.name: f.read_bytes() for f in self.logs.iterdir()}

    def compteurs(self):
        return (self.parties.call_count, self.claude.call_count, self.envoi.call_count)

    def premier_cycle(self):
        """Un message de l'Angleterre à chaque bot, traité avec des fichiers lisibles."""
        self.jeu.recevoir(1759400000, "ENGLAND", "FRANCE")
        self.jeu.recevoir(1759400001, "ENGLAND", "GERMANY")
        etat, _ = self.cycle(None)
        return etat

    def test_fichiers_lisibles(self):
        etat = self.premier_cycle()
        # Par bot : une lecture des parties, une réponse et une extraction, un envoi.
        self.assertEqual(self.compteurs(), (2, 4, 2))
        self.assertEqual(json.loads(self.etat.read_text()), etat)
        self.assertEqual(etat["bot1:7"]["replied_ts"], ["1759400000"])
        self.assertEqual(
            json.loads(self.engagements.read_text()),
            {"7": {"S1901M": {"FRANCE": ["A PAR - BUR"], "GERMANY": ["A MUN - RUH"]}}},
        )
        # Rien de nouveau : les bots lisent, sans appeler Claude ni rien changer.
        avant = self.instantane()
        etat, sortie = self.cycle(etat)
        self.assertEqual(self.compteurs(), (4, 4, 2))
        self.assertEqual(self.instantane(), avant)
        self.assertEqual(sortie, "")

    def test_etat_en_memoire_conserve_tant_que_les_fichiers_sont_lisibles(self):
        # Règle « corriger une donnée d'état puis redémarrer » : sans redémarrage ni
        # fichier illisible, l'état en mémoire réécrit le fichier corrigé à la main.
        etat = self.premier_cycle()
        avant = self.etat.read_bytes()
        self.etat.write_text("{}")
        etat, _ = self.cycle(etat)
        self.assertEqual(self.etat.read_bytes(), avant)
        self.assertEqual(self.compteurs(), (4, 4, 2))

    def verifier_muet_puis_reprise(self, fichier, reparer):
        etat = self.premier_cycle()
        intact = fichier.read_bytes()
        self.jeu.recevoir(1759400100, "ENGLAND", "FRANCE")
        fichier.write_bytes(intact[: len(intact) // 2])
        avant, compteurs = self.instantane(), self.compteurs()
        for _ in range(3):
            etat, sortie = self.cycle(etat)
            self.assertIsNone(etat)
            self.assertEqual(sortie.count("[silent]"), 1)
            self.assertIn(str(fichier), sortie)
            self.assertIn("move it aside", sortie)
            self.assertEqual(self.compteurs(), compteurs)
            self.assertEqual(self.instantane(), avant)
        reparer(fichier, intact)
        etat, sortie = self.cycle(etat)
        self.assertNotIn("[silent]", sortie)
        self.assertIn("1759400100", etat["bot1:7"]["replied_ts"])
        self.assertEqual(json.loads(self.etat.read_text()), etat)
        return compteurs

    def test_engagements_illisibles_plusieurs_cycles_puis_repares(self):
        compteurs = self.verifier_muet_puis_reprise(
            self.engagements, lambda fichier, intact: fichier.write_bytes(intact)
        )
        # Reprise : deux lectures des parties, une réponse et une extraction, un envoi.
        self.assertEqual(self.compteurs(), tuple(a + b for a, b in zip(compteurs, (2, 2, 1))))

    def test_etat_illisible_plusieurs_cycles_puis_repare(self):
        compteurs = self.verifier_muet_puis_reprise(
            self.etat, lambda fichier, intact: fichier.write_bytes(intact)
        )
        # L'état relu du disque connaît les messages déjà traités : un seul envoi.
        self.assertEqual(self.compteurs(), tuple(a + b for a, b in zip(compteurs, (2, 2, 1))))

    def test_etat_illisible_puis_ecarte(self):
        compteurs = self.verifier_muet_puis_reprise(
            self.etat, lambda fichier, intact: fichier.rename(fichier.with_suffix(".ecarte"))
        )
        # Fichier absent = état vide : les trois messages sont traités à nouveau.
        self.assertEqual(self.compteurs(), tuple(a + b for a, b in zip(compteurs, (2, 5, 3))))

    def test_reprise_depuis_le_disque_et_non_depuis_la_memoire(self):
        # Pendant le silence, l'état en mémoire est abandonné : une correction faite
        # dans le fichier d'état est prise en compte à la reprise, sans redémarrage.
        etat = self.premier_cycle()
        intact = self.engagements.read_bytes()
        self.engagements.write_bytes(b"")
        etat, _ = self.cycle(etat)
        corrige = json.loads(self.etat.read_text())
        corrige["bot1:7"]["exchange_counts"]["S1901M:FRANCE<->ENGLAND"] = 5
        self.etat.write_text(json.dumps(corrige))
        self.engagements.write_bytes(intact)
        etat, _ = self.cycle(etat)
        self.assertEqual(etat["bot1:7"]["exchange_counts"]["S1901M:FRANCE<->ENGLAND"], 5)
        self.assertEqual(json.loads(self.etat.read_text()), etat)

    def verifier_coupure_pendant_claude(self, expediteur, sincere, marque, fichier=None):
        """Un fichier devient illisible après le contrôle de tête de cycle."""
        etat = self.premier_cycle()
        fichier = fichier or self.engagements
        intact = fichier.read_bytes()
        self.jeu.recevoir(1759400100, expediteur, "FRANCE")
        self.sinceres["FRANCE"] = [sincere]
        avant, compteurs = self.instantane(), self.compteurs()
        self.pendant_claude = lambda: fichier.write_bytes(b'{"7": {"S19')
        memoire, copie = etat, copy.deepcopy(etat)
        etat, sortie = self.cycle(etat)
        self.assertIsNone(etat)
        self.assertEqual(memoire, copie)  # aucun engagement inscrit ni retiré en mémoire
        self.assertEqual(sortie.count("[silent]"), 1)
        self.assertNotIn(marque, sortie)
        # Claude a été appelé une fois (coupure pendant l'appel) ; bot2 n'est pas traité.
        self.assertEqual(self.compteurs(), tuple(a + b for a, b in zip(compteurs, (1, 1, 0))))
        avant[fichier.name] = b'{"7": {"S19'
        self.assertEqual(self.instantane(), avant)
        # Réparé : le message, resté en attente, reçoit sa réponse.
        fichier.write_bytes(intact)
        etat, sortie = self.cycle(etat)
        self.assertIn(marque, sortie)
        self.assertIn("1759400100", etat["bot1:7"]["replied_ts"])
        self.assertEqual(self.envoi.call_count, compteurs[2] + 1)
        return etat

    def test_coupure_avant_l_enregistrement_d_un_engagement(self):
        etat = self.verifier_coupure_pendant_claude("GERMANY", "A BRE - PIC", "sincere commitments")
        self.assertEqual(
            etat["bot1:7"]["sincere_by_recipient"]["by_recipient"],
            {"ENGLAND": ["A PAR - BUR"], "GERMANY": ["A BRE - PIC"]},
        )

    def test_coupure_du_fichier_d_etat_pendant_l_appel_a_claude(self):
        # Ni le fichier d'état illisible ni le fichier d'engagements ne sont réécrits.
        self.verifier_coupure_pendant_claude(
            "GERMANY", "A BRE - PIC", "sincere commitments", fichier=self.etat
        )

    def test_etat_illisible_pendant_l_extraction(self):
        # Seul appel à Claude du cycle : l'extraction. Le point de sauvegarde qui la
        # suit ne remplace pas le fichier devenu illisible.
        etat = self.premier_cycle()
        self.jeu.recevoir(1759400100, "FRANCE", "ENGLAND")  # la conversation s'allonge
        self.pendant_claude = lambda: self.etat.write_bytes(b'{"bot1:7"')
        engagements = self.engagements.read_bytes()
        etat, sortie = self.cycle(etat)
        self.assertIsNone(etat)
        self.assertEqual(sortie.count("[silent]"), 1)
        self.assertEqual(
            self.instantane(),
            {self.etat.name: b'{"bot1:7"', self.engagements.name: engagements},
        )

    def test_coupure_avant_le_retrait_d_un_engagement(self):
        # A PAR - PIC vaut 0,8 de plus que A PAR - BUR promis à l'Angleterre : retrait.
        etat = self.verifier_coupure_pendant_claude("GERMANY", "A PAR - PIC", "[betrayal]")
        self.assertEqual(
            etat["bot1:7"]["sincere_by_recipient"]["by_recipient"],
            {"ENGLAND": [], "GERMANY": ["A PAR - PIC"]},
        )
        self.assertEqual(
            json.loads(self.engagements.read_text())["7"]["S1901M"]["FRANCE"], ["A PAR - PIC"]
        )

    def test_main_ne_sort_pas_sur_un_etat_illisible_au_demarrage(self):
        self.jeu.recevoir(1759400000, "ENGLAND", "FRANCE")
        self.etat.write_bytes(b'{"bot1:7": {"replied_ts": [')
        avant = self.instantane()
        pauses = []

        def pause(secondes):
            pauses.append(self.compteurs())
            if len(pauses) == 3:
                self.assertEqual(self.instantane(), avant)
                self.etat.write_text("{}")  # réparation, conteneur en marche
            if len(pauses) == 4:
                raise FinDEssai

        sortie = io.StringIO()
        with mock.patch.object(bot.time, "sleep", pause), contextlib.redirect_stdout(sortie):
            with self.assertRaises(FinDEssai):
                bot.main()
        # Trois cycles muets, puis un cycle normal : une réponse, une extraction, un envoi.
        self.assertEqual(pauses, [(0, 0, 0), (0, 0, 0), (0, 0, 0), (2, 2, 1)])
        self.assertEqual(sortie.getvalue().count("[silent]"), 3)
        self.assertEqual(json.loads(self.etat.read_text())["bot1:7"]["replied_ts"], ["1759400000"])


if __name__ == "__main__":
    unittest.main()
