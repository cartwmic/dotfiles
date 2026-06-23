# Design — add-opsx-loop-kickoff

## Context

The `openspec-loop` skill is a worker playbook; a skill cannot inject the next turn, so it cannot guarantee looping. The pi `goal` extension proves the mechanism (agent_end + sendUserMessage followUp + a judge + budget), but it is generic and we keep it opsx-agnostic (ADR-0006). This change adds a dedicated pi adapter that guarantees the loop for opsx, with `opsx-gate` as the judge.

References: intent.md, proposal.md, specs/opsx-loop-kickoff/spec.md, clarify.md (all answered); ADR-0001/0004 (agent_end mechanism), ADR-0006/0007.

## Goals / Non-Goals

- **Goal:** one pi command `/opsx-loop <change>` that loops deterministically until `opsx-gate` is green or the budget is hit.
- **Non-Goal:** modifying `goal` or the `openspec-loop` skill; creating worktrees; non-pi kickoff.

## Decisions

### D1 — Dedicated self-contained extension, not a goal modification
**Choice:** new `dot_pi/agent/extensions/opsx-loop/` reusing the `agent_end`/`followUp` pattern with its own small pure helpers (no cross-extension import).
**Alternatives:** add `/opsx-loop` to the goal extension (couples goal to opsx); cross-import goal helpers (fragile across deployed dirs).
**Rationale:** keeps goal generic (ADR-0006); self-contained avoids deploy-time import path issues. 4-point: multiple ✓, lasting ✓, contestable ~, constrains ✓ → ADR-worthy (note, not promoted at M).

### D2 — Judge = `opsx-gate` command via spawn; exit 0 = met
**Choice:** spawn `opsx-gate <change> [--worktree <path>]`, capture combined output, exit 0 = met. Non-fatal on spawn failure (treated as not-met).
**Rationale:** the gate is the deterministic stop (ADR-0005); no model self-assessment.

### D3 — Budget from review.md front-matter `loop_max_iterations`
**Choice:** parse `loop_max_iterations` from the change's review.md front-matter (dependency-free), default 40. Single budget governs the loop.
**Rationale:** consistency with the gate's source of truth; avoids a second disagreeing budget.

## Risks / Trade-offs

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Re-entrant agent_end during async gate run | Med | Med | `evaluating` flag guard (clarify C1) |
| Worker turn doesn't advance → spin until budget | Low | Low | Budget cap; report remaining failures on exhaustion |
| Worktree path stale/empty | Low | Med | Resolve from review.md; omit --worktree when empty (gate handles same-tree) |
| Duplication of the loop mechanism vs goal | Low | Low | Accepted: ~30 lines, keeps goal agnostic (D1) |

## Migration Plan

1. Add the extension (index.ts + helpers.ts + helpers.test.ts).
2. Tests for the pure helpers (budget parse, verdict-from-exit, arg parse).
3. Deploy via chezmoi; pi auto-discovers the extension dir.

## Open Questions

- Whether to later expose loop status in the goal status indicator namespace (cosmetic; deferred).
