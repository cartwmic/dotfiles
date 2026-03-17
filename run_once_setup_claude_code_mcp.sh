#!/bin/sh
# Chezmoi run_once script to set up Claude Code MCP servers
# This runs once when chezmoi init/apply is executed on a new machine

set -eu

SCRIPT="$HOME/.local/user_scripts/setup_claude_code_mcp_tools.sh"

if [ ! -x "$SCRIPT" ]; then
  echo "[setup_claude_code_mcp] INFO: MCP setup script not found at $SCRIPT, skipping"
  exit 0
fi

exec "$SCRIPT"
