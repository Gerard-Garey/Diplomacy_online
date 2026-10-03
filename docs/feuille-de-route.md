# Feuille de route

Tenue par `architect`, après chaque série de PR fusionnées. Chaque mise à jour est datée et cite le SHA de `main` et de la branche de travail.

## 1. Branche de travail en cours

Mise à jour du 2026-10-02 — `main` : `450f159`.

- **Branche** : `claude/import-initial` — PR à ouvrir en brouillon
- **Périmètre** (fermé ; import initial, sans issue préalable) :
  - [x] Adapter le modèle au projet (règles, sous-agents, glossaire, cahier des charges) — circuit : 4 — résultats : aucun
  - [x] Reporter le projet dans le dépôt (patchs, overlay, scripts d'installation) — circuit : 3 — résultats : aucun (arbres identiques à l'origine, ADR 0002)
  - [x] Valider `cicero/overlay/Dockerfile` par un build complet, puis le démarrage sur base vide — fait le 2026-10-03 (tête `d0daffd` et suivantes), circuit : 3 — résultats : aucun
- **Revue finale complète** : `audit`, `expert-webdip` (installation)

## 2. Branches suivantes

| Branche | Issues | Motif du regroupement | Dépend de |
|---|---|---|---|
| validation du build | à créer | Exécuter le `Dockerfile` de bout en bout, corriger, puis démarrer la pile depuis un clone neuf | import initial fusionné |
| non-régression | à créer | Positions rejouées de parties terminées comme références ; essais indépendants de la partie 15 | validation du build |

## 3. Issues hors plan

Issues ouvertes non rattachées à une branche, avec la raison.

## 4. Décisions du mainteneur

| N° | Date | Décision | Où elle est consignée |
|---|---|---|---|
| M1 | 2026-10-02 | Dépôt de patchs et script d'installation ; build complet depuis les sources ; cible Ubuntu + GPU NVIDIA ≥ 8 Go | ADR 0002 |
| M2 | 2026-10-02 | Sous-agents : deux experts (`expert-cicero`, `expert-webdip`), `app-review` et `docwriter` conservés ; licence MIT, AGPL-3.0 pour `webdiplomacy/` | `CLAUDE.md`, `NOTICE` |
| M3 | 2026-10-02 | Validation du build Docker différée (« écrire maintenant, valider plus tard ») | ADR 0002, README « État » |
| M4 | 2026-08-19 | Rester proche de Cicero : pas d'engagements négatifs, pas d'effet du dialogue hors mouvement | ADR 0003, exigence 2.9 |

## 5. Escalades, relances et arrêts hors branche

Consultations faites hors de toute branche ouverte (`docs/agents/routage.md`, § 7) ; une consultation Fable compte pour la branche suivante.

| Date | Fiche / modèle / critère déclenché / statut obtenu / suite |
|---|---|
