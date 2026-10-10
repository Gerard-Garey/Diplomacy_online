# Cahier des charges

Ce document fixe ce que le projet doit faire ; `CLAUDE.md` renvoie ici pour le fond. Chaque exigence est numérotée pour être citée dans les issues, les ADR et les revues (`docs/exigences.md` § 2.3).

## 1. Objet et destinataires

1.1. Faire jouer un humain à Diplomacy, sur une instance locale de webDiplomacy, contre six bots dont les ordres viennent du moteur de recherche de Cicero et les messages de Claude.

1.2. Servir de banc d'expérience sur la négociation : influence du dialogue sur les ordres, tenue des promesses, réaction à une trahison. Ce qui prime est de **pouvoir expliquer un comportement observé**, par le code et par une mesure.

1.3. Être installable par un tiers, sur une autre machine, à partir du seul dépôt.

## 2. Exigences de fond

2.1. **Le moteur décide.** Les ordres sont calculés par la recherche de Cicero ; aucun mécanisme du projet ne doit pouvoir faire jouer à un bot une action nettement inférieure, en valeur, à sa meilleure action. Le dialogue n'agit que comme incitation.

2.2. **Le dialogue part du plan.** Un bot négocie en connaissant son action préférée et ses alternatives, avec leur coût, afin qu'une négociation puisse réellement modifier son plan.

2.3. **Parcimonie.** Un bot ne divulgue que ce que l'accord discuté exige ; jamais son plan entier, jamais les propos ni les intentions prêtées à une autre puissance.

2.4. **Le mensonge est permis, mais distingué.** Un bot peut bluffer dans un message. Seuls ses engagements sincères sont transmis au moteur, de sorte qu'un bluff ne puisse pas devenir vrai par ce canal.

2.5. **Une seule parole par unité.** Deux engagements sincères contraires sur une même unité ne coexistent pas ; le second ne remplace le premier que si le bot déclare la rupture, si le plan qui le réalise vaut nettement plus et si le moteur le jouerait ; sinon le premier tient et le second est un bluff.

2.6. **Un ordre impossible ou illégal n'est jamais une promesse**, ni pour un bot ni pour le joueur.

2.7. **Mémoire des promesses du joueur.** Chaque bot tient le bilan des promesses que le joueur lui a faites et tenues ou rompues, et sa confiance en dépend. Chaque bot tient aussi le bilan de ses propres promesses, et ne le rappelle à Claude que pour l'interlocuteur courant.

2.8. **Cloisonnement.** Un bot n'a accès qu'à ses propres conversations ; les bots ne se parlent pas entre eux ; un bot n'ouvre jamais une conversation.

2.9. **Fidélité à Cicero.** Le projet étend les mécanismes de Cicero plutôt que de s'en éloigner. Décision du mainteneur du 2026-08-19 : les engagements négatifs (zone démilitarisée, renoncement à une construction) et l'effet du dialogue hors phase de mouvement ne sont **pas** traités, parce qu'ils sortiraient de ce cadre.

2.10. **Niveau de rigueur.** Distinguer ce qui est établi par lecture du code, ce qui est mesuré sur une partie, et ce qui est supposé. Une seule partie ne fonde pas une statistique.

2.11. **Accord préalable.** Toute modification d'un paramètre ou d'une consigne qui change le comportement ou la force des bots est annoncée au mainteneur, avec son effet attendu, avant d'être appliquée.

## 3. Exigences documentaires

3.1. `docs/doc/architecture.md` permet à un lecteur sans accès au code de comprendre qui calcule quoi, par où passe l'information, et ce que le mécanisme des promesses garantit ou non.

3.2. `README.md` suffit pour installer et démarrer, et **dit ce qui a été validé et ce qui ne l'a pas été**.

3.3. Les limites connues sont écrites là où le lecteur les cherchera, pas seulement dans un ADR.

## 4. Exigences d'architecture

4.1. Le dépôt ne contient que les patchs et fichiers nouveaux ; les amonts sont épinglés par `versions.env`.

4.2. **Clef en main** : `git clone`, `./install.sh`, `./demarrer.sh`, sur Ubuntu avec GPU NVIDIA d'au moins 8 Go, Docker et `nvidia-container-toolkit`. L'image Cicero se construit depuis les sources, sans rien reprendre d'une autre machine.

4.3. Aucune donnée locale dans le dépôt : ni jeton, ni base de données, ni comptes, ni état de partie, ni chemin personnel. La base se crée vide au premier démarrage.

4.4. `install.sh` est relançable et s'arrête, sur un prérequis manquant, avec un message qui dit quoi faire.

4.5. Les amonts appliqués par `install.sh` sont identiques à l'arbre de travail du mainteneur (`outils/exporter_patchs.sh --verifier`).

## 5. Interface

5.1. L'interface de jeu est celle de webDiplomacy, que le projet ne redessine pas.

5.2. Un message de bot est toujours un texte de joueur : jamais de sortie brute de modèle, de JSON ni de mention d'IA ; il est écrit dans la langue du message reçu.

5.3. Un message n'est jamais renvoyé sur la foi d'une erreur : un envoi incertain est d'abord relu dans les messages de la partie, y compris après le redémarrage d'un conteneur ; un renvoi après deux relectures négatives peut encore doubler un message que le site aurait stocké avec retard (ADR 0005, écart 3).

5.4. Une phase se résout sans action d'administration dès que tous les joueurs actifs sont prêts.

5.5. `check_orders.sh <gameID>` donne, pour toute partie en cours, les ordres en cache de chaque bot.
