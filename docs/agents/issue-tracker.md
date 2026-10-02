# Suivi des issues : GitHub

Les issues et les specs de ce dépôt sont des issues GitHub de `<propriétaire>/<dépôt>` (**À ADAPTER**). **La voie d'accès dépend de l'environnement**, et les deux coexistent : la CLI `gh` sur le poste local, les outils `mcp__github__*` en session cloud.

| | Poste local | Session cloud |
|---|---|---|
| `gh` | installé (`winget install GitHub.cli`) et authentifié (`gh auth login`) | **absent** |
| outils `mcp__github__*` | disponibles | disponibles |
| `GH_TOKEN` / `GITHUB_TOKEN` | — | présents dans l'environnement |

Les six agents de `.claude/agents/` déclarent leurs outils GitHub dans leur frontmatter, selon deux profils : `coder`, `audit`, `docwriter` et `app-review` en lecture seule (`mcp__github__issue_read`, `mcp__github__list_issues`), `architect` et `expert` y ajoutant l'écriture d'issues (`mcp__github__issue_write`, `mcp__github__add_issue_comment`). Aucun ne reçoit d'outil GitHub touchant aux fichiers du dépôt, ce qui préserve la règle « ceux qui vérifient n'écrivent pas ».

## Conventions

Chaque opération, dans les deux voies :

| Opération | Outil MCP | Équivalent `gh` |
|---|---|---|
| Créer une issue | `mcp__github__issue_write`, `method: "create"` (champs `title`, `body`, `labels`) | `gh issue create --title "..." --body "..."` |
| Lire une issue | `mcp__github__issue_read`, `method: "get"` (puis `get_comments`, `get_labels`) | `gh issue view <n> --comments` |
| Lister les issues | `mcp__github__list_issues` (filtres `state`, `labels`) | `gh issue list --state open --json number,title,body,labels` |
| Commenter | `mcp__github__add_issue_comment` | `gh issue comment <n> --body "..."` |
| Libellés | `mcp__github__issue_write`, `method: "update"`, champ `labels` | `gh issue edit <n> --add-label` / `--remove-label` |
| Fermer | `mcp__github__issue_write`, `method: "update"`, `state: "closed"` et `state_reason` | `gh issue close <n> --comment "..."` |

`owner` et `repo` sont ceux du dépôt (**À ADAPTER**). Avec `gh`, le dépôt se déduit de `git remote -v`, automatiquement dans un clone.

Les outils `mcp__github__*` peuvent être différés : s'ils ne figurent pas dans la liste d'outils, les charger avec `ToolSearch` (`select:mcp__github__issue_read`, par exemple). Les sous-agents, eux, n'ont ni `ToolSearch` ni d'autre moyen d'en charger : ils ne disposent que des outils de leur frontmatter.

### Repli : l'API REST

Si aucun outil MCP n'est disponible et que `gh` est absent, `Bash` suffit, `GH_TOKEN` étant présent en session cloud :

```bash
curl -sS -H "Authorization: Bearer $GH_TOKEN" \
     -H "Accept: application/vnd.github+json" \
     -H "X-GitHub-Api-Version: 2022-11-28" \
     https://api.github.com/repos/<propriétaire>/<dépôt>/issues/1
```

C'est un repli, pas la voie normale : il contourne la granularité des profils ci-dessus, et tout agent disposant de `Bash` peut ainsi écrire sur GitHub quels que soient les outils de son frontmatter. Ne l'employer que si les deux autres voies manquent, et le signaler dans le compte rendu.

## Constats établis (22 septembre 2026)

Trois points vérifiés en session cloud, consignés pour qu'ils ne soient pas retestés à l'aveugle :

1. **Le champ `tools:` d'un sous-agent accepte les noms MCP**, sous les trois formes : outil nommé (`mcp__github__issue_read`), serveur entier (`mcp__github`) et joker (`mcp__github__*`). Test : trois agents privés de `Bash`, portant chacun une forme, ont tous rendu les métadonnées exactes de l'issue #1, absentes du dépôt.
2. **Seule la forme nommée restreint réellement.** `mcp__github` et `mcp__github__*` donnent la même liste de 56 outils, écriture comprise (`push_files`, `create_or_update_file`, `delete_file`, `merge_pull_request`). D'où le choix des noms explicites dans les frontmatters.
3. **Les fiches de `.claude/agents/` ne sont pas rechargées en cours de session** : la définition utilisée est celle lue au démarrage. Une modification de frontmatter ne se teste donc que dans une session neuve, démarrée sur une branche qui la porte déjà. La documentation officielle annonce un rechargement à chaud : c'est faux dans cet environnement.



