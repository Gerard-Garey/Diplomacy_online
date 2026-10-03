# Architecture

Ce document décrit ce que fait l'ensemble et ce que le projet a ajouté aux deux logiciels d'amont. Les chemins `amont/…` désignent les arbres préparés par `install.sh`.

## 1. Vue d'ensemble

```
        joueur humain (navigateur)
                 │
                 ▼
┌────────────────────────────────────────────┐
│ webDiplomacy  (pile Docker « webdiplomacy »)│
│  webserver (nginx, :43000)  php-fpm        │
│  mariadb   redis   sse   mailhog           │
└───────▲───────────────────────▲────────────┘
        │ API /api.php          │ API /api.php
        │ (clés bot1…bot7)      │
┌───────┴────────────┐  ┌───────┴─────────────┐
│ cicero-orders      │  │ cicero-dialogue     │
│ moteur Cicero, GPU │  │ claude_dialogue_bot │
│ calcule et soumet  │  │ lit les messages,   │
│ les ordres         │  │ appelle `claude -p`,│
│                    │  │ envoie les réponses │
└───────┬────────────┘  └───────▲─────────────┘
        │   volume partagé webdip_logs_test/  │
        ├── current_plans.json ───────────────►   plan du moteur → dialogue
        ◄── pseudo_commitments.json ──────────┤   engagements sincères → moteur
            claude_dialogue_state.json            état du bot de dialogue
```

Les deux conteneurs Cicero partagent la même image (`cicero-webdip`) ; `docker-entrypoint.sh` lance l'un ou l'autre rôle. Ils rejoignent le réseau `webdiplomacy_default` de la pile webDiplomacy, d'où le nom de projet fixé par `demarrer.sh`.

## 2. Les ordres : Cicero sans son dialogue

L'agent est `conf/common/agents/cicero_no_dialogue.prototxt` : le moteur de recherche de Cicero (BQRE1P / piKL) et son modèle de réévaluation des ordres, **sans** les modèles de dialogue de Meta, qui demandent plus de mémoire GPU que les 8 Go visés. Trois poids de modèle sont chargés (liste dans `versions.env`).

En phase de mouvement, l'ordre final est une meilleure réponse à une recherche bilatérale corrélée (`run_best_response_against_correlated_bilateral_search`, `amont/cicero/fairdiplomacy/agents/bqre1p_agent.py`). Deux propriétés en découlent, établies par lecture du code et par l'expérience :

- **Le texte des messages influence le calcul.** Les ordres plausibles de chaque paire (bot, interlocuteur) sont réévalués par un modèle qui lit la conversation de cette paire, et d'elle seule (`game_from_two_party_view`, `amont/cicero/fairdiplomacy/utils/game.py`). Un bot n'a donc jamais connaissance d'une conversation à laquelle il ne participe pas.
- **C'est une incitation, jamais une contrainte.** Chaque action candidate est notée `valeur + λ · log(probabilité)` (`br_corr_bilateral_search.py`). La valeur vient de simulations qui ne lisent aucun texte ; le dialogue ne déplace que la probabilité. Avec le réglage du projet (`br_regularize_lambda: 1e-2`), il départage des actions de valeur voisine, il ne fait pas jouer un coup nettement moins bon.

Limites à connaître :

- **Hors phase de mouvement, le dialogue n'a aucun effet.** Constructions et retraites passent par la recherche ordinaire (`use_br_correlated_search` renvoie faux). Une promesse portant sur une construction n'a aucun moyen d'être honorée par ce mécanisme.
- **Le tirage final n'a pas de graine** : à position identique, deux calculs peuvent différer. Un simple échange de messages relance le calcul du bot concerné et peut changer son ordre sans qu'aucune information nouvelle n'entre en jeu.

Pour expliquer un ordre, les journaux du moteur donnent, pour chaque action candidate, sa probabilité et sa valeur (un fichier `game_<partie>_<PUISSANCE>.log` par partie et par puissance). Ils sont montés hors du conteneur, dans `amont/cicero/journaux_moteur` (`cicero/overlay/docker-compose.yml`), et survivent donc à l'arrêt de la pile ; chaque démarrage de `cicero-orders` y ouvre un nouveau dossier horodaté.

