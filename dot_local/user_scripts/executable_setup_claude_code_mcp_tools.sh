#!/bin/sh

set -eu

SCRIPT="$HOME/.local/user_scripts/apply_harness_config.sh"

if [ ! -x "$SCRIPT" ]; then
  echo "[setup_claude_code_mcp_tools] ERROR: Harness config adapter not found at $SCRIPT" >&2
  exit 1
fi

"$SCRIPT" claude
