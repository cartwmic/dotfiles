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
# Use the provider request as the durable "worker turn started" signal. The
# `opsx-loop started` notification is transient and may scroll out of the pane;
# waiting on it can burn the whole fake gate sequence before the hold is written.
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20

echo "PASS: held-change armed before hold (provider turn observed)"

python3 - <<PY
from pathlib import Path
p = Path(r"$SCENARIO_CWD/openspec/changes/held-change/review.md")
s = p.read_text()
s = s.replace('loop_max_iterations: 5\n', 'loop_max_iterations: 5\nloop_hold: true\nloop_hold_reason: decision audit in code-review.md round 1\n')
p.write_text(s)
PY

scn_assert_pane "loop_hold.*decision audit in code-review.md round 1|decision audit in code-review.md round 1" "loop hold stops continuation with reason" 30

scn_send "/opsx-loop held-change"

if grep -q "loop_hold: true" "$SCENARIO_CWD/openspec/changes/held-change/review.md"; then
  echo "FAIL: loop_hold still present after re-arm" >&2
  SCN_FAILED=1
else
  echo "PASS: loop_hold cleared from review.md"
fi

if grep -q "loop_hold cleared by named re-arm (/opsx-loop held-change); reason was: decision audit in code-review.md round 1" "$SCENARIO_CWD/openspec/changes/held-change/review.md"; then
  echo "PASS: named re-arm preserved previous hold reason in Execution Notes"
else
  echo "FAIL: named re-arm did not preserve previous hold reason in Execution Notes" >&2
  cat "$SCENARIO_CWD/openspec/changes/held-change/review.md" >&2
  SCN_FAILED=1
fi

scn_finish
