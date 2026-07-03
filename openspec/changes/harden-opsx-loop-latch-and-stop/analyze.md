<!-- authored: delegate blind analyze -->
# Analyze Findings

**Mode:** single-model (blind analyze cross-check; authoring conversation unseen; `.rev*`/`review.md` excluded)
**Generated:** 2026-07-02 by delegate blind analyze

Scope: contradictions across intent/proposal/clarify/design/specs; constitution/domain;
EARS quality; MODIFIED-supersets-base faithfulness; achievability vs. current source
(`dot_pi/agent/extensions/opsx-loop/index.ts`, `dot_local/bin/executable_opsx`); interplay
with opsx-review-convergence / doneness-judge / stall detection; tasks readiness.

## Findings (ranked)

### M1 — major — proposal.md ↔ specs/opsx-loop-orchestration/spec.md (delta only ADDs; base scenario un-modified)
**Problem.** proposal "Modified Capabilities" claims the orchestration change "prescribes
setting `loop_hold` (**replaces** 'halt via host loop-stop, else stall detection')." The
delta only ADDs `Terminal landings set the loop hold`; it does NOT modify the base
requirement `Review Dispatch Bound By Convergence Discipline`, whose scenario **Landing
halts loop continuation** (base `openspec/specs/opsx-loop-orchestration/spec.md`) still
blesses stopping "via the host's loop-stop mechanism where available, **otherwise by
performing no further change-directory or commit activity so the host's stall detection
stops the loop**." That degraded stall-burn landing is exactly the mechanism intent G-C
declares unreliable ("relying on prose landings + stall burn (observed failing this
session)"). Post-archive the merged spec carries both the new deterministic-hold rule and
the old stall-burn blessing — a live contradiction and a proposal↔delta mismatch.
**Fix.** MODIFY `Review Dispatch Bound By Convergence Discipline`'s "Landing halts loop
continuation" scenario so `loop_hold` is the required primary channel (host loop-stop =
set `loop_hold` with the audit reason), with stall detection demoted to an explicit
degraded fallback — matching the proposal's "replaces." Or correct the proposal wording to
"adds, complements" (weaker; leaves the contradiction). MODIFY is the intent-faithful
choice.

### M2 — major — base opsx-loop-kickoff scenario contradicts the ADDED convention-fallback requirement
**Problem.** The delta ADDs `Worktree resolution convention fallback` (blank/stale locator
→ probe canonical `opsx worktree` path → use iff valid, else no `--worktree`). But the base
requirement `opsx-gate is the deterministic judge` retains the un-modified scenario **Blank
or stale worktree path falls back to no-worktree gate** (`THEN` run `opsx gate` WITHOUT
`--worktree`). For the identical trigger (blank/stale `Worktree Path`) the base says "go
straight to no-worktree" while the new requirement inserts a convention probe first. After
archive both live in `opsx-loop-kickoff/spec.md` as conflicting responses to the same state.
**Fix.** MODIFY the base "Blank or stale worktree path falls back to no-worktree gate"
scenario to chain through the probe: blank/stale → convention probe → iff the probed path
is a valid `opsx/<change>` worktree use it, ELSE run without `--worktree`. Keeps the
terminal degrade identical and removes the contradiction.

