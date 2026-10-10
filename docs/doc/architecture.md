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

Un appel à Claude en échec (réseau, quota) n'est pas pris pour un silence : `_claude_result_text` lève une erreur, le message n'est pas marqué comme traité et le cycle suivant réessaie. Seule une réponse du modèle illisible, sans échec de l'appel, vaut silence. Une réponse dont le champ `reply` est nul ou vide vaut silence elle aussi : le message reçu est marqué comme traité, et rien de ce que la réponse portait par ailleurs n'est retenu — rien n'ayant été dit, rien n'a été promis (`generate_reply`, `claude_dialogue_bot.py:1171-1176`). Ces silences-là sont des décisions, message par message ; le silence de tout le bot sur un fichier d'état illisible est décrit au § 6.

Le vrai Cicero procède dans l'ordre *plan → intentions → messages* : ses messages sont écrits à partir de ce qu'il compte jouer. Le projet reprend ce sens de circulation :

1. **Export du plan.** À chaque calcul, `cicero-orders` écrit dans `current_plans.json` son action préférée et les suivantes (six plans au plus, `TOP_K`), chacune avec son **coût** : la valeur perdue par rapport à l'action préférée — `export_plans`, `fairdiplomacy/utils/plan_export.py:46`. Les plans sont classés par score (§ 2) et non par valeur : l'action préférée n'est pas toujours la mieux valorisée, et un coût peut être nul ou négatif (il est négatif pour 47 des 150 plans alternatifs exportés par les 30 recherches réelles du 2026-10-03, § 4). Trois clés accompagnent les plans :
   - `order_values` : pour chaque ordre présent dans au moins une action candidate de la recherche, et pas seulement dans les six plans exportés, la **valeur de cet ordre**, c'est-à-dire la valeur de l'action de meilleur score qui le contient — ce que le moteur jouerait s'il était tenu à cet ordre (`plan_export.py:106-111`). Ce n'est pas la meilleure valeur brute de l'ordre, qui peut venir d'une action que le moteur ne jouerait pas ;
   - `candidates` : toutes les actions candidates de la recherche, dans l'ordre du classement, chacune avec sa valeur et sa probabilité **avant** renfort (§ 4) ;
   - `search` : les paramètres de cette recherche — `lambda`, le λ réellement appliqué, qui n'est pas le réglage de 1e-2 mais ce réglage mis à l'échelle par le moteur à chaque recherche (`bqre1p_agent.py:1207-1211` ; de 0,0025 à 0,024 sur les mêmes 30 recherches) ; `boost`, le multiplicateur de renfort (1,0 si le mécanisme des engagements est désactivé dans la configuration, `exported_boost`, `plan_export.py:36`) ; `max_prob`, le plafond.

   `candidates` et `search` sont écrites ensemble ou pas du tout : s'il manque une probabilité ou un paramètre, aucune des deux ne l'est, et le bot de dialogue tient le classement pour inconnu (`_search_table`, `plan_export.py:152`). Le fichier grossit ainsi de toutes les actions candidates (35 au plus par puissance) à chaque export ; rien ne le purge à ce jour.
2. **Dialogue informé.** Le bot de dialogue place ce plan dans la consigne de Claude. Les alternatives sont l'essentiel : elles disent quelles concessions sont presque gratuites, donc ce qu'une négociation peut réellement faire changer. Un coût nul ou négatif (au plus 0,0005, `FREE_COST`) est affiché « free », sans signe ; c'est un affichage, l'export garde le chiffre (`_shown_cost`, `claude_dialogue_bot.py:168`). La consigne comporte, dans cet ordre et quand elles ont un contenu, quatre sections propres à la situation :
   - le plan : action préférée et alternatives avec leur coût (`build_plan_section`, `:128`) ;
   - « Promises you have already made this phase » : ce que le bot a déjà sincèrement promis dans la phase, à qui, et ce que coûte chaque promesse tenue, avec la règle de la trahison déclarée (`build_commitments_section`, `:399` ; § 4) ;
   - « Your own record with X » : le bilan des promesses que le bot a lui-même faites à l'interlocuteur courant, et à lui seul (`build_own_record_section`, `:466` ; § 4) ;
   - « Track record of X with you » : le bilan des promesses de l'interlocuteur (`build_trust_section`, `:493` ; registre de confiance, § 4).
3. **Parcimonie.** La consigne interdit de livrer le plan en bloc, d'énumérer ses unités, de rapporter les propos d'une autre puissance, et de révéler ce qui a été promis à une autre puissance ou qu'une promesse faite à une autre est rompue (`SYSTEM_PROMPT_TEMPLATE`, `claude_dialogue_bot.py:1043-1048`). Le bluff reste permis.

## 4. Les promesses

Chaque réponse de Claude est un objet JSON à trois champs : `reply`, le message envoyé ; `sincere`, **jamais transmis au joueur**, qui liste les ordres que le bot vient de s'engager à jouer et compte réellement jouer ; `betray`, privé lui aussi et presque toujours vide, qui liste les promesses déjà faites dans la phase que le bot **déclare rompre** (`SYSTEM_PROMPT_TEMPLATE`, `claude_dialogue_bot.py:1052-1062`). Un bluff figure dans `reply` et pas dans `sincere`. Un champ `betray` absent ou mal formé vaut liste vide : une liste à moitié lue ne doit rompre aucune promesse (`generate_reply`, `:1167-1170`).

