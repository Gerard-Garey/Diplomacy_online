#!/usr/bin/env python3
"""Couche R de la référence de non-régression (issue #31, critère 3) : un lot de recherches réelles comparé au résumé de la référence.

Bibliothèque standard seule, Python 3.7, hors conteneur ; aucune recherche n'est lancée
ici, ni site ni GPU. Le lot se capture à part (tests/mesure/capture_reference.py
commandes GAMEID --couche-r, puis rejeu_moteur.py, `cicero-orders` arrêté) : jamais en
CI ni dans un workflow, à la main, par la session principale. Deux commandes :

    python3 tests/reference_couche_r.py resumer <relevés> --vers <dossier du jeu> [--sauf MOTIF ...]
    python3 tests/reference_couche_r.py comparer <relevés du lot> [--jeu D] [--sortie F.json]
                                                 [--positions PHASE[:PUISSANCE] ...] [--seulement MOTIF] [--sauf MOTIF ...]

`resumer` écrit le résumé de la référence (repetee.json) dans le jeu d'essai et son bloc
au manifeste : SESSION PRINCIPALE SEULE, après visa (ADR 0006, décision 6). Il refuse un
jeu qui ne passe pas son contrôle, un résumé déjà là, et des relevés dont le tirage 0
n'est pas la table figée du jeu. `comparer` rend 0 (pas de régression), 1 (régression)
ou 2 (non concluant, lot invalide, relevé ou jeu illisible). --seulement et --sauf
choisissent les fichiers de relevés par leur nom (une position a un seul fichier : la
seconde passe d'une position s'écarte par --sauf '*passe2*').

Ce que la couche garantit. La couche D rejoue des fonctions pures sur des tables figées :
elle ne voit pas un changement de cicero_no_dialogue.prototxt, du patch du moteur, du
commit épinglé ni de l'image. La couche R compare des recherches réelles, refaites sur les
positions répétées de la référence, au résumé de leurs tirages d'origine.

Résumé d'une position, sur ses n recherches A sans engagement (un fichier de relevés) :
moyenne et écart type (à n - 1) de ln lambda et de la valeur de tête
(candidates[0].value) ; têtes observées et leurs effectifs ; pour chaque ordre « stable »
(dans order_values d'une majorité stricte des tirages) moyenne, écart type, effectif ;
S_ov, racine de la moyenne des variances des ordres stables ; S_G, racine de la moyenne
des variances de G(E, N) = order_values[N] - order_values[E] sur les couples d'ordres
stables d'une même unité (_order_loc du bot), tirages où les deux sont présents ; boost
et max_prob. Planchers, écrits dans le fichier : la médiane sur les positions de chacune
des quatre dispersions. Les moyennes sont écrites telles quelles, les dispersions à cinq
décimales : le lot fait des relevés de la référence elle-même en ressort « identique ».

Statistiques d'un lot de K recherches A, f = racine(1 / K + 1 / n) :
  T_lambda = |moyenne du lot de ln lambda - moyenne de référence| / (max(écart type, plancher) x f) ;
  T_v      = la même sur la valeur de tête ;
  T_ov     = médiane, sur les ordres stables présents dans au moins un tirage du lot, de
             |moyenne du lot - moyenne de référence|, divisée par max(S_ov, plancher) x f ;
  T_G      = médiane, sur les couples d'ordres stables couverts, de l'écart de G entre lot
             et référence, divisée par max(S_G, plancher) x f ;
  couverture = part des ordres stables présents dans au moins un tirage du lot ;
  tête     = nombre de tirages du lot dont la tête est la tête modale de la référence ;
  structure, sur toutes les lignes du lot (A et B), à l'identique : les contrôles de
             rejeu_moteur.py (`controles`), un seul appel à export_plans, search.boost et
             search.max_prob égaux à ceux de la référence.

Par position : « lot invalide » (couverture nulle : ce n'est pas la position) ;
« identique » (structure satisfaite, couverture entière, écarts nuls à 1e-12) ; « hors
tolérance » (un T > 5, couverture < 0,75, contrôle structurel en échec, ou tête de
référence unanime sur au moins 5 tirages et absente d'un lot d'au moins 3) ; « dans la
tolérance » sinon. Par exécution : « lot invalide » ; « régression » (un contrôle
structurel en échec, un T > 10, au moins 2 positions hors tolérance, ou le test des
signes : au moins k positions sur P bougent dans le même sens sur ln lambda, la valeur
de tête ou la médiane signée d'order_values, k étant le plus petit entier tel que
2 x P(Bin(P, 1/2) >= k) <= 0,01 -- 17 à 21 positions, inapplicable à moins de 8) ;
« non concluant » (exactement une position hors tolérance, une position attendue
absente, ou un lot de moins de 3 recherches A : relancer cette seule position, une fois ;
de nouveau hors tolérance, c'est une régression) ; « pas de régression » sinon.

Ce que cette couche n'est pas : les recherches B ne sont jugées que sur la structure
(elles ne sont pas indépendantes des A) ; rien sur Claude, sur les phases de retraite et
d'ajustement, sur une partie avancée ; une seule table comparée à la référence n'est pas
un critère. La sortie nomme ses limites (`limites`).
"""
import argparse
import fnmatch
import hashlib
import itertools
import json
import math
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True  # avant tout chargement de cicero/overlay (#27)

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(ICI / "mesure"))
import bruit_valeurs  # noqa: E402  (lecture des relevés, _order_loc du bot)
import commun  # noqa: E402
import reference_jeu  # noqa: E402

