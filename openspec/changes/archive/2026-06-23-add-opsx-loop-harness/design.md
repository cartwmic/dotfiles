# Design — add-opsx-loop-harness

## Context

opsx-superpowers today declares structure but enforces almost nothing: per-Scale
gating "lives in the skills" (README), `openspec validate` checks only structure,
and every quality gate is prose an LLM can skip. The user wants an
explore→loop flow: agree on intent interactively, then have a single orchestrator
agent drive a change to completion behind a deterministic gate, integrated into
the harness but not coupled to it. This design realizes that with a harness-neutral
enforcement spine plus thin per-harness adapters, reusing the existing `goal`
extension as a generic loop runtime.

References: proposal.md; specs/**/spec.md; clarify.md (all findings answered);
constitution principles II (canonical skill path), V (mise owns tool install),
VIII (openspec workspace not deployed), IX (skill edits ≥ M get adversarial
review); domain invariants 2, 8, 12, 13.

## Goals

- Deterministic, harness-agnostic enforcement of every workflow step and gate.
- One orchestrator agent drives the loop in-session; reviews delegated to subagents.
- Explore stays a human gate; intent is frozen and authoritative for the loop.
- Swapping harness costs only re-binding thin adapters, never workflow logic.

## Non-Goals

- Replacing OpenSpec or migrating to Spec-Kit/Kiro (rejected; keeps the schema investment).
- A bespoke loop engine (the `goal` extension already is one).
- Git-hook backstop (deferred to a follow-up change, per owner).
- Property-based test generation from specs (out of scope).

## Decisions

### D1 — Enforcement is a harness-neutral exit-code CLI (`opsx-gate`)
**Choice:** `opsx-gate` is the **primary** source of enforcement truth: it reads state + manifest +
verdicts and exits 0/non-zero with a red-check report. The loop, archive, and (later) git hooks all
obey the same exit code. Archive additionally re-checks the code-review/verify verdicts as
**defense-in-depth** (a human can invoke archive without going through the loop), so the two are
intentionally consistent rather than contradictory.
**Alternatives:** schema prose (status quo, unenforceable); per-harness hook logic (couples
enforcement to pi); gate-only with archive trusting the gate blindly (loses the manual-archive guard).
**Rationale:** an LLM can't be bound by prose; a deterministic outer-harness constraint can. "Primary
source" not "single source" — archive's redundant check is a deliberate guard for out-of-loop archiving,
and both read the same fields so they cannot diverge.
**ADR 4-point:** multiple approaches ✓, lasting ✓, contestable ✓, constrains future ✓ → **ADR.**

### D2 — Loop runtime is the existing `goal` extension with a pluggable command-judge
**Choice:** Add a command-judge to `goal` (exit 0 = met). opsx plugs in as worker=skill,
judge=`opsx-gate`. The extension never learns about opsx.
**Alternatives:** build an opsx-coupled loop extension; bash-only loop.
**Rationale:** keeps the runtime generic and reusable for any gated workflow; maximal
decoupling — deleting the extension loses only continuation convenience.
**ADR 4-point:** all four ✓ → **ADR.**

### D3 — Single-orchestrator-in-harness is primary; Ralph bash is the portability fallback
**Choice:** Primary driver = one orchestrator agent session looped by the extension,
dispatching subagents. Fallback = stateless Ralph bash loop parameterized by `AGENT_CMD`.
**Alternatives:** Ralph-only (no native subagents/UI); orchestrator-only (no portability escape).
**Rationale:** in-session gives native subagents, context, interruptibility; the bash fallback
preserves harness-agnostic execution (CI, other harness, no extension).
**ADR 4-point:** multiple ✓, lasting ✓, contestable ✓, constrains ✓ → **ADR.**

### D4 — `Worktree Mode` defaults to `worktree-required` for all Scales
**Choice:** Every change runs in an isolated worktree by default; `same-tree` is an explicit
override. **BREAKING** default change.
**Alternatives:** keep `same-tree` default; worktree-eligible default.
**Rationale:** an autonomous loop needs blast-radius containment; isolation is a safety
prerequisite, not tidiness (harness-engineering guidance). XS overhead accepted for consistency;
`same-tree` remains one keystroke away.
**ADR 4-point:** all four ✓ → **ADR.**

### D5 — Post-impl review is a skill-managed `code-review.md`, not a graph artifact
**Choice:** Mirror verify.md/retrospective.md: template in schema, produced by the apply skill
after verify green, gating archive via `Code Review Mode`. Reuses adversarial-review-cycle over
the diff; degrades to single-model.
**Alternatives:** declare it in the schema graph (breaks existence-only `isComplete`); fold into
retrospective (wrong lifecycle moment).
**Rationale:** same documented reason verify/retro are skill-managed; lets Scale gate it.
**ADR 4-point:** multiple ✓, lasting ✓, contestable ~, constrains ✓ → **ADR (borderline; promote).**

