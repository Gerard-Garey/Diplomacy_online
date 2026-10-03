"""Banc d'essai déterministe de la logique des promesses (issues #2, #3, #4).

Charge les trois fichiers du dépôt qui portent cette logique
(cicero/overlay/claude_dialogue_bot.py, fairdiplomacy/utils/plan_export.py et
fairdiplomacy/utils/pseudo_commitments.py) par importlib, sans pile, sans
Claude, sans GPU : les modules de Cicero qu'ils importent sont des doublures.
Deux d'entre elles ont un contenu réel, parce que les fonctions testées s'en
servent : fairdiplomacy.typedefs (alias de types) et fairdiplomacy.utils.orders
(normalize_order_spacing et get_unit_location, recopiées de l'amont). Seule la
ligne `return` de normalize_order_spacing, ajoutée par le patch, est contrôlée
par tests/test_promesses.py contre cicero/patches/0001-cicero.patch ;
get_unit_location vient de l'amont non modifié, que le dépôt ne contient pas :
sa recopie n'est contrôlée par aucun test.

Sert à tests/test_promesses.py (comportement cible) et à
tests/mesure_promesses.py (sortie actuelle, colonne « avant » du tableau
avant / après) : les deux lisent les mêmes entrées, définies ici.
"""
import contextlib
import importlib.util
import io
import itertools
import json
import re
import sys
import tempfile
import types
from pathlib import Path
from typing import Dict, Tuple
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
OVERLAY = RACINE / "cicero" / "overlay"

# Modules de Cicero importés par les trois fichiers, absents hors du conteneur.
DOUBLURES = [
    "fairdiplomacy_external.webdip_api",
    "parlai_diplomacy.utils.game2seq.format_helpers.state",
    "fairdiplomacy.data.build_dataset",
    "fairdiplomacy.pydipcc",
    "fairdiplomacy.typedefs",
    "fairdiplomacy.utils.plan_export",
    "fairdiplomacy.utils.orders",
    "fairdiplomacy.utils.pseudo_commitments",
]

# Ligne de normalize_order_spacing dans l'amont patché (cicero/patches/0001-cicero.patch).
LIGNE_NORMALISATION = 'return re.sub(r"(?<=\\S)-(?=\\S)", " - ", order.strip())'


def normalize_order_spacing(order):
    return re.sub(r"(?<=\S)-(?=\S)", " - ", order.strip())


def get_unit_location(order):
    pieces = order.split()
    assert len(pieces) >= 2
    return pieces[1]


class ErreurBanc(Exception):
    """Le banc n'a pas pu faire ce qu'on lui demandait : jamais l'échec attendu d'une issue."""


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, str(chemin))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def charger_modules():
    """Rend (bot, plan_export, pseudo_commitments), chargés depuis le dépôt."""
    for nom in DOUBLURES:
        parties = nom.split(".")
        for i in range(1, len(parties) + 1):
            sys.modules[".".join(parties[:i])] = mock.MagicMock()
    typedefs = types.ModuleType("fairdiplomacy.typedefs")
    typedefs.Order = typedefs.Power = str
    typedefs.Action = Tuple[str, ...]
    typedefs.PowerPolicies = Dict[str, Dict[Tuple[str, ...], float]]
    orders = types.ModuleType("fairdiplomacy.utils.orders")
    orders.normalize_order_spacing = normalize_order_spacing
    orders.get_unit_location = get_unit_location
    sys.modules["fairdiplomacy.typedefs"] = typedefs
    sys.modules["fairdiplomacy.utils.orders"] = orders
    utils = OVERLAY / "fairdiplomacy" / "utils"
    plan_export = _charger("banc_plan_export", utils / "plan_export.py")
    pseudo_commitments = _charger("banc_pseudo_commitments", utils / "pseudo_commitments.py")
    bot = _charger("banc_claude_dialogue_bot", OVERLAY / "claude_dialogue_bot.py")
    return bot, plan_export, pseudo_commitments


bot, plan_export, pseudo_commitments = charger_modules()

