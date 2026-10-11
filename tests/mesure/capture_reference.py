"""Capture du jeu d'essai figé de la référence de non-régression (issue #31, ADR 0006).

Trois outils, dont rejeu_moteur.py se sert (--historique, relevé `arguments_export`) :

  historique d'une partie   les ordres joués, par phase et par puissance, en notation
                            du moteur, lus dans le statut du site (GET game/status) ;
  position depuis l'historique seul, sans site : pydipcc rejoue les ordres ;
  arguments bruts d'export_plans : l'appel est doublé dans l'espace de noms de
                            l'agent, le moteur n'est pas modifié.

À lancer dans un conteneur éphémère de l'image cicero-webdip:latest (Python 3.7) :

    python /mesure/capture_reference.py historique GAMEID --sortie /mesure/resultats/historique_GAMEID.json
    python /mesure/capture_reference.py comparer GAMEID --historique /mesure/resultats/historique_GAMEID.json
    python3 tests/mesure/capture_reference.py commandes GAMEID [--phases ...] [--repetees PHASE[:PUISSANCE] ...] [--tirages 5]   (sur le poste)
    python3 tests/mesure/capture_reference.py commandes GAMEID --couche-r [--tirages 5] [--reseau NOM]   (lot de la couche R)
    python3 tests/mesure/capture_reference.py identite --dossier D --sha SHA --image ID     (sur le poste, au lancement)

`historique` et `comparer` lisent le site (GET seulement) et ne lancent aucune
recherche. `comparer` vérifie, phase par phase, que la position rejouée
depuis l'historique est celle que rend le site (get_state, clé du plateau).
`commandes` n'accède à rien : il imprime les commandes de la campagne de capture, ou,
avec --couche-r, celles d'un lot de la couche R (les positions répétées, rejouées pour
tests/reference_couche_r.py comparer ; tests/mesure/lancer_couche_r.sh les enchaîne).
Aucune des deux suites ne relance cicero-orders (#33) : chacune relève son état initial,
à restaurer à la main. `commandes` se lance sur le poste, depuis le dépôt : --phases et
--repetees sont validés par tests/reference_jeu.py, qu'un conteneur n'a pas.
--dry-run (historique, comparer) : ni site ni pydipcc, une partie doublée de deux
phases fait tourner l'extraction, le rejeu et la comparaison.

Ce que le site règle et que l'historique ne porte pas (ADR 0006 : rien d'autre de la
partie) : le système de score (`potType`) et la durée d'une phase. `historique` les
affiche ; ils se redonnent à rejeu_moteur.py par --score et --minutes-de-phase, et
s'écrivent ainsi dans la commande de capture du manifeste.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # commun.charger lit cicero/overlay : pas de .pyc à côté des sources (#27)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import commun  # noqa: E402

ARGUMENTS_EXPORT = (
    "game_id", "phase", "power", "action_values", "top_k",
    "prior_policy", "regularize_lambda", "boost", "max_prob",
)
PHASES_DE_MOUVEMENT = ("S1901M", "F1901M", "S1902M", "F1902M", "S1903M", "F1903M")
SCORES = {"sos": "SCORING_SOS", "dss": "SCORING_DSS"}
# Comme fairdiplomacy_external.webdip_api.webdip_state_to_game.
SCORE_DU_POT = {"Unranked": "sos", "Sum-of-squares": "sos", "Points-per-supply-center": "sos", "Winner-takes-all": "dss"}


# ---------------------------------------------------------------------------
# Historique des ordres
# ---------------------------------------------------------------------------

def extraire_historique(game):
    """{"phases": [{"name", "orders": {puissance: [ordres]}}]} des phases jouées d'une partie pydipcc.

    Les phases passées seulement (get_phase_history) : la phase en cours, sans
    ordres, n'y est pas. Rien d'autre n'est lu de la partie : ni message, ni état.
    """
    phases = []
    for phase in game.get_phase_history():
        ordres = {p: list(phase.orders[p]) for p in commun.POWERS if phase.orders.get(p)}
        phases.append({"name": phase.name, "orders": ordres})
    return {"phases": phases}


def partie_depuis_historique(classe_de_partie, historique, phase, score=None, minutes_de_phase=None):
    """Une partie au début de `phase`, reconstruite depuis l'historique des ordres seul.

    `classe_de_partie` : pydipcc.Game (ou sa doublure). Chaque phase de
    l'historique est rejouée (set_orders, process) jusqu'à `phase` ; le nom de la
    phase courante est contrôlé à chaque pas, un historique qui ne suit pas la
    partie arrête tout. `score` (« sos », « dss ») et `minutes_de_phase` : ce que
    webdip_state_to_game règle d'après le site, laissé tel que pydipcc le crée si
    rien n'est donné. Rend (partie, nombre de phases rejouées).
    """
    game = classe_de_partie()
    if score is not None:
        game.set_scoring_system(getattr(classe_de_partie, SCORES[score]))
    if minutes_de_phase is not None:
        game.set_metadata("phase_minutes", str(minutes_de_phase))
    rejouees = 0
    for jouee in historique["phases"]:
        if game.current_short_phase == phase:
            break
        if game.current_short_phase != jouee["name"]:
            raise SystemExit(
                "historique : la partie rejouée est en %s, l'historique donne %s"
                % (game.current_short_phase, jouee["name"])
            )
        for puissance, ordres in jouee["orders"].items():
            game.set_orders(puissance, list(ordres))
        game.process()
        rejouees += 1
    if game.current_short_phase != phase:
        raise SystemExit(
            "historique : %s n'est pas atteinte (la partie rejouée s'arrête en %s)"
            % (phase, game.current_short_phase)
        )
    return game, rejouees


# ---------------------------------------------------------------------------
# Arguments bruts d'export_plans
# ---------------------------------------------------------------------------

def arguments_bruts(args, kwargs):
    """Les arguments d'un appel à export_plans, par nom, en types que JSON écrit sans perte.

    Les nombres passent par float(), comme export_plans le fait lui-même avant
    d'arrondir : le rejeu de l'export sur ces arguments part des mêmes flottants.
    """
    nommes = dict(zip(ARGUMENTS_EXPORT, args))
    nommes.update(kwargs)
    avant = nommes.get("prior_policy")

    def nombre(valeur):
        return None if valeur is None else float(valeur)

    return {
        "phase": nommes.get("phase"), "puissance": nommes.get("power"),
        "action_values": [
            [list(action), float(valeur), float(prob), float(score)]
            for action, valeur, prob, score in nommes.get("action_values") or []
        ],
        "prior_policy": None if avant is None else [[list(action), float(prob)] for action, prob in avant.items()],
        "regularize_lambda": nombre(nommes.get("regularize_lambda")),
        "boost": nombre(nommes.get("boost")), "max_prob": nombre(nommes.get("max_prob")),
    }


def doubler_export(module_agent, puits):
    """Double export_plans là où l'agent l'appelle ; rend la fonction d'origine.

    fairdiplomacy/agents/bqre1p_agent.py importe le nom (`from ... import
    export_plans`) : c'est donc l'attribut de ce module-là qu'on remplace, par une
    enveloppe qui note les arguments dans `puits` puis appelle l'original avec les
    mêmes arguments. Ni le moteur ni plan_export ne sont modifiés, et l'export se
    fait comme sans doublage. Une erreur de relevé est notée, jamais levée.
    """
    original = module_agent.export_plans

    def export_plans(*args, **kwargs):
        try:
            puits.append(arguments_bruts(args, kwargs))
        except Exception as e:
            puits.append({"erreur": "%s: %s" % (type(e).__name__, e)})
        return original(*args, **kwargs)

    export_plans.original = original
    module_agent.export_plans = export_plans
    return original


def arguments_de_la_recherche(puits, phase, puissance):
    """(arguments du dernier appel pour cette phase et cette puissance, nombre d'appels notés) ; None s'il n'y en a pas."""
    pour_elle = [a for a in puits if a.get("phase") == phase and a.get("puissance") == puissance]
    if not pour_elle:
        return None, len(puits)
    return {c: v for c, v in pour_elle[-1].items() if c not in ("phase", "puissance")}, len(puits)


# ---------------------------------------------------------------------------
# Doublures de l'essai à sec
# ---------------------------------------------------------------------------

HISTORIQUE_DOUBLURE = {"phases": [
    {"name": "S1901M", "orders": {"FRANCE": ["A PAR - BUR", "A MAR - SPA", "F BRE - MAO"], "GERMANY": ["A MUN - RUH"]}},
    {"name": "F1901M", "orders": {"FRANCE": ["A BUR H", "A SPA H", "F MAO - POR"], "GERMANY": ["A RUH - BEL"]}},
]}


class _PhaseDoublure:
    def __init__(self, name, orders):
        self.name, self.orders = name, orders


def doublure_de_partie(historique, suivante="W1901A"):
    """Une classe qui se comporte comme pydipcc.Game pour ce qu'en lisent les fonctions d'ici.

    Les phases se suivent dans l'ordre de `historique`, puis `suivante` ; l'état
    d'une position est la liste des ordres joués jusque-là. Aucune règle du jeu.
    """
    noms = [p["name"] for p in historique["phases"]] + [suivante]

    class PartieDoublure:
        SCORING_SOS, SCORING_DSS = 0, 1

        def __init__(self):
            self.jouees, self.en_cours, self.score, self.metadonnees = [], {}, None, {}

        @property
        def current_short_phase(self):
            return noms[len(self.jouees)]

        def set_scoring_system(self, score):
            self.score = score

        def set_metadata(self, cle, valeur):
            self.metadonnees[cle] = valeur

        def get_metadata(self, cle):
            return self.metadonnees.get(cle, "")

        def set_orders(self, puissance, ordres):
            self.en_cours[puissance] = tuple(ordres)

        def process(self):
            self.jouees.append(_PhaseDoublure(self.current_short_phase, self.en_cours))
            self.en_cours = {}

        def get_phase_history(self):
            return list(self.jouees)

        def get_state(self):
            return {"jouees": [(p.name, sorted(p.orders.items())) for p in self.jouees]}

        def compute_board_hash(self):
            return hash(json.dumps(self.get_state(), sort_keys=True))

        def rolled_back_to_phase_start(self, phase):
            copie = PartieDoublure()
            copie.jouees = self.jouees[:noms.index(phase)]
            return copie

    return PartieDoublure


def partie_doublure_jouee(historique=None):
    """La partie doublée, toutes ses phases jouées : ce que rendrait webdip_state_to_game."""
    historique = HISTORIQUE_DOUBLURE if historique is None else historique
    classe = doublure_de_partie(historique)
    game = classe()
    for jouee in historique["phases"]:
        for puissance, ordres in jouee["orders"].items():
            game.set_orders(puissance, ordres)
        game.process()
    return classe, game


# ---------------------------------------------------------------------------
# Site (lecture seule)
# ---------------------------------------------------------------------------

def lire_partie_du_site(game_id):
    """(partie pydipcc, ce que le statut dit de la partie) : GET game/status, rien n'est écrit."""
    from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game

    contexte = None
    for puissance in commun.POWERS:
        try:
            contexte = commun.trouver_contexte(game_id, puissance)
            break
        except SystemExit:
            continue
    if contexte is None:
        raise SystemExit("aucun compte bot ne joue dans la partie %s" % game_id)
    statut = get_status_json(contexte)
    if statut is None:
        raise SystemExit("statut de la partie %s illisible" % game_id)
    # Pas de processStatus : game/status ne l'expose pas (api/responses/game_state.php), il valait toujours null (#33).
    releve = {c: statut.get(c) for c in ("gameID", "turn", "phase", "gameOver", "potType", "phaseLengthInMinutes")}
    releve["messages"] = sum(len(p.get("messages") or []) for p in statut.get("phases") or [])
    game = webdip_state_to_game(statut)  # retire les messages du JSON : comptés avant
    releve["phase_courante"] = game.current_short_phase
    return game, releve


def comparer_positions(classe_de_partie, game, historique, score=None, minutes_de_phase=None):
    """Par phase de l'historique : la position rejouée est-elle celle de la partie d'origine ?

    Rend [(phase, états égaux, clés du plateau égales)].
    """
    lignes = []
    for jouee in historique["phases"]:
        origine = game.rolled_back_to_phase_start(jouee["name"])
        rejouee, _ = partie_depuis_historique(classe_de_partie, historique, jouee["name"], score, minutes_de_phase)
        lignes.append((
            jouee["name"], origine.get_state() == rejouee.get_state(),
            origine.compute_board_hash() == rejouee.compute_board_hash(),
        ))
    return lignes


# ---------------------------------------------------------------------------
# Identité de la capture
# ---------------------------------------------------------------------------

IDENTITE = "identite_capture.json"


def ecrire_identite(dossier, sha_depot, image, date=None):
    """Écrit, au lancement de la campagne, ce qui dit quel code et quelle image produisent les tables.

    Dans <dossier>/resultats/identite_capture.json : SHA du dépôt, identifiant de
    l'image, date. Le manifeste du jeu d'essai le reprend (reference_jeu.py
    reduire --identite). Refuse d'écraser une identité déjà écrite : une campagne
    a une seule identité.
    """
    import time

    if not re.fullmatch(r"[0-9a-f]{40}", sha_depot or ""):
        raise SystemExit("identité : SHA complet du dépôt attendu (40 chiffres hexadécimaux)")
    if not re.fullmatch(r"[A-Za-z0-9_.:/@-]{1,100}", image or ""):
        raise SystemExit("identité : identifiant d'image attendu (docker image inspect --format '{{.Id}}')")
    fichier = Path(dossier) / "resultats" / IDENTITE
    if fichier.exists():
        raise SystemExit("identité : %s existe déjà (une campagne, une identité)" % fichier)
    identite = {"sha_depot": sha_depot, "image": image, "date": date or time.strftime("%Y-%m-%d")}
    commun.ecrire_json(fichier, identite)
    return fichier, identite


# ---------------------------------------------------------------------------
# Commandes de la campagne
# ---------------------------------------------------------------------------

DOCKER = (
    'docker run --rm{gpu}{reseau} \\\n'
    '  -v "$PWD/{dossier}:/mesure"{modeles} \\\n'
    '{environnement}'
    '  cicero-webdip:latest \\\n'
    '  {commande}'
)
# Réseau de la pile (compose) : il n'existe que pile démarrée. La campagne de capture lit le site, elle le garde ;
# un lot de la couche R part sans lui, sur le réseau par défaut de Docker, sauf --reseau (#33).
RESEAU_DE_LA_PILE = "webdiplomacy_default"
ENVIRONNEMENT_DE_LA_PILE = "  -e WEBDIP_API_URL=http://webserver/api.php -e CICERO_REDIS_IP=redis -e CICERO_REDIS_PORT=6379 \\\n"
# Nom de réseau imprimé après --network : il ne commence pas par un tiret (« --privileged » passerait pour une
# option de docker run). « none » est refusé : un lancement télécharge son vocabulaire au démarrage (#34).
RESEAU = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
# Dossier d'un lot : sous amont/ (hors git : un lot ne s'écrit ni dans tests/reference ni ailleurs dans le dépôt
# versionné), chemin relatif à la racine du dépôt, sans « .. » ni composante qui commence par un point ou un
# tiret ; il est imprimé tel quel dans des lignes de shell. Ni amont/cicero ni amont/webdiplomacy, ni rien
# dessous : ce sont les clones d'amont, dont outils/exporter_patchs.sh parcourt les fichiers non suivis.
DOSSIER = re.compile(r"amont/(?!(?:cicero|webdiplomacy)(?:/|\Z))[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*")
REGLE_DU_DOSSIER = ("sous amont/, relatif à la racine du dépôt, sans « .. », aucune composante ne commençant par un point ou un tiret, "
                    "hors des clones d'amont (ni amont/cicero ni amont/webdiplomacy)")
# État initial de cicero-orders, relevé avant l'arrêt, dans les deux suites ; aucune ne le relance (#33 : le
# 2026-10-10, le redémarrage imprimé a produit 7 envois d'ordres sur une partie en pause). Conteneur absent
# (après ./arreter.sh) : docker inspect sort en code 1, l'état vaut « absent » et rien n'est arrêté.
ETAT_DE_CICERO_ORDERS = (
    "ETAT=$(docker inspect --format '{{.State.Status}}' cicero-orders 2>/dev/null) || ETAT=absent",
    'echo "cicero-orders : état initial $ETAT (à restaurer à la main, cette suite ne relance rien)"',
    '[ "$ETAT" = absent ] || docker stop cicero-orders',
)
DOSSIER_DE_CAMPAGNE = "amont/capture-reference"  # hors git, et à part des relevés du 2026-10-03 (amont/mesure)
# Positions répétées (`--tirages` tirages A + B), fixées par expert-cicero pour #31 et #26 : 21 positions.
# Les autres positions des phases de la campagne ont un tirage, recherche A seule.
POSITIONS_REPETEES = (
    [("S1901M", p) for p in commun.POWERS] + [("S1902M", p) for p in commun.POWERS]
    + [("F1902M", p) for p in ("AUSTRIA", "ENGLAND", "FRANCE", "GERMANY", "RUSSIA")]
    + [("S1903M", p) for p in ("FRANCE", "TURKEY")]
)
# Seconde passe d'une position répétée, dans un fichier distinct : contrôle d'indépendance des lancements.
SECONDE_PASSE = (("S1903M", "FRANCE"),)
ETIQUETTE_SECONDE_PASSE = "passe2"
# Lot de la couche R (#31, critère 3) : les positions répétées, rejouées dans un dossier à part.
DOSSIER_COUCHE_R = "amont/couche-r"
# Mesuré sur la campagne du 2026-10-10 (43 lancements, 241 recherches) : recherche A 50,5 s (131 recherches) et
# B 24,1 s (110) en moyenne, d'après les duree_s des relevés ; démarrage d'un lancement, 46 s en médiane (durée
# du lancement dans le journal de la campagne, moins la somme de ses recherches ; de 22 à 67 s).
DUREES = {"A": 50.5, "B": 24.1, "lancement": 46.0}
# Le lot de la couche R du 2026-10-11 (les 21 lancements des positions répétées) a duré 14 548 s d'après son
# journal de campagne, pour 8 799 s estimés par DUREES : 14 548 / 8 799 = 1,653, arrondi au-dessus. La carte
# graphique était occupée par ailleurs pendant près de deux heures (surcroît de 1,7 à 3,4 Gio) ; le mécanisme du
# ralentissement n'est pas établi (#33). Les mêmes 21 lancements avaient duré 8 999 s le 2026-10-10.
MAJORATION_OBSERVEE = 1.66


def lire_positions(valeurs):
    """« S1902M » (les sept puissances) ou « S1902M:FRANCE » -> [(phase, puissance)], sans doublon."""
    positions = []
    for valeur in valeurs:
        phase, _, puissance = valeur.partition(":")
        puissances = [puissance.upper()] if puissance else list(commun.POWERS)
        if puissances[0] not in commun.POWERS or not phase_valide(phase):
            raise SystemExit("position inconnue : %r" % valeur)
        positions += [(phase, p) for p in puissances if (phase, p) not in positions]
    return positions


def plan_de_campagne(phases, repetees, tirages, seconde_passe=SECONDE_PASSE):
    """[(phase, puissance, tirages, engagements, étiquette)] : un lancement par ligne, dans l'ordre de la campagne."""
    lancements = []
    for phase in phases:
        for puissance in commun.POWERS:
            if (phase, puissance) in repetees:
                lancements.append((phase, puissance, tirages, "auto:prefere", None))
            else:
                lancements.append((phase, puissance, 1, "aucun", None))
    lancements += [(phase, puissance, tirages, "auto:prefere", ETIQUETTE_SECONDE_PASSE) for phase, puissance in seconde_passe]
    return lancements


def duree_estimee(lancements):
    """Secondes : par lancement, son démarrage et ses tirages (A + B avec engagement, A seule sinon)."""
    return sum(
        DUREES["lancement"] + n * (DUREES["A"] + (DUREES["B"] if engagements != "aucun" else 0.0))
        for _phase, _puissance, n, engagements, _etiquette in lancements
    )


def fourchette_de_duree(lancements):
    """(basse, haute) en secondes : l'estimation tirée de la campagne du 2026-10-10, et elle majorée du rapport observé sur le lot du 2026-10-11."""
    basse = duree_estimee(lancements)
    return basse, basse * MAJORATION_OBSERVEE


def texte_de_duree(lancements):
    """La fourchette, telle que les deux suites l'impriment : elle nomme les deux campagnes dont elle vient.

    La borne haute est un rapport appliqué à l'estimation, pas une durée relevée : seul le lot entier de la
    couche R (21 lancements) a été mesuré le 2026-10-11.
    """
    def heures(secondes):
        return "%d h %02d" % (secondes // 3600, secondes % 3600 // 60)

    basse, haute = fourchette_de_duree(lancements)
    return ("de %s (campagne du 2026-10-10) à %s (× %s, observé sur les 21 lancements du lot du 2026-10-11, carte "
            "graphique occupée par ailleurs pendant près de deux heures)"
            % (heures(basse), heures(haute), ("%.2f" % MAJORATION_OBSERVEE).replace(".", ",")))


def phase_valide(valeur):
    """Vrai si `valeur` est une phase (reference_jeu.est_phase) ; elle est imprimée dans des lignes de shell."""
    racine = str(Path(__file__).resolve().parent.parent)
    if racine not in sys.path:
        sys.path.insert(0, racine)
    try:
        import reference_jeu
    except ImportError:
        raise SystemExit("validation des phases : tests/reference_jeu.py introuvable (`commandes` se lance depuis le dépôt)")
    return reference_jeu.est_phase(valeur)


def _argument(valide, nature):
    """Un type d'argparse : la valeur, ou le refus d'argparse (code 2, rien sur la sortie standard)."""
    def lire(valeur):
        if not valide(valeur):
            raise argparse.ArgumentTypeError("%s invalide : %r" % (nature, valeur))
        return valeur

    return lire


def _entier(minimum, nature):
    """Un type d'argparse : un entier au moins égal à `minimum`, ou le refus d'argparse (code 2)."""
    def lire(valeur):
        if not re.fullmatch(r"[0-9]+", valeur) or int(valeur) < minimum:
            raise argparse.ArgumentTypeError("%s invalide : %r (entier au moins égal à %d)" % (nature, valeur, minimum))
        return int(valeur)

    return lire


def _reseau(valeur):
    """Le type d'argparse de --reseau : un nom de réseau Docker, sauf « none »."""
    if valeur == "none":
        raise argparse.ArgumentTypeError(
            "réseau Docker invalide : 'none' (un accès sortant à Internet est requis au démarrage de chaque lancement, #34)")
    return _argument(RESEAU.fullmatch, "réseau Docker")(valeur)


def commandes_de_campagne(game_id, phases, repetees, tirages, score, minutes_de_phase, dossier=DOSSIER_DE_CAMPAGNE):
    """Les commandes de la campagne de capture, dans l'ordre ; rien n'est lancé.

    Un lancement par position (phase, puissance) : `tirages` tirages A + B
    (--engagements auto:prefere, engagement figé au tirage 0) pour les positions
    `repetees`, un tirage A seul (--engagements aucun) pour les autres ; puis la
    seconde passe. Les relevés vont dans un dossier à part : la réduction prend la
    recherche A du premier tirage de chaque fichier, et ne doit pas tomber sur un
    relevé plus ancien de la même position. La suite arrête cicero-orders et ne
    le relance pas (#33) : elle affiche son état initial, à restaurer à la main.
    """
    historique = "/mesure/resultats/historique_%s.json" % game_id
    pile = dict(reseau=" --network %s" % RESEAU_DE_LA_PILE, environnement=ENVIRONNEMENT_DE_LA_PILE, dossier=dossier)
    sans_gpu = dict(pile, gpu="", modeles="")
    avec_gpu = dict(pile, gpu=" --gpus all", modeles=' -v "$PWD/amont/cicero/models:/opt/cicero/models:ro"')
    reglages = " --score %s" % score + ("" if minutes_de_phase is None else " --minutes-de-phase %s" % minutes_de_phase)
    lancements = plan_de_campagne(phases, repetees, tirages)
    lignes = [
        "# Depuis la racine du dépôt. cicero-orders est arrêté pour les recherches (GPU de 8 Go), après annonce.",
        "# Prérequis : pile démarrée (réseau %s ; l'historique se lit sur le site), image cicero-webdip:latest," % RESEAU_DE_LA_PILE,
        "#    modèles sous amont/cicero/models.",
        "# %d lancements, %d recherches ; durée estimée des recherches : %s." % (
            len(lancements), sum(n * (2 if e != "aucun" else 1) for _p, _q, n, e, _x in lancements),
            texte_de_duree(lancements)),
        "mkdir -p %s/resultats && cp tests/mesure/* %s/" % (dossier, dossier),
        "# 0. Identité de la capture, écrite une fois au lancement (le manifeste la reprendra).",
        "python3 tests/mesure/capture_reference.py identite --dossier %s \\\n"
        "  --sha \"$(git rev-parse HEAD)\" --image \"$(docker image inspect --format '{{.Id}}' cicero-webdip:latest)\"" % dossier,
        "# 1. Historique des ordres (GET seulement, aucune recherche), puis contrôle de la position rejouée.",
        DOCKER.format(commande="python /mesure/capture_reference.py historique %s --sortie %s" % (game_id, historique), **sans_gpu),
        DOCKER.format(commande="python /mesure/capture_reference.py comparer %s --historique %s%s" % (game_id, historique, reglages), **sans_gpu),
        "# 2. Recherches (cicero-orders arrêté). Cette suite ne le relance pas (#33) : noter l'état initial",
        "#    qu'affiche la deuxième ligne, il se restaure à la main.",
    ] + list(ETAT_DE_CICERO_ORDERS)
    for phase, puissance, n, engagements, etiquette in lancements:
        if etiquette:
            lignes.append("# Seconde passe de %s %s, dans un fichier distinct (contrôle d'indépendance ; hors réduction)." % (phase, puissance))
        lignes.append(DOCKER.format(
            commande="python /mesure/rejeu_moteur.py %s %s %s %d --historique %s%s --engagements %s%s"
            % (game_id, phase, puissance, n, historique, reglages, engagements,
               " --etiquette %s" % etiquette if etiquette else ""),
            **avec_gpu
        ))
    lignes += [
        "#    cicero-orders est resté arrêté : le remettre à la main dans l'état noté avant les recherches.",
        "# 3. Les relevés bruts sont hors git ET sous amont/, que install.sh peut refaire : les copier ailleurs",
        "#    (hors du dépôt) dès la fin de la campagne ; ils ne se recapturent pas à l'identique.",
        "cp -a %s/resultats <dossier de conservation hors du dépôt>/" % dossier,
        "# 4. Sur le poste, après visa : réduction des relevés (session principale seule).",
        "python3 tests/reference_jeu.py reduire %s/resultats/m1_%s_*_engagements_*.jsonl \\\n"
        "  --historique %s/resultats/historique_%s.json --vers tests/reference \\\n"
        "  --identite %s/resultats/%s --partie %s --creee-le <AAAA-MM-JJ> \\\n"
        "  --commande \"capture_reference.py commandes %s --score %s%s\""
        % (dossier, game_id, dossier, game_id, dossier, IDENTITE, game_id, game_id, score,
           "" if minutes_de_phase is None else " --minutes-de-phase %s" % minutes_de_phase),
        "python3 tests/reference_couche_d.py --generer",
        "bash tests/verifier.sh",
    ]
    return lignes


def commandes_de_la_couche_r(game_id, repetees, tirages, score, minutes_de_phase, dossier=DOSSIER_COUCHE_R, reseau=None):
    """Les commandes d'un lot de la couche R, dans l'ordre ; rien n'est lancé.

    Un lancement par position répétée : `tirages` tirages A + B (--engagements
    auto:prefere), sans seconde passe, dans un dossier à part (un lot a un seul
    fichier de relevés par position). L'historique est celui du jeu d'essai : aucun
    accès à webDiplomacy, et les lancements partent sans le réseau de la pile, qui
    peut donc être arrêtée ; `reseau` rétablit `--network` et les variables de la
    pile. La suite arrête cicero-orders s'il existe et ne le relance pas (#33) : elle
    affiche son état initial, à restaurer à la main. Si `repetees` n'est pas la
    liste entière des positions répétées (relance d'une position, exécution réduite
    à une phase), la comparaison imprimée les nomme par --positions.
    """
    historique = "/mesure/resultats/historique_%s.json" % game_id
    avec_gpu = dict(
        gpu=" --gpus all", modeles=' -v "$PWD/amont/cicero/models:/opt/cicero/models:ro"', dossier=dossier,
        reseau="" if reseau is None else " --network %s" % reseau,
        environnement="" if reseau is None else ENVIRONNEMENT_DE_LA_PILE,
    )
    reglages = " --score %s" % score + ("" if minutes_de_phase is None else " --minutes-de-phase %s" % minutes_de_phase)
    lancements = [(phase, puissance, tirages, "auto:prefere", None) for phase, puissance in repetees]
    lignes = [
        "# Lot de la couche R (#31) : depuis la racine du dépôt, à la main ; jamais en CI ni dans un workflow.",
        "# Prérequis : image cicero-webdip:latest, modèles sous amont/cicero/models ; %s." % (
            "la pile peut être arrêtée (ni son réseau ni cicero-orders ne sont requis)" if reseau is None
            else "le réseau Docker %s existe (celui de la pile : il n'existe que pile démarrée)" % reseau if reseau == RESEAU_DE_LA_PILE
            else "le réseau Docker %s existe (celui de la pile, %s, n'existe que pile démarrée)" % (reseau, RESEAU_DE_LA_PILE)),
        "#    Aucun accès à webDiplomacy ; accès sortant à Internet requis au démarrage de chaque lancement",
        "#    (vocabulaire GPT-2 téléchargé depuis dl.fbaipublicfiles.com).",
        "# %d lancements, %d recherches ; durée estimée : %s." % (
            len(lancements), sum(2 * n for _p, _q, n, _e, _x in lancements), texte_de_duree(lancements)),
        "# Dossier neuf : un relevé plus ancien d'une même position ferait refuser le lot (un fichier par position).",
        "mkdir %s && mkdir %s/resultats && cp tests/mesure/* %s/" % (dossier, dossier, dossier),
        "# 1. Historique des ordres : celui du jeu d'essai.",
        "cp tests/reference/historique.json %s/resultats/historique_%s.json" % (dossier, game_id),
        "# 2. Recherches. cicero-orders doit être arrêté (GPU de 8 Go), après annonce. Cette suite ne le relance pas",
        "#    (#33) : noter l'état initial qu'affiche la deuxième ligne, il se restaure à la main.",
    ] + list(ETAT_DE_CICERO_ORDERS)
    for phase, puissance, n, engagements, _etiquette in lancements:
        lignes.append(DOCKER.format(
            commande="python /mesure/rejeu_moteur.py %s %s %s %d --historique %s%s --engagements %s"
            % (game_id, phase, puissance, n, historique, reglages, engagements),
            **avec_gpu
        ))
    lignes += [
        "# 3. Comparaison au résumé de la référence ; code de retour 0 : pas de régression, 1 : régression,",
        "#    2 : non concluant ou lot invalide. Le détail reste sous amont/, hors git.",
        "python3 tests/reference_couche_r.py comparer %s/resultats --sortie %s/couche_r.json%s" % (
            dossier, dossier, "" if list(repetees) == list(POSITIONS_REPETEES)
            else " --positions " + " ".join("%s:%s" % position for position in repetees)),
        "# 4. cicero-orders est resté arrêté : le remettre à la main dans l'état noté à l'étape 2.",
    ]
    return lignes


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commandes = p.add_subparsers(dest="commande")
    h = commandes.add_parser("historique", help="historique des ordres d'une partie, lu sur le site (GET)")
    h.add_argument("game_id", type=int)
    h.add_argument("--sortie", help="fichier JSON à écrire (dossier de mesure) ; sans lui, sortie standard")
    h.add_argument("--dry-run", action="store_true", help="partie doublée : ni site ni pydipcc")
    c = commandes.add_parser("comparer", help="position rejouée depuis l'historique contre celle du site, phase par phase")
    c.add_argument("game_id", type=int)
    c.add_argument("--historique", required=True)
    c.add_argument("--score", choices=sorted(SCORES))
    c.add_argument("--minutes-de-phase", type=int)
    c.add_argument("--dry-run", action="store_true", help="partie doublée : ni site ni pydipcc")
    k = commandes.add_parser("commandes", help="imprime les commandes de la campagne de capture, sans rien lancer")
    k.add_argument("game_id", type=_entier(1, "GAME_ID"))
    k.add_argument("--phases", nargs="+", default=list(PHASES_DE_MOUVEMENT), type=_argument(phase_valide, "phase"))
    k.add_argument("--repetees", nargs="*", metavar="PHASE[:PUISSANCE]",
                   help="positions à `--tirages` tirages A + B (défaut : les 21 de POSITIONS_REPETEES)")
    k.add_argument("--tirages", type=_entier(1, "nombre de tirages"), default=5)
    k.add_argument("--couche-r", action="store_true",
                   help="les commandes d'un lot de la couche R : les positions répétées seules, sans seconde passe, "
                        "dans %s ; cicero-orders n'est pas relancé (--phases est sans objet)" % DOSSIER_COUCHE_R)
    k.add_argument("--dossier", type=_argument(DOSSIER.fullmatch, "dossier (%s)" % REGLE_DU_DOSSIER),
                   help="avec --couche-r seulement : dossier du lot, neuf, sous amont/ (défaut : %s)" % DOSSIER_COUCHE_R)
    k.add_argument("--reseau", metavar="NOM", type=_reseau,
                   help="avec --couche-r seulement : réseau Docker des lancements, avec les variables de la pile (%s, "
                        "pile démarrée) ; sans lui, le réseau par défaut de Docker ; « none » est refusé" % RESEAU_DE_LA_PILE)
    # Partie 3, lu dans le statut du site par la session principale : potType « Unranked », que
    # webdip_state_to_game lit comme SCORING_SOS (SCORE_DU_POT), et des phases de 4 320 minutes.
    k.add_argument("--score", choices=sorted(SCORES), default="sos")
    k.add_argument("--minutes-de-phase", type=_entier(0, "durée de phase"), default=4320)
    i = commandes.add_parser("identite", help="écrit l'identité de la capture (SHA du dépôt, image, date) ; sur le poste")
    i.add_argument("--dossier", required=True, help="dossier de la campagne (ex. %s)" % DOSSIER_DE_CAMPAGNE)
    i.add_argument("--sha", required=True, help="git rev-parse HEAD")
    i.add_argument("--image", required=True, help="docker image inspect --format '{{.Id}}' cicero-webdip:latest")
    i.add_argument("--date", help="AAAA-MM-JJ (défaut : aujourd'hui)")
    args = p.parse_args(argv)

    if args.commande == "commandes":
        for option, valeur in (("--dossier", args.dossier), ("--reseau", args.reseau)):
            if valeur is not None and not args.couche_r:  # sans --couche-r, elle serait ignorée sans le dire
                k.error("%s ne vaut qu'avec --couche-r" % option)
        repetees = list(POSITIONS_REPETEES) if args.repetees is None else lire_positions(args.repetees)
        if args.couche_r:
            print("\n".join(commandes_de_la_couche_r(
                args.game_id, repetees, args.tirages, args.score, args.minutes_de_phase,
                args.dossier or DOSSIER_COUCHE_R, args.reseau)))
            return 0
        print("\n".join(commandes_de_campagne(
            args.game_id, args.phases, repetees, args.tirages, args.score, args.minutes_de_phase)))
        return 0
    if args.commande == "identite":
        fichier, identite = ecrire_identite(args.dossier, args.sha, args.image, args.date)
        print("identité de la capture écrite dans %s : %s" % (fichier, json.dumps(identite)))
        return 0
    if args.commande == "historique":
        if args.dry_run:
            _classe, game = partie_doublure_jouee()
            releve = {"doublure": True, "phase_courante": game.current_short_phase}
        else:
            game, releve = lire_partie_du_site(args.game_id)
        historique = extraire_historique(game)
        texte = json.dumps(historique, ensure_ascii=True, separators=(",", ":"))
        print("partie %s : %s" % (args.game_id, json.dumps(releve, ensure_ascii=False)), file=sys.stderr)
        if "potType" in releve:
            print("  réglages à redonner au rejeu : --score %s --minutes-de-phase %s" % (
                SCORE_DU_POT.get(releve["potType"], "?"), releve.get("phaseLengthInMinutes")), file=sys.stderr)
        print("  %d phase(s) jouée(s), %d octets : %s" % (
            len(historique["phases"]), len(texte), " ".join(ph["name"] for ph in historique["phases"])), file=sys.stderr)
        if args.sortie and not args.dry_run:
            commun.ecrire_json(args.sortie, historique)
        else:
            print(texte)
        return 0
    if args.commande == "comparer":
        if args.dry_run:
            classe, game = partie_doublure_jouee()
            historique = extraire_historique(game)
        else:
            from fairdiplomacy import pydipcc
            classe = pydipcc.Game
            game, releve = lire_partie_du_site(args.game_id)
            historique = json.loads(Path(args.historique).read_text())
            if args.score is None:  # comme webdip_state_to_game, d'après le site
                args.score = SCORE_DU_POT.get(releve.get("potType"))
            if args.minutes_de_phase is None:
                args.minutes_de_phase = releve.get("phaseLengthInMinutes")
            print("réglages du rejeu : --score %s --minutes-de-phase %s" % (args.score, args.minutes_de_phase))
        lignes = comparer_positions(classe, game, historique, args.score, args.minutes_de_phase)
        for phase, etats, cles in lignes:
            print("%s : état %s, clé du plateau %s" % (phase, "identique" if etats else "DIFFÉRENT", "identique" if cles else "DIFFÉRENTE"))
        identiques = sum(1 for _p, etats, cles in lignes if etats and cles)
        print("position rejouée identique à celle du site : %d phase(s) sur %d" % (identiques, len(lignes)))
        return 0 if identiques == len(lignes) else 1
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
