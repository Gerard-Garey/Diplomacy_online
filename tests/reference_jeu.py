#!/usr/bin/env python3
"""Jeu d'essai figé de la référence de non-régression (issue #31, ADR 0006) : format, réducteur, contrôle.

Bibliothèque standard seule, ni amont/ ni conteneur. Trois usages :

    python3 tests/reference_jeu.py controler [--dossier D] [--racine R]
    python3 tests/reference_jeu.py reduire --historique H.json --vers D --partie N --creee-le DATE \\
        --sha SHA --image ETIQUETTE --commande "..." RELEVES.jsonl [RELEVES.jsonl ...]
    python3 tests/reference_jeu.py manifeste --dossier D

`controler` est appelé par tests/verifier.sh (ADR 0006, décision 3) ; il passe sur un
dossier absent ou vide. `reduire` transforme des relevés de tests/mesure/rejeu_moteur.py
(bruts, hors git) en jeu d'essai : seule la session principale le lance vers
tests/reference/, après visa (ADR 0006, décision 6). `manifeste` refait la liste des
fichiers et les tailles d'un jeu dont les fichiers ont changé (attendus régénérés).

Format (ADR 0006, décision 2), un dossier :

    manifeste.json          partie source, phases, puissances, capture, taille, fichiers
    historique.json         {"phases": [{"name": "S1901M", "orders": {"AUSTRIA": [ordres]}}]}
    tables/<PHASE>.json     {"phase": "S1901M", "tables": {"AUSTRIA": <table>}}
    attendus/<PHASE>.json   {"phase": "S1901M", "attendus": {"AUSTRIA": {"D2": ...}}}

<table> : les quatre clés que plan_export écrit et que le bot de dialogue lit,
`plans` (rank, orders, value, cost_vs_best), `order_values`, `candidates` (orders,
value, prob), `search` (lambda, boost, max_prob) ; plus, quand ils ont été relevés,
les arguments bruts d'export_plans sous `export_plans` : `action_values` (value,
prob, score, et `orders` quand ce ne sont pas ceux du candidat de même rang),
`prior_policy` (prob, et `action` -- le rang de l'action dans `action_values` -- ou
`orders` si elle n'y est pas), `regularize_lambda`, `boost`,
`max_prob`. Les attendus sont ceux de tests/reference_couche_d.py.

Ce qu'un relevé contient en plus n'entre pas : `computed_at`, `gpu`, `duree_s`,
`journal`, `statut`, `game_id`, texte de message. Le réducteur ne recopie que les
clés nommées ci-dessus, et le contrôle refuse toute autre clé.
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # ni __pycache__ dans tests/ (#27)

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "tests" / "reference"
EMPLACEMENT = "tests/reference"  # seul dossier admis, relatif à la racine du dépôt
MANIFESTE, HISTORIQUE, TABLES, ATTENDUS = "manifeste.json", "historique.json", "tables", "attendus"
FORMAT = 1
NATURE = "100 % bots"
PLAFOND_OCTETS = 512 * 1024  # ADR 0006, décision 3 : le dépasser demande une annotation de l'ADR
# Mesuré sur les relevés m1_3_* (30 recherches) : l'ordre le plus long y fait 22 caractères.
# 24 est la borne de l'ADR 0006 (« moins de 24 caractères »).
LONGUEUR_ORDRE_MAX = 24

POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]
# Lieux de la carte : VALID_LOC_STRS de dipcc/dipcc/cc/loc.cc, dans l'amont Cicero au commit
# épinglé par versions.env (75 provinces et 6 côtes nommées), recopiés ici parce que la batterie
# tourne sans amont/. tests/test_reference.py compare cette copie au fichier d'amont quand il est là.
LIEUX = frozenset((
    "YOR EDI LON LVP NTH WAL CLY NWG ENG IRI NAO BEL DEN HEL HOL NWY SKA BAR BRE MAO PIC BUR RUH "
    "BAL KIE SWE FIN STP STP/NC GAS PAR NAF POR SPA SPA/NC SPA/SC WES MAR MUN BER BOT LVN PRU "
    "STP/SC MOS TUN LYO TYS PIE BOH SIL TYR WAR SEV UKR ION TUS NAP ROM VEN GAL VIE TRI ARM BLA "
    "RUM ADR AEG ALB APU EAS GRE BUD SER ANK SMY SYR BUL BUL/EC CON BUL/SC"
).split())
# Toujours par fullmatch : « $ » accepterait un saut de ligne final. [0-9] : « \d » accepte tout chiffre Unicode.
ORDRE = re.compile(
    r"[AF] (\S+) (?:H|B|D|R (\S+)|- (\S+)(?: VIA)?|S [AF] (\S+)(?: - (\S+))?|C [AF] (\S+) - (\S+))"
)
PHASE = re.compile(r"[SFW](?:19|20)[0-9]{2}[MRA]")
EMPREINTE = re.compile(r"[0-9a-f]{16}")
COUT = re.compile(r"free|[0-9]+\.[0-9]{3}")
PONCTUATION = re.compile(r"[.,;:!?'\"()\[\]{}<>]")
# Valeurs du manifeste, le seul fichier où une date et un numéro de partie apparaissent.
DATE = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}")
SHA = re.compile(r"[0-9a-f]{40}(?:-modifie)?")  # « -modifie » : attendus générés sur un arbre de travail modifié
SHA256 = re.compile(r"[0-9a-f]{64}")
IMAGE = re.compile(r"[A-Za-z0-9_.:/@-]{1,100}")
LONGUEUR_COMMANDE_MAX = 400
ENTIER_MAX = 2 ** 53  # au-delà, un entier JSON n'est plus un nombre que le format connaît

CLES_TABLE = ("plans", "order_values", "candidates", "search")
CLES_PLAN = ("rank", "orders", "value", "cost_vs_best")
CLES_CANDIDAT = ("orders", "value", "prob")
CLES_RECHERCHE = ("lambda", "boost", "max_prob")
CLES_ARGUMENTS = ("action_values", "prior_policy", "regularize_lambda", "boost", "max_prob")
# Ce que l'ADR exclut par construction : nommé ici pour que le refus le dise.
CLES_EXCLUES = (
    "computed_at", "gpu", "duree_s", "journal", "statut", "game_id", "message", "message_declencheur",
    "engagements_du_fichier", "sender", "recipient", "reply",
)
# Verdicts de _reject_contradictions et balises du journal du bot (sans crochets), tels
# que tests/reference_couche_d.py les enregistre.
VOCABULAIRE = frozenset((
    "accepted", "superseded", "undeclared", "unknown_value", "below_margin", "not_played",
    "conflicting", "no_such_promise", "no_replacement", "restated",
))
BALISES = frozenset((
    "double-deal", "betrayal", "revision", "betrayal-refused", "betrayal-ignored", "filtered",
    "send-uncertain", "send-pending", "send-retry", "send-confirmed", "send-muted", "send-failed",
    "trust", "own-record",
))
# Clés des attendus de la couche D (liste blanche : l'étendre, c'est étendre le format).
CLES_ATTENDUS = frozenset((
    "D1r", "D2", "D3", "D4", "D5", "D6",
    "couts", "aucune", "prefere", "alternative", "deux", "absent",
    "promesses", "tete", "q_tete", "moment_q", "score_tete", "somme_scores",
    "label", "sans_label", "sans_table",
    "plan", "engagements", "engagements_sans_table", "consigne", "empreinte", "longueur",
    "ordres", "gains", "messages", "expediteur", "sincere", "betray", "balises", "retour",
    "cycle", "deux_detenteurs", "deux_trahisons",
    "by_recipient", "own_promises", "fichier",
    "recus", "propres", "resolue", "kept", "broken", "exemples", "lignes",
)) | VOCABULAIRE | BALISES
CLES_MANIFESTE = {
    "": ("format", "partie", "phases", "puissances", "capture", "taille_octets", "fichiers"),
    "partie": ("numero", "creee_le", "nature"),
    "capture": ("date", "sha_code", "image", "commande"),
    "attendus": ("date", "sha_code", "commande"),
    "fichiers": ("chemin", "octets", "sha256"),
}


class Refus(Exception):
    """Ce qu'on demande de réduire ou d'écrire n'est pas un jeu d'essai admissible."""


def _nombre(valeur):
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return False
    if isinstance(valeur, int):
        return abs(valeur) < ENTIER_MAX  # math.isfinite lève sur un entier de 400 chiffres
    return math.isfinite(valeur)


def _entier(valeur):
    return isinstance(valeur, int) and not isinstance(valeur, bool) and 0 <= valeur < ENTIER_MAX


def est_phase(valeur):
    return isinstance(valeur, str) and PHASE.fullmatch(valeur) is not None


def est_ordre(valeur):
    """Un ordre en notation du moteur, dont chaque lieu est un lieu de la carte."""
    if not isinstance(valeur, str) or len(valeur) > LONGUEUR_ORDRE_MAX:
        return False
    trouve = ORDRE.fullmatch(valeur)
    return trouve is not None and all(lieu in LIEUX for lieu in trouve.groups() if lieu is not None)


def _sans_doublon(paires):
    objet = {}
    for cle, valeur in paires:
        if cle in objet:
            raise ValueError("clé JSON en double : %r" % (cle[:40],))
        objet[cle] = valeur
    return objet


def charger_json(texte):
    """json.loads qui refuse une clé écrite deux fois dans un objet : la seconde masquerait la première au contrôle.

    Lève ValueError ; un JSON trop imbriqué pour être lu (RecursionError) en est une aussi.
    """
    try:
        return json.loads(texte, object_pairs_hook=_sans_doublon)
    except RecursionError:
        raise ValueError("JSON trop imbriqué")


def _ordre_des_phases(phase):
    return (int(phase[1:5]), "SFW".index(phase[0]))


# ---------------------------------------------------------------------------
# Lecture et écriture
# ---------------------------------------------------------------------------

def ecrire_json(chemin, donnees):
    """Une ligne, sans espace : la taille compte (plafond). Les flottants gardent leur écriture exacte."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(donnees, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def fichiers_du_jeu(dossier):
    """Chemins relatifs (avec des /) de tous les fichiers du dossier, triés ; [] s'il est absent.

    Les liens symboliques n'en sont pas : voir liens_du_jeu.
    """
    dossier = Path(dossier)
    if dossier.is_symlink() or not dossier.is_dir():
        return []
    return sorted(
        f.relative_to(dossier).as_posix() for f in dossier.rglob("*")
        if f.is_file() and not f.is_symlink() and not any(p.is_symlink() for p in _parents(dossier, f))
    )


