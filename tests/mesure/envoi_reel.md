# M4 — essai d'envoi réel (#5) sur une partie jetable

But : vérifier sur le vrai site que le texte posté par l'API et le texte relu dans le statut
ont la même clé `_message_key` (accent, `&`, `<`, saut de ligne, émoji), ce dont dépend le
journal d'envoi (`pending_send`). Coût : aucun appel à Claude si l'étape 1 est respectée ;
GPU : les recherches que `cicero-orders` lance de lui-même sur la partie jetable.

Toutes les commandes se lancent depuis la racine du dépôt. Le texte envoyé est fixe
(`TEXTE` dans `comparer_message.py`).

**Où est la clé du bot.** Table `wD_ApiKeys` (colonne `apiKey`, jointe à `wD_Users` par
`userID`) ; les mêmes valeurs sont dans `play_webdip.api_key` de
`amont/cicero/conf/c07_play_webdip/play_cicero_full_test.prototxt` et dans `API_KEYS` de
`claude_dialogue_bot.py`. Elle n'est écrite ni ici ni dans les scripts : `comparer_message.py`
la lit dans la configuration de l'image et retrouve le compte qui tient la puissance par la
route `players/active_games`.

## 0. Préparer

```bash
bash amont/mesure/preparer.sh        # rafraîchit amont/mesure/apres/ (arbre de travail)
```

## 1. Arrêter le bot de dialogue (à annoncer au mainteneur, M12)

Sans cela, le message d'essai déclenche des appels à Claude hors budget : le bot du
destinataire y répond (`process_bot` répond à tout message reçu, jusqu'à dix échanges par
paire et par phase), et le bot de l'expéditeur lance une extraction d'engagements sur la
conversation, y compris pour un message adressé à tous.

```bash
docker stop cicero-dialogue
```

## 2. Créer la partie jetable

```bash
docker exec -e XDEBUG_MODE=off webdiplomacy-php-fpm-1 php /application/gamecreateBotsOnly.php Essai-envoi-5
```

Dernière ligne attendue : `gameID=<N>`. Dans la suite, `N` est ce numéro
(`export N=<numéro>`). Les sept comptes bots tiennent les pays 1 à 7 dans l'ordre de leurs
identifiants (pays 3 = ITALY, pays 5 = AUSTRIA).

## 3. Envoyer le message par l'API

```bash
docker run --rm --network webdiplomacy_default \
  -v "$PWD/amont/mesure:/mesure" \
  -e WEBDIP_API_URL=http://webserver/api.php \
  -e CICERO_REDIS_IP=redis -e CICERO_REDIS_PORT=6379 \
  cicero-webdip:latest \
  python /mesure/comparer_message.py envoyer "$N" ITALY AUSTRIA --confirmer-envoi
```

Sortie : le texte envoyé, le statut HTTP, la réponse du site (le message relu dans la table)
et l'issue selon `_send_outcome`. Trace : `amont/mesure/resultats/m4_envoi_<N>.json`.
Le script refuse la partie 3.

## 4. Relire le statut et comparer

```bash
docker run --rm --network webdiplomacy_default \
  -v "$PWD/amont/mesure:/mesure" \
  -e WEBDIP_API_URL=http://webserver/api.php \
  -e CICERO_REDIS_IP=redis -e CICERO_REDIS_PORT=6379 \
  cicero-webdip:latest \
  python /mesure/comparer_message.py comparer "$N" ITALY
```

Sortie : le texte tel que le site le rend (entités, `<br />`), le texte décodé par
`_messages_sent_by`, l'égalité des clés `_message_key`, les caractères envoyés absents du
texte relu (l'émoji, si la table le stocke en `?`). Code de sortie 0 si le message est
retrouvé exactement une fois. Trace : `amont/mesure/resultats/m4_comparaison_<N>.json`.

Contrôle croisé en base (lecture seule) :

```bash
docker exec webdiplomacy-db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
  -e "SELECT id, timeSent, turn, fromCountryID, toCountryID, phaseMarker, HEX(message), message FROM wD_GameMessages WHERE gameID='"$N"'"'
```

## 5. Mettre la partie jetable en pause (SQL)

Même écriture que `processGame::togglePause` (`gamemaster/game.php`) : le temps restant est
calculé avant que `processTime` soit annulé (MariaDB évalue les affectations de gauche à droite).

```bash
docker exec webdiplomacy-db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
  -e "UPDATE wD_Games SET processStatus=\"Paused\", pauseTimeRemaining=GREATEST(CAST(processTime AS SIGNED)-UNIX_TIMESTAMP(),0), processTime=NULL WHERE id='"$N"' AND name=\"Essai-envoi-5\" AND processStatus=\"Not-processing\"; SELECT id, name, phase, turn, processStatus, processTime, pauseTimeRemaining FROM wD_Games WHERE id='"$N"'"'
```

Attendu : `processStatus = Paused`, `processTime = NULL`, `pauseTimeRemaining` positif (comme
la partie 3).

## 6. Avant de relancer le bot de dialogue : retirer le message d'essai

La pause n'empêche pas le bot de répondre : `players/active_games` rend aussi les parties en
pause, et le message d'essai, sans réponse, serait traité au redémarrage (appels à Claude).
Corriger la donnée, puis redémarrer (jamais l'inverse) :

```bash
docker exec webdiplomacy-db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
  -e "DELETE FROM wD_GameMessages WHERE gameID='"$N"'; SELECT COUNT(*) FROM wD_GameMessages WHERE gameID='"$N"'"'
docker start cicero-dialogue
docker logs --since 3m cicero-dialogue 2>&1 | tail -20   # aucune ligne « replying to » pour la partie N
```

## Non vérifié tant que la procédure n'a pas tourné

- Ce que le site stocke pour l'émoji et pour les accents (`htmlentities` dans
  `Database::escape`, lu, non exécuté) : c'est l'objet de l'essai.
- Les deux requêtes SQL d'écriture (étapes 5 et 6) n'ont pas été exécutées.
- `cicero-orders` reste en marche : il calcule et soumet les ordres de la partie jetable tant
  qu'elle n'est pas en pause, et relance une recherche pour les puissances concernées à
  l'arrivée du message. Si ce temps GPU gêne, faire l'étape 5 juste après l'étape 2 :
  `SendMessage::run` (`api.php`) ne teste pas la pause (lu, non exécuté).
