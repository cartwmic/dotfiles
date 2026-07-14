# Intent — preserve-opsx-loop-across-native-retries

Status: explore-frozen

## Intent

Keep an armed `opsx-loop` active while Pi performs native retry,
auto-compaction/retry, or queued continuation after a failed low-level agent
run. The extension currently treats `agent_end(error)` as terminal and clears
the loop before Pi evaluates its own continuation policy. Pi can then retry and
successfully resume the worker turn, but the resumed work is detached from the
loop host and no longer advances through `opsx gate`.

Treat `agent_end` as an attempt boundary, not proof that worker execution is
terminal. Use Pi's `agent_settled` lifecycle signal to decide when an unresolved
error has truly exhausted every host-managed continuation. Preserve the existing
clean-turn continuation topology instead of moving the whole loop onto
`agent_settled`.

Primary outcome: a transient provider failure may remain visible in the
transcript, but Pi's successful native retry continues under the same active
opsx loop and reaches the normal gate-driven next action.

## Evidence and failure sequence

Pi 0.80.6 documents and implements this ordering:

```text
low-level run ends
  → extension agent_end handlers run
  → Pi evaluates native retry / compaction / queued continuation
  → another low-level run may continue
  → agent_settled fires only when no automatic continuation remains
```

The current `dot_pi/agent/extensions/opsx-loop/index.ts` handler clears loop
state immediately when the last assistant message has `stopReason: "error"`.
Observed Codex SSE header timeouts therefore produced this sequence:

```text
agent_end(error)
  → opsx-loop clears active state
  → Pi native retry succeeds
  → worker turn resumes without opsx-loop gate continuation
```

The timeout exposed the lifecycle mismatch; its provider-specific transport
mechanism is not the lifecycle contract this change fixes.

## Frozen design decisions

1. **Hybrid lifecycle handling.** Keep clean `agent_end` processing where it is:
   increment the worker-turn budget, inspect hold state, run `opsx gate`, and
   queue the next follow-up within Pi's existing top-level run. Use
   `agent_settled` only to resolve an error that remained unresolved after all
   Pi-managed continuation paths. A full migration of clean continuation to
   `agent_settled` is rejected because it would turn every loop iteration into a
   new top-level prompt and alter `before_agent_start`, RPC, UI, queueing,
   compaction, and cross-extension behavior.

2. **Error `agent_end` preserves the loop.** On `stopReason: "error"`, record the
   latest error outcome against the exact active loop session/generation, consume
   or reset per-attempt latches as required, and return without clearing,
   incrementing the loop turn budget, running the gate, or injecting another
   worker directive. Pi remains the sole owner of immediate retry, backoff,
   auto-compaction/retry, and queued-message continuation.

3. **Success supersedes a pending error.** A later clean `agent_end` in the same
   active loop clears the recorded error and follows the existing gate path.
   Failed low-level attempts do not count as loop progress; the eventual clean
   worker boundary counts once.

4. **Explicit user abort remains immediately terminal.** `stopReason:
   "aborted"` continues to clear the loop at `agent_end`. Resilience must never
   fight Escape, `/opsx-loop clear`, session replacement, or another explicit
   user stop.

5. **Settled unresolved errors retain existing terminal policy.** When
   `agent_settled` fires and the latest outcome is still an error belonging to
   the same active loop session, perform the existing bounded context-overflow
   recovery when applicable; otherwise stop visibly and preserve the worktree.
   A persistent overflow after the one compact-and-retry allowance still stops.

6. **Identity-guard every deferred action.** A recorded error and its later
   settled event may act only when the original loop object/generation is still
   current and active. A stop, clear, re-arm, session switch, reload, or loop
   replacement invalidates the pending outcome. A stale settled event must not
   clear, compact, notify for, or continue a newer loop.

7. **No extension-owned retry policy.** Add no retry engine, timer, backoff,
   provider/model fallback, status-code table, error-string classifier, or
   transport-recovery budget. The extension does not need to predict whether an
   error is retryable: preserving state at `agent_end(error)` and observing
   `agent_settled` delegates that decision to Pi's native policy.

