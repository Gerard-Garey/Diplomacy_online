"""M3 -- appels réels à Claude par generate_reply, avant (7b7ce70) et après (arbre de travail).

À lancer dans le conteneur cicero-dialogue, après `bash amont/mesure/preparer.sh --dialogue` :

    python /mesure/claude_avant_apres.py --entree /mesure/resultats/m1_....jsonl --lister
    python /mesure/claude_avant_apres.py --entree ... --interlocuteur X --tiers T --dry-run
    python /mesure/claude_avant_apres.py --entree ... --interlocuteur X --tiers T --n 1
    python /mesure/claude_avant_apres.py --entree ... --interlocuteur X --tiers T

Cinq situations fabriquées sur une entrée réelle exportée par M1 (recherche A) :
S1 sans conflit, S2 conflit acceptable, S3 conflit à refuser, S4 révision,
S5 bilan. S1 à S3 : avant et après ; S4 et S5 : après seulement. 20 tirages par
case : 160 appels, PLAFOND DUR (compteur persistant resultats/m3_compteur_appels.json).

Rien n'est écrit dans l'état de production : les deux versions du bot sont
chargées comme modules distincts depuis /tmp/mesure/{avant,apres} (à défaut
avant/ et apres/ à côté du script), leurs fonctions d'écriture sont neutralisées,
CICERO_PLANS_FILE et PSEUDO_COMMITMENTS_FILE pointent dans <MESURE_DIR>/travail.
Aucun message n'est envoyé ; le site n'est lu qu'une fois (statut de la partie).

--dry-run : construit et imprime les consignes, n'appelle pas Claude.
--simuler : réponses fabriquées à la place de Claude (essai de la chaîne de
            relevés), fichiers et compteur à part.
Hors conteneur (essai à sec), les modules de Cicero sont des doublures : pas de
plateau réel, légalité des ordres non contrôlée.
"""
import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import commun  # noqa: E402

PLAFOND = 160            # appels réels à Claude, toutes exécutions confondues
TIRAGES = 20
ECHECS_DE_SUITE_MAX = 3  # arrêt si la CLI échoue trois fois de suite : le plafond ne se brûle pas sur une panne
SITUATIONS = ("S1", "S2", "S3", "S4", "S5")
VERSIONS = {"S1": ("avant", "apres"), "S2": ("avant", "apres"), "S3": ("avant", "apres"),
            "S4": ("apres",), "S5": ("apres",)}

# Messages reçus de l'interlocuteur X : textes fixes ; seuls les ordres choisis dans la table y sont insérés.
MESSAGES = {
    "S1": "Quick one about your unit in {unite}: are you playing {O} this turn? I'd like to plan around it.",
    "S2": "I need you to play {N} this turn. Can you commit to that?",
    "S3": "I need you to play {N} this turn. Can you commit to that?",
    "S4": "Change of plan on my side: instead of {E}, I now need you to play {N} this turn. Can you commit to that?",
    "S5": "Last turn you promised me {promis} and then you played {joue}. Why should I believe anything you say now?",
}


class PlafondAtteint(RuntimeError):
    pass


class ASec(RuntimeError):
    """--dry-run : la consigne est construite, l'appel n'est pas fait."""


# ---------------------------------------------------------------------------
# Chargement des deux versions
# ---------------------------------------------------------------------------

def _interdit(*_a, **_k):
    raise RuntimeError("écriture d'état interdite pendant la mesure")


def charger_version(nom, dossier):
    """Le bot de `dossier` et ses fairdiplomacy.utils, comme modules distincts de ceux de l'image."""
    dossier = Path(dossier)
    pc = commun.charger("mesure_%s_pseudo_commitments" % nom, dossier / "pseudo_commitments.py")
    pe = commun.charger("mesure_%s_plan_export" % nom, dossier / "plan_export.py")
    noms = {"fairdiplomacy.utils.pseudo_commitments": pc, "fairdiplomacy.utils.plan_export": pe}
    anciens = {k: sys.modules.get(k) for k in noms}
    sys.modules.update(noms)
    try:
        bot = commun.charger("mesure_%s_claude_dialogue_bot" % nom, dossier / "claude_dialogue_bot.py")
    finally:
        for k, v in anciens.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    for ecriture in ("save_state", "save_commitments_file", "_write_json_file", "remove_commitment",
                     "process_bot", "run_cycle", "main"):
        if hasattr(bot, ecriture):
            setattr(bot, ecriture, _interdit)
    commun.refuser_volume_production(bot.COMMITMENTS_FILE, pe.PLANS_FILE, pc.COMMITMENTS_FILE)
    return bot, pc, pe


