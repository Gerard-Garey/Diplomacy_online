---
status: accepted
date: 2026-10-10
---

# Un jeu d'essai figé, tiré d'une partie 100 % bots, est versionné sous `tests/reference/` ; l'état d'exécution d'une instance reste interdit dans le dépôt

Consigne la décision du mainteneur du 2026-10-10 (PR #30, « Décisions du mainteneur du 2026-10-10 » ; issue #31) : la référence de non-régression fonctionnelle repose sur un **jeu réduit versionné**, par exception écrite à l'exigence 4.3. Rédigé par `architect` (routage Fable, `docs/agents/routage.md` § 4.1.3 ; première consultation Fable de la branche `claude/non-regression`). Le code est lu à `b52bcc8`, tête de la branche ; les relevés cités sont ceux d'`amont/mesure/resultats/` (hors git), remesurés le jour même quand la mesure ne demande pas la pile.

## Contexte

**Il n'existe pas de référence de non-régression fonctionnelle** (`CLAUDE.md`, « Changements de résultats et reproductibilité », dernier point). Les issues qui changent un comportement des bots (#24, #25, #21, marge de 0,05 après #26, #13) doivent se mesurer contre une référence ; aujourd'hui chaque tableau avant / après se reconstruit sur la pile, à la main, et les calculs sur relevés faits hors git ne concordent pas entre eux (ADR 0004, « Limites connues », « Bruit des valeurs » : trois scripts non versionnés, trois grandeurs).

**L'obstacle est une règle du projet.** L'exigence 4.3 (« ni état de partie ») et l'invariant « Rien de local dans le dépôt » (`CLAUDE.md`, « Architecture ») interdisent l'état de partie dans le dépôt ; `tests/verifier.sh:63-72` le contrôle par trois tests : chemin personnel (`/home/<nom>/`), jeton (`sk-ant-…`, `CLAUDE_CODE_OAUTH_TOKEN`), et **cinq noms de fichiers** (`.sql.gz`, `.sqlite`, `.dump`, `claude_dialogue_state.json`, `config.php`). Rien ne contrôle le contenu d'un fichier JSON de tests. Pour cette raison les relevés de la branche `claude/promesses` sont restés hors git (`tests/mesure/LISEZMOI.md` : « Les résultats contiennent de l'état de partie et ne sont pas versionnés ») ; une référence hors git n'est rejouable que sur le poste du mainteneur, ce qui contredit l'objet du dépôt (exigences 1.3 et 4.2 : installable et vérifiable par un tiers depuis le seul dépôt).

