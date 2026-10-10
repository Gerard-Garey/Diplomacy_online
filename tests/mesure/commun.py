"""Outils communs aux scripts de mesure de la branche claude/promesses (hors dépôt).

Python 3.7 (image cicero-webdip). Rien ici n'écrit hors du dossier de mesure
(MESURE_DIR, /mesure par défaut dans un conteneur, le dossier du script sinon).

Hors conteneur (essais à sec), les modules de Cicero sont absents : des
doublures les remplacent, comme dans tests/banc_promesses.py.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import types
from pathlib import Path

ICI = Path(__file__).resolve().parent
if Path("/opt/cicero/fairdiplomacy").is_dir() and "/opt/cicero" not in sys.path:
    sys.path.insert(0, "/opt/cicero")  # l'image : les scripts sont lancés depuis /mesure
MESURE_DIR = Path(os.environ.get("MESURE_DIR", "/mesure" if Path("/mesure").is_dir() else str(ICI)))
RESULTATS = MESURE_DIR / "resultats"
TRAVAIL = MESURE_DIR / "travail"

# Volume partagé de production : aucun script de mesure ne doit y écrire.
VOLUME_PRODUCTION = "webdip_logs_test"
CONF_SITE = Path("/opt/cicero/conf/c07_play_webdip/play_cicero_full_test.prototxt")
POWERS = ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "ITALY", "RUSSIA", "TURKEY"]
SCORE_PROB_FLOOR = 1e-6

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


def normalize_order_spacing(order):
    return re.sub(r"(?<=\S)-(?=\S)", " - ", order.strip())


def get_unit_location(order):
    pieces = order.split()
    assert len(pieces) >= 2
    return pieces[1]


def cicero_present():
    """Vrai dans l'image (fairdiplomacy compilé), faux sur le poste."""
    try:
        import fairdiplomacy.pydipcc  # noqa: F401
        return True
    except Exception:
        return False


def installer_doublures():
    """Doublures des modules de Cicero, pour les essais à sec hors conteneur."""
    from typing import Dict, Tuple
    from unittest import mock

    for nom in DOUBLURES:
        parties = nom.split(".")
        for i in range(1, len(parties) + 1):
            sys.modules[".".join(parties[:i])] = mock.MagicMock()
    typedefs = types.ModuleType("fairdiplomacy.typedefs")
    typedefs.Order = typedefs.Power = typedefs.Location = str
    typedefs.Action = Tuple[str, ...]
    typedefs.PowerPolicies = Dict[str, Dict[Tuple[str, ...], float]]
    orders = types.ModuleType("fairdiplomacy.utils.orders")
    orders.normalize_order_spacing = normalize_order_spacing
    orders.get_unit_location = get_unit_location
    sys.modules["fairdiplomacy.typedefs"] = typedefs
    sys.modules["fairdiplomacy.utils.orders"] = orders


def charger(nom, chemin):
    """Charge un fichier Python comme module `nom`, sans le mettre dans sys.modules."""
    spec = importlib.util.spec_from_file_location(nom, str(chemin))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(chemin):
    return hashlib.sha256(Path(chemin).read_bytes()).hexdigest()


def refuser_volume_production(*chemins):
    for chemin in chemins:
        if VOLUME_PRODUCTION in Path(str(chemin)).resolve().parts:
            raise SystemExit("REFUS : %s est dans le volume de production (%s)" % (chemin, VOLUME_PRODUCTION))