# ---------------------------------------------------------------------------
# Choix des couples (E, N) dans la table
# ---------------------------------------------------------------------------

def couples(entree, pc, marge):
    """Tous les couples (E, N) d'ordres distincts d'une même unité dont la valeur est connue."""
    plans, ov = entree.get("plans") or [], entree.get("order_values") or {}
    candidates, search = entree.get("candidates"), entree.get("search")
    dans_plans = set(o for p in plans for o in p["orders"])
    prefere = plans[0]["orders"] if plans else []
    trouves = []
    for unite, ordres in commun.ordres_par_unite(candidates or []).items():
        for e in ordres:
            for n in ordres:
                if e == n or e not in ov or n not in ov:
                    continue
                head = pc.engine_head_action(candidates, search, [n])
                trouves.append({
                    "unite": unite, "E": e, "N": n, "gain": round(ov[n] - ov[e], 5),
                    "N_en_tete_apres_renfort": head is not None and n in head,
                    "dans_les_plans_affiches": e in dans_plans and n in dans_plans,
                    "N_dans_le_plan_prefere": n in prefere,
                })
    s2 = sorted((c for c in trouves if c["gain"] > marge and c["N_en_tete_apres_renfort"]),
                key=lambda c: (not c["dans_les_plans_affiches"], -c["gain"], c["E"], c["N"]))
    s3 = sorted((c for c in trouves if c["gain"] <= marge),
                key=lambda c: (not c["dans_les_plans_affiches"], not c["gain"] > 0,
                               not c["N_en_tete_apres_renfort"], -c["gain"], c["E"], c["N"]))
    return s2, s3


def couple_impose(texte):
    e, n = [commun.normalize_order_spacing(x) for x in texte.split("|")]
    return e, n


def phase_de_mouvement_precedente(phase):
    saison, annee = phase[0], int(phase[1:5])
    return "S%dM" % annee if saison == "F" else "F%dM" % (annee - 1)


# ---------------------------------------------------------------------------
# Appel à Claude : plafond, relevé de la consigne et de la sortie brute
# ---------------------------------------------------------------------------

class Appels:
    """Remplace `subprocess` dans le module du bot : compte, plafonne et garde la consigne et la sortie."""

    def __init__(self, mode, compteur):
        self.mode, self.compteur, self.dernier, self.simulation = mode, compteur, {}, None

    def __getattr__(self, nom):  # tout le reste du module subprocess (exceptions comprises)
        return getattr(subprocess, nom)

    def lire_compteur(self):
        if self.compteur.exists():
            return int(json.loads(self.compteur.read_text())["appels"])
        return 0

    def run(self, cmd, **kwargs):
        self.dernier = {"cmd": list(cmd)}
        if self.mode == "dry":
            raise ASec()
        if self.mode == "simule":
            stdout = self.simulation()
        else:
            fait = self.lire_compteur()
            if fait >= PLAFOND:
                raise PlafondAtteint("plafond de %d appels atteint" % PLAFOND)
            # Compté AVANT l'appel : un appel interrompu reste compté.
            commun.ecrire_json(self.compteur, {"appels": fait + 1, "plafond": PLAFOND})
            stdout = subprocess.run(cmd, **kwargs).stdout
        self.dernier["stdout"] = stdout
        return types.SimpleNamespace(stdout=stdout, stderr="", returncode=0)


def reponses_simulees(situation):
    """Sorties fabriquées de la CLI, pour l'essai de la chaîne de relevés (jamais comptées)."""
    e, n, tiers = situation.get("E") or "A PAR H", situation.get("N") or "A PAR - BUR", situation.get("tiers") or "NOBODY"
    textes = [
        json.dumps({"reply": "ok, deal", "sincere": [n], "betray": [e]}),
        "This isn't an agent-messaging task, here is my answer anyway",
        json.dumps({"reply": "fine", "sincere": [n], "betray": "not a list"}),
        json.dumps({"reply": "sure {but} I told %s about %s" % (tiers.title(), e), "sincere": [n]}),
        json.dumps({"reply": None, "sincere": [n], "betray": []}),
        json.dumps({"reply": "will do", "sincere": [n.replace(" - ", "-")], "betray": [e.lower()]}),
    ]
    sorties = [json.dumps({"result": t, "is_error": False, "modelUsage": {"modele-simule": {}}, "total_cost_usd": 0.0}) for t in textes]
    sorties.append(json.dumps({"result": "API Error: simulated", "is_error": True}))
    etat = {"i": 0}

    def suivante():
        etat["i"] += 1
        return sorties[(etat["i"] - 1) % len(sorties)]

    return suivante


