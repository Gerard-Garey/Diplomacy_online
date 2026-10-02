---
status: accepted
date: 2026-09-30
---

# Opus par défaut pour architect et expert, effort réglé à part, Fable réservé à une liste fermée de cas

## Contexte

`architect` et `expert` tournaient sur Fable pour toutes leurs missions, sans effort ni plafond de tours fixés (l'effort venait de la session). Les dépôts dérivés du modèle ont montré trois sources de consommation, sans mesure fine disponible : Fable pour des missions routinières (rattachement d'issues, tenue de la feuille de route, rédaction d'issues) ; la lecture imposée au démarrage (tous les ADR, `CONTEXT.md`, la feuille de route entière : jusqu'à environ 1 Mo de texte dans un projet dérivé, mesuré par `wc -c`) ; l'absence de borne à l'exploration. Le mainteneur travaille sur abonnement : la contrainte est la limite d'usage, pas un coût unitaire.

Contraintes techniques (Claude Code 2.1.286, documentation officielle) : le paramètre `model` d'un appel `Agent` l'emporte sur le `model` de la fiche ; l'effort ne peut pas être passé à l'appel de l'outil `Agent`, seulement fixé dans la fiche (`effort`) (l'API des workflows l'accepte : `.claude/workflows/circuit-technique.js`, `effort: 'low'`) ; un sous-agent lancé ne change ni de modèle ni d'effort ; les fiches ne sont pas rechargées en cours de session (`docs/agents/issue-tracker.md`, constat 3).

## Décision

Arrêtée par le mainteneur le 30 septembre 2026, après entretien (priorités : qualité, puis consommation, puis autonomie ; la latence compte peu) :

1. **Opus par défaut** pour `architect` et `expert` ; **deux fiches par rôle** au même corps : de base (effort `medium`, 40 tours, routine) et `-approfondi` (effort `high`, 80 tours, jugement), générée par script et contrôlée par la CI.
2. **Fable**, par le paramètre `model` de l'appel sur la fiche `-approfondi`, **sans demander** dans trois cas seulement : échec documenté d'Opus `high` sur un blocage de raisonnement ; désaccord entre agents (Fable instruit, le mainteneur tranche quand `CLAUDE.md` le prévoit) ; rédaction d'un ADR d'architecture. Tout autre usage est proposé au mainteneur. Un changement de résultat n'appelle Fable que sur décision du mainteneur. Fable en `high` ; `xhigh` ou `max` sur accord.
3. **Escalade selon la nature du blocage** : information manquante → l'obtenir ; exploration incomplète → effort ; raisonnement → modèle. Une issue qui touche un ADR, un invariant ou un contrat partagé passe d'abord par Opus `high`.
4. **Plafonds** : par question, une relance ciblée, une hausse d'effort, une consultation Fable, puis arrêt ; au-delà de trois consultations Fable par branche (ADR compris), accord du mainteneur.
5. **Modèle indisponible** : arrêt et question au mainteneur, aucun remplacement silencieux.
6. **Lecture ciblée** par type de mission ; lecture complète réservée à la révision globale.
7. **Retour structuré** (statut, preuves vérifiées / hypothèses / non vérifiées, critères déclenchés) ; l'orchestrateur décide de la suite, l'agent ne décide pas de son escalade.
8. **Traçabilité** : journal local par hook `SubagentStop` ; une ligne par escalade dans la PR.
9. Modèles désignés par **alias**. La politique est un point de départ que chaque projet adapte (`docs/agents/routage.md`, § 9).

## Options écartées

- **Fable pour tout** (état antérieur) : qualité sûre, mais consommation maximale sur des missions routinières.
- **Une seule fiche par rôle, effort hérité de la session** : l'effort ne peut alors varier qu'avec la session entière, pas par mission.
- **Fiches jumelles tenues à la main** : dérive certaine entre les deux corps ; remplacée par une génération contrôlée par la CI.
- **Fable en `medium` par défaut** : Fable n'étant appelé qu'après filtrage des cas faciles, un passage en `medium` risquerait de gâcher l'unique consultation Fable autorisée par question ; `medium` reste possible sur indication du mainteneur.
- **Routage par le nombre d'issues ou par la confiance déclarée de l'agent** : signaux complémentaires seulement ; une issue unique à fort impact serait sous-évaluée.
- **Consultation par un workflow fixant l'effort à l'appel** : un workflow ne se lance que sur commande explicite du mainteneur (`CLAUDE.md`, « Workflows », principe 1) et sert à des circuits, pas à des consultations isolées.
- **Escalade décidée par le sous-agent** : impossible techniquement (ni modèle ni effort modifiables en cours de consultation, pas d'outil `Agent`) et contraire à la séparation constats / décision.

## Conséquences

- Fichiers : `.claude/agents/architect.md`, `expert.md` (frontmatter, lecture ciblée, bloc « Retour ») ; `architect-approfondi.md`, `expert-approfondi.md` (générées) ; `.claude/outils/fiches_jumelles.sh`, `bilan_journal.sh` ; `.claude/hooks/journal_agents.sh` et `.claude/settings.json` ; `docs/agents/routage.md` ; `CLAUDE.md`, `README.md`, `CONTEXT.md`, CI, modèle de PR, gabarit de la feuille de route.
- Effet sur les résultats : aucun (organisation des agents seulement).
- Ce que l'ADR ne règle pas : l'effort de la fiche prime sur celui de la session (documentation Claude Code des sous-agents, champ `effort` : « Overrides the session effort level ») mais n'est pas observable dans le journal ; un plafond de tours ne borne pas les tokens ; les seuils sont des valeurs de départ, à calibrer sur les premières consultations réelles (`docs/agents/routage.md`, § 8). Retour arrière : § 8 du même document.
