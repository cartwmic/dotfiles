# software-change provider

A loop-engine protocol v1 workflow provider for driving a software change from
intent through delivery. Standalone Rust binary; imports no loop-engine crates.

Deployed by chezmoi to `~/.local/share/loop-engine-providers/software-change/`,
built and registered by `run_onchange_build_loop_engine_providers.sh.tmpl`.

## What this owns, and what it does not

The engine owns run identity, current state, lifecycle, the journal, the stored
graph, and committed evidence. This provider owns the graph declaration, gate
policy, run-input validation, guidance, and compatibility judgment.

Gates **judge**; they never perform the work. Requesting `implementation-ready`
does not implement anything — you do the work, then ask the gate whether the
evidence supports the transition.

## Graph

```text
explore ──intent-ready──▶ design ──design-ready──▶ plan ──plan-ready──▶ implement ⟲ phase-complete
                                                                            │
                                                                            │ implementation-ready
                                                                            ▼
                                                              implementation-review
                                                                 │                │
                                                  changes-requested            approved
                                                                 │                ▼
                                                             implement           end
```

`implement` is a **self-loop**: one request per phase of the approved plan, in
the plan's order. The run stays there however many phases there are, which is
what lets the graph be frozen at run creation — before any plan exists — while
still gating every phase.

### Gates on each transition

| Transition | Gates |
|---|---|
| `explore → design` | `intent-ready`, `intent-semantic` |
| `design → plan` | `design-ready`, `design-semantic` |
| `plan → implement` | `plan-ready`, `plan-semantic` |
| `implement → implement` | `phase-complete`, `phase-review` |
| `implement → implementation-review` | `implementation-ready` |
| `implementation-review → end` | `implementation-review-approved`, `implementation-semantic` |
| `implementation-review → implement` | `implementation-review-changes-requested` |

Six of the seven transitions carry **two** gates: one deterministic, one judged.
Both must pass, and neither substitutes for the other.

The pairing on `implementation-review → end` is the one worth explaining.
Without it the last thing between a change and `end` would be an agent writing
`{"verdict": "approved"}` into its own review file — and the journal would record
that self-approval as though a review had happened. `implementation-semantic`
judges the cumulative diff against `intent.json`, at request time, on the
`intent-delivered` axis. A `changes_requested` verdict still moves the run on the
author's word alone; only `approved` has to survive an independent judgment.

### Why there are no `design-review` or `plan-review` states

There were, and they are gone. Both documents are already judged on the
transition **out of** the state that produced them — `design-semantic` and
`plan-semantic` read the document against its upstream and can refuse it. A
review state after that judged nothing: it read a document a judge had just
accepted, and its only gate checked that a file said `approved`.

What it did instead was launder self-approval. An agent writing
`{"verdict": "approved"}` into its own review file produced a permanent journal
entry reading "design-review approved", indistinguishable from a review somebody
actually performed. **A record that cannot tell scrutiny from its imitation is
worse than no record.**

The revision cycle survives without them. A rejected `design-ready` leaves the
run in `design`; the author fixes the document and requests again. That is the
same loop the `changes-requested` edge provided, minus a state whose only output
was a claim about itself.

`implementation-review` is kept because it is not the same shape: it reviews
**code**, which no earlier gate has looked at, and its approving transition
carries a judge.

### Judgment is withheld, never bought, on a failing transition

Semantic gates run **last** in an invocation, after every deterministic one. If
anything deterministic has already failed, the judgment is skipped and the gate
returns a failure reading `not judged: …`.

This is the schema short-circuit generalised. Measured before the fix: a phase
whose checkpoint commands exited non-zero still spent three axis judges and a
decider on a diff it had already refused.

```
phase-complete=FAIL  phase-review=FAIL
why: phase P1 checkpoint: boom: exit 1 | not judged: phase-complete must pass
     before the phase diff is judged, and no model call was spent on a
     transition that cannot complete
judge calls: 0        (was 4)
```

The withheld verdict is a **failure carrying a reason**, never a pass: no judge
ruled, so no claim in the author's favour would be honest.

