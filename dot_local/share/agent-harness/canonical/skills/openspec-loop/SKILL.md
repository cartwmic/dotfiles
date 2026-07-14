---
name: openspec-loop
description: Drive an opsx-superpowers change to completion as a single orchestrator agent, advancing until opsx gate is green and delegating every review/validation-judgment step to a blind subagent. Use after an explore session has frozen intent.md, to autonomously complete propose→apply→archive behind the deterministic gate.
license: MIT
compatibility: Requires the opsx gate CLI and an opsx-superpowers change. Subagent dispatch and loop continuation are capability hooks that degrade to inline.
---

# openspec-loop

**Announce at start:** "I'm using the openspec-loop skill."

Single-orchestrator, gate-driven loop. One agent stays in control, consults
`opsx gate` for the next failing check, performs the next step, and repeats until
the gate exits 0. Reviews are delegated to blind subagents judged against a frozen
baseline. This is the harness-neutral workflow brain; the loop runtime (continuation
budget) and subagent dispatch are adapters.

## Preconditions

- `intent.md` exists in the change dir (frozen by `openspec-explore`). It is the
  immutable baseline; never edit it without explicit human authorization.
- `opsx gate` is on PATH. The gate — not your judgment — defines "done".

**Tier vocabulary.** Scale is `XS | S | M` plus an optional boolean `full_rigor`
front-matter key (default false). `full_rigor: true` restores the former L/XL extras
(standalone clarify + blind analyze dispatch + an independently dispatched blind
doneness judge). Plain Scale M folds clarify into the proposal, runs analyze
deterministic-only, and rides doneness on the code-review dispatch (below). The
2-model blind adversarial code review's `code_review_mode` DEFAULTS to
`gating-required` at Scale M (with or without `full_rigor`) and to `advisory` below M
when the key is absent; the gate derives that default fail-closed, so omitting the key
at M can never skip the review. XS/S may raise it to `gating-required` explicitly.

## Worktree-always execution & writeback discipline

Worktree execution is the ONLY execution model at EVERY Scale, XS included. Apply
runs ensure → locator capture → implement → review → merge → cleanup in an isolated
`opsx/<change>` worktree; there is no same-tree execution path, no tier that opts out,
and no `worktree_mode` switchboard key (a `worktree_mode` key in review.md
front-matter is a fail-closed gate red naming the delete-the-key remedy). Implement in
the worktree; gate with `--worktree <path>`.

**Writeback owner split (keeps sealed verdicts fresh).** Sealed verdicts bind to the
`opsx/<change>` worktree branch HEAD, so land each artifact on the tree that owns it:
- **Worktree branch:** task checkboxes in `tasks.md` (the gate reads tasks.md
  worktree-side), the implementation diff, and the verdict artifacts the gate
  reads worktree-side (verify.md, code-review.md — including its embedded Round
  Ledger section — doneness.md; verdict-file-only commits are exempt from the
  range-staleness check by design).
- **Integration checkout:** `loop_hold`/`loop_hold_reason`, follow-ups.md routing,
  Execution Notes, and the review.md-hosted `Fidelity Round Ledger` — orchestrator
  bookkeeping per the writeback-owner discipline (a ledger rides its HOST artifact's
  tree: code-review.md's Round Ledger is worktree-side with its host, review.md's
  Fidelity Round Ledger is integration-side with its host), so bookkeeping never
  moves the verdict-bound worktree HEAD.
- **Backstop:** a bookkeeping commit MISPLACED onto the `opsx/<change>` worktree
  branch moves the verdict-bound HEAD and therefore STALES the sealed verdicts via the
  existing range-freshness check — a loud fail-closed gate red whose remedy is
  re-review. Misplacement is always detected, never silently green.

**Judged inputs committed before any fidelity dispatch.** intent.md, design.md, and
`specs/**` edits land COMMITTED on the integration checkout BEFORE any design-fidelity
dispatch — the fidelity digests bind committed integration-checkout content, so an
uncommitted judged input is invisible to digest and judge accountability. Editing a
judged input on the worktree branch is a writeback-owner-discipline violation.

## The cycle

Each turn:

