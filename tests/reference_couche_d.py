#!/usr/bin/env python3
"""Couche D de la référence de non-régression (issue #31) : fonctions pures rejouées sur le jeu d'essai figé.

Déterministe, sans amont/ ni conteneur, sans Claude ni GPU : les trois fichiers du
dépôt qui portent la logique des promesses sont chargés comme dans
tests/banc_promesses.py. Lancée par tests/verifier.sh.

    python3 tests/reference_couche_d.py                      compare tests/reference/ à ses attendus
    python3 tests/reference_couche_d.py --jeu D [--tout] [--sortie F.json]
    python3 tests/reference_couche_d.py --jeu D --mutations  critère d'acceptation (a) de #31
    python3 tests/reference_couche_d.py --jeu D --textes PHASE PUISSANCE
    python3 tests/reference_couche_d.py --jeu D --generer    SESSION PRINCIPALE SEULE, après visa

--generer affiche d'abord, grandeur par grandeur, ce que les attendus déjà là
deviennent (rien n'est écrasé sans être montré). Il lit l'état du dépôt par git
(lecture seule, --no-optional-locks) : sur un arbre de travail modifié il refuse,
sauf --arbre-modifie, qui note alors le SHA suivi de « -modifie » ; sans git, --sha
est obligatoire. L'arbre contrôlé est cicero/overlay et tests/, sauf tests/reference/ :
le jeu d'essai que `reference_jeu.py reduire` vient d'y poser n'est pas encore suivi,
et les attendus s'y écrivent. Ce dossier est gardé autrement : --generer commence par
le contrôle du jeu (`reference_jeu.controler`) et refuse, sans rien écrire, un jeu qui ne
le passe pas -- une table retouchée à la main ne correspond plus au manifeste, et les
empreintes ne sont pas refaites par-dessus. Le refus dit comment en sortir, selon le cas :
une table ou l'historique qui ne correspondent plus au manifeste, et rien d'autre --
`reference_jeu.py manifeste` si la modification est voulue, puis --generer ; toute autre
violation (attendus/ retouché, par exemple) -- supprimer attendus/, `reference_jeu.py
manifeste`, puis --generer. La batterie, elle, n'appelle jamais git ici.

Tant que le jeu d'essai est absent ou vide, rien n'est comparé : la commande le dit
et rend 0. Sinon, pour chaque table (phase, puissance) :

  D1   export_plans rejoué sur ses arguments bruts (`export_plans` de la table), comparé
       aux quatre clés de la table. Inactif pour une table sans arguments relevés.
  D1r  export_plans rejoué sur la table elle-même (ses candidats, leur valeur déjà
       arrondie, leur probabilité d'avant renfort) : `order_values`, `candidates`,
       `search` et les plans doivent en ressortir tels quels ; seul `cost_vs_best`,
       recalculé sur des valeurs arrondies, a ses attendus (`couts`).
  D2   renfort, sur cinq jeux de promesses tirés de la table par une règle fixe
       (jeux_de_promesses) : aucune ; un ordre du plan préféré ; un ordre d'une
       alternative ; deux ordres ; un ordre absent de tout candidat. Par jeu : la
       politique renforcée comme le moteur la calcule (boosted_policy, plafond par
       défaut), résumée (q de la tête, moment = somme des (rang + 1) x q : toute
       probabilité qui change le déplace), et le classement recalculé par le bot
       (rescored_candidates, engine_head_action : rang de la tête, son score, la
       somme des scores).
  D3   verdict de _reject_contradictions pour chaque couple ordonné (ancien, nouveau)
       d'ordres distincts d'une même unité : avec label (un verdict et un gain par
       couple), sans label et sans table (décompte des verdicts) ; plus un cas par
       table, `deux_trahisons` : deux trahisons déclarées dans un même message, sur
       deux unités (rejugement de la troisième condition).
  D4   texte de build_plan_section, de build_commitments_section (avec et sans table)
       et de la consigne système, sur les promesses « prefere » et « alternative » :
       empreinte du texte (16 chiffres hexadécimaux de son SHA-256) et coûts affichés.
  D5   cycles simulés (run_cycle, Claude et le site doublés) sur des suites fixes de
       réponses fabriquées : `cycle` (promesse, ordre contraire, trahison déclarée,
       révision, deux ordres pour une unité, trahison refusée) et `deux_detenteurs`
       (la même promesse faite à deux puissances, puis trahie devant une troisième).
       Par message : balises du journal et retour de _reject_contradictions ; puis
       by_recipient, own_promises et le fichier d'engagements.
  D6   registre de confiance (_score_promises) : chaque ordre de la table pris comme
       promesse, jugé contre les ordres de l'historique, dans les deux sens (promesses
       reçues, promesses du bot).

Les scénarios de D3 (`deux_trahisons`) et de D5 se choisissent d'après les verdicts
de D3 (scenarios) : ils sont choisis une fois, à la génération, et relus ensuite
dans les attendus (scenarios_enregistres). Une modification du code change donc le
comportement mesuré sur une suite inchangée, jamais la suite elle-même.

Ce que cette couche est, et n'est pas :
  - D1r est gardée même quand D1 est active : c'est elle qui voit la définition
    d'`order_values` sur une table sans arguments bruts.
  - La table d'une position est la recherche A du tirage 0 du premier fichier de
    relevés : une table réelle parmi d'autres, pas « la table typique » de la
    position (le bruit d'une recherche à l'autre est l'objet de #26 et de la couche R).
  - Un changement de cicero_no_dialogue.prototxt, du patch du moteur, du commit
    épinglé ou de l'image est invisible ici : la couche D rejoue des fonctions
    pures sur des tables figées. Le voir est le rôle de la couche R.

Comparaison à l'identique ; flottants à 1e-12 relatif. Une différence est une ligne
« couche | phase | puissance | grandeur | avant | après », prête pour un tableau
avant / après. Un texte n'est enregistré que par son empreinte (aucun texte n'entre
dans tests/reference/, ADR 0006) : --textes l'affiche tel que le code le produit.

--mutations : recharge les trois fichiers avec, tour à tour, chacune des
modifications volontaires de MUTATIONS (texte source modifié en mémoire, rien n'est
écrit) et compte les grandeurs qui changent par couche ; rend 1 si l'une d'elles
n'est vue par aucune couche. Les paramètres qui vivent dans la configuration du
moteur (multiplicateur, lambda) sont, dans une table, des données : la couche D les
fixe, c'est la couche R qui voit leur changement.
"""
import argparse
import contextlib
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # avant tout chargement de cicero/overlay (#27)

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(ICI / "mesure"))
import banc_promesses as banc  # noqa: E402
import commun  # noqa: E402
import reference_jeu  # noqa: E402

