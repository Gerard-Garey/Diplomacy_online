"""M1 -- rejeu du moteur sur une position de la partie, avec engagements fabriqués.

À lancer dans un conteneur éphémère de l'image cicero-webdip:latest, le
conteneur cicero-orders étant arrêté (GPU de 8 Go) :

    python /mesure/rejeu_moteur.py GAMEID PHASE PUISSANCE N --engagements <fichier.json|auto:prefere|auto:alternative>
    python /mesure/rejeu_moteur.py GAMEID PHASE PUISSANCE N --incremental

Par tirage : lecture seule du statut de la partie, rolled_back_to_phase_start,
recherche A sans engagement, puis recherche B avec les engagements (fichier
PSEUDO_COMMITMENTS_FILE hors du volume de production), déclenchée par un message
ajouté à la copie en mémoire du jeu (rien n'est envoyé au site). --incremental :
la promesse est un ordre déjà tenu par l'action de tête de A, les messages
viennent d'un tiers et sont adressés à tous, et une recherche C suit B.

Relevés : une ligne JSON par recherche dans <MESURE_DIR>/resultats/.
--dry-run : aucun site, aucun moteur ; une doublure du moteur (table fabriquée,
vraies fonctions boosted_policy et export_plans du dépôt) fait tourner toute la
chaîne de relevés et de contrôles. --doublure-compose y simule le défaut du
renfort composé (M33), pour vérifier que le contrôle le voit.
"""
import argparse
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Avant tout chargement : commun.charger lit des fichiers de cicero/overlay, où un .pyc
# passerait pour un fichier d'overlay (outils/exporter_patchs.sh --verifier, install.sh ; #27).
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import commun  # noqa: E402

AGENT_CFG = "/opt/cicero/conf/common/agents/cicero_no_dialogue.prototxt"
MESSAGE_DIRECT = "Hello, what are your plans for this turn?"
MESSAGE_A_TOUS = "Good luck to everyone this turn."
TOLERANCE = 1e-6  # écart relatif admis entre deux probabilités exportées (6 chiffres significatifs)


class Journal(logging.Handler):
    """Garde les lignes de journal de plan_export, pseudo_commitments et de la mise à jour incrémentale."""

    MOTIFS = ("plan_export:", "pseudo_commitments:", "Incremental update")

    def __init__(self):
        logging.Handler.__init__(self, level=logging.INFO)
        self.lignes = []

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return
        if any(m in message for m in self.MOTIFS):
            self.lignes.append("%s %s" % (record.levelname, message))

    def vider(self):
        lignes, self.lignes = self.lignes, []
        return lignes


