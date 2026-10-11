"""Bruit des valeurs d'une recherche à l'autre, sur les relevés de rejeu_moteur.py (#26).

Bibliothèque standard seule, Python 3.7, hors conteneur comme dedans ; aucune
recherche n'est lancée, ni site ni GPU :

    python3 tests/mesure/bruit_valeurs.py <dossier de relevés> [--sortie fichier.json]

Entrée : les fichiers m1_*.jsonl du dossier (une ligne par recherche ; les lignes
« comparaison » du mode incrémental sont laissées de côté).

Grandeur. Pour une table T (l'entrée exportée d'une recherche) et un couple
ordonné (E, N) d'ordres distincts d'une même unité, tous deux dans order_values :
G_T(E, N) = round(order_values[N] - order_values[E], 5), le `gain` que
claude_dialogue_bot._reject_contradictions compare à COMMITMENT_SWITCH_MARGIN.
L'unité d'un ordre est celle de _order_loc, et la marge est lue dans le fichier
du bot : ni l'une ni l'autre ne sont recopiées ici.

Bruit. d = G_T - moyenne de G sur les autres tables du groupe, à quatre niveaux :
  « recherches_a » : les recherches A sans engagement, seules, groupées par
                     (partie, phase, puissance) -- le niveau du critère ;
  « recherches_b » : les recherches B seules, par position et engagements
                     retenus -- informatif ;
  « groupe »       : (partie, phase, puissance, engagements retenus, type de
                     recherche A / B / C), toutes recherches : le cumul de A et
                     de B -- informatif ;
  « engagements »  : le même sans le type de recherche. B et C d'un rejeu
                     incrémental y sont réunis : ce ne sont pas deux tirages
                     indépendants, la valeur est un minorant -- informatif.
La recherche B d'un tirage est une mise à jour incrémentale de la recherche A
du même tirage, sur le même état d'agent : ses observations ne sont pas
indépendantes de celles de A, et le cumul affiche un effectif supérieur à
l'information réelle.
Écarts par paire de tables d'une même position (partie, phase, puissance), pour
la continuité avec les chiffres cités dans #26 : |G_T1 - G_T2|, classés selon que
les deux tables ont les mêmes engagements retenus ou non.

Action porteuse d'un ordre : la première action de `candidates`, dans l'ordre
exporté, qui le contient -- celle dont plan_export tire order_values[ordre].
Un couple est à « porteuse changée » si celle de E ou de N n'est pas la même
dans toutes les tables comparées.

Un couple qui n'est que dans une des tables comparées n'a pas d'écart : il est
écarté, et compté (« 1 table » dans le tableau).

Centiles : la valeur observée de rang ceil((n - 1) x q), sans interpolation --
jamais en dessous de la part annoncée des valeurs.

Critère (#26), relatif à la marge : « protège » si aucune acceptation sur bruit,
99e centile de |d| <= marge / 2 au total et <= marge dans la pire position ;
« ne protège pas » si 95e centile >= marge au total, ou si plus de 1 % des
observations sans gain (moyenne des autres tables <= 0) sont acceptées. Le
verdict n'est rendu que s'il est concluant ; sinon « non concluant », avec ce
que le critère donnerait en lecture indicative. À côté du nombre d'acceptations
sur bruit, le nombre de tables, de couples (table, ordre E) et de positions
distincts qui les portent : informatif, l'issue du critère n'en dépend pas (une
seule table qui s'écarte des autres donne autant d'acceptations qu'elle a de
couples partant de l'ordre déplacé). Le critère se lit sur le niveau
« recherches_a » (décision du mainteneur, 2026-10-10) ; les trois autres niveaux
ne sont jamais concluants. Un rejet de l'indépendance des tirages d'un
lancement, ou une paire de tables jumelles (voir « Dispersion »), entre dans
les avertissements : le verdict n'est alors pas concluant.

Trois compléments. Les deux premiers sont informatifs et n'entrent pas dans le
verdict ; le troisième n'y entre que par ses mises en garde.

Règle entière. La vraie _reject_contradictions du bot est rejouée sur chaque
table, avec le vrai engine_head_action (hors image, celui de
fairdiplomacy/utils/pseudo_commitments.py à côté du bot, à la place de la
doublure ; un témoin le contrôle au chargement). Scénario : le bot a promis E
et déclare le rompre pour N, E et N ordres distincts d'une même unité, pris
parmi les ordres valués d'au moins une table du groupe (niveau « groupe »,
groupes d'au moins deux tables) ; les autres engagements du groupe restent
promis. Écarté et compté : E sur l'unité d'un autre engagement du groupe (deux
paroles sur une unité). Deux classes : « table à jour » si E est un engagement
du groupe (la table a été calculée sous la promesse), « table antérieure »
sinon (le bot est en avance sur le moteur). Issue par (scénario, table) :
« remplace », ou le motif du refus (unknown_value, below_margin, not_played).
Un couple absent d'une table n'est pas écarté : la règle y rend unknown_value.
Pour n tables dont k « remplace » : k x (n - k) désaccords sur n x (n - 1) / 2
paires ; le taux de désaccord est la probabilité que deux recherches de la même
position décident différemment. Disputé : k >= 1 (G(E, N) = -G(N, E) : la
moitié au moins des couples est refusée partout). Attribution : un désaccord
est attribué au motif de la table qui refuse (additif). Instabilité propre de
chaque condition (non additive), u étant le nombre de tables où l'issue n'est
pas unknown_value : valeur connue, u x (n - u) sur les paires ; marge, m tables
connues hors below_margin, m x (u - m) sur u x (u - 1) / 2 ; condition (e),
e tables « remplace » quand la marge est retirée (margin = -inf), e x (u - e).
Acceptation sur bruit effective : « remplace » alors qu'au moins une autre
table du groupe porte le couple et que la moyenne de G sur ces tables est <= 0.
Acceptation sans autre table, comptée à part et jamais additionnée :
« remplace » alors qu'aucune autre table du groupe ne porte le couple -- pas
reproductible (les autres recherches rendent unknown_value), mais rien ne dit
que son gain soit du bruit ; elle relève de l'instabilité de l'ensemble des
candidats, que mesure déjà l'attribution à unknown_value.

Décompte par événement (informatif, hors verdict : le critère publié reste le
verdict par observation ; décision du mainteneur, 2026-10-10). Unité : le couple
(table, E), E étant la promesse rompue, sur les recherches A sans engagement
seules, jugé par la règle entière à la marge du bot. Exposé : au moins un N
sans gain (le couple (E, N) est dans la table et dans au moins une autre du
groupe, et la moyenne de G sur ces autres tables est <= 0). (a) : part des
(table, E) exposés qui ont au moins une acceptation sur bruit. (b) : part des
remplacements acceptés qui sont sur bruit (les acceptations sans autre table
sont au dénominateur, jamais au numérateur). Lecture indicative : « protégerait »
si (a) <= 1 % et (b) <= 5 % ; « ne protégerait pas » si (a) > 5 % ou
(b) > 20 % ; « partiel » entre les deux ; « indéterminée » sans (table, E)
exposé. Deux lignes de plus : la restriction aux promesses « réalistes » (E est
un ordre d'un des plans exportés de la table jugée, ce que Claude voit), et le
rappel « marge seule » (G > marge sans la condition (e) : les acceptations du
critère par observation, comptées par événement).

Effet de la recherche B, apparié. Unité : le tirage (fichier, tirage) où
coexistent la recherche A sans engagement et la table du groupe.
delta = G_B - G_A dans le tirage ; effet = moyenne des delta ; erreur type
s / racine(n), s à n - 1 ; intervalle à 95 % de Student (quantiles recalculés
par intégration numérique jusqu'à 20 degrés de liberté, 1,96 « approché »
au-delà) ; pas d'erreur type à moins de 3 tirages. Lecture des seuls couples
principaux (E engagé, N) : « distinguable du bruit » si l'intervalle exclut 0,
« négligeable devant la marge » s'il tient dans +/- marge / 2, « non conclusif »
sinon. Synthèse entre positions (unité : la position) : moyenne par position
de l'effet de ses couples principaux estimés sur au moins 3 tirages (les autres
sont écartés et comptés, comme les positions qui n'en gardent aucun), refaite
sans le tirage sur lequel l'engagement a été choisi. B - A mêle le message déclencheur, la
mise à jour incrémentale et l'engagement : c'est l'effet de la recherche B
entière. L'estimateur non apparié (différence de moyennes) reste sous ses clés.

Dispersion dans un fichier et entre fichiers. Sur les couples présents dans
toutes les tables du groupe, G en entiers (x 1e5) et calculs en fractions.
Écart type intra : racine du carré moyen dans les fichiers. Groupe réparti sur
au moins deux fichiers d'au moins deux tables : R = CM inter / CM intra, et
test par permutation exacte des tables entre fichiers de mêmes tailles (p =
part des répartitions dont R >= R observé, comparé par produit en croix ;
unilatéral supérieur ; au plus 20 000 répartitions). p <= 0,05 : « indépendance
des tirages d'un lancement rejetée » ; sinon « non rejetée », jamais établie.
Tables jumelles : paires de tables d'un même fichier et d'un même type aux
order_values identiques ou au search.lambda identique (attendu : aucune).
Le contrôle par search.lambda suppose un lambda dynamique, différent d'un
tirage à l'autre (mis en cache par état d'agent et par phase, il ne se répète
que si l'état est réutilisé). Un fichier dont toutes les paires ont le même
lambda est nommé dans la mise en garde, avec les deux causes possibles : état
partagé entre tirages, ou lambda non dynamique dans la configuration.
Un rejet ou une paire jumelle, quel que soit le type de recherche, est une
mise en garde en tête du tableau et un avertissement du verdict.
Engagements différents d'un fichier à l'autre : quand les recherches B d'une
position n'ont pas les mêmes engagements retenus dans tous ses fichiers (le
choix de l'engagement dépend du tirage), elles forment des groupes distincts
et le test sur le type B n'existe pas ; le constat est rendu tel quel, une
ligne par position, avec les engagements de chaque fichier.

Sorties : un tableau lisible sur la sortie standard, le détail complet en JSON
(<dossier>/bruit_valeurs.json, ou --sortie ; sans --sortie, refus d'écrire dans
un dépôt git hors de son dossier amont/, que git ignore : un relevé contient de
l'état de partie). Relevé illisible : un message sur la sortie d'erreur et le
code de retour 2.
"""
import argparse
import fractions
import itertools
import json
import math
import re
import sys
from pathlib import Path
from unittest import mock

# Avant tout chargement : commun.charger lit cicero/overlay, où un .pyc
# passerait pour un fichier d'overlay (outils/exporter_patchs.sh --verifier, install.sh ; #27).
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import commun  # noqa: E402

MOTIF = "m1_*.jsonl"
MARGES_BALAYEES = (0.02, 0.03, 0.05, 0.08, 0.10)
CENTILES = (("mediane", 0.50), ("c90", 0.90), ("c95", 0.95), ("c99", 0.99))
TYPE_SANS_ENGAGEMENT = "A"  # la recherche de référence de l'effet de l'engagement

# Critère d'expert-cicero (#26), en fractions de la marge.
PROTEGE_C99_TOTAL = 0.5
PROTEGE_C99_PIRE_POSITION = 1.0
NE_PROTEGE_PAS_C95_TOTAL = 1.0
NE_PROTEGE_PAS_PART_SUR_BRUIT = 0.01
# En deçà, pas de verdict : jusqu'à 100 valeurs le 99e centile est le maximum ; à
# deux tables par groupe, d n'est que l'écart de la paire. Dix positions : un
# choix de prudence, le 99e centile des écarts par paire va de 0,0027 à 0,0629
# d'une position à l'autre sur les relevés du 2026-10-03.
MIN_OBSERVATIONS = 100
MIN_TABLES_PAR_GROUPE = 3
MIN_POSITIONS = 10
# Le critère se lit sur les recherches A sans engagement (décision du mainteneur, 2026-10-10) :
# la recherche B d'un tirage est une mise à jour incrémentale de sa recherche A, sur le même
# état d'agent ; ses observations ne sont pas indépendantes de celles de A.
NIVEAU_DE_LA_SPECIFICATION = "recherches_a"
TYPE_AVEC_ENGAGEMENT = "B"

NIVEAUX = (
    ("recherches_a", "recherches A sans engagement, seules, par position : le niveau du critère"),
    ("recherches_b", "recherches B seules, par position et engagements retenus -- informatif"),
    ("groupe", "position, engagements retenus et type de recherche : cumul de A et de B -- informatif"),
    ("engagements", "position et engagements retenus, types de recherche réunis -- informatif"),
)
HORS_CRITERE = {
    "recherches_b": "niveau « recherches_b » : la recherche B d'un tirage est une mise à jour incrémentale de sa "
                    "recherche A, pas une mesure indépendante du bruit ; donné à titre indicatif seulement",
    "groupe": "niveau « groupe » : cumul des recherches A et B, qui ne sont pas indépendantes (B est une mise à jour "
              "incrémentale du même tirage) : l'effectif affiché dépasse l'information réelle ; donné à titre "
              "indicatif seulement",
    "engagements": "niveau « engagements » : hors de la spécification, donné à titre indicatif seulement",
}
CLASSES = ("memes_engagements", "engagements_differents")
PORTEUSES = ("inchangee", "changee", "inconnue")
CLES_RECHERCHE = ("game_id", "phase", "puissance", "recherche", "engagements_retenus_par_le_moteur")

# Règle entière : les issues sont lues dans le retour de _reject_contradictions.
MOTIFS = ("unknown_value", "below_margin", "not_played")
ISSUES = ("remplace",) + MOTIFS
CLASSES_REGLE = (
    ("table_a_jour", "table à jour", "E est un engagement du groupe : la table a été calculée sous la promesse"),
    ("table_anterieure", "table antérieure", "E n'était pas dans la recherche : le bot est en avance sur le moteur"),
)
# Décompte par événement (avis d'expert-cicero du 2026-10-10 sur #26, § 1.1), en parts : (a) des (table, E)
# exposés, (b) des remplacements acceptés. Informatif : aucun de ces seuils n'entre dans le verdict.
PROTEGERAIT_A, PROTEGERAIT_B = 0.01, 0.05
NE_PROTEGERAIT_PAS_A, NE_PROTEGERAIT_PAS_B = 0.05, 0.20
LECTURES_PAR_EVENEMENT = ("protégerait", "partiel", "ne protégerait pas", "indéterminée")
DESTINATAIRE = "X"  # à qui les promesses rejouées sont faites : un seul, son nom n'entre dans aucune issue
# Témoin du chargement : deux actions d'une unité, lambda nul (le score est la valeur). Rompre
# BUR pour PIC gagne 0,10 et PIC est l'action de tête : la règle remplace. Sous la doublure
# d'engine_head_action, elle rendrait not_played.
TEMOIN = {
    "ancien": "A PAR - BUR", "nouveau": "A PAR - PIC",
    "entree": {
        "plans": [], "order_values": {"A PAR - PIC": 0.40, "A PAR - BUR": 0.30},
        "candidates": [{"orders": ["A PAR - PIC"], "value": 0.40, "prob": 0.25},
                       {"orders": ["A PAR - BUR"], "value": 0.30, "prob": 0.25}],
        "search": {"lambda": 0.0, "boost": 3.0, "max_prob": 0.4},
    },
}

