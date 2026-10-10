"""Banc d'essai déterministe de la logique des promesses (issues #2, #3, #4, #17).

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

Le bot importe engine_head_action de pseudo_commitments, qui est ici une doublure
vide : charger_modules lui rend la vraie fonction, celle du fichier du dépôt.

Sert à tests/test_promesses.py (comportement cible) et à
tests/mesure_promesses.py (sortie actuelle, colonne « avant » du tableau
avant / après) : les deux lisent les mêmes entrées, définies ici.

L'envoi et le statut de partie sont ceux de tests/faux_site.py : l'envoi rend
ce que rend le site, et le message envoyé se relit dans le statut (#5).
"""
import contextlib
import importlib.util
import io
import itertools
import json
import math
import random
import re
import sys
import tempfile
import types
from pathlib import Path
from typing import Dict, Tuple
from unittest import mock

import faux_site

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


class InvariantRompu(AssertionError):
    """Critère (g) de #17 : deux ordres pour une unité dans pseudo_commitments.json."""


def unites_en_double(ordres):
    """Unités qui reçoivent plus d'un ordre distinct (comparés en forme normalisée)."""
    par_unite = {}
    for ordre in ordres:
        ordre = normalize_order_spacing(ordre)
        par_unite.setdefault(get_unit_location(ordre), set()).add(ordre)
    return sorted(unite for unite, distincts in par_unite.items() if len(distincts) > 1)


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
    # La condition moteur de #17 : la vraie fonction, pas l'attribut de la doublure.
    bot.engine_head_action = pseudo_commitments.engine_head_action
    return bot, plan_export, pseudo_commitments


bot, plan_export, pseudo_commitments = charger_modules()

# ---------------------------------------------------------------------------
# Position : la France a trois unités ; ordres légaux de chacune.
# ---------------------------------------------------------------------------
PARTIE, PHASE = 7, "S1901M"
PHASE_SUIVANTE = "F1901M"
ORDRES_LEGAUX = {
    "PAR": ["A PAR H", "A PAR - PIC", "A PAR - BUR", "A PAR - GAS"],
    "MAR": ["A MAR H", "A MAR - SPA", "A MAR - PIE"],
    "BRE": ["F BRE H", "F BRE - ENG", "F BRE - MAO"],
}
PIC, BUR, GAS = "A PAR - PIC", "A PAR - BUR", "A PAR - GAS"


class PhaseJouee:
    """Une phase de get_all_phases : son nom et les ordres joués par puissance."""

    def __init__(self, name, orders):
        self.name, self.orders = name, orders


class FauxJeu:
    """Ce que le bot et legal_commitments lisent d'une partie.

    La partie commence en PHASE ; resoudre() la clôt avec les ordres joués et
    passe à la suivante. Comme dans une vraie partie, get_all_phases rend aussi
    la phase courante, sans ordres. Les unités ne bougent pas d'une phase à
    l'autre : les ordres légaux restent ORDRES_LEGAUX.
    """

    def __init__(self):
        self.messages = {}
        self.phase = PHASE
        self.resolues = []

    def get_current_phase(self):
        return self.phase

    def get_state(self):
        return {}

    def get_all_phases(self):
        return self.resolues + [PhaseJouee(self.phase, {})]

    def rolled_back_to_phase_start(self, phase):
        return self

    def resoudre(self, ordres, suivante=PHASE_SUIVANTE):
        """Clôt la phase courante : `ordres` par puissance, tels qu'ils ont été joués."""
        self.resolues.append(PhaseJouee(self.phase, {p: list(o) for p, o in ordres.items()}))
        self.phase = suivante

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


# Paramètres de recherche du banc : lambda de cicero_no_dialogue.prototxt (1e-2),
# multiplicateur et plafond du renfort (#4).
RECHERCHE = {"lambda": 0.01, "boost": 3.0, "max_prob": 0.4}


def candidats(*actions):
    """Clé `candidates` : une action par couple (ordres, valeur), probabilités égales."""
    return [
        {"orders": list(ordres), "value": valeur, "prob": float("%.6g" % (1 / len(actions)))}
        for ordres, valeur in actions
    ]