RACINE = ICI.parent
TOLERANCE = 1e-12  # relative, sur les flottants
UTILS = banc.OVERLAY / "fairdiplomacy" / "utils"
FICHIERS = {
    "plan_export": UTILS / "plan_export.py",
    "pseudo_commitments": UTILS / "pseudo_commitments.py",
    "bot": banc.OVERLAY / "claude_dialogue_bot.py",
}
COUCHES = ("D1", "D1r", "D2", "D3", "D4", "D5", "D6")
PHASE_COURANTE = "COURANTE"  # phase en cours du jeu de D6 : toutes celles de l'historique sont résolues

# Modifications volontaires du critère d'acceptation (a) de #31 : (nom, fichier, texte
# remplacé, texte mis à sa place). Chaque texte remplacé doit se trouver une fois, et une
# seule, dans le fichier : sinon la mutation est périmée et --mutations le dit.
MUTATIONS = (
    ("marge 0,05 -> 0,03", "bot",
     "COMMITMENT_SWITCH_MARGIN = 0.05\n", "COMMITMENT_SWITCH_MARGIN = 0.03\n"),
    ("arrondi du gain : 4 décimales au lieu de 5", "bot",
     "gain = round(v_new - v_old, 5)", "gain = round(v_new - v_old, 4)"),
    ("order_values : meilleure valeur brute de l'ordre", "plan_export",
     "order_values.setdefault(order, value if math.isfinite(value) else None)",
     "order_values[order] = value if order_values.get(order) is None else max(order_values[order], value)"),
    ("multiplicateur du renfort 3 -> 2 (appliqué par boosted_policy)", "pseudo_commitments",
     "factor = boost_multiplier ** (held / len(promised))",
     "factor = (boost_multiplier * 2.0 / 3.0) ** (held / len(promised))"),
    ("plafond du renfort 0,4 -> 0,5", "pseudo_commitments",
     "MAX_COMMITMENT_PROB = 0.4\n", "MAX_COMMITMENT_PROB = 0.5\n"),
    ("plancher de probabilité du score 1e-6 -> 1e-3", "pseudo_commitments",
     "SCORE_PROB_FLOOR = 1e-6\n", "SCORE_PROB_FLOOR = 1e-3\n"),
    ("lambda doublé dans le score recalculé", "pseudo_commitments",
     "values[action] + regularize_lambda * math.log(", "values[action] + 2.0 * regularize_lambda * math.log("),
)


class MutationPerimee(Exception):
    """Le texte qu'une mutation remplace n'est plus (une seule fois) dans le fichier."""


# ---------------------------------------------------------------------------
# Modules mesurés
# ---------------------------------------------------------------------------

def charger_modules(remplacements=()):
    """(bot, plan_export, pseudo_commitments) : ceux du banc, ou des mutants.

    `remplacements` : [(fichier, ancien, nouveau)], appliqués au texte source en
    mémoire avant son exécution ; aucun fichier n'est écrit. Les doublures des
    modules de Cicero sont celles que le banc a installées à son chargement.
    """
    if not remplacements:
        return banc.bot, banc.plan_export, banc.pseudo_commitments
    modules = {}
    for nom, chemin in FICHIERS.items():
        source = chemin.read_text(encoding="utf-8")
        for fichier, ancien, nouveau in remplacements:
            if fichier != nom:
                continue
            if source.count(ancien) != 1:
                raise MutationPerimee("%r se trouve %d fois dans %s" % (ancien, source.count(ancien), chemin.name))
            source = source.replace(ancien, nouveau)
        module = types.ModuleType("mutant_" + nom)
        module.__file__ = str(chemin)
        exec(compile(source, str(chemin), "exec"), module.__dict__)
        modules[nom] = module
    # Comme banc.charger_modules : la vraie fonction, pas l'attribut de la doublure.
    modules["bot"].engine_head_action = modules["pseudo_commitments"].engine_head_action
    return modules["bot"], modules["plan_export"], modules["pseudo_commitments"]


@contextlib.contextmanager
def _dans_le_banc(modules):
    """Les fonctions du banc (rejet_complet, Banc) travaillent sur `modules` le temps du bloc."""
    bot, plan_export, pseudo_commitments = modules
    with mock.patch.object(banc, "bot", bot), mock.patch.object(banc, "plan_export", plan_export), \
            mock.patch.object(banc, "pseudo_commitments", pseudo_commitments), \
            mock.patch.object(bot, "normalize_order_spacing", banc.normalize_order_spacing):
        yield


def empreinte(texte):
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Scénarios fixes, tirés de la table
# ---------------------------------------------------------------------------

def ordres_de_la_table(table):
    """{unité: [ordres distincts]}, dans l'ordre de première apparition dans `candidates`."""
    return commun.ordres_par_unite(table["candidates"])


PROVINCES = sorted(lieu for lieu in reference_jeu.LIEUX if "/" not in lieu)


def ordre_absent(table):
    """Un ordre de la première unité du plan préféré qu'aucun candidat ne joue : tenir, sinon un mouvement.

    Bien formé, pas forcément légal : seule compte son absence de la table.
    """
    genre, lieu = table["plans"][0]["orders"][0].split()[:2]
    joues = {o for ordres in ordres_de_la_table(table).values() for o in ordres}
    essais = ["%s %s H" % (genre, lieu)] + ["%s %s - %s" % (genre, lieu, vers) for vers in PROVINCES]
    return next(o for o in essais if o not in joues)


def ordre_sans_unite(table):
    """Un ordre pour une province où la puissance n'a aucune unité à ordonner."""
    unites = {lieu.split("/")[0] for lieu in ordres_de_la_table(table)}
    return "A %s H" % next(province for province in PROVINCES if province not in unites)