def _parents(dossier, fichier):
    """Les dossiers entre `dossier` (exclu) et `fichier` (exclu)."""
    return [dossier / p for p in fichier.relative_to(dossier).parents if str(p) != "."]


def liens_du_jeu(dossier):
    """Liens symboliques du dossier (lui compris) : un jeu d'essai n'en contient pas."""
    dossier = Path(dossier)
    if dossier.is_symlink():
        return ["."]
    if not dossier.is_dir():
        return []
    return sorted(f.relative_to(dossier).as_posix() for f in dossier.rglob("*") if f.is_symlink())


def _fichiers_de_phase(presents, sous_dossier):
    """Phases des fichiers <sous_dossier>/<PHASE>.json présents, dans l'ordre de la partie."""
    phases = [
        f.split("/")[1][:-len(".json")] for f in presents
        if f.count("/") == 1 and f.startswith(sous_dossier + "/") and f.endswith(".json")
    ]
    return sorted((p for p in phases if est_phase(p)), key=_ordre_des_phases)


def lire_jeu(dossier):
    """Le jeu d'essai du dossier, ou None s'il est absent ou vide.

    Rend {"manifeste", "historique", "tables": {phase: {puissance: table}},
    "attendus": {phase: {puissance: attendus}}}. Les tables et les attendus sont
    ceux des fichiers présents, phases dans l'ordre de la partie : le manifeste ne
    choisit pas ce qui est comparé (un manifeste raccourci ne retire rien à la
    couche D). Ne contrôle rien : voir controler().
    """
    dossier = Path(dossier)
    presents = fichiers_du_jeu(dossier)
    if not presents:
        return None
    jeu = {
        "manifeste": charger_json((dossier / MANIFESTE).read_text(encoding="utf-8")),
        "historique": charger_json((dossier / HISTORIQUE).read_text(encoding="utf-8")),
        "tables": {}, "attendus": {},
    }
    for nom, cle in ((TABLES, "tables"), (ATTENDUS, "attendus")):
        for phase in _fichiers_de_phase(presents, nom):
            contenu = charger_json((dossier / nom / (phase + ".json")).read_text(encoding="utf-8"))[cle]
            jeu[cle][phase] = {p: contenu[p] for p in POWERS if p in contenu}
    return jeu


