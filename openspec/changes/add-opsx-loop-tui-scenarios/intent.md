# Intent — add-opsx-loop-tui-scenarios

Status: explore-frozen

## Intent

Add a TUI-backed scenario test suite for the `opsx-loop` Pi extension that validates the extension through the same surface the user uses: a real Pi TUI process driven through tmux. The suite exists to catch user-visible command and loop regressions that pure helper tests cannot catch, especially silent failures where a command handler returns data that Pi discards instead of notifying the TUI.

The suite should be modeled on the existing `pi-tui-scenario-tests` skill and may copy/adapt its shell harness, but it must be specialized for `opsx-loop`: real Pi TUI, isolated tmux server per scenario, in-dev extension loading, deterministic temp repos, fake `opsx` command behavior, and a fake low-cost provider where a completed agent turn is needed. Default tests should be deterministic and cheap; optional real-model smoke may exist outside the default gate.

Primary outcome: every user-facing `/opsx-loop` command path is exercised in an actual Pi TUI, with assertions against pane-visible notifications/status and side effects, so command regressions are caught before a change is considered green.

## Scope

Create an `opsx-loop` TUI scenario suite under the repo's test tree, likely:

```text
tests/opsx-tui/
  SCENARIOS.md
  scripts/
    scenario-lib.sh
    run-all-scenarios.sh
    run-scenario-s00-status.sh
    run-scenario-s01-models.sh
    run-scenario-s02-green-change.sh
    run-scenario-s03-red-arm-clear.sh
    run-scenario-s04-goal-distill.sh
    run-scenario-s05-hold-rearm.sh
```

Exact scenario numbering may change during proposal/design, but the suite must cover the behavior categories below.

## Required scenario coverage

1. **Status / bare command visibility.** `/opsx-loop` and `/opsx-loop status` with no active loop show a pane-visible notification such as "No active opsx-loop". This protects against the historical bug where bare/status/clear/models returned strings that Pi discarded.
2. **Clear visibility and stop behavior.** `/opsx-loop clear` with no active loop shows "No active opsx-loop to clear"; when a loop is active it clears the loop, aborts an active turn when applicable, and no further continuations are injected.
3. **Models wrapper.** `/opsx-loop models`, `models list`, and `models set <role> <model>` delegate to `opsx models` with the full argument vector preserved and surface CLI output in the TUI. Multi-token arguments must not be truncated.
4. **Already-green change.** `/opsx-loop <change>` against a fake green gate exits with a pane-visible "already passes opsx gate" / "ready to archive" notification and does not arm a loop or inject a worker turn.
5. **Red arm + status + continuation path.** `/opsx-loop <change>` against a fake red gate arms the loop, injects a worker directive, reports active status, and after a fake agent turn runs the fake gate and either continues or stops according to the scripted result.
6. **Goal/conversation distill.** `/opsx-loop goal <multi word text>` preserves the full goal text, starts distilling intent, injects a distill-scoped directive (not drive-to-green autonomy), and pauses with a pane-visible confirmation notice when a new change with `intent.md` appears.
7. **Loop hold + re-arm.** A `loop_hold: true` review.md front-matter state stops continuation and surfaces the reason; named re-arm clears the hold fields, records Execution Notes, surfaces the old reason, and proceeds with the normal turn-0 gate behavior.
8. **Interrupt/error stop (if practical in deterministic harness).** Escape-driven interrupt stops an active loop and does not re-inject. If a stable fake-provider interrupt scenario is too costly/flaky for v1, document it as optional/nightly rather than silently omitting the risk.

## Harness design decisions

- **Real Pi TUI is non-negotiable.** The suite must launch `pi` in tmux and drive slash commands through `tmux send-keys`; unit tests or direct extension API tests are not substitutes for this suite.
- **Private tmux server per scenario.** Every scenario uses `tmux -L <unique-socket>` and tears down that private server. No shared tmux server, no broad `pkill`, no cross-scenario state.
- **No sleep-based completion waits.** Use pane regexes, fake provider log counters, fake `opsx` invocation logs, or other exact signals. Tiny draw-settle sleeps are acceptable only after a readiness/completion signal.
- **In-dev extension loading.** Run Pi with `-ne -e dot_pi/agent/extensions/opsx-loop` (or built equivalent if proposal chooses a build step) so installed global extensions cannot shadow the source under test.
- **Deterministic fake `opsx`.** Scenario temp repos prepend a fake `opsx` executable to `PATH` so gate/model/worktree responses are scripted, logged, and cheap. The fake must record argv/cwd/env so scenarios can assert delegation behavior.
- **Fake provider for agent-turn scenarios.** Where `agent_end` behavior must be exercised, use a local deterministic provider or minimal test extension/provider rather than spending real API calls in the default suite. Optional real-model smoke may be manually/nightly gated.
- **Two-tier assertions.** Every scenario has mechanical assertions (pane text, fake command log, file state) and, where a model turn is involved, a coherence/end-to-end assertion that the right directive or continuation actually reached the provider.

## Constraints

- Preserve existing deterministic unit/helper tests; this suite supplements them, not replaces them.
- Keep default test run cheap enough for local use and eligible for the opsx gate once stable.
- BSD/macOS shell compatibility matters; repo test scripts should not assume GNU-only tools unless already handled with fallbacks.
- Tests must not write persistent Pi session state (`--no-session`) or mutate the user's real OpenSpec workspace; each scenario owns a temp repo and temp HOME/cache where practical.
- No secrets or real API keys in fixtures. Real-model smoke, if added, must be opt-in via env var and skipped by default.
- Do not weaken `opsx-loop` behavior to make tests easy; tests must drive the real extension surface.

## Invariants honored

- Constitution I: this is dotfiles source; any persistent test harness files live in the chezmoi repo, not ad-hoc home-directory state.
- Constitution III: no secrets in source; fake providers and fake CLIs use deterministic local behavior only.
- Constitution VIII: `openspec/` remains repo-local workflow state and is not a deployed home config surface.
- Domain invariant 12: if any supporting skill material is added or changed, canonical skill source must live under `dot_local/share/agent-harness/canonical/skills/`; this change should prefer tests over skill edits unless the existing skill must be updated.

## Non-goals

- No broad Pi TUI provider/bridge regression catalog; this suite is for `opsx-loop` command and loop behavior.
- No replacement for `pi-tui-scenario-tests`; copy/adapt its harness ideas rather than moving that skill.
- No default dependence on real Claude/OpenAI/OpenRouter calls.
- No archive/deploy automation; the extension still stops at ready-to-archive / hold / confirmation states.
- No new `opsx-loop` runtime semantics unless a scenario exposes an actual bug that must be fixed in this change.

## Acceptance sketch

- `tests/opsx-tui/scripts/run-all-scenarios.sh` runs all default scenarios and produces a summary with pass/fail/timeout counts and per-scenario logs.
- Default scenarios launch real Pi in tmux, load the source `opsx-loop` extension, and assert pane-visible behavior for all core slash commands.
- Fake `opsx` invocation logs prove `models` and `gate` commands receive the expected argv/cwd/env.
- A regression that changes `ctx.ui.notify(...)` back into a discarded return string causes at least one TUI scenario to fail.
- Optional real-model smoke, if present, is skipped unless explicitly enabled.

## Suggested Scale

Scale: M, `full_rigor: false`.

Rationale: this is a typical cross-file feature within a single capability (`opsx-loop` testing). It does not intentionally introduce breaking runtime semantics, migration, or a new ADR-worthy architecture decision.
