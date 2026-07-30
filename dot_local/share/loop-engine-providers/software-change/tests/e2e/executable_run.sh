#!/usr/bin/env bash
#
# End-to-end coverage of the workflow's DETERMINISTIC surface, driven through
# the production `loop-engine` CLI against the installed provider binary.
#
# What this is for. Every gate module has unit tests, and `tests/design/`
# measures one semantic gate against real models. Neither touches the vertical
# that carries an actual run: the engine accepting the graph, resolving a
# transition, invoking the provider over stdio, applying its verdicts, moving
# state, and recording evidence. That vertical was verified by hand, which is
# how the graph came to describe moves the guidance promised and the engine
# refused.
#
# The judge is a script. Semantic gates are non-deterministic by construction,
# so an end-to-end suite cannot assert their verdicts and must not try --
# `tests/design/` is where judgment is measured. Here the judge is replaced by
# a scripted one so a full lifecycle costs milliseconds instead of six minutes
# of model calls, and so the surface that IS deterministic can be asserted
# exactly. That also buys something no real judge can: an exact count of judge
# invocations, which is the only way to prove judgment was withheld rather than
# spent and discarded.
#
#   ./run.sh                  every scenario
#   ./run.sh back_edge        named scenarios only
#   ./run.sh --list           scenario names
#
# Exit status is 0 only when every scenario passed.

set -u -o pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BIN=${SC_BIN:-"$HOME/.local/share/loop-engine-providers/bin/software-change"}
ENGINE=${SC_ENGINE:-loop-engine}
OUT=${SC_OUT:-"${TMPDIR:-/tmp}/sc-e2e"}

# --------------------------------------------------------------- preflight

command -v "$ENGINE" >/dev/null 2>&1 || {
    echo "SKIP: $ENGINE is not on PATH; this suite drives the production CLI" >&2
    exit 0
}
[ -x "$BIN" ] || {
    echo "FAIL: provider binary not found at $BIN" >&2
    echo "      build and deploy it first, or set SC_BIN" >&2
    exit 1
}
command -v git >/dev/null 2>&1 || { echo "FAIL: git is required" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"
export LOOP_ENGINE_HOME="$OUT/engine"
mkdir -p "$LOOP_ENGINE_HOME"

JUDGE_DIR="$OUT/judge"
mkdir -p "$JUDGE_DIR"
JUDGE_CALLS="$JUDGE_DIR/calls"
JUDGE_VERDICT="$JUDGE_DIR/verdict"
echo pass > "$JUDGE_VERDICT"
: > "$JUDGE_CALLS"

# A judge that ignores every flag, records that it was called, and answers with
# whatever the control file currently says. The provider passes the material as
# the final argument; nothing here reads it, because reading it would be
# pretending to judge.
cat > "$JUDGE_DIR/judge.sh" <<JUDGE
#!/bin/sh
echo call >> "$JUDGE_CALLS"
verdict=\$(cat "$JUDGE_VERDICT")
if [ "\$verdict" = "fail" ]; then
    printf '%s\n' '{"verdict":"fail","reason":"scripted refusal from the e2e judge"}'
else
    printf '%s\n' '{"verdict":"pass","reason":"scripted acceptance from the e2e judge"}'
fi
JUDGE
chmod +x "$JUDGE_DIR/judge.sh"

# --------------------------------------------------------------- assertions

FAILURES=0
SCENARIO=""
STEP_OUT=""

note() { printf '    %s\n' "$*"; }

fail() {
    printf '  \033[31mFAIL\033[0m %s: %s\n' "$SCENARIO" "$*"
    if [ -n "$STEP_OUT" ]; then
        printf '%s\n' "$STEP_OUT" | sed 's/^/      | /'
    fi
    FAILURES=$((FAILURES + 1))
    return 1
}

# Run one CLI command, keeping its output for assertions and failure reports.
engine() {
    STEP_OUT=$("$ENGINE" "$@" 2>&1)
    return 0
}

expect_contains() {
    case "$STEP_OUT" in
        *"$1"*) return 0 ;;
        *) fail "expected output to contain: $1" ;;
    esac
}

