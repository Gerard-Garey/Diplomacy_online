#!/usr/bin/env python3
"""Persistance de l'état du bot de dialogue et journal d'envoi (issue #5).

Appelle directement load_state / save_state, load_commitments_file /
save_commitments_file, puis run_cycle et main, de
cicero/overlay/claude_dialogue_bot.py, dans un dossier temporaire : ni pile, ni
Claude, ni GPU. Les modules de Cicero que le bot importe sont remplacés par des
doublures, ce qui permet de lancer le test hors du conteneur (CI comprise) ;
l'appel à Claude (subprocess.run) et l'envoi (post_req) sont des doublures
comptées ; l'envoi et la relecture des messages passent par tests/faux_site.py.

Usage : python3 tests/test_etat_dialogue.py
"""
import contextlib
import copy
import errno
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import faux_site

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

    # Toute OSError autre que « fichier absent » vaut « illisible », en lecture comme en écriture.
    def test_lecture_refusee(self):
        self.ecrire(ETAT)
        avant = self.fichier.read_bytes()
        refus = PermissionError(errno.EACCES, "Permission denied")
        with mock.patch.object(Path, "read_text", side_effect=refus):
            with self.assertRaises(bot.UnreadableStateFile) as capture:
                self.lire()
            with self.assertRaises(bot.UnreadableStateFile):
                self.ecrire(ETAT_SUIVANT)
        message = str(capture.exception)
        self.assertIn(str(self.fichier), message)
        self.assertIn("cannot be read (PermissionError", message)
        self.assertIn("move it aside", message)
        self.assertEqual(self.fichier.read_bytes(), avant)

    def test_repertoire_a_la_place_du_fichier(self):
        self.fichier.mkdir(parents=True)
        with self.assertRaises(bot.UnreadableStateFile) as capture:
            self.lire()
        self.assertIn("cannot be read (IsADirectoryError", str(capture.exception))
        with self.assertRaises(bot.UnreadableStateFile):
            self.ecrire(ETAT)
        self.assertTrue(self.fichier.is_dir())

    def test_fichier_a_la_place_du_dossier(self):
        self.fichier.parent.write_text("pas un dossier")
        with self.assertRaises(bot.UnreadableStateFile) as capture:
            self.lire()
        self.assertIn("cannot be read (NotADirectoryError", str(capture.exception))

    def test_ecriture_impossible(self):
        # Disque plein au remplacement, puis à l'écriture du temporaire : le fichier reste intact.
        self.ecrire(ETAT)
        avant = self.fichier.read_bytes()
        plein = OSError(errno.ENOSPC, "No space left on device")
        for cible in ((bot.os, "replace"), (Path, "write_text")):
            with mock.patch.object(*cible, side_effect=plein):
                with self.assertRaises(bot.UnreadableStateFile) as capture:
                    self.ecrire(ETAT_SUIVANT)
            message = str(capture.exception)
            self.assertIn(str(self.fichier), message)
            self.assertIn("cannot be written (OSError", message)
            self.assertIn("disk space", message)
            self.assertEqual(self.fichier.read_bytes(), avant)
        self.assertEqual(self.lire(), ETAT)


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

    ENVOI = {
        "phase": "S1901M", "added": {"by_recipient": ["A PAR - PIC"], "commitments": ["A PAR - PIC"]},
        "removed": [{"order": "A PAR - BUR", "holders": ["ENGLAND"]}],
    }

    def test_retrait_sans_ecraser_un_fichier_illisible(self):
        # L'application d'un envoi et son annulation lisent puis réécrivent : sur un
        # fichier illisible, elles s'arrêtent à la lecture.
        self.fichier.parent.mkdir(parents=True)
        self.fichier.write_bytes(b'{"7": {"S1901M": {"FRA')
        for fonction in (bot._apply_send_to_commitments, bot._undo_send_in_commitments):
            with self.assertRaises(bot.UnreadableStateFile):
                fonction(7, "FRANCE", self.ENVOI)
            self.assertEqual(self.fichier.read_bytes(), b'{"7": {"S1901M": {"FRA')

    def test_application_et_annulation_d_un_envoi_idempotentes(self):
        # Un engagement hérité écrit sans espaces est le même engagement ; les autres
        # entrées (autre unité, autre puissance, autre phase) ne sont pas touchées.
        depart = {"7": {"S1901M": {"FRANCE": ["F BRE - MAO", "A PAR-BUR"], "GERMANY": ["A MUN - RUH"]},
                        "F1901M": {"FRANCE": ["A PAR - PIC"]}}}
        with mock.patch.object(bot, "normalize_order_spacing", lambda o: o.replace("-", " - ").replace("  ", " ").replace("  ", " ")):
            self.ecrire(depart)
            for _ in range(2):
                bot._apply_send_to_commitments(7, "FRANCE", self.ENVOI)
                self.assertEqual(self.lire()["7"]["S1901M"]["FRANCE"], ["F BRE - MAO", "A PAR - PIC"])
            for _ in range(2):
                bot._undo_send_in_commitments(7, "FRANCE", self.ENVOI)
                self.assertEqual(self.lire()["7"]["S1901M"]["FRANCE"], ["F BRE - MAO", "A PAR - BUR"])
            self.assertEqual(self.lire()["7"]["S1901M"]["GERMANY"], ["A MUN - RUH"])
            self.assertEqual(self.lire()["7"]["F1901M"], {"FRANCE": ["A PAR - PIC"]})
            # Un envoi sans engagement n'écrit rien.
            self.fichier.unlink()
            vide = {"phase": "S1901M", "added": {"by_recipient": [], "commitments": []}, "removed": []}
            bot._apply_send_to_commitments(7, "FRANCE", vide)
            bot._undo_send_in_commitments(7, "FRANCE", vide)
            self.assertFalse(self.fichier.exists())


class FauxJeu:
    """Ce que process_bot lit d'une partie : la phase, l'état, les messages."""

    def __init__(self):
        self.messages = {}
        self.phase = "S1901M"

    def get_current_phase(self):
        return self.phase

    def get_state(self):
        return {}

    def get_all_phases(self):
        return []

    def recevoir(self, ts, expediteur, destinataire):
        self.messages[ts] = {
            "sender": expediteur, "recipient": destinataire,
            "message": "bonjour", "phase": self.phase,
        }


class FinDEssai(BaseException):
    """Arrête la boucle sans fin de main ; main ne l'intercepte pas."""


PUISSANCES = {1: "FRANCE", 2: "GERMANY", 3: "ENGLAND"}
# Entrée au format complet (#17) : la table des candidats et les paramètres de la
# recherche accompagnent les plans. La condition « le moteur jouerait l'ordre »
# est une doublure (voir setUp) : ces tests portent sur la persistance.
PLANS_FRANCE = {
    "plans": [
        {"orders": ["A PAR - PIC"], "value": 0.9, "cost_vs_best": 0.0},
        {"orders": ["A PAR - BUR"], "value": 0.1, "cost_vs_best": -0.8},
    ],
    "candidates": [
        {"orders": ["A PAR - PIC"], "value": 0.9, "prob": 0.5},
        {"orders": ["A PAR - BUR"], "value": 0.1, "prob": 0.5},
    ],
    "search": {"lambda": 0.01, "boost": 3.0, "max_prob": 0.4},
}


