<!-- authored: delegate blind clarify -->
# Clarify: simplify-and-parallelize-opsx-workflow

## Context

Blind clarify review of the 12 delta specs for `simplify-and-parallelize-opsx-workflow`
(concurrency set A1–A5 + simplification set B1–B4 + spec consolidation 12→7 capabilities).
Reviewer had NO authoring context; did not read review.md Execution Notes, code-review.md,
/tmp files, or archive contents. Baselines read: frozen `intent.md`, `proposal.md`,
`audit.md`, all 12 deltas, every touched live `openspec/specs/<cap>/spec.md`,
`constitution.md`, `domain.md`.

Three passes run: **Ambiguity**, **Inconsistency**, **Completeness**. AUTONOMOUS mode —
every finding self-resolved to the more conservative / intent-faithful option; nothing
escalated. `intent.md` never edited; live spec-of-record never edited. Where a resolution
changed intended behavior, the relevant **delta** spec was edited (full MODIFIED
restatement discipline preserved).

### Consolidation tiling verified (baseline sanity)

The REMOVED sets tile the ADDED consolidations **exactly** (checked header-by-header
against the live spec-of-record):

- `opsx-loop` ADDED = 21 = kickoff(12 REMOVED) + orchestration(9 REMOVED). Exact.
- `opsx-adversarial-review` ADDED = 25 = review-convergence(11) + post-impl-review(8) +
  doneness-judge(5) REMOVED, + 1 new `M-Tier Review Stack Thinning`. Exact.
- gate-enforcement per-tier artifact set ↔ workflow-schema `Per-Tier Review Stack` ↔
  adversarial-review `M-Tier Review Stack Thinning` all agree (plain-M: no standalone
  clarify/analyze-dispatch, doneness rides code-review; full_rigor: full independent stack;
  2-model code review gating-required at every tier).
- opsx-loop `Doneness Judge Dispatch` ↔ adversarial-review `Blind Scope-Anchored Judge`
  agree on the full_rigor→independent / plain-M→ride tiering.

## Findings