expect_missing() {
    case "$STEP_OUT" in
        *"$1"*) fail "expected output NOT to contain: $1" ;;
        *) return 0 ;;
    esac
}

expect_state()   { expect_contains "State: $1"; }
expect_ok()      { expect_contains "Outcome: completed"; }
expect_refused() { expect_contains "Outcome: rejected"; }

# The graph the engine actually stored for this run, as JSON on disk. The human
# renderer prints only the graph digest, and the digest is not what needs
# asserting -- the topology is.
GRAPH_JSON=""
stored_graph() {
    local dir="$OUT/exports/$SCENARIO"
    rm -rf "$dir"
    mkdir -p "$OUT/exports"
    "$ENGINE" run export "$1" --output "$dir" >/dev/null 2>&1 || {
        fail "could not export the run"
        return 1
    }
    GRAPH_JSON="$dir/state.json"
}

judge_reset() { : > "$JUDGE_CALLS"; }
judge_count() { wc -l < "$JUDGE_CALLS" | tr -d ' '; }
judge_says()  { echo "$1" > "$JUDGE_VERDICT"; }

expect_judge_calls() {
    local want=$1 got
    got=$(judge_count)
    [ "$got" = "$want" ] || fail "expected $want judge invocation(s), saw $got"
}

expect_judge_calls_at_least() {
    local want=$1 got
    got=$(judge_count)
    [ "$got" -ge "$want" ] || fail "expected at least $want judge invocation(s), saw $got"
}

# --------------------------------------------------------------- fixtures

# One coherent document set. The intent's acceptance lines are cited verbatim by
# the design's coverage, and the design's elements verbatim by the plan's
# `covers`, because both are checked for exact set equality. Two phases, so the
# phase loop has something to iterate and batching has something to skip.
ACCEPT_A='A run in which at least one record fails exits with a non-zero status'
ACCEPT_B='A run in which every record succeeds exits with status zero'
ELEMENT_A='A per-run failure tally owned by the import session'
ELEMENT_B='An exit-status mapping applied once at process end'

seed_intent() {
    local root=$1 revision=${2:-1} extra=${3:-}
    cat > "$root/intent.json" <<JSON
{
  "revision": "$revision",
  "problem": "A caller running the batch importer from a shell script cannot tell a partially failed run from a wholly successful one. Per-record errors go to stderr and the process exits zero regardless, so the calling script continues as though every record landed.",
  "outcome": "A caller that can only see the process exit status can tell whether every record was imported.",
  "acceptance": ["$ACCEPT_A", "$ACCEPT_B"$extra],
  "non_goals": ["Retrying or repairing failed records", "Changing which records are considered valid"],
  "constraints": ["Existing callers that check only for a zero exit keep working when nothing fails"]
}
JSON
}

seed_design() {
    local root=$1 revision=${2:-1} intent_revision=${3:-1}
    cat > "$root/design.json" <<JSON
{
  "revision": "$revision",
  "intent_revision": "$intent_revision",
  "approach": "The import session gains a failure tally that every record outcome reports into, and the process exit status is derived from that tally once, at the end, rather than from the last operation performed.",
  "elements": ["$ELEMENT_A", "$ELEMENT_B"],
  "decisions": [
    {
      "decision": "The tally lives on the import session rather than in a module-level counter",
      "rationale": "Two imports in one process would share a module-level counter and report each other's failures.",
      "rejected": ["A module-level counter", "Threading a boolean through every record call"]
    }
  ],
  "coverage": [
    { "acceptance": "$ACCEPT_A", "delivered_by": "$ELEMENT_B, reading the tally described by $ELEMENT_A" },
    { "acceptance": "$ACCEPT_B", "delivered_by": "$ELEMENT_B, which yields zero when the tally is empty" }
  ],
  "risks": ["A record path that fails without reporting into the tally would be counted as a success"]
}
JSON
}

