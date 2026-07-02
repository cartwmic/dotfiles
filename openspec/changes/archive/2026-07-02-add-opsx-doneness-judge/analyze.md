<!-- authored: in-session -->
# Analyze Findings

**Mode:** adversarial-review-cycle
**Generated:** 2026-07-02 by in-session author + blind subagents (claude-opus-4-8, openai-codex/gpt-5.5)

## Check 1 — Constitution compliance

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I. Spec-first, EARS ACs | compliant | All behavior lands in `specs/**/spec.md` as EARS ACs; code sketch is in design.md only | — |
| II. Deterministic gate authority | compliant | Gate stays a field-reader (D1); no model call in gate path; doneness judged upstream, sealed | — |
| III. Blind adversarial review (IX) | compliant | Doneness judge is a blind subagent; provenance adapter-stamped, gate rejects `degraded-single-model` | — |
| IV. Harness-neutral core + adapters (ADR-0007) | compliant | Verdict is a file the gate reads; no-adapter path degrades to manual production, never silent pass (P1-2 fix) | — |
| V. Worktree-required at Scale ≥ M (ADR-0008) | compliant | Change declares Worktree Mode worktree-required; freshness recomputed from located worktree | — |
| VI. Frozen intent baseline | compliant | Judge baseline is frozen `intent.md`; gate compares `sha256(intent.md)` (DJ-002 fix) | — |

## Check 2 — EARS pattern check (major, human-triage)

| # | File:line | AC | True positive? | Suggested rewrite | Status |
|---|---|---|---|---|---|
| E1 | opsx-doneness-judge:Absent-or-unparseable | "…value other than satisfied or not… treat as not established" | no | keyword `not` is a verdict value, not an error event | n/a |
| E2 | gate:Unprovenanced-or-self-authored…fails | uses `degraded`/`fails` | no | describes a deterministic check outcome (IF/THEN), not a WHEN-error | n/a |

No true-positive event-as-error ACs. All failure conditions are expressed IF/THEN or as gate-check outcomes.

## Check 3 — AC↔design coverage

| AC ID | Design section reference | Status | Severity |
|---|---|---|---|
| opsx-doneness-judge.sealed-doneness-verdict-artifact | D1, How (doneness.md format) | covered | — |
| opsx-doneness-judge.blind-scope-anchored-judge | D2, D5, How (skill) | covered | — |
| opsx-doneness-judge.freshness-bound-verdict | How (gate freshness + intent-hash) | covered | — |
| opsx-doneness-judge.anti-self-forge-provenance | D1, How (adapter-stamped provenance) | covered | — |
| opsx-doneness-judge.scale-gated-with-waiver | D6, How (waiver rationale) | covered | — |
| opsx-gate-enforcement.doneness-verdict-enforcement | D1, D3, How (gate) | covered | — |
| opsx-loop-orchestration.doneness-judge-dispatch | D2, How (skill), P1-2 degraded path | covered | — |
| opsx-loop-kickoff.stall-detection-stops-the-loop | D4, How (extension) | covered | — |
| opsx-workflow-schema.mode-switchboard + artifact-graph | D6, DJ-006 template | covered | — |

## Check 4 — design↔ADR promotion candidates (Scale ≥ L)

| Decision | 4-point score | ADR-candidate? | Rationale |
|---|---|---|---|
| D1 sealed verdict, no model in gate | 4 | yes | Reverses the prior "deterministic, no LLM doneness judge" stance — ADR-worthy |
| D2 dedicated artifact + judge | 4 | yes | Lasting structural choice (two orthogonal axes); fold into the same ADR |
| D3 doneness gates loop-stop | 3 | yes | Consequential; couples to ∞-budget backstop; same ADR |
| D4 doneness-aware stall (strict-shrink) | 4 | yes | Load-bearing backstop; the sole ∞-loop guard; same ADR |
| D5 reuse review role | 1 | no | Config reuse; no dedicated role |
| D6 scale-gated waiver | 2 | no | Mirrors existing validation-source waiver |

→ Single ADR promoting D1–D4 (doneness-judge introduction + backstop) at archive.

## Check 5 — Duplicate detection

| # | Locations | Restated constraint | Action |
|---|---|---|---|
| Dup1 | doneness-judge:Freshness + gate:Doneness-Verdict-Enforcement | freshness/intent-hash/diff-base match | differentiate — capability defines "not established", gate defines the failed check (intentional layering, I3) |
| Dup2 | doneness-judge:Anti-Self-Forge + gate:Unprovenanced | adapter-stamped provenance | differentiate — same layering; not a true duplicate |

## Check 6 — Implementation language in specs

| # | AC ID | Tech mentioned | Rewrite suggestion |
|---|---|---|---|
| Imp1 | doneness-judge / gate | `sha256`, `Diff Base SHA..HEAD` | kept — these are normative identity/freshness constraints (carve-out, mirrors code-review freshness), not solution-prescribing |

## Check 7 — Unresolved clarify findings

| # | clarify.md ref | Status | Risk |
|---|---|---|---|
| U1 | A1 | answered (flipped to B: strict-shrink) | none — closes the ∞-loop hole (P0-1) |
| U2 | A2, A3, I1–I3, C1–C4 | answered | none |

## Adversarial review rounds

