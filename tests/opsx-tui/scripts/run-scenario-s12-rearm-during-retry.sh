#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=sequence
export FAKE_OPSX_GATE_SEQUENCE=1,0
export FAKE_OPENAI_STATUS_SEQUENCE=500,200,200
# Replacement turn-0 gate outlasts Pi's first retry delay, forcing the old
# retry to finish inside the async invalidation window this scenario guards.
export FAKE_OPSX_GATE_DELAY_SECONDS=3
scn_setup "s12-rearm-during-retry"
scn_make_change "old-retry-change"
scn_make_change "replacement-change"
scn_pi_start

scn_send "/opsx-loop old-retry-change"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
scn_send "/opsx-loop replacement-change"
scn_assert_pane 'OpenSpec change "replacement-change"' "named re-arm queues replacement directive during native retry" 20
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 3 40
scn_assert_pane "replacement-change — gate green\. Ready to archive" "replacement directive owns its clean boundary" 30
scn_assert_file "$FAKE_LOG_DIR/gate-count-old-retry-change" "^1$" "old retry cannot evaluate its replaced loop"
scn_assert_file "$FAKE_LOG_DIR/gate-count-replacement-change" "^2$" "replacement gates only at kickoff and its own clean turn"
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" 3 3 "replacement green landing injects no extra turn"

scn_finish