def jeux_de_promesses(table):
    """Les cinq jeux de promesses de D2, par une règle qui ne dépend que de la table.

    « prefere » et « alternative » : commun.choisir_engagements, la règle des
    engagements fabriqués de tests/mesure/rejeu_moteur.py. « deux » : l'ordre de
    « prefere », et le premier ordre de la table qui porte sur une autre unité et que
    le plan préféré ne joue pas (à défaut, un second ordre du plan préféré).
    """
    prefere, _ = commun.choisir_engagements(table, "prefere")
    alternative, _ = commun.choisir_engagements(table, "alternative")
    tete = table["plans"][0]["orders"]
    unite = commun.get_unit_location(prefere[0])
    autres = [
        o for lieu, ordres in ordres_de_la_table(table).items() for o in ordres
        if lieu != unite and o not in tete
    ] or [o for o in tete if o != prefere[0]]
    return {
        "aucune": [], "prefere": prefere, "alternative": alternative,
        "deux": prefere + autres[:1], "absent": [ordre_absent(table)],
    }


def interlocuteurs(puissance, nombre=2):
    """Les premières autres puissances : à qui le bot promet dans D3, D4 et D5."""
    return tuple(p for p in commun.POWERS if p != puissance)[:nombre]


def _couples(d3_label, sauf_unite=None):
    return [
        (ancien, nouveau, verdict) for ancien, nouveaux in d3_label.items() for nouveau, verdict in nouveaux.items()
        if commun.get_unit_location(ancien) != sauf_unite
    ]


def couple_du_cycle(d3_label, sauf_unite=None):
    """Un couple (ancien, nouveau) : le premier que D3 accepte, sinon celui de plus grand gain ; None s'il n'y en a pas."""
    couples = _couples(d3_label, sauf_unite)
    for ancien, nouveau, verdict in couples:
        if verdict[0] == "superseded":
            return ancien, nouveau
    chiffres = [c for c in couples if c[2][1] is not None]
    if chiffres:
        return max(chiffres, key=lambda c: c[2][1])[:2]  # max rend le premier en cas d'égalité
    return couples[0][:2] if couples else None


def scenarios(table, puissance, d3_label):
    """Les entrées des scénarios qui se choisissent d'après les verdicts de D3 (à la génération seulement).

    `cycle` et `deux_detenteurs` : suites de [expéditeur, sincere, betray], les
    réponses de Claude fabriquées de D5. `deux_trahisons` : {"sincere", "betray"},
    le message de D3 qui trahit deux promesses à la fois. Un scénario que la table
    n'offre pas (pas deux ordres pour une unité, pas deux unités) est absent.
    """
    premier, second, troisieme = interlocuteurs(puissance, 3)
    couple = couple_du_cycle(d3_label)
    if couple is None:  # aucune unité n'a deux ordres : une promesse, redite
        ordre = table["plans"][0]["orders"][0]
        return {"cycle": [[premier, [ordre], None], [second, [ordre], None]]}
    ancien, nouveau = couple
    unite = commun.get_unit_location(ancien)
    cycle = [
        [premier, [ancien], None],            # promesse
        [second, [nouveau], None],            # ordre contraire sans label
        [second, [nouveau], [ancien]],        # trahison déclarée
        [premier, [nouveau], [ancien]],       # la même, dans la conversation d'origine
        [second, [ancien, nouveau], [ordre_absent(table)]],  # deux ordres pour l'unité, label sans objet
    ]
    # Une seconde unité, où D3 refuse la trahison (si la table en offre une) : promesse, puis trahison déclarée.
    for refuse, contre, verdict in _couples(d3_label, unite):
        if verdict[0] in ("below_margin", "not_played"):
            cycle += [[premier, [refuse], None], [second, [contre], [refuse]]]
            break
    choisis = {
        "cycle": cycle,
        # La même promesse tenue par deux puissances, puis trahie devant une troisième.
        "deux_detenteurs": [[premier, [ancien], None], [second, [ancien], None], [troisieme, [nouveau], [ancien]]],
    }
    autre = couple_du_cycle(d3_label, unite)
    if autre is not None:
        choisis["deux_trahisons"] = {"sincere": [nouveau, autre[1]], "betray": [ancien, autre[0]]}
    return choisis


CLES_MESSAGE = ("expediteur", "sincere", "betray", "balises", "retour")


def _message(message):
    """Un message de D5 par ses clés, qu'il soit écrit en liste (attendus enregistrés) ou déjà en objet."""
    return dict(zip(CLES_MESSAGE, message)) if isinstance(message, list) else message


def scenarios_enregistres(attendus):
    """Les mêmes entrées, relues dans les attendus d'une table ; None s'ils n'en portent pas."""
    if not isinstance(attendus, dict) or not isinstance(attendus.get("D5"), dict):
        return None
    relus = {
        nom: [[m["expediteur"], m["sincere"], m["betray"]] for m in map(_message, cycle["messages"])]
        for nom, cycle in attendus["D5"].items()
    }
    deux = attendus.get("D3", {}).get("deux_trahisons")
    if deux is not None:
        relus["deux_trahisons"] = {"sincere": deux["sincere"], "betray": deux["betray"]}
    return relus


# ---------------------------------------------------------------------------
# Les couches
# ---------------------------------------------------------------------------

def _quatre_cles(table):
    return {cle: table[cle] for cle in reference_jeu.CLES_TABLE}


def _exporter(plan_export, phase, puissance, action_values, avant, recherche, dossier):
    fichier = Path(dossier) / "current_plans.json"
    if fichier.exists():
        fichier.unlink()
    with mock.patch.object(plan_export, "PLANS_FILE", fichier):
        plan_export.export_plans(
            "0", phase, puissance, action_values, prior_policy=avant,
            regularize_lambda=recherche[0], boost=recherche[1], max_prob=recherche[2],
        )
        entree = plan_export.load_plans("0", phase, puissance)
    if not entree:
        raise ValueError("export_plans n'a rien écrit")
    entree.pop("computed_at", None)
    return entree


def d1(modules, phase, puissance, table, dossier):
    """export_plans sur ses arguments bruts ; None si la table n'en a pas."""
    arguments = table.get("export_plans")
    if arguments is None:
        return None
    # Une action écrite sans ses ordres est celle du même rang dans `candidates` (reference_jeu.reduire_arguments).
    actions = [
        tuple(a["orders"] if "orders" in a else table["candidates"][i]["orders"])
        for i, a in enumerate(arguments["action_values"])
    ]
    avant = {
        (actions[ligne["action"]] if "action" in ligne else tuple(ligne["orders"])): ligne["prob"]
        for ligne in arguments["prior_policy"]
    }
    action_values = [(actions[i], a["value"], a["prob"], a["score"]) for i, a in enumerate(arguments["action_values"])]
    recherche = (arguments["regularize_lambda"], arguments["boost"], arguments["max_prob"])
    return _exporter(modules[1], phase, puissance, action_values, avant, recherche, dossier)


