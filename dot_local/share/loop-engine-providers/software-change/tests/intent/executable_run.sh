#!/bin/sh
# Bounded real-model intent calibration.
# release-core: fixed 12-case cohort, three targeted observations each.
# characterization: one targeted observation per selected or complete corpus case.
set -eu

HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
MANIFEST="$HERE/manifest.json"
OUT=${SC_OUT:-"${TMPDIR:-/tmp}/sc-intent-characterization"}
GAP=${SC_GAP:-5}
JUDGE=${SC_JUDGE_MODEL:-openai-codex/gpt-5.6-sol}
DECIDER=${SC_DECIDER_MODEL:-openai-codex/gpt-5.6-sol}
TIMEOUT=${SC_TIMEOUT:-1200}
PARALLEL=${SC_MAX_PARALLEL_AXES:-1}
PROFILE=${SC_PROFILE:-characterization}
CASE_JOBS=${SC_CASE_JOBS:-1}
ATTESTATION=${SC_FIDELITY_ATTESTATION:-}
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

case "$PROFILE" in
  release-core|characterization) ;;
  *) echo "SC_PROFILE must be release-core or characterization" >&2; exit 2 ;;
esac
case "$CASE_JOBS" in
  ''|*[!0-9]*|0) echo "SC_CASE_JOBS must be a positive integer" >&2; exit 2 ;;
esac
case "$PARALLEL" in
  ''|*[!0-9]*|0) echo "SC_MAX_PARALLEL_AXES must be a positive integer" >&2; exit 2 ;;
esac
[ ! -e "$OUT" ] || {
  echo "SC_OUT already exists; calibration artifacts are immutable: $OUT" >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 2; }
if [ "$PROFILE" = release-core ]; then
  [ -n "$ATTESTATION" ] && [ -f "$ATTESTATION" ] || {
    echo "release-core requires SC_FIDELITY_ATTESTATION naming a readable file" >&2
    exit 2
  }
fi

if [ "${SC_BIN+x}" = x ]; then
  BIN=$SC_BIN
else
  BIN="$ROOT/target/debug/software-change"
  cargo build --quiet --bin software-change --manifest-path "$ROOT/Cargo.toml" || exit 2
fi
[ -x "$BIN" ] || { echo "provider binary not executable: $BIN" >&2; exit 2; }
SC_BIN="$BIN" python3 "$HERE/check_manifest.py" || exit 2
[ "$JUDGE" != "intent-calibration/controlled-axis-v1" ] || {
  echo "real axis model uses reserved controlled identity" >&2; exit 2
}
[ "$DECIDER" != "intent-calibration/controlled-axis-v1" ] || {
  echo "real consensus model uses reserved controlled identity" >&2; exit 2
}

if [ "$PROFILE" = release-core ]; then
  [ "$#" -eq 0 ] || {
    echo "release-core uses the fixed manifest cohort and does not accept case arguments" >&2
    exit 2
  }
  CASES=$(python3 - "$MANIFEST" <<'PY'
import json,sys
print(" ".join(json.load(open(sys.argv[1]))["release_core_cases"]))
PY
  )
  ATTEMPTS=3
else
  if [ "$#" -gt 0 ]; then
    CASES="$*"
  else
    CASES=$(python3 - "$MANIFEST" <<'PY'
import json,sys
print(" ".join(case["id"] for case in json.load(open(sys.argv[1]))["cases"]))
PY
    )
  fi
  ATTEMPTS=1
fi
for case_id in $CASES; do
  python3 - "$MANIFEST" "$case_id" <<'PY' >/dev/null || exit 2
import json,sys
manifest=json.load(open(sys.argv[1])); wanted=sys.argv[2]
if not any(case["id"]==wanted for case in manifest["cases"]):
    raise SystemExit(f"unknown case: {wanted}")
PY
done

mkdir -p "$OUT/observations" "$OUT/raw"
EVIDENCE_SET_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
CANDIDATE_ID=$(python3 - "$BIN" <<'PY'
import hashlib,sys
with open(sys.argv[1],"rb") as handle:
    print("sha256:"+hashlib.file_digest(handle,"sha256").hexdigest())
PY
)