class SondeGPU(threading.Thread):
    """Mémoire GPU utilisée (Mio), relevée chaque seconde par nvidia-smi : maximum sur la recherche."""

    COMMANDE = ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]

    def __init__(self):
        threading.Thread.__init__(self, daemon=True)
        self.fin = threading.Event()
        self.max_utilise, self.total, self.erreur = None, None, None

    @classmethod
    def lire(cls):
        sortie = subprocess.run(cls.COMMANDE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        utilise, total = sortie.stdout.decode().strip().splitlines()[0].split(",")
        return int(utilise), int(total)

    def run(self):
        while not self.fin.is_set():
            try:
                utilise, self.total = self.lire()
                self.max_utilise = max(self.max_utilise or 0, utilise)
            except Exception as e:  # nvidia-smi absent du conteneur : relevé vide, pas d'arrêt
                self.erreur = "%s: %s" % (type(e).__name__, e)
                return
            self.fin.wait(1.0)

    def arreter(self):
        self.fin.set()
        self.join(timeout=15)
        return {"max_utilise_mio": self.max_utilise, "total_mio": self.total, "erreur": self.erreur}


# ---------------------------------------------------------------------------
# Moteurs
# ---------------------------------------------------------------------------

class MoteurReel:
    def __init__(self, game_id, phase, puissance):
        import heyhi
        from fairdiplomacy.agents import build_agent_from_cfg
        from fairdiplomacy.utils import plan_export, pseudo_commitments

        self.game_id, self.phase, self.puissance = game_id, phase, puissance
        self.pc, self.pe = pseudo_commitments, plan_export
        self.ctx = commun.trouver_contexte(game_id, puissance)
        self.agent = build_agent_from_cfg(heyhi.load_config(AGENT_CFG))
        self.game, self.player, self.horloge = None, None, int(time.time())

    def nouvelle_partie(self):
        from fairdiplomacy.agents.player import Player
        from fairdiplomacy_external.webdip_api import get_status_json, webdip_state_to_game

        statut = get_status_json(self.ctx)  # GET game/status : lecture seule
        if statut is None:
            raise SystemExit("statut de la partie %s illisible" % self.game_id)
        releve = {k: statut.get(k) for k in ("gameID", "turn", "phase", "gameOver", "processStatus")}
        courante = webdip_state_to_game(statut)
        releve["phase_courante"] = courante.current_short_phase
        self.game = courante.rolled_back_to_phase_start(self.phase)
        releve["game_id_conserve_par_le_retour_arriere"] = self.game.get_metadata("game_id") == str(self.game_id)
        self.game.set_metadata("game_id", str(self.game_id))
        releve["messages_dans_la_copie"] = len(self.game.messages)
        self.player = Player(self.agent, self.puissance)
        return releve

    def promesses_effectives(self, ordres):
        """Ce que le moteur retient des engagements du fichier (légalité, conflits)."""
        return self.pc.resolve_commitment_conflicts(self.pc.legal_commitments(self.game, self.puissance, ordres))

    def ajouter_message(self, expediteur, destinataire, texte):
        from fairdiplomacy.typedefs import Timestamp

        self.horloge += 1
        self.game.add_message(
            expediteur, destinataire, texte,
            time_sent=Timestamp.from_seconds(self.horloge), increment_on_collision=True,
        )
        return len(self.game.messages)

    def recherche(self):
        action = self.player.get_orders(self.game)
        resultat = self.player.state.get_last_search_result(self.game)
        politique = None
        if resultat is not None:
            # Après la recherche, le résultat porte la politique d'AVANT renfort (M33).
            politique = [[list(a), float(p)] for a, p in resultat.get_bp_policy()[self.puissance].items()]
        return list(action), politique


class MoteurDoublure:
    """Essai à sec : table fabriquée, vraies fonctions du dépôt (boosted_policy, export_plans)."""

    # Actions et valeurs : plans de ITALY, partie 3, S1902M (current_plans.json de production).
    # Probabilités et lambda : FABRIQUÉS pour l'essai à sec.
    TABLE = [
        (("A TUN H", "F ION - AEG", "F NAP - ION", "A VEN H"), 0.17583, 0.30),
        (("A TUN H", "F ION - AEG", "F NAP - ION", "A VEN S A TRI"), 0.17103, 0.25),
        (("A TUN H", "F ION - EAS", "F NAP - ION", "A VEN H"), 0.13124, 0.15),
        (("A TUN H", "F ION - EAS", "F NAP - ION", "A VEN S A TRI"), 0.13158, 0.12),
        (("A TUN H", "F ION - AEG", "F NAP - ION", "A VEN - PIE"), 0.15881, 0.10),
        (("A TUN H", "F ION - EAS", "F NAP - ION", "A VEN - PIE"), 0.12204, 0.08),
    ]
    LAMBDA, BOOST = 1e-2, 3.0

    def __init__(self, game_id, phase, puissance, pc, pe, compose=False):
        self.game_id, self.phase, self.puissance = game_id, phase, puissance
        self.pc, self.pe, self.compose = pc, pe, compose
        self.politique, self.messages = None, 0

    def nouvelle_partie(self):
        self.politique = {a: p for a, _v, p in self.TABLE}
        self.messages = 0
        return {"doublure": True}

    def promesses_effectives(self, ordres):
        return list(ordres)

    def ajouter_message(self, expediteur, destinataire, texte):
        self.messages += 1
        return self.messages

    def recherche(self):
        valeurs = {a: v for a, v, _p in self.TABLE}
        avant = dict(self.politique)
        promesses = self.pc.load_commitments(str(self.game_id), self.phase).get(self.puissance, [])
        bp = self.pc.boosted_policy(avant, promesses, self.BOOST) if promesses else dict(avant)
        action_values = sorted(
            ((a, valeurs[a], bp[a], commun.score(valeurs[a], bp[a], self.LAMBDA)) for a in bp),
            key=lambda ligne: -ligne[3],
        )
        self.pe.export_plans(
            str(self.game_id), self.phase, self.puissance, action_values,
            prior_policy=avant, regularize_lambda=self.LAMBDA,
            boost=self.pe.exported_boost(True, self.BOOST), max_prob=self.pc.MAX_COMMITMENT_PROB,
        )
        if self.compose:  # défaut simulé : la politique renforcée sert de départ à la recherche suivante
            self.politique = bp
        return list(action_values[0][0]), [[list(a), float(p)] for a, p in avant.items()]


# ---------------------------------------------------------------------------
# Contrôles (fonctions pures)
# ---------------------------------------------------------------------------

def proches(a, b):
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b), 1e-12)


