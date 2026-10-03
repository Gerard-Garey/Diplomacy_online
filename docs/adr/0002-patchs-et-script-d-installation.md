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
- **Validation du 2026-10-03** (levée du différé M3) : le `Dockerfile` a été exécuté de bout en bout sur la machine d'origine, puis la pile démarrée depuis `amont/` sur une base vide (inscription, partie contre six bots, ordres, réponse à un message). Corrections qu'il a fallu : `nvidia-cuda-toolkit` dans l'image, versions conda épinglées (`mkl`), dépendances du serveur SSE, dossier `cache/`, ligne Classic de `wD_VariantInfo`, volume nommé pour la base. L'exigence 4.2 est démontrée sur cette machine seulement ; elle ne l'est pas sur une autre machine. L'interface « beta » est construite par `install.sh` et servie ; son fonctionnement dans un navigateur n'a pas été vérifié.
- Non réglé : secret du *gamemaster* de valeur fixe, acceptable tant que le site n'écoute que sur la machine locale.
