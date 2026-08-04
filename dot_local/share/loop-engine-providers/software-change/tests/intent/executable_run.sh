#!/bin/sh
# Real-model calibration for intent classification authority.
# Release profile collects three fresh targeted observations plus one fresh
# full-roster observation per manifest row. Smoke profile collects one targeted
# observation for fast tuning. Controlled challenge axes use judge_wrapper.py;
# consensus stays real.
set -eu

HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
MANIFEST="$HERE/manifest.json"
OUT=${SC_OUT:-"${TMPDIR:-/tmp}/sc-intent-qualification"}
GAP=${SC_GAP:-5}
JUDGE=${SC_JUDGE_MODEL:-openai-codex/gpt-5.6-sol}
DECIDER=${SC_DECIDER_MODEL:-openai-codex/gpt-5.6-sol}
TIMEOUT=${SC_TIMEOUT:-1200}
PARALLEL=${SC_MAX_PARALLEL_AXES:-1}
PROFILE=${SC_PROFILE:-release}
CASE_JOBS=${SC_CASE_JOBS:-1}
REAL_COMMAND_JSON=${SC_JUDGE_COMMAND_JSON:-'["pi"]'}
EXTENSIONS_JSON=${SC_JUDGE_EXTENSIONS_JSON:-}
if [ -z "$EXTENSIONS_JSON" ]; then
  if [ "${SC_JUDGE_EXT+x}" = x ]; then
    EXTENSIONS_JSON=$(SC_VALUE="$SC_JUDGE_EXT" python3 -c 'import json,os; v=os.environ["SC_VALUE"]; print(json.dumps([v] if v else []))')
  elif [ "${JUDGE%%/*}" = "claude-bridge" ]; then
    EXTENSIONS_JSON=$(python3 -c 'import json,os; print(json.dumps([os.path.expanduser("~/.pi/agent/git/github.com/cartwmic/pi-claude-bridge/index.ts")]))')
  else
    EXTENSIONS_JSON='[]'
  fi
fi

if [ "${SC_BIN+x}" = x ]; then
  BIN=$SC_BIN
else
  BIN="$ROOT/target/debug/software-change"
  cargo build --quiet --bin software-change --manifest-path "$ROOT/Cargo.toml" || exit 2
fi
[ -x "$BIN" ] || { echo "provider binary not executable: $BIN" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 2; }
SC_BIN="$BIN" python3 "$HERE/check_manifest.py" || exit 2
[ "$JUDGE" != "intent-calibration/controlled-axis-v1" ] || { echo "real axis model uses reserved controlled identity" >&2; exit 2; }
[ "$DECIDER" != "intent-calibration/controlled-axis-v1" ] || { echo "real consensus model uses reserved controlled identity" >&2; exit 2; }
case "$PROFILE" in release|smoke) ;; *) echo "SC_PROFILE must be release or smoke" >&2; exit 2;; esac
case "$CASE_JOBS" in ''|*[!0-9]*|0) echo "SC_CASE_JOBS must be a positive integer" >&2; exit 2;; esac
case "$PARALLEL" in ''|*[!0-9]*|0) echo "SC_MAX_PARALLEL_AXES must be a positive integer" >&2; exit 2;; esac

rm -rf "$OUT"
mkdir -p "$OUT/observations" "$OUT/raw"

BIN="$BIN" ROOT="$ROOT" python3 - <<'PY' > "$OUT/describe-request.json"
import json,os
print(json.dumps({
 "protocol_major":1,"role":"describe","invocation_id":"intent-qualification-describe",
 "registration":{"registration_id":"intent-qualification","config_revision":1,
  "executable":os.environ["BIN"],"argv":[],"working_directory":os.environ["ROOT"],"timeout_seconds":60},
 "payload":{}
}))
PY
"$BIN" < "$OUT/describe-request.json" > "$OUT/provider-graph.json" 2> "$OUT/describe-stderr.txt" || {
  echo "provider describe failed; see $OUT/describe-stderr.txt" >&2; exit 2;
}
RUBRIC_SET=$(python3 - "$OUT/provider-graph.json" <<'PY'
import json,re,sys
reply=json.load(open(sys.argv[1])); graph=reply["result"]["graph"]
text=next(s for s in graph["states"] if s["id"]=="explore")["static_guidance"]["text"]
m=re.search(r"^RUBRIC SET \(intent-semantic\): ([0-9a-f]+)$",text,re.M)
if not m: raise SystemExit("frozen explore guidance lacks intent rubric identity")
print(m.group(1))
PY
) || exit 2
python3 - "$OUT/provider-graph.json" "$OUT/graph.json" <<'PY'
import json,sys
reply=json.load(open(sys.argv[1]))
json.dump(reply["result"]["graph"],open(sys.argv[2],"w"),indent=2)
PY

