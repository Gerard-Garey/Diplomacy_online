# Scripts de mesure du tableau avant / après (branche `claude/promesses`)

Copie de référence des scripts écrits et lancés depuis `amont/mesure/` (hors git) le 2026-10-03.
Pour les relancer : `mkdir -p amont/mesure && cp tests/mesure/* amont/mesure/`, puis suivre les
commandes en tête de chaque script. Les résultats (`amont/mesure/resultats/`) contiennent de
l'état de partie et ne sont pas versionnés.

| Script | Mesure | Exige |
|---|---|---|
| `rejeu_moteur.py` | recherches réelles sur une position rejouée : table exportée, action de tête, renfort non composé | `cicero-orders` arrêté (GPU), image `cicero-webdip:latest` |
| `renfort_apparie.py` | ancien et nouveau renfort appliqués à la même table réelle (#4) | les relevés de `rejeu_moteur.py` |
| `bruit_valeurs.py` | bruit des valeurs d'une recherche à l'autre (#26) : variation du gain que compare `COMMITMENT_SWITCH_MARGIN`, par groupe, par position et par paire de tables ; aucune recherche lancée, lançable hors conteneur. Reporté, à faire avant le dépouillement de la campagne : instabilité de la règle entière (marge, condition (e), `unknown_value`), erreur type de l'effet de l'engagement, dispersion dans un fichier et entre fichiers | les relevés de `rejeu_moteur.py` |
| `claude_avant_apres.py` | 160 appels réels à Claude, consigne avant / après (#17) ; plafond dur ; `--dry-run` | conteneur `cicero-dialogue` ; **accord du mainteneur** |
| `comparer_message.py`, `envoi_reel.md` | aller-retour d'un message sur le site (#5) | `cicero-dialogue` arrêté pendant l'essai |
| `preparer.sh`, `commun.py` | extraction des deux versions, outils communs | — |