def d1r(modules, phase, puissance, table, dossier):
    """export_plans sur la table elle-même : tout doit en ressortir tel quel, sauf `cost_vs_best`."""
    candidats, recherche = table["candidates"], table["search"]
    action_values = [(tuple(c["orders"]), c["value"], c["prob"], 0.0) for c in candidats]
    avant = {tuple(c["orders"]): c["prob"] for c in candidats}
    entree = _exporter(
        modules[1], phase, puissance, action_values, avant,
        (recherche["lambda"], recherche["boost"], recherche["max_prob"]), dossier,
    )
    return _sans_couts(entree)


def _sans_couts(entree):
    resultat = _quatre_cles(entree)
    resultat["couts"] = [p["cost_vs_best"] for p in entree["plans"]]
    resultat["plans"] = [{c: p[c] for c in ("rank", "orders", "value")} for p in entree["plans"]]
    return resultat


def d2(modules, table):
    pc = modules[2]
    candidats, recherche = table["candidates"], table["search"]
    politique = {tuple(c["orders"]): c["prob"] for c in candidats}
    actions = list(politique)
    resultat = {}
    for nom, promesses in jeux_de_promesses(table).items():
        # Comme le moteur (apply_commitments_to_policy) : le plafond est celui du module.
        q = pc.boosted_policy(politique, promesses, recherche["boost"])
        lignes = pc.rescored_candidates(candidats, recherche, promesses)
        tete = pc.engine_head_action(candidats, recherche, promesses)
        scores = [ligne[3] for ligne in lignes]
        rang = actions.index(tete)
        resultat[nom] = {
            "promesses": list(promesses), "tete": rang,
            "q_tete": q[tete], "moment_q": math.fsum((i + 1) * q[a] for i, a in enumerate(actions)),
            "score_tete": scores[rang], "somme_scores": math.fsum(scores),
        }
    return resultat


def _verdict(retour):
    acceptes, retrogrades, remplaces, _conflits, _ignores = retour
    if remplaces:
        return ["superseded", remplaces[0][3]]
    if retrogrades:
        return [retrogrades[0][2], retrogrades[0][3]]
    return ["accepted" if acceptes else "conflicting", None]


def _resumer(retour):
    """Le retour de _reject_contradictions, par verdict ; les listes vides ne s'écrivent pas."""
    acceptes, retrogrades, remplaces, conflits, ignores = retour
    resume = {"accepted": list(acceptes)}
    for nouveau, ancien, raison, gain in retrogrades:
        resume.setdefault(raison, []).append([nouveau, ancien] if gain is None else [nouveau, ancien, gain])
    resume["superseded"] = [list(ligne) for ligne in remplaces]
    resume["conflicting"] = [list(ligne) for ligne in conflits]
    resume["betrayal-ignored"] = [list(ligne) for ligne in ignores]
    return {cle: lignes for cle, lignes in resume.items() if lignes}


def d3(modules, puissance, table, entrees=None):
    """Verdicts par couple, et le cas `deux_trahisons` ; rend (grandeurs, entrées des scénarios).

    `entrees` : celles des attendus (scenarios_enregistres) ; None : choisies ici,
    d'après les verdicts qui viennent d'être calculés (génération).
    """
    tiers = interlocuteurs(puissance)[0]
    table_moteur = dict(order_values=table["order_values"], candidates=table["candidates"], search=table["search"])
    label, sans_label, sans_table = {}, {}, {}
    with _dans_le_banc(modules):
        for ordres in ordres_de_la_table(table).values():
            for ancien in ordres:
                for nouveau in ordres:
                    if nouveau == ancien:
                        continue
                    retour, _ = banc.rejet_complet([nouveau], {tiers: [ancien]}, table["plans"], betray=[ancien], **table_moteur)
                    label.setdefault(ancien, {})[nouveau] = _verdict(retour)
                    retour, _ = banc.rejet_complet([nouveau], {tiers: [ancien]}, table["plans"], **table_moteur)
                    statut = _verdict(retour)[0]
                    sans_label[statut] = sans_label.get(statut, 0) + 1
                    retour, _ = banc.rejet_complet(
                        [nouveau], {tiers: [ancien]}, table["plans"], betray=[ancien],
                        order_values=table["order_values"], table=False,
                    )
                    statut = _verdict(retour)[0]
                    sans_table[statut] = sans_table.get(statut, 0) + 1
        resultat = {"label": label, "sans_label": sans_label, "sans_table": sans_table}
        if entrees is None:
            entrees = scenarios(table, puissance, label)
        deux = entrees.get("deux_trahisons")
        if deux is not None:
            retour, _ = banc.rejet_complet(
                deux["sincere"], {tiers: list(deux["betray"])}, table["plans"], betray=deux["betray"], **table_moteur
            )
            resultat["deux_trahisons"] = {"sincere": deux["sincere"], "betray": deux["betray"], "retour": _resumer(retour)}
    return resultat, entrees


def textes_d4(modules, phase, puissance, table):
    """Les quatre textes de D4, tels que le code les produit, et les coûts qu'ils affichent."""
    bot = modules[0]
    premier, second = interlocuteurs(puissance)
    promesses = jeux_de_promesses(table)
    by_recipient = {d: o for d, o in ((premier, promesses["prefere"]), (second, promesses["alternative"])) if o}
    plans, order_values = table["plans"], table["order_values"]
    with _dans_le_banc(modules), mock.patch.object(bot, "load_plans", lambda *a, **k: _quatre_cles(table)):
        plan = bot.build_plan_section(0, phase, puissance)
        engagements = bot.build_commitments_section(
            by_recipient, premier, plans, order_values, candidates=table["candidates"], search=table["search"],
        )
        sans_table = bot.build_commitments_section(by_recipient, premier, plans, order_values)
        consigne = bot.SYSTEM_PROMPT_TEMPLATE.format(
            power=puissance, margin=bot.COMMITMENT_SWITCH_MARGIN, plan_section=plan,
            commitments_section=engagements, own_record_section="", trust_section="",
        )
        couts_plan = [bot._shown_cost(p.get("cost_vs_best")) for p in plans[1:]]
        couts_engagements = []
        for ordres in by_recipient.values():
            for ordre in ordres:
                valeur = bot._order_value(ordre, plans, order_values)
                couts_engagements.append(None if valeur is None else bot._shown_cost(plans[0]["value"] - valeur))
    return {
        "plan": (plan, couts_plan), "engagements": (engagements, couts_engagements),
        "engagements_sans_table": (sans_table, None), "consigne": (consigne, None),
    }