1. Run `opsx gate <change> --worktree <path>` (worktree execution is the ONLY model
   at every Scale including XS — apply always ran ensure → locator capture → implement
   → review → merge → cleanup in the `opsx/<change>` worktree, so a worktree path
   always exists).
   - Exit 0 → **stop**; report the change ready to archive.
   - Non-zero → read the report. Findings are emitted in lifecycle dependency
     order; take the **earliest blocking** `GATE-FAIL` line.
2. Address exactly that failure (one unit of progress), then commit. Every commit
   the loop drives on the INTEGRATION checkout SHALL be path-scoped to the change
   directory — `git commit -m "<msg>" -- openspec/changes/<change> <other change-scoped paths>` (message flag BEFORE the `--` pathspec terminator)
   — never a bare `git commit -a`/`git add -A`, so an unrelated dirty file in the
   integration tree can never ride along in a loop commit (A2).

   | Earliest failure | Action |
   |---|---|
   | missing artifact | author it (`openspec-propose`/edit), tracing to `intent.md` |
   | unchecked tasks | implement the next task under its file contract; check it off |
   | failing validation command | fix the code; never weaken the gate |
   | missing/failing review (clarify/analyze/code-review/verify) | **dispatch a blind subagent** (below) |
   | failing `doneness` (the sole remaining failure at Scale ≥ M) | seal `doneness.md`: at plain M via the code-review dispatch's final section (designated reviewer = first `review` model); at full_rigor via the **independent blind doneness judge** (below) |

3. Loop. Bound by `loop_max_iterations` (review.md front-matter), mapped onto the
   runtime turn budget so a single budget governs the loop. On budget exhaustion,
   stop and **preserve** the worktree/branch for inspection.

## Subagent review against baseline (mandatory)

Every review or validation-**judgment** step is delegated to a blind subagent — the
orchestrator never self-authors a verdict. The subagent judges current work against
the phase-appropriate baseline:

| Phase | Baseline the subagent judges against |
|---|---|
| clarify | `intent.md` |
| analyze | `intent.md` + proposal + specs + design + constitution + domain |
| code-review (post-apply) | `intent.md` + proposal + specs + design + plan + tasks status, over the diff `Diff Base SHA..HEAD` |
| doneness (intent-satisfaction) | frozen `intent.md` + the delta acceptance criteria, over the diff `Diff Base SHA..HEAD` |

The subagent authors the verdict artifact by FILLING the schema's shipped
template — `templates/verify.md`, `templates/code-review.md`,
`templates/doneness.md` under
`~/.local/share/openspec/schemas/opsx-superpowers/` — never by free-writing
the gate-parsed fields (the templates already carry the exact field formats
the gate reads: `**Verdict:**`, `**Doneness:**`, `reviewer-provenance:`, Diff
Base SHA, reviewed range, `review_mode`). For Constitution-IX changes
(existing-skill edits) the code-review must be multi-model adversarial; a
`degraded-single-model` verdict does **not** satisfy the gate — `opsx gate`
and archive treat it as failed.
(opsx-skill-integration.openspec-loop-orchestrator-skill-exists)