BIN="$BIN" ROOT="$ROOT" python3 - <<'PY' > "$OUT/describe-request.json"
import json,os
print(json.dumps({
    "protocol_major":1,
    "role":"describe",
    "invocation_id":"intent-calibration-describe",
    "registration":{
        "registration_id":"intent-calibration",
        "config_revision":1,
        "executable":os.environ["BIN"],
        "argv":[],
        "working_directory":os.environ["ROOT"],
        "timeout_seconds":60,
    },
    "payload":{},
}))
PY
"$BIN" < "$OUT/describe-request.json" > "$OUT/provider-graph.json" 2> "$OUT/describe-stderr.txt" || {
  echo "provider describe failed; see $OUT/describe-stderr.txt" >&2
  exit 2
}
RUBRIC_SET=$(python3 - "$OUT/provider-graph.json" <<'PY'
import json,re,sys
reply=json.load(open(sys.argv[1])); graph=reply["result"]["graph"]
text=next(state for state in graph["states"] if state["id"]=="explore")["static_guidance"]["text"]
match=re.search(r"^RUBRIC SET \(intent-semantic\): ([0-9a-f]+)$",text,re.M)
if not match: raise SystemExit("frozen explore guidance lacks intent rubric identity")
print(match.group(1))
PY
) || exit 2
python3 - "$OUT/provider-graph.json" "$OUT/graph.json" <<'PY'
import json,sys
reply=json.load(open(sys.argv[1])); json.dump(reply["result"]["graph"],open(sys.argv[2],"w"),indent=2)
PY
EVIDENCE_SET_ID="$EVIDENCE_SET_ID" CANDIDATE_ID="$CANDIDATE_ID" RUBRIC_SET="$RUBRIC_SET" PROFILE="$PROFILE" python3 - <<'PY' > "$OUT/evidence-set.json"
import json,os
print(json.dumps({
    "schema_version":1,
    "profile":os.environ["PROFILE"],
    "evidence_set_id":os.environ["EVIDENCE_SET_ID"],
    "candidate_id":os.environ["CANDIDATE_ID"],
    "rubric_set":os.environ["RUBRIC_SET"],
},indent=2))
PY

run_case() {
  case_id=$1
  case_index=$2
  case_status=0
  CASE_JSON=$(python3 - "$MANIFEST" "$case_id" <<'PY'
import json,sys
print(json.dumps(next(case for case in json.load(open(sys.argv[1]))["cases"] if case["id"]==sys.argv[2]),separators=(",",":")))
PY
  )
  lane=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["lane"])')
  fixture=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["fixture"])')
  selected_axis=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["selected_axis"])')
  challenge=""
  if [ "$lane" = challenge ]; then
    challenge=$(CASE_JSON="$CASE_JSON" python3 -c 'import json,os; print(json.loads(os.environ["CASE_JSON"])["challenge"])')
  fi

  attempt=1
  while [ "$attempt" -le "$ATTEMPTS" ]; do
    sequence=$(((case_index - 1) * ATTEMPTS + attempt))
    obs_root="$OUT/raw/$case_id/targeted-$attempt"
    artifact="$obs_root/artifact"
    work="$obs_root/work"
    mkdir -p "$artifact" "$work"
    cp "$HERE/$fixture" "$artifact/intent.json"
    route_log="$obs_root/routes.jsonl"
    : > "$route_log"
    if [ "$lane" = challenge ]; then
      axis_model=intent-calibration/controlled-axis-v1
      command_json=$(WRAPPER="$HERE/judge_wrapper.py" python3 -c 'import json,os; print(json.dumps([os.environ["WRAPPER"]]))')
    else
      axis_model=$JUDGE
      command_json=$REAL_COMMAND_JSON
    fi
    AXIS_MODEL="$axis_model" DECIDER="$DECIDER" COMMAND_JSON="$command_json" EXTENSIONS_JSON="$EXTENSIONS_JSON" SELECTED_AXIS="$selected_axis" TIMEOUT="$TIMEOUT" PARALLEL="$PARALLEL" python3 - "$work/.loop-workflow.toml" <<'PY'
import json,os,sys
command=json.loads(os.environ["COMMAND_JSON"]); extensions=json.loads(os.environ["EXTENSIONS_JSON"])
if not isinstance(command,list) or not command or not all(isinstance(value,str) and value for value in command):
    raise SystemExit("judge command JSON must be nonempty string array")
if not isinstance(extensions,list) or not all(isinstance(value,str) and value for value in extensions):
    raise SystemExit("extensions JSON must be string array")