# Effet apparié et dispersion.
UNITE = 100000  # G est exporté à 5 décimales : en entiers, les sommes de carrés sont exactes
MIN_TIRAGES_ERREUR_TYPE = 3
SEUIL_P = 0.05
MAX_REPARTITIONS = 20000
CORRELATIONS_DE_PUISSANCE = (0.2, 0.5, 0.8, 0.9)
LIBELLE_EFFET = "effet de la recherche B (message, mise à jour incrémentale, engagement)"
# Quantile 0,975 de la loi de Student, par degré de liberté (1 à 20) : recalculé par
# intégration numérique (student_quantile, que tests/test_bruit_valeurs.py compare à cette
# table). Au-delà de 20 : celui de la loi normale, rendu avec la mention « approché ».
STUDENT_975 = (
    12.706205, 4.302653, 3.182446, 2.776445, 2.570582, 2.446912, 2.364624, 2.306004, 2.262157, 2.228139,
    2.200985, 2.178813, 2.160369, 2.144787, 2.131450, 2.119905, 2.109816, 2.100922, 2.093024, 2.085963,
)
NORMALE_975 = 1.96


class ErreurReleve(Exception):
    """Relevé absent, vide ou illisible : un message pour l'utilisateur, pas une trace."""


# ---------------------------------------------------------------------------
# Règle du bot de dialogue (lue, pas recopiée)
# ---------------------------------------------------------------------------

def trouver_bot(chemin=None):
    if chemin:
        candidats = [Path(chemin)]
    else:
        candidats = [Path("/opt/cicero/claude_dialogue_bot.py")]  # image
        if len(commun.ICI.parents) > 1:  # dépôt, ou amont/mesure ; pas /mesure, dans un conteneur
            candidats.insert(0, commun.ICI.parents[1] / "cicero" / "overlay" / "claude_dialogue_bot.py")
    for candidat in candidats:
        if candidat.is_file():
            return candidat
    raise ErreurReleve(
        "claude_dialogue_bot.py introuvable (%s) : donner son chemin par --bot"
        % ", ".join(str(c) for c in candidats)
    )


def brancher_tete(module, bot):
    """Donne au bot le vrai engine_head_action quand il a reçu celui d'une doublure.

    Hors image, fairdiplomacy.utils.pseudo_commitments est une doublure : la
    condition (e) de _reject_contradictions répondrait toujours « pas joué ». La
    fonction est prise dans le fichier voisin du bot, au même chemin relatif dans
    l'overlay et dans l'image (comme tests/banc_promesses.py)."""
    if not isinstance(module.engine_head_action, mock.Mock):
        return
    source = bot.parent / "fairdiplomacy" / "utils" / "pseudo_commitments.py"
    try:
        module.engine_head_action = commun.charger("mesure_bruit_pseudo_commitments", source).engine_head_action
    except Exception as e:
        raise ErreurReleve("%s : engine_head_action illisible (%s: %s)" % (source, type(e).__name__, e))


def issue_de_la_regle(rejeter, ancien, nouveau, engagements, entree, marge=None):
    """(issue, gain) de _reject_contradictions pour « promis `ancien`, déclaré rompu pour `nouveau` ».

    L'appel de production (claude_dialogue_bot.process_bot) : les promesses tenues
    sont les `engagements` et `ancien` ; `marge` None laisse celle du bot. Issue :
    « remplace », ou le motif rendu avec l'ordre rétrogradé. Lève ErreurReleve sur
    tout autre retour : la règle a changé, le script doit suivre."""
    promesses = [f for f in engagements if f != ancien] + [ancien]
    try:
        _acceptes, retrogrades, remplaces, contradictoires, ignores = rejeter(
            [nouveau], {DESTINATAIRE: promesses}, entree.get("plans"), margin=marge, betray=[ancien],
            order_values=entree.get("order_values"), candidates=entree.get("candidates"), search=entree.get("search"))
    except Exception as e:
        raise ErreurReleve("_reject_contradictions (%s -> %s) : %s: %s" % (ancien, nouveau, type(e).__name__, e))
    if contradictoires or ignores or len(retrogrades) + len(remplaces) != 1:
        raise ErreurReleve(
            "_reject_contradictions (%s -> %s) : retour inattendu (%d rétrogradé(s), %d remplacé(s), %d contradictoire(s), "
            "%d ignoré(s)) -- la règle a changé, le script doit suivre"
            % (ancien, nouveau, len(retrogrades), len(remplaces), len(contradictoires), len(ignores)))
    if remplaces:
        return "remplace", remplaces[0][3]
    if retrogrades[0][2] not in MOTIFS:
        raise ErreurReleve(
            "_reject_contradictions (%s -> %s) : motif inattendu « %s » -- la règle a changé, le script doit suivre"
            % (ancien, nouveau, retrogrades[0][2]))
    return retrogrades[0][2], retrogrades[0][3]


def temoin(module, bot):
    """Lève ErreurReleve si la règle chargée ne remplace pas la promesse du témoin."""
    try:
        issue, _gain = issue_de_la_regle(
            module._reject_contradictions, TEMOIN["ancien"], TEMOIN["nouveau"], (), TEMOIN["entree"])
    except ErreurReleve as e:
        raise ErreurReleve("%s : règle mal chargée (%s)" % (bot, e))
    if issue != "remplace":
        raise ErreurReleve(
            "%s : règle mal chargée -- le témoin (%s promis, rompu pour %s, gain 0,10, %s en tête) rend « %s » au lieu "
            "de « remplace » ; engine_head_action est-il celui de pseudo_commitments ?"
            % (bot, TEMOIN["ancien"], TEMOIN["nouveau"], TEMOIN["nouveau"], issue))


def charger_bot(chemin=None):
    """(module, chemin) du bot de dialogue, chargé comme dans les essais à sec, la règle contrôlée par le témoin."""
    bot = trouver_bot(chemin)
    if not commun.cicero_present():
        commun.installer_doublures()
    try:
        module = commun.charger("mesure_bruit_claude_dialogue_bot", bot)
        float(module.COMMITMENT_SWITCH_MARGIN), module._order_loc, module._reject_contradictions
    except Exception as e:
        raise ErreurReleve("%s : COMMITMENT_SWITCH_MARGIN, _order_loc ou _reject_contradictions illisible (%s: %s)"
                           % (bot, type(e).__name__, e))
    brancher_tete(module, bot)
    temoin(module, bot)
    return module, bot


def charger_regle(chemin=None):
    """(marge, _order_loc, chemin) du bot de dialogue ; la règle entière se prend dans charger_bot."""
    module, bot = charger_bot(chemin)
    return float(module.COMMITMENT_SWITCH_MARGIN), module._order_loc, bot


# ---------------------------------------------------------------------------
# Lecture des relevés
# ---------------------------------------------------------------------------

def _nombre(x):
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:  # entier trop grand pour un flottant
        return False


def gains(order_values, order_loc):
    """{(E, N): G} pour tout couple ordonné d'ordres distincts d'une même unité."""
    par_unite = {}
    for ordre in order_values:
        unite = order_loc(ordre)
        if unite is not None:
            par_unite.setdefault(unite, []).append(ordre)
    g = {}
    for ordres in par_unite.values():
        for e, n in itertools.permutations(ordres, 2):
            g[(e, n)] = round(order_values[n] - order_values[e], 5)  # comme _reject_contradictions
    return g


def porteuses(order_values, candidates):
    """{ordre: action porteuse}, ou None si la table des actions candidates manque
    ou ne porte pas tous les ordres. Lève ErreurReleve si elle n'est pas une liste d'actions."""
    if not candidates:
        return None
    if not isinstance(candidates, list):
        raise ErreurReleve("candidates n'est pas une liste d'actions")
    p = {}
    for candidate in candidates:
        ordres = candidate.get("orders") if isinstance(candidate, dict) else None
        if not isinstance(ordres, list) or not all(isinstance(ordre, str) for ordre in ordres):
            raise ErreurReleve("candidates porte une action qui n'est pas une liste d'ordres")
        for ordre in ordres:
            p.setdefault(ordre, tuple(ordres))
    return p if all(ordre in p for ordre in order_values) else None


def lire_releves(dossier, order_loc):
    """Rend (tables, lecture). Lève ErreurReleve sur un relevé absent, vide ou illisible."""
    dossier = Path(dossier)
    if not dossier.is_dir():
        raise ErreurReleve("%s n'est pas un dossier" % dossier)
    fichiers = sorted(dossier.glob(MOTIF))
    if not fichiers:
        raise ErreurReleve("aucun relevé %s dans %s" % (MOTIF, dossier))
    tables, sans_table, comparaisons, a_sec = [], [], 0, 0
    for fichier in fichiers:
        try:
            lignes = fichier.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            raise ErreurReleve("%s : illisible (%s)" % (fichier, e))
        if not any(ligne.strip() for ligne in lignes):
            raise ErreurReleve("%s : relevé vide" % fichier)
        for numero, ligne in enumerate(lignes, 1):
            if not ligne.strip():
                continue
            ou = "%s:%d" % (fichier, numero)
            try:
                releve = json.loads(ligne)
            except (ValueError, RecursionError) as e:
                raise ErreurReleve("%s : ligne qui n'est pas du JSON (%s)" % (ou, str(e) or type(e).__name__))
            if not isinstance(releve, dict):
                raise ErreurReleve("%s : ligne qui n'est pas un objet JSON" % ou)
            if "comparaison" in releve:
                comparaisons += 1
                continue
            manquantes = [cle for cle in CLES_RECHERCHE if cle not in releve]
            if manquantes:
                raise ErreurReleve("%s : relevé de recherche sans %s" % (ou, ", ".join(manquantes)))
            engagements = releve["engagements_retenus_par_le_moteur"]
            if not isinstance(engagements, list) or not all(isinstance(o, str) for o in engagements):
                raise ErreurReleve("%s : engagements_retenus_par_le_moteur n'est pas une liste d'ordres" % ou)
            entree = releve.get("entree")
            order_values = entree.get("order_values") if isinstance(entree, dict) else None
            if not order_values:  # recherche sans entrée exportée : relevée telle quelle par rejeu_moteur
                sans_table.append(ou)
                continue
            if not isinstance(order_values, dict) or not all(_nombre(v) for v in order_values.values()):
                raise ErreurReleve("%s : order_values n'est pas un dictionnaire ordre -> valeur" % ou)
            try:
                porteuses_de_la_table = porteuses(order_values, entree.get("candidates"))
            except ErreurReleve as e:
                raise ErreurReleve("%s : %s" % (ou, e))
            a_sec += bool(releve.get("a_sec"))
            tables.append({
                "nom": "%s:%d" % (fichier.name, numero),
                "position": (str(releve["game_id"]), str(releve["phase"]), str(releve["puissance"])),
                "engagements": tuple(sorted(engagements)),
                "recherche": str(releve["recherche"]),
                "tirage": releve.get("tirage"),
                "g": gains(order_values, order_loc),
                "porteuses": porteuses_de_la_table,
                "fichier": fichier.name,
                "tirage_du_choix": releve.get("engagement_choisi_au_tirage"),
                # La table telle que le bot la lit, pour rejouer la règle entière.
                "entree": {cle: entree.get(cle) for cle in ("plans", "order_values", "candidates", "search")},
            })
    if not tables:
        raise ErreurReleve("aucune table exportée dans les %d relevé(s) de %s" % (len(fichiers), dossier))
    lecture = {
        "dossier": str(dossier), "fichiers": len(fichiers), "tables": len(tables),
        "recherches_sans_table": sans_table, "lignes_comparaison_ignorees": comparaisons,
        "tables_d_essai_a_sec": a_sec,
        "parties": sorted({t["position"][0] for t in tables}),
        "phases": sorted({t["position"][1] for t in tables}),
        "positions": len({t["position"] for t in tables}),
    }
    return tables, lecture


# ---------------------------------------------------------------------------
# Calculs (fonctions pures)
# ---------------------------------------------------------------------------

def centile(valeurs, q):
    """Valeur observée de rang ceil((n - 1) x q), à partir de 0 ; None sur une liste vide."""
    if not valeurs:
        return None
    triees = sorted(valeurs)
    return triees[int(math.ceil((len(triees) - 1) * q))]


def resumer(valeurs):
    """Effectif, médiane, 90e, 95e, 99e centile et maximum."""
    r = {"n": len(valeurs)}
    for nom, q in CENTILES:
        r[nom] = centile(valeurs, q)
    r["max"] = max(valeurs) if valeurs else None
    return r


def _porteuse_changee(tables, couple):
    """True / False, ou None si une des tables n'a pas d'actions candidates."""
    if any(t["porteuses"] is None for t in tables):
        return None
    return any(len({t["porteuses"][ordre] for t in tables}) > 1 for ordre in couple)


def cle_groupe(table, niveau):
    cle = table["position"] + (table["engagements"],)
    return cle if niveau == "engagements" else cle + (table["recherche"],)


def tables_du_niveau(tables, niveau):
    """Les tables d'un niveau : toutes, sauf aux deux niveaux restreints à un type de recherche."""
    if niveau == "recherches_a":
        return [t for t in tables if t["recherche"] == TYPE_SANS_ENGAGEMENT and not t["engagements"]]
    if niveau == "recherches_b":
        return [t for t in tables if t["recherche"] == TYPE_AVEC_ENGAGEMENT]
    return tables


def observations(tables, niveau):
    """Une observation par (groupe, couple, table) : G de la table, moyenne des autres, d.

    Seuls comptent les groupes d'au moins deux tables et, dans un groupe, les
    couples présents dans au moins deux tables. Rend aussi la taille de chaque
    groupe et, par groupe d'au moins deux tables, le nombre de couples écartés
    parce qu'une seule table les porte."""
    groupes = {}
    for t in tables:
        groupes.setdefault(cle_groupe(t, niveau), []).append(t)
    obs, seuls = [], {}
    for cle, membres in sorted(groupes.items()):
        if len(membres) < 2:
            continue
        seuls[cle] = 0
        couples = sorted({c for t in membres for c in t["g"]})
        for couple in couples:
            presentes = [t for t in membres if couple in t["g"]]
            if len(presentes) < 2:
                seuls[cle] += 1
                continue
            changee = _porteuse_changee(presentes, couple)
            for t in presentes:
                autres = [u["g"][couple] for u in presentes if u is not t]
                reference = sum(autres) / len(autres)
                obs.append({
                    "groupe": cle, "position": cle[:3], "couple": couple, "table": t["nom"],
                    "g": t["g"][couple], "reference": reference, "d": round(t["g"][couple] - reference, 10),
                    "tables": len(presentes), "porteuse_changee": changee,
                })
    return obs, {cle: len(membres) for cle, membres in groupes.items()}, seuls


