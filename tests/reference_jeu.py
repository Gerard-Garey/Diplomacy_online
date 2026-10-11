#!/usr/bin/env python3
"""Jeu d'essai figé de la référence de non-régression (issue #31, ADR 0006) : format, réducteur, contrôle.

Bibliothèque standard seule, ni amont/ ni conteneur. Trois usages :

    python3 tests/reference_jeu.py controler [--dossier D] [--racine R]
    python3 tests/reference_jeu.py reduire --historique H.json --vers D --partie N --creee-le DATE \\
        --sha SHA --image ETIQUETTE --commande "..." [--sauf MOTIF ...] RELEVES.jsonl [RELEVES.jsonl ...]
    python3 tests/reference_jeu.py manifeste --dossier D

`controler` est appelé par tests/verifier.sh (ADR 0006, décision 3) ; il passe sur un
dossier absent ou vide (la batterie, elle, exige le manifeste de tests/reference/). Avec le dossier, il contrôle le dépôt entier : emplacement unique
des tables, et deux tests sur les seuls noms de fichiers (noms des fichiers d'état,
extensions en liste fermée : `controler_noms`). `reduire` transforme des relevés de tests/mesure/rejeu_moteur.py
(bruts, hors git) en jeu d'essai : seule la session principale le lance vers
tests/reference/, après visa (ADR 0006, décision 6) ; il refuse, code 2 et rien d'écrit, un relevé, un
historique ou une identité absent, illisible ou d'une forme inattendue, une valeur non finie, zéro table, une
autre partie que --partie, un fichier donné deux fois ou deux fichiers de même nom, et deux relevés retenus
(recherche A, tirage 0) pour une même position, dans deux fichiers ou dans un seul : le fichier d'une position
répétée porte plusieurs relevés de cette position (ses tirages, recherches A et B), un seul est retenu (--sauf
écarte des fichiers par leur nom, comme pour `resumer` : la seconde passe s'écarte par --sauf '*passe2*' ; un
dossier vaut ses m1_*.jsonl). Seul le refus du contrôle final de `construire_jeu` (le jeu écrit ne passe pas
`controler`), code 2 lui aussi, laisse dans --vers les fichiers écrits, pour être lus. `manifeste` refait la liste des
fichiers et les tailles d'un jeu dont les fichiers ont changé (attendus régénérés) ; il
refuse, sans rien écrire, un jeu dont le résumé (repetee.json) n'est plus celui que le manifeste a noté,
ou que le manifeste ne note plus alors qu'il en porte le bloc.

Format (ADR 0006, décision 2), un dossier :

    manifeste.json          partie source, phases, puissances, capture, taille, fichiers
    historique.json         {"phases": [{"name": "S1901M", "orders": {"AUSTRIA": [ordres]}}]}
    tables/<PHASE>.json     {"phase": "S1901M", "tables": {"AUSTRIA": <table>}}
    attendus/<PHASE>.json   {"phase": "S1901M", "attendus": {"AUSTRIA": {"D2": ...}}}
    repetee.json            facultatif : résumé des positions répétées (couche R), {"planchers": {...},
                            "positions": {"S1901M": {"AUSTRIA": <résumé>}}}

<table> : les quatre clés que plan_export écrit et que le bot de dialogue lit,
`plans` (rank, orders, value, cost_vs_best), `order_values`, `candidates` (orders,
value, prob), `search` (lambda, boost, max_prob) ; plus, quand ils ont été relevés,
les arguments bruts d'export_plans sous `export_plans` : `action_values` (value,
prob, score, et `orders` quand ce ne sont pas ceux du candidat de même rang),
`prior_policy` (prob, et `action` -- le rang de l'action dans `action_values` -- ou
`orders` si elle n'y est pas), `regularize_lambda`, `boost`,
`max_prob`. Les attendus sont ceux de tests/reference_couche_d.py.

Ces arguments bruts sont liés entre eux, et le contrôle le vérifie sur chaque table qui les porte (#40 :
la couche D ne lit ni le score, ni la probabilité d'`action_values`, ni ce qu'une valeur ou une probabilité
garde sous l'arrondi de l'export) : le score est value + regularize_lambda x ln(max(prob, 1e-6)) (I1), les
scores ne croissent pas le long de la liste (I2), et la probabilité d'une action est celle de sa ligne de
`prior_policy` (I3). I3 ne vaut que sans engagement : le jeu ne reçoit que des tables de recherches A.

<résumé> (tests/reference_couche_r.py, qui l'écrit et le lit ; ADR 0006, décision 2 : des
grandeurs résumées et leurs tolérances, jamais les recherches brutes) : `n` tirages ;
`ln_lambda` et `v_tete` [moyenne, écart type] ; `tetes` [{orders, n}] ; `order_values`
{ordre: [moyenne, écart type, effectif]} ; `S_ov`, `S_G` ; `boost`, `max_prob`. Le manifeste
en porte alors le bloc `repetee` : date, SHA du code, commande, et des relevés d'origine
(hors git) leur nombre, celui des recherches résumées et une empreinte.

Ce qu'un relevé contient en plus n'entre pas : `computed_at`, `gpu`, `duree_s`,
`journal`, `statut`, `game_id`, texte de message. Le réducteur ne recopie que les
clés nommées ci-dessus, et le contrôle refuse toute autre clé.
"""
import argparse
import errno
import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # ni __pycache__ dans tests/ (#27)

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "tests" / "reference"
EMPLACEMENT = "tests/reference"  # seul dossier admis, relatif à la racine du dépôt
MANIFESTE, HISTORIQUE, TABLES, ATTENDUS = "manifeste.json", "historique.json", "tables", "attendus"
REPETEE = "repetee.json"  # résumé des positions répétées (couche R) : facultatif, avec son bloc au manifeste
FORMAT = 1
NATURE = "100 % bots"
PLAFOND_OCTETS = 512 * 1024  # ADR 0006, décision 3 : le dépasser demande une annotation de l'ADR
# Mesuré sur les relevés m1_3_* (30 recherches) : l'ordre le plus long y fait 22 caractères.
# 24 est la borne de l'ADR 0006 (« moins de 24 caractères »).
LONGUEUR_ORDRE_MAX = 24
# Contrôle des noms (ADR 0006, annotation du 2026-10-10, point D ; feuille de route, question 16), sur les
# fichiers versionnés ou à versionner du dépôt entier. Il ne lit que des noms : ce qu'un nom ne dit pas
# (table en littéral dans du code, fichier coupé) lui échappe, et l'ADR l'accepte par écrit.
# Les trois fichiers d'état d'une instance (ADR 0006, décision 1), par leur nom où qu'il soit dans le nom de
# base (décision du mainteneur, 2026-10-10) : `old_current_plans.json`, `2026-10-10_claude_dialogue_state.json`.
# Hors de portée d'un test sur le nom de base, et non traités : une autre graphie (`claude-dialogue-state.json`,
# avec des tirets) et un nom porté par le dossier (`current_plans/3.json`).
NOMS_D_ETAT = ("current_plans", "pseudo_commitments", "claude_dialogue_state")
# Ce que le contrôle du manifeste dit d'un fichier retouché : tests/reference_couche_d.py (--generer) le relit.
NE_CORRESPOND_PLUS = "ne correspond plus au manifeste"
# Ce que le refus de I3 dit de sa portée (#40) : l'égalité est celle d'une recherche sans engagement.
SANS_ENGAGEMENT = ("L'égalité ne vaut que pour une table de recherche sans engagement (recherche A) : avec engagement, "
                   "le renfort déplace la probabilité d'action_values, et une telle table n'entre pas dans le jeu")
