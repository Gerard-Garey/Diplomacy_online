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
- **Reste à faire** : le `Dockerfile` n'a pas encore été exécuté de bout en bout (décision du mainteneur : validation différée). Tant qu'il ne l'est pas, l'exigence 4.2 n'est pas démontrée.
- Non réglé : construction de l'interface « beta » de webDiplomacy ; secret du *gamemaster* de valeur fixe, acceptable tant que le site n'écoute que sur la machine locale.
