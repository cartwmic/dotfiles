#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-deterministic-loop-states

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=green
scn_setup "s02-green-change"
scn_make_change "green-change"
scn_pi_start

scn_send "/opsx-loop green-change"
scn_assert_pane "already passes opsx gate|ready to archive" "green change reports ready without arming"
scn_assert_file "$FAKE_LOG_DIR/opsx.log" "gate[[:space:]]+green-change" "gate invoked for green change"

if [[ -f "$PROVIDER_LOG" ]] && grep -q "/chat/completions" "$PROVIDER_LOG"; then
  echo "FAIL: green change injected a worker/provider turn" >&2
  cat "$PROVIDER_LOG" >&2
  SCN_FAILED=1
else
  echo "PASS: green change did not call provider"
fi

scn_finish
