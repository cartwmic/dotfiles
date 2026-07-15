## Why

Pi emits `agent_end` before deciding whether to retry, compact-and-retry, or drain a queued continuation, but `opsx-loop` currently clears active state on every errored `agent_end`. A successful Pi-native retry therefore resumes detached from the gate-driven loop; this violates the existing deterministic-loop outcome while Constitution I requires the deployed extension fix to live in chezmoi source.

## What Changes

- Modify the `opsx-loop` capability so an errored low-level `agent_end` preserves the active loop and records a session-bound pending error instead of treating the attempt as terminal.
- Keep clean-turn gate evaluation and continuation injection on `agent_end`, preserving the current same-run queue topology.
- Keep explicit user abort immediately terminal.
- Handle only an unresolved final error from `agent_settled`, including the existing bounded context-overflow compact-and-retry path and visible worktree-preserving stop.
- Invalidate deferred outcomes after clear, re-arm, replacement, reload, or session switch so stale settled events cannot affect a newer loop.
- Add deterministic lifecycle regression coverage and, where practical, real-TUI coverage for native retry continuity.
- Do not add provider-specific classification, extension-owned retry/backoff/fallback, or direct `pi-subagents` changes.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `opsx-loop`: replace “every worker error stops immediately” with attempt-versus-settlement semantics while preserving abort, gate, budget, hold, compaction, and terminal-landing behavior.

## Impact

### Affected code and artifacts

- `dot_pi/agent/extensions/opsx-loop/index.ts`: lifecycle event handling and pending-outcome ownership.
- `dot_pi/agent/extensions/opsx-loop/helpers.ts` and focused tests only if extracting state transitions improves deterministic coverage.
- `dot_pi/agent/extensions/opsx-loop/helpers.test.ts` and/or extension/TUI scenario tests: retry-success, retry-exhaustion, abort, overflow, and stale-event regressions.
- `openspec/specs/opsx-loop/spec.md` through this change's delta spec.

### APIs, dependencies, and systems

- Uses Pi's public `agent_settled` extension event available in the supported Pi runtime; no private `pi-ai` retry import or provider API dependency.
- No command grammar, persisted file format, model configuration, archive behavior, or external service changes.
- OpenSpec workspace remains repo-local under Constitution VIII; deployed runtime source remains under chezmoi's `dot_pi/` source tree per Constitution I.

## Open Questions

- None. Frozen intent resolves lifecycle ownership: `agent_end(error)` defers, clean `agent_end` continues normally, and `agent_settled` decides only unresolved terminal errors.
- Assumption recorded: the supported Pi runtime emits one `agent_settled` only after native retry, compaction/retry, and queued continuation are exhausted, matching Pi 0.80.6 public extension documentation and implementation.

<!-- authored: in-session -->
