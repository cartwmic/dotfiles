#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_STATUS_SEQUENCE=500,200
scn_setup "s11-clear-during-retry"
scn_make_change "stale-clear-change"
scn_pi_start

scn_send "/opsx-loop stale-clear-change"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
# Execute extension command during Pi's native retry delay. Clear invalidates the
# LoopState object that owns the pending error before final settlement arrives.
scn_send "/opsx-loop clear"
scn_assert_pane "Cleared opsx-loop: stale-clear-change" "clear executes while native retry is pending" 20
sleep 4
scn_capture >/dev/null
if grep -qE "opsx-loop stopped \(error\): stale-clear-change|gate green\. Ready to archive" "$PANE_LOG"; then
  echo "FAIL: stale settlement affected cleared loop" >&2
  SCN_FAILED=1
else
  echo "PASS: stale settlement cannot stop or continue cleared loop"
fi
scn_assert_file "$FAKE_LOG_DIR/gate-count-stale-clear-change" "^1$" "cleared pending attempt never reaches another gate"

scn_finish