def controler(entree, politique_avant, action_rendue, promesses, pc, journal):
    """Les quatre contrôles du protocole (§ 1.3, point 2) sur une recherche."""
    c = {}
    entree = entree or {}
    candidates, search, plans = entree.get("candidates"), entree.get("search"), entree.get("plans") or []
    c["entree_exportee"] = bool(entree)
    c["order_values_present"] = isinstance(entree.get("order_values"), dict) and bool(entree.get("order_values"))
    c["candidates_present"] = isinstance(candidates, list) and bool(candidates)
    c["search_present"] = isinstance(search, dict)
    c["avertissement_table_inutilisable"] = any("no usable candidate table" in ligne for ligne in journal)

    # Chaque action de la table est-elle dans la politique d'avant renfort, avec sa probabilité ?
    c["politique_avant_relue"] = politique_avant is not None
    if c["candidates_present"] and politique_avant is not None:
        avant = {tuple(a): p for a, p in politique_avant}
        absentes = [x["orders"] for x in candidates if tuple(x["orders"]) not in avant]
        ecarts = [
            x["orders"] for x in candidates
            if tuple(x["orders"]) in avant and not proches(x["prob"], float("%.6g" % avant[tuple(x["orders"])]))
        ]
        c["actions_hors_politique_avant"] = absentes
        c["probabilites_differentes_de_la_politique_avant"] = ecarts
        c["table_dans_politique_avant"] = not absentes and not ecarts
    else:
        c["table_dans_politique_avant"] = None

    # La tête recalculée par la fonction du bot de dialogue est-elle l'action exportée et l'action rendue ?
    tete_exportee = plans[0]["orders"] if plans else None
    recalculee = pc.engine_head_action(candidates, search, promesses)
    c["tete_exportee"] = tete_exportee
    c["tete_recalculee"] = list(recalculee) if recalculee is not None else None
    c["action_rendue"] = action_rendue
    c["tete_recalculee_egale_exportee"] = recalculee is not None and list(recalculee) == tete_exportee
    c["tete_recalculee_egale_rendue"] = recalculee is not None and list(recalculee) == action_rendue
    c["tete_exportee_egale_rendue"] = tete_exportee == action_rendue
    lignes = pc.rescored_candidates(candidates, search, promesses)
    if lignes:
        scores = sorted((ligne[3] for ligne in lignes), reverse=True)
        # Un écart de l'ordre de l'arrondi de l'export (1e-5) explique une tête différente.
        c["ecart_des_deux_premiers_scores_recalcules"] = scores[0] - scores[1] if len(scores) > 1 else None
    c["promesses_tenues_par_action_rendue"] = commun.tenues(action_rendue or [], promesses)
    return c


def comparer_probabilites(nom_1, entree_1, nom_2, entree_2, promesses):
    """Renfort non composé : candidates[].prob de deux recherches successives, action par action."""
    p1 = {tuple(c["orders"]): c["prob"] for c in (entree_1 or {}).get("candidates") or []}
    p2 = {tuple(c["orders"]): c["prob"] for c in (entree_2 or {}).get("candidates") or []}
    communes = [a for a in p1 if a in p2]
    lignes = [
        {"orders": list(a), "tenues": commun.tenues(a, promesses), nom_1: p1[a], nom_2: p2[a]}
        for a in communes
    ]
    rapports = [p2[a] / p1[a] for a in communes if p1[a] > 0 and commun.tenues(a, promesses) > 0]
    return {
        "recherches": [nom_1, nom_2],
        "tables_presentes": bool(p1) and bool(p2),
        "actions_communes": len(communes),
        "actions_seulement_dans_%s" % nom_1: [list(a) for a in p1 if a not in p2],
        "actions_seulement_dans_%s" % nom_2: [list(a) for a in p2 if a not in p1],
        "egales": bool(communes) and all(proches(p1[a], p2[a]) for a in communes),
        "rapport_max_sur_actions_tenant_la_promesse": max(rapports) if rapports else None,
        "croissantes": bool(rapports) and max(rapports) > 1 + TOLERANCE,
        "lignes": lignes,
    }


# ---------------------------------------------------------------------------
# Déroulé
# ---------------------------------------------------------------------------