`betray` **ne quitte jamais le bot de dialogue** : il n'est écrit dans aucun fichier lu par le moteur. Ce qui atteint le moteur reste la liste d'ordres de `pseudo_commitments.json`, issue de `sincere` ; `betray` ne fait que décider lesquels de ces ordres sont retenus.

Les ordres sincères suivent ce chemin :

| Étape | Où | Effet |
|---|---|---|
| Normalisation | `normalize_order_spacing` (`fairdiplomacy/utils/orders.py`) | `F TRI-ALB` devient `F TRI - ALB` |
| Filtre de légalité | `legal_commitments` (`fairdiplomacy/utils/pseudo_commitments.py`) | Un ordre impossible pour cette puissance n'est jamais retenu |
| Cohérence dans un message | `_reject_contradictions` (`claude_dialogue_bot.py:333`) | Deux ordres distincts pour une même unité dans la liste `sincere` d'un même message : aucun des deux n'est retenu, et la promesse déjà faite pour cette unité, s'il y en a une, reste telle quelle (ligne de journal `[double-deal]`). Le même ordre écrit deux fois compte une fois |
| Cohérence entre interlocuteurs | `_reject_contradictions` (`claude_dialogue_bot.py:220`) | Deux promesses contraires sur une même unité : la première tient, et la seconde est un bluff, sauf **trahison déclarée** — trois conditions cumulatives, détaillées ci-dessous. Une promesse remplacée est retirée chez toutes les puissances qui la détenaient, et non chez une seule |
| Injection | `build_extra_plausible_actions`, appelée depuis `get_orders` | L'action promise est ajoutée aux candidats par le mécanisme d'amont `extra_plausible_orders` : elle ne peut pas être évincée et reçoit une probabilité calculée par le modèle |
| Renfort | `boosted_policy`, appelée par `apply_commitments_to_policy` (`fairdiplomacy/utils/pseudo_commitments.py:204` et `:344`) | La probabilité de chaque action candidate est multipliée selon la **part des ordres promis qu'elle contient**, sous plafond (formule ci-dessous) |

**Renfort gradué.** Avec n le nombre d'ordres promis (légaux et sans conflit), m(a) le nombre de ceux que contient l'action candidate a, p(a) sa probabilité avant renfort et k le multiplicateur :

```
p'(a) = max( p(a), min( p(a) · k^(m(a)/n), plafond ) )
q(a)  = p'(a) / Σ p'
```

k vaut 3 (`pseudo_commitment_boost`, `cicero_no_dialogue.prototxt`) et le plafond 0,4 (`MAX_COMMITMENT_PROB`, `pseudo_commitments.py:47`). Une action qui tient toutes les promesses reçoit le multiplicateur entier, celle qui en tient la moitié sa racine carrée, celle qui n'en tient aucune n'est pas modifiée avant la renormalisation. Le `max` fait que le plafond ne peut que retenir un renfort : il n'abaisse jamais une action déjà au-dessus de lui. Seules des probabilités sont lues et écrites, jamais une valeur.

Exemple mesuré (`python3 tests/mesure_promesses.py`, lignes « 4a ») : deux ordres promis, trois actions de probabilités 0,5 (aucun ordre tenu), 0,3 (un ordre) et 0,2 (les deux). Avant renormalisation : 0,5 ; 0,3 · √3 = 0,52 ramené à 0,4 ; 0,2 · 3 = 0,6 ramené à 0,4. Après : 0,3846 / 0,3077 / 0,3077, quel que soit l'ordre dans lequel les actions sont rangées. L'égalité des deux dernières vient du plafond.

Trois conséquences à connaître :

