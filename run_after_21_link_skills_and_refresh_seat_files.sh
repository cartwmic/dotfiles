#!/bin/sh
#
# Runs after every apply (run_after, not run_onchange): links the skills again and renders the seat files again.
#
# A git-repo external (the work profile's private playbook) is cloned or pulled during the apply, after chezmoi has written the seat files
# (~/.claude/fleet/seat-*.json, which list every skill under ~/.claude/skills as "off" unless the seat keeps it, .chezmoitemplates/fleet_seat) and
# without changing any input of script 20. Script 20 is run_onchange, so it does not run for a skill that only arrives by a later pull: the skill
# was neither linked nor in the seat files until some unrelated input of script 20 changed. So this script, which always runs and is cheap when
# nothing changed, links what the clone now holds (apply_harness_config.sh skills, the same linking script 20 does) and then refresh_seat_files.sh
# renders the seat files again. A failed link stops it before the refresh. It prints only what it changed.
# `chezmoi apply <path>` runs no scripts at all: a scoped apply is covered by the skills fleet_seat names from the source.
set -eu

SCRIPT="$HOME/.local/user_scripts/apply_harness_config.sh"
REFRESH="$HOME/.local/user_scripts/refresh_seat_files.sh"

if [ ! -x "$SCRIPT" ]; then
  echo "[link_skills] INFO: Harness config adapter not found at $SCRIPT, skipping"
  exit 0
fi

out="$(mktemp)"
trap 'rm -f "$out"' EXIT
if ! "$SCRIPT" skills >"$out" 2>&1; then
  cat "$out" >&2
  exit 1
fi
grep -v 'Linking canonical skills' "$out" || true

"$REFRESH"
