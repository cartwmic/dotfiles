# Analyze Findings

<!--
STRICTLY READ-ONLY. Do not modify other artifacts. Produce a remediation
report. Severity: blocker | major | minor.
-->

**Mode:** single-model (blind cross-check; reviewer did not see the authoring conversation)
**Generated:** 2026-07-02 by analyze cross-check (opsx-superpowers)

## Check 1 — Constitution compliance

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I. Chezmoi single source of truth | compliant | Edits target chezmoi source paths (schema templates, canonical skills); no one-off machine state introduced. | — |
| II. Skills in canonical-harness pipeline | **violated** | proposal.md Impact lists the openspec-loop skill edit at `dot_pi/agent/skills/openspec-loop/SKILL.md`. That path does not exist: the skill's canonical source is `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`, and `dot_pi/agent/` holds `extensions/` (incl. the `opsx-loop` **extension**), not `skills/`. Directs an edit to a non-canonical / non-deployed location. | major (F5) |
| III. No secrets in source | inapplicable | No credentials/keys touched. | — |
| IV. Idempotent install scripts | inapplicable | No `run_once_*`/`run_onchange_*`/install scripts in scope. | — |
| V. mise owns dev-tool install | compliant | intent/design: no new tools, no new model roles; reuse existing dispatch/provenance machinery. | — |
| VI. launchd PATH | inapplicable | No plists. | — |
| VII. Termux not deployed | inapplicable | — | — |
| VIII. openspec/ workspace not deployed | compliant | Change lives under `openspec/changes/`; deployed surfaces (schema templates, canonical skills) are edited in their own source paths. | — |
| IX. Skill edits → adversarial review at Scale ≥ M | compliant (self-referential) | intent/design/constraints acknowledge Constitution IX; this very change edits existing skills and so must itself run multi-model adversarial review. No spec conflict; noted for the review artifact. | — |
| X. Memory promotion opt-in | inapplicable | follow-ups.md surfacing is explore-input, not memory `retain`. | — |

## Check 2 — EARS pattern check (major, human-triage)

| # | File:line | AC | True positive? | Suggested rewrite | Status |
|---|---|---|---|---|---|
| E1 | specs/opsx-review-convergence/spec.md:84 | "WHEN reviewer verdicts … (at least one pass and one **fail**) for 2 consecutive rounds …" | no | "fail" is a verdict *value* in a normal split-detection event, not an error condition. WHEN is correct. | n/a |
| E2 | specs/opsx-loop-orchestration/spec.md:11 | "WHEN a gating review round returns a **fail** verdict and fixes have been committed" | no (ambiguous) | A fail verdict is the loop's expected, anticipated branch (not an exceptional/unwanted event), so WHEN reads correctly; IF-THEN not required. | n/a |

No true-positive EARS misuse. All error-shaped conditionals in the deltas (e.g. workflow-schema "Invalid value falls back") already use IF-THEN.

## Check 3 — AC↔design coverage

| AC ID | Design section reference | Status | Severity |
|---|---|---|---|
| opsx-review-convergence.baseline-bounded-verdict-contract | intent "Baseline-bounded verdict contract"; proposal "What Changes" #1 | covered | — |
| opsx-review-convergence.severity-rubric-and-floor | intent "Severity floor + calibration rubric"; D2 (comparability) | covered | — |
| opsx-review-convergence.finding-routing-and-follow-ups | intent "Finding routing"; D4/D5 | covered | — |
| opsx-review-convergence.orchestrator-round-ledger | intent "Orchestrator-side round ledger"; D2/D6 | covered (see F3 on per-round count derivation) | — |
| opsx-review-convergence.trajectory-stop-and-round-budget | D2; intent "Trajectory stop + round budget"; clarify A1/I1 | covered | — |
| opsx-review-convergence.disclosure-round | D3; intent "Split-verdict protocol" | covered | — |
| opsx-review-convergence.decision-audit-landing | D4; intent "Decision-audit landing"; clarify C1 | covered (see F1/F2 on waiver/resume mechanics) | — |
| opsx-review-convergence.scope-widening-protocol | D5; intent "Prose scope + evidence-gated widening" | covered | — |
| opsx-review-convergence.advisory-surface-audit | intent "Advisory surface audit"; D-scope | covered | — |
| opsx-review-convergence.reviewer-model-stability | intent "Reviewer-model stability"; clarify I2 | covered | — |
| opsx-post-impl-review.* (3) | D3/D6; proposal Modified Capabilities | covered | — |
| opsx-loop-orchestration.* (3) | D1 (thin bindings); intent | covered | — |
| opsx-workflow-schema.* (2) | D6; proposal | covered | — |
| "Full re-review every round" (intent) | intent "Full re-review"; loop-orch "full-diff blind re-review each round" | partial — asserted in requirement prose, no dedicated scenario forbidding delta-scoped rounds | minor |

