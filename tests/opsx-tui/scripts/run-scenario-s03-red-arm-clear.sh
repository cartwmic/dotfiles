#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-deterministic-loop-states

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_DELAY_MS=1000
scn_setup "s03-red-arm-clear"
scn_make_change "red-change"
scn_pi_start

scn_send "/opsx-loop red-change"
# Clear immediately after arming, while the slash-command lane is still idle.
# If we wait for the first provider request, Pi treats later input as active-turn
# steer text and the /opsx-loop clear command is not executed until after the
# autonomous loop has already continued/stalled.
sleep 0.2
scn_send "/opsx-loop clear"
scn_assert_pane "Cleared opsx-loop: red-change" "clear stops armed loop"

provider_count=0
[[ -f "$PROVIDER_LOG" ]] && provider_count=$(grep -cE "/chat/completions" "$PROVIDER_LOG" 2>/dev/null || true)
provider_count=${provider_count:-0}
if (( provider_count <= 1 )); then
  echo "PASS: clear allowed at most one in-flight provider request (got $provider_count)"
  scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" "$provider_count" 3 "clear prevents further provider continuation"
else
  echo "FAIL: clear raced too late — expected at most 1 provider request, got $provider_count" >&2
  [[ -f "$PROVIDER_LOG" ]] && cat "$PROVIDER_LOG" >&2 || true
  SCN_FAILED=1
fi
scn_assert_file "$FAKE_LOG_DIR/opsx.log" "env_FAKE_OPSX_WORKTREE_PATH=" "fake opsx logs relevant env values"

scn_finish