def version_cli():
    try:
        r = subprocess.run(["claude", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return r.stdout.decode().strip()
    except Exception as e:
        return "indisponible (%s)" % type(e).__name__


# ---------------------------------------------------------------------------
# Un tirage
# ---------------------------------------------------------------------------

def aplatir(texte):
    return " ".join(str(texte).upper().split())


def fuites(reply, situation):
    """Présence, dans le message visible, de ce qui ne doit pas y être (critère (e))."""
    if reply is None:
        return {}
    bas = reply.lower()
    f = {"sincere": "sincere" in bas, "betray": "betray" in bas, "accolade": "{" in reply or "}" in reply}
    if situation.get("tiers"):
        e = aplatir(situation["E"])
        f["ordre_promis_au_tiers"] = e in aplatir(reply) or e.replace(" - ", "-") in aplatir(reply)
        f["nom_du_tiers"] = situation["tiers"].lower() in bas
    return f


def tirer(version, situation, modules, contexte, appels):
    bot, _pc, _pe = modules[version]
    p, x, phase, gid = contexte["puissance"], contexte["interlocuteur"], contexte["phase"], contexte["game_id"]
    entree = contexte["entree"]
    by_recipient = copy.deepcopy(situation["by_recipient"])
    affichees = [o for ordres in by_recipient.values() for o in ordres]

    arguments = {"plan_section": bot.build_plan_section(gid, phase, p), "trust_section": ""}
    if version == "avant":
        arguments["commitments_section"] = bot.build_commitments_section(by_recipient, x)
    else:
        arguments["commitments_section"] = bot.build_commitments_section(
            by_recipient, x, entree.get("plans"), entree.get("order_values"),
            candidates=entree.get("candidates"), search=entree.get("search"),
        )
        arguments["own_record_section"] = bot.build_own_record_section(situation.get("own_record") or {}, x)

    r = {"situation": situation["nom"], "version": version, "appel_echoue": False}
    appels.simulation = contexte["simulations"][situation["nom"]]
    appels.dernier = {}
    try:
        rendu = bot.generate_reply(p, x, contexte["plateau"], phase, situation["message"], **arguments)
    except ASec:
        rendu = None
    except PlafondAtteint:
        raise
    except Exception as e:  # CLI en erreur, délai dépassé : compté au plafond, sans donnée
        rendu = None
        r.update({"appel_echoue": True, "erreur": "%s: %s" % (type(e).__name__, str(e)[:300])})

    cmd = appels.dernier.get("cmd") or []
    systeme = cmd[cmd.index("--system-prompt") + 1] if "--system-prompt" in cmd else ""
    utilisateur = cmd[2] if len(cmd) > 2 else ""
    r.update({
        "taille_consigne_systeme": len(systeme), "taille_consigne_utilisateur": len(utilisateur),
        "modele_demande": cmd[cmd.index("--model") + 1] if "--model" in cmd else None,
        "promesses_affichees": affichees,
    })
    if appels.mode == "dry":
        r["consigne_systeme"], r["consigne_utilisateur"] = systeme, utilisateur
        return r

    stdout = appels.dernier.get("stdout")
    try:
        enveloppe = json.loads(stdout)
        r["modele_servi"] = sorted((enveloppe.get("modelUsage") or {}).keys()) or None
        r["cout_usd"], r["duree_ms"] = enveloppe.get("total_cost_usd"), enveloppe.get("duration_ms")
    except Exception:
        r["modele_servi"] = None
    if rendu is None:
        return r

    # Sortie brute relue comme le fait la version : JSON lisible ou non, champs tels qu'émis.
    texte = bot._claude_result_text(stdout)
    obj = bot._parse_reply_json(texte)
    r["sortie_brute"] = texte
    r["json_lisible"] = obj is not None
    brut = obj or {}
    r["betray_brut"] = brut.get("betray")
    r["betray_brut_present"] = "betray" in brut
    r["betray_brut_est_une_liste"] = isinstance(brut.get("betray"), list) if "betray" in brut else None
    r["sincere_brut"] = brut.get("sincere")

    reply, sincere = rendu[0], list(rendu[1])
    betray = list(rendu[2]) if len(rendu) > 2 else []
    r["betray_rendu_est_une_liste"] = isinstance(rendu[2], list) if len(rendu) > 2 else None
    r["reply_nul"] = reply == bot.NO_REPLY_TOKEN
    r["reply"] = None if r["reply_nul"] else reply
    r["sincere"], r["betray"] = sincere, betray

    # Labels émis (champ brut) : reproduisent-ils exactement une promesse affichée ?
    emis = [o for o in brut.get("betray", []) if isinstance(o, str)] if isinstance(brut.get("betray"), list) else []
    if version == "avant":
        emis = []  # l'ancien contrat de sortie n'a pas de label : un champ "betray" n'y a aucun effet
    r["labels_emis"] = emis
    r["labels_exacts"] = [o for o in emis if o in affichees]
    r["labels_exacts_apres_normalisation"] = [o for o in emis if commun.normalize_order_spacing(o) in affichees]

    # Ordre contraire à une promesse affichée, sans label pour elle (sur la liste sincere émise).
    # Compté seulement quand un message part : sans reply, les deux versions n'envoient rien.
    emis_sinceres = [commun.normalize_order_spacing(o) for o in (brut.get("sincere") or []) if isinstance(o, str)]
    labels = [commun.normalize_order_spacing(o) for o in emis]
    contraires = [
        (o, e) for o in emis_sinceres for e in affichees
        if not r["reply_nul"] and commun.get_unit_location(o) == commun.get_unit_location(e) and o != e
    ]
    r["ordres_contraires"] = [list(c) for c in contraires]
    r["ordre_contraire_sans_label"] = any(e not in labels for _o, e in contraires)

    # Verdict de _reject_contradictions de la version, sur une copie de l'état fabriqué.
    if contexte["game"] is not None:
        legaux = bot.legal_commitments(contexte["game"], p, sincere)
    else:
        legaux = [commun.normalize_order_spacing(o) for o in sincere]  # à sec : légalité non contrôlée
    r["sincere_illegaux"] = [o for o in sincere if o not in legaux]
    if version == "avant":
        accepte, retrograde, remplace = bot._reject_contradictions(legaux, by_recipient, entree.get("plans"))
        verdict = {"accepted": accepte, "demoted": retrograde, "superseded": remplace}
    else:
        accepte, retrograde, remplace, conflit, ignore = bot._reject_contradictions(
            legaux, by_recipient, entree.get("plans"), betray=betray, order_values=entree.get("order_values"),
            candidates=entree.get("candidates"), search=entree.get("search"),
        )
        verdict = {"accepted": accepte, "demoted": retrograde, "superseded": remplace,
                   "conflicting": conflit, "ignored": ignore}
    r["verdict"] = json.loads(json.dumps(verdict))
    r["fuites"] = fuites(r["reply"], situation)
    return r


# ---------------------------------------------------------------------------
# Résumé
# ---------------------------------------------------------------------------

def resumer(tirages, cli):
    lignes, cases = [], {}
    for t in tirages:
        cases.setdefault((t["situation"], t["version"]), []).append(t)

    def compte(ts, f):
        return sum(1 for t in ts if f(t))

    lignes.append("RÉSUMÉ M3 -- CLI : %s. Vingt tirages ne distinguent que de gros écarts (exigence 2.10)." % cli)
    for (s, v) in sorted(cases):
        ts = cases[(s, v)]
        ok = [t for t in ts if not t["appel_echoue"]]
        lus = [t for t in ok if t["json_lisible"]]
        raisons = {}
        for t in lus:
            for d in t["verdict"].get("demoted", []):
                cle = d[2] if len(d) > 2 else "demoted"
                raisons[cle] = raisons.get(cle, 0) + 1
            for label, raison in t["verdict"].get("ignored", []):
                raisons["ignored:" + raison] = raisons.get("ignored:" + raison, 0) + 1
        lignes.append(
            "%s %-5s : %d tirages, %d appels en échec, JSON illisible %d, reply nul %d, sincere non vide %d, "
            "tirages avec label %d (labels émis %d, exacts %d), ordre contraire sans label %d, "
            "trahisons acceptées (superseded) %d, refus %s, fuites %d, consigne système %s car., utilisateur %s car., modèle servi %s"
            % (s, v, len(ts), len(ts) - len(ok), compte(ok, lambda t: not t["json_lisible"]),
               compte(lus, lambda t: t["reply_nul"]), compte(lus, lambda t: t["sincere"]),
               compte(lus, lambda t: t["labels_emis"]), sum(len(t["labels_emis"]) for t in lus),
               sum(len(t["labels_exacts"]) for t in lus), compte(lus, lambda t: t["ordre_contraire_sans_label"]),
               compte(lus, lambda t: t["verdict"].get("superseded")), raisons or "aucun",
               compte(lus, lambda t: any(t["fuites"].values())),
               sorted(set(t["taille_consigne_systeme"] for t in ts)), sorted(set(t["taille_consigne_utilisateur"] for t in ts)),
               sorted(set(m for t in ok for m in (t.get("modele_servi") or ["non donné"]))))
        )

    def groupe(situations, version):
        return [t for s in situations for t in cases.get((s, version), []) if not t["appel_echoue"]]

    lignes.append("CRITÈRES DE L'ISSUE #17")
    av, ap = groupe(("S1", "S2", "S3"), "avant"), groupe(("S1", "S2", "S3"), "apres")
    ill_av, ill_ap = compte(av, lambda t: not t["json_lisible"]), compte(ap, lambda t: not t["json_lisible"])
    taux = lambda k, n: (float(k) / n) if n else None  # noqa: E731
    tous_ap = groupe(SITUATIONS, "apres")
    pas_liste = compte(tous_ap, lambda t: t["json_lisible"] and t["betray_brut_present"] and not t["betray_brut_est_une_liste"])
    absent = compte(tous_ap, lambda t: t["json_lisible"] and not t["betray_brut_present"])
    rendu_pas_liste = compte(tous_ap, lambda t: t["json_lisible"] and t["betray_rendu_est_une_liste"] is not True)
    b = (taux(ill_ap, len(ap)) is not None and taux(ill_av, len(av)) is not None
         and taux(ill_ap, len(ap)) <= taux(ill_av, len(av)) and rendu_pas_liste == 0)
    lignes.append(
        "(b) JSON illisible S1-S3 : avant %d / %d, après %d / %d ; `betray` rendu par generate_reply pas une liste : %d ; "
        "champ brut absent : %d, présent mais pas une liste : %d (sur %d sorties « après ») -> %s"
        % (ill_av, len(av), ill_ap, len(ap), rendu_pas_liste, absent, pas_liste, len(tous_ap), "TENU" if b else "NON TENU"))
    s1 = groupe(("S1",), "apres")
    c = compte(s1, lambda t: t["json_lisible"] and t["labels_emis"])
    lignes.append("(c) S1 après : %d tirage(s) avec label sur %d -> %s" % (c, len(s1), "TENU" if s1 and c == 0 else "NON TENU"))
    conflit = [t for t in groupe(("S2", "S3", "S4"), "apres") if t["json_lisible"]]
    emis, exacts = sum(len(t["labels_emis"]) for t in conflit), sum(len(t["labels_exacts"]) for t in conflit)
    d = "non évaluable (aucun label émis)" if not emis else ("TENU" if exacts * 20 >= emis * 18 else "NON TENU")
    lignes.append("(d) S2-S4 après : %d label(s) exact(s) sur %d émis (seuil 18 / 20) -> %s" % (exacts, emis, d))
    for s in ("S2", "S3", "S4"):
        for v in VERSIONS[s]:
            g = [t for t in groupe((s,), v) if t["json_lisible"]]
            lignes.append("    %s %s : ordre contraire sans label %d / %d" % (s, v, compte(g, lambda t: t["ordre_contraire_sans_label"]), len(g)))
    for v in ("avant", "apres"):
        g = [t for t in groupe(SITUATIONS, v) if t["json_lisible"] and not t["reply_nul"]]
        par_type = {}
        for t in g:
            for k, vrai in t["fuites"].items():
                par_type[k] = par_type.get(k, 0) + (1 if vrai else 0)
        n_fuites = compte(g, lambda t: any(t["fuites"].values()))
        suffixe = (" -> %s" % ("TENU" if g and n_fuites == 0 else "NON TENU")) if v == "apres" else ""
        lignes.append("(e) %s : %d reply avec fuite sur %d (%s)%s" % (v, n_fuites, len(g), par_type, suffixe))
    for s in SITUATIONS:
        tailles = {v: sorted(set(t["taille_consigne_systeme"] for t in cases.get((s, v), []))) for v in VERSIONS[s]}
        lignes.append("(f) %s : taille de la consigne système (caractères) %s" % (s, tailles))
    lignes.append("La détection des fuites est textuelle (nom de la puissance tierce, ordre promis tel qu'écrit) : "
                  "relire les `reply` du fichier de tirages pour les paraphrases.")
    return lignes


# ---------------------------------------------------------------------------
# Déroulé
# ---------------------------------------------------------------------------

def lire_entree(fichiers, tirage, recherche, puissance):
    for fichier in fichiers:
        for r in commun.lire_lignes(fichier):
            if r.get("recherche") == recherche and r.get("tirage") == tirage and (puissance is None or r["puissance"] == puissance):
                return r, fichier
    raise SystemExit("aucun relevé (recherche %s, tirage %s, puissance %s) dans %s" % (recherche, tirage, puissance, fichiers))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entree", nargs="+", required=True, help="relevés JSON lignes de M1")
    p.add_argument("--tirage", type=int, default=0)
    p.add_argument("--recherche", default="A")
    p.add_argument("--puissance", help="puissance P (défaut : celle du premier relevé trouvé)")
    p.add_argument("--interlocuteur", help="X")
    p.add_argument("--tiers", help="T")
    p.add_argument("--s2", help='couple imposé "E|N" pour S2 (et S1, S4)')
    p.add_argument("--s3", help='couple imposé "E|N" pour S3')
    p.add_argument("--n", type=int, default=TIRAGES, help="tirages par case (défaut 20)")
    p.add_argument("--lister", action="store_true", help="imprime les couples (E, N) de chaque relevé A et s'arrête")
    p.add_argument("--dry-run", action="store_true", help="construit et imprime les consignes, sans appeler Claude")
    p.add_argument("--simuler", action="store_true", help="réponses fabriquées au lieu de Claude (essai de la chaîne)")
    p.add_argument("--refaire-echecs", action="store_true", help="retire les tirages en échec d'appel et les refait (dans le plafond)")
    p.add_argument("--versions", help="dossier contenant avant/ et apres/ (défaut : /tmp/mesure, sinon le dossier du script)")
    args = p.parse_args()
    if args.n > TIRAGES:
        raise SystemExit("REFUS : --n %d dépasse %d tirages par case (plafond de %d appels)" % (args.n, TIRAGES, PLAFOND))

    reel = commun.cicero_present()
    essai = args.dry_run or args.simuler or args.lister
    if not reel and not essai:
        raise SystemExit("REFUS : hors du conteneur, seuls --lister, --dry-run et --simuler sont possibles")
    if reel:
        sys.path.insert(0, "/opt/cicero")
    else:
        commun.installer_doublures()

    travail = commun.MESURE_DIR / ("travail" if not essai else "travail_sec")
    resultats = commun.MESURE_DIR / ("resultats" if not essai else "resultats_sec")
    os.environ["CICERO_PLANS_FILE"] = str(travail / "m3_current_plans.json")
    os.environ["PSEUDO_COMMITMENTS_FILE"] = str(travail / "m3_pseudo_commitments.json")
    commun.refuser_volume_production(travail, resultats)

    racine = Path(args.versions) if args.versions else (Path("/tmp/mesure") if Path("/tmp/mesure/avant").is_dir() else commun.ICI)
    empreintes = {v: {f.name: commun.sha256(f) for f in sorted((racine / v).glob("*.py"))} for v in ("avant", "apres")}

    if args.lister:
        _bot, pc, _pe = charger_version("apres", racine / "apres")
        for fichier in args.entree:
            for r in commun.lire_lignes(fichier):
                if r.get("recherche") != args.recherche:
                    continue
                s2, s3 = couples(r.get("entree") or {}, pc, _bot.COMMITMENT_SWITCH_MARGIN)
                print("%s tirage %s %s : %d couple(s) S2, %d couple(s) S3" % (r["puissance"], r["tirage"], fichier, len(s2), len(s3)))
                for nom, liste in (("S2", s2[:5]), ("S3", s3[:5])):
                    for c in liste:
                        print("   %s %s" % (nom, json.dumps(c, ensure_ascii=False)))
        return

    releve, fichier = lire_entree(args.entree, args.tirage, args.recherche, args.puissance and args.puissance.upper())
    entree, puissance, phase, gid = releve["entree"], releve["puissance"], releve["phase"], releve["game_id"]
    commun.ecrire_json(travail / "m3_current_plans.json", {str(gid): {phase: {puissance: entree}}})
    commun.ecrire_json(travail / "m3_pseudo_commitments.json", {})
    modules = {v: charger_version(v, racine / v) for v in ("avant", "apres")}
    bot_apres, pc_apres, _ = modules["apres"]
    marge = bot_apres.COMMITMENT_SWITCH_MARGIN

    autres = [x for x in commun.POWERS if x != puissance]
    x = (args.interlocuteur or autres[0]).upper()
    t = (args.tiers or [a for a in autres if a != x][0]).upper()
    if len({puissance, x, t}) != 3 or x not in commun.POWERS or t not in commun.POWERS:
        raise SystemExit("P, X et T doivent être trois puissances distinctes : %s %s %s" % (puissance, x, t))

    s2, s3 = couples(entree, pc_apres, marge)
    ov = entree.get("order_values") or {}
    if args.s2:
        e2, n2 = couple_impose(args.s2)
    elif s2:
        e2, n2 = s2[0]["E"], s2[0]["N"]
    else:
        raise SystemExit("la table de %s n'offre aucun couple S2 (gain > %s et N en tête après renfort) : autre puissance, ou --s2" % (puissance, marge))
    if args.s3:
        e3, n3 = couple_impose(args.s3)
    elif s3:
        e3, n3 = s3[0]["E"], s3[0]["N"]
    else:
        raise SystemExit("la table de %s n'offre aucun couple S3 (gain <= %s) : autre puissance, ou --s3" % (puissance, marge))
    prefere = entree["plans"][0]["orders"]
    autre = [o for o in prefere if commun.get_unit_location(o) != commun.get_unit_location(e2)]
    if not autre:
        raise SystemExit("S1 : %s n'a qu'une unité, pas d'autre unité dont parler" % puissance)
    o1 = autre[0]

    # Plateau et partie : lecture seule du statut, une fois.
    game, plateau, promis5, joue5 = None, "(board state not available in this dry run)", "A PAR - BUR", "A PAR - PIC"
    phase_passee = phase_de_mouvement_precedente(phase)
    if reel:
        from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game
        from parlai_diplomacy.utils.game2seq.format_helpers.state import StateFlattener

        courante = webdip_state_to_game(get_status_json(commun.trouver_contexte(gid, puissance)))
        game = courante.rolled_back_to_phase_start(phase)
        plateau = StateFlattener(version=2).flatten_state(game.get_state(), phase)
        joues = [ph.orders.get(puissance, []) for ph in courante.get_phase_history() if ph.name == phase_passee]
        mouvements = [o for o in (joues[0] if joues else []) if not o.endswith(" H")]
        if not mouvements:
            raise SystemExit("S5 : aucun ordre de %s autre qu'un maintien en %s" % (puissance, phase_passee))
        joue5 = mouvements[0]
        promis5 = " ".join(joue5.split()[:2]) + " H"  # promesse fabriquée : le maintien de l'unité qui a bougé

    situations = [
        {"nom": "S1", "by_recipient": {t: [e2]}, "E": e2, "N": None, "tiers": t,
         "message": MESSAGES["S1"].format(unite=commun.get_unit_location(o1), O=o1)},
        {"nom": "S2", "by_recipient": {t: [e2]}, "E": e2, "N": n2, "tiers": t, "message": MESSAGES["S2"].format(N=n2)},
        {"nom": "S3", "by_recipient": {t: [e3]}, "E": e3, "N": n3, "tiers": t, "message": MESSAGES["S3"].format(N=n3)},
        {"nom": "S4", "by_recipient": {x: [e2]}, "E": e2, "N": n2, "tiers": None, "message": MESSAGES["S4"].format(E=e2, N=n2)},
        {"nom": "S5", "by_recipient": {}, "E": None, "N": None, "tiers": None,
         "own_record": {x: {"kept": 0, "broken": 1, "examples": [{"phase": phase_passee, "promised": promis5, "actual": joue5}]}},
         "message": MESSAGES["S5"].format(promis=promis5, joue=joue5)},
    ]

    print("M3 -- P = %s, X = %s, T = %s, partie %s, phase %s, entrée : %s (tirage %s, recherche %s)"
          % (puissance, x, t, gid, phase, fichier, args.tirage, args.recherche))
    print("marge = %s ; search = %s ; %d actions candidates" % (marge, entree.get("search"), len(entree.get("candidates") or [])))
    for nom, e, n in (("S2 (et S1, S4)", e2, n2), ("S3", e3, n3)):
        tete = pc_apres.engine_head_action(entree.get("candidates"), entree.get("search"), [n])
        print("couple %s : E = %r (valeur %s), N = %r (valeur %s), gain = %s, N en tête après renfort : %s"
              % (nom, e, ov.get(e), n, ov.get(n), round(ov[n] - ov[e], 5) if e in ov and n in ov else None,
                 tete is not None and n in tete))
    for s in situations:
        print("%s : promesses %s ; message de %s : %r" % (s["nom"], s["by_recipient"], x, s["message"]))
        if s.get("own_record"):
            print("     bilan fabriqué : %s" % s["own_record"])
    for v in ("avant", "apres"):
        print("version %s : %s" % (v, empreintes[v]))

    configuration = {"puissance": puissance, "X": x, "T": t, "entree": entree, "situations": situations,
                     "empreintes": empreintes, "plateau": plateau}
    empreinte = hashlib.sha1(json.dumps(configuration, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    suffixe = "_simule" if args.simuler else ""
    f_tirages = resultats / ("m3_tirages_%s%s.jsonl" % (empreinte, suffixe))
    f_compteur = resultats / "m3_compteur_appels.json"

    mode = "dry" if args.dry_run else ("simule" if args.simuler else "reel")
    appels = Appels(mode, f_compteur)
    for bot, _pc, _pe in modules.values():
        bot.subprocess = appels
    contexte = {"puissance": puissance, "interlocuteur": x, "phase": phase, "game_id": gid, "entree": entree,
                "plateau": plateau, "game": game,
                "simulations": {s["nom"]: reponses_simulees(s) for s in situations}}

    if args.dry_run:
        for s in situations:
            for v in VERSIONS[s["nom"]]:
                r = tirer(v, s, modules, contexte, appels)
                print("=" * 100)
                print("%s %s -- consigne système : %d caractères ; consigne utilisateur : %d caractères ; modèle demandé : %s"
                      % (s["nom"], v, r["taille_consigne_systeme"], r["taille_consigne_utilisateur"], r["modele_demande"]))
                print("-" * 100)
                print(r["consigne_systeme"])
                print("-" * 100)
                print(r["consigne_utilisateur"])
        print("=" * 100)
        print("--dry-run : %d appels prévus pour --n %d, aucun fait" % (args.n * sum(len(v) for v in VERSIONS.values()), args.n))
        return

    cli = version_cli()
    faits = commun.lire_lignes(f_tirages)
    if args.refaire_echecs and any(t["appel_echoue"] for t in faits):
        faits = [t for t in faits if not t["appel_echoue"]]
        f_tirages.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in faits))
    deja = set((t["situation"], t["version"], t["tirage"]) for t in faits)
    plan = []
    for i in range(args.n):
        for s in situations:
            ordre = VERSIONS[s["nom"]] if i % 2 == 0 else VERSIONS[s["nom"]][::-1]  # alternance avant / après
            plan.extend((i, s, v) for v in ordre if (s["nom"], v, i) not in deja)
    restant = PLAFOND - appels.lire_compteur() if mode == "reel" else len(plan)
    print("CLI : %s ; tirages déjà faits : %d ; appels à faire : %d ; appels restants sous le plafond de %d : %d"
          % (cli, len(deja), len(plan), PLAFOND, restant))
    if len(plan) > restant:
        raise SystemExit("REFUS : %d appels à faire, %d restants sous le plafond de %d" % (len(plan), restant, PLAFOND))
    print("tirages dans %s" % f_tirages, flush=True)

    echecs = 0
    for i, s, v in plan:
        r = tirer(v, s, modules, contexte, appels)
        r.update({"tirage": i, "cli": cli, "empreinte": empreinte, "simule": args.simuler})
        commun.ajouter_ligne(f_tirages, r)
        echecs = echecs + 1 if r["appel_echoue"] else 0
        print("  %s %-5s tirage %2d : %s" % (
            s["nom"], v, i,
            "ÉCHEC %s" % r.get("erreur") if r["appel_echoue"] else
            "JSON illisible" if not r["json_lisible"] else
            "reply %s ; sincere %s ; betray %s ; verdict %s"
            % ("nul" if r["reply_nul"] else repr(r["reply"][:80]), r["sincere"], r["betray"],
               {k: val for k, val in r["verdict"].items() if val})), flush=True)
        if echecs >= ECHECS_DE_SUITE_MAX and mode == "reel":
            print("ARRÊT : %d appels en échec de suite ; relancer la même commande reprend là où elle s'est arrêtée" % echecs)
            break

    lignes = resumer(commun.lire_lignes(f_tirages), cli)
    print("\n".join(lignes))
    commun.ecrire_json(resultats / ("m3_resume_%s%s.json" % (empreinte, suffixe)),
                       {"configuration": configuration, "cli": cli, "resume": lignes})
    if mode == "reel":
        print("compteur : %d appels sur %d" % (appels.lire_compteur(), PLAFOND))


if __name__ == "__main__":
    main()
