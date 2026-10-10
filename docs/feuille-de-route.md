# Feuille de route

Tenue par `architect`, après chaque série de PR fusionnées. Chaque mise à jour est datée et cite le SHA de `main` et de la branche de travail.

## 1. Branche de travail en cours

Mise à jour du 2026-10-10 (septième : point d'étape après la fusion de la PR #16) — `main` : `449f02d` (commit de fusion de la PR #16, tête de branche `3dde397`). **Aucune branche de travail n'est ouverte** (`gh pr list --state open` : aucune PR). La branche suivante est **proposée** au § 2.1 ; son périmètre est à fixer par le mainteneur.

**Bilan de `claude/promesses` (close, fusionnée le 2026-10-10, M51).**

- **Livré et fermé** (`gh issue list --state all`, 2026-10-10 : #2, #3, #4, #5, #17 `CLOSED`) : deux ordres contraires d'un même message, aucun retenu (#2) ; trahison déclarée — label `betray`, marge de 0,05 en valeur, condition (e), mémoire des promesses du bot, index `order_values`, clés `candidates` et `search` de `current_plans.json` (#17, qui implémente #3 ; ADR 0004) ; renfort de probabilité gradué, fonction pure commune au moteur et au bot de dialogue (#4) ; écriture atomique, bot muet sur fichier illisible, journal d'envoi `pending_send` (#5 ; ADR 0005). Banc déterministe dans la CI (89 + 172 tests à `3dde397`, passation de la PR #16), scripts de mesure versionnés (`tests/mesure/`), documentation de fond passée une fois et validée par les deux experts.
- **Livré, non fermé** : #12 — script de création d'une partie 100 % bots (`e0624e6`), partie `gameID=3` créée et mise en pause ; l'issue reste ouverte (M49), deux critères n'étant pas mesurés : A3 (une partie ordinaire se crée et se joue comme avant) et « moins de sept bots : échec propre, rien en base ».
- **Reste, porté hors de la branche** : critère (c) de #17 non tenu sur 1 tirage sur 20, accepté pour la branche (M50), suite dans #24 ; dix constats de `/code-review` et sept de l'audit final, aucun corrigé dans la branche, portés par #24 à #29 et par le complément de #22 (M52) ; marge de 0,05 à réexaminer après #26 ; reformulations des exigences 2.5, 2.7, 5.3 et de `CLAUDE.md` (M53) ; référence de non-régression fonctionnelle, toujours sans issue (§ 2.1).
- **Jamais mesuré** (passation de la PR #16, § 4) : Claude sur une autre position, une autre puissance ou une demande négative ; l'ordre réellement joué après une promesse ; le renfort au printemps 1901 (0,07 à 0,16 calculé, non observé) ; le statut de l'API pour un message de plus de 65 000 octets ; un message stocké avec retard après deux relectures négatives.
- **État du poste** (passation, non remesuré par `architect`) : pile en service (M54) sur l'image construite à `afc0dfe` ; partie 3 en pause, source des positions rejouées ; un message posté dans cette partie déclenche des appels à Claude, y compris entre bots (#14) ; compteur des appels de `claude_avant_apres.py` au plafond de 160.

Les § 1.1 à 1.6 ci-dessous décrivent `claude/promesses` et sont **conservés pour l'historique** ; le § 1.7 est tenu à jour.

Mise à jour précédente du 2026-10-10 (sixième, après la revue finale d'`expert-cicero` et d'`audit`) — `main` : `7b9ec68` (fusion de la PR #19, Dependabot) ; `claude/promesses` : `1a0f4a1` (documentation de fond corrigée après la validation d'`expert-cicero`), PR brouillon #16. Mises à jour précédentes : 2026-10-03, `2d5294f`, `41e009f` (sur `7372dcf`), `1256927` (sur `0fdb5bf`), `bddce95` (sur `7b7ce70`), puis 2026-10-10, `9105c96` (sur `ab872ab`).

**État au 2026-10-10, après la revue finale.** Code de fond inchangé depuis le visa (`d353257`, `b995620` ; les commits postérieurs à `ab872ab` sont tous `docs:` ou `claude:`). Documentation de fond passée (`8404c10`, `4af70d6`, `66e1d43`, puis `d85d6d2` et `1a0f4a1` après la validation de fond). Revue finale : `expert-cicero` et `audit` passés ; leurs corrections de texte sont portées dans les ADR 0004 et 0005 (mentions « corrigé le 2026-10-10 »), le glossaire et la présente mise à jour ; leurs constats sans correction dans la branche sont au § 1.7 (points 7 à 13) et au § 3 (« Constats sans issue »). Batteries à la présente mise à jour : `bash tests/verifier.sh` vert (sortie au compte rendu d'`architect`) ; `outils/exporter_patchs.sh --verifier` : voir § 1.7, point 7. Reste avant la sortie du brouillon : les décisions du § 1.7, dont le point 13 (`Closes #12`), et `/code-review`.

**État au 2026-10-10, avant la revue finale** (conservé pour l'historique). Le code de fond de #2, #17 / #3, #4 et #5 est **commité et visé** : commits `b995620` (#4), `d353257` (#2, #3, #5, #17), `afc0dfe` et `053e496` (tests), portés par la PR temporaire #20 (M43), fusionnée par le mainteneur le 2026-10-10 (`9ac8511`, visa : M47) après la mesure sur Claude (160 appels, M46). `main` a ensuite été fusionnée dans la branche (`ab872ab`). Batteries vertes à `ab872ab` (`tests/test_etat_dialogue.py` : 89 tests ; `tests/test_promesses.py` : 172 ; remesurées le 2026-10-10). Reste : ADR 0005 (fait, présente mise à jour), documentation de fond (T9, `docwriter`, un passage), revue finale (§ 1.6), sortie du brouillon. La pile exécute l'image construite sur `afc0dfe` (`053e496` n'ajoute que des tests).

**État au 2026-10-03** (conservé pour l'historique). Le code de fond était écrit et audité, dans l'arbre de travail, non commité (M40), sauvegardé dans `amont/sauvegardes/` ; corrections finales M32 à M35 ; mesures sur la pile autorisées (M38), protocole au § 1.3.

- **Branche** : `claude/promesses` — PR #16, fusionnée le 2026-10-10 (`449f02d`).
- **Objet** : logique des promesses. Périmètre fixé par le mainteneur le 2026-10-03 (M10, M11), étendu le même jour sur son accord : trahison retirée chez tous les destinataires (avec #2, M19), réponse vide et sourdine (avec #5, M17), issue #17 (M24), qui remplace la tâche T5 telle que spécifiée et implémente #3 ; #3 reste dans le périmètre et est fermée par le même travail.
- **Périmètre** (fermé : six issues, #12, #2, #3, #4, #5, #17) :
  - [ ] T1 — option « partie 100 % bots » — #12, **non close** (M49) : script en ligne de commande (`e0624e6`) ; partie `gameID=3` créée le 2026-10-03, elle avance seule ; critères d'exécution A1 à A5 en cours de levée (dans l'issue) — au 2026-10-10, A3 et le critère « moins de sept bots » de l'issue ne sont pas mesurés : § 1.7, point 13 ; reportés à la branche suivante (§ 2.1)
  - [x] T2 — banc déterministe (`7372dcf` : `tests/banc_promesses.py`, `tests/test_promesses.py`, `tests/mesure_promesses.py`, cibles en échecs attendus) ; la mesure « avant » répétée (appels réels à Claude) reste à faire avant les commits de fond
  - [x] T3 — #5, volet technique (écriture atomique, garde de `load_state`, bot muet sur fichier illisible) — `e351abf` ; résultats : aucun ; réserves mineures d'`audit` reprises avec T7
  - [x] T4 — #2 — `d353257` (commit commun, M40), visé (M47) — résultat changé (`sincere`)
  - [x] T5 — #17, qui spécifie et implémente #3 (trahison déclarée, mémoire des promesses du bot, index `order_values`) — ADR 0004 révisé puis complété — `d353257`, visé (M47) ; corrections M32 à M35 comprises ; la politique d'avant renfort remise dans le résultat de recherche (M33) a été contrôlée sur la pile (4 transitions réelles sur 4, passation du 2026-10-03) — résultat changé (`sincere`, `[betrayal]`, consigne, `current_plans.json`)
  - [x] T6 — #4 — `b995620`, visé (M47) ; renfort gradué en fonction pure, commune au moteur et au bot de dialogue (`pseudo_commitments.py`), dont dépend la condition (e) — résultat changé (probabilité des actions, donc ordres tirés)
  - [x] T7 — #5, volet de fond (journal d'envoi `pending_send`, trois envois au plus, réponse vide, sourdine ; M17, M36) — `d353257`, visé avec ses trois écarts (M45, M47) ; **ADR 0005** (présente mise à jour) — résultat changé (`sincere`, moment où un engagement atteint le moteur)
  - [x] T8 — mesures faites (protocole du § 1.3 : pile le 2026-10-03, Claude le 2026-10-10, M46), tableau avant / après unique (passation et commentaire de la PR #20), visa du mainteneur par la fusion de la PR #20 (M47) ; critère (c) de #17 non tenu sur 1 tirage sur 20, (e) signalé 1 fois sur 100 par un détecteur textuel — suite à donner : § 1.7
  - [x] T9 — documentation de fond, un passage (règle 9) : `dcffdcf` (#2), `cce0d47` (#3), `0d6ac9a` (#4), `8404c10` (#5), `4af70d6` (#17), `66e1d43` (#12) ; corrections après validation `d85d6d2` (#12), `1a0f4a1` et `3dde397` (#17, #4). Les textes des exigences et de `CLAUDE.md` listés par les ADR 0004 et 0005 ne sont **pas** modifiés (M53)
  - [x] T10 — revue finale complète (§ 1.6) : `expert-cicero`, `expert-webdip`, `audit` et `/code-review` passés le 2026-10-10 (dix constats de `/code-review`, aucun corrigé dans la branche, portés en issues) ; sortie du brouillon puis fusion (M51)

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
| 6 à 9 | **Découpage révisé (M40)** : les rangs 6 à 9 ci-dessous décrivent l'ordre des travaux ; les commits sont au nombre de trois — `cicero:` #4 (`b995620`) ; `cicero:` commun à #2, #17 / #3 et #5 (`d353257`) ; `tests:` (`afc0dfe`, puis `053e496`, tests seuls) — voir § 1.3 ; portés par la PR #20, fusionnée dans la branche le 2026-10-10 (`9ac8511`) | T4 à T7 | session principale | — | oui |
| 6 | `cicero:` deux ordres contraires d'un même message, trahison retirée chez tous les destinataires (#2) | T4 | voir § 1.2 | 2 | oui |
| 7 | `cicero:` cible et gradation du renfort de probabilité, fonction pure partagée (#4) | T6 | voir § 1.2 | 2 | oui |
| 8 | `cicero:` trahison déclarée, condition (e), marge 0,05, mémoire des promesses du bot, `order_values`, `candidates` et `search` (#17, ferme #3) | T5 | voir § 1.2 | 1 | oui |
| 9 | `cicero:` journal d'envoi, trois essais, réponse vide, sourdine (#5) | T7 | voir § 1.2 | 1 | oui |
| — | mesure « après », tableau unique, **visa du mainteneur** ; les rangs 6 à 9 ne sont commités qu'ensuite — **dérogation M43** : commités sans visa sur une branche temporaire (PR #20), le visa étant la fusion de cette PR (`9ac8511`, 2026-10-10, M47) | T8 | session principale, `expert-cicero` relit le tableau | — | — |
| 10 | `tests:` retrait des marques d'échec attendu devenues des succès — fait dans `afc0dfe` (aucun échec attendu ne subsiste dans les deux modules, remesuré le 2026-10-10) | T4 à T7 | `coder` → `audit` | 3 | non |
| 10 bis | `docs:` ADR 0005 (journal d'envoi), glossaire, feuille de route, décisions M42 à M48 | T7 | `architect-approfondi`, routage Fable (§ 4.1.3, deuxième consultation Fable de la branche) | 4 | non |
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
| T7 (#5) | Critère d'origine : un envoi en échec (erreur réseau, statut 4xx ou 5xx simulés) ne laisse aucun engagement enregistré et ne marque pas le message comme répondu ; un message n'est jamais envoyé deux fois (exigence 5.3). **Tel qu'implémenté (M17, M36), confirmé par le mainteneur le 2026-10-10 (M45) et consigné dans l'ADR 0005** : un envoi incertain garde l'engagement (état et fichier) sous `pending_send` jusqu'à sa résolution par relecture des messages de la partie ; sourdine ou abandon (trois envois, ou changement de phase) : engagements défaits, message marqué répondu, échange non compté ; le même texte n'est renvoyé qu'après deux relectures négatives ; une promesse dont le message n'est pas parti n'est ni jugée ni rappelée. Écarts au critère d'origine, **acceptés** : l'engagement existe pendant l'incertitude ; le message est marqué répondu à l'abandon ; un renvoi après deux relectures négatives peut doubler un message stocké avec retard (risque résiduel envers l'exigence 5.3 ; l'essai d'envoi réel du § 1.3 a été fait une fois, message retrouvé une fois, émoji stocké `????` ; le cas du retard de stockage n'est pas exercé). Texte de l'exigence 5.3 à rouvrir par le mainteneur (§ 1.7). |
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

### 1.7 Décisions en attente du mainteneur (au 2026-10-10)

**Issue de chaque point après la fusion de la PR #16** (point d'étape du 2026-10-10 ; le texte d'origine des points est conservé plus bas) :

| Point | Issue | Détail |
|---|---|---|
| 1 | **encore à trancher** | textes des exigences 2.5 et 2.7 et de `CLAUDE.md`, « Architecture » : à soumettre au mot près (M53) ; l'ADR 0004 est à compléter par la condition moteur (e) dans la phrase proposée |
| 2 | **encore à trancher** | texte de l'exigence 5.3 (ADR 0005, Conséquences) : même traitement (M53) |
| 3 | **réglé**, devenu #24 | critère (c) accepté pour la branche (M50) ; suite : #24 (consigne d'abord, garde de code ensuite si besoin) |
| 4 | **encore à trancher** (formel) | critère (e) : lecture « pas une fuite » rendue par `expert-cicero` et portée au corps de la PR #16 ; le visa a été donné connaissance prise (M47), mais aucune confirmation expresse du mainteneur n'est consignée |
| 5 | **encore à trancher** | rattachement de #21 : proposé à la branche B2 du § 2.2 (et non plus à la branche non-régression) |
| 6 | **devenu #29** | commentaire de `_message_key`, faux site, tests de l'annonce après `[send-retry]` / `[send-resume]` |
| 7 | **devenu #27** | `__pycache__` et `exporter_patchs.sh --verifier` ; cause toujours présente à `449f02d` (`outils/exporter_patchs.sh:28`, `find . -type f` sans exclusion ; relu le 2026-10-10) |
| 8 | **devenu #25** | sortie de Claude de type inattendu |
| 9 | **devenu #28** | script de concordance documentation ↔ code |
| 10 | **devenu #29** | en-tête périmé de `pseudo_commitments.py`, joint au même commit |
| 11 | **réglé** | complément ajouté au corps de #22 (M52 ; relu le 2026-10-10) |
| 12 | **devenu #26** pour la mesure ; **encore à trancher** pour la marge | commentaire posé sur #13 pour le printemps 1901 (M52) ; garder ou revoir 0,05 : décision du mainteneur après #26 |
| 13 | **réglé** | `Closes #12` retiré de la PR #16, #12 ouverte (M49) ; les deux mesures restent à faire (§ 2.1) |

Texte d'origine (avant la fusion). Signalées par `architect`, non décidées. Chacune se tranchait avant la sortie du brouillon de la PR #16, sauf mention contraire.

1. **Textes proposés par l'ADR 0004** (Conséquences, « Textes à rouvrir ») : `docs/exigences.md` 2.5 (règle à trois conditions, texte d'`expert-cicero`) et 2.7 (bilan des propres promesses du bot) ; `CLAUDE.md`, « Architecture » (phrase du retour *dialogue → moteur*, nommant `betray`). Le texte des exigences et de `CLAUDE.md` est au mainteneur ; `docwriter` applique.
2. **Texte de l'exigence 5.3** : garantie « à relecture près » depuis le journal d'envoi (ADR 0005, écart 3) ; formulation proposée dans l'ADR 0005, Conséquences.
3. **Suite à donner au critère (c) de #17** (« aucun label sans conflit »), non tenu sur 1 tirage sur 20 (S1, tirage 14 : `sincere` rempli du plan entier, quatre ordres dont un non énoncé, trahison déclarée et acceptée par le moteur ; même sur-remplissage 3 fois sur 20 en S5, sans trahison — commentaire du 2026-10-10 de la PR #20). Le visa a été donné connaissance prise de ce résultat (M47). Options à départager : accepter en l'état (le label est exact ; ce qui est en cause est un `sincere` plus large que le texte) ; issue hors branche sur la consigne (`sincere` limité aux ordres énoncés dans `reply`) avec mesure ; ou garde de code (un ordre de `sincere` absent du texte de la réponse n'est pas retenu — résultat changé, tableau et visa). Hors branche dans tous les cas ; `expert-cicero` à consulter avant de rédiger l'issue.
4. **Lecture du critère (e)** : 1 réponse sur 100 signalée par le détecteur textuel (S3, tirage 0 : la France citée comme menace, ni la promesse ni l'ordre promis révélés) ; lecture de la session principale « pas une fuite de promesse », **à confirmer par le mainteneur** (commentaire du 2026-10-10 de la PR #20).
5. **Rattachement de #21** (promesse rompue réaffirmée à la puissance trahie ; change un résultat, la consigne) : proposé à la branche non-régression (§ 2), qui passerait à cinq issues ; à défaut, branche propre après la référence de non-régression.
6. **Retouche mineure sans effet sur un résultat**, à l'appréciation de la session principale (correctif rapide ou issue) : commentaire de `_message_key` (« not verified », `claude_dialogue_bot.py:831`) et faux site (un « ? » par caractère) à mettre en concordance avec l'essai réel (émoji stocké `????`) ; test manquant sur l'annonce à la confirmation par `[send-retry]` / `[send-resume]` (ADR 0005, limites connues).

Points ajoutés après la revue finale du 2026-10-10 (`expert-cicero`, `audit`). Aucun n'est corrigé dans la branche et aucune issue n'est créée : texte des issues à proposer par la session, création sur accord du mainteneur (tableau du § 3).

7. **`outils/exporter_patchs.sh --verifier` échoue sur un `__pycache__` laissé sous `cicero/overlay/`** (audit, 2026-10-10). Mécanisme, lu : le contrôle parcourt tous les fichiers de l'overlay (`find . -type f`, `outils/exporter_patchs.sh:27-29`) et compare chacun à `amont/` ; un `.pyc` écrit par un test lancé hors de `tests/verifier.sh` (qui, lui, pose `PYTHONDONTWRITEBYTECODE=1`, `tests/verifier.sh:9`) n'y a pas d'équivalent et donne « Overlay en retard sur amont/ ». Les caches ont été supprimés par la session ; **la cause n'est pas corrigée**. Correction technique (circuit 3, aucun résultat changé) : exclure `__pycache__` du parcours, ou faire poser la variable par les batteries. Correctif rapide possible (un seul domaine, `install:`).
8. **Sortie de Claude de type inattendu** (`claude_dialogue_bot.py:1161-1177`, lu, non exécuté ; antérieur à la branche) : un `reply` qui n'est pas une chaîne est envoyé tel quel (`str(reply)`) ; un `sincere` qui n'est pas une liste n'est pas écarté (une chaîne est parcourue caractère par caractère, un nombre lève une exception), alors que `betray` est validé (lignes 1167-1169). Écarter un `sincere` mal formé change le contenu de `sincere` retenu : résultat, donc tableau et visa. Hors branche.
9. **`tests/verifier.sh` ne contrôle pas la concordance documentaire** (décomptes de tests, numéros de lignes et noms de fonctions cités par la documentation et les ADR). Deux des corrections du jour (ADR 0005 : « douze tests », ordre INSERT / Redis) auraient été prises par un tel contrôle. Principe 7 des workflows (« un contrôle récurrent sans script en appelle un ») : issue à proposer, branche non-régression ou exploitation.
10. **En-tête de `pseudo_commitments.py` périmé** (`cicero/overlay/fairdiplomacy/utils/pseudo_commitments.py:21-27`) : « a separate LLM with no access to the piKL policy » et « bends orders towards words » décrivent l'état d'avant l'ancrage du dialogue sur le plan (`current_plans.json`) et d'avant le champ `sincere`. Commentaire seul, aucun résultat ; le fichier est un overlay, à reporter depuis `amont/`.
11. **Complément proposé à #22** (audit) : une exception dans une partie prive le bot des parties suivantes du cycle — `process_bot` parcourt les parties sans garde par partie (`claude_dialogue_bot.py:1186`), l'exception n'étant attrapée qu'au niveau du bot (lignes 1731-1735), lu ; et l'état n'est pas validé à la lecture pour `replied_ts`, `exchange_counts`, `sincere_by_recipient`, `trust`, `pending_promises`, ni `current_plans.json` quand sa forme est inattendue (constat d'`audit`, **non revérifié** par `architect`). Même sujet que #22 (isolement par partie) : à ajouter au corps de l'issue, sur accord du mainteneur.
12. **Bruit des valeurs et marge de 0,05.** L'estimation « 0,01 au plus » de l'ADR 0004 n'est pas fondée ; trois calculs du 2026-10-10 sur les relevés `m1_3_*` (`expert-cicero`, `docwriter`, `architect`) ne concordent pas entre eux et mêlent bruit et effet de l'engagement (ADR 0004, limites connues, « Bruit des valeurs »). À décider : faire écrire une mesure versionnée (recherches répétées aux mêmes engagements, définition écrite par `expert-cicero`), puis garder ou revoir la marge (M27) ; revoir la marge change un résultat. S'y rattache le poids du renfort au printemps 1901 (ADR 0004, limites connues ; calculé, non observé), à traiter avec #13.
13. **`Closes #12` alors que deux critères ne sont pas mesurés** : A3 (une partie ordinaire se crée et se joue comme avant) et « moins de sept bots : échec propre, rien en base » (issue #12). Le corps de la PR #16 porte `Closes #12` (vérifié le 2026-10-10, `gh pr view 16`) et les cases de l'issue ne sont pas cochées. À trancher **avant la sortie du brouillon** : mesurer les deux critères (session principale, pile démarrée ; « moins de sept bots » demande de retirer un compte bot, à annoncer : M12), ou retirer `Closes #12` de la PR et laisser l'issue ouverte avec ce reste.

## 2. Branches suivantes

### 2.1 Prochaine branche de travail — **proposition d'`architect` du 2026-10-10, non décidée**

Le mainteneur fixe le périmètre (`CLAUDE.md`, « Git et GitHub ») ; rien de ce qui suit n'est engagé tant qu'il ne l'a pas fait. Aucune branche ni PR n'est créée.

- **Nom proposé** : `claude/non-regression`.
- **Objet** : rendre le travail sur les bots mesurable et sans risque — une batterie qui ne se casse plus toute seule, une partie 100 % bots où un message ne lance plus d'échange entre bots, une référence de non-régression, le bruit des valeurs chiffré. **Aucun paramètre ni consigne des bots n'y change** dans une partie ordinaire ; les issues qui changent un comportement (#24, #25, #21, marge) viennent après, pour être mesurées contre cette référence (§ 2.2, B2).
- **Périmètre proposé** (fermé, cinq issues) : #27, #14, une issue à créer (référence de non-régression fonctionnelle), #26, #12 (reste à mesurer).

| Rang | Issue | Tâche | Agent | Circuit | Résultat changé | Exige la pile | Appels à Claude |
|---|---|---|---|---|---|---|---|
| 0 | — | PR brouillon, fiche de branche ; commit préparatoire des reformulations M53 si le mainteneur les a approuvées au mot près (exigences 2.5, 2.7, 5.3 ; `CLAUDE.md`) | session principale, `architect` | 4 | non | non | non |
| 1 | #27 | exclure `__pycache__` du parcours de `outils/exporter_patchs.sh` ; les scripts de `tests/` n'écrivent plus de `.pyc` | `coder` → `audit` | 3 | non | non (`amont/` requis pour la seconde batterie) | non |
| 2 | #14 | garde de l'exigence 2.8 : un bot ne répond pas à une puissance tenue par un bot ; forme à spécifier (ci-dessous) ; tests au banc (`tests/faux_site.py`) | `expert-cicero` et `expert-webdip` spécifient, séparément → `coder` → `audit` → `docwriter` → `expert` valide | 1 | **oui dans une partie 100 % bots** (plus de réponse entre bots) ; **non attendu** dans une partie ordinaire, à mesurer (rang 5) | non pour le code et le banc ; oui pour le contrôle du rang 5 | non au banc ; quelques appels au contrôle du rang 5 |
| 3 | à créer | référence de non-régression fonctionnelle : positions rejouées de la partie 3, grandeurs relevées, tolérances, commande de comparaison ; forme à spécifier (ci-dessous) | `expert-cicero` spécifie → `coder` → `audit` → `docwriter` | 1 | non (elle fixe l'existant) | oui pour la capture (recherches réelles, `cicero-orders` arrêté : M12) ; non pour la comparaison déterministe | non dans la proposition ; une couche « Claude » serait un ajout soumis à accord |
| 4 | #26 | script versionné de mesure du bruit des valeurs (`tests/mesure/`), définition écrite par `expert-cicero` ; recherches répétées aux **mêmes** engagements (16 des 18 paires existantes diffèrent par un engagement fabriqué) | `expert-cicero` définit → `coder` → `audit` | 3, précédé de la définition | non | oui (même campagne de recherches que le rang 3) | non |
| 5 | #12 | deux mesures restantes : A3 (partie ordinaire créée et jouée comme avant) et « moins de sept bots : échec propre, rien en base » ; A3 sert aussi de contrôle à #14 | session principale, sur la pile ; `expert-webdip` relit ; `coder` seulement si une mesure échoue | mesure, sans code attendu | non | oui ; « moins de sept bots » demande de retirer un compte bot : à annoncer (M12) | oui si un message est envoyé dans la partie ordinaire (contrôle de #14) |
| 6 | toutes | documentation de fond, un passage (règle 9), puis revue finale (règle 10) | `docwriter` ; `audit`, les deux experts, `/code-review` | 4 | non | non | non |

**Raisons de l'ordre.**

- **#27 d'abord** : elle fait échouer la seconde batterie de `coder` et d'`audit` dès qu'un test est lancé à la main ; un seul commit, aucun résultat. Variante laissée au mainteneur : la sortir en correctif rapide avant l'ouverture de la branche (la condition « un seul domaine de commit » n'est tenue que si la correction se limite à `outils/exporter_patchs.sh`).
- **#14 avant toute mesure sur la pile** : tant que la garde manque, un message posté dans la partie 3 lance un échange entre bots, chaque réponse appelant Claude (jusqu'à dix réponses par côté, par paire et par phase : `MAX_EXCHANGES_PER_PAIR_PER_PHASE`, `claude_dialogue_bot.py:37` ; filtre actuel sans regard sur l'expéditeur : `claude_dialogue_bot.py:1437-1440`, lu à `449f02d`). Les rangs 3 à 5 travaillent sur cette partie.
- **Référence avant #26 dans le code, une seule campagne sur la pile** : les deux lisent des tables de recherche réelles et demandent `cicero-orders` arrêté ; un seul arrêt annoncé.
- **#12 en dernier** : A3 se mesure sur le code final de la branche et vaut contrôle « partie ordinaire inchangée » pour #14.

**Deux formes à fixer avant le code** (avis d'`architect`, à confirmer par les experts et par le mainteneur) :

- **#14, forme de la garde.** L'issue pose deux options : filtrer les comptes bots, ou faire taire la seule puissance scénarisée. Avis : elles répondent à deux besoins distincts et se composent. (1) Garde de production, toujours active : un bot ne répond pas à un message dont l'expéditeur est une puissance tenue, dans cette partie, par l'un des comptes que le démon de dialogue pilote lui-même (`API_KEYS`, `claude_dialogue_bot.py:28`) — l'information est locale au démon, sans appel à la plateforme (hypothèse de forme, à confirmer par `expert-webdip`). (2) Dispositif d'essai, hors de la branche : une « puissance scénarisée », déclarée par partie, dont les messages sont traités comme ceux d'un joueur et dont le bot se tait ; sans elle, la garde (1) rend impossible tout message scénarisé dans une partie 100 % bots. La branche proposée ne fait que (1) ; (2) est un terme nouveau et une lecture de l'exigence 2.8 à trancher (ADR), reportés à B3. Test de suppression : la garde (1) est un prédicat pur sur (partie, expéditeur), testable au banc sans pile.
- **Référence de non-régression, forme et emplacement.** Avis : deux couches. Couche déterministe, dans la CI : des tables de recherche réelles enregistrées, passées aux fonctions pures (renfort gradué, `order_values`, condition (e), table de décision de #17), sorties comparées à l'identique. Couche répétée, hors CI : recherches du moteur sur position rejouée, comparées avec une tolérance tirée de #26. **Obstacle** : ces tables et positions sont de l'état de partie, que l'exigence 4.3 et `tests/verifier.sh` interdisent dans le dépôt, et les relevés actuels sont hors git pour cette raison (`tests/mesure/LISEZMOI.md`). Décision du mainteneur requise avant le rang 3 (§ 2.3, question 2).

**Variante.** Si le mainteneur veut corriger sans attendre le `sincere` trop large (#24, qui fausse dès aujourd'hui le bilan `own_promises`), #24 peut prendre la place de #12 ; la branche change alors un résultat (consigne), demande une campagne d'appels à Claude (60 au moins : S1, S5 et S2, vingt tirages chacune, compteur à relever) et son tableau se construit sans référence. `architect` ne le recommande pas.

### 2.2 Branches suivantes (proposition du 2026-10-10)

Dans cet ordre, sauf décision contraire du mainteneur. Les noms sont indicatifs.

| Branche | Issues | Motif du regroupement | Dépend de |
|---|---|---|---|
| B2 — `claude/sincere-enonce` | #24, #25, #21, #29 ; plus la marge de 0,05 si le mainteneur la revoit après #26 | Même module (`generate_reply`, consigne et boucle d'envoi de `claude_dialogue_bot.py`) ; #24, #25 et #21 changent un résultat (`sincere`, consigne) : un seul tableau avant / après, une seule campagne d'appels à Claude, un visa ; #25 touche le contrat de sortie `reply` / `sincere` (issue sensible) ; #29 (tests et commentaires, aucun résultat) protège la même boucle d'envoi | B1 : référence de non-régression, bruit chiffré (#26), garde #14 |
| B3 — essais de bout en bout | #9, #15, #28 ; plus la « puissance scénarisée » (issue et ADR à proposer) | Essais fonctionnels sans humain et sans écriture dans les fichiers de production (#9), mesures restées non vérifiées (#15), concordance documentation ↔ code par script (#28) | B1 (#14, partie 100 % bots) ; B2 (contrat de sortie et signature définitifs) |
| B4 — installation reproductible | #6, #7, #8, #13 | inchangé : `Dockerfile` et `install.sh`, une seule reconstruction de l'image ; #13 (λ) à peser avec le commentaire du 2026-10-10 sur le printemps 1901 | B1 (référence : épingler le modèle, retirer les outils ou changer λ change un résultat) ; #13 attend le mainteneur (`needs-info`) |
| B5 — exploitation | #10, #11, #18, #22, #23 | inchangé : durcissement et tenue dans le temps de la pile | B1 pour le redémarrage en cours de phase (#10) |

Dépendances au 2026-10-10. **Ajoutées** : B2 → B1 (référence, #26, #14) ; B3 → B1 et B2. **Retirées** : #21 → non-régression (passe à B2) ; #9 et #15 sortent de la branche non-régression, scindée en B1 et B3 ; exploitation → `claude/promesses` (satisfaite par la fusion). **Inchangées** : installation reproductible → référence de non-régression ; exploitation → non-régression pour #10.

### 2.3 Questions à trancher par le mainteneur (2026-10-10)

1. **Périmètre de la prochaine branche** : la proposition du § 2.1 (cinq issues), sa variante, ou un autre découpage ; nom de la branche.
2. **Référence de non-régression et exigence 4.3** : versionner un petit jeu de positions et de tables de recherche tirées de la partie 3 (partie 100 % bots, sans compte ni message de joueur), avec une exception écrite dans l'exigence 4.3 et dans `tests/verifier.sh` (ADR) ; ou garder ces données hors git et ne versionner que les scripts (la référence n'est alors pas rejouable sur une autre machine) ; ou la limiter à des tables fabriquées par le banc. Création de l'issue correspondante, sur accord.
3. **#14** : forme de la garde (§ 2.1) ; qui vise le changement — il ne touche que les parties 100 % bots : `expert-cicero` selon `CLAUDE.md`, ou le mainteneur comme pour `claude/promesses` ; annonce préalable dans tous les cas (exigence 2.11).
4. **#27** : dans la branche (rang 1) ou en correctif rapide dès maintenant.
5. **Reformulations M53** (exigences 2.5, 2.7, 5.3 ; `CLAUDE.md`, « Architecture », « Rigueur », « Commandes ») : textes à approuver au mot près ; proposées en commit préparatoire de la branche.
6. **Mesure « moins de sept bots » de #12** sur la pile en service (retrait temporaire d'un compte bot) ou sur une base de travail séparée.
7. **Triage** de #21, #22, #23, #24, #25 et #29 (`needs-triage`) : `ready-for-agent` proposé pour toutes.
8. **Rattachement de #21** à B2 ; **lecture du critère (e)** de #17 à confirmer (§ 1.7, points 4 et 5).
9. **Marge de 0,05** : après #26 ; si elle change, à joindre à B2 (résultat, tableau, visa).

État au 2026-10-03 du tableau des branches (remplacé par les § 2.1 et 2.2) : non-régression (#9, #14, #15, référence à créer, #21 proposé), installation reproductible (#6, #7, #8, #13), exploitation (#10, #11, #18, #22, #23).

Dépendances ajoutées le 2026-10-03 : non-régression → `claude/promesses` (remplace « validation du build ») ; installation reproductible → non-régression ; exploitation → `claude/promesses` et non-régression. Dépendance retirée : la ligne « validation du build », faite dans la PR #1 (§ 6). Ajouts de la seconde mise à jour : #14 et #15 → non-régression (#15, point « installation sur une autre machine », peut être levé plus tôt par toute session cloud, sans attendre la branche) ; #13 → installation reproductible, après décision du mainteneur ; #10, point « aucun compte administrateur » : T1 n'a pas créé de compte Admin (M20, script en ligne de commande), le point reste à #10.

Recoupements à connaître :

- #9 et #2, #17 : `test_multiparty.py` dépaquette mal le retour de `_reject_contradictions` ; la signature est touchée dans `claude/promesses` (#2, puis #17 qui ajoute le label en entrée) ; #9 reprend la signature finale, celle que fixe le banc `tests/banc_promesses.py`.
- #14 et #12 : la garde de l'exigence 2.8 n'a de sens que dans la partie 100 % bots ; la question posée à `architect` par #14 (filtre sur les comptes bots ou silence de la seule puissance scénarisée) se tranche au plan de la branche non-régression, avec les positions de `gameID=3` sous la main.
- #11 (point 2) et #5 : un JSON illisible remet le fichier à vide ; la garde posée par T3 sur l'état du bot de dialogue est à reprendre pour `current_plans.json`.
- #11 et #17 : `current_plans.json` reçoit `candidates` (toutes les actions candidates) et `search` (ADR 0004, décision 12) ; le fichier grossit d'autant (2,8 → 9,9 ko par puissance et par phase, passation de la PR #20), à prendre en compte dans la purge des fichiers d'état : issue #23 (créée le 2026-10-10, M48).
- #11 et #5 : `sent_ts` de `claude_dialogue_state.json` croît d'une marque par message envoyé (ADR 0005, « Ce que l'ADR ne règle pas ») ; à purger avec les autres fichiers d'état.
- #22 et #5 : un bot muet par `UnreadableStateFile` laisse son `pending_send` à 0 tentative et reprend l'envoi à la réparation (ADR 0005, décision 1) ; l'isolement par partie doit garder ce comportement.
- #18 et #10 : deux durcissements sans changement de résultat ; #18 est du domaine `repo:` (plus `docs:` pour le README). Le ruleset et les modes de fusion sont déjà appliqués (M41) ; la section « Sécurité du dépôt » du README, à laquelle `CLAUDE.md` renvoie déjà, peut être avancée en correctif rapide `docs:` si le mainteneur le veut, le script de contrôle restant à la branche.
- #10 (aucun compte administrateur créé) et T1 : la partie 100 % bots est réservée à l'administrateur. Si T1 crée ce compte, ce point de #10 est réglé par `claude/promesses` et s'y note.
- #10 (motif du correctif du gamemaster dans l'architecture § 5) : le texte actuel du § 5 donne déjà le motif rectifié (`d843896`, `83e2087`) ; à confirmer par `docwriter`, puis à rayer de l'issue.
- #6 et #7 pendant `claude/promesses` : voir § 1.3, version de la CLI et modèle notés à chaque mesure.

Recoupements ajoutés le 2026-10-10 :

- #14 et #12 (A3) : le contrôle « partie ordinaire inchangée » de #14 et le critère A3 de #12 sont une même mesure.
- #26 et la référence de non-régression : mêmes tables de recherche réelles, mêmes scripts (`tests/mesure/rejeu_moteur.py`), même arrêt de `cicero-orders` ; la tolérance de la couche répétée de la référence vient du chiffre de #26.
- #26, la marge de 0,05 et #13 : le commentaire `claude_dialogue_bot.py:40-41` (« well above the noise ») se corrige avec la mesure ; revoir la marge ou λ change un résultat (B2, B4).
- #24 et #25 : même fonction (`generate_reply`) et même contrat de sortie ; la garde de code de #24 (option 2 de l'issue) et la validation de type de #25 se spécifient ensemble ; #24, option 2, demande un ADR (contrat de sortie).
- #24, #21 et #6, #7 : une mesure sur Claude n'est comparable que si la CLI et le modèle servi n'ont pas changé (mesure du 2026-10-10 : `claude-sonnet-5-5`, CLI 2.1.288) ; sinon la mesure « avant » est refaite.
- #29 et #9 : l'en-tête périmé de `pseudo_commitments.py` est cité par les deux ; #29 le corrige, à rayer de #9 ensuite.
- #9 et la PR #16 : `cicero/overlay/essais/test_multiparty.py:55` dépaquette deux valeurs du retour de `_reject_contradictions` (constat d'audit de la revue finale), à répercuter sur #9.
- #28 et la règle 9 : le script de concordance sert à chaque passage de `docwriter` ; placé en B3 faute de place, il peut être avancé sur décision du mainteneur.

## 3. Issues hors plan

Aucune : les vingt issues ouvertes (`gh issue list --state open`, 2026-10-10, après la fusion de la PR #16) sont rattachées à une branche **proposée** (§ 2.1 et 2.2 ; aucune n'est décidée). Six portent encore `needs-triage` (#21 à #25, #29) : triage à faire par le mainteneur. Fermées par la PR #16 : #2, #3, #4, #5, #17 (vérifié le 2026-10-10).

| Issue | État | Libellés | Tâche | Branche (proposée, sauf mention) |
|---|---|---|---|---|
| #2 | fermée | `ready-for-agent` | deux ordres contraires : `d353257`, visé | `claude/promesses` (fusionnée) |
| #3 | fermée | `ready-for-agent` | implémentée par #17 : `d353257`, visé | `claude/promesses` (fusionnée) |
| #4 | fermée | `ready-for-agent` | renfort gradué : `b995620`, visé | `claude/promesses` (fusionnée) |
| #5 | fermée | `ready-for-agent` | `e351abf`, `d353257` ; ADR 0005 ; trois écarts acceptés (M45) | `claude/promesses` (fusionnée) |
| #17 | fermée | `enhancement`, `ready-for-agent` | ADR 0004 ; `d353257`, visé ; critère (c) : #24 | `claude/promesses` (fusionnée) |
| #12 | ouverte | `enhancement`, `ready-for-agent` | script livré (`e0624e6`) ; restent A3 et « moins de sept bots » (M49) | B1, rang 5 |
| #27 | ouverte | `bug`, `ready-for-agent` | `__pycache__` et contrôle des patchs | B1, rang 1 (ou correctif rapide) |
| #14 | ouverte | `ready-for-agent` | garde de l'exigence 2.8 | B1, rang 2 |
| à créer | — | `enhancement`, `needs-triage` proposés | référence de non-régression fonctionnelle | B1, rang 3 |
| #26 | ouverte | `enhancement`, `ready-for-agent` | mesure versionnée du bruit des valeurs | B1, rang 4 |
| #24 | ouverte | `bug`, `needs-triage` | `sincere` rempli d'ordres que la réponse n'énonce pas ; change un résultat | B2 |
| #25 | ouverte | `bug`, `needs-triage` | sortie de Claude mal typée ; change un résultat, contrat de sortie | B2 |
| #21 | ouverte | `bug`, `needs-triage` | promesse rompue réaffirmée à la puissance trahie ; change un résultat (consigne) | B2 (rattachement à trancher) |
| #29 | ouverte | `enhancement`, `needs-triage` | tests de l'annonce après renvoi ou reprise ; commentaires périmés | B2 |
| #9 | ouverte | `ready-for-agent` | reprise des essais | B3 |
| #15 | ouverte | `ready-for-human` | quatre mesures ; le point « autre machine » peut être levé par une session cloud à tout moment | B3 |
| #28 | ouverte | `enhancement`, `ready-for-agent` | script de concordance documentation ↔ code | B3 |
| #6 | ouverte | `ready-for-agent` | outils du bot de dialogue, CLI épinglée | B4 |
| #7 | ouverte | `ready-for-agent` | versions à épingler | B4 |
| #8 | ouverte | `ready-for-agent` | mise à jour de `amont/` | B4 |
| #13 | ouverte | `needs-info` | λ : décision du mainteneur (1e-2 documenté, ou 3e-3 avec tableau et visa) ; commentaire du 2026-10-10 sur le printemps 1901 | B4 |
| #10 | ouverte | `ready-for-agent` | durcissements | B5 |
| #11 | ouverte | `ready-for-agent` | arrêt court, purge des fichiers d'état | B5 |
| #18 | ouverte | `ready-for-agent` | reste : section « Sécurité du dépôt » du README, script de contrôle (M41, M44) | B5 |
| #22 | ouverte | `bug`, `needs-triage` | isolement par partie ; corps complété le 2026-10-10 (M52) | B5 |
| #23 | ouverte | `enhancement`, `needs-triage` | croissance de `current_plans.json` | B5 |

Les quatre points « non vérifiés » de la passation de la PR #1 sont devenus l'issue #15. Les constats de la revue finale du 2026-10-10 sont tous devenus des issues ou des compléments d'issue (§ 1.7, tableau d'issue des points 6 à 13) : il ne reste aucun constat sans issue.

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
| M32 | 2026-10-03 | Plusieurs trahisons dans un même message : rejugées jusqu'à stabilité (un N refusé `not_played` est retiré des engagements projetés, son E remis, les autres rejugés), au lieu d'une passe conjointe unique. Mesure d'`audit` : 0 violation sur 29 778 remplacements acceptés (60 000 tables engendrées) ; avant : 29 sur 29 969. Limite assumée : refus par excès (42 des 16 533 refus `not_played` auraient été acceptés seuls). Amende M26. *Note du 2026-10-10 : ces chiffres viennent d'un script non versionné et ne se reproduisent pas ; « acceptés seuls » désignait une autre grandeur ; la décision n'en dépend pas (ADR 0004, décision 12, corrigé le 2026-10-10).* | ADR 0004 (complété), décision 12 |
| M33 | 2026-10-03 | Recherche incrémentale : le renfort se composait quand le moteur repartait de la politique déjà renforcée (lecture d'`expert-cicero`, non mesurée ; impossible à sept bots, possible avec un humain). Corrigé dans le patch du moteur : la politique d'avant renfort est remise dans le résultat de recherche. À contrôler sur une recherche réelle | ADR 0004 (complété), décision 12 ; § 1.3 |
| M34 | 2026-10-03 | Journal : les balises `[betrayal]` et `[revision]` ne sont écrites qu'après confirmation de l'envoi du message (avant, une trahison annulée par une sourdine ou un abandon était comptée) | ADR 0004 (complété), décision 15 |
| M35 | 2026-10-03 | Consigne, texte adopté pour la condition : « Your engine honours the switch only if what it would play when held to the replacing order is worth clearly more (by more than {margin}) than what it would play when held to the promise, and only if it would then actually play the replacing order. » | ADR 0004 (complété), décision 16 |
| M36 | 2026-10-03 | Journal d'envoi (#5), précisions de M17 : deux relectures négatives avant de renvoyer le même texte (décision de prudence de la session principale, signalée au mainteneur) ; un `pending_send` mal formé → le message auquel il répondait est marqué répondu, rien d'autre n'est défait | § 1.4 (T7) ; ADR 0004 (complété), Conséquences ; ADR propre à prévoir |
| M37 | 2026-10-03 | Mesure de #4 : appariée et hors ligne (ancien et nouveau renfort appliqués à la même table réelle, approchée au second ordre) | § 1.3 |
| M38 | 2026-10-03 | Mesures autorisées sur la pile : image actuelle conservée (`cicero-webdip:avant`) puis reconstruction ; 30 recherches réelles ; 160 appels à Claude (trois situations avant et après, 120 ; deux situations propres au nouveau code, après seulement, 40 ; précise M23) ; essai d'envoi réel sur une partie jetable | § 1.3 |
| M39 | 2026-10-03 | Pile relancée par `demarrer.sh` après le redémarrage de la machine | § 1.3 ; M12 |
| M40 | 2026-10-03 | Découpage des commits après la perte des diffs par issue (redémarrage de la machine, dossier temporaire effacé) : un commit pour #4, un commit commun à #2, #17 / #3 et #5, un commit pour les tests ; dérogation à « un commit par issue qui change un résultat ». Le code reste hors git jusqu'au visa, sauvegardé dans `amont/sauvegardes/` | § 1.3 ; PR #16 (à noter) |
| M41 | 2026-10-03 | Réglages de sécurité du dépôt : ruleset « Protection main » importé et modes de fusion restreints au commit de fusion ; issue #18 créée pour le reste (section « Sécurité du dépôt » du README, script de contrôle) | issue #18 ; § 2 et § 3 |
| M42 | 2026-10-03 | Les 160 appels à Claude de la mesure « après » (M23, M38) ne sont pas lancés ce jour-là ; le travail s'arrête juste avant, le code de fond étant écrit, audité et mesuré sur la pile | PR #20, passation du 2026-10-03 (§ 1 et § 3) |
| M43 | 2026-10-03 | Branche temporaire `claude/promesses-en-attente-de-visa`, PR #20 vers la branche de travail, commits de fond sans visa pour les mettre à l'abri et les soumettre : **dérogation** à « une seule branche de travail à la fois » et à « sans visa, rien n'est commité » (`CLAUDE.md`) ; le visa est la fusion de la PR #20 (commit de fusion) | PR #20 (corps et passation) ; § 1.1, rang « mesure après » |
| M44 | 2026-10-03 | Réglages de sécurité du dépôt appliqués (complète M41) : ruleset « Protection main » actif, commit de fusion seul (squash et rebase désactivés), analyse de secrets et protection à la poussée activées, Dependabot (`.github/dependabot.yml` ; PR #19) — vérifié le 2026-10-10 par `gh api` (`secret_scanning: enabled`, `push_protection: enabled`, `allow_squash_merge: false`, `allow_rebase_merge: false`, ruleset 24422687 `active`) | issue #18 (reste : section du README, script de contrôle) ; `.github/ruleset-main.json` |
| M45 | 2026-10-10 | Les trois écarts de #5 au critère d'origine de T7 sont **acceptés** : l'engagement est lisible par le moteur pendant l'incertitude d'un envoi (jusqu'à sept cycles) ; le message est marqué répondu à l'abandon ; le risque de doublon n'est pas nul (renvoi après deux relectures négatives, message stocké avec retard — cas non exercé) | PR #20, « Décisions du mainteneur du 2026-10-10 » ; ADR 0005, décision 13 ; § 1.4 (T7) |
| M46 | 2026-10-10 | Les 160 appels à Claude sont **lancés** : position rejouée de la partie 3, S1902M, Italie, interlocuteur Autriche, tiers France (modèle servi `claude-sonnet-5-5`, CLI 2.1.288, 0,96 USD). Résultat : critères (b) JSON lisible et (d) labels exacts (31 sur 31) **tenus** ; (c) aucun label sans conflit **non tenu sur 1 tirage sur 20** (`sincere` rempli du plan entier) ; (e) aucune fuite **signalé 1 fois sur 100** par un détecteur textuel (à la lecture, pas une fuite de promesse ; lecture à confirmer, § 1.7) ; (f) consigne + 1 477 caractères | PR #20, commentaire du 2026-10-10 ; relevés hors git (`amont/mesure/resultats/m3_*`) |
| M47 | 2026-10-10 | **Visa** du code de fond de #2, #3, #4, #5 et #17 par la fusion de la PR #20 (`9ac8511`), connaissance prise du résultat de M46 ; `main` ensuite fusionnée dans `claude/promesses` (`ab872ab`) | `9ac8511` ; § 1 et § 1.1 |
| M48 | 2026-10-10 | Création des issues #21 (promesse rompue réaffirmée à la puissance trahie), #22 (fichier d'engagements mal formé : isolement par partie), #23 (croissance de `current_plans.json`), proposées à la passation du 2026-10-03 ; libellés `needs-triage` posés, triage à faire | issues #21, #22, #23 ; § 2 et § 3 |
| M49 | 2026-10-10 | **#12 n'est pas fermée par la PR #16** : mot-clé de fermeture retiré du corps de la PR ; script livré et documenté, critères A3 (partie ordinaire inchangée) et « moins de sept bots : échec propre » non mesurés. Vérifié après la fusion : #12 `OPEN` | PR #16 (corps, passation du 2026-10-10) ; § 1 et § 2.1 |
| M50 | 2026-10-10 | Critère (c) de #17 (« aucun label sans conflit »), non tenu sur 1 tirage sur 20 : **accepté pour la branche** `claude/promesses` ; suite dans l'issue #24 (consigne, puis remesure) | PR #16 (corps) ; issue #24 ; § 1.7, point 3 |
| M51 | 2026-10-10 | **Sortie du brouillon** de la PR #16 autorisée, puis **fusion** par le mainteneur en commit de fusion : `449f02d` (tête `3dde397`, 2026-10-10 08:49 UTC). #2, #3, #4, #5 et #17 fermées par la fusion (vérifié) ; mise à jour de la feuille de route reportée après la fusion (présent point d'étape) | `449f02d` ; § 1 et § 6 |
| M52 | 2026-10-10 | Créations sur accord : issues #24 (`sincere` plus large que la réponse), #25 (sortie de Claude mal typée), #26 (mesure versionnée du bruit des valeurs), #27 (`__pycache__` et contrôle des patchs), #28 (concordance documentation ↔ code par script), #29 (tests de l'annonce après renvoi ou reprise) ; complément au corps de #22 (exceptions de `process_bot`, validation de l'état, `current_plans.json` mal formé) ; commentaire sur #13 (λ au printemps 1901) | issues #24 à #29, #22, #13 ; § 1.7 et § 3 |
| M53 | 2026-10-10 | Reformulations des exigences 2.5 et 2.7 et de `CLAUDE.md`, « Architecture » (ADR 0004, à compléter par la condition moteur), de l'exigence 5.3 (ADR 0005, Conséquences), de `CLAUDE.md`, « Rigueur » (exception pendant un silence du bot) et « Commandes » (la première batterie lance aussi les tests) : **à traiter après la fusion**, textes à soumettre au mot près ; rien n'est modifié à ce jour | passation de la PR #16 (§ 2 et § 3) ; § 1.7, points 1 et 2 ; § 2.3, question 5 |
| M54 | 2026-10-10 | La pile est **laissée en service** après la branche (image construite sur `afc0dfe`, partie 3 en pause) ; M12 reste applicable | passation de la PR #16 (§ 2 et § 5) |

## 5. Escalades, relances et arrêts hors branche

Consultations faites hors de toute branche ouverte (`docs/agents/routage.md`, § 7) ; une consultation Fable compte pour la branche suivante.

| Date | Fiche / modèle / critère déclenché / statut obtenu / suite |
|---|---|
| 2026-10-10 | `architect-approfondi` / opus / point d'étape après la fusion de la PR #16 ; critères signalés : seuil « macro » (branche non-régression scindée, B2 insérée), invariant « rien de local dans le dépôt » et exigence 4.3 en jeu pour la référence, contrat de sortie (#25, #24) / `revue requise` / périmètre et questions du § 2.3 portés au mainteneur ; aucune consultation Fable |

## 6. Branches fusionnées

| Branche | PR | Fusion | Périmètre | Revue finale |
|---|---|---|---|---|
| `claude/promesses` | #16 (et #20, temporaire, M43) | `449f02d` (tête `3dde397`), 2026-10-10 | Logique des promesses : #2, #3, #4, #5, #17 fermées ; #12 livrée, laissée ouverte (M49). Résultats changés : `sincere`, consigne, probabilité des actions, `current_plans.json`, ordre des écritures et des envois ; tableau avant / après dans la PR #20, visa M47 ; ADR 0004 et 0005 | `expert-cicero`, `expert-webdip`, `audit` (complet), `/code-review` (dix constats portés en issues #24 à #29 et complément de #22) ; deux consultations Fable (ADR 0004, ADR 0005) |
| `claude/import-initial` | #1 | `a9566a2` (tête `d84cebc`), 2026-10-03 | Import initial, sans issue préalable : modèle adapté au projet (circuit 4) ; projet reporté dans le dépôt, arbres identiques à l'origine (circuit 3, ADR 0002) ; `Dockerfile` validé par un build complet puis démarrage sur base vide, le 2026-10-03 (circuit 3). Résultats : aucun | `audit`, `expert-webdip`, `docwriter`, `/code-review`, joués par des agents génériques instruits de lire leur fiche ; `architect` non passé ; commits `7b8451d` à `d84cebc` relus par la session principale seule (M9) |
