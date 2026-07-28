//! Executable workflow authority.
//!
//! This module *is* the workflow definition. Changing it changes the graph
//! revision for newly created runs; existing runs keep the canonical snapshot
//! taken at their creation.

use serde_json::{json, Value};

/// Every gate this build implements. `check_compatibility` and `evaluate_gates`
/// compare stored-graph gate IDs against this set, so removing an entry here is
/// what makes an old run report incompatible rather than silently misbehave.
pub const SUPPORTED_GATES: &[&str] = &[
    "intent-ready",
    "intent-semantic",
    "design-ready",
    "design-semantic",
    "plan-ready",
    "plan-semantic",
    "phase-complete",
    "phase-review",
    "implementation-ready",
    "implementation-semantic",
    "implementation-review-approved",
    "implementation-review-changes-requested",
];

pub fn is_supported_gate(gate_id: &str) -> bool {
    SUPPORTED_GATES.contains(&gate_id)
}

/// Static guidance for `explore`.
///
/// The full contract lives here rather than in an external file so that the run
/// snapshot is self-sufficient: an operator resuming a cold run learns exactly
/// what to produce from `run show`, with no provider invocation. Live guidance
/// stays strictly additive.
const EXPLORE_GUIDANCE: &str = r#"Capture the INTENT of this change: what must become true, and why. Do not describe how.

Write `intent.json` at the root of artifact_root, then request `intent-ready`.

--- TEMPLATE ---
{
  "revision":    "1",
  "problem":     "What is wrong or missing today, and why it matters now.",
  "outcome":     "One sentence: what is true when this is done.",
  "acceptance":  ["Observable, solution-agnostic, verifiable statements."],
  "non_goals":   ["Explicit scope fence: what this change is NOT."],
  "constraints": ["Optional. Real external limits, not preferences."]
}

--- TWO TESTS TO APPLY TO EVERY LINE ---
1. SUBSTITUTION. If someone shipped a COMPLETELY DIFFERENT implementation that
   made this statement true, would you be satisfied?
     yes -> it is intent.
     no  -> you have encoded a HOW. Either:
            (a) something outside this change genuinely forces that choice --
                rewrite it as the PROPERTY that is forced, and put THAT under
                `constraints`; or
            (b) it is only your preference -- delete it here and argue for it in
                the design document.
            A preference does not become a constraint by being moved.
            EXCEPTION: if the interface itself is what the change is for -- an
            exit-status mapping, a wire shape, a published format that outside
            parties will depend on -- then the exact values ARE the intent. Say
            plainly in `problem` who depends on that contract and why the
            current one fails them, and state the mapping in `acceptance`. Do
            not launder a real contract decision into a fabricated constraint.

2. OUTSIDE VERIFICATION. Could this be checked by someone who cannot see the
   code and did not do the work?
     yes -> it is an outcome.
     no  -> it is a task. Tasks belong in the plan.
   Observable is not enough on its own. A reader must be able to tell from this
   document what situation to create and what result counts as success. Words
   like "acceptable", "supported", "appropriate" or "reliable" fail unless you
   say here what they mean.

WHICH TEST APPLIES WHERE. These two tests are yours to apply while writing. The
gates enforce them AND the further field rules below -- this table is not the
whole standard.
  problem      neither test. Name who is affected and in what situation, and
               what it costs them. Do not put the solution or the work here:
               `problem` is the one field the other checks do not read, so it is
               where a plan hides most easily. It is checked for exactly that.
  outcome      both tests.
  acceptance   both tests, per entry.
  non_goals    neither test -- a non-goal is not something that becomes true, so
               substitution does not apply. Exclude a CAPABILITY, never a
               mechanism: excluding "replacing the serializer" forecloses the
               design, while excluding "adding retry behaviour" fences the scope.
               An EMPTY list is fine when there is nothing plausible left to
               fence -- if `outcome` and `acceptance` already close every
               adjacent reading, do not invent a temptation to disclaim. The
               gate asks whether scope is open, not whether a list is long.
  constraints  neither test. Each entry must be a limit imposed from OUTSIDE
               this change. An entry that states a PROPERTY the world requires --
               "the on-disk format must stay readable by the previous release" --
               stands on its own; you do not have to cite a source for it. An
               entry that names a MECHANISM, tool, vendor or existing component
               must say what imposes it: an existing interface, a published
               format, a policy, a regulation, a contract, a cost or operating
               limit. "We must use X because it is required", with no
               identifiable source, is a preference in a disguise the gate is
               built to see through.

intent = what must become true, and why
design = how, structurally
plan   = what steps, in what order

The examples below are ILLUSTRATIVE ONLY. Do not mirror their subject matter.
Write about your actual change.

--- GOOD EXAMPLE A: a small change ---
{
  "revision": "1",
  "problem": "The batch command exits zero even when some records fail, so downstream automation treats a partial failure as a clean run and never retries.",
  "outcome": "Downstream automation can tell a partially failed batch run from a fully successful one without inspecting per-record output.",
  "acceptance": [
    "A run where every record succeeded is distinguishable from one where any record failed",
    "The number of failed records is available to the caller of the run",
    "A fully successful run reports success exactly as it does today"
  ],
  "non_goals": [
    "Changing whether any individual record succeeds or fails",
    "Adding retry behaviour"
  ]
}

--- THE SAME CHANGE, WRITTEN BADLY ---
{
  "revision": "1",
  "problem": "batch.rs returns Ok(()) at the end",
  "outcome": "Change the return type to Result<Summary, BatchError> and propagate failures",
  "acceptance": [
    "Add a BatchError enum",
    "Change run_batch to return Result<Summary, BatchError>",
    "Update the three call sites",
    "Add a test for the error path"
  ],
  "non_goals": []
}

Why it fails: every acceptance entry is a TASK, so it is a plan wearing an
intent filename. It fixes the mechanism (a return type) instead of the outcome,
so a better solution would score as failure. `problem` states a code fact rather
than an impact on anyone. And nothing anywhere fences the scope -- neither the
empty `non_goals` nor the task list, which is bounded only by construction --
so downstream work can grow without ever contradicting this document.

--- GOOD EXAMPLE B: a larger change ---
{
  "revision": "1",
  "problem": "Work in progress is lost when a session expires, and expiry is silent, so people discover it only when they try to submit. Support receives repeated reports of lost work.",
  "outcome": "Someone who steps away and comes back does not lose work they had already entered.",
  "acceptance": [
    "Entered work survives the session expiring while the page is still open",
    "A person is told their session expired before they attempt to submit",
    "Recovering earlier work needs no support intervention",
    "A session that never expires still requires no recovery step at submit time"
  ],
  "non_goals": [
    "Changing how long a session lasts",
    "Preserving work across different devices"
  ],
  "constraints": [
    "Recovered work must never be readable by another account",
    "Entered work must not leave our data-residency boundary"
  ]
}

Note the last acceptance line in both examples: a regression fence, naming one
existing behaviour this change must not disturb. Name it. "Everything else
behaves exactly as today" quantifies over behaviour you have not stated and
cannot be checked by anyone, so it is rejected rather than credited.

--- BORDERLINE 1: a real constraint vs a smuggled preference ---
CONSTRAINT (belongs here):
    "The on-disk format must stay readable by the previous release."
PREFERENCE (does not):
    "Use the existing serializer."

The second names a mechanism. Ask: if a different serializer preserved the
format, would you object? If not, the thing you actually care about is the
format. Strip the mechanism and write what is left.

--- BORDERLINE 2: an outcome vs a task ---
TASK (belongs in the plan):
    "Add a resume endpoint."
OUTCOME (belongs here):
    "An interrupted upload can be continued without starting over."

The task names one solution. The outcome admits several -- a resumable
endpoint, chunked retry, a client-side buffer -- and is still verifiable by
someone who cannot see the code.

--- BORDERLINE 3: a fence vs a mechanism ban ---
FENCE (belongs in non_goals):
    "Adding retry behaviour"
MECHANISM BAN (does not):
    "Replacing the existing serializer"

The first excludes a capability someone might have thought was included. The
second forbids an implementation option, which quietly decides the design. If
you need the format preserved, say so under constraints as a property.

--- THE PASTE TEST FOR `problem` ---
Could your problem sentence be pasted, unchanged, into an unrelated change? If
yes, it is not a problem statement. "People who depend on this hit avoidable
friction" fits every change ever proposed and is rejected on sight. Name who,
what they were doing, and what it cost them.

