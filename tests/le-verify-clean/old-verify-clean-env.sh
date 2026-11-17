#!/bin/bash
# FIXTURE: the old helper, verbatim (the template as of 2026-11-17), kept so the test can show it deleting another run's folder. Do not use it; use le-verify-clean.
# LE verify on this machine with the agent session's T3*/CLAUDE* variables removed: journey 283 (hp9) fails step 6 when they leak into its rig (seen 2026-11-14 on abf5ea97).
# Cleans its own scratch at exit: the old tree lean-change made (/tmp/lean-change-old-<its pid>-*) and every /tmp/le-journey-* folder that appeared during the run whose
# repo copy is at this run's head or base (journeys hard-code /tmp and jr.mjs drops JOURNEY_SCRATCH_DIR, so the folder cannot be redirected). Folders of other runs are left alone.
# Usage: checks/verify-clean-env.sh <out.json>
W=/home/cartwmic/.local/share/coordinator-workspace/loop-engine/close-summary-20261116
cd "$W" || exit 1
OUT=$1
HEAD=$(git -C repo rev-parse HEAD)
BASE=$(python3 -c 'import json;print(json.load(open("profile.json"))["base"])')
BEFORE=$(mktemp "$W/.verify-before.XXXX")
ls -d /tmp/le-journey-* 2>/dev/null | sort > "$BEFORE"
VPID=
cleanup() {
  [ -n "$VPID" ] && rm -rf /tmp/lean-change-old-"$VPID"-*
  for d in $(ls -d /tmp/le-journey-* 2>/dev/null | sort | comm -13 "$BEFORE" -); do
    r=$(ls -d "$d/playbook-repo" "$d/personal/playbook-repo" 2>/dev/null | head -1)
    h=$([ -n "$r" ] && git -C "$r" rev-parse HEAD 2>/dev/null)
    if [ "$h" = "$HEAD" ] || [ "$h" = "$BASE" ]; then rm -rf "$d"; echo "verify-clean-env: removed $d" >&2; fi
  done
  rm -f "$BEFORE"
}
trap cleanup EXIT
trap 'kill -TERM "$VPID" 2>/dev/null; exit 143' TERM INT
for v in $(env | grep -oE '^(T3[A-Z_]*|CLAUDE[A-Z_]*)=' | tr -d =); do unset "$v"; done
lean-change verify < show-full.json > "$OUT" &
VPID=$!
wait "$VPID"
