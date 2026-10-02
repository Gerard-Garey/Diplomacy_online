# Routage du modèle et de l'effort des agents de pilotage et de fond

Politique appliquée par la session principale quand elle consulte `architect` ou `expert` (et toute fiche d'expert dupliquée). Décision : ADR 0001. Les agents de réalisation et de vérification (`coder`, `docwriter`, `audit`, `app-review`) ne sont pas concernés : leur fiche fixe leur modèle.

**Point de départ, pas politique figée.** Les valeurs ci-dessous sont celles du modèle de dépôt. Chaque projet créé à partir du modèle les adapte à son domaine, à son architecture et à ses risques (passages **À ADAPTER**, § 9), puis les réévalue à mesure qu'il évolue (§ 8).

## 1. Principes

1. **Opus par défaut, Fable rarement.** Fable est réservé aux cas du § 4.1, ou à l'accord du mainteneur ; il n'est jamais un réflexe devant une difficulté.
2. **L'effort se règle indépendamment du modèle** : `medium` pour la routine, `high` pour le jugement.
3. **Les sous-agents rendent des constats, des preuves et des points ouverts ; la session principale applique la politique et décide de la suite.** Un agent signale les critères qu'il a rencontrés (§ 6), il ne décide pas de sa propre escalade, et il ne peut lancer aucun autre agent (l'outil `Agent` est absent de sa liste d'outils).
4. **Aucune escalade sans motif observable, aucune boucle** : plafonds du § 5.
5. **Aucun remplacement silencieux** d'un modèle par un autre (§ 5.3).

## 2. Mécanisme

Le paramètre `model` d'un appel `Agent` l'emporte sur le `model` de la fiche ; l'effort, lui, ne peut pas être passé à l'appel et vient de la fiche (champ `effort`), qui prime sur l'effort de la session (documentation Claude Code des sous-agents, champ `effort` : « Overrides the session effort level ») mais n'est pas observable dans le journal (§ 7). D'où deux fiches par rôle, au même corps :

| Fiche | Modèle servi | Effort | `maxTurns` | Usage |
|---|---|---|---|---|
| `architect`, `expert` | `opus` | `medium` | 40 | routine (§ 3) |
| `architect-approfondi`, `expert-approfondi` | `opus` | `high` | 80 | jugement (§ 3) |
| `architect-approfondi`, `expert-approfondi` appelées avec `model: "fable"` | Fable (fiche : `opus`, l'appel l'emporte) | `high` | 80 | cas du § 4.1, ou accord du mainteneur |

- Les fiches `-approfondi` sont **générées** par `bash .claude/outils/fiches_jumelles.sh` à partir de la fiche de base : seul le frontmatter diffère (nom, description, effort, `maxTurns`). Ne jamais les modifier à la main ; la CI vérifie la concordance (`--verifier`). La liste des rôles dédoublés est la variable `ROLES` du script (**À ADAPTER** : un expert dupliqué y est ajouté).
- Fable en `xhigh` ou `max` : jamais sans accord explicite du mainteneur (il faudrait alors une troisième fiche, à créer sur décision). Fable en `medium` (fiche de base appelée avec `model: "fable"`) : sur indication explicite du mainteneur seulement.
- Les modèles sont désignés par **alias** (`opus`, `fable`), qui suivent les nouvelles versions ; le journal (§ 7) note la version effectivement servie.
- Une fiche modifiée n'est prise en compte que par une **session neuve** (`docs/agents/issue-tracker.md`, constat 3).

## 3. Matrice

« Routine » = fiche de base (Opus `medium`) ; « jugement » = fiche `-approfondi` (Opus `high`) ; « Fable » = fiche `-approfondi` avec `model: "fable"`.

| Rôle | Mission | Signaux observables | Départ | Preuves attendues | Suite | Arrêt |
|---|---|---|---|---|---|---|
| architect | Rattacher les nouvelles issues au point d'étape (lot) | aucun critère du § 4.2 | routine | tableau de couverture : chaque issue du lot → tâche → branche prévue, ou hors plan / doublon, avec la raison | un critère du § 4.2 → ligne « issue sensible » | toutes les issues du lot couvertes |
| architect | Point d'étape après fusion | lot ≥ 8 issues, ou plusieurs branches touchées (**À ADAPTER**) | routine ; jugement si l'un des signaux | SHA cités, dépendances ajoutées / retirées explicites, décisions M-n | seuil « macro » (§ 4.3) atteint → Fable **proposé** au mainteneur | feuille de route à jour |
| architect | Plan de la branche suivante | — | jugement | trois à cinq issues, ordre des commits, agent et circuit par tâche, critères d'acceptation | § 4.1 | plan complet |
| architect | Issue sensible : ADR, invariant de `CLAUDE.md` ou contrat partagé touché | § 4.2 | jugement | ADR et invariants cités, effet sur les contrats, branches touchées | § 4.1 ; sinon Fable **proposé** | avis rendu, ou décision du mainteneur |
| architect | Rédaction d'un ADR **d'architecture** (couches, invariants, contrats) | — | **Fable** (routage initial) | contexte, options écartées, conséquences | décision du mainteneur | ADR proposé |
| architect | Rédaction d'un ADR d'organisation (Git, processus, outillage) | — | jugement | idem | idem | idem |
| expert | Validation après audit, sans changement de résultat | — | routine | diff, rapport d'audit, verdict référencé | relance ciblée si une preuve manque | verdict |
| expert | Validation avec tableau avant / après (hors résultat final ou verdict) ; conformité à une source ; spécification ou plan | — | jugement | citation précise (texte, article, paragraphe) ou mesure exécutée ; chaque conclusion marquée vérifiée / hypothèse / non vérifiée | § 4.1 ; deux lectures → § 4.4 | verdict, matrice ou plan complet |
| expert | Nouvelle approche, méthode nouvelle | au moins deux options sans preuve qui départage | jugement | options, apport de chacune, références retrouvées | **arbitrage du mainteneur** ; Fable seulement à sa demande ou par § 4.1 | options décrites |
| tous | Changement d'un résultat final ou d'un verdict | tableau avant / après | jugement | tableau avant / après, lignes expliquées | Fable **seulement sur décision du mainteneur** | visa du mainteneur |

Mission absente de la matrice (par exemple révision globale, relecture d'une PR, revue de fond avant livraison) : jugement par défaut ; la session principale propose de l'ajouter à la matrice au point d'étape suivant.

## 4. Critères

### 4.1 Fable sans demander au mainteneur (liste fermée)

1. **Échec documenté d'Opus `high`** : après la consultation en jugement (et, s'il y a lieu, la relance ciblée), la preuve attendue manque encore **et** le blocage est de raisonnement — ni une information manquante, ni une exploration interrompue (§ 5.1).
2. **Désaccord entre agents** : expert contre `audit`, deux experts entre eux, ou un avis rendu par un agent qui contredit un ADR accepté alors que la question ne porte pas sur cet ADR (une issue ou une consultation qui propose de le modifier est une issue sensible, § 4.2 : Opus `high` d'abord, ADR 0001, décision 3). Fable **instruit** le désaccord, par une consultation neuve de la fiche `-approfondi` du rôle dont relève la question (le fond à `expert`, la forme du code et les ADR à `architect`), avec le dossier (§ 5.4) ; la décision reste au mainteneur quand `CLAUDE.md` la lui réserve.
3. **Rédaction d'un ADR d'architecture** (routage initial, § 3).

Tout autre usage de Fable est **proposé** au mainteneur (un message, réponse oui / non), qui peut aussi le demander d'office.

### 4.2 Issue sensible (revue plus forte, même pour une seule issue)

- un ADR accepté ou un invariant de `CLAUDE.md`, « Architecture », est contredit ou modifié ;
- un **contrat partagé** change : interface entre modules ou couches, format de données ou d'état, catalogue ou table utilisés par plusieurs branches (**À ADAPTER** : liste des contrats du projet) ;
- un résultat final ou un verdict change (Fable sur décision du mainteneur seulement).

Le nombre d'issues d'un lot n'est qu'un complément : un gros lot fait passer en jugement, il ne déclenche jamais Fable à lui seul ; une issue unique à fort impact est sensible quel que soit le lot.

### 4.3 Seuil « macro » du point d'étape (Fable proposé au mainteneur)

Un nouvel ADR d'architecture, ou le remplacement d'un ADR, est proposé ; **ou**, selon leur importance, au-dessus des seuils suivants (**À ADAPTER**) :
- au moins deux couches ou modules dont les dépendances changent ;
- au moins deux branches suivantes redécoupées ou réordonnées ;
- un jalon dont le contenu change.

Sous le seuil : jugement, sans question au mainteneur.

### 4.4 Ni Fable ni effort : obtenir une information ou une preuve

- **Deux lectures d'une source** : vérifier d'abord qu'il ne s'agit pas d'un problème de documentation (version erronée, texte inaccessible, extraction défectueuse) ; si oui, obtenir la bonne source. Si les deux lectures subsistent, l'expert les décrit et le mainteneur tranche (`CLAUDE.md`) : Fable n'est pas requis.
- **Issue insuffisamment décrite** : question au mainteneur (libellé `needs-info`), pas d'escalade.
- **Source non retrouvée** par l'agent : décision du mainteneur, même si l'agent se dit sûr.
- **Question qu'aucun test ni aucune source ne tranche** : d'abord chercher la mesure ou la source ; si le blocage est de raisonnement, Fable est **proposé**.

## 5. Transitions, plafonds et arrêts

### 5.1 Cinq actions, choisies selon la nature du blocage

| Blocage constaté dans le retour | Action | Forme |
|---|---|---|
| statut `complet` sans les preuves prévues, retour marqué partiel par Claude Code (plafond de tours `maxTurns` atteint), ou retour sans bloc « Retour » | **relance ciblée** | reprise du même agent (`SendMessage`), contexte conservé, même fiche ; statut requalifié `partiel` |
| exploration incomplète (lectures non faites, périmètre non couvert) ou blocage de raisonnement, en routine | **hausse d'effort** | consultation neuve de la fiche `-approfondi`, avec le dossier (§ 5.4) |
| exploration incomplète en jugement | **relance ciblée** | reprise du même agent (`SendMessage`), même fiche ; ensuite arrêt (§ 5.2) |
| blocage de raisonnement en jugement, ou critère du § 4.1 | **changement de modèle** | consultation neuve de la fiche `-approfondi` avec `model: "fable"`, avec le dossier |
| information, source ou mesure manquante | **obtenir l'information ou la preuve** | lancer la mesure, retrouver la source, ou demander au mainteneur |
| décision réservée (visa, deux lectures, approche, source non retrouvée, Fable proposé) | **décision humaine** | question au mainteneur, avec les rapports |

Ordre selon la nature du blocage : information → preuve ; exploration → effort ; raisonnement → effort en routine, puis modèle en jugement. Pas de palier Opus `high` imposé avant Fable quand un critère du § 4.1 est présent d'emblée : § 4.1.3 (ADR d'architecture) dès le départ, § 4.1.2 (désaccord) dès qu'il est constaté, même entre consultations de routine.

### 5.2 Plafonds

- **Par question** : au plus une relance ciblée, une hausse d'effort et une consultation Fable ; ensuite arrêt et compte rendu au mainteneur, statut `revue requise` ; l'accord du mainteneur lève le plafond (§ 5.5).
- **Par branche de travail** : au-delà de **3 consultations Fable** (ADR compris), accord du mainteneur avant chaque nouvelle consultation.
- **Par consultation** : `maxTurns` de la fiche (40 ou 80). Ce plafond borne les tours, **pas les tokens** ; une réponse courte ne borne pas le raisonnement.

### 5.3 Modèle indisponible, plafond atteint

Arrêt et question au mainteneur : attendre, ou accepter une consultation Opus `high` dont l'avis porte la mention « rendu sans Fable, à revoir ». Jamais de remplacement silencieux : la session principale compare le modèle servi, relevé par le journal (§ 7), au modèle demandé, qu'elle note dans la ligne d'escalade de la PR (le journal ne voit pas le `model` passé à l'appel).