### Why there is no `validation` state

There was one, and it ran the repository's checks once at the end. Two problems:
a failure at that point says only "something in this change is broken", and the
commands lived in `.loop-workflow.toml`, which makes validation a property of the
repository. It is not — a phase that adds persistence and a phase that adds an
interface do not need the same checks.

Both are fixed by moving the commands into `plan.json`, one list per phase
`checkpoint`, and running them at each phase boundary. The plan is reviewed and
approved, so the commands are reviewed with it, and a failure names the phase.

## Run inputs

Immutable after `run create`.

| Input | Required | Meaning |
|---|:---:|---|
| `artifact_root` | yes | Absolute directory holding the JSON documents and `reviews/` |
| `work_root` | yes | Absolute repository directory; checkpoint commands run here, `.loop-workflow.toml` is read from here, and diffs are taken here |
| `change_id` | no | Short human identifier |

Both paths must be absolute and must already exist — gates dereference them from
an arbitrary working directory, so a relative path would resolve differently per
invocation.

## Gate policy

### Artifact gates (review and hand-off)

Read JSON documents beneath `artifact_root`. Every document needs a non-empty
`revision`. Each gate checks that its document names the exact revision of the
document it descends from, which is what makes a **stale review fail instead of
approving superseded work**.

| Gate | Document | Must reference |
|---|---|---|
| `intent-ready` | `intent.json` | — |
| `design-ready` | `design.json` | `intent_revision` = intent's `revision` |
| `plan-ready` | `plan.json` | `subject_revision` = design's `revision` |
| `implementation-ready` | `implementation.json` | `plan_revision` = plan's `revision` |
| `phase-complete` | `implementation.json` | `plan_revision` = plan's `revision`; phases a **prefix** of the plan's |
| `implementation-review-*` | `reviews/implementation-review.json` | `subject_revision` = implementation's `revision`; non-empty `subject_commit` |

Review documents also carry `verdict`: `approved` or `changes_requested`. The
verdict must match the event requested — asking for `approved` against a document
that says `changes_requested` is `gate.failed`.

#### The intent schema

`intent.json` is the one document with a required shape beyond `revision`,
because it anchors everything downstream. The full contract — template, worked
examples, and borderline cases — lives in the `explore` state's static guidance,
so `run show` teaches it without any provider call.

| Field | Required | Rule |
|---|:---:|---|
| `revision` | yes | non-empty string |
| `problem` | yes | string |
| `outcome` | yes | string |
| `acceptance` | yes | array of strings |
| `non_goals` | yes | array of strings |
| `constraints` | no | if present, array of strings |

Presence and type only. **No length minimums and no entry counts** — length is
not a proxy for substance and a count is not a proxy for a real scope fence.
All violations are reported in a single attempt. Rules live in
`src/gates/intent.rs`.

Substance is judged separately, by the `intent-semantic` gate below. The two
layers are complementary and neither can substitute for the other.

#### The design schema

`design.json` has a required shape too, and one check no other gate performs.
The full contract — template, worked examples, borderline cases — lives in the
`design` state's static guidance.

| Field | Required | Rule |
|---|:---:|---|
| `revision` | yes | non-empty string |
| `intent_revision` | yes | string; must equal `intent.json`'s `revision` |
| `approach` | yes | string |
| `elements` | yes | array of strings |
| `decisions` | yes | array of `{decision, rationale, rejected?}` |
| `coverage` | yes | array of `{acceptance, delivered_by}` |
| `risks` | yes | array of strings; may be empty |

**Acceptance-citation coverage.** The set of `coverage[].acceptance` strings must
equal the set of `acceptance` lines in the intent revision the design
references — verbatim, once each, nothing extra. A dropped or quietly reworded
criterion is caught here, before a single model call is spent. Rules live in
`src/gates/design.rs`.

Citing a line is **not** delivering it. Entailment is the `acceptance-covered`
axis below. Linkage is checked *before* the schema, so a design written against
a superseded intent is told that, rather than handed a set difference computed
against a document it was never written against.

#### The plan schema

