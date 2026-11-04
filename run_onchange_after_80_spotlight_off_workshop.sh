#!/bin/sh
# Turn Spotlight indexing off for /Volumes/Workshop (agent worktrees; nobody searches them with Spotlight). Personal Mac only (.chezmoiignore).
# Reproduce: chezmoi apply (runs when this file changes), or by hand: mdutil -i off /Volumes/Workshop
# Undo:      mdutil -i on /Volumes/Workshop (this script does not turn it off again unless its text changes).
# Does nothing when the volume is not mounted or indexing is already off. Only that volume is touched.
set -eu
log() { printf '[spotlight_off_workshop] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)" = Darwin ] || exit 0
volume=${SPOTLIGHT_WORKSHOP_VOLUME:-/Volumes/Workshop}
if [ ! -d "$volume" ]; then
  log INFO "$volume is not mounted; nothing to do"
  exit 0
fi
enabled() { mdutil -s "$volume" 2>&1 | grep -q 'Indexing enabled'; }
if ! enabled; then
  log INFO "indexing already off for $volume"
  exit 0
fi
mdutil -i off "$volume" >/dev/null
if enabled; then
  log ERROR "indexing is still on for $volume after mdutil -i off"
  exit 1
fi
log INFO "indexing off for $volume (undo: mdutil -i on $volume)"