def d4(modules, phase, puissance, table):
    resultat = {}
    for nom, (texte, couts) in textes_d4(modules, phase, puissance, table).items():
        resultat[nom] = {"empreinte": empreinte(texte), "longueur": len(texte)}
        if couts is not None:
            resultat[nom]["couts"] = couts
    return resultat


def d5(modules, phase, puissance, table, entrees):
    """Un cycle simulé par scénario de `entrees` (hors `deux_trahisons`, qui est de D3), chacun dans un banc neuf."""
    resultat = {}
    for nom, messages in entrees.items():
        if nom == "deux_trahisons":
            continue
        jeu = banc.FauxJeu(puissance, ordres_de_la_table(table), phase)
        releves = []
        with _dans_le_banc(modules), banc.Banc(_quatre_cles(table), jeu=jeu, interlocuteurs=interlocuteurs(puissance, 3)) as essai:
            for expediteur, sincere, betray in messages:
                journal = essai.message(expediteur, sincere, betray)
                releves.append({
                    "expediteur": expediteur, "sincere": sincere, "betray": betray,
                    "balises": {b.strip("[]"): n for b, n in banc.balises(journal).items()},
                    "retour": _resumer(essai.retours[-1]),
                })
            en_attente = essai.promesses_du_bot().get("pending", {})
            resultat[nom] = {
                "messages": releves,
                "by_recipient": essai.by_recipient(),
                "own_promises": {cle.split(":", 1)[1]: ordres for cle, ordres in en_attente.items()},
                "fichier": essai.engagements(),
            }
    return resultat


class _Position:
    def __init__(self, puissance, unites):
        self.puissance, self.unites = puissance, unites

    def get_orderable_locations(self):
        return {self.puissance: list(self.unites)}


class JeuHistorique:
    """Ce que _score_promises lit d'une partie : ses phases jouées, et les unités à ordonner au début d'une phase."""

    def __init__(self, historique, puissance, unites):
        self.phases = [banc.PhaseJouee(p["name"], p["orders"]) for p in historique["phases"]]
        self.puissance, self.unites = puissance, unites

    def get_all_phases(self):
        return self.phases + [banc.PhaseJouee(PHASE_COURANTE, {})]

    def rolled_back_to_phase_start(self, phase):
        return _Position(self.puissance, self.unites)


def d6(modules, phase, puissance, table, historique):
    bot = modules[0]
    unites = ordres_de_la_table(table)
    promesses = [o for ordres in unites.values() for o in ordres] + [ordre_absent(table), ordre_sans_unite(table)]
    jeu = JeuHistorique(historique, puissance, unites)
    tiers = interlocuteurs(puissance)[0]
    resultat = {}
    with _dans_le_banc(modules):
        for nom, cle, options in (
            ("recus", "%s:%s" % (phase, puissance), {}),
            ("propres", "%s:%s" % (phase, tiers), {"promiser": puissance, "current_phase": PHASE_COURANTE}),
        ):
            en_attente, registre, sortie = {cle: list(promesses)}, {}, io.StringIO()
            with contextlib.redirect_stdout(sortie):
                bot._score_promises(jeu, en_attente, registre, **options)
            fiche = registre.get(cle.split(":", 1)[1], {})
            resultat[nom] = {
                "resolue": cle not in en_attente,
                "kept": fiche.get("kept", 0), "broken": fiche.get("broken", 0),
                "exemples": empreinte(json.dumps(fiche.get("examples", []), sort_keys=True)),
                "lignes": len(sortie.getvalue().splitlines()),
            }
    return resultat


def calculer_table(modules, phase, puissance, table, historique, dossier, entrees=None):
    """Les grandeurs de toutes les couches pour une table. Une couche qui lève rend {"erreur": ...}.

    `entrees` : les scénarios relus dans les attendus ; None : choisis d'après D3 (génération).
    """
    resultat = {}

    def couche(nom, fonction, *arguments):
        try:
            valeur = fonction(*arguments)
        except Exception as e:  # une mutation peut faire lever : c'est une différence, pas un arrêt
            valeur = {"erreur": "%s: %s" % (type(e).__name__, str(e)[:200])}
        if valeur is not None:
            resultat[nom] = valeur
        return valeur

    couche("D1", d1, modules, phase, puissance, table, dossier)
    couche("D1r", d1r, modules, phase, puissance, table, dossier)
    couche("D2", d2, modules, table)
    try:
        resultat["D3"], entrees = d3(modules, puissance, table, entrees)
    except Exception as e:
        resultat["D3"], entrees = {"erreur": "%s: %s" % (type(e).__name__, str(e)[:200])}, entrees or {}
    couche("D4", d4, modules, phase, puissance, table)
    couche("D5", d5, modules, phase, puissance, table, entrees)
    couche("D6", d6, modules, phase, puissance, table, historique)
    return resultat


def calculer(jeu, modules=None, scenarios_fixes=True):
    """{phase: {puissance: grandeurs}} pour toutes les tables du jeu.

    `scenarios_fixes` : les scénarios de D3 et de D5 sont ceux des attendus de la
    table quand elle en a ; faux (génération) : ils sont choisis à neuf.
    """
    modules = charger_modules() if modules is None else modules
    with tempfile.TemporaryDirectory() as dossier:
        return {
            phase: {
                puissance: calculer_table(
                    modules, phase, puissance, table, jeu["historique"], dossier,
                    scenarios_enregistres(jeu["attendus"].get(phase, {}).get(puissance)) if scenarios_fixes else None,
                )
                for puissance, table in tables.items()
            }
            for phase, tables in jeu["tables"].items()
        }


# ---------------------------------------------------------------------------
# Attendus
# ---------------------------------------------------------------------------

