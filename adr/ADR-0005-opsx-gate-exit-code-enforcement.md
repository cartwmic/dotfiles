# ADR-0005: opsx-gate is the harness-neutral exit-code enforcement spine

**Status:** Accepted
**Date:** 2026-06-22
**Source change:** `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/`

## Context

The opsx-superpowers workflow enforced nothing: per-Scale gating "lives in the
skills," `openspec validate` checks only structure, and every quality gate was
prose an LLM can ignore. We wanted enforcement that an agent cannot talk past,
integrated into the harness but not coupled to it (Constitution II).

## Decision Drivers

- LLM compliance with instructions is probabilistic; deterministic outer-harness
  constraints are not.
- Must work across pi / Claude / Codex / bare terminal (single identity, many harnesses).
- One source of truth callable by the loop, archive, git hooks, and a human.

## Considered Options

### Option A: Deterministic exit-code CLI (`opsx-gate`)
A single command reads state + manifest + verdicts and exits 0/non-zero with a
stable `GATE-FAIL <check_id> <blocking> <message>` report.

**Pros:** harness-agnostic; deterministic; one contract everything obeys.
**Cons:** verdict inputs are still agent-authored (mitigated by freshness — ADR pending/D9).

### Option B: Schema prose gating (status quo)
**Cons:** unenforceable; the problem we are solving.

### Option C: Per-harness hook logic
**Cons:** couples enforcement to one harness; re-implemented per host.

## Decision Outcome

**Chosen option:** A.

**Rationale:** a markdown framework cannot bind an LLM; only a deterministic
wrapper around it can. The gate is the **primary** source of enforcement truth;
archive re-checks the same fields as defense-in-depth for out-of-loop archiving.

## Consequences

**Positive:** enforcement lives below the harness (exit codes); swappable hosts.
**Negative:** judgment verdicts remain attestations (bound to the diff via freshness, not proof).
**Neutral:** a validation manifest (`opsx-gates.yaml`) is required at Scale ≥ M.

## Links

- `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/design.md` (Decision D1)
- Related: ADR-0006, ADR-0007, ADR-0008
