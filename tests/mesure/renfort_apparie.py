"""M2 -- mesure appariée de #4 : ancien et nouveau renfort appliqués à la même table réelle.

Hors GPU, sur le poste ou dans un conteneur :

    python3 amont/mesure/renfort_apparie.py amont/mesure/resultats/m1_*.jsonl

Entrée : les relevés de M1 (entrée exportée `candidates` / `search`, et l'ordre
d'itération réel de la politique du moteur, `politique_avant_renfort`).
Ancien renfort : apply_commitments_to_policy du commit 7b7ce70
(amont/mesure/avant/pseudo_commitments.py, extrait par preparer.sh), rejoué pour
plusieurs ordres d'itération du dictionnaire, puisque son résultat en dépend.
Nouveau renfort : boosted_policy de l'arbre de travail.
Dans les deux cas : score = value + lambda * ln(max(q, 1e-6)), action de tête.

LIMITE, répétée dans la sortie : la mesure est APPARIÉE (même table, mêmes
valeurs, mêmes probabilités d'avant renfort pour les deux renforts) et APPROCHÉE
AU SECOND ORDRE : les valeurs sont celles d'une recherche faite avec le nouveau
code ; une recherche faite avec l'ancien renfort aurait pondéré autrement les
actions et injecté la même action promise, donc estimé des valeurs un peu
différentes. Seul l'effet direct du renfort sur le classement est mesuré.
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

# Avant tout chargement : commun.charger lit des fichiers de cicero/overlay, où un .pyc
# passerait pour un fichier d'overlay (outils/exporter_patchs.sh --verifier, install.sh ; #27).
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import commun  # noqa: E402

AVERTISSEMENT = (
    "Mesure appariée (même table pour l'ancien et le nouveau renfort), approchée au second ordre : "
    "les valeurs viennent d'une recherche faite avec le nouveau renfort ; l'ancien renfort aurait "
    "conduit à des valeurs légèrement différentes, qui ne sont pas rejouées ici."
)


def charger_renforts(avant, apres):
    if not commun.cicero_present():
        commun.installer_doublures()
    ancien = commun.charger("mesure_avant_pseudo_commitments", avant)
    nouveau = commun.charger("mesure_apres_pseudo_commitments", apres)
    # Les engagements fabriqués sont pris dans la table : légaux par construction. Sans partie
    # sous la main, le filtre de légalité de l'ancien module est remplacé par la seule normalisation.
    ancien.legal_commitments = lambda game, power, orders: [commun.normalize_order_spacing(o) for o in orders]
    return ancien, nouveau


def ordres_d_iteration(candidates, politique_moteur):
    """{nom: [actions]} : les ordres d'itération du dictionnaire rejoués pour l'ancien renfort."""
    table = [tuple(c["orders"]) for c in candidates]
    prob = {tuple(c["orders"]): c["prob"] for c in candidates}
    ordres = {
        "table": table,                    # ordre de la table exportée : score décroissant
        "table_inverse": table[::-1],
        "prob_decroissante": sorted(table, key=lambda a: -prob[a]),
        "prob_croissante": sorted(table, key=lambda a: prob[a]),
    }
    if politique_moteur:
        rang = {tuple(a): i for i, (a, _p) in enumerate(politique_moteur)}
        if all(a in rang for a in table):
            ordres["moteur"] = sorted(table, key=lambda a: rang[a])  # ordre réel du dictionnaire du moteur (M1)
    return ordres


def jeux_d_engagements(entree, max_paires):
    """Jeux fabriqués à partir de la table : chaque ordre des plans exportés seul,
    puis les paires d'ordres de deux unités différentes (au plus max_paires)."""
    vus, ordres = set(), []
    for plan in entree.get("plans") or []:
        for o in plan["orders"]:
            if o not in vus:
                vus.add(o)
                ordres.append(o)
    jeux = [[o] for o in ordres]
    paires = [
        [a, b] for a, b in itertools.combinations(ordres, 2)
        if commun.get_unit_location(a) != commun.get_unit_location(b)
    ]
    return jeux + paires[:max_paires], max(0, len(paires) - max_paires)


def masse_par_tenues(q, promesses):
    """[masse des actions tenant 0 promesse, 1, ..., n]."""
    masses = [0.0] * (len(promesses) + 1)
    for action, p in q.items():
        masses[commun.tenues(action, promesses)] += p
    return [round(m, 6) for m in masses]


