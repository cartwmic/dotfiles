# Proposal: simplify-and-parallelize-opsx-workflow

## Why

The opsx workflow must support 2–3 concurrent loops on the same repo (different
changes, different pi sessions, worktrees) — a real solo-developer requirement,
not a team feature. An independent simplicity audit (audit.md, verdict: mixed)
found (a) the pre-audit concurrency plan over-engineered (locks/nonces guarding
windows a human already gates), (b) the M tier stacking five blind judgment
layers + nine documents on "typical feature" changes, (c) the Scale system
advertising five tiers when the gate distinguishes only three, and (d) the top
under-investment: no cross-session visibility of the loop fleet. This change
implements the audit-lean concurrency set and the accepted simplification
findings in one coordinated schema-surgery pass (intent.md, frozen fbc9ad9).

## What Changes

### A — Concurrency (audit-lean)

- **A1 land-base-current:** archive/land precondition — `merge-base(opsx/<change>,
  main) == main HEAD`. Deterministic git plumbing; forces rebase-before-land;
  the rebase staleness-fires a fresh review (accepted cost).
- **A2 path-scoped main commits:** loop-driven integration-checkout commits use
  `git commit -- <paths>`; a deterministic detector flags any main commit
  touching more than one `openspec/changes/<change>/` dir (detection, not
  prevention).
- **A3 duplicate-ADR-number scan** at archive.
- **A4 worktree ensure refuse/reuse rules:** reuse iff existing worktree
  validates on branch `opsx/<change>`; refuse loudly; never auto-delete.
- **A5 `opsx status` fleet view:** read-only, deterministic, model-free scan of
  all active changes: gate summary + last failing check, Scale, worktree path +
  health, `loop_hold` + reason, Diff Base staleness vs main HEAD.

### B — Simplification

- **B1 M-tier thinning:** at Scale M the doneness question rides the
  code-review dispatch (no separate dispatch) with the verdict still written to
  a separate `doneness.md` (gate artifact check, freshness binding, and the
  Scale≥M doneness policy unchanged); clarify folds into the proposal's
  Open Questions section at M; analyze thins to its deterministic checks at M.
  The full independent stack (standalone blind clarify, analyze, independently
  dispatched doneness judge) is retained at the top tier.
- **B2 Scale collapse 5→3:** XS / S / M as the gate-real tiers; ADR promotion,
  adversarial-on-analyze, and retrospective become an explicit opt-in
  front-matter flag (`full_rigor` extras) instead of hidden L/XL consequences.
  Former L/XL ⇒ "M + flag".
- **B3 spec consolidation 12 → ~8:** merge opsx-loop-kickoff +
  opsx-loop-orchestration into one loop capability; merge
  opsx-review-convergence + opsx-post-impl-review into one adversarial-review
  capability; fold opsx-doneness-judge's requirements into the review + gate
  capabilities per B1. Documentation topology only: every surviving requirement
  and scenario preserved or explicitly retired with rationale.
- **B4 riders:** XS/S auto-downgrade to `same-tree` worktree mode unless
  overridden (worktree-required default stays at M); drop the project-layer
  models yaml (env > front-matter > user > default); goal-loop spec gains an
  explicit deprecation/fallback status note.

## Non-goals (from intent)

Per-change flock / PID stale-lock healing; distill nonce; branch-first
authoring + `.opsx-control`; in-session multi-loop; semantic latch matching;
weakening the 2-model adversarial code review; automating archive/merge/push/
deploy; removing goal-loop; rewriting archived changes to new tiers;
multi-user features.

## Impact

| Surface | Change |
|---|---|
| `dot_local/bin/executable_opsx` | `opsx status` verb (A5); land-base-current + ADR-dup + multi-dir-commit checks (A1/A2/A3) wired into gate/archive paths; ensure refuse/reuse hardening (A4); 3-tier scale table + flag (B2); M-tier artifact-requirement changes (B1) |
| `dot_pi/agent/extensions/opsx-loop/` | consume 3-tier scale + flag; doneness dispatch routing at M (B1); no lock/nonce machinery |
| `dot_local/share/openspec/schemas/opsx-superpowers/` | README Scale table 5→3 + flag; templates (review.md front-matter: flag, tier vocabulary; doneness/code-review templates for the combined M dispatch) |
| `openspec/specs/` | consolidation per B3 (merges + retirements via delta specs); goal-loop deprecation note; opsx-gate-enforcement + opsx-cli + opsx-workflow-schema + opsx-model-config deltas |
| Skills (`dot_local/share/agent-harness/canonical/skills/`) | openspec-loop, openspec-propose, openspec-apply-change refs, openspec-archive-change: A2 commit discipline, B1 dispatch shape, B2 tier vocabulary, A1 land precondition — Constitution IX applies |
| Tests | `tests/opsx-cli`, `tests/opsx-gate`, `tests/opsx-models`, `tests/opsx-review-convergence`, extension bun tests: updated + new coverage for A1–A5, B1, B2, B4 |

## Capability homes for deltas

- `opsx-gate-enforcement` — A1 land check, A3 archive scan, B1 per-tier
  artifact requirements, B2 tier vocabulary.
- `opsx-cli` — A5 `opsx status`, A2 detector, A4 ensure rules.
- `opsx-workflow-schema` — B2 tiers + flag, B4 same-tree downgrade, B1
  per-tier review stack, A2 commit discipline rule.
- `opsx-loop` (NEW, consolidates opsx-loop-kickoff + opsx-loop-orchestration) —
  loop behavior unchanged except tier consumption; consolidation deltas.
- `opsx-adversarial-review` (NEW, consolidates opsx-review-convergence +
  opsx-post-impl-review + doneness-judge requirements) — B1 dispatch shapes.
- `opsx-model-config` — B4 drop project layer.
- `goal-loop` — B4 deprecation note.

## Open Questions

None blocking — decisions settled in intent.md (frozen). Clarify pass will
stress the consolidation mapping (B3) and the B2 flag semantics.
