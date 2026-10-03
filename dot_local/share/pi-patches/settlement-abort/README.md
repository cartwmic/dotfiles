# Settlement abort

Tested against **Pi 0.99.2 and 1.0.0**, including its actual bundled CLI and unbundled
`dist/cli.js`. Enabled on `personal` and `axon-work-computer`; other profiles
(including unset) reverse only this patch's exact blocks, preserving siblings.

Pi's low-level agent clears its signal before `agent_before_settle`. Previously,
ordinary RPC abort or TUI Escape during that boundary could not cancel nested
work through `ctx.signal`, and returned proposals were committed before Pi
checked the abort flag. Final `agent_settled` handlers also need cancellation:
upstream marks the session non-streaming before awaiting these handlers, so
Escape otherwise does not call session abort.

This patch owns one AbortController for `_runAgentPrompt`: it survives low-level
continuations, retries and automatic compaction, fires synchronously from
`session.abort()`, and remains available throughout awaited notification-only
`agent_settled` handlers. `isStreaming` includes this final settlement phase;
`isIdle` preserves upstream main-agent idle semantics
(`!_isAgentRunActive && !isCompacting`), so idle-guarded settled consumers can
publish READY. Idle here does not mean all notification work has finished.
Escape uses `isStreaming`; internal `waitForIdle()` and its resolver use the
busy/compacting predicate so RPC abort still waits for handlers to finish. The settled-dispatch finalizer clears its captured controller
before deferred prompts run. An exception-safe outer operation finalizer also
clears its own controller, but only when identity still matches: it cannot clear
a newer operation's controller. A new operation gets a new controller.
`ctx.signal` uses that operation signal, falling back to the low-level signal
outside an operation. Returned pre-settlement entries are discarded before
commit if abort was requested. Settled remains notification-only: no action
capability, outcome field or print-guidance changes are added.

Extensions must observe `ctx.signal.aborted` before issuing late notifications
or other direct side effects. The host discards returned boundary proposals
even when a handler ignores the signal; it cannot undo an already-issued
notification or cancel an uncooperative asynchronous task. Abort still waits
for handlers to finish. This is cancellation signaling, not forced termination.

## Exact anchors

The payload checks literal blocks in `dist/core/agent-session.js`,
`dist/core/extensions/types.d.ts`, and the unique CLI chunk containing
`async _runAgentPrompt(messages){`. Anchors are `_runAgentPrompt` entry,
`_emitAgentSettled` call in its finalizer, `abort()` entry, `getSignal` callback,
the pre-settlement commit/flush/context block, settled-dispatch entry/finalizer,
streaming getter, internal idle wait/resolver, and the existing signal JSDoc.
The public idle getter is validated but not changed in v2.
The checked strings and their reversals are in `patch.mjs`. Changed, ambiguous,
partial or mixed application refuses before replacing any target; JavaScript
syntax is validated in temporary files first. No whole-file backup restoration.

## Validation

From the maintained checkout:

```sh
python3 tests/pi-patches/settlement_abort.py
```

The test copies a real Pi 0.99.2 or 1.0.0 package into temporary storage, uses isolated
homes and a local scripted OpenAI-compatible backend, and never reads real
credentials. Set `PI_SETTLEMENT_SOURCE_PACKAGE` to another installed package
root if needed. It demonstrates the unpatched regression, then proves ordinary
RPC abort and real PTY Escape during a delayed boundary, late returned guidance
suppression, no notification or extra model request, and a clean follow-up
turn. A second fixture delays `agent_settled` itself: unpatched RPC abort leaks
its notification; patched RPC and real TUI Escape abort it before release.
RPC state remains streaming and abort response waits for handler completion.
It also proves normal notifications, deferred user prompts, cleanup after a
settled-handler exception, normal continuation, signal reuse within continuation,
fresh signal on a second operation, module/bundle execution, `--check`,
idempotence, missing/ambiguous anchor refusal without writes, disabled-profile
exact reversal and sibling preservation. Installed target hashes are unchanged.
Retry/compaction lifetimes are preserved structurally, not separately exercised
by this proof. Deferred prompts and settled-handler exceptions are public-tested.

For a private target only:

```sh
PI_SETTLEMENT_ABORT_PACKAGE=/absolute/private/pi-copy \
PI_CHEZMOI_PROFILE=personal node dot_local/share/pi-patches/settlement-abort/patch.mjs
PI_SETTLEMENT_ABORT_PACKAGE=/absolute/private/pi-copy \
PI_CHEZMOI_PROFILE=personal node dot_local/share/pi-patches/settlement-abort/patch.mjs --check
```

The override suppresses receipt writes, including the live receipt. Normal
application uses the existing patch helper and writes its standard receipt.
After a same-version reinstall explicitly rerun the helper and `--check`:
the onchange source/version hash alone does not detect replaced dist contents.

### v1 review corrections preserved in v2

Controller initialization is inside the operation method (a per-operation dynamic
property), preserving the headless sibling's contiguous replacement. The proof
runs the actual apply helper twice against a private three-patch root, verifies
sibling checks and exact disabled reversal, and suppresses private receipts.

Awaited final settlement remains busy/cancelable, but custom-message delivery
excludes that phase from active-run streaming branches: triggered custom messages
use existing settled deferral; nontrigger messages persist and display immediately.
Public controls exercise both on module and bundled RPC paths.

Follow-up and deferred controls require new scripted backend requests, exact
request counts, and successful SCRIPTED-ANSWER entries after their initiating
turns. TUI startup waits for session_start readiness, not a fixed sleep. Handler
exception controls exercise ExtensionRunner-caught errors, not propagated host
dispatch exceptions. No live apply or external provider calls are part of proof.

## v2 compatibility and rollout status

v1 conflated public main-agent idle with busy final-settlement work. This made
`ctx.isIdle()` false inside every awaited `agent_settled` callback and suppressed
stock Herdr's existing guarded idle publication. v2 restores that public getter
without removing streaming/cancellation during final settlement. No consumer
bypasses its guard and no private session fields are accessed by extensions.

The upgrader accepts only the complete exact v1 block set (legacy payload SHA256
`9c408c5e65767992bb39772e66bc04c9bea98673643c0ea3dc8d5b766be73064`),
normalizes its own blocks in memory, and validates all v2 targets before writing.
Unknown revisions, mixed markers, partial v1/v2 application, and changed idle
anchors fail closed. `--check` rejects v1 until explicit upgrade. Disabled
profiles reverse exact v1 or v2 blocks; sibling edits are preserved.

Private proof now reproduces v1's false idle guard on both real CLI paths,
then requires v2's true idle guard and notification delivery while RPC still
reports streaming. A byte-identical stock Herdr extension is also loaded in a
private PTY Pi against a scripted Unix IPC socket: v1 suppresses post-working
idle; v2 publishes it. This proves stock adapter publication, not full Herdr
server/Overview acceptance or live READY. The existing abort, deferred/backend
answer, custom-message, sibling helper/reversal and exception checks remain.
Optional `PI_SETTLEMENT_PROOF_ARTIFACTS` retains private journey traces and
scripted backend/IPC transcripts outside Git.

**Rollout pending:** these are private copied-Pi checks. No live apply, restart,
commit or push is authorized by this fix. After independent review and owner
approval, use the maintained normal apply helper with the real profile, verify
all sibling checks, restart/reload the affected Pi host as separately approved,
and rerun the consumer-owned Overview native READY journey. Installed processes
cannot pick up this source change without that separately approved rollout.