if [ "$#" -gt 0 ]; then CASES="$*"; else CASES=$(python3 - "$MANIFEST" <<'PY'
import json,sys
print(" ".join(c["id"] for c in json.load(open(sys.argv[1]))["cases"]))
PY
); fi
for case_id in $CASES; do
  python3 - "$MANIFEST" "$case_id" <<'PY' >/dev/null || exit 2
import json,sys
m=json.load(open(sys.argv[1])); wanted=sys.argv[2]
if not any(c["id"]==wanted for c in m["cases"]): raise SystemExit(f"unknown case: {wanted}")
PY
done

if [ "$PROFILE" = smoke ]; then
  MODES=targeted
  OBSERVATIONS_PER_CASE=1
else
  MODES="targeted all_axes"
  OBSERVATIONS_PER_CASE=4
fi

run_case() {
  case_id=$1
  case_index=$2
  case_status=0
  case_sequence=0
  CASE_JSON=$(python3 - "$MANIFEST" "$case_id" <<'PY'
import json,sys
print(json.dumps(next(c for c in json.load(open(sys.argv[1]))["cases"] if c["id"]==sys.argv[2]),separators=(",",":")))
PY
)
  lane=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["lane"])')
  fixture=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["fixture"])')
  selected_axis=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["selected_axis"])')
  challenge=""
  if [ "$lane" = challenge ]; then challenge=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["challenge"])'); fi

  for mode in $MODES; do
    if [ "$mode" = targeted ]; then
      if [ "$PROFILE" = smoke ]; then attempts=1; else attempts=3; fi
    else
      attempts=1
    fi
    attempt=1
    while [ "$attempt" -le "$attempts" ]; do
      case_sequence=$((case_sequence + 1))
      sequence=$(((case_index - 1) * OBSERVATIONS_PER_CASE + case_sequence))
      obs_root="$OUT/raw/$case_id/$mode-$attempt"
      artifact="$obs_root/artifact"; work="$obs_root/work"
      mkdir -p "$artifact" "$work"
      cp "$HERE/$fixture" "$artifact/intent.json"
      route_log="$obs_root/routes.jsonl"; : > "$route_log"
      if [ "$lane" = challenge ]; then axis_model=intent-calibration/controlled-axis-v1; command_json=$(WRAPPER="$HERE/judge_wrapper.py" python3 -c 'import json,os; print(json.dumps([os.environ["WRAPPER"]]))')
      else axis_model=$JUDGE; command_json=$REAL_COMMAND_JSON
      fi
      AXIS_MODEL="$axis_model" DECIDER="$DECIDER" COMMAND_JSON="$command_json" EXTENSIONS_JSON="$EXTENSIONS_JSON" MODE="$mode" SELECTED_AXIS="$selected_axis" TIMEOUT="$TIMEOUT" PARALLEL="$PARALLEL" python3 - "$work/.loop-workflow.toml" <<'PY'