def _par_porteuse(lignes, valeur):
    tri = {nom: [] for nom in PORTEUSES}
    for ligne in lignes:
        nom = "inconnue" if ligne["porteuse_changee"] is None else ("changee" if ligne["porteuse_changee"] else "inchangee")
        tri[nom].append(valeur(ligne))
    return {nom: resumer(v) for nom, v in tri.items()}


def _part(n, total):
    return None if not total else n / total


def cle_marge(marge):
    return "%.2f" % marge


def bloc_bruit(obs, marges, couples_seuls=0):
    """Indicateurs (1) à (4), (6) et (7) sur un ensemble d'observations."""
    abs_d = [abs(o["d"]) for o in obs]
    sans_gain = sum(1 for o in obs if o["reference"] <= 0)  # la population à risque
    couples = {}
    for o in obs:
        couples.setdefault((o["groupe"], o["couple"]), []).append(o)
    bloc = {
        "tables": len({o["table"] for o in obs}),
        "couples": len(couples),
        "couples_dans_une_seule_table": couples_seuls,
        "observations": len(obs),
        "observations_sans_gain": sans_gain,
        "abs_d": resumer(abs_d),
        "par_porteuse": _par_porteuse(obs, lambda o: abs(o["d"])),
        "par_marge": {},
    }
    for marge in marges:
        non_unanimes = sum(1 for lignes in couples.values() if len({o["g"] > marge for o in lignes}) > 1)
        acceptations = [o for o in obs if o["g"] > marge]
        sur_bruit = [o for o in acceptations if o["reference"] <= 0]
        bloc["par_marge"][cle_marge(marge)] = {
            "couples_non_unanimes": non_unanimes,
            "part_couples_non_unanimes": _part(non_unanimes, len(couples)),
            "acceptations": len(acceptations),
            "acceptations_sur_bruit": len(sur_bruit),
            # Ce qui les porte : une table qui s'écarte des autres en donne plusieurs à elle seule.
            "tables_sur_bruit": len({o["table"] for o in sur_bruit}),
            "ordres_sur_bruit": len({(o["table"], o["couple"][0]) for o in sur_bruit}),
            "positions_sur_bruit": len({o["position"] for o in sur_bruit}),
            "part_sur_bruit_des_observations_sans_gain": _part(len(sur_bruit), sans_gain),
            "part_sur_bruit_des_observations": _part(len(sur_bruit), len(obs)),
            "part_sur_bruit_des_acceptations": _part(len(sur_bruit), len(acceptations)),
            "marge_effective": None if not abs_d else round(marge - centile(abs_d, 0.99), 10),
        }
    return bloc


def nom_position(position):
    return " ".join(position)


def nom_groupe(cle):
    nom = "%s | %s" % (nom_position(cle[:3]), ", ".join(cle[3]) or "sans engagement")
    return nom + (" | %s" % cle[4] if len(cle) > 4 else "")


def niveau_bruit(tables, niveau, marges):
    tables = tables_du_niveau(tables, niveau)
    obs, tailles, seuls = observations(tables, niveau)
    par_position, par_groupe = {}, {}
    for o in obs:
        par_position.setdefault(o["position"], []).append(o)
        par_groupe.setdefault(o["groupe"], []).append(o)

    def seuls_de(position):
        return sum(n for g, n in seuls.items() if g[:3] == position)

    return {
        "groupes": len(tailles),
        "groupes_d_au_moins_deux_tables": len(seuls),
        "groupes_sans_couple_commun": sum(1 for g in seuls if g not in par_groupe),
        "tables_par_groupe_min": min(tailles[g] for g in par_groupe) if par_groupe else None,
        "types_de_recherche_reunis": any(
            len({t["recherche"] for t in tables if cle_groupe(t, niveau) == g}) > 1 for g in par_groupe
        ),
        "total": bloc_bruit(obs, marges, sum(seuls.values())),
        "par_position": {
            nom_position(p): bloc_bruit(o, marges, seuls_de(p)) for p, o in sorted(par_position.items())
        },
        "par_groupe": {nom_groupe(g): bloc_bruit(o, marges, seuls[g]) for g, o in sorted(par_groupe.items())},
    }


def ecarts_par_paire(tables):
    """Une ligne par (paire de tables d'une même position, couple commun aux deux)."""
    par_position = {}
    for t in tables:
        par_position.setdefault(t["position"], []).append(t)
    lignes, paires = [], []
    for position, membres in sorted(par_position.items()):
        for t1, t2 in itertools.combinations(membres, 2):
            classe = CLASSES[0] if t1["engagements"] == t2["engagements"] else CLASSES[1]
            paire = {
                "position": position, "classe": classe, "tables": (t1["nom"], t2["nom"]),
                "meme_type": t1["recherche"] == t2["recherche"],
                "couples_seuls": len(set(t1["g"]) ^ set(t2["g"])),
            }
            paires.append(paire)
            for couple in sorted(set(t1["g"]) & set(t2["g"])):
                lignes.append(dict(
                    paire, couple=couple, g=(t1["g"][couple], t2["g"][couple]),
                    ecart=round(abs(t1["g"][couple] - t2["g"][couple]), 10),
                    porteuse_changee=_porteuse_changee((t1, t2), couple),
                ))
    return lignes, paires


def bloc_paires(lignes, paires, marges):
    bloc = {
        "paires": len(paires),
        "paires_de_meme_type": sum(1 for p in paires if p["meme_type"]),
        "couples": len(lignes),
        "couples_dans_une_seule_table": sum(p["couples_seuls"] for p in paires),
        "ecart": resumer([ligne["ecart"] for ligne in lignes]),
        "par_porteuse": _par_porteuse(lignes, lambda ligne: ligne["ecart"]),
        "par_marge": {},
    }
    for marge in marges:
        changes = sum(1 for ligne in lignes if (ligne["g"][0] > marge) != (ligne["g"][1] > marge))
        sur_bruit = sum(1 for ligne in lignes if max(ligne["g"]) > marge and min(ligne["g"]) <= 0)
        bloc["par_marge"][cle_marge(marge)] = {
            "verdicts_changes": changes,
            "part_verdicts_changes": _part(changes, len(lignes)),
            "acceptations_sur_bruit": sur_bruit,
            "part_acceptations_sur_bruit": _part(sur_bruit, len(lignes)),
        }
    return bloc


def synthese_paires(tables, marges):
    lignes, paires = ecarts_par_paire(tables)
    sortie = {}
    for classe in CLASSES + ("toutes",):
        l_c = [x for x in lignes if classe in ("toutes", x["classe"])]
        p_c = [x for x in paires if classe in ("toutes", x["classe"])]
        positions = sorted({p["position"] for p in p_c})
        sortie[classe] = {
            "total": bloc_paires(l_c, p_c, marges),
            "par_position": {
                nom_position(position): bloc_paires(
                    [x for x in l_c if x["position"] == position],
                    [x for x in p_c if x["position"] == position], marges)
                for position in positions
            },
        }
    return sortie


def effet_engagement(tables):
    """Moyenne de G avec les engagements moins moyenne de G en recherche A sans engagement,
    par couple commun aux deux groupes : l'effet de l'engagement, à part du bruit."""
    groupes = {}
    for t in tables:
        groupes.setdefault(cle_groupe(t, "groupe"), []).append(t)

    def moyennes(membres):
        somme = {}
        for t in membres:
            for couple, g in t["g"].items():
                somme.setdefault(couple, []).append(g)
        return {couple: sum(v) / len(v) for couple, v in somme.items()}

    lignes = []
    for cle, membres in sorted(groupes.items()):
        position, engagements, recherche = cle[:3], cle[3], cle[4]
        reference = groupes.get(position + ((), TYPE_SANS_ENGAGEMENT))
        if not engagements or not reference:
            continue
        avec, sans = moyennes(membres), moyennes(reference)
        effets = {c: round(avec[c] - sans[c], 10) for c in sorted(set(avec) & set(sans))}
        vers = [e for (_ancien, nouveau), e in effets.items() if nouveau in engagements]
        lignes.append({
            "groupe": nom_groupe(cle), "position": nom_position(position), "recherche": recherche,
            "tables_avec": len(membres), "tables_sans": len(reference), "couples": len(effets),
            "abs_effet": resumer([abs(e) for e in effets.values()]),
            # G(E, N) et G(N, E) sont opposés : la moyenne signée n'a de sens que sur
            # les couples orientés vers l'ordre engagé (N engagé).
            "couples_vers_l_ordre_engage": len(vers),
            "effet_moyen_vers_l_ordre_engage": None if not vers else round(sum(vers) / len(vers), 10),
            "effet_max_vers_l_ordre_engage": max(vers) if vers else None,
            "effet_min_vers_l_ordre_engage": min(vers) if vers else None,
            "_effets": effets, "_vers": vers,
        })
    tous = [abs(e) for ligne in lignes for e in ligne["_effets"].values()]
    vers = [e for ligne in lignes for e in ligne["_vers"]]
    par_type = {}
    for recherche in sorted({ligne["recherche"] for ligne in lignes}):
        du_type = [ligne for ligne in lignes if ligne["recherche"] == recherche]
        v = [e for ligne in du_type for e in ligne["_vers"]]
        par_type[recherche] = {
            "groupes": len(du_type),
            "abs_effet": resumer([abs(e) for ligne in du_type for e in ligne["_effets"].values()]),
            "couples_vers_l_ordre_engage": len(v),
            "effet_moyen_vers_l_ordre_engage": None if not v else round(sum(v) / len(v), 10),
        }
    for ligne in lignes:
        del ligne["_effets"], ligne["_vers"]
    return {
        "reference": "recherche %s sans engagement de la même position" % TYPE_SANS_ENGAGEMENT,
        "total": {
            "groupes": len(lignes), "abs_effet": resumer(tous), "couples_vers_l_ordre_engage": len(vers),
            "effet_moyen_vers_l_ordre_engage": None if not vers else round(sum(vers) / len(vers), 10),
        },
        "par_type_de_recherche": par_type,
        "par_groupe": lignes,
    }

# ---------------------------------------------------------------------------
# Règle entière (la vraie _reject_contradictions, rejouée table par table)
# ---------------------------------------------------------------------------

def _paires(n):
    return n * (n - 1) // 2


def _taux(desaccords, paires):
    return {"desaccords": desaccords, "paires": paires, "taux": _part(desaccords, paires)}


def scenarios_de_la_regle(tables, rejeter, order_loc, marges):
    """Une ligne par (groupe d'au moins deux tables, E, N) : l'issue de la règle dans chaque table.

    Rend (lignes, états impossibles écartés par groupe, nombre de groupes d'une seule table)."""
    groupes = {}
    for t in tables:
        groupes.setdefault(cle_groupe(t, "groupe"), []).append(t)
    lignes, impossibles, seuls = [], {}, 0
    for cle, membres in sorted(groupes.items()):
        if len(membres) < 2:
            seuls += 1
            continue
        engages = cle[3]
        unites_engagees = {}
        for f in engages:
            unites_engagees.setdefault(order_loc(f), set()).add(f)
        par_unite = {}
        for ordre in sorted({o for t in membres for o in t["entree"]["order_values"]}):
            if order_loc(ordre) is not None:
                par_unite.setdefault(order_loc(ordre), []).append(ordre)
        impossibles[cle] = 0
        for unite, ordres in sorted(par_unite.items()):
            for ancien, nouveau in itertools.permutations(ordres, 2):
                if unites_engagees.get(unite, set()) - {ancien}:  # deux paroles sur une unité (exigence 2.5)
                    impossibles[cle] += 1
                    continue

                def issues(marge):
                    rendus = []
                    for t in membres:
                        try:
                            rendus.append(issue_de_la_regle(rejeter, ancien, nouveau, engages, t["entree"], marge))
                        except ErreurReleve as e:
                            raise ErreurReleve("%s : %s" % (t["nom"], e))
                    return rendus

                rendus = issues(None)  # la marge du bot : l'appel de production
                sans_marge = [issue for issue, _gain in issues(float("-inf"))]
                if "below_margin" in sans_marge or any(
                        (a == "unknown_value") != (b == "unknown_value") for (a, _g), b in zip(rendus, sans_marge)):
                    raise ErreurReleve(
                        "_reject_contradictions (%s -> %s, groupe %s) : sans marge, les issues %s ne sont pas celles "
                        "attendues -- la règle a changé, le script doit suivre"
                        % (ancien, nouveau, nom_groupe(cle), sans_marge))
                g = [t["g"].get((ancien, nouveau)) for t in membres]
                # Deux comptes disjoints : sans autre table qui porte le couple, rien ne dit que le gain soit du bruit.
                sur_bruit, sans_autre, sans_gain = [], [], []
                for i, (issue, _gain) in enumerate(rendus):
                    autres = [x for j, x in enumerate(g) if j != i and x is not None]
                    sans_autre.append(issue == "remplace" and not autres)
                    sur_bruit.append(issue == "remplace" and bool(autres) and sum(autres) / len(autres) <= 0)
                    # La population à risque du décompte par événement : le couple est dans la table et ailleurs.
                    sans_gain.append(g[i] is not None and bool(autres) and sum(autres) / len(autres) <= 0)
                lignes.append({
                    "groupe": cle, "position": cle[:3], "couple": (ancien, nouveau),
                    "classe": CLASSES_REGLE[0][0] if ancien in engages else CLASSES_REGLE[1][0],
                    "tables": [t["nom"] for t in membres],
                    "issues": [issue for issue, _gain in rendus], "gains": [gain for _issue, gain in rendus],
                    "sans_marge": sans_marge,
                    "par_marge": {cle_marge(m): [issue for issue, _gain in issues(m)] for m in marges},
                    "sur_bruit": sur_bruit, "sans_autre_table": sans_autre, "sans_gain": sans_gain,
                })
    return lignes, impossibles, seuls


def _desaccords(listes):
    """Désaccords par paire de tables sur la décision (« remplace » ou non), cumulés."""
    return _taux(sum(r.count("remplace") * (len(r) - r.count("remplace")) for r in listes),
                 sum(_paires(len(r)) for r in listes))


