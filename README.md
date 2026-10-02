# Modele_vibe_code — modèle d'organisation Claude Code

Modèle de dépôt pour mener un projet avec Claude Code : sous-agents spécialisés, circuits de travail, règles Git et GitHub, traçabilité des changements de résultats. Il ne contient aucun code métier ; chaque projet part de ce modèle et remplit les passages marqués **À ADAPTER**.

Travail en cours.

## Contenu

| Chemin | Rôle |
|---|---|
| `CLAUDE.md` | Règles lues par Claude Code à chaque session : Git et GitHub, architecture, changements de résultats, rigueur, sous-agents, circuits, workflows |
| `.claude/agents/` | Six sous-agents : `architect` (pilotage), `expert` (fond, à spécialiser), `coder`, `docwriter` (réalisation), `audit`, `app-review` (vérification) |
| `.claude/agents/*-approfondi.md` | Variantes de jugement d'`architect` et d'`expert` (effort `high`), générées par `.claude/outils/fiches_jumelles.sh` |
| `docs/agents/routage.md` | Politique de routage du modèle et de l'effort d'`architect` et d'`expert` (ADR 0001) |
| `.claude/hooks/journal_agents.sh`, `.claude/outils/bilan_journal.sh` | Journal local des sous-agents terminés (hook `SubagentStop`) et son bilan |
| `.claude/workflows/circuit-technique.js` | Circuit `coder` → batteries → `audit` léger, une reprise au plus, sans commit ni push |
| `.claude/settings.json`, `.claude/hooks/` | Permissions, hooks (installation des plugins `mattpocock-skills` et `document-skills`, journal des sous-agents) |
| `CONTEXT.md` | Glossaire du domaine et de l'organisation |
| `docs/exigences.md` | Gabarit du cahier des charges |
| `docs/feuille-de-route.md` | Gabarit de la feuille de route tenue par `architect` |
| `docs/adr/` | Décisions consignées (gabarit `0000-gabarit.md`) |
| `docs/agents/` | Suivi des issues (GitHub, `gh` ou MCP), libellés de tri, documentation du domaine |
| `.github/` | Modèles d'issue et de PR, CI minimale, Dependabot |

## Démarrer un projet à partir du modèle

1. Créer le dépôt avec « Use this template » sur `Gerard-Garey/Modele_vibe_code`, puis appliquer « Sécurité du dépôt » ci-dessous : ni les réglages, ni le ruleset, ni les libellés ne sont copiés par le modèle.
2. Remplir chaque passage **À ADAPTER** : `grep -rn "À ADAPTER\|A ADAPTER" .`
   - `CLAUDE.md` : contexte, dépôt de référence, batteries de vérification, domaines de commit, architecture, exigences de rigueur ;
   - `.claude/agents/expert.md` : spécialité et sources qui font foi (dupliquer la fiche si le projet a besoin de deux experts, par ex. méthode et réglementation) ;
   - `.claude/workflows/circuit-technique.js` : `BATTERIES` et `ZONES_PROTEGEES` ;
   - `docs/exigences.md`, `CONTEXT.md` ;
   - `.github/workflows/ci.yml` : jobs de tests, à ajouter aux contrôles requis du ruleset.
3. Adapter les critères de routage du modèle et de l'effort (ci-dessous, « Routage du modèle et de l'effort »).
4. Retirer les agents inutiles (par ex. `app-review` sans interface) et leurs mentions dans `CLAUDE.md`.
5. Créer les libellés d'issues (« Use this template » ne les copie pas) : `bash .github/creer_labels.sh OWNER/REPO` — libellés de tri de `docs/agents/triage-labels.md`, plus `bug`, `enhancement` et `documentation`.
6. Premier travail : demander à `architect` le plan de la première branche de travail.

## Façon de travailler

- **Une branche de travail à la fois**, au périmètre fermé d'issues, PR brouillon dès la création ; fusion par le mainteneur, par commit de fusion, CI verte.
- **Ceux qui écrivent ne vérifient pas, ceux qui vérifient n'écrivent pas** ; un agent n'entre dans le circuit que si la modification touche son domaine.
- **Toute affirmation sur le code s'adosse à une mesure** exécutée ; tout changement de résultat a son tableau avant / après et son visa.
- **Audit léger en cours, revue finale complète avant la sortie du brouillon** ; documentation écrite une seule fois, en fin de branche.
- **Les issues ne sont créées qu'avec l'accord du mainteneur** ; les workflows ne commitent, ne poussent et ne créent rien.