## Pull requests comme surface de tri

**PR comme surface de demande : non.** _(Passer à `oui` si ce dépôt traite les PR externes comme des demandes de fonctionnalité ; `/triage` lit ce paramètre.)_

Lorsqu'il vaut `oui`, les PR suivent les mêmes libellés et états que les issues. En session cloud, les outils correspondants sont `mcp__github__pull_request_read` et `mcp__github__list_pull_requests` ; sur le poste local, les équivalents `gh pr` :

- **Lire une PR** : `gh pr view <numéro> --comments`, et `gh pr diff <numéro>` pour le diff.
- **Lister les PR externes à trier** : `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`, puis ne garder que les `authorAssociation` valant `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR` ou `NONE` (écarter `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Commenter / étiqueter / fermer** : `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub partage une seule numérotation entre issues et PR : un `#42` isolé peut désigner l'une ou l'autre. Résoudre avec `mcp__github__pull_request_read` puis à défaut `mcp__github__issue_read` (ou `gh pr view 42`, puis `gh issue view 42`).

## Quand un skill demande de « publier dans le suivi des issues »

Créer une issue GitHub.

## Quand un skill demande de « récupérer le ticket concerné »

Lire l'issue : `mcp__github__issue_read` (`method: "get"`, puis `get_comments`), ou `gh issue view <numéro> --comments` en local.

## Opérations de wayfinding

Utilisées par `/wayfinder`. La **carte** est une issue unique, dont les tickets sont des issues **enfants**.

- **Carte** : une issue unique portant le libellé `wayfinder:map`, dont le corps contient les sections Notes / Décisions à ce jour / Zones floues. `gh issue create --label wayfinder:map`.
- **Ticket enfant** : une issue rattachée à la carte comme sous-issue GitHub (`mcp__github__issue_write` avec `parent_issue_number`, ou `mcp__github__sub_issue_write` ; `gh api` sur l'endpoint des sous-issues en local). Si les sous-issues ne sont pas activées, ajouter l'enfant à une liste de tâches dans le corps de la carte et placer `Part of #<carte>` en tête du corps de l'enfant. Libellés : `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Une fois pris, le ticket est assigné au développeur qui le pilote.
- **Blocage** : les **dépendances natives d'issues** de GitHub, représentation canonique et visible dans l'interface. Ajouter une dépendance avec `gh api --method POST repos/<owner>/<repo>/issues/<enfant>/dependencies/blocked_by -F issue_id=<id-bdd-bloquant>`, où `<id-bdd-bloquant>` est l'**identifiant de base de données** numérique de l'issue bloquante (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, et _non_ le `#numéro` ni le `node_id`). GitHub expose `issue_dependencies_summary.blocked_by` (bloquants ouverts uniquement, le verrou effectif). Si les dépendances ne sont pas disponibles, se rabattre sur une ligne `Blocked by: #<n>, #<n>` en tête du corps de l'enfant. Un ticket est débloqué lorsque tous ses bloquants sont fermés.
- **Requête de frontière** : lister les enfants ouverts de la carte (`gh issue list --state open`, restreint aux sous-issues ou à la liste de tâches de la carte), écarter ceux qui ont un bloquant ouvert (`issue_dependencies_summary.blocked_by > 0`, ou une issue ouverte dans la ligne `Blocked by`) ou un assigné ; le premier dans l'ordre de la carte l'emporte.
- **Prise en charge** : `mcp__github__issue_write` (`method: "update"`, champ `assignees`), ou `gh issue edit <n> --add-assignee @me` ; première écriture de la session.
- **Résolution** : `mcp__github__add_issue_comment`, puis `mcp__github__issue_write` (`method: "update"`, `state: "closed"`), puis ajouter un pointeur de contexte (résumé + lien) dans la section Décisions à ce jour de la carte.
