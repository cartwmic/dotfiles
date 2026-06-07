# Clarify Findings

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | pi-ntfy-notify.notify-on-turn-end | "An assistant turn ends" is ambiguous between pi's `turn_end` (fires per LLM turn, multiple times per prompt incl. mid-tool-call) and `agent_end` (fires once per user prompt, when the agent returns to awaiting input). | Bind to `agent_end` — one notification per prompt, when pi is actually awaiting input | Bind to `turn_end` — notify on every internal LLM turn (noisy; fires mid-tool) | answered | **A.** Goal is "know when awaiting input"; `agent_end` is the awaiting-input boundary. Prior decision "every agent turn end" = every prompt's end, not every internal turn. Spec language "turn" means the `agent_end` cycle. |
| A2 | pi-ntfy-notify.notification-identifies-session | "Active terminal-multiplexer session name" — required field, or best-effort when no multiplexer is present? | Include multiplexer name when available; omit gracefully when absent | Treat multiplexer name as mandatory (error/blank when not under zellij) | answered | **A.** Read from `ZELLIJ_SESSION_NAME`; when unset (no multiplexer), omit that segment. Notification still delivered with pi session name only. |
| A3 | pi-ntfy-notify.notification-includes-content-excerpt | "Text-only excerpt of the last assistant message" — does it include the assistant's reasoning/thinking text, or only the user-facing response text? | Response text only — exclude reasoning/thinking blocks | Include reasoning text in the excerpt | answered | **A.** Excerpt the final response text only; reasoning excluded (less leak, more relevant to "what is it asking me"). |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | notify-on-turn-end, no-op-when-unconfigured | Interactive turn ends AND no channel configured | "deliver notification" vs "take no action" | ambiguous which wins | unconfigured precedence: no-op wins | answered | **B.** `no-op-when-unconfigured` takes precedence; the configured-channel precondition gates `notify-on-turn-end`. Made explicit: notify only WHEN a channel is configured. |
| I2 | notify-on-turn-end, delivery-failures-are-non-fatal | Turn ends, channel configured, delivery attempted | none (complementary: deliver vs swallow-on-failure) | n/a | n/a | answered | No conflict. Failure path is a refinement of the deliver path. |

## Pass 3 — Completeness (event/state combination enumeration)

Declared events: `assistant turn ends`. Declared states: interactive/non-interactive, configured/unconfigured, willRetry/not-retry, last-message has-text/no-text.

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | turn ends via user abort/interrupt (Esc) | Should an aborted/interrupted turn notify? | Treat as undefined; rely on whether `agent_end` fires | Notify on abort too — user is awaiting input again | answered | **B (soft).** If `agent_end` fires for aborts, notify normally (still an awaiting-input boundary). No special-casing; whatever boundary pi reports as `agent_end` triggers a notification. No extra AC needed — covered by `notify-on-turn-end`. |
| C2 | turn ends, channel configured, but no network/DNS on host | Covered? | — | — | answered | Covered by `delivery-failures-are-non-fatal` (channel unreachable scenario). No gap. |
| C3 | multiple concurrent pi sessions each end a turn | Dedup/grouping needed? | Each session notifies independently (no dedup) | Add dedup/replace AC | answered | **A.** Per-session independent notifications; identity fields disambiguate. Dedup explicitly out of scope (proposal non-goals). |

## Outstanding (status != answered)

- None. All findings answered.

## Summary

- Pass 1 findings: 3; unanswered: 0; deferred: 0
- Pass 2 findings: 2; unanswered: 0; deferred: 0
- Pass 3 findings: 3; unanswered: 0; deferred: 0
- **Gate status:** READY for design