# `phase_two_goal` lets a scenario revise the plan in a phase that has NOT been
# claimed, which is the legitimate case; `phase_one_id` lets one rename a phase
# that HAS been claimed, which is the case the prefix rule must refuse.
seed_plan() {
    local root=$1 revision=${2:-1} subject_revision=${3:-1}
    local phase_one_id=${4:-P1} phase_two_goal=${5:-Derive the exit status from the tally}
    cat > "$root/plan.json" <<JSON
{
  "revision": "$revision",
  "subject_revision": "$subject_revision",
  "phases": [
    {
      "id": "$phase_one_id",
      "goal": "Give the import session a failure tally that record outcomes report into",
      "covers": ["$ELEMENT_A"],
      "tasks": [
        {
          "id": "T1",
          "title": "Add the failure tally to the import session",
          "depends_on": [],
          "delivers": "An import session that counts the record outcomes reported as failures",
          "context": ["The session object is the only thing that spans a whole import, so it is where a per-run count can live without two imports in one process sharing it."],
          "done_when": ["Every record outcome path reports into the tally"]
        }
      ],
      "checkpoint": { "commands": [ { "name": "unit", "run": ["true"] } ] }
    },
    {
      "id": "P2",
      "goal": "$phase_two_goal",
      "covers": ["$ELEMENT_B"],
      "tasks": [
        {
          "id": "T2",
          "title": "Map the tally onto the process exit status",
          "depends_on": ["T1"],
          "delivers": "A process that exits non-zero when the tally is non-empty",
          "context": ["The mapping happens once at process end so that a later successful record cannot overwrite an earlier failure's status."],
          "done_when": ["A run with a failed record exits non-zero and a clean run exits zero"]
        }
      ],
      "checkpoint": { "commands": [ { "name": "unit", "run": ["true"] } ] }
    }
  ]
}
JSON
}

seed_cursor() {
    local root=$1 revision=${2:-1} plan_revision=${3:-1} phases=${4:-[]}
    cat > "$root/implementation.json" <<JSON
{ "revision": "$revision", "plan_revision": "$plan_revision",
  "base_commit": "$(cd "$WORK" && git rev-parse HEAD)", "phases": $phases }
JSON
}

seed_review() {
    local root=$1 revision=${2:-1} subject_revision=${3:-1} verdict=${4:-approved}
    mkdir -p "$root/reviews"
    cat > "$root/reviews/implementation-review.json" <<JSON
{ "revision": "$revision", "subject_revision": "$subject_revision",
  "subject_commit": "$(cd "$WORK" && git rev-parse HEAD)", "verdict": "$verdict" }
JSON
}

# A fresh workspace and run. Sets ART, WORK and RUN for the scenario.
new_run() {
    local name=$1
    ART="$OUT/$name/artifacts"
    WORK="$OUT/$name/work"
    mkdir -p "$ART" "$WORK"
    (
        cd "$WORK" || exit 1
        git init -q .
        git config user.email e2e@example.invalid
        git config user.name "e2e"
        echo "seed" > seed.txt
        git add seed.txt
        git commit -q -m "base"
    ) || { fail "could not create the workspace repository"; return 1; }

    cat > "$WORK/.loop-workflow.toml" <<TOML
[judge]
model = "e2e/scripted"
command = ["$JUDGE_DIR/judge.sh"]
timeout_seconds = 60
max_parallel_axes = 3
TOML

    printf '{"artifact_root":"%s","work_root":"%s"}' "$ART" "$WORK" > "$OUT/$name/inputs.json"
    STEP_OUT=$("$ENGINE" run create software-change --inputs "$OUT/$name/inputs.json" 2>&1)
    case "$STEP_OUT" in
        *"State: explore"*) ;;
        *) fail "run create did not land in explore"; return 1 ;;
    esac
    # Taken from this run's own creation output. `run list` would report every
    # run the suite has made, and picking one out of that list by position is
    # how a scenario ends up asserting against its neighbour.
    RUN=$(printf '%s\n' "$STEP_OUT" | awk '/^Run: / { print $2; exit }')
    [ -n "$RUN" ] || { fail "could not resolve the created run id"; return 1; }
    judge_reset
}

