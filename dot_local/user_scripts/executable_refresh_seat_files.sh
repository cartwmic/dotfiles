#!/bin/sh
#
# Rewrites every managed ~/.claude/fleet/seat-*.json from its template. Run by run script 20 right after
# apply_harness_config.sh has linked the skills.
#
# Why: the seat files turn off every skill a seat does not keep, so the template lists the skills under ~/.claude/skills (.chezmoitemplates/fleet_seat).
# chezmoi renders and writes the files BEFORE any run script, so a skill that only arrives in this apply (a git-repo external's clone or pull,
# which the template cannot name from the source) was missing from every seat file until the next apply. The files then render again with the
# skill on disk, so the rewrite here is exactly what the next apply would write: chezmoi sees no drift and no second apply is needed.
#
# `chezmoi cat` renders without taking the persistent-state lock a nested `chezmoi apply` would time out on. It needs the apply's own
# source, config and destination, which chezmoi gives every run script as CHEZMOI_* variables. Run by hand: `chezmoi apply` is the way; this
# refuses to guess a source and config.
set -eu

: "${CHEZMOI_SOURCE_DIR:?run this from a chezmoi run script (it needs the CHEZMOI_* variables)}"
: "${CHEZMOI_CONFIG_FILE:?run this from a chezmoi run script (it needs the CHEZMOI_* variables)}"
: "${CHEZMOI_DEST_DIR:?run this from a chezmoi run script (it needs the CHEZMOI_* variables)}"
chezmoi_bin="${CHEZMOI_EXECUTABLE:-chezmoi}"

chez() {
  "$chezmoi_bin" --source "$CHEZMOI_SOURCE_DIR" --config "$CHEZMOI_CONFIG_FILE" --destination "$CHEZMOI_DEST_DIR" "$@"
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# the managed set decides which seat files this profile has (none on a profile that leaves .claude/fleet out)
chez managed --include=files --path-style=absolute | grep '/\.claude/fleet/seat-[^/]*\.json$' > "$work/seats" || true

while IFS= read -r seat; do
  chez cat "$seat" > "$work/new"
  if ! cmp -s "$work/new" "$seat"; then
    cat "$work/new" > "$seat"  # in place: the file keeps its mode
    echo "[refresh_seat_files] Updated $seat"
  fi
done < "$work/seats"
