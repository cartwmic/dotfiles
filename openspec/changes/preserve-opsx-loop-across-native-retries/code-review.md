# Code Review

**Change:** preserve-opsx-loop-across-native-retries
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** openai-codex/gpt-5.6-sol via pi-subagents; claude-bridge/claude-opus-4-8 via pi-subagents
**Diff Base SHA:** a5cc8de5040107e121a199caf845358a395b98d0
**Reviewed Range:** a5cc8de5040107e121a199caf845358a395b98d0..1468ce06a5b0cc1c671756396517b34321421065
**Attested HEAD:** 1468ce06a5b0cc1c671756396517b34321421065
**Baseline:** intent.md + proposal + specs + plan + tasks status
**Generated:** 2026-07-14

## Verdict contract

Reviewers could fail only for a frozen-baseline violation or an objective correctness/security defect. P0 is confirmed baseline violation or critical defect; P1 is must-fix within contract; P2/P3 are advisory. Pass requires no open P0/P1.

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---:|---:|---:|---:|---|---|
| 1 | blind | 0 | 1 | 2 | 2 | gpt-5.6-sol:fail claude-opus-4-8:pass | 81a49b653e79004520c2ca43792b27f4e44de0ff |
| 2 | blind | 0 | 0 | 0 | 3 | gpt-5.6-sol:pass claude-opus-4-8:pass | 1468ce06a5b0cc1c671756396517b34321421065 |

Invalid dispatches were excluded from the ledger and round budget: one pre-review dispatch mutated integration-side `progress.md`; one configured Fable dispatch returned only a quota-limit message; two Opus outputs lacked the exact attestation preamble and were re-dispatched or superseded before consolidation.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | `compactionWasAborted` retains a fuzzy abort/cancel text fallback after the reliable signal/name checks; a future opaque provider message could conservatively land instead of degrade to direct inject. | P3 | deferred |
| 2 | `agent_settled` resets owner tracking before its not-idle early return; current identity fallback is safe, but cross-extension nested-run ordering remains a host-contract edge. | P3 | deferred |
| 3 | Cleared `LoopState` objects retain `active: true`; current `loop !== session` guards make them inert, but future refactors must preserve identity checks. | P3 | deferred |

## Applied fixes

- `a36f9752769c9815c13425df325c0432550711b0` binds transfer to the exact replacement directive and adds prequeued-user coverage.
- `0f1aa648b64f713b74ef285b2f51c3c5100f543a` invalidates old ownership before asynchronous turn-zero gate work.
- `b4dd9763710176710e1c6f4b9850e0c969dd8893` adds arm generations, duplicate-rearm protection, pending-arm cancellation, and abort-aware compaction callbacks.
- `1468ce06a5b0cc1c671756396517b34321421065` seals fresh green verification after all runtime fixes.

## Validation evidence

- `bun test dot_pi/agent/extensions/opsx-loop/helpers.test.ts`: 94 pass, 0 fail.
- `tests/opsx-tui/scripts/run-all-scenarios.sh`: 17 pass, 0 fail, 0 timeout.
- Opt-in real interrupt scenario: pass.
- `openspec validate preserve-opsx-loop-across-native-retries --strict`: pass.
- `bun build dot_pi/agent/extensions/opsx-loop/index.ts --target=node`: pass.
- No gate, validation manifest, stable spec, Constitution, or `goal` extension file changed.

## Residual risks

- Pi event-order contract is validated against installed Pi 0.80.6; rerun s07-s16 after Pi lifecycle upgrades.
- Proactive-compaction abort shares the same reviewed callback/helper as directly tested overflow-compaction abort but has no separate TUI scenario.
- Advisory P3 findings above do not violate frozen intent or establish a correctness/security defect.

## Verdict rationale

Both counted blind reviewers attested the same worktree HEAD and passed the final quiet round with zero P0/P1. Implementation preserves loop state across Pi-native retries, gates exactly once after clean continuation, lands unresolved errors visibly, bounds overflow recovery, lets abort/clear/re-arm win, and prevents stale or duplicate queued work from claiming replacement ownership. No gate or manifest was weakened.