`plan.json` is the third document with a required shape, and it is the one the
rest of the workflow executes. The full contract — template, worked examples,
borderline cases — lives in the `plan` state's static guidance.

A plan is a list of **phases**; each phase carries **tasks** and one
**checkpoint**.

| Field | Required | Rule |
|---|:---:|---|
| `revision` | yes | non-empty string |
| `subject_revision` | yes | string; must equal `design.json`'s `revision` |
| `phases[].id` | yes | non-empty string, unique |
| `phases[].goal` | yes | string |
| `phases[].covers` | no | array of design `elements`, cited verbatim |
| `phases[].tasks[]` | yes | `{id, title, depends_on, delivers, context, done_when}` |
| `phases[].checkpoint` | yes | `{commands, timeout_seconds?, review?}` |
| `checkpoint.commands[]` | yes | `{name, run, working_directory?}`; may be empty |
| `checkpoint.review` | no | `{axes, context?}` |

Presence and type only, as with the other schemas — but three kinds of
**referential integrity** are also decidable without a model, and are checked:

- **Identifiers.** Phase ids unique, task ids unique, command names unique
  within a checkpoint.
- **Dependencies.** Every `depends_on` names a task that exists; no dependency
  points forward into a later phase; no cycle. A dependency *within* a phase is
  legal and is how a plan tells a driver which tasks may not run in parallel.
- **Element coverage.** The set of `covers` strings must equal the set of
  `elements` in the design revision the plan references — verbatim, nothing
  extra. This is the plan-side analogue of the design's acceptance citation.

None of these are opinions about quality; each is a plan that cannot be executed
as written. Rules live in `src/gates/plan.rs`.

**Argv is deliberately not inspected.** `"run": []` passes the schema and fails
when the checkpoint executes it. There is no allowlist: the author supplies argv,
the author is the operator, and a fence that must permit `sh` to be useful is not
a fence.

Citing an element is **not** building it. Entailment is the `design-faithful`
axis below.

### The semantic gates

The second gate on `explore → design`, `design → plan`, and
`plan → implement`. They answer what a schema cannot: *is this actually intent,
or has a plan leaked into it*, *does this design actually deliver that intent*,
and *would this plan build that design without the worker inventing it*. Both
gates on a transition must pass.

Judgment is delegated to language models, in two stages:

1. **One independent judge per axis, run concurrently.** Each sees the document
   and exactly one rubric. They do not see each other.
2. **One deciding judge**, which sees the document *and* every axis verdict with
   its reasoning. Its verdict is the binding one.

| Axis | Question |
|---|---|
| `solution-agnostic` | Does intent encode a chosen solution — libraries, files, types, "refactor X to use Y"? |
| `outside-verifiable` | Could every acceptance line be checked by someone who cannot see the code? |
| `scope-fenced` | Do `non_goals` and `outcome` actually constrain what happens next? An empty `non_goals` fails on that alone. |
| `constraints-are-limits` | Are `constraints` real external limits, or solution preferences in disguise? A property-shaped limit needs no citation; one naming a mechanism must say what imposes it. Absent or empty passes without a model call. |
| `problem-grounded` | Does `problem` name who is hurt, doing what, at what cost — and does it stay clear of the solution? It is the one field no other axis reads, so it is checked for carrying the plan. |
| `problem-grounded` | Does `problem` state consequence, or merely restate the solution in negative form? |

#### `design-semantic` axes

Every design judge is given the accepted `intent.json` as labelled context
alongside the design, because the failure this gate exists to catch — a design
that quietly delivers something else — is invisible when a design is read
against itself.

| Axis | Question |
|---|---|
| `intent-faithful` | Built as written, would it deliver the intent's `outcome` without breaking a `constraints` entry or doing `non_goals` work — and is any weaker guarantee stated openly? |
| `acceptance-covered` | Does each `delivered_by` name something the design describes, and would it actually make its acceptance line true? |
| `structural-not-procedural` | Is this a structure — parts with responsibilities — or an order of work? Structural ordering (a dependency) is allowed; a task sequence is not. |
| `decisions-justified` | Is each rationale load-bearing rather than a restatement, and is a contested choice missing? Judges whether reasoning is *present*, never whether the decision is *right*. |
| `risk-honest` | Are the risks specific rather than truisms, and are changed dependencies or moved data named? |

