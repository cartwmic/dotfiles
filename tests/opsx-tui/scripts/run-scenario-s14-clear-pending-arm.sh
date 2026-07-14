#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPSX_GATE_DELAY_SECONDS=3
scn_setup "s14-clear-pending-arm"
scn_make_change "pending-arm-change"
scn_pi_start

scn_send "/opsx-loop pending-arm-change"
sleep 0.5
scn_send "/opsx-loop clear"
scn_assert_pane "Cleared opsx-loop: pending-arm-change" "clear cancels async turn-zero arm" 20
sleep 4
# Pi serializes slash-command handlers: clear may run immediately after the
# delayed gate handler queued its directive, but it must abort before provider
# execution and prevent any later lifecycle effect.
provider_count=0
[[ -f "$PROVIDER_LOG" ]] && provider_count=$(grep -cE "/chat/completions" "$PROVIDER_LOG" 2>/dev/null || true)
if (( provider_count == 0 )); then
  echo "PASS: cancelled pending arm injects no provider turn"
else
  echo "FAIL: cancelled pending arm injected $provider_count provider turn(s)" >&2
  SCN_FAILED=1
fi

scn_finish
