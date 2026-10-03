# Glossaire

Vocabulaire à employer tel quel dans le code, la documentation, les issues et les comptes rendus d'agents. Un terme nouveau ou précisé est ajouté par `architect`.

## Domaine

- **Amont** : l'un des deux logiciels tiers, Cicero ou webDiplomacy, à son commit épinglé ; par extension le dossier `amont/` où `install.sh` les prépare. *Ne pas dire* : upstream, vendor.
- **Patch** : modification d'un fichier existant d'un amont (`*/patches/`). **Overlay** : fichier nouveau copié dans un amont (`*/overlay/`).
- **Puissance** : l'un des sept pays du jeu, en majuscules et en anglais comme dans le code (`AUSTRIA`, `ITALY`…). *Ne pas dire* : nation, joueur (un joueur *tient* une puissance).
- **Bot** : compte `bot1`…`bot7` de webDiplomacy tenant une puissance ; ses ordres viennent du moteur, ses messages de Claude. La correspondance bot ↔ puissance change à chaque partie.
- **Moteur** : la recherche stratégique de Cicero (BQRE1P / piKL) qui calcule les ordres, conteneur `cicero-orders`. *Ne pas dire* : l'IA, Cicero tout court (ambigu avec son dialogue, que le projet n'utilise pas).
- **Bot de dialogue** : `claude_dialogue_bot.py`, conteneur `cicero-dialogue`.
- **Phase** : `S1901M`, `F1901M`, `W1901A`… (saison, année, type : `M` mouvement, `R` retraite, `A` ajustement). Le dialogue n'agit sur les ordres qu'en phase de mouvement.
- **Ordre** : instruction pour une unité, en notation du moteur, avec espaces (`F TRI - ALB`, `A BUD S A SER`). **Action** : l'ensemble des ordres d'une puissance pour une phase.
- **Ordres plausibles** : les actions candidates (35 au plus) entre lesquelles le moteur choisit ; une action absente de cette liste ne peut pas être jouée.
- **Plan** : l'action préférée du moteur et ses alternatives, chacune avec son **coût** (valeur perdue par rapport à la meilleure), exportées dans `current_plans.json`.
- **Ordre en cache** : l'ordre qu'un bot jouerait si la phase se résolvait maintenant, lu par `check_orders.sh` ; il peut encore changer.
- **Promesse** : engagement, pris dans un message, de jouer un ordre précis cette phase. **Engagement sincère** : promesse que le bot compte tenir, inscrite dans le champ privé `sincere`. **Bluff** : promesse faite dans le message et absente de `sincere`.
- **Promesse rompue** : promesse légale au moment où elle a été faite, non retrouvée dans les ordres résolus. Un ordre impossible ou illégal n'est jamais une promesse.
- **Trahison** : remplacement d'un engagement sincère par un autre, contraire, sur la même unité, retiré chez toutes les puissances qui détenaient le premier (ligne de journal `[betrayal]` par puissance trahie). Depuis l'ADR 0004, elle n'est acceptée que **déclarée** : Claude inscrit la promesse rompue dans le champ privé `betray` **et** le plan qui réalise le nouvel ordre vaut nettement plus (`COMMITMENT_SWITCH_MARGIN`) ; sinon la première promesse tient et le nouvel ordre est un bluff (`[double-deal]` sans label, `[betrayal-refused]` avec label et gain insuffisant). *Ne pas dire* : trahison pour un ordre contraire sans label (c'est une hallucination ou un bluff). **Double jeu** : promesses contraires faites à deux puissances sur une même unité (`[double-deal]`).
- **Trahison déclarée** : la trahison au sens ci-dessus, le terme insistant sur la déclaration par le label ; `betray` ne quitte jamais le bot de dialogue. **Révision** : même règle (label et marge) quand la promesse remplacée avait été faite au destinataire même du message ; notée `[revision]`, elle ne compte pas comme promesse rompue envers lui.
- **Promesses du bot** (`own_promises`) : promesses sincères que le bot a lui-même faites, conservées par partie et par puissance dans `claude_dialogue_state.json`, résolues contre ses ordres joués ; Claude n'en reçoit le bilan que pour l'interlocuteur courant.
- **Registre de confiance** : bilan, tenu par chaque bot, des promesses tenues et rompues par chaque interlocuteur.
- **Ancrage** : le fait que le dialogue soit écrit à partir du plan du moteur. *Ne pas dire* : grounding.
- **Partie ordinaire** : un humain contre six bots (exigence 1.1). **Partie 100 % bots** : partie d'essai dont les sept puissances sont tenues par des bots, lançable seulement par un administrateur ou directement par Claude ; elle fournit, sans action humaine, les positions à rejouer. *Ne pas dire* : partie automatique, self-play (qui désigne l'entraînement de Cicero).
- **Position rejouée** : l'état d'une partie ramené au début d'une phase donnée (`rolled_back_to_phase_start`), sur lequel on relance le calcul du moteur ou le bot de dialogue ; support des tableaux avant / après. Le tirage n'ayant pas de graine, une même position rejouée ne redonne pas forcément les mêmes ordres.
- **Clef en main** : un `git clone` suivi de `./install.sh` et `./demarrer.sh` suffit, sans rien reprendre d'une autre machine.