#### `plan-semantic` axes

Every plan judge is given the accepted `design.json` as labelled context. A plan
is judged as an execution of something already agreed, and half these axes cannot
rule at all without it.

| Axis | Question |
|---|---|
| `task-sized` | Could a fresh worker read one task and know when to stop — neither inventing what the change is, nor being handed a keystroke? Fails in **both** directions. |
| `context-sufficient` | Does `context` orient without fencing? Too thin and the worker re-derives settled ground; too prescriptive and it becomes a reading permit. |
| `done-observable` | Could someone who did not do the work decide each `done_when` entry? Need not be machine-checkable. |
| `checkpoint-meaningful` | Could the checkpoint catch **its own phase** failing — or would it be green whether or not the work happened? |
| `decision-free` | Does the plan settle or contradict anything the design shaped? Ordering and grouping are the plan's; structure is not. |
| `design-faithful` | Would the tasks of a phase actually build the elements it claims? Citation is already checked; this is delivery. |
| `dependencies-honest` | Are the declared dependencies the real ones? Fails for a missing dependency **and** for a chain that serialises work with no constraint. |

Three of these axes carry explicit fences against demanding **implementation
form** — which type, which module, which signature. They were added after
testing, because without them `task-sized` and `context-sufficient` both failed a
plan for leaving form open while `decision-free` would have failed the same plan
for supplying it. Two axes that cannot both be satisfied make a gate
unpassable, and the fix is a fence, not a looser threshold.

#### `phase-review` axes

The first judged subject that is **not a document**. It reads the phase's diff
against that phase's tasks, with the accepted `design.json` as labelled context.

| Axis | Question |
|---|---|
| `tasks-actually-done` | Does the diff contain the work each task describes, such that each `done_when` is now true? Placeholders, unimplemented declarations and asserting-nothing tests fail. |
| `no-scope-creep` | Does the diff contain substantial work no task in this phase asked for? Entailed work, incidental fixes and lockfiles pass; a smuggled refactor does not. |
| `design-faithful` | Does the code that now exists have the shape the design describes? Final phase only, appended automatically. |

Which of these run is chosen **by the plan, phase by phase**, under
`checkpoint.review.axes` — not by `.loop-workflow.toml`. Which phases are worth
judging and on what is a property of the change, and a repository setting could
not name a phase. There is deliberately no config key for them; one would look
like it worked and do nothing.

Each axis is fenced against re-adjudicating the checkpoint commands. A
`done_when` naming a runtime condition passes with a note saying the commands
decided it — reading a passing test suite's source to second-guess it is not the
judge's job.

#### `implementation-semantic` axes

Runs on `implementation-review --approved--> end` over the cumulative diff, with
`intent.json` as labelled context.

| Axis | Question |
|---|---|
| `intent-delivered` | If this shipped, would every `acceptance` entry be true and the `problem` be gone? Fails a change that addresses a **proxy** for the problem, does a `non_goals` entry, or violates a `constraints` entry. |

This is the only judgment in the run that compares **code to intent**. Everything
before it compares each step to the step before — design to intent, plan to
design, each phase to its own tasks — so a change can pass every gate and still
not deliver what was asked for, because no link ever checked further than its own
neighbour.

`risk-honest` is deliberately bounded. It does **not** ask "is anything missing"
in general: that question is unsatisfiable, because one more hypothetical crash
or race can always be imagined, and in testing it rejected the same worked
example three times running, each time for a different unnamed hazard. It fails
for an omission in exactly two cases — behaviour something already depends on
that this design changes, and existing data this design moves — both decidable
from the documents in front of the judge.

The decider exists because ANDing narrow judges makes the gate as flaky as its
flakiest axis. It can overturn an axis that misread the document, and can also
reject a document every axis passed. It may **not** overturn an axis because the
defect looks small — "pedantic", "minor" and "immaterial" are named in its rubric
as non-reasons. Nor may it rule that an axis went outside its rubric: the decider
is never shown the axis rubrics, so that ground would be guesswork wearing the
clothes of a finding. Every axis verdict is recorded as evidence regardless of
which way it went, so dissent stays auditable.

