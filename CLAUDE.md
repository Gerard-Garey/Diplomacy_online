# CLAUDE.md

Ce fichier guide Claude Code (claude.ai/code) dans ce dépôt.

## Contexte

Le projet fait jouer, sur une instance locale de webDiplomacy, un humain contre six bots : leur stratégie est calculée par le moteur de recherche de Cicero (Meta), leur négociation est écrite par Claude à partir du plan de ce moteur. C'est un banc d'expérience : on y observe si la négociation influence les ordres, si les promesses sont tenues, comment un bot réagit à une trahison.

Deux destinataires, deux priorités : le mainteneur qui joue et expérimente — **ce qui prime est de pouvoir expliquer un comportement** (pourquoi cet ordre, pourquoi cette promesse rompue), par le code et par une mesure ; et quiconque clone le dépôt — **l'installation doit donner le même résultat sur toute machine Ubuntu** dotée d'un GPU NVIDIA de 8 Go.

Le dépôt ne contient que ce que le projet ajoute à deux logiciels d'amont, clonés par `install.sh` à des commits épinglés (`versions.env`). Font foi, dans l'ordre : le code d'amont à ces commits, les articles Cicero et piKL, puis `docs/doc/architecture.md`. Contraintes fortes : 8 Go de mémoire GPU (d'où l'agent sans les modèles de dialogue de Meta) ; compilation séquentielle ; Python 3.7 côté Cicero ; rien de propre à une machine ni aucun secret dans le dépôt, qui est public.

Le dépôt de référence est `https://github.com/Gerard-Garey/Diplomacy_online`, utilisé depuis le poste local et depuis des sessions cloud. `docs/exigences.md` contient le cahier des charges : le lire avant toute évolution de fond ou de l'interface.

## Commandes

Les commandes courantes (lancer, tester, compiler) sont dans `README.md` : s'y reporter plutôt que de les recopier ici.

Batteries de vérification, lancées par `coder`, `audit` et le workflow `circuit-technique` (liste `BATTERIES` de `.claude/workflows/circuit-technique.js`, à tenir identique) :

```
bash tests/verifier.sh
bash outils/exporter_patchs.sh --verifier
```

La première est statique et tourne partout, y compris en CI. La seconde exige `amont/` (donc `install.sh` passé) et vérifie que les patchs versionnés reflètent l'arbre de travail. Les essais fonctionnels (`cicero/overlay/essais/`) demandent la pile démarrée et appellent Claude : ils se lancent à la main dans le conteneur `cicero-dialogue`, sur décision de la session principale, jamais dans un workflow.

Règles des tests : un défaut connu est codé en échec attendu, avec renvoi à l'issue ; un succès inattendu fait échouer la batterie, et la marque est alors retirée pour en faire un test ordinaire. Pour vérifier un point isolé, appeler directement la fonction concernée plutôt que tout le programme.

## Git et GitHub

