# Analyze Findings

**Mode:** adversarial-review-cycle (Scale L)
**Generated:** 2026-06-20 by orchestrator + blind reviewer subagents

## Check 1 — Constitution compliance

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I. Chezmoi single source of truth | compliant | All new files at chezmoi source paths (`dot_local/bin/`, `dot_local/share/...`, `dot_pi/...`) | — |
| II. Skills in canonical pipeline | compliant | `openspec-loop` at `dot_local/share/agent-harness/canonical/skills/` | — |
| III. No secrets in source | compliant | No credentials introduced | — |
| IV. Install scripts idempotent | inapplicable | `opsx-gate`/`opsx-loop` are CLIs, not install scripts | — |
| V. mise owns dev-tool install | compliant | `yq` added via mise task, not run_onchange | — |
| VIII. openspec workspace not deployed | compliant | Deliverables ship via `dot_*` paths; the openspec/ change dir is workspace-only | — |
| IX. Skill edits get adversarial review ≥ M | compliant | This change edits apply/archive/explore skills at Scale L → adversarial review invoked (this artifact) | — |
| X. Memory promotion opt-in | inapplicable | No memory writes in this change | — |

## Check 2 — EARS pattern check (major, human-triage)

| # | File:line | AC | True positive? | Suggested rewrite | Status |
|---|---|---|---|---|---|
| E1 | opsx-gate-enforcement: manifest-validation-execution | "WHEN a manifest gate command exits non-zero" | no | A non-zero exit is the nominal input the gate observes, not an error of the gate; WHEN is correct | n/a |
| E2 | goal-loop: pluggable-command-judge | "WHEN ... the judge command exits non-zero" | no | Same — observing a not-met verdict is nominal loop behavior | n/a |

## Check 3 — AC↔design coverage

| Capability | Design reference | Status |
|---|---|---|
| opsx-gate-enforcement | D1, D6 | covered |
| opsx-loop-orchestration | D3, D7, D8 | covered |
| opsx-post-impl-review | D5 | covered |
| goal-loop | D2 | covered |
| opsx-workflow-schema | D4, D6 | covered |
| opsx-skill-integration | D3, D8 | covered |

## Check 4 — design↔ADR promotion candidates (Scale ≥ L)

| Decision | 4-point score | ADR-candidate? | Rationale |
|---|---|---|---|
| D1 enforcement = exit-code CLI | 4 | yes | Foundational, contestable, constrains everything downstream |
| D2 generic command-judge in goal ext | 4 | yes | Decoupling decision with lasting consequence |
| D3 orchestrator primary, Ralph fallback | 4 | yes | Execution-model choice, reasonable disagreement |
| D4 worktree-required default all Scales | 4 | yes | BREAKING default; clear ADR |
| D5 code-review skill-managed not graph | 3 | yes | Mirrors prior skill-managed rationale |
| D6 opsx-gates.yaml manifest | 1 | no | Format choice; low lasting impact |
| D7 blind-subagent review vs baseline | 3 | yes | Independence/enforcement-separation decision |
| D8 frozen intent.md | 2 | no | Sensible, low contestability |

## Check 5 — Duplicate detection

| # | Locations | Restated constraint | Action |
|---|---|---|---|
| Dup1 | opsx-loop-orchestration.subagent-review-against-baseline + opsx-post-impl-review (baseline) | Both describe the phase-keyed review baseline | differentiate — loop states the general rule; post-impl applies it to the diff. Design D7/D5 keep them distinct. minor |

## Check 6 — Implementation language in specs

| # | AC ID | Tech mentioned | Note |
|---|---|---|---|
| Imp1 | opsx-workflow-schema.worktree-lifecycle-ownership | `git worktree`, branch `opsx/<change>` | Behavioral interface contract; consistent with the existing spec's git-level detail. minor — acceptable |
| Imp2 | opsx-gate-enforcement.* | `opsx-gates.yaml`, `OPSX_VALIDATE`, `git diff` | These are the capability's public interface names, not incidental tech. minor — acceptable |

## Check 7 — Unresolved clarify findings

| # | clarify.md ref | Status | Risk |
|---|---|---|---|
| — | A1, A2, A3, I1, C1, C2, C3 | all answered | none |

## Outstanding risks

- Markdown-scraping of Scale/Code-Review-Mode by `opsx-gate` is brittle (design Open Question): consider machine-readable review.md fields. Tracked, not a blocker.

## Adversarial review appendices

Blind reviewers (review-plans skill, no cross-talk). Round 1. Three dispatched;
one (claude-opus-4-8) failed on a provider usage cap. Two returned substantive
reviews; both verdicts REQUEST-CHANGES with strongly convergent findings.

### Appendix A — reviewer gpt-5.5 (openai-codex)
12 findings (OPSX-001..012). Key: OPSX-001 advisory code-review block contradiction (P0);
OPSX-002 permissive Scale default unsafe (P1); OPSX-003 worktree topology underspecified (P1);
OPSX-004 gate report not machine-readable (P1); OPSX-005 verify not mode-aware (P1);
OPSX-006 code-review production vs clarify C3 contradiction (P1); OPSX-007 pi-subagents naming
vs harness-neutral (P1). Verdict: REQUEST-CHANGES.