## 3. Le dialogue : Claude, ancré sur le plan du moteur

`claude_dialogue_bot.py` interroge l'API toutes les 60 s pour chaque bot et répond aux messages reçus en appelant la CLI Claude Code en mode non interactif. Le dialogue est **réactif** : un bot n'ouvre jamais une conversation, et les bots ne se parlent pas entre eux.

Un appel à Claude en échec (réseau, quota) n'est pas pris pour un silence : `_claude_result_text` lève une erreur, le message n'est pas marqué comme traité et le cycle suivant réessaie. Seule une réponse du modèle illisible, sans échec de l'appel, vaut silence.

Le vrai Cicero procède dans l'ordre *plan → intentions → messages* : ses messages sont écrits à partir de ce qu'il compte jouer. Le projet reprend ce sens de circulation :

1. **Export du plan.** À chaque calcul, `cicero-orders` écrit dans `current_plans.json` son action préférée et les suivantes, chacune avec son **coût** (valeur perdue par rapport à la meilleure) — `fairdiplomacy/utils/plan_export.py`.
2. **Dialogue informé.** Le bot de dialogue place ce plan dans la consigne de Claude. Les alternatives sont l'essentiel : elles disent quelles concessions sont presque gratuites, donc ce qu'une négociation peut réellement faire changer.
3. **Parcimonie.** La consigne interdit de livrer le plan en bloc, d'énumérer ses unités ou de rapporter les propos d'une autre puissance. Le bluff reste permis.

## 4. Les promesses

Chaque réponse de Claude est un objet JSON à deux champs : `reply`, le message envoyé, et `sincere`, **jamais transmis au joueur**, qui liste les ordres que le bot vient de s'engager à jouer et compte réellement jouer. Un bluff figure dans `reply` et pas dans `sincere`.

Les ordres sincères suivent ce chemin :