def _serrer_d3(label):
    """Verdicts avec label, par unité, sans répéter ni l'ordre ni le verdict à chaque couple (plafond de taille).

    Par unité : ses ordres ; `gains`, un par couple (ancien, nouveau), ancien
    d'abord, dans l'ordre des ordres ; puis, par verdict, les rangs des couples
    qui le reçoivent.
    """
    par_unite = {}
    for ancien in label:
        par_unite.setdefault(commun.get_unit_location(ancien), []).append(ancien)
    unites = []
    for ordres in par_unite.values():
        verdicts = [label[a][n] for a in ordres for n in ordres if n != a]
        unite = {"ordres": ordres, "gains": [gain for _statut, gain in verdicts]}
        for rang, (statut, _gain) in enumerate(verdicts):
            unite.setdefault(statut, []).append(rang)
        unites.append(unite)
    return unites


def _desserrer_d3(unites):
    label = {}
    for unite in unites:
        couples = [(a, n) for a in unite["ordres"] for n in unite["ordres"] if n != a]
        statuts = {rang: cle for cle, rangs in unite.items() if cle not in ("ordres", "gains") for rang in rangs}
        for rang, (ancien, nouveau) in enumerate(couples):
            label.setdefault(ancien, {})[nouveau] = [statuts.get(rang), unite["gains"][rang]]
    return label


def a_enregistrer(obtenu):
    """Ce qui s'écrit dans attendus/ : tout, sauf ce que la table porte déjà (D1, et D1r hors `couts`).

    Les verdicts de D3 avec label y sont rangés par unité (_serrer_d3), et un
    message de D5 s'écrit en liste, dans l'ordre de CLES_MESSAGE : la taille compte.
    """
    enregistre = {}
    for phase, tables in obtenu.items():
        for puissance, grandeurs in tables.items():
            garde = {c: v for c, v in grandeurs.items() if c != "D1"}
            if "couts" in garde.get("D1r", {}):
                garde["D1r"] = {"couts": garde["D1r"]["couts"]}
            if "label" in garde.get("D3", {}):
                garde["D3"] = dict(garde["D3"], label=_serrer_d3(garde["D3"]["label"]))
            if "erreur" not in garde.get("D5", {"erreur": 1}):
                garde["D5"] = {
                    nom: dict(cycle, messages=[[m[cle] for cle in CLES_MESSAGE] for m in cycle["messages"]])
                    for nom, cycle in garde["D5"].items()
                }
            enregistre.setdefault(phase, {})[puissance] = garde
    return enregistre


def attendus_complets(jeu):
    """{phase: {puissance: attendus}} : ceux du dossier, complétés par ce que la table porte (D1, D1r).

    Une table sans attendus enregistrés n'y figure pas.
    """
    complets = {}
    for phase, tables in jeu["tables"].items():
        for puissance, table in tables.items():
            enregistres = jeu["attendus"].get(phase, {}).get(puissance)
            if enregistres is None:
                continue
            attendu = dict(enregistres)
            if "export_plans" in table:
                attendu["D1"] = _quatre_cles(table)
            attendu["D1r"] = dict(_sans_couts(table), couts=enregistres.get("D1r", {}).get("couts"))
            if isinstance(attendu.get("D3", {}).get("label"), list):
                attendu["D3"] = dict(attendu["D3"], label=_desserrer_d3(attendu["D3"]["label"]))
            if isinstance(attendu.get("D5"), dict):
                attendu["D5"] = {
                    nom: dict(cycle, messages=[_message(m) for m in cycle["messages"]])
                    for nom, cycle in attendu["D5"].items()
                }
            complets.setdefault(phase, {})[puissance] = attendu
    return complets


# ---------------------------------------------------------------------------
# Comparaison
# ---------------------------------------------------------------------------

ABSENT = "(absent)"


def _est_nombre(valeur):
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def differences(avant, apres, chemin=""):
    """[(grandeur, avant, après)] ; à l'identique, flottants à TOLERANCE relative."""
    if isinstance(avant, dict) and isinstance(apres, dict):
        lignes = []
        for cle in list(avant) + [c for c in apres if c not in avant]:
            ici = "%s/%s" % (chemin, cle) if chemin else str(cle)
            if cle not in avant:
                lignes.append((ici, ABSENT, apres[cle]))
            elif cle not in apres:
                lignes.append((ici, avant[cle], ABSENT))
            else:
                lignes.extend(differences(avant[cle], apres[cle], ici))
        return lignes
    if isinstance(avant, (list, tuple)) and isinstance(apres, (list, tuple)):
        if len(avant) != len(apres):
            return [(chemin, list(avant), list(apres))]
        return [
            ligne for i, (a, b) in enumerate(zip(avant, apres))
            for ligne in differences(a, b, "%s/%d" % (chemin, i))
        ]
    if _est_nombre(avant) and _est_nombre(apres):
        egaux = avant == apres or math.isclose(avant, apres, rel_tol=TOLERANCE, abs_tol=0.0)
        return [] if egaux else [(chemin, avant, apres)]
    return [] if avant == apres and type(avant) is type(apres) else [(chemin, avant, apres)]


def nombre_de_grandeurs(valeur):
    if isinstance(valeur, dict):
        return sum(nombre_de_grandeurs(v) for v in valeur.values())
    if isinstance(valeur, (list, tuple)):
        return sum(nombre_de_grandeurs(v) for v in valeur)
    return 1


def comparer(attendus, obtenu):
    """([(couche, phase, puissance, grandeur, avant, après)], grandeurs comparées, tables sans attendus)."""
    lignes, total, sans_attendus = [], 0, []
    for phase, tables in obtenu.items():
        for puissance, grandeurs in tables.items():
            attendu = attendus.get(phase, {}).get(puissance)
            if attendu is None:
                sans_attendus.append("%s %s" % (phase, puissance))
                continue
            total += nombre_de_grandeurs(attendu)
            for grandeur, avant, apres in differences(attendu, grandeurs):
                couche, _, reste = grandeur.partition("/")
                lignes.append((couche, phase, puissance, reste, avant, apres))
    return lignes, total, sans_attendus


def par_couche(lignes):
    decompte = {couche: 0 for couche in COUCHES}
    for ligne in lignes:
        decompte[ligne[0]] = decompte.get(ligne[0], 0) + 1
    return decompte


def _court(valeur, largeur=60):
    texte = valeur if valeur == ABSENT else json.dumps(valeur, ensure_ascii=False)
    return texte if len(texte) <= largeur else texte[:largeur - 1] + "…"


