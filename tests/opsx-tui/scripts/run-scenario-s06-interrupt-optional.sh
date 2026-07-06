#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-deterministic-loop-states
# Interrupt timing is provider/runtime-sensitive. This scenario is opt-in until
# proven stable enough for the default gate.

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

if [[ "${OPSX_TUI_ENABLE_INTERRUPT:-0}" != "1" ]]; then
  echo "SKIP: set OPSX_TUI_ENABLE_INTERRUPT=1 to run interrupt smoke"
  exit 0
fi

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_DELAY_MS=10000
scn_setup "s06-interrupt-optional"
scn_make_change "interrupt-change"
scn_pi_start

scn_send "/opsx-loop interrupt-change"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
scn_send_key Escape
scn_assert_pane "stopped \(aborted\)|interrupted|aborted" "escape interrupt stops loop" 30

scn_finish
