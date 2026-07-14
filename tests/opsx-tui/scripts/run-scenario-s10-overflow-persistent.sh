#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_STATUS_SEQUENCE=400,400
export FAKE_OPENAI_ERROR_MESSAGE="context length exceeded"
scn_setup "s10-overflow-persistent"
scn_make_change "overflow-persistent-change"
scn_pi_start

scn_send "/opsx-loop overflow-persistent-change"
scn_assert_pane "context overflow; compacting and retrying once" "first settled overflow consumes one recovery allowance" 30
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 2 30
scn_assert_pane "context overflow persisted after a compact-and-retry" "second settled overflow lands visibly" 30
scn_assert_file "$FAKE_LOG_DIR/gate-count-overflow-persistent-change" "^1$" "overflow attempts do not run the gate"
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" 2 3 "persistent overflow receives no third retry"

scn_finish