**Ce que la référence demande** (spécification d'`expert-cicero`, issue #31) : l'historique des ordres de la partie 3 (partie 100 % bots créée par #12, en pause depuis le 2026-10-03), d'où `pydipcc` reconstruit chaque position ; et, par position et par puissance, la table de recherche réduite aux quatre clés que le bot de dialogue lit (`plans`, `order_values`, `candidates`, `search`), plus les arguments bruts d'`export_plans` (`action_values`, `prior_policy`, `regularize_lambda`, `boost`, `max_prob` ; `plan_export.py:46-55`) pour rejouer l'export lui-même.

**Faits mesurés par `expert-cicero` le 2026-10-10** (cités comme tels ; ceux qui demandent la pile ne sont pas revérifiés) :

1. aucun contenu personnel ni secret dans les relevés `m1_3_*.jsonl` (recherche par motifs : chemins, clés, jetons, courriels, adresses, noms d'utilisateur) ni dans le statut de la partie ;
2. l'historique des ordres seul pèse **4 046 octets**, et `pydipcc` en reconstruit une position identique à celle du site dans **12 phases sur 12** (*non revérifié sans la pile*) ;
3. tables réduites, sans identifiant de partie, horodatage ni donnée de machine : **3,6 ko par table**, environ **150 ko pour 42 tables** (7 puissances × 6 phases de mouvement), **300 ko** avec les arguments bruts d'`export_plans` ;
4. l'arrondi du gain à 4 décimales (au lieu de 5) change **2 verdicts sur 30 tables réelles et 0 sur 3 000 tables fabriquées** ; à l'inverse, le multiplicateur de renfort 3 → 2 change **0 verdict sur les tables réelles et 1 036 sur les fabriquées** (tableau de mutations) ;
5. `tests/verifier.sh` ne refuse que cinq noms de fichiers ;
6. un fragment de la partie 3 est **déjà versionné** : `tests/mesure/rejeu_moteur.py:156-168`, classe `MoteurDoublure`, six actions et leurs valeurs de l'Italie en S1902M, « plans de ITALY, partie 3, S1902M (current_plans.json de production) », depuis `afc0dfe` (branche `claude/promesses`, visée M47).

**Remesuré par `architect` le 2026-10-10** sur `amont/mesure/resultats/m1_3_*.jsonl` (14 fichiers, 34 enregistrements, 30 recherches réelles ; script en ligne, `python3 -I`) :

- motifs `/home/`, `sk-ant`, `OAUTH`, courriel, `api_key`, `password`, `token`, nom d'utilisateur du poste : **0 ligne** sur 34 (fait 1 confirmé pour les relevés) ;
- le `statut` relevé ne contient que `gameID`, `gameOver`, `phase`, `phase_courante`, `processStatus`, `turn`, deux témoins booléens et un compteur de messages (0) : aucun compte, aucun message (fait 1 confirmé pour le statut) ;
- tables réduites aux quatre clés : **4 025 octets** en moyenne (min 2 866, max 6 493 ; total 120 746 octets pour 30), soit **169 ko** extrapolés à 42 tables — même ordre de grandeur que le fait 3 (l'écart de 10 % tient à la façon de compter, l'expert ayant pu retirer `rank` et `cost_vs_best`, recalculables) ;
- **ce qu'un relevé contient en plus et que la référence ne doit pas reprendre** : `gpu` (`max_utilise_mio`, `total_mio` : donnée de machine), `duree_s`, `computed_at` (horodatage), `journal` (lignes de journal du moteur), `message_declencheur` (texte d'un message fabriqué), `statut`, `game_id`. C'est la **réduction** qui rend le jeu admissible, pas sa provenance seule.

**Pourquoi maintenant.** #31 est au rang 3 de la branche `claude/non-regression` (PR #30) ; `coder` ne peut rien versionner sous `tests/reference/` tant que l'exigence 4.3 l'interdit à la lettre, et l'audit devrait refuser. Le fragment versionné depuis `afc0dfe` montre que, sans règle écrite, l'exception se fait quand même, en silence et sans contrôle.

## Décision

Arrêtée par le mainteneur le 2026-10-10 (point 1 et principe du point 2) ; forme fixée par `architect` (points 2 à 7), à confirmer par le mainteneur pour les textes du point 7.

1. **Deux catégories de données, une seule règle chacune.**
   - **État d'exécution d'une instance** : tout ce qu'une pile en service produit ou reçoit — base de données, journaux, fichiers d'état des conteneurs (`current_plans.json`, `pseudo_commitments.json`, `claude_dialogue_state.json` et leurs sauvegardes), messages de joueurs ou de bots, comptes, jetons, chemins, données de machine (GPU, durées, horodatages). **Toujours interdit dans le dépôt**, quelle que soit la partie d'origine.
   - **Jeu d'essai figé** : un extrait réduit d'une partie **100 % bots** (aucun joueur humain, aucun message humain ; `CONTEXT.md`), limité à ce dont les fonctions pures du projet ont besoin pour être rejouées, versionné dans un **seul dossier**, `tests/reference/`, avec un **manifeste**. **Admis**, aux conditions des points 2 à 4.

2. **Contenu admis du jeu d'essai figé** (liste fermée ; l'étendre est une annotation datée du présent ADR) :
   - l'**historique des ordres** de la partie source : par phase, les ordres de chaque puissance, en notation du moteur ; rien d'autre de la partie (ni messages, ni comptes, ni identifiants de la plateforme) ;
   - par phase de mouvement et par puissance, la **table de recherche réduite** aux clés `plans` (`rank`, `orders`, `value`, `cost_vs_best`), `order_values`, `candidates` (`orders`, `value`, `prob`), `search` (`lambda`, `boost`, `max_prob`) — les clés que `plan_export.py` écrit et que le bot de dialogue lit ;
   - les **arguments bruts d'`export_plans`** pour la même recherche (`action_values` : action, valeur, probabilité a priori, score ; `prior_policy` ; `regularize_lambda`, `boost`, `max_prob`), afin de rejouer l'export ;
   - pour la couche répétée (#31, couche R) : par position, les **grandeurs résumées** retenues par `expert-cicero` (action de tête modale, valeur de tête, `order_values`, λ) et leurs tolérances, jamais les recherches brutes ;
   - le **manifeste** : partie source (numéro local, date de création, nature « 100 % bots »), phases et puissances couvertes, date de capture, SHA du code et étiquette de l'image qui ont produit les tables, commande de capture, taille totale, liste des fichiers. Le manifeste est le seul fichier où le numéro de partie et une date apparaissent.
   Exclus par construction : tout texte de message (reçu, envoyé ou fabriqué — les messages fabriqués des essais vivent dans le code des tests, `tests/banc_promesses.py`), `computed_at`, `gpu`, `duree_s`, `journal`, `statut`, `game_id` dans les tables, engagements d'un fichier d'état.

3. **Contrôle par script dans `tests/verifier.sh`** (principe 7 des workflows : un contrôle mécanique est un script ; `audit` lit sa sortie), ajouté par #31, quatre tests qui font échouer la batterie :
   - **emplacement unique** : aucun fichier de données de partie (`.json`, `.jsonl`) versionné hors de `tests/reference/` ne contient les clés `plans`, `candidates`, `order_values` ou `search` ensemble ; le dossier `tests/reference/` est le seul admis ;
   - **liste blanche des clés** : toute clé JSON présente sous `tests/reference/` appartient à la liste du point 2 (plus les clés du manifeste) ; une clé inconnue est un échec, avec son chemin ;
   - **aucun texte de message** : aucune valeur de type chaîne hors manifeste ne dépasse une longueur fixée par `coder` sur la mesure de l'ordre le plus long du jeu (un ordre tient en moins de 24 caractères : `A TUN - APU VIA`, 15 ; `F ION C A TUN - APU`, 19), ni ne contient un caractère de ponctuation de phrase ;
   - **plafond de taille** : `tests/reference/` pèse au plus **512 Kio** au total (attendu : environ 300 ko, fait 3 et remesure) ; le dépasser demande une annotation du présent ADR, pas une hausse silencieuse du plafond.
   Les contrôles existants (`/home/<nom>/`, jetons, cinq noms de fichiers) continuent de s'appliquer au dossier.

4. **Source et nombre.** Une seule partie source à la fois (la partie 3 ; années 1901 à 1903, phases de mouvement, exigence 2.10 : une seule partie ne fonde pas une statistique, la référence fixe l'existant, elle ne le juge pas). Changer de partie source, ou en ajouter une, est une décision du mainteneur, annotée ici ; la partie source doit être 100 % bots.

5. **Sort du fragment déjà versionné** (`tests/mesure/rejeu_moteur.py:156-168`). Il est de la nature du jeu d'essai figé (partie 3, actions et valeurs, aucune donnée exclue) et est **régularisé** par le présent ADR ; il viole seulement l'emplacement unique. #31 le remplace par une lecture de la table S1902M / ITALY de `tests/reference/` (les probabilités et λ, fabriqués pour l'essai à sec, restent dans le code), de sorte que l'emplacement unique soit vrai sans exception ; d'ici là, aucun autre extrait de partie n'est écrit dans un fichier de code.

6. **Qui régénère la référence, et quand** (`CLAUDE.md`, « Changements de résultats et reproductibilité », dernier point, inchangé) : la **session principale seule**, jamais un agent ni un workflow, **après visa** du tableau avant / après du changement qui la rend fausse (mainteneur pour un résultat final ou un verdict, `expert` sinon). Une régénération est une nouvelle capture sur les **mêmes positions** (l'historique des ordres ne change pas), commitée en `tests:` avec le manifeste mis à jour (date, SHA, image), le numéro de la décision ou de la PR qui porte le visa, et la ligne du tableau qu'elle reflète. Une ligne de référence qui change sans ligne de tableau est une régression (`CLAUDE.md`), pas une référence à régénérer.

7. **Textes à rouvrir** (le mainteneur valide au mot près ; appliqués ensuite par `docwriter` pour `docs/exigences.md` et par la session principale pour `CLAUDE.md`, domaine `claude:`). Aucun des deux fichiers n'est modifié par le présent ADR.

   **Exigence 4.3**, texte actuel :
   > 4.3. Aucune donnée locale dans le dépôt : ni jeton, ni base de données, ni comptes, ni état de partie, ni chemin personnel. La base se crée vide au premier démarrage.

   Texte proposé :
   > 4.3. Aucune donnée locale dans le dépôt : ni jeton, ni base de données, ni comptes, ni chemin personnel, ni état d'exécution d'une instance (journaux, fichiers d'état des conteneurs, messages, parties). Seule exception, écrite dans l'ADR 0006 : un jeu d'essai figé, tiré d'une partie 100 % bots et réduit à l'historique des ordres et aux tables du moteur, versionné dans le seul dossier `tests/reference/` avec son manifeste, et contrôlé par `tests/verifier.sh` (clés en liste blanche, aucun texte de message, plafond de taille). La base se crée vide au premier démarrage.

   **`CLAUDE.md`, « Architecture », invariant « Rien de local dans le dépôt »**, texte actuel :
   > - **Rien de local dans le dépôt** : ni chemin personnel, ni jeton, ni base de données, ni état de partie. `tests/verifier.sh` le contrôle.

   Texte proposé :
   > - **Rien de local dans le dépôt** : ni chemin personnel, ni jeton, ni base de données, ni état d'exécution d'une instance (journaux, fichiers d'état, messages, parties). Seule exception : le jeu d'essai figé de `tests/reference/` (partie 100 % bots, historique des ordres et tables réduites, manifeste ; ADR 0006). `tests/verifier.sh` contrôle l'interdiction et l'exception.

   À rouvrir aussi, **après** la livraison de #31 et non maintenant : `CLAUDE.md`, « Changements de résultats et reproductibilité », dernier point (« Il n'existe pas encore de référence de non-régression fonctionnelle ») ; `tests/mesure/LISEZMOI.md`, phrase « Les résultats … ne sont pas versionnés » (surface d'impact documentaire de #31, `docwriter`).

## Options écartées

- **Référence hors git** (relevés dans `amont/mesure/resultats/`, scripts seuls versionnés — l'état actuel). Ce qu'elle manque : la couche déterministe ne tourne ni en CI ni chez un tiers ; la référence meurt avec le poste ; c'est déjà ce régime qui a produit trois calculs non concordants et non versionnés sur les mêmes relevés (ADR 0004, « Bruit des valeurs »). Elle reste le régime des **relevés bruts** (recherches répétées, appels à Claude), qui ne sont pas la référence.
- **Tables fabriquées seules** (le banc `tests/banc_promesses.py`, déjà dans la CI). Ce qu'elles manquent : le tableau de mutations d'`expert-cicero` (fait 4) montre que les deux jeux voient des régressions différentes — l'arrondi du gain change 2 verdicts sur 30 tables réelles et 0 sur 3 000 fabriquées ; le multiplicateur 3 → 2 en change 0 sur les réelles et 1 036 sur les fabriquées. Les tables réelles ont la structure du moteur (actions partageant la plupart des ordres, valeurs serrées, 35 candidats au plus) que le banc n'imite pas ; le banc a la couverture combinatoire que 30 tables n'ont pas. Le banc est donc **conservé en complément**, pas remplacé.
- **Versionner les relevés `m1_3_*.jsonl` tels quels.** Refusé : ils contiennent une donnée de machine (`gpu`), des durées, des horodatages, des lignes de journal, le texte d'un message fabriqué et le statut de la partie (remesure ci-dessus). La réduction aux quatre clés et aux arguments bruts est ce qui rend le jeu admissible.
- **Une partie ordinaire comme source** (un humain, six bots). Refusé : ses messages et son compte sont ceux d'une personne ; les retirer laisserait des ordres influencés par une négociation qu'on ne verrait pas. Seule une partie 100 % bots est admise (point 4).
- **Référence téléchargée** (pièce jointe de version, Git LFS, dépôt séparé). Refusé : ajoute une dépendance hors du dépôt alors que l'exigence 4.2 veut le dépôt seul ; ne règle que la taille, qui ne pose pas problème (300 ko, plafond 512 Kio), et pas la question du contenu, qui est la seule en jeu.
- **Garder l'exigence 4.3 telle quelle et tolérer l'exception sans l'écrire** (ce qui s'est fait pour le fragment depuis `afc0dfe`). Refusé : une exception non écrite se recopie sans contrôle ; le test de suppression est net — sans règle, rien n'empêche le prochain fragment d'embarquer un message ou un identifiant.
- **Contrôle par liste noire de clés** (refuser `message`, `reply`, `sender`…). Refusé au profit de la liste blanche : une liste noire oublie toujours la clé suivante ; la liste blanche fait du format de la référence un contrat explicite, que `coder` étend en l'écrivant.

## Conséquences

- **Fichiers.** Nouveau dossier `tests/reference/` et son manifeste, scripts de capture et de comparaison, quatre tests dans `tests/verifier.sh` (#31, `coder` → `audit`) ; `tests/mesure/rejeu_moteur.py:156-168` lit la table depuis la référence (#31) ; `CONTEXT.md` : termes « état d'exécution d'une instance », « jeu d'essai figé », « référence de non-régression » (présente consultation) ; `docs/exigences.md` 4.3 et `CLAUDE.md` : textes du point 7, après validation du mainteneur ; `tests/mesure/LISEZMOI.md` et `docs/doc/architecture.md` : surface d'impact documentaire de #31 (`docwriter`, fin de branche).
- **Fiches d'agents.** Aucune ne change ; `audit` applique le point 3 en lisant la sortie de `tests/verifier.sh`, il ne refait pas le décompte des clés.
- **Résultats.** Aucun : la référence fixe l'existant ; aucun paramètre ni consigne ne change.
- **Reste à faire.** La liste blanche exacte et les tailles sont fixées par `coder` dans le script à partir des clés mesurées ici et de la spécification de #31, validées par `expert-cicero` sur le diff ; la première capture demande l'arrêt annoncé de `cicero-orders` (M12 ; environ 2 h 17 en campagne commune avec #26) ; les tolérances de la couche R viennent de #26.
- **Ce que l'ADR ne règle pas.** Les tolérances de la couche répétée (#26, puis décision du mainteneur sur la marge) ; la couche « Claude » (contenu de `sincere` produit par le modèle, hors #31) ; les phases de retraite et d'ajustement et les parties avancées (hors #31) ; la forme exacte des fichiers (un par table ou un par phase : `coder`, sous le plafond) ; ce que devient la référence si la partie 3 est supprimée du poste (le jeu versionné suffit à la couche D ; la couche R demande une pile, pas la partie d'origine, puisque la position se reconstruit depuis l'historique des ordres).

Issues : #31 (référence), #26 (tolérances de la couche R), #12 (partie 100 % bots, source du jeu), #27 (bytecode exclu du contrôle des patchs : préalable à toute donnée JSON de tests), #24, #25, #21, #13 (changements de comportement à mesurer contre la référence). PR #30. ADR 0004 (limites connues, bruit des valeurs), ADR 0002 (le dépôt ne contient que ce que le projet ajoute : le jeu d'essai figé est une donnée du projet, pas un amont).