| Étape | Où | Effet |
|---|---|---|
| Normalisation | `normalize_order_spacing` (`fairdiplomacy/utils/orders.py`) | `F TRI-ALB` devient `F TRI - ALB` |
| Filtre de légalité | `legal_commitments` (`fairdiplomacy/utils/pseudo_commitments.py`) | Un ordre impossible pour cette puissance n'est jamais retenu |
| Cohérence entre interlocuteurs | `_reject_contradictions` (`claude_dialogue_bot.py`) | Deux promesses contraires sur une même unité : la première tient, sauf si le plan qui réalise la seconde vaut nettement plus (marge `COMMITMENT_SWITCH_MARGIN`) ; l'autre devient un bluff. *Écart connu entre ce texte et le code, voir [issue #3](https://github.com/Gerard-Garey/Diplomacy_online/issues/3).* |
| Injection | `build_extra_plausible_actions`, appelée depuis `get_orders` | L'action promise est ajoutée aux candidats par le mécanisme d'amont `extra_plausible_orders` : elle ne peut pas être évincée et reçoit une probabilité calculée par le modèle |
| Renfort | `apply_commitments_to_policy` | Sa probabilité est multipliée, sous plafond. *Écart connu entre ce texte et le code, voir [issue #4](https://github.com/Gerard-Garey/Diplomacy_online/issues/4).* |

L'action promise est ensuite **évaluée comme les autres** : si sa valeur est nettement inférieure, elle n'est pas jouée. Une promesse ne peut donc pas faire jouer un bot contre son intérêt ; en contrepartie, elle n'est pas garantie.

**Registre de confiance.** Les promesses *du joueur* sont extraites de la conversation, filtrées par la même règle de légalité, puis comparées à ses ordres réels une fois la phase résolue. Le bilan (tenues, rompues, exemples) est rappelé à Claude dans les échanges suivants.

Ce que le mécanisme ne couvre pas : les engagements négatifs (« je n'entre pas en Bohême », « je ne construis pas de flotte ») n'ont pas de traduction en ordres et ne sont ni injectés ni suivis.

## 5. Ce que le projet modifie dans webDiplomacy

Quatre corrections, toutes dans `webdiplomacy/patches/` (les adaptations d'installation portées par le même patch sont décrites au § 6) :

- **Traitement automatique des phases.** Le script de démarrage d'amont (`install/gamemaster-entrypoint.sh`) appelle `gamemaster.php` avec un secret vide dans l'URL, ce qu'accepte la configuration d'exemple (`$gameMasterSecret=''` dans `config.sample.php`) ; la variable d'environnement qu'il pose aussi n'est pas lue pour un appel HTTP. `install.sh` écrit un secret non vide dans `config.php` : l'appel d'amont serait alors refusé sans erreur visible, et le patch place ce même secret dans l'URL. Sur une base neuve, ce qui bloque le traitement dans l'amont est autre : `LastProcessTime` vaut 0, et `gamemaster.php` suspend les parties tant que cette valeur a plus de 12 min (`$downtimeTriggerMinutes`) ; `demarrer.sh` la remet à l'heure (§ 6).
- **Course dans OPcache** sur ce même appel périodique (`opcache.validate_timestamps = 0`). Conséquence : après modification d'un fichier PHP, recréer le conteneur `php-fpm`.
- Robustesse de `Misc::write`, de la création de partie contre des bots, et de l'URL de validation des comptes en local.
- Service `bot-service` (bots élémentaires, profil `bots`), conservé pour les essais sans Cicero ; à ne pas faire tourner en même temps que Cicero.

## 6. Installation et reproductibilité

`install.sh` clone les amonts aux commits de `versions.env`, applique les patchs, copie les fichiers nouveaux, crée `config.php`, installe les dépendances PHP, télécharge les poids nécessaires et construit l'image. Il crée aussi le dossier `cache/` de webDiplomacy (absent d'un clone neuf, et sans lequel la création de partie échoue), installe les dépendances du serveur SSE (versions figées par le `package-lock.json` de `webdiplomacy/overlay` ; sans ce serveur, nginx ne résout pas l'hôte `sse` et le site ne démarre pas) et construit l'interface cliquable `beta/`, celle qu'ouvre par défaut un compte neuf. Rien de ce qui est propre à une machine n'est versionné : ni `.env` (jeton), ni la base, ni l'état des parties.

Ce que l'installation fixe dans webDiplomacy :

- **Variante Classic seule.** `config.php` restreint `variantIDs` à la variante 1, et la ligne Classic de `wD_VariantInfo`, vide sur une base neuve, est posée à la création de la base (`install/variantInfoClassic.sql`).
- **Base dans un volume nommé** (`webdiplomacy-db-data`) : elle est conservée par `arreter.sh`, alors qu'un volume anonyme serait perdu au premier `docker compose down`.
- **Ports publiés sur `127.0.0.1` seulement** : la pile garde les mots de passe d'amont et n'est pas faite pour être exposée.
- **Serveur SSE configuré par l'environnement du compose** (`SSE_PORT`, `REDIS_HOST`, `REDIS_PORT`, `SSE_SECRET`) : sans ces variables il écoute sur le port 3000 et cherche Redis en local, alors que nginx l'attend sur `sse:43006`.

Trois points de vigilance :

- Après plus de 12 min sans traitement, webDiplomacy suspend les parties jusqu'à une remise à l'heure de `LastProcessTime` : c'est le cas sur une base neuve et après tout arrêt prolongé de la pile. `demarrer.sh` rend d'abord aux parties en cours la durée de l'arrêt (leur échéance `processTime` est repoussée d'autant, sans quoi une phase échue pendant l'arrêt serait résolue avant le retour des bots), puis remet `LastProcessTime` à l'heure.
- Redis n'est pas persistant, et Cicero refuse de démarrer sans la clé `message_review_version` ; `demarrer.sh` la pose à chaque démarrage.
- L'état du bot de dialogue est chargé une fois en mémoire puis réécrit en entier à chaque étape. Modifier `claude_dialogue_state.json` à la main n'a d'effet que si le conteneur est **redémarré juste après**.
