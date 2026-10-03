# Diplomacy_online

Jouer à Diplomacy sur une instance locale de [webDiplomacy](https://github.com/kestasjk/webDiplomacy) contre six bots dont la stratégie est calculée par [Cicero](https://github.com/facebookresearch/diplomacy_cicero) (Meta) et dont la négociation en langage naturel est écrite par Claude.

Ce dépôt ne contient **que ce que le projet ajoute** aux deux logiciels d'amont : des patchs, des fichiers nouveaux, et les scripts qui assemblent le tout. Les amonts sont clonés à des commits épinglés lors de l'installation.

## État

| Élément | État |
|---|---|
| Fonctionnement de l'ensemble (ordres, dialogue, promesses) | Éprouvé sur des parties réelles, sur la machine d'origine |
| `install.sh` jusqu'à la préparation des amonts (clonage, patchs, configuration, dépendances PHP) | Vérifié par un essai à blanc |
| Construction de l'image Cicero par le `Dockerfile` de ce dépôt | Validée le 2026-10-03 sur la machine d'origine : build complet depuis les sources en 20 min environ, image de 16,7 Go ; PyTorch y voit le GPU, `pydipcc`, `postman` et les protos s'importent |
| Démarrage de la pile depuis ce dépôt, sur une base vide | Validé le 2026-10-03 : inscription d'un joueur, partie créée contre six bots, ordres soumis par les six, réponse de Claude à un message, données conservées après `arreter.sh` puis `demarrer.sh` |
| **Interface « beta » (React, carte cliquable) de webDiplomacy** | **Non construite par `install.sh`** : `beta/` répond 404. Choisir l'interface à menus déroulants (voir « Première partie ») |
| Serveur d'événements (`webdiplomacy-sse`) | Démarre, mais ne joint pas Redis faute de configuration ; sans effet constaté sur l'interface classique |

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

1. Créer son compte par `register.php`. Le courriel de validation arrive dans MailHog, sur <http://localhost:43001> : suivre son lien.
2. Dans le formulaire du compte, choisir **« Dropdown menus »** pour « Default map UI » : l'interface cliquable n'est pas construite, et une partie ouverte avec elle renvoie une erreur 404. Un compte déjà créé ouvre une partie par `board.php?gameID=<n>&view=dropDown`.
3. Créer la partie par « Start an AI/Bot Game » (`botgamecreate.php`), variante Classic. Les six bots la rejoignent aussitôt ; les messages y sont ouverts (presse « Regular »).

Les bots soumettent leurs ordres en quelques minutes, et le bot de dialogue relève les messages toutes les 60 s.

`./install.sh` est relançable : une étape déjà faite est sautée. Options : `--sans-build`, `--sans-modeles`.

| Commande | Effet |
|---|---|
| `./demarrer.sh` | Démarre webDiplomacy, initialise Redis, démarre les conteneurs `cicero-orders` et `cicero-dialogue` |
| `./arreter.sh` | Arrête tout ; la base et les parties sont conservées (volume Docker `webdiplomacy_webdiplomacy-db-data`) |
| `amont/cicero/check_orders.sh <gameID>` | Affiche les ordres que chaque bot a en cache pour la phase en cours |
| `bash tests/verifier.sh` | Batterie statique (syntaxe, patchs, absence de secret et de chemin personnel) |

## Organisation du dépôt

| Chemin | Contenu |
|---|---|
| `versions.env` | Commits d'amont épinglés et liste des poids de modèle nécessaires |
| `cicero/patches/` | Modifications de fichiers existants de Cicero et de deux de ses sous-modules |
| `cicero/overlay/` | Fichiers nouveaux copiés dans l'arbre Cicero : `Dockerfile`, bot de dialogue, configuration de l'agent, export du plan, engagements |
| `webdiplomacy/patches/`, `webdiplomacy/overlay/` | Idem pour webDiplomacy |
| `install.sh`, `demarrer.sh`, `arreter.sh` | Installation et exploitation |
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

Un fichier **nouveau** se copie à la main dans le dossier `overlay/` correspondant. Le code Cicero est copié dans l'image, non monté : toute modification demande `./install.sh` (reconstruction) puis `./demarrer.sh`.

Règles de contribution (branche unique, PR brouillon, visa des changements de comportement) : `CLAUDE.md`.

## Licences

Voir `NOTICE`. En bref : les fichiers de ce dépôt sont sous licence MIT, sauf `webdiplomacy/`, dérivé d'un logiciel AGPL-3.0 et placé sous cette licence. Les poids de modèle de Cicero, téléchargés à l'installation et jamais redistribués ici, sont sous CC BY-NC 4.0 : **usage non commercial**.