# Drive the run from `explore` to the named state with a coherent document set.
advance_to() {
    local target=$1
    seed_intent "$ART"
    engine run request "$RUN" intent-ready && expect_state design || return 1
    [ "$target" = design ] && return 0

    seed_design "$ART"
    engine run request "$RUN" design-ready && expect_state plan || return 1
    [ "$target" = plan ] && return 0

    seed_plan "$ART"
    engine run request "$RUN" plan-ready && expect_state implement || return 1
    [ "$target" = implement ] && return 0

    fail "advance_to does not know how to reach $target"
    return 1
}

# --------------------------------------------------------------- scenarios

# The graph itself has to survive the engine's semantic validation. Nine unit
# tests assert the shape of the Rust constant; only this asserts that the engine
# accepts it -- including the two properties the revision edges depend on, which
# no unit test can reach: empty `gate_ids`, and one event id reused from several
# source states.
scenario_graph() {
    new_run graph || return 1
    stored_graph "$RUN" || return 1
    STEP_OUT=$(python3 "$HERE/inspect_graph.py" edges "$GRAPH_JSON")

    expect_contains "transitions 13" || return 1
    expect_contains "gateless 6" || return 1

    # The six revision edges, each gate-free, and one event id reused from three
    # source states. Both are properties only the engine can confirm it accepts;
    # a unit test reads the Rust array and learns nothing about either.
    expect_contains "edge design revise-intent explore -" || return 1
    expect_contains "edge plan revise-intent explore -" || return 1
    expect_contains "edge plan revise-design design -" || return 1
    expect_contains "edge implement revise-intent explore -" || return 1
    expect_contains "edge implement revise-design design -" || return 1
    expect_contains "edge implement revise-plan plan -" || return 1

    # The forward path is still double-gated where it should be.
    expect_contains "edge explore intent-ready design intent-ready,intent-semantic" || return 1
    expect_contains "edge implement implementation-ready implementation-review implementation-ready"
}

# The forward path, end to end, with every gate passing. If this breaks, the
# workflow does not work at all.
scenario_happy_path() {
    new_run happy || return 1
    advance_to implement || return 1

    seed_cursor "$ART" 1 1 '[{"id":"P1"}]'
    engine run request "$RUN" phase-complete
    expect_ok && expect_state implement || return 1

    seed_cursor "$ART" 2 1 '[{"id":"P1"},{"id":"P2"}]'
    engine run request "$RUN" phase-complete
    expect_ok && expect_state implement || return 1

    engine run request "$RUN" implementation-ready
    expect_ok && expect_state implementation-review || return 1

    seed_review "$ART" 1 2 approved
    engine run request "$RUN" approved
    expect_ok && expect_state end || return 1
}

# A rejection must leave the run exactly where it was, with the same event still
# requestable. A gate that moved the run on refusal would strand it.
scenario_rejection_preserves_state() {
    new_run refuse || return 1
    seed_intent "$ART"
    printf '{"revision":"1"}' > "$ART/intent.json"
    engine run request "$RUN" intent-ready
    expect_refused && expect_state "explore (unchanged)" || return 1
    expect_contains "intent-ready"
}

# Unknown events, and events that exist elsewhere in the graph but not here.
scenario_illegal_events() {
    new_run illegal || return 1
    engine run request "$RUN" not-a-real-event
    expect_refused && expect_state "explore (unchanged)" || return 1

    # `revise-intent` is declared -- from three other states, never from explore.
    engine run request "$RUN" revise-intent
    expect_refused && expect_state "explore (unchanged)" || return 1

    # `design-ready` is legal in `design`, not here.
    engine run request "$RUN" design-ready
    expect_refused && expect_state "explore (unchanged)" || return 1
}