### 5.4 Dossier d'escalade

Une consultation neuve (hausse d'effort ou changement de modèle) reçoit un dossier court, et non une nouvelle revue globale :

```
Question résiduelle :
Contraintes (ADR, invariants, décisions M-n) :
Conclusions établies (avec leurs preuves) :
Sources et fichiers utiles (chemins, articles) :
Tentatives et résultats (fiche, modèle, statut, ce qui a manqué) :
Contradictions :
Preuve attendue pour conclure :
```

### 5.5 Priorité entre règles

1. `CLAUDE.md` (visa, décisions réservées au mainteneur, deux lectures d'une source) ;
2. indisponibilité d'un modèle ou plafond atteint (§ 5.2, § 5.3) : arrêt et question au mainteneur ; son accord lève le plafond ;
3. décisions explicites du mainteneur ;
4. critères du § 4.1 ;
5. jugement de la session principale, appuyé sur les signaux du § 3.

Un signal auto-déclaré (difficulté ressentie, note de confiance) complète l'analyse sans la remplacer.

## 6. Retour structuré des agents

Chaque consultation se termine par un bloc « Retour » (fiches `architect` et `expert`, section « Retour ») : statut (`complet`, `partiel`, `revue requise`), résultat, preuves (chaque conclusion vérifiée / hypothèse / non vérifiée), informations manquantes, décisions non résolues, critères déclenchés (§ 4), prochaine action recommandée. `architect` y ajoute le tableau de couverture du lot et les dépendances modifiées. `complet` exige toutes les preuves prévues au § 3 ; sinon la session principale requalifie en `partiel` (§ 5.1).

## 7. Traçabilité

- **Journal local** : le hook `SubagentStop` (`.claude/hooks/journal_agents.sh`) ajoute une ligne JSON par sous-agent terminé (toutes fiches, pas seulement les consultations) à `.claude/journal-agents.jsonl` (non versionné) : date, agent, identifiant, modèles servis, nombre d'appels au modèle, contexte au dernier appel (tokens d'entrée, cache compris), durée. Il ne mesure ni l'effort (non exposé) ni les tokens de sortie (non fiables dans le transcript). Le transcript est écrit de façon asynchrone et peut ne pas contenir les derniers messages quand le hook s'exécute : appels et contexte au dernier appel sont des minorants possibles. En session cloud, il disparaît avec le conteneur : avant la fin d'une telle session, la session principale colle la sortie de `bash .claude/outils/bilan_journal.sh` dans un commentaire de la PR de la branche de travail.
- **Bilan** : `bash .claude/outils/bilan_journal.sh` agrège le journal par agent et par modèle. Une reprise (`SendMessage`) ajoute pour le même sous-agent une ligne cumulative (appels, durée attente comprise) : le bilan ne garde que la dernière et compte les reprises.
- **Trace durable** : chaque escalade (hausse d'effort, Fable), relance ciblée ou arrêt est noté par la session principale dans la PR de la branche de travail, une ligne : `fiche / modèle / critère déclenché / statut obtenu / suite`. Hors de toute branche ouverte (point d'étape entre deux branches, par exemple), la ligne va dans la section « Escalades, relances et arrêts hors branche » de `docs/feuille-de-route.md`, et une consultation Fable faite hors branche compte pour la branche suivante (§ 5.2).
- `/usage` (abonnement) attribue approximativement l'usage récent aux sous-agents (24 h ou 7 jours, poste courant seulement) ; l'export OpenTelemetry est l'autre source, que le modèle ne configure pas.

## 8. Calibration et retour arrière

- **Calibration** : après les dix premières consultations `architect` et `expert` d'un projet, puis à chaque point d'étape d'`architect`, relire le bilan du journal et les lignes d'escalade des PR : part des relances ciblées (fiches trop légères ?), escalades vers Fable et leur apport réel, contexte au dernier appel (lectures trop larges ?). Ajuster les seuils et efforts par un commit `claude:` motivé ; une réorientation durable s'annote dans l'ADR 0001.
- **Retour au comportement antérieur** (Fable pour tout), sur décision du mainteneur : de préférence, annuler le commit de fusion de la PR qui a introduit la politique (`git revert -m 1 <sha>`), puis rétablir l'ADR 0001 (que l'annulation supprime) avec une annotation datée « Politique abandonnée le … » (ou `superseded by NNNN` si un nouvel ADR consigne le retour) ; dans un projet créé depuis le modèle, qui n'a pas ce commit, ou à défaut, à la main : remettre `model: fable` dans `architect.md` et `expert.md`, retirer `effort` et `maxTurns`, vider `ROLES` dans `.claude/outils/fiches_jumelles.sh`, supprimer les fiches `-approfondi`, retirer de `CLAUDE.md` le paragraphe « Routage du modèle et de l'effort », et annoter l'ADR 0001.