lines=[
    "schema_version = 1", "", "[judge]",
    f"model = {json.dumps(os.environ['AXIS_MODEL'])}",
    f"consensus_model = {json.dumps(os.environ['DECIDER'])}",
    f"command = {json.dumps(command)}",
    f"extensions = {json.dumps(extensions)}",
    f"timeout_seconds = {int(os.environ['TIMEOUT'])}",
    f"max_parallel_axes = {int(os.environ['PARALLEL'])}",
    f"axes = [{json.dumps(os.environ['SELECTED_AXIS'])}]",
]
open(sys.argv[1],"w").write("\n".join(lines)+"\n")
PY
    BIN="$BIN" ARTIFACT="$artifact" WORK="$work" CASE_ID="$case_id" ATTEMPT="$attempt" GRAPH="$OUT/graph.json" TIMEOUT="$TIMEOUT" python3 - "$obs_root/request.json" <<'PY'
import json,os,sys
graph=json.load(open(os.environ["GRAPH"]))
request={
    "protocol_major":1,
    "role":"evaluate_gates",
    "invocation_id":f"intent-{os.environ['CASE_ID']}-targeted-{os.environ['ATTEMPT']}",
    "registration":{
        "registration_id":"intent-calibration",
        "config_revision":1,
        "executable":os.environ["BIN"],
        "argv":[],
        "working_directory":os.environ["WORK"],
        "timeout_seconds":int(os.environ["TIMEOUT"]),
    },
    "payload":{
        "snapshot":{
            "current_state":"explore",
            "inputs":{"artifact_root":os.environ["ARTIFACT"],"work_root":os.environ["WORK"]},
            "stored_graph":graph,
        },
        "event":"intent-ready",
        "required_gate_ids":["intent-ready","intent-semantic"],
        "selected_evidence":[],
        "inline_evidence":[],
    },
}
json.dump(request,open(sys.argv[1],"w"),indent=2)
PY
    set +e
    if [ "$lane" = challenge ]; then
      SC_INTENT_CHALLENGE="$HERE/$challenge" SC_INTENT_MODE=targeted SC_INTENT_ROUTE_LOG="$route_log" SC_INTENT_REAL_CONSENSUS_MODEL="$DECIDER" SC_INTENT_REAL_COMMAND_JSON="$REAL_COMMAND_JSON" "$BIN" < "$obs_root/request.json" > "$obs_root/response.json" 2> "$obs_root/stderr.txt"
    else
      "$BIN" < "$obs_root/request.json" > "$obs_root/response.json" 2> "$obs_root/stderr.txt"
    fi
    provider_exit=$?
    set -e
    if ! python3 "$HERE/report.py" observe \
      --manifest "$MANIFEST" --case "$case_id" --mode targeted --attempt "$attempt" \
      --sequence "$sequence" --provider-exit "$provider_exit" \
      --response "$obs_root/response.json" --stderr "$obs_root/stderr.txt" \
      --output "$OUT/observations/$case_id/targeted-$attempt.json" \
      --axis-model "$axis_model" --consensus-model "$DECIDER" --rubric-set "$RUBRIC_SET" \
      --evidence-set-id "$EVIDENCE_SET_ID" --candidate-id "$CANDIDATE_ID" \
      --route-log "$route_log"
    then
      # Mismatch and indeterminate observations are retained evidence. Aggregation
      # decides whether the complete set qualifies.
      [ -s "$OUT/observations/$case_id/targeted-$attempt.json" ] || case_status=1
    fi
    attempt=$((attempt + 1))
    [ "$GAP" = 0 ] || sleep "$GAP"
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

set +e
if [ "$PROFILE" = release-core ]; then
  python3 "$HERE/report.py" aggregate \
    --profile "$PROFILE" --manifest "$MANIFEST" --observations "$OUT/observations" \
    --output "$OUT/run.json" --axis-model "$JUDGE" --consensus-model "$DECIDER" \
    --rubric-set "$RUBRIC_SET" --evidence-set-id "$EVIDENCE_SET_ID" \
    --candidate-id "$CANDIDATE_ID" --attestation "$ATTESTATION"
else
  python3 "$HERE/report.py" aggregate \
    --profile "$PROFILE" --manifest "$MANIFEST" --observations "$OUT/observations" \
    --output "$OUT/run.json" --axis-model "$JUDGE" --consensus-model "$DECIDER" \
    --rubric-set "$RUBRIC_SET" --evidence-set-id "$EVIDENCE_SET_ID" \
    --candidate-id "$CANDIDATE_ID" $CASES
fi
aggregate_status=$?
set -e
[ "$status" -eq 0 ] || aggregate_status=1
if [ "$aggregate_status" -ne 0 ]; then
  echo "calibration incomplete or nonqualifying; inspect: python3 $HERE/report.py show --reasons $OUT/run.json" >&2
fi
exit "$aggregate_status"
