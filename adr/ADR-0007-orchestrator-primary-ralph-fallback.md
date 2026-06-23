# ADR-0007: Single-orchestrator-in-harness is the primary loop driver; Ralph bash is the portability fallback

**Status:** Accepted
**Date:** 2026-06-22
**Source change:** `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/`

## Context

Two loop-driver models exist: a single orchestrator agent that stays in-session
and dispatches subagents, or a stateless Ralph-style bash loop that re-invokes a
headless agent each iteration. We needed in-harness integration without losing
harness-agnostic execution.

## Decision Drivers

- Native subagents, context, interruptibility, status indicator (in-session wins).
- Harness-agnostic escape hatch for CI / other harness / no extension.
- Reviews must be delegated to blind subagents judged against a frozen baseline.

## Considered Options

### Option A: Orchestrator primary + Ralph bash fallback
`openspec-loop` skill drives one agent session (continued by the goal runtime,
ADR-0006), dispatching subagent reviews. The `opsx-loop` bash driver
(`AGENT_CMD`-parameterized) is the portability fallback.

**Pros:** best of both — native orchestration + a deterministic escape hatch.
**Cons:** in-session loses Ralph's stateless crash-resilience (mitigated by budget + worktree preservation).

### Option B: Ralph-only
**Cons:** no native subagents/UI; weaker review independence.

### Option C: Orchestrator-only
**Cons:** no portability hatch; couples the workflow to one harness's runtime.

## Decision Outcome

**Chosen option:** A.

**Rationale:** the orchestrator gives the day-to-day experience; the bash fallback
preserves the "delete the adapter, workflow still runs" guarantee. Subagent dispatch
is a capability hook that degrades to inline (a degraded review does not satisfy a
gating-required code-review).

## Consequences

**Positive:** integrated where it helps (kickoff, runtime, subagents), neutral where it must be (workflow, enforcement).
**Negative:** two execution paths to maintain (skill + bash).
**Neutral:** swapping harness = re-binding two thin adapters (`AGENT_CMD`, subagent dispatch).

## Links

- `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/design.md` (Decision D3)
- Related: ADR-0005, ADR-0006, ADR-0008