# ---------------------------------------------------------------------------
# Position : la France a trois unités ; ordres légaux de chacune.
# ---------------------------------------------------------------------------
PARTIE, PHASE = 7, "S1901M"
ORDRES_LEGAUX = {
    "PAR": ["A PAR H", "A PAR - PIC", "A PAR - BUR", "A PAR - GAS"],
    "MAR": ["A MAR H", "A MAR - SPA", "A MAR - PIE"],
    "BRE": ["F BRE H", "F BRE - ENG", "F BRE - MAO"],
}
PIC, BUR, GAS = "A PAR - PIC", "A PAR - BUR", "A PAR - GAS"


class FauxJeu:
    """Ce que le bot et legal_commitments lisent d'une partie."""

    def __init__(self):
        self.messages = {}

    def get_current_phase(self):
        return PHASE

    def get_state(self):
        return {}

    def get_all_phases(self):
        return []

    def get_orderable_locations(self):
        return {"FRANCE": list(ORDRES_LEGAUX)}

    def get_all_possible_orders(self):
        return ORDRES_LEGAUX


def plans(*valeurs):
    """Liste `plans` de current_plans.json : un plan par couple (ordre, valeur), meilleur d'abord."""
    meilleur = valeurs[0][1]
    return [
        {"rank": i + 1, "orders": [ordre], "value": valeur, "cost_vs_best": round(meilleur - valeur, 5)}
        for i, (ordre, valeur) in enumerate(valeurs)
    ]


# #2 : BUR à 0,30 et PIC à 0,20 (mesure de l'expert).
PLANS_2 = plans((BUR, 0.30), (PIC, 0.20))
# #3 : GAS, promis d'abord, est absent des plans exportés.
PLANS_3 = plans((PIC, 0.30))
# Deux ordres connus des plans, écart supérieur à la marge (non-régression).
PLANS_CONNUS = plans((PIC, 0.9), (BUR, 0.1))


def rejet(sincere, anterieurs, plans_exportes):
    """Les trois premiers retours de _reject_contradictions, et les antérieurs après l'appel."""
    anterieurs = {d: list(o) for d, o in anterieurs.items()}
    with mock.patch.object(bot, "normalize_order_spacing", normalize_order_spacing):
        retour = bot._reject_contradictions(list(sincere), anterieurs, plans_exportes)
    return retour[0], retour[1], retour[2], anterieurs


# ---------------------------------------------------------------------------
# #3 : export des plans. 14 candidats ; GAS n'apparaît qu'au rang 12.
# ---------------------------------------------------------------------------
def candidats_14():
    """action_values de 14 candidats, meilleur d'abord : (action, valeur, bp_prob, pice)."""
    paris = [PIC, BUR] * 5 + ["A PAR H", GAS, "A PAR H", PIC]
    mar = ["A MAR - SPA", "A MAR - PIE", "A MAR H"]
    return [
        ((paris[i], mar[i % 3], "F BRE - MAO"), round(0.50 - 0.02 * i, 2), 0.05, 0.0)
        for i in range(14)
    ]


def exporter(candidats, dossier):
    """Appelle export_plans dans `dossier` ; rend l'entrée écrite pour la France."""
    fichier = Path(dossier) / "current_plans.json"
    with mock.patch.object(plan_export, "PLANS_FILE", fichier):
        plan_export.export_plans(str(PARTIE), PHASE, "FRANCE", candidats)
        return plan_export.load_plans(str(PARTIE), PHASE, "FRANCE")


# ---------------------------------------------------------------------------
# #4 : renfort de probabilité. A1 tient un ordre promis, A2 les deux, A3 aucun.
# ---------------------------------------------------------------------------
PROMESSES_4 = ["A MAR - SPA", "F BRE - ENG"]
A1 = ("A MAR - SPA", "A PAR - BUR", "F BRE - MAO")
A2 = ("A MAR - SPA", "A PAR - BUR", "F BRE - ENG")
A3 = ("A MAR - PIE", "A PAR - BUR", "F BRE - MAO")
A1_BIS = ("A MAR - SPA", "A PAR - PIC", "F BRE - MAO")  # un ordre promis, comme A1
# Exemple de l'issue #4 : 0,5 à l'action qui ne tient aucun ordre promis, 0,3 à
# celle qui en tient un, 0,2 à celle qui tient les deux.
POLITIQUE_ISSUE_4 = {A3: 0.5, A1: 0.3, A2: 0.2}
MULTIPLICATEUR = 3.0  # pseudo_commitment_boost de cicero_no_dialogue.prototxt
AUTRES = {"GERMANY": {("A MUN - RUH",): 0.6, ("A MUN - BUR",): 0.4}}


