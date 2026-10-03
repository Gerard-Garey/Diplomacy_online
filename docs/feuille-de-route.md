# Feuille de route

Tenue par `architect`, après chaque série de PR fusionnées. Chaque mise à jour est datée et cite le SHA de `main` et de la branche de travail.

## 1. Branche de travail en cours

Mise à jour du 2026-10-03 (quatrième, après la validation de fond d'`expert-cicero` et les décisions M32 à M41) — `main` : `a9566a2` (fusion de la PR #1) ; `claude/promesses` : `7b7ce70`, PR brouillon #16. Mises à jour précédentes du même jour : `2d5294f`, `41e009f` (sur `7372dcf`), puis `1256927` (sur `0fdb5bf`).

**État au 2026-10-03.** Le code de fond est écrit et audité pour #2, #17 / #3, #4 et #5 ; il est dans l'arbre de travail, **non commité** (visa à venir, M40) et sauvegardé dans `amont/sauvegardes/` (hors dépôt). Corrections finales en cours chez `coder` (M32 à M35). Les mesures sur la pile sont autorisées par le mainteneur (M38) ; protocole au § 1.3.

- **Branche** : `claude/promesses` — PR #16, brouillon.
- **Objet** : logique des promesses. Périmètre fixé par le mainteneur le 2026-10-03 (M10, M11), étendu le même jour sur son accord : trahison retirée chez tous les destinataires (avec #2, M19), réponse vide et sourdine (avec #5, M17), issue #17 (M24), qui remplace la tâche T5 telle que spécifiée et implémente #3 ; #3 reste dans le périmètre et est fermée par le même travail.
- **Périmètre** (fermé : six issues, #12, #2, #3, #4, #5, #17) :
  - [x] T1 — option « partie 100 % bots » — #12 : script en ligne de commande (`e0624e6`) ; partie `gameID=3` créée le 2026-10-03, elle avance seule ; critères d'exécution A1 à A5 en cours de levée (dans l'issue)
  - [x] T2 — banc déterministe (`7372dcf` : `tests/banc_promesses.py`, `tests/test_promesses.py`, `tests/mesure_promesses.py`, cibles en échecs attendus) ; la mesure « avant » répétée (appels réels à Claude) reste à faire avant les commits de fond
  - [x] T3 — #5, volet technique (écriture atomique, garde de `load_state`, bot muet sur fichier illisible) — `e351abf` ; résultats : aucun ; réserves mineures d'`audit` reprises avec T7
  - [ ] T4 — #2 — écrit et audité, dans l'arbre de travail, non commité (attend le visa) — résultat changé (`sincere`)
  - [ ] T5 — #17, qui spécifie et implémente #3 (trahison déclarée, mémoire des promesses du bot, index `order_values`) — ADR 0004 révisé puis complété — écrit et audité, reprise après T6 comprise (M25 à M30), non commité (attend le visa) ; **corrections finales en cours** : rejugement jusqu'à stabilité (M32), politique d'avant renfort remise dans le résultat de recherche (M33, patch du moteur, à contrôler sur une recherche réelle), balises après confirmation de l'envoi (M34), texte de la consigne (M35), `search.boost` à 1,0 quand les engagements sont désactivés — résultat changé (`sincere`, `[betrayal]`, consigne, `current_plans.json`)
  - [ ] T6 — #4 — écrit et audité, non commité (attend le visa) ; renfort gradué en fonction pure, commune au moteur et au bot de dialogue (`pseudo_commitments.py`), dont dépend la condition (e) — résultat changé (probabilité des actions, donc ordres tirés)
  - [ ] T7 — #5, volet de fond (journal d'envoi `pending_send`, trois envois au plus, réponse vide, sourdine ; M17, M36) — écrit et audité, non commité (attend le visa) — résultat changé (`sincere`, moment où un engagement atteint le moteur)
  - [ ] T8 — mesures (protocole du § 1.3, autorisé par M38), tableau avant / après unique, visa du mainteneur
  - [ ] T9 — documentation de fond, un passage (règle 9), textes listés par l'ADR 0004 compris

### 1.1 Ordre des commits

Ce qui dépend de la spécification des experts est marqué **(experts)** : le plan reste vrai quelle que soit leur réponse, seul le détail désigné peut bouger.

| Rang | Commit | Tâche | Agent | Circuit | Résultat changé |
|---|---|---|---|---|---|
| 0 | `docs:` feuille de route, annotation de l'ADR 0002, glossaire | présente mise à jour | `architect` | 4 | non |
| 1 | `docs:` ADR sur le dialogue entre bots — **seulement si** les experts retiennent que les bots se parlent (§ 1.4) ; le document précède alors le code (règle 9, exception) | T1 | `architect-approfondi`, routage Fable | — | — |
| 2 | `webdip:` création d'une partie à sept bots, réservée à l'administrateur ou à un lancement direct **(experts : page, script ou les deux ; mode d'accès administrateur)** | T1 | `expert-webdip` spécifie → `coder` → `audit` (+ `app-review` si une page change) | 1 | non pour une partie ordinaire (critère A1) |
| 3 | `cicero:` ce que la partie 100 % bots demande aux deux démons **(experts : peut être vide)** | T1 | `expert-cicero` spécifie → `coder` → `audit` | 1 | non pour une partie ordinaire ; oui si le dialogue entre bots est ouvert |
| 4 | `tests:` tests en échec attendu pour #2, #3, #4 et #5, renvoyant chacun à son issue ; procédure de capture et de rejeu des positions **(experts : emplacement, nombre de positions et de tirages)** | T2 | `coder` → `audit` | 3 | non |
| 5 | `cicero:` écriture atomique de `save_state` et `save_commitments_file`, garde de `load_state` sur un JSON tronqué (#5) | T3 | `coder` → `audit` | 3 | non |
| — | mesure « avant » sur le code de rang 5 (aucun commit) | T2 | session principale, protocole d'`expert-cicero` | — | — |
| 5 bis | `docs:` ADR 0004 (trahison déclarée), annotation de l'ADR 0003, glossaire, feuille de route — le document précède le code (règle 9, exception) | T5 | `architect-approfondi`, routage Fable (§ 4.1.3) | 4 | non |
| 6 à 9 | **Découpage révisé (M40)** : les rangs 6 à 9 ci-dessous décrivent l'ordre des travaux ; les commits sont au nombre de trois — `cicero:` #4 ; `cicero:` commun à #2, #17 / #3 et #5 ; `tests:` — voir § 1.3 | T4 à T7 | session principale | — | oui |
| 6 | `cicero:` deux ordres contraires d'un même message, trahison retirée chez tous les destinataires (#2) | T4 | voir § 1.2 | 2 | oui |
| 7 | `cicero:` cible et gradation du renfort de probabilité, fonction pure partagée (#4) | T6 | voir § 1.2 | 2 | oui |
| 8 | `cicero:` trahison déclarée, condition (e), marge 0,05, mémoire des promesses du bot, `order_values`, `candidates` et `search` (#17, ferme #3) | T5 | voir § 1.2 | 1 | oui |
| 9 | `cicero:` journal d'envoi, trois essais, réponse vide, sourdine (#5) | T7 | voir § 1.2 | 1 | oui |
| — | mesure « après », tableau unique, **visa du mainteneur** ; les rangs 6 à 9 ne sont commités qu'ensuite | T8 | session principale, `expert-cicero` relit le tableau | — | — |
| 10 | `tests:` retrait des marques d'échec attendu devenues des succès | T4 à T7 | `coder` → `audit` | 3 | non |
| 11 | `docs:` un commit par issue | T9 | `docwriter` → `expert` valide le diff | 4 | non |

Raisons de l'ordre (révisé le 2026-10-03 d'après `expert-cicero`, après la spécification de #17) :

- **Rang 5 avant la mesure « avant »** : le volet technique de #5 ne change aucun résultat ; le placer avant fait que l'écart avant / après ne contient que les quatre modifications de fond, et protège l'état pendant les essais.
- **#2 avant #17** : même fonction (`_reject_contradictions`, `claude_dialogue_bot.py:163`) ; la règle de #2 (plus d'un ordre entrant pour l'unité : aucun retenu) est la ligne 1 de la table de décision de #17, appliquée avant le label ; #2 corrige aussi la clé `by_recipient[None]`.
- **#17 avec #3** : #17 reprend la décision de #3 (valeur inconnue → la première promesse tient, index `order_values` exporté par `plan_export.py`) et y ajoute la condition du label ; un seul commit, qui ferme les deux issues.
- **#4 avant la reprise de #17** (M31, révision du 2026-10-03 ; remplace « #5 de fond avant #4 ») : la condition (e) de l'ADR 0004 appelle la fonction de renfort de #4 (`apply_commitments_to_policy`, `pseudo_commitments.py:171`, à rendre pure et partagée) ; l'écrire deux fois ferait diverger (e) du moteur. Ordre réel des travaux : #2 (fait, audité) ; #17 et #3, partie déterministe et consigne (faites, auditées) ; #4 (en cours) ; reprise de #17 ; #5 de fond ; mesures et visa. Le diff de #17 se construit en deux temps mais reste un seul commit.
- **#5 de fond en dernier** : #5 change le point de persistance des engagements, que #17 utilise pour `own_promises` (tel qu'implémenté : état et fichier d'engagements écrits **avant** l'envoi sous le journal `pending_send`, défaits si le message n'est pas parti ; et non « après envoi confirmé », formulation antérieure de cette ligne et de l'issue #17) ; il reste côté bot de dialogue et ne dépend ni de #4 ni de (e). Dépendance retirée : « #4 en dernier pour ne rejouer le moteur qu'une fois » ; les rejeux moteur se font après le rang 8, quand l'export (`candidates`, `search`) est définitif.

### 1.2 Circuit de chaque issue

- **#2, #3, #4 — circuit 2 (correction de fond).** Chacune est un écart entre le code et un texte qui fait foi dans le projet : exigence 2.5 et ADR 0003, décision 5, pour #2 et #3 ; tableau du § 4 de `docs/doc/architecture.md` pour #4. Déroulé : `expert-cicero` établit la lecture → le mainteneur tranche (un résultat change) → `coder` → `audit` → `expert-cicero` contrôle la conformité → `docwriter`. Pour #3, l'issue pose deux lectures (tenir ou abandonner) : `expert-cicero` les décrit, le mainteneur tranche. Si l'expert conclut, sur #4, que le texte de référence ne dit rien du cumul par ordre promis, cette partie devient une règle nouvelle et suit le circuit 1.
- **#5, volet de fond — circuit 1 (évolution de fond).** Aucun texte ne fixe l'ordre entre l'enregistrement et l'envoi ; deux règles s'y opposent (l'invariant « l'état écrit sur disque l'est aussitôt » et l'exigence 5.3, « jamais envoyé deux fois »). Question à cheval : `expert-cicero` (sens d'un engagement dont le message n'est pas parti) et `expert-webdip` (statuts de l'API, `post_req`), séparément. `post_req` est un fichier d'amont : le corriger passe par un patch.
- **#17 (avec #3) — circuit 1 (évolution de fond)**, la règle du label étant nouvelle : spécifiée par `expert-cicero` (issue #17), décidée par le mainteneur (M24), consignée dans l'ADR 0004 → `coder` → `audit` → `docwriter` → `expert-cicero` valide. La table de décision de l'issue fait foi ; chaque ligne est un test du banc.
- **#5, volet technique — circuit 3.**
- **T1 — circuit 1**, spécifié par les deux experts.

Mesure (protocole d'`expert-cicero`, volume approuvé par le mainteneur) : partie déterministe par le banc (appel direct et cycle simulé, `tests/mesure_promesses.py`) ; partie répétée par appels réels à Claude, cinq situations fabriquées à partir d'une position de la partie `gameID=3`, vingt tirages chacune : trois situations avant et après (120 appels), deux situations propres au nouveau code, après seulement (40 appels), soit 160 appels ; protocole complet au § 1.3. Vingt tirages ne distinguent que de gros écarts (exigence 2.10) ; le tableau le dit.

### 1.3 Tableau avant / après et visa (M10)

Un seul tableau et un seul visa pour #2 à #5, par décision du mainteneur.

**Découpage des commits (M40, 2026-10-03 ; remplace « les commits restent distincts, un par issue »).** Les diffs par issue, conservés hors du dépôt dans un dossier temporaire, ont été perdus au redémarrage de la machine (dossier effacé). Le mainteneur a décidé de trois commits : un commit `cicero:` pour #4 ; un commit `cicero:` commun à #2, #17 / #3 et #5 ; un commit `tests:`. C'est une **dérogation** à la règle « un commit par issue qui change un résultat » (`CLAUDE.md`, « Git et GitHub »), à noter dans la PR #16 ; le tableau avant / après garde une section par issue, et le message du commit commun renvoie aux quatre issues. Le code reste hors git jusqu'au visa, sauvegardé dans `amont/sauvegardes/` (ignoré par git).

**Protocole de mesure retenu** (autorisé par le mainteneur, M38) :

1. l'image actuelle est conservée sous l'étiquette `cicero-webdip:avant` ; l'image est reconstruite sur le nouveau code ;
2. **30 recherches réelles** du moteur sur le nouveau code, avec quatre contrôles : la table exportée est présente (`candidates`, `search`) ; les actions candidates sont toutes dans la copie de la politique avant renfort ; la tête recalculée par le bot de dialogue est l'action jouée ; le renfort n'est pas composé d'une recherche à l'autre (M33) ;
3. **mesure appariée de #4**, hors ligne (M37) : l'ancien et le nouveau renfort appliqués à la même table réelle, la comparaison étant approchée au second ordre ;
4. **160 appels à Claude** : trois situations avant et après (120), deux situations propres au nouveau code, après seulement (40) ;
5. **essai d'envoi réel** sur une partie jetable (journal d'envoi de #5).

- Le tableau a une section par issue. Chaque ligne est expliquée par une seule des quatre modifications ; une ligne inexpliquée est une régression.
- **Lignes déterministes** (mesurées une fois) : appel direct de la fonction corrigée, avec les entrées citées dans l'issue.
- **Lignes sur position rejouée** (répétées) : mêmes positions, mêmes messages reçus, plusieurs tirages **(experts : nombre de positions, de tirages, grandeurs relevées)**.
- Chaque mesure note la version de la CLI Claude Code et le modèle servi : ni l'une ni l'autre n'est épinglée (#6, #7), et l'image est reconstruite entre « avant » et « après ». Si l'une a changé, la mesure « avant » est refaite sur la nouvelle image.
- Les rangs 6 à 9 restent dans l'arbre de travail jusqu'au visa (`CLAUDE.md` : sans visa, rien n'est commité), sauvegardés dans `amont/sauvegardes/` ; découpage des commits : M40, ci-dessus. Ce travail se fait donc sur le poste local, pas en session cloud.
- Les décomptes de `[betrayal]` et `[revision]` ne portent pas sur la même définition avant et après (M34 : après confirmation de l'envoi seulement) ; le tableau le dit.
- Toute reconstruction ou redémarrage de la pile est annoncé au mainteneur avant d'être lancé (M12) ; la reconstruction du protocole est autorisée (M38) ; la pile a été relancée par `demarrer.sh` après le redémarrage de la machine (M39).

### 1.4 Critères d'acceptation

| Tâche | Critère |
|---|---|
| T1 | A1. Une partie à sept bots se crée et avance jusqu'à la fin d'une année sans action humaine. A2. Un compte ordinaire ne peut pas la créer (requête refusée, mesure citée). A3. Une partie ordinaire (un humain, six bots) se crée et se joue comme avant : même configuration du moteur, mêmes fichiers partagés. A4. Mémoire GPU et nombre d'appels à Claude par phase mesurés à sept bots. A5. Aucun état de partie dans le dépôt (`tests/verifier.sh`). |
| T2 | La procédure rejoue une position sans action humaine et donne, pour #2 à #5, la mesure « avant » ; les tests en échec attendu échouent pour la raison décrite dans l'issue. |
| T3 | Un fichier d'état tronqué ne fait plus boucler le conteneur (essai sur un fichier tronqué exprès) ; écriture par fichier temporaire et `os.replace`, comme `plan_export.py` ; aucun résultat modifié. |
| T4 (#2) | Deux ordres contraires pour une même unité dans une même liste `sincere` : un seul au plus est retenu, selon la règle établie par `expert-cicero` ; plus de clé `by_recipient[None]` ni de `"null"` sérialisé. |
| T5 (#17, #3) | Critères (a) à (g) de l'issue #17 : chaque ligne de la table de décision (0 à 8, 6 bis comprise) est un test du banc qui passe, état inchangé dans les cas refusés ; `betray` toujours une liste ; 0 label sur 20 sans conflit, au moins 18 labels exacts sur 20 en conflit ; aucun `reply` ne contient `sincere`, `betray`, une accolade ni la promesse faite à un tiers ; taille de consigne mesurée ; au plus un ordre par unité dans `pseudo_commitments.json`. Pour #3 : valeur inconnue → la première promesse tient ; texte du § 4 de l'architecture, docstring et code concordent ; la mention « écart connu » du § 4 est retirée. Révision (M25 à M30) : `order_values` vaut la valeur de l'action de meilleur score contenant l'ordre ; (e) calculée par la fonction de renfort de #4, la même que celle du moteur (un test compare les deux sur une même table) ; `candidates` ou `search` absents → `unknown_value` ; marge 0,05 ; au plus un ordre par unité et par destinataire dans `own_promises.pending` ; aucun coût négatif affiché à Claude, `cost_vs_best` exporté inchangé. |
| T6 (#4) | Sur l'exemple de l'issue (promesses `A MAR - SPA` et `F BRE - ENG`, politique 0,5 / 0,3 / 0,2), les probabilités obtenues sont celles de la règle établie ; la somme vaut 1 ; aucune valeur d'action n'est modifiée (invariant « le moteur décide ») ; le renfort est une fonction pure, appelée par le moteur et par le bot de dialogue. |
| T7 (#5) | Critère d'origine : un envoi en échec (erreur réseau, statut 4xx ou 5xx simulés) ne laisse aucun engagement enregistré et ne marque pas le message comme répondu ; un message n'est jamais envoyé deux fois (exigence 5.3). **Tel qu'implémenté (M17, M36), à confirmer par le mainteneur au visa** : un envoi incertain garde l'engagement (état et fichier) sous `pending_send` jusqu'à sa résolution par relecture des messages de la partie ; sourdine ou abandon (trois envois, ou changement de phase) : engagements défaits, message marqué répondu, échange non compté ; le même texte n'est renvoyé qu'après deux relectures négatives ; une promesse dont le message n'est pas parti n'est ni jugée ni rappelée. Écarts au critère d'origine : l'engagement existe pendant l'incertitude ; le message est marqué répondu à l'abandon ; un renvoi après deux relectures négatives peut doubler un message stocké avec retard (risque résiduel envers l'exigence 5.3, que l'essai d'envoi réel du § 1.3 observe). |
| T8 | Tableau complet, chaque ligne expliquée, visé par le mainteneur. |
| T9 | `docs/doc/architecture.md` § 3 et § 4 et `README.md` concordent avec le code final ; diff validé par `expert`. |

### 1.5 Point ouvert de T1 : d'où viennent les messages

Les issues #2 à #5 portent sur des engagements, qui n'existent que s'il y a des messages. Une partie à sept bots sans dialogue donne des positions, pas des promesses. Deux voies, à départager par `expert-cicero` puis par le mainteneur :

- **Voie A — messages injectés par un script**, au nom d'une puissance, sur une position rejouée : le stimulus est fixe, donc comparable avant et après.
- **Voie B — les bots se parlent**, ce que l'exigence 2.8 exclut aujourd'hui.

Constat de lecture, non rejoué : le bot de dialogue répond à tout message reçu, sans regarder si l'expéditeur est un bot (`claude_dialogue_bot.py:547`). Dans une partie à sept bots, un seul message injecté lance donc un échange entre deux bots, borné à dix réponses par paire et par phase (`MAX_EXCHANGES_PER_PAIR_PER_PHASE`, ligne 33). La voie A touche ainsi l'exigence 2.8 dans sa lettre, sauf si l'expéditeur injecté est exclu des réponses. Conséquence sur l'ADR : voir la décision M11 et le compte rendu d'`architect` du 2026-10-03.

Issue du point (2026-10-03) : les messages scénarisés par l'API sont écartés de la branche ; la garde de l'exigence 2.8 fait l'objet de #14 (branche non-régression, § 2). La mesure répétée de la branche passe par `generate_reply` directement (§ 1.2), sans message injecté dans la partie.

### 1.6 Revue finale complète (règle 10)

`audit` (code et batteries), `expert-cicero` (fond des promesses, tableau), `expert-webdip` (patch de webDiplomacy, accès administrateur), `app-review` si une page de webDiplomacy est ajoutée ou modifiée, `docwriter`, puis `/code-review`.

## 2. Branches suivantes

Dans cet ordre, sauf décision contraire du mainteneur.

| Branche | Issues | Motif du regroupement | Dépend de |
|---|---|---|---|
| non-régression | #9, #14, #15, plus une issue à créer (référence de non-régression) | Même dossier (`cicero/overlay/essais/`) et même besoin : des essais qui ne supposent ni la partie 15 ni une action humaine, et qui n'écrivent pas dans les fichiers de production. #14 (garde de l'exigence 2.8) est le prérequis des messages scénarisés par l'API, donc d'un essai de la chaîne entière sans humain ; #15 (quatre points non vérifiés de l'import) sont des mesures à exécuter, dont deux (arrêt long, reprise après échec d'appel) demandent la pile et la partie 100 % bots | `claude/promesses` : positions rejouées et partie 100 % bots (T1, T2) ; signature de `_reject_contradictions` fixée par #2 et #17 |
| installation reproductible | #6, #7, #8, #13 | #6 et #7 touchent le `Dockerfile` (une seule reconstruction de l'image) et épinglent ce dont dépend le comportement des bots (CLI, modèle) ; #7 et #8 touchent `install.sh` ; #13 (`br_regularize_lambda`, 1e-2 contre 3e-3) touche `cicero_no_dialogue.prototxt`, paramètre du moteur embarqué dans la même image : si le mainteneur revient à 3e-3, c'est un changement de résultat à mesurer contre la référence de non-régression, avec #6 et #7 | non-régression : épingler le modèle, retirer les outils ou changer λ change un résultat, à mesurer contre une référence ; #13 attend la décision du mainteneur (`needs-info`) |
| exploitation | #10, #11, #18, plus deux issues à créer sur accord (isolement par partie d'un fichier d'engagements mal formé ; croissance de `current_plans.json`) | Durcissement et tenue dans le temps de la pile : redémarrage, secret, fichiers d'état, réglages de sécurité du dépôt | `claude/promesses` (#5 : même code de persistance que #11, point 2) ; non-régression pour la question du redémarrage en cours de phase (#10) |

Dépendances ajoutées le 2026-10-03 : non-régression → `claude/promesses` (remplace « validation du build ») ; installation reproductible → non-régression ; exploitation → `claude/promesses` et non-régression. Dépendance retirée : la ligne « validation du build », faite dans la PR #1 (§ 6). Ajouts de la seconde mise à jour : #14 et #15 → non-régression (#15, point « installation sur une autre machine », peut être levé plus tôt par toute session cloud, sans attendre la branche) ; #13 → installation reproductible, après décision du mainteneur ; #10, point « aucun compte administrateur » : T1 n'a pas créé de compte Admin (M20, script en ligne de commande), le point reste à #10.

Recoupements à connaître :

- #9 et #2, #17 : `test_multiparty.py` dépaquette mal le retour de `_reject_contradictions` ; la signature est touchée dans `claude/promesses` (#2, puis #17 qui ajoute le label en entrée) ; #9 reprend la signature finale, celle que fixe le banc `tests/banc_promesses.py`.
- #14 et #12 : la garde de l'exigence 2.8 n'a de sens que dans la partie 100 % bots ; la question posée à `architect` par #14 (filtre sur les comptes bots ou silence de la seule puissance scénarisée) se tranche au plan de la branche non-régression, avec les positions de `gameID=3` sous la main.
- #11 (point 2) et #5 : un JSON illisible remet le fichier à vide ; la garde posée par T3 sur l'état du bot de dialogue est à reprendre pour `current_plans.json`.
- #11 et #17 : `current_plans.json` reçoit `candidates` (toutes les actions candidates) et `search` (ADR 0004, décision 12) ; le fichier grossit d'autant, à prendre en compte dans la purge des fichiers d'état (issue complémentaire à créer sur accord, § 3).
- #18 et #10 : deux durcissements sans changement de résultat ; #18 est du domaine `repo:` (plus `docs:` pour le README). Le ruleset et les modes de fusion sont déjà appliqués (M41) ; la section « Sécurité du dépôt » du README, à laquelle `CLAUDE.md` renvoie déjà, peut être avancée en correctif rapide `docs:` si le mainteneur le veut, le script de contrôle restant à la branche.
- #10 (aucun compte administrateur créé) et T1 : la partie 100 % bots est réservée à l'administrateur. Si T1 crée ce compte, ce point de #10 est réglé par `claude/promesses` et s'y note.
- #10 (motif du correctif du gamemaster dans l'architecture § 5) : le texte actuel du § 5 donne déjà le motif rectifié (`d843896`, `83e2087`) ; à confirmer par `docwriter`, puis à rayer de l'issue.
- #6 et #7 pendant `claude/promesses` : voir § 1.3, version de la CLI et modèle notés à chaque mesure.

## 3. Issues hors plan

Aucune : les seize issues ouvertes (#2 à #15, #17, #18) sont rattachées et triées (libellés posés le 2026-10-03, M13 ; #18 créée le même jour, `ready-for-agent`).

| Issue | Libellés | Tâche | Branche |
|---|---|---|---|
| #2 | `ready-for-agent` | T4 | `claude/promesses` |
| #3 | `ready-for-agent` | T5, fermée par le commit de #17 | `claude/promesses` |
| #4 | `ready-for-agent` | T6 | `claude/promesses` |
| #5 | `ready-for-agent` | T3 (technique, fait), T7 (fond) | `claude/promesses` |
| #12 | `enhancement`, `ready-for-agent` | T1 (fait, critères A1 à A5 à lever) | `claude/promesses` |
| #17 | `enhancement`, `ready-for-agent` | T5 — ADR 0004 (révisé) ; reprise après T6 | `claude/promesses` |
| #6 | `ready-for-agent` | outils du bot de dialogue, CLI épinglée | installation reproductible |
| #7 | `ready-for-agent` | versions à épingler | installation reproductible |
| #8 | `ready-for-agent` | mise à jour de `amont/` | installation reproductible |
| #13 | `needs-info` | décision du mainteneur (garder 1e-2 documenté, ou revenir à 3e-3 avec tableau et visa) ; documentation dans tous les cas | installation reproductible |
| #9 | `ready-for-agent` | reprise des essais | non-régression |
| #14 | `ready-for-agent` | garde de l'exigence 2.8 ; forme à fixer par `architect` au plan de la branche | non-régression |
| #15 | `ready-for-human` | quatre mesures à exécuter par le mainteneur ou une session avec la pile ; le point « autre machine » peut être levé par une session cloud à tout moment | non-régression |
| #10 | `ready-for-agent` | durcissements | exploitation |
| #11 | `ready-for-agent` | arrêt court, purge des fichiers d'état | exploitation |
| #18 | `ready-for-agent` | réglages de sécurité du dépôt : ruleset « Protection main » importé et modes de fusion restreints le 2026-10-03 (M41) ; reste la section « Sécurité du dépôt » du README (`docwriter`) et le script de contrôle (`coder` → `audit`, circuit 3) | exploitation |
| à créer | — | référence de non-régression | non-régression |
| à créer sur accord | `bug`, `needs-triage` | `cicero :` promesse rompue réaffirmée à la puissance trahie — après une trahison, la section des promesses ne montre plus rien de la puissance trahie avant la phase suivante (ADR 0004, limites connues) ; change un résultat (consigne) | à fixer : après `claude/promesses`, avec la référence de non-régression (non-régression au plus tôt) |
| à créer sur accord | `bug`, `needs-triage` | `cicero :` isolement par partie d'un fichier d'engagements mal formé — une forme inattendue dans une seule partie rend tous les bots muets (ADR 0004, limites connues ; M18) | exploitation |
| à créer sur accord | `enhancement`, `needs-triage` | `install :` croissance de `current_plans.json` (clés `candidates` et `search`, 35 actions au plus par puissance et par export) — complément de #11 | exploitation |

Les quatre points « non vérifiés » de la passation de la PR #1 sont devenus l'issue #15.

## 4. Décisions du mainteneur

| N° | Date | Décision | Où elle est consignée |
|---|---|---|---|
| M1 | 2026-10-02 | Dépôt de patchs et script d'installation ; build complet depuis les sources ; cible Ubuntu + GPU NVIDIA ≥ 8 Go | ADR 0002 |
| M2 | 2026-10-02 | Sous-agents : deux experts (`expert-cicero`, `expert-webdip`), `app-review` et `docwriter` conservés ; licence MIT, AGPL-3.0 pour `webdiplomacy/` | `CLAUDE.md`, `NOTICE` |
| M3 | 2026-10-02 | Validation du build Docker différée (« écrire maintenant, valider plus tard ») — levée le 2026-10-03 | ADR 0002, README « État » |
| M4 | 2026-08-19 | Rester proche de Cicero : pas d'engagements négatifs, pas d'effet du dialogue hors mouvement | ADR 0003, exigence 2.9 |
| M5 | 2026-10-03 | Pile et données : la partie en cours sur l'ancienne pile est mise de côté, la nouvelle pile part d'une base vide ; la base, les journaux et l'état des parties ne vont jamais sur GitHub | PR #1, passation du 2026-10-03 (11:04 UTC) ; exigence 4.3 ; `tests/verifier.sh` |
| M6 | 2026-10-03 | Le modèle d'ordres `cicero_imitation_bilateral_orders_prefix` est gardé pour le moment, à retirer s'il s'avère inutile. Principe rappelé : on n'utilise pas le dialogue de Cicero, seulement son moteur ; Claude écrit les échanges. Le retirer change un résultat (mesure avec et sans, visa) | PR #1, même passation ; `versions.env` (`MODELES`) |
| M7 | 2026-10-03 | Plateforme : l'interface cliquable est construite par `install.sh` ; seule la variante Classic est proposée contre les bots ; `bot-service` est gardé tel quel | `2f38b12`, `ce330ee` ; ADR 0002 (annotation) ; `docs/doc/architecture.md` § 5 ; README « État » |
| M8 | 2026-10-03 | Bot de dialogue : un appel à Claude en échec n'est plus pris pour un silence ; pour les outils de Claude Code, mesurer avant de corriger (mesure faite, pas de fuite, correction non appliquée) | `73479ff` ; issue #6 |
| M9 | 2026-10-03 | La PR #1 est fusionnée par le mainteneur lui-même, en commit de fusion, sans passage d'`audit` sur `7b8451d` à `d84cebc` | `a9566a2` ; PR #1, passation du 2026-10-03 (12:15 UTC) |
| M10 | 2026-10-03 | Branche suivante : logique des promesses, issues #2 à #5 dans une seule branche, un tableau avant / après et un visa pour l'ensemble ; `architect` passe dans cette même branche | PR #1, même passation ; § 1 et § 1.3 |
| M11 | 2026-10-03 | Les essais tournent sans intervention humaine : la branche commence par une option « partie 100 % bots », lançable seulement par un administrateur ou directement par Claude, qui fournit les positions à rejouer | PR #1, même passation ; § 1 (T1, T2) ; `CONTEXT.md` |
| M12 | 2026-10-03 | Pile en service : prévenir le mainteneur avant tout `install.sh` ou `demarrer.sh` | PR #1, même passation ; § 1.3 |
| M13 | 2026-10-03 | Organisation : la session démarre dans le dépôt, pour charger les agents de `.claude/agents/` ; les libellés de triage de `CLAUDE.md` sont à créer et à poser — créés le 2026-10-03, posés sur toutes les issues ouvertes (#2 à #15, #17 ; `needs-info` sur #13, `ready-for-human` sur #15, `ready-for-agent` ailleurs) ; création des issues #12 à #15 et #17 approuvée | PR #1, même passation ; § 3 |
| M14 | 2026-10-03 | #2 : deux ordres contraires pour une même unité dans un même message, aucun des deux n'est retenu (`[double-deal]`, promesse antérieure intacte) | PR #16 ; ADR 0004, décision 10 |
| M15 | 2026-10-03 | #3 : une promesse antérieure de valeur inconnue tient ; `current_plans.json` reçoit un index `order_values` (valeur de chaque ordre sur tous les candidats). Reprise par #17 (point 7) | PR #16 ; issue #17 |
| M16 | 2026-10-03 | #4 : renfort de probabilité gradué, multiplicateur k^(promesses tenues / promesses faites), plafond inchangé | PR #16 ; issue #4 |
| M17 | 2026-10-03 | #5 fond : réponse vide avec `sincere` non vide → engagements nouveaux écartés (ajout de périmètre) ; journal d'envoi écrit avant l'envoi, résolu au cycle suivant par relecture des messages, même texte renvoyé, trois essais au plus, puis abandon et engagement retiré ; destinataire en sourdine (statut 200, rien de stocké) → engagement retiré | PR #16 ; ADR 0004, table de #17 ligne 0 |
| M18 | 2026-10-03 | #5 technique : fichier d'état ou d'engagements illisible, y compris erreur système (`OSError`) → le bot reste en vie, muet, et répète un message explicite jusqu'à réparation | PR #16 ; `e351abf` |
| M19 | 2026-10-03 | Trahison après une promesse faite à deux puissances : l'ordre antérieur est retiré chez tous les destinataires ; traité avec #2 et #3 (ajout de périmètre) | PR #16 ; ADR 0004, décision 5 |
| M20 | 2026-10-03 | #12 : « administrateur » désigne l'opérateur du poste ; la partie 100 % bots se crée par un script en ligne de commande, en overlay, sans patch ni compte Admin | PR #16 ; `e0624e6` |
| M21 | 2026-10-03 | Partie d'essai n° 2 supprimée avant le premier lancement de #12 (sauvegarde SQL locale, hors dépôt) ; la partie à sept bots s'arrête par une pause posée en SQL une fois les positions recueillies | PR #16 |
| M22 | 2026-10-03 | Push et ouverture de PR autorisés sans demander sur une branche de travail, hors `main` | PR #16 |
| M23 | 2026-10-03 | Mesure de la branche : partie déterministe par le banc ; partie répétée par 160 appels réels à Claude (cinq situations, vingt tirages, avant et après), volume approuvé | issue #17 ; § 1.2 |
| M24 | 2026-10-03 | Trahison déclarée (#17) : (1) une trahison n'est acceptée que déclarée par le label `betray` **et** avec un gain de valeur au-dessus de la marge ; sans label, hallucination, la première promesse tient ; label sans gain suffisant ou valeur inconnue, refusé ; (2) effet moteur inchangé, échange d'engagement, seule la probabilité bouge ; (3) consigne : à qui il a promis quoi, prix d'une rupture, trahison déclarée autorisée, bilan de ses propres promesses pour l'interlocuteur courant seulement ; (4) remplacer une promesse faite au destinataire même : même règle, notée `[revision]`, pas une promesse rompue envers lui ; (5) retrait sans remplacement refusé dans cette branche, occurrences comptées. Précisions : le label reproduit l'ordre promis exact ; #17 remplace #3 et l'implémente | issue #17 ; ADR 0004 ; annotation de l'ADR 0003 |
| M25 | 2026-10-03 | Trahison, grandeur comparée : pour chaque ordre, la valeur de l'action de meilleur score qui le contient (ce que le moteur jouerait s'il y était tenu), et non la meilleure valeur brute ; la marge reste en valeur ; `order_values` garde son nom, sa définition change. Écartés : comparer des scores, restreindre aux candidats de probabilité non négligeable, garder la meilleure valeur brute. Amende M15 | ADR 0004 (révisé), décision 11 |
| M26 | 2026-10-03 | Condition (e) : une trahison n'est acceptée que si, en plus du label et de la marge, une action contenant le nouvel ordre prend la tête du classement du moteur après renfort ; calcul dans le bot de dialogue sur la table exportée, clés `candidates` et `search` ajoutées à `current_plans.json`, fonction de renfort commune avec #4. Écarté : accepter la limite connue sans (e) | ADR 0004 (révisé), décision 12 |
| M27 | 2026-10-03 | Marge fixe portée de 0,02 à 0,05 (« il faut qu'il y ait un coût à la trahison ») ; une seule marge. Écarté : marge croissante avec les ruptures passées | ADR 0004 (révisé), décision 13 |
| M28 | 2026-10-03 | Table de décision de #17 : ligne 5 étendue (valeur inconnue, ou `candidates` / `search` absents → `unknown_value`) ; ligne 6 bis (label, gain > marge, (e) fausse → `not_played`, la promesse tient, `[betrayal-refused]`) ; ligne 7 : gain > marge et (e) | ADR 0004 (révisé), décision 10 ; issue #17 (table à recopier) |
| M29 | 2026-10-03 | Révision séquentielle : trahir une promesse faite à X puis promettre sincèrement le nouvel ordre à X avant la résolution est une révision ; l'ancienne promesse sort du bilan envers X (au plus un ordre par unité et par destinataire dans `own_promises.pending`, le dernier dit sincèrement) | ADR 0004 (révisé), décision 6 ; `CONTEXT.md` |
| M30 | 2026-10-03 | Coûts affichés à Claude : nul ou négatif (≤ 0,0005) → « free », dans la section des promesses et dans la liste des plans (ajout de périmètre) ; `cost_vs_best` exporté inchangé | ADR 0004 (révisé), décision 14 |
| M31 | 2026-10-03 | Ordre des travaux : #4 (renfort gradué, fonction pure partagée) avant la reprise de #17, dont la condition (e) dépend ; un seul visa pour l'ensemble (M10) | § 1 et § 1.1 ; ADR 0004 (révisé), Conséquences |
| M32 | 2026-10-03 | Plusieurs trahisons dans un même message : rejugées jusqu'à stabilité (un N refusé `not_played` est retiré des engagements projetés, son E remis, les autres rejugés), au lieu d'une passe conjointe unique. Mesure d'`audit` : 0 violation sur 29 778 remplacements acceptés (60 000 tables engendrées) ; avant : 29 sur 29 969. Limite assumée : refus par excès (42 des 16 533 refus `not_played` auraient été acceptés seuls). Amende M26 | ADR 0004 (complété), décision 12 |
| M33 | 2026-10-03 | Recherche incrémentale : le renfort se composait quand le moteur repartait de la politique déjà renforcée (lecture d'`expert-cicero`, non mesurée ; impossible à sept bots, possible avec un humain). Corrigé dans le patch du moteur : la politique d'avant renfort est remise dans le résultat de recherche. À contrôler sur une recherche réelle | ADR 0004 (complété), décision 12 ; § 1.3 |
| M34 | 2026-10-03 | Journal : les balises `[betrayal]` et `[revision]` ne sont écrites qu'après confirmation de l'envoi du message (avant, une trahison annulée par une sourdine ou un abandon était comptée) | ADR 0004 (complété), décision 15 |
| M35 | 2026-10-03 | Consigne, texte adopté pour la condition : « Your engine honours the switch only if what it would play when held to the replacing order is worth clearly more (by more than {margin}) than what it would play when held to the promise, and only if it would then actually play the replacing order. » | ADR 0004 (complété), décision 16 |
| M36 | 2026-10-03 | Journal d'envoi (#5), précisions de M17 : deux relectures négatives avant de renvoyer le même texte (décision de prudence de la session principale, signalée au mainteneur) ; un `pending_send` mal formé → le message auquel il répondait est marqué répondu, rien d'autre n'est défait | § 1.4 (T7) ; ADR 0004 (complété), Conséquences ; ADR propre à prévoir |
| M37 | 2026-10-03 | Mesure de #4 : appariée et hors ligne (ancien et nouveau renfort appliqués à la même table réelle, approchée au second ordre) | § 1.3 |
| M38 | 2026-10-03 | Mesures autorisées sur la pile : image actuelle conservée (`cicero-webdip:avant`) puis reconstruction ; 30 recherches réelles ; 160 appels à Claude (trois situations avant et après, 120 ; deux situations propres au nouveau code, après seulement, 40 ; précise M23) ; essai d'envoi réel sur une partie jetable | § 1.3 |
| M39 | 2026-10-03 | Pile relancée par `demarrer.sh` après le redémarrage de la machine | § 1.3 ; M12 |
| M40 | 2026-10-03 | Découpage des commits après la perte des diffs par issue (redémarrage de la machine, dossier temporaire effacé) : un commit pour #4, un commit commun à #2, #17 / #3 et #5, un commit pour les tests ; dérogation à « un commit par issue qui change un résultat ». Le code reste hors git jusqu'au visa, sauvegardé dans `amont/sauvegardes/` | § 1.3 ; PR #16 (à noter) |
| M41 | 2026-10-03 | Réglages de sécurité du dépôt : ruleset « Protection main » importé et modes de fusion restreints au commit de fusion ; issue #18 créée pour le reste (section « Sécurité du dépôt » du README, script de contrôle) | issue #18 ; § 2 et § 3 |

## 5. Escalades, relances et arrêts hors branche

Consultations faites hors de toute branche ouverte (`docs/agents/routage.md`, § 7) ; une consultation Fable compte pour la branche suivante.

| Date | Fiche / modèle / critère déclenché / statut obtenu / suite |
|---|---|

## 6. Branches fusionnées

| Branche | PR | Fusion | Périmètre | Revue finale |
|---|---|---|---|---|
| `claude/import-initial` | #1 | `a9566a2` (tête `d84cebc`), 2026-10-03 | Import initial, sans issue préalable : modèle adapté au projet (circuit 4) ; projet reporté dans le dépôt, arbres identiques à l'origine (circuit 3, ADR 0002) ; `Dockerfile` validé par un build complet puis démarrage sur base vide, le 2026-10-03 (circuit 3). Résultats : aucun | `audit`, `expert-webdip`, `docwriter`, `/code-review`, joués par des agents génériques instruits de lire leur fiche ; `architect` non passé ; commits `7b8451d` à `d84cebc` relus par la session principale seule (M9) |
