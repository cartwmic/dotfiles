#!/bin/sh
# Opt-in: builds the herdr-control Claude plugin zip. .mcp.json is generated here
# so the committed source holds no user-specific absolute path. Installs nothing;
# the owner uploads the zip in Claude Desktop (Customize > Plugins).
set -eu
umask 022
src=$(cd "$(dirname -- "$0")" && pwd -P)
wrapper="${HOME:?HOME is not set}/.local/share/herdr-mcp/herdr_control_mcp_child.sh"
out="${1:-$HOME/Downloads/herdr-control-plugin.zip}"
log() { printf '[build-claude-plugin] %s: %s\n' "$1" "$2"; }

[ -f "$wrapper" ] || { log ERROR "$wrapper missing; run install.sh first"; exit 1; }
case $wrapper in *'"'*|*'\'*) log ERROR "unsupported character in HOME"; exit 1 ;; esac
work=$(mktemp -d "${TMPDIR:-/tmp}/herdr-claude-plugin.XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/.claude-plugin"
cp "$src/claude-plugin/.claude-plugin/plugin.json" "$work/.claude-plugin/plugin.json"
printf '{\n  "mcpServers": {\n    "herdr": {\n      "command": "/bin/sh",\n      "args": ["%s"]\n    }\n  }\n}\n' "$wrapper" > "$work/.mcp.json"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate "$work" >/dev/null || { log ERROR "claude plugin validate failed"; exit 1; }
  log INFO "claude plugin validate passed"
else
  log WARN "claude CLI not found; skipped validation"
fi
mkdir -p "$(dirname -- "$out")"
rm -f "$out"
(cd "$work" && zip -q -X -r "$out" .claude-plugin .mcp.json)
log INFO "wrote $out"