## 9. Adapter la politique à un projet

Emplacements réellement lus :

| Emplacement | Ce qu'on y adapte |
|---|---|
| `docs/agents/routage.md` (ce fichier) | matrice (§ 3), seuils et contrats partagés (§ 4.2, § 4.3), plafonds (§ 5.2) |
| frontmatter de `architect.md` et `expert.md` | effort et `maxTurns` de routine ; le script reprend leur modèle, leurs outils et leur corps dans les fiches `-approfondi` |
| `.claude/outils/fiches_jumelles.sh`, variables `ROLES`, `EFFORT_APPROFONDI`, `TOURS_APPROFONDI` | rôles dédoublés (experts supplémentaires), effort et plafond de jugement |
| `CLAUDE.md`, « Sous-agents » | renvoi à ce fichier ; règles qui priment (§ 5.5, rang 1) ; liste du § 4.1 et plafonds du § 5.2, recopiés : à tenir identiques |

Ces critères s'articulent avec `CLAUDE.md` sans le remplacer : les décisions qu'il réserve au mainteneur restent les siennes quel que soit le modèle. Vérification : `bash .claude/outils/fiches_jumelles.sh --verifier` (CI), puis, dans une session neuve, une consultation de chaque fiche suivie de `bash .claude/outils/bilan_journal.sh` pour lire le modèle servi.

Exemple d'adaptation (projet de calcul réglementaire) : contrats partagés = table des paramètres réglementaires et format d'entrée ; seuil « macro » = une couche de calcul touchée suffit ; un deuxième expert `regulatory` ajouté à `ROLES` ; validation après audit en jugement, parce qu'un écart de conformité y coûte plus qu'une consultation Opus `high`.