--- BORDERLINE 4: specific vs fog ---
FOG (rejected):
    "problem":    "People who depend on this hit avoidable friction, wasting
                   time and generating support load."
    "outcome":    "The friction that motivated this change is gone."
    "acceptance": ["The motivating friction no longer occurs"]
    "non_goals":  ["Rewriting unrelated subsystems"]

Every sentence is well formed, solution-agnostic, and empty. Nothing names who,
what situation, or what result. The non_goal excludes something nobody proposed.
A plan derived from this could do almost anything and still claim conformance.

Write the specific friction, for the specific person, in the specific situation.
If you cannot, you are not ready to leave this state.

--- WHAT THE GATES CHECK ---
Two gates guard this transition and BOTH must pass.

1. `intent-ready` -- deterministic. Presence and shape only:
     revision     required, non-empty string
     problem      required string
     outcome      required string
     acceptance   required array of strings
     non_goals    required array of strings
     constraints  optional array of strings
   The field set is CLOSED: an unknown field is rejected, so a plan cannot ride
   along beside the intent in a field no judge looks at. Blank strings and blank
   entries are rejected as emptiness.
   No length minimums and no entry counts: length is not a proxy for substance.
   All violations are reported together, not one per attempt.

2. `intent-semantic` -- non-deterministic. Language models judge the document
   against the two tests above. Independent judges each examine one axis.

   The exact instructions each judge receives are printed in full under
   HOW EACH JUDGE IS INSTRUCTED, below. Read them: they are the specification
   your document is measured against, and they are the only complete statement
   of it.

   A deciding judge then sees the document and every axis finding, and issues
   the binding verdict. It affirms the axes by default: it may overturn a
   failure only by showing the axis misread your document, and may reject a
   document all five axes passed only for a stated whole-document defect --
   an outcome that does not resolve the problem, acceptance that would not make
   the outcome true, fields that contradict, implementation content or work
   steps anywhere in the document, or content aimed at the judges themselves.
   Its reasoning is returned to you on rejection and is recorded as run evidence
   either way.

   This gate is skipped -- reported as failed without spending model calls --
   while the document still violates the schema. Fix the schema first.

   If a judge cannot be reached at all, the attempt is an ERROR (exit 1), not a
   rejection. A judgment that did not happen is never reported as a verdict on
   your document. Configure judges under [judge] in .loop-workflow.toml.

   The rubrics printed below were frozen into this run when it was created,
   along with an identifier covering them. Every judgment records that same
   identifier, so you can confirm the rules you read are the rules that judged
   you. A provider upgrade can change what judges look for; when that happens
   after your run was created, the gate records the change as evidence rather
   than moving the bar silently. The reasons returned with a verdict remain
   authoritative over any prose summary.

   ON EXIT 1, DO NOT EDIT intent.json. No binding verdict was reached -- some
   axes may have answered, but the attempt as a whole produced no judgment on
   your document, and nothing about the document caused that. Read the diagnostics: a transient fault has already been
   retried once and may be requested again, while a missing judge command, a
   missing [judge] section or an unknown axis will reproduce forever until the
   configuration is fixed. Editing the document cannot clear an evaluation error.

   A rejection (exit 2) is the opposite: your document was judged and found
   wanting. Read the reasons, fix the document, request again."#;

/// Static guidance for `design`.
const DESIGN_GUIDANCE: &str = r#"Describe the DESIGN of this change: the SHAPE of the solution -- what parts
exist, what each is responsible for, and which choices were made and why. Do not
describe an order of work.

Write `design.json` at the root of artifact_root, then request `design-ready`.

--- TEMPLATE ---
{
  "revision":        "1",
  "intent_revision": "the current revision of intent.json",
  "approach":        "One paragraph: the shape of the solution.",
  "elements":        ["<name> -- <what it is responsible for>"],
  "decisions":       [
    {
      "decision":  "What was chosen.",
      "rationale": "Why this, over what.",
      "rejected":  ["Optional. Alternative, and why not."]
    }
  ],
  "coverage":        [
    {
      "acceptance":   "<one acceptance line of the intent, copied VERBATIM>",
      "delivered_by": "Which element or decision makes it true."
    }
  ],
  "risks":           ["What is assumed, what could fail, what this disturbs."]
}

--- THE TEST TO APPLY TO THE WHOLE DOCUMENT ---
Could two competent engineers build from this and produce STRUCTURALLY THE SAME
system, without either of them having to decide a LOAD-BEARING question you left
open?
  yes -> it is a design.
  no  -> either it is a sketch (a choice is missing) or it is a plan (an order
         of work has taken the place of a structure).

LOAD-BEARING means the choice changes a named part, a responsibility, a
boundary, an externally observable guarantee, compatibility, or a migration. You
are NOT required to close every implementation choice -- no finite design can.
Which data structure holds a count, or which of two equivalent libraries formats
a string, may be left to whoever builds it, and the gate will not ask.

--- THREE TESTS TO APPLY TO EVERY LINE ---
1. RESPONSIBILITY. Does this name a PART and what it is answerable for, or does
   it name a FILE and an edit to make in it?
     part -> it belongs in `elements`.
     edit -> it is plan content. Delete it; the plan will say it.

2. REVISABILITY. Would a later reader learn from this rationale what would have
   to change for the decision to be revisited?
     yes -> it is a rationale.
     no  -> it is a restatement. "Cleaner", "simpler", "idiomatic" and "standard"
            say nothing unless you say simpler for whom, and at what cost.

3. GUARANTEE. Working exactly as described, with nothing outside it going wrong,
   does this deliver what the intent asked for?
     yes -> keep it. You may still NAME what could defeat it -- that is a risk,
            and the risk judge asks for exactly that. "This assumes every record
            outcome reaches the tally" does not weaken your guarantee; it says
            what would break it.
     no  -> it fails, and admitting the weakness does not save it. A shortfall
            that follows from the mechanism you chose -- "counts are
            best-effort", "available on request", "exact numbers are out of
            scope", "delivered in a later change" -- is a decision to deliver
            less than was asked. Saying so plainly under `decisions` is honest
            and is still a rejection, and rephrasing it as an assumption changes
            nothing: the gate judges what gets built, not how the sentence is
            worded. If the intent asks for more than this change should deliver,
            the INTENT is what has to change -- go back, revise it, and return
            here. Candour is not permission.

intent = what must become true, and why
design = how, structurally
plan   = what steps, in what order

`coverage` is the join between intent and design. Every acceptance line of the
intent must appear there exactly once, copied character for character, paired
with the thing that makes it true. Paraphrasing a criterion is how a criterion
gets quietly softened, so paraphrase is rejected mechanically.

The examples below are ILLUSTRATIVE ONLY. Do not mirror their subject matter.
They are written against the small intent excerpted immediately below, so that
coverage citations can be shown matching real acceptance lines. Your own
citations must match YOUR intent, not this one.

--- THE INTENT THESE EXAMPLES ARE WRITTEN AGAINST (excerpt) ---
{
  "revision": "1",
  "problem": "The batch command exits zero even when some records fail, so downstream automation treats a partial failure as a clean run and never retries.",
  "outcome": "Downstream automation can tell a partially failed batch run from a fully successful one without inspecting per-record output.",
  "acceptance": [
    "A run where every record succeeded is distinguishable from one where any record failed",
    "When any record fails, the number of failed records is reported to the caller",
    "A fully successful run reports success exactly as it does today"
  ],
  "non_goals": [
    "Changing how individual records are processed",
    "Adding retry behaviour"
  ]
}

Notice what that second line does NOT say. "When any record fails, the number is
reported" can be delivered without touching the successful path; "the number is
always available" could not, and would have contradicted the third line. Two
acceptance lines that pull against each other put every design that follows in an
impossible position -- if you find yourself in one, the intent is what needs
revising.

