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

Bruit. d = G_T - moyenne de G sur les autres tables du groupe, à deux niveaux :
  « groupe »      : (partie, phase, puissance, engagements retenus, type de
                    recherche A / B / C) -- la définition de la spécification ;
  « engagements » : le même sans le type de recherche. B et C d'un rejeu
                    incrémental y sont réunis : ce ne sont pas deux tirages
                    indépendants, la valeur est un minorant.
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
que le critère donnerait en lecture indicative. Le niveau « engagements » n'est
jamais concluant.

Reporté, à faire avant le dépouillement de la campagne de recherches (#26) :
l'instabilité de la règle entière (marge, condition (e), unknown_value, par
_reject_contradictions) ; l'erreur type de l'effet de l'engagement ; la
dispersion dans un fichier et entre fichiers.

Sorties : un tableau lisible sur la sortie standard, le détail complet en JSON
(<dossier>/bruit_valeurs.json, ou --sortie ; sans --sortie, refus d'écrire dans
un dépôt git hors de son dossier amont/, que git ignore : un relevé contient de
l'état de partie). Relevé illisible : un message sur la sortie d'erreur et le
code de retour 2.
"""
import argparse
import itertools
import json
import math
import re
import sys
from pathlib import Path

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
NIVEAU_DE_LA_SPECIFICATION = "groupe"

NIVEAUX = (
    ("groupe", "position, engagements retenus et type de recherche"),
    ("engagements", "position et engagements retenus, types de recherche réunis"),
)
CLASSES = ("memes_engagements", "engagements_differents")
PORTEUSES = ("inchangee", "changee", "inconnue")
CLES_RECHERCHE = ("game_id", "phase", "puissance", "recherche", "engagements_retenus_par_le_moteur")


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


def charger_regle(chemin=None):
    """(marge, _order_loc, chemin) du bot de dialogue, chargé comme dans les essais à sec."""
    bot = trouver_bot(chemin)
    if not commun.cicero_present():
        commun.installer_doublures()
    try:
        module = commun.charger("mesure_bruit_claude_dialogue_bot", bot)
        return float(module.COMMITMENT_SWITCH_MARGIN), module._order_loc, bot
    except Exception as e:
        raise ErreurReleve("%s : COMMITMENT_SWITCH_MARGIN et _order_loc illisibles (%s: %s)" % (bot, type(e).__name__, e))


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
    return cle + (table["recherche"],) if niveau == "groupe" else cle


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


def verdict(niveau, marge, nom=NIVEAU_DE_LA_SPECIFICATION):
    """Critère d'expert-cicero (#26) sur un niveau de bruit, à la marge donnée.

    `verdict` n'est l'issue du critère que si rien n'empêche de conclure ; sinon
    « non concluant » (« indéterminé » sans aucune observation), l'issue du
    critère passant dans `lecture_indicative` et les raisons dans `avertissements`."""
    total = niveau["total"]
    v = {
        "marge": marge, "observations": total["observations"], "lecture_indicative": None,
        "concluant": False, "avertissements": [],
    }
    if not total["observations"]:
        v["verdict"] = "indéterminé"
        v["avertissements"].append(sans_observation(niveau) + " : le bruit n'est pas mesurable à ce niveau")
        return v
    a_marge = total["par_marge"][cle_marge(marge)]
    pire_nom, pire = max(niveau["par_position"].items(), key=lambda item: item[1]["abs_d"]["c99"])
    part = a_marge["part_sur_bruit_des_observations_sans_gain"] or 0.0  # aucune observation sans gain : rien à accepter
    v.update({
        "c95_total": total["abs_d"]["c95"], "c99_total": total["abs_d"]["c99"],
        "pire_position": pire_nom, "c99_pire_position": pire["abs_d"]["c99"],
        "acceptations_sur_bruit": a_marge["acceptations_sur_bruit"],
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
        v["avertissements"].append(
            "niveau « %s » : hors de la spécification, donné à titre indicatif seulement" % nom
        )
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
    v["concluant"] = not v["avertissements"]
    v["verdict"] = issue if v["concluant"] else "non concluant"
    v["lecture_indicative"] = None if v["concluant"] else issue
    return v


def sans_observation(niveau):
    """Pourquoi un niveau n'a aucune observation."""
    if not niveau["groupes_d_au_moins_deux_tables"]:
        return "aucun des %d groupe(s) ne compte deux tables" % niveau["groupes"]
    return ("%d groupe(s) d'au moins deux tables, mais aucun couple d'ordres commun à deux tables"
            % niveau["groupes_d_au_moins_deux_tables"])


def analyser(tables, lecture, marge, marges=MARGES_BALAYEES, source_marge=None):
    marges = tuple(sorted(set(marges) | {marge}))
    bruit = {nom: niveau_bruit(tables, nom, marges) for nom, _ in NIVEAUX}
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
        "reporte": [
            "instabilité de la règle entière (marge, condition (e), unknown_value) par _reject_contradictions",
            "erreur type de l'effet de l'engagement",
            "dispersion dans un fichier et entre fichiers",
        ],
        "lecture": lecture,
        "bruit": bruit,
        "paires": synthese_paires(tables, marges),
        "effet_engagement": effet_engagement(tables),
        "verdict": {nom: verdict(bruit[nom], marge, nom) for nom, _ in NIVEAUX},
    }