TAU = 5.0  # sur T_lambda, T_v, T_ov et T_G ; au-delà de 2 x TAU, une seule position fait une régression
COUVERTURE_MIN = 0.75
K_MIN = 3  # recherches A par position, en deçà : lot incomplet
N_TETE = 5  # la tête n'est jugée que si elle est unanime sur au moins N_TETE tirages de référence
N_MIN_REFERENCE = 3  # une position de moins de 3 recherches A n'est pas résumée (majorité stricte, écart type)
ALPHA_SIGNES = 0.01
NUL = 1e-12  # « identique » : écarts nuls à NUL
DECIMALES = 5  # des dispersions du résumé ; les moyennes gardent leur écriture exacte
GRANDEURS = (("lambda", "ln_lambda"), ("v_tete", "v_tete"), ("ov", "S_ov"), ("G", "S_G"))  # (T, plancher)
SIGNES = (("d_ln_lambda", "ln lambda"), ("d_v_tete", "valeur de tête"), ("d_ov_mediane_signee", "médiane signée d'order_values"))
# Contrôles de rejeu_moteur.controler, à l'identique.
CONTROLES_VRAIS = (
    "entree_exportee", "order_values_present", "candidates_present", "search_present", "politique_avant_relue",
    "table_dans_politique_avant", "tete_recalculee_egale_exportee", "tete_recalculee_egale_rendue",
    "tete_exportee_egale_rendue",
)
CONTROLES_FAUX = ("avertissement_table_inutilisable",)
CONTROLES_VIDES = ("actions_hors_politique_avant", "probabilites_differentes_de_la_politique_avant")
VERDICTS = ("identique", "dans la tolérance", "hors tolérance", "lot invalide")
DECISIONS = ("pas de régression", "régression", "non concluant", "lot invalide")
CODES = {"pas de régression": 0, "régression": 1, "non concluant": 2, "lot invalide": 2}
COMMANDE_RESUMER = "python3 tests/reference_couche_r.py resumer <relevés> --vers <dossier>"
# Sensibilité et fausses alertes : mesures d'expert-cicero du 2026-10-10 (spécification de la couche R, § 2.4),
# sur les 43 relevés de la campagne de capture, par un script d'étalonnage non versionné ; elles ne se
# recalculent pas d'un lot, et chaque phrase qui en cite un chiffre le dit.
LIMITES_MESUREES = (
    "un décalage commun à toutes les positions n'est vu que par le test des signes : + 0,01 sur toutes les valeurs a "
    "été détecté, + 0,005 ne l'a pas été (lot de 2 tirages contre un résumé de 3, mesure du 2026-10-10 ; script "
    "d'étalonnage non versionné)",
    "fausses alertes : sur 20 000 exécutions complètes simulées sous hypothèse nulle, aucune position hors tolérance et "
    "1,9 % de « régression » par le seul test des signes ; borne pessimiste (loi de Student à 4 degrés de liberté) : "
    "jusqu'à environ 30 % de « non concluant » et 5 % de « régression » ; le taux réel est entre les deux, non mesuré "
    "(script d'étalonnage non versionné)",
    "tau = 5 est au-dessus du maximum observé sous hypothèse nulle (4,72 sur 567 comparaisons non indépendantes) : ce "
    "n'est pas un centile estimé (script d'étalonnage non versionné)",
    "une partie, 1901 à 1903, phases de mouvement : rien sur les retraites, les ajustements, une partie avancée, ni "
    "sur Claude",
)


class ErreurLot(Exception):
    """Lot, résumé ou jeu inutilisable : un message pour l'utilisateur, pas une trace."""


# ---------------------------------------------------------------------------
# Calculs (fonctions pures)
# ---------------------------------------------------------------------------

def tirage(entree):
    """Ce que la couche lit d'une table exportée. Lève ErreurLot si la table n'a pas la forme attendue."""
    try:
        candidats, recherche = entree["candidates"], entree["search"]
        t = {
            "lam": float(recherche["lambda"]), "boost": recherche["boost"], "max_prob": recherche["max_prob"],
            "tete": tuple(candidats[0]["orders"]), "v_tete": float(candidats[0]["value"]),
            "ov": {ordre: float(valeur) for ordre, valeur in entree["order_values"].items()},
        }
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        raise ErreurLot("table sans candidates, search ou order_values lisibles (%s)" % type(e).__name__)
    if not t["lam"] > 0 or not math.isfinite(t["lam"]):
        raise ErreurLot("search.lambda = %r : un lambda fini, strictement positif, est attendu" % (recherche["lambda"],))
    # Une valeur non finie traverserait toute comparaison sans la faire échouer (nan > tau est faux).
    if not math.isfinite(t["v_tete"]):
        raise ErreurLot("valeur de tête non finie (candidates[0].value = %r)" % (candidats[0]["value"],))
    non_finies = sorted(ordre for ordre, valeur in t["ov"].items() if not math.isfinite(valeur))
    if non_finies:
        raise ErreurLot("order_values non fini pour %d ordre(s), dont %s" % (len(non_finies), non_finies[0]))
    return t


def moyenne(valeurs):
    return sum(valeurs) / len(valeurs)


def ecart_type(valeurs):
    """À n - 1 ; 0 pour une seule valeur."""
    if len(valeurs) < 2:
        return 0.0
    m = moyenne(valeurs)
    return math.sqrt(sum((x - m) ** 2 for x in valeurs) / (len(valeurs) - 1))


def couples(ordres, order_loc):
    """Couples (non ordonnés) d'ordres d'une même unité, dans l'ordre alphabétique."""
    par_unite = {}
    for ordre in sorted(ordres):
        unite = order_loc(ordre)
        if unite is not None:
            par_unite.setdefault(unite, []).append(ordre)
    return [c for _unite, les_siens in sorted(par_unite.items()) for c in itertools.combinations(les_siens, 2)]


def resumer_position(tirages, order_loc):
    """Le résumé d'une position sur ses tirages (sans arrondi) ; la forme est celle du fichier."""
    n = len(tirages)
    ln_lambda = [math.log(t["lam"]) for t in tirages]
    v_tete = [t["v_tete"] for t in tirages]
    presences = {}
    for t in tirages:
        for ordre in t["ov"]:
            presences[ordre] = presences.get(ordre, 0) + 1
    stables = {}
    for ordre, k in sorted(presences.items()):
        if 2 * k > n:  # majorité stricte
            valeurs = [t["ov"][ordre] for t in tirages if ordre in t["ov"]]
            stables[ordre] = [moyenne(valeurs), ecart_type(valeurs), k]
    variances_g = []
    for e, nouveau in couples(stables, order_loc):
        g = [t["ov"][nouveau] - t["ov"][e] for t in tirages if e in t["ov"] and nouveau in t["ov"]]
        if len(g) >= 2:
            variances_g.append(ecart_type(g) ** 2)
    tetes = {}
    for t in tirages:
        tetes[t["tete"]] = tetes.get(t["tete"], 0) + 1
    return {
        "n": n,
        "ln_lambda": [moyenne(ln_lambda), ecart_type(ln_lambda)],
        "v_tete": [moyenne(v_tete), ecart_type(v_tete)],
        # La tête modale d'abord ; à effectif égal, la première observée (ordre des tirages).
        "tetes": [{"orders": list(tete), "n": k} for tete, k in sorted(tetes.items(), key=lambda item: -item[1])],
        "order_values": stables,
        "S_ov": math.sqrt(moyenne([s * s for _m, s, _k in stables.values()])) if stables else 0.0,
        "S_G": math.sqrt(moyenne(variances_g)) if variances_g else 0.0,
        "boost": tirages[0]["boost"], "max_prob": tirages[0]["max_prob"],
    }