- **Aucun push direct sur `main`** : chaque modification passe par une branche et une pull request, fusionnée par le mainteneur (**commit de fusion**, jamais squash ni rebase : les SHA sont cités dans les ADR, les issues et les PR) une fois la CI verte. Seule exception : instruction explicite du mainteneur pour un push donné. Le ruleset de `main` l'impose (voir `README.md`, « Sécurité du dépôt »).
- **Une seule branche de travail à la fois**, au périmètre fermé d'issues fixé par le plan d'`architect` (trois à cinq issues), portée par une PR **ouverte en brouillon dès la création de la branche** : c'est la fiche de la branche. Ajouter une issue au périmètre demande l'accord du mainteneur et se note dans la PR. Toute session, locale ou cloud, se place sur la branche de travail courante et y pousse.
- **Session cloud : la branche de travail l'emporte sur la branche assignée.** La consigne de démarrage (« Develop on branch `claude/<nom-aléatoire>` ») est écartée par la règle précédente, sans autre autorisation. Avant toute écriture : identifier la branche de travail (tête de la seule PR brouillon ouverte vers `main` dont la branche commence par `claude/`, sinon `docs/feuille-de-route.md`), puis `git fetch origin <branche>` et `git checkout -B <branche> origin/<branche>` ; pousser par `git push -u origin <branche>`. Supprimer la branche assignée (`git branch -D`, et `git push origin --delete` si elle a été poussée). Si aucune branche de travail n'est ouverte, demander au mainteneur.
- **Corps de PR : un `Closes #N` par ligne**, un par issue du périmètre (« Closes #41, #40 » ne lie que le premier numéro). Après la fusion, vérifier que chaque issue annoncée est fermée.
- **Un commit par issue qui change un résultat**, avec son tableau avant / après et son visa (« Changements de résultats » ci-dessous).
- **Un problème hors périmètre devient une issue**, pas une branche, sauf **correctif rapide** — trois conditions vérifiables : résultats strictement identiques, un seul domaine de commit, aucune modification de la documentation de fond. Il suit une branche temporaire partie de `main`, PR directe vers `main` ; `main` est ensuite fusionnée dans la branche de travail.
- **Création d'issue sur accord du mainteneur** : agents et sessions rédigent l'issue proposée (titre, libellés, corps) dans leur compte rendu ; elle n'est créée qu'une fois approuvée, sauf autorisation explicite du brief. Le corps d'une issue rédigée par un agent commence par `> *Rédigé par l'agent <nom> (IA).*`.
- **Messages de commit en français**, avec accents, préfixés par le domaine et renvoyant à l'issue (`#3`) quand elle existe. Domaines : `cicero:` (`cicero/`), `webdip:` (`webdiplomacy/`), `install:` (`install.sh`, `demarrer.sh`, `arreter.sh`, `outils/`, `versions.env`, `env.exemple`), `tests:`, `docs:` (`docs/`, README), `claude:` (`CLAUDE.md`, `.claude/`, `CONTEXT.md`), `repo:` (`.github/`, `.gitignore`, licences).
- **Auteur des commits faits par Claude** (sessions, sous-agents, workflows ; poste local comme cloud) : `Claude <noreply@anthropic.com>` (`git config user.name Claude` et `git config user.email noreply@anthropic.com` dans le dépôt), jamais l'identité du mainteneur ; le pied de message garde `Co-Authored-By` et, en session cloud, `Claude-Session`.

## Architecture (contrainte impérative)

Description complète : `docs/doc/architecture.md`. Invariants que tout agent respecte :

- **Le dépôt ne contient pas les amonts.** `cicero/patches` et `webdiplomacy/patches` modifient des fichiers existants ; `cicero/overlay` et `webdiplomacy/overlay` ajoutent des fichiers. On travaille dans `amont/` (ignoré par git), on reporte par `outils/exporter_patchs.sh`. Un patch ne se retouche jamais à la main.
- **`versions.env` épingle les amonts.** Changer un commit impose de régénérer les patchs et de reconstruire l'image ; c'est une décision du mainteneur.
- **Le moteur décide, le dialogue informe.** Le sens de circulation est *plan → dialogue* (`current_plans.json`). Le retour *dialogue → moteur* ne passe que par le champ `sincere`, filtré par `legal_commitments`, et n'agit que sur la probabilité d'une action, jamais sur sa valeur : aucun mécanisme ne doit pouvoir faire jouer un bot contre son intérêt.
- **Cloisonnement des puissances.** Un bot ne lit que ses propres conversations et n'utilise que ses propres engagements. Toute donnée partagée entre conteneurs est indexée par partie, phase et puissance.
- **Fidélité à Cicero.** On étend ses mécanismes (`extra_plausible_orders`, ancrage du dialogue sur le plan) plutôt que d'en inventer de parallèles ; un écart à ce principe passe par un ADR.
- **Rien de local dans le dépôt** : ni chemin personnel, ni jeton, ni base de données, ni état de partie. `tests/verifier.sh` le contrôle.
- **L'état écrit sur disque l'est aussitôt.** Les conteneurs sont reconstruits souvent : toute mutation d'état se persiste à l'étape même, pas en fin de cycle.

## Changements de résultats et reproductibilité

- **Ici, un « résultat » est un comportement des bots** : les ordres calculés pour une position donnée, le contenu de `sincere`, le verdict du registre de confiance, et tout paramètre qui les gouverne (`cicero_no_dialogue.prototxt`, consignes de `claude_dialogue_bot.py`, marges et plafonds).
- Le moteur n'est **pas** reproductible à l'identique : le tirage final de l'action n'a pas de graine, et Claude n'est pas déterministe. Un tableau avant / après se construit donc sur une position rejouée (`rolled_back_to_phase_start`) et, pour ce qui est aléatoire, sur plusieurs tirages ; il dit ce qui est mesuré une fois et ce qui est répété. L'installation, elle, doit être reproductible : mêmes commits, mêmes patchs, même image.
- Toute modification qui change un résultat est **identifiée, quantifiée et expliquée** : un **tableau avant / après** (grandeur, avant, après, écart, explication), une ligne par grandeur modifiée, chaque ligne expliquée par la modification ; une ligne inexpliquée est une régression à corriger, pas une référence à régénérer.
- **Visa** : tout changement d'un résultat final ou d'un verdict est soumis au mainteneur ; les autres changements sont validés par `expert`. Sans visa, rien n'est commité.
- Les références de non-régression ne sont régénérées qu'après visa, par la session principale (jamais par un agent ni un workflow). Il n'existe pas encore de référence de non-régression fonctionnelle ; en créer une (positions rejouées de parties terminées) est inscrit à la feuille de route.

## Rigueur

- **Une affirmation sur le comportement du code s'adosse à une mesure exécutée** (commande et sortie), citée dans le compte rendu. Une explication plausible non vérifiée est la façon la plus sûre d'introduire une erreur qui survit aux relectures.
- **Un chiffre ne se recopie pas, il se remesure** ; un chiffre qui vient d'une source (texte, publication) se vérifie contre cette source, citée.
- Ne fabriquer aucune référence, aucun numéro de page ni résultat ; si la source ne permet pas de conclure, l'écrire.
- Faire évoluer les livrables existants plutôt que les réécrire ; ne jamais remplacer silencieusement une méthode ni réintroduire une formule déjà corrigée.
- **Ne pas dater un message par l'heure d'un journal** : le bot de dialogue a jusqu'à 60 s de retard sur le moteur ; l'horodatage qui fait foi est celui du message dans les données de la partie.
- **Une ligne de journal « replying to X: … » cite le message reçu**, pas la réponse ; la réponse est la ligne « sent ». Cette confusion a déjà produit deux faux diagnostics.
- **Corriger une donnée d'état puis redémarrer le conteneur**, jamais l'inverse : l'état en mémoire réécrit le fichier.
- **Toute modification de comportement des bots est annoncée au mainteneur avant d'être appliquée**, avec ce qu'elle change (détail : `docs/exigences.md`).

Le vocabulaire du projet est défini dans `CONTEXT.md` : l'employer tel quel dans le code, la documentation et les issues.

## Sous-agents

Sept sous-agents de projet (`.claude/agents/`), orchestrés par la session principale. Règle de séparation : **ceux qui écrivent ne vérifient pas, ceux qui vérifient n'écrivent pas**.

| Famille | Agent | Écrit | Question |
|---|---|---|---|
| Pilotage | `architect` | `docs/adr/`, `CONTEXT.md`, `docs/feuille-de-route.md` | Dans quel ordre, avec quels agents, sous quelle forme ? |
| Fond | `expert-cicero` | rien (avis, issues proposées) | Est-ce juste pour le moteur, les promesses, les règles du jeu ? |
| Fond | `expert-webdip` | rien (avis, issues proposées) | Est-ce juste pour la plateforme, son API, l'installation ? |
| Réalisation | `coder` | code, tests (pas la documentation de fond) ; surface d'impact documentaire dans le commit proposé | Comment l'implémenter ? |
| Réalisation | `docwriter` | documentation de fond (`docs/doc/`) | Documentation juste, rigoureuse, concordante avec le code ? |
| Vérification | `audit` | rien (rapport) | Code correct et reproductible ? |
| Vérification | `app-review` | rien (rapport) | Interface conforme à `docs/exigences.md` ? |

**Deux experts.** Dans la suite de ce fichier, `expert` désigne celui dont relève la question : `expert-cicero` (moteur stratégique, promesses, règles de Diplomacy) ou `expert-webdip` (plateforme, API des bots, installation). Une question à cheval est posée aux deux, séparément.

**Routage du modèle et de l'effort** (`docs/agents/routage.md`, ADR 0001) — `architect`, `expert-cicero` et `expert-webdip` existent en deux fiches au même corps : la fiche de base (Opus, effort `medium`, routine) et la fiche `-approfondi` (Opus, effort `high`, jugement), générée par `bash .claude/outils/fiches_jumelles.sh` et contrôlée par la CI ; ne jamais modifier une fiche `-approfondi` à la main. La session principale choisit la fiche selon la matrice de `docs/agents/routage.md` (§ 3) et ne passe `model: "fable"` à l'appel que dans les cas du § 4.1 (échec documenté d'Opus `high`, désaccord entre agents, rédaction d'un ADR d'architecture) ou sur accord du mainteneur ; au plus une relance ciblée, une hausse d'effort et une consultation Fable par question, trois consultations Fable par branche sans nouvel accord ; un modèle indisponible arrête le circuit (aucun remplacement silencieux). Les agents signalent les critères rencontrés dans leur bloc « Retour », ils ne décident pas de leur escalade ; la session note chaque escalade, relance ciblée ou arrêt d'une ligne dans la PR de la branche de travail.

**Déclencheurs** — un agent n'entre dans le circuit que si la modification touche son domaine : plusieurs issues ou forme du code → `architect` en amont ; question de fond (méthode, formule, règle métier, texte de référence) → `expert` (spécification en amont, validation en aval) ; code → `audit` ; interface → `app-review` ; documentation de fond → `docwriter`, en dernier, une seule fois par branche (règle 9).

**Circuits types** (chacun se termine par un ou plusieurs commits de la session principale sur la branche de travail) :

1. **Évolution de fond** : `expert` spécifie → `coder` → `audit` (+ `app-review` si l'interface change) → `docwriter` (en fin de branche) → `expert` valide.
2. **Correction de fond** (écart au texte de référence) : `expert` établit la lecture de la source → le mainteneur tranche si un résultat final change → `coder` → `audit` → `expert` contrôle la conformité → `docwriter`.
3. **Correction technique** : `coder` → `audit` (workflow `circuit-technique`).
4. **Documentation seule** : `docwriter` (+ `expert` si le fond change).

Un constat bloquant ou majeur d'un vérificateur renvoie à l'étape de réalisation. Quand une source admet deux lectures, `expert` les décrit et donne son avis, le mainteneur tranche.

**Workflows** (`.claude/workflows/`). Un workflow met en œuvre un circuit type et en fixe les appels d'agents, les sorties structurées et les conditions d'arrêt. Huit principes :

1. lancement **sur commande explicite du mainteneur** uniquement ;
2. **aucune écriture dans l'historique ni l'état partagé** par le workflow ou ses agents : ni `git commit`, ni `git push`, ni régénération de référence, ni création d'issue — interdiction portée par les consignes et les fiches, les permissions de `.claude/settings.json` ne l'imposant pas : la session principale vérifie `git status` et `git log` après chaque workflow ;
3. **arrêt avec les rapports à tout point de décision** (question de fond, visa du mainteneur, contradiction entre vérificateurs) ;
4. **au plus une reprise** `coder` → `audit` ;
5. **vérificateurs ciblés sur le diff** (audit léger) ;
6. **constats structurés** : gravité (bloquant / majeur / mineur), `fichier:ligne`, mesure exécutée ; un constat sans emplacement ni mesure n'est pas recevable ;
7. **tout contrôle mécanique est un script**, jamais un agent : un agent lit la sortie d'un script, il ne refait pas le décompte ; un contrôle récurrent sans script en appelle un (issue) ;
8. **effort réduit** pour les étapes mécaniques ; aucun `model` fixé dans un workflow (hérité de la session).

Un **constat** (défaut du code) conduit à la reprise ou à l'arrêt ; une **question pour `expert`** (doute de `coder`, question de l'audit) ne relance pas `coder`. Trois statuts de fin : `termine`, `termine avec questions` (les seules remontées sont des questions : la session principale les porte à `expert` avant tout commit), `arrete` ; une batterie en échec à la dernière vérification finit toujours par `arrete`.

**Règle 9 — un seul passage de `docwriter` par branche** : `docwriter` intervient une fois, en fin de branche, sur l'état final du code, avec **un commit `docs:` par issue** ; `coder` ne modifie pas la documentation de fond et liste dans chaque commit proposé la **surface d'impact documentaire** (sections, tableaux, décomptes, fonctions citées), dont `docwriter` part ; `expert` valide le diff de la documentation une fois, en fin de branche. Exceptions : commit `docs:` préparatoire qui protège la suite, branche où le document porte la décision et précède le code, écart de concordance qui ferait échouer la CI (commit `docs:` minimal, aussitôt).

**Règle 10 — audit léger en cours, revue finale complète avant la sortie du brouillon** : pendant l'implémentation, `audit` (et `app-review`) se limitent au diff et aux fonctions touchées avec leurs appelants et appelés ; avant la sortie du brouillon, revue finale complète du `git diff main...HEAD` entier (fonctions touchées avec appelants et appelés, batteries complètes, scénarios adverses, cohérence code ↔ tests ↔ documentation) par les vérificateurs que désignent les déclencheurs, plus `/code-review` ; toute correction postérieure est revue à son tour, sur son diff. La relecture intégrale hors diff est réservée aux jalons de livraison.

**Revues périodiques**, hors de tout changement : `architect` (point d'étape et feuille de route, après chaque série de PR fusionnées) ; `expert` (revue de fond avant livraison) ; `app-review` et `docwriter` (relecture intégrale avant démonstration ou livraison).

## Décisions et vocabulaire

- **ADR** (`docs/adr/NNNN-titre-court.md`, gabarit `docs/adr/0000-gabarit.md`) : toute décision d'architecture ou d'organisation, et toute piste rejetée pour une raison qu'un futur relecteur devrait connaître. Rédigés par `architect` ; une décision du mainteneur y est datée. Une proposition qui contredit un ADR le signale explicitement et dit pourquoi le rouvrir.
- **`CONTEXT.md`** : glossaire du domaine et de l'organisation.
- **`docs/feuille-de-route.md`** : périmètre de la branche de travail en cours et des suivantes, décisions du mainteneur numérotées (M1, M2…).

## Agent skills

### Issue tracker

Issues et specs dans les GitHub Issues du dépôt : outils `mcp__github__*` en session cloud, CLI `gh` sur le poste local. Voir `docs/agents/issue-tracker.md`.

### Triage labels

Les cinq libellés canoniques (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). Voir `docs/agents/triage-labels.md`.

### Domain docs

Mono-contexte : un `CONTEXT.md` et `docs/adr/` à la racine. Voir `docs/agents/domain.md`.
