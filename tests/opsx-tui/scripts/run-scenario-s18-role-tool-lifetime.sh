#!/usr/bin/env bash
# AC: opsx-loop.armed-loop-mutes-generic-subagent-tool
# AC: opsx-loop.goal-and-conversation-kickoff

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_DELAY_MS=3000
scn_setup "s18-role-tool-lifetime"
scn_make_change "tool-owner-a"
scn_make_change "tool-owner-b"

review_b="$SCENARIO_CWD/openspec/changes/tool-owner-b/review.md"
python3 - <<PY
from pathlib import Path
p = Path(r"$review_b")
s = p.read_text().replace(
    "loop_max_iterations: 5\n",
    "loop_max_iterations: 5\nloop_hold: true\nloop_hold_reason: force write-failure transition\n",
)
p.write_text(s)
PY
chmod 0444 "$review_b"

scn_pi_start

request_has_tool() {
  local index="$1"
  local tool="$2"
  python3 - "$PROVIDER_LOG" "$index" "$tool" <<'PY'
import json
import sys

path, wanted_index, wanted_tool = sys.argv[1], int(sys.argv[2]), sys.argv[3]
requests = []
with open(path, encoding="utf-8") as f:
    for line in f:
        outer = json.loads(line)
        if "/chat/completions" not in outer.get("url", ""):
            continue
        body = json.loads(outer.get("body", "{}"))
        requests.append(body)
if wanted_index >= len(requests):
    raise SystemExit(2)
names = [item.get("function", {}).get("name") for item in requests[wanted_index].get("tools", [])]
raise SystemExit(0 if wanted_tool in names else 1)
PY
}

assert_request_tool() {
  local index="$1"
  local expected="$2"
  local msg="$3"
  if request_has_tool "$index" opsx_dispatch; then
    if [[ "$expected" == present ]]; then
      echo "PASS: $msg"
    else
      echo "FAIL: $msg" >&2
      SCN_FAILED=1
    fi
  else
    if [[ "$expected" == absent ]]; then
      echo "PASS: $msg"
    else
      echo "FAIL: $msg" >&2
      SCN_FAILED=1
    fi
  fi
}

scn_send "/opsx-loop tool-owner-a"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
assert_request_tool 0 present "named loop exposes opsx_dispatch"

scn_send "/opsx-loop goal inspect merged tool lifetime"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 2 30
assert_request_tool 1 absent "named-to-goal replacement restores pre-arm tools"
scn_send "/opsx-loop clear"
scn_assert_pane "Cleared opsx-loop: goal" "goal replacement drains before second transition" 20

scn_send "/opsx-loop tool-owner-a"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 3 30
assert_request_tool 2 present "second named loop re-arms opsx_dispatch"

scn_send "/opsx-loop tool-owner-b"
scn_assert_pane "failed to clear loop_hold" "failed re-arm reports hold write error" 20
scn_send "probe after failed re-arm"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 4 30
assert_request_tool 3 absent "failed re-arm restores pre-arm tools"

scn_finish