### D5b — `opsx-gate` reads modes ONLY from review.md front-matter; the prose table is documentation
**Choice:** review.md carries a YAML front-matter block (`scale`, `worktree_mode`, `verification_mode`,
`code_review_mode`, `loop_max_iterations`, `validation_source_mode`); `opsx-gate` sources every mode from
the front-matter ONLY and never parses the prose mode table. The table is a non-authoritative human
mirror that the schema templates + apply skill keep in sync — there is no dual-source divergence for the
gate to detect because the gate has a single source.
**Alternatives:** regex-scrape the prose table (original plan); keep both + a divergence check (round-2
P2-10) — rejected because detecting divergence requires parsing the very table D5b exists to stop parsing.
**Rationale:** the gate is the enforcement spine; a misparse yields a silently-wrong gate. One structured
source is deterministic and removes the self-contradiction. Promoted from an Open Question to a decision.
**ADR 4-point:** multiple ✓, lasting ✓, contestable ~, constrains ✓ → **ADR (promote).**

### D6 — Validation manifest is `opsx-gates.yaml` (YAML + `yq`)
**Choice:** Structured YAML manifest of `{id, run, required}` gate commands; replaces the
dangling `project.md` validator reference. `jq`+JSON is the zero-new-dep fallback.
**Alternatives:** markdown table (parser-hostile); JSON (no comments).
**Rationale:** matches schema.yaml/lefthook.yml style; clean `yq` parse; comments allowed.
**ADR 4-point:** multiple ✓, lasting ~, contestable ~, constrains ✗ → not ADR (note in design).

### D7 — Reviews are delegated to blind subagents judging against a phase-keyed baseline
**Choice:** Every review/validation-judgment step → blind subagent. Baseline = intent.md
pre-design; intent + proposal/specs/design post-apply. Subagent writes the verdict; the gate
only reads it.
**Alternatives:** orchestrator self-reviews (marks own homework); fixed single baseline.
**Baseline:** pre-design = intent.md; post-apply = intent.md + proposal + specs + design + plan + tasks
status (the reviewer checks the impl followed the approved execution/verification path).
**Rationale:** independence catches drift from intent; keeps the gate deterministic by separating
judgment (subagent) from enforcement (gate).
**ADR 4-point:** multiple ✓, lasting ✓, contestable ~, constrains ✓ → **ADR (promote).**

### D8 — Explore freezes an immutable `intent.md`
**Choice:** `openspec-explore` writes intent + constraints + invariants to intent.md; the loop
and reviewers treat it as source-of-truth; mutating it requires a human.
**Alternatives:** keep intent only in the proposal Why; no frozen baseline.
**Rationale:** a stable north star is what lets the autonomous loop run without drifting from
what was agreed.
**ADR 4-point:** multiple ~, lasting ✓, contestable ✗, constrains ✓ → not ADR (note in design).

## Risks / Trade-offs

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Worktree-required adds ceremony to trivial XS fixes | High | Low | `same-tree` explicit override remains trivial to select |
| Single orchestrator loses Ralph's crash-resilience | Med | Med | Ralph bash fallback documented; budget bound; worktree preserves partial work |
| `opsx-gate` front-matter malformed / table drifts from front-matter | Low | Med | Front-matter is the sole machine source (D5b); sed/awk parse; absent/unparseable Scale fails the gate; table is documentation only |
| Subagent dispatch unavailable on some harness | Med | Low | Capability hook degrades to inline with a degraded-mode notice |
| `yq` new dependency | Low | Low | Install via mise (Constitution V); JSON+jq fallback path documented |
| Gate green but human disagrees with frozen intent | Low | Med | Intent mutation requires human; loop halts rather than editing intent |
| Agent self-attests verdicts (checkboxes/Verdict) then keeps editing | High | High | Verdict freshness: verify/code-review record reviewed base..HEAD; gate fails on stale range + missing provenance field (D9) |
| Worktree isolation collides with chezmoi's fixed source root | High | High | Deploy-affecting verifications run post-merge or with `--source <worktree>`; never `chezmoi apply` real home from a loop worktree (D10) |
| Loop reaches GATE-PASS with no agent-independent check (empty manifest) | Med | High | Scale ≥ M requires ≥1 validation source else loud UNVERIFIED warning; this repo ships a live opsx-gates.yaml |

## Migration Plan

1. Land harness-neutral core first: `opsx-gate`, `opsx-gates.yaml` template, `openspec-loop` skill.
2. Add `goal` command-judge (generic, opsx-agnostic) — independently shippable.
3. Schema edits: `Code Review Mode`, worktree default flip, `code-review.md` template, README.
4. Skill edits: apply (worktree lifecycle + code-review production), archive (code-review gate +
   merge/cleanup), explore (freeze intent). Constitution IX → adversarial review on these edits.
5. Thin pi kickoff adapter (`/opsx-loop`) last; verify delete-the-extension litmus still runs the
   workflow via bash fallback.

## Adversarial review resolutions

- **D1 reworded** to "primary source" + archive defense-in-depth (reviewers F4).
- **D5b added**: machine-readable review.md front-matter, replacing table scraping (reviewers F3 — the
  single-point-of-failure parse risk). Resolves the former Open Question.