Its rubric names four flaws as **material on their own** — a task in
`acceptance`, a constraint naming a mechanism rather than a property, an empty
`non_goals`, and a `problem` stating a code fact with no consequence. Without
that list the decider overturned a correctly-failing axis roughly two times in
three, treating a real flaw as pedantry. It may still overturn a genuine
misreading; it may not overturn merely because a flaw is small.

Rubrics live in `src/gates/semantic.rs`. Each rubric names what is *not* its
business — an unfenced judge drifts into scoring everything, and then every axis
returns the same verdict.

**Rubrics are published, verbatim, into static guidance.** Each state's guidance
carries the exact text every judge receives, composed at graph-build time from
the same constants the judges read, so the published bar cannot drift from the
applied one. A test asserts every axis rubric appears in the emitted graph, so a
new axis cannot ship unpublished.

Guidance publishes a subject where someone standing in that state has to satisfy
or **select** those rules. `plan` therefore carries the `phase-review` rubrics as
well as its own — a plan declares which checkpoint axes run, and choosing them
blind would be choosing from a menu with no dishes on it — and `implement`
carries them again, because that is where they judge and so where drift has to be
detectable. Each set is identified by its own gate:

```text
RUBRIC SET (plan-semantic): 5d5b7bf5dbffb604
RUBRIC SET (phase-review): 5edefff57086bebf
```

This is a correction, not a nicety. The provider's own doctrine is that static
guidance must be sufficient to know what to produce without a live provider
call. While the deciding rules were invisible it was not: a document could
follow every published example and still fail on a rule the author was never
shown. The evidence is that this repository's own worked plan example needed
six corrections before it passed — found by the judges, against rubrics written
by the same author.

Publication is **verbatim**, including the roughly one line in ten addressed to
the judge rather than the author (`Do not rule on X — other judges cover
those`). Editing it would read slightly better and cost two things worth more:
an author can hash what they read and compare it to the `rubrics` value in every
evidence record — *the rules I was shown are provably the rules that judged me* —
and a mis-marked span would vanish from the author's copy while still deciding
their document. A framing note carries the cost instead, telling the reader the
text speaks to the judge. Guidance roughly doubles: explore 31 KB, design 50 KB,
plan 43 KB, against a 256 KiB bound.

**Configuration** is the `[judge]` table in `.loop-workflow.toml`; see
`example.loop-workflow.toml`. `model` is the only required key. Axis subsets are
per-document: `axes` selects intent axes, `design_axes` design axes, `plan_axes`
plan axes. The three vocabularies are disjoint and are not interchangeable —
naming an intent axis under `plan_axes` is a configuration error, not a silent
default, and an unknown TOML key anywhere is rejected rather than ignored.

**Judge throughput is the binding cost, and the provider matters more than the
model.** Axis judges run in bounded waves — `max_parallel_axes`, default 3 —
because they are processes, not threads, and past a handful in flight they stop
behaving like parallel work. Judging one plan across seven axes, measured:

| Judge provider | Wall clock | Outcome |
|---|---|---|
| `openai-codex/gpt-5.6-sol` | 1m38s | every axis determinate |
| `claude-bridge/claude-haiku-4-5` | 25m+ | most axes timed out |

A bridged model shells out to another coding agent and pays its whole startup on
every call. The bridged run did not merely take longer — it produced
`evaluation_error`, which reads like a broken provider rather than a saturated
one. Prefer a direct-API provider for judges. If you must use a bridge, set
`max_parallel_axes = 1` and raise both `timeout_seconds` and the provider
registration timeout accordingly.

**Failure-mode policy.** Any judge that does not return a determinate verdict —
CLI missing, timeout, non-zero exit, unparseable reply, no `[judge]` section,
unknown axis — makes the attempt an `evaluation_error` (`error`, exit 1), never
a gate failure. A gate failure is a claim about the author's document; if no
judgment happened, no such claim is honest, and a broken judge must never become
a silent pass. Fail closed.