import json,os,sys
command=json.loads(os.environ["COMMAND_JSON"]); extensions=json.loads(os.environ["EXTENSIONS_JSON"])
if not isinstance(command,list) or not command or not all(isinstance(v,str) and v for v in command): raise SystemExit("judge command JSON must be nonempty string array")
if not isinstance(extensions,list) or not all(isinstance(v,str) and v for v in extensions): raise SystemExit("extensions JSON must be string array")
lines=["schema_version = 1","","[judge]",f"model = {json.dumps(os.environ['AXIS_MODEL'])}",f"consensus_model = {json.dumps(os.environ['DECIDER'])}",f"command = {json.dumps(command)}",f"extensions = {json.dumps(extensions)}",f"timeout_seconds = {int(os.environ['TIMEOUT'])}",f"max_parallel_axes = {int(os.environ['PARALLEL'])}"]
if os.environ["MODE"]=="targeted": lines.append(f"axes = [{json.dumps(os.environ['SELECTED_AXIS'])}]")
open(sys.argv[1],"w").write("\n".join(lines)+"\n")
PY
      BIN="$BIN" ARTIFACT="$artifact" WORK="$work" CASE_ID="$case_id" MODE="$mode" ATTEMPT="$attempt" GRAPH="$OUT/graph.json" TIMEOUT="$TIMEOUT" python3 - "$obs_root/request.json" <<'PY'
import json,os,sys
graph=json.load(open(os.environ["GRAPH"]))
request={"protocol_major":1,"role":"evaluate_gates","invocation_id":f"intent-{os.environ['CASE_ID']}-{os.environ['MODE']}-{os.environ['ATTEMPT']}","registration":{"registration_id":"intent-qualification","config_revision":1,"executable":os.environ["BIN"],"argv":[],"working_directory":os.environ["WORK"],"timeout_seconds":int(os.environ["TIMEOUT"])},"payload":{"snapshot":{"current_state":"explore","inputs":{"artifact_root":os.environ["ARTIFACT"],"work_root":os.environ["WORK"]},"stored_graph":graph},"event":"intent-ready","required_gate_ids":["intent-ready","intent-semantic"],"selected_evidence":[],"inline_evidence":[]}}
json.dump(request,open(sys.argv[1],"w"),indent=2)
PY
      set +e
      if [ "$lane" = challenge ]; then
        SC_INTENT_CHALLENGE="$HERE/$challenge" SC_INTENT_MODE="$mode" SC_INTENT_ROUTE_LOG="$route_log" SC_INTENT_REAL_CONSENSUS_MODEL="$DECIDER" SC_INTENT_REAL_COMMAND_JSON="$REAL_COMMAND_JSON" "$BIN" < "$obs_root/request.json" > "$obs_root/response.json" 2> "$obs_root/stderr.txt"
      else
        "$BIN" < "$obs_root/request.json" > "$obs_root/response.json" 2> "$obs_root/stderr.txt"
      fi
      provider_exit=$?
      set -e
      python3 "$HERE/report.py" observe --manifest "$MANIFEST" --case "$case_id" --mode "$mode" --attempt "$attempt" --sequence "$sequence" --provider-exit "$provider_exit" --response "$obs_root/response.json" --stderr "$obs_root/stderr.txt" --output "$OUT/observations/$case_id/$mode-$attempt.json" --axis-model "$axis_model" --consensus-model "$DECIDER" --rubric-set "$RUBRIC_SET" --route-log "$route_log" || case_status=1
      attempt=$((attempt + 1))
      [ "$GAP" = 0 ] || sleep "$GAP"
    done
  done
  return "$case_status"
}

status=0
case_index=0
running=0
pids=""
for case_id in $CASES; do
  case_index=$((case_index + 1))
  (run_case "$case_id" "$case_index") &
  pids="$pids $!"
  running=$((running + 1))
  if [ "$running" -ge "$CASE_JOBS" ]; then
    for pid in $pids; do wait "$pid" || status=1; done
    pids=""
    running=0
  fi
done
for pid in $pids; do wait "$pid" || status=1; done

python3 "$HERE/report.py" aggregate --profile "$PROFILE" --manifest "$MANIFEST" --observations "$OUT/observations" --output "$OUT/run.json" --axis-model "$JUDGE" --consensus-model "$DECIDER" --rubric-set "$RUBRIC_SET" $CASES || status=1
[ "$status" -eq 0 ] || { echo "nonmatching evidence; inspect: python3 $HERE/report.py show --reasons $OUT/run.json" >&2; }
exit "$status"