def candidats_du_banc(plans_exportes, order_values=None):
    """Table des candidats d'une entrée du banc, quand le test n'en donne pas.

    Avec un index : une action d'un seul ordre par ordre de l'index, à sa valeur,
    la mieux valorisée d'abord. Sans index : une action par plan exporté. Les
    probabilités sont égales. Ne convient qu'aux cas où une seule unité est en
    jeu ; les autres donnent leur table (voir mesure_promesses.ENTREE_BILAN).
    """
    if order_values is not None:
        ordres = sorted(order_values, key=lambda o: -order_values[o])
        return candidats(*(((o,), order_values[o]) for o in ordres))
    return candidats(*((p["orders"], p["value"]) for p in plans_exportes or []))


def rejet_complet(sincere, anterieurs, plans_exportes, betray=None, order_values=None,
                  table=True, candidates=None, search=None, margin=None):
    """Tous les retours de _reject_contradictions, et les antérieurs après l'appel.

    `betray` (#17) et `order_values` (#3) ne sont passés que s'ils sont donnés.
    La table du moteur (`candidates`, `search`) est celle du banc
    (candidats_du_banc, RECHERCHE) sauf si elle est donnée ; `table` faux :
    aucune n'est passée, comme pour une entrée écrite avant #17.
    """
    anterieurs = {d: list(o) for d, o in anterieurs.items()}
    options = {}
    if betray is not None:
        options["betray"] = list(betray)
    if order_values is not None:
        options["order_values"] = order_values
    if margin is not None:
        options["margin"] = margin
    if table:
        options["candidates"] = (
            candidats_du_banc(plans_exportes, order_values) if candidates is None else candidates
        )
        options["search"] = RECHERCHE if search is None else search
    with mock.patch.object(bot, "normalize_order_spacing", normalize_order_spacing):
        retour = bot._reject_contradictions(list(sincere), anterieurs, plans_exportes, **options)
    return tuple(retour), anterieurs


def rejet(sincere, anterieurs, plans_exportes, betray=None, order_values=None, **options):
    """Les trois premiers retours de _reject_contradictions, et les antérieurs après l'appel."""
    retour, anterieurs = rejet_complet(
        sincere, anterieurs, plans_exportes, betray, order_values, **options
    )
    return retour[0], retour[1], retour[2], anterieurs