class Montage:
    """Doublures communes : bot1 joue la France, bot2 l'Allemagne, partie 7."""

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.logs = Path(self.dossier.name) / "webdip_logs_test"
        self.logs.mkdir()
        self.etat = self.logs / "claude_dialogue_state.json"
        self.engagements = self.logs / "pseudo_commitments.json"
        self.jeu = FauxJeu()
        self.sinceres = {"FRANCE": ["A PAR - BUR"], "GERMANY": ["A MUN - RUH"]}
        self.labels = {}  # label de trahison (betray) par puissance, absent par défaut
        self.textes = {}  # texte de la réponse par puissance ; absent : "entendu" ; None : silence
        self.reponses = 0  # appels à Claude pour une réponse (hors extraction)
        self.site = faux_site.FauxSite()
        self.pendant_claude = None  # appelée au premier appel à Claude qui suit

        def claude(commande, **kwargs):
            if self.pendant_claude:
                action, self.pendant_claude = self.pendant_claude, None
                action()
            consigne = commande[commande.index("--system-prompt") + 1]
            reponse = {"mine": [], "theirs": []}
            for puissance, ordres in self.sinceres.items():
                if consigne.startswith("You are playing " + puissance):
                    self.reponses += 1
                    reponse = {"reply": self.textes.get(puissance, "entendu"), "sincere": ordres}
                    if puissance in self.labels:
                        reponse["betray"] = self.labels[puissance]
            return mock.Mock(stdout=json.dumps({"result": json.dumps(reponse)}))

        self.claude = mock.Mock(side_effect=claude)
        self.envoi = mock.Mock(side_effect=self.site.post_req)
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
            "get_status_json": self.site.statut,
            "webdip_state_to_game": lambda status: self.jeu,
            "normalize_order_spacing": lambda ordre: ordre,
            "legal_commitments": lambda jeu, puissance, ordres: list(ordres),
            "engine_head_action": lambda candidats, recherche, promis: ("A PAR - PIC",),
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


