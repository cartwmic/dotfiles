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
# Some payloads live in Pi git extensions that track their default branch (response-visibility delegates to
# cartwmic/pi-response-visibility). Plain `pi update` leaves extensions alone, so before the loop this script runs
# `pi update --extension <source>` for each source in $PI_PATCH_EXTENSIONS (default: that one). A refresh that fails
# (offline, for example) is a WARN: the installed copy is used and the patch itself says whether it still fits.
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

# Refresh the Pi extensions whose code the patches delegate to. The sources are the exact strings in Pi's settings packages list
# (.chezmoitemplates/pi_settings_desired), the same on both desktop profiles. Pinned `git:...@sha` sources are not listed here.
# A new response-visibility checkout cannot recognise a Pi tree that the previous checkout patched (the patch text changes between
# helper revisions), so when the refresh moves the checkout, the old checkout's own helper first rolls its patch back (old=pre-refresh
# HEAD, extracted with git archive); the loop below then applies the new one.
PI_AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
refresh_extension() {
  extension="$1"
  dir="$PI_AGENT_DIR/git/${extension#https://}"
  old=$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)
  log "refreshing Pi extension: $extension"
  if ! pi update --extension "$extension"; then
    log "WARN: could not refresh $extension; using the installed copy"
    return 0
  fi
  new=$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)
  case "$extension" in
    */pi-response-visibility)
      if [ -n "$old" ] && [ "$old" != "$new" ] && [ -f "$PATCHES_ROOT/response-visibility/patch.mjs" ]; then
        log "response-visibility helper moved ${old%"${old#???????}"} -> ${new%"${new#???????}"}; rolling back its patch with the old helper first"
        old_dir=$(mktemp -d)
        if git -C "$dir" archive "$old" | tar -x -C "$old_dir" &&
          PI_RESPONSE_VISIBILITY_HELPER="$old_dir/bin/core.mjs" node "$PATCHES_ROOT/response-visibility/patch.mjs" --rollback; then
          :
        else
          log "WARN: could not roll back the old response-visibility patch; the patch step below reports whether the tree still fits"
        fi
        rm -rf "$old_dir"
      fi
      ;;
  esac
}
if [ "$pi_present" != no ]; then
  export PATH="$HOME/.local/bin:$HOME/.pi/agent/bin:$PATH"
  for extension in ${PI_PATCH_EXTENSIONS-https://github.com/cartwmic/pi-response-visibility}; do
    if command -v pi >/dev/null 2>&1; then
      refresh_extension "$extension"
    else
      log "WARN: pi not on PATH; not refreshing $extension"
    fi
  done
fi

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
