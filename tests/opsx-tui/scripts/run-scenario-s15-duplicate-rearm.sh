#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=sequence
export FAKE_OPSX_GATE_SEQUENCE=1,1,0
export FAKE_OPENAI_STATUS_SEQUENCE=500,200,200,200,200
export FAKE_OPENAI_RESPONSE="stale-owned-response"
# Initial old arm = generation 1; two same-change replacements = 2 then 3.
export FAKE_OPENAI_MATCH_TEXT='[opsx-loop arm generation: 3]'
export FAKE_OPENAI_MATCH_RESPONSE="latest-arm-owned-response"
scn_setup "s15-duplicate-rearm"
scn_make_change "old-duplicate-change"
scn_make_change "same-replacement-change"
scn_pi_start

scn_send "/opsx-loop old-duplicate-change"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
scn_send "/opsx-loop same-replacement-change"
scn_send "/opsx-loop same-replacement-change"
scn_assert_pane "same-replacement-change — gate green\. Ready to archive" "latest same-change re-arm reaches green" 60
scn_capture >/dev/null
owned_line=$(grep -n "latest-arm-owned-response" "$PANE_LOG" | tail -1 | cut -d: -f1 || true)
green_line=$(grep -n "same-replacement-change — gate green\. Ready to archive" "$PANE_LOG" | tail -1 | cut -d: -f1 || true)
if [[ -n "$owned_line" && -n "$green_line" ]] && (( owned_line < green_line )); then
  echo "PASS: stale identical directive cannot claim latest generation"
else
  echo "FAIL: replacement gated before latest generated directive response" >&2
  SCN_FAILED=1
fi
scn_assert_file "$FAKE_LOG_DIR/gate-count-old-duplicate-change" "^1$" "old loop never re-gates"
scn_assert_file "$FAKE_LOG_DIR/gate-count-same-replacement-change" "^3$" "same-change gates twice at arm and once for latest directive"
provider_count=$(grep -cE "/chat/completions" "$PROVIDER_LOG" 2>/dev/null || true)
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" "$provider_count" 3 "green latest arm injects no extra turn"

scn_finish