def planchers_des_positions(resumes):
    """Médiane, sur les positions, de chacune des quatre dispersions."""
    return {
        "ln_lambda": statistics.median(r["ln_lambda"][1] for r in resumes),
        "v_tete": statistics.median(r["v_tete"][1] for r in resumes),
        "S_ov": statistics.median(r["S_ov"] for r in resumes),
        "S_G": statistics.median(r["S_G"] for r in resumes),
    }


def arrondir(resume):
    """Le résumé tel qu'il s'écrit : dispersions à DECIMALES décimales, moyennes telles quelles."""
    def court(x):
        return round(x, DECIMALES)

    return dict(
        resume,
        ln_lambda=[resume["ln_lambda"][0], court(resume["ln_lambda"][1])],
        v_tete=[resume["v_tete"][0], court(resume["v_tete"][1])],
        order_values={ordre: [m, court(s), k] for ordre, (m, s, k) in resume["order_values"].items()},
        S_ov=court(resume["S_ov"]), S_G=court(resume["S_G"]),
    )


def echecs_des_controles(releve):
    """Contrôles structurels d'une ligne de relevé qui ne sont pas satisfaits (noms), hors boost et max_prob."""
    controles = releve.get("controles")
    if not isinstance(controles, dict):
        return ["controles absents"]
    echecs = [cle for cle in CONTROLES_VRAIS if controles.get(cle) is not True]
    echecs += [cle for cle in CONTROLES_FAUX if controles.get(cle) is not False]
    echecs += [cle for cle in CONTROLES_VIDES if controles.get(cle) != []]
    if releve.get("appels_export") != 1:
        echecs.append("appels_export = %r" % (releve.get("appels_export"),))
    return echecs


def echecs_de_recherche(recherches, reference):
    """search.boost et search.max_prob de chaque ligne du lot, égaux à ceux de la référence."""
    echecs = []
    for cle in ("boost", "max_prob"):
        autres = sorted({repr(r.get(cle) if isinstance(r, dict) else None) for r in recherches
                         if not isinstance(r, dict) or r.get(cle) != reference[cle]})
        if autres:
            echecs.append("search.%s = %s (référence : %r)" % (cle, ", ".join(autres), reference[cle]))
    return echecs


def _mediane(valeurs):
    """Médiane ; nan dès qu'une valeur n'est pas finie (statistics.median, qui trie, pourrait la laisser passer)."""
    return statistics.median(valeurs) if all(math.isfinite(x) for x in valeurs) else float("nan")


def _rapport(ecart, echelle):
    """écart / échelle ; une échelle nulle (dispersion et plancher nuls) ne pardonne aucun écart."""
    if ecart == 0:
        return 0.0
    return ecart / echelle if echelle > 0 else float("inf")


def comparer_position(reference, lot, order_loc, planchers, tau=TAU, structure=(), recherches=None):
    """Un lot de recherches A d'une position contre son résumé de référence.

    `lot` : les tirages (tirage()) des recherches A ; `structure` : les contrôles de relevé déjà
    trouvés en échec ; `recherches` : le bloc `search` de toutes les lignes du lot, A et B (par
    défaut, celui des tirages de `lot`). Rend les quatre T, les écarts bruts et le verdict."""
    if not lot:
        raise ErreurLot("aucune recherche A dans le lot")
    if not reference["order_values"]:
        raise ErreurLot("résumé de référence sans ordre stable")
    k_lot, n = len(lot), reference["n"]
    f = math.sqrt(1.0 / k_lot + 1.0 / n)
    modale = reference["tetes"][0]
    if recherches is None:
        recherches = [{"boost": t["boost"], "max_prob": t["max_prob"]} for t in lot]
    o = {
        "K": k_lot, "n": n, "f": f,
        "tete_reference": list(modale["orders"]), "tete_reference_effectif": modale["n"],
        "tete_lot": sum(1 for t in lot if list(t["tete"]) == list(modale["orders"])),
        "structure": list(structure) + echecs_de_recherche(recherches, reference),
    }
    o["tete_jugee"] = modale["n"] == n and n >= N_TETE and k_lot >= K_MIN
    o["d_ln_lambda"] = moyenne([math.log(t["lam"]) for t in lot]) - reference["ln_lambda"][0]
    o["T_lambda"] = _rapport(abs(o["d_ln_lambda"]), max(reference["ln_lambda"][1], planchers["ln_lambda"]) * f)
    o["d_v_tete"] = moyenne([t["v_tete"] for t in lot]) - reference["v_tete"][0]
    o["T_v_tete"] = _rapport(abs(o["d_v_tete"]), max(reference["v_tete"][1], planchers["v_tete"]) * f)
    du_lot = {
        ordre: moyenne([t["ov"][ordre] for t in lot if ordre in t["ov"]])
        for ordre in reference["order_values"] if any(ordre in t["ov"] for t in lot)
    }
    o["ordres_stables"], o["ordres_couverts"] = len(reference["order_values"]), len(du_lot)
    o["couverture"] = len(du_lot) / len(reference["order_values"])
    if not du_lot:
        o.update({
            "d_ov_mediane_signee": None, "ov_mediane": None, "ov_max": None, "T_ov": None,
            "G_mediane": None, "G_max": None, "T_G": None, "couples": 0,
            "hors": ["couverture"], "grossier": False, "verdict": "lot invalide",
        })
        return o
    ecarts = [du_lot[ordre] - reference["order_values"][ordre][0] for ordre in sorted(du_lot)]
    o["d_ov_mediane_signee"] = _mediane(ecarts)
    o["ov_mediane"] = _mediane([abs(x) for x in ecarts])
    o["ov_max"] = max(abs(x) for x in ecarts)
    o["T_ov"] = _rapport(o["ov_mediane"], max(reference["S_ov"], planchers["S_ov"]) * f)
    ecarts_g = [
        abs((du_lot[nouveau] - du_lot[e]) - (reference["order_values"][nouveau][0] - reference["order_values"][e][0]))
        for e, nouveau in couples(du_lot, order_loc)
    ]
    o["couples"] = len(ecarts_g)
    o["G_mediane"] = _mediane(ecarts_g) if ecarts_g else 0.0
    o["G_max"] = max(ecarts_g) if ecarts_g else 0.0
    o["T_G"] = _rapport(o["G_mediane"], max(reference["S_G"], planchers["S_G"]) * f)
    # « not T <= tau », et non « T > tau » : un T non fini (nan compris) met la position hors tolérance.
    hors = [nom for nom, _plancher in GRANDEURS if not o["T_" + nom] <= tau]
    if o["couverture"] < COUVERTURE_MIN:
        hors.append("couverture")
    if o["tete_jugee"] and o["tete_lot"] == 0:
        hors.append("tete")
    if o["structure"]:
        hors.append("structure")
    o["hors"] = hors
    o["grossier"] = any(not o["T_" + nom] <= 2 * tau for nom, _plancher in GRANDEURS)
    nuls = all(abs(o[cle]) <= NUL for cle in ("d_ln_lambda", "d_v_tete", "ov_max", "G_max"))
    if hors:
        o["verdict"] = "hors tolérance"
    elif nuls and o["couverture"] == 1.0:
        o["verdict"] = "identique"
    else:
        o["verdict"] = "dans la tolérance"
    return o