## Organisation du travail

- **Branche de travail** : l'unique branche `claude/…` en cours, au périmètre fermé d'issues, portée par une PR brouillon vers `main`.
- **Correctif rapide** : modification hors périmètre qui laisse les résultats strictement identiques, touche un seul domaine de commit et pas la documentation de fond ; branche temporaire partie de `main`, PR directe.
- **Tableau avant / après** : pour un commit qui change un résultat, une ligne par grandeur modifiée (avant, après, écart, explication).
- **Visa** : approbation d'un tableau avant / après — par le mainteneur pour un résultat final ou un verdict, par `expert` sinon. Sans visa, rien n'est commité.
- **Surface d'impact documentaire** : liste, dans le commit proposé par `coder`, des endroits de la documentation que la modification oblige à rouvrir ; point de départ de `docwriter`.
- **Constat** : défaut du code relevé par un vérificateur, avec gravité (bloquant / majeur / mineur), `fichier:ligne` et mesure exécutée. Conduit à une reprise ou à un arrêt.
- **Question pour `expert`** : doute sur le fond, qui n'est pas un défaut du code ; ne relance pas `coder`.
- **Audit léger** : lecture du diff et des fonctions touchées avec leurs appelants et appelés.
- **Revue finale complète** : lecture de tout `git diff main...HEAD`, batteries complètes et scénarios adverses, avant la sortie du brouillon.
- **Mesure** : commande exécutée et sa sortie, qui fonde une affirmation sur le comportement du code.
- **Consultation** : un appel d'un agent de pilotage ou de fond par la session principale ; se termine par un bloc « Retour » (statut `complet`, `partiel` ou `revue requise`).
- **Routine / jugement** : les deux niveaux d'une consultation d'`architect` ou d'`expert` — fiche de base (Opus, effort `medium`) ou fiche `-approfondi` (Opus, effort `high`) ; voir `docs/agents/routage.md`.
- **Escalade** : passage d'une consultation à un niveau supérieur, hausse d'effort (routine → jugement) ou changement de modèle (Opus → Fable), sur un critère observable ; distincte de la **relance ciblée** (même agent, même fiche, retour incomplet) et de la demande d'information.
- **Question** (routage) : la question résiduelle d'une consultation, rattachée à une issue ou à une mission ; unité des plafonds de `docs/agents/routage.md` (§ 5.2) ; la reformuler ne remet pas ses plafonds à zéro.
- **Dossier d'escalade** : question résiduelle, contraintes, conclusions établies, sources, tentatives, contradictions et preuve attendue, transmis à la consultation suivante pour éviter une nouvelle revue globale.
