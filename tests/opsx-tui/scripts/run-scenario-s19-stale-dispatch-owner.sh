#!/usr/bin/env bash
# AC: opsx-loop.opsx-dispatch-forces-resolved-role-model
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_DELAY_MS=2000
export FAKE_OPENAI_TOOL_CALL_MATCH_SEQUENCE="dispatch-owner-old|dispatch-owner-new"
export FAKE_OPENAI_TOOL_CALL_ARGUMENTS='{"role":"review","task":"verify exact dispatch owner","agent":"definitely-missing-agent"}'
scn_setup "s19-stale-dispatch-owner"
scn_make_change "dispatch-owner-old"
scn_make_change "dispatch-owner-new"
scn_pi_start

tool_result_contains() {
  local request_index="$1"
  local pattern="$2"
  python3 - "$PROVIDER_LOG" "$request_index" "$pattern" <<'PY'
import json
import re
import sys

path, wanted_index, pattern = sys.argv[1], int(sys.argv[2]), sys.argv[3]
requests = []
with open(path, encoding="utf-8") as f:
    for line in f:
        outer = json.loads(line)
        if "/chat/completions" not in outer.get("url", ""):
            continue
        requests.append(json.loads(outer.get("body", "{}")))
if wanted_index >= len(requests):
    raise SystemExit(2)
results = [message.get("content", "") for message in requests[wanted_index].get("messages", []) if message.get("role") == "tool"]
text = "\n".join(str(result) for result in results)
raise SystemExit(0 if re.search(pattern, text) else 1)
PY
}

scn_send "/opsx-loop dispatch-owner-old"
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 1 20
scn_send "/opsx-loop dispatch-owner-new"
# Stale tool result below is the durable ownership signal: it can be refused as
# not-armed only after the replacement has invalidated the old exact owner.
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 2 30
if tool_result_contains 1 "no opsx-loop is armed"; then
  echo "PASS: stale old request cannot dispatch against replacement loop"
else
  echo "FAIL: stale old request was not rejected by exact owner" >&2
  cat "$PROVIDER_LOG" >&2
  SCN_FAILED=1
fi

scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 4 40
if tool_result_contains 3 "spawn (error|failed)"; then
  echo "PASS: replacement-owned directive reaches dispatch spawn path"
else
  echo "FAIL: replacement-owned directive did not reach dispatch spawn path" >&2
  cat "$PROVIDER_LOG" >&2
  SCN_FAILED=1
fi

scn_send "/opsx-loop clear"
scn_assert_pane "Cleared opsx-loop: dispatch-owner-new" "dispatch ownership scenario drains replacement loop" 20

scn_finish