**Findings file is the sole verdict source.** For EVERY reviewer/judge dispatch (code
review, doneness, design fidelity, judged clarify/analyze), derive the verdict, the
findings, AND the attestation EXCLUSIVELY from the subagent's findings OUTPUT FILE
(the dispatch's `output:` file). The conversational reply is NEVER a verdict input —
no matter how confidently it claims a pass. A findings file that is ABSENT, or that
lacks the required verdict line/attestation fields, consolidates as INVALID (not
fail): excluded from gating, the round ledger, and the round budget; incident
recorded; re-dispatch or repair the reviewer set. Never infer a verdict from a
partial file or from the reply.
(opsx-adversarial-review.findings-file-sole-verdict-source)

### Verdict contract (embed in every gating reviewer prompt)

A gating reviewer may FAIL only for (a) a **frozen-baseline violation** — intent.md,
delta ACs, design decisions, constitution/domain — or (b) an **objective
correctness/security defect**, even where the baseline is silent. Taste, style,
alternative-design preference, beyond-scope demands → advisory (P2/P3), cannot gate.
Embed the severity rubric verbatim (single lens; cite the violated baseline element):
P0 confirmed baseline violation / critical defect · P1 must-fix within the contract ·
P2 should-fix advisory · P3 nit. **Verdict: pass ⇔ no open P0/P1**; open P2/P3 are
recorded as warnings and never force another round.
(opsx-adversarial-review.baseline-bounded-verdict-contract,
 opsx-adversarial-review.severity-rubric-and-floor)

## Review convergence (mandatory)

Gating review rounds **converge or land** — they never spin. Full-diff blind
re-review each round; the discipline below contains the cost.

**Round ledger (orchestrator-maintained).** After every gating round, append a row
to the review artifact's Round tracker (code-review.md for diff reviews; a `Round
Ledger` section appended to analyze.md for analyze-type rounds): round number, mode,
consolidated severity counts — **max across reviewers per severity**, no cross-
reviewer finding matching — per-reviewer verdicts, reviewed HEAD.
BLINDNESS RED FLAGS — never include in a blind reviewer prompt: the ledger, prior-
round findings, another reviewer's output. Only the single marked disclosure round
discloses. PROVENANCE RED FLAG — a sealed multi-round Verdict with no ledger row is
a provenance defect: repair the ledger before archive.
(opsx-adversarial-review.orchestrator-round-ledger,
 opsx-adversarial-review.prose-surface-fidelity)

**Tree-identity attestation (every blind dispatch).** Every reviewer/judge prompt
requires the subagent to record, as its FIRST findings-output lines, `Attested
HEAD: <verbatim git rev-parse HEAD — full 40-hex>` and `Attested Path: <verbatim
git rev-parse --show-toplevel>` from its own execution context (always pin the
dispatch `cwd` to the reviewed tree). Count a verdict ONLY when the attested HEAD
literal equals the dispatched range head's full SHA AND the attested path
realpath-equals the dispatched tree root. The dispatched tree is PURPOSE-KEYED, never
keyed to whether an implementation worktree happens to exist: post-implementation
dispatches (code review, doneness) attest the `opsx/<change>` WORKTREE — the path
check discriminates it from the integration checkout, and an integration-checkout
attestation is INVALID for them; proposal-phase judgments (clarify, analyze, design
fidelity) attest the INTEGRATION CHECKOUT ALWAYS — including a fidelity re-judge
dispatched AFTER the implementation worktree exists (these judgments never receive
their own worktree; their judged inputs live in the integration checkout), the
attested path equals the canonicalized integration-checkout root and the attested
HEAD equals the integration-checkout HEAD at dispatch (HEAD carries the
discrimination). Missing/non-40-hex/mismatched ⇒ the
verdict is **INVALID — not fail**: it never satisfies multi-model gating, never
enters the ledger as a reviewer verdict, never counts toward `review_max_rounds`;
record the incident and re-dispatch. TWO consecutive all-invalid attempts of the
same round ⇒ stop and route to the decision-audit landing with a
dispatch-integrity error (never retry unbounded). Seal `**Attested HEAD:**` into
code-review.md (and doneness.md for the full_rigor independent judge) only when
every counted reviewer attested the same value.
(opsx-adversarial-review.reviewer-tree-identity-attestation)

**Read-only round window (dual-tree snapshot/void/restore).** Immediately before
dispatching a round's reviewers/judges and identically after the last returns,
capture `git rev-parse HEAD` + `git status --porcelain=v1` of the REVIEWED WORKTREE
AND (when it is a different tree — the worktree-always norm) ALSO the INTEGRATION
CHECKOUT. The ONLY excluded paths are the dispatched change's own bookkeeping files —
`openspec/changes/<change>/review.md` and `openspec/changes/<change>/follow-ups.md`
(the only in-window writes permitted); the change's JUDGED INPUTS and remaining
artifacts (intent.md, design.md, `specs/**`, proposal.md, clarify.md, tasks.md,
plan.md, verdict artifacts) are NEVER excluded, so a judge mutating the very files it
judges voids the round. For the integration checkout, an intervening commit or
porcelain delta does NOT void WHEN it exclusively touches OTHER changes'
`openspec/changes/<other-change>/` paths (sibling concurrent authoring — committed OR
uncommitted) OR the dispatched change's own bookkeeping files (review.md,
follow-ups.md — committed OR uncommitted); anything else (code, specs, templates, the
dispatched change's judged inputs) VOIDS. A voided round ⇒ ALL its verdicts INVALID;
restore surgically and SYMMETRICALLY — `git restore` only tracked paths whose status
changed across the window, delete only untracked paths introduced in-window, with the
restore AND delete sets EXCLUDING other changes' `openspec/changes/<other-change>/`
paths (a sibling's concurrent authoring is never restored or deleted) and the
dispatched change's own excluded paths; NEVER blanket `git clean`, never pre-existing
untracked/ignored state — and record the incident in the ledger/Execution Notes.
(opsx-adversarial-review.read-only-reviewer-dispatch)

**Migration sweep before round 1.** WHERE the change declares
`openspec/changes/<change>/sweep.txt` (retired tokens / forbidden patterns,
one ERE per line), run `opsx sweep <change>` and resolve ALL hits BEFORE
dispatching the first gating review round — the whole stale-prose defect
class dies in one deterministic pass instead of one instance per blind round.
The gate enforces the same sweep conditionally, but pre-round-1 resolution is
what saves review rounds.
(opsx-cli.migration-completeness-sweep-command)

**Continuation/stop conditions (quiet-round default).** After each completed
gating round: FIRST attempt and land the fixes for that round's findings,
THEN evaluate IN ORDER — evaluating before fixing makes (b) unreachable and
kills autonomous convergence:

| # | Condition | Rule | Then |
|---|---|---|---|
| a | quiet round | latest round P0+P1 = 0 (max across reviewers) | seal `Verdict: pass`; stop rounds |
| b | converging | findings open AND change-scoped fixes landed since the round AND completed rounds < `review_max_rounds` | dispatch next round autonomously — NO human ruling |
| c | thrash guard | findings open AND no fix landed (progress signal absent) | disclosure/landing |
| d | hard cap | completed rounds ≥ `review_max_rounds` (absent/invalid ⇒ 5) | disclosure/landing — regardless of trajectory |

The **progress signal is change-scoped**, per round type: post-apply rounds —
the reviewed worktree branch HEAD moved (bookkeeping artifacts — verdicts,
ledger, follow-ups.md, review.md, clarify.md — are NEVER committed on the
reviewed branch; they land on the integration checkout, so only
implementation fixes move it); analyze-type rounds (pre-apply, no worktree) —
a commit since the round's reviewed HEAD touching the change's AUTHORED fix
surfaces (proposal.md, design.md, specs/**, tasks.md, plan.md); ledger seals,
follow-ups routing, note-logging, and sibling-change commits never count.
Under (b), the round TYPE still follows the disclosure trigger below —
converging decides WHETHER to continue, never whether the round is blind.

WHERE review.md front-matter sets `review_budget_mode: land-on-stop` (opt-in,
and the reading of any unknown value), the pre-quiet-round behavior governs:
stop on a flat-or-rising P0+P1 across the two most recent rounds, or on
budget exhaustion, and land for a ruling at every stop.

A stop with open P0/P1 **never** seals pass and **never** silently continues
— under either mode; quiet-round only automates CONTINUE, never SEAL.
(opsx-adversarial-review.trajectory-stop-and-round-budget,
 opsx-workflow-schema.review-budget-mode-front-matter)

**Disclosure round (max 1 per change).** WHEN verdicts split (≥1 pass + ≥1 fail on
the same HEAD) for 2 consecutive rounds, or a stop fires while a split is present:
run ONE deliberately non-blind consensus round — same reviewers, each sees the
others' findings, produce a joint findings set + verdict — sealed with
`review_mode: disclosure-consensus` (satisfies multi-model gating only when ≥2
distinct models participated). Never a second disclosure round.
(opsx-adversarial-review.disclosure-round)

**Decision-audit landing.** IF open P0/P1 remain after stops + any disclosure round:
halt review cycling and present the user a tiered audit — 🔴 need-your-call /
🟡 worth-a-glance / 🟢 trust-me — covering open findings, autonomous fix decisions,
and every Scope Expansions entry. NEVER force green; NEVER dispatch reviewer models
beyond the resolved `review` set to break a deadlock. Halt loop continuation by
setting `loop_hold: true` + `loop_hold_reason` (pointing at the audit) in the
review.md front-matter of the INTEGRATION checkout — the copy the loop host reads;
writing only the worktree copy split-brains the hold into invisibility — and commit
it as part of the landing turn. NEVER clear a loop_hold yourself: clearing is
reserved to the human named re-arm (`/opsx-loop <change>`). WHERE the host has no
loop_hold support, stop committing so stall detection ends the loop — in both cases
present the audit once, not every re-injected turn.
(opsx-loop.terminal-landings-set-the-loop-hold) User rulings: **fix** → grants a
recorded round-budget extension (note in ledger), resume rounds (ledger continues,
not reset); **waive** → record the finding user-waived in follow-ups.md AND re-seal
`Verdict: pass` with the `waived_by_user` field (waived findings + rationale,
reviewed range unchanged) — pass by explicit human authorization, never
self-authored; **re-scope** → back to explore/propose.
(opsx-adversarial-review.decision-audit-landing,
 opsx-adversarial-review.waiver-sealed-pass)

**Scope widening (evidence-gated).** intent.md states intended scope in prose. WHEN
a finding falls outside it: required to meet the frozen intent's outcomes (cite
evidence) → widen — log a review.md `Scope Expansions` entry (what + evidence)
BEFORE committing the fix, treat as in-scope; not required → route to
`follow-ups.md` (create from the template on first routing), advisory, never gates.
Intent MEANING is never edited — if a fix would change it, halt and ask. Every
widening surfaces at the landing or gate-green.
(opsx-adversarial-review.scope-widening-protocol)

**Advisory surface audit (property-style intents).** WHERE the intent claims a
codebase-wide property ("no X anywhere", "impossible via code") rather than an
enumerable diff: dispatch ONE advisory blind surface-enumeration audit before the
first implementation task; feed its output into tasks.md and the intent's
stated-scope prose. Advisory output routes to tasks/scope/follow-ups — it never
triggers a fix-then-re-review cycle.
(opsx-adversarial-review.advisory-surface-audit)

**Reviewer-model stability.** All blind rounds of a change use the `review` role
set resolved at the first gating round. RED FLAG — "one more model to confirm" /
mid-change reviewer additions: prohibited; the stop conditions and landing govern.
Exception: the user explicitly reconfigures the `review` role (log it in the
ledger; applies to subsequent rounds only).
(opsx-adversarial-review.reviewer-model-stability)

Capability hook `subagent-dispatch`: WHILE `/opsx-loop` is armed, route role-bound
review/impl/(opt-in author) work through `opsx_dispatch` (generic `subagent` is
muted). WHILE disarmed, use the host adapter (e.g. pi-subagents / `subagent`) when
registered; if none, run inline, mark `review_mode: degraded-single-model`, and tell
the user it does not satisfy a gating-required review — recommend running
`adversarial-review-cycle` manually.

### Doneness judge (Scale ≥ M, `doneness_mode: required`)

The deterministic gate proves only *mechanical* doneness. Intent-satisfaction is judged
by a **blind reviewer/judge subagent**, sealed into a separate `doneness.md`, and read by
the gate (which runs no model). The tree-identity attestation preamble and read-only
round window (above) apply to this dispatch too — the full_rigor independent judge's
attested HEAD is sealed into doneness.md and gate-bound to its recorded Reviewed Range
head. Dispatch it **after the mechanical gate checks pass** and
no fresh `satisfied` verdict exists (i.e. `doneness` is the sole remaining `GATE-FAIL`).
The DISPATCH CHANNEL is tier-conditioned — the sealed artifact and its fields are
identical either way:

- **Plain Scale M (no `full_rigor`): COMBINED dispatch.** Do NOT open a separate
  doneness dispatch. Instead the doneness question rides the blind code-review dispatch
  as a dedicated, final required section, answered by ONE DESIGNATED reviewer. WHERE the
  resolved `review` role has more than one model, the designated reviewer is the FIRST
  model in that set, so exactly one verdict is sealed. That reviewer writes `doneness.md`
  SEPARATELY from the code-review findings, stamped `review_mode: blind-single-judge`.
  Co-locating the section never weakens the 2-model blind code review.
- **Scale M + `full_rigor`: INDEPENDENT dispatch.** Dispatch a separate blind doneness
  judge subagent (distinct from the code-review reviewers) — the current top-tier
  behavior.
- Either way, the judge runs on the resolved **`review`** role model (`opsx models
  review --change <name>`; no new role). Baseline = frozen `intent.md` + the delta ACs,
  judged over `Diff Base SHA..HEAD`. Charter: rule `satisfied` **only** when the frozen
  intent's stated outcomes are met — never demand beyond-scope / gold-plated work.
- The subagent (not the orchestrator) authors `doneness.md` from `templates/doneness.md`:
  `Doneness: satisfied|not`, the unmet `## Gaps` when `not`, an adapter-stamped `Judge`
  provenance field with `review_mode: blind-single-judge` (one independent blind judge —
  the normal case; `adversarial-multimodel` only when ≥2 distinct judge models were
  actually dispatched), `Frozen-Intent SHA` = `sha256(intent.md)`, the immutable `Diff
  Base SHA`, and `Reviewed Range` = `Diff Base SHA..HEAD`.
- **Freshness:** a new commit invalidates a prior verdict — re-dispatch the judge against
  the current HEAD rather than reuse a stale `doneness.md`.
- **No dispatch adapter:** do NOT seal a `degraded-single-model`-stamped `satisfied`
  verdict — leave `doneness.md` absent or seal `Doneness: not`, and tell the user a green
  doneness verdict is reachable only via a dispatch-capable harness or an explicit
  `doneness_mode: waived` with a non-empty `doneness_waiver_rationale`. (This keeps the
  adapterless state mapped to the loop's bounded stall signal instead of spinning.)

(opsx-loop.doneness-judge-dispatch,
 opsx-loop.subagent-review-against-baseline,
 opsx-adversarial-review.blind-scope-anchored-judge)

## Role models (opsx models)

The orchestrator CONSUMES harness-neutral model config (it does not own it). The
opsx-loop pi extension exports `OPSX_AUTHOR_MODEL` / `OPSX_REVIEW_MODELS` /
`OPSX_IMPL_MODEL` / `OPSX_AUTHOR_IN_SESSION` on loop start; from any harness, resolve
directly with `opsx models <role> --change <name>` (values are already
provider-qualified).

### Armed loop (`/opsx-loop` active)

WHILE the loop is armed, role-bound review / impl / (opt-in author) dispatch MUST
go through `opsx_dispatch` — NOT the generic `subagent` tool with a soft-honored
`model:` argument (`subagent` is muted for the armed session).

- Call `opsx_dispatch({ role: "review"|"impl"|"author", task, agent? })`.
- Role is the sole model source: any caller `model` is ignored.
- `role: "review"` — ONE call; the tool auto fan-outs one spawn per configured
  review model in list order. Do NOT loop callerside over review models.
- `role: "impl"` — ONE call; tool forces the resolved impl model.
- `role: "author"` — only when `OPSX_AUTHOR_IN_SESSION` is `false` (opt-in
  delegated authoring); otherwise author in-session with the
  `<!-- authored: in-session -->` marker.
- Unset role → `opsx_dispatch` refuses with an actionable `opsx models set`
  hint. Treat that refusal as correct — do NOT fall back to the session model
  and do NOT retry via generic `subagent`.

### Disarmed sessions (no loop)

WHILE no loop is armed, skills MAY use the generic `subagent` tool. Pass each
configured review/impl model verbatim as `model:` when known. Unset roles fall
back to the session/default model — never hard-fail on the disarmed path.
`opsx_dispatch` is armed-loop-only; do not require it when disarmed.

(opsx-skill-integration.skills-honor-configured-role-models)

## Stop conditions

- `opsx gate` exits 0 → ready to archive (the loop does not itself archive).
- Budget exhausted → stop, preserve worktree, report remaining failures.
- A clarify blocker or adversarial 🔴-tier decision needing the owner → pause and ask.
- Review convergence stop (thrash guard / hard cap — or treadmill/budget under
  `land-on-stop`) with open P0/P1 → decision-audit landing (see Review
  convergence); the loop halts until the user rules. Converging rounds with
  fixes landing are NOT a stop — they continue autonomously.
- ANY terminal landing that awaits a human ruling (decision audit, green report
  already presented, blocked state) → set `loop_hold` + reason on the
  integration-checkout review.md instead of relying on prose or stall burn;
  never clear it yourself.
  (opsx-loop.terminal-landings-set-the-loop-hold)

## Harness-agnostic fallback

With no loop-continuation adapter, the workflow still runs via the `opsx loop` bash
driver (Ralph-style, `AGENT_CMD`-parameterized) calling this same prompt and gate.
Deleting the kickoff adapter loses convenience, not the workflow.