# `end` is final, so it declares no exit. An engine that accepted one would have
# rejected the graph, but the run-level behaviour is worth pinning too.
scenario_final_state_is_terminal() {
    new_run final || return 1
    advance_to implement || return 1
    seed_cursor "$ART" 1 1 '[{"id":"P1"}]'
    engine run request "$RUN" phase-complete || return 1
    seed_cursor "$ART" 2 1 '[{"id":"P1"},{"id":"P2"}]'
    engine run request "$RUN" phase-complete || return 1
    engine run request "$RUN" implementation-ready || return 1
    seed_review "$ART" 1 2 approved
    engine run request "$RUN" approved
    expect_state end || return 1

    engine run show "$RUN"
    expect_missing "revise-intent" || return 1
    engine run request "$RUN" revise-intent
    expect_refused
}

# The revision edges. Each must be requestable from its source, move the run
# without evaluating anything, and spawn no judge -- an ungated edge that
# invoked the provider would be paying for a move that decides nothing.
scenario_back_edge() {
    new_run backedge || return 1
    advance_to plan || return 1

    engine run show "$RUN"
    expect_contains "revise-intent" || return 1
    expect_contains "revise-design" || return 1

    judge_reset
    engine run request "$RUN" revise-design
    expect_ok && expect_state design || return 1
    expect_judge_calls 0 || return 1

    engine run request "$RUN" revise-intent
    expect_ok && expect_state explore || return 1
    expect_judge_calls 0 || return 1

    # And from `implement`, where all three are available.
    new_run backedge_implement || return 1
    advance_to implement || return 1
    judge_reset
    engine run request "$RUN" revise-plan
    expect_ok && expect_state plan || return 1
    engine run request "$RUN" revise-intent
    expect_ok && expect_state explore || return 1
    expect_judge_calls 0
}

# The whole point of the revision edges: revise upstream, and everything below
# is refused until it is re-pointed. This is the cascade the guidance promises.
scenario_cascade() {
    new_run cascade || return 1
    advance_to plan || return 1

    engine run request "$RUN" revise-intent
    expect_state explore || return 1

    # A revised intent is judged again -- it is not carried forward on the
    # strength of the judgment its predecessor earned.
    seed_intent "$ART" 2 ', "A partially failed run names the failing records on stderr"'
    judge_reset
    engine run request "$RUN" intent-ready
    expect_ok && expect_state design || return 1
    expect_judge_calls_at_least 2 || return 1

    # The design still names revision 1 and must now be refused.
    engine run request "$RUN" design-ready
    expect_refused && expect_state "design (unchanged)" || return 1

    engine run evidence list "$RUN"
    expect_contains "diagnosis" || return 1

    # Re-point it -- and the coverage must cite the new acceptance line, so a
    # re-point that only changes the revision number does not survive either.
    seed_design "$ART" 2 2
    engine run request "$RUN" design-ready
    expect_refused || return 1

    python3 - "$ART" <<'PY'
import json, sys
root = sys.argv[1]
intent = json.load(open(f"{root}/intent.json"))
design = json.load(open(f"{root}/design.json"))
covered = {entry["acceptance"] for entry in design["coverage"]}
for line in intent["acceptance"]:
    if line not in covered:
        design["coverage"].append({"acceptance": line, "delivered_by": design["elements"][0]})
json.dump(design, open(f"{root}/design.json", "w"), indent=2)
PY
    engine run request "$RUN" design-ready
    expect_ok && expect_state plan || return 1

    # The plan is now stale in turn.
    engine run request "$RUN" plan-ready
    expect_refused && expect_state "plan (unchanged)"
}