- **La probabilité d'une action promise peut baisser.** La renormalisation répartit sur toutes les actions le renfort donné aux autres : avec deux ordres promis, la politique 0,6 (tient les deux) / 0,1 (un seul) / 0,3 (aucun) devient 0,559 / 0,161 / 0,280 (appel direct de `boosted_policy`).
- **Un ordre promis qu'aucune action candidate ne contient compte dans n** et affaiblit donc le renfort des autres ordres promis. C'est la règle décidée (k élevé à la part des promesses tenues), pas un défaut ; l'injection (ligne précédente du tableau) est ce qui fait entrer l'ordre promis parmi les candidats à la recherche suivante.
- **Le renfort ne dépend plus de l'ordre de rangement des actions.** Avant cette règle, il visait la première action rencontrée qui contenait chaque ordre promis. Mesure appariée du 2026-10-03, ancien et nouveau renfort appliqués aux mêmes tables réelles (30 recherches d'une partie 100 % bots, phases S1902M, F1902M et S1903M ; 808 jeux d'engagements fabriqués à partir des ordres de ces tables) : l'action de tête change dans 100 cas sur 808 (12,4 %) ; l'ancien résultat dépendait de l'ordre de rangement pour l'action de tête dans 120 cas (14,9 %) et pour les probabilités dans 790 (97,8 %). La comparaison est **approchée** : les valeurs viennent de recherches faites avec le nouveau renfort, et celles qu'aurait données l'ancien n'ont pas été rejouées (`tests/mesure/renfort_apparie.py` ; les relevés, qui contiennent de l'état de partie, ne sont pas versionnés).

Côté moteur, un fichier d'engagements absent, illisible ou de forme inattendue ne fait jamais échouer le calcul des ordres : `load_commitments` (`pseudo_commitments.py:50`) rend alors « aucun engagement », avec un avertissement dans le journal du moteur, et une puissance dont l'entrée n'est pas une liste d'ordres est ignorée sans que les autres le soient.

**Trahison déclarée.** Une promesse déjà faite dans la phase (notée E) n'est remplacée par un ordre contraire pour la même unité (noté N) que si trois conditions sont réunies ; sinon E tient et N est un bluff — le message part tel quel, le moteur ne voit pas N.

1. **Déclaration.** Claude a inscrit E dans `betray`, à l'identique de ce que la consigne lui affiche (les espaces autour du tiret sont normalisés avant comparaison). Sans cette déclaration, un ordre contraire est tenu pour une inattention du modèle, pas pour une décision.
2. **Gain.** La valeur de N dépasse celle de E de plus de 0,05 (`COMMITMENT_SWITCH_MARGIN`, `claude_dialogue_bot.py:42`). Les deux valeurs sont lues dans `order_values` (§ 3) : on compare ce que le moteur jouerait tenu à N et ce qu'il jouerait tenu à E. La différence est arrondie à cinq décimales, précision de l'export, et l'inégalité est stricte. La marge se compare en valeur, jamais en score.
3. **Condition (e) : le moteur jouerait N.** Une fois E échangé contre N, une action contenant N doit prendre la tête du classement du moteur après renfort.

Pourquoi trois conditions. La première sépare une décision d'une hallucination : avant elle, la règle de valeur s'appliquait seule, et un ordre contraire écrit par inadvertance retirait la promesse dès que le gain passait la marge. La deuxième donne un coût à la parole rompue et protège du bruit des valeurs, qui sont des estimations par simulation ; 0,05 est l'ordre de grandeur de l'étendue des valeurs d'une table (étendue médiane de 0,051 sur les 30 recherches réelles du 2026-10-03). La troisième évite de rompre deux promesses pour une : sans elle, le moteur peut ne jouer ni E, qu'on vient de retirer, ni N, qu'il ne retient pas. L'ADR 0004 rapporte à ce sujet une mesure d'`expert-cicero` sur 55 tables relevées dans les journaux de deux parties — sur la seule marge, près de 45 % des remplacements acceptés auraient été dans ce cas ; les couples (E, N) y étaient toutes les paires d'ordres d'une même unité, non des promesses observées, et la mesure n'a pas été refaite pour ce document.

*Calcul de la condition (e).* Il se fait dans le bot de dialogue, sur les clés `candidates` et `search` de `current_plans.json` (`engine_head_action` et `rescored_candidates`, `fairdiplomacy/utils/pseudo_commitments.py:323` et `:263`). Avec S' l'ensemble des engagements de la puissance tels que le message les laisserait (un ordre par unité, tous interlocuteurs confondus), v(a) la valeur de l'action a et λ, k, plafond les paramètres de `search` :

```
q(a)  = renfort gradué de p(a) pour les promesses S'      (formule ci-dessus, même fonction que le moteur)
s'(a) = v(a) + λ · ln( max(q(a), 1e-6) )
(e) est vraie si N appartient à l'action de s' maximal    (la première du classement en cas d'égalité)
```

Le plancher de 1e-6 est celui du moteur (`br_corr_bilateral_search.py:339`). Le renfort est calculé par `boosted_policy`, la fonction même que le moteur applique : deux copies de la formule feraient diverger la condition du comportement réel. Si la table est absente ou illisible (entrée écrite par une version antérieure, valeur ou probabilité non finie, action en double), le classement est inconnu et tout remplacement est refusé ; la consigne l'annonce alors à Claude, promesse par promesse (« cannot be replaced this phase »).

*Portée de ce calcul.* Il est **exact sur la table exportée** : sur les 30 recherches réelles du 2026-10-03, l'action de tête recalculée par le bot de dialogue était l'action exportée et l'action rendue par le moteur, 30 fois sur 30. Il est **prudent quant à l'ensemble des candidats** : la recherche suivante y ajoutera l'action injectée, que la table ne contient pas encore, et un N qu'aucun candidat ne contient est refusé. Il **ne dit rien de la réestimation des valeurs** d'une recherche à l'autre : l'hypothèse est qu'elles bougent peu, et ce bruit n'est pas mesuré. Pour que les probabilités exportées soient bien celles d'avant renfort, le patch du moteur copie la politique avant de la renforcer, passe cette copie à l'export et la remet dans le résultat de recherche (`bqre1p_agent.py:1082` et `:1242`) : sans cela, une recherche incrémentale — celle qui repart du résultat précédent — renforcerait une politique déjà renforcée. Contrôle du 2026-10-03 : probabilités exportées égales d'une recherche à la suivante sur les 4 transitions incrémentales observées (deux puissances, une phase).

*Table de décision*, appliquée unité par unité, après le filtre de légalité. Chaque ligne est un test de `tests/test_promesses.py` ; `python3 tests/mesure_promesses.py` en imprime le résultat (lignes « L0 » à « L8 »).

| Ligne | Cas | Sort de N | Journal |
|---|---|---|---|
| 0 | `reply` nul ou vide ; ou message finalement non parti (sourdine, abandon) | rien n'est retenu, ni `sincere` ni `betray` ; les promesses restent ou reviennent à ce qu'elles étaient | — (`[send-muted]`, `[send-failed]`) |
| 1 | plusieurs ordres distincts pour l'unité dans `sincere` | aucun retenu ; E tient ; un label sur E est ignoré (`conflicting`) | `[double-deal]`, et `[betrayal-ignored]` s'il y a un label |
| 2 | aucune promesse antérieure pour l'unité | accepté | — |
| 3 | N = E (redite) | accepté, à ce destinataire aussi ; un label sur E est ignoré (`restated`) | `[betrayal-ignored]` s'il y a un label |
| 4 | N ≠ E, sans label | bluff (`undeclared`) | `[double-deal]` |
| 5 | label ; valeur de N ou de E inconnue, table du moteur absente ou illisible, ou N absent de tout candidat | bluff (`unknown_value`) | `[betrayal-refused]` |
| 6 | label ; gain ≤ 0,05 | bluff (`below_margin`) | `[betrayal-refused]`, avec le gain |
| 6 bis | label ; gain > 0,05 ; condition (e) fausse | bluff (`not_played`) | `[betrayal-refused]`, avec le gain |
| 7 | label ; gain > 0,05 ; condition (e) vraie | accepté ; E retiré chez toutes les puissances qui le détenaient | `[betrayal]` par puissance trahie, `[revision]` si E avait été promis au destinataire du message |
| 8 | label sans ordre de remplacement pour l'unité (`no_replacement`), ou qui ne reproduit aucune promesse de la phase (`no_such_promise`) | le label est ignoré ; la promesse tient | `[betrayal-ignored]` |

Retirer une promesse sans la remplacer n'est donc pas possible (ligne 8). Un N illégal est écarté par le filtre de légalité avant la table (`[filtered]`) : son label reste sans remplacement.

*Plusieurs trahisons dans un même message* sont **rejugées jusqu'à stabilité** (`claude_dialogue_bot.py:359-382`). Les remplacements qui ont passé la déclaration et le gain sont projetés ensemble dans S', et l'action de tête est calculée ; tout N qui n'y figure pas est refusé (`not_played`), son E est remis dans S', et les N restants sont rejugés sur ce nouvel ensemble, jusqu'à ce qu'aucun ne soit plus retiré. Chaque tour retire au moins un N, ce qui borne le nombre de tours. Propriété obtenue : tout remplacement accepté appartient à l'action de tête calculée sur les engagements finalement enregistrés (0 exception sur 1 517 remplacements acceptés, 3 000 tables engendrées à graine fixe : `python3 tests/mesure_promesses.py`, lignes « P »). Limite assumée : l'itération ne fait que retirer. Un N refusé à un tour n'est pas rejugé ensuite, alors qu'il aurait parfois été accepté ; le refus pèche par excès, du côté prudent, puisqu'il laisse en place la promesse antérieure (ordre de grandeur rapporté par l'ADR 0004, décision 12, mesure d'`audit` non refaite ici : 42 refus sur 16 533).

*Lignes de journal.* Les refus (`[double-deal]`, `[betrayal-refused]`, `[betrayal-ignored]`) ne changent aucun engagement et sont écrits au moment du jugement. Les lignes qui annoncent un changement ne sortent qu'à la confirmation de l'envoi, au plus une fois (journal d'envoi, plus bas) :

- `[betrayal] <P> drops <E> promised to <X> in favour of <N> for <Y> (value gain …)` : une ligne par puissance X trahie, Y étant le destinataire du message ;
- `[revision] <P> replaces <E> promised to <X> with <N> in the same conversation (value gain …)` : **révision**. E avait été promis au destinataire même du message ; le remplacement suit la même règle (déclaration, gain, condition (e)) mais ne compte pas comme promesse rompue envers lui ;
- `[revision] <P> now promises <N> to <X>: <E>, promised to them earlier this phase and dropped since, no longer counts as a promise to them` : **révision séquentielle**. E, promis à X, a d'abord été trahi dans un message à un tiers ; le bot promet ensuite sincèrement N à X avant la résolution : l'ancienne promesse sort du bilan envers X (`claude_dialogue_bot.py:1584-1606`).

Une promesse trahie sans que la puissance trahie reçoive le nouvel ordre reste, elle, comptée envers cette puissance : ce qui fera foi est l'ordre joué (« Promesses du bot », plus bas).

Ces règles maintiennent un invariant : **au plus un engagement sincère par unité**, tous interlocuteurs confondus (`_reject_contradictions`, `claude_dialogue_bot.py:255`). Le moteur le contrôle une seconde fois à la lecture du fichier : si `pseudo_commitments.json` portait malgré tout deux ordres distincts pour une unité, `resolve_commitment_conflicts` (`fairdiplomacy/utils/pseudo_commitments.py:133`) les écarterait tous les deux et s'en remettrait au plan pour cette unité.

L'action promise est ensuite **évaluée comme les autres** : si sa valeur est nettement inférieure, elle n'est pas jouée. Une promesse ne peut donc pas faire jouer un bot contre son intérêt ; en contrepartie, elle n'est pas garantie.

**Journal d'envoi.** Un engagement n'a de sens que si le message qui le porte est parti. Or le site n'offre aucune clé d'idempotence, et une requête d'envoi peut paraître en échec alors que son message a été stocké. Le bot de dialogue ne renvoie donc jamais une réponse sur la foi d'une erreur : il écrit d'abord ce qu'il s'apprête à envoyer, puis tranche une issue douteuse en relisant les messages de la partie (`process_bot`, `claude_dialogue_bot.py:1225-1253`). L'ordre des écritures est fixe :

1. l'état (`claude_dialogue_state.json`) : les promesses de la phase telles que la réponse les laisse (`by_recipient`, et `own_promises` décrit plus bas), et une entrée `pending_send` — une par bot et par partie — qui dit ce qui est envoyé (message auquel on répond, destinataire, texte, phase) et de quoi le défaire (ordres ajoutés, promesses retirées avec les puissances qui les détenaient, lignes de journal en attente, nombre d'envois et de relectures) ;
2. le fichier d'engagements `pseudo_commitments.json` ;
3. le compteur d'envois, dans l'état ;
4. la requête d'envoi.

La réponse du site est ensuite classée (`_send_outcome`, `claude_dialogue_bot.py:918`) :

| Issue | Critère | Effet |
|---|---|---|
| **Confirmé** | statut 200 et corps JSON dont la liste `messages` contient le message stocké, avec son `timeSent` | message reçu marqué comme traité, échange compté, envoi noté dans `sent_ts`, `pending_send` effacé |
| **Sourdine** | statut 200 et liste `messages` vide : le destinataire a coupé les messages de cette puissance, rien n'est stocké | engagements de la réponse défaits (fichier d'engagements, puis état) ; message marqué comme traité, échange non compté ; journal `[send-muted]` |
| **Incertain** | tout le reste : autre statut, corps qui n'est pas du JSON, exception réseau | `pending_send` reste ; rien n'est renvoyé sur-le-champ ; journal `[send-uncertain]` |