# Listes fermées, mesurées sur les 106 fichiers du dépôt le 2026-10-10. Une extension ou un nom nouveau
# s'ajoute ici, dans le commit qui introduit le fichier : la ligne se voit dans le diff.
EXTENSIONS_ADMISES = (
    ".py", ".md", ".sh", ".yml", ".patch", ".prototxt", ".json", ".exemple", ".txt", ".sql", ".php", ".js", ".env",
)
NOMS_SANS_EXTENSION = ("Dockerfile", "LICENSE", "NOTICE", ".gitignore", ".gitattributes", ".dockerignore")

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
# Cohérence des arguments bruts d'export_plans (#40). Le score d'une action est celui que la recherche calcule,
# amont Cicero au commit épinglé par versions.env (e85afeddb34f5b7c1ea0827203b425a0f7e68ead),
# fairdiplomacy/agents/br_corr_bilateral_search.py:339 :
#     pice_value = value + regularize_lambda * np.log(max(prob, 1e-6))
# puis la liste est triée par score décroissant (:342). Mesuré sur les 42 tables du jeu versionné (628 actions),
# avec math.log : écart nul. La tolérance couvre un écart d'arrondi entre np.log et math.log d'une machine à
# l'autre (prudence, non mesurée) ; elle est absolue, les scores étant de l'ordre de l'unité.
PLANCHER_PROB_SCORE = 1e-6
TOLERANCE_SCORE = 1e-12

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
# Clés du résumé des positions répétées (liste blanche : l'étendre, c'est étendre le format).
CLES_REPETEE = ("planchers", "positions")
CLES_PLANCHERS = ("ln_lambda", "v_tete", "S_ov", "S_G")
CLES_RESUME = ("n", "ln_lambda", "v_tete", "tetes", "order_values", "S_ov", "S_G", "boost", "max_prob")
CLES_TETE = ("orders", "n")
CLES_MANIFESTE = {
    "": ("format", "partie", "phases", "puissances", "capture", "taille_octets", "fichiers"),
    "partie": ("numero", "creee_le", "nature"),
    "capture": ("date", "sha_code", "image", "commande"),
    "attendus": ("date", "sha_code", "commande"),
    "repetee": ("date", "sha_code", "commande", "releves"),
    "releves": ("fichiers", "recherches", "sha256"),
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


def lire_repetee(dossier):
    """Le résumé des positions répétées du jeu (couche R), ou None s'il n'y est pas. Ne contrôle rien : voir controler()."""
    fichier = Path(dossier) / REPETEE
    if fichier.is_symlink() or not fichier.is_file():
        return None
    return charger_json(fichier.read_text(encoding="utf-8"))


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


def refuser_resume_retouche(dossier, manifeste):
    """Lève Refus si le résumé (repetee.json) présent n'est pas celui que le manifeste a noté, taille et empreinte.

    Garde de la commande `manifeste` : refaire les empreintes entérinerait un résumé retouché. Deux cas : le
    manifeste note le fichier et le fichier présent a une autre taille ou une autre empreinte ; le manifeste
    ne le note plus mais porte le bloc « repetee » (#40 : le résumé sorti du dossier, `manifeste`, le résumé
    retouché remis, `manifeste` -- au second appel, rien ne dit plus que le fichier est celui que le bloc décrit).
    Un résumé absent du dossier passe (deuxième des trois temps qui le refont : fichier et bloc supprimés,
    manifeste refait, puis `resumer`), comme un fichier que le manifeste ne note pas et dont il n'a pas le bloc
    (le contrôle, lui, refuse ce résumé sans bloc).
    """
    fichier = Path(dossier) / REPETEE
    fichiers = manifeste.get("fichiers")
    notes = [f for f in fichiers if isinstance(f, dict) and f.get("chemin") == REPETEE] if isinstance(fichiers, list) else []
    if fichier.is_symlink() or not fichier.is_file():
        return
    if not notes:
        if "repetee" in manifeste:
            raise Refus("%s est dans le dossier et le manifeste en porte le bloc « repetee », mais ne note plus ce fichier "
                        "(ni taille ni empreinte) : rien ne dit que c'est le résumé que ce bloc décrit, la commande "
                        "`manifeste` ne l'entérine pas, rien n'est écrit. Restaurer le manifeste et le résumé depuis git, "
                        "ou refaire le résumé (session principale, après visa) : 1) supprimer ce fichier et le bloc "
                        "« repetee » du manifeste ; 2) relancer `manifeste` ; 3) python3 tests/reference_couche_r.py "
                        "resumer <relevés> --vers %s" % (fichier, dossier))
        return
    octets = fichier.read_bytes()
    if any(f.get("octets") != len(octets) or f.get("sha256") != hashlib.sha256(octets).hexdigest() for f in notes):
        raise Refus("%s n'a plus la taille ou l'empreinte que le manifeste a notées pour ce résumé : la commande `manifeste` "
                    "ne refait pas un résumé, rien n'est écrit. Le restaurer depuis git avec le manifeste, ou le refaire "
                    "(session principale, après visa) : 1) supprimer ce fichier et le bloc « repetee » du manifeste ; "
                    "2) relancer `manifeste` ; 3) python3 tests/reference_couche_r.py resumer <relevés> --vers %s"
                    % (fichier, dossier))


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

    Une ligne non retenue se reconnaît à sa raison (une chaîne, là où une table est un objet), pas à sa
    phase : celle d'une ligne retenue est rendue telle qu'elle est écrite, `null` compris.

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
        arguments, deja = table["export_plans"], len(c.violations)
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
        if len(c.violations) == deja:  # la cohérence ne se juge que sur des arguments bien formés
            _controler_coherence(c, arguments, ici)


def _controler_coherence(c, arguments, ici):
    """I1 à I3 (#40) sur les arguments bruts d'export_plans d'une table, déjà contrôlés dans leur forme.

    Trois liens que la couche D ne rejoue pas (export_plans déballe le score sans le lire, ne lit pas la
    probabilité d'`action_values`, arrondit valeurs et probabilités) : ils gardent le score, la probabilité
    et ce qui reste sous l'arrondi contre une retouche d'une seule de ces données. Une retouche qui les
    déplace ensemble (valeur et score du même écart, par exemple) reste cohérente, donc invisible ici.
    """
    actions, coefficient = arguments["action_values"], arguments["regularize_lambda"]
    for i, action in enumerate(actions):
        la = "%s.action_values[%d]" % (ici, i)
        attendu = action["value"] + coefficient * math.log(max(action["prob"], PLANCHER_PROB_SCORE))
        if not abs(action["score"] - attendu) <= TOLERANCE_SCORE:
            c.ko(la + ".score", "I1 : %r n'est pas value + regularize_lambda x ln(max(prob, %g)) = %r (écart %.3g, "
                 "tolérance %g ; value %r, prob %r, regularize_lambda %r) : score, valeur ou probabilité retouché"
                 % (action["score"], PLANCHER_PROB_SCORE, attendu, abs(action["score"] - attendu), TOLERANCE_SCORE,
                    action["value"], action["prob"], coefficient))
        if i and action["score"] > actions[i - 1]["score"]:
            c.ko(la + ".score", "I2 : %r dépasse le score de l'action précédente (%r) : action_values est triée par "
                 "score décroissant, et export_plans prend l'ordre de la liste" % (action["score"], actions[i - 1]["score"]))
    designees = set()
    for j, ligne in enumerate(arguments["prior_policy"]):
        i = ligne.get("action")
        if not _entier(i) or i >= len(actions):  # action hors d'action_values (`orders`), ou rang hors bornes
            continue
        designees.add(i)
        if actions[i]["prob"] != ligne["prob"]:
            c.ko("%s.action_values[%d].prob" % (ici, i), "I3 : %r n'est pas la probabilité de prior_policy[%d] (%r), qui "
                 "désigne cette action. %s" % (actions[i]["prob"], j, ligne["prob"], SANS_ENGAGEMENT))
    for i in range(len(actions)):
        if i not in designees:
            c.ko("%s.action_values[%d].prob" % (ici, i), "I3 : aucune ligne de prior_policy ne désigne cette action par "
                 "son rang (`action`). %s" % SANS_ENGAGEMENT)


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


def _controler_repetee(c, donnees):
    """Le résumé des positions répétées : clés nommées, nombres, ordres ; rend ses positions [(phase, puissance)]."""
    positions = []
    if not c.objet(donnees, "", CLES_REPETEE):
        return positions
    if c.objet(donnees["planchers"], "planchers", CLES_PLANCHERS):
        for cle in CLES_PLANCHERS:
            c.nombre(donnees["planchers"][cle], "planchers." + cle)
    if not isinstance(donnees["positions"], dict):
        c.ko("positions", "objet attendu")
        return positions
    for phase, par_puissance in donnees["positions"].items():
        c.chaine(phase, "positions (clé)", (_est_phase,))
        if not isinstance(par_puissance, dict):
            c.ko("positions.%s" % phase[:LONGUEUR_ORDRE_MAX], "objet attendu")
            continue
        for puissance, resume in par_puissance.items():
            ici = "positions.%s.%s" % (phase[:LONGUEUR_ORDRE_MAX], puissance[:12])
            c.chaine(puissance, "positions.%s (clé)" % phase[:LONGUEUR_ORDRE_MAX], (_est_puissance,))
            positions.append((phase, puissance))
            if not c.objet(resume, ici, CLES_RESUME):
                continue
            if not _entier(resume["n"]) or resume["n"] < 2:
                c.ko(ici + ".n", "nombre de tirages (entier, au moins 2) attendu")
            for cle in ("ln_lambda", "v_tete"):
                paire = resume[cle]
                if not isinstance(paire, list) or len(paire) != 2:
                    c.ko("%s.%s" % (ici, cle), "[moyenne, écart type] attendu")
                    continue
                for i, valeur in enumerate(paire):
                    c.nombre(valeur, "%s.%s[%d]" % (ici, cle, i))
            for cle in ("S_ov", "S_G", "boost", "max_prob"):
                c.nombre(resume[cle], "%s.%s" % (ici, cle))
            tetes = c.liste(resume["tetes"], ici + ".tetes")
            if not tetes:
                c.ko(ici + ".tetes", "au moins une tête attendue")
            for i, tete in tetes:
                la = "%s.tetes[%d]" % (ici, i)
                if c.objet(tete, la, CLES_TETE):
                    c.ordres(tete["orders"], la + ".orders")
                    c.entier(tete["n"], la + ".n")
            if not isinstance(resume["order_values"], dict):
                c.ko(ici + ".order_values", "objet attendu")
                continue
            for ordre, triplet in resume["order_values"].items():
                la = "%s.order_values.%s" % (ici, ordre[:LONGUEUR_ORDRE_MAX])
                c.chaine(ordre, ici + ".order_values (clé)", (_est_ordre,))
                if not isinstance(triplet, list) or len(triplet) != 3:
                    c.ko(la, "[moyenne, écart type, effectif] attendu")
                    continue
                c.nombre(triplet[0], la + "[0]")
                c.nombre(triplet[1], la + "[1]")
                c.entier(triplet[2], la + "[2]")
    return positions


def _controler_manifeste(c, manifeste, dossier, presents, tables):
    """Le manifeste : clés nommées, chaque valeur typée, et fidèle au dossier.

    `tables` : {phase: clés de l'objet `tables` du fichier} pour les fichiers de
    tables lus. Les phases du manifeste sont exactement celles des fichiers de
    tables/ (celles d'attendus/ en font partie), ses puissances l'union de celles
    des tables : un manifeste raccourci ne peut pas soustraire une table à la couche D.
    """
    if not c.objet(manifeste, "", CLES_MANIFESTE[""], ("attendus", "repetee")):
        return
    if manifeste["format"] != FORMAT or isinstance(manifeste["format"], bool):
        c.ko("format", "%d attendu" % FORMAT)
    partie, capture = manifeste["partie"], manifeste["capture"]
    if c.objet(partie, "partie", CLES_MANIFESTE["partie"]):
        c.entier(partie["numero"], "partie.numero")
        c.motif(partie["creee_le"], "partie.creee_le", DATE, "date AAAA-MM-JJ")
        if partie["nature"] != NATURE:
            c.ko("partie.nature", "%r attendu : seule une partie 100 %% bots est admise" % NATURE)
    if ("repetee" in manifeste) != (REPETEE in presents):  # le résumé et son bloc vont ensemble
        c.ko("repetee", "bloc sans %s dans le dossier" % REPETEE if "repetee" in manifeste
             else "%s est dans le dossier sans son bloc (date, SHA, commande, relevés d'origine)" % REPETEE)
    for cle, bloc in (("capture", capture), ("attendus", manifeste.get("attendus")), ("repetee", manifeste.get("repetee"))):
        if cle != "capture" and cle not in manifeste:
            continue
        if not c.objet(bloc, cle, CLES_MANIFESTE[cle]):
            continue
        if cle == "repetee" and c.objet(bloc["releves"], "repetee.releves", CLES_MANIFESTE["releves"]):
            c.entier(bloc["releves"]["fichiers"], "repetee.releves.fichiers")
            c.entier(bloc["releves"]["recherches"], "repetee.releves.recherches")
            c.motif(bloc["releves"]["sha256"], "repetee.releves.sha256", SHA256, "SHA-256")
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
            if relatif == REPETEE:  # refaire les empreintes entérinerait un résumé retouché : il se restaure ou se refait
                c.ko("fichiers", "%s n'a plus la taille ou l'empreinte que le manifeste a notées pour ce résumé : le "
                     "restaurer depuis git avec le manifeste, ou refaire le résumé par `python3 "
                     "tests/reference_couche_r.py resumer` (session principale, après visa) ; la commande `manifeste` "
                     "ne refait pas un résumé" % relatif)
            else:
                c.ko("fichiers", "%s %s (taille ou empreinte) : "
                     "refaire le manifeste, par la session principale après visa" % (relatif, NE_CORRESPOND_PLUS))
    if manifeste["taille_octets"] != sum(f["octets"] for f in listes.values() if _entier(f["octets"])):
        c.ko("taille_octets", "n'est pas la somme des tailles des fichiers listés")


def controler(dossier=DOSSIER):
    """Violations de l'ADR 0006 (décision 3) dans le dossier du jeu d'essai ; [] s'il est absent, vide ou conforme.

    Liste blanche des clés (toute clé JSON est nommée par le format, ou est un ordre,
    une puissance), aucune chaîne hors manifeste plus longue qu'un ordre ni qui
    porte une ponctuation de phrase -- et, plus strictement, aucune qui ne soit un
    ordre, une puissance, une phase ou un mot du vocabulaire --, plafond de taille,
    manifeste fidèle au dossier, aucun fichier d'un autre type. Et, sur les arguments bruts
    d'export_plans de chaque table, trois liens que la couche D ne rejoue pas (I1 à I3, #40 :
    `_controler_coherence`).
    """
    dossier = Path(dossier)
    presents = fichiers_du_jeu(dossier)
    violations = [
        "%s : %s : lien symbolique (un jeu d'essai n'en contient pas : ce qu'il désigne échappe au contrôle)"
        % (dossier.name, lien) for lien in liens_du_jeu(dossier)
    ]
    if not presents:
        return violations
    tables, manifeste, repetees = {}, None, None
    taille = sum((dossier / f).stat().st_size for f in presents)
    if taille > PLAFOND_OCTETS:
        violations.append("%s : %d octets, plafond %d (512 Kio ; ADR 0006, décision 3)" % (dossier.name, taille, PLAFOND_OCTETS))
    for relatif in presents:
        c = _Controle(relatif)
        parties = relatif.split("/")
        phase = parties[-1][:-len(".json")] if relatif.endswith(".json") else ""
        connu = relatif in (MANIFESTE, HISTORIQUE, REPETEE) or (
            len(parties) == 2 and parties[0] in (TABLES, ATTENDUS) and est_phase(phase)
        )
        if not connu:
            c.ko("", "fichier qui n'est pas du format du jeu d'essai (manifeste.json, historique.json, "
                     "tables/<PHASE>.json, attendus/<PHASE>.json, repetee.json)")
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
            elif relatif == REPETEE:
                repetees = _controler_repetee(c, donnees)  # ses positions se comparent plus bas aux tables lues
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
    if repetees is not None:
        c = _Controle(REPETEE)
        for phase, puissance in repetees:
            if puissance not in tables.get(phase, ()):
                c.ko("positions.%s.%s" % (phase[:LONGUEUR_ORDRE_MAX], puissance[:12]),
                     "résumé d'une position sans table dans %s/" % TABLES)
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


def fichiers_du_depot(racine, suivis_seuls=False):
    """Fichiers versionnés ou à versionner (non ignorés) du dépôt, relatifs à sa racine.

    `suivis_seuls` : les seuls fichiers versionnés, sans ceux de l'arbre de travail qui ne le sont pas encore.
    """
    selection = ["--cached"] if suivis_seuls else ["--cached", "--others", "--exclude-standard"]
    sortie = subprocess.run(
        ["git", "-C", str(racine), "ls-files", "-z"] + selection,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return [f for f in sortie.stdout.decode("utf-8", "replace").split("\0") if f]


def nom_lisible(relatif):
    """Le nom tel qu'il s'écrit dans une ligne d'échec : lui-même, ou son `repr` s'il porte un caractère
    non imprimable (un retour à la ligne couperait la ligne et en détacherait le motif du refus)."""
    return relatif if relatif.isprintable() else repr(relatif)


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
                % (nom_lisible(relatif), ", ".join(CLES_TABLE), EMPLACEMENT)
            )
    return violations


def nom_d_etat(relatif):
    """Vrai si le nom de base est celui d'un fichier d'état d'une instance ou d'une de ses copies.

    Contient l'un des NOMS_D_ETAT et contient « .json » : aussi `.json.bak`, `.json.gz`, `.jsonl`,
    `current_plans_copie.json`, `old_current_plans.json` ; pas `pseudo_commitments.py` ni
    `test_pseudo_commitments.py`. Sans égard à la casse.
    """
    nom = relatif.rsplit("/", 1)[-1].lower()
    return any(etat in nom for etat in NOMS_D_ETAT) and ".json" in nom


def extension(relatif):
    """Dernière extension du nom de base, point compris ; "" s'il n'en a pas (`Dockerfile`, `.gitignore`)."""
    nom = relatif.rsplit("/", 1)[-1]
    return nom[nom.rindex("."):] if "." in nom[1:] else ""


def controler_noms(racine=RACINE, fichiers=None):
    """Deux tests sur les seuls noms des fichiers du dépôt, tests/reference/ compris.

    Aucun fichier d'état d'une instance, sous aucune de ses formes (`nom_d_etat`) ; aucune
    extension hors de EXTENSIONS_ADMISES, aucun nom sans extension hors de NOMS_SANS_EXTENSION.
    Un fichier peut être refusé aux deux titres : chaque refus a sa ligne.
    """
    fichiers = fichiers_du_depot(racine) if fichiers is None else fichiers
    violations = []
    for relatif in sorted(fichiers):
        lisible = nom_lisible(relatif)
        if nom_d_etat(relatif):
            violations.append(
                "%s : nom d'un fichier d'état d'une instance (nom de base qui contient %s, et « .json ») : il n'entre "
                "pas au dépôt, même en copie ou en sauvegarde (ADR 0006, décision 1)" % (lisible, ", ".join(NOMS_D_ETAT))
            )
        suffixe, nom = extension(relatif), relatif.rsplit("/", 1)[-1]
        if suffixe and suffixe not in EXTENSIONS_ADMISES:
            violations.append(
                "%s : extension %s hors de la liste fermée (%s) : un relevé, une sauvegarde ou une table sous un autre "
                "type n'entre pas au dépôt (ADR 0006). Si le fichier est légitime, ajouter son extension à "
                "EXTENSIONS_ADMISES (tests/reference_jeu.py) dans le commit qui l'introduit"
                % (lisible, nom_lisible(suffixe), " ".join(EXTENSIONS_ADMISES))
            )
        elif not suffixe and nom not in NOMS_SANS_EXTENSION:
            violations.append(
                "%s : nom sans extension hors de la liste fermée (%s). Si le fichier est légitime, ajouter son nom à "
                "NOMS_SANS_EXTENSION (tests/reference_jeu.py) dans le commit qui l'introduit"
                % (lisible, " ".join(NOMS_SANS_EXTENSION))
            )
    return violations


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

# Relevés d'un dossier passé à `reduire` : MOTIF de tests/mesure/bruit_valeurs.py (celui que lit `resumer`),
# recopié ici parce que ce module n'importe que la bibliothèque standard. tests/test_reference.py compare les deux.
MOTIF_RELEVES = "m1_*.jsonl"
# Ce qu'une donnée d'une forme imprévue lève à la réduction : un refus, jamais une trace.
# Ce que tests/mesure/capture_reference.py écrit dans l'identité de la capture, dans l'ordre (date, SHA, image) de `reduire`.
CLES_IDENTITE = ("date", "sha_depot", "image")
FORME_INATTENDUE = (RecursionError, TypeError, AttributeError, KeyError, IndexError, ValueError, OverflowError)


def _lire_texte(chemin, quoi):
    """Le texte d'un fichier d'entrée de `reduire` ; lève Refus, qui nomme le fichier, s'il est absent ou n'est pas de l'UTF-8."""
    try:
        return Path(chemin).read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise Refus("%s : %s qui n'est pas de l'UTF-8 (octet %d)" % (chemin, quoi, e.start))
    except OSError as e:
        raise Refus("%s : %s absent ou illisible (%s)" % (chemin, quoi, e.strerror or type(e).__name__))


def _lire_json(chemin, quoi):
    texte = _lire_texte(chemin, quoi)
    try:
        return charger_json(texte)
    except ValueError as e:
        raise Refus("%s : %s, JSON invalide (%s)" % (chemin, quoi, str(e)[:80]))


def _non_fini(valeur, chemin=""):
    """Chemin du premier nombre d'une donnée réduite que le format n'admet pas (NaN, inf, entier démesuré), ou None.

    json.loads lit `NaN`, `Infinity` et `1e999` (inf) ; ecrire_json les refuserait en cours d'écriture.
    """
    if isinstance(valeur, dict):
        for cle, contenu in valeur.items():
            trouve = _non_fini(contenu, "%s.%s" % (chemin, str(cle)[:LONGUEUR_ORDRE_MAX]) if chemin else str(cle)[:LONGUEUR_ORDRE_MAX])
            if trouve is not None:
                return trouve
    elif isinstance(valeur, list):
        for i, contenu in enumerate(valeur):
            trouve = _non_fini(contenu, "%s[%d]" % (chemin, i))
            if trouve is not None:
                return trouve
    elif isinstance(valeur, (int, float)) and not isinstance(valeur, bool) and not _nombre(valeur):
        return chemin or "(racine)"
    return None


def lire_identite(chemin):
    """(date, SHA du dépôt, image) du fichier d'identité de la capture ; lève Refus s'il est absent, illisible ou d'une autre forme.

    Chaque champ est une chaîne : un nombre (`NaN` compris, que json.loads lit) ne passerait qu'à l'écriture
    du manifeste, historique et tables déjà écrits.
    """
    identite = _garder(_lire_json(chemin, "identité de la capture"), CLES_IDENTITE, "%s : identité de la capture" % chemin)
    for cle in CLES_IDENTITE:
        if not isinstance(identite[cle], str):
            raise Refus("%s : identité de la capture, %s : chaîne attendue, %s trouvé" % (chemin, cle, type(identite[cle]).__name__))
    return tuple(identite[cle] for cle in CLES_IDENTITE)


def lire_historique(chemin):
    """L'historique des ordres du fichier, tel qu'il est écrit ; lève Refus s'il ne se réduit pas (absent, illisible, forme, valeur non finie)."""
    historique = _lire_json(chemin, "historique des ordres")
    try:
        fautif = _non_fini(reduire_historique(historique))
    except Refus as e:
        raise Refus("%s : %s" % (chemin, e))
    except FORME_INATTENDUE as e:
        raise Refus("%s : forme inattendue de l'historique des ordres (%s)" % (chemin, type(e).__name__))
    if fautif is not None:
        raise Refus("%s : nombre non fini dans l'historique des ordres (%s)" % (chemin, fautif))
    return historique


def _lire_releves(chemins):
    """(« fichier:ligne », relevé) de chaque ligne non blanche ; lève Refus sur un fichier absent, non UTF-8 ou vide,
    et sur une ligne qui n'est pas un objet JSON (relevé tronqué compris)."""
    for chemin in chemins:
        vide = True
        for numero, ligne in enumerate(_lire_texte(chemin, "relevé").splitlines(), 1):
            if not ligne.strip():
                continue
            vide, origine = False, "%s:%d" % (Path(chemin).name, numero)
            try:
                releve = charger_json(ligne)
            except ValueError as e:
                raise Refus("%s : ligne JSON invalide ou tronquée (%s)" % (origine, str(e)[:80]))
            if not isinstance(releve, dict):
                raise Refus("%s : objet attendu, %s trouvé" % (origine, type(releve).__name__))
            yield origine, releve
        if vide:
            raise Refus("%s : relevé vide (aucune ligne)" % chemin)


def fichiers_de_releves(chemins, sauf=()):
    """(retenus, noms écartés) des fichiers de relevés donnés, triés ; un dossier vaut ses MOTIF_RELEVES.

    `sauf` : motifs de nom (fnmatch), comme --sauf de tests/reference_couche_r.py ; un fichier écarté n'est pas lu.
    Lève Refus, qui cite les chemins complets, sur un fichier donné deux fois (deux écritures du même chemin,
    un dossier et l'un de ses fichiers, ou un fichier et un lien symbolique vers lui, fussent-ils dans le même
    dossier) et sur deux fichiers retenus de même nom : les messages de refus et `sauf` désignent un fichier
    par son nom, qui doit donc n'en désigner qu'un. Le premier refus est jugé avant `sauf`, qui ne le lève pas ;
    un chemin qui ne se résout pas (boucle de liens) est refusé comme un relevé illisible.
    """
    retenus, ecartes, vus, noms = [], [], {}, {}
    for chemin in chemins:
        chemin = Path(chemin)
        if chemin.is_dir():
            trouves = sorted(chemin.glob(MOTIF_RELEVES))
            if not trouves:
                raise Refus("%s : aucun relevé %s dans ce dossier" % (chemin, MOTIF_RELEVES))
        else:
            trouves = [chemin]
        for fichier in trouves:
            try:
                reel = fichier.resolve()
            except (OSError, RuntimeError) as e:  # RuntimeError : boucle de liens, avant Python 3.13
                raise Refus("%s : relevé absent ou illisible (%s)" % (fichier, getattr(e, "strerror", None) or os.strerror(errno.ELOOP)))
            if reel in vus:
                raise Refus("fichier de relevés donné deux fois, ou un lien vers lui : %s et %s" % (vus[reel], fichier))
            vus[reel] = fichier
            if any(fnmatch.fnmatch(fichier.name, motif) for motif in sauf):
                ecartes.append(fichier.name)
                continue
            if fichier.name in noms:
                raise Refus("deux fichiers de relevés de même nom : %s et %s ; un fichier est désigné par son nom "
                            "(messages de refus, --sauf) : en renommer un" % (noms[fichier.name], fichier))
            noms[fichier.name] = fichier
            retenus.append(str(fichier))
    if not retenus:
        raise Refus("aucun fichier de relevés retenu (--sauf %s)" % " ".join(sauf))
    return sorted(retenus), sorted(ecartes)


def reduire_fichiers(chemins, recherche="A", tirage=0, a_sec=False, partie=None, sauf=()):
    """{phase: {puissance: table}} des relevés donnés, une table par position ; rend aussi les noms des fichiers écartés par `sauf`.

    Lève Refus, qui nomme le fichier et la ligne : relevé illisible ou d'une forme inattendue, nombre non fini
    dans une table, position d'un relevé retenu qui n'est pas une phase et une puissance (`null` compris),
    relevé retenu d'une autre partie que `partie` (None : non comparé), deux relevés retenus (recherche
    `recherche`, tirage `tirage`) pour une même position, dans deux fichiers ou dans un seul (le message nomme
    les deux : aucun ne l'emporte, on en écarte un par `sauf`), aucune table retenue. Les autres relevés d'une
    position (autres tirages, autre recherche) ne sont pas retenus : un fichier peut en porter plusieurs.
    """
    retenus, ecartes = fichiers_de_releves(chemins, sauf)
    tables, origines = {}, {}
    for origine, ligne in _lire_releves(retenus):
        try:
            phase, puissance, table = reduire_releve(ligne, recherche, tirage, a_sec)
            fautif = _non_fini(table) if isinstance(table, dict) else None
        except Refus as e:
            raise Refus("%s : %s" % (origine, e))
        except FORME_INATTENDUE as e:
            raise Refus("%s : forme inattendue du relevé (%s)" % (origine, type(e).__name__))
        if not isinstance(table, dict):  # ligne non retenue : `table` en est la raison
            continue
        if not est_phase(phase) or not isinstance(puissance, str) or puissance not in POWERS:
            raise Refus("%s : position qui n'est pas une phase et une puissance (%s, %s)" % (origine, _apercu(phase), _apercu(puissance)))
        if fautif is not None:
            raise Refus("%s : nombre non fini dans la table de %s %s (%s)" % (origine, phase, puissance, fautif))
        if partie is not None and (not _entier(ligne.get("game_id")) or ligne["game_id"] != partie):
            raise Refus("%s : relevé de la partie %s (game_id), pas de la partie %d demandée (--partie)"
                        % (origine, repr(ligne.get("game_id"))[:40], partie))
        if (phase, puissance) in origines:
            raise Refus("deux relevés pour la position %s %s (%s, %s) : un jeu a une table par position ; en écarter un "
                        "(--sauf MOTIF écarte un fichier par son nom)" % (phase, puissance, origines[phase, puissance], origine))
        origines[phase, puissance] = origine
        tables.setdefault(phase, {})[puissance] = table
    if not tables:
        raise Refus("aucune table retenue (recherche %s, tirage %s) dans %d fichier(s) de relevés : %s"
                    % (recherche, tirage, len(retenus), " ".join(Path(f).name for f in retenus[:3]) + (" …" if len(retenus) > 3 else "")))
    return tables, ecartes


def _numero_de_partie(texte):
    """Type argparse de --partie : un `game_id` n'est pas négatif, et « partie -1, pas la partie -1 demandée » ne dirait rien."""
    if not (texte.isascii() and texte.isdigit()):  # int() admettrait aussi '1_0', ' 3 ' et '٣'
        raise argparse.ArgumentTypeError("entier positif ou nul attendu, %r trouvé" % texte[:40])
    return int(texte)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commandes = p.add_subparsers(dest="action")  # pas « commande » : c'est une option de `reduire`
    c = commandes.add_parser("controler", help="contrôle du jeu d'essai, de l'emplacement unique et des noms (tests/verifier.sh)")
    c.add_argument("--dossier", default=str(DOSSIER))
    c.add_argument("--racine", default=str(RACINE),
                   help="dépôt où chercher une table hors de tests/reference/ et un nom de fichier non admis")
    c.add_argument("--sans-emplacement", action="store_true", help="ne contrôle que le dossier (ni emplacement, ni noms)")
    r = commandes.add_parser("reduire", help="relevés de rejeu_moteur.py -> jeu d'essai (session principale, après visa)")
    r.add_argument("releves", nargs="+", help="fichiers de relevés, ou dossier (ses %s)" % MOTIF_RELEVES.replace("%", "%%"))
    r.add_argument("--sauf", metavar="MOTIF", action="append", help="écarte les fichiers de ce nom (répétable)")
    r.add_argument("--historique", required=True, help="historique des ordres (capture_reference.py historique)")
    r.add_argument("--vers", required=True, help="dossier du jeu, vide ou absent")
    r.add_argument("--recherche", default="A")
    r.add_argument("--tirage", type=int, default=0)
    r.add_argument("--partie", type=_numero_de_partie, required=True, help="numéro local de la partie source (entier positif ou nul)")
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
            try:
                fichiers = fichiers_du_depot(args.racine)
            except (subprocess.CalledProcessError, OSError) as e:  # hors d'un dépôt git, ou git absent
                motif = (getattr(e, "stderr", None) or b"").decode("utf-8", "replace").strip().splitlines()
                print("REFUS : --racine %s : git n'y liste aucun fichier (%s) ; --sans-emplacement ne contrôle que le dossier"
                      % (args.racine, motif[0][:120] if motif else type(e).__name__), file=sys.stderr)
                return 2
            violations += controler_emplacement(args.racine, fichiers) + controler_noms(args.racine, fichiers)
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
                args.date, args.sha, args.image = lire_identite(args.identite)
            if None in (args.date, args.sha, args.image):
                raise Refus("--identite, ou bien --date, --sha et --image")
            # Les entrées sont lues et réduites avant toute écriture : un refus d'entrée ne laisse rien dans --vers
            # (le contrôle final de construire_jeu, lui, laisse les fichiers écrits, pour être lus).
            historique = lire_historique(args.historique)
            tables, ecartes = reduire_fichiers(args.releves, args.recherche, args.tirage, partie=args.partie, sauf=args.sauf or ())
            manifeste = construire_jeu(
                args.vers, historique, tables,
                {
                    "partie": {"numero": args.partie, "creee_le": args.creee_le, "nature": NATURE},
                    "capture": {"date": args.date, "sha_code": args.sha, "image": args.image, "commande": args.commande},
                },
            )
        except Refus as e:
            print("REFUS : %s" % e, file=sys.stderr)
            return 2
        for ecarte in ecartes:
            print("écarté (--sauf) : %s" % ecarte)
        print("Jeu d'essai écrit dans %s : %d table(s), %d octets hors manifeste." % (
            args.vers, sum(len(t) for t in tables.values()), manifeste["taille_octets"]))
        return 0
    if args.action == "manifeste":
        dossier = Path(args.dossier)
        try:
            try:
                manifeste = charger_json((dossier / MANIFESTE).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise Refus("%s absent ou illisible (%s : %s) : rien à refaire"
                            % (dossier / MANIFESTE, type(e).__name__, str(getattr(e, "strerror", None) or e)[:120]))
            if not isinstance(manifeste, dict):
                raise Refus("%s : objet attendu, %s trouvé" % (dossier / MANIFESTE, type(manifeste).__name__))
            refuser_resume_retouche(dossier, manifeste)
        except Refus as e:
            print("REFUS : %s" % e, file=sys.stderr)
            return 2
        ecrire_manifeste(dossier, manifeste)
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
