---
name: pi-tui-scenario-tests
description: Use when end-to-end behavior of the Pi TUI must be validated — extension features, provider/bridge regressions, conversation-coherence checks, abort/steer/fork/compaction flows, or any change where unit tests can't catch silent corruption of the user-facing experience.
---

# Pi TUI Scenario Tests

## Overview

Pi is an interactive TUI agent. Real failure modes — silent context loss, broken abort, ghost session-ids, model amnesia after compaction, autocorrect that "displays right but submits wrong" — only surface end-to-end. This skill codifies the proven harness for **feature-driven, tmux-driven scenario tests** against a real Pi process.

**Core principle:** Mechanical assertions catch crashes. **Only a coherence probe — a follow-up assertion that requires the right thing to have actually happened end-to-end (not just locally) — catches silent corruption.** "We didn't crash" is not testing what users actually experience.

## When to Use

- Pi extension changes that affect user-visible behavior (editor, commands, status, hooks)
- Provider/bridge changes (claude-bridge, openai-codex, custom adapters)
- Session refactors (`/fork`, `/tree`, `/compact`, resume, branching)
- Abort/steer/queue-follow-up flows (`Escape`, `Alt+Enter`)
- Subagent / cross-provider orchestration changes

**Don't use for:** pure-library changes with no TUI-visible effect — write unit tests.

## Harness shape (always)

```text
1. Start Pi in a fresh tmux session, with provider/model/extension under test
2. Drive input:    tmux send-keys -t <session>:0 -- '<text>' Enter
3. Wait for completion via a SIGNAL (not a sleep)
4. Capture output: tmux capture-pane -t <session>:0 -p -S -2000
5. Apply mechanical assertions (grep / file checks) AND a coherence probe
6. Tear down session
```

A drop-in implementation of every step lives at `examples/scripts/scenario-lib.sh`. Source it from each per-scenario script.

## Pi-specific gotchas (verified, non-negotiable)

| Action | Pi binding | tmux send-keys |
|---|---|---|
| Submit | `Enter` | `Enter` |
| **Abort current turn** | **`Escape`** (`app.interrupt`) | `Escape` |
| Clear editor (NOT abort) | `Ctrl-C` (`app.clear`) | `C-c` |
| Exit pi (empty editor) | `Ctrl-D` | `C-d` |
| Queue follow-up while running | `Alt+Enter` | `M-Enter` |

- **Escape ≠ Ctrl-C.** `C-c` silently clears the editor; the model never sees an interrupt and the test gives a false negative.
- **tmux extended keys must be on** (`set -g extended-keys on`, `set -g extended-keys-format csi-u`) per Pi's `docs/tmux.md`, otherwise `M-Enter` collapses to `Enter` and Alt+Enter scenarios silently fail.
- **Provider/model uses `provider/id` form**: `--provider claude-bridge --model claude-bridge/claude-haiku-4-5`. Append `:high` for thinking level.
- **Loading an in-dev extension:** `pi -e ./dist/index.js` for one-shot, or `cp -r dist data ~/.pi/agent/extensions/<name>/` + `/reload` for hot-loading. Add `-ne` to disable auto-discovered extensions when an installed copy could shadow your in-dev build.

## Two-tier assertions (both axes, every scenario)

**Mechanical (the floor) — pick what fits the change under test:**
- Pane text contains/doesn't contain a marker (most extension features are pre-submit; pane is the source of truth)
- File state on disk (extension persistence, learned dicts, cache files)
- Notify/status messages appear (capture in pane after `notify()` calls)
- Tool-call counts / cache profile / session ids in provider debug logs (when the change is provider-side)

**Coherence (the actual pass criterion):** Confirm the right thing happened *end-to-end*, not just locally. The probe shape varies by scenario type:

| Scenario type | Coherence probe shape |
|---|---|
| Pre-submit transformation (autocorrect, snippet expansion) | After typing, ask the model "echo back exactly what I typed" — assert the *transformed* text, proving it reached the model |
| Memory across turns | Send something, then a follow-up requiring recall, with paired positive + negative regex |
| Abort/steer | After the disruption, next turn must reference both topics correctly |
| Tool/session flow | Next turn must use cached results without re-calling the tool |

**The negative-regex rule (always):** Without a negative pattern, "I don't recall X" passes a positive check for "X". Pair them.

```bash
scn_assert_response \
    "Did I ever ask you about the printing press" \
    "yes.*printing press|asked.*printing press" \
    "did not ask|never mentioned|don't recall" \
    "S5 coherence: model recalls abandoned topic"
```

## Completion-signal-based waiting (no sleeps)