# ---------------------------------------------------------------------------
# Tableau lisible
# ---------------------------------------------------------------------------

def _f(x, chiffres=4):
    return "-" if x is None else "%.*f" % (chiffres, x)


def _pc(x):
    return "-" if x is None else "%.1f %%" % (100 * x)


def _stats(s):
    return "%7d %8s %8s %8s %8s %8s" % (s["n"], _f(s["mediane"]), _f(s["c90"]), _f(s["c95"]), _f(s["c99"]), _f(s["max"]))


ENTETE_STATS = "%7s %8s %8s %8s %8s %8s" % ("n", "médiane", "c90", "c95", "c99", "max")


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
    l.append("Effet de l'engagement, à part du bruit : moyenne de G avec engagements - moyenne de G en %s"
             % effet["reference"])
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

    l.append("")
    l.append("Verdict selon le critère d'expert-cicero (#26), marge %s" % marge)
    for nom, _description in NIVEAUX:
        v = resultat["verdict"][nom]
        if "c99_total" not in v:
            l.append("  niveau « %s » : %s" % (nom, v["verdict"].upper()))
        else:
            titre = v["verdict"].upper()
            if not v["concluant"]:
                titre += " -- lecture indicative : le critère donnerait « %s »%s" % (
                    v["lecture_indicative"],
                    " ; minorant du bruit" if resultat["bruit"][nom]["types_de_recherche_reunis"] else "")
            l.append("  niveau « %s » : %s" % (nom, titre))
            l.append("    c95 %s, c99 %s, pire position %s (c99 %s), %d acceptation(s) sur bruit (%s des %d observations "
                     "sans gain), marge effective %s"
                     % (_f(v["c95_total"]), _f(v["c99_total"]), v["pire_position"], _f(v["c99_pire_position"]),
                        v["acceptations_sur_bruit"], _pc(v["part_sur_bruit_des_observations_sans_gain"]),
                        v["observations_sans_gain"], _f(v["marge_effective"])))
        for avertissement in v["avertissements"]:
            l.append("    AVERTISSEMENT : %s" % avertissement)
    l.append("  Portée : %s." % resultat["portee"])
    l.append("  Reporté : %s." % " ; ".join(resultat["reporte"]))
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
        marge, order_loc, bot = charger_regle(args.bot)
        tables, lecture = lire_releves(args.dossier, order_loc)
        sortie = Path(args.sortie) if args.sortie else sortie_par_defaut(args.dossier)
        resultat = analyser(tables, lecture, marge, source_marge=bot.name)
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
