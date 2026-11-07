# Diplomacy_online

Jouer à Diplomacy sur une instance locale de [webDiplomacy](https://github.com/kestasjk/webDiplomacy) contre six bots dont la stratégie est calculée par [Cicero](https://github.com/facebookresearch/diplomacy_cicero) (Meta) et dont la négociation en langage naturel est écrite par Claude.

Ce dépôt ne contient **que ce que le projet ajoute** aux deux logiciels d'amont : des patchs, des fichiers nouveaux, et les scripts qui assemblent le tout. Les amonts sont clonés à des commits épinglés lors de l'installation.

## État

| Élément | État |
|---|---|
| Fonctionnement de l'ensemble (ordres, dialogue, promesses) | Éprouvé sur des parties réelles, sur la machine d'origine |
| Logique des promesses révisée (trahison déclarée, renfort gradué, journal d'envoi) | Mesurée sur bancs et positions rejouées : tests sans pile (`bash tests/verifier.sh`) ; le 2026-10-03, 30 recherches réelles du moteur et un essai d'envoi réel ; le 2026-10-10, 160 appels à Claude sur une seule position, et le bruit des valeurs mesuré sur les recherches répétées d'une partie 100 % bots (110 recherches sans engagement, 21 positions) : au 99e centile il dépasse la marge exigée d'une trahison, qui, prise seule, ne protège donc que partiellement du bruit ; le cas où cette marge travaille n'est pas mesuré. Aucune partie jouée contre un humain n'entre dans ces mesures. Détail et limites : `docs/doc/architecture.md` § 4 |
| Référence de non-régression (jeu d'essai figé de `tests/reference/`, couches D et R) | Couche D rejouée par `bash tests/verifier.sh` : 42 tables réelles, 24 770 grandeurs comparées, 0 différence. Couche R exécutée une fois sur le moteur, le 2026-10-11, sur l'image même de la capture : 210 recherches sur 21 positions, « pas de régression » ; aucun changement n'y était introduit, l'exécution ne dit rien du pouvoir de détection. Le lancement de la couche R pile arrêtée et son script d'enchaînement (`tests/mesure/lancer_couche_r.sh`) ne sont validés que par une doublure de `docker` : jamais exécutés sur le moteur. Une seule partie, années 1901 à 1903 ; rien sur Claude. Détail et limites : `docs/doc/architecture.md` § 7 |
| `install.sh` jusqu'à la préparation des amonts (clonage, patchs, configuration, dépendances PHP) | Vérifié par un essai à blanc |
| Construction de l'image Cicero par le `Dockerfile` de ce dépôt | Validée le 2026-10-03 sur la machine d'origine : build complet depuis les sources en 20 min environ, image de 16,7 Go ; PyTorch y voit le GPU, `pydipcc`, `postman` et les protos s'importent |
| Démarrage de la pile depuis ce dépôt, sur une base vide | Validé le 2026-10-03 : inscription d'un joueur, partie créée contre six bots, ordres soumis par les six, réponse de Claude à un message, données conservées après `arreter.sh` puis `demarrer.sh` |
| Interface « beta » (React, carte cliquable) de webDiplomacy | Construite par `install.sh` depuis le 2026-10-03 (1 min 30) : le mainteneur y a saisi ses ordres et envoyé un message dans la partie d'essai, phase résolue |
| Serveur d'événements (`webdiplomacy-sse`) | Configuré depuis le 2026-10-03 : il écoute et joint Redis, `/events` répond. Le rafraîchissement automatique de l'interface cliquable n'a pas été observé à l'écran |

## Prérequis

- Ubuntu avec un GPU NVIDIA d'au moins 8 Go, pilote installé ;
- Docker, le plugin `docker compose` et `nvidia-container-toolkit` (`docker run --rm --gpus all ubuntu:26.04 nvidia-smi` doit afficher le GPU) ;
- `git`, `wget`, `gpg` ;
- environ 25 Go de disque, et de la mémoire : la compilation est volontairement séquentielle (`-j1`) parce que la compilation parallèle a fait tomber la machine d'origine ;
- un abonnement Claude, pour le jeton du bot de dialogue.

## Installation

```bash
git clone https://github.com/Gerard-Garey/Diplomacy_online.git
cd Diplomacy_online
cp env.exemple .env        # puis y coller le jeton obtenu par `claude setup-token`
./install.sh                # 20 à 30 min : clonage, patchs, poids de modèle, compilation
./demarrer.sh
```

Le site est alors sur <http://localhost:43000>. La base de données est créée vide au premier démarrage, avec les comptes `bot1` à `bot7`, leurs clés d'API et la variante Classic.

### Première partie

1. Créer son compte par `register.php`. Une épreuve anti-robot demande de cliquer sur la carte les centres de ravitaillement d'un pays. Le courriel de validation arrive ensuite dans MailHog, sur <http://localhost:43001> : suivre son lien.
2. Compléter le formulaire du compte. L'interface par défaut est la carte cliquable ; l'interface à menus déroulants reste disponible (« Dropdown menus », ou `board.php?gameID=<n>&view=dropDown`).
3. Créer la partie par « Start an AI/Bot Game » (`botgamecreate.php`), variante Classic. Les six bots la rejoignent aussitôt ; les messages y sont ouverts (presse « Regular »). **Ne pas cliquer sur « join the queue »** : la file « full-press » de l'amont cherche des bots qui n'existent pas ici, et la partie serait créée sans adversaire.

Les bots soumettent leurs ordres en quelques minutes, et le bot de dialogue relève les messages toutes les 60 s.

À savoir :

- seule la variante Classic est proposée ; un compte ordinaire est limité à trois parties contre bots en cours ;
- aucun compte administrateur n'est créé ;
- les ports ne sont publiés que sur `127.0.0.1` : le site n'est pas joignable depuis une autre machine ;
- après un redémarrage de la machine, relancer `./demarrer.sh` : il rend aux parties en cours la durée de l'arrêt ;
- les journaux du moteur (valeur et probabilité de chaque action, par partie et par puissance) sont dans `amont/cicero/journaux_moteur` ;
- `bot-service` (bots élémentaires qui tiennent leurs positions) reste dans le dépôt sous le profil `bots`, qu'aucun script ne lance. **Ne pas le démarrer à côté de Cicero** : il validerait des ordres à sa place.

### Partie 100 % bots (essais)

Pour obtenir des positions sans jouer soi-même, une partie dont les sept puissances sont tenues par les bots se crée en ligne de commande, pile démarrée :

```bash
docker exec -e XDEBUG_MODE=off webdiplomacy-php-fpm-1 \
  php /application/gamecreateBotsOnly.php <nom>
```

- `<nom>` : 1 à 50 caractères parmi `A-Z a-z 0-9 _ . -`, le premier alphanumérique ; un nom déjà pris est refusé, ainsi que tout nom commençant par « SB » suivi d'au moins un caractère (`SB_x`, `SBtest`, `Sbires`), que webDiplomacy prendrait pour un bac à sable et dont il repousserait l'échéance à 2033 ;
- codes de sortie : 0, avec `gameID=<n>` en dernière ligne ; 2, mauvais usage (rien n'est lu en base) ; 1, échec (rien n'est créé) ;
- le script ne répond qu'en ligne de commande (403 par le site) ; les bots ne s'y parlent pas tant qu'aucun message n'y est posté : aucun code ne l'empêche (#14), et un seul message injecté au nom d'une puissance ouvre un échange entre deux bots, jusqu'à dix réponses par côté, par paire et par phase, chaque réponse appelant Claude ; rien n'arrête la partie d'elle-même avant sa fin, le mainteneur l'arrête par une pause posée en base. Détail : `docs/doc/architecture.md` § 5.

`./install.sh` est relançable : une étape déjà faite est sautée. Options : `--sans-build`, `--sans-modeles`.

| Commande | Effet |
|---|---|
| `./demarrer.sh` | Démarre webDiplomacy, initialise Redis, démarre les conteneurs `cicero-orders` et `cicero-dialogue` |
| `./arreter.sh` | Arrête tout ; la base et les parties sont conservées (volume Docker `webdiplomacy_webdiplomacy-db-data`) |
| `amont/cicero/check_orders.sh <gameID>` | Affiche les ordres que chaque bot a en cache pour la phase en cours |
| `bash tests/verifier.sh` | Batterie statique (syntaxe, patchs, absence de secret et de chemin personnel, contrôle du jeu d'essai figé et des noms de fichiers du dépôt) et tests par appel direct : bot de dialogue, logique des promesses, mesure du bruit des valeurs, outillage de la référence, puis couche D de la référence de non-régression ; tourne sans la pile, sans GPU et sans appel à Claude |
| `python3 tests/mesure/capture_reference.py commandes <gameID> --couche-r` | Imprime, sans rien lancer, les commandes d'un lot de la couche R (code 2 pour une position inconnue de `--repetees`) : recherches réelles sur les 21 positions répétées, `cicero-orders` arrêté (durée imprimée en fourchette, de 2 h 26 à 4 h 03 ; 4 h 02 mesurées le 2026-10-11). La pile peut rester arrêtée (`--reseau` relance les lancements sur son réseau) ; un accès sortant à Internet est requis. La suite arrête `cicero-orders` s'il existe et ne le relance pas : il se restaure à la main. À la main, jamais en CI |
| `bash tests/mesure/lancer_couche_r.sh <gameID>` | Enchaîne cette suite, un journal par lancement, puis la comparaison ; refuse si `cicero-orders` tourne et ne relance rien. Code de `comparer` (0, 1, 2) ; 3 : refus avant tout lancement, rien de créé ; 4 : lancement en échec ; 5 : décompte final faux ; 6 : `comparer` sans verdict. Validé par doublure de `docker` seule : jamais exécuté sur le moteur |
| `python3 tests/reference_couche_r.py comparer <relevés>` | Compare ce lot au résumé de la référence ; code 0 : pas de régression, 1 : régression, 2 : non concluant, lot invalide ou relevés que la lecture refuse (dont une ligne sans numéro de tirage entier ; détail : `docs/doc/architecture.md` § 7) |
| `python3 tests/reference_jeu.py reduire <relevés> …` | Réduit les relevés d'une campagne de capture en jeu d'essai : session principale seule, après visa. Code 2 : refus, une ligne « REFUS : » qui nomme le fichier et la cause, rien d'écrit, y compris pour une lecture ou une écriture impossible — sauf si le jeu écrit ne passe pas le contrôle final (fichiers laissés pour être lus) ou si l'écriture échoue après un premier fichier (fichiers laissés, le refus le dit : vider le dossier avant de relancer). La seconde passe s'écarte par `--sauf '*passe2*'`, comme pour `resumer`. Procédure : `docs/doc/architecture.md` § 7 |
| `python3 tests/reference_couche_r.py resumer <relevés> --vers <jeu>`, `python3 tests/reference_jeu.py manifeste --dossier <jeu>` | Écrivent le résumé des positions répétées, ou refont le manifeste d'un jeu dont les fichiers ont changé : session principale seule, après visa. Code 0 : écrit ; 2 : refus, le jeu est laissé tel qu'il était (`resumer` retire le résumé et remet le manifeste si le jeu, résumé écrit, ne passe plus son contrôle ; `manifeste` refuse un résumé retouché, ou non noté ou absent alors que le manifeste en porte le bloc, ou un fichier `*.ecriture` laissé par une écriture interrompue — `resumer` aussi, s'il apparaît pendant son écriture ; `manifeste` refuse de même une lecture ou une écriture impossible) |

## Organisation du dépôt

| Chemin | Contenu |
|---|---|
| `versions.env` | Commits d'amont épinglés et liste des poids de modèle nécessaires |
| `cicero/patches/` | Modifications de fichiers existants de Cicero et de deux de ses sous-modules |
| `cicero/overlay/` | Fichiers nouveaux copiés dans l'arbre Cicero : `Dockerfile`, bot de dialogue, configuration de l'agent, export du plan, engagements |
| `webdiplomacy/patches/`, `webdiplomacy/overlay/` | Idem pour webDiplomacy |
| `install.sh`, `demarrer.sh`, `arreter.sh` | Installation et exploitation |
| `tests/` | Batterie statique (`verifier.sh`), banc déterministe de la logique des promesses et de l'état du bot de dialogue, sortie mesurée du banc (`mesure_promesses.py`), scripts des mesures faites sur la pile (`mesure/`), jeu d'essai figé de la référence de non-régression (`reference/`, seule exception à l'exigence 4.3 : ADR 0006) et ses scripts (`reference_jeu.py`, `reference_couche_d.py`, `reference_couche_r.py`) |
| `outils/exporter_patchs.sh` | Reporte dans le dépôt le travail fait dans `amont/` |
| `docs/doc/architecture.md` | Fonctionnement d'ensemble ; **à lire en premier** |
| `docs/exigences.md`, `docs/adr/`, `docs/feuille-de-route.md` | Cahier des charges, décisions, plan |
| `CLAUDE.md`, `.claude/`, `CONTEXT.md` | Règles de travail avec Claude Code, sous-agents, glossaire |

## Développer

On travaille dans `amont/cicero` et `amont/webdiplomacy`, qui sont des arbres complets et testables, puis on reporte :

```bash
outils/exporter_patchs.sh              # régénère les patchs
outils/exporter_patchs.sh --verifier   # échoue si le dépôt est en retard sur amont/
```

Un fichier **nouveau** se copie à la main dans le dossier `overlay/` correspondant. Le bytecode Python (`__pycache__`, `*.pyc`) n'est pas un fichier d'overlay : `--verifier` l'ignore, les scripts de `tests/`, lancés directement, n'en écrivent pas dans les overlays (`sys.dont_write_bytecode`), et `bash tests/verifier.sh` échoue s'il en reste dans un overlay après les tests. Le code Cicero est copié dans l'image, non monté : toute modification demande `./install.sh` (reconstruction) puis `./demarrer.sh`.

Règles de contribution (branche unique, PR brouillon, visa des changements de comportement) : `CLAUDE.md`.

## Licences

Voir `NOTICE`. En bref : les fichiers de ce dépôt sont sous licence MIT, sauf `webdiplomacy/`, dérivé d'un logiciel AGPL-3.0 et placé sous cette licence. Les poids de modèle de Cicero, téléchargés à l'installation et jamais redistribués ici, sont sous CC BY-NC 4.0 : **usage non commercial**.