## Check 4 — design↔ADR promotion candidates (Scale ≥ L)

This is a skill-edit change (Constitution IX) with cross-capability reach; design self-scores every decision as an ADR candidate. Flagged for the adversarial-review / archive promotion step (schema offers promotion at archive, not here).

| Decision | 4-point score | ADR-candidate? | Rationale |
|---|---|---|---|
| D1 single capability + thin bindings | 4 | yes | Constrains future spec layout; see F8 (binding vs. restating). |
| D2 trajectory on counts not identity | 4 | yes | Load-bearing; see F3 (count derivation). |
| D3 one disclosure round | 4 | yes | Defines the sole sanctioned blindness break; see F6. |
| D4 decision-audit landing | 4 | yes | Loop UX / human-stop contract; see F1/F2/F4. |
| D5 prose scope + evidence-gated widening | 4 | yes | Constrains intent authoring. |
| D6 prose + sealed fields, mechanization deferred | 3 (borderline) | yes if gate mechanization follows | Reversible-by-design; front-matter format pre-staged. |

## Check 5 — Duplicate detection

| # | Locations | Restated constraint | Action |
|---|---|---|---|
| Dup1 | opsx-review-convergence "Scope Widening Protocol" + opsx-loop-orchestration "Scope Widening Handled In The Loop" | Both carry full normative SHALL prose for "widen with logged evidence when required to meet frozen intent, else route to follow-ups.md." | differentiate — bind by reference (F8); mitigates archive-time drift (domain #14). |
| Dup2 | opsx-review-convergence "Orchestrator Round Ledger" + opsx-post-impl-review "Round Ledger Sealed In Code Review" | Ledger row shape restated. | keep both — deliberately differentiated (generic definition vs. code-review.md sealing surface) per D1; acceptable. |

## Check 6 — Implementation language in specs

| # | AC ID | Tech mentioned | Rewrite suggestion |
|---|---|---|---|
| — | — | `follow-ups.md`, `code-review.md`, `review.md`, `review_max_rounds`, `review_mode: disclosure-consensus`, front-matter | No action — these are the opsx-superpowers **schema domain vocabulary** (artifact and sealed-field names), which the workflow-schema/post-impl-review capabilities legitimately specify. No leaked infra tech (no DB/library/TTL). |

## Check 7 — Unresolved clarify findings

| # | clarify.md ref | Status | Risk |
|---|---|---|---|
| — | A1, A2, I1, I2, C1, C2, C3, C4 | all answered (0 unanswered, 0 deferred) | Verified each resolution is reflected in the delta spec: A1/I1 → trajectory "two most recent consecutive rounds" + zero-blocker-budget carve-out; I2 → reviewer-stability "UNLESS the user has reconfigured" scenario; C2 → ledger "(…; the pre-implementation analyze artifact …)"; C1 → waiver scenario. No residual unresolved clarify risk. |

## Findings (severity-ranked)

### F1 (blocker) — Budget-exhaustion landing contradicts "user ruling resumes the loop" for a `fix` ruling
`opsx-review-convergence.trajectory-stop-and-round-budget` makes stop condition (c) a **SHALL**: stop when completed rounds ≥ `review_max_rounds`. `decision-audit-landing`'s "User ruling resumes the loop" scenario says on a user `fix` ruling the orchestration MAY resume review rounds and "the round ledger SHALL continue (**not reset**)." After a budget-exhaustion landing, completed-rounds already ≥ budget; a resumed round makes it budget+1, which still satisfies (c)'s SHALL-stop, so no further blind round can dispatch — yet `fix` is the primary ruling and inherently needs another round to verify. No budget-extension-on-ruling is defined. The two ACs are normatively irreconcilable on the most common landing→resume path; tasks generated from this would encode a loop that cannot act on a user `fix` after a budget stop. **Failure scenario:** budget=5, five fail rounds → budget stop → landing → user rules "fix" → fixes committed → orchestration tries to resume → condition (c) still holds → re-stops → re-lands the same audit indefinitely (bounded only by the blunt stall/turn backstop). **Fix:** define that a user `fix`/`re-scope` ruling raises or re-baselines the budget (e.g., grants N additional rounds), or scope "resume" to trajectory/split stops only and state budget stops require an explicit budget bump.

### F2 (major) — Waiver→pass has no defined path to a `pass` Verdict without violating the reviewer-authored-verdict rule
`decision-audit-landing` (C1) says a user-waived P0/P1 is "removed from the open P0/P1 set, so the severity floor's `pass` condition is satisfied." But the live `opsx-post-impl-review` "Post Apply Code Review Artifact" requirement makes the review **subagent** author `code-review.md`'s `Verdict` (orchestrator "SHALL only trigger and collect it"), the `Verdict` is freshness-bound to the reviewed HEAD, and provenance is adapter-stamped. A waiver moves no HEAD and dispatches no new review, so the sealed `Verdict: fail` at that HEAD persists; the archive gate ("refuse to archive unless code-review.md Verdict is pass") still reads fail. Nothing defines how the floor's satisfied `pass` becomes the *sealed* `Verdict` the gate reads without the orchestrator overwriting a reviewer-authored, adapter-stamped, freshness-bound field — which the live spec forbids. **Failure scenario:** one open P1, user waives at the audit → open set empties → but code-review.md still reads `Verdict: fail` (reviewer-sealed, HEAD unchanged) → archive gate blocks → change cannot land despite the human authorization the landing promised. **Fix:** specify a distinct sealed "waiver clearance" field the gate/floor reads (separate from the reviewer `Verdict`), so a waiver satisfies the gate without mutating reviewer-authored provenance.

### F3 (major) — Per-round P0+P1 count is undefined across multiple blind reviewers, undermining the "comparable across rounds" hard dependency
The trajectory stop, the converged stop, and intent's explicitly-named "hard dependency" (comparable severity counts) all consume a single per-round `P0+P1` count. But a gating round dispatches **N blind reviewers** (multi-model is the normal case), each producing its own free-text finding set, and D2's own argument — "blind free-text findings do not normalize across fresh reviewer contexts" — applies *within* a round across reviewers, not only across rounds. The ledger requirement records "per-severity finding counts (P0/P1/P2/P3)" (one set per round) and "per-reviewer verdicts" (plural) but never defines how N reviewers' findings collapse into the round's counts (sum double-counts shared defects; union cannot dedup without the normalization D2 says is impossible). The live "converged findings" consolidation exists for code-review but is not wired to this ledger, and its subjectivity is exactly the comparability risk. **Failure scenario:** round 2 and round 3 each have 3 real blocking defects, but reviewer verbosity/overlap yields counts 4 then 4 (or 3 then 5) purely from consolidation choice → trajectory stop trips (or fails to) on an artifact of counting, not real progress. **Fix:** define the per-round count derivation (which consolidation step, dedup rule, whose set) before trajectory logic is implementable deterministically.

### F4 (major) — Decision-audit landing is not reconciled with the opsx-loop-kickoff continuation engine
The landing "SHALL halt review cycling and present the user a tiered decision audit … SHALL NOT continue dispatching review rounds," and "the user rules; the loop resumes." But the live `opsx-loop-kickoff` extension — which this change does **not** modify — re-injects a worker turn on *any* red gate and clears the loop only on green gate, budget exhaustion, stall detection, interrupt, or manual clear; injected directives instruct "run autonomously — not to pause for … user confirmation." With open P0/P1, `code-review.md` Verdict is fail → gate red → the extension re-injects another continuation turn after the landing turn ends. Nothing defines a "landing = await-human" stop signal the extension honors, so the landing either re-presents the audit every turn until the blunt stall/budget backstop clears the loop, or relies on undefined harness question-pause semantics — and once the loop is stall/budget-cleared, "the loop resumes" (which implies the same active loop continues) no longer holds. This directly weakens the intent's "never an unbounded escalation." **Failure scenario:** landing fires → worker turn ends with red gate → kickoff injects "resume the change, do not pause" → orchestrator re-lands → repeat until stall detection bails out, never cleanly waiting on the user. **Fix:** define how the landing signals the kickoff continuation engine to pause (or that landing sets a state the extension treats as stop-and-await), acknowledging opsx-loop-kickoff is out of this change's modified set.

### F5 (major) — proposal Impact directs the openspec-loop skill edit to a wrong, non-canonical path (Constitution II)
proposal.md Impact "Skills" lists `dot_pi/agent/skills/openspec-loop/SKILL.md`. Verified on disk: no `dot_pi/agent/skills/` exists; the skill's canonical source is `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`, while `dot_pi/agent/extensions/opsx-loop/` is the *pi extension* (the opsx-loop-kickoff capability). The Impact conflates the skill (canonical harness path, Constitution II) with the extension. Taken literally by tasks/apply, edits land in a non-deployed / non-existent path (domain invariant #4: `.pi/`-style paths are symlink targets, not sources). **Failure scenario:** tasks author writes file contracts against `dot_pi/agent/skills/openspec-loop/SKILL.md`; the change either edits the wrong file or a machine-only path, and the real canonical skill is never updated. **Fix:** correct Impact to `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`, and separately name the extension if the kickoff extension is genuinely in scope.

### F6 (minor) — Disclosure-consensus (non-blind) satisfies multi-model gating, but the live "adversarial path is conducted blind" scenario is not reconciled
`opsx-post-impl-review` delta "Disclosure Consensus Review Mode" adds a **non-blind** mode that "SHALL satisfy a gating-required multi-model adversarial code review." The live "Adversarial Review With Degradation" requirement's scenario states the adversarial path "SHALL be conducted **blind** over the diff." The delta is authored as ADDED (not MODIFIED), so the live blind-adversarial normative text is left standing beside a non-blind mode that claims to satisfy the same gate. intent sanctions this as "the only sanctioned blindness break," so it is behaviorally intended, but the spec hygiene is incomplete. **Fix:** MODIFY the live adversarial requirement to carve out `disclosure-consensus`, or add a scenario reconciling "blind" with the one bounded disclosure exception.

### F7 (minor) — Analyze-round ledger requirement has no field/template surface
`orchestrator-round-ledger` binds the ledger into "the pre-implementation analyze artifact for analyze-type gating rounds," and clarify C2 broadened the requirement to cover analyze rounds. But `opsx-workflow-schema` "Convergence Template Support" adds ledger fields only to the `code-review.md` template; the analyze template gets no ledger fields, and C2 explicitly defers the analyze field-format. The SHALL is thus currently unexecutable for multi-round analyze (Scale-L adversarial-review) gating — no artifact surface to seal into. **Fix:** either soften the analyze clause to behavioral-only (matching C2's stated deferral) or add the analyze template fields; as written the normative SHALL and the deferred surface disagree.

### F8 (minor) — Duplicated normative scope-widening prose invites archive-time drift
See Dup1. `opsx-review-convergence.scope-widening-protocol` and `opsx-loop-orchestration.scope-widening-handled-in-the-loop` both carry full SHALL prose for the same widen/route rule. D1's stated design is "thin bindings" that reference the single source, but the loop-orchestration AC restates the rule rather than binding to it. Two full normative copies in different capability specs can diverge on future edits (domain #14: MODIFIED must carry full content). **Fix:** reword the loop-orchestration requirement to bind to `opsx-review-convergence`'s protocol by reference rather than restating its normative content.

## Outstanding risks

- **F1** is a hard normative contradiction on the primary landing→resume path — must be resolved before tasks.
- **F2/F3/F4** are behavioral gaps in the three load-bearing mechanisms (waiver clearance, trajectory count, landing↔loop handoff); each is implementable only after a design decision the specs currently omit. Track to resolution before archive.
- **F5** is a factual/path error that will misdirect the tasks file contracts if not corrected.
- Doneness interplay (checked, no finding): a code-review waiver clears only the code-review gate; the independent doneness judge can still block on intent-satisfaction — consistent defense-in-depth, no contradiction, but the decision audit surfaces review findings only (not doneness gaps), which is acceptable given doneness has its own gate.

## Summary

- Blockers: 1 (F1) → MUST be resolved before tasks artifact is generated
- Major findings: 4 (F2, F3, F4, F5) → confirm/resolve before archive
- Minor findings: 3 (F6, F7, F8)
- **Gate status:** BLOCKED on 1 blocker

**Readiness verdict:** BLOCKED — 1 blocker, 4 major, 3 minor; not READY for tasks until F1 is resolved.
