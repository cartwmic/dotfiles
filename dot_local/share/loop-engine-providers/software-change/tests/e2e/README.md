# End-to-end suite

Black-box coverage of the workflow's **deterministic surface**, driven through
the production `loop-engine` CLI against the installed provider binary.

    ./run.sh                  every scenario  (~26s)
    ./run.sh back_edge graph  named scenarios only
    ./run.sh --list           scenario names

Exit status is 0 only when every scenario passed. Artifacts stay under `$SC_OUT`
(default `$TMPDIR/sc-e2e`) so a failure can be read afterwards: each scenario has
its own `artifacts/` and `work/`, and the engine home holds the traces.

`SC_BIN` overrides the provider under test, which is how a mutant build gets
measured. `SC_ENGINE` overrides the CLI. The suite skips, rather than fails, when
`loop-engine` is not on PATH.

## Why this exists separately from the unit tests

Every gate module has unit tests, and they are the right place for gate logic.
What they cannot reach is the vertical that carries an actual run: the engine
validating and freezing the graph, resolving a transition, invoking the provider
over stdio, applying its verdicts, moving state, and recording evidence.

That vertical had no automated coverage at all. It is how the graph came to
describe moves the guidance promised and the engine refused — a defect that
needed three blind model reviews to surface, and that any one of these scenarios
would have caught on the first run.

Two properties in particular are invisible from inside the crate, and the whole
revision-edge design rests on both:

- the engine accepts a transition with an **empty gate list**
- the engine accepts **one event id declared from several source states**

A unit test reads the Rust array and learns nothing about either.

## The judge is a script

Semantic gates are non-deterministic by construction — identical input has been
measured passing one sample and failing the next. An end-to-end suite cannot
assert their verdicts and must not try; `tests/design/` is where judgment is
measured, against real models, per rubric change.

Here `[judge].command` points at a shell script that records the call and answers
from a control file. A full lifecycle costs milliseconds instead of six minutes
of model calls, the deterministic surface can be asserted exactly, and one thing
becomes available that no real judge can offer: an **exact count of judge
invocations**. That count is the only way to prove judgment was *withheld*
rather than spent and discarded, because the verdict alone cannot tell the two
apart.

Worth naming: the configurability of `[judge].command` is a finding in its own
right — an author who controls it controls the judge. Whatever eventually
constrains it has to leave this seam open, or it removes the suite along with the
hole.

## Scenarios

| Scenario | What it pins |
|---|---|
| `graph` | The engine accepts the stored projection: 13 transitions, 6 gate-free, every revision edge present, forward path still double-gated |
| `happy_path` | `explore` → `end` with every gate passing |
| `rejection_preserves_state` | A refusal leaves the run in place with the same event still requestable |
| `illegal_events` | Unknown events, and events declared elsewhere but not here, are refused |
| `final_state_is_terminal` | `end` offers no exit |
| `back_edge` | Every revision edge moves the run, spawns no judge, and is available from each of its sources |
| `cascade` | Revise upstream → every downstream document refused → re-point → forward again |
| `withheld_judgment` | A deterministic failure spends **zero** judge calls; the same transition with a valid document does spend them |
| `judge_refusal` | A stored refusal replays; raising `revision` alone does not resample; a real content edit is judged afresh |
| `cursor_repoint` | After `revise-plan` the cursor is stale, then resumes once re-pointed |
| `cursor_prefix_violation` | A plan revision that touches an already-claimed phase is refused |
| `live_guidance` | Cold arrival, return with downstream documents, and an already-stale link |
| `guidance_names_only_real_events` | Every event-shaped token in the published guidance is an event or gate the **stored** graph declares |
| `batching_skips_a_phase` | The documented limit: two phases claimed at once verifies only the second, and `implementation-ready` accepts it anyway |

The last row asserts a **known defect**, deliberately. It is documented in the
implement guidance and the README, so it must not change silently in either
direction — regressing further, or being fixed while the guidance still warns
about it.

## What this suite does not cover

- **Judgment.** Verdicts, rubric behaviour, axis boundaries — `tests/design/`,
  with real models. Only `design-semantic` has such a matrix today;
  `intent-semantic`, `plan-semantic`, `phase-review` and `implementation-semantic`
  have none.
- **Document quality.** The fixtures are one coherent document set. The input
  space is unbounded free text; coverage here is per-facet, not exhaustive.
- **Checkpoint argv.** Deliberately uninspected by the provider, so the fixture
  runs `true`.

## Measured

The suite bites. Two mutant builds, each caught by exactly the scenarios that
should catch them and no others:

| Mutation | Caught by |
|---|---|
| `plan --revise-design--> design` deleted from the transition table | `graph`, `back_edge` |
| Cursor phase-order comparison short-circuited to always agree | `cursor_prefix_violation` |