def ecrire_json(chemin, donnees):
    chemin = Path(chemin)
    refuser_volume_production(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    with open(str(tmp), "w") as f:
        json.dump(donnees, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(chemin))


def ajouter_ligne(chemin, donnees):
    """Ajoute une ligne JSON et la force sur disque (un relevé par ligne)."""
    chemin = Path(chemin)
    refuser_volume_production(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(str(chemin), "a") as f:
        f.write(json.dumps(donnees, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def lire_lignes(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        return []
    return [json.loads(ligne) for ligne in chemin.read_text().splitlines() if ligne.strip()]


def horodatage():
    return time.strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# Table exportée (candidates, search)
# ---------------------------------------------------------------------------

def score(valeur, q, lam):
    import math
    return valeur + lam * math.log(max(q, SCORE_PROB_FLOOR))


def tete(candidates, q_par_action, lam):
    """Action de plus haut score, la première de la table en cas d'égalité
    (règle de pseudo_commitments.engine_head_action), et l'écart au second score."""
    lignes = [(tuple(c["orders"]), score(c["value"], q_par_action[tuple(c["orders"])], lam)) for c in candidates]
    meilleure = lignes[0]
    for ligne in lignes[1:]:
        if ligne[1] > meilleure[1]:
            meilleure = ligne
    autres = sorted((s for a, s in lignes if a != meilleure[0]), reverse=True)
    return meilleure[0], (meilleure[1] - autres[0]) if autres else None


def tenues(action, promesses):
    return len(set(promesses).intersection(action))


def ordres_par_unite(candidates):
    """{unité: [ordres distincts]}, dans l'ordre de première apparition dans la table."""
    par_unite = {}
    for c in candidates:
        for o in c["orders"]:
            liste = par_unite.setdefault(get_unit_location(o), [])
            if o not in liste:
                liste.append(o)
    return par_unite


def choisir_engagements(entree, mode):
    """Engagements fabriqués à partir d'une première recherche sans engagement.

    "prefere"     : un ordre du plan préféré (plans[0]) que le plan de rang 2 ne
                    joue pas, à défaut le premier ordre du plan préféré qui
                    n'est pas commun à toutes les actions candidates ;
    "alternative" : l'ordre par lequel la première alternative (plans[1], sinon
                    la suivante) s'écarte du plan préféré.
    Rend ([ordres], explication). Liste vide si la table n'offre pas le cas.
    """
    plans = entree.get("plans") or []
    if not plans:
        return [], "aucun plan exporté"
    prefere = plans[0]["orders"]
    autres = [p["orders"] for p in plans[1:]]
    if mode == "prefere":
        for alt in autres:
            propres = [o for o in prefere if o not in alt]
            if propres:
                return [propres[0]], "ordre du plan préféré absent du plan %s" % alt
        tous = [c["orders"] for c in entree.get("candidates") or []]
        for o in prefere:
            if any(o not in a for a in tous):
                return [o], "ordre du plan préféré, non commun à toutes les actions candidates"
        return [prefere[0]], "premier ordre du plan préféré (toutes les actions le jouent : renfort sans effet)"
    if mode == "alternative":
        for alt in autres:
            propres = [o for o in alt if o not in prefere]
            if propres:
                return [propres[0]], "ordre de l'alternative %s absent du plan préféré" % alt
        return [], "aucune alternative ne s'écarte du plan préféré"
    raise ValueError(mode)


# ---------------------------------------------------------------------------
# Site (lecture seule)
# ---------------------------------------------------------------------------

def url_api():
    return os.environ.get("WEBDIP_API_URL", "http://webserver/api.php")


def cles_du_site():
    """Clés d'API des comptes bots, lues dans la configuration de l'image
    (play_webdip.api_key de play_cicero_full_test.prototxt), jamais écrites ici.
    MESURE_API_KEYS (liste séparée par des virgules) les remplace."""
    if os.environ.get("MESURE_API_KEYS"):
        return [c.strip() for c in os.environ["MESURE_API_KEYS"].split(",") if c.strip()]
    texte = CONF_SITE.read_text()
    trouve = re.search(r'api_key:\s*"([^"]+)"', texte)
    if not trouve:
        raise SystemExit("clé d'API introuvable dans %s" % CONF_SITE)
    return [c.strip() for c in trouve.group(1).split(",") if c.strip()]


def trouver_contexte(game_id, puissance):
    """Context (gameID, countryID, api_url, api_key) du compte qui tient
    `puissance` dans la partie : route players/active_games (GET), comme
    claude_dialogue_bot.get_active_games."""
    from fairdiplomacy.data.build_dataset import COUNTRY_ID_TO_POWER_OR_ALL
    from fairdiplomacy.typedefs import Context
    from fairdiplomacy_external.webdip_api import ACTIVE_GAMES_ROUTE, get_req

    for cle in cles_du_site():
        reponse = get_req(url_api(), {"route": ACTIVE_GAMES_ROUTE}, cle)
        for g in json.loads(reponse.content).get("games", []):
            if int(g["gameID"]) == int(game_id) and COUNTRY_ID_TO_POWER_OR_ALL[g["countryID"]] == puissance:
                return Context(gameID=int(game_id), countryID=g["countryID"], api_url=url_api(), api_key=cle)
    raise SystemExit("aucun compte bot ne tient %s dans la partie %s" % (puissance, game_id))
