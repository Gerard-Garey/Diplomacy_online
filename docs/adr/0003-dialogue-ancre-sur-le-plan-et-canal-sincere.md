---
status: accepted
date: 2026-08-19
---

# Le dialogue est ancré sur le plan du moteur ; seuls les engagements sincères reviennent au moteur

ADR rédigé a posteriori, le 2026-10-02, à partir des décisions prises par le mainteneur pendant les parties 15 et 22.

## Contexte

Dans la première version, Claude écrivait les messages des bots sans connaître ce que le moteur comptait jouer : les promesses étaient souvent rompues, non par calcul mais parce qu'elles ne reposaient sur rien. La lecture du code d'amont a montré que réactiver les « pseudo-ordres » de Cicero n'était pas le levier attendu : ils servent à écrire son propre dialogue, dépendent de modèles trop lourds pour 8 Go, et `get_orders` ne les reçoit pas.

## Décision

Arrêtée par le mainteneur entre le 2026-08-15 et le 2026-08-19.

1. Le moteur exporte son plan (action préférée, alternatives, coût de chacune) ; le bot de dialogue le fournit à Claude.
2. Le mensonge reste permis ; la consigne impose la parcimonie.
3. Claude rend, avec chaque message, la liste privée de ses engagements sincères. Elle seule est transmise au moteur.
4. Un engagement sincère entre dans les ordres plausibles par le mécanisme d'amont `extra_plausible_orders`, puis est évalué comme toute autre action. Deux actions injectées au plus par calcul, pour borner le coût.
5. Entre deux engagements contraires sur une même unité, le premier tient, sauf si le plan réalisant le second vaut plus d'une marge (0,02) de mieux.
6. Un ordre impossible ou illégal n'est retenu comme promesse ni pour un bot ni pour le joueur.
7. Chaque bot tient le registre des promesses du joueur.
8. Les engagements négatifs et l'effet du dialogue hors phase de mouvement ne sont pas traités, pour rester proche de Cicero (2026-08-19).

## Options écartées

- **Dialogue sans mensonge**, à la manière de Cicero : écarté par le mainteneur, qui veut observer le bluff.
- **Extraire les engagements par une seconde lecture de la conversation** : cet appel n'a pas vu l'intention et ne peut pas distinguer un bluff ; conservé seulement pour les promesses du joueur.
- **Renforcer la probabilité d'un ordre sans l'évaluer** (première version) : un ordre halluciné recevait un poids arbitraire. Remplacé par l'injection, qui soumet l'ordre aux simulations.
- **Consigne seule contre le double jeu** : mesurée insuffisante, Claude s'engageant malgré elle sur deux ordres contraires ; la règle est appliquée par le code.

## Conséquences

- Fichiers : `plan_export.py`, `pseudo_commitments.py`, `claude_dialogue_bot.py`, `searchbot_agent.py`, `bqre1p_agent.py`, `agents.proto`, `cicero_no_dialogue.prototxt`.
- Effet attendu, à mesurer : les promesses de coût quasi nul devraient tenir ; celles qui demandent un vrai sacrifice restent rompues, puisque la valeur domine par construction.
- Coût : chaque action injectée ajoute des simulations. La mémoire GPU a déjà été saturée une fois par cette recherche (`bilateral_search_num_cond_sample` ramené de 20 à 10).
- Non réglé : aucune référence de non-régression ; les essais de `cicero/overlay/essais/` reposent sur la partie 15 de la machine d'origine.
