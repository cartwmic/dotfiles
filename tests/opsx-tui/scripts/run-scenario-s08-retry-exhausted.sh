#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
# Pi defaults to three native retry attempts after the initial request.
export FAKE_OPENAI_STATUS_SEQUENCE=500,500,500,500
scn_setup "s08-retry-exhausted"
scn_make_change "retry-exhausted-change"
scn_pi_start

scn_send "/opsx-loop retry-exhausted-change"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 4 45
scn_assert_pane "opsx-loop stopped \(error\): retry-exhausted-change" "exhausted native retries produce one final opsx stop" 30
scn_assert_file "$FAKE_LOG_DIR/gate-count-retry-exhausted-change" "^1$" "failed attempts do not run the gate"
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" 4 3 "opsx adds no retry after Pi settles"

scn_finish
