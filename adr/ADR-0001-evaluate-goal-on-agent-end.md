# ADR-0001: Evaluate a pi goal loop on `agent_end`, not `turn_end`

**Status:** Accepted
**Date:** 2026-06-07
**Source change:** `openspec/changes/add-pi-goal-extension/`

## Context

The `goal-loop` pi extension reproduces Claude Code's `/goal`: after the agent hands control back to the user, a separate judge model decides whether a completion condition holds, and if not the loop injects another turn. Pi exposes several lifecycle events; the loop must evaluate at the moment that corresponds to "control returns to the user" — the analogue of Claude Code's Stop hook.

## Decision Drivers

- Must judge only *complete* worker output, never mid-tool-loop partial state.
- Must mirror the Stop-hook semantics (`/goal` fires when the agent would otherwise stop).
- Must be empirically verifiable against the live pi runtime.

## Considered Options

### Option A: hook `agent_end`
Subscribe to `pi.on("agent_end")`, which fires once per full agent run after the entire tool loop completes.

**Pros:**
- Fires exactly when control returns to the user (spike-confirmed).
- One evaluation per run; clean re-injection point.

**Cons:**
- Requires care to avoid re-entrancy from the injected follow-up turn.

### Option B: hook `turn_end`
**Pros / Cons:** `turn_end` fires per assistant message *within* the agent loop (between tool calls), so it would judge incomplete work and fire multiple times per run. Wrong granularity.

### Option C: poll session state on a timer
**Pros / Cons:** No native hook dependency, but racy, wasteful, and cannot align with turn boundaries.

## Decision Outcome

**Chosen option:** A

**Rationale:** A spike (`pi -p … -e`) confirmed `agent_end` fires once per full run at the control-return boundary, and that `sendUserMessage(..., {deliverAs:"followUp"})` from inside the handler drives the next turn. `turn_end` mid-loop firing makes it unusable for completion judging.

## Consequences

**Positive:**
- Correct evaluation boundary; deterministic one-eval-per-run with a re-entrancy guard.

**Negative:**
- Couples the extension to pi's `agent_end` event shape (`{messages}`).

**Neutral:**
- The same hook carries the message list used for transcript + `stopReason` (interrupt detection).

## Links

- Source design discussion: `openspec/changes/add-pi-goal-extension/design.md` (Decision D1)
- Related ADRs: ADR-0002, ADR-0003
