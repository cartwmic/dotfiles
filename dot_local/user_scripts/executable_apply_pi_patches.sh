#!/bin/sh
#
# Applies all chezmoi-managed runtime patches to the user's installed
# pi-coding-agent / pi-ai trees. Idempotent. Safe to run on machines
# without pi installed (exits 0, one notice line per skipped patch).
#
# A failing patch does not stop the loop: every patch runs, each failure is named, and the script exits 1
# at the end. It also keeps a failure marker (names of the failed patches) at $PI_PATCH_FAILURE_MARKER, or
# ${XDG_STATE_HOME:-~/.local/state}/pi-patches/failed, which run_after_99_report_pi_patch_failures reads so
# a failed patch run never hides the scripts that come after it. A run where every patch passes removes it.
#
# See: ~/.local/share/chezmoi/dot_local/share/pi-patches/<patch>/README.md

set -eu

SCRIPT_NAME="apply_pi_patches"
PATCHES_ROOT="${PI_PATCHES_ROOT:-$HOME/.local/share/chezmoi/dot_local/share/pi-patches}"
FAILURE_MARKER="${PI_PATCH_FAILURE_MARKER:-${XDG_STATE_HOME:-$HOME/.local/state}/pi-patches/failed}"

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

# One Pi-installed check, the same locator every patch uses (pi-root.mjs). With no Pi, the
# "applying patch" line is left out, so a skipped patch prints exactly its own notice line.
# If the check itself cannot run, keep the line; the patches then fail or report as they always did.
pi_present=$(node --input-type=module -e 'import { pathToFileURL } from "node:url"; const { piCodingAgentRoot } = await import(pathToFileURL(process.argv[1]).href); process.stdout.write(piCodingAgentRoot() ? "yes" : "no");' "$PATCHES_ROOT/pi-root.mjs") || pi_present=unknown

# Iterate every patch directory containing a patch.mjs.
exit_code=0
failed_patches=""
for patch_dir in "$PATCHES_ROOT"/*/; do
  [ -d "$patch_dir" ] || continue
  patch_script="${patch_dir}patch.mjs"
  if [ ! -f "$patch_script" ]; then
    continue
  fi

  patch_name=$(basename "$patch_dir")
  if [ "$pi_present" != no ]; then
    log "applying patch: $patch_name"
  fi
  if ! node "$patch_script"; then
    log_error "patch $patch_name failed — see diagnostic above"
    exit_code=1
    failed_patches="$failed_patches $patch_name"
  fi
done

if [ "$exit_code" -ne 0 ]; then
  log_error "failed patches:$failed_patches — fix them, then run: mise run apply-pi-patches"
  mkdir -p "$(dirname "$FAILURE_MARKER")"
  printf '%s\n' "$failed_patches" > "$FAILURE_MARKER"
else
  rm -f "$FAILURE_MARKER"
fi
exit "$exit_code"