Un envoi incertain se résout en tête d'un cycle suivant (`settle_pending_send`, `claude_dialogue_bot.py:1323`). Le bot cherche dans les messages de la partie un message de sa puissance au même destinataire, de même texte (à la représentation près : sauts de ligne, entités HTML, caractères que le site ne stocke pas), pas plus ancien que le message auquel il répondait, et qui ne soit pas déjà un envoi connu de `sent_ts` (`_find_pending_send`, `:896`). Trouvé, l'envoi est confirmé (`[send-confirmed]`). Absent, le bot attend un cycle (`[send-pending]`). À la seconde relecture négative de suite (`SEND_REREADS_BEFORE_RETRY`), de deux choses l'une : si la phase n'a pas changé et que moins de trois envois ont été faits (`MAX_SEND_ATTEMPTS`), il renvoie **le même texte** (`[send-retry]`) ; sinon il abandonne (`[send-failed]`) — engagements défaits, message marqué comme traité, échange non compté. Une réponse écrite dans l'état mais jamais postée (fichier d'engagements impossible à écrire, processus arrêté avant la requête) est postée à la reprise (`[send-resume]`), ou abandonnée si la phase a changé.

Ce que cela garantit et ce que cela coûte :

- **`pending_send` est sur disque avant la requête** : un conteneur arrêté entre la requête et sa confirmation retrouve l'entrée au redémarrage et relit les messages avant de poster quoi que ce soit.
- **Tant qu'un envoi est incertain, le moteur lit l'engagement** : le fichier d'engagements est écrit avant la requête, et n'est défait qu'à la sourdine ou à l'abandon. Pendant ce temps, ce bot ne traite aucun autre message de cette partie, ni la vérification des promesses, ni leur extraction (`claude_dialogue_bot.py:1410` et `:1646`) : une promesse dont le message n'est pas confirmé n'est ni jugée ni rappelée à Claude.
- **Les lignes de journal qui annoncent un changement d'engagement** (`sincere commitments -> …`, et les balises `[betrayal]` et `[revision]` d'un remplacement de promesse) sont gardées dans `pending_send` et imprimées **à la confirmation de l'envoi, une fois l'état écrit** (`confirm_send`, `:1254`). Une réponse en sourdine ou abandonnée n'en imprime aucune ; une réponse confirmée à un cycle ultérieur les imprime à ce cycle. Elles sortent **au plus une fois** : si le processus s'arrête entre l'écriture de l'état confirmé et l'impression, elles sont perdues. Un décompte de ces lignes dans les journaux est donc un minorant.