**An unchanged subject gets its previous answer, not a fresh roll — but only if
that answer was NO.** A completed judgment is stored under
`artifact_root/.judgments/`, keyed by the *judged content*, the rubric hash, the
selected axes and both models. Re-requesting an unchanged, previously **rejected**
subject replays that verdict without calling a judge. Editing changes the key, so
a real fix is always judged afresh. Without this the cheapest route past the gate
is to re-request an unchanged document until nondeterministic judges fall your
way; every blind reviewer raised it. The cost is that the provider is no longer
stateless.

A stored **pass** is never replayed, for any subject. The cache is
author-writable and every input to its key is knowable by the author — the rubric
hash is printed in the evidence of their previous attempt — so a stored pass is
precisely the entry an adversarial author would forge, and replaying only
rejections makes a forged entry worthless: the sole verdict it can supply is one
against its author's own interest. `intent-semantic` was the last exception here
and it was an oversight, not a policy; it is now `false` like every other
subject. The cost is re-judging an unchanged document that already passed, which
does not arise in the ordinary flow because a pass moves the run on.

The key is deliberately not the file's bytes. The document is canonicalised
first — object keys sorted, whitespace dropped, `revision` removed — because
re-indenting a file, reordering its keys, or bumping a field no rubric reads are
not edits, and each would otherwise mint a fresh key and re-roll the judges. List
order is preserved: the order of `acceptance` entries is content.

This is **not** a security boundary, and the wording above is chosen to avoid
claiming otherwise. The cache lives under `artifact_root`, which the author
writes, so an author set on resampling can delete it; the provider has no state
location the author cannot reach. Failing closed on an unreadable cache would be
the worse trade — a cache that can block a judgment is a new way for the gate to
be wrong. So a miss is always safe, and every read or write failure degrades to
judging normally.

**An axis with nothing to judge costs nothing.** When `constraints` is absent or
empty, `constraints-are-limits` is decided as a pass without a model call — its
rubric already says so — and the evidence records that it was decided without a
judge. Six calls become five for the common case.

**Which rubrics judged this is recorded, and a changed bar is detected.** Every
attempt emits a `judge-rubrics` evidence record carrying a hash of the exact
rubric text plus both model names, so a verdict today's binary would not repeat
is still explainable from the journal.

Because rubrics are now published into guidance, they are **frozen in the run's
graph snapshot** — and `evaluate_gates` receives that snapshot. So the gate
compares the rubric set it is about to apply against the one the run was created
under, and emits a `judge-rubric-drift` record when they differ:

> `rubrics:drift:this run was created under rubric set e3d4d96f2578ecca for
> intent.json, and was judged by c34ac61031955c6f; the provider was rebuilt with
> different judge instructions after the run began.`

**Recorded, not enforced.** The verdict stands. Refusing would strand a run
mid-flight over a change that is usually a deliberate improvement, and the
author's real need is to know which rules applied — which the evidence answers.
What changes is that the journal can now explain a judgment the run's own stored
guidance would not predict. Verified in both directions: a rebuilt provider
emits exactly one drift record and still completes the transition; an unchanged
one emits none.

**The document is untrusted input.** Every judge prompt says so, and a reply must
be exactly one JSON object (a single markdown fence is tolerated). Scanning a
reply for the first object that carries a verdict — the original behaviour —
would let a document containing `{"verdict":"pass"}` have its own object quoted
back as the judge's answer.

**One retry, indeterminate only.** A judge that returns nothing determinate is
asked exactly once more; a determinate pass or fail is never re-asked, so the
fail-closed policy is untouched. This covers the observed transient of a judge
exiting 0 having written nothing at all. The reported diagnostic carries both
attempts so a persistent fault reads differently from a one-off flake.

**Short-circuit.** While the document still violates the schema, the semantic
gate fails without spending a single model call, and says so. Fix the schema
first.