def ecrire_manifeste(dossier, manifeste):
    """Écrit le manifeste après y avoir refait la liste des fichiers, leurs tailles et leurs empreintes."""
    dossier = Path(dossier)
    fichiers = []
    for relatif in fichiers_du_jeu(dossier):
        if relatif == MANIFESTE:
            continue
        octets = (dossier / relatif).read_bytes()
        fichiers.append({"chemin": relatif, "octets": len(octets), "sha256": hashlib.sha256(octets).hexdigest()})
    manifeste = dict(manifeste, fichiers=fichiers, taille_octets=sum(f["octets"] for f in fichiers))
    (dossier / MANIFESTE).write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return manifeste


# ---------------------------------------------------------------------------
# Réducteur : d'un relevé de rejeu_moteur.py à une table du jeu
# ---------------------------------------------------------------------------

def _garder(objet, cles, quoi):
    if not isinstance(objet, dict):
        raise Refus("%s : objet attendu, %s trouvé" % (quoi, type(objet).__name__))
    manquantes = [c for c in cles if c not in objet]
    if manquantes:
        raise Refus("%s : clé(s) absente(s) %s" % (quoi, manquantes))
    return {c: objet[c] for c in cles}


def reduire_table(entree):
    """Les quatre clés d'une entrée de current_plans.json, et rien d'autre (ni `computed_at`)."""
    table = _garder(entree, CLES_TABLE, "entrée exportée")
    return {
        "plans": [_garder(p, CLES_PLAN, "plan") for p in table["plans"]],
        "order_values": dict(table["order_values"]),
        "candidates": [_garder(c, CLES_CANDIDAT, "candidat") for c in table["candidates"]],
        "search": _garder(table["search"], CLES_RECHERCHE, "search"),
    }


def reduire_arguments(arguments, candidats=()):
    """Arguments bruts d'export_plans, tels que rejeu_moteur.py les relève (`arguments_export`).

    Relevé : `action_values` [[ordres, valeur, probabilité, score]], `prior_policy`
    [[ordres, probabilité]] et les trois paramètres. Rendu : le bloc `export_plans`
    d'une table, où une action n'est pas écrite deux fois (la taille compte) : une
    action d'`action_values` est écrite sans ses ordres quand ce sont ceux du
    candidat de même rang de la table (`candidats`), et une action de
    `prior_policy` est désignée par son rang dans `action_values` quand elle s'y trouve.
    """
    brut = _garder(arguments, CLES_ARGUMENTS, "arguments d'export_plans")
    for cle in CLES_ARGUMENTS:
        if brut[cle] is None:  # export sans politique d'avant renfort ou sans paramètre : pas de quoi le rejouer
            raise Refus("arguments d'export_plans : %s est nul" % cle)
    actions, rang = [], {}
    for i, (ordres, valeur, prob, score) in enumerate(brut["action_values"]):
        action = {"value": valeur, "prob": prob, "score": score}
        if i >= len(candidats) or list(candidats[i]["orders"]) != list(ordres):
            action["orders"] = list(ordres)
        actions.append(action)
        rang[tuple(ordres)] = i
    avant = []
    for ordres, prob in brut["prior_policy"]:
        if tuple(ordres) in rang:
            avant.append({"action": rang[tuple(ordres)], "prob": prob})
        else:
            avant.append({"orders": list(ordres), "prob": prob})
    return {
        "action_values": actions, "prior_policy": avant,
        "regularize_lambda": brut["regularize_lambda"], "boost": brut["boost"], "max_prob": brut["max_prob"],
    }


