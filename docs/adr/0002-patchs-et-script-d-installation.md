---
status: accepted
date: 2026-10-02
---

# Le dépôt ne contient que des patchs et des fichiers nouveaux ; un script assemble les amonts

## Contexte

Le projet vivait dans deux clones de dépôts tiers aux modifications non commitées : `diplomacy_cicero` (11 fichiers modifiés, deux sous-modules patchés, une dizaine de fichiers nouveaux) et `webDiplomacy` (7 fichiers modifiés, un service ajouté). Aucun ne pointait vers un dépôt du mainteneur, et l'image Docker de Cicero copiait un environnement conda compilé à la main sur une machine : rien n'était réinstallable ailleurs.

## Décision

Arrêtée par le mainteneur le 2026-10-02.

1. Le dépôt contient, par amont, un dossier `patches/` (fichiers existants modifiés) et un dossier `overlay/` (fichiers nouveaux). Les amonts ne sont pas copiés.
2. `versions.env` épingle le commit de chaque amont ; `install.sh` les clone dans `amont/` (ignoré par git), applique patchs et overlay, puis construit.
3. L'image Cicero est construite entièrement depuis les sources par `cicero/overlay/Dockerfile`.
4. On développe dans `amont/` ; `outils/exporter_patchs.sh` reporte le travail dans le dépôt, et son mode `--verifier` contrôle que les deux concordent.
5. Machine cible : Ubuntu, GPU NVIDIA d'au moins 8 Go, Docker et `nvidia-container-toolkit`.
6. Licences : MIT, sauf `webdiplomacy/`, dérivé d'un code AGPL-3.0 et placé sous cette licence (`NOTICE`).

## Options écartées

- **Sous-modules vers des forks** : historique complet, mais trois dépôts à tenir et des sous-modules imbriqués (Cicero en a déjà, dont deux que le projet patche).
- **Monorepo** : un seul clone, mais environ 1,5 Go hors modèles, deux licences mêlées dans un même arbre, et des mises à jour d'amont difficiles.
- **Image pré-construite publiée** : rapide, mais non reconstructible depuis les sources et dépendante d'un registre.

## Conséquences

- Les chemins personnels codés en dur ont été remplacés par `/opt/cicero` et par des variables d'environnement ; le patch du `Makefile` de postman retire l'appel à `git submodule update`, sans objet dans un build Docker.
- Mesure du 2026-10-02 : `install.sh --sans-build --sans-modeles`, exécuté sur des clones vierges, produit des arbres identiques octet pour octet à l'arbre de travail d'origine (20 fichiers comparés) et se relance sans rien réappliquer.
- **Validation du 2026-10-03** (levée du différé M3) : le `Dockerfile` a été exécuté de bout en bout sur la machine d'origine, puis la pile démarrée depuis `amont/` sur une base vide (inscription, partie contre six bots, ordres, réponse à un message). Corrections qu'il a fallu : `nvidia-cuda-toolkit` dans l'image, versions conda épinglées (`mkl`), dépendances du serveur SSE, dossier `cache/`, ligne Classic de `wD_VariantInfo`, volume nommé pour la base. L'exigence 4.2 est démontrée sur cette machine seulement ; elle ne l'est pas sur une autre machine. L'interface « beta » est construite par `install.sh` ; le mainteneur y a joué une phase de la partie d'essai (ordres et message).
- Non réglé : secret du *gamemaster* de valeur fixe, acceptable tant que le site n'écoute que sur la machine locale. La revue finale du 2026-10-03 a montré que ce n'était pas le cas (ports publiés sur toutes les interfaces) ; ils ne le sont plus que sur `127.0.0.1` depuis `943cbd4`.

## Annotation du 2026-10-03 (`architect`, après la fusion de la PR #1, `main` à `a9566a2`)

Relecture contre l'état de `main`. Le texte ci-dessus avait été mis à jour par la session principale pendant la branche d'import ; la décision est inchangée.

- **Rectification** : le commit qui restreint les ports à `127.0.0.1` est `943cbd4` (patch de webDiplomacy), et non `7b8451d` comme l'écrivait la version fusionnée (ce dernier ne touche que `tests/verifier.sh`). Le SHA a été corrigé dans le texte.
- **Corrections du 2026-10-03 omises de la liste** : dans le `Makefile` de Cicero, le `make -j` de la cible `selfplay` remplacé par `$(MAKE)` (compilation séquentielle) ; dans `demarrer.sh`, l'attente de « READY », le contrôle du site et la remise à l'heure de `LastProcessTime` ; dans `tests/verifier.sh`, la recherche de jeton quand `.env` existe.
- **Décision 4, précision** : depuis `ae01861`, `exporter_patchs.sh --verifier` contrôle aussi les fichiers d'overlay, pas seulement les patchs. `install.sh` recopie encore `overlay/` sur `amont/` sans avertir (#8).
- **Limite de la décision 2** : après un changement de patch, `install.sh` ne sait pas mettre à jour un `amont/` existant ; le seul remède, supprimer `amont/<x>`, emporte les poids et l'état des parties (#8).
- **Décisions du mainteneur du 2026-10-03** (feuille de route, M7) : l'interface cliquable est construite par `install.sh` (`2f38b12`) ; seule la variante Classic est proposée contre les bots (`ce330ee`) ; `bot-service` est gardé tel quel.
- **Ce qui reste ouvert a désormais une issue** : secret du *gamemaster* et arbre servi par nginx (#10) ; versions non épinglées, donc « même image sur toute machine » non garanti (#7) ; arrêt court non compensé (#11). L'installation sur une autre machine que celle d'origine n'a toujours pas été essayée.

Issues : #7, #8, #10, #11.