def bloc_regle(lignes, marges):
    """Indicateurs de la règle entière sur un ensemble de scénarios."""
    issues = [ligne["issues"] for ligne in lignes]
    disputes = [r for r in issues if "remplace" in r]
    attribution = {motif: 0 for motif in MOTIFS}
    propre = {"unknown_value": [0, 0], "marge": [0, 0], "condition_e": [0, 0]}
    for ligne in lignes:
        r, n = ligne["issues"], len(ligne["issues"])
        for motif in MOTIFS:
            attribution[motif] += r.count("remplace") * r.count(motif)
        u = n - r.count("unknown_value")  # tables où l'issue est connue
        m = u - r.count("below_margin")
        e = ligne["sans_marge"].count("remplace")
        for nom, d, paires in (("unknown_value", u * (n - u), _paires(n)), ("marge", m * (u - m), _paires(u)),
                               ("condition_e", e * (u - e), _paires(u))):
            propre[nom][0] += d
            propre[nom][1] += paires
    bloc = {
        "scenarios": len(lignes),
        "scenarios_disputes": len(disputes),
        "scenarios_a_decision_non_unanime": sum(1 for r in disputes if r.count("remplace") < len(r)),
        "scenarios_a_motif_non_unanime": sum(1 for r in issues if len(set(r)) > 1),
        "issues": {issue: sum(r.count(issue) for r in issues) for issue in ISSUES},
        "desaccord": {"tous": _desaccords(issues), "disputes": _desaccords(disputes)},
        "attribution": attribution,
        "instabilite_propre": {nom: _taux(d, paires) for nom, (d, paires) in propre.items()},
        "acceptations_sur_bruit_effectives": sum(sum(ligne["sur_bruit"]) for ligne in lignes),
        "acceptations_sans_autre_table": sum(sum(ligne["sans_autre_table"]) for ligne in lignes),
        "par_marge": {},
    }
    bloc["part_scenarios_a_decision_non_unanime"] = _part(bloc["scenarios_a_decision_non_unanime"], len(lignes))
    for marge in marges:
        a_marge = [ligne["par_marge"][cle_marge(marge)] for ligne in lignes]
        disputes_a_marge = [r for r in a_marge if "remplace" in r]
        bloc["par_marge"][cle_marge(marge)] = {
            "scenarios_disputes": len(disputes_a_marge),
            "desaccord": {"tous": _desaccords(a_marge), "disputes": _desaccords(disputes_a_marge)},
        }
    return bloc


def regle_entiere(tables, rejeter, order_loc, marges, scenarios=None):
    """`scenarios` : le retour de scenarios_de_la_regle, quand il a déjà été calculé (la règle n'est pas rejouée deux fois)."""
    lignes, impossibles, seuls = scenarios or scenarios_de_la_regle(tables, rejeter, order_loc, marges)
    sortie = {
        "appel": "_reject_contradictions([N], {%r: engagements du groupe sauf E, puis E}, plans, betray=[E], "
                 "order_values, candidates, search) sur chaque table du groupe" % DESTINATAIRE,
        "unite": "(groupe, E, N, table) ; groupes du niveau « groupe » d'au moins deux tables",
        "limites": [
            "informatif : n'entre pas dans le verdict",
            "un désaccord entre tables n'est pas en soi un défaut de la marge : un gain réel proche du seuil "
            "bascule quel que soit le seuil",
            "les groupes B ne sont pas indépendants des groupes A (mise à jour incrémentale du même tirage)",
        ],
        "groupes_d_une_seule_table_non_rejoues": seuls,
        "etats_impossibles_ecartes": sum(impossibles.values()),
        "etats_impossibles_ecartes_par_groupe": {nom_groupe(g): n for g, n in sorted(impossibles.items()) if n},
        "classes": {},
    }
    for classe, _titre, description in CLASSES_REGLE:
        de_la_classe = [ligne for ligne in lignes if ligne["classe"] == classe]
        positions = sorted({ligne["position"] for ligne in de_la_classe})
        groupes = sorted({ligne["groupe"] for ligne in de_la_classe})
        sortie["classes"][classe] = {
            "definition": description,
            "total": bloc_regle(de_la_classe, marges),
            "par_position": {
                nom_position(q): bloc_regle([x for x in de_la_classe if x["position"] == q], marges) for q in positions},
            "par_groupe": {
                nom_groupe(g): bloc_regle([x for x in de_la_classe if x["groupe"] == g], marges) for g in groupes},
            "scenarios": [
                {"groupe": nom_groupe(x["groupe"]), "ancien": x["couple"][0], "nouveau": x["couple"][1],
                 "tables": x["tables"], "issues": x["issues"], "gains": x["gains"], "sans_marge": x["sans_marge"],
                 "sur_bruit": x["sur_bruit"], "sans_autre_table": x["sans_autre_table"]}
                for x in de_la_classe
            ],
        }
    return sortie


# ---------------------------------------------------------------------------
# Décompte par événement (table, E) -- informatif, hors verdict
# ---------------------------------------------------------------------------

def lecture_par_evenement(part_a, part_b):
    """Lecture indicative des deux parts ; `part_b` None (aucun remplacement accepté) vaut 0."""
    if part_a is None:
        return LECTURES_PAR_EVENEMENT[3]
    part_b = part_b or 0.0
    if part_a > NE_PROTEGERAIT_PAS_A or part_b > NE_PROTEGERAIT_PAS_B:
        return LECTURES_PAR_EVENEMENT[2]
    if part_a <= PROTEGERAIT_A and part_b <= PROTEGERAIT_B:
        return LECTURES_PAR_EVENEMENT[0]
    return LECTURES_PAR_EVENEMENT[1]


def _bloc_evenements(exposes, fautifs, acceptations, sur_bruit, positions, sans_autre=None):
    """Les deux parts et, pour la règle entière (`sans_autre` donné), leur lecture.

    `exposes`, `fautifs` : ensembles de (table, E) ; `positions` : {table: position}."""
    bloc = {
        "exposes": len(exposes), "avec_acceptation_sur_bruit": len(fautifs), "part_a": _part(len(fautifs), len(exposes)),
        "acceptations": acceptations, "acceptations_sur_bruit": sur_bruit, "part_b": _part(sur_bruit, acceptations),
        "tables_sur_bruit": len({table for table, _e in fautifs}),
        "positions_sur_bruit": len({positions[table] for table, _e in fautifs}),
        "evenements_sur_bruit": [{"table": table, "ancien": e} for table, e in sorted(fautifs)],
    }
    bloc["lecture_indicative"] = None  # la marge seule est un rappel : l'unité se juge par la règle entière
    if sans_autre is not None:
        bloc["dont_acceptations_sans_autre_table"] = sans_autre
        bloc["lecture_indicative"] = lecture_par_evenement(bloc["part_a"], bloc["part_b"])
    return bloc


def decompte_par_evenement(tables, lignes, marge):
    """Décompte par événement (table, E) sur les recherches A sans engagement -- informatif, hors verdict.

    `lignes` : les scénarios de scenarios_de_la_regle (issues à la marge du bot). Trois lectures : la
    règle entière ; la même restreinte aux promesses « réalistes » (E dans un des plans exportés de la
    table jugée) ; la marge seule (G > marge, sans la condition (e)), en rappel."""
    de_a = tables_du_niveau(tables, NIVEAU_DE_LA_SPECIFICATION)
    positions = {t["nom"]: t["position"] for t in de_a}
    de_a_seules = [ligne for ligne in lignes if not ligne["groupe"][3] and ligne["groupe"][4] == TYPE_SANS_ENGAGEMENT]
    # Les tables jugées : celles des groupes d'au moins deux tables, les seuls que la règle rejoue.
    jugees = {table for ligne in de_a_seules for table in ligne["tables"]}
    dans_les_plans = {
        t["nom"]: {o for plan in (t["entree"].get("plans") or []) if isinstance(plan, dict) for o in plan.get("orders") or []}
        for t in de_a}

    def regle(realiste):
        exposes, fautifs, acceptations, sur_bruit, sans_autre = set(), set(), 0, 0, 0
        for ligne in de_a_seules:
            ancien = ligne["couple"][0]
            for i, table in enumerate(ligne["tables"]):
                if realiste and ancien not in dans_les_plans[table]:
                    continue
                if ligne["sans_gain"][i]:
                    exposes.add((table, ancien))
                acceptations += ligne["issues"][i] == "remplace"
                sans_autre += ligne["sans_autre_table"][i]
                if ligne["sur_bruit"][i]:
                    sur_bruit += 1
                    fautifs.add((table, ancien))
        return _bloc_evenements(exposes, fautifs, acceptations, sur_bruit, positions, sans_autre)

    obs, _tailles, _seuls = observations(de_a, NIVEAU_DE_LA_SPECIFICATION)
    sans_gain = [o for o in obs if o["reference"] <= 0]
    acceptees = [o for o in obs if o["g"] > marge]
    acceptees_sur_bruit = [o for o in acceptees if o["reference"] <= 0]
    return {
        "statut": "informatif, hors verdict : le critère publié reste le verdict par observation "
                  "(décision du mainteneur, 2026-10-10)",
        "unite": "(table, E) : une recherche %s sans engagement et une promesse rompue E ; exposé si au moins un N est "
                 "sans gain (couple (E, N) dans la table et dans une autre du groupe, moyenne de G sur les autres <= 0)"
                 % TYPE_SANS_ENGAGEMENT,
        "niveau": NIVEAU_DE_LA_SPECIFICATION, "marge": marge,
        "tables": len(jugees), "positions": len({positions[table] for table in jugees}),
        "parts": {
            "a": "part des (table, E) exposés qui ont au moins une acceptation sur bruit",
            "b": "part des remplacements acceptés qui sont sur bruit",
        },
        "seuils": {
            "protegerait": "(a) <= %s et (b) <= %s" % (PROTEGERAIT_A, PROTEGERAIT_B),
            "ne_protegerait_pas": "(a) > %s ou (b) > %s" % (NE_PROTEGERAIT_PAS_A, NE_PROTEGERAIT_PAS_B),
            "partiel": "entre les deux",
        },
        "regle_entiere": regle(False),
        "regle_entiere_promesses_realistes": regle(True),
        "marge_seule": _bloc_evenements(
            {(o["table"], o["couple"][0]) for o in sans_gain}, {(o["table"], o["couple"][0]) for o in acceptees_sur_bruit},
            len(acceptees), len(acceptees_sur_bruit), positions),
        "limites": [
            "informatif : n'entre pas dans le verdict, et ses seuils ne sont pas un critère publié",
            "les recherches A sans engagement sont la classe « table antérieure » (le bot en avance sur le moteur) : "
            "rien ici sur une table calculée sous la promesse",
            "« réaliste » : E est un ordre d'un des plans exportés de la table jugée, une hypothèse sur ce que Claude "
            "promet ; aucune promesse réelle n'est rejouée",
            "peu d'événements : un ou deux (table, E) déplacent la lecture",
        ],
    }


# ---------------------------------------------------------------------------
# Loi de Student (bibliothèque standard : pas de statistics.NormalDist en Python 3.7)
# ---------------------------------------------------------------------------

def student_cdf(x, ddl, pas=2000):
    """Fonction de répartition de la loi de Student, par la méthode de Simpson."""
    if x < 0:
        return 1 - student_cdf(-x, ddl, pas)

    def densite(t):
        return (math.exp(math.lgamma((ddl + 1) / 2.0) - math.lgamma(ddl / 2.0)) / math.sqrt(ddl * math.pi)
                * (1 + t * t / ddl) ** (-(ddl + 1) / 2.0))

    h = x / pas
    somme = densite(0) + densite(x)
    for i in range(1, pas):
        somme += (4 if i % 2 else 2) * densite(i * h)
    return 0.5 + somme * h / 3


def student_quantile(p, ddl, pas=2000):
    """Quantile d'ordre p >= 0,5 de la loi de Student, par dichotomie sur student_cdf."""
    bas, haut = 0.0, 100.0
    for _ in range(60):
        milieu = (bas + haut) / 2
        if student_cdf(milieu, ddl, pas) < p:
            bas = milieu
        else:
            haut = milieu
    return (bas + haut) / 2


def quantile_975(ddl):
    """(quantile 0,975 de Student à `ddl` degrés de liberté, approché ?)."""
    if 1 <= ddl <= len(STUDENT_975):
        return STUDENT_975[ddl - 1], False
    return NORMALE_975, True


def _fraction_de_g(g):
    return fractions.Fraction(int(round(g * UNITE)), UNITE)


def _arrondi(x):
    return None if x is None else round(float(x), 10)


def statistique(valeurs):
    """Moyenne, écart type à n - 1, erreur type s / racine(n), t et intervalle à 95 % de Student.

    `valeurs` : des fractions, pour qu'une dispersion nulle le soit exactement. À
    moins de MIN_TIRAGES_ERREUR_TYPE valeurs, seule la moyenne est rendue. À
    dispersion nulle, l'erreur type est 0 et t n'est pas calculé."""
    n = len(valeurs)
    r = {"n": n, "effet": None, "ecart_type": None, "erreur_type": None, "t": None, "ic95": None,
         "quantile": None, "quantile_approche": None}
    if not n:
        return r
    moyenne = sum(valeurs, fractions.Fraction(0)) / n
    r["effet"] = _arrondi(moyenne)
    if n < MIN_TIRAGES_ERREUR_TYPE:
        return r
    variance = sum(((x - moyenne) ** 2 for x in valeurs), fractions.Fraction(0)) / (n - 1)
    quantile, approche = quantile_975(n - 1)
    r.update({"quantile": quantile, "quantile_approche": approche})
    if variance == 0:
        r.update({"ecart_type": 0.0, "erreur_type": 0.0, "ic95": [r["effet"], r["effet"]]})
        return r
    ecart_type = math.sqrt(float(variance))
    erreur_type = ecart_type / math.sqrt(n)
    r.update({
        "ecart_type": _arrondi(ecart_type), "erreur_type": _arrondi(erreur_type),
        "t": _arrondi(float(moyenne) / erreur_type),
        "ic95": [_arrondi(float(moyenne) - quantile * erreur_type), _arrondi(float(moyenne) + quantile * erreur_type)],
    })
    return r


def lecture_de_l_effet(stat, marge):
    """Lecture à trois issues d'un couple principal (plus « nul » et « sans erreur type »)."""
    if stat["ic95"] is None:
        return "sans erreur type"
    bas, haut = stat["ic95"]
    if stat["erreur_type"] == 0 and stat["effet"] == 0:
        return "nul"
    distinguable = bas > 0 or haut < 0
    negligeable = -marge / 2 <= bas and haut <= marge / 2
    if distinguable and negligeable:
        return "distinguable du bruit, négligeable devant la marge"
    if distinguable:
        return "distinguable du bruit"
    return "négligeable devant la marge" if negligeable else "non conclusif"


LECTURES = (
    "distinguable du bruit", "distinguable du bruit, négligeable devant la marge", "négligeable devant la marge",
    "non conclusif", "nul", "sans erreur type",
)