8. **Provider-neutral behavior.** The lifecycle applies equally to Codex,
   Anthropic, OpenAI-compatible, bridge, and future providers. No acceptance
   criterion may depend on the text `Codex SSE response headers timed out` or any
   other provider-specific error string, except deterministic fixtures that
   prove messages are treated opaquely.

## Scope

- Update the `opsx-loop` extension lifecycle handling in
  `dot_pi/agent/extensions/opsx-loop/`.
- Update helper/unit coverage for pending-error state and loop-session identity
  if the implementation extracts testable helpers.
- Add lifecycle-level coverage proving retry-success, retry-exhaustion, abort,
  overflow recovery, stop-during-retry, and re-arm-during-retry behavior.
- Update the `opsx-loop` capability spec: a low-level worker error is no longer
  itself terminal; an unresolved error after `agent_settled` is terminal.
- Update TUI scenario coverage if needed to prove a real Pi native retry resumes
  under the still-active loop rather than only simulating direct handler calls.

## Constraints

- Preserve deterministic, model-free orchestration: the extension invokes no
  LLM and does not classify provider failures.
- Preserve current clean-turn queue topology and gate-as-judge semantics.
- Preserve immediate explicit-abort behavior and all named re-arm / `loop_hold`
  authorization invariants.
- Preserve the existing one-shot context-overflow compact-and-retry bound and
  worktree-preserving terminal landing.
- Preserve active-loop-only context elision and ensure an errored low-level
  attempt cannot leak its `elided` latch into a later successful retry.
- Do not count transient failed attempts against `Loop Max Iterations` or stall
  detection.
- Use Pi's public `agent_settled` extension hook; do not import private retry
  utilities or compiled internal modules.

## Invariants

- While Pi can still continue automatically, an errored low-level run cannot by
  itself disarm an active opsx loop.
- A successful native retry reaches exactly one normal gate evaluation and at
  most one loop continuation injection for that clean worker boundary.
- Explicit user abort always wins and cannot be undone by a later settled event.
- Deferred error handling cannot mutate a replacement or re-armed loop.
- Final exhausted errors land visibly; the extension never spins or silently
  remains armed and idle.
- The implementation remains provider-neutral and bounded by Pi's retry policy
  plus the existing opsx overflow-recovery allowance.

## Non-goals

- Fixing Codex WebSocket-to-SSE fallback stickiness or changing Pi HTTP idle
  timeout settings.
- Adding an opsx-level transport retry, model fallback, retry budget, or spending
  policy.
- Changing Pi core retry classification or exposing `willRetry` to extension
  `agent_end` handlers.
- Moving successful loop continuation wholesale from `agent_end` to
  `agent_settled`.
- Direct changes to the separately installed `pi-subagents` repository. A child
  process that prematurely treats a retryable assistant error as terminal is a
  related but independent lifecycle defect; subagent tool failures remain
  recoverable by the still-active parent worker and gate loop.
- Changing archive, merge, review-convergence, or doneness semantics.

## Acceptance sketch

- Given an active loop and `agent_end(error)` followed by Pi native retry and
  `agent_end(success)`, loop state remains active throughout, failed attempt does
  not consume a loop turn, and the successful boundary runs the gate once.
- Given repeated errors ending in `agent_settled`, the loop performs no extra
  transport retry and lands with the existing visible final-error behavior.
- Given explicit abort, loop clears immediately even if a later settled event is
  emitted.
- Given final context overflow, existing one-shot compact-and-retry behavior is
  preserved; a second settled overflow stops with worktree preserved.
- Given clear or named re-arm while retry is pending, the old settled event has
  no effect on the new loop state.
- Given any provider/error message shape with `stopReason: "error"`, behavior is
  identical without matching provider-specific text.
- Existing clean-turn, hold, gate-green, budget, stall, and compaction tests stay
  green.

## Suggested Scale

Scale: M, `full_rigor: false`.

Rationale: this is a cross-file behavioral correction within one existing
capability (`opsx-loop`), with lifecycle, spec, unit, and likely TUI scenario
coverage. It introduces no breaking migration, cross-capability architecture,
or new extension-owned retry policy that would justify `full_rigor: true`.
