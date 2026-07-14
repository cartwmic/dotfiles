# Execution Plan

Execution Mode = standard. Apply creates the mandatory `opsx/preserve-opsx-loop-across-native-retries` worktree, records its immutable diff base and locator in integration-side `review.md`, and performs implementation commits on the worktree branch.

## Plan step 1: Add deterministic retrying-provider fixture

- **Covers:** T2.1
- **Pre-conditions:** Worktree exists; current fake provider scenarios pass with no status-sequence environment variable.
- **Action:**
  1. Add an opt-in comma-separated HTTP status sequence to the fake OpenAI server, indexed per `/chat/completions` request.
  2. Return an OpenAI-shaped retryable error for non-2xx entries and preserve current SSE success behavior for `200` or exhausted sequence entries.
  3. Run one existing provider-backed scenario to prove default behavior is unchanged.
  4. Commit `test(opsx-loop): script provider status sequence`.
- **Verification:** `tests/opsx-tui/scripts/run-scenario-s02-green-change.sh` passes.
- **Rollback:** Revert the step commit; existing fake server behavior returns unchanged.

## Plan step 2: Add native-retry scenarios

- **Covers:** T2.2, T2.3
- **Pre-conditions:** Step 1 fixture can return `500,200` and repeated `500` responses deterministically; default Pi retry is enabled.
- **Action:**
  1. Add `s07-native-retry`: first provider request fails retryably, Pi retries successfully, fake gate transitions red-to-green, and pane/log assertions require gate-green landing plus exactly two provider requests.
  2. Run s07 against pre-fix extension and confirm it fails because the first errored `agent_end` clears the loop before retry success.
  3. Add `s08-retry-exhausted`: enough retryable failures exhaust Pi's bounded native retry policy, pane shows exactly one opsx final-error stop, and provider count does not grow afterward.
  4. Register both default scenarios and document their deterministic signals and AC `opsx-loop.interrupt-or-error-stops-the-loop`.
  5. Commit `test(opsx-loop): cover native retry settlement`.
- **Verification:** Pre-fix s07 exposes missing gate-green landing; scripts pass shell syntax checks; existing s06 interrupt/clear coverage remains registered.
- **Rollback:** Revert the step commit; no runtime source is affected.

## Plan step 3: Preserve loop through errored attempts

- **Covers:** T1.1, T1.2
- **Pre-conditions:** Step 2 scenarios reproduce retry continuity and exhaustion behavior; Pi public `agent_settled` hook is available.
- **Action:**
  1. Add a pending assistant-error field to `LoopState`, making deferred ownership intrinsic to the exact loop object.
  2. Split `agent_end` handling: abort clears immediately; error records pending outcome, resets per-attempt elision state, and returns; clean outcome clears pending error then follows unchanged gate/continuation logic.
  3. Move existing overflow-only recovery and final error landing into a shared settled-error path invoked from `agent_settled` only when the current active loop owns a pending error.
  4. Guard compaction callback and all deferred effects with loop identity plus active-state checks.
  5. Run s07, s08, focused unit tests, and existing clear/interrupt scenarios; commit `fix(opsx-loop): preserve loop through native retries`.
- **Verification:** Native-retry success reaches one gate-green landing; exhausted retries stop once; `bun test dot_pi/agent/extensions/opsx-loop/helpers.test.ts` passes; existing s03 and s06 semantics remain.
- **Rollback:** Revert the step commit, retaining failing scenarios as defect evidence.

## Plan step 4: Close blind-verification lifecycle gaps

- **Covers:** T2.4
- **Pre-conditions:** Initial blind verification identifies missing overflow and stale-ownership lifecycle coverage.
- **Action:**
  1. Make fake provider error text configurable so deterministic HTTP 400 responses can model provider-neutral context overflow.
  2. Add one-shot and persistent-overflow scenarios proving settled recovery is bounded.
  3. Add clear-during-retry, named-re-arm-during-retry, prequeued-user-work, duplicate-re-arm, pending-arm clear, and overflow-compaction abort scenarios.
  4. Track top-level run ownership across low-level retries; transfer only on a generation-tagged exact replacement directive, invalidate stale async arm transactions, and treat compaction abort/cancel as terminal without retry injection.
  5. Run all added scenarios and commit focused lifecycle fixes with explanatory bodies.
- **Verification:** s09–s12 pass; old retry gate count remains one; replacement gate count advances only after its own directive.
- **Rollback:** Revert the step commit and retain the initial red verification finding.

## Plan step 5: Validate and retain evidence

- **Covers:** T3.1
- **Pre-conditions:** Steps 1–3 committed; every implementation task checkbox reflects worktree state.
- **Action:**
  1. Run focused helper tests and all default opsx TUI scenarios.
  2. Run strict OpenSpec validation and the worktree-aware opsx gate.
  3. Fill `verify.md` from the schema template with exact command results and AC-to-test mapping.
  4. Check off T3.1 and commit `test(opsx-loop): retain retry lifecycle evidence`.
- **Verification:** All recorded commands exit 0 and every delta AC has a literal test citation.
- **Rollback:** Revert only the verify/task-status commit; implementation remains inspectable.

## Completion Verification

- `bun test dot_pi/agent/extensions/opsx-loop/helpers.test.ts` — all focused unit tests pass.
- `tests/opsx-tui/scripts/run-all-scenarios.sh` — all default deterministic TUI scenarios pass.
- `openspec validate preserve-opsx-loop-across-native-retries --strict` — change artifacts validate.
- `opsx gate preserve-opsx-loop-across-native-retries --worktree <recorded-path>` — deterministic gate exits 0 after sealed review/doneness artifacts are fresh.

## Manual Adjustments

- Design artifact omitted: frozen intent already resolves the only consequential architecture choice (hybrid event topology), and implementation remains a localized lifecycle correction with no new public API or ADR-worthy decision.
- Tests precede runtime modification despite `execution_mode: standard` because the real-Pi TUI scenario provides the strongest regression proof for event ordering.

<!-- authored: in-session -->
