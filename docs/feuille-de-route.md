# Feuille de route

Tenue par `architect`, après chaque série de PR fusionnées. Chaque mise à jour est datée et cite le SHA de `main` et de la branche de travail.

## 1. Branche de travail en cours

Mise à jour du 2026-10-03 — `main` : `a9566a2` (fusion de la PR #1) ; `claude/promesses` : `a9566a2` (créée, aucun commit propre).

- **Branche** : `claude/promesses` — PR à ouvrir en brouillon dès le premier commit poussé.
- **Objet** : logique des promesses. Périmètre fixé par le mainteneur le 2026-10-03 (M10, M11).
- **Périmètre** (fermé : quatre issues et une issue à créer) :
  - [ ] T1 — option « partie 100 % bots » — #12 (créée le 2026-10-03 sur accord du mainteneur), spécifiée par `expert-webdip` et `expert-cicero`
  - [ ] T2 — protocole de mesure, positions rejouées et mesure « avant » — rattaché à l'issue de T1
  - [ ] T3 — #5, volet technique (écriture atomique de l'état, garde de `load_state`) — résultats : aucun
  - [ ] T4 — #2 — résultat changé (`sincere`)
  - [ ] T5 — #3 — résultat changé (`sincere`, promesse tenue ou abandonnée)
  - [ ] T6 — #4 — résultat changé (probabilité des actions, donc ordres tirés)
  - [ ] T7 — #5, volet de fond (engagement enregistré avant l'envoi, statut HTTP) — résultat changé (`sincere`)
  - [ ] T8 — mesure « après », tableau avant / après unique, visa du mainteneur
  - [ ] T9 — documentation de fond, un passage (règle 9)

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
| 6 | `cicero:` deux ordres contraires d'un même message (#2) | T4 | voir § 1.2 | 2 | oui |
| 7 | `cicero:` promesse antérieure sortie des plans exportés (#3) | T5 | voir § 1.2 | 2 | oui |
| 8 | `cicero:` cible du renfort de probabilité (#4) | T6 | voir § 1.2 | 2 | oui |
| 9 | `cicero:` enregistrement après envoi confirmé, statut HTTP contrôlé (#5) | T7 | voir § 1.2 | 1 | oui |
| — | mesure « après », tableau unique, **visa du mainteneur** ; les rangs 6 à 9 ne sont commités qu'ensuite | T8 | session principale, `expert-cicero` relit le tableau | — | — |
| 10 | `tests:` retrait des marques d'échec attendu devenues des succès | T4 à T7 | `coder` → `audit` | 3 | non |
| 11 | `docs:` un commit par issue | T9 | `docwriter` → `expert` valide le diff | 4 | non |

Raisons de l'ordre :

- **Rang 5 avant la mesure « avant »** : le volet technique de #5 ne change aucun résultat ; le placer avant fait que l'écart avant / après ne contient que les quatre modifications de fond, et protège l'état pendant les essais.
- **#2 avant #3** : même fonction (`_reject_contradictions`, `claude_dialogue_bot.py:163`) ; #2 corrige aussi la clé `by_recipient[None]`, que #3 lirait.
- **#4 ensuite** : autre module (`apply_commitments_to_policy`, `pseudo_commitments.py:171`), côté moteur, indépendant des deux premiers.
- **#5 de fond en dernier** : il déplace le moment où un engagement est enregistré, donc ce que les trois autres voient ; mesuré en dernier, son effet ne se mêle pas au leur.

### 1.2 Circuit de chaque issue

- **#2, #3, #4 — circuit 2 (correction de fond).** Chacune est un écart entre le code et un texte qui fait foi dans le projet : exigence 2.5 et ADR 0003, décision 5, pour #2 et #3 ; tableau du § 4 de `docs/doc/architecture.md` pour #4. Déroulé : `expert-cicero` établit la lecture → le mainteneur tranche (un résultat change) → `coder` → `audit` → `expert-cicero` contrôle la conformité → `docwriter`. Pour #3, l'issue pose deux lectures (tenir ou abandonner) : `expert-cicero` les décrit, le mainteneur tranche. Si l'expert conclut, sur #4, que le texte de référence ne dit rien du cumul par ordre promis, cette partie devient une règle nouvelle et suit le circuit 1.
- **#5, volet de fond — circuit 1 (évolution de fond).** Aucun texte ne fixe l'ordre entre l'enregistrement et l'envoi ; deux règles s'y opposent (l'invariant « l'état écrit sur disque l'est aussitôt » et l'exigence 5.3, « jamais envoyé deux fois »). Question à cheval : `expert-cicero` (sens d'un engagement dont le message n'est pas parti) et `expert-webdip` (statuts de l'API, `post_req`), séparément. `post_req` est un fichier d'amont : le corriger passe par un patch.
- **#5, volet technique — circuit 3.**
- **T1 — circuit 1**, spécifié par les deux experts.

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
| T5 (#3) | Le sort d'une promesse sortie des plans exportés suit la décision du mainteneur ; texte du § 4 de l'architecture, docstring et code concordent ; la mention « écart connu » du § 4 est retirée. |
| T6 (#4) | Sur l'exemple de l'issue (promesses `A MAR - SPA` et `F BRE - ENG`, politique 0,5 / 0,3 / 0,2), les probabilités obtenues sont celles de la règle établie ; la somme vaut 1 ; aucune valeur d'action n'est modifiée (invariant « le moteur décide »). |
| T7 (#5) | Un envoi en échec (erreur réseau, statut 4xx ou 5xx simulés) ne laisse aucun engagement enregistré et ne marque pas le message comme répondu ; un message n'est jamais envoyé deux fois (exigence 5.3). |
| T8 | Tableau complet, chaque ligne expliquée, visé par le mainteneur. |
| T9 | `docs/doc/architecture.md` § 3 et § 4 et `README.md` concordent avec le code final ; diff validé par `expert`. |

### 1.5 Point ouvert de T1 : d'où viennent les messages

Les issues #2 à #5 portent sur des engagements, qui n'existent que s'il y a des messages. Une partie à sept bots sans dialogue donne des positions, pas des promesses. Deux voies, à départager par `expert-cicero` puis par le mainteneur :

- **Voie A — messages injectés par un script**, au nom d'une puissance, sur une position rejouée : le stimulus est fixe, donc comparable avant et après.
- **Voie B — les bots se parlent**, ce que l'exigence 2.8 exclut aujourd'hui.

Constat de lecture, non rejoué : le bot de dialogue répond à tout message reçu, sans regarder si l'expéditeur est un bot (`claude_dialogue_bot.py:547`). Dans une partie à sept bots, un seul message injecté lance donc un échange entre deux bots, borné à dix réponses par paire et par phase (`MAX_EXCHANGES_PER_PAIR_PER_PHASE`, ligne 33). La voie A touche ainsi l'exigence 2.8 dans sa lettre, sauf si l'expéditeur injecté est exclu des réponses. Conséquence sur l'ADR : voir la décision M11 et le compte rendu d'`architect` du 2026-10-03.

### 1.6 Revue finale complète (règle 10)

`audit` (code et batteries), `expert-cicero` (fond des promesses, tableau), `expert-webdip` (patch de webDiplomacy, accès administrateur), `app-review` si une page de webDiplomacy est ajoutée ou modifiée, `docwriter`, puis `/code-review`.

## 2. Branches suivantes

Dans cet ordre, sauf décision contraire du mainteneur.

| Branche | Issues | Motif du regroupement | Dépend de |
|---|---|---|---|
| non-régression | #9, plus une issue à créer (référence de non-régression) | Même dossier (`cicero/overlay/essais/`) et même besoin : des essais qui ne supposent ni la partie 15 ni une action humaine, et qui n'écrivent pas dans les fichiers de production | `claude/promesses` : positions rejouées et partie 100 % bots (T1, T2) ; signature de `_reject_contradictions` fixée par #2 et #3 |
| installation reproductible | #6, #7, #8 | #6 et #7 touchent le `Dockerfile` (une seule reconstruction de l'image) et épinglent ce dont dépend le comportement des bots (CLI, modèle) ; #7 et #8 touchent `install.sh` | non-régression : épingler le modèle ou retirer les outils change un résultat, à mesurer contre une référence |
| exploitation | #10, #11 | Durcissement et tenue dans le temps de la pile : redémarrage, secret, fichiers d'état | `claude/promesses` (#5 : même code de persistance que #11, point 2) ; non-régression pour la question du redémarrage en cours de phase (#10) |

Dépendances ajoutées le 2026-10-03 : non-régression → `claude/promesses` (remplace « validation du build ») ; installation reproductible → non-régression ; exploitation → `claude/promesses` et non-régression. Dépendance retirée : la ligne « validation du build », faite dans la PR #1 (§ 6).

Recoupements à connaître :

- #9 et #2 : `test_multiparty.py` dépaquette mal le retour de `_reject_contradictions` ; toute retouche de cette signature dans `claude/promesses` se répercute sur #9.
- #11 (point 2) et #5 : un JSON illisible remet le fichier à vide ; la garde posée par T3 sur l'état du bot de dialogue est à reprendre pour `current_plans.json`.
- #10 (aucun compte administrateur créé) et T1 : la partie 100 % bots est réservée à l'administrateur. Si T1 crée ce compte, ce point de #10 est réglé par `claude/promesses` et s'y note.
- #10 (motif du correctif du gamemaster dans l'architecture § 5) : le texte actuel du § 5 donne déjà le motif rectifié (`d843896`, `83e2087`) ; à confirmer par `docwriter`, puis à rayer de l'issue.
- #6 et #7 pendant `claude/promesses` : voir § 1.3, version de la CLI et modèle notés à chaque mesure.

## 3. Issues hors plan

Aucune : les dix issues ouvertes (#2 à #11) sont rattachées.

| Issue | Tâche | Branche |
|---|---|---|
| #2 | T4 | `claude/promesses` |
| #3 | T5 | `claude/promesses` |
| #4 | T6 | `claude/promesses` |
| #5 | T3 (technique), T7 (fond) | `claude/promesses` |
| #6 | outils du bot de dialogue, CLI épinglée | installation reproductible |
| #7 | versions à épingler | installation reproductible |
| #8 | mise à jour de `amont/` | installation reproductible |
| #9 | reprise des essais | non-régression |
| #10 | durcissements | exploitation |
| #11 | arrêt court, purge des fichiers d'état | exploitation |
| à créer | T1, T2 — partie 100 % bots | `claude/promesses` |
| à créer | référence de non-régression | non-régression |

Sans issue à ce jour, relevé dans la passation de la PR #1 (« Non vérifié ») : installation sur une autre machine que celle d'origine ; arrêt long réel suivi de `demarrer.sh` ; rafraîchissement de l'interface cliquable par le serveur SSE ; reprise d'un message après un vrai échec d'appel à Claude.

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
| M13 | 2026-10-03 | Organisation : la session démarre dans le dépôt, pour charger les agents de `.claude/agents/` ; les libellés de triage de `CLAUDE.md` sont à créer et à poser — créés le 2026-10-03, posés sur #2 à #11 (session du 2026-10-03, le jeton ayant reçu le droit d'écriture sur les issues) | PR #1, même passation |

## 5. Escalades, relances et arrêts hors branche

Consultations faites hors de toute branche ouverte (`docs/agents/routage.md`, § 7) ; une consultation Fable compte pour la branche suivante.

| Date | Fiche / modèle / critère déclenché / statut obtenu / suite |
|---|---|

## 6. Branches fusionnées

| Branche | PR | Fusion | Périmètre | Revue finale |
|---|---|---|---|---|
| `claude/import-initial` | #1 | `a9566a2` (tête `d84cebc`), 2026-10-03 | Import initial, sans issue préalable : modèle adapté au projet (circuit 4) ; projet reporté dans le dépôt, arbres identiques à l'origine (circuit 3, ADR 0002) ; `Dockerfile` validé par un build complet puis démarrage sur base vide, le 2026-10-03 (circuit 3). Résultats : aucun | `audit`, `expert-webdip`, `docwriter`, `/code-review`, joués par des agents génériques instruits de lire leur fiche ; `architect` non passé ; commits `7b8451d` à `d84cebc` relus par la session principale seule (M9) |