def renfort(politique, ordre=None, promesses=PROMESSES_4):
    """apply_commitments_to_policy sur la politique de la France, clés présentées dans `ordre`.

    Rend la politique entière (toutes les puissances) après l'appel.
    """
    ordre = list(politique) if ordre is None else ordre
    entree = {"FRANCE": {a: politique[a] for a in ordre}}
    entree.update({p: dict(d) for p, d in AUTRES.items()})
    return pseudo_commitments.apply_commitments_to_policy(
        entree, FauxJeu(), {"FRANCE": list(promesses)}, "FRANCE", MULTIPLICATEUR
    )


def permutations(politique):
    return [list(p) for p in itertools.permutations(politique)]


def cible_r3(politique, promesses=PROMESSES_4, k=MULTIPLICATEUR):
    """Règle R3 décidée le 2026-10-03 : mu(a) = k^(m/n), plafond, renormalisation."""
    plafond = pseudo_commitments.MAX_COMMITMENT_PROB
    n = len(promesses)
    brut = {
        a: max(p, min(p * k ** (len(set(promesses) & set(a)) / n), plafond))
        for a, p in politique.items()
    }
    total = sum(brut.values())
    return {a: p / total for a, p in brut.items()}


# ---------------------------------------------------------------------------
# Cycles du bot de dialogue : bot1 joue la France, partie 7.
# ---------------------------------------------------------------------------
class Banc:
    """Fait tourner run_cycle dans un dossier temporaire, Claude et l'envoi doublés.

    `entree_plans` est l'entrée de la France dans current_plans.json (lue par le
    vrai load_plans) : {"plans": [...]} et, au format cible de #3, "order_values".
    legal_commitments est la vraie fonction, sur la position de FauxJeu.
    """

    def __init__(self, entree_plans=None):
        self.entree_plans = entree_plans
        self.jeu = FauxJeu()
        self.retours = []  # retours successifs de _reject_contradictions
        self.sincere = []
        self.appels_inconnus = []  # consignes d'appels à Claude que la doublure n'a pas reconnues
        self.horloge = 1759400000
        self.etat = None

    def __enter__(self):
        self.pile = contextlib.ExitStack()
        logs = Path(self.pile.enter_context(tempfile.TemporaryDirectory())) / "webdip_logs_test"
        logs.mkdir()
        self.fichier_etat = logs / "claude_dialogue_state.json"
        self.fichier_engagements = logs / "pseudo_commitments.json"
        self.fichier_plans = logs / "current_plans.json"
        if self.entree_plans is not None:
            self.fichier_plans.write_text(
                json.dumps({str(PARTIE): {PHASE: {"FRANCE": self.entree_plans}}})
            )

        # Les deux appels à Claude se reconnaissent à leur consigne système. Un
        # appel qui n'est ni l'un ni l'autre est noté, et message() lève : lever
        # ici ne suffirait pas, le bot rattrape les exceptions de ces appels.
        extractions = {
            bot.COMMITMENT_SYSTEM_PROMPT.format(power="FRANCE", other=autre)
            for autre in ("GERMANY", "ENGLAND")
        }

        def claude(commande, **kwargs):
            consigne = commande[commande.index("--system-prompt") + 1]
            if consigne in extractions:
                reponse = {"mine": [], "theirs": []}
            elif consigne.startswith("You are playing FRANCE"):
                reponse = {"reply": "entendu", "sincere": self.sincere}
            else:
                self.appels_inconnus.append(consigne[:60])
                raise ErreurBanc("appel à Claude non reconnu : %r" % consigne[:60])
            return mock.Mock(stdout=json.dumps({"result": json.dumps(reponse)}))

        rejet_reel = bot._reject_contradictions

        def rejet_espionne(*args, **kwargs):
            retour = rejet_reel(*args, **kwargs)
            self.retours.append(retour)
            return retour

        doublures = {
            "STATE_FILE": self.fichier_etat,
            "COMMITMENTS_FILE": self.fichier_engagements,
            "API_KEYS": ["bot1"],
            "COUNTRY_ID_TO_POWER_OR_ALL": {1: "FRANCE", 2: "GERMANY", 3: "ENGLAND"},
            "POWER_TO_ID": {"FRANCE": 1, "GERMANY": 2, "ENGLAND": 3},
            "get_active_games": lambda cle: [{"gameID": PARTIE, "countryID": 1, "variantID": 1}],
            "get_status_json": lambda ctx: {},
            "webdip_state_to_game": lambda status: self.jeu,
            "normalize_order_spacing": normalize_order_spacing,
            "legal_commitments": pseudo_commitments.legal_commitments,
            "load_plans": plan_export.load_plans,
            "post_req": mock.Mock(return_value=mock.Mock(status_code=200)),
            "_reject_contradictions": rejet_espionne,
        }
        self.envoi = doublures["post_req"]
        for nom, valeur in doublures.items():
            self.pile.enter_context(mock.patch.object(bot, nom, valeur))
        self.pile.enter_context(mock.patch.object(plan_export, "PLANS_FILE", self.fichier_plans))
        self.pile.enter_context(mock.patch.object(bot.subprocess, "run", claude))
        return self

    def __exit__(self, *exc):
        return self.pile.__exit__(*exc)

    def message(self, expediteur, sincere):
        """`expediteur` écrit à la France, qui répond avec la liste `sincere` ; rend le journal.

        Lève ErreurBanc si le cycle n'est pas allé au bout du traitement du
        message : run_cycle rattrape les exceptions de process_bot et ne les
        signale que dans son journal, et un cycle interrompu n'enregistre rien,
        ce qu'un test prendrait pour « rien n'est promis ».
        """
        self.horloge += 60
        self.jeu.messages[self.horloge] = {
            "sender": expediteur, "recipient": "FRANCE", "message": "bonjour", "phase": PHASE,
        }
        self.sincere = list(sincere)
        retours, envois = len(self.retours), self.envoi.call_count
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.etat = bot.run_cycle(self.etat)
        journal = sortie.getvalue()
        defauts = [m for m in ("unexpected error", "[silent]", "failed") if m in journal]
        if self.appels_inconnus:
            defauts.append("appel à Claude non reconnu : %r" % self.appels_inconnus)
        if len(self.retours) != retours + 1:
            defauts.append("_reject_contradictions appelé %d fois" % (len(self.retours) - retours))
        if self.envoi.call_count != envois + 1:
            defauts.append("post_req appelé %d fois" % (self.envoi.call_count - envois))
        repondus = (self.etat or {}).get("bot1:%d" % PARTIE, {}).get("replied_ts", [])
        if str(self.horloge) not in repondus:
            defauts.append("message absent de replied_ts")
        if defauts:
            raise ErreurBanc("cycle interrompu (%s) ; journal :\n%s" % (" ; ".join(defauts), journal))
        return journal

    def by_recipient(self):
        """by_recipient tel qu'il est écrit sur disque."""
        etat = json.loads(self.fichier_etat.read_text())
        return etat["bot1:%d" % PARTIE]["sincere_by_recipient"]["by_recipient"]

    def engagements(self):
        """Engagements de la France dans pseudo_commitments.json ([] si rien n'est écrit)."""
        if not self.fichier_engagements.exists():
            return []
        donnees = json.loads(self.fichier_engagements.read_text())
        return donnees.get(str(PARTIE), {}).get(PHASE, {}).get("FRANCE", [])


def entree(plans_exportes, order_values=None):
    """Entrée de current_plans.json ; `order_values` au format cible de #3 s'il est donné."""
    donnees = {"computed_at": 0, "plans": plans_exportes}
    if order_values is not None:
        donnees["order_values"] = order_values
    return donnees


def trahison(entree_plans, premier, second):
    """La France promet `premier` à l'Angleterre puis `second` à l'Allemagne.

    Rend (retour de _reject_contradictions au second message, by_recipient, engagements).
    """
    with Banc(entree_plans) as banc:
        banc.message("ENGLAND", [premier])
        banc.message("GERMANY", [second])
        return banc.retours[-1], banc.by_recipient(), banc.engagements()