# Judgment is withheld, never bought, on a transition that has already failed
# deterministically. Only a call count can prove this: the verdict alone cannot
# distinguish a judgment that was skipped from one that was made and discarded.
scenario_withheld_judgment() {
    new_run withheld || return 1
    seed_intent "$ART"
    advance_to design || return 1

    # A design that fails the schema. The semantic gate on this transition must
    # return a failure without spending a single call.
    printf '{"revision":"1","intent_revision":"1"}' > "$ART/design.json"
    judge_reset
    engine run request "$RUN" design-ready
    expect_refused && expect_state "design (unchanged)" || return 1
    expect_judge_calls 0 || return 1

    # With the schema satisfied, the judges do run -- proving the zero above was
    # the short circuit and not a broken judge command.
    seed_design "$ART"
    judge_reset
    engine run request "$RUN" design-ready
    expect_ok || return 1
    expect_judge_calls_at_least 2
}

# A refused judgment is stored and replayed, and the only thing that earns a
# fresh one is a change a judge could actually see. This is the anti-resample
# property: without it, a rejected document is one retry away from a different
# mood.
scenario_judge_refusal() {
    new_run refusal || return 1
    seed_intent "$ART"
    judge_says fail
    engine run request "$RUN" intent-ready
    expect_refused && expect_state "explore (unchanged)" || return 1

    # Same document, judge now willing to pass. The stored refusal replays and
    # no judge is spawned, so rerolling a rejection is not available.
    judge_says pass
    judge_reset
    engine run request "$RUN" intent-ready
    expect_refused || return 1
    expect_judge_calls 0 || return 1

    # Raising `revision` alone must not buy a resample either. Nothing in any
    # rubric reads that field, so it is stripped from the cache key on purpose
    # -- otherwise it would be a one-character retry button.
    seed_intent "$ART" 2
    judge_reset
    engine run request "$RUN" intent-ready
    expect_refused || return 1
    expect_judge_calls 0 || return 1

    # An edit a judge could see is a different subject, and is judged afresh.
    seed_intent "$ART" 3 ', "A partially failed run names the failing records on stderr"'
    judge_reset
    engine run request "$RUN" intent-ready
    expect_ok && expect_state design || return 1
    expect_judge_calls_at_least 2
}

# `revise-plan` is the one edge that touches the phase cursor, because the
# cursor names the plan revision it descends from.
scenario_cursor_repoint() {
    new_run cursor || return 1
    advance_to implement || return 1
    seed_cursor "$ART" 1 1 '[{"id":"P1"}]'
    engine run request "$RUN" phase-complete
    expect_ok || return 1

    engine run request "$RUN" revise-plan
    expect_state plan || return 1

    # Revise a phase that has NOT been claimed: legitimate.
    seed_plan "$ART" 2 1 P1 "Derive the exit status from the tally, once, at process end"
    engine run request "$RUN" plan-ready
    expect_ok && expect_state implement || return 1

    # The cursor still names plan revision 1 and is refused.
    engine run request "$RUN" phase-complete
    expect_refused && expect_state "implement (unchanged)" || return 1

    # Re-pointed -- revision raised, plan_revision updated, phases untouched.
    seed_cursor "$ART" 2 2 '[{"id":"P1"},{"id":"P2"}]'
    engine run request "$RUN" phase-complete
    expect_ok && expect_state implement
}

# The prefix rule is what stops a plan revision rewriting history: a phase that
# has been verified cannot be changed underneath its verification.
scenario_cursor_prefix_violation() {
    new_run prefix || return 1
    advance_to implement || return 1
    seed_cursor "$ART" 1 1 '[{"id":"P1"}]'
    engine run request "$RUN" phase-complete
    expect_ok || return 1

    engine run request "$RUN" revise-plan
    expect_state plan || return 1

    # Rename the phase the cursor has already claimed.
    seed_plan "$ART" 2 1 P0
    engine run request "$RUN" plan-ready
    expect_ok && expect_state implement || return 1

    seed_cursor "$ART" 2 2 '[{"id":"P1"},{"id":"P0"}]'
    engine run request "$RUN" phase-complete
    expect_refused && expect_state "implement (unchanged)" || return 1
    engine run evidence list "$RUN"
    expect_contains "diagnosis"
}

