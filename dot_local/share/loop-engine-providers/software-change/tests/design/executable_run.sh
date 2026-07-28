#!/bin/sh
# Regression matrix for the design-semantic gate.
#
#   ./run.sh                 run every case in expectations.tsv
#   ./run.sh good hollow-asserted
#                            run named cases only
#
# Each case is one direct invocation of the provider binary in the
# `evaluate_gates` role: no engine, no run state. The judges are real model
# calls, so a full matrix costs roughly (cases x 6) calls and (cases x 2)
# minutes, and is run serially on purpose -- concurrent invocations make the
# bridge time out.
#
# Environment:
#   SC_BIN            provider binary          (default: the deployed one)
#   SC_JUDGE_MODEL    axis judge model
#   SC_DECIDER_MODEL  deciding judge model
#   SC_JUDGE_EXT      extension the models need, "" for none
#   SC_OUT            where artifacts and replies are kept
#   SC_GAP            seconds between cases    (default 15)
#
# Exit status is 0 only when every case matched its expectation. A case whose
# judges returned no determinate verdict is retried once and then reported as
# INDETERMINATE, which is not a pass.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
BIN=${SC_BIN:-"$HOME/.local/share/loop-engine-providers/bin/software-change"}
OUT=${SC_OUT:-"${TMPDIR:-/tmp}/sc-design-matrix"}
GAP=${SC_GAP:-15}
JUDGE=${SC_JUDGE_MODEL:-claude-bridge/claude-haiku-4-5}
DECIDER=${SC_DECIDER_MODEL:-claude-bridge/claude-sonnet-5}
EXT=${SC_JUDGE_EXT-"$HOME/.pi/agent/git/github.com/cartwmic/pi-claude-bridge/index.ts"}

[ -x "$BIN" ] || { echo "no provider binary at $BIN (set SC_BIN)" >&2; exit 2; }

WORK="$OUT/work"
mkdir -p "$WORK"
if [ -n "$EXT" ]; then EXT_LINE="extensions = [\"$EXT\"]"; else EXT_LINE=""; fi
cat > "$WORK/.loop-workflow.toml" <<TOML
schema_version = 1

[judge]
model = "$JUDGE"
consensus_model = "$DECIDER"
$EXT_LINE
timeout_seconds = 840

[validation]
commands = [{ id = "noop", run = ["/usr/bin/true"] }]
TOML

cases=$(grep -v '^#' "$HERE/expectations.tsv" | grep -v '^[[:space:]]*$' | cut -f1)
if [ $# -gt 0 ]; then cases="$*"; fi

status=0
for c in $cases; do
  [ -f "$HERE/cases/$c.json" ] || { echo "unknown case: $c" >&2; exit 2; }

  art="$OUT/art-$c"
  rm -rf "$art"; mkdir -p "$art"
  cp "$HERE/intent.json" "$art/intent.json"
  cp "$HERE/cases/$c.json" "$art/design.json"

  ART="$art" WORK="$WORK" CASE="$c" python3 -c '
import json, os
print(json.dumps({
 "protocol_major": 1, "role": "evaluate_gates",
 "invocation_id": "matrix-" + os.environ["CASE"],
 "registration": {"registration_id": "matrix", "config_revision": 1,
   "executable": "/nonexistent", "argv": [],
   "working_directory": os.environ["WORK"], "timeout_seconds": 900},
 "payload": {"snapshot": {"current_state": "design",
     "inputs": {"artifact_root": os.environ["ART"], "work_root": os.environ["WORK"]}},
   "event": "design-ready",
   "required_gate_ids": ["design-ready", "design-semantic"],
   "selected_evidence": [], "inline_evidence": []}}))
' > "$OUT/req-$c.json"

  attempt=1
  while : ; do
    "$BIN" < "$OUT/req-$c.json" > "$OUT/out-$c.json" 2> "$OUT/err-$c.txt" || true
    if ! python3 "$HERE/report.py" --indeterminate "$OUT/out-$c.json"; then break; fi
    [ "$attempt" -ge 2 ] && break
    attempt=2
    sleep "$GAP"
  done

  python3 "$HERE/report.py" --check "$HERE/expectations.tsv" "$c" "$OUT/out-$c.json" || status=1
  sleep "$GAP"
done

exit "$status"