### M3 — major — loop_hold write-copy vs. orchestrator's worktree cwd: G-C can be silently defeated (achievability + test gap)
**Problem.** clarify I2 correctly pinned the WRITE copy to the integration checkout, and
the extension reads it there (`readReview(change, ctx.cwd)`, `ctx.cwd` = integration root,
index.ts:134). BUT during a loop the orchestrator operates **in the worktree** and writes
every other review.md field there — the gate's ARTIFACT SOURCE RESOLUTION block
(`executable_opsx` ~430) reads modes/verdicts/`Diff Base SHA` from the **worktree** copy,
which is where apply writes them. `loop_hold` is the lone review.md field that must be
written to the **integration** copy instead. The natural agent action ("set `loop_hold:
true` in review.md") edits the worktree copy the agent is standing in — which the extension
never reads → the hold is invisible → landing re-injects → the precise split-brain this
change exists to kill. The spec pins the copy but nothing enforces the operational HOW, and
no scenario/test asserts the extension observes a hold written to the integration copy while
the change's other artifacts live in the worktree.
**Fix.** (a) `openspec-loop` SKILL.md landing prose MUST direct the `loop_hold` write to the
**integration-checkout** review.md explicitly (not the worktree copy the loop otherwise
edits); (b) add an extension test that sets `loop_hold` in the integration copy only and
asserts continuation is suppressed; (c) add a spec scenario making the integration-copy
write observable-to-host requirement testable. Note the extension observes the working-tree
file (no commit strictly required for observation) — reconcile the requirement's "committed
as part of the landing turn" wording with that.

### M4 — major — "canonical `opsx worktree` convention path" has no single source; probe must re-derive the very convention whose duplication caused G-D
**Problem.** clarify A2 asserts a single deterministic path "emitted by `opsx worktree`."
Ground truth: the canonical path is computed inline as
`WPATH="$(dirname "$ROOT")/$(basename "$ROOT")--opsx-$CHANGE"` (`executable_opsx`:962) and
is **overridable via `--path`** at `opsx worktree ensure`; there is no read-only
path-emitting interface (`ensure` mutates — it creates the worktree). So the gate fallback
and the extension `resolveWorktree` fallback must each **re-derive** the path expression
independently (design even names a helpers.ts "canonical path" helper). That reintroduces
3–4 copies of the same convention — the exact duplicated-locator-derivation class of bug
G-D is closing — plus a blind spot for any worktree created with a non-default `--path`.
**Fix.** Single-source the convention: add a read-only `opsx worktree path <change>`
(or `--print-path`) subcommand consumed by both gate and extension, OR spec the derivation
as one canonical expression with a test asserting gate/extension/`ensure` agree. Explicitly
document that the fallback cannot locate custom-`--path` worktrees (publication is the only
cover for those) so tasks don't assume total coverage. Publication (primary) mitigates for
post-rule changes; the fallback's derivation divergence is the residual.

### m1 — minor — EARS density on the ADDED "Loop hold blocks continuation" requirement
Single requirement packs WHILE + WHEN + AND + set/clear/notify/record into one run-on with
many SHALLs. Achievable and unambiguous, but consider splitting the SET path from the CLEAR
path for testability. Not blocking.

### m2 — minor — named-re-arm hold-clear must be ordered BEFORE the turn-0 green short-circuit
The `set` handler runs the gate first and, on `pre.met`, returns early WITHOUT arming
(index.ts:422-428). The ADDED scenario `Named re-arm clears the hold and surfaces the
reason` requires clear-hold + surface-reason + Execution-Notes append to happen even when
the change is already green (then report ready-to-archive per Guard 1). Implementation MUST
insert the hold-clear/surfacing BEFORE the green early-return, else a held+green re-arm
neither clears nor surfaces the hold. design D5 already says "clears … then proceeds"; flag
so tasks encode the ordering.

### m3 — minor — loop_hold persists in review.md after a green stop
Per clarify I1 a green gate stop pre-empts the hold; clearing happens only on named re-arm.
So a change that goes green while `loop_hold: true` retains the stale field into archive.
Harmless (schema pins the gate to ignore hold state) but worth a one-line note in the
schema/template that a stale `loop_hold` on an archived change is inert.

## Check 1 — Constitution compliance

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I. Chezmoi single source of truth | compliant | All edits under chezmoi source paths (`dot_pi/...`, `dot_local/...`, `openspec/` workspace). | — |
| II. Skills in canonical pipeline | compliant | Skill edits target `dot_local/share/agent-harness/canonical/skills/openspec-loop` + apply reference — the canonical path. | — |
| III. No secrets | inapplicable | No credentials touched. | — |
| IV. Idempotent install scripts | inapplicable | No `run_once/onchange/install` scripts. | — |
| V. mise owns dev-tool install | inapplicable | — | — |
| VI. launchd PATH | inapplicable | — | — |
| VII. Termux not chezmoi-deployed | inapplicable | — | — |
| VIII. openspec/ not deployed | compliant | Change in `openspec/` workspace; template edit correctly at user-level `dot_local/share/openspec/schemas/...`. | — |
| IX. Skill changes → adversarial review at Scale ≥ M | compliant | review.md Scale M, `code_review_mode: gating-required`, `review_models` pinned, `review_max_rounds: 5`. Edits openspec-loop + apply reference → IX triggers, satisfied. | — |
| X. Memory promotion opt-in | inapplicable | — | — |

Domain: invariant 14 (MODIFIED = FULL content) honored — the two MODIFIED requirements
(kickoff `Goal and conversation kickoff`; gate `Verdict Freshness And Provenance`) reproduce
full base text + all base scenarios plus additions. Invariant 12/2/3 (skill/schema paths)
respected. No domain violation.

## Check 2 — EARS pattern check

| # | File:line | AC | True positive? | Suggested rewrite | Status |
|---|---|---|---|---|---|
| E1 | kickoff `Worktree resolution convention fallback` | "WHEN the `Worktree Path` locator … is absent, empty, or **fails validation**" | no | "fails validation" is a legit trigger state, not error-response prose | n/a |
| E2 | gate `Verdict Freshness And Provenance` | "SHALL treat a verdict as **failed** if the recorded range does not equal …" | no | state-driven SHALL; correct EARS | n/a |
| E3 | kickoff `Loop hold blocks continuation` | compound WHILE/WHEN/AND with multiple SHALLs | ambiguous | split SET vs CLEAR path (see m1) | pending |

## Check 3 — AC↔design coverage

| AC ID | Design reference | Status | Severity |
|---|---|---|---|
| kickoff.goal-mode-never-latches | D1 | covered | — |
| kickoff.active-change-inventory | D2 | covered | — |
| kickoff.distill-autonomy-scoped | D3 | covered | — |
| kickoff.loop-hold-blocks-continuation | D4 | covered | — |
| kickoff.named-re-arm-clears-hold | D5 | covered (ordering caveat m2) | minor |
| kickoff.worktree-convention-fallback | D6 | covered (single-source gap M4) | major |
| kickoff.stall-baseline-seeded-at-arm | D7 | covered | — |
| orchestration.terminal-landings-set-hold | D4 | covered (write-copy gap M3; base-scenario conflict M1) | major |
| gate.locator-published-to-integration | D6 | covered | — |
| gate.worktree-located-w-convention-fallback | D6 | covered (M2/M4) | major |
| schema.loop-hold-frontmatter-keys | D4 | covered | — |

## Check 4 — design↔ADR promotion candidates (Scale M — informational)

| Decision | 4-point score | ADR-candidate? | Rationale |
|---|---|---|---|
| D1 explicit-resume-only latch; no text matching | 4 | yes | multiple approaches (sweep/semantic/text), lasting, prior disagreement (supersedes G-A1), constrains future latch grammar. Extends the ADR-0007 model-free lineage — strong ADR candidate at archive. |
| D4 `loop_hold` as landing channel | 3 | yes | sentinel/keyword/prose alternatives rejected; durable cross-harness contract. |
| D6 locator publication + convention fallback | 3 | yes | accepts non-ff merges as a standing cost; future-constraining. |
| D5/D7/D3/D2 | ≤2 | no | mechanical or直接 consequences of D1/D4. |

Scale is M; ADR promotion is offered at archive, not required here. Flagged per check.

## Check 5 — Duplicate detection

| # | Locations | Restated constraint | Action |
|---|---|---|---|
| Dup1 | base orchestration "Landing halts loop continuation" + delta "Terminal landings set the loop hold" | how a non-convergence landing stops the loop | **differentiate/merge → M1** (MODIFY base to route through loop_hold) |
| Dup2 | base kickoff "Blank or stale worktree path falls back to no-worktree gate" + delta "Worktree resolution convention fallback" | blank/stale-locator resolution | **differentiate → M2** (chain base through the probe) |

## Check 6 — Implementation language in specs

No offending tech-leak ACs. `loop_hold` / `loop_hold_reason` / `Worktree Path` /
`Diff Base SHA` are artifact field names (the spec's own vocabulary), not implementation
tech. `opsx/<change>` branch naming is a domain convention. No rewrites needed.

## Check 7 — Unresolved clarify findings

| # | clarify ref | Status | Risk |
|---|---|---|---|
| — | A1,A2,A3,I1,I2,I3,C1,C2,C3 | all answered (9/9, 0 deferred) | A2 resolution rests on a "single emitted path" that has no read-only interface → see M4; I2 pinned the copy but not the operational HOW → see M3 |

## Achievability vs. source (verified)

- `resolveWorktree` at index.ts:205, reads `Worktree Path` body field from integration `cwd`
  (index.ts:134/206). Convention fallback insertable here. ✓ (single-source caveat M4)
- Distill stall off-by-one CONFIRMED: `preChangeDirs` captured at arm (index.ts:404) but
  `lastDirs` left `undefined`; turn-1 sets `dirsChanged=true` via `prevDirs===undefined`
  (index.ts:490-494) → STALL_LIMIT=3 costs 4 turns. D7 fix (seed `lastDirs=preChangeDirs` at
  arm) yields exactly 3. Achievable, line refs accurate. ✓
- Worker-phase stall (`stallCount` seeded to 1, index.ts ~578-582) is NOT off-by-one and is
  correctly left un-modified. ✓
- Front-matter reader already exists (`parseLoopBudget`, helpers.ts:269, parses between
  `---` fences) → `loop_hold` front-matter read is trivially feasible; hold-parse helper in
  helpers.ts is realistic. ✓
- Guard 1 (`pre.met` → ready-to-archive notify, no arm) present at index.ts:422-428;
  re-arm hold-clear ordering caveat = m2. ✓
- Gate `fm()` front-matter reader (executable_opsx:396) + `bodyfield` locator read at
  executable_opsx:431 (BEFORE the ART_ROOT→worktree switch at ~435) confirm the locator is
  read from the integration checkout while modes/verdicts read from the worktree — the field
  bifurcation underlying M3. Gate is correctly specced to never read `loop_hold`. ✓
- Canonical path `$(dirname ROOT)/$(basename ROOT)--opsx-<change>` at executable_opsx:962,
  `--path`-overridable, no read-only emit → M4. ✓

## Interplay (review-convergence / doneness-judge / stall)

- opsx-review-convergence: the decision-audit landing (base `Review Dispatch Bound By
  Convergence Discipline`) is the primary consumer of `loop_hold`; the un-modified base
  scenario is M1. No new convergence-ledger mechanization (correctly a non-goal).
- doneness-judge: untouched; the doneness gap-set stall ratchet (base `Stall detection stops
  the loop`) is correctly NOT modified — the off-by-one was distill-only. No conflict.
- stall detection: distill stall (D7) and worker/doneness stall are distinct guards; delta
  touches only the distill guard. Consistent.

## Outstanding risks

- M1–M4 tracked for pre-archive human-recorded resolution (majors).
- Non-ff archive merges from locator publication (design-accepted, observed survivable).
- Residual duplicate distillation if the agent ignores the inventory — stall guard is the
  bounded landing (severity: wasted turns, not wrong work).

## Summary

- Blockers: 0 → tasks generation not halted
- Major findings: 4 (M1 base-orchestration contradiction / proposal mismatch; M2 base-kickoff
  worktree-scenario contradiction; M3 loop_hold write-copy vs worktree cwd / test gap;
  M4 no single-source canonical path) → confirm/resolve before archive
- Minor findings: 3 (m1 EARS density; m2 re-arm clear ordering; m3 stale hold post-green)
- **Gate status:** READY for tasks — 0 blockers. Majors M1–M4 must be human-resolved before archive.
