#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-deterministic-loop-states

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPENAI_DELAY_MS=5000
scn_setup "s04-goal-distill"
scn_pi_start

scn_send "/opsx-loop goal build a multi word thing"
scn_assert_pane "distilling intent.*build a multi word thing|started from goal:.*build a multi word thing" "goal kickoff preserves multi-word text"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
scn_assert_file "$PROVIDER_LOG" "build a multi word thing" "distill directive sent full goal to provider"

mkdir -p "$SCENARIO_CWD/openspec/changes/distilled-change"
cat > "$SCENARIO_CWD/openspec/changes/distilled-change/intent.md" <<'EOF_INTENT'
# Intent — distilled-change
Status: explore-frozen
EOF_INTENT

git -C "$SCENARIO_CWD" add openspec/changes/distilled-change/intent.md
git -C "$SCENARIO_CWD" commit -q -m "distill change intent"

scn_assert_pane "distilled-change.*PAUSED for intent confirmation|PAUSED.*distilled-change" "new intent pauses for confirmation"

scn_finish
