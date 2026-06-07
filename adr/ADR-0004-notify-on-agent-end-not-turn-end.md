# ADR-0004: Fire pi notifications on `agent_end`, not `turn_end`

**Status:** Accepted
**Date:** 2026-06-07
**Source change:** `openspec/changes/add-pi-ntfy-extension/`

## Context

The ntfy notification extension must alert a remote user when a pi session is
*awaiting their input*. Pi exposes several lifecycle events that fire around
assistant activity (`turn_start`/`turn_end`, `message_*`, `agent_start`/
`agent_end`). Choosing the wrong one makes the notification either too noisy
(buzzing mid-work) or too late/absent. This choice defines the core trigger of
the capability and constrains every future notification feature (toggling,
excerpts, batching).

## Decision Drivers

- The signal must mean "pi is now waiting for you," not "pi did some internal work."
- `turn_end` fires once per internal LLM turn — multiple times per user prompt,
  including between tool calls while pi is still working.
- `agent_end` fires once per user prompt, when the agent returns to the
  awaiting-input state.

## Considered Options

### Option A: subscribe to `agent_end`
One notification per prompt, at the awaiting-input boundary.

**Pros:**
- Exactly matches the user-facing meaning ("your turn").
- One notification per prompt — no mid-work noise.

**Cons:**
- Does not surface intermediate progress (acceptable; not a goal).

### Option B: subscribe to `turn_end`
**Pros:** finer-grained. **Cons:** fires repeatedly mid-prompt (including
between tool calls), contradicting the awaiting-input intent — notification spam.

### Option C: `message_end` filtered to assistant
**Pros:** message-level granularity. **Cons:** same over-firing as B, plus
fires within streaming/tool sequences.

## Decision Outcome

**Chosen option:** A — `agent_end`.

**Rationale:** `agent_end` is the awaiting-input boundary; it fires once when pi
returns control to the user, which is precisely the event the notification
should represent.

## Consequences

- The handler keys off `agent_end` and reads `event.messages` for the excerpt.
- Note (corrected during implementation): the extension-facing `AgentEndEvent`
  is `{ type, messages }` only — it has **no `willRetry` field** (that exists on
  a different internal agent-session event). Any "skip auto-retries" logic must
  not rely on `willRetry` from this event.
- Interactivity is guarded via `ctx.hasUI` (true in TUI/RPC, false in
  print/json); `ctx.isInteractive()` does not exist in pi 0.78.1.
- Future per-notification features (toggle, excerpt shaping, batching) build on
  this single trigger.