| ID | Pass | Finding | Option A (keep) | Option B (change) | Status | Resolution + rationale |
|----|------|---------|-----------------|-------------------|--------|------------------------|
| A-1 | Ambiguity | B1 plain-M doneness "rides the blind code-review dispatch (**same blind reviewer**)" but the code review is a ≥2-model dispatch — which reviewer answers doneness, and how is one `Doneness: satisfied\|not` field consolidated across models? `adversarial-multimodel` is in the provenance vocab, contradicting the singular provenance stamp. | Leave "same blind reviewer" singular, unspecified which model / how consolidated. | Specify a deterministic single designated reviewer + single-model provenance. | answered | **B (EDITED).** intent.md B1 says "same blind reviewer" (singular) and "no separate dispatch"; the freshness/provenance binding records a single "judging review-role model identity". Most intent-faithful reading: exactly ONE reviewer answers doneness — deterministically the FIRST model in the resolved `review` set — stamped `blind-single-judge`; the other reviewers emit no competing verdict; the 2-model code review itself stays unweakened. This matches full_rigor's single-judge cardinality. Edited `opsx-adversarial-review` (Blind Scope-Anchored Judge: body + new scenario) and `opsx-loop` (Doneness Judge Dispatch plain-M scenario). |
| A-2 | Ambiguity | A1 Land Base Currency hardcodes `merge-base(opsx/<change>, main)==main HEAD`, but the worktree lifecycle supports a configurable `--integration-branch`; if the integration branch ≠ `main`, A1 checks the wrong ref. | Keep literal `main`. | Generalize to the recorded Integration Branch locator. | answered | **A (no edit).** intent.md A1/A2 state `main` verbatim; grounding assumptions fix a solo-dev chezmoi repo whose integration branch is `main`. Conservative = mirror intent literally rather than widen scope. Documented assumption: A1 treats `main` as the integration branch; a non-`main` integration branch is out of scope for this change (follow-up if ever observed). |
| A-3 | Ambiguity | A5 `opsx status` output contract is undefined for a change with no `review.md` (undeclared Scale, no `opsx/<change>` branch — e.g. a from-scratch change mid-distill). Could crash on the missing Scale/branch. | Leave unspecified. | Print placeholders, never crash, still exit 0. | answered | **B (EDITED).** intent A5 mandates a read-only, deterministic view that "always exits 0" and serves recovery ergonomics. Crashing on an incomplete change defeats the fleet view. Added `opsx-cli` Status Fleet View scenario: undeclared Scale / absent branch → stable placeholder (`—`/`unknown`), exit 0, no error. |
| A-4 | Ambiguity | B2 `full_rigor` is a single boolean, but former `L` (ADR + adversarial-analyze) and former `XL` (+ retrospective) had different extras — one flag can't distinguish them; an author wanting L-extras-but-not-retrospective can't express it. | Keep one boolean enabling ALL extras. | Add a second flag / enum to separate L vs XL extras. | answered | **A (no edit).** intent.md B2 explicitly collapses: "ADR promotion, adversarial-on-analyze, and retrospective become an explicit opt-in flag" and "former L and XL labels map to 'M + full_rigor'." One flag turning on all extras is the settled design; adding granularity re-expands the surface the audit told us to shrink. workflow-schema scenarios already fire ADR-prompt + adversarial-analyze + retrospective all on `full_rigor: true` — internally consistent. |
| A-5 | Ambiguity | A1 edge cases: detached HEAD, first-ever change, merge commits on the branch. | Leave implicit. | Enumerate each edge case. | answered | **A (no edit, except same-tree — see C-1).** `main` is a branch ref, so `main HEAD` resolves deterministically regardless of the integration checkout being detached (git plumbing, no ambiguity). First-ever change: branch created from `main` ⇒ merge-base == `main HEAD` trivially (the "Current base permits landing" scenario covers it). Merge commits on `opsx/<change>`: `merge-base` is well-defined over a DAG with merges. The only genuinely undefined edge — a same-tree change with NO `opsx/<change>` branch — is escalated to C-1 and edited there. |
| I-1 | Inconsistency | `opsx-skill-integration` (live spec-of-record, **no delta in the change**) still declares the Scale vocabulary `XS \| S \| M \| L \| XL` (Up-front Scale prompt) and "For changes with Scale ≥ L … invoke adversarial-review-cycle" (Analyze gates tasks generation). After B2 the gate fails closed on `L`/`XL`, so a propose-skill author following this spec would author a Scale the gate rejects. Direct contradiction with the gate-enforcement + workflow-schema deltas. | Ship the change without touching opsx-skill-integration. | Add an opsx-skill-integration delta remapping L/XL → M + `full_rigor`. | answered | **B (EDITED — new delta).** intent B2/B3 + the "no stray L/XL semantics left live" discipline require the skill contracts to speak the collapsed vocabulary; leaving them is a live contradiction (a change that fails its own gate). Created `specs/opsx-skill-integration/spec.md` with MODIFIED `Schema-aware openspec-propose` (Scale prompt → `XS\|S\|M` + full_rigor, never offers L/XL) and MODIFIED `Analyze gates tasks generation` (full_rigor invokes adversarial-review-cycle; plain-M thins analyze to deterministic checks). Conservative = eliminate the contradiction, not ship it. |
| I-2 | Inconsistency | `opsx-skill-integration` "openspec-loop orchestrator skill exists" references the **retired** `opsx-loop-orchestration` capability (consolidated into `opsx-loop` under B3), leaving a dangling capability name. | Keep the stale reference. | Remap to the consolidated `opsx-loop` capability. | answered | **B (EDITED — same new delta).** B3 is documentation-topology: every surviving reference should name the surviving capability. Cheap and correct to fix in the delta I already had to author. MODIFIED the requirement body to "per the consolidated `opsx-loop` capability (which absorbs the retired `opsx-loop-orchestration`)". (Note: `opsx-cli`'s command-convention exemption list still names retired capabilities as historical identifier substrings — left as-is; non-normative, and the substrings persist in archived specs regardless. Low, accepted.) |
| I-3 | Inconsistency | Stray "Scale M **or above** / **and above**" phrasing survives verbatim in `opsx-adversarial-review` (Scale-Gated With Waiver, Code Review Mode) and `opsx-workflow-schema` (Doneness Mode) — but under B2, M is the top tier, so "above M" is empty. | Keep the carried-over phrasing. | Rewrite every instance to "M (the top tier)". | answered | **A (no edit).** "M or above" evaluates correctly (= M, since M is top) and `full_rigor` is still Scale M, not a higher tier. These are verbatim carry-overs from the consolidated capabilities; the B3 constraint is preserve-verbatim, and rewriting many instances risks drift against the "no behavior change from consolidation" rule. Harmless; documented so a future reader doesn't infer a hidden tier above M. |
| I-4 | Inconsistency | Do gate-enforcement's lifecycle-order list (`…clarify…analyze…doneness`) and required-artifact set contradict plain-M thinning (clarify/analyze not required at plain M)? | — | — | answered | **No contradiction (verified).** The lifecycle order is a total ordering used for first-red-wins selection; artifacts that are not required at a tier are simply not checked — their presence in the ordering is inert. gate-enforcement's plain-M "SHALL NOT include a standalone clarify.md or blind analyze verdict" and full_rigor "SHALL include clarify.md, analyze.md" tile exactly with workflow-schema + adversarial-review. Status answered, no edit. |
| I-5 | Inconsistency | Do the REMOVED consolidation sets exactly tile the ADDED sets, with no requirement dropped or duplicated across the two new capabilities and the five retirement stubs? | — | — | answered | **Tiles exactly (verified).** loop: 12+9 REMOVED = 21 ADDED; adversarial: 11+8+5 REMOVED = 24 + 1 new = 25 ADDED. Every retired requirement header re-appears in its consolidation target; no orphan, no duplicate. Doneness dispatch is described consistently in both `opsx-loop` (orchestration view) and `opsx-adversarial-review` (judge view) with the same full_rigor/plain-M tiering. No edit. |
| C-1 | Completeness | A1 Land Base Currency requires `merge-base(opsx/<change>, main)` unconditionally, but B4 auto-downgrades XS/S to **same-tree** mode (no `opsx/<change>` branch). The missing ref would make the merge-base fail → every same-tree (XS/S) archive refused as a "stale base". | Leave unconditional (fail-closed on missing branch). | Treat an absent `opsx/<change>` branch (same-tree) as precondition-satisfied. | answered | **B (EDITED).** Fail-closed here is NOT the safe direction — it blocks the B4-default same-tree archive path entirely, contradicting intent B4. A1's purpose is preventing a stale *branch* landing over intervening `main` commits; a same-tree change commits directly onto the integration checkout, so no divergent base exists and the failure class is moot. Edited `opsx-gate-enforcement` Land Base Currency: added a WHERE clause + scenario — absent `opsx/<change>` branch ⇒ satisfied, never a missing-ref failure. |
| C-2 | Completeness | Migration/cutover for **in-flight** (non-archived) changes still labeled `L`/`XL` at cutover is undocumented. intent covers post-land changes and forbids rewriting archives, but the in-flight case falls between. | Leave to the fail-closed gate silently. | Document the fail-closed + relabel cutover explicitly. | answered | **B (EDITED).** The fail-closed gate already handles it *safely* (a loud unknown-Scale failure, never a silent permissive pass), but the cutover was untraceable. Added a `opsx-workflow-schema` Scale-adaptive-gating scenario: in-flight `L`/`XL` fails closed and the README migration note instructs relabel to `M` + `full_rigor: true`; archived changes untouched. Matches intent's "migration applies to changes created after this lands" + "no rewriting of archived changes." |
| C-3 | Completeness | Fail-closed validation for the NEW front-matter keys (`full_rigor`, `doneness_mode`, tier-derived `worktree_mode`). | — | — | answered | **Covered (verified), no edit.** `full_rigor` fail-closed: gate-enforcement "Unparseable full_rigor flag fails closed" + workflow-schema "Unknown Scale or non-boolean full_rigor fails closed". `doneness_mode`: waiver requires non-empty `doneness_waiver_rationale` else stays required (workflow-schema + adversarial-review Scale-Gated With Waiver). `worktree_mode`: tier default derived, explicit value always wins. All new keys fail closed / default conservatively. |
| C-4 | Completeness | Each of A1–A5, B1–B4 traceable to ≥1 requirement + scenario. | — | — | answered | **Traceable (verified), no edit.** A1→gate Land Base Currency; A2→cli Multi-Dir Detector + schema Path-Scoped Integration Commits; A3→gate Duplicate ADR Number Scan; A4→cli Worktree Lifecycle Commands (reuse/refuse); A5→cli Status Fleet View. B1→adversarial M-Tier Review Stack Thinning + Blind Scope-Anchored Judge + loop Doneness Judge Dispatch + gate Required Artifact By Scale + schema Per-Tier Review Stack; B2→schema Scale-adaptive gating + gate Required Artifact By Scale; B3→the two consolidations + five retirement stubs; B4→schema Worktree Mode tier default + model-config Layered Resolution (drop project layer) + goal-loop Deprecation and Fallback Status. |

## Decision

**READY for design.** All 14 findings answered (0 unanswered). Six findings edited delta
specs; eight were resolved as already-correct / keep-per-intent.

## Rationale

Every resolution took the more conservative / intent-faithful branch:

- Where fail-closed was genuinely safest (C-3, unknown Scale, unparseable flags) the specs
  already enforce it — confirmed, not weakened.
- Where blind fail-closed would have *broken* an intended path (C-1 same-tree archive) the
  resolution restores the intended behavior, because A1's stale-base failure class does not
  apply to same-tree commits — matching intent B4.
- Ambiguities with a singular-vs-plural reading (A-1 doneness reviewer) were pinned to the
  singular, deterministic reading intent.md's own wording ("same blind reviewer") and the
  single-model provenance stamp demand — without weakening the load-bearing 2-model code
  review (an explicit intent constraint).
- The one true live contradiction (I-1/I-2, opsx-skill-integration still speaking the
  retired L/XL vocabulary and a retired capability name) was eliminated by adding the
  missing delta, honoring the "no stray L/XL semantics left live except migration notes"
  discipline.
- Scope-expanding options (A-2 configurable integration branch, A-4 second rigor flag,
  I-3 mass rephrase) were declined as re-expanding a surface the audit told us to shrink.

## Impact

Delta specs edited (6 files; `intent.md` and live spec-of-record untouched):

1. `specs/opsx-skill-integration/spec.md` — **NEW delta** (I-1, I-2): remap Scale
   `L`/`XL` → `XS\|S\|M` + `full_rigor`; remap retired `opsx-loop-orchestration` ref →
   `opsx-loop`.
2. `specs/opsx-gate-enforcement/spec.md` — Land Base Currency (C-1): same-tree /
   branch-absent ⇒ satisfied.
3. `specs/opsx-adversarial-review/spec.md` — Blind Scope-Anchored Judge (A-1): one
   deterministic designated doneness reviewer + `blind-single-judge` provenance.
4. `specs/opsx-loop/spec.md` — Doneness Judge Dispatch (A-1): mirror the designated-reviewer
   determinism at plain M.
5. `specs/opsx-workflow-schema/spec.md` — Scale-adaptive gating (C-2): in-flight L/XL
   cutover-relabel note.
6. `specs/opsx-cli/spec.md` — Status Fleet View (A-3): review.md/branch-absent robustness.

Downstream (design/tasks) must implement: the deterministic first-review-model doneness
designation at plain M; the same-tree land-base bypass; the `opsx status` placeholder
handling; the propose-skill Scale-vocabulary remap + a README L/XL→M+full_rigor migration
note.

## Validation (both strict gates green after edits)

```
$ openspec validate simplify-and-parallelize-opsx-workflow --strict
Change 'simplify-and-parallelize-opsx-workflow' is valid
EXIT=0
```

```
$ openspec validate --specs --strict
- Validating...
✓ spec/goal-loop
✓ spec/opsx-cli
✓ spec/opsx-doneness-judge
✓ spec/opsx-gate-enforcement
✓ spec/opsx-loop-kickoff
✓ spec/opsx-loop-orchestration
✓ spec/opsx-model-config
✓ spec/opsx-post-impl-review
✓ spec/opsx-review-convergence
✓ spec/opsx-skill-integration
✓ spec/opsx-spec-quality
✓ spec/opsx-workflow-schema
✓ spec/pi-model-visibility
✓ spec/pi-ntfy-notify
Totals: 14 passed, 0 failed (14 items)
EXIT=0
```

---
**Gate: READY for design** — 0 unanswered findings.