def afficher(lignes, limite=None):
    print("couche | phase | puissance | grandeur | avant | après")
    for couche, phase, puissance, grandeur, avant, apres in lignes[:limite]:
        print("%s | %s | %s | %s | %s | %s" % (couche, phase, puissance, grandeur, _court(avant), _court(apres)))
    if limite is not None and len(lignes) > limite:
        print("… %d autre(s) différence(s) : --tout les affiche, --sortie les écrit" % (len(lignes) - limite))


def resume(decompte):
    return ", ".join("%s : %d" % (couche, n) for couche, n in decompte.items() if n) or "aucune"


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def _tables(jeu):
    return [(phase, puissance, table) for phase, tables in jeu["tables"].items() for puissance, table in tables.items()]


def commande_comparer(jeu, args):
    obtenu = calculer(jeu)
    lignes, total, sans_attendus = comparer(attendus_complets(jeu), obtenu)
    tables = _tables(jeu)
    if not tables:
        print("ÉCHEC : %s n'est pas vide mais aucune table n'y est comparée (aucun fichier de %s/)." % (
            args.jeu, reference_jeu.TABLES))
        return 1
    sans_arguments = sum(1 for _p, _q, table in tables if "export_plans" not in table)
    print("Couche D : %d table(s), %d grandeur(s) comparée(s), %d différence(s) (%s)." % (
        len(tables) - len(sans_attendus), total, len(lignes), resume(par_couche(lignes))))
    if sans_arguments:
        print("  D1 inactive pour %d table(s) sur %d : arguments bruts d'export_plans non relevés." % (sans_arguments, len(tables)))
    if sans_attendus:
        print("ÉCHEC : attendus absents pour %d table(s) (%s) : à générer par la session principale (--generer)." % (
            len(sans_attendus), ", ".join(sans_attendus[:6]) + ("…" if len(sans_attendus) > 6 else "")))
    if lignes:
        afficher(lignes, None if args.tout else 40)
        if args.sortie:
            Path(args.sortie).write_text(json.dumps(
                [dict(zip(("couche", "phase", "puissance", "grandeur", "avant", "apres"), ligne)) for ligne in lignes],
                ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("ÉCHEC : la couche D diffère de la référence. Une ligne ci-dessus qui n'est pas expliquée par la "
              "modification en cours est une régression ; la référence ne se régénère qu'après visa.")
    return 1 if lignes or sans_attendus else 0


def commande_mutations(jeu, args):
    attendus = attendus_complets(jeu)
    if not attendus:
        print("ÉCHEC : le jeu n'a pas d'attendus, rien à quoi comparer une mutation.")
        return 1
    temoin, total, _ = comparer(attendus, calculer(jeu))
    print("Sans mutation : %d différence(s) sur %d grandeur(s)." % (len(temoin), total))
    print("mutation | " + " | ".join(COUCHES) + " | total | vue")
    echec = bool(temoin)
    for nom, fichier, ancien, nouveau in MUTATIONS:
        try:
            modules = charger_modules([(fichier, ancien, nouveau)])
        except MutationPerimee as e:
            print("%s | mutation périmée : %s" % (nom, e))
            echec = True
            continue
        lignes, _, _ = comparer(attendus, calculer(jeu, modules))
        decompte = par_couche(lignes)
        print("%s | %s | %d | %s" % (nom, " | ".join(str(decompte[c]) for c in COUCHES), len(lignes), "oui" if lignes else "NON"))
        if args.tout:
            afficher(lignes)
        echec = echec or not lignes
    return 1 if echec else 0


MESURES = ("cicero/overlay", "tests")  # ce dont les attendus dépendent : le code mesuré et le harnais
# Le jeu d'essai est la donnée produite, ni le code mesuré ni le harnais : posé juste avant --generer,
# il n'est pas encore suivi, et un contrôle qui le compterait refuserait toujours. Pathspec git, relatif
# à RACINE ; un renommage à cheval reste vu par son côté contrôlé (« D » ou « A » au lieu de « R »).
HORS_MESURES = "tests/reference"


def arbre_modifie():
    """Fichiers modifiés ou non suivis sous MESURES, hors HORS_MESURES, d'après git (lecture seule) ; None si git ne répond pas."""
    try:
        sortie = subprocess.run(
            # --untracked-files : status.showUntrackedFiles=no, chez l'appelant, cacherait un harnais non suivi.
            ["git", "--no-optional-locks", "-C", str(RACINE), "status", "--porcelain", "--untracked-files=normal", "--"]
            + list(MESURES)
            + [":(exclude)" + HORS_MESURES],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if sortie.returncode != 0:
        return None
    return [ligne for ligne in sortie.stdout.decode("utf-8", "replace").splitlines() if ligne.strip()]


def sha_du_depot():
    try:
        sortie = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(RACINE), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    return sortie.stdout.decode().strip() if sortie.returncode == 0 else None


def _table_ou_historique_retouche(violation):
    """Vrai si la violation est « <table ou historique> ne correspond plus au manifeste », telle que l'écrit le contrôle."""
    parties = violation.split(" : ")
    if len(parties) < 3 or parties[:2] != [reference_jeu.MANIFESTE, "fichiers"]:
        return False
    fichier, _espace, suite = parties[2].partition(" ")
    return suite.startswith(reference_jeu.NE_CORRESPOND_PLUS) and (
        fichier == reference_jeu.HISTORIQUE or fichier.startswith(reference_jeu.TABLES + "/"))


def refus_du_jeu(dossier, violations):
    """Le message du refus de --generer devant un jeu qui ne passe pas son contrôle : ce qui ne va pas, et la sortie.

    Deux cas. Une table ou l'historique ne correspondent plus au manifeste, et rien d'autre : la
    commande `manifeste` suffit, si la modification est voulue. Toute autre violation (attendus/
    retouché, fichier en trop...) : les attendus sont à refaire, en trois temps. Ce chemin ne lève
    pas une violation portée par le contenu d'une table ou de l'historique : le message le dit.
    """
    autres = [v for v in violations if not _table_ou_historique_retouche(v)]
    tete = "REFUS : le jeu d'essai de %s ne passe pas son contrôle (%d violation(s), dont : %s) ; rien n'est écrit. " % (
        dossier, len(violations), (autres or violations)[0])
    manifeste = "python3 tests/reference_jeu.py manifeste --dossier %s" % dossier
    if not autres:
        return tete + (
            "--generer ne change pas les tables (ADR 0006) : une table ou l'historique ne correspond plus au manifeste. "
            "Si la modification est voulue, refaire d'abord le manifeste : %s (session principale, après visa), puis "
            "relancer --generer." % manifeste)
    return tete + (
        "La violation n'est pas seulement celle d'une table ou de l'historique retouchés : refaire le manifeste ne "
        "suffit pas. Pour refaire les attendus, en trois temps (session principale, après visa) : 1) supprimer %s ; "
        "2) %s ; 3) relancer --generer. Une violation portée par le contenu d'une table ou de l'historique se corrige "
        "d'abord dans le fichier : ce chemin ne la lève pas." % (dossier / reference_jeu.ATTENDUS, manifeste))


def commande_generer(jeu, args):
    dossier = Path(args.jeu)
    # Le jeu d'essai est hors du contrôle d'arbre (HORS_MESURES) : c'est son manifeste qui le garde. Plus bas,
    # ecrire_manifeste refait toutes les empreintes ; sans ce refus, une table retouchée à la main y serait entérinée.
    violations = reference_jeu.controler(dossier)
    if violations:
        print(refus_du_jeu(dossier, violations), file=sys.stderr)
        return 2
    modifies = arbre_modifie()
    sha = args.sha or sha_du_depot()
    if sha is None:
        print("REFUS : git ne répond pas ; donner --sha (SHA complet du code mesuré).", file=sys.stderr)
        return 2
    if modifies is None and not args.sha:
        print("REFUS : l'état de l'arbre de travail est inconnu ; donner --sha.", file=sys.stderr)
        return 2
    if modifies:
        if not args.arbre_modifie:
            print("REFUS : arbre de travail modifié sous %s, hors %s (%d fichier(s), dont %s) : le SHA noté ne "
                  "dirait pas quel code a produit les attendus. Commiter d'abord, ou --arbre-modifie (le SHA est "
                  "alors suivi de « -modifie »)." % (
                      " et ".join(MESURES), HORS_MESURES, len(modifies), modifies[0].strip()), file=sys.stderr)
            return 2
        sha += "-modifie"
    obtenu = calculer(jeu, scenarios_fixes=False)
    erreurs = [
        "%s %s %s : %s" % (couche, phase, puissance, valeur["erreur"])
        for phase, tables in obtenu.items() for puissance, grandeurs in tables.items()
        for couche, valeur in grandeurs.items() if isinstance(valeur, dict) and "erreur" in valeur
    ]
    if erreurs:
        print("REFUS : une couche a levé, rien n'est écrit :\n  " + "\n  ".join(erreurs), file=sys.stderr)
        return 2
    # Ce que les attendus déjà là deviennent : montré avant d'être écrasé.
    ecrasees, _total, nouvelles = comparer(attendus_complets(jeu), obtenu)
    if ecrasees:
        print("Attendus écrasés : %d grandeur(s) changent (%s)." % (len(ecrasees), resume(par_couche(ecrasees))))
        afficher(ecrasees, None if args.tout else 40)
    elif jeu["attendus"]:
        print("Attendus écrasés : aucune grandeur ne change.")
    if jeu["attendus"] and nouvelles:
        print("Attendus nouveaux pour %d table(s)." % len(nouvelles))
    for phase, contenu in a_enregistrer(obtenu).items():
        reference_jeu.ecrire_json(dossier / reference_jeu.ATTENDUS / (phase + ".json"), {"phase": phase, "attendus": contenu})
    reference_jeu.ecrire_manifeste(dossier, dict(jeu["manifeste"], attendus={
        "date": args.date or time.strftime("%Y-%m-%d"), "sha_code": sha,
        "commande": "python3 tests/reference_couche_d.py --jeu <dossier> --generer",
    }))
    violations = reference_jeu.controler(dossier)
    for violation in violations:
        print("ÉCHEC : %s" % violation)
    print("Attendus de %d table(s) écrits dans %s (code %s)." % (len(_tables(jeu)), dossier / reference_jeu.ATTENDUS, sha))
    return 1 if violations else 0


def commande_textes(jeu, args):
    phase, puissance = args.textes[0], args.textes[1].upper()
    table = jeu["tables"].get(phase, {}).get(puissance)
    if table is None:
        print("aucune table %s %s dans le jeu" % (phase, puissance), file=sys.stderr)
        return 2
    for nom, (texte, _couts) in textes_d4(charger_modules(), phase, puissance, table).items():
        print("=== %s (%s, %d caractères)\n%s" % (nom, empreinte(texte), len(texte), texte))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--jeu", default=str(reference_jeu.DOSSIER), help="dossier du jeu d'essai (défaut : tests/reference)")
    p.add_argument("--tout", action="store_true", help="affiche toutes les différences (40 par défaut)")
    p.add_argument("--sortie", help="écrit toutes les différences dans ce fichier JSON (hors dépôt)")
    p.add_argument("--mutations", action="store_true", help="critère d'acceptation (a) : chaque mutation doit être vue")
    p.add_argument("--textes", nargs=2, metavar=("PHASE", "PUISSANCE"), help="affiche les textes de D4 d'une table")
    p.add_argument("--generer", action="store_true", help="écrit les attendus (session principale seule, après visa)")
    p.add_argument("--sha", help="avec --generer : SHA complet du code (défaut : git rev-parse HEAD)")
    p.add_argument("--arbre-modifie", action="store_true",
                   help="avec --generer : accepte un arbre de travail modifié, noté par « -modifie » après le SHA")
    p.add_argument("--date", help="avec --generer : date (défaut : aujourd'hui)")
    args = p.parse_args(argv)

    try:
        jeu = reference_jeu.lire_jeu(args.jeu)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print("ÉCHEC : jeu d'essai illisible dans %s (%s : %s) ; voir tests/reference_jeu.py controler." % (
            args.jeu, type(e).__name__, str(e)[:120]))
        return 1
    if jeu is None:
        if reference_jeu.liens_du_jeu(args.jeu):
            print("ÉCHEC : %s ne contient que des liens symboliques." % args.jeu)
            return 1
        print("Couche D : %s est absent ou vide, rien n'est comparé." % args.jeu)
        return 0
    if args.generer:
        return commande_generer(jeu, args)
    if args.mutations:
        return commande_mutations(jeu, args)
    if args.textes:
        return commande_textes(jeu, args)
    return commande_comparer(jeu, args)


if __name__ == "__main__":
    sys.exit(main())
