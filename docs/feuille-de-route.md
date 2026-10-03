# Feuille de route

Tenue par `architect`, après chaque série de PR fusionnées. Chaque mise à jour est datée et cite le SHA de `main` et de la branche de travail.

## 1. Branche de travail en cours

Mise à jour du 2026-10-03 (seconde, après l'ADR 0004) — `main` : `a9566a2` (fusion de la PR #1) ; `claude/promesses` : `7372dcf`, PR brouillon #16. Première mise à jour du même jour : `2d5294f`.

- **Branche** : `claude/promesses` — PR #16, brouillon.
- **Objet** : logique des promesses. Périmètre fixé par le mainteneur le 2026-10-03 (M10, M11), étendu le même jour sur son accord : trahison retirée chez tous les destinataires (avec #2, M19), réponse vide et sourdine (avec #5, M17), issue #17 (M24), qui remplace la tâche T5 telle que spécifiée et implémente #3 ; #3 reste dans le périmètre et est fermée par le même travail.
- **Périmètre** (fermé : six issues, #12, #2, #3, #4, #5, #17) :
  - [x] T1 — option « partie 100 % bots » — #12 : script en ligne de commande (`e0624e6`) ; partie `gameID=3` créée le 2026-10-03, elle avance seule ; critères d'exécution A1 à A5 en cours de levée (dans l'issue)
  - [x] T2 — banc déterministe (`7372dcf` : `tests/banc_promesses.py`, `tests/test_promesses.py`, `tests/mesure_promesses.py`, cibles en échecs attendus) ; la mesure « avant » répétée (appels réels à Claude) reste à faire avant les commits de fond
  - [x] T3 — #5, volet technique (écriture atomique, garde de `load_state`, bot muet sur fichier illisible) — `e351abf` ; résultats : aucun ; réserves mineures d'`audit` reprises avec T7
  - [ ] T4 — #2 — implémenté dans l'arbre de travail, non commité, en audit — résultat changé (`sincere`)
  - [ ] T5 — #17, qui spécifie et implémente #3 (trahison déclarée, mémoire des promesses du bot, index `order_values`) — ADR 0004 — résultat changé (`sincere`, `[betrayal]`, consigne)
  - [ ] T6 — #4 — résultat changé (probabilité des actions, donc ordres tirés)
  - [ ] T7 — #5, volet de fond (journal d'envoi, trois essais, réponse vide, sourdine) — résultat changé (`sincere`)
  - [ ] T8 — mesure « après », tableau avant / après unique, visa du mainteneur
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
| 6 | `cicero:` deux ordres contraires d'un même message, trahison retirée chez tous les destinataires (#2) | T4 | voir § 1.2 | 2 | oui |
| 7 | `cicero:` trahison déclarée, mémoire des promesses du bot, index `order_values` (#17, ferme #3) | T5 | voir § 1.2 | 1 | oui |
| 8 | `cicero:` journal d'envoi, trois essais, réponse vide, sourdine (#5) | T7 | voir § 1.2 | 1 | oui |
| 9 | `cicero:` cible et gradation du renfort de probabilité (#4) | T6 | voir § 1.2 | 2 | oui |
| — | mesure « après », tableau unique, **visa du mainteneur** ; les rangs 6 à 9 ne sont commités qu'ensuite | T8 | session principale, `expert-cicero` relit le tableau | — | — |
| 10 | `tests:` retrait des marques d'échec attendu devenues des succès | T4 à T7 | `coder` → `audit` | 3 | non |
| 11 | `docs:` un commit par issue | T9 | `docwriter` → `expert` valide le diff | 4 | non |

Raisons de l'ordre (révisé le 2026-10-03 d'après `expert-cicero`, après la spécification de #17) :

- **Rang 5 avant la mesure « avant »** : le volet technique de #5 ne change aucun résultat ; le placer avant fait que l'écart avant / après ne contient que les quatre modifications de fond, et protège l'état pendant les essais.
- **#2 avant #17** : même fonction (`_reject_contradictions`, `claude_dialogue_bot.py:163`) ; la règle de #2 (plus d'un ordre entrant pour l'unité : aucun retenu) est la ligne 1 de la table de décision de #17, appliquée avant le label ; #2 corrige aussi la clé `by_recipient[None]`.
- **#17 avec #3** : #17 reprend la décision de #3 (valeur inconnue → la première promesse tient, index `order_values` exporté par `plan_export.py`) et y ajoute la condition du label ; un seul commit, qui ferme les deux issues.
- **#5 de fond avant #4** : #5 déplace le point de persistance des engagements (après envoi confirmé), que #17 utilise pour `own_promises` ; il reste côté bot de dialogue. #4 touche le moteur (`apply_commitments_to_policy`, `pseudo_commitments.py:171`) : le placer en dernier fait que les rejeux moteur ne sont faits qu'une fois, sur l'export définitif des engagements.

### 1.2 Circuit de chaque issue

- **#2, #3, #4 — circuit 2 (correction de fond).** Chacune est un écart entre le code et un texte qui fait foi dans le projet : exigence 2.5 et ADR 0003, décision 5, pour #2 et #3 ; tableau du § 4 de `docs/doc/architecture.md` pour #4. Déroulé : `expert-cicero` établit la lecture → le mainteneur tranche (un résultat change) → `coder` → `audit` → `expert-cicero` contrôle la conformité → `docwriter`. Pour #3, l'issue pose deux lectures (tenir ou abandonner) : `expert-cicero` les décrit, le mainteneur tranche. Si l'expert conclut, sur #4, que le texte de référence ne dit rien du cumul par ordre promis, cette partie devient une règle nouvelle et suit le circuit 1.
- **#5, volet de fond — circuit 1 (évolution de fond).** Aucun texte ne fixe l'ordre entre l'enregistrement et l'envoi ; deux règles s'y opposent (l'invariant « l'état écrit sur disque l'est aussitôt » et l'exigence 5.3, « jamais envoyé deux fois »). Question à cheval : `expert-cicero` (sens d'un engagement dont le message n'est pas parti) et `expert-webdip` (statuts de l'API, `post_req`), séparément. `post_req` est un fichier d'amont : le corriger passe par un patch.
- **#17 (avec #3) — circuit 1 (évolution de fond)**, la règle du label étant nouvelle : spécifiée par `expert-cicero` (issue #17), décidée par le mainteneur (M24), consignée dans l'ADR 0004 → `coder` → `audit` → `docwriter` → `expert-cicero` valide. La table de décision de l'issue fait foi ; chaque ligne est un test du banc.
- **#5, volet technique — circuit 3.**
- **T1 — circuit 1**, spécifié par les deux experts.

Mesure (protocole d'`expert-cicero`, volume approuvé par le mainteneur) : partie déterministe par le banc (appel direct et cycle simulé, `tests/mesure_promesses.py`) ; partie répétée par appels réels à Claude, cinq situations fabriquées à partir d'une position de la partie `gameID=3`, vingt tirages chacune, avant et après : 160 appels. Vingt tirages ne distinguent que de gros écarts (exigence 2.10) ; le tableau le dit.

### 1.3 Tableau avant / après et visa (M10)

Un seul tableau et un seul visa pour #2 à #5, par décision du mainteneur ; les commits restent distincts, un par issue.

- Le tableau a une section par issue. Chaque ligne est expliquée par une seule des quatre modifications ; une ligne inexpliquée est une régression.
- **Lignes déterministes** (mesurées une fois) : appel direct de la fonction corrigée, avec les entrées citées dans l'issue.
- **Lignes sur position rejouée** (répétées) : mêmes positions, mêmes messages reçus, plusieurs tirages **(experts : nombre de positions, de tirages, grandeurs relevées)**.
- Chaque mesure note la version de la CLI Claude Code et le modèle servi : ni l'une ni l'autre n'est épinglée (#6, #7), et l'image est reconstruite entre « avant » et « après ». Si l'une a changé, la mesure « avant » est refaite sur la nouvelle image.
- Les rangs 6 à 9 restent dans l'arbre de travail jusqu'au visa (`CLAUDE.md` : sans visa, rien n'est commité). La session principale conserve hors du dépôt le diff de chaque issue, pour faire quatre commits distincts. Ce travail se fait donc sur le poste local, pas en session cloud.
- Toute reconstruction ou redémarrage de la pile est annoncé au mainteneur avant d'être lancé (M12).

### 1.4 Critères d'acceptation

| Tâche | Critère |
|---|---|
| T1 | A1. Une partie à sept bots se crée et avance jusqu'à la fin d'une année sans action humaine. A2. Un compte ordinaire ne peut pas la créer (requête refusée, mesure citée). A3. Une partie ordinaire (un humain, six bots) se crée et se joue comme avant : même configuration du moteur, mêmes fichiers partagés. A4. Mémoire GPU et nombre d'appels à Claude par phase mesurés à sept bots. A5. Aucun état de partie dans le dépôt (`tests/verifier.sh`). |
| T2 | La procédure rejoue une position sans action humaine et donne, pour #2 à #5, la mesure « avant » ; les tests en échec attendu échouent pour la raison décrite dans l'issue. |
| T3 | Un fichier d'état tronqué ne fait plus boucler le conteneur (essai sur un fichier tronqué exprès) ; écriture par fichier temporaire et `os.replace`, comme `plan_export.py` ; aucun résultat modifié. |
| T4 (#2) | Deux ordres contraires pour une même unité dans une même liste `sincere` : un seul au plus est retenu, selon la règle établie par `expert-cicero` ; plus de clé `by_recipient[None]` ni de `"null"` sérialisé. |
| T5 (#17, #3) | Critères (a) à (g) de l'issue #17 : chaque ligne de la table de décision est un test du banc qui passe, état inchangé dans les cas refusés ; `betray` toujours une liste ; 0 label sur 20 sans conflit, au moins 18 labels exacts sur 20 en conflit ; aucun `reply` ne contient `sincere`, `betray`, une accolade ni la promesse faite à un tiers ; taille de consigne mesurée ; au plus un ordre par unité dans `pseudo_commitments.json`. Pour #3 : valeur inconnue → la première promesse tient ; texte du § 4 de l'architecture, docstring et code concordent ; la mention « écart connu » du § 4 est retirée. |
| T6 (#4) | Sur l'exemple de l'issue (promesses `A MAR - SPA` et `F BRE - ENG`, politique 0,5 / 0,3 / 0,2), les probabilités obtenues sont celles de la règle établie ; la somme vaut 1 ; aucune valeur d'action n'est modifiée (invariant « le moteur décide »). |
| T7 (#5) | Un envoi en échec (erreur réseau, statut 4xx ou 5xx simulés) ne laisse aucun engagement enregistré et ne marque pas le message comme répondu ; un message n'est jamais envoyé deux fois (exigence 5.3). |
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
| exploitation | #10, #11 | Durcissement et tenue dans le temps de la pile : redémarrage, secret, fichiers d'état | `claude/promesses` (#5 : même code de persistance que #11, point 2) ; non-régression pour la question du redémarrage en cours de phase (#10) |

Dépendances ajoutées le 2026-10-03 : non-régression → `claude/promesses` (remplace « validation du build ») ; installation reproductible → non-régression ; exploitation → `claude/promesses` et non-régression. Dépendance retirée : la ligne « validation du build », faite dans la PR #1 (§ 6). Ajouts de la seconde mise à jour : #14 et #15 → non-régression (#15, point « installation sur une autre machine », peut être levé plus tôt par toute session cloud, sans attendre la branche) ; #13 → installation reproductible, après décision du mainteneur ; #10, point « aucun compte administrateur » : T1 n'a pas créé de compte Admin (M20, script en ligne de commande), le point reste à #10.

Recoupements à connaître :

- #9 et #2, #17 : `test_multiparty.py` dépaquette mal le retour de `_reject_contradictions` ; la signature est touchée dans `claude/promesses` (#2, puis #17 qui ajoute le label en entrée) ; #9 reprend la signature finale, celle que fixe le banc `tests/banc_promesses.py`.
- #14 et #12 : la garde de l'exigence 2.8 n'a de sens que dans la partie 100 % bots ; la question posée à `architect` par #14 (filtre sur les comptes bots ou silence de la seule puissance scénarisée) se tranche au plan de la branche non-régression, avec les positions de `gameID=3` sous la main.
- #11 (point 2) et #5 : un JSON illisible remet le fichier à vide ; la garde posée par T3 sur l'état du bot de dialogue est à reprendre pour `current_plans.json`.
- #10 (aucun compte administrateur créé) et T1 : la partie 100 % bots est réservée à l'administrateur. Si T1 crée ce compte, ce point de #10 est réglé par `claude/promesses` et s'y note.
- #10 (motif du correctif du gamemaster dans l'architecture § 5) : le texte actuel du § 5 donne déjà le motif rectifié (`d843896`, `83e2087`) ; à confirmer par `docwriter`, puis à rayer de l'issue.
- #6 et #7 pendant `claude/promesses` : voir § 1.3, version de la CLI et modèle notés à chaque mesure.

## 3. Issues hors plan

Aucune : les quinze issues ouvertes (#2 à #15, #17) sont rattachées et triées (libellés posés le 2026-10-03, M13).

| Issue | Libellés | Tâche | Branche |
|---|---|---|---|
| #2 | `ready-for-agent` | T4 | `claude/promesses` |
| #3 | `ready-for-agent` | T5, fermée par le commit de #17 | `claude/promesses` |
| #4 | `ready-for-agent` | T6 | `claude/promesses` |
| #5 | `ready-for-agent` | T3 (technique, fait), T7 (fond) | `claude/promesses` |
| #12 | `enhancement`, `ready-for-agent` | T1 (fait, critères A1 à A5 à lever) | `claude/promesses` |
| #17 | `enhancement`, `ready-for-agent` | T5 — ADR 0004 | `claude/promesses` |
| #6 | `ready-for-agent` | outils du bot de dialogue, CLI épinglée | installation reproductible |
| #7 | `ready-for-agent` | versions à épingler | installation reproductible |
| #8 | `ready-for-agent` | mise à jour de `amont/` | installation reproductible |
| #13 | `needs-info` | décision du mainteneur (garder 1e-2 documenté, ou revenir à 3e-3 avec tableau et visa) ; documentation dans tous les cas | installation reproductible |
| #9 | `ready-for-agent` | reprise des essais | non-régression |
| #14 | `ready-for-agent` | garde de l'exigence 2.8 ; forme à fixer par `architect` au plan de la branche | non-régression |
| #15 | `ready-for-human` | quatre mesures à exécuter par le mainteneur ou une session avec la pile ; le point « autre machine » peut être levé par une session cloud à tout moment | non-régression |
| #10 | `ready-for-agent` | durcissements | exploitation |
| #11 | `ready-for-agent` | arrêt court, purge des fichiers d'état | exploitation |
| à créer | — | référence de non-régression | non-régression |

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

## 5. Escalades, relances et arrêts hors branche

Consultations faites hors de toute branche ouverte (`docs/agents/routage.md`, § 7) ; une consultation Fable compte pour la branche suivante.

| Date | Fiche / modèle / critère déclenché / statut obtenu / suite |
|---|---|

## 6. Branches fusionnées

| Branche | PR | Fusion | Périmètre | Revue finale |
|---|---|---|---|---|
| `claude/import-initial` | #1 | `a9566a2` (tête `d84cebc`), 2026-10-03 | Import initial, sans issue préalable : modèle adapté au projet (circuit 4) ; projet reporté dans le dépôt, arbres identiques à l'origine (circuit 3, ADR 0002) ; `Dockerfile` validé par un build complet puis démarrage sur base vide, le 2026-10-03 (circuit 3). Résultats : aucun | `audit`, `expert-webdip`, `docwriter`, `/code-review`, joués par des agents génériques instruits de lire leur fiche ; `architect` non passé ; commits `7b8451d` à `d84cebc` relus par la session principale seule (M9) |