**Judge isolation.** Judges are spawned with tool use, extension discovery,
skills, prompt templates and context-file discovery all disabled, from a
temporary directory. A judge must see the rubric and the document, and nothing
else. Extensions that supply a provider must therefore be named explicitly in
`[judge].extensions`.

> **Caveat that bit once.** If your model is served by a *bridge* to another
> agent CLI, the isolation flags apply to `pi`, not to the CLI behind the
> bridge: that CLI keeps its own persona and its own context files, and
> `--system-prompt` never reaches it. The rubric is therefore sent in the user
> message as well, which no bridge can discard. Without that, judges answered as
> coding assistants offering to *implement* the document instead of judging it,
> and every axis came back indeterminate.

**Cost and latency.** One model call per axis plus one decider — five calls at
default settings. Measured ~40s wall-clock for four axes with
`claude-haiku-4-5` axes and a `claude-sonnet-5` decider; ~24s for one axis. Every
rejected attempt pays it again, which is why the schema short-circuit exists.
Trim with `[judge].axes`.

Minimal review document:

```json
{ "revision": "2", "subject_revision": "2", "verdict": "approved" }
```

### The phase loop

`implementation.json` is a **cursor**, not a report. It is append-only, never
revised, and never reviewed — unlike the three authored documents above it.

```json
{ "revision": "1", "plan_revision": "1", "base_commit": "abc123",
  "phases": [ { "id": "P1", "commit": "def456" } ] }
```

The entry is written **before** the gate runs. It is a claim — "I have finished
this phase" — exactly as `design.json` claims to deliver the intent, and the gate
is what decides whether the claim survives. Claiming first means a rejection
leaves nothing to unwind, and re-requesting is idempotent because it re-verifies
the same phase.

`phase-complete` and `phase-review` both act on the **last** claimed phase:

- `phase-complete` runs that phase's `checkpoint.commands` as argv in
  `work_root`. Every one must exit 0.
- `phase-review` judges that phase's **diff** on the axes the plan declared for
  it. A phase declaring no axes passes without a judgment; whether declaring none
  was right is what `checkpoint-meaningful` decided when the plan was approved.

`implementation-ready` requires the claimed list to be the plan's phases, in
order, complete.

**Known limit: it checks claims, not verifications.** A gate receives the run's
inputs and stored graph, not its journal, so the provider cannot see which
`phase-complete` transitions the engine actually accepted. A run whose every
checkpoint was rejected can still leave `implement` on a complete claim list —
verified directly:

```
every phase checkpoint fails       phase-complete=FAIL phase-review=FAIL
leaving implement anyway           implementation-ready=PASS
```

The backstop is `implementation-semantic` at the end, which judges the whole diff
against the intent and finds work that was never done. That is defence in depth,
not the phase loop holding, and the guidance in `implement` says so rather than
implying a guarantee that is not there.

**The final phase always gets `design-faithful`**, appended by the provider
whether or not the plan named it. Per-phase reviews only ever compare one phase
to its own tasks; the last phase is the only point at which the whole change
exists to be compared against the design. Left to the author this is the axis
that gets forgotten, and the forgetting is invisible.

Checkpoint axis names are validated by `plan-ready`, so a plan naming an axis
this build does not implement is rejected at review rather than breaking the loop
halfway through the change.

`run guidance` in `implement` names the current phase, its tasks, its checkpoint
commands and its review axes. It is the only surface that can: static guidance is
frozen at run creation, before any plan exists. It deliberately does **not**
claim to know whether the last claimed phase was accepted — the provider reads
documents, not the journal — and says so rather than guessing.

### How the diff is taken

`git diff <base>` against the **working tree**, so uncommitted work counts. A
gate that only saw commits would pass a phase whose work exists only in the
author's editor.

Untracked files are rendered in full via `git diff --no-index` against
`/dev/null`. New files are usually the substance of a phase, and git will not
mention them until they are added — which a gate must never do. Ignored files
stay ignored.

`base` is the previous phase's recorded `commit`, or `base_commit` for the first
phase. **`commit` is optional**: without it there is no boundary, so every phase
is judged against everything accumulated since `base_commit`. Noisier, never
wrong, and the judges are told explicitly that this is what happened rather than
left to infer it from the volume.

