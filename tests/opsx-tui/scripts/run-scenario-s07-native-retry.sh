#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=sequence
export FAKE_OPSX_GATE_SEQUENCE=1,0
export FAKE_OPENAI_STATUS_SEQUENCE=500,200
scn_setup "s07-native-retry"
scn_make_change "native-retry-change"
scn_pi_start

scn_send "/opsx-loop native-retry-change"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 2 30
scn_assert_pane "gate green\. Ready to archive" "successful Pi-native retry returns to opsx gate" 30
scn_assert_file "$FAKE_LOG_DIR/gate-count-native-retry-change" "^2$" "gate runs once at kickoff and once after retry success"
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" 2 3 "green landing injects no extra provider turn"

scn_finish