Limites connues, au regard de l'exigence « un message n'est jamais envoyé deux fois » (5.3) :

- le renvoi après deux relectures négatives peut doubler un message que le site stockerait avec plus de deux cycles de retard : rien, côté site, ne borne ce retard, et le choix de deux relectures est une prudence, pas une garantie ;
- un `pending_send` mal formé (état modifié à la main ou endommagé) ne peut être ni confirmé ni défait : le message auquel il répondait est marqué comme traité si son identifiant se lit encore, rien d'autre n'est défait ; s'il ne se lit plus, le bot l'écrit dans son journal et ce message peut recevoir une seconde réponse (`:1326-1348`) ;
- le journal d'envoi dépend du fichier d'état : sans lui, les messages déjà traités sont pris pour nouveaux (§ 6).

Mesuré : le banc sans pile (`python3 tests/test_etat_dialogue.py`, 89 tests, où le site est remplacé par la doublure `tests/faux_site.py`) et **un** essai d'envoi réel, le 2026-10-03, sur une partie jetable — un message portant accents, `&`, `<`, saut de ligne et émoji a été classé « confirmé » puis retrouvé exactement une fois par relecture ; le site a stocké l'émoji sous la forme `????`, ce que la clé de comparaison tolère (procédure : `tests/mesure/envoi_reel.md`). Cet essai ne porte ni sur la sourdine, ni sur un envoi réellement incertain, ni sur un stockage tardif : ces cas ne sont éprouvés que contre la doublure. La décision et ses motifs relèvent de l'ADR 0005 (journal d'envoi).