def reduire_releve(ligne, recherche="A", tirage=0, a_sec=False):
    """(phase, puissance, table) pour une ligne de relevé, ou (None, None, raison) si elle n'est pas retenue.

    Retenue : la recherche `recherche` du tirage `tirage` (par défaut la recherche A,
    sans engagement, du premier tirage). Un relevé d'essai à sec (table de la
    doublure) est refusé, sauf `a_sec`. Lève Refus si l'entrée exportée manque ou
    n'a pas ses quatre clés : une table réduite ne se devine pas.
    """
    if "comparaison" in ligne:
        return None, None, "ligne de comparaison (mode incrémental)"
    if ligne.get("recherche") != recherche or ligne.get("tirage") != tirage:
        return None, None, "recherche %s, tirage %s" % (ligne.get("recherche"), ligne.get("tirage"))
    if ligne.get("a_sec") and not a_sec:
        raise Refus("relevé d'essai à sec (doublure du moteur) : ce n'est pas une table réelle")
    table = reduire_table(ligne.get("entree"))
    if ligne.get("arguments_export") is not None:
        table["export_plans"] = reduire_arguments(ligne["arguments_export"], table["candidates"])
    return ligne["phase"], ligne["puissance"], table


def reduire_historique(historique):
    """{"phases": [{"name", "orders": {puissance: [ordres]}}]}, et rien d'autre de la partie."""
    phases = []
    for phase in _garder(historique, ("phases",), "historique")["phases"]:
        phase = _garder(phase, ("name", "orders"), "phase de l'historique")
        phases.append({
            "name": phase["name"],
            "orders": {p: list(phase["orders"][p]) for p in POWERS if phase["orders"].get(p)},
        })
    return {"phases": phases}


def construire_jeu(dossier, historique, tables, manifeste):
    """Écrit un jeu d'essai dans `dossier` (vide ou absent) ; rend le manifeste écrit.

    `tables` : {phase: {puissance: table}}, déjà réduites. `manifeste` : les clés
    `partie` et `capture` ; phases, puissances, tailles et fichiers sont calculés.
    Lève Refus si le résultat ne passe pas controler() : rien d'inadmissible n'est
    laissé sans le dire (les fichiers écrits restent, pour être lus).
    """
    dossier = Path(dossier)
    if fichiers_du_jeu(dossier):
        raise Refus("%s n'est pas vide : un jeu d'essai ne s'écrit pas par-dessus un autre" % dossier)
    ecrire_json(dossier / HISTORIQUE, reduire_historique(historique))
    phases = sorted(tables, key=_ordre_des_phases)
    for phase in phases:
        contenu = {p: tables[phase][p] for p in POWERS if p in tables[phase]}
        ecrire_json(dossier / TABLES / (phase + ".json"), {"phase": phase, "tables": contenu})
    ecrit = ecrire_manifeste(dossier, dict(
        manifeste, format=FORMAT, phases=phases,
        puissances=[p for p in POWERS if any(p in tables[phase] for phase in phases)],
    ))
    violations = controler(dossier)
    if violations:
        raise Refus("jeu d'essai refusé par le contrôle :\n  " + "\n  ".join(violations))
    return ecrit


# ---------------------------------------------------------------------------
# Contrôle (ADR 0006, décision 3)
# ---------------------------------------------------------------------------

class _Controle:
    def __init__(self, fichier):
        self.fichier, self.violations = fichier, []

    def ko(self, chemin, message):
        self.violations.append("%s : %s : %s" % (self.fichier, chemin or "(racine)", message))

    def objet(self, valeur, chemin, cles, facultatives=()):
        """Vrai si `valeur` est un objet dont toutes les clés sont admises ; signale le reste."""
        if not isinstance(valeur, dict):
            self.ko(chemin, "objet attendu")
            return False
        for cle in valeur:
            if cle not in cles and cle not in facultatives:
                exclue = " (exclue par l'ADR 0006)" if cle in CLES_EXCLUES else ""
                self.ko(chemin, "clé hors liste blanche : %r%s" % (cle[:40], exclue))
        for cle in cles:
            if cle not in valeur:
                self.ko(chemin, "clé absente : %r" % cle)
        return all(cle in valeur for cle in cles)

    def liste(self, valeur, chemin):
        if not isinstance(valeur, list):
            self.ko(chemin, "liste attendue")
            return []
        return list(enumerate(valeur))

    def nombre(self, valeur, chemin):
        if not _nombre(valeur):
            self.ko(chemin, "nombre fini attendu")

    def motif(self, valeur, chemin, motif, quoi):
        """Une valeur du manifeste : une chaîne de la forme attendue, jamais un objet ni une liste."""
        if not isinstance(valeur, str) or motif.fullmatch(valeur) is None:
            self.ko(chemin, "%s attendu : %s" % (quoi, _apercu(valeur)))

    def entier(self, valeur, chemin):
        if not _entier(valeur):
            self.ko(chemin, "entier positif attendu : %s" % _apercu(valeur))

    def chaine(self, valeur, chemin, admis):
        """Une chaîne hors manifeste est un ordre, une puissance, une phase ou un mot du vocabulaire."""
        if not isinstance(valeur, str):
            self.ko(chemin, "chaîne attendue")
        elif len(valeur) > LONGUEUR_ORDRE_MAX:
            self.ko(chemin, "chaîne de %d caractères (plus de %d : pas un ordre) : %r…"
                    % (len(valeur), LONGUEUR_ORDRE_MAX, valeur[:20]))
        elif PONCTUATION.search(valeur) and not COUT.fullmatch(valeur):
            self.ko(chemin, "ponctuation de phrase dans une chaîne : %r" % valeur)
        elif not any(test(valeur) for test in admis):
            self.ko(chemin, "chaîne qui n'est pas %s : %r" % (admis[0].__doc__, valeur))

    def ordres(self, valeur, chemin):
        for i, ordre in self.liste(valeur, chemin):
            self.chaine(ordre, "%s[%d]" % (chemin, i), (_est_ordre,))


