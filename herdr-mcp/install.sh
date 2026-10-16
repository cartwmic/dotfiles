#!/bin/sh
# Opt-in installer: copies the Herdr control MCP bridge, child wrapper and
# herdr-mcp-tunnel into ~/.local/share/herdr-mcp and links
# ~/.local/bin/herdr-mcp-tunnel. Idempotent. Installs no tunnel-client,
# credential, or LaunchAgent; those are separate explicit commands.
set -eu
umask 022
src=$(cd "$(dirname -- "$0")" && pwd -P)
dest="${HOME:?HOME is not set}/.local/share/herdr-mcp"
link="$HOME/.local/bin/herdr-mcp-tunnel"
log() { printf '[herdr-mcp-install] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)-$(uname -m)" = Darwin-arm64 ] || { log ERROR "macOS arm64 only"; exit 1; }
if [ -e "$link" ] || [ -L "$link" ]; then
  [ -L "$link" ] && [ "$(readlink "$link")" = "$dest/herdr-mcp-tunnel" ] ||
    { log ERROR "$link exists and is not our symlink; refusing"; exit 1; }
fi
mkdir -p "$dest" "$HOME/.local/bin"
for f in herdr_control_mcp.py:0644 herdr_control_mcp_child.sh:0755 herdr-mcp-tunnel:0755 README.md:0644; do
  name=${f%%:*} mode=${f##*:}
  if cmp -s "$src/$name" "$dest/$name"; then continue; fi
  tmp=$(mktemp "$dest/.$name.XXXXXX")
  trap 'rm -f "$tmp"' EXIT
  if ! { cp "$src/$name" "$tmp" && chmod "$mode" "$tmp" && mv "$tmp" "$dest/$name"; }; then
    rm -f "$tmp"; log ERROR "could not install $dest/$name"; exit 1
  fi
  trap - EXIT
  log INFO "installed $dest/$name"
done
[ -L "$link" ] || { ln -s "$dest/herdr-mcp-tunnel" "$link"; log INFO "linked $link"; }
log INFO "files current in $dest"
if [ -f "$HOME/Library/LaunchAgents/local.herdr-mcp-tunnel.plist" ]; then
  log INFO "a LaunchAgent is installed; restart it to use updated files: herdr-mcp-tunnel agent uninstall && herdr-mcp-tunnel agent install"
fi