**Registre de confiance.** Les promesses *du joueur* sont extraites de la conversation, filtrées par la même règle de légalité, puis comparées à ses ordres réels une fois la phase résolue. Le bilan (tenues, rompues, exemples) est rappelé à Claude dans les échanges suivants.

**Promesses du bot.** Chaque bot tient aussi le bilan de ses propres promesses sincères (`own_promises`, dans `claude_dialogue_state.json`, par bot et par partie) : `pending`, les promesses non encore jugées, par phase et par destinataire, et `record`, le bilan par destinataire (tenues, rompues, dix derniers exemples de promesses rompues). Elles sont écrites à la même étape que les engagements, sous le journal d'envoi, et défaites avec eux si le message n'est pas parti. Une phase est jugée dès qu'elle figure dans la partie et n'est plus la phase courante ; la comparaison est celle du registre de confiance (`_score_promises`, `claude_dialogue_bot.py:534`), avec une règle propre au bot : une unité laissée sans ordre s'est maintenue, si bien qu'un maintien promis est tenu et tout autre ordre rompu. `pending` porte au plus un ordre par unité et par destinataire, le dernier dit sincèrement. Claude ne reçoit ce bilan que pour l'interlocuteur courant (section « Your own record with X », trois exemples au plus) : ce qui a été promis à une puissance ne doit pas pouvoir filtrer dans la conversation d'une autre.

Limites connues du mécanisme, sans correction à ce jour :

- **Table non réexportée.** Après un remplacement accepté, les messages suivants de la phase sont jugés sur la même table tant que le moteur n'a pas refait une recherche : le jugement ne voit ni l'action injectée ni les valeurs réestimées.
- **Promesse rompue réaffirmée.** Après une trahison, la section des promesses de la consigne ne montre plus rien de ce qui avait été promis à la puissance trahie, jusqu'à la phase suivante : Claude peut lui réaffirmer la promesse qu'il vient de rompre.
- **`sincere` plus large que ce qui a été dit.** Observé dans la mesure du 2026-10-10 ci-dessous : Claude a parfois rangé tout son plan préféré dans `sincere`, y compris des ordres qu'il n'avait pas énoncés. Le code ne peut pas le détecter : il ne lit pas le message.
- **Bruit des valeurs non mesuré.** La marge de 0,05 suppose que les valeurs varient peu d'une recherche à l'autre ; si ce bruit approchait la marge, elle serait à revoir. L'échelle même de la valeur (une part de score entre 0 et 1) est une hypothèse d'`expert-cicero`, non vérifiée contre le code d'amont (ADR 0004).

**Ce qui est mesuré, et ce qui ne l'est pas.** Trois niveaux de preuve, à ne pas confondre, puis ce qui manque :

