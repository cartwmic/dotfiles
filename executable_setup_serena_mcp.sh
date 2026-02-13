#!/bin/sh

# Script to add serena MCP server to ~/.claude.json if not already present

CLAUDE_JSON="$HOME/.claude.json"

# Check if claude.json exists
if [ ! -f "$CLAUDE_JSON" ]; then
  echo "[setup_serena_mcp] INFO: $CLAUDE_JSON not found, skipping serena MCP setup"
  exit 0
fi

# Check if jq is available
if ! command -v jq >/dev/null 2>&1; then
  echo "[setup_serena_mcp] ERROR: jq is required but not installed"
  exit 1
fi

# Check if serena is already configured
if jq -e '.mcpServers.serena' "$CLAUDE_JSON" >/dev/null 2>&1; then
  echo "[setup_serena_mcp] INFO: serena MCP server already configured"
  exit 0
fi

# Add serena MCP server configuration
jq '.mcpServers.serena = {
  "type": "stdio",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/oraios/serena",
    "serena",
    "start-mcp-server",
    "--context=claude-code",
    "--project-from-cwd"
  ],
  "env": {}
}' "$CLAUDE_JSON" >"$CLAUDE_JSON.tmp" && mv "$CLAUDE_JSON.tmp" "$CLAUDE_JSON"

if [ $? -eq 0 ]; then
  echo "[setup_serena_mcp] SUCCESS: Added serena MCP server to $CLAUDE_JSON"
else
  echo "[setup_serena_mcp] ERROR: Failed to update $CLAUDE_JSON"
  rm -f "$CLAUDE_JSON.tmp"
  exit 1
fi
