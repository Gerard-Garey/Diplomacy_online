---
status: accepted
date: 2026-10-03
---

# Une promesse n'est remplacée que si Claude déclare la rupture et si le plan qui la réalise vaut nettement plus

Amende l'ADR 0003 (décisions 3 et 5), qu'il ne réécrit pas : l'ADR 0003 reçoit une annotation datée qui renvoie ici. Rédigé par `architect` (routage initial Fable, `docs/agents/routage.md` § 4.1.3) à partir de la spécification d'`expert-cicero` et des décisions du mainteneur consignées dans l'issue #17.

## Contexte

L'ADR 0003, décision 5, pose qu'entre deux engagements contraires sur une même unité « le premier tient, sauf si le plan réalisant le second vaut plus d'une marge (0,02) de mieux ». Le code applique cette règle seul : `_reject_contradictions` (`claude_dialogue_bot.py`, `7372dcf`, lignes 163-214) compare la valeur du meilleur plan contenant chaque ordre et remplace la promesse antérieure dès que `v_new - v_old > COMMITMENT_SWITCH_MARGIN`, sans que Claude ait exprimé l'intention de rompre quoi que ce soit. Un ordre contraire qui vient d'une hallucination ou d'une inattention de Claude produit donc le même effet qu'une rupture délibérée : la promesse antérieure est retirée, la ligne `[betrayal]` est écrite.

Mesure (banc déterministe, `tests/test_promesses.py`, `7372dcf`, `test_ancien_format_repli_sur_les_plans`) : avec les plans connus du banc, un ordre `A PAR - PIC` promis à `GERMANY` après `A PAR - BUR` promis à `ENGLAND` remplace la première promesse avec un gain de 0,8 ; aucune déclaration de Claude n'intervient. Le rappel des promesses de la phase est remis à zéro à chaque phase ; Claude ne connaît pas son propre bilan passé.

