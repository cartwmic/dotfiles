#!/bin/sh
#
# Proof that the last `chezmoi apply` left this machine as the repo says. Exit 0 when it did, 1 when it did not.
#
# Plain `chezmoi verify` cannot be used for this: the run_after scripts (75, 90, 99) run on every apply, so chezmoi always lists
# them as pending and exits 1 even right after a clean apply. This checks what a clean apply guarantees instead:
#   1. every managed file, directory and symlink matches the source (`chezmoi verify --exclude=scripts`)
#   2. no Pi patch failure is recorded (the marker apply_pi_patches.sh writes, see run_after_99_report_pi_patch_failures.sh)
#   3. with Pi installed, every Pi patch still verifies against the installed Pi (each patch.mjs --check)
# Run it after `chezmoi apply`:  ~/.local/user_scripts/verify_dotfiles.sh
# Not covered: codex hook trust (script 90 prints its own error) and whether run_onchange scripts ran.

PATCHES_ROOT="${PI_PATCHES_ROOT:-$HOME/.local/share/pi-patches}"
FAILURE_MARKER="${PI_PATCH_FAILURE_MARKER:-${XDG_STATE_HOME:-$HOME/.local/state}/pi-patches/failed}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
status=0

pass() { echo "[verify_dotfiles] ok: $1"; }
fail() { echo "[verify_dotfiles] FAIL: $1" >&2; status=1; }

if output=$(chezmoi verify --exclude=scripts 2>&1); then
  pass "managed files match the source"
else
  fail "managed files differ from the source; run: chezmoi diff --exclude=scripts"
  [ -z "$output" ] || echo "$output" | head -20 >&2
fi

if [ -s "$FAILURE_MARKER" ]; then
  fail "Pi patch failure recorded:$(tr '\n' ' ' < "$FAILURE_MARKER"); fix it, then run: mise run apply-pi-patches"
else
  pass "no Pi patch failure recorded"
fi

if [ -d "$PATCHES_ROOT" ] && command -v node >/dev/null 2>&1; then
  profile="${PI_CHEZMOI_PROFILE:-$(chezmoi data --format json 2>/dev/null | jq -er '.profile' 2>/dev/null)}"
  export PI_CHEZMOI_PROFILE="$profile"
  pi_root=$(node --input-type=module -e 'import { pathToFileURL } from "node:url"; const { piCodingAgentRoot } = await import(pathToFileURL(process.argv[1]).href); process.stdout.write(piCodingAgentRoot() ?? "");' "$PATCHES_ROOT/pi-root.mjs" 2>/dev/null)
  if [ -z "$pi_root" ]; then
    pass "Pi is not installed; no Pi patches to check"
  elif [ -z "$profile" ]; then
    fail "cannot read the chezmoi profile (chezmoi data); Pi patches not checked"
  else
    for patch_dir in "$PATCHES_ROOT"/*/; do
      [ -f "${patch_dir}patch.mjs" ] || continue
      name=$(basename "$patch_dir")
      if node "${patch_dir}patch.mjs" --check >/dev/null 2>&1; then
        pass "Pi patch $name"
      else
        fail "Pi patch $name does not verify against the installed Pi; run: node ${patch_dir}patch.mjs --check"
      fi
    done
  fi
fi

if [ "$status" -eq 0 ]; then
  echo "[verify_dotfiles] PASS"
else
  echo "[verify_dotfiles] FAILED: this machine does not match the dotfiles; see FAIL lines above" >&2
fi
exit "$status"
