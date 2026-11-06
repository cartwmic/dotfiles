#!/bin/sh
# Create the AGENT_TMP directory and the cache directory (npm, and uv later) on the Workshop SSD (dot_config/agent-scratch/workshop.env). Personal Mac only (.chezmoiignore).
# Reproduce: chezmoi apply (runs when this file changes), or by hand: mkdir -p /Volumes/Workshop/macbook/tmp-home /Volumes/Workshop/macbook/cache
# Undo:      rmdir those two (only while empty; this script never removes anything).
# Moves nothing: the ~/tmp move is a separate, dry-run-by-default script (~/.local/user_scripts/agent_tmp_move.py).
# When the volume is not mounted it says so and fails (exit 1). It never creates a directory anywhere else.
set -eu
log() { printf '[agent_scratch_workshop] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)" = Darwin ] || exit 0
root=${AGENT_WORKSHOP_ROOT:-/Volumes/Workshop}
if [ ! -d "$root/macbook" ]; then
  log ERROR "$root/macbook is not there (is Workshop mounted?); not creating anything"
  exit 1
fi
mkdir -p "$root/macbook/tmp-home" "$root/macbook/cache"
log INFO "$root/macbook/tmp-home and $root/macbook/cache are ready"