# Live guidance is the only surface that can tell a first visit from a return,
# and it derives that from the documents on disk rather than from run history.
scenario_live_guidance() {
    new_run guidance || return 1

    engine run guidance "$RUN"
    expect_contains "WHERE THIS RUN STANDS" || return 1
    expect_contains "first pass" || return 1

    advance_to plan || return 1
    engine run request "$RUN" revise-intent
    expect_state explore || return 1

    engine run guidance "$RUN"
    expect_contains "You are revising" || return 1
    expect_contains "design.json" || return 1
    expect_contains "in agreement" || return 1

    python3 - "$ART" <<'PY'
import json, sys
path = f"{sys.argv[1]}/intent.json"
document = json.load(open(path))
document["revision"] = "9"
json.dump(document, open(path, "w"), indent=2)
PY
    engine run guidance "$RUN"
    expect_contains "ALREADY STALE"
}

# Static guidance must not name a move the engine will refuse. A unit test
# checks this against the Rust table; this checks it against what the engine
# actually stored and actually accepts.
scenario_guidance_names_only_real_events() {
    new_run vocabulary || return 1
    stored_graph "$RUN" || return 1
    STEP_OUT=$(python3 "$HERE/inspect_graph.py" vocabulary "$GRAPH_JSON")
    expect_missing "UNDECLARED" || return 1
    expect_contains "vocabulary checked"
}

# The documented limit, pinned so it cannot regress silently into something
# worse and cannot be quietly fixed without updating what the guidance claims.
scenario_batching_skips_a_phase() {
    new_run batching || return 1
    advance_to implement || return 1

    # Two phases claimed at once. Only the last is verified, and P1's checkpoint
    # never runs. The guidance warns about exactly this; the suite records that
    # the warning is still true.
    seed_cursor "$ART" 1 1 '[{"id":"P1"},{"id":"P2"}]'
    engine run request "$RUN" phase-complete
    expect_ok && expect_state implement || return 1

    engine run request "$RUN" implementation-ready
    expect_ok && expect_state implementation-review || return 1
    note "known limit: P1 was never verified and implementation-ready accepted the run anyway"
}

# --------------------------------------------------------------- runner

SCENARIOS=(
    graph
    happy_path
    rejection_preserves_state
    illegal_events
    final_state_is_terminal
    back_edge
    cascade
    withheld_judgment
    judge_refusal
    cursor_repoint
    cursor_prefix_violation
    live_guidance
    guidance_names_only_real_events
    batching_skips_a_phase
)

if [ "${1:-}" = "--list" ]; then
    printf '%s\n' "${SCENARIOS[@]}"
    exit 0
fi

STEP_OUT=$("$ENGINE" provider add software-change \
    --exec "$BIN" --working-directory "$OUT" --timeout 300 2>&1)
case "$STEP_OUT" in
    *"Handle: software-change"*) ;;
    *) printf '%s\n' "$STEP_OUT"; echo "FAIL: could not register the provider" >&2; exit 1 ;;
esac

SELECTED=("$@")
[ ${#SELECTED[@]} -eq 0 ] && SELECTED=("${SCENARIOS[@]}")

echo "provider: $BIN"
echo "engine home: $LOOP_ENGINE_HOME"
echo

for name in "${SELECTED[@]}"; do
    SCENARIO="$name"
    STEP_OUT=""
    before=$FAILURES
    if ! declare -F "scenario_$name" >/dev/null; then
        printf '  \033[31mFAIL\033[0m %s: no such scenario\n' "$name"
        FAILURES=$((FAILURES + 1))
        continue
    fi
    "scenario_$name"
    if [ "$FAILURES" = "$before" ]; then
        printf '  \033[32mok\033[0m   %s\n' "$name"
    fi
done

echo
if [ "$FAILURES" = 0 ]; then
    echo "all ${#SELECTED[@]} scenario(s) passed"
    exit 0
fi
echo "$FAILURES assertion(s) failed; artifacts under $OUT"
exit 1
