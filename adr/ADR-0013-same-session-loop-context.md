# ADR-0013: The opsx loop runs same-session, not fresh-context-per-iteration

**Status:** Accepted
**Date:** 2026-07-02
**Source change:** direct-edit audit remediation (docs/audits/2026-07-02-opsx-workflow-audit.md, finding 10)
**Supersedes:** —
**Superseded by:** —

## Context

The 2026 consensus for autonomous coding loops (Ralph Wiggum pattern, Anthropic
long-running-harness guidance) favors a FRESH context per iteration: each worker turn
spawns a new session whose entire input is the worker prompt + gate report + file/git
state, so iteration N is independent of the mistakes and stale assumptions of turns
1..N-1. The opsx-loop pi extension instead re-injects continuation turns into ONE live
session via `sendUserMessage(followUp)`; context accumulates across the whole run.

The 2026-07-02 audit flagged this as the one deliberate architectural divergence from
best practice that was undocumented.

## Decision

Keep the same-session loop, and document the trade-off here rather than refactor.

Rationale:
- **Visibility & steering**: the user watches every turn live in the TUI and can steer
  mid-loop by typing; fresh-per-iteration hides work in subprocesses.
- **Simplicity**: `agent_end` + `sendUserMessage` is the validated, minimal mechanism
  (ADR-0001/0004); per-iteration spawning adds process management, abort plumbing, and
  new failure modes.
- **Existing mitigations for context rot**: state already lives in files/git (review.md
  front-matter, tasks.md, sealed verdicts, commits) — the fresh-context prerequisite is
  met; the stall detector (failure-key + progress token + doneness gap-set ratchet)
  terminates unproductive long streaks; the frozen intent.md keeps the baseline immune
  to drifting session beliefs; blind subagent reviewers/judges run in separate contexts,
  so verdicts are NOT contaminated by the builder session.
- **Escape hatches exist**: the harness-agnostic `opsx loop` bash driver IS the
  fresh-context pattern (pipes the prompt into a fresh `$AGENT_CMD` per iteration) and
  remains available; a wedged session can be cleared and re-armed with
  `/opsx-loop <change>` at any time, losing nothing (all state is in files).

## Consequences

- Long red streaks accumulate context and can hit compaction; the stall detector
  (STALL_LIMIT=3 no-progress turns) bounds how long that can continue unproductively.
- If future evidence shows quality degradation on long loops, the recorded upgrade path
  is a hybrid: same-session until stall/threshold, then restart the worker fresh from
  gate report + files. This ADR should then be superseded, not silently ignored.