**Nothing is truncated.** A cap would silently drop hunks, and the dropped one is
exactly as likely as any other to be the one that mattered. Uncapped, an
oversized diff overruns the judge and surfaces as `evaluation_error` — visible,
and pointing at the real problem, which is a phase too large to review. Measured
diff size is recorded as evidence on every judgment, so the failure is not a
surprise.

A `base_commit` git cannot resolve is a **gate failure** naming the value, not an
evaluation error: the cursor is wrong, nothing is broken.

### Reviewing code, not a revision

`reviews/implementation-review.json` carries `subject_commit` as well as
`subject_revision`, and it is **required**. A document review can link by
revision because a document cannot change without its revision changing; code
can — the tree moves under a reviewer silently. A review with no
`subject_commit` states nothing about what was read, which leaves nothing to
detect drift against, so the whole mechanism would be decorative.

Mismatch against `HEAD` does **not** fail the gate. It records
`review-commit-drift` evidence and the verdict stands, matching the
rubric-drift precedent: refusing would strand a finished change over what is
usually a rebase or an unrelated file landing after the reviewer was satisfied.
What the reader needs is to know the review was written against a different tree,
and now the journal says so.

### Command gates (checkpoints)

Commands come from `plan.json`, executed directly as argv: no shell, no word
splitting, no expansion. Invoke `/bin/sh -c` explicitly if you need shell syntax.

The argv is deliberately **not** inspected beyond its type. `plan-ready` accepts
an empty `run` array, which then fails at execution — the author is the operator,
and a fence that must permit `sh` to be useful is not a fence.

An unspawnable executable is `evaluation_error` (`error`, exit 1) — deliberately
distinct from a command that ran and failed, which is an honest gate verdict
(`rejected`, exit 2). An empty command list is legitimate: a phase may rely
entirely on its declared review, or be pure preparation.

Each command's captured output is hashed into an evidence record with its argv,
exit code, duration, and a bounded output snippet.

## Timeouts

The whole invocation is bounded by the registration timeout (default 60s). The
provider reserves 5 seconds of that budget so it can still write its result
envelope before the engine's SIGTERM lands, and computes **one deadline for the
whole invocation** from what remains.

Every stage clamps to that shared deadline. This matters because an invocation
can run several: `phase-complete` executes the checkpoint commands and then
`phase-review` judges the diff. Each stage previously derived its own budget from
the registration timeout, starting from its own clock — so a 900s registration
could spend 895s on tests and then hand the judge a fresh 895s. The engine's
SIGTERM landed first, and a provider killed before it can write its envelope
reads as broken rather than as slow. A stage starting late now inherits what is
left, not a fresh copy of its configured budget.

**The 60s default is too small for the semantic gate** — a four-axis judgment
plus decider needs several minutes of headroom on a slow link. Since a slow suite
and a judgment now genuinely compete for one budget, give the commands their own
ceiling with `checkpoint.timeout_seconds` in the plan and raise the registration
timeout enough for both.

```sh
loop-engine provider update software-change \
  --exec ~/.local/share/loop-engine-providers/bin/software-change \
  --timeout 900
```

## Changing the workflow

`src/graph.rs` is the workflow definition. Editing it changes the graph revision
for **newly created runs only** — existing runs keep the canonical snapshot taken
at their creation, which is what keeps active runs stable across provider edits.

After changing gate IDs, `run compatibility <RUN-ID>` on active runs reports
which stored gates this build no longer implements. Do it while the run is still
active; it rejects on terminal runs.

## Development

```sh
cd ~/.local/share/chezmoi/dot_local/share/loop-engine-providers/software-change
CARGO_TARGET_DIR=/tmp/sc-target cargo test
CARGO_TARGET_DIR=/tmp/sc-target cargo build --release
```

Edit under the chezmoi source tree, not the deployed copy, then `chezmoi apply`.

Protocol reference: `docs/provider-protocol-v1.md` and `docs/graph-projection.md`
in <https://github.com/cartwmic/loop-engine>.