# ---------------------------------------------------------------------------
# #3 : export des plans. 14 candidats ; GAS n'apparaît qu'au rang 12.
# ---------------------------------------------------------------------------
def candidats_14():
    """action_values de 14 candidats, meilleur d'abord : (action, valeur, bp_prob, pice).

    Quatorze actions distinctes, comme les clés d'une politique : la flotte de
    Brest change d'ordre tous les six candidats.
    """
    paris = [PIC, BUR] * 5 + ["A PAR H", GAS, "A PAR H", PIC]
    mar = ["A MAR - SPA", "A MAR - PIE", "A MAR H"]
    bre = ["F BRE - MAO", "F BRE - ENG", "F BRE H"]
    return [
        ((paris[i], mar[i % 3], bre[i // 6]), round(0.50 - 0.02 * i, 2), 0.05, 0.0)
        for i in range(14)
    ]


def exporter(action_values, dossier, avant_renfort=None, recherche=RECHERCHE, table=True):
    """Appelle export_plans dans `dossier` ; rend l'entrée écrite pour la France.

    `avant_renfort` : politique avant renfort ({action: probabilité}) ; par défaut
    les probabilités d'`action_values` (aucun engagement : rien n'a été renforcé).
    `table` faux : appel d'avant #17, sans politique ni paramètres de recherche.
    """
    fichier = Path(dossier) / "current_plans.json"
    options = {}
    if table:
        if avant_renfort is None:
            avant_renfort = {action: prob for action, _, prob, _ in action_values}
        options = dict(
            prior_policy=avant_renfort, regularize_lambda=recherche["lambda"],
            boost=recherche["boost"], max_prob=recherche["max_prob"],
        )
    with mock.patch.object(plan_export, "PLANS_FILE", fichier):
        plan_export.export_plans(str(PARTIE), PHASE, "FRANCE", action_values, **options)
        return plan_export.load_plans(str(PARTIE), PHASE, "FRANCE")


def classer(actions, regularize_lambda, promesses=(), k=None, plafond=None):
    """action_values comme le moteur les rend, à partir de (action, valeur, p avant renfort).

    Applique le renfort du moteur (boosted_policy) pour `promesses`, calcule le
    score valeur + lambda x ln(max(p, 1e-6)) et trie par score décroissant
    (br_corr_bilateral_search.py). Rend (action_values, politique avant renfort).
    """
    avant = {action: p for action, _, p in actions}
    apres = pseudo_commitments.boosted_policy(
        avant, promesses, RECHERCHE["boost"] if k is None else k,
        RECHERCHE["max_prob"] if plafond is None else plafond,
    )
    lignes = [
        (action, valeur, apres[action], valeur + regularize_lambda * math.log(max(apres[action], 1e-6)))
        for action, valeur, _ in actions
    ]
    return sorted(lignes, key=lambda x: -x[-1]), avant


# ---------------------------------------------------------------------------
# #17 : tables engendrées, plusieurs trahisons déclarées dans un même message.
# ---------------------------------------------------------------------------
def tables_engendrees(nombre, graine=17):
    """`nombre` cas tirés par un générateur à graine fixe : (entrée, antérieurs, sincere, betray).

    Entrée au format de #17 pour huit à vingt actions distinctes des trois
    unités : valeurs de 0 à 0,30 à 0,01 près, probabilités avant renfort tirées
    puis normalisées, lambda de 0,01 ou 0,1, classement et index comme le moteur
    et export_plans les font (classer, première action qui contient l'ordre).
    L'Angleterre tient une promesse sur chacune des trois unités ; le message
    les remplace toutes, labels compris, par un autre ordre joué par un candidat.
    """
    tirage = random.Random(graine)
    toutes = list(itertools.product(*ORDRES_LEGAUX.values()))
    for _ in range(nombre):
        actions = tirage.sample(toutes, tirage.randint(8, 20))
        poids = [tirage.random() ** 3 for _ in actions]
        table = [
            (action, round(0.3 * tirage.random(), 2), float("%.6g" % (p / sum(poids))))
            for action, p in zip(actions, poids)
        ]
        joues = [sorted({action[i] for action in actions}) for i in range(len(ORDRES_LEGAUX))]
        anciens, nouveaux = [], []
        for ordres in joues:
            if len(ordres) < 2:
                continue
            ancien, nouveau = tirage.sample(ordres, 2)
            anciens.append(ancien)
            nouveaux.append(nouveau)
        regularize_lambda = tirage.choice((0.01, 0.1))
        action_values, avant = classer(table, regularize_lambda, anciens)
        index = {}
        for action, valeur, _, _ in action_values:
            for ordre in action:
                index.setdefault(ordre, valeur)
        ecrit = entree(
            [], index,
            [{"orders": list(a), "value": v, "prob": avant[a]} for a, v, _, _ in action_values],
            dict(RECHERCHE, **{"lambda": regularize_lambda}),
        )
        yield ecrit, {"ENGLAND": anciens}, nouveaux, list(anciens)


def remplacements_hors_tete(cas, rejeter=None):
    """Sur les cas de tables_engendrees : (remplacements acceptés, dont hors tête, premier cas fautif).

    Hors tête : l'ordre accepté n'appartient pas à l'action que le moteur met en
    tête (engine_head_action) pour les promesses telles que le message les
    laisse -- les antérieures, moins les remplacées, plus les acceptées.
    `rejeter` : la fonction mesurée, par défaut _reject_contradictions du dépôt.
    """
    rejeter = bot._reject_contradictions if rejeter is None else rejeter
    acceptes = fautifs = 0
    premier = None
    with mock.patch.object(bot, "normalize_order_spacing", normalize_order_spacing):
        for ecrit, anterieurs, sincere, betray in cas:
            retour = rejeter(
                list(sincere), {d: list(o) for d, o in anterieurs.items()}, ecrit["plans"],
                betray=list(betray), order_values=ecrit["order_values"],
                candidates=ecrit["candidates"], search=ecrit["search"],
            )
            finales = {get_unit_location(o): o for ordres in anterieurs.values() for o in ordres}
            finales.update({get_unit_location(o): o for o in retour[0]})
            tete = pseudo_commitments.engine_head_action(
                ecrit["candidates"], ecrit["search"], list(finales.values())
            )
            for _destinataire, _ancien, nouveau, _gain in retour[2]:
                acceptes += 1
                if nouveau not in tete:
                    fautifs += 1
                    if premier is None:
                        premier = (ecrit, anterieurs, sincere, betray, retour, tete)
    return acceptes, fautifs, premier


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

    L'envoi passe par `site` (faux_site.FauxSite) : il réussit, sauf si
    `site.comportements` annonce autre chose pour les prochains envois.

    `entree_plans` est l'entrée de la France dans current_plans.json (lue par le
    vrai load_plans) : voir entree() et entree_ancienne().
    legal_commitments et engine_head_action sont les vraies fonctions, sur la
    position de FauxJeu.
    """

    def __init__(self, entree_plans=None):
        self.entree_plans = entree_plans
        self.jeu = FauxJeu()
        self.retours = []  # retours successifs de _reject_contradictions
        self.sincere = []
        self.betray = None  # label de trahison de la réponse ; None : champ absent
        self.reply = "entendu"
        self.appels_inconnus = []  # consignes d'appels à Claude que la doublure n'a pas reconnues
        self.consignes = []  # consigne système de chaque appel de réponse, dans l'ordre
        self.horloge = 1759400000
        self.etat = None
        self.site = faux_site.FauxSite()

    def __enter__(self):
        self.pile = contextlib.ExitStack()
        logs = Path(self.pile.enter_context(tempfile.TemporaryDirectory())) / "webdip_logs_test"
        logs.mkdir()
        self.fichier_etat = logs / "claude_dialogue_state.json"
        self.fichier_engagements = logs / "pseudo_commitments.json"
        self.fichier_plans = logs / "current_plans.json"
        if self.entree_plans is not None:
            # Le même plan pour les deux phases du banc.
            self.fichier_plans.write_text(json.dumps({str(PARTIE): {
                phase: {"FRANCE": self.entree_plans} for phase in (PHASE, PHASE_SUIVANTE)
            }}))

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
                self.consignes.append(consigne)
                reponse = {"reply": self.reply, "sincere": self.sincere}
                if self.betray is not None:
                    reponse["betray"] = self.betray
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
            "get_status_json": self.site.statut,
            "webdip_state_to_game": lambda status: self.jeu,
            "normalize_order_spacing": normalize_order_spacing,
            "legal_commitments": pseudo_commitments.legal_commitments,
            "load_plans": plan_export.load_plans,
            "post_req": mock.Mock(side_effect=self.site.post_req),
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

    def message(self, expediteur, sincere, betray=None, reply="entendu"):
        """`expediteur` écrit à la France, qui répond avec la liste `sincere` ; rend le journal.

        `betray` est le label de trahison de la réponse (#17), tel que Claude
        l'écrirait : None laisse le champ absent, toute autre valeur est rendue
        telle quelle (y compris mal formée). `reply` nul : la France se tait.

        Lève ErreurBanc si le cycle n'est pas allé au bout du traitement du
        message : run_cycle rattrape les exceptions de process_bot et ne les
        signale que dans son journal, et un cycle interrompu n'enregistre rien,
        ce qu'un test prendrait pour « rien n'est promis ». Lève InvariantRompu
        si pseudo_commitments.json porte ensuite deux ordres pour une unité.
        """
        self.recevoir(expediteur, sincere, betray, reply)
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
        if self.envoi.call_count != envois + (1 if reply else 0):
            defauts.append("post_req appelé %d fois" % (self.envoi.call_count - envois))
        repondus = (self.etat or {}).get("bot1:%d" % PARTIE, {}).get("replied_ts", [])
        if str(self.horloge) not in repondus:
            defauts.append("message absent de replied_ts")
        if defauts:
            raise ErreurBanc("cycle interrompu (%s) ; journal :\n%s" % (" ; ".join(defauts), journal))
        doubles = unites_en_double(self.engagements())
        if doubles:
            raise InvariantRompu(
                "pseudo_commitments.json : plus d'un ordre pour %s (%s)" % (doubles, self.engagements())
            )
        return journal

    def recevoir(self, expediteur, sincere, betray=None, reply="entendu"):
        """Dépose un message d'`expediteur` pour la France et règle la réponse de Claude, sans cycle."""
        self.horloge += 60
        self.jeu.messages[self.horloge] = {
            "sender": expediteur, "recipient": "FRANCE", "message": "bonjour",
            "phase": self.jeu.phase,
        }
        self.sincere = list(sincere)
        self.betray, self.reply = betray, reply

    def cycle(self):
        """Un cycle, sans rien exiger de son issue (envoi en échec, message laissé en attente) ; rend le journal.

        Ne lève que si le cycle a été interrompu par autre chose qu'un envoi.
        """
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.etat = bot.run_cycle(self.etat)
        journal = sortie.getvalue()
        defauts = [m for m in ("unexpected error", "[silent]", "generation failed") if m in journal]
        if self.appels_inconnus:
            defauts.append("appel à Claude non reconnu : %r" % self.appels_inconnus)
        if defauts:
            raise ErreurBanc("cycle interrompu (%s) ; journal :\n%s" % (" ; ".join(defauts), journal))
        return journal

    def repondus(self):
        """replied_ts tel qu'il est écrit sur disque."""
        return self.etat_du_bot()["replied_ts"]

    def cycle_sans_message(self):
        """Un cycle où la France n'a rien à lire (résolution des promesses) ; rend le journal."""
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.etat = bot.run_cycle(self.etat)
        journal = sortie.getvalue()
        defauts = [m for m in ("unexpected error", "[silent]", "failed") if m in journal]
        if defauts:
            raise ErreurBanc("cycle interrompu (%s) ; journal :\n%s" % (" ; ".join(defauts), journal))
        return journal

    def recharger(self):
        """Oublie l'état en mémoire : le cycle suivant repart du fichier, comme après un redémarrage."""
        self.etat = None

    def etat_du_bot(self):
        """État de bot1 dans la partie, tel qu'il est écrit sur disque."""
        return json.loads(self.fichier_etat.read_text())["bot1:%d" % PARTIE]

    def by_recipient(self):
        """by_recipient tel qu'il est écrit sur disque."""
        return self.etat_du_bot()["sincere_by_recipient"]["by_recipient"]

    def promesses_du_bot(self):
        """own_promises tel qu'il est écrit sur disque ({} si la clé manque)."""
        return self.etat_du_bot().get("own_promises", {})

    def engagements(self):
        """Engagements de la France pour la phase courante dans pseudo_commitments.json ([] si rien n'est écrit)."""
        if not self.fichier_engagements.exists():
            return []
        donnees = json.loads(self.fichier_engagements.read_text())
        return donnees.get(str(PARTIE), {}).get(self.jeu.phase, {}).get("FRANCE", [])


def entree(plans_exportes, order_values=None, candidates=None, search=None):
    """Entrée de current_plans.json au format complet de #17.

    `order_values` : celui qui est donné, sinon la valeur du premier plan qui
    contient chaque ordre. `candidates` et `search` : ceux qui sont donnés, sinon
    la table du banc (candidats_du_banc) et RECHERCHE.
    """
    if candidates is None:
        candidates = candidats_du_banc(plans_exportes, order_values)
    if order_values is None:
        order_values = {}
        for plan in plans_exportes:
            for ordre in plan["orders"]:
                order_values.setdefault(ordre, plan["value"])
    return {
        "computed_at": 0, "plans": plans_exportes, "order_values": order_values,
        "candidates": candidates, "search": RECHERCHE if search is None else search,
    }


def entree_ancienne(plans_exportes, order_values=None):
    """Entrée écrite avant #17 : ni `candidates` ni `search` ; l'index s'il est donné."""
    donnees = {"computed_at": 0, "plans": plans_exportes}
    if order_values is not None:
        donnees["order_values"] = order_values
    return donnees


def trahison(entree_plans, premier, second, betray=None):
    """La France promet `premier` à l'Angleterre puis `second` à l'Allemagne.

    `betray` est le label du second message. Rend (retour de
    _reject_contradictions au second message, by_recipient, engagements).
    """
    with Banc(entree_plans) as banc:
        banc.message("ENGLAND", [premier])
        banc.message("GERMANY", [second], betray)
        return banc.retours[-1], banc.by_recipient(), banc.engagements()


# Balises du journal comptées par les tests et par la mesure.
BALISES = (
    "[double-deal]", "[betrayal]", "[revision]", "[betrayal-refused]", "[betrayal-ignored]",
    "[send-uncertain]", "[send-pending]", "[send-retry]", "[send-confirmed]", "[send-muted]", "[send-failed]",
)


def balises(journal):
    """Nombre de lignes du journal portant chaque balise (les balises absentes sont omises)."""
    lignes = journal.splitlines()
    comptes = {b: sum(1 for l in lignes if b in l) for b in BALISES}
    return {b: n for b, n in comptes.items() if n}