--- GOOD EXAMPLE ---
{
  "revision": "1",
  "intent_revision": "1",
  "approach": "A run keeps a tally of the records it processed and the ones that failed. The run's reported result is derived from that tally when the run ends, so 'some records failed' becomes a property of the run itself rather than something a caller must reconstruct from per-record output.",
  "elements": [
    "run tally -- owns the counts of processed and failed records for one run, and is the only place a failure count is derived from",
    "record processing -- keeps its existing responsibility for a single record, and reports each outcome to the tally instead of discarding it",
    "run result -- what the caller observes when a run ends. It is formed from the tally: a run the tally recorded no failures for produces exactly today's result; a run with failures produces a result that additionally carries the count the tally holds"
  ],
  "decisions": [
    {
      "decision": "The run result carries a count of failed records, not the failed records themselves.",
      "rationale": "The intent asks callers to tell partial failure apart and to know how many records failed; carrying the records would put a record representation into the run boundary, which callers would then depend on and we would be obliged to keep stable. Revisit this if a caller is ever required to act on individual failures.",
      "rejected": ["Return the failed records with the result -- makes the record shape a public contract", "Write a separate failure report -- puts the answer somewhere the caller has to go looking for"]
    },
    {
      "decision": "A run in which nothing failed produces exactly the result it produces today.",
      "rationale": "Existing callers treat today's success signal as the whole contract, so changing it for successful runs breaks them while delivering nothing the intent asked for. Revisit only if the success signal itself has to change for another reason.",
      "rejected": ["Always return the new richer result -- forces every existing caller to change for no gain"]
    }
  ],
  "coverage": [
    {
      "acceptance": "A run where every record succeeded is distinguishable from one where any record failed",
      "delivered_by": "run result -- its failure count is non-zero exactly when the tally recorded a failed record"
    },
    {
      "acceptance": "When any record fails, the number of failed records is reported to the caller",
      "delivered_by": "run result -- the failure-bearing form carries the number the tally holds"
    },
    {
      "acceptance": "A fully successful run reports success exactly as it does today",
      "delivered_by": "run result -- the form it takes when the tally recorded no failures"
    }
  ],
  "risks": [
    "This assumes every record outcome reaches the tally. A processing path that ends early without reporting would undercount failures, and the run would report clean.",
    "A caller that assumes every run produces the same result shape has to tolerate the failure-bearing form. Whether any caller makes that assumption has not been checked.",
    "Automation that today reads a partially failed run as a clean one will start seeing failures. That is the point of the change, but anything downstream that was tuned to the old behaviour changes at the same moment, and this design does not stage that.",
    "The tally is assumed to belong to exactly one run. If records are ever processed concurrently, or one process handles several runs, updates to a tally would have to be ordered and separated, and nothing here says how."
  ]
}

--- THE SAME CHANGE, WRITTEN BADLY ---
{
  "revision": "1",
  "intent_revision": "1",
  "approach": "First add a BatchError enum, then change run_batch to return Result<Summary, BatchError>, then update the three call sites, then add a test for the error path.",
  "elements": [
    "batch.rs -- change the return type of run_batch",
    "errors.rs -- add the BatchError enum",
    "tests/batch_test.rs -- add a test for the error path"
  ],
  "decisions": [
    {
      "decision": "Return a Result.",
      "rationale": "It is the idiomatic approach and is cleaner."
    }
  ],
  "coverage": [
    {
      "acceptance": "A run where every record succeeded is distinguishable from one where any record failed",
      "delivered_by": "the new error handling"
    },
    {
      "acceptance": "When any record fails, the number of failed records is reported to the caller",
      "delivered_by": "Summary"
    },
    {
      "acceptance": "A fully successful run reports success exactly as it does today",
      "delivered_by": "handled by the refactor"
    }
  ],
  "risks": ["Bugs may occur.", "Testing will be needed."]
}

Why it fails: `approach` is an order of work and `elements` are files with edits,
so it is a plan wearing a design filename -- nothing states what exists when it
is done or what each part is answerable for. `Summary` is delivered_by for a
criterion but appears nowhere else in the document, and "the new error handling"
and "handled by the refactor" name nothing at all. The one rationale restates
its own decision. Changing the return type also changes what a fully successful
run reports, which the intent explicitly required to stay as it is. The risks
are truisms that would be true of any change.

--- BORDERLINE 1: structural order vs a plan ---
STRUCTURAL (allowed):
    "The run result is derived from the tally, so the tally must be complete
     before the result is formed."
PLAN (not allowed):
    "First add the tally, then wire it into the result, then update callers."

The first is a dependency between parts and is true of the finished system. The
second is a sequence of work and is true only while the work is happening.

--- BORDERLINE 2: an element vs an edit ---
ELEMENT (belongs here):
    "run tally -- owns the failure count for one run"
EDIT (belongs in the plan):
    "batch.rs -- add a counter field to the run struct"

Ask what the thing is answerable for. If the answer is a file, it is not an
element.

--- BORDERLINE 3: a rationale vs a restatement ---
RESTATEMENT (rejected):
    "decision:  Report a failure count.
      rationale: Because a count is what callers need."
RATIONALE (accepted):
    "decision:  Report a failure count.
      rationale: Carrying the records themselves would make the record shape a
                 public contract we would be obliged to keep stable. Revisit if
                 a caller must act on individual failures."

--- BORDERLINE 4: delivered_by that names something, vs one that does not ---
NAMES NOTHING (rejected):
    "delivered_by": "the new error handling"
NAMES SOMETHING (accepted):
    "delivered_by": "run result -- its failure count is non-zero exactly when
                     the tally recorded a failed record"

A `delivered_by` must point at an element or a decision that is described
elsewhere in this document. If it points at something you never described, the
design is not finished.

AND THE HARDER RULE: what you write inside a `coverage` entry is a CLAIM, not a
description. The argument for why a line comes true has to be findable in
`approach`, `elements` or `decisions`. Coverage is the join, not the evidence.