def mesurer(candidates, search, politique_moteur, promesses, ancien, nouveau, puissance):
    lam, boost, max_prob = search["lambda"], search["boost"], search["max_prob"]
    avant = {tuple(c["orders"]): c["prob"] for c in candidates}
    cas = {"engagements": promesses, "n": len(promesses)}

    tete_0, _ = commun.tete(candidates, avant, lam)
    cas["sans_renfort"] = {
        "masse_par_tenues": masse_par_tenues(avant, promesses),
        "tete": list(tete_0), "tete_tenues": commun.tenues(tete_0, promesses),
    }

    q_nouveau = nouveau.boosted_policy(avant, promesses, boost, max_prob)
    tete_n, ecart_n = commun.tete(candidates, q_nouveau, lam)
    verif = nouveau.engine_head_action(candidates, search, promesses)
    cas["nouveau"] = {
        "masse_par_tenues": masse_par_tenues(q_nouveau, promesses),
        "tete": list(tete_n), "tete_tenues": commun.tenues(tete_n, promesses), "ecart_au_second": ecart_n,
        "tete_egale_engine_head_action": verif is not None and tuple(verif) == tete_n,
    }

    cas["ancien"] = {}
    for nom, ordre in ordres_d_iteration(candidates, politique_moteur).items():
        politique = {puissance: {a: avant[a] for a in ordre}}  # dict neuf : l'ancienne fonction modifie en place
        q_ancien = ancien.apply_commitments_to_policy(politique, None, {puissance: list(promesses)}, puissance, boost)[puissance]
        tete_a, ecart_a = commun.tete(candidates, q_ancien, lam)
        cas["ancien"][nom] = {
            "masse_par_tenues": masse_par_tenues(q_ancien, promesses),
            "tete": list(tete_a), "tete_tenues": commun.tenues(tete_a, promesses), "ecart_au_second": ecart_a,
            "q": {" | ".join(a): round(p, 9) for a, p in q_ancien.items()},
        }
    reference = "moteur" if "moteur" in cas["ancien"] else "table"
    cas["ancien_reference"] = reference
    tetes = set(tuple(v["tete"]) for v in cas["ancien"].values())
    qs = [v.pop("q") for v in cas["ancien"].values()]
    cas["ancien_tete_depend_de_l_ordre"] = len(tetes) > 1
    cas["ancien_probabilites_dependent_de_l_ordre"] = any(
        abs(q[a] - qs[0][a]) > 1e-9 for q in qs[1:] for a in qs[0]
    )
    cas["tete_change_ancien_vers_nouveau"] = tuple(cas["ancien"][reference]["tete"]) != tete_n
    cas["tete_change_sans_renfort_vers_nouveau"] = tete_0 != tete_n
    return cas