### Appendix B — reviewer deepseek-v4-pro
13 findings (F1..F13) + challenged assumptions. Key: F1 spec/clarify code-review contradiction (P0);
F2 same-tree diff base undefined (P0); F3 markdown parse = silent-green single point of failure (P1);
F4 D1 single-source contradicted by archive re-enforcement (P1); F5 worktree creation failure modes (P1);
F6 loop budget unconfigured (P1); F7 modified-vs-new capability classification (P1). Verdict: REQUEST-CHANGES.

### Convergence + resolution

| Theme | Reviewers | Severity | Resolution |
|---|---|---|---|
| code-review production vs mode=none (clarify C3) | A:OPSX-006, B:F1 | P0 | Fixed: AC gated on mode ≠ none + None-mode suppress scenario |
| advisory code-review/verify must not block gate | A:OPSX-001/005, B:(F1) | P0/P1 | Fixed: gate "Mode Aware Verdict Reading" conditions on Verification/Code Review Mode |
| same-tree diff base undefined | B:F2 | P0 | Fixed: diff-base scenario for worktree + same-tree |
| markdown parse → silent-green gate | A:OPSX-004, B:F3 | P1 | Fixed: D5b machine-readable review.md front-matter; gate reads structured fields |
| D1 single-source vs archive re-check | B:F4 | P1 | Fixed: D1 reworded "primary source" + archive defense-in-depth |
| permissive Scale default unsafe | A:OPSX-002 | P1 | Fixed: absent/unparseable Scale fails the gate |
| worktree creation/branch failure modes | A:OPSX-003/012, B:F5 | P1 | Fixed: reuse-existing + abort-on-failure + preserve-on-budget ACs |
| loop budget unconfigured | B:F6 | P1 | Fixed: `loop_max_iterations` front-matter + Scale defaults |
| degraded inline review loses adversarial quality | B:F10/A1 | P2 | Fixed: degraded-mode scenario notes loss + recommends manual cycle |
| goal command-judge config point | B:F9 | P2 | Fixed: config-precedence scenario in goal-loop |
| pi-subagents naming vs harness-neutral | A:OPSX-007 | P1 | Acknowledged: pre-existing schema coupling at Delegation layer; subagent dispatch is a capability hook with inline fallback (design D7/capability-hooks). Tracked, not expanded here |
| worktree-required at all Scales vs M+ only | B:alt2/A2 | scope | Owner decision: keep all-Scales (explicit "default for all sizes"); same-tree override documented |
| gate report JSONL schema | A:OPSX-004 | P2 | Deferred to tasks/impl detail (design Open Question) |
| manifest required:false / OPSX_VALIDATE format | A:OPSX-009/010 | P2 | Deferred to tasks/impl detail |
| modified-vs-new capability classification | B:F7 | P1 | Reviewed, not a defect: the three are existing capabilities; ADDED-only deltas to existing specs are valid and `openspec validate --strict` passes |

### Appendix C — reviewer claude-opus-4-8 (claude-bridge), round 2
Deeper review over the full artifact set (incl. tasks/plan). 1 P0 + 5 P1 + P2s. Verdict: REQUEST-CHANGES. All applied:

| # | Finding | Sev | Resolution |
|---|---|---|---|
| P0-1 | Gate reads agent-authored verdicts verbatim (no freshness/provenance) → "cannot talk past" false | P0 | Fixed: D9 Verdict Freshness And Provenance — record reviewed base..HEAD + provenance; gate fails stale/unprovenanced; proposal claim scoped |
| P1-2 | cheap→expensive ≠ dependency order within artifacts | P1 | Fixed: lifecycle emission-order scenario |
| P1-3 | yq needed Step 1 but installed Step 5; jq can't read YAML front-matter | P1 | Fixed: front-matter parsed sed/awk dep-free; yq reserved for manifest + pulled to Step 1 |
| P1-4 | worktree isolation vs chezmoi fixed source root; deploy checks can't validate from worktree | P1 | Fixed: D10 — deploy checks post-merge / `--source`; never apply real home from worktree; Risk row |
| P1-5 | manifest optional → loop reaches GATE-PASS with no agent-independent check | P1 | Fixed: Scale≥M requires ≥1 validation source else UNVERIFIED; live opsx-gates.yaml task (T1.5) |
| P1-6 | Constitution IX claimed by analyze (plan review), not the skill diffs | P1 | Fixed: code-review.md is the IX point; single-model degrade → archive blocked |
| P2-7..11 | merge conflict semantics; dual budgets; verdict authorship; front-matter↔table divergence; deferred report format | P2 | Fixed (7,8,9,10) / tracked (11 → T1.2) |

### Appendix D — round 3 (final validation): opus + gpt-5.5, blind, against revised artifacts
0 P0. ~4 P1 each, strongly convergent — all coherence breaks introduced by round-1/2 patches. All applied:

