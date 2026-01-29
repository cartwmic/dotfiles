#!/bin/bash

# Check if op is available
if ! command -v op >/dev/null 2>&1; then
  echo "[update_claude_settings] ERROR: 1Password CLI (op) is required but not installed"
  exit 1
fi

# Get auth token from 1Password
echo "[update_claude_settings] INFO: Retrieving ANTHROPIC_AUTH_TOKEN from 1Password..."
ANTHROPIC_AUTH_TOKEN=$(op read 'op://personal/z.ai - key 1/credential' --no-newline 2>&1)
if [ $? -ne 0 ]; then
  echo "[update_claude_settings] ERROR: Failed to retrieve auth token from 1Password: $ANTHROPIC_AUTH_TOKEN"
  exit 1
fi

echo "$ANTHROPIC_AUTH_TOKEN"