def part(k, n):
    return "%d / %d (%.1f %%)" % (k, n, 100.0 * k / n) if n else "0 / 0"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("releves", nargs="+", help="fichiers JSON lignes écrits par M1")
    p.add_argument("--recherches", default="A", help="recherches de M1 dont la table est prise (défaut : A, sans engagement)")
    p.add_argument("--max-paires", type=int, default=60)
    p.add_argument("--avant", default=str(commun.ICI / "avant" / "pseudo_commitments.py"))
    p.add_argument("--apres", default=str(commun.ICI.parents[1] / "cicero" / "overlay" / "fairdiplomacy" / "utils" / "pseudo_commitments.py"))
    p.add_argument("--sortie", help="fichier JSON de sortie (défaut : resultats/m2_<horodatage>.json à côté des relevés)")
    args = p.parse_args()

    if not Path(args.apres).exists():  # dans un conteneur : la copie faite par preparer.sh
        args.apres = str(commun.ICI / "apres" / "pseudo_commitments.py")
    ancien, nouveau = charger_renforts(args.avant, args.apres)
    print(AVERTISSEMENT)
    print("ancien  : %s sha256 %s" % (args.avant, commun.sha256(args.avant)))
    print("nouveau : %s sha256 %s" % (args.apres, commun.sha256(args.apres)))

    resultats, ecartes = [], []
    for fichier in args.releves:
        engagements_m1 = {}
        lignes = [r for r in commun.lire_lignes(fichier) if "recherche" in r]
        for r in lignes:  # les engagements réellement fabriqués par M1 pour ce tirage
            if r.get("engagements_retenus_par_le_moteur"):
                engagements_m1[r["tirage"]] = r["engagements_retenus_par_le_moteur"]
        for r in lignes:
            if r["recherche"] not in args.recherches.split(","):
                continue
            entree = r.get("entree") or {}
            candidates, search = entree.get("candidates"), entree.get("search")
            position = "%s %s %s tirage %s recherche %s" % (r["game_id"], r["phase"], r["puissance"], r["tirage"], r["recherche"])
            if nouveau.engine_head_action(candidates, search, ()) is None:
                ecartes.append("%s (%s) : table absente ou illisible" % (position, fichier))
                continue
            if search["max_prob"] != ancien.MAX_COMMITMENT_PROB:
                ecartes.append("%s : plafond exporté %s différent de celui de l'ancien code %s" % (position, search["max_prob"], ancien.MAX_COMMITMENT_PROB))
                continue
            jeux, paires_ecartees = jeux_d_engagements(entree, args.max_paires)
            m1 = engagements_m1.get(r["tirage"])
            if m1 and m1 not in jeux:
                jeux.append(m1)
            for promesses in jeux:
                cas = mesurer(candidates, search, r.get("politique_avant_renfort"), promesses, ancien, nouveau, r["puissance"])
                cas.update({"position": position, "fichier": str(fichier), "puissance": r["puissance"],
                            "search": search, "actions_candidates": len(candidates),
                            "engagements_de_m1": promesses == m1, "paires_non_mesurees": paires_ecartees})
                resultats.append(cas)

    for cas in resultats:
        a = cas["ancien"][cas["ancien_reference"]]
        print(
            "%s | %s | masse par nb de promesses tenues (0..n) : sans %s, ancien[%s] %s, nouveau %s | "
            "tête tient : ancien %d, nouveau %d sur %d | tête change : %s | ancien dépend de l'ordre : tête %s, probabilités %s"
            % (cas["position"], cas["engagements"], cas["sans_renfort"]["masse_par_tenues"], cas["ancien_reference"],
               a["masse_par_tenues"], cas["nouveau"]["masse_par_tenues"], a["tete_tenues"], cas["nouveau"]["tete_tenues"],
               cas["n"], cas["tete_change_ancien_vers_nouveau"], cas["ancien_tete_depend_de_l_ordre"],
               cas["ancien_probabilites_dependent_de_l_ordre"])
        )

    n = len(resultats)
    resume = {"avertissement": AVERTISSEMENT, "cas": n, "tables_ecartees": ecartes}
    for nom, cle in (
        ("tête différente entre l'ancien renfort (ordre de référence) et le nouveau", "tete_change_ancien_vers_nouveau"),
        ("tête de l'ancien renfort dépendante de l'ordre d'itération", "ancien_tete_depend_de_l_ordre"),
        ("probabilités de l'ancien renfort dépendantes de l'ordre d'itération", "ancien_probabilites_dependent_de_l_ordre"),
        ("tête différente entre l'absence de renfort et le nouveau renfort", "tete_change_sans_renfort_vers_nouveau"),
    ):
        resume[cle] = part(sum(1 for c in resultats if c[cle]), n)
    for taille in sorted(set(c["n"] for c in resultats)):
        sous = [c for c in resultats if c["n"] == taille]
        for version, lire in (("ancien", lambda c: c["ancien"][c["ancien_reference"]]), ("nouveau", lambda c: c["nouveau"])):
            compte = [sum(1 for c in sous if lire(c)["tete_tenues"] == k) for k in range(taille + 1)]
            resume["n=%d %s : cas par nombre de promesses tenues par la tête (0..n)" % (taille, version)] = compte
    resume["ordre de référence de l'ancien renfort"] = sorted(set(c["ancien_reference"] for c in resultats))
    resume["nouveau : tête égale à engine_head_action"] = part(sum(1 for c in resultats if c["nouveau"]["tete_egale_engine_head_action"]), n)

    print("\nRÉSUMÉ M2")
    for cle, valeur in resume.items():
        print("  %s : %s" % (cle, valeur))

    sortie = Path(args.sortie) if args.sortie else Path(args.releves[0]).resolve().parent / ("m2_%s.json" % commun.horodatage())
    commun.ecrire_json(sortie, {"resume": resume, "cas": resultats})
    print("M2 : %s" % sortie)


if __name__ == "__main__":
    main()