def _apercu(valeur):
    return repr(valeur)[:40] if isinstance(valeur, str) else type(valeur).__name__


def _est_ordre(valeur):
    """un ordre en notation du moteur"""
    return est_ordre(valeur)


def _est_puissance(valeur):
    """une puissance"""
    return valeur in POWERS


def _est_phase(valeur):
    """une phase"""
    return est_phase(valeur)


def _est_mot(valeur):
    """un mot du vocabulaire des attendus"""
    return valeur in VOCABULAIRE or valeur in BALISES or bool(EMPREINTE.fullmatch(valeur)) or bool(COUT.fullmatch(valeur))


def _controler_historique(c, donnees):
    if not c.objet(donnees, "", ("phases",)):
        return
    for i, phase in c.liste(donnees["phases"], "phases"):
        chemin = "phases[%d]" % i
        if not c.objet(phase, chemin, ("name", "orders")):
            continue
        c.chaine(phase["name"], chemin + ".name", (_est_phase,))
        if not isinstance(phase["orders"], dict):
            c.ko(chemin + ".orders", "objet attendu")
            continue
        for puissance, ordres in phase["orders"].items():
            c.chaine(puissance, chemin + ".orders (clé)", (_est_puissance,))
            c.ordres(ordres, "%s.orders.%s" % (chemin, puissance[:12]))


def _controler_actions(c, valeur, chemin, cles, nombres):
    for i, action in c.liste(valeur, chemin):
        ici = "%s[%d]" % (chemin, i)
        if c.objet(action, ici, cles):
            c.ordres(action["orders"], ici + ".orders")
            for cle in nombres:
                c.nombre(action[cle], "%s.%s" % (ici, cle))


def _controler_table(c, table, chemin):
    if not c.objet(table, chemin, CLES_TABLE, ("export_plans",)):
        return
    for i, plan in c.liste(table["plans"], chemin + ".plans"):
        ici = "%s.plans[%d]" % (chemin, i)
        if c.objet(plan, ici, CLES_PLAN):
            c.ordres(plan["orders"], ici + ".orders")
            for cle in ("rank", "value", "cost_vs_best"):
                c.nombre(plan[cle], "%s.%s" % (ici, cle))
    if isinstance(table["order_values"], dict):
        for ordre, valeur in table["order_values"].items():
            c.chaine(ordre, chemin + ".order_values (clé)", (_est_ordre,))
            c.nombre(valeur, "%s.order_values.%s" % (chemin, ordre[:LONGUEUR_ORDRE_MAX]))
    else:
        c.ko(chemin + ".order_values", "objet attendu")
    _controler_actions(c, table["candidates"], chemin + ".candidates", CLES_CANDIDAT, ("value", "prob"))
    if c.objet(table["search"], chemin + ".search", CLES_RECHERCHE):
        for cle in CLES_RECHERCHE:
            c.nombre(table["search"][cle], "%s.search.%s" % (chemin, cle))
    if "export_plans" in table:
        ici = chemin + ".export_plans"
        arguments = table["export_plans"]
        if not c.objet(arguments, ici, CLES_ARGUMENTS):
            return
        for i, action in c.liste(arguments["action_values"], ici + ".action_values"):
            la = "%s.action_values[%d]" % (ici, i)
            if c.objet(action, la, ("value", "prob", "score"), ("orders",)):
                if "orders" in action:
                    c.ordres(action["orders"], la + ".orders")
                for cle in ("value", "prob", "score"):
                    c.nombre(action[cle], "%s.%s" % (la, cle))
        for i, ligne in c.liste(arguments["prior_policy"], ici + ".prior_policy"):
            la = "%s.prior_policy[%d]" % (ici, i)
            if isinstance(ligne, dict) and "orders" in ligne:
                if c.objet(ligne, la, ("orders", "prob")):
                    c.ordres(ligne["orders"], la + ".orders")
                    c.nombre(ligne["prob"], la + ".prob")
            elif c.objet(ligne, la, ("action", "prob")):
                c.nombre(ligne["action"], la + ".action")
                c.nombre(ligne["prob"], la + ".prob")
        for cle in ("regularize_lambda", "boost", "max_prob"):
            c.nombre(arguments[cle], "%s.%s" % (ici, cle))


def _controler_par_puissance(c, donnees, cle, nom_de_fichier, controle):
    if not c.objet(donnees, "", ("phase", cle)):
        return
    c.chaine(donnees["phase"], "phase", (_est_phase,))
    if donnees["phase"] != nom_de_fichier:
        c.ko("phase", "%r n'est pas la phase du nom de fichier" % (donnees["phase"],))
    if not isinstance(donnees[cle], dict):
        c.ko(cle, "objet attendu")
        return
    for puissance, contenu in donnees[cle].items():
        c.chaine(puissance, cle + " (clé)", (_est_puissance,))
        controle(c, contenu, "%s.%s" % (cle, puissance[:12]))