Le besoin exprimé par le mainteneur le 2026-10-03 (issue #17) : Claude doit savoir ce qu'il a promis, être encouragé à le tenir, et pouvoir rompre une promesse par une décision déclarée, que le code distingue d'une hallucination.

**Ce que fait Cicero.** Chez Cicero, l'intention (les pseudo-ordres) est recalculée à chaque message par la recherche ; il n'existe aucune déclaration de rupture. L'écart entre deux intentions successives est seulement journalisé : `log_pseudoorder_consistency` (`amont/cicero/fairdiplomacy/agents/searchbot_agent.py:1299-1316`, commit épinglé `e85afedd`), appelée depuis `_get_phase_pseudo_orders` (ligne 1659), calcule la part d'ordres communs entre les anciens et les nouveaux pseudo-ordres et écrit « My old pseudo » / « My new pseudo » dans le journal. Rien n'en découle pour les ordres. Le label `betray` est donc un écart à Cicero (exigence 2.9), justifié ci-dessous.

## Décision

Arrêtée par le mainteneur le 2026-10-03 (issue #17, « Décisions du mainteneur », points 1 à 7).

1. **Deux conditions cumulatives.** Un engagement sincère antérieur de la phase (E) n'est remplacé par un engagement nouveau contraire sur la même unité (N) que si Claude **déclare** la rupture, en inscrivant E dans un champ privé `betray` de sa sortie JSON, **et** si le meilleur plan réalisant N vaut plus que le meilleur plan réalisant E d'au moins `COMMITMENT_SWITCH_MARGIN`. Sinon E tient et N est un bluff (N figure dans `reply`, pas dans les engagements retenus).
2. **Hallucination et refus.** N sans label : E tient, journal `[double-deal]`. Label avec gain insuffisant, ou valeur de N ou de E inconnue : E tient, journal `[betrayal-refused]`. La condition s'ajoute par un ET à la règle de l'ADR 0003 : l'ensemble des remplacements acceptés devient un sous-ensemble de celui d'aujourd'hui.
3. **Effet moteur inchangé.** Un remplacement accepté reste un échange d'engagement : E retiré de `pseudo_commitments.json`, N injecté par `extra_plausible_orders` et renforcé par `apply_commitments_to_policy`. Seule la probabilité bouge, jamais la valeur (ADR 0003, décision 4 ; exigence 2.1).
4. **Le label ne quitte pas le bot de dialogue.** `betray` est lu par `claude_dialogue_bot.py` et n'est écrit ni dans `pseudo_commitments.json` ni dans aucun fichier lu par le moteur. Ce qui atteint le moteur reste la liste d'ordres de `pseudo_commitments.json`, filtrée par `legal_commitments`.
5. **Trahison chez tous les détenteurs.** Quand E avait été promis à plusieurs puissances, un remplacement accepté le retire chez toutes : journal `[betrayal]` par puissance trahie.
6. **Révision.** Remplacer une promesse faite au destinataire même du message suit la même règle (label et marge) ; le journal note `[revision]`, et ce remplacement ne compte pas comme promesse rompue envers lui.
7. **Retrait sans remplacement : refusé** dans cette branche. Un label sans ordre de remplacement pour l'unité est ignoré (`[betrayal-ignored]`), la promesse tient ; les occurrences sont comptées dans la mesure.
8. **Désignation.** Le label reproduit l'ordre promis exact, tel qu'affiché à Claude, normalisé par `normalize_order_spacing` avant comparaison ; un label qui ne correspond à aucune promesse antérieure est ignoré (`[betrayal-ignored]`).
9. **Mémoire des promesses du bot.** Le bot conserve ses propres promesses (`own_promises`, clés `pending` et `record`) dans `claude_dialogue_state.json`, par partie et par puissance, écrites au même point de persistance que `by_recipient`, et résolues contre les ordres réellement joués par la boucle de `verify_promises`, factorisée. La consigne rappelle à Claude ce qu'il a promis à qui dans la phase, le prix d'une rupture (coût du plan), et son bilan passé envers l'interlocuteur courant seulement (exigence 2.8 : rien sur les autres puissances). Une promesse trahie reste comptée pour les puissances trahies : la vérité est l'ordre joué.
10. **Ordre des contrôles.** La table de décision de l'issue #17 (lignes 0 à 8) fait foi pour l'implémentation ; elle s'applique par unité, après `legal_commitments` et après la règle de #2 (plus d'un ordre distinct entrant pour l'unité : aucun retenu, label ignoré).

## Options écartées

- **Label seul décisif** (Claude déclare, le code s'exécute) : rouvrirait la possibilité qu'un bluff ou une hallucination déplace l'engagement sans gain de valeur, c'est-à-dire ce que l'ADR 0003 (option « renforcer sans évaluer ») et l'exigence 2.1 interdisent ; la marge de valeur reste la garde contre le bruit des rollouts.
- **Label transmis au moteur** (par exemple un champ dans `pseudo_commitments.json`) : ouvrirait un second canal *dialogue → moteur*, contraire à l'invariant de `CLAUDE.md` (« le retour ne passe que par `sincere` ») ; le moteur n'a rien à en faire, l'échange d'engagement lui suffit.
- **Pénaliser en probabilité l'ancien ordre** au lieu de le retirer : mécanisme nouveau sans équivalent chez Cicero (exigence 2.9), effet à mesurer sur la politique, et résultat identique dans le cas utile (l'ordre promis n'est plus favorisé) ; le retrait pur et simple est l'extension minimale de l'existant.
- **Retrait sans remplacement** (`betray` sans N) : demande de définir ce qu'un engagement « retiré » signifie pour les puissances qui l'ont reçu et pour la mesure ; reporté hors de cette branche, les occurrences sont comptées pour décider plus tard.
- **Désignation par l'unité seule** (`betray: ["A PAR"]`) : plus court pour Claude, mais ambigu dès qu'une unité a reçu deux promesses successives dans la phase, et impossible à apparier avec le texte affiché ; l'ordre exact est ce que Claude a sous les yeux.
- **Historique de toutes les puissances dans la consigne** (bilan du bot envers chacune) : plus informatif, mais contraire au cloisonnement (exigence 2.8, 2.3) et à la parcimonie : ce que le bot a promis à un tiers ne doit pas pouvoir filtrer dans un message.
- **Annoter l'ADR 0003 sans nouvel ADR** : écarté parce que la décision change deux contrats partagés (sortie JSON de Claude, format de `claude_dialogue_state.json`) et ajoute une condition à une décision citée par l'exigence 2.5 et par l'architecture § 4 ; une annotation ne porte pas ce poids, et l'ADR 0003 reste cité tel quel par ses lecteurs.

## Conséquences

- **Invariants de `CLAUDE.md`.** « Le retour *dialogue → moteur* ne passe que par le champ `sincere` » reste vrai au sens où rien d'autre que les ordres de `pseudo_commitments.json` n'atteint le moteur ; `betray` est un champ privé du bot de dialogue qui ne fait que **restreindre** ce que `sincere` produit. La phrase mérite d'être précisée pour nommer `betray` (texte proposé ci-dessous). « Le moteur décide » et « cloisonnement » inchangés ; exigence 2.9 : l'écart (label sans équivalent chez Cicero) est consigné ici.
- **Contrats partagés.** Sortie JSON de Claude : `{"reply": …, "sincere": […], "betray": […]}`, `betray` absent ou mal formé valant `[]` (aucun ancien message n'est rejeté). Format d'état : nouvelle clé `own_promises` dans `claude_dialogue_state.json` ; un état sans cette clé est lu comme vide. Fichiers : `claude_dialogue_bot.py` (consigne, `_reject_contradictions` ou sa remplaçante, persistance), `plan_export.py` (index `order_values`, décision 7 de l'issue #17), `tests/test_promesses.py`, `tests/mesure_promesses.py`.
- **ADR 0003.** Décision 3 (« Claude rend, avec chaque message, la liste privée de ses engagements sincères. Elle seule est transmise au moteur ») : la sortie comporte désormais aussi `betray`, privé lui aussi et non transmis ; « elle seule est transmise au moteur » reste exact. Décision 5 (« le premier tient, sauf si le plan réalisant le second vaut plus d'une marge (0,02) de mieux ») : la condition devient « sauf si Claude déclare la rupture **et** si le plan réalisant le second vaut plus d'une marge de mieux ». Annotation datée ajoutée en fin de l'ADR 0003 ; rien d'autre n'y change.
- **Résultats changés** : contenu de `sincere` retenu, nombre de lignes `[betrayal]` (en baisse par construction), consigne de Claude (taille et texte). Tableau avant / après unique de la branche (M10), partie déterministe (table de l'issue #17, par appel direct et cycle simulé) et partie répétée (cinq situations, vingt tirages, avant et après : 160 appels réels à Claude, volume approuvé) ; visa du mainteneur avant tout commit.
- **Textes à rouvrir**, par `docwriter` en fin de branche (règle 9), formulations proposées :
  - `docs/exigences.md` 2.5 : « Deux engagements sincères contraires sur une même unité ne coexistent pas ; le second ne remplace le premier que si le bot déclare la rupture et si le plan qui le réalise vaut nettement plus ; sinon le premier tient et le second est un bluff. » (texte d'`expert-cicero`).
  - `docs/exigences.md` 2.7 : ajouter « Chaque bot tient aussi le bilan de ses propres promesses, et ne le rappelle à Claude que pour l'interlocuteur courant. »
  - `CLAUDE.md`, « Architecture » : « Le retour *dialogue → moteur* ne passe que par le champ `sincere`, filtré par `legal_commitments` et restreint par la déclaration de rupture `betray` (qui ne quitte pas le bot de dialogue), et n'agit que sur la probabilité d'une action, jamais sur sa valeur. »
  - `docs/doc/architecture.md` § 3 (trois champs de la sortie JSON, section « Your own record with X » de la consigne) et § 4 (ligne « Cohérence entre interlocuteurs » : règle à deux conditions, lignes de journal `[betrayal-refused]`, `[revision]`, `[betrayal-ignored]` ; retrait de la mention « écart connu, issue #3 » ; registre de confiance : les promesses du bot lui-même).
  - `CONTEXT.md` : « Trahison » précisé, « Révision » et « Trahison déclarée » ajoutés (fait avec cet ADR).
- **Ce que l'ADR ne règle pas** : le retrait d'une promesse sans remplacement ; l'effet d'une trahison sur le registre de confiance *du joueur* (inchangé) ; la valeur de la marge (0,02, ADR 0003) ; la forme de la garde de l'exigence 2.8 (#14).

Issues : #17 (porte la décision et l'implémente), #3 (remplacée et fermée par le même travail), #2 (règle appliquée en amont, ligne 1 de la table), #5 (ligne 0 de la table : réponse nulle, sourdine, envoi en échec).
