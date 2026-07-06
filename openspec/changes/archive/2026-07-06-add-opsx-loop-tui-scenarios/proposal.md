<!-- authored: in-session -->

## Why

`opsx-loop` has already had user-visible regressions where slash commands returned strings that Pi discarded, so unit tests passed while the real TUI appeared to do nothing. This change adds real Pi TUI coverage so the OpenSpec loop is validated through the surface the user actually invokes, while respecting Constitution III by using deterministic fake providers and no real secrets/API keys.

## What Changes

- Add a tmux-driven `tests/opsx-tui` scenario suite that launches a real Pi TUI with the source `opsx-loop` extension loaded in-dev.
- Add deterministic fixtures for a fake `opsx` command and fake provider so default scenarios are cheap, local, and reproducible.
- Cover slash-command visibility, model delegation, green/red gate loop paths, goal distill pause, hold/re-arm, and interrupt/error stop behavior where stable.
- Add scenario docs and runner output so failures preserve pane logs, fake command logs, and summary evidence.
- Integrate the new suite as an optional/default-local validator without requiring real model credentials; real-model smoke remains opt-in if present.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `opsx-loop`: adds TUI-backed scenario-test requirements for the existing Pi extension command and loop behavior.

## Impact

Affected files:

- `tests/opsx-tui/**` — new TUI scenario harness, fixtures, scripts, and docs.
- `dot_pi/agent/extensions/opsx-loop/**` — only if scenarios expose defects that must be fixed; no semantic change is intended up front.
- Existing test/gate docs or scripts — may be updated to reference the new scenario runner.

Affects which projects:

- This dotfiles/OpenSpec workspace only; the suite exercises the locally configured Pi runtime but uses temp repos and no deployed secrets.

## Open Questions

- Q1: Should default scenarios call real hosted models? Resolution: no. Use a fake provider by default; any real-model smoke is opt-in/nightly because credentials, latency, rate limits, and provider drift would make the gate flaky.
- Q2: Should the suite copy the generic Pi TUI scenario skill verbatim? Resolution: no. Copy/adapt private-tmux and signal-driven patterns, but specialize waits and assertions around `opsx-loop` pane notices, fake `opsx` logs, and fake provider request logs.

## Plain-M deterministic analyze notes

- Tiling: proposal, spec, tasks, and plan trace to the frozen intent's command visibility, deterministic harness, and optional real-model smoke outcomes.
- EARS lint: spec scenarios use `WHEN` for nominal triggers and `IF` for unwanted/error conditions.
- Traceability: implementation tasks cite canonical AC IDs from `opsx-loop` delta requirements, and plan completion verification includes the scenario runner.