- **Round 1 (blind, opus-4-8 + gpt-5.5):** both REQUEST-CHANGES. Combined 2 P0 + 2 P1 + P2s.
  - P0-1/DJ-003: gap-set backstop defeatable (any-difference resets) → **fixed** strict-shrink (clarify A1→B; loop-kickoff stall rewrite; D4).
  - P0-2/DJ-001: provenance self-attested → **fixed** adapter-stamped, gate rejects `degraded-single-model` (doneness-judge + gate + orchestration).
  - DJ-002/P2-1: gate never verified intent-hash/diff-base → **fixed** `sha256(intent.md)` + immutable Diff Base compare (doneness-judge Freshness + gate).
  - P1-1: doneness not guaranteed sole failed-check → **fixed** emit-only-as-sole-remaining + doneness.md is mode-conditioned verdict not structural artifact (gate).
  - P1-2: no degraded/no-adapter path → **fixed** degraded-single-model + manual-production escape (orchestration).
  - DJ-004: waiver rationale unenforced → **fixed** `doneness_waiver_rationale` required + gate fails bare waiver (doneness-judge, schema, gate).
  - P2-2/3/4/5, DJ-005/6: sentinel gap-set; gap-signal only for `not`; `Doneness Mode` in switchboard + front-matter scenario; WHEN/WHEN symmetry; `templates/doneness.md` required → **all fixed**.
- **Round 2 (blind convergence, opus-4-8 + gpt-5.5):** both REQUEST-CHANGES (opus 1 P0 + 1 P1; gpt 2 P1). Core: the per-prior-eval strict-shrink was still defeatable by asymmetric oscillation ({a,b}→{a}→{a,b}→{a}).
  - P0-1 (opus): oscillation defeats backstop; two scenarios contradict → **fixed** monotonic ratchet against running minimum `min_gaps` (reset only on proper-subset-of-min; reset min on failed-set/worktree change or green).
  - P1-1 (opus): preserved live reset scenario unqualified, overlaps doneness carve-out; stale-`not` undefined → **fixed** narrowed reset scenario to exclude `{doneness}`-not/absent/unparseable; added re-judge-before-stall scenario (HEAD advance alone doesn't reset).
  - R2-GPT-02 (P1): activation predicate omitted absent/unparseable; reliance on gate free-text message → **fixed** activation = `{doneness}` sole AND state ∈ {not, absent, unparseable}; extension classifies by parsing `doneness.md` directly, not the gate message.
  - R2-GPT-01 / P2-2 (opus): adapterless-green overclaim → **fixed** de-claimed; enforcement (not green) survives adapter removal; green only via dispatch-capable harness or rationaled waiver.
  - P2-1 (opus): "cannot self-forge" overclaim vs same-UID actor → **fixed** softened to tripwire posture matching in-session authoring marker.
  - P2-3 (opus): orchestration dispatch precondition narrower than gate (bare-waiver gap) → **fixed** added bare-waiver-resolved-within-loop scenario.
  - R2-GPT-03 (P2): positive waiver scenario omitted rationale → **fixed** added non-empty rationale + renamed.
- **Round 3 (blind convergence, opus-4-8 + gpt-5.5):** gpt APPROVE (0/0/0); opus REQUEST-CHANGES (0 P0 + 1 P1 + 3 P2). The running-minimum ratchet, deterministic-gate invariant, anti-forge chain, and waiver coherence all verified sound.
  - DJ-1 (P1): degraded/unprovenanced `satisfied` reopened the ∞-loop adapterless (routed to defeatable content/HEAD signal; re-judge cannot self-heal a structural no-adapter cause) → **fixed** (orchestration no-adapter branch now leaves `doneness.md` absent or seals `Doneness: not`, never a degraded `satisfied`; maps adapterless state to the bounded gap-set/∅ signal so the loop STALLS).
  - DJ-2 (P2): ∅ sentinel could manufacture a spurious progress reset → **fixed** (empty-set sentinel is NOT progress and does NOT overwrite `min_gaps`; only a NON-EMPTY proper-subset reduction is progress; loop-kickoff prose + dedicated scenario).
  - DJ-3 (P2): canonical parse-only invariant omitted doneness → **fixed** (MODIFIED gate `Mode Aware Verdict Reading` now enumerates doneness alongside verify/code-review as a mode-conditioned, parse-only verdict).
  - DJ-4 (P2): clarify C4 mixed `{doneness, code-review}` set is unreachable by gate suppression → **fixed** (clarify C4 note added; gap-set signal applies iff `{doneness}` is the sole emitted failure).
- **Round 4 (blind convergence, opus-4-8 + gpt-5.5):** **both APPROVE — 0 P0 / 0 P1.** gpt 0/0/0; opus 0/0/2. The two opus P2s are ACCEPTED-not-fixed: (P2-1) schema front-matter scenario enumeration — already complete on disk (enumerates `validation_source_mode` + `doneness_mode`; stale read); (P2-2) provenance-degraded-`satisfied` routing — explicitly out-of-threat-model (unreachable in autonomous flow per DJ-1; only a same-UID manual forge produces it, conceded), left unedited to avoid staling the converged verdict range. Both scratch reviews in `.rev4-*.md`.

## Outstanding risks

- R (judge false-positive): a blind scope-anchored judge could seal `satisfied` on an unmet intent; mitigated by freshness re-judge on every commit + adapter-stamped provenance traceability. Tracked, accepted.
- R (gap-set parse brittleness): fixed `## Gaps` bullet format + normalization; absent/unparseable ⇒ `not` + empty-set sentinel (fail-safe). Tracked.

## Summary

- Blockers: 0 (all round-1/2/3 P0/P1 resolved)
- Major findings: 0 open
- Minor findings: 0 open (round-4 P2s accepted-not-fixed with rationale above)
- **Gate status:** READY for tasks — round-4 blind convergence: both reviewers APPROVE, 0 P0 / 0 P1