def lire_engagements(chemin, game_id, phase, puissance):
    """Liste d'ordres, {PUISSANCE: [ordres]} ou {partie: {phase: {PUISSANCE: [ordres]}}}."""
    donnees = json.loads(Path(chemin).read_text())
    if isinstance(donnees, dict) and str(game_id) in donnees:
        donnees = donnees[str(game_id)].get(phase, {})
    if isinstance(donnees, dict):
        donnees = donnees.get(puissance, [])
    if not isinstance(donnees, list) or not all(isinstance(o, str) for o in donnees):
        raise SystemExit("%s : engagements de %s illisibles" % (chemin, puissance))
    return donnees


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("game_id", type=int)
    p.add_argument("phase")
    p.add_argument("puissance")
    p.add_argument("n_tirages", type=int)
    p.add_argument("--engagements", default="auto:prefere",
                   help="fichier JSON, ou auto:prefere / auto:alternative (choisis sur la recherche A)")
    p.add_argument("--incremental", action="store_true",
                   help="contrôle du renfort non composé : promesse tenue par la tête, messages tiers -> ALL, recherches B et C")
    p.add_argument("--expediteur", help="puissance qui envoie le message déclencheur (défaut : la première autre)")
    p.add_argument("--dry-run", action="store_true", help="doublure du moteur, aucun accès au site ni au GPU")
    p.add_argument("--doublure-compose", action="store_true", help="avec --dry-run : simule le renfort composé")
    args = p.parse_args()
    args.puissance = args.puissance.upper()
    if args.puissance not in commun.POWERS:
        raise SystemExit("puissance inconnue : %s" % args.puissance)
    expediteur = (args.expediteur or [x for x in commun.POWERS if x != args.puissance][0]).upper()

    sec = args.dry_run
    resultats = commun.MESURE_DIR / ("resultats_sec" if sec else "resultats")
    travail = commun.MESURE_DIR / ("travail_sec" if sec else "travail")
    travail.mkdir(parents=True, exist_ok=True)
    # Les deux modules lisent ces variables à l'import : fixées avant, et jamais dans le volume de production.
    f_engagements = Path(os.environ.setdefault("PSEUDO_COMMITMENTS_FILE", str(travail / "pseudo_commitments.json")))
    f_plans = Path(os.environ.setdefault("CICERO_PLANS_FILE", str(travail / "current_plans.json")))
    if sec:
        f_engagements, f_plans = travail / "pseudo_commitments.json", travail / "current_plans.json"
        os.environ["PSEUDO_COMMITMENTS_FILE"], os.environ["CICERO_PLANS_FILE"] = str(f_engagements), str(f_plans)
    commun.refuser_volume_production(f_engagements, f_plans)

    journal = Journal()
    logging.getLogger().addHandler(journal)
    logging.getLogger().setLevel(logging.INFO)

    if sec:
        commun.installer_doublures()
        utils = commun.ICI.parents[1] / "cicero" / "overlay" / "fairdiplomacy" / "utils"
        pc = commun.charger("mesure_pseudo_commitments", utils / "pseudo_commitments.py")
        pe = commun.charger("mesure_plan_export", utils / "plan_export.py")
        moteur = MoteurDoublure(args.game_id, args.phase, args.puissance, pc, pe, compose=args.doublure_compose)
    else:
        if Path("/opt/cicero").is_dir():
            sys.path.insert(0, "/opt/cicero")
        moteur = MoteurReel(args.game_id, args.phase, args.puissance)
        pc, pe = moteur.pc, moteur.pe
    # Les modules chargés écrivent-ils bien là où on l'attend ?
    assert Path(str(pc.COMMITMENTS_FILE)) == f_engagements, (pc.COMMITMENTS_FILE, f_engagements)
    assert Path(str(pe.PLANS_FILE)) == f_plans, (pe.PLANS_FILE, f_plans)
    commun.refuser_volume_production(pc.COMMITMENTS_FILE, pe.PLANS_FILE)
    if journal not in logging.getLogger().handlers:  # heyhi peut refaire la configuration des journaux
        logging.getLogger().addHandler(journal)

    mode = "incremental" if args.incremental else "engagements"
    sortie = resultats / ("m1_%s_%s_%s_%s_%s.jsonl" % (args.game_id, args.phase, args.puissance, mode, commun.horodatage()))
    print("M1 : relevés dans %s" % sortie, flush=True)
    print("     engagements : %s ; plans : %s" % (f_engagements, f_plans), flush=True)

    def rechercher(tirage, nom, promesses, statut, message):
        if f_plans.exists():
            f_plans.unlink()  # une entrée absente après la recherche se voit
        journal.vider()
        sonde = SondeGPU()
        sonde.start()
        debut = time.time()
        action, politique = moteur.recherche()
        duree = time.time() - debut
        gpu = sonde.arreter()
        lignes = journal.vider()
        entree = pe.load_plans(str(args.game_id), args.phase, args.puissance)
        effectives = moteur.promesses_effectives(promesses) if promesses else []
        releve = {
            "mesure": "M1", "mode": mode, "a_sec": sec, "game_id": args.game_id, "phase": args.phase,
            "puissance": args.puissance, "tirage": tirage, "recherche": nom,
            "engagements_du_fichier": promesses, "engagements_retenus_par_le_moteur": effectives,
            "message_declencheur": message, "statut": statut, "duree_s": round(duree, 2), "gpu": gpu,
            "action_rendue": action, "politique_avant_renfort": politique, "entree": entree,
            "controles": controler(entree, politique, action, effectives, pc, lignes), "journal": lignes,
        }
        commun.ajouter_ligne(sortie, releve)
        c = releve["controles"]
        print(
            "  tirage %d recherche %s : %.1f s, GPU max %s Mio ; table %s ; table dans la politique d'avant renfort : %s ; "
            "tête recalculée = exportée : %s, = rendue : %s ; avertissement : %s"
            % (tirage, nom, duree, gpu["max_utilise_mio"],
               "présente" if c["candidates_present"] and c["search_present"] else "ABSENTE",
               c["table_dans_politique_avant"], c["tete_recalculee_egale_exportee"],
               c["tete_recalculee_egale_rendue"], c["avertissement_table_inutilisable"]),
            flush=True,
        )
        return releve

    for tirage in range(args.n_tirages):
        statut = moteur.nouvelle_partie()
        commun.ecrire_json(f_engagements, {})
        a = rechercher(tirage, "A", [], statut, None)

        if args.incremental or args.engagements.startswith("auto:"):
            choix = "prefere" if args.incremental else args.engagements.split(":", 1)[1]
            promesses, raison = commun.choisir_engagements(a["entree"] or {}, choix)
            # En mode incrémental la promesse doit être tenue par l'action réellement rendue.
            if args.incremental and promesses and promesses[0] not in a["action_rendue"]:
                promesses, raison = [a["action_rendue"][0]], "premier ordre de l'action rendue (la tête exportée ne la tient pas)"
        else:
            promesses, raison = lire_engagements(args.engagements, args.game_id, args.phase, args.puissance), "fichier %s" % args.engagements
        print("  tirage %d engagements fabriqués : %s (%s)" % (tirage, promesses, raison), flush=True)
        if not promesses:
            print("  tirage %d : aucun engagement à fabriquer, recherche B non faite" % tirage, flush=True)
            continue
        commun.ecrire_json(f_engagements, {str(args.game_id): {args.phase: {args.puissance: promesses}}})

        if args.incremental:
            message = {"sender": expediteur, "recipient": "ALL", "message": MESSAGE_A_TOUS}
        else:
            message = {"sender": expediteur, "recipient": args.puissance, "message": MESSAGE_DIRECT}
        moteur.ajouter_message(message["sender"], message["recipient"], message["message"])
        b = rechercher(tirage, "B", promesses, statut, message)
        if not args.incremental:
            continue

        moteur.ajouter_message(message["sender"], message["recipient"], message["message"])
        c = rechercher(tirage, "C", promesses, statut, message)
        effectives = b["engagements_retenus_par_le_moteur"]
        for nom_1, r1, nom_2, r2 in (("A", a, "B", b), ("B", b, "C", c)):
            comparaison = comparer_probabilites(nom_1, r1["entree"], nom_2, r2["entree"], effectives)
            commun.ajouter_ligne(sortie, {
                "mesure": "M1", "mode": mode, "a_sec": sec, "tirage": tirage,
                "comparaison": comparaison, "engagements": effectives,
            })
            print(
                "  tirage %d renfort non composé %s -> %s : probabilités égales : %s ; croissantes : %s (rapport max %s)"
                % (tirage, nom_1, nom_2, comparaison["egales"], comparaison["croissantes"],
                   comparaison["rapport_max_sur_actions_tenant_la_promesse"]),
                flush=True,
            )

    print("M1 terminé : %s" % sortie, flush=True)


if __name__ == "__main__":
    main()