- *Établi par test, sans la pile* : la table de décision, le renfort, la condition (e) et le journal d'envoi, par appel direct des fonctions et par cycles simulés (`bash tests/verifier.sh` : 172 tests pour les promesses, 89 pour l'état et l'envoi). Le site et Claude y sont des doublures.
- *Mesuré sur le moteur réel*, le 2026-10-03 : 30 recherches sur des positions rejouées d'une partie 100 % bots (phases S1902M, F1902M, S1903M) — table exportée présente 30 fois sur 30, toutes les actions présentes dans la politique d'avant renfort 30 sur 30, action de tête recalculée égale à l'action exportée et à l'action rendue 30 sur 30 (`tests/mesure/rejeu_moteur.py` ; relevés non versionnés, ils contiennent de l'état de partie).
- *Mesuré sur Claude*, le 2026-10-10 : 160 appels réels, **une seule position et une seule puissance** (même partie, S1902M, `ITALY` ; interlocuteur `AUSTRIA`, tiers `FRANCE`), 20 tirages par case, ancienne et nouvelle consigne ([relevé complet](https://github.com/Gerard-Garey/Diplomacy_online/pull/20#issuecomment-6095335803) ; script `tests/mesure/claude_avant_apres.py`). Avec la nouvelle consigne :
  - conflit où la trahison est acceptable (gain 0,062) : 11 tirages sur 20 portent un label, tous exacts ; 9 trahisons sont acceptées, 2 labels viennent sans ordre de remplacement et sont ignorés ; dans les 11 autres tirages la promesse est gardée. Avec l'ancienne consigne, 0 sur 20 inscrivait quoi que ce soit dans `sincere` ;
  - conflit sous la marge (gain 0,029) : aucun label sur 20, la condition de gain n'a pas eu à refuser ;
  - révision avec le destinataire : 20 labels exacts et 20 révisions acceptées sur 20 ;
  - aucun ordre contraire sans label sur 100 réponses ; aucune sortie JSON illisible sur 60 ;
  - **critère non tenu** : dans la situation sans conflit, 1 tirage sur 20 porte un label — Claude y range tout son plan préféré dans `sincere` et déclare la trahison d'une promesse faite au tiers, que le moteur accepte. Le même sur-remplissage de `sincere`, sans trahison, apparaît 3 fois sur 20 dans la situation où le bilan du bot est rappelé ;
  - une réponse sur 100 nomme le tiers, comme une menace et sans révéler ni la promesse ni l'ordre promis (détection textuelle, lecture à confirmer par le mainteneur) ;
  - la consigne système passe d'environ 4 620 à environ 6 100 caractères dans les trois situations comparées.

  Vingt tirages ne distinguent que de gros écarts, et une position ne fonde pas une statistique : ces fréquences décrivent cette position, pas le comportement des bots en général.
- *Non mesuré* : une autre puissance, une autre phase ; le bruit des valeurs d'une recherche à l'autre ; les paraphrases d'une fuite ; l'effet de ces règles sur une partie jouée contre un humain.

Ce que le mécanisme ne couvre pas : les engagements négatifs (« je n'entre pas en Bohême », « je ne construis pas de flotte ») n'ont pas de traduction en ordres et ne sont ni injectés ni suivis.

## 5. Ce que le projet modifie dans webDiplomacy

Trois corrections portées par le patch `webdiplomacy/patches/0001-webdiplomacy.patch` (les adaptations d'installation du même patch sont décrites au § 6), et deux ajouts en fichiers nouveaux, dans `webdiplomacy/overlay/` :

- **Traitement automatique des phases.** Le script de démarrage d'amont (`install/gamemaster-entrypoint.sh`) appelle `gamemaster.php` avec un secret vide dans l'URL, ce qu'accepte la configuration d'exemple (`$gameMasterSecret=''` dans `config.sample.php`) ; la variable d'environnement qu'il pose aussi n'est pas lue pour un appel HTTP. `install.sh` écrit un secret non vide dans `config.php` : l'appel d'amont serait alors refusé sans erreur visible, et le patch place ce même secret dans l'URL. Sur une base neuve, ce qui bloque le traitement dans l'amont est autre : `LastProcessTime` vaut 0, et `gamemaster.php` suspend les parties tant que cette valeur a plus de 12 min (`$downtimeTriggerMinutes`) ; `demarrer.sh` la remet à l'heure (§ 6).
- **Course dans OPcache** sur ce même appel périodique (`opcache.validate_timestamps = 0`). Conséquence : après modification d'un fichier PHP, recréer le conteneur `php-fpm`.
- Robustesse de `Misc::write`, de la création de partie contre des bots, et de l'URL de validation des comptes en local.
- Service `bot-service` (bots élémentaires, profil `bots`), conservé pour les essais sans Cicero ; à ne pas faire tourner en même temps que Cicero. Le `docker-compose.yml` d'amont déclare déjà ce service ; ses sources sont un ajout (`webdiplomacy/overlay/bot-service/`).
- **Partie 100 % bots** : `gamecreateBotsOnly.php` (`webdiplomacy/overlay/`, aucun patch), qui crée une partie dont les sept puissances sont tenues par les comptes de type bot. Elle sert aux essais : elle fournit, sans action humaine, des positions à rejouer.
  - **Ligne de commande seulement.** Appelé par le serveur web, le script répond 403 avant d'avoir rien chargé (`gamecreateBotsOnly.php:17-21`) : aucune page ni aucun compte ne permet de créer une telle partie, et « administrateur » désigne ici l'opérateur du poste.
  - **Ce qu'il reprend et ce qu'il change.** Il reprend la création de `botgamecreate.php` — variante Classic, presse « Regular », phases de trois jours (`:81-82`) — avec trois différences. `playerTypes` vaut `Members` et non `MemberVsBots`, parce qu'à chaque changement de phase l'amont examine, pour toute partie d'un autre type, s'il ne reste que des bots, afin d'y forcer la nulle (`amont/webdiplomacy/gamemaster/game.php:849-850`). `missingPlayerPolicy` vaut `Wait` et non `Normal`. Les sept comptes dont le type contient « bot », pris par identifiant croissant, reçoivent les pays 1 à 7, sans créateur humain (`:73-86`).
  - **Nom de la partie.** Un argument, de 1 à 50 caractères parmi lettres non accentuées, chiffres, `_`, `.` et `-`, le premier étant alphanumérique. Tout nom commençant par « SB » suivi d'un caractère est refusé, quelle que soit la casse (`:30`) : l'amont reconnaît ses bacs à sable par `name LIKE 'SB_%'`, où `_` est un joker, et repousse leur échéance à une date qui n'arrive jamais (`gamemaster/backgroundTasks.php:274`) — la partie ne se résoudrait plus. Un nom déjà pris est refusé lui aussi, au lieu d'être suffixé en silence (`:68-70`).
  - **Issue.** Code 0 et dernière ligne `gameID=<n>` (`:116-117`) ; code 2 sur un mauvais usage, avant toute connexion à la base (`:29-36`) ; code 1 sur tout échec, transaction annulée, rien n'étant créé (`:96-102`), y compris quand l'amont arrête le script par ses propres erreurs (`:38-48`). Il faut exactement sept comptes de type bot (`:76-77`). L'indice `processHint` donné au traitement des phases est écrit après la validation de la transaction ; son échec ne défait pas la partie, qui démarre au cycle suivant (`:104-113`).
  - **Portée.** Dans une telle partie les bots ne se parlent pas (§ 3 : un bot n'ouvre jamais une conversation) : elle donne des positions, pas des promesses. Une partie a été créée ainsi le 2026-10-03 (partie 3 de la machine d'origine) ; les positions rejouées citées au § 4 (S1902M, F1902M, S1903M) en viennent, ce qui établit qu'elle a avancé sans action humaine jusqu'au printemps 1903 au moins. Le script ne prévoit pas son arrêt : le mainteneur l'arrête par une pause posée en SQL une fois les positions recueillies.

## 6. Installation et reproductibilité

`install.sh` clone les amonts aux commits de `versions.env`, applique les patchs, copie les fichiers nouveaux, crée `config.php`, installe les dépendances PHP, télécharge les poids nécessaires et construit l'image. Il crée aussi le dossier `cache/` de webDiplomacy (absent d'un clone neuf, et sans lequel la création de partie échoue), installe les dépendances du serveur SSE (versions figées par le `package-lock.json` de `webdiplomacy/overlay` ; sans ce serveur, nginx ne résout pas l'hôte `sse` et le site ne démarre pas) et construit l'interface cliquable `beta/`, celle qu'ouvre par défaut un compte neuf. Rien de ce qui est propre à une machine n'est versionné : ni `.env` (jeton), ni la base, ni l'état des parties.

Ce que l'installation fixe dans webDiplomacy :

- **Variante Classic seule.** `config.php` restreint `variantIDs` à la variante 1, et la ligne Classic de `wD_VariantInfo`, vide sur une base neuve, est posée à la création de la base (`install/variantInfoClassic.sql`).
- **Base dans un volume nommé** (`webdiplomacy-db-data`) : elle est conservée par `arreter.sh`, alors qu'un volume anonyme serait perdu au premier `docker compose down`.
- **Ports publiés sur `127.0.0.1` seulement** : la pile garde les mots de passe d'amont et n'est pas faite pour être exposée.
- **Serveur SSE configuré par l'environnement du compose** (`SSE_PORT`, `REDIS_HOST`, `REDIS_PORT`, `SSE_SECRET`) : sans ces variables il écoute sur le port 3000 et cherche Redis en local, alors que nginx l'attend sur `sse:43006`.

Quatre points de vigilance :

- Après plus de 12 min sans traitement, webDiplomacy suspend les parties jusqu'à une remise à l'heure de `LastProcessTime` : c'est le cas sur une base neuve et après tout arrêt prolongé de la pile. `demarrer.sh` rend d'abord aux parties en cours la durée de l'arrêt (leur échéance `processTime` est repoussée d'autant, sans quoi une phase échue pendant l'arrêt serait résolue avant le retour des bots), puis remet `LastProcessTime` à l'heure.
- Redis n'est pas persistant, et Cicero refuse de démarrer sans la clé `message_review_version` ; `demarrer.sh` la pose à chaque démarrage.
- L'état du bot de dialogue est lu sur le disque au premier cycle, gardé en mémoire, puis réécrit en entier à chaque étape, par fichier temporaire et `os.replace` : un arrêt en cours d'écriture laisse le fichier précédent intact (`_write_json_file`, `claude_dialogue_bot.py:739`). Modifier `claude_dialogue_state.json` à la main n'a donc d'effet que si le conteneur est **redémarré juste après** ; sinon l'état en mémoire réécrit le fichier.
- Un fichier d'état ou d'engagements **présent mais illisible** (tronqué, vide, autre chose qu'un objet JSON, inaccessible), ou un fichier d'engagements dont la forme n'est pas `{partie: {phase: {puissance: [ordres]}}}`, n'est ni pris pour un état vide ni écrasé. Le bot de dialogue reste en vie et **muet** : aucun message lu, aucun appel à Claude, aucun envoi, aucune écriture ; il répète une ligne `[silent]` qui nomme le fichier et dit quoi faire, abandonne son état en mémoire et le relit sur le disque au premier cycle où les deux fichiers sont lisibles (`run_cycle`, `:1712` ; `check_state_files`, `:801`). C'est le seul cas où une réparation à la main se fait **sans redémarrage**. Le contrôle est refait avant chaque appel à Claude, après lui et à chaque écriture. Le silence vaut pour tous les bots et toutes les parties, même si une seule partie est en cause. Un fichier **absent** vaut état vide : sans le fichier d'état, les messages déjà traités recevraient une seconde réponse. Le moteur, lui, continue de calculer ses ordres, sans les engagements qu'il ne peut pas lire (§ 4).