class Cycles(Montage, unittest.TestCase):
    """run_cycle et main : fichiers lisibles, illisibles, réparés."""

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
        # La mémoire des promesses du bot est écrite avec by_recipient (#17).
        self.assertEqual(
            etat["bot1:7"]["own_promises"],
            {"pending": {"S1901M:ENGLAND": ["A PAR - BUR"]}, "record": {}},
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

    def verifier_coupure_pendant_claude(self, expediteur, sincere, marque, fichier=None, betray=None):
        """Un fichier devient illisible après le contrôle de tête de cycle."""
        etat = self.premier_cycle()
        fichier = fichier or self.engagements
        intact = fichier.read_bytes()
        self.jeu.recevoir(1759400100, expediteur, "FRANCE")
        self.sinceres["FRANCE"] = [sincere]
        if betray is not None:
            self.labels["FRANCE"] = betray
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
        # La mémoire des promesses du bot suit by_recipient : rien pendant la coupure
        # (état en mémoire inchangé, contrôlé plus haut), la promesse après la reprise.
        self.assertEqual(
            etat["bot1:7"]["own_promises"]["pending"],
            {"S1901M:ENGLAND": ["A PAR - BUR"], "S1901M:GERMANY": ["A BRE - PIC"]},
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
        # A PAR - PIC vaut 0,8 de plus que A PAR - BUR promis à l'Angleterre, et la
        # trahison est déclarée (#17) : retrait.
        etat = self.verifier_coupure_pendant_claude(
            "GERMANY", "A PAR - PIC", "[betrayal]", betray=["A PAR - BUR"]
        )
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



# Messages reçus par la France : clés de game.messages, en centisecondes (Timestamp).
T1, T2, T3 = 175940000000, 175940010000, 175940020000
PAIRE = "S1901M:FRANCE<->ENGLAND"
BUR, PIC = "A PAR - BUR", "A PAR - PIC"
ECHECS_EN_APPARENCE = (
    faux_site.EXCEPTION, faux_site.EXCEPTION_STOCKE, faux_site.ERREUR_500,
    faux_site.ERREUR_500_STOCKE, faux_site.HTML, faux_site.JSON_PUIS_HTML,
)


# Balises et ligne qui annoncent un changement d'engagement effectif (#17) : imprimées
# une fois l'envoi confirmé, jamais avant.
ANNONCES = ("[betrayal]", "[revision]", "sincere commitments ->")


class Envois(Montage, unittest.TestCase):
    """Journal d'envoi (#5, volet de fond) : critères (a) à (m), bot1 seul (la France)."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(bot, "API_KEYS", ["bot1"])
        patch.start()
        self.addCleanup(patch.stop)

    def bot1(self):
        """État de bot1 dans la partie, tel qu'il est écrit sur disque."""
        return json.loads(self.etat.read_text())["bot1:7"]

    def promis(self):
        """Engagements de la France dans pseudo_commitments.json ([] si rien n'est écrit)."""
        if not self.engagements.exists():
            return []
        return json.loads(self.engagements.read_text()).get("7", {}).get("S1901M", {}).get("FRANCE", [])

    def par_destinataire(self):
        return self.bot1()["sincere_by_recipient"]["by_recipient"]

    def verifier_envoi_confirme(self, time_sent, texte="entendu"):
        """État de (a) : message marqué, échange compté, engagement présent, rien en attente."""
        etat = self.bot1()
        self.assertEqual(etat["replied_ts"], [str(T1)])
        self.assertEqual(etat["exchange_counts"], {PAIRE: 1})
        self.assertNotIn("pending_send", etat)
        self.assertEqual(etat["sent_ts"], [bot._sent_mark(time_sent, "ENGLAND", texte)])
        self.assertEqual(self.par_destinataire(), {"ENGLAND": [BUR]})
        self.assertEqual(etat["own_promises"]["pending"], {"S1901M:ENGLAND": [BUR]})
        self.assertEqual(self.promis(), [BUR])
        return etat

    def verifier_envoi_annule(self, marque, sortie):
        """État de (f) et (g) : engagement retiré, message marqué, échange non compté."""
        etat = self.bot1()
        self.assertEqual(sortie.count(marque), 1)
        self.assertEqual(etat["replied_ts"], [str(T1)])
        self.assertEqual(etat["exchange_counts"], {})
        self.assertNotIn("pending_send", etat)
        self.assertNotIn("sent_ts", etat)
        self.assertEqual(self.par_destinataire(), {"ENGLAND": []})
        self.assertEqual(etat["own_promises"]["pending"], {})
        self.assertEqual(self.promis(), [])

    def test_a_envoi_confirme(self):
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, sortie = self.cycle(None)
        self.assertEqual(self.envoi.call_count, 1)
        self.assertIn("  sent (status=200): 'entendu'", sortie)
        self.verifier_envoi_confirme(1759400501)
        self.assertEqual(json.loads(self.etat.read_text()), etat)

    def test_b_etat_puis_engagements_ecrits_avant_l_envoi(self):
        vus = []
        self.site.pendant_l_envoi = lambda envoye: vus.append((self.bot1(), self.promis()))
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.cycle(None)
        (etat, promis), = vus
        self.assertEqual(etat["pending_send"], {
            "ts": str(T1), "recipient": "ENGLAND", "text": "entendu", "phase": "S1901M",
            "added": {"by_recipient": [BUR], "commitments": [BUR]},
            "removed": [],
            "own_pending": {"key": "S1901M:ENGLAND", "before": None},
            "journal": ["  sincere commitments -> ['A PAR - BUR']"],
            "attempts": 1, "rereads": 0,
        })
        self.assertEqual(etat["sincere_by_recipient"]["by_recipient"], {"ENGLAND": [BUR]})
        self.assertEqual(etat["own_promises"]["pending"], {"S1901M:ENGLAND": [BUR]})
        self.assertEqual(etat["replied_ts"], [])
        self.assertEqual(promis, [BUR])

    def test_c_envoi_incertain(self):
        for comportement in ECHECS_EN_APPARENCE:
            with self.subTest(comportement=comportement):
                self.setUp()
                self.site.comportements = [comportement]
                self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
                self.jeu.recevoir(T2, "GERMANY", "FRANCE")
                etat, sortie = self.cycle(None)
                self.assertEqual(self.envoi.call_count, 1)
                self.assertEqual(self.reponses, 1)  # le message de l'Allemagne n'est pas traité
                # Ni extraction des promesses reçues : un seul appel à Claude, la réponse.
                self.assertEqual(self.claude.call_count, 1)
                self.assertNotIn("commitment_counts", self.bot1())
                self.assertEqual(sortie.count("[send-uncertain]"), 1)
                self.assertNotIn("sent (status", sortie)
                etat = self.bot1()
                self.assertEqual(etat["replied_ts"], [])
                self.assertEqual(etat["exchange_counts"], {})
                self.assertEqual(etat["pending_send"]["ts"], str(T1))
                self.assertEqual((etat["pending_send"]["attempts"], etat["pending_send"]["rereads"]), (1, 0))
                self.assertEqual(self.par_destinataire(), {"ENGLAND": [BUR]})
                self.assertEqual(self.promis(), [BUR])
                self.doCleanups()

    def test_d_relecture_qui_confirme(self):
        for comportement in (faux_site.EXCEPTION_STOCKE, faux_site.ERREUR_500_STOCKE, faux_site.JSON_PUIS_HTML):
            for redemarrage in (False, True):  # (h) : état rechargé du disque entre les deux cycles
                with self.subTest(comportement=comportement, redemarrage=redemarrage):
                    self.setUp()
                    self.site.comportements = [comportement]
                    self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
                    etat, _ = self.cycle(None)
                    compteurs = self.compteurs()
                    etat, sortie = self.cycle(None if redemarrage else etat)
                    # Ni réponse demandée à Claude ni envoi ; l'extraction, écartée du
                    # cycle de l'envoi incertain, a lieu ici (un appel).
                    self.assertEqual((self.reponses, self.envoi.call_count), (1, compteurs[2]))
                    self.assertEqual(self.claude.call_count, compteurs[1] + 1)
                    self.assertEqual(self.bot1()["commitment_counts"], {PAIRE: 1})
                    self.assertEqual(sortie.count("[send-confirmed]"), 1)
                    self.verifier_envoi_confirme(1759400501)
                    self.assertEqual(json.loads(self.etat.read_text()), etat)
                    self.assertEqual(len(self.site.messages), 1)
                    self.doCleanups()

    def test_d_meme_etat_qu_un_envoi_confirme_d_emblee(self):
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.cycle(None)
        # Comparaison des contenus : la clé sent_ts n'est pas inscrite au même rang.
        direct = (json.loads(self.etat.read_text()), self.engagements.read_bytes())
        self.doCleanups()
        self.setUp()
        self.site.comportements = [faux_site.ERREUR_500_STOCKE]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        self.cycle(etat)
        self.assertEqual((json.loads(self.etat.read_text()), self.engagements.read_bytes()), direct)

    def test_e_relecture_negative_puis_renvoi_du_meme_texte(self):
        for redemarrage in (False, True):
            with self.subTest(redemarrage=redemarrage):
                self.setUp()
                self.site.comportements = [faux_site.ERREUR_500]
                self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
                etat, _ = self.cycle(None)
                compteurs = self.compteurs()
                # Premier cycle : une relecture négative, rien n'est envoyé.
                etat, sortie = self.cycle(None if redemarrage else etat)
                self.assertEqual(self.compteurs()[1:], compteurs[1:])
                self.assertEqual(sortie.count("[send-pending]"), 1)
                self.assertEqual((self.bot1()["pending_send"]["attempts"], self.bot1()["pending_send"]["rereads"]), (1, 1))
                self.assertEqual(self.promis(), [BUR])
                # Deuxième cycle : un seul envoi, du même texte, sans réponse demandée à
                # Claude ; l'envoi une fois confirmé, l'extraction a lieu (un appel).
                etat, sortie = self.cycle(None if redemarrage else etat)
                self.assertEqual(self.reponses, 1)
                self.assertEqual(self.claude.call_count, compteurs[1] + 1)
                self.assertEqual(self.envoi.call_count, compteurs[2] + 1)
                self.assertEqual(sortie.count("[send-retry]"), 1)
                self.assertEqual(self.site.textes_envoyes(), ["entendu", "entendu"])
                self.assertEqual(self.site.envois[0], self.site.envois[1])
                self.verifier_envoi_confirme(1759400501)
                self.assertEqual(len(self.site.messages), 1)
                self.doCleanups()

    def test_e_au_renvoi_etat_et_engagements_sont_sur_disque(self):
        self.site.comportements = [faux_site.ERREUR_500]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        etat, _ = self.cycle(etat)
        vus = []
        self.site.pendant_l_envoi = lambda envoye: vus.append((self.bot1()["pending_send"], self.promis()))
        self.cycle(etat)
        (en_attente, promis), = vus
        self.assertEqual((en_attente["attempts"], en_attente["rereads"]), (2, 0))
        self.assertEqual(promis, [BUR])

    def test_f_plafond_atteint(self):
        self.site.comportements = [faux_site.ERREUR_500] * 3
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, sorties = None, []
        for _ in range(7):
            etat, sortie = self.cycle(etat)
            sorties.append(sortie)
        # Envois aux cycles 1, 3 et 5 ; abandon au cycle 7, après deux relectures négatives.
        self.assertEqual([s.count("[send-uncertain]") for s in sorties], [1, 0, 1, 0, 1, 0, 0])
        self.assertEqual([s.count("[send-failed]") for s in sorties], [0, 0, 0, 0, 0, 0, 1])
        self.assertEqual(self.site.textes_envoyes(), ["entendu"] * 3)
        self.assertEqual(self.reponses, 1)
        self.verifier_envoi_annule("[send-failed]", sorties[-1])
        self.assertIn("3 attempts", sorties[-1])
        # Le message est marqué : plus rien n'est envoyé ni demandé à Claude.
        compteurs = self.compteurs()
        etat, sortie = self.cycle(etat)
        self.assertEqual(self.compteurs()[1:], compteurs[1:])
        self.assertEqual(sortie, "")

    def test_f_phase_changee(self):
        self.site.comportements = [faux_site.ERREUR_500]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        self.jeu.phase = "F1901M"
        self.jeu.messages = {}
        etat, sortie = self.cycle(etat)
        self.assertEqual(sortie.count("[send-pending]"), 1)
        etat, sortie = self.cycle(etat)
        self.assertEqual(self.envoi.call_count, 1)
        self.assertEqual(sortie.count("[send-failed]"), 1)
        self.assertIn("the phase has moved on from S1901M to F1901M", sortie)
        etat = self.bot1()
        self.assertEqual(etat["replied_ts"], [str(T1)])
        self.assertEqual(etat["exchange_counts"], {})
        self.assertNotIn("pending_send", etat)
        self.assertEqual(etat["own_promises"]["pending"], {})
        self.assertEqual(self.promis(), [])

    def test_f_phase_changee_mais_message_stocke(self):
        # Le message est sur le site : confirmé même après le changement de phase.
        self.site.comportements = [faux_site.ERREUR_500_STOCKE]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        self.jeu.phase = "F1901M"
        self.jeu.messages = {}
        etat, sortie = self.cycle(etat)
        self.assertEqual(sortie.count("[send-confirmed]"), 1)
        etat = self.bot1()
        self.assertEqual(etat["exchange_counts"], {PAIRE: 1})
        self.assertEqual(etat["own_promises"]["pending"], {"S1901M:ENGLAND": [BUR]})
        self.assertEqual(self.promis(), [BUR])

    def test_g_sourdine(self):
        self.site.comportements = [faux_site.SOURDINE]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, sortie = self.cycle(None)
        self.assertEqual(self.envoi.call_count, 1)
        self.verifier_envoi_annule("[send-muted]", sortie)
        self.assertEqual(self.site.messages, [])
        compteurs = self.compteurs()
        etat, sortie = self.cycle(etat)
        self.assertEqual(self.compteurs()[1:], compteurs[1:])
        self.assertEqual(sortie, "")

    def test_i_message_identique_anterieur_ne_confirme_pas(self):
        # Première réponse « entendu », confirmée (dans sent_ts). Le second message a été
        # reçu avant qu'elle ne parte : elle est postérieure à ts_reçu, mais déjà connue.
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        self.site.comportements = [faux_site.ERREUR_500]
        self.jeu.recevoir(T2, "ENGLAND", "FRANCE")
        self.assertLess(T2 // 100, self.site.messages[0]["timeSent"])
        etat, _ = self.cycle(etat)
        etat, sortie = self.cycle(etat)
        self.assertEqual(sortie.count("[send-pending]"), 1)
        self.assertNotIn("[send-confirmed]", sortie)
        self.assertEqual(self.bot1()["pending_send"]["rereads"], 1)
        self.assertEqual(self.bot1()["exchange_counts"], {PAIRE: 1})
        # Sans sent_ts, la même relecture confirmerait à tort : le test porte bien sur lui.
        en_attente = self.bot1()["pending_send"]
        envoyes = bot._messages_sent_by(self.site.statut(), 1)
        self.assertIsNone(bot._find_pending_send(en_attente, envoyes, 3, self.bot1()["sent_ts"]))
        self.assertEqual(bot._find_pending_send(en_attente, envoyes, 3, []), 1759400501)

    def test_i_recherche_du_message(self):
        en_attente = {"ts": str(T2), "recipient": "ENGLAND", "text": "entendu"}
        seconde = T2 // 100
        cas = (
            ("rien sur le site", [], [], None),
            ("antérieur au message reçu", [(seconde - 1, 3, "entendu")], [], None),
            ("à la seconde du message reçu", [(seconde, 3, "entendu")], [], seconde),
            ("autre destinataire", [(seconde + 5, 2, "entendu")], [], None),
            ("autre texte", [(seconde + 5, 3, "entendu !")], [], None),
            ("déjà connu", [(seconde + 5, 3, "entendu")], [bot._sent_mark(seconde + 5, "ENGLAND", "entendu")], None),
            ("connu pour un autre destinataire", [(seconde + 5, 3, "entendu")],
             [bot._sent_mark(seconde + 5, "GERMANY", "entendu")], seconde + 5),
            ("connu pour un autre texte", [(seconde + 5, 3, "entendu")],
             [bot._sent_mark(seconde + 5, "ENGLAND", "non")], seconde + 5),
            ("deux à la même seconde, un connu", [(seconde + 5, 3, "entendu")] * 2,
             [bot._sent_mark(seconde + 5, "ENGLAND", "entendu")], seconde + 5),
            ("deux à la même seconde, deux connus", [(seconde + 5, 3, "entendu")] * 2,
             [bot._sent_mark(seconde + 5, "ENGLAND", "entendu")] * 2, None),
            ("le plus ancien des inconnus", [(seconde + 9, 3, "entendu"), (seconde + 5, 3, "entendu")], [], seconde + 5),
        )
        for nom, envoyes, connus, attendu in cas:
            with self.subTest(nom):
                self.assertEqual(bot._find_pending_send(en_attente, envoyes, 3, connus), attendu)

    def test_i_lecture_du_statut(self):
        # Toutes les phases sont lues ; seuls les messages de l'expéditeur sont rendus,
        # décodés ; une entrée mal formée est ignorée.
        statut = {"phases": [
            {"phase": "Diplomacy", "messages": [
                {"fromCountryID": 1, "toCountryID": 3, "message": "a &amp; b<br />c", "timeSent": 10},
                {"fromCountryID": 3, "toCountryID": 1, "message": "bonjour", "timeSent": 11},
                {"fromCountryID": 1, "toCountryID": 3, "message": "sans date"},
                "pas un message",
            ]},
            {"phase": "Retreats"},
            {"phase": "Diplomacy", "messages": [
                {"fromCountryID": 1, "toCountryID": 2, "message": "&eacute;t&eacute;", "timeSent": 20},
            ]},
        ]}
        self.assertEqual(bot._messages_sent_by(statut, 1), [(10, 3, "a & b\nc"), (20, 2, "été")])
        for vide in ({}, {"phases": None}, None, []):
            self.assertEqual(bot._messages_sent_by(vide, 1), [])

    def test_j_reply_nul_avec_sincere(self):
        self.textes["FRANCE"] = None
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, sortie = self.cycle(None)
        self.assertIn("no reply: sincere ['A PAR - BUR'] and betray [] ignored", sortie)
        self.assertEqual(self.envoi.call_count, 0)
        self.assertFalse(self.engagements.exists())
        etat = self.bot1()
        self.assertEqual(etat["replied_ts"], [str(T1)])
        self.assertEqual(etat["exchange_counts"], {})
        self.assertNotIn("pending_send", etat)
        self.assertEqual(self.par_destinataire(), {})
        # Même chose quand un engagement existe déjà : le fichier garde ses octets.
        self.textes["FRANCE"] = "entendu"
        self.jeu.recevoir(T2, "ENGLAND", "FRANCE")
        self.cycle(None)
        avant = self.engagements.read_bytes()
        self.textes["FRANCE"], self.sinceres["FRANCE"] = "", [PIC]
        self.jeu.recevoir(T3, "ENGLAND", "FRANCE")
        self.cycle(None)
        self.assertEqual(self.engagements.read_bytes(), avant)
        self.assertEqual(self.envoi.call_count, 1)

    def ecriture_en_panne(self, fichier):
        """os.replace qui refuse d'écrire `fichier` (disque plein) et laisse passer les autres."""
        reel = os.replace

        def remplacer(source, cible):
            if Path(str(cible)) == fichier:
                raise OSError(errno.ENOSPC, "No space left on device")
            return reel(source, cible)

        return mock.patch.object(bot.os, "replace", remplacer)

    def test_k_etat_illisible_a_l_etape_2(self):
        # Le fichier d'état devient illisible pendant l'appel à Claude (contrôle d'après
        # l'appel), ou son écriture échoue à l'étape 2 : ni engagement écrit, ni envoi.
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.pendant_claude = lambda: self.etat.write_bytes(b'{"bot1:7"')
        etat, sortie = self.cycle(None)
        self.assertIsNone(etat)
        self.assertEqual(sortie.count("[silent]"), 1)
        self.assertEqual(self.envoi.call_count, 0)
        self.assertFalse(self.engagements.exists())
        self.assertEqual(self.etat.read_bytes(), b'{"bot1:7"')

    def test_k_ecriture_de_l_etat_impossible_a_l_etape_2(self):
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.cycle(None)  # l'état existe ; l'engagement de T1 aussi
        avant = self.instantane()
        self.sinceres["FRANCE"] = ["A BRE - PIC"]
        self.jeu.recevoir(T2, "GERMANY", "FRANCE")
        vus = []

        def panne_si_envoi_en_attente(source, cible, reel=os.replace):
            if Path(str(cible)) == self.etat and "pending_send" in Path(str(source)).read_text():
                vus.append(json.loads(Path(str(source)).read_text())["bot1:7"]["pending_send"]["ts"])
                raise OSError(errno.ENOSPC, "No space left on device")
            return reel(source, cible)

        with mock.patch.object(bot.os, "replace", panne_si_envoi_en_attente):
            etat, sortie = self.cycle(None)
        self.assertEqual(vus, [str(T2)])
        self.assertIsNone(etat)
        self.assertEqual(sortie.count("[silent]"), 1)
        self.assertIn("cannot be written (OSError", sortie)
        self.assertEqual(self.envoi.call_count, 1)  # celui de T1 seulement
        self.assertEqual(self.instantane()[self.engagements.name], avant[self.engagements.name])
        self.assertEqual(self.instantane()[self.etat.name], avant[self.etat.name])
        # Écriture rétablie : le message, resté en attente, reçoit sa réponse, une fois.
        etat, sortie = self.cycle(etat)
        self.assertEqual(self.envoi.call_count, 2)
        self.assertEqual(self.promis(), [BUR, "A BRE - PIC"])

    def test_c3_ecriture_des_engagements_impossible_a_l_etape_3(self):
        # Scénario de l'audit : seule l'écriture du fichier d'engagements échoue (sa
        # lecture et l'écriture de l'état réussissent), douze cycles. Aucune tentative
        # n'est comptée sans envoi, rien n'est annoncé « abandonné » ni « annulé ».
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat = None
        with self.ecriture_en_panne(self.engagements):
            for _ in range(12):
                etat, sortie = self.cycle(etat)
                self.assertIsNone(etat)
                self.assertEqual(sortie.count("[silent]"), 1)
                self.assertIn(str(self.engagements), sortie)
                self.assertIn("cannot be written (OSError", sortie)
                self.assertNotIn("[send-", sortie)
                en_attente = self.bot1()["pending_send"]  # écrit à l'étape 2
                self.assertEqual((en_attente["ts"], en_attente["attempts"], en_attente["rereads"]), (str(T1), 0, 0))
                self.assertEqual(self.bot1()["replied_ts"], [])
                self.assertEqual((self.reponses, self.claude.call_count, self.envoi.call_count), (1, 1, 0))
                self.assertEqual(self.promis(), [])
        # Écriture rétablie : un seul envoi, au cycle même, engagement écrit avant ; la
        # réponse n'est pas redemandée à Claude et le joueur la reçoit.
        vus = []
        self.site.pendant_l_envoi = lambda envoye: vus.append((self.bot1()["pending_send"]["attempts"], self.promis()))
        etat, sortie = self.cycle(etat)
        self.assertEqual(vus, [(1, [BUR])])
        self.assertEqual((sortie.count("[send-resume]"), sortie.count("[send-failed]")), (1, 0))
        self.assertEqual((self.reponses, self.envoi.call_count), (1, 1))
        self.assertEqual(self.site.textes_envoyes(), ["entendu"])
        self.assertEqual(len(self.site.messages), 1)
        self.verifier_envoi_confirme(1759400501)
        self.cycle(etat)
        self.assertEqual((self.reponses, self.envoi.call_count), (1, 1))

    def test_c3_jamais_poste_et_phase_changee(self):
        # Jamais posté, et la phase passe pendant la panne : rien n'est envoyé après coup.
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        with self.ecriture_en_panne(self.engagements):
            etat, _ = self.cycle(None)
        self.jeu.phase = "F1901M"
        etat, sortie = self.cycle(etat)
        self.assertEqual(self.envoi.call_count, 0)
        self.assertIn("was never posted", sortie)
        self.assertEqual(sortie.count("[send-failed]"), 1)
        etat = self.bot1()
        self.assertEqual((etat["replied_ts"], etat["exchange_counts"]), ([str(T1)], {}))
        self.assertNotIn("pending_send", etat)
        self.assertEqual(etat["own_promises"]["pending"], {})

    def test_f_abandon_annonce_une_fois_l_annulation_ecrite(self):
        # Plafond atteint pendant une panne d'écriture du fichier d'engagements : rien
        # n'est défait, donc rien n'est annoncé ; l'abandon est imprimé une fois, au
        # cycle où l'annulation est écrite.
        self.site.comportements = [faux_site.ERREUR_500] * 3
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat = None
        for _ in range(6):
            etat, _ = self.cycle(etat)
        avant = self.instantane()
        with self.ecriture_en_panne(self.engagements):
            for _ in range(3):
                etat, sortie = self.cycle(etat)
                self.assertIsNone(etat)
                self.assertEqual((sortie.count("[silent]"), sortie.count("[send-failed]")), (1, 0))
                # (le temporaire de l'écriture refusée reste dans le dossier)
                self.assertEqual({nom: self.instantane()[nom] for nom in avant}, avant)
        self.assertEqual((self.bot1()["pending_send"]["attempts"], self.promis()), (3, [BUR]))
        etat, sortie = self.cycle(etat)
        self.verifier_envoi_annule("[send-failed]", sortie)
        self.assertEqual(self.envoi.call_count, 3)

    def test_e_compteur_de_relectures_ecrit_a_l_etape_meme(self):
        # Le processus est tué pendant le cycle de la première relecture négative, après
        # le traitement de bot1 : le compteur de relectures est déjà sur disque, et le
        # cycle suivant, parti du disque, renvoie le texte (deuxième relecture négative).
        patch = mock.patch.object(bot, "API_KEYS", ["bot1", "bot2"])
        patch.start()
        self.addCleanup(patch.stop)
        self.site.comportements = [faux_site.ERREUR_500]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.cycle(None)
        self.assertEqual(self.bot1()["pending_send"]["rereads"], 0)
        reel = self.parties.side_effect

        def tuer_a_bot2(cle):
            if cle == "bot2":
                raise FinDEssai()
            return reel(cle)

        self.parties.side_effect = tuer_a_bot2
        with self.assertRaises(FinDEssai):
            self.cycle(None)
        self.parties.side_effect = reel
        self.assertEqual(self.bot1()["pending_send"]["rereads"], 1)
        etat, sortie = self.cycle(None)
        self.assertEqual((sortie.count("[send-retry]"), self.envoi.call_count), (1, 2))

    def test_extraction_ecartee_tant_que_l_envoi_n_est_pas_resolu(self):
        # Envoi incertain puis relectures négatives : aucun appel à Claude, rien d'écrit
        # pour l'extraction, jusqu'au cycle où l'envoi est résolu.
        self.site.comportements = [faux_site.ERREUR_500]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        etat, _ = self.cycle(etat)
        self.assertEqual(self.claude.call_count, 1)
        self.assertNotIn("commitment_counts", self.bot1())
        etat, _ = self.cycle(etat)  # renvoi, confirmé : l'extraction a lieu
        self.assertEqual((self.reponses, self.claude.call_count), (1, 2))
        self.assertEqual(self.bot1()["commitment_counts"], {PAIRE: 1})

    def test_sent_ts_abime(self):
        # sent_ts édité à la main : ce qui n'est pas une marque est retiré, avec une
        # ligne de journal, et la partie n'est pas bloquée.
        for abime, garde in (([["x"]], []), ([["x"], "1:ENGLAND:abc", 3], ["1:ENGLAND:abc"]), ("texte", [])):
            with self.subTest(abime=abime):
                self.setUp()
                self.site.comportements = [faux_site.ERREUR_500_STOCKE]
                self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
                etat, _ = self.cycle(None)
                etat["bot1:7"]["sent_ts"] = abime
                etat, sortie = self.cycle(etat)
                self.assertNotIn("unexpected error", sortie)
                self.assertEqual((sortie.count("[sent-ts]"), sortie.count("[send-confirmed]")), (1, 1))
                self.assertEqual(self.bot1()["sent_ts"], garde + [bot._sent_mark(1759400501, "ENGLAND", "entendu")])
                self.assertEqual(self.bot1()["replied_ts"], [str(T1)])
                etat, sortie = self.cycle(etat)
                self.assertEqual(sortie, "")
                self.doCleanups()

    def test_fichier_d_engagements_de_forme_inattendue(self):
        # JSON valide, forme inattendue : comme un fichier illisible. Le contrôle de
        # tête l'arrête avant toute lecture de partie et tout appel à Claude.
        formes = (
            {"7": []},
            {"7": {"S1901M": []}},
            {"7": {"S1901M": {"FRANCE": "A PAR - BUR"}}},
            {"7": {"S1901M": {"FRANCE": ["A PAR - BUR", 3]}}},
            {"8": {"F1901M": {"GERMANY": [["x"]]}}},  # autre partie : même fichier, même règle
        )
        for forme in formes:
            with self.subTest(forme=forme):
                self.setUp()
                contenu = json.dumps(forme).encode()
                self.engagements.write_bytes(contenu)
                self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
                etat = None
                for _ in range(3):
                    etat, sortie = self.cycle(etat)
                    self.assertIsNone(etat)
                    self.assertEqual(sortie.count("[silent]"), 1)
                    self.assertIn("is JSON but not in the expected shape", sortie)
                    self.assertIn(str(self.engagements), sortie)
                    self.assertEqual(self.compteurs(), (0, 0, 0))
                    self.assertEqual(self.instantane(), {self.engagements.name: contenu})
                # Réparé : le message, resté en attente, reçoit sa réponse.
                self.engagements.write_text(json.dumps({"7": {"S1901M": {"FRANCE": []}}}))
                etat, sortie = self.cycle(etat)
                self.assertEqual((self.reponses, self.envoi.call_count), (1, 1))
                self.verifier_envoi_confirme(1759400501)
                self.doCleanups()

    def test_forme_inattendue_apparue_pendant_l_appel_a_claude(self):
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.pendant_claude = lambda: self.engagements.write_text('{"7": []}')
        etat, sortie = self.cycle(None)
        self.assertIsNone(etat)
        self.assertEqual((sortie.count("[silent]"), self.envoi.call_count), (1, 0))
        self.assertEqual(self.engagements.read_text(), '{"7": []}')
        self.assertNotIn("pending_send", self.bot1())
        self.assertNotIn("sincere_by_recipient", self.bot1())

    def test_c1_etat_illisible_pendant_l_envoi_un_seul_message(self):
        # L'état devient illisible pendant post_req, qui réussit. Aucune mémoire des ts
        # n'est gardée à travers le silence : c'est pending_send, écrit avant l'envoi,
        # qui évite le second envoi au retour à la normale.
        intact = []

        def couper(envoye):
            intact.append(self.etat.read_bytes())
            self.etat.write_bytes(b'{"bot1:7": {"repl')

        self.site.pendant_l_envoi = couper
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, sortie = self.cycle(None)
        self.site.pendant_l_envoi = None
        self.assertIsNone(etat)
        self.assertEqual(sortie.count("[silent]"), 1)
        for _ in range(2):
            etat, sortie = self.cycle(etat)
            self.assertIsNone(etat)
            self.assertEqual(sortie.count("[silent]"), 1)
        self.assertEqual((self.reponses, self.envoi.call_count), (1, 1))
        self.assertIn(b'"pending_send"', intact[0])
        self.etat.write_bytes(intact[0])
        etat, sortie = self.cycle(etat)
        self.assertEqual(sortie.count("[send-confirmed]"), 1)
        self.assertEqual((self.reponses, self.envoi.call_count), (1, 1))
        self.assertEqual(len(self.site.messages), 1)
        self.verifier_envoi_confirme(1759400501)

    def test_c2_engagements_illisibles_apres_le_controle_de_tete(self):
        # Le fichier d'engagements devient illisible après le contrôle de tête de cycle :
        # ni écriture de l'état (point de sauvegarde), ni appel à Claude.
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        reel = self.parties.side_effect

        def parties(cle):
            self.engagements.write_bytes(b'{"7": {"S19')
            return reel(cle)

        self.parties.side_effect = parties
        etat, sortie = self.cycle(None)
        self.assertIsNone(etat)
        self.assertEqual(sortie.count("[silent]"), 1)
        self.assertEqual(self.compteurs(), (1, 0, 0))
        self.assertFalse(self.etat.exists())

    def test_c2_engagements_illisibles_juste_avant_l_appel_a_claude(self):
        # Même chose quand le fichier se dégrade après le premier point de sauvegarde.
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        def section(*args):
            self.engagements.write_bytes(b'{"7": {"S19')
            return ""

        with mock.patch.object(bot, "build_plan_section", section):
            etat, sortie = self.cycle(None)
        self.assertIsNone(etat)
        self.assertEqual(sortie.count("[silent]"), 1)
        self.assertEqual(self.compteurs(), (1, 0, 0))
        self.assertNotIn("pending_send", self.bot1())

    def test_c4_erreur_de_lecture_bot_muet_message_explicite(self):
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.etat.mkdir()  # un répertoire à la place du fichier d'état
        for _ in range(2):
            etat, sortie = self.cycle(None)
            self.assertIsNone(etat)
            self.assertEqual(sortie.count("[silent]"), 1)
            self.assertIn("cannot be read (IsADirectoryError", sortie)
            self.assertIn(str(self.etat), sortie)
            self.assertEqual(self.compteurs(), (0, 0, 0))
        self.etat.rmdir()
        etat, sortie = self.cycle(None)
        self.assertEqual(self.envoi.call_count, 1)

    # Lignes qui annoncent le changement d'engagement de scenario_trahison, dans l'ordre.
    ANNONCES_TRAHISON = [
        "  [betrayal] FRANCE drops 'A PAR - BUR' promised to ENGLAND in favour of 'A PAR - PIC' "
        "for GERMANY (value gain +0.8000)",
        "  [revision] FRANCE replaces 'A PAR - BUR' promised to GERMANY with 'A PAR - PIC' in the "
        "same conversation (value gain +0.8000)",
        "  sincere commitments -> ['A PAR - PIC']",
    ]

    def scenario_trahison(self):
        """BUR promis à l'Angleterre et à l'Allemagne ; rend l'état après ces deux messages."""
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.jeu.recevoir(T2, "GERMANY", "FRANCE")
        etat, _ = self.cycle(None)
        self.assertEqual(self.par_destinataire(), {"ENGLAND": [BUR], "GERMANY": [BUR]})
        # L'Allemagne écrit de nouveau : PIC, trahison de BUR déclarée et acceptée.
        self.sinceres["FRANCE"], self.labels["FRANCE"] = [PIC], [BUR]
        self.jeu.recevoir(T3, "GERMANY", "FRANCE")
        return etat

    def test_l_abandon_apres_une_trahison_acceptee(self):
        for comportements, marque, cycles in (
            ([faux_site.ERREUR_500] * 3, "[send-failed]", 7), ([faux_site.SOURDINE], "[send-muted]", 1),
        ):
            with self.subTest(marque=marque):
                self.setUp()
                etat = self.scenario_trahison()
                avant, promis_avant = self.bot1(), self.promis()
                self.site.comportements = list(comportements)
                etat, sortie = self.cycle(etat)
                journal = sortie
                if cycles > 1:
                    # Envoi incertain : l'engagement est gardé, la promesse retirée l'est encore.
                    en_attente = self.bot1()["pending_send"]
                    self.assertEqual(en_attente["added"], {"by_recipient": [PIC], "commitments": [PIC]})
                    self.assertEqual(en_attente["removed"], [{"order": BUR, "holders": ["ENGLAND", "GERMANY"]}])
                    self.assertEqual(en_attente["own_pending"], {"key": "S1901M:GERMANY", "before": [BUR]})
                    self.assertEqual(self.par_destinataire(), {"ENGLAND": [], "GERMANY": [PIC]})
                    self.assertEqual(self.promis(), [PIC])
                for _ in range(cycles - 1):
                    etat, sortie = self.cycle(etat)
                    journal += sortie
                self.assertEqual(sortie.count(marque), 1)
                # L'envoi n'est jamais confirmé : aucun changement d'engagement n'est annoncé,
                # à aucun cycle (les lignes restent dans pending_send, puis partent avec lui).
                for annonce in ANNONCES:
                    self.assertEqual(journal.count(annonce), 0, annonce)
                # La promesse abandonnée est rendue à ses deux détenteurs, partout.
                self.assertEqual(self.par_destinataire(), {"ENGLAND": [BUR], "GERMANY": [BUR]})
                self.assertEqual(self.promis(), [BUR])
                self.assertEqual(
                    self.bot1()["own_promises"]["pending"],
                    {"S1901M:ENGLAND": [BUR], "S1901M:GERMANY": [BUR]},
                )
                # Au plus un ordre par unité, et l'état d'avant le message, au ts marqué près
                # (et à la longueur de la conversation déjà lue par l'extraction).
                self.assertEqual(len({o.split()[1] for o in self.promis()}), len(self.promis()))
                apres = self.bot1()
                self.assertEqual(sorted(apres.pop("replied_ts")), sorted(avant.pop("replied_ts") + [str(T3)]))
                self.assertEqual(apres.pop("commitment_counts")["S1901M:FRANCE<->GERMANY"], 2)
                self.assertEqual(avant.pop("commitment_counts")["S1901M:FRANCE<->GERMANY"], 1)
                self.assertEqual(apres, avant)
                self.assertEqual(self.promis(), promis_avant)
                self.doCleanups()

    def test_l_trahison_confirmee_par_relecture(self):
        etat = self.scenario_trahison()
        self.site.comportements = [faux_site.ERREUR_500_STOCKE]
        etat, sortie = self.cycle(etat)
        # Envoi incertain : rien n'est annoncé, les lignes attendent dans pending_send.
        self.assertEqual([sortie.count(a) for a in ANNONCES], [0, 0, 0])
        self.assertEqual(self.bot1()["pending_send"]["journal"], self.ANNONCES_TRAHISON)
        # Fichier d'engagements remis à la main dans son état d'avant : la confirmation le réapplique.
        self.engagements.write_text(json.dumps({"7": {"S1901M": {"FRANCE": [BUR]}}}))
        etat, sortie = self.cycle(etat)
        self.assertEqual(sortie.count("[send-confirmed]"), 1)
        # Au cycle de la confirmation, une fois, après la ligne qui la constate : une
        # ligne [betrayal] par puissance trahie (ici l'Angleterre seule).
        lignes = sortie.splitlines()
        self.assertIn("[send-confirmed]", lignes[0])
        self.assertEqual(lignes[1:4], self.ANNONCES_TRAHISON)
        self.assertEqual([sortie.count(a) for a in ANNONCES], [1, 1, 1])
        self.assertEqual(self.par_destinataire(), {"ENGLAND": [], "GERMANY": [PIC]})
        self.assertEqual(self.promis(), [PIC])
        self.assertEqual(
            self.bot1()["own_promises"]["pending"], {"S1901M:ENGLAND": [BUR], "S1901M:GERMANY": [PIC]}
        )

    def test_l_trahison_confirmee_d_emblee_journal_inchange(self):
        # Non-régression : mêmes lignes, dans le même ordre, avant la ligne « sent ».
        etat = self.scenario_trahison()
        etat, sortie = self.cycle(etat)
        lignes = sortie.splitlines()
        debut = lignes.index(self.ANNONCES_TRAHISON[0])
        self.assertIn("replying to GERMANY", lignes[debut - 1])
        self.assertEqual(
            lignes[debut:debut + 4], self.ANNONCES_TRAHISON + ["  sent (status=200): 'entendu'"]
        )
        self.assertEqual([sortie.count(a) for a in ANNONCES], [1, 1, 1])
        self.assertNotIn("pending_send", self.bot1())

    def test_l_trahison_annoncee_une_fois_si_l_etat_ne_s_ecrit_pas_a_la_confirmation(self):
        # Message stocké (200), mais l'écriture de l'état qui retire pending_send échoue :
        # rien n'est annoncé à ce cycle ; au suivant, la relecture confirme et annonce, une fois.
        etat = self.scenario_trahison()

        def panne_a_la_confirmation(source, cible, reel=os.replace):
            if Path(str(cible)) == self.etat:
                ecrit = json.loads(Path(str(source)).read_text())["bot1:7"]
                if "pending_send" not in ecrit and str(T3) in ecrit["replied_ts"]:
                    raise OSError(errno.ENOSPC, "No space left on device")
            return reel(source, cible)

        with mock.patch.object(bot.os, "replace", panne_a_la_confirmation):
            etat, sortie = self.cycle(etat)
        self.assertIsNone(etat)
        self.assertEqual((sortie.count("[silent]"), sortie.count("sent (status")), (1, 0))
        self.assertEqual([sortie.count(a) for a in ANNONCES], [0, 0, 0])
        self.assertEqual(len(self.site.messages), 3)
        etat, sortie = self.cycle(etat)
        self.assertEqual(sortie.count("[send-confirmed]"), 1)
        self.assertEqual([sortie.count(a) for a in ANNONCES], [1, 1, 1])
        etat, sortie = self.cycle(etat)
        self.assertEqual([sortie.count(a) for a in ANNONCES], [0, 0, 0])
        self.assertEqual((self.envoi.call_count, len(self.site.messages)), (3, 3))

    def test_l_pending_send_d_avant_le_journal_confirme_sans_annonce(self):
        # État écrit par une version sans la clé `journal` : il reste valide, la
        # confirmation par relecture se fait, sans ligne à annoncer.
        etat = self.scenario_trahison()
        self.site.comportements = [faux_site.ERREUR_500_STOCKE]
        self.cycle(etat)
        etat = json.loads(self.etat.read_text())
        del etat["bot1:7"]["pending_send"]["journal"]
        self.etat.write_text(json.dumps(etat))
        etat, sortie = self.cycle(None)
        self.assertEqual((sortie.count("[send-confirmed]"), sortie.count("[send-failed]")), (1, 0))
        self.assertEqual([sortie.count(a) for a in ANNONCES], [0, 0, 0])
        self.assertEqual(self.par_destinataire(), {"ENGLAND": [], "GERMANY": [PIC]})

    TEXTE_M = "D'accord & merci : été, ça < 3 > 2\r\nligne 2 \"citée\" &amp; <br />fin  "

    def test_m_texte_avec_accents_et_balises(self):
        self.textes["FRANCE"] = self.TEXTE_M
        self.site.comportements = [faux_site.ERREUR_500_STOCKE]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        # Le site ne stocke pas le texte tel quel : la comparaison brute échouerait.
        stocke = self.site.messages[0]["message"]
        self.assertEqual(
            stocke,
            "D'accord &amp; merci : &eacute;t&eacute;, &ccedil;a &lt; 3 &gt; 2<br />"
            "ligne 2 \"cit&eacute;e\" &amp;amp; <br />fin",
        )
        etat, sortie = self.cycle(etat)
        self.assertEqual(sortie.count("[send-confirmed]"), 1)
        self.assertEqual(self.envoi.call_count, 1)
        self.verifier_envoi_confirme(1759400501, self.TEXTE_M.strip())

    def test_m_caractere_hors_plan_de_base(self):
        # Hypothèse non vérifiée sur le site : un émoji stocké en « ? ». La relecture confirme
        # dans les deux cas (stocké tel quel, ou remplacé).
        for remplace in (False, True):
            with self.subTest(remplace=remplace):
                self.setUp()
                self.site.quatre_octets = remplace
                self.textes["FRANCE"] = "ok \U0001F600 ça marche ?"
                self.site.comportements = [faux_site.ERREUR_500_STOCKE]
                self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
                etat, _ = self.cycle(None)
                self.assertEqual("?" in self.site.messages[0]["message"].split("&ccedil;")[0], remplace)
                etat, sortie = self.cycle(etat)
                self.assertEqual(sortie.count("[send-confirmed]"), 1)
                self.assertEqual(self.envoi.call_count, 1)
                self.doCleanups()

    def test_m_cle_de_comparaison(self):
        cle = bot._message_key
        self.assertEqual(cle(" a\r\nb\rc<br />d\n "), "a\nb\nc\nd")
        self.assertEqual(cle("a &amp; b &lt; c &eacute;"), "a & b < c é")
        self.assertEqual(cle("ok \U0001F600 ?"), cle("ok ? ?"))
        self.assertNotEqual(cle("oui"), cle("non"))
        self.assertNotEqual(cle("A PAR - BUR"), cle("A PAR - PIC"))
        for texte in (self.TEXTE_M, "x", "a\n\nb", "&amp;amp;", "<b>gras</b>"):
            self.assertEqual(cle(bot._decode_stored_message(faux_site.echapper(texte))), cle(texte), texte)

    def test_classement_de_la_reponse_du_site(self):
        def reponse(statut, corps):
            return mock.Mock(status_code=statut, content=corps)

        un = b'{"messages": [{"fromCountryID": 1, "message": "entendu", "timeSent": 1759400501, "toCountryID": 3, "turn": 0}]}'
        cas = (
            (reponse(200, un), ("sent", 1759400501)),
            (reponse(200, un.decode()), ("sent", 1759400501)),
            (reponse(200, b'{"messages": []}'), ("muted", None)),
            (reponse(500, un), "uncertain"),
            (reponse(403, b'{"messages": []}'), "uncertain"),
            (reponse(200, b""), "uncertain"),
            (reponse(200, b"<html>"), "uncertain"),
            (reponse(200, un + b"<br /><b>Warning</b>"), "uncertain"),
            (reponse(200, b"<b>Notice</b>" + un), "uncertain"),
            (reponse(200, b"1759400501"), "uncertain"),
            (reponse(200, b'{"messages": null}'), "uncertain"),
            (reponse(200, b'{"messages": [{"message": "entendu"}]}'), "uncertain"),
            (reponse(200, b'{"messages": [{"timeSent": true}]}'), "uncertain"),
            (reponse(200, b'\xff'), "uncertain"),
            (reponse(200, None), "uncertain"),
            (mock.Mock(spec=[]), "uncertain"),
        )
        for i, (rendu, attendu) in enumerate(cas):
            with self.subTest(i):
                obtenu = bot._send_outcome(rendu)
                if attendu == "uncertain":
                    self.assertEqual(obtenu[0], "uncertain")
                    self.assertIsInstance(obtenu[1], str)
                else:
                    self.assertEqual(obtenu, attendu)

    def test_pending_send_mal_forme_ecarte(self):
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        etat, _ = self.cycle(None)
        for mal_forme, marque in (
            ("texte", None), ({}, None), ({"ts": ["x"]}, None),
            ({"ts": str(T2), "recipient": "SPAIN", "text": "x", "phase": "S1901M",
              "added": {"by_recipient": [], "commitments": []}, "removed": [],
              "own_pending": None, "attempts": 1, "rereads": 0}, str(T2)),
            ({"ts": str(T3), "recipient": "ENGLAND", "text": "x", "phase": "S1901M",
              "added": {"by_recipient": [], "commitments": []}, "removed": [],
              "own_pending": None, "attempts": -1, "rereads": 0}, str(T3)),
            # `ts` écrit comme un entier : le message répondu se dit aussi bien.
            ({"ts": T2, "recipient": "ENGLAND", "text": "x"}, str(T2)),
            ({"ts": True}, None), ({"ts": -1}, None),
            # `journal` qui n'est pas une liste de lignes.
            ({"ts": str(T3), "recipient": "ENGLAND", "text": "x", "phase": "S1901M",
              "added": {"by_recipient": [], "commitments": []}, "removed": [],
              "own_pending": None, "journal": "[betrayal]", "attempts": 1, "rereads": 0}, str(T3)),
        ):
            with self.subTest(mal_forme=mal_forme):
                etat["bot1:7"]["pending_send"] = mal_forme
                etat, sortie = self.cycle(etat)
                self.assertEqual(sortie.count("[send-failed] malformed pending_send"), 1)
                self.assertEqual(sortie.count("WARNING"), 0 if marque else 1)
                self.assertNotIn("pending_send", self.bot1())
                self.assertEqual(marque in self.bot1()["replied_ts"], bool(marque))
                self.assertEqual(self.envoi.call_count, 1)
                self.assertEqual(self.promis(), [BUR])

    def test_pending_send_mal_forme_message_stocke_jamais_renvoye(self):
        # Scénario de l'audit : 500 mais message stocké, puis `attempts` retiré à la
        # main de l'état. Le message reçu est marqué répondu : ni second appel à
        # Claude, ni second message ; rien d'autre n'est défait.
        self.site.comportements = [faux_site.ERREUR_500_STOCKE]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.cycle(None)
        etat = json.loads(self.etat.read_text())
        del etat["bot1:7"]["pending_send"]["attempts"]
        self.etat.write_text(json.dumps(etat))
        etat = None
        for attendu in (1, 0, 0):
            etat, sortie = self.cycle(etat)
            self.assertEqual(sortie.count("[send-failed] malformed pending_send"), attendu)
        self.assertEqual((self.reponses, self.envoi.call_count, len(self.site.messages)), (1, 1, 1))
        etat = self.bot1()
        self.assertEqual(etat["replied_ts"], [str(T1)])
        self.assertNotIn("pending_send", etat)
        self.assertEqual(self.par_destinataire(), {"ENGLAND": [BUR]})
        self.assertEqual(self.promis(), [BUR])

    def test_pending_send_mal_forme_ts_entier_message_stocke_jamais_renvoye(self):
        # Même scénario, `ts` réécrit à la main comme un entier : le message reçu est
        # marqué répondu lui aussi (avant : entrée jetée, seconde réponse envoyée).
        self.site.comportements = [faux_site.ERREUR_500_STOCKE]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.cycle(None)
        etat = json.loads(self.etat.read_text())
        etat["bot1:7"]["pending_send"]["ts"] = T1
        self.etat.write_text(json.dumps(etat))
        etat = None
        for attendu in (1, 0, 0):
            etat, sortie = self.cycle(etat)
            self.assertEqual(sortie.count("[send-failed] malformed pending_send"), attendu)
            self.assertNotIn("WARNING", sortie)
        self.assertEqual((self.reponses, self.envoi.call_count, len(self.site.messages)), (1, 1, 1))
        self.assertEqual(self.bot1()["replied_ts"], [str(T1)])

    def test_cloisonnement_un_envoi_incertain_ne_bloque_que_son_bot(self):
        # bot1 (France) a un envoi incertain ; bot2 (Allemagne), dans la même partie, répond.
        patch = mock.patch.object(bot, "API_KEYS", ["bot1", "bot2"])
        patch.start()
        self.addCleanup(patch.stop)
        self.site.comportements = [faux_site.ERREUR_500]
        self.jeu.recevoir(T1, "ENGLAND", "FRANCE")
        self.jeu.recevoir(T2, "ENGLAND", "GERMANY")
        etat, _ = self.cycle(None)
        self.assertEqual(self.envoi.call_count, 2)
        etat = json.loads(self.etat.read_text())
        self.assertIn("pending_send", etat["bot1:7"])
        self.assertNotIn("pending_send", etat["bot2:7"])
        self.assertEqual(etat["bot2:7"]["replied_ts"], [str(T2)])


if __name__ == "__main__":
    unittest.main()