def _controler_attendus(c, valeur, chemin):
    """Attendus de la couche D : clés en liste blanche (ou ordre, puissance), valeurs sans texte."""
    if isinstance(valeur, dict):
        for cle, contenu in valeur.items():
            if cle not in CLES_ATTENDUS and not est_ordre(cle) and cle not in POWERS:
                exclue = " (exclue par l'ADR 0006)" if cle in CLES_EXCLUES else ""
                c.ko(chemin, "clé hors liste blanche : %r%s" % (cle[:40], exclue))
            _controler_attendus(c, contenu, "%s.%s" % (chemin, cle[:LONGUEUR_ORDRE_MAX]))
    elif isinstance(valeur, list):
        for i, contenu in enumerate(valeur):
            _controler_attendus(c, contenu, "%s[%d]" % (chemin, i))
    elif isinstance(valeur, str):
        c.chaine(valeur, chemin, (_est_mot, _est_ordre, _est_puissance, _est_phase))
    elif valeur is not None and not isinstance(valeur, bool):
        c.nombre(valeur, chemin)


def _controler_manifeste(c, manifeste, dossier, presents, tables):
    """Le manifeste : clés nommées, chaque valeur typée, et fidèle au dossier.

    `tables` : {phase: clés de l'objet `tables` du fichier} pour les fichiers de
    tables lus. Les phases du manifeste sont exactement celles des fichiers de
    tables/ (celles d'attendus/ en font partie), ses puissances l'union de celles
    des tables : un manifeste raccourci ne peut pas soustraire une table à la couche D.
    """
    if not c.objet(manifeste, "", CLES_MANIFESTE[""], ("attendus",)):
        return
    if manifeste["format"] != FORMAT or isinstance(manifeste["format"], bool):
        c.ko("format", "%d attendu" % FORMAT)
    partie, capture = manifeste["partie"], manifeste["capture"]
    if c.objet(partie, "partie", CLES_MANIFESTE["partie"]):
        c.entier(partie["numero"], "partie.numero")
        c.motif(partie["creee_le"], "partie.creee_le", DATE, "date AAAA-MM-JJ")
        if partie["nature"] != NATURE:
            c.ko("partie.nature", "%r attendu : seule une partie 100 %% bots est admise" % NATURE)
    for cle, bloc in (("capture", capture), ("attendus", manifeste.get("attendus"))):
        if cle == "attendus" and "attendus" not in manifeste:
            continue
        if not c.objet(bloc, cle, CLES_MANIFESTE[cle]):
            continue
        c.motif(bloc["date"], cle + ".date", DATE, "date AAAA-MM-JJ")
        c.motif(bloc["sha_code"], cle + ".sha_code", SHA, "SHA complet (40 chiffres hexadécimaux)")
        if "image" in CLES_MANIFESTE[cle]:
            c.motif(bloc["image"], cle + ".image", IMAGE, "identifiant d'image (100 caractères au plus, sans espace)")
        commande = bloc["commande"]
        if not isinstance(commande, str) or not 0 < len(commande) <= LONGUEUR_COMMANDE_MAX or not commande.isprintable():
            c.ko(cle + ".commande", "commande sur une ligne de %d caractères au plus attendue : %s"
                 % (LONGUEUR_COMMANDE_MAX, _apercu(commande)))
    for cle, test in (("phases", _est_phase), ("puissances", _est_puissance)):
        for i, valeur in c.liste(manifeste[cle], cle):
            c.chaine(valeur, "%s[%d]" % (cle, i), (test,))
    des_fichiers = _fichiers_de_phase(presents, TABLES)
    if manifeste["phases"] != des_fichiers:
        c.ko("phases", "ne sont pas exactement celles des fichiers de %s/ (%s)" % (TABLES, " ".join(des_fichiers) or "aucun"))
    en_trop = [p for p in _fichiers_de_phase(presents, ATTENDUS) if p not in des_fichiers]
    if en_trop:
        c.ko("phases", "attendus sans table pour %s" % " ".join(en_trop))
    des_tables = [p for p in POWERS if any(p in cles for cles in tables.values())]
    if manifeste["puissances"] != des_tables:
        c.ko("puissances", "ne sont pas exactement celles des tables (%s)" % (" ".join(des_tables) or "aucune"))
    c.entier(manifeste["taille_octets"], "taille_octets")
    listes = {}
    for i, fichier in c.liste(manifeste["fichiers"], "fichiers"):
        ici = "fichiers[%d]" % i
        if not c.objet(fichier, ici, CLES_MANIFESTE["fichiers"]):
            continue
        c.entier(fichier["octets"], ici + ".octets")
        c.motif(fichier["sha256"], ici + ".sha256", SHA256, "SHA-256")
        if not isinstance(fichier["chemin"], str) or len(fichier["chemin"]) > 40:
            c.ko(ici + ".chemin", "chemin relatif attendu : %s" % _apercu(fichier["chemin"]))
        elif fichier["chemin"] in listes:
            c.ko(ici + ".chemin", "%s est listé deux fois" % fichier["chemin"])
        else:
            listes[fichier["chemin"]] = fichier
    for relatif in sorted(set(presents) - set(listes) - {MANIFESTE}):
        c.ko("fichiers", "%s est dans le dossier mais pas dans le manifeste" % relatif)
    for relatif in sorted(set(listes) - set(presents)):
        c.ko("fichiers", "%s est dans le manifeste mais pas dans le dossier" % relatif)
    for relatif in sorted(set(listes) & set(presents)):
        octets = (dossier / relatif).read_bytes()
        if listes[relatif]["octets"] != len(octets) or listes[relatif]["sha256"] != hashlib.sha256(octets).hexdigest():
            c.ko("fichiers", "%s ne correspond plus au manifeste (taille ou empreinte) : "
                 "refaire le manifeste, par la session principale après visa" % relatif)
    if manifeste["taille_octets"] != sum(f["octets"] for f in listes.values() if _entier(f["octets"])):
        c.ko("taille_octets", "n'est pas la somme des tailles des fichiers listés")


