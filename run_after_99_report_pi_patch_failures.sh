#!/bin/sh
# Runs after every full chezmoi apply, last (99): chezmoi stops at the first failing script, so the Pi patch step (30) records a failure
# in a marker file and exits 0, the later scripts (65, 75, 90) still run, and this one turns the marker into the apply's non-zero exit.
# apply_pi_patches.sh writes the marker when a patch fails and removes it when every patch passes (including `mise run apply-pi-patches`).
marker="${PI_PATCH_FAILURE_MARKER:-${XDG_STATE_HOME:-$HOME/.local/state}/pi-patches/failed}"
[ -s "$marker" ] || exit 0
echo "[pi_patches] ERROR: Pi runtime patches are not all applied. Failed:$(tr '\n' ' ' < "$marker")" >&2
echo "[pi_patches] The other setup scripts ran. Fix the patch (see the [apply_pi_patches] errors above), then run: mise run apply-pi-patches" >&2
exit 1