| Theme | Reviewers | Resolution |
|---|---|---|
| D5b "never scrape table" vs round-2 divergence check | opus P1-1 | front-matter sole source; divergence check dropped; table is docs |
| degraded inline review re-opened D9 self-attestation | opus P1-2, gpt REV3-003 | degraded-single-model fails gating + Constitution IX; provenance adapter-stamped |
| command-judge vs unmodified transcript-only rule | opus P1-3 | MODIFIED Judge Each Completed Turn (transcript-only scoped to model judge) |
| intent.md baseline not gate-required; emission-order omits analyze/review | opus P1-4 | intent.md required at M+; emission order reconciled |
| worktree reuse reset freshness base | gpt REV3-001 | Diff Base SHA = merge-base, immutable; reuse preserves or halts |
| code-review trigger deadlock under advisory verify | gpt REV3-002 | trigger = pre-review checks green, not verify-specifically |
| UNVERIFIED warning vs non-bypassable thesis | opus P2-3, gpt REV3-004 | Scale≥M missing source = FAIL unless validation_source_mode:waived |
| same-tree no stored diff base | opus P2-4, gpt REV3-008 | Diff Base SHA recorded both modes + Worktree Path locator |
| required:false vs any-non-zero-fails | opus P2-2 | required:true fails, required:false warns |
| review baseline incoherent | gpt REV3-005 | unified: intent + proposal/specs/design/plan/tasks |
| proposal single-source; clarify A2; stale risk row; report format | opus P2-1/P2-5, gpt REV3-007/010 | all updated |

### Appendix E — round 4 (re-validation): opus + gpt-5.5, blind
0 P0, 3 P1 each, convergent — all reconciliation of contradictions the round-3 edits left. All applied:

| Theme | Reviewers | Resolution |
|---|---|---|
| dual base-SHA: stale `Worktree Base SHA` vs immutable `Diff Base SHA` | opus F1, gpt REV4-001 | deleted Worktree Base SHA; file-contract diffs + freshness use immutable Diff Base SHA (Per-task contracts MODIFIED) |
| same-tree base undefined; clarify C1 stale | opus F2 | clarify C1 updated; same-tree Diff Base SHA capture scenario + same-tree freshness locator |
| this change missing now-required intent.md | opus F3 | intent.md authored for the change |
| orchestration post-apply baseline omits plan/tasks | gpt REV4-002 | baseline unified to intent + proposal/specs/design/plan/tasks |
| validation cwd not bound to located worktree | gpt REV4-003 | validations run with cwd=worktree + OPSX_* env; fail if no worktree under worktree-required |
| stale plan JSONL note; validation_source_mode not listed | opus P2 | plan note → line protocol; validation_source_mode added to front-matter contract |

### Appendix F — round 5 (convergence check): opus APPROVE (0/0); gpt 1 P1
opus: 0 P0/P1, explicit APPROVE with a full convergence checklist (all green). gpt: 1 P1 (REV5-001) — the carried-over `Delegation Mode` scenario still hard-coded pi-subagents, contradicting the harness-neutral intent. Applied: rewrote it as a `subagent-dispatch` capability hook (eligible degrades inline, required fails without an adapter; pi-subagents = the pi adapter only).

### Appendix G — round 6 (final sign-off): BOTH APPROVE, 0 P0/P1
opus and gpt-5.5 both returned explicit APPROVE with no remaining P0/P1. Stop condition met (both approve + P0+P1=0). One non-blocking note (opus): leave verdict artifacts uncommitted until the gate passes so producing them doesn't self-stale the range — captured in plan.md Notes for T6.1 dogfood.

### Convergence trajectory
| Round | Reviewers | P0 | P1 | Verdict |
|---|---|---|---|---|
| 1 | gpt-5.5, deepseek-v4-pro | 2 | 7 | REQUEST-CHANGES |
| 2 | opus-4.8 (bridge) | 1 | 5 | REQUEST-CHANGES |
| 3 | opus, gpt-5.5 | 0 | ~8 | REQUEST-CHANGES |
| 4 | opus, gpt-5.5 | 0 | 3 | REQUEST-CHANGES |
| 5 | opus, gpt-5.5 | 0 | 1 | opus APPROVE / gpt RC |
| 6 | opus, gpt-5.5 | 0 | 0 | **BOTH APPROVE** |

## Summary

- Blockers: 0 remaining; converged at round 6 (both reviewers APPROVE)
- (round-1 2 P0 + round-2 1 P0 resolved; rounds 3-6 0 P0)
- Major findings: 0 remaining unresolved (round-1 + round-2 P1 resolved or tracked)
- Minor findings: internal Dup1/Imp1/Imp2 + deferred-to-impl (gate JSONL, manifest semantics)
- Reviewers: gpt-5.5, deepseek-v4-pro (round 1), claude-opus-4-8 via claude-bridge (round 2). All REQUEST-CHANGES; all findings applied.
- **Gate status:** READY for tasks
