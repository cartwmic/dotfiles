# ADR-0002: Use a separate, configurable judge model for the goal loop

**Status:** Accepted
**Date:** 2026-06-07
**Source change:** `openspec/changes/add-pi-goal-extension/`

## Context

The defining feature of a `/goal`-style loop is that a *fresh* model — not the one doing the work — decides whether the completion condition is met. The `goal-loop` extension must pick and authenticate that judge model from within an extension, using only the pi APIs available (`ctx.modelRegistry`, `complete()` from `@mariozechner/pi-ai`).

## Decision Drivers

- Independent evaluator: the judge must not be the worker (avoids self-grading bias).
- Must reuse pi's credential resolution — no API keys in source (constitution Principle III).
- Must degrade gracefully when a preferred judge is unauthenticated.
- Cheap/fast by default (one judge call per turn).

## Considered Options

### Option A: resolve a small judge model by precedence, separate from the worker
Precedence: `PI_GOAL_JUDGE_MODEL` env → `config.json` `judgeModel` → built-in small-model preference list (`anthropic/claude-haiku-4-5` → `deepseek/deepseek-v4-flash`) → fall back to `ctx.model`. First that returns `getApiKeyAndHeaders().ok` wins.

**Pros:**
- Independent evaluator; user-configurable; survives missing auth via fallback.
- Reuses pi's auth (no secrets in source).

**Cons:**
- A misconfigured judge model silently falls through to the session model.

### Option B: reuse the worker/session model as judge
**Pros / Cons:** Simplest, but the worker grading its own output biases toward "done" and defeats the entire worker/judge split.

### Option C: a single hard-coded judge model
**Pros / Cons:** Predictable, but breaks the moment that provider is unauthenticated and removes user control.

## Decision Outcome

**Chosen option:** A

**Rationale:** The worker/judge separation *is* the feature; a configurable preference list with an auth-aware fallback keeps it independent, robust, and cheap while honoring Principle III.

## Consequences

**Positive:**
- Independent, configurable, fault-tolerant judging; no secrets in source.

**Negative:**
- Fallback-to-session-model can mask a typo'd `judgeModel`; surfaced only via the verdict reason.

**Neutral:**
- Judge cost is one small-model call per turn — negligible vs the main turn.

## Links

- Source design discussion: `openspec/changes/add-pi-goal-extension/design.md` (Decision D2; see also D3 capture path, D11 prompt placement)
- Related ADRs: ADR-0001, ADR-0003
