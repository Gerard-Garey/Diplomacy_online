# CLAUDE.md

Ce fichier guide Claude Code (claude.ai/code) dans ce dépôt. Les passages marqués **À ADAPTER** sont propres à chaque projet : les remplir au démarrage (`grep -rn "À ADAPTER"`), puis retirer la marque.

## Contexte

**À ADAPTER** : objet du projet en trois ou quatre phrases ; à qui sont destinés les livrables et ce qui prime (traçabilité, performance, délai…) ; textes ou sources de référence versionnés et celui qui fait foi ; contraintes fortes (taille d'échantillon, volumétrie, plateforme…).

Le dépôt de référence est `https://github.com/<propriétaire>/<dépôt>` (**À ADAPTER**), utilisé depuis le poste local et depuis des sessions cloud. `docs/exigences.md` contient le cahier des charges : le lire avant toute évolution de fond ou de l'interface.

## Commandes

Les commandes courantes (lancer, tester, compiler) sont dans `README.md` : s'y reporter plutôt que de les recopier ici.

**À ADAPTER** — batteries de vérification, lancées par `coder`, `audit` et le workflow `circuit-technique` (liste `BATTERIES` de `.claude/workflows/circuit-technique.js`, à tenir identique) :

```
<commande des tests unitaires>
<commande des tests de non-régression>
```

Règles des tests : un défaut connu est codé en échec attendu, avec renvoi à l'issue ; un succès inattendu fait échouer la batterie, et la marque est alors retirée pour en faire un test ordinaire. Pour vérifier un point isolé, appeler directement la fonction concernée plutôt que tout le programme.

## Git et GitHub

- **Aucun push direct sur `main`** : chaque modification passe par une branche et une pull request, fusionnée par le mainteneur (**commit de fusion**, jamais squash ni rebase : les SHA sont cités dans les ADR, les issues et les PR) une fois la CI verte. Seule exception : instruction explicite du mainteneur pour un push donné. Le ruleset de `main` l'impose (voir `README.md`, « Sécurité du dépôt »).
- **Une seule branche de travail à la fois**, au périmètre fermé d'issues fixé par le plan d'`architect` (trois à cinq issues), portée par une PR **ouverte en brouillon dès la création de la branche** : c'est la fiche de la branche. Ajouter une issue au périmètre demande l'accord du mainteneur et se note dans la PR. Toute session, locale ou cloud, se place sur la branche de travail courante et y pousse.
- **Session cloud : la branche de travail l'emporte sur la branche assignée.** La consigne de démarrage (« Develop on branch `claude/<nom-aléatoire>` ») est écartée par la règle précédente, sans autre autorisation. Avant toute écriture : identifier la branche de travail (tête de la seule PR brouillon ouverte vers `main` dont la branche commence par `claude/`, sinon `docs/feuille-de-route.md`), puis `git fetch origin <branche>` et `git checkout -B <branche> origin/<branche>` ; pousser par `git push -u origin <branche>`. Supprimer la branche assignée (`git branch -D`, et `git push origin --delete` si elle a été poussée). Si aucune branche de travail n'est ouverte, demander au mainteneur.
- **Corps de PR : un `Closes #N` par ligne**, un par issue du périmètre (« Closes #41, #40 » ne lie que le premier numéro). Après la fusion, vérifier que chaque issue annoncée est fermée.
- **Un commit par issue qui change un résultat**, avec son tableau avant / après et son visa (« Changements de résultats » ci-dessous).
- **Un problème hors périmètre devient une issue**, pas une branche, sauf **correctif rapide** — trois conditions vérifiables : résultats strictement identiques, un seul domaine de commit, aucune modification de la documentation de fond. Il suit une branche temporaire partie de `main`, PR directe vers `main` ; `main` est ensuite fusionnée dans la branche de travail.
- **Création d'issue sur accord du mainteneur** : agents et sessions rédigent l'issue proposée (titre, libellés, corps) dans leur compte rendu ; elle n'est créée qu'une fois approuvée, sauf autorisation explicite du brief. Le corps d'une issue rédigée par un agent commence par `> *Rédigé par l'agent <nom> (IA).*`.
- **Messages de commit en français**, avec accents, préfixés par le domaine et renvoyant à l'issue (`#3`) quand elle existe. Domaines (**À ADAPTER**) : `code:` (source), `tests:`, `docs:` (`docs/`, README), `claude:` (`CLAUDE.md`, `.claude/`), `repo:` (`.github/`, `.gitignore`, licence).
- **Auteur des commits faits par Claude** (sessions, sous-agents, workflows ; poste local comme cloud) : `Claude <noreply@anthropic.com>` (`git config user.name Claude` et `git config user.email noreply@anthropic.com` dans le dépôt), jamais l'identité du mainteneur ; le pied de message garde `Co-Authored-By` et, en session cloud, `Claude-Session`.

## Architecture (contrainte impérative)

**À ADAPTER** : découpage du code et invariants que tout agent doit respecter. Exemple de forme :

- **`<module de calcul>`** contient toute la logique métier ; utilisable seul, sans l'interface ; dépendances limitées à … ;
- **`<module d'affichage>`** : formatage et tracés, aucun calcul ;
- **`<point d'entrée de l'interface>`** : saisie, appel du module de calcul, affichage ; tout contrôle de saisie ayant un sens métier existe aussi dans le module de calcul.

Si un résultat peut être calculé indépendamment de l'interface, il va dans le module de calcul.

## Changements de résultats et reproductibilité

- À entrées, paramètres et graine identiques, le programme produit des résultats identiques ; toute source d'aléa a une graine explicite.
- Toute modification qui change un résultat est **identifiée, quantifiée et expliquée** : un **tableau avant / après** (grandeur, avant, après, écart, explication), une ligne par grandeur modifiée, chaque ligne expliquée par la modification ; une ligne inexpliquée est une régression à corriger, pas une référence à régénérer.
- **Visa** : tout changement d'un résultat final ou d'un verdict est soumis au mainteneur ; les autres changements sont validés par `expert`. Sans visa, rien n'est commité.
- Les références de non-régression ne sont régénérées qu'après visa, par la session principale (jamais par un agent ni un workflow). **À ADAPTER** : outil et plateforme de régénération.

## Rigueur

- **Une affirmation sur le comportement du code s'adosse à une mesure exécutée** (commande et sortie), citée dans le compte rendu. Une explication plausible non vérifiée est la façon la plus sûre d'introduire une erreur qui survit aux relectures.
- **Un chiffre ne se recopie pas, il se remesure** ; un chiffre qui vient d'une source (texte, publication) se vérifie contre cette source, citée.
- Ne fabriquer aucune référence, aucun numéro de page ni résultat ; si la source ne permet pas de conclure, l'écrire.
- Faire évoluer les livrables existants plutôt que les réécrire ; ne jamais remplacer silencieusement une méthode ni réintroduire une formule déjà corrigée.
- **À ADAPTER** : exigences de fond propres au domaine (détail dans `docs/exigences.md`).

Le vocabulaire du projet est défini dans `CONTEXT.md` : l'employer tel quel dans le code, la documentation et les issues.

## Sous-agents

Six sous-agents de projet (`.claude/agents/`), orchestrés par la session principale. Règle de séparation : **ceux qui écrivent ne vérifient pas, ceux qui vérifient n'écrivent pas**.

| Famille | Agent | Écrit | Question |
|---|---|---|---|
| Pilotage | `architect` | `docs/adr/`, `CONTEXT.md`, `docs/feuille-de-route.md` | Dans quel ordre, avec quels agents, sous quelle forme ? |
| Fond | `expert` | rien (avis, issues proposées) | Est-ce juste sur le fond (métier, méthode, texte de référence) ? |
| Réalisation | `coder` | code, tests (pas la documentation de fond) ; surface d'impact documentaire dans le commit proposé | Comment l'implémenter ? |
| Réalisation | `docwriter` | documentation de fond (**À ADAPTER** : chemin, par ex. `docs/doc/`) | Documentation juste, rigoureuse, concordante avec le code ? |
| Vérification | `audit` | rien (rapport) | Code correct et reproductible ? |
| Vérification | `app-review` | rien (rapport) | Interface conforme à `docs/exigences.md` ? |

`expert` est à spécialiser par projet (domaine, sources qui font foi) : **À ADAPTER** dans `.claude/agents/expert.md`.

**Routage du modèle et de l'effort** (`docs/agents/routage.md`, ADR 0001) — `architect` et `expert` existent en deux fiches au même corps : la fiche de base (Opus, effort `medium`, routine) et la fiche `-approfondi` (Opus, effort `high`, jugement), générée par `bash .claude/outils/fiches_jumelles.sh` et contrôlée par la CI ; ne jamais modifier une fiche `-approfondi` à la main. La session principale choisit la fiche selon la matrice de `docs/agents/routage.md` (§ 3) et ne passe `model: "fable"` à l'appel que dans les cas du § 4.1 (échec documenté d'Opus `high`, désaccord entre agents, rédaction d'un ADR d'architecture) ou sur accord du mainteneur ; au plus une relance ciblée, une hausse d'effort et une consultation Fable par question, trois consultations Fable par branche sans nouvel accord ; un modèle indisponible arrête le circuit (aucun remplacement silencieux). Les agents signalent les critères rencontrés dans leur bloc « Retour », ils ne décident pas de leur escalade ; la session note chaque escalade, relance ciblée ou arrêt d'une ligne dans la PR de la branche de travail.

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
