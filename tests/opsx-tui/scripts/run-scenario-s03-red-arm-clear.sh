#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-deterministic-loop-states

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_DELAY_MS=10000
scn_setup "s03-red-arm-clear"
scn_make_change "red-change"
scn_pi_start

scn_send "/opsx-loop red-change"
scn_assert_pane "opsx-loop started.*red-change" "red change arms loop"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20

scn_send "/opsx-loop status"
scn_assert_pane "opsx-loop active|change: red-change" "status names active red change"

scn_send "/opsx-loop clear"
scn_assert_pane "Cleared opsx-loop: red-change" "clear stops active loop"

scn_finish