# ---------------------------------------------------------------------------
# Effet de la recherche B, apparié par tirage
# ---------------------------------------------------------------------------

def _variance(valeurs):
    moyenne = sum(valeurs, fractions.Fraction(0)) / len(valeurs)
    return sum(((x - moyenne) ** 2 for x in valeurs), fractions.Fraction(0)) / (len(valeurs) - 1)


def _apparie_du_groupe(cle, membres, references, marge, sans_le_tirage_du_choix):
    """L'effet apparié d'un groupe avec engagements ; `references` : {(position, fichier, tirage): [tables A]}."""
    engages = cle[3]
    par_tirage = {}
    for t in membres:
        par_tirage.setdefault((t["fichier"], t["tirage"]), []).append(t)
    paires, non_apparies, ecartes = [], 0, 0
    for (fichier, tirage), du_tirage in sorted(par_tirage.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        de_reference = references.get(cle[:3] + (fichier, tirage), [])
        if tirage is None or len(du_tirage) != 1 or len(de_reference) != 1:
            non_apparies += len(du_tirage)
        elif sans_le_tirage_du_choix and du_tirage[0]["tirage_du_choix"] == tirage:
            ecartes += 1
        else:
            paires.append((de_reference[0], du_tirage[0]))
    par_couple = {}
    for a, b in paires:
        for couple in sorted(set(a["g"]) & set(b["g"])):
            par_couple.setdefault(couple, []).append((_fraction_de_g(a["g"][couple]), _fraction_de_g(b["g"][couple])))
    principaux, autres = [], []
    for couple, valeurs in sorted(par_couple.items()):
        stat = statistique([b - a for a, b in valeurs])
        if couple[0] not in engages:
            autres.append(stat)
            continue
        stat = dict({"ancien": couple[0], "nouveau": couple[1]}, **stat)
        stat.update({"erreur_type_non_appariee": None, "t_non_apparie": None, "correlation_a_b": None})
        if stat["n"] >= MIN_TIRAGES_ERREUR_TYPE:
            v_a, v_b = _variance([a for a, _b in valeurs]), _variance([b for _a, b in valeurs])
            non_appariee = math.sqrt(float(v_a + v_b) / stat["n"])
            stat["erreur_type_non_appariee"] = _arrondi(non_appariee)
            if non_appariee:
                stat["t_non_apparie"] = _arrondi(stat["effet"] / non_appariee)
            if v_a and v_b:
                m_a = sum((a for a, _b in valeurs), fractions.Fraction(0)) / stat["n"]
                m_b = sum((b for _a, b in valeurs), fractions.Fraction(0)) / stat["n"]
                covariance = sum(((a - m_a) * (b - m_b) for a, b in valeurs), fractions.Fraction(0)) / (stat["n"] - 1)
                stat["correlation_a_b"] = _arrondi(float(covariance) / math.sqrt(float(v_a * v_b)))
        stat["lecture"] = lecture_de_l_effet(stat, marge)
        principaux.append(stat)
    return {
        "groupe": nom_groupe(cle), "position": nom_position(cle[:3]), "recherche": cle[4],
        "tirages_apparies": len(paires), "tables_sans_tirage_apparie": non_apparies,
        "tirages_du_choix_ecartes": ecartes,
        "couples": len(par_couple),
        "principaux": principaux,
        "autres": {
            "couples": len(autres),
            "couples_sans_erreur_type": sum(1 for x in autres if x["ic95"] is None),
            "abs_effet": resumer([abs(x["effet"]) for x in autres]),
            "abs_t": resumer([abs(x["t"]) for x in autres if x["t"] is not None]),
        },
    }


def _entre_positions(groupes):
    """Synthèse dont l'unité est la position : moyenne par position de l'effet de ses couples principaux.

    Seuls entrent les couples estimés sur au moins MIN_TIRAGES_ERREUR_TYPE tirages : un couple vu
    dans un seul tirage pèserait autant qu'un couple vu dans tous. Les autres sont comptés, ainsi
    que les positions qui n'en gardent aucun."""
    par_position, ecartes = {}, {}
    for groupe in groupes:
        retenus = par_position.setdefault(groupe["position"], [])
        ecartes.setdefault(groupe["position"], 0)
        for couple in groupe["principaux"]:
            if couple["n"] >= MIN_TIRAGES_ERREUR_TYPE:
                retenus.append(fractions.Fraction(repr(couple["effet"])))
            else:
                ecartes[groupe["position"]] += 1
    moyennes = {q: sum(v, fractions.Fraction(0)) / len(v) for q, v in sorted(par_position.items()) if v}
    synthese = statistique(list(moyennes.values()))
    synthese["positions"] = synthese.pop("n")
    synthese["tirages_min_par_couple"] = MIN_TIRAGES_ERREUR_TYPE
    synthese["couples_principaux_ecartes"] = sum(ecartes.values())
    synthese["positions_sans_couple_retenu"] = sum(1 for v in par_position.values() if not v)
    synthese["par_position"] = {
        q: {"couples_principaux": len(par_position[q]), "couples_principaux_ecartes": ecartes[q], "effet": _arrondi(m)}
        for q, m in moyennes.items()}
    return synthese


def effet_apparie(tables, marge):
    """Effet de la recherche B estimé en apparié par tirage, à côté de l'estimateur non apparié."""
    groupes, references = {}, {}
    for t in tables:
        groupes.setdefault(cle_groupe(t, "groupe"), []).append(t)
        if t["recherche"] == TYPE_SANS_ENGAGEMENT and not t["engagements"]:
            references.setdefault(t["position"] + (t["fichier"], t["tirage"]), []).append(t)

    def par_groupe(sans_le_tirage_du_choix):
        return [_apparie_du_groupe(cle, membres, references, marge, sans_le_tirage_du_choix)
                for cle, membres in sorted(groupes.items()) if cle[3]]

    lignes, sans_choix = par_groupe(False), par_groupe(True)
    principaux = [couple for groupe in lignes for couple in groupe["principaux"]]
    autres_sans = sum(groupe["autres"]["couples_sans_erreur_type"] for groupe in lignes)
    sensibilite = _entre_positions(sans_choix)
    sensibilite["tirages_du_choix_ecartes"] = sum(groupe["tirages_du_choix_ecartes"] for groupe in sans_choix)
    # Un couple principal qui n'existe qu'au tirage du choix n'a plus aucun tirage : il sort sans être « écarté ».
    sensibilite["couples_principaux_du_seul_tirage_du_choix"] = sum(
        len({(c["ancien"], c["nouveau"]) for c in avec["principaux"]}
            - {(c["ancien"], c["nouveau"]) for c in sans["principaux"]})
        for avec, sans in zip(lignes, sans_choix))
    return {
        "libelle": LIBELLE_EFFET,
        "unite": "le tirage (fichier, tirage) où coexistent la recherche %s sans engagement et la table du groupe"
                 % TYPE_SANS_ENGAGEMENT,
        "estimateur": "effet = moyenne des delta = G_B - G_A du tirage ; erreur type = s / racine(n), s à n - 1 ; "
                      "intervalle à 95 %% de Student à n - 1 degrés de liberté ; pas d'erreur type à moins de %d tirages"
                      % MIN_TIRAGES_ERREUR_TYPE,
        "marge": marge,
        "couples_principaux": len(principaux),
        "couples_sans_erreur_type": sum(1 for c in principaux if c["ic95"] is None) + autres_sans,
        "lectures_des_couples_principaux": {
            lecture: sum(1 for c in principaux if c["lecture"] == lecture) for lecture in LECTURES},
        "par_groupe": lignes,
        "entre_positions": _entre_positions(lignes),
        "sensibilite_sans_le_tirage_du_choix": sensibilite,
        "limites": [
            "B - A mêle le message déclencheur, la mise à jour incrémentale et l'engagement : aucune recherche B sans "
            "engagement ne les sépare",
            "le test de Student suppose des delta à peu près normaux ; à 5 tirages, un test de signes ne descend pas "
            "sous p = 2/32",
            "les couples autres que principaux sont rendus sans lecture : des centaines de tests non indépendants "
            "donnent 5 % de faux positifs attendus",
            "seule la synthèse entre positions a des unités indépendantes",
            "l'engagement est choisi sur la table A d'un tirage : biais de sélection possible, d'où la synthèse refaite "
            "sans ce tirage",
        ],
    }


# ---------------------------------------------------------------------------
# Dispersion dans un fichier et entre fichiers
# ---------------------------------------------------------------------------

def _sce(lignes, parts):
    """(SCE inter, SCE intra) cumulées sur les couples, en unités entières au carré.

    `lignes` : par couple, G entier de chaque table ; `parts` : par fichier, les indices de ses tables."""
    inter = intra = fractions.Fraction(0)
    for ligne in lignes:
        for indices in parts:
            valeurs = [ligne[i] for i in indices]
            carre = fractions.Fraction(sum(valeurs) ** 2, len(valeurs))
            intra += sum(v * v for v in valeurs) - carre
            inter += carre
        inter -= fractions.Fraction(sum(ligne) ** 2, len(ligne))
    return inter, intra


def repartitions(indices, tailles):
    """Toutes les répartitions de `indices` en fichiers des tailles données, dans l'ordre."""
    if len(tailles) == 1:
        yield (tuple(indices),)
        return
    for choisis in itertools.combinations(indices, tailles[0]):
        reste = [i for i in indices if i not in choisis]
        for suite in repartitions(reste, tailles[1:]):
            yield (choisis,) + suite


def nombre_de_repartitions(tailles):
    n = math.factorial(sum(tailles))
    for taille in tailles:
        n //= math.factorial(taille)
    return n


def _p(numerateur, denominateur):
    return {"numerateur": numerateur, "denominateur": denominateur,
            "fraction": "%d/%d" % (numerateur, denominateur), "valeur": numerateur / denominateur}


def puissance_indicative(tailles):
    """Puissance du test F à 5 % sous modèle normal, par corrélation intra-fichier : un ordre de grandeur.

    Deux fichiers de même taille seulement (F à 1 degré de liberté = carré d'un Student) ; None sinon."""
    if len(tailles) != 2 or tailles[0] != tailles[1] or 2 * (tailles[0] - 1) > len(STUDENT_975):
        return None
    n, ddl = tailles[0], 2 * (tailles[0] - 1)
    critique = quantile_975(ddl)[0]
    return {
        "%.1f" % rho: round(2 * (1 - student_cdf(critique / math.sqrt(1 + n * rho / (1 - rho)), ddl)), 2)
        for rho in CORRELATIONS_DE_PUISSANCE
    }


def dispersion_du_groupe(cle, membres):
    par_fichier = {}
    for i, t in enumerate(membres):
        par_fichier.setdefault(t["fichier"], []).append(i)
    parts = [tuple(indices) for _fichier, indices in sorted(par_fichier.items())]
    tailles = [len(indices) for indices in parts]
    communs = sorted(set.intersection(*(set(t["g"]) for t in membres)))
    lignes = [[int(round(t["g"][couple] * UNITE)) for t in membres] for couple in communs]
    ddl_intra, ddl_inter = sum(tailles) - len(parts), len(parts) - 1
    inter, intra = _sce(lignes, parts)
    r = {
        "groupe": nom_groupe(cle), "position": nom_position(cle[:3]), "recherche": cle[4],
        "fichiers": sorted(par_fichier), "tables_par_fichier": tailles,
        "couples": len(communs),
        "couples_ecartes_absents_d_une_table": len(set.union(*(set(t["g"]) for t in membres))) - len(communs),
        "ddl_intra": ddl_intra, "ecart_type_intra": None, "decomposition": None,
    }
    if not communs or not ddl_intra:
        return r
    cm_intra = intra / (len(communs) * ddl_intra)
    r["ecart_type_intra"] = _arrondi(math.sqrt(float(cm_intra)) / UNITE)
    if len(parts) < 2 or min(tailles) < 2:
        return r
    cm_inter = inter / (len(communs) * ddl_inter)
    d = {
        "ddl_inter": ddl_inter,
        "sce_inter": _arrondi(inter / UNITE ** 2), "sce_intra": _arrondi(intra / UNITE ** 2),
        "sce_inter_par_couple": _arrondi(inter / UNITE ** 2 / len(communs)),
        "sce_intra_par_couple": _arrondi(intra / UNITE ** 2 / len(communs)),
        "cm_inter": _arrondi(cm_inter / UNITE ** 2), "cm_intra": _arrondi(cm_intra / UNITE ** 2),
        "r": _arrondi(cm_inter / cm_intra) if cm_intra else None,
        "correlation_intra_fichier": None,
        "puissance_indicative": puissance_indicative(tailles),
    }
    if len(set(tailles)) == 1 and cm_inter + (tailles[0] - 1) * cm_intra:
        d["correlation_intra_fichier"] = _arrondi((cm_inter - cm_intra) / (cm_inter + (tailles[0] - 1) * cm_intra))
    f_par_couple, intra_nul = [], 0
    for ligne in lignes:
        inter_c, intra_c = _sce([ligne], parts)
        if intra_c:
            f_par_couple.append(float((inter_c / ddl_inter) / (intra_c / ddl_intra)))
        else:
            intra_nul += 1
    d["f_par_couple"] = resumer(f_par_couple)
    d["couples_a_intra_nul"] = intra_nul
    d["reperes_sous_h0"] = None
    if ddl_inter == 1:  # F(1, ddl) est le carré d'un Student à ddl degrés de liberté
        d["reperes_sous_h0"] = {
            "mediane": round(student_quantile(0.75, ddl_intra) ** 2, 3),
            "c95": round(student_quantile(0.975, ddl_intra) ** 2, 3),
        }
    total = nombre_de_repartitions(tailles)
    d["repartitions"] = total
    if total > MAX_REPARTITIONS:
        d.update({"p": None, "p_queue_inferieure": None, "p_minimal": None,
                  "lecture": "pas de test : %d répartitions, plus de %d" % (total, MAX_REPARTITIONS)})
    else:
        superieures = inferieures = au_maximum = 0
        maximum = None
        for repartition in repartitions(list(range(len(membres))), tailles):
            inter_p, intra_p = _sce(lignes, repartition)
            superieures += inter_p * intra >= inter * intra_p  # R' >= R, sans division
            inferieures += inter_p * intra <= inter * intra_p
            if maximum is None or inter_p > maximum:  # la somme inter + intra ne dépend pas de la répartition
                maximum, au_maximum = inter_p, 0
            au_maximum += inter_p == maximum
        d.update({
            "p": _p(superieures, total), "p_queue_inferieure": _p(inferieures, total), "p_minimal": _p(au_maximum, total),
            "lecture": "indépendance des tirages d'un lancement %s"
                       % ("rejetée" if superieures <= SEUIL_P * total else "non rejetée"),
        })
    d["rejet"] = d["p"] is not None and d["p"]["numerateur"] <= SEUIL_P * total
    r["decomposition"] = d
    return r


def _lambda(table):
    search = table["entree"]["search"]
    valeur = search.get("lambda") if isinstance(search, dict) else None
    return valeur if _nombre(valeur) else None


def tables_jumelles(tables):
    """Paires de tables d'un même fichier, d'une même position et d'un même type, identiques par
    order_values ou par search.lambda : le signe d'un état partagé entre tirages.

    Le contrôle par search.lambda suppose un lambda dynamique, différent d'un tirage à l'autre :
    mis en cache par état d'agent et par phase, il ne se répète que si l'état est réutilisé.
    Un fichier dont toutes les paires ont le même lambda est nommé à part : état partagé d'un
    bout à l'autre du lancement, ou lambda qui n'est pas dynamique dans la configuration."""
    par_fichier = {}
    for t in tables:
        par_fichier.setdefault((t["fichier"],) + t["position"] + (t["recherche"],), []).append(t)
    examinees, memes_valeurs, meme_lambda, du_fichier = 0, [], [], {}
    for cle, membres in sorted(par_fichier.items()):
        for t1, t2 in itertools.combinations(membres, 2):
            examinees += 1
            compte = du_fichier.setdefault(cle[0], [0, 0])  # paires examinées, jumelles par lambda
            compte[0] += 1
            if t1["entree"]["order_values"] == t2["entree"]["order_values"]:
                memes_valeurs.append([t1["nom"], t2["nom"]])
            if _lambda(t1) is not None and _lambda(t1) == _lambda(t2):
                meme_lambda.append([t1["nom"], t2["nom"]])
                compte[1] += 1
    return {
        "paires_examinees": examinees,
        "paires_jumelles": len({tuple(paire) for paire in memes_valeurs + meme_lambda}),
        "order_values_identiques": memes_valeurs, "lambda_identique": meme_lambda,
        "hypothese_du_controle_par_lambda": "lambda dynamique, différent d'un tirage à l'autre",
        "fichiers_entierement_jumeaux_par_lambda": sorted(f for f, (n, k) in du_fichier.items() if n == k),
    }


def engagements_differents_entre_fichiers(tables):
    """Positions dont les recherches B n'ont pas les mêmes engagements retenus dans tous leurs fichiers.

    Le choix de l'engagement dépend du tirage sur lequel il est fait : deux lancements d'une même
    position peuvent en figer deux. Les recherches B forment alors des groupes distincts, et la
    décomposition entre fichiers du type B n'existe pas. Un constat, pas une mise en garde."""
    par_position = {}
    for t in tables:
        if t["recherche"] == TYPE_AVEC_ENGAGEMENT:
            par_position.setdefault(t["position"], {}).setdefault(t["fichier"], []).append(t["engagements"])
    lignes = []
    for position, par_fichier in sorted(par_position.items()):
        if len({frozenset(engagements) for engagements in par_fichier.values()}) < 2:
            continue  # un seul fichier, ou les mêmes engagements dans chacun : rien ne distingue les lancements
        lignes.append({
            "position": nom_position(position), "recherche": TYPE_AVEC_ENGAGEMENT,
            "par_fichier": [
                {"fichier": fichier, "engagements": list(e), "tables": engagements.count(e)}
                for fichier, engagements in sorted(par_fichier.items()) for e in sorted(set(engagements))],
        })
    return lignes


def dispersion(tables):
    groupes = {}
    for t in tables:
        groupes.setdefault(cle_groupe(t, "groupe"), []).append(t)
    lignes = [dispersion_du_groupe(cle, membres) for cle, membres in sorted(groupes.items()) if len(membres) >= 2]
    intra = [ligne["ecart_type_intra"] for ligne in lignes if ligne["ecart_type_intra"] is not None]
    jumelles = tables_jumelles(tables)
    mises_en_garde = []
    for ligne in lignes:
        d = ligne["decomposition"]
        if d and d["rejet"]:
            mises_en_garde.append(
                "indépendance des tirages d'un lancement rejetée (groupe %s : R = %s, p = %s = %.4f) : les tirages d'un "
                "même fichier ne sont pas des répétitions valides"
                % (ligne["groupe"], _f(d["r"], 2), d["p"]["fraction"], d["p"]["valeur"]))
    if jumelles["paires_jumelles"]:
        mises_en_garde.append(
            "%d paire(s) de tables jumelles (même fichier, même type ; order_values identiques : %d, search.lambda "
            "identique : %d), par exemple %s : état partagé entre tirages, qui ne sont pas des répétitions valides"
            % (jumelles["paires_jumelles"], len(jumelles["order_values_identiques"]), len(jumelles["lambda_identique"]),
               " et ".join((jumelles["order_values_identiques"] + jumelles["lambda_identique"])[0])))
        if jumelles["fichiers_entierement_jumeaux_par_lambda"]:
            mises_en_garde[-1] += (
                " ; toutes les paires de %s ont le même search.lambda : état partagé entre tirages, ou lambda non "
                "dynamique dans la configuration" % ", ".join(jumelles["fichiers_entierement_jumeaux_par_lambda"]))
    return {
        "unite": "couples présents dans toutes les tables du groupe (niveau « groupe »), G en entiers x %d" % UNITE,
        "seuil_p": SEUIL_P, "repartitions_max": MAX_REPARTITIONS,
        "groupes": len(lignes),
        "groupes_decomposes": sum(1 for ligne in lignes if ligne["decomposition"]),
        "ecart_type_intra": resumer(intra),
        "ecart_type_intra_par_type": {
            recherche: resumer([ligne["ecart_type_intra"] for ligne in lignes
                                if ligne["recherche"] == recherche and ligne["ecart_type_intra"] is not None])
            for recherche in sorted({ligne["recherche"] for ligne in lignes})},
        "par_groupe": lignes,
        "tables_jumelles": jumelles,
        "engagements_differents_entre_fichiers": engagements_differents_entre_fichiers(tables),
        "mises_en_garde": mises_en_garde,
        "limites": [
            "un non-rejet n'établit pas l'indépendance : avec deux fichiers, l'inter-fichiers n'a qu'un degré de liberté",
            "la corrélation intra-fichier est rendue sans intervalle : à un degré de liberté, elle n'en a pas d'utilisable",
            "le test sur un groupe B n'est pas une confirmation indépendante de celui du groupe A",
            "une position, une partie, des lancements consécutifs de la même image : rien sur un changement d'image "
            "ou de machine",
        ],
    }


def portee(lecture):
    """Ce que couvrent les relevés lus : parties et années, avec le rappel de l'exigence 2.10."""
    annees = sorted({trouve.group(0) for trouve in (re.search(r"\d{4}", phase) for phase in lecture["phases"]) if trouve})
    etendue = "années inconnues" if not annees else (
        annees[0] if len(annees) == 1 else "%s à %s" % (annees[0], annees[-1]))
    parties = lecture["parties"]
    texte = "%d partie%s (%s), %s" % (len(parties), "s" if len(parties) > 1 else "", ", ".join(parties), etendue)
    if len(parties) == 1:
        texte += " : mesuré sur une partie, ce qui ne fonde pas une statistique (exigence 2.10)"
    return texte


def verdict(niveau, marge, nom=NIVEAU_DE_LA_SPECIFICATION, independance=()):
    """Critère d'expert-cicero (#26) sur un niveau de bruit, à la marge donnée.

    `verdict` n'est l'issue du critère que si rien n'empêche de conclure ; sinon
    « non concluant » (« indéterminé » sans aucune observation), l'issue du
    critère passant dans `lecture_indicative` et les raisons dans `avertissements`.
    `independance` : les mises en garde de la dispersion (indépendance rejetée,
    tables jumelles) ; les tirages ne sont alors plus des répétitions valides."""
    total = niveau["total"]
    v = {
        "marge": marge, "observations": total["observations"], "lecture_indicative": None,
        "concluant": False, "avertissements": [],
    }
    if not total["observations"]:
        v["verdict"] = "indéterminé"
        v["avertissements"].append(sans_observation(niveau) + " : le bruit n'est pas mesurable à ce niveau")
        v["avertissements"].extend(independance)
        return v
    a_marge = total["par_marge"][cle_marge(marge)]
    pire_nom, pire = max(niveau["par_position"].items(), key=lambda item: item[1]["abs_d"]["c99"])
    part = a_marge["part_sur_bruit_des_observations_sans_gain"] or 0.0  # aucune observation sans gain : rien à accepter
    v.update({
        "c95_total": total["abs_d"]["c95"], "c99_total": total["abs_d"]["c99"],
        "pire_position": pire_nom, "c99_pire_position": pire["abs_d"]["c99"],
        "acceptations_sur_bruit": a_marge["acceptations_sur_bruit"],
        # Informatif : l'issue du critère ne lit que le nombre d'acceptations.
        "tables_sur_bruit": a_marge["tables_sur_bruit"], "ordres_sur_bruit": a_marge["ordres_sur_bruit"],
        "positions_sur_bruit": a_marge["positions_sur_bruit"],
        "observations_sans_gain": total["observations_sans_gain"],
        "part_sur_bruit_des_observations_sans_gain": a_marge["part_sur_bruit_des_observations_sans_gain"],
        "marge_effective": a_marge["marge_effective"],
    })
    if v["c95_total"] >= NE_PROTEGE_PAS_C95_TOTAL * marge or part > NE_PROTEGE_PAS_PART_SUR_BRUIT:
        issue = "ne protège pas"
    elif (a_marge["acceptations_sur_bruit"] == 0 and v["c99_total"] <= PROTEGE_C99_TOTAL * marge
            and v["c99_pire_position"] <= PROTEGE_C99_PIRE_POSITION * marge):
        issue = "protège"
    else:
        issue = "protège partiellement"
    if nom != NIVEAU_DE_LA_SPECIFICATION:
        v["avertissements"].append(HORS_CRITERE.get(
            nom, "niveau « %s » : hors de la spécification, donné à titre indicatif seulement" % nom))
    if total["observations"] < MIN_OBSERVATIONS:
        v["avertissements"].append(
            "%d observation(s), moins de %d : le 99e centile est le maximum"
            % (total["observations"], MIN_OBSERVATIONS)
        )
    if niveau["tables_par_groupe_min"] < MIN_TABLES_PAR_GROUPE:
        v["avertissements"].append(
            "des groupes de %d tables, moins de %d : d n'y est que l'écart d'une paire"
            % (niveau["tables_par_groupe_min"], MIN_TABLES_PAR_GROUPE)
        )
    if len(niveau["par_position"]) < MIN_POSITIONS:
        v["avertissements"].append(
            "%d position(s) mesurée(s), moins de %d" % (len(niveau["par_position"]), MIN_POSITIONS)
        )
    if niveau["types_de_recherche_reunis"]:
        v["avertissements"].append(
            "des groupes réunissent des recherches de types différents (B et C d'un rejeu incrémental, "
            "qui ne sont pas deux tirages indépendants) : la valeur est un minorant du bruit"
        )
    v["avertissements"].extend(independance)
    v["concluant"] = not v["avertissements"]
    v["verdict"] = issue if v["concluant"] else "non concluant"
    v["lecture_indicative"] = None if v["concluant"] else issue
    return v


def sans_observation(niveau):
    """Pourquoi un niveau n'a aucune observation."""
    if not niveau["groupes"]:
        return "aucune table à ce niveau"
    if not niveau["groupes_d_au_moins_deux_tables"]:
        return "aucun des %d groupe(s) ne compte deux tables" % niveau["groupes"]
    return ("%d groupe(s) d'au moins deux tables, mais aucun couple d'ordres commun à deux tables"
            % niveau["groupes_d_au_moins_deux_tables"])


def analyser(tables, lecture, marge, rejeter, order_loc, marges=MARGES_BALAYEES, source_marge=None):
    marges = tuple(sorted(set(marges) | {marge}))
    bruit = {nom: niveau_bruit(tables, nom, marges) for nom, _ in NIVEAUX}
    effet = effet_engagement(tables)
    effet["apparie"] = effet_apparie(tables, marge)
    dispersions = dispersion(tables)
    scenarios = scenarios_de_la_regle(tables, rejeter, order_loc, marges)
    return {
        "mesure": "bruit des valeurs d'une recherche à l'autre (#26)",
        "portee": portee(lecture),
        "grandeur": "G_T(E, N) = round(order_values[N] - order_values[E], 5), E et N ordres distincts d'une même unité",
        "bruit_definition": "d = G_T - moyenne de G sur les autres tables du groupe",
        "centiles": "valeur observée de rang ceil((n - 1) x q)",
        "marge": marge, "marge_lue_dans": source_marge, "marges_balayees": list(marges),
        "criteres": {
            "protege": "aucune acceptation sur bruit, c99 total <= %s x marge, c99 de la pire position <= %s x marge"
                       % (PROTEGE_C99_TOTAL, PROTEGE_C99_PIRE_POSITION),
            "ne_protege_pas": "c95 total >= %s x marge, ou part acceptée des observations sans gain "
                              "(moyenne des autres tables <= 0) > %s"
                              % (NE_PROTEGE_PAS_C95_TOTAL, NE_PROTEGE_PAS_PART_SUR_BRUIT),
            "effectifs_pour_conclure": {
                "observations": MIN_OBSERVATIONS, "tables_par_groupe": MIN_TABLES_PAR_GROUPE,
                "positions": MIN_POSITIONS,
            },
        },
        "reporte": [],
        "niveau_du_critere": NIVEAU_DE_LA_SPECIFICATION,
        "mises_en_garde": dispersions["mises_en_garde"],
        "lecture": lecture,
        "bruit": bruit,
        "paires": synthese_paires(tables, marges),
        "effet_engagement": effet,
        "regle_entiere": regle_entiere(tables, rejeter, order_loc, marges, scenarios),
        "dispersion": dispersions,
        "verdict": {nom: verdict(bruit[nom], marge, nom, dispersions["mises_en_garde"]) for nom, _ in NIVEAUX},
        # Informatif, à côté du verdict : il n'en lit rien et n'y change rien.
        "par_evenement": decompte_par_evenement(tables, scenarios[0], marge),
    }


# ---------------------------------------------------------------------------
# Tableau lisible
# ---------------------------------------------------------------------------

def _f(x, chiffres=4):
    return "-" if x is None else "%.*f" % (chiffres, x)


def _pc(x):
    return "-" if x is None else "%.1f %%" % (100 * x)


def _nb(n, nom):
    """« 1 table », « 2 tables »."""
    return "%d %s%s" % (n, nom, "s" if n > 1 else "")


def _porteurs(bloc):
    """« dans 1 table, 1 ordre, 1 position » : ce qui porte les acceptations sur bruit."""
    return "dans %s, %s, %s" % (_nb(bloc["tables_sur_bruit"], "table"), _nb(bloc["ordres_sur_bruit"], "ordre"),
                                _nb(bloc["positions_sur_bruit"], "position"))


def _stats(s):
    return "%7d %8s %8s %8s %8s %8s" % (s["n"], _f(s["mediane"]), _f(s["c90"]), _f(s["c95"]), _f(s["c99"]), _f(s["max"]))


ENTETE_STATS = "%7s %8s %8s %8s %8s %8s" % ("n", "médiane", "c90", "c95", "c99", "max")


def _dp(taux):
    """« désaccords/paires (part) »."""
    return "%d/%d (%s)" % (taux["desaccords"], taux["paires"], _pc(taux["taux"]))


def _tableau_apparie(apparie, marge):
    l = [""]
    l.append("Effet de la recherche B (message, mise à jour incrémentale, engagement), apparié par tirage -- informatif")
    l.append("  unité : %s." % apparie["unite"])
    l.append("  %s." % apparie["estimateur"])
    if not apparie["par_groupe"]:
        l.append("  aucun groupe avec engagements")
        return l
    l.append("  couples principaux (E engagé -> N) : le gain que la règle lit en production")
    l.append("  %-58s %2s %9s %8s %7s %21s %8s %6s  %s" % (
        "", "n", "effet", "ET", "t", "IC à 95 %", "ET n.a.", "r(A,B)", "lecture"))
    for groupe in apparie["par_groupe"]:
        l.append("  groupe %s : %d tirage(s) apparié(s), %d table(s) sans tirage apparié"
                 % (groupe["groupe"], groupe["tirages_apparies"], groupe["tables_sans_tirage_apparie"]))
        for c in groupe["principaux"]:
            ic = "-" if c["ic95"] is None else "[%+.5f ; %+.5f]" % tuple(c["ic95"])
            l.append("    %-56s %2d %9s %8s %7s %21s %8s %6s  %s%s" % (
                ("%s -> %s" % (c["ancien"], c["nouveau"]))[:56], c["n"],
                "-" if c["effet"] is None else "%+.5f" % c["effet"], _f(c["erreur_type"], 5), _f(c["t"], 2), ic,
                _f(c["erreur_type_non_appariee"], 5), _f(c["correlation_a_b"], 2), c["lecture"],
                " (quantile approché)" if c["quantile_approche"] else ""))
        autres = groupe["autres"]
        if autres["couples"]:
            l.append("    autres couples, sans lecture : %d ; |effet| médiane %s, c95 %s, max %s ; |t| médiane %s, c95 %s, "
                     "max %s ; %d sans erreur type"
                     % (autres["couples"], _f(autres["abs_effet"]["mediane"], 5), _f(autres["abs_effet"]["c95"], 5),
                        _f(autres["abs_effet"]["max"], 5), _f(autres["abs_t"]["mediane"], 2), _f(autres["abs_t"]["c95"], 2),
                        _f(autres["abs_t"]["max"], 2), autres["couples_sans_erreur_type"]))
    l.append("  ET n.a. : erreur type non appariée, racine(s_A^2 / n + s_B^2 / n) ; r(A,B) : corrélation de G entre A et B.")
    l.append("  lectures des %d couples principaux : %s" % (apparie["couples_principaux"], " ; ".join(
        "%s : %d" % (lecture, n) for lecture, n in apparie["lectures_des_couples_principaux"].items() if n) or "aucune"))
    l.append("  « distinguable du bruit » : l'intervalle exclut 0 ; « négligeable devant la marge » : il tient dans "
             "+/- %s / 2." % marge)
    for titre, cle in (("entre positions (unité : la position, moyenne de l'effet de ses couples principaux estimés sur "
                        "au moins %d tirages)" % MIN_TIRAGES_ERREUR_TYPE, "entre_positions"),
                       ("la même sans le tirage sur lequel l'engagement a été choisi",
                        "sensibilite_sans_le_tirage_du_choix")):
        e = apparie[cle]
        ic = "-" if e["ic95"] is None else "[%+.5f ; %+.5f]" % tuple(e["ic95"])
        l.append("  %s : %d position(s), moyenne %s, écart type %s, ET %s, t %s, IC à 95 %% %s%s%s" % (
            titre, e["positions"], "-" if e["effet"] is None else "%+.5f" % e["effet"], _f(e["ecart_type"], 5),
            _f(e["erreur_type"], 5), _f(e["t"], 2), ic, " (quantile approché)" if e["quantile_approche"] else "",
            "" if cle == "entre_positions" else " ; %d tirage(s) écarté(s)" % e["tirages_du_choix_ecartes"]))
        l.append("    %d couple(s) principal(aux) écarté(s), estimé(s) sur moins de %d tirages ; %d position(s) sans aucun "
                 "couple retenu%s" % (
                     e["couples_principaux_ecartes"], e["tirages_min_par_couple"], e["positions_sans_couple_retenu"],
                     "" if cle == "entre_positions" else " ; %d couple(s) principal(aux) du seul tirage du choix, sorti(s) "
                     "avec lui" % e["couples_principaux_du_seul_tirage_du_choix"]))
    for limite in apparie["limites"]:
        l.append("  limite : %s." % limite)
    return l


def _tableau_regle(regle, marge):
    l = [""]
    l.append("Règle entière : _reject_contradictions rejouée sur chaque table (marge %s) -- informatif, hors verdict"
             % marge)
    l.append("  scénario : le bot a promis E et déclare le rompre pour N (E, N ordres distincts d'une unité, valués dans")
    l.append("  au moins une table du groupe) ; unité : %s." % regle["unite"])
    l.append("  %d état(s) impossible(s) écarté(s) (E sur l'unité d'un autre engagement du groupe) ; %d groupe(s) d'une"
             % (regle["etats_impossibles_ecartes"], regle["groupes_d_une_seule_table_non_rejoues"]))
    l.append("  seule table non rejoué(s).")
    for classe, titre, description in CLASSES_REGLE:
        de_la_classe = regle["classes"][classe]
        l.append("  classe « %s » (%s)" % (titre, description))
        if not de_la_classe["total"]["scenarios"]:
            l.append("    aucun scénario")
            continue
        l.append("    %-50s %6s %8s %9s %9s %20s %20s %8s %9s %11s" % (
            "", "scén.", "disputés", "déc. n.u.", "motif n.u.", "désaccord (tous)", "désaccord (disputés)", "remplace",
            "sur bruit", "sans autre"))

        def ligne(nom, bloc):
            return "    %-50s %6d %8d %9d %9d %20s %20s %8d %9d %11d" % (
                nom[:50], bloc["scenarios"], bloc["scenarios_disputes"], bloc["scenarios_a_decision_non_unanime"],
                bloc["scenarios_a_motif_non_unanime"], _dp(bloc["desaccord"]["tous"]),
                _dp(bloc["desaccord"]["disputes"]), bloc["issues"]["remplace"], bloc["acceptations_sur_bruit_effectives"],
                bloc["acceptations_sans_autre_table"])

        total = de_la_classe["total"]
        l.append(ligne("total", total))
        for nom, bloc in de_la_classe["par_position"].items():
            l.append(ligne("position " + nom, bloc))
        if classe == CLASSES_REGLE[0][0]:
            for nom, bloc in de_la_classe["par_groupe"].items():
                l.append(ligne("groupe " + nom, bloc))
        l.append("    issues par (scénario, table) : %s" % ", ".join(
            "%s %d" % (issue, total["issues"][issue]) for issue in ISSUES))
        l.append("    désaccords attribués au motif de la table qui refuse : %s" % ", ".join(
            "%s %d" % (motif, total["attribution"][motif]) for motif in MOTIFS))
        l.append("    instabilité propre (non additive) : valeur connue %s ; marge %s ; condition (e) %s" % (
            _dp(total["instabilite_propre"]["unknown_value"]), _dp(total["instabilite_propre"]["marge"]),
            _dp(total["instabilite_propre"]["condition_e"])))
        l.append("    selon la marge (scénarios disputés, désaccord sur tous) : %s" % " ; ".join(
            "%s : %d, %s" % (m, b["scenarios_disputes"], _dp(b["desaccord"]["tous"]))
            for m, b in total["par_marge"].items()))
        l.append("    sur bruit : « remplace » alors qu'au moins une autre table du groupe porte le couple et que la moyenne "
                 "de G sur ces tables est <= 0 : %d." % total["acceptations_sur_bruit_effectives"])
        l.append("    sans autre : « remplace » alors qu'aucune autre table du groupe ne porte le couple : %d, compté à part "
                 "(pas reproductible, mais rien ne dit que le gain soit du bruit)." % total["acceptations_sans_autre_table"])
    l.append("  scén. : scénarios (groupe, E, N) ; disputés : au moins une table « remplace » ; déc. n.u. : décision non")
    l.append("  unanime ; motif n.u. : issues non toutes égales ; désaccord : k x (n - k) paires de tables en désaccord")
    l.append("  sur n x (n - 1) / 2, la probabilité que deux recherches de la même position décident différemment.")
    for limite in regle["limites"]:
        l.append("  limite : %s." % limite)
    return l


def _fraction(n, total):
    """« 2/1270 (0.16 %) »."""
    return "%d/%d (%s)" % (n, total, "-" if not total else "%.2f %%" % (100.0 * n / total))


def _tableau_evenements(evenements):
    l = [""]
    l.append("Décompte par événement (table, E), recherches A sans engagement, marge %s -- informatif, hors verdict"
             % cle_marge(evenements["marge"]))
    l.append("  le critère publié reste le verdict par observation ci-dessus (décision du mainteneur, 2026-10-10).")
    l.append("  unité : %s." % evenements["unite"])
    l.append("  (a) %s ; (b) %s." % (evenements["parts"]["a"], evenements["parts"]["b"]))
    l.append("  %-44s %20s %20s %8s %10s  %s" % ("", "(a)", "(b)", "tables", "positions", "lecture indicative"))
    for titre, cle in (("règle entière", "regle_entiere"),
                       ("règle entière, promesses « réalistes »", "regle_entiere_promesses_realistes"),
                       ("marge seule (rappel)", "marge_seule")):
        bloc = evenements[cle]
        l.append("  %-44s %20s %20s %8s %10s  %s" % (
            titre, _fraction(bloc["avec_acceptation_sur_bruit"], bloc["exposes"]),
            _fraction(bloc["acceptations_sur_bruit"], bloc["acceptations"]),
            "%d/%d" % (bloc["tables_sur_bruit"], evenements["tables"]),
            "%d/%d" % (bloc["positions_sur_bruit"], evenements["positions"]), bloc["lecture_indicative"] or "-"))
    l.append("  lecture indicative : « protégerait » si %s ; « ne protégerait pas » si %s ; « partiel » %s ; aucune pour"
             % (evenements["seuils"]["protegerait"], evenements["seuils"]["ne_protegerait_pas"],
                evenements["seuils"]["partiel"]))
    l.append("  la marge seule, que nul message ne subit seule. tables, positions : celles qui portent un (table, E) avec")
    l.append("  acceptation sur bruit, sur celles des groupes d'au moins deux tables.")
    l.append("  « réalistes » : E est un ordre d'un des plans exportés de la table jugée. Marge seule : G > marge, sans la")
    l.append("  condition (e). Au dénominateur de (b), règle entière : %d acceptation(s) sans autre table (%d en réaliste)."
             % (evenements["regle_entiere"]["dont_acceptations_sans_autre_table"],
                evenements["regle_entiere_promesses_realistes"]["dont_acceptations_sans_autre_table"]))
    for limite in evenements["limites"]:
        l.append("  limite : %s." % limite)
    return l


def _tableau_dispersion(dispersions):
    l = [""]
    l.append("Dispersion dans un fichier et entre fichiers")
    l.append("  unité : %s." % dispersions["unite"])
    intra = dispersions["ecart_type_intra"]
    l.append("  écart type intra-fichier de G, par groupe d'au moins deux tables (%d groupe(s)) : médiane %s, c95 %s, max %s"
             % (intra["n"], _f(intra["mediane"], 5), _f(intra["c95"], 5), _f(intra["max"], 5)))
    for recherche, s in dispersions["ecart_type_intra_par_type"].items():
        l.append("    recherches %s (%d groupe(s)) : médiane %s, c95 %s, max %s"
                 % (recherche, s["n"], _f(s["mediane"], 5), _f(s["c95"], 5), _f(s["max"], 5)))
    jumelles = dispersions["tables_jumelles"]
    l.append("  tables jumelles (même fichier, même type) : %d paire(s) sur %d examinée(s) -- order_values identiques : %d, "
             "search.lambda identique : %d ; attendu : 0"
             % (jumelles["paires_jumelles"], jumelles["paires_examinees"], len(jumelles["order_values_identiques"]),
                len(jumelles["lambda_identique"])))
    l.append("    le contrôle par search.lambda suppose un %s." % jumelles["hypothese_du_controle_par_lambda"])
    for constat in dispersions["engagements_differents_entre_fichiers"]:
        l.append("  position %s : recherches %s aux engagements différents d'un fichier à l'autre -- %s ; elles forment "
                 "des groupes distincts, pas de test d'indépendance sur le type %s (le choix de l'engagement dépend du "
                 "tirage)"
                 % (constat["position"], constat["recherche"], " ; ".join(
                     "%s (%s, %s)" % (", ".join(x["engagements"]) or "sans engagement", x["fichier"],
                                      _nb(x["tables"], "table"))
                     for x in constat["par_fichier"]), constat["recherche"]))
    decomposes = [g for g in dispersions["par_groupe"] if g["decomposition"]]
    if not decomposes:
        l.append("  aucun groupe réparti sur au moins deux fichiers d'au moins deux tables : pas de décomposition, pas de "
                 "test d'indépendance des tirages d'un lancement")
    for g in decomposes:
        d = g["decomposition"]
        l.append("  groupe %s : fichiers de %s tables, %d couple(s) (%d écarté(s), absents d'une table)"
                 % (g["groupe"], " et ".join(str(n) for n in g["tables_par_fichier"]), g["couples"],
                    g["couples_ecartes_absents_d_une_table"]))
        l.append("    SCE inter %s (%d ddl par couple), SCE intra %s (%d ddl par couple) ; R = CM inter / CM intra = %s ; "
                 "écart type intra %s ; corrélation intra-fichier %s (sans intervalle)"
                 % (_f(d["sce_inter"], 6), d["ddl_inter"], _f(d["sce_intra"], 6), g["ddl_intra"], _f(d["r"], 3),
                    _f(g["ecart_type_intra"], 5), _f(d["correlation_intra_fichier"], 5)))
        f = d["f_par_couple"]
        reperes = d["reperes_sous_h0"]
        l.append("    F par couple (%d, %d à intra nul) : médiane %s, c95 %s, max %s%s"
                 % (f["n"], d["couples_a_intra_nul"], _f(f["mediane"], 3), _f(f["c95"], 3), _f(f["max"], 3),
                    "" if not reperes else " ; repères sous H0 : médiane %.3f, 5 %% au-dessus de %.3f"
                    % (reperes["mediane"], reperes["c95"])))
        if d["p"] is None:
            l.append("    %s" % d["lecture"])
        else:
            l.append("    permutation exacte des tables entre fichiers (%d répartitions) : p = %s = %.4f (plus petit p "
                     "atteignable : %s = %.4f) ; queue inférieure %s"
                     % (d["repartitions"], d["p"]["fraction"], d["p"]["valeur"], d["p_minimal"]["fraction"],
                        d["p_minimal"]["valeur"], d["p_queue_inferieure"]["fraction"]))
            l.append("    lecture, au seuil de %s : %s%s" % (
                dispersions["seuil_p"], d["lecture"].upper() if d["rejet"] else d["lecture"],
                "" if d["rejet"] else " (non rejetée n'est pas établie)"))
        if d["puissance_indicative"]:
            l.append("    puissance indicative (modèle normal, seuil de 5 %%), par corrélation intra-fichier : %s"
                     % " ; ".join("%s : %d sur 100" % (rho, round(100 * x))
                                  for rho, x in d["puissance_indicative"].items()))
        else:
            l.append("    puissance indicative : non calculée (hors du cas de deux fichiers de même taille)")
        if g["recherche"] != TYPE_SANS_ENGAGEMENT:
            l.append("    type %s : pas une confirmation indépendante du test sur le type %s."
                     % (g["recherche"], TYPE_SANS_ENGAGEMENT))
    for limite in dispersions["limites"]:
        l.append("  limite : %s." % limite)
    return l


def tableau(resultat):
    marge = cle_marge(resultat["marge"])
    lecture = resultat["lecture"]
    l = []
    l.append("Bruit des valeurs d'une recherche à l'autre (#26)")
    l.append("  relevés : %s -- %d fichier(s), %d table(s), %d position(s) ; partie(s) %s ; phases %s"
             % (lecture["dossier"], lecture["fichiers"], lecture["tables"], lecture["positions"],
                ", ".join(lecture["parties"]), ", ".join(lecture["phases"])))
    if lecture["recherches_sans_table"]:
        l.append("  recherches sans table exportée, écartées : %s" % ", ".join(lecture["recherches_sans_table"]))
    if lecture["tables_d_essai_a_sec"]:
        l.append("  ATTENTION : %d table(s) d'essai à sec (doublure du moteur), pas des recherches réelles"
                 % lecture["tables_d_essai_a_sec"])
    l.append("  grandeur : %s" % resultat["grandeur"])
    l.append("  marge : %s (COMMITMENT_SWITCH_MARGIN, lue dans %s)" % (marge, resultat["marge_lue_dans"]))
    l.append("  portée : %s" % resultat["portee"])
    for mise_en_garde in resultat["mises_en_garde"]:
        l.append("  MISE EN GARDE : %s" % mise_en_garde)
    if resultat["mises_en_garde"]:
        l.append("  (ces mises en garde entrent dans les avertissements du verdict, qui n'est alors pas concluant)")
    l.append("  Le critère se lit sur les recherches A sans engagement, seules. La recherche B d'un tirage est une mise")
    l.append("  à jour incrémentale de sa recherche A : ses observations ne sont pas indépendantes de celles de A. Les")
    l.append("  niveaux « recherches_b », « groupe » (cumul A + B) et « engagements » sont informatifs.")

    for nom, description in NIVEAUX:
        niveau = resultat["bruit"][nom]
        l.append("")
        l.append("Bruit |d| -- niveau « %s » (%s) : %d groupe(s), dont %d d'au moins deux tables"
                 % (nom, description, niveau["groupes"], niveau["groupes_d_au_moins_deux_tables"]))
        if not niveau["total"]["observations"]:
            l.append("  aucune observation : %s" % sans_observation(niveau))
            if niveau["total"]["couples_dans_une_seule_table"]:
                l.append("  %d couple(s) écarté(s), présents dans une seule table de leur groupe"
                         % niveau["total"]["couples_dans_une_seule_table"])
            continue
        l.append("  %-52s %6s %7s %7s %s %15s %9s %9s" % (
            "", "tables", "couples", "1 table", ENTETE_STATS, "non unanimes", "sur bruit", "marge eff."))

        def ligne(titre, bloc):
            m = bloc["par_marge"][marge]
            return "  %-52s %6d %7d %7d %s %5d (%7s) %9d %9s" % (
                titre[:52], bloc["tables"], bloc["couples"], bloc["couples_dans_une_seule_table"],
                _stats(bloc["abs_d"]), m["couples_non_unanimes"], _pc(m["part_couples_non_unanimes"]),
                m["acceptations_sur_bruit"], _f(m["marge_effective"]))

        l.append(ligne("total", niveau["total"]))
        for titre, bloc in niveau["par_position"].items():
            l.append(ligne("position " + titre, bloc))
        for titre, bloc in niveau["par_groupe"].items():
            l.append(ligne("groupe " + titre, bloc))
        l.append("  1 table : couples écartés, présents dans une seule table de leur groupe ;")
        l.append("  n : observations (couple x table) ; non unanimes : couples dont « G > %s » n'est pas le même dans"
                 % marge)
        l.append("  toutes les tables du groupe ; sur bruit : G > %s alors que la moyenne des autres tables est <= 0 ;"
                 % marge)
        l.append("  marge eff. : marge - c99.")
        m = niveau["total"]["par_marge"][marge]
        if m["acceptations_sur_bruit"]:
            l.append("  les %d acceptation(s) sur bruit sont %s (ordre : couple (table, ordre E))."
                     % (m["acceptations_sur_bruit"], _porteurs(m)))
        l.append("  selon l'action porteuse :")
        for cas in PORTEUSES:
            if niveau["total"]["par_porteuse"][cas]["n"]:
                l.append("    %-50s %14s %s" % (cas, "", _stats(niveau["total"]["par_porteuse"][cas])))
        l.append("  selon la marge :")
        l.append("    %6s %22s %12s %9s %14s %10s %14s %10s" % (
            "marge", "couples non unanimes", "acceptations", "sur bruit", "des sans gain", "des obs.",
            "des accept.", "marge eff."))
        for m, b in niveau["total"]["par_marge"].items():
            l.append("    %6s %12d (%7s) %12d %9d %14s %10s %14s %10s" % (
                m, b["couples_non_unanimes"], _pc(b["part_couples_non_unanimes"]), b["acceptations"],
                b["acceptations_sur_bruit"], _pc(b["part_sur_bruit_des_observations_sans_gain"]),
                _pc(b["part_sur_bruit_des_observations"]), _pc(b["part_sur_bruit_des_acceptations"]),
                _f(b["marge_effective"])))
        l.append("    des sans gain : part des %d observations dont la moyenne des autres tables est <= 0 (celle du critère)."
                 % niveau["total"]["observations_sans_gain"])

    l.append("")
    l.append("Écarts par paire de tables d'une même position, |G_T1 - G_T2| (marge %s)" % marge)
    l.append("  %-40s %6s %7s %7s %s %17s %9s" % (
        "", "paires", "m. type", "1 table", ENTETE_STATS, "verdicts changés", "sur bruit"))

    def ligne_paires(titre, bloc):
        m = bloc["par_marge"][marge]
        return "  %-40s %6d %7d %7d %s %7d (%7s) %9d" % (
            titre[:40], bloc["paires"], bloc["paires_de_meme_type"], bloc["couples_dans_une_seule_table"],
            _stats(bloc["ecart"]), m["verdicts_changes"], _pc(m["part_verdicts_changes"]),
            m["acceptations_sur_bruit"])

    titres = {"memes_engagements": "mêmes engagements", "engagements_differents": "engagements différents",
              "toutes": "toutes les paires"}
    for classe in CLASSES + ("toutes",):
        l.append(ligne_paires(titres[classe], resultat["paires"][classe]["total"]))
        if classe == "toutes":
            continue
        for titre, bloc in resultat["paires"][classe]["par_position"].items():
            l.append(ligne_paires("  " + titre, bloc))
    l.append("  m. type : paires de deux recherches du même type ; 1 table : couples écartés, présents dans une seule")
    l.append("  des deux tables ; n : couples ordonnés communs aux deux tables ;")
    l.append("  sur bruit : G > %s dans une table, <= 0 dans l'autre." % marge)
    l.append("  selon l'action porteuse :")
    for classe in CLASSES:
        for cas in PORTEUSES:
            s = resultat["paires"][classe]["total"]["par_porteuse"][cas]
            if s["n"]:
                l.append("    %-38s %14s %s" % ("%s, %s" % (titres[classe], cas), "", _stats(s)))
    l.append("  selon la marge (verdicts changés, puis acceptations sur bruit) :")
    for classe in CLASSES:
        par_marge = resultat["paires"][classe]["total"]["par_marge"]
        l.append("    %-24s %s" % (titres[classe], " ; ".join(
            "%s : %d (%s), %d" % (m, b["verdicts_changes"], _pc(b["part_verdicts_changes"]), b["acceptations_sur_bruit"])
            for m, b in par_marge.items())))

    effet = resultat["effet_engagement"]
    l.append("")
    l.append("Effet de la recherche B (message, mise à jour incrémentale, engagement), non apparié : moyenne de G avec")
    l.append("engagements - moyenne de G en %s" % effet["reference"])
    if not effet["par_groupe"]:
        l.append("  aucun groupe avec engagements qui ait sa recherche de référence")
    else:
        l.append("  %-52s %s %8s %10s" % ("", ENTETE_STATS, "vers eng.", "effet moy."))

        def ligne_effet(titre, bloc):
            return "  %-52s %s %8d %10s" % (
                titre[:52], _stats(bloc["abs_effet"]), bloc["couples_vers_l_ordre_engage"],
                _f(bloc["effet_moyen_vers_l_ordre_engage"]))

        l.append(ligne_effet("total (%d groupes)" % effet["total"]["groupes"], effet["total"]))
        for recherche, bloc in effet["par_type_de_recherche"].items():
            l.append(ligne_effet("recherches %s (%d groupes)" % (recherche, bloc["groupes"]), bloc))
        for bloc in effet["par_groupe"]:
            l.append(ligne_effet(bloc["groupe"], bloc))
        l.append("  statistiques de |effet| par couple ; vers eng. : couples (E, N) dont N est un ordre engagé, et leur")
        l.append("  effet moyen signé. À une table par groupe, l'effet n'est pas séparable du bruit de cette table.")

    l.extend(_tableau_apparie(effet["apparie"], marge))
    l.extend(_tableau_regle(resultat["regle_entiere"], marge))
    l.extend(_tableau_dispersion(resultat["dispersion"]))

    l.append("")
    l.append("Verdict selon le critère d'expert-cicero (#26), marge %s" % marge)
    for nom, _description in NIVEAUX:
        v = resultat["verdict"][nom]
        if nom == NIVEAU_DE_LA_SPECIFICATION:
            l.append("  Critère lu sur les recherches A sans engagement, seules :")
        elif nom == NIVEAUX[1][0]:
            l.append("  À titre informatif, hors verdict (les observations B ne sont pas indépendantes de celles de A) :")
        if "c99_total" not in v:
            l.append("  niveau « %s » : %s" % (nom, v["verdict"].upper()))
        else:
            titre = v["verdict"].upper()
            if not v["concluant"]:
                titre += " -- lecture indicative : le critère donnerait « %s »%s" % (
                    v["lecture_indicative"],
                    " ; minorant du bruit" if resultat["bruit"][nom]["types_de_recherche_reunis"] else "")
            l.append("  niveau « %s » : %s" % (nom, titre))
            l.append("    c95 %s, c99 %s, pire position %s (c99 %s), %d acceptation(s) sur bruit%s (%s des "
                     "%d observations sans gain), marge effective %s"
                     % (_f(v["c95_total"]), _f(v["c99_total"]), v["pire_position"], _f(v["c99_pire_position"]),
                        v["acceptations_sur_bruit"], ", " + _porteurs(v) if v["acceptations_sur_bruit"] else "",
                        _pc(v["part_sur_bruit_des_observations_sans_gain"]),
                        v["observations_sans_gain"], _f(v["marge_effective"])))
        for avertissement in v["avertissements"]:
            l.append("    AVERTISSEMENT : %s" % avertissement)
    l.append("  Portée : %s." % resultat["portee"])
    if resultat["reporte"]:
        l.append("  Reporté : %s." % " ; ".join(resultat["reporte"]))
    l.extend(_tableau_evenements(resultat["par_evenement"]))
    return "\n".join(l)


def sortie_par_defaut(dossier):
    """<dossier>/bruit_valeurs.json, sauf dans un dépôt git hors de son dossier amont/.

    Le détail nomme positions, puissances et ordres d'une partie : de l'état de
    partie, qui n'a pas sa place dans le dépôt. amont/ est ignoré par git. La
    garde lit l'arborescence et n'appelle pas git, absent de l'image."""
    dossier = Path(dossier).resolve()
    for racine in [dossier] + list(dossier.parents):
        if (racine / ".git").exists():
            if dossier.relative_to(racine).parts[:1] != ("amont",):
                raise ErreurReleve(
                    "%s est dans le dépôt %s, hors de amont/ : donner --sortie pour le fichier JSON" % (dossier, racine)
                )
            break
    return dossier / "bruit_valeurs.json"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier", help="dossier des relevés m1_*.jsonl de rejeu_moteur.py")
    p.add_argument("--sortie", help="fichier JSON du détail (défaut : <dossier>/bruit_valeurs.json, refusé dans le dépôt hors de amont/)")
    p.add_argument("--bot", help="chemin de claude_dialogue_bot.py (défaut : celui du dépôt, sinon de l'image)")
    args = p.parse_args(argv)
    try:
        module, bot = charger_bot(args.bot)
        marge, order_loc = float(module.COMMITMENT_SWITCH_MARGIN), module._order_loc
        tables, lecture = lire_releves(args.dossier, order_loc)
        sortie = Path(args.sortie) if args.sortie else sortie_par_defaut(args.dossier)
        resultat = analyser(tables, lecture, marge, module._reject_contradictions, order_loc, source_marge=bot.name)
        try:
            sortie.parent.mkdir(parents=True, exist_ok=True)
            sortie.write_text(json.dumps(resultat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        except OSError as e:
            raise ErreurReleve("%s : écriture impossible (%s)" % (sortie, e))
    except ErreurReleve as e:
        print("bruit_valeurs : %s" % e, file=sys.stderr)
        return 2
    print(tableau(resultat))
    print("\nDétail complet : %s" % sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