HOLLOW (rejected), even though every citation resolves:
    "elements": ["failure visibility -- responsible for making a run with any
                  failed record distinguishable from a clean one"]
    "delivered_by": "failure visibility"

That element is the acceptance line with a noun bolted on. Where does the fact
come from? What carries it to the party the line names? The document never says,
so two engineers would invent two different systems. An element earns its place
by naming a RESPONSIBILITY, not by renaming the requirement.

SOUND (accepted):
    "elements": ["run tally -- owns the counts of processed and failed records
                  for one run, and is the only place a failure count is derived
                  from",
                 "run result -- what the caller observes when a run ends; a
                  failed run carries the count the tally holds"]
    "delivered_by": "run result -- it carries out the count the tally holds"

Test each element by covering up the acceptance lines. If an element still says
something about the system, it is a part. If it only makes sense as an echo of a
requirement, it is coverage theatre and this gate rejects it.

THE SUBTLER VERSION, and the one that gets written most often: parts that sound
like parts but only ASSERT that they hold the fact.

ASSERTED (rejected):
    "elements": ["failure accounting -- knows how many records failed in a run",
                 "run boundary -- exposes success vs partial failure to the
                  caller"]

How does failure accounting come to know? What connects it to the boundary?
Nothing in the document says, so nothing has been designed -- the requirement has
been restated in three pieces. Whoever plans this still has to invent the whole
mechanism.

For every acceptance line, your document must let a reader answer three
questions, and the gate checks all three:
    ORIGIN    which part produces or observes the fact, and out of what?
    CARRIAGE  what carries it from there to where the caller meets it?
    ARRIVAL   what does the party named in the acceptance line actually see?

In the good example above: the tally derives the count from record outcomes
reported to it (origin), the run result is formed from the tally (carriage), and
the caller observes the run result (arrival). Three links, all stated.

HOW FAR DOWN THIS GOES, because it is a fair question: to the level of named
parts and how they relate, and no further. You do not have to say what type
holds the count, how the result is encoded, what the field is called, or what
happens on an error. Those are the plan's business, and the gate is told not to
ask for them. If the path can be restated in one sentence using only names your
document already gives, the chain holds.

--- BORDERLINE 5: a fair risk vs a truism ---
TRUISM (rejected):
    "Bugs may occur."  "This may take longer than expected."
RISK (accepted):
    "This assumes every record outcome reaches the tally; a path that ends early
     without reporting would report a clean run."

A risk is specific to THIS design. If it would read identically on any other
change, it says nothing. A risk that only repeats something the intent already
put under `non_goals` is rejected too: the intent has already excluded it, so
naming it here adds nothing.

You are NOT required to enumerate generic operational hazards -- crashes, races,
lost processes, infrastructure failures. The gate does not ask for them, because
one more can always be imagined. It asks for exactly three omissions:
  (a) behaviour something already depends on that this design changes;
  (b) existing data this design moves, reshapes or reinterprets;
  (c) a caller-observable contract, or a stored or transmitted shape, that this
      design changes.
Name those three. An empty list is allowed only when none of them applies -- and
note that (c) is decided from YOUR OWN TEXT: if your design describes a change to
what a caller sees, staying silent about who depends on it does not clear the
check, it fails it.

The gate does NOT require you to enumerate your assumptions, and no judge will
fail you for one you did not write down. State the ones a reader needs. If you
do state one, state what it would mean for it to be false -- an assumption
without its consequence tells a reviewer nothing.

--- BORDERLINE 6: a hazard vs a weakening dressed as one ---
HAZARD (belongs in risks, and does not fail the gate):
    "This assumes every record outcome reaches the tally; a processing path that
     ended early without reporting would report a clean run."

WEAKENING (fails, however it is worded):
    decision: "Report outcomes to the tally without ordering the updates."
    risk:     "This assumes concurrent reports are never lost; the count may be
               lower than the true number of failures."

The second is a pair: a decision that declines a safeguard, and an admission of
the shortfall that decision permits. The intent asked for the number of failed
records. A number that may be too low is not that number, and moving the
admission into `risks` does not change what gets built. If you need that
trade-off, say so in the INTENT -- qualify the acceptance line there and get it
reviewed -- then design against the qualified line.

The gate does not accept "a competent implementer would handle that anyway". If
a safeguard is what makes an acceptance line true, this document is where it
belongs.

--- BORDERLINE 7: a live alternative vs a straw man ---
STRAW MAN (rejected):
    "rejected": ["Do nothing", "Rewrite the whole system"]
LIVE ALTERNATIVE (accepted):
    "rejected": ["Return the failed records -- makes the record shape a public
                  contract we would have to keep stable"]

`rejected` is for options someone would actually have proposed, each with the
reason it lost. A list of options nobody was considering is decoration, and this
gate rejects it.

You do NOT have to record every choice you made. A decision entry is required in
two cases only: when `approach`, an element or a decision names another way this
could have been built that you did not take, and when two elements are
alternative ways to satisfy the same acceptance line with nothing saying which
owns it. A choice the document never raises is not a missing decision.

Two things that are NOT forks, and will not be treated as one:
  - CONTRAST WITH TODAY. "A property of the run rather than something a caller
    reconstructs" contrasts with the behaviour the intent already rejected.
    There is nothing left to decide, so no decision entry is owed.
  - A HYPOTHETICAL IN `risks`. Raising what would happen if something else were
    true is what that field is for. It is never read as an undecided fork.

--- WHEN A GATE REFUSES THIS DOCUMENT ---
You stay in this state. There is no separate review step to bounce back from:
`design-ready` and `design-semantic` are the review, and a refusal leaves the run
exactly where it was with the reasons attached.

Bump `revision` when you make a substantive change, and keep `intent_revision`
equal to the CURRENT intent revision -- if the intent itself was revised, re-read
it, because your coverage citations must match its acceptance lines character for
character and the old ones will no longer match.

Passing sends you straight to `plan`. There is no `design-review` state, and its
absence is deliberate: your document has just been judged against the intent by
gates that can refuse it, and a state whose only gate checked that a file said
`approved` would add a journal entry claiming scrutiny that nothing performed.

--- WHAT THE GATES CHECK ---
Two gates guard this transition and BOTH must pass.

1. `design-ready` -- deterministic. Two things:
   a. Presence and shape. The field set is CLOSED: an unknown field is rejected,
      so a task list cannot ride along under a key of its own invention. Note
      what that does NOT buy you: every field here is or contains free text, so
      a schedule pasted into a risk or a `delivered_by` passes the schema. The
      semantic gate reads the whole document for exactly that reason.
        revision        required, non-empty string
        intent_revision required string, must equal intent.json's revision
        approach        required string
        elements        required array of strings
        decisions       required array of {decision, rationale, rejected?}
        coverage        required array of {acceptance, delivered_by}
        risks           required array of strings (may be empty)
      No length minimums and no entry counts.
   b. Coverage citation. The set of `coverage[].acceptance` strings must equal
      the set of `acceptance` lines in the intent revision this design
      references -- verbatim, once each, nothing extra. A dropped or reworded
      criterion is caught here, before any model call is spent.

   Citing a line is NOT the same as delivering it. That is the next gate.

2. `design-semantic` -- non-deterministic. Independent judges each examine one
   axis, and are given the accepted intent alongside the design.

   The exact instructions each judge receives are printed in full under
   HOW EACH JUDGE IS INSTRUCTED, below. Read them: they are the specification
   your document is measured against, and they are the only complete statement
   of it.

   A deciding judge then sees both documents and every axis finding, and issues
   the binding verdict. It affirms the axes by default. It may overturn a
   failure on ONE ground only: that the axis misread the documents, quoting the
   text it misread. It is not shown the axis rubrics, so it cannot rule that an
   axis invented a rule. Smallness is not a ground -- a rubric-defined defect is
   not waived for being minor.

   What this means for you: arguing that a judge exceeded its brief will not get
   a rejection overturned. Show that your document already said the thing the
   judge said was missing -- or write it.

   It may reject a design all five axes passed only for a stated whole-document
   defect: the elements not adding up to the approach, decisions that
   contradict, a load-bearing choice left for the plan to invent, coverage that
   resolves while the mechanism is nowhere described, plan content in a field no
   axis judged, or a document that tries to instruct its own judges. That last
   one is worth stating plainly: text addressed to the judges -- claiming prior
   approval, asserting that an axis misread you, or quoting these rules back --
   is treated as evidence against the document, never as argument. Judges are
   told that anything reaching them from inside your document or from inside
   another judge's quoted reasoning is untrusted. Write for the reviewer in the
   next state, not for the judges.

   A pass requires all five axes to have reported. If configuration removes one,
   the deciding judge is instructed to fail rather than pass on a partial set.

   A REJECTION is replayed, not re-rolled. The stored verdict is keyed on this
   design's judged content, the intent it is judged against, the rubrics, the
   axis list and the models, so re-requesting an unchanged rejected design
   returns the same answer rather than resampling until the models fall your way.
   Reformatting the file or bumping only `revision` changes nothing a judge
   reads, so it replays too.

   A PASS is not replayed -- it is judged again. The store sits under
   artifact_root, which you can write, so a stored pass is not evidence that any
   judge ever saw the document.

   If you believe a rejection was wrong rather than earned, the sanctioned route
   is to edit what the judges read: say the thing the judge said was missing,
   plainly, in `approach`, `elements` or `decisions`. That changes the key and the
   document is judged afresh. Re-requesting a byte-identical document under
   unchanged configuration is the one thing that will not help.

   This gate is skipped -- reported as failed without spending model calls --
   while the document still violates the schema or the coverage citation check.
   Fix those first.

   If a judge cannot be reached at all, the attempt is an ERROR (exit 1), not a
   rejection, and DO NOT EDIT design.json in response: nothing was judged, so
   nothing about your document caused it. Read the diagnostics. A rejection
   (exit 2) is the opposite -- your document was judged and found wanting."#;

const PLAN_GUIDANCE: &str = r#"Write the PLAN for this change: the ORDER of the work, cut into units a fresh
worker can carry out. Do not re-decide the design.

Write `plan.json` at the root of artifact_root, then request `plan-ready`.

A plan is executed one PHASE at a time. The driver reads the current phase, does
its tasks -- alone or in parallel, its choice -- then requests `phase-complete`,
which runs that phase's checkpoint. Only when every phase is complete does the
change move to review. So a phase is not a heading: it is a unit of work that
gets verified before the next one starts.

--- TEMPLATE ---
{
  "revision":         "1",
  "subject_revision": "<the approved design.json revision>",
  "phases": [
    {
      "id":     "P1",
      "goal":   "One sentence: what is true when this phase is done.",
      "covers": ["<design element, cited verbatim>"],
      "tasks": [
        {
          "id":         "T001",
          "title":      "Short label.",
          "depends_on": ["<task ids this one consumes the output of>"],
          "delivers":   "The result this task produces.",
          "context":    ["<what to read to be oriented; not a fence>"],
          "done_when":  ["<conditions someone else could check>"]
        }
      ],
      "checkpoint": {
        "commands": [
          { "name": "test", "run": ["cargo", "test"], "working_directory": null }
        ],
        "timeout_seconds": 600,
        "review": { "axes": ["<axis id>"], "context": ["design.json"] }
      }
    }
  ]
}

`run` is argv executed directly: no shell, no globbing, no pipelines. For shell
syntax, invoke a shell explicitly: ["sh", "-lc", "cargo test 2>&1 | tail"].
`working_directory` is relative to work_root, or null for work_root itself.
`covers` and `review` are optional per phase; `checkpoint` and `commands` are
not, though `commands` may be empty.

--- THE TEST THAT DECIDES TASK SIZE ---

Every task is handed to ONE worker who has no memory of this project and sees
only that task, the documents its `context` names, and the repository.

    Could that worker READ THIS TASK AND KNOW WHEN TO STOP?

Two ways to fail it, and plans fail in both directions:

  They would have to INVENT THE CHANGE -> too broad. The task names an area
  ("error handling", "the persistence layer") or leaves decisions unsettled that
  nothing settles for them.

  There is NOTHING LEFT TO DECIDE -> too narrow. The task is a keystroke: add an
  import, rename a symbol, add one field. It has no result of its own.

Task count is not the measure. Three large tasks and thirty small ones can each
be right. What matters is that every task is a unit of work with a result.

--- THE TEST THAT DECIDES WHAT BELONGS IN A PLAN ---

    If this choice were made differently, would the SHAPE the design describes
    change?

  Yes -> you are designing. It belongs in the design, which has already been
         judged; revise `design.json` and re-run its gates rather than deciding
         it here.
  No  -> you are planning. Order, grouping, and where to verify are yours.

Naming a file or a function to touch is execution detail, not design -- unless
it introduces a structure the design does not have.

--- CONTEXT POINTS, IT DOES NOT FENCE ---

`context` exists so a worker does not re-derive what is already settled. It is
not a reading list and not a permission boundary. A worker is always free to
explore the repository; naming three files does not forbid the fourth.

  Too thin:         [] on a task that plainly depends on a decision recorded
                    elsewhere, or that consumes the output of a task in
                    `depends_on` without saying what that output is.
  Too prescriptive: a long enumeration meant to bound what may be read, or a
                    list that dictates which functions to write in what order.

An empty `context` is correct for a task whose work is fully described by its
own `delivers` and `done_when`.

--- DEPENDS_ON IS A CLAIM ABOUT PARALLELISM ---

The driver decides what to run at the same time, and `depends_on` is the only
thing telling it what it may not. So both errors are real:

  Missing:  two tasks that would collide, or one that consumes another's output,
            with nothing declared. The driver runs them together and one works
            against something that does not exist yet.
  False:    a chain where each task depends on the previous one only because it
            was written second. That forbids all parallel work while claiming a
            constraint that is not there.

Within a phase, no declared dependency means "these may run in parallel". Say it
only when it is true.

--- CHECKPOINTS ARE WHERE UNVERIFIED WORK STOPS ACCUMULATING ---

Between checkpoints, nothing is confirmed. A checkpoint should be able to detect
its own phase failing -- not merely re-confirm what the previous one established.

Balance is the whole point. Checkpoint after every task and the plan is mostly
overhead. Checkpoint once at the end and a phase-four mistake is discovered
after phase nine. Put the boundary where a coherent result exists, and make the
checkpoint able to see it.

The practical test, and the one plans fail most often: read the checkpoint
against the phase's own `done_when` entries. If a condition needs the whole
thing running and the checkpoint only exercises a part, the checkpoint is green
whether or not the phase succeeded.

An empty `commands` list is legitimate: a phase whose result is not mechanically
checkable may rely on a declared `review`, and a preparation phase may confirm
nothing. It is wrong only when the phase did substantive work and NEITHER
commands NOR review could detect it going wrong.

COMMANDS AND REVIEW ANSWER DIFFERENT QUESTIONS. A suite tells you nothing broke.
It does not tell you the phase was done -- a suite that was green before the
phase is green after it if the work was skipped -- and it cannot establish a
property stated as an absence of change. Where either of those matters, the
phase needs a review as well as commands.

`review` axes available at a checkpoint: tasks-actually-done, no-scope-creep,
design-faithful. They judge the actual diff, not a self-report.

--- THE DESIGN THESE EXAMPLES ARE WRITTEN AGAINST (excerpt) ---
{
  "revision": "1",
  "approach": "A run keeps a tally of the records it processed and the ones that failed. The run's reported result is derived from that tally when the run ends...",
  "elements": [
    "run tally -- owns the counts of processed and failed records for one run, and is the only place a failure count is derived from",
    "record processing -- keeps its existing responsibility for a single record, and reports each outcome to the tally instead of discarding it",
    "run result -- what the caller observes when a run ends. It is formed from the tally: a run the tally recorded no failures for produces exactly today's result; a run with failures produces a result that additionally carries the count the tally holds"
  ]
}

Elements are cited in `covers` VERBATIM. A deterministic check compares them, so
a paraphrase is rejected before any judge sees the plan.

--- GOOD EXAMPLE ---
{
  "revision": "1",
  "subject_revision": "1",
  "phases": [
    {
      "id": "P1",
      "goal": "A run's failures are counted, and the count is fed by the code that processes records.",
      "covers": [
        "run tally -- owns the counts of processed and failed records for one run, and is the only place a failure count is derived from",
        "record processing -- keeps its existing responsibility for a single record, and reports each outcome to the tally instead of discarding it"
      ],
      "tasks": [
        {
          "id": "T001",
          "title": "Counts for one run",
          "depends_on": [],
          "delivers": "A run has a tally that records how many records it processed and how many failed, and it is the only place a failure count is derived from.",
          "context": ["design.json"],
          "done_when": [
            "A run that processed records reports how many it processed and how many failed",
            "No other part of the system derives a failure count independently"
          ]
        },
        {
          "id": "T002",
          "title": "Record outcomes reach the tally",
          "depends_on": ["T001"],
          "delivers": "Every path that finishes processing a record reports that outcome to the run's tally.",
          "context": [
            "design.json",
            "T001 -- builds the tally this reports into"
          ],
          "done_when": [
            "A run in which some records failed has a tally whose failure count equals the number that failed",
            "A record that succeeded is counted as processed and not as failed",
            "How an individual record is processed is unchanged"
          ]
        }
      ],
      "checkpoint": {
        "commands": [
          { "name": "suite", "run": ["cargo", "test"] }
        ],
        "timeout_seconds": 600,
        "review": {
          "axes": ["tasks-actually-done"],
          "context": ["design.json"]
        }
      }
    },
    {
      "id": "P2",
      "goal": "Callers can tell a partially failed run from a clean one.",
      "covers": [
        "run result -- what the caller observes when a run ends. It is formed from the tally: a run the tally recorded no failures for produces exactly today's result; a run with failures produces a result that additionally carries the count the tally holds"
      ],
      "tasks": [
        {
          "id": "T003",
          "title": "The result a run reports",
          "depends_on": ["T001"],
          "delivers": "A run ends by reporting a result derived from its tally: unchanged when nothing failed, carrying the failure count when something did.",
          "context": [
            "design.json",
            "T001 -- builds the tally this result is derived from"
          ],
          "done_when": [
            "A result formed from a tally that recorded no failures is exactly the result reported today",
            "A result formed from a tally that recorded failures carries the number that tally holds",
            "A caller can tell those two apart without inspecting per-record output"
          ]
        }
      ],
      "checkpoint": {
        "commands": [
          { "name": "suite", "run": ["cargo", "test"] }
        ],
        "timeout_seconds": 900,
        "review": {
          "axes": ["tasks-actually-done", "no-scope-creep"],
          "context": ["design.json"]
        }
      }
    }
  ]
}

Why this passes. T001 and T002 each have a result a stranger could recognise, and
neither is a keystroke. T002 declares T001 because it reports INTO the tally --
a real consumption, not writing order.

T003 declares T001 and not T002, and the reason is worth studying because it is
where this example was originally WRONG. Forming a result reads the tally; it
does not care who populated it. But an earlier draft gave T003 the condition
"a run with failures reports a result carrying the number of failed records",
and that is an END-TO-END condition -- it cannot be observed unless record
processing is already feeding the tally, which is T002's job. The declared
dependency then understated the real one. The fix was not to add T002 to
`depends_on`; it was to state what T003 actually delivers. A result formed FROM
A TALLY is checkable against a tally set up directly, with no dependency on who
fills it in production.

That is the general move: when `done_when` and `depends_on` disagree, one of
them is describing a different task than the other. Usually the condition
drifted end-to-end and the fix is to narrow it, not to bolt on a dependency.

T001 carried a second error of the same family, and it is the subtlest one on
this page. It originally said the tally is "the only place THOSE COUNTS come
from" -- both of them. The design says it is "the only place A FAILURE COUNT is
derived from". One word wider, and it is a shape claim the design never made:
the plan would have forbidden deriving a processed-count elsewhere, which the
design left open. Extending an exclusivity, tightening a scope, or generalising
a guarantee are all ways of deciding, and they are easy to write by accident
while trying to be crisp. When a task restates a design element, restate it at
exactly the design's width.

Note also that T002 and T003 sit in different phases, so T002 is complete before
T003 begins regardless of what either declares. A dependency pointing back into
an earlier phase is legal and useful -- it documents what the task reads -- but
it buys no parallelism. Parallelism is a WITHIN-PHASE property: tasks in one
phase that declare no dependency on each other are the ones a driver may run at
the same time.

The checkpoints are the third place this example was originally wrong, and the
error is the most common one there is. P1 ended with a unit-test-only command
while its own `done_when` said "a run in which some records failed has a tally
whose failure count equals the number that failed". That is an INTEGRATION
condition -- it needs a run, with records. A unit-only checkpoint is green
whether or not P1 achieved it, which means the phase boundary verified nothing.

Read your checkpoint against your own `done_when`, not against habit. If a
condition in the phase needs the whole thing running, a checkpoint that does not
run the whole thing cannot see the phase fail.

Both phases therefore end with the suite. Identical commands are fine when both
phases need the same reach; making them differ for the sake of differing is
decoration.

But both also carry a REVIEW, and that is the part worth taking from this
example. A suite that was green before a phase started is green afterwards
whether or not the phase happened. Commands establish THAT NOTHING BROKE; they
are weak evidence that anything was BUILT, and no evidence at all for a property
stated as an absence -- "a successful run reports exactly what it reports
today". That is why P1 reviews tasks-actually-done and P2 adds no-scope-creep:
the commands and the review answer different questions, and a phase that carries
only commands is trusting the suite to notice work that was never done.

--- THE SAME CHANGE, WRITTEN BADLY ---
{
  "revision": "1",
  "subject_revision": "1",
  "phases": [
    {
      "id": "P1",
      "goal": "Implement the change",
      "covers": [
        "run tally -- owns the counts of processed and failed records for one run, and is the only place a failure count is derived from",
        "record processing -- keeps its existing responsibility for a single record, and reports each outcome to the tally instead of discarding it",
        "run result -- what the caller observes when a run ends. It is formed from the tally: a run the tally recorded no failures for produces exactly today's result; a run with failures produces a result that additionally carries the count the tally holds"
      ],
      "tasks": [
        {
          "id": "T001",
          "title": "Add the BatchError enum",
          "depends_on": [],
          "delivers": "A BatchError enum in src/batch/error.rs",
          "context": [],
          "done_when": ["The enum is added"]
        },
        {
          "id": "T002",
          "title": "Add the imports",
          "depends_on": ["T001"],
          "delivers": "Imports updated",
          "context": [],
          "done_when": ["T002 is done"]
        },
        {
          "id": "T003",
          "title": "Error handling",
          "depends_on": ["T002"],
          "delivers": "Error handling for the batch subsystem",
          "context": [
            "src/batch/mod.rs", "src/batch/run.rs", "src/batch/record.rs",
            "src/batch/error.rs", "src/cli/args.rs", "src/cli/output.rs",
            "tests/batch.rs -- read these and only these"
          ],
          "done_when": ["Error handling is clean and correct"]
        },
        {
          "id": "T004",
          "title": "Update the tests",
          "depends_on": ["T003"],
          "delivers": "Tests updated",
          "context": [],
          "done_when": ["Ran the tests"]
        }
      ],
      "checkpoint": { "commands": [] }
    }
  ]
}

Every failure this plan carries, named:

  T001 invents a BatchError enum. The design has three elements and none of them
  is an error type -- the plan is DECIDING, not planning, and the design was
  already approved without it.

  T002 is a keystroke. "Add the imports" has no result; nobody would ever be
  handed it as a unit of work.

  T003 is an area, not a task. "Error handling for the batch subsystem" leaves
  the worker to invent what the change is. Its `context` is the opposite failure
  -- seven files with "read these and only these", which fences the worker
  instead of orienting them.

  `done_when` fails three different ways: "The enum is added" restates the task,
  "T002 is done" is circular, "Error handling is clean and correct" has no
  standard anyone else could apply, and "Ran the tests" is an activity that can
  be true while the suite is red.

  The dependency chain T001 -> T002 -> T003 -> T004 is writing order, not
  consumption. It tells the driver nothing may run in parallel, which is false.

  One phase with an empty checkpoint means nothing is verified until the whole
  change is done -- the exact accumulation a phase boundary exists to stop.

--- BORDERLINE 1: sequencing vs designing ---

  PLANNING:  "Build the tally before the result that reads it."
             Order. Build them the other way and the design is unchanged.

  DESIGNING: "The tally is a separate module with its own persistence layer."
             The design named an element, not a module with storage. Choose
             differently and the shape changes.

--- BORDERLINE 2: a real dependency vs writing order ---

  REAL:    T002 depends_on T001 -- T002 reports INTO the tally T001 creates.
           Run them together and T002 has nothing to report to.

  WRITING: in the bad example below, T004 depends_on T003 because T003 was
           written first. Nothing T004 does consumes anything T003 produced.
           Declaring it costs the driver every chance to parallelise -- and
           since all four sit in ONE phase, that cost is real rather than
           theoretical.

  The question is not "would I naturally do this second?" but "does this
  consume what that produced?"

--- BORDERLINE 3: an observable condition vs a task restatement ---

  OBSERVABLE:  "A run with failures reports the number of failed records."
               Someone who did not do the work can check it.

  RESTATEMENT: "The failure count is implemented."
               Only the person who did the work can say. It is the task with
               "is implemented" appended.

  A condition need not be machine-checkable. A person deciding it is fine; the
  test is whether SOMEONE ELSE can decide it.

--- BORDERLINE 4: a checkpoint that sees its phase vs one that does not ---

  SEES IT:    P1 ends with unit tests over the counts P1 built. If the counts
              are wrong, the checkpoint is red.

  BLIND:      a phase that changes only the caller-visible result, ending with a
              checkpoint that runs the same unit tests as the phase before and
              nothing that exercises the result. It is green either way, so it
              establishes nothing about this phase.

  A checkpoint identical to the previous phase's is fine when the phases do
  similar work. It is a failure when the phase built something the checkpoint
  cannot see.

--- BORDERLINE 5: compression vs a dropped element ---

  COMPRESSION: one task delivering what three sentences of design prose
               describe. Legitimate -- plans are not obliged to mirror design
               paragraph for paragraph.

  DROPPED:     a phase citing an element in `covers` whose tasks would not
               produce it. The citation passes the deterministic check and the
               element still never gets built. This is the failure `covers` is
               least able to catch on its own, and it is what the design-faithful
               judge is looking for.

--- WHEN A GATE REFUSES THIS DOCUMENT ---

You stay in this state. `plan-ready` and `plan-semantic` are the review; a
refusal leaves the run here with the reasons attached and nothing to unwind.

Raise `revision` when you make a substantive change and keep `subject_revision`
pointing at the design you are planning against. If a refusal points at something
the DESIGN does not support, that is a design problem and not a task to write
around: revise `design.json`, request `design-ready` again from `design`, and
come back. Smuggling the fix into a task hides a design change inside a plan.

Passing sends you straight to `implement`. There is no `plan-review` state, for
the same reason there is no `design-review` one.

--- WHAT THE GATES CHECK ---

`plan-ready` -- deterministic, no models:
  presence and type of every field, at every level
  unknown fields rejected, at every level
  `revision` and `subject_revision` non-empty
  `subject_revision` equals the current design.json `revision`
  phase ids unique; task ids unique
  every `depends_on` names a task that exists
  no dependency points forward into a later phase
  no dependency cycle
  every design `element` cited verbatim by some phase's `covers`
  nothing cited that the design does not contain
  command names unique within a checkpoint

It does NOT check: how many tasks or phases, how long any text is, whether argv
is sensible, or whether the commands exist. An empty `run` array passes here and
fails when the checkpoint executes it.

`plan-semantic` -- independent judges, one per axis, then a deciding judge.

The exact instructions each judge receives are printed in full under HOW EACH
JUDGE IS INSTRUCTED, below. Read them: they are the specification this document
is measured against, and the only complete statement of it. A one-line summary
per axis used to sit here; it was a lossy paraphrase of text now shipped whole,
and keeping both would have let the two drift apart with you paying for it.

Neither layer substitutes for the other. Judges are told what is NOT their
business, so a finding that reads as a different axis's concern is a misread
worth saying so in the review.

A schema-invalid document is reported as failed WITHOUT spending model calls, so
fix `plan-ready` violations first -- they cost nothing to re-request. If a judge
cannot be reached at all the attempt is an ERROR (exit 1), not a rejection: do
not edit plan.json in response, because nothing about it was judged.
"#;

const IMPLEMENT_GUIDANCE: &str = r#"Carry out the approved plan in work_root, ONE PHASE AT A TIME.

This state does not advance per task. It advances per PHASE: you do a phase's
tasks -- alone, or several at once, your choice -- then request `phase-complete`,
which runs that phase's checkpoint. The run stays here until every phase is
verified, then you request `implementation-ready`.

Call `run guidance` to see which phase is current, its tasks, and its checkpoint.
That is the only surface that can tell you: this text was frozen before a plan
existed, so it cannot name your phases.

--- THE CURSOR ---

`implementation.json` at the root of artifact_root tracks where you are.

{
  "revision":      "1",
  "plan_revision": "<the approved plan.json revision>",
  "base_commit":   "<commit the work starts from>",
  "phases": [
    { "id": "P1", "commit": "<commit at the end of P1>" }
  ]
}

Write it with an empty `phases` list before starting the first phase. Set
`base_commit` to the commit you are building on TOP of -- resolve it now, when
implement begins, not earlier: the run was created back at `explore`, and the
repository may have moved since. It must be a commit that exists; every review in
this state measures its diff from it, and a name git cannot resolve fails the
gate.

It is APPENDED TO, never revised. Unlike intent, design and plan, this document
is not authored prose and is never reviewed. Nothing reads `revision` except the
gate that requires it to be non-empty.

--- THE LOOP ---

  1. `run guidance`            -> which phase, its tasks, its checkpoint
  2. do that phase's tasks
  3. commit                    -> optional, but see below
  4. append { "id": "<phase>", "commit": "<sha>" } to `phases`
  5. request `phase-complete`  -> the gate verifies THAT phase
  6. repeat until every phase is listed
  7. request `implementation-ready`

Step 4 comes BEFORE step 5 on purpose. The entry is a CLAIM -- "I have finished
this phase" -- and the gate is what verifies it, exactly as design.json claims to
deliver the intent and a gate decides whether it does. Claiming first means a
rejection leaves nothing to unwind: the claim simply stays unverified, you fix
the work, and you request again.

--- WHY COMMIT PER PHASE ---

`commit` is optional and the loop works without it. What it buys is the scope of
the review.

  committed:     a phase is reviewed against the diff since the PREVIOUS phase's
                 commit. Each review sees that phase's work and nothing else.
  not committed: there is no boundary to diff from, so every phase is reviewed
                 against everything accumulated since `base_commit`. Reviews get
                 noisier as the change grows, and a late phase is judged
                 alongside work already accepted.

Neither is wrong. Committing is what makes "this phase's diff" mean anything.

--- WHAT THE CHECKPOINT DOES ---

Requesting `phase-complete` runs TWO gates over the LAST phase listed in
`phases`, and both must pass:

  phase-complete   runs that phase's `checkpoint.commands`, as argv, in work_root
  phase-review     judges the phase's DIFF against that phase's tasks, using the
                   axes the plan declared for it

A rejection names which of the two failed, so read the gate id before assuming
the tests broke.

`phase-review` is skipped -- and passes -- when the phase declares no review
axes. That is a legitimate plan decision and it was judged when the plan was
approved; it is not re-litigated here.

The review reads the actual diff, not a description of it. There is nothing to
write and no report to author: what you did is what gets judged.

--- WHAT THE REVIEW SEES ---

The diff is taken from your recorded boundary to the WORKING TREE, not to HEAD.
Uncommitted work counts. So does untracked work: files git is not tracking are
shown to the judge in full, because otherwise a phase that consists mostly of new
files would look empty. Nothing is truncated.

That last point has a consequence worth planning around: an enormous phase can
overrun the judge's context, and the gate then reports an evaluation error rather
than a verdict. If that happens, the phase was too big to review, which is a plan
problem and not a provider one. The diff's measured size is recorded as evidence
on every judgment, so you can see it coming.

On the FINAL phase the provider adds `design-faithful` to whatever review that
phase declares, whether or not the plan named it. Per-phase reviews only ever see
one phase against its own tasks; something has to ask whether the whole change
built the design, and the last phase is where the whole change exists.

--- WHEN A PHASE FAILS ---

`phase-complete` is rejected (exit 2). The run stays in `implement`, the phase
stays claimed-but-unverified, and nothing needs undoing. Read the reasons, fix
the work, request again. Leave the entry in `phases` -- removing it would only
make the gate verify the phase before it.

A rejection is not a reason to move on to the next phase, and this is the one
place the loop trusts you rather than checking.

`implementation-ready` reads your cursor. It can see that you CLAIMED every
phase; it cannot see which of those claims the engine accepted, because a gate is
handed the run's inputs and its stored graph, not its journal. So a run whose
every checkpoint was rejected can still leave this state on a complete claim
list.

What catches it is the end: `implementation-semantic` judges the whole diff
against the intent on the way to `end`, and work that was never done is not there
to be found. That is a real backstop and it is not the same thing as the phase
loop having held. If you skip past a rejection you are not getting away with
anything -- you are deferring the whole bill to one judgment at the end, which is
where it is most expensive to be told no.

--- LEAVING THIS STATE ---

`implementation-ready` requires `phases` to list every phase of the approved
plan, in the plan's order, with nothing extra and nothing skipped. If you are
rejected here, compare your list against the plan rather than the work you
remember doing.

The state you land in reviews the CUMULATIVE change against the INTENT -- not
against the plan. Every check up to that point compared each step to the step
before it: the design to the intent, the plan to the design, each phase to its
own tasks. A change can pass all of those and still not deliver what was asked
for, because nothing has yet compared the code to the intent directly. That is
the one remaining question, and it is why the last review is not simply a bigger
version of the phase reviews.
"#;

const IMPLEMENTATION_REVIEW_GUIDANCE: &str = r#"Decide whether this change is finished.

Read the CODE, not the documents about it. Every phase has already been verified
against its own tasks and every checkpoint command has passed, so re-reading the
plan tells you nothing new. The question left is the one nothing in the run has
asked yet: does the change deliver the INTENT?

--- WHAT TO WRITE ---

`reviews/implementation-review.json`:

{
  "revision":         "1",
  "subject_revision": "<the current implementation.json revision>",
  "subject_commit":   "<the commit you actually read>",
  "verdict":          "approved" | "changes_requested"
}

`subject_commit` is what makes this review honest. A document review can link by
revision, because a document cannot change without its revision changing. Code
can: the tree moves under a reviewer silently. If the repository has moved past
the commit you recorded, the gate records that as evidence and the verdict still
stands -- but the record now says the review was written against a different tree
than the one that shipped.

--- YOUR APPROVAL IS NOT THE LAST WORD ---

Requesting `approved` runs two gates. One checks this document. The other,
`implementation-semantic`, judges the CUMULATIVE DIFF against `intent.json` on
the `intent-delivered` axis, at the moment you request it, reading the tree as it
stands now.

That is deliberate. Without it, the only thing between a change and `end` would
be an agent writing `{"verdict": "approved"}` into its own review file, and the
run's journal would record that self-approval as though a review had happened.

So a `changes_requested` verdict sends the run back to `implement` on your word
alone, but an `approved` one has to survive an independent judgment. The rubric
that judgment uses is published in full below.

--- IF THE JUDGE REFUSES ---

The run stays here. Read the reason, request `changes-requested` to go back to
`implement`, fix the gap, and come back. Do not edit the intent to match what was
built: the intent was accepted, and moving the target is how a change comes to
deliver nothing anybody asked for.
"#;

/// `(id, final, static guidance)`
const STATES: &[(&str, bool, &str)] = &[
    ("explore", false, EXPLORE_GUIDANCE),
    ("design", false, DESIGN_GUIDANCE),
    ("plan", false, PLAN_GUIDANCE),
    ("implement", false, IMPLEMENT_GUIDANCE),
    ("implementation-review", false, IMPLEMENTATION_REVIEW_GUIDANCE),
    ("end", true, "Change complete. No further work remains."),
];

/// `(source state, event, target state, gates)`
///
/// A transition may name several gates. The engine evaluates them in one
/// provider invocation and completes the transition only when every named gate
/// returns `passed`.
/// There are NO `design-review` or `plan-review` states, and their absence is
/// deliberate.
///
/// Both documents are already judged on the transition out of the state that
/// produced them -- `design-semantic` and `plan-semantic` read the document
/// against its upstream and can refuse it. A review state after that judged
/// nothing: it read a document a judge had just accepted, and its only gate
/// checked that a file said `approved`.
///
/// What it did instead was launder self-approval. An agent writing
/// `{"verdict": "approved"}` into its own review file produced a permanent
/// journal entry reading "design-review approved", indistinguishable from a
/// review somebody actually performed. A record that cannot tell scrutiny from
/// its imitation is worse than no record.
///
/// The revision cycle survives without them. A rejected `design-ready` leaves
/// the run in `design`; the author fixes the document and requests again. That
/// is the same loop the `changes-requested` edge provided, minus a state whose
/// only output was a claim about itself.
///
/// `implementation-review` is kept because it is not the same shape: it reviews
/// CODE, which no earlier gate has looked at, and its approving transition
/// carries `implementation-semantic` so the approval must survive an
/// independent judgment rather than merely being recorded.
const TRANSITIONS: &[(&str, &str, &str, &[&str])] = &[
    // Two gates guard the only way out of `explore`: a deterministic schema
    // check, and a non-deterministic judgment of whether the document is really
    // intent rather than a plan in disguise. They are complementary layers and
    // neither can substitute for the other.
    ("explore", "intent-ready", "design", &["intent-ready", "intent-semantic"]),
    // Same two-layer shape as `explore`: schema and acceptance-citation are
    // decidable without a model; whether the design actually delivers the
    // intent is not.
    ("design", "design-ready", "plan", &["design-ready", "design-semantic"]),
    // Third document to carry the two-layer shape. The schema settles shape,
    // identifier integrity and design-element coverage; whether the tasks are
    // sized for a fresh worker, carry enough context, and checkpoint anywhere
    // useful is not decidable without a model.
    ("plan", "plan-ready", "implement", &["plan-ready", "plan-semantic"]),
    // The phase loop. Each request verifies ONE phase: the last one
    // implementation.json claims complete. The run stays in `implement` however
    // many phases the plan has, so the graph does not depend on plan content --
    // which it cannot, being frozen before any plan exists.
    ("implement", "phase-complete", "implement", &["phase-complete", "phase-review"]),
    ("implement", "implementation-ready", "implementation-review", &["implementation-ready"]),
    // The judge rides on the APPROVING transition, not on entry to the review
    // state. Without it the last thing between a change and `end` is an agent
    // writing `{"verdict": "approved"}` into its own review file, and the
    // journal would record that self-approval as a review having happened. This
    // is the one judgment in the run that compares the CODE to the INTENT.
    (
        "implementation-review",
        "approved",
        "end",
        &["implementation-review-approved", "implementation-semantic"],
    ),
    (
        "implementation-review",
        "changes-requested",
        "implement",
        &["implementation-review-changes-requested"],
    ),
];

/// Static guidance for one state: the authored prose, plus the verbatim judge
/// rubrics for any state whose exit is semantically judged.
///
/// Composed here from the same constants the judges read, rather than written
/// out by hand, so the published bar cannot drift from the applied one. A
/// hand-maintained summary is a second source of truth, and the author is the
/// one who pays when the two disagree.
///
/// This is also what makes the doctrine hold: static guidance must be enough to
/// know what to produce without any live provider call. While the deciding rules
/// were invisible it was not -- a document could follow every published example
/// and still fail on a rule the author was never shown.
fn state_guidance(state_id: &str, authored: &str) -> String {
    let mut out = authored.to_string();
    for subject in crate::gates::semantic::subjects_for_state(state_id) {
        out.push_str(&crate::gates::semantic::published_rubrics(subject));
    }
    out
}

pub fn workflow_graph() -> Value {
    let states: Vec<Value> = STATES
        .iter()
        .map(|(id, is_final, guidance)| {
            json!({
                "id": id,
                "final": is_final,
                "static_guidance": { "kind": "text", "text": state_guidance(id, guidance) },
            })
        })
        .collect();

    let transitions: Vec<Value> = TRANSITIONS
        .iter()
        .map(|(source, event, target, gates)| {
            json!({
                "source_state": source,
                "event": event,
                "target_state": target,
                "gate_ids": gates,
            })
        })
        .collect();

    json!({
        "initial_state": "explore",
        "states": states,
        "transitions": transitions,
        "input_declarations": [
            {
                "id": "change_id",
                "kind": "string",
                "required": false,
                "metadata": { "summary": "Short human identifier for this change." }
            },
            {
                "id": "artifact_root",
                "kind": "path",
                "required": true,
                "metadata": { "summary": "Absolute directory holding intent/design/plan/implementation documents and reviews/." }
            },
            {
                "id": "work_root",
                "kind": "path",
                "required": true,
                "metadata": { "summary": "Absolute repository directory. Validation commands run here and .loop-workflow.toml is read from here." }
            }
        ],
        "live_guidance_supported": true,
        "metadata": {
            "workflow": "software-change",
            "workflow_version": "1",
            "config_file": ".loop-workflow.toml",
        },
    })
}

/// Advisory text for `live_guidance`. Falls back to stored static guidance when
/// the run sits in a state this build no longer recognizes.
pub fn live_guidance_for(state: &str) -> Option<&'static str> {
    STATES
        .iter()
        .find(|(id, _, _)| *id == state)
        .map(|(_, _, guidance)| *guidance)
}

#[cfg(test)]
mod guidance_tests {
    use super::PLAN_GUIDANCE;
    use serde_json::Value;

    /// Pull the JSON document that follows a `--- HEADING ---` marker.
    fn example(heading: &str) -> Value {
        let start = PLAN_GUIDANCE
            .find(heading)
            .unwrap_or_else(|| panic!("guidance has no section {heading}"));
        let rest = &PLAN_GUIDANCE[start + heading.len()..];
        let open = rest.find('{').expect("section has no JSON document");
        let bytes = rest.as_bytes();
        let mut depth = 0usize;
        let mut in_string = false;
        let mut escaped = false;
        for index in open..bytes.len() {
            let byte = bytes[index] as char;
            if in_string {
                match byte {
                    _ if escaped => escaped = false,
                    '\\' => escaped = true,
                    '"' => in_string = false,
                    _ => {}
                }
                continue;
            }
            match byte {
                '"' => in_string = true,
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        let slice = &rest[open + start - start..=index];
                        return serde_json::from_str(slice)
                            .unwrap_or_else(|e| panic!("{heading}: {e}"));
                    }
                }
                _ => {}
            }
        }
        panic!("{heading}: unterminated JSON document");
    }

    fn taught_design() -> Value {
        example("--- THE DESIGN THESE EXAMPLES ARE WRITTEN AGAINST (excerpt) ---")
    }

    /// The plan we hand authors as correct must satisfy the gate we judge them
    /// with. A guidance example that its own schema rejects teaches the wrong
    /// thing and is worse than no example.
    #[test]
    fn the_good_example_satisfies_the_plan_schema() {
        let reasons = crate::gates::plan::check(
            &example("--- GOOD EXAMPLE ---"),
            Some(&taught_design()),
        );
        assert_eq!(reasons, Vec::<String>::new());
    }

    /// The bad example must be rejected by SOMETHING. It is deliberately shaped
    /// to fail on judgment rather than schema, so this pins which layer catches
    /// it -- if the schema ever starts rejecting it, the example stops
    /// demonstrating what it claims to demonstrate.
    #[test]
    fn the_bad_example_is_schema_valid_and_fails_only_on_judgment() {
        let reasons = crate::gates::plan::check(
            &example("--- THE SAME CHANGE, WRITTEN BADLY ---"),
            Some(&taught_design()),
        );
        assert_eq!(
            reasons,
            Vec::<String>::new(),
            "the bad example must pass the schema so that it demonstrates a \
             SEMANTIC failure; if the schema now catches it, either the example \
             or this claim needs updating"
        );
    }

    /// The elements the examples cite must be the elements the excerpt declares,
    /// or the coverage lesson is taught against a design nobody can see.
    #[test]
    fn the_examples_cite_the_design_excerpt_verbatim() {
        let design = taught_design();
        let elements = design["elements"].as_array().unwrap();
        assert_eq!(elements.len(), 3);
        for name in ["--- GOOD EXAMPLE ---", "--- THE SAME CHANGE, WRITTEN BADLY ---"] {
            let plan = example(name);
            let cited: Vec<&str> = plan["phases"]
                .as_array()
                .unwrap()
                .iter()
                .flat_map(|phase| phase["covers"].as_array().into_iter().flatten())
                .filter_map(Value::as_str)
                .collect();
            for element in elements {
                assert!(
                    cited.contains(&element.as_str().unwrap()),
                    "{name} does not cite {element}"
                );
            }
        }
    }
}
