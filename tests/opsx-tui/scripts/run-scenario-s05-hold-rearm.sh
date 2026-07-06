#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-deterministic-loop-states

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=sequence
export FAKE_OPSX_GATE_SEQUENCE=1,1,0
export FAKE_OPENAI_DELAY_MS=4000
scn_setup "s05-hold-rearm"
scn_make_change "held-change"
scn_pi_start

scn_send "/opsx-loop held-change"
scn_assert_pane "opsx-loop started.*held-change" "held-change arms before hold"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20

python3 - <<PY
from pathlib import Path
p = Path(r"$SCENARIO_CWD/openspec/changes/held-change/review.md")
s = p.read_text()
s = s.replace('loop_max_iterations: 5\n', 'loop_max_iterations: 5\nloop_hold: true\nloop_hold_reason: decision audit in code-review.md round 1\n')
p.write_text(s)
PY

scn_assert_pane "loop_hold.*decision audit in code-review.md round 1|decision audit in code-review.md round 1" "loop hold stops continuation with reason" 30

scn_send "/opsx-loop held-change"
scn_assert_pane "hold was set:|cleared by re-arm" "named re-arm clears hold and surfaces previous reason" 30

if grep -q "loop_hold: true" "$SCENARIO_CWD/openspec/changes/held-change/review.md"; then
  echo "FAIL: loop_hold still present after re-arm" >&2
  SCN_FAILED=1
else
  echo "PASS: loop_hold cleared from review.md"
fi

scn_finish
