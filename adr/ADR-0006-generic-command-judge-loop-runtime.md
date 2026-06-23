# ADR-0006: The loop runtime is the generic goal extension with a pluggable command-judge

**Status:** Accepted
**Date:** 2026-06-22
**Source change:** `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/`

## Context

The opsx drive-to-completion loop needs a continuation engine (inject turns,
budget, judge, status). The pi `goal` extension already is one. We did not want
to build an opsx-coupled loop extension (Constitution II: integrated, not coupled).

## Decision Drivers

- Reuse battle-tested machinery over rebuilding.
- Keep the runtime generic so it drives ANY gated workflow, not just opsx.
- The "delete the extension, workflow still runs" litmus.

## Considered Options

### Option A: Add a pluggable command-judge to the generic goal extension
Judge may be a model (existing) OR a shell command whose exit code is the verdict
(`PI_GOAL_JUDGE_CMD` / `config.judgeCommand`). opsx plugs in as worker = skill,
judge = `opsx-gate`. The extension never learns the word "opsx".

**Pros:** maximal decoupling; reusable; small additive change; model judge unchanged.
**Cons:** command judge evaluates external state (outside the transcript) — required a
MODIFIED "Judge Each Completed Turn" to scope the transcript-only rule to the model judge.

### Option B: Build an opsx-coupled loop extension
**Cons:** couples a harness extension to opsx; duplicates the goal engine.

### Option C: Bash-only loop (no extension)
**Cons:** loses in-session orchestration, native subagents, UI; kept as the fallback (ADR-0007).

## Decision Outcome

**Chosen option:** A.

**Rationale:** the generic command-judge makes the runtime reusable and leaves opsx
substance entirely in the `openspec-loop` skill + `opsx-gate` CLI. Deleting the
extension loses only continuation convenience.

## Consequences

**Positive:** goal extension stays opsx-agnostic; one engine for any gated loop.
**Negative:** command judge can inspect filesystem/git (power that must be wired carefully).
**Neutral:** non-fatal on judge exec failure (treated as not-met).

## Links

- `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/design.md` (Decision D2)
- Related: ADR-0002 (separate judge model), ADR-0005, ADR-0007
