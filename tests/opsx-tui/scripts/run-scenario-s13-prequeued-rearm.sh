#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=sequence
export FAKE_OPSX_GATE_SEQUENCE=1,0
export FAKE_OPENAI_STATUS_SEQUENCE=500,200,200,200
export FAKE_OPENAI_RESPONSE="old-owned-response"
export FAKE_OPENAI_MATCH_TEXT='replacement-prequeued-change'
export FAKE_OPENAI_MATCH_RESPONSE="replacement-owned-response"
scn_setup "s13-prequeued-rearm"
scn_make_change "old-prequeued-change"
scn_make_change "replacement-prequeued-change"
scn_pi_start

scn_send "/opsx-loop old-prequeued-change"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
# Queue unrelated user work ahead of the replacement directive during retry
# backoff. Only the exact generated replacement directive may transfer ownership.
scn_send "old queued steering message"
scn_send "/opsx-loop replacement-prequeued-change"
scn_assert_pane 'OpenSpec change "replacement-prequeued-change"' "replacement directive is queued behind old user work" 20
scn_assert_pane "replacement-prequeued-change — gate green\. Ready to archive" "replacement reaches green after its own response" 45
scn_capture >/dev/null
replacement_line=$(grep -n "replacement-owned-response" "$PANE_LOG" | tail -1 | cut -d: -f1 || true)
green_line=$(grep -n "replacement-prequeued-change — gate green\. Ready to archive" "$PANE_LOG" | tail -1 | cut -d: -f1 || true)
if [[ -n "$replacement_line" && -n "$green_line" ]] && (( replacement_line < green_line )); then
  echo "PASS: unrelated queued user response cannot gate replacement"
else
  echo "FAIL: replacement gated before its exact directive response" >&2
  SCN_FAILED=1
fi
scn_assert_file "$FAKE_LOG_DIR/gate-count-old-prequeued-change" "^1$" "old queued work cannot re-gate replaced loop"
scn_assert_file "$FAKE_LOG_DIR/gate-count-replacement-prequeued-change" "^2$" "replacement gates only at kickoff and exact directive completion"
provider_count=$(grep -cE "/chat/completions" "$PROVIDER_LOG" 2>/dev/null || true)
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" "$provider_count" 3 "green replacement injects no extra provider turn"

scn_finish
