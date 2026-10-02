#!/usr/bin/env bash
###############################################################################
#  .claude/hooks/installer_plugins.sh  --  HOOK SessionStart DE CLAUDE CODE
#
#  Materialise les plugins declares dans enabledPlugins (.claude/settings.json).
#  La declaration est versionnee et suit donc le depot, mais les plugins eux-
#  memes vivent dans ~/.claude/plugins/, hors du depot : une session cloud
#  repart d'un conteneur neuf ou rien n'est installe, et les skills du plugin
#  sont alors absentes de la session.
#
#  Le hook n'installe que ce qui manque, et n'echoue jamais : une session sans
#  reseau ou sans CLI claude demarre normalement, sans ces skills.
#
#  ATTENTION : mattpocock-skills est du code tiers (github.com/mattpocock/
#  skills.git), epingle a un commit par le catalogue officiel. Il s'execute
#  dans les sessions de travail du projet. Retirer la ligne de PLUGINS
#  ci-dessous pour cesser de l'installer.
###############################################################################

PLUGINS="mattpocock-skills@claude-plugins-official"

CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
INSTALLES="$CONFIG/plugins/installed_plugins.json"

if ! command -v claude >/dev/null 2>&1; then
  echo "Plugins : CLI claude introuvable, installation ignoree." >&2
  exit 0
fi

poses=""
ignores=""

for plugin in $PLUGINS; do
  nom="${plugin%%@*}"

  # Deja materialise (poste local, ou session deja preparee) : rien a faire.
  # Le registre a pour cle le plugin@marketplace complet.
  if [ -f "$INSTALLES" ] && grep -q "\"$plugin\"" "$INSTALLES" 2>/dev/null; then
    continue
  fi

  echo "Installation du plugin $plugin..." >&2
  if timeout 180 claude plugin install "$plugin" >/dev/null 2>&1; then
    poses="$poses $nom"
  else
    ignores="$ignores $nom"
  fi
done

[ -n "$poses" ] && echo "Plugins installes pour cette session :$poses (leurs skills sont disponibles des la session suivante)."
[ -n "$ignores" ] && echo "ATTENTION : plugins non installes :$ignores. Leurs skills sont absentes de cette session."

exit 0