- **Mode-aware verdicts**: opsx-gate now conditions verify/code-review checks on Verification Mode /
  Code Review Mode so advisory modes never block (reviewers OPSX-001, OPSX-005, F1).
- **Worktree failure + budget ACs** added; **same-tree diff base** defined for code-review (reviewers
  F2, F5, OPSX-012).
- **Loop budget** surfaced as `loop_max_iterations` in review.md with Scale-keyed defaults (reviewer F6).
- **Worktree-required at all Scales retained** despite the reviewers' "M+ only" alternative: this is an
  explicit owner decision (default for all sizes); `same-tree` override documented for trivial fixes.
- **One adversarial cycle covers all three skill edits** (apply/archive/explore) in this change, per
  Constitution IX read at the change granularity, not per-file (reviewer A3).
- **intent.md is change-scoped, not capability-scoped**: it travels to the archive dir with the change
  and is not promoted into capability specs — intentional (reviewer F11).

## Adversarial review round 2 (opus via claude-bridge) resolutions

- **D9 — Verdict freshness + provenance** (P0-1): the gate read agent-authored verdicts verbatim, so "cannot talk past" did not hold for the judgment checks. Now verify.md/code-review.md record the reviewed `base..HEAD` range + a subagent provenance field; opsx-gate recomputes the range and fails stale or unprovenanced verdicts. The proposal claim is now scoped to: structural + manifest + freshness checks are non-bypassable; judgment verdicts are attestation **bound to the current diff**.
- **D10 — chezmoi source-root vs worktree** (P1-4): deploy-affecting verifications (chezmoi apply, harness symlinks, `openspec templates/schemas`, mise) resolve the fixed source root, not the worktree. Decision: run those verifications post-merge (or with `CHEZMOI_SOURCE_DIR`/`--source <worktree>`), and NEVER `chezmoi apply` real home from a loop worktree. Captured as a Risk row + worktree-lifecycle guard.
- **Front-matter parsed dependency-free** (P1-3): opsx-gate reads review.md front-matter with a sed/awk `key: value` reader (no yq); yq is reserved for `opsx-gates.yaml`, making the jq+JSON manifest fallback story complete. yq install moves to the core step's pre-conditions.
- **Constitution IX satisfied by code-review.md, not analyze** (P1-6): the analyze adversarial review covered the plan, not the skill diffs. The gating code-review.md (reusing adversarial-review over the diff) is the IX satisfaction point for the apply/archive/explore edits; IF code-review degrades to single-model, IX is NOT satisfied and archive is blocked for skill-editing changes.
- **Emission order** (P1-2): required-artifact failures emit in lifecycle dependency order, not cost order, so first-red-wins picks the earliest unmet dependency.
- **Verdict authorship** (P2-9): the review subagent authors code-review.md; the skill only triggers/collects (supports D9 provenance).
- **Front-matter authoritative + divergence check** (P2-10); **single budget mapping** (P2-8); **post-green merge-conflict abort + named integration branch/strategy** (P2-7).

## Adversarial review round 3 (final validation, opus + gpt-5.5) resolutions

- **D5b self-contradiction** (P1-1): "never scrape table" vs round-2 "detect table divergence" — resolved by
  making front-matter the sole machine source; divergence check dropped; table is documentation.
- **Degraded review re-opened D9 hole** (P1-2/REV3-003): inline/single-model review = self-attestation.
  Now `review_mode: degraded-single-model` does NOT satisfy a gating-required code-review; provenance is
  adapter-stamped, not agent-written; degraded review fails Constitution IX for skill-editing changes.
- **Command-judge vs transcript-only rule** (P1-3): added a MODIFIED `Judge Each Completed Turn` block
  scoping transcript-only to the model evaluator; command-judge evaluates external state by exit code.
- **intent.md not gate-required + emission-order omissions** (P1-4): intent.md is now Scale≥M required;
  emission order reconciled to include review (first), intent, analyze.
- **Worktree reuse reset the freshness base** (REV3-001): `Diff Base SHA` = integration merge-base,
  immutable per branch; reuse preserves it or halts; gate locates the worktree via `Worktree Path`.
- **code-review trigger deadlock** (REV3-002): trigger is "pre-review checks green," not "verify green,"
  so gating-required code-review under advisory verify cannot deadlock.
- **UNVERIFIED was only a warning** (P2-3/REV3-004): missing agent-independent source at Scale≥M now FAILS
  the gate unless `validation_source_mode: waived` with rationale.
- **same-tree had no stored base** (P2-4/REV3-008): `Diff Base SHA` recorded in both modes.
- **required:false vs any-non-zero-fails** (P2-2): required:true fails, required:false warns.
- **review baseline incoherent** (REV3-005): unified to intent + proposal/specs/design/plan/tasks.
- **proposal "single source"** (P2-1): reworded to "primary source."
- **stale clarify A2 + stale markdown-risk row** (P2-5/REV3-010): both updated.
- **gate report format** (REV3-007): minimal stable line protocol `GATE-FAIL <check_id> <blocking> <message>`.

## Open Questions
- Recommended per-Scale loop budgets (S=20/M=40/L=80 starting point) — tune during dogfooding.
