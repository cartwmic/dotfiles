#!/bin/sh

# Script to install MCP tools for Claude Code
# - Uses `claude mcp add` to register MCP servers
# - Supports fetching API keys from 1Password CLI
# - Idempotent: ignores "already exists" errors

log() {
  echo "[setup_claude_code_mcp_tools] $1"
}

log_error() {
  echo "[setup_claude_code_mcp_tools] ERROR: $1" >&2
}

log_info() {
  echo "[setup_claude_code_mcp_tools] INFO: $1"
}

# Check for claude CLI
if ! command -v claude >/dev/null 2>&1; then
  log_error "claude CLI is required but not installed"
  exit 1
fi

# Helper to get secret from 1Password
# Usage: get_op_secret "op://vault/item/field"
get_op_secret() {
  if ! command -v op >/dev/null 2>&1; then
    log_error "1Password CLI (op) is required but not installed"
    return 1
  fi
  op read "$1" --no-newline
}

# Helper to add an MCP server, ignoring "already exists" errors
# Usage: add_mcp_server "server-name" "full command as string"
add_mcp_server() {
  server_name="$1"
  shift
  log_info "Adding MCP server: $server_name"
  output=$("$@" 2>&1)
  status=$?
  if [ $status -eq 0 ]; then
    log_info "Added: $server_name"
  elif echo "$output" | grep -q "already exists\|already added"; then
    log_info "Already exists: $server_name"
  else
    log_error "Failed to add $server_name: $output"
  fi
}

log_info "Installing MCP servers..."

# ============================================================================
# MCP SERVERS CONFIGURATION
# Add new servers below using add_mcp_server "name" command args...
# ============================================================================

# Context7 - requires API key from 1Password
CONTEXT7_API_KEY=$(get_op_secret "op://personal/context7 - api key/credential")
if [ -n "$CONTEXT7_API_KEY" ]; then
  add_mcp_server "context7" claude mcp add --transport http context7 https://mcp.context7.com/mcp \
    --header "CONTEXT7_API_KEY: $CONTEXT7_API_KEY"
else
  log_info "Skipping context7: API key not available"
fi

# ============================================================================
# END MCP SERVERS CONFIGURATION
# ============================================================================

log_info "MCP tools setup complete"