`tmux send-keys ... Enter` returns immediately. `sleep N` is flaky and slow. Watch a signal that fires **exactly once per turn**:

| Signal | When it works | How to use |
|---|---|---|
| **Pane idle marker** | Any provider, any extension | Wait for "esc to interrupt" footer to disappear, or for a specific spinner glyph to vanish from `capture-pane` output |
| **Custom marker in response** | When you can prompt the model to emit it | Ask: "End your reply with `DONE-MARKER-9F2A`." Wait for the marker in the pane. |
| **Provider debug log line** | When the provider/bridge writes one log line per completed turn | Pre-count occurrences in the log file, send keys, poll until count grows. Example: claude-bridge writes `caching session=<id>` per `query()`. |
| **File-system state change** | When the extension writes on every event | Stat the file mtime, send keys, poll until mtime changes |

The lib defaults to the pane-idle signal. Override with `SCN_PROVIDER_DEBUG_LOG=<path>` + `SCN_COMPLETION_SIGNAL_REGEX=<pattern>` to use a debug-log signal, or set `SCN_IDLE_REGEX=<pattern>` to customize the pane marker.

For pre-submit assertions (no Enter ever pressed — the extension acted in the editor), no completion wait is needed; just `capture-pane` after a small fixed settle (≤500 ms).

## Tmux session hygiene

- One scenario = one fresh session (`pi-scn-<scenario>-$$`). Never reuse.
- `trap 'scn_pi_stop' EXIT` so failed scripts still clean up.
- Per-script timeout in the batch runner (default 5 min) — Pi can hang on subtle bugs.
- `--no-session` keeps your session JSONL out of `~/.pi/agent/sessions/`.

## Writing a new scenario

1. State the user story (one sentence) and pick `S<N>`.
2. Define what regression this catches that nothing else does.
3. Decide tier: **pre-submit pane** (cheap, fast, no model needed) vs **submit + coherence probe** (real model call). Most scenarios are pre-submit.
4. Write the steps as literal send-text, with timing constraints ("as soon as the first paragraph appears").
5. List mechanical assertions (pane substrings, file state, log lines).
6. Write the coherence probe if needed (positive/negative regex pair).
7. Copy `examples/scripts/run-scenario-template.sh` to your project's `scripts/run-scenario-s<N>.sh` (or `tests/scenarios/...`), fill in.
8. Add the scenario block to your project's `SCENARIOS.md` using the template structure.

The catalog at `examples/SCENARIOS.md` covers 18 provider/bridge scenarios (text, tools, abort, steer, resume, fork, tree, compaction, subagents). For an extension-flavored example, see `mobile-autocorrect`'s 25-scenario catalog in pi-mobile-typing-utils. Copy-and-adapt rather than starting blank.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `C-c` for abort | Clears editor, model never sees interrupt | Use `Escape` |
| `sleep 10` after send | Flaky on slow turns, slow on fast | Completion signal |
| Positive-only coherence | "Don't recall X" passes a check for "X" | Pair positive + negative |
| Reusing tmux sessions | State leak between scenarios | Fresh session + `trap` |
| Asserting only on pane for provider/bridge changes | Cache/session-id bugs invisible there | Also assert provider debug log |
| Asserting on bridge log for extension-only changes | Doesn't tell you what the user saw | Also assert pane / file state |
| Default tmux key handling | `M-Enter` → `Enter`, Alt+Enter scenarios pass falsely | Enable extended keys |
| Pre-submit scenario uses Enter + completion wait | Adds model latency for nothing | `scn_send_no_enter` + capture |

## Red flags — STOP

- "Just sleep a bit longer" → flaky, never converges
- "Pane text contains the topic, good enough" → false-pass risk; add negative regex (or assert exact transformed substring for pre-submit cases)
- "Don't need the bridge log, user only sees the pane" → for provider-side changes, silent corruption hides in the bridge log
- "Don't need the pane, user gets the model response" → for extension-side changes, the user's typed buffer is the source of truth
- "This is the same as S\<X\>, skip it" → scenarios are catalogued by the regression class they catch, not the prompt's words

## Reference layout

```
pi-tui-scenario-tests/
  SKILL.md                           # this file
  examples/
    SCENARIOS.md                     # 18-scenario provider/bridge template catalog
    scripts/
      scenario-lib.sh                # drop-in shared helpers (provider-agnostic defaults)
      run-scenario-template.sh       # per-scenario runner skeleton
      run-all-scenarios.sh           # batch runner with timeouts + summary
```

The example bundle was harvested from `pi-claude-bridge`. Copy `examples/scripts/` into your project's `scripts/` or `tests/scenarios/` and adapt scenarios from `examples/SCENARIOS.md`.