def sans_recherche_a(reference, structure):
    """Une position dont le lot n'a aucune recherche A lisible mais des contrôles en échec : rien n'est mesuré,
    la structure suffit à la mettre hors tolérance."""
    modale = reference["tetes"][0]
    o = {cle: None for cle in (
        "f", "d_ln_lambda", "T_lambda", "d_v_tete", "T_v_tete", "d_ov_mediane_signee", "ov_mediane", "ov_max", "T_ov",
        "G_mediane", "G_max", "T_G")}
    o.update({
        "K": 0, "n": reference["n"], "tete_reference": list(modale["orders"]), "tete_reference_effectif": modale["n"],
        "tete_lot": 0, "tete_jugee": False, "structure": list(structure), "ordres_stables": len(reference["order_values"]),
        "ordres_couverts": 0, "couverture": None, "couples": 0, "hors": ["structure"], "grossier": False,
        "verdict": "hors tolérance",
    })
    return o


def seuil_signes(positions, alpha=ALPHA_SIGNES):
    """(k, p) : le plus petit k tel que p = 2 x P(Bin(positions, 1/2) >= k) <= alpha ; (None, None) s'il n'y en a pas."""
    def combinaisons(n, k):
        return math.factorial(n) // (math.factorial(k) * math.factorial(n - k))

    for k in range(positions // 2 + 1, positions + 1):
        queue = 2 * sum(combinaisons(positions, j) for j in range(k, positions + 1))
        if queue <= alpha * 2 ** positions:
            return k, queue / 2.0 ** positions
    return None, None


def nom_position(position):
    return "%s %s" % position


def ordre_de_la_partie(position):
    """Clé de tri : la phase dans l'ordre de la partie, puis la puissance dans celui du jeu."""
    phase, puissance = position
    if not reference_jeu.est_phase(phase) or puissance not in reference_jeu.POWERS:
        return (1, 0, 0, phase, puissance)  # une position mal nommée se range à la fin, sans lever
    annee, saison = reference_jeu._ordre_des_phases(phase)
    return (0, annee, saison, phase, reference_jeu.POWERS.index(puissance))


def decider(par_position, attendues=None, k_min=K_MIN, tau=TAU):
    """La décision de l'exécution. `par_position` : {(phase, puissance): sortie de comparer_position}.

    `attendues` : les positions que l'exécution devait couvrir (par défaut, celles de `par_position`) ;
    `k_min` : nombre de recherches A en deçà duquel une position rend le lot incomplet."""
    attendues = sorted(par_position if attendues is None else attendues, key=ordre_de_la_partie)
    invalides = sorted((p for p, o in par_position.items() if o["verdict"] == "lot invalide"), key=ordre_de_la_partie)
    jugees = {p: o for p, o in par_position.items() if o["verdict"] != "lot invalide"}
    hors = sorted((p for p, o in jugees.items() if o["hors"]), key=ordre_de_la_partie)
    manquantes = [p for p in attendues if p not in par_position]
    courtes = sorted((p for p, o in jugees.items() if o["K"] < k_min), key=ordre_de_la_partie)
    mesurees = [o for o in jugees.values() if o["K"]]  # le test des signes ne lit que des écarts mesurés
    seuil, p_seuil = seuil_signes(len(mesurees))
    signes = {"positions": len(mesurees), "seuil": seuil, "p_du_seuil": p_seuil, "alpha": ALPHA_SIGNES, "grandeurs": {}}
    for cle, _libelle in SIGNES:
        plus = sum(1 for o in mesurees if o[cle] > 0)
        moins = sum(1 for o in mesurees if o[cle] < 0)
        signes["grandeurs"][cle] = {
            "plus": plus, "moins": moins, "declenche": seuil is not None and max(plus, moins) >= seuil}
    motifs = []
    en_structure = sorted((p for p, o in jugees.items() if o["structure"]), key=ordre_de_la_partie)
    grossieres = sorted((p for p, o in jugees.items() if o["grossier"]), key=ordre_de_la_partie)
    if en_structure:
        motifs.append("contrôle structurel en échec (%s)" % ", ".join(nom_position(p) for p in en_structure))
    if grossieres:
        motifs.append("un T au-delà de %g (%s)" % (2 * tau, ", ".join(nom_position(p) for p in grossieres)))
    if len(hors) >= 2:
        motifs.append("%d positions hors tolérance" % len(hors))
    for cle, libelle in SIGNES:
        g = signes["grandeurs"][cle]
        if g["declenche"]:
            motifs.append("test des signes sur %s : %d contre %d, seuil %d sur %d positions"
                          % (libelle, g["plus"], g["moins"], seuil, len(mesurees)))
    if invalides:
        decision = "lot invalide"
        motifs = ["couverture nulle, ce n'est pas la position attendue (%s)" % ", ".join(nom_position(p) for p in invalides)]
    elif motifs:
        decision = "régression"
    else:
        if len(hors) == 1:
            motifs.append("une position hors tolérance (%s) : la relancer seule, une fois ; de nouveau hors tolérance, "
                          "c'est une régression" % nom_position(hors[0]))
        if manquantes:
            motifs.append("lot incomplet : %d position(s) attendue(s) absente(s) (%s)"
                          % (len(manquantes), ", ".join(nom_position(p) for p in manquantes)))
        if courtes:
            motifs.append("lot incomplet : moins de %d recherches A (%s)"
                          % (k_min, ", ".join(nom_position(p) for p in courtes)))
        decision = "non concluant" if motifs else "pas de régression"
    return {
        "decision": decision, "motifs": motifs, "positions_comparees": len(par_position),
        "hors_tolerance": [nom_position(p) for p in hors], "invalides": [nom_position(p) for p in invalides],
        "manquantes": [nom_position(p) for p in manquantes], "moins_de_k_min": [nom_position(p) for p in courtes],
        "signes": signes,
    }


def tolerances_lisibles(reference, planchers, k_lot, tau=TAU):
    """Les tolérances d'une position en unités des grandeurs, pour un lot de `k_lot` recherches A."""
    f = math.sqrt(1.0 / k_lot + 1.0 / reference["n"])
    return {
        "ln_lambda": tau * f * max(reference["ln_lambda"][1], planchers["ln_lambda"]),
        "v_tete": tau * f * max(reference["v_tete"][1], planchers["v_tete"]),
        "order_values": tau * f * max(reference["S_ov"], planchers["S_ov"]),
        "G": tau * f * max(reference["S_G"], planchers["S_G"]),
    }


def limites(references, planchers, par_position, sans_recherche_b):
    """Ce que la comparaison ne voit pas, en phrases : la sortie les porte toujours."""
    l = []
    tolerances = [tolerances_lisibles(references[p], planchers, o["K"]) for p, o in sorted(par_position.items())
                  if p in references and o["K"]]
    if tolerances:
        l.append(
            "un changement limité à une position et inférieur à sa tolérance n'est pas vu : sur ce lot, selon la "
            "position, de %.3f à %.3f sur la médiane d'order_values, de %.3f à %.3f sur la valeur de tête, de %.3f à "
            "%.3f sur la médiane de G, et un facteur de %.2f à %.2f sur lambda"
            % (min(t["order_values"] for t in tolerances), max(t["order_values"] for t in tolerances),
               min(t["v_tete"] for t in tolerances), max(t["v_tete"] for t in tolerances),
               min(t["G"] for t in tolerances), max(t["G"] for t in tolerances),
               math.exp(min(t["ln_lambda"] for t in tolerances)), math.exp(max(t["ln_lambda"] for t in tolerances))))
    l.extend(LIMITES_MESUREES)
    l.append("les recherches B ne sont jugées que sur la structure : elles ne sont pas indépendantes des recherches A")
    if sans_recherche_b:
        l.append("lot sans recherche B : renfort non contrôlé")
    return l


# ---------------------------------------------------------------------------
# Lecture : relevés du lot, résumé du jeu
# ---------------------------------------------------------------------------

def _retenu(nom, seulement, sauf):
    return (seulement is None or fnmatch.fnmatch(nom, seulement)) and not any(fnmatch.fnmatch(nom, motif) for motif in sauf)


def lire_lot(dossier, order_loc, seulement=None, sauf=()):
    """Le lot d'un dossier de relevés de rejeu_moteur.py : (positions, lecture).

    `positions` : {(phase, puissance): {"A": tirages des recherches A sans engagement, dans l'ordre des
    tirages ; "tables" : leurs tables ; "recherches" : le bloc search de chaque ligne, A et B ;
    "structure" : contrôles de relevé en échec ; "lignes", "lignes_b", "fichier"}}. La lecture des
    tables est celle de bruit_valeurs.lire_releves ; les contrôles (`controles`, `appels_export`)
    sont relus ligne à ligne. Lève ErreurLot (ou bruit_valeurs.ErreurReleve) sur un lot inutilisable."""
    dossier = Path(dossier)
    if not dossier.is_dir():
        raise ErreurLot("%s n'est pas un dossier" % dossier)
    fichiers = [f for f in sorted(dossier.glob(bruit_valeurs.MOTIF)) if _retenu(f.name, seulement, sauf)]
    if not fichiers:
        raise ErreurLot("aucun relevé %s retenu dans %s (--seulement, --sauf)" % (bruit_valeurs.MOTIF, dossier))
    # Seuls les fichiers retenus sont lus : un relevé écarté par --sauf peut être illisible. lire_releves lit un
    # dossier entier ; il reçoit un dossier temporaire de liens vers les fichiers retenus, sous leurs noms.
    with tempfile.TemporaryDirectory(prefix="couche_r_") as vue:
        for fichier in fichiers:
            os.symlink(str(fichier.resolve()), os.path.join(vue, fichier.name))
        try:
            tables, lecture = bruit_valeurs.lire_releves(vue, order_loc)
        except bruit_valeurs.ErreurReleve as e:
            raise ErreurLot(str(e).replace(vue, str(dossier)))
    if lecture["tables_d_essai_a_sec"]:
        raise ErreurLot("%d table(s) d'essai à sec (doublure du moteur) : ce ne sont pas des recherches" % lecture["tables_d_essai_a_sec"])
    noms = {f.name for f in fichiers}
    positions, parties = {}, set()
    for fichier in fichiers:
        for releve in commun.lire_lignes(fichier):
            if "comparaison" in releve:
                continue
            position = (str(releve["phase"]), str(releve["puissance"]))
            parties.add(str(releve["game_id"]))
            p = positions.setdefault(position, {
                "A": [], "tables": [], "recherches": [], "structure": [], "lignes": 0, "lignes_b": 0, "fichier": fichier.name})
            if p["fichier"] != fichier.name:
                raise ErreurLot("deux fichiers pour la position %s (%s, %s) : un lot en a un seul par position ; en "
                                "écarter un par --sauf ou --seulement" % (nom_position(position), p["fichier"], fichier.name))
            p["lignes"] += 1
            p["lignes_b"] += releve["recherche"] == bruit_valeurs.TYPE_AVEC_ENGAGEMENT
            entree = releve.get("entree")
            p["recherches"].append(entree.get("search") if isinstance(entree, dict) else None)
            for echec in echecs_des_controles(releve):
                if echec not in p["structure"]:
                    p["structure"].append(echec)
    de_a = [t for t in bruit_valeurs.tables_du_niveau(tables, bruit_valeurs.NIVEAU_DE_LA_SPECIFICATION) if t["fichier"] in noms]
    for t in sorted(de_a, key=lambda t: (t["fichier"], t["tirage"] is None, t["tirage"] or 0, t["nom"])):
        p = positions[t["position"][1:]]
        try:
            p["A"].append(tirage(t["entree"]))
            p["tables"].append(t["entree"])
        except ErreurLot as e:  # une table que la couche ne sait pas lire est un échec de structure, pas un arrêt
            p["structure"].append("%s : %s" % (t["nom"], e))
    return positions, {
        "dossier": str(dossier), "fichiers": [f.name for f in fichiers], "parties": sorted(parties),
        "lignes": sum(p["lignes"] for p in positions.values()),
        "recherches_a": sum(len(p["A"]) for p in positions.values()),
        "recherches_b": sum(p["lignes_b"] for p in positions.values()),
    }


def lot_des_tables(tables):
    """Un lot d'une recherche par position, fait de tables exportées : {phase: {puissance: table}} -> positions.

    Sans relevé, donc sans contrôle de relevé : la structure ne porte que sur search.boost et search.max_prob."""
    return {
        (phase, puissance): {
            "A": [tirage(table)], "tables": [table], "recherches": [table.get("search")], "structure": [],
            "lignes": 1, "lignes_b": 0, "fichier": None}
        for phase, par_puissance in tables.items() for puissance, table in par_puissance.items()
    }


def references_du_resume(resume):
    """{(phase, puissance): résumé de la position} d'un résumé lu ou construit."""
    return {(phase, puissance): r for phase, par_puissance in resume["positions"].items() for puissance, r in par_puissance.items()}


def comparer_lot(positions, resume, order_loc, attendues=None, k_min=K_MIN, tau=TAU):
    """Un lot (lire_lot, lot_des_tables) contre un résumé : (par position, décision, positions hors couche R).

    `attendues` : les positions que l'exécution devait couvrir ; par défaut, toutes celles du résumé."""
    references = references_du_resume(resume)
    attendues = sorted(references if attendues is None else attendues, key=ordre_de_la_partie)
    par_position = {}
    for position in attendues:
        lot = positions.get(position)
        if lot is None or not (lot["A"] or lot["structure"]):
            continue
        if not lot["A"]:
            par_position[position] = sans_recherche_a(references[position], lot["structure"])
            continue
        par_position[position] = comparer_position(
            references[position], lot["A"], order_loc, resume["planchers"], tau, lot["structure"], lot["recherches"])
    hors_couche = sorted((p for p in positions if p not in references), key=ordre_de_la_partie)
    return par_position, decider(par_position, attendues, k_min, tau), hors_couche


# ---------------------------------------------------------------------------
# Tableau lisible
# ---------------------------------------------------------------------------

def _t(x):
    return "-" if x is None else "%.2f" % x


def _d(x, chiffres=4):
    return "-" if x is None else "%+.*f" % (chiffres, x)


def tableau(par_position, decision, hors_couche, lecture, bornes):
    l = ["Couche R : lot de recherches réelles contre le résumé de la référence (#31)"]
    if lecture:
        l.append("  lot : %s -- %d fichier(s), %d ligne(s), %d recherche(s) A, %d recherche(s) B ; partie(s) %s"
                 % (lecture["dossier"], len(lecture["fichiers"]), lecture["lignes"], lecture["recherches_a"],
                    lecture["recherches_b"], ", ".join(lecture["parties"])))
    l.append("  tolérance : T <= %g sur les quatre grandeurs, couverture >= %s ; T = écart / (max(dispersion de "
             "référence, plancher) x racine(1 / K + 1 / n))" % (TAU, COUVERTURE_MIN))
    l.append("  %-16s %-18s %2s %6s %6s %6s %6s %9s %9s %9s %9s %-22s %6s  %s" % (
        "position", "verdict", "K", "T_lam", "T_v", "T_ov", "T_G", "d ln lam", "d v tête", "méd|d ov|", "méd|d G|",
        "tête (lot ; réf.)", "couv.", "structure"))
    for position, o in sorted(par_position.items(), key=lambda item: ordre_de_la_partie(item[0])):
        tete = "%d/%d ; %d/%d%s" % (o["tete_lot"], o["K"], o["tete_reference_effectif"], o["n"],
                                    "" if o["tete_jugee"] else ", non jugée")
        l.append("  %-16s %-18s %2d %6s %6s %6s %6s %9s %9s %9s %9s %-22s %6s  %s" % (
            nom_position(position), o["verdict"], o["K"], _t(o["T_lambda"]), _t(o["T_v_tete"]), _t(o["T_ov"]), _t(o["T_G"]),
            _d(o["d_ln_lambda"]), _d(o["d_v_tete"]), "-" if o["ov_mediane"] is None else "%.4f" % o["ov_mediane"],
            "-" if o["G_mediane"] is None else "%.4f" % o["G_mediane"], tete, _t(o["couverture"]),
            "satisfaite" if not o["structure"] else "ÉCHEC : " + " ; ".join(o["structure"])))
        if o["hors"]:
            l.append("  %-16s   hors tolérance sur : %s" % ("", ", ".join(o["hors"])))
    if not par_position:
        l.append("  aucune position comparée")
    if hors_couche:
        l.append("  hors couche R (positions du lot sans résumé de référence), ignorées : %s"
                 % ", ".join(nom_position(p) for p in hors_couche))
    signes = decision["signes"]
    if signes["seuil"] is None:
        l.append("  test des signes : inapplicable à %d position(s) (aucun seuil n'atteint %s ; il en faut au moins 8)"
                 % (signes["positions"], signes["alpha"]))
    else:
        l.append("  test des signes (%d positions, seuil %d dans le même sens, p = %.4f) : %s" % (
            signes["positions"], signes["seuil"], signes["p_du_seuil"], " ; ".join(
                "%s %d contre %d%s" % (libelle, signes["grandeurs"][cle]["plus"], signes["grandeurs"][cle]["moins"],
                                       " -- DÉCLENCHÉ" if signes["grandeurs"][cle]["declenche"] else "")
                for cle, libelle in SIGNES)))
    l.append("Décision : %s" % decision["decision"].upper())
    for motif in decision["motifs"]:
        l.append("  %s" % motif)
    l.append("Limites :")
    for limite in bornes:
        l.append("  - %s." % limite)
    return "\n".join(l)


# ---------------------------------------------------------------------------
# Commandes
# ---------------------------------------------------------------------------

def lire_positions(valeurs, references):
    """« S1902M » ou « S1902M:FRANCE » -> positions du résumé ; lève ErreurLot si l'une n'y est pas."""
    positions = []
    for valeur in valeurs:
        phase, _, puissance = valeur.partition(":")
        trouvees = [p for p in sorted(references, key=ordre_de_la_partie) if p[0] == phase and puissance.upper() in ("", p[1])]
        if not trouvees:
            raise ErreurLot("--positions %s : aucune position du résumé de référence" % valeur)
        positions += [p for p in trouvees if p not in positions]
    return positions


def lire_reference(dossier):
    """(jeu, résumé) d'un jeu d'essai contrôlé ; lève ErreurLot s'il manque, ne passe pas son contrôle ou n'a pas de résumé."""
    dossier = Path(dossier)
    try:
        jeu = reference_jeu.lire_jeu(dossier)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ErreurLot("jeu d'essai illisible dans %s (%s : %s)" % (dossier, type(e).__name__, str(e)[:120]))
    if jeu is None:
        raise ErreurLot("%s est absent ou vide : pas de référence" % dossier)
    violations = reference_jeu.controler(dossier)
    if violations:
        raise ErreurLot("le jeu d'essai de %s ne passe pas son contrôle (%d violation(s), dont : %s)"
                        % (dossier, len(violations), violations[0]))
    return jeu, reference_jeu.lire_repetee(dossier)


def _meme_partie(lecture, jeu):
    numero = str(jeu["manifeste"]["partie"]["numero"])
    if lecture["parties"] != [numero]:
        raise ErreurLot("lot de la partie %s, référence de la partie %s : ce n'est pas le même jeu de positions"
                        % (", ".join(lecture["parties"]), numero))


def commande_comparer(args, order_loc):
    jeu, resume = lire_reference(args.jeu)
    if resume is None:
        raise ErreurLot("%s n'a pas de résumé des positions répétées (%s) : à poser par la session principale, après "
                        "visa (%s)" % (args.jeu, reference_jeu.REPETEE, COMMANDE_RESUMER))
    positions, lecture = lire_lot(args.releves, order_loc, args.seulement, args.sauf or ())
    _meme_partie(lecture, jeu)
    references = references_du_resume(resume)
    attendues = lire_positions(args.positions, references) if args.positions else None
    par_position, decision, hors_couche = comparer_lot(positions, resume, order_loc, attendues)
    bornes = limites(references, resume["planchers"], par_position, not lecture["recherches_b"])
    print(tableau(par_position, decision, hors_couche, lecture, bornes))
    if args.sortie:
        detail = {
            "mesure": "couche R de la référence de non-régression (#31)",
            "parametres": {"tau": TAU, "couverture_min": COUVERTURE_MIN, "k_min": K_MIN, "alpha_signes": ALPHA_SIGNES,
                           "planchers": resume["planchers"]},
            "lot": lecture, "reference": jeu["manifeste"].get("repetee"),
            "positions": {nom_position(p): o for p, o in sorted(par_position.items(), key=lambda item: ordre_de_la_partie(item[0]))},
            "hors_couche_r": [nom_position(p) for p in hors_couche],
            "decision": decision, "limites": bornes,
        }
        try:
            Path(args.sortie).parent.mkdir(parents=True, exist_ok=True)
            Path(args.sortie).write_text(json.dumps(detail, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except OSError as e:
            raise ErreurLot("%s : écriture impossible (%s)" % (args.sortie, e))
        print("\nDétail complet : %s" % args.sortie)
    return CODES[decision["decision"]]


def empreinte_des_releves(dossier, noms):
    """SHA-256 de la liste « nom, SHA-256 du fichier » des relevés retenus, triée : qui a les relevés la recalcule."""
    liste = "".join("%s %s\n" % (nom, hashlib.sha256((Path(dossier) / nom).read_bytes()).hexdigest()) for nom in sorted(noms))
    return hashlib.sha256(liste.encode("utf-8")).hexdigest()


def construire_resume(positions, order_loc):
    """(résumé tel qu'il s'écrit, positions écartées faute de tirages) d'un lot de référence."""
    retenues = {p: lot for p, lot in positions.items() if len(lot["A"]) >= N_MIN_REFERENCE}
    if not retenues:
        raise ErreurLot("aucune position d'au moins %d recherches A sans engagement" % N_MIN_REFERENCE)
    bruts = {p: resumer_position(lot["A"], order_loc) for p, lot in retenues.items()}
    sans_ordre = sorted(p for p, r in bruts.items() if not r["order_values"])
    if sans_ordre:
        raise ErreurLot("position(s) sans ordre stable : %s" % ", ".join(nom_position(p) for p in sans_ordre))
    resume = {
        "planchers": {cle: round(valeur, DECIMALES) for cle, valeur in planchers_des_positions(list(bruts.values())).items()},
        "positions": {},
    }
    for phase, puissance in sorted(bruts, key=ordre_de_la_partie):
        resume["positions"].setdefault(phase, {})[puissance] = arrondir(bruts[(phase, puissance)])
    return resume, sorted((p for p in positions if p not in retenues), key=ordre_de_la_partie)


def commande_resumer(args, order_loc):
    dossier = Path(args.vers)
    jeu, deja = lire_reference(dossier)
    if deja is not None:
        raise ErreurLot("%s existe déjà : un résumé ne s'écrit pas par-dessus un autre ; le supprimer d'abord, puis "
                        "`reference_jeu.py manifeste` (session principale, après visa)" % (dossier / reference_jeu.REPETEE))
    positions, lecture = lire_lot(args.releves, order_loc, args.seulement, args.sauf or ())
    _meme_partie(lecture, jeu)
    # Une référence ne se résume pas sur des relevés en échec : contrôle de relevé, table illisible, valeur non finie.
    en_echec = sorted((p for p, lot in positions.items() if lot["structure"]), key=ordre_de_la_partie)
    if en_echec:
        raise ErreurLot("relevés en échec de structure pour %d position(s), rien n'est écrit : %s"
                        % (len(en_echec), " ; ".join("%s (%s)" % (nom_position(p), positions[p]["structure"][0]) for p in en_echec)))
    resume, ecartees = construire_resume(positions, order_loc)
    # Le résumé est celui des tirages dont le jeu a figé le premier : la recherche A du tirage 0 est la table du jeu.
    retenues = sorted(references_du_resume(resume), key=ordre_de_la_partie)
    differentes = []
    for phase, puissance in retenues:
        table = jeu["tables"].get(phase, {}).get(puissance)
        premiere = positions[(phase, puissance)]["tables"][0]
        if table is None or any(table.get(cle) != premiere.get(cle) for cle in ("order_values", "candidates", "search")):
            differentes.append(nom_position((phase, puissance)))
    if differentes:
        raise ErreurLot("la recherche A du tirage 0 n'est pas la table figée du jeu pour %d position(s) sur %d (%s) : "
                        "ces relevés ne sont pas ceux de la référence"
                        % (len(differentes), len(retenues), ", ".join(differentes)))
    import reference_couche_d as couche_d  # état du dépôt, lu comme pour les attendus de la couche D
    modifies = couche_d.arbre_modifie()
    sha = args.sha or couche_d.sha_du_depot()
    if sha is None:
        raise ErreurLot("git ne répond pas ; donner --sha (SHA complet du code qui résume)")
    if modifies is None and not args.sha:
        raise ErreurLot("l'état de l'arbre de travail est inconnu ; donner --sha")
    if modifies:
        if not args.arbre_modifie:
            raise ErreurLot("arbre de travail modifié sous %s, hors %s (%d fichier(s), dont %s) : commiter d'abord, ou "
                            "--arbre-modifie (le SHA est alors suivi de « -modifie »)"
                            % (" et ".join(couche_d.MESURES), couche_d.HORS_MESURES, len(modifies), modifies[0].strip()))
        sha += "-modifie"
    fichiers = sorted({positions[p]["fichier"] for p in retenues})
    reference_jeu.ecrire_json(dossier / reference_jeu.REPETEE, resume)
    reference_jeu.ecrire_manifeste(dossier, dict(jeu["manifeste"], repetee={
        "date": args.date or time.strftime("%Y-%m-%d"), "sha_code": sha, "commande": COMMANDE_RESUMER,
        "releves": {
            "fichiers": len(fichiers), "recherches": sum(len(positions[p]["A"]) for p in retenues),
            "sha256": empreinte_des_releves(args.releves, fichiers),
        },
    }))
    violations = reference_jeu.controler(dossier)
    for violation in violations:
        print("ÉCHEC : %s" % violation)
    print("Résumé de %d position(s) écrit dans %s (%d octets ; code %s)." % (
        len(retenues), dossier / reference_jeu.REPETEE, (dossier / reference_jeu.REPETEE).stat().st_size, sha))
    print("  %d fichier(s) de relevés, %d recherche(s) A ; tirage 0 égal à la table figée du jeu : %d position(s) sur %d."
          % (len(fichiers), sum(len(positions[p]["A"]) for p in retenues), len(retenues), len(retenues)))
    print("  planchers : %s" % ", ".join("%s %s" % (cle, resume["planchers"][cle]) for cle in reference_jeu.CLES_PLANCHERS))
    if ecartees:
        print("  %d position(s) de moins de %d recherches A, hors couche R : %s"
              % (len(ecartees), N_MIN_REFERENCE, ", ".join(nom_position(p) for p in ecartees)))
    return 1 if violations else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commandes = p.add_subparsers(dest="action")
    r = commandes.add_parser("resumer", help="écrit le résumé de la référence dans le jeu (session principale, après visa)")
    c = commandes.add_parser("comparer", help="compare un lot de recherches réelles au résumé de la référence")
    for commande in (r, c):
        commande.add_argument("releves", help="dossier des relevés m1_*.jsonl de rejeu_moteur.py")
        commande.add_argument("--seulement", metavar="MOTIF", help="ne retient que les fichiers de ce nom (motif du shell)")
        commande.add_argument("--sauf", metavar="MOTIF", action="append", help="écarte les fichiers de ce nom (répétable)")
        commande.add_argument("--bot", help="chemin de claude_dialogue_bot.py (défaut : celui du dépôt, sinon de l'image)")
    r.add_argument("--vers", required=True, help="dossier du jeu d'essai (tests/reference)")
    r.add_argument("--sha", help="SHA complet du code (défaut : git rev-parse HEAD)")
    r.add_argument("--arbre-modifie", action="store_true", help="accepte un arbre de travail modifié, noté par « -modifie »")
    r.add_argument("--date", help="date AAAA-MM-JJ (défaut : aujourd'hui)")
    c.add_argument("--jeu", default=str(reference_jeu.DOSSIER), help="dossier du jeu d'essai (défaut : tests/reference)")
    c.add_argument("--positions", nargs="+", metavar="PHASE[:PUISSANCE]",
                   help="positions que l'exécution devait couvrir (défaut : toutes celles du résumé)")
    c.add_argument("--sortie", help="écrit le détail dans ce fichier JSON (hors dépôt : il nomme les ordres d'une partie)")
    args = p.parse_args(argv)
    if args.action is None:
        p.print_help()
        return 2
    try:
        _marge, order_loc, _bot = bruit_valeurs.charger_regle(args.bot)
        return commande_resumer(args, order_loc) if args.action == "resumer" else commande_comparer(args, order_loc)
    except (ErreurLot, bruit_valeurs.ErreurReleve) as e:
        print("couche R : %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
