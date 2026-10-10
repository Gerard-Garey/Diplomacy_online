# Scripts de mesure du tableau avant / après (branche `claude/promesses`)

Copie de référence des scripts écrits et lancés depuis `amont/mesure/` (hors git) le 2026-10-03.
Pour les relancer : `mkdir -p amont/mesure && cp tests/mesure/* amont/mesure/`, puis suivre les
commandes en tête de chaque script. Les résultats (`amont/mesure/resultats/`) contiennent de
l'état de partie et ne sont pas versionnés.

| Script | Mesure | Exige |
|---|---|---|
| `rejeu_moteur.py` | recherches réelles sur une position rejouée : table exportée, action de tête, renfort non composé | `cicero-orders` arrêté (GPU), image `cicero-webdip:latest` |
| `renfort_apparie.py` | ancien et nouveau renfort appliqués à la même table réelle (#4) | les relevés de `rejeu_moteur.py` |
| `bruit_valeurs.py` | bruit des valeurs d'une recherche à l'autre (#26) : variation du gain que compare `COMMITMENT_SWITCH_MARGIN`, par groupe, par position et par paire de tables ; aucune recherche lancée, lançable hors conteneur. Le critère se lit sur les recherches A sans engagement, seules (les recherches B, mises à jour incrémentales du même tirage, et le cumul A + B sont informatifs) ; la ligne du verdict dit dans combien de tables, d'ordres et de positions tombent les acceptations sur bruit. Trois compléments : la règle entière (`_reject_contradictions` rejouée sur chaque table, avec le vrai `engine_head_action` : désaccord par paire de tables, attribution à la marge, à la condition (e) ou à `unknown_value` ; acceptations sur bruit effectives, et à part celles qu'aucune autre table ne permet de comparer) ; l'effet de la recherche B apparié par tirage, avec erreur type et intervalle de Student, et sa synthèse entre positions sur les couples estimés sur au moins trois tirages ; la dispersion dans un fichier et entre fichiers (permutation exacte, tables jumelles — le contrôle par `search.lambda` suppose un lambda dynamique —, engagements différents d'un fichier à l'autre), dont un rejet rend le verdict non concluant. À côté du verdict, informatif et hors verdict (décision du mainteneur, 2026-10-10) : le décompte par événement — unité (table, E) sur les recherches A, jugée par la règle entière ; part des (table, E) exposés qui ont une acceptation sur bruit, part des remplacements acceptés qui sont sur bruit, lecture indicative « protégerait » / « partiel » / « ne protégerait pas » ; la même restreinte aux promesses « réalistes » (E dans un des plans exportés de la table jugée), et le rappel « marge seule » | les relevés de `rejeu_moteur.py` |
| `claude_avant_apres.py` | 160 appels réels à Claude, consigne avant / après (#17) ; plafond dur ; `--dry-run` | conteneur `cicero-dialogue` ; **accord du mainteneur** |
| `comparer_message.py`, `envoi_reel.md` | aller-retour d'un message sur le site (#5) | `cicero-dialogue` arrêté pendant l'essai |
| `preparer.sh`, `commun.py` | extraction des deux versions, outils communs | — |
