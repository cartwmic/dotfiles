<!-- authored: delegate blind clarify -->
# Clarify Findings

<!--
Blind clarify review (fresh context, authoring conversation unseen). Three passes
over the EARS acceptance criteria in specs/**/spec.md, judged against the FROZEN
intent.md. AUTONOMOUS mode: every finding resolved with the more conservative /
intent-faithful option; nothing left for the user. Resolutions that change intended
AC wording were applied as minimal spec edits (intent.md immutable). `openspec
validate harden-opsx-loop-latch-and-stop --strict` green before and after.
-->

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | opsx-loop-kickoff / "Loop hold blocks continuation" | The extension checks `loop_hold` in "the armed change's review.md" — from WHICH checkout (integration vs worktree)? A split-brain read would defeat G-C. | Leave checkout unspecified; reader infers | Pin to the integration-checkout copy | **answered** | **B (already pinned; no kickoff edit).** The opsx-gate-enforcement ADDED requirement in THIS change states the loop extension "resolve[s] review.md from the integration checkout." So the read side is already fixed. The exposure is on the WRITE side (see I2). No kickoff-spec edit needed; cross-reference is intent-invariant "gate result identical from checkout or worktree (locator convergence)." |
| A2 | opsx-gate-enforcement + opsx-loop-kickoff / convention fallback | "the canonical `opsx worktree` convention path" — is this a single deterministic path? | Deterministic path emitted by `opsx worktree` | Define a new path expression | **answered** | **A.** `opsx worktree` yields one canonical path per change (constraint: extension/gate stay deterministic, model-free — ADR-0007 lineage). Both surfaces validate the probed path is a git worktree on `opsx/<change>` before use, so an accidental collision is rejected. No edit. |
| A3 | opsx-loop-kickoff / "Goal and conversation kickoff" | "snapshot the existing active change directories" (all dirs) vs the inventory subset ("carrying a committed `intent.md`") — same set? | Two distinct sets by design | Unify them | **answered** | **A.** Intent decision 2: inventory = `openspec/changes/*` entries WITH a committed `intent.md`; the snapshot is the broader delta baseline for new-dir detection. Different purposes, both deterministic (dir listing + front-matter parse). Keeping them distinct is intent-faithful. No edit. |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | kickoff "Loop hold blocks continuation" × base "opsx-gate is the deterministic judge" (green stop) | Agent turn ends while loop active; gate green AND `loop_hold: true` both possible | Which stop message fires; is hold even checked on green? | Undefined ordering | Pin evaluation order | **answered** | **A (keep; already ordered).** Intent decision 4 wording is "checks it at `agent_end` **before re-injecting a continuation**." Green gate stops WITHOUT a continuation (base spec), so the hold matters only on the red/continuation path; a green change's own stop pre-empts. Both outcomes are "stop the loop" — no conflicting observable. Ordering is already implied; no edit. |
| I2 | orchestration "Terminal landings set the loop hold" × gate-enforcement "loop extension resolves review.md from the integration checkout" | Orchestrator commits `loop_hold` "as part of the landing turn"; extension reads from integration checkout | Hold written to worktree/change-branch copy is invisible to the host → G-C fix silently defeated | Leave write location unspecified | State the write must land in the integration-checkout copy | **answered** | **B — EDITED orchestration spec.** This is the exact G-D split-brain applied to `loop_hold`. Intent invariant: "gate result identical whether resolved from integration checkout or worktree (locator convergence)"; the hold channel needs the same convergence. Edited the requirement to "the same copy the loop host resolves from the integration checkout, so the hold is observable to the host." |
| I3 | kickoff scenario "Named re-arm clears the hold and surfaces the reason" × base "Kickoff on an already-green change does not loop" (Guard 1) | Held change + named re-arm + gate already green | Scenario said "SHALL arm the loop normally"; Guard 1 forbids arming a green change | Keep "arm normally" | Route re-arm through turn-0 gate check | **answered** | **B — EDITED kickoff scenario.** Intent decision 1: Guard 1 (turn-0 `pre.met` → ready-to-archive notify WITHOUT arming) handles the green case; decision 5: re-arm clears the hold. A held+green re-arm must clear then behave per Guard 1, not force a worker turn. Reworded to "then proceed with normal kickoff evaluation (arming … or … reporting the change ready to archive WITHOUT arming when its gate is already green)." |

## Pass 3 — Completeness (event/state combination enumeration)

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | `loop_hold: true` × empty/absent `loop_hold_reason` at `agent_end` | Reason is "mandatory" (schema) but the extension can still observe `true` with no reason — hold, or ignore? | Undefined; risk of re-injecting | Land anyway (fail-safe) | **answered** | **B — EDITED kickoff (added scenario).** Intent invariant: "setting `loop_hold` requires no privilege (fail-safe direction)." Ignoring a hold because the reason is empty would re-drive a landing the orchestrator meant to stop — the wrong-direction failure. Added scenario "Hold true with a missing reason still lands": hold honored, loop cleared, generic held-without-reason notice. The `true`-REQUIRES-reason rule stays a template-authoring constraint (opsx-workflow-schema), not a runtime re-drive trigger. |
| C2 | Stall guard fires while a turn budget IS configured (stall limit < budget) | Does the 3-turn stall guard apply when `loop_max_iterations` is set? | Prose "INDEPENDENT of the budget" governs | Broaden the scenario WHILE clause | **answered** | **A.** The requirement prose is explicit: "INDEPENDENT of the budget, the extension SHALL bound the distilling phase with a stall guard." The two scenarios (budget-set / budget-unset) are illustrative extremes; the prose is authoritative and already covers the mixed case. Editing the scenario risks narrowing an already-correct requirement. No edit. |
| C3 | Explicit `--worktree <path>` supplied AND invalid (gate path) | Fall through to convention probe, or fail? | Probe convention silently | Fail on bad explicit path | **answered** | **A.** The fallback antecedent is scoped to the *recorded locator* being "absent, empty, or fails validation" — it does not cover an explicit operator-supplied `--worktree`. Conservative reading: an explicit path is an operator assertion; silently substituting a different tree would mask an operator error. The convention probe is for the empty/stale-locator case only. No edit; behavior is the safer default. |

## Outstanding (status != answered)

- (none — all 9 findings answered; 0 unanswered, 0 deferred)

## Summary

- Pass 1 findings: 3; unanswered: 0; deferred: 0 (edits: 0)
- Pass 2 findings: 3; unanswered: 0; deferred: 0 (edits: I2 → orchestration spec; I3 → kickoff scenario)
- Pass 3 findings: 3; unanswered: 0; deferred: 0 (edits: C1 → kickoff added scenario)
- **Files edited:** `specs/opsx-loop-orchestration/spec.md` (I2), `specs/opsx-loop-kickoff/spec.md` (I3 + C1)
- **Validate:** `openspec validate harden-opsx-loop-latch-and-stop --strict` → green before and after edits
- **Gate status:** READY for design