def controler(dossier=DOSSIER):
    """Violations de l'ADR 0006 (décision 3) dans le dossier du jeu d'essai ; [] s'il est absent, vide ou conforme.

    Liste blanche des clés (toute clé JSON est nommée par le format, ou est un ordre,
    une puissance), aucune chaîne hors manifeste plus longue qu'un ordre ni qui
    porte une ponctuation de phrase -- et, plus strictement, aucune qui ne soit un
    ordre, une puissance, une phase ou un mot du vocabulaire --, plafond de taille,
    manifeste fidèle au dossier, aucun fichier d'un autre type.
    """
    dossier = Path(dossier)
    presents = fichiers_du_jeu(dossier)
    violations = [
        "%s : %s : lien symbolique (un jeu d'essai n'en contient pas : ce qu'il désigne échappe au contrôle)"
        % (dossier.name, lien) for lien in liens_du_jeu(dossier)
    ]
    if not presents:
        return violations
    tables, manifeste = {}, None
    taille = sum((dossier / f).stat().st_size for f in presents)
    if taille > PLAFOND_OCTETS:
        violations.append("%s : %d octets, plafond %d (512 Kio ; ADR 0006, décision 3)" % (dossier.name, taille, PLAFOND_OCTETS))
    for relatif in presents:
        c = _Controle(relatif)
        parties = relatif.split("/")
        phase = parties[-1][:-len(".json")] if relatif.endswith(".json") else ""
        connu = relatif in (MANIFESTE, HISTORIQUE) or (
            len(parties) == 2 and parties[0] in (TABLES, ATTENDUS) and est_phase(phase)
        )
        if not connu:
            c.ko("", "fichier qui n'est pas du format du jeu d'essai (manifeste.json, historique.json, "
                     "tables/<PHASE>.json, attendus/<PHASE>.json)")
            violations.extend(c.violations)
            continue
        try:
            donnees = charger_json((dossier / relatif).read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            c.ko("", "JSON illisible (%s : %s)" % (type(e).__name__, str(e)[:80]))
            violations.extend(c.violations)
            continue
        try:
            if relatif == MANIFESTE:
                manifeste = (c, donnees)  # jugé en dernier : il se compare aux tables lues
            elif relatif == HISTORIQUE:
                _controler_historique(c, donnees)
            elif parties[0] == TABLES:
                _controler_par_puissance(c, donnees, "tables", phase, _controler_table)
                if isinstance(donnees, dict) and isinstance(donnees.get("tables"), dict):
                    tables[phase] = set(donnees["tables"])
            else:
                _controler_par_puissance(c, donnees, "attendus", phase, _controler_attendus)
        except (RecursionError, TypeError, AttributeError, KeyError, IndexError, OverflowError) as e:
            # Une forme que le contrôle n'a pas prévue est une violation, jamais une trace.
            c.ko("", "forme inattendue (%s)" % type(e).__name__)
        violations.extend(c.violations)
    if manifeste is not None:
        c, donnees = manifeste
        try:
            _controler_manifeste(c, donnees, dossier, presents, tables)
        except (RecursionError, TypeError, AttributeError, KeyError, IndexError, OverflowError) as e:
            c.ko("", "forme inattendue (%s)" % type(e).__name__)
        violations.extend(c.violations)
    if MANIFESTE not in presents:
        violations.append("%s : manifeste absent (%s)" % (dossier.name, MANIFESTE))
    if HISTORIQUE not in presents:
        violations.append("%s : historique des ordres absent (%s)" % (dossier.name, HISTORIQUE))
    return violations


def _cles(valeur, trouvees):
    if isinstance(valeur, dict):
        trouvees.update(valeur)
        for contenu in valeur.values():
            _cles(contenu, trouvees)
    elif isinstance(valeur, list):
        for contenu in valeur:
            _cles(contenu, trouvees)


def porte_une_table(chemin):
    """Vrai si un fichier .json ou .jsonl porte ensemble les quatre clés d'une table de recherche.

    Fichier illisible comme JSON : jugé sur son texte (les quatre noms entre guillemets).
    """
    texte = Path(chemin).read_text(encoding="utf-8", errors="replace")
    trouvees = set()
    try:
        for bloc in (texte.splitlines() if str(chemin).endswith(".jsonl") else [texte]):
            if bloc.strip():
                _cles(json.loads(bloc), trouvees)
    except (ValueError, RecursionError):
        trouvees = {cle for cle in CLES_TABLE if '"%s"' % cle in texte}
    return all(cle in trouvees for cle in CLES_TABLE)


def fichiers_du_depot(racine):
    """Fichiers versionnés ou à versionner (non ignorés) du dépôt, relatifs à sa racine."""
    sortie = subprocess.run(
        ["git", "-C", str(racine), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return [f for f in sortie.stdout.decode("utf-8", "replace").split("\0") if f]


def controler_emplacement(racine=RACINE, fichiers=None):
    """Emplacement unique : aucun .json ni .jsonl hors de tests/reference/ ne porte une table de recherche."""
    racine = Path(racine)
    fichiers = fichiers_du_depot(racine) if fichiers is None else fichiers
    violations = []
    for relatif in sorted(fichiers):
        if not relatif.endswith((".json", ".jsonl")) or relatif.startswith(EMPLACEMENT + "/"):
            continue
        if (racine / relatif).is_file() and porte_une_table(racine / relatif):
            violations.append(
                "%s : porte les clés %s d'une table de recherche hors de %s/ (emplacement unique, ADR 0006)"
                % (relatif, ", ".join(CLES_TABLE), EMPLACEMENT)
            )
    return violations


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def _lire_releves(chemins):
    for chemin in chemins:
        for numero, ligne in enumerate(Path(chemin).read_text(encoding="utf-8").splitlines(), 1):
            if ligne.strip():
                yield "%s:%d" % (Path(chemin).name, numero), json.loads(ligne)


def reduire_fichiers(chemins, recherche="A", tirage=0, a_sec=False):
    """{phase: {puissance: table}} des relevés donnés ; le premier relevé retenu d'une position l'emporte.

    Rend aussi les lignes écartées parce que la position avait déjà sa table.
    """
    tables, doublons = {}, []
    for origine, ligne in _lire_releves(sorted(str(c) for c in chemins)):
        try:
            phase, puissance, table = reduire_releve(ligne, recherche, tirage, a_sec)
        except Refus as e:
            raise Refus("%s : %s" % (origine, e))
        if phase is None:
            continue
        if puissance in tables.setdefault(phase, {}):
            doublons.append("%s (%s %s)" % (origine, phase, puissance))
            continue
        tables[phase][puissance] = table
    return tables, doublons


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commandes = p.add_subparsers(dest="action")  # pas « commande » : c'est une option de `reduire`
    c = commandes.add_parser("controler", help="contrôle du jeu d'essai et de l'emplacement unique (tests/verifier.sh)")
    c.add_argument("--dossier", default=str(DOSSIER))
    c.add_argument("--racine", default=str(RACINE), help="dépôt où chercher une table hors de tests/reference/")
    c.add_argument("--sans-emplacement", action="store_true", help="ne contrôle que le dossier")
    r = commandes.add_parser("reduire", help="relevés de rejeu_moteur.py -> jeu d'essai (session principale, après visa)")
    r.add_argument("releves", nargs="+")
    r.add_argument("--historique", required=True, help="historique des ordres (capture_reference.py historique)")
    r.add_argument("--vers", required=True, help="dossier du jeu, vide ou absent")
    r.add_argument("--recherche", default="A")
    r.add_argument("--tirage", type=int, default=0)
    r.add_argument("--partie", type=int, required=True, help="numéro local de la partie source")
    r.add_argument("--creee-le", required=True, help="date de création de la partie source")
    r.add_argument("--identite", help="fichier écrit au lancement de la campagne (capture_reference.py identite) : "
                                      "date, SHA du dépôt et identifiant de l'image en sont repris")
    r.add_argument("--date", help="date de capture AAAA-MM-JJ (sans --identite)")
    r.add_argument("--sha", help="SHA complet du code qui a produit les tables (sans --identite)")
    r.add_argument("--image", help="identifiant de l'image (sans --identite)")
    r.add_argument("--commande", required=True, help="commande de capture")
    m = commandes.add_parser("manifeste", help="refait la liste des fichiers et les tailles du manifeste")
    m.add_argument("--dossier", required=True)
    args = p.parse_args(argv)

    if args.action == "controler":
        violations = controler(args.dossier)
        if not args.sans_emplacement:
            violations += controler_emplacement(args.racine)
        for violation in violations:
            print("ÉCHEC : %s" % violation)
        presents = fichiers_du_jeu(args.dossier)
        if not violations:
            taille = sum((Path(args.dossier) / f).stat().st_size for f in presents)
            print("Jeu d'essai figé : %s." % (
                "%d fichier(s), %d octets sur %d, conforme" % (len(presents), taille, PLAFOND_OCTETS)
                if presents else "dossier absent ou vide, rien à contrôler"
            ))
        return 1 if violations else 0
    if args.action == "reduire":
        try:
            if args.identite:
                identite = _garder(charger_json(Path(args.identite).read_text(encoding="utf-8")),
                                   ("date", "sha_depot", "image"), "identité de la capture")
                args.date, args.sha, args.image = identite["date"], identite["sha_depot"], identite["image"]
            if None in (args.date, args.sha, args.image):
                raise Refus("--identite, ou bien --date, --sha et --image")
            tables, doublons = reduire_fichiers(args.releves, args.recherche, args.tirage)
            manifeste = construire_jeu(
                args.vers, json.loads(Path(args.historique).read_text(encoding="utf-8")), tables,
                {
                    "partie": {"numero": args.partie, "creee_le": args.creee_le, "nature": NATURE},
                    "capture": {"date": args.date, "sha_code": args.sha, "image": args.image, "commande": args.commande},
                },
            )
        except Refus as e:
            print("REFUS : %s" % e, file=sys.stderr)
            return 2
        for doublon in doublons:
            print("écarté (position déjà pourvue) : %s" % doublon)
        print("Jeu d'essai écrit dans %s : %d table(s), %d octets hors manifeste." % (
            args.vers, sum(len(t) for t in tables.values()), manifeste["taille_octets"]))
        return 0
    if args.action == "manifeste":
        dossier = Path(args.dossier)
        ecrire_manifeste(dossier, json.loads((dossier / MANIFESTE).read_text(encoding="utf-8")))
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