Détail : `CLAUDE.md`.

## Routage du modèle et de l'effort

`architect` et `expert` tournent sur Opus par défaut : effort `medium` pour la routine et `high` pour le jugement, Fable réservé à une liste fermée de cas ou à l'accord du mainteneur, avec des plafonds d'escalade (`docs/agents/routage.md`, ADR 0001).

**Cette politique est un point de départ.** Chaque projet créé à partir du modèle peut, et doit, définir ses propres critères d'escalade du modèle et de l'effort selon son domaine, son architecture, ses risques et ses contraintes, puis les réévaluer à mesure qu'il évolue (après les premières consultations réelles, puis à chaque point d'étape d'`architect`).

- **Où** : les critères (matrice, contrats partagés, seuil « macro », plafonds) dans `docs/agents/routage.md` ; l'effort et le plafond de tours de routine dans le frontmatter d'`architect.md` et d'`expert.md` ; les rôles dédoublés, l'effort et le plafond de jugement dans les variables `ROLES`, `EFFORT_APPROFONDI` et `TOURS_APPROFONDI` de `.claude/outils/fiches_jumelles.sh`, puis `bash .claude/outils/fiches_jumelles.sh` pour régénérer les fiches `-approfondi`.
- **Articulation** : les règles de `CLAUDE.md` priment (visa, décisions réservées au mainteneur, deux lectures d'une source) ; la politique ne fait que choisir la fiche et le modèle d'une consultation.
- **Vérification** : `bash .claude/outils/fiches_jumelles.sh --verifier` (aussi en CI) ; puis, dans une **session neuve** (les fiches ne sont pas rechargées en cours de session), une consultation de chaque fiche et `bash .claude/outils/bilan_journal.sh`, qui affiche le modèle réellement servi ; les escalades, relances ciblées et arrêts sont notés dans la PR (section « Escalades, relances et arrêts »).
- **Exemple** : un projet de calcul réglementaire déclare comme contrats partagés sa table de paramètres et son format d'entrée, abaisse le seuil « macro » à une seule couche de calcul touchée, ajoute un expert `regulatory` à `ROLES`, et passe la validation après audit en jugement.
- **Limites** : un plafond de tours n'est pas un plafond de tokens, une réponse courte ne borne pas le raisonnement, l'effort effectif n'est pas observable dans le journal, et la politique ne supprime pas les angles morts des modèles.

## Sécurité du dépôt

Réglages appliqués au modèle, à reproduire sur tout dépôt créé depuis lui (`OWNER/REPO` à remplacer) ; indispensables si le dépôt est public :

- fusion par **commit de fusion seulement** (squash et rebase désactivés), wiki désactivé ;
- **secret scanning** et **push protection** activés ; **alertes et correctifs de sécurité Dependabot** activés ;
- Actions limitées à celles de GitHub (`github_owned_allowed`), jeton des workflows en lecture seule, actions épinglées par SHA ;
- ruleset **« Protection main »** : suppression et force-push interdits, PR obligatoire (fusion par commit de fusion, fils de discussion résolus), contrôle requis « Contrôles du dépôt » à jour avec `main`, sans contournement.

```bash
R=OWNER/REPO
gh api -X PATCH repos/$R -F allow_squash_merge=false -F allow_rebase_merge=false -F allow_merge_commit=true -F has_wiki=false \
  -f 'security_and_analysis[secret_scanning][status]=enabled' -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
gh api -X PUT repos/$R/vulnerability-alerts
gh api -X PUT repos/$R/automated-security-fixes
gh api -X PUT repos/$R/actions/permissions -F enabled=true -f allowed_actions=selected
gh api -X PUT repos/$R/actions/permissions/selected-actions -F github_owned_allowed=true -F verified_allowed=false
gh api -X PUT repos/$R/actions/permissions/workflow -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false
gh api -X POST repos/$R/rulesets --input .github/ruleset-main.json
```

Le ruleset est dans `.github/ruleset-main.json`. L'appliquer **après** le premier push sur `main`, qu'il bloque ensuite.
