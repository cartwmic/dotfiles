#!/bin/sh
#
# Applies all chezmoi-managed runtime patches to the user's installed
# pi-coding-agent / pi-ai trees. Idempotent. Safe to run on machines
# without pi installed (exits 0 with a notice).
#
# See: ~/.local/share/chezmoi/dot_local/share/pi-patches/<patch>/README.md

set -eu

SCRIPT_NAME="apply_pi_patches"
PATCHES_ROOT="${PI_PATCHES_ROOT:-$HOME/.local/share/chezmoi/dot_local/share/pi-patches}"

log() {
  echo "[$SCRIPT_NAME] $1"
}

log_error() {
  echo "[$SCRIPT_NAME] ERROR: $1" >&2
}

if ! command -v node >/dev/null 2>&1; then
  log "node not found on PATH — skipping pi patches"
  exit 0
fi

if [ ! -d "$PATCHES_ROOT" ]; then
  log "no patches directory at $PATCHES_ROOT — skipping"
  exit 0
fi

# Iterate every patch directory containing a patch.mjs.
exit_code=0
for patch_dir in "$PATCHES_ROOT"/*/; do
  [ -d "$patch_dir" ] || continue
  patch_script="${patch_dir}patch.mjs"
  if [ ! -f "$patch_script" ]; then
    continue
  fi

  patch_name=$(basename "$patch_dir")
  log "applying patch: $patch_name"
  if ! node "$patch_script"; then
    log_error "patch $patch_name failed — see diagnostic above"
    exit_code=1
  fi
done

exit "$exit_code"
