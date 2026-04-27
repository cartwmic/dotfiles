---
name: pi-tui-scenario-tests
description: Use when end-to-end behavior of the Pi TUI must be validated — extension features, provider/bridge regressions, conversation-coherence checks, abort/steer/fork/compaction flows, or any change where unit tests can't catch silent corruption of the user-facing experience.
---

# Pi TUI Scenario Tests

## Overview

Pi is an interactive TUI agent. Real failure modes — silent context loss, broken abort, ghost session-ids, model amnesia after compaction, autocorrect that "displays right but submits wrong" — only surface end-to-end. This skill codifies the proven harness for **feature-driven, tmux-driven scenario tests** against a real Pi process.

**Core principle:** Mechanical assertions catch crashes. **Only a coherence probe — a follow-up assertion that requires the right thing to have actually happened end-to-end — catches silent corruption.** "We didn't crash" isn't testing what users experience.

## When to Use

- Pi extension changes affecting user-visible behavior (editor, commands, status, hooks)
- Provider/bridge changes (claude-bridge, openai-codex, custom adapters)
- Session refactors (`/fork`, `/tree`, `/compact`, resume, branching)
- Abort/steer/queue-follow-up flows (`Escape`, `Alt+Enter`)
- Subagent / cross-provider orchestration changes

**Don't use for:** pure-library changes with no TUI-visible effect — write unit tests.

## Harness shape

```text
1. Start pi in a fresh tmux session (private server per scenario)
2. Drive input:    tmux send-keys -t <session>:0 -- '<text>' Enter
3. Wait for completion via a SIGNAL (not a sleep)
4. Capture output: tmux capture-pane -t <session>:0 -p -S -2000
5. Apply mechanical assertions AND a coherence probe
6. Tear down session
```

A drop-in implementation lives at `examples/scripts/scenario-lib.sh` — source it from each scenario script. The lib handles all the gotchas below.

## Pi-specific gotchas (verified, non-negotiable)

| Action | Pi binding | tmux send-keys |
|---|---|---|
| Submit | `Enter` | `Enter` |
| **Abort current turn** | **`Escape`** (`app.interrupt`) | `Escape` |
| Clear editor (NOT abort) | `Ctrl-C` (`app.clear`) | `C-c` |
| Exit pi (empty editor) | `Ctrl-D` | `C-d` |
| Queue follow-up while running | `Alt+Enter` | `M-Enter` |

- **Escape ≠ Ctrl-C.** `C-c` silently clears the editor; the model never sees an interrupt.
- **tmux extended keys must be on** (`set -g extended-keys on`, `set -g extended-keys-format csi-u`); otherwise `M-Enter` collapses to `Enter` and Alt+Enter scenarios silently pass.
- **Provider/model uses `provider/id` form**: `--provider claude-bridge --model claude-bridge/claude-haiku-4-5`. Append `:high` for thinking level.
- **In-dev extension:** `pi -e ./dist/index.js`, or `cp -r dist data ~/.pi/agent/extensions/<name>/` + `/reload`. Add `-ne` to skip auto-discovered copies that would shadow your build.

## Two-tier assertions (every scenario)

**Mechanical (the floor):**
- Pane text contains/doesn't contain a marker
- File state on disk (extension persistence, learned dicts, cache files)
- Notify/status messages in the pane after `notify()` calls
- Tool-call counts / cache profile / session ids in provider debug logs (provider-side changes)

**Coherence (the actual pass criterion):** confirm the right thing happened *end-to-end*. Probe shape varies:

| Scenario type | Coherence probe |
|---|---|
| Pre-submit transformation (autocorrect, snippet) | After typing, ask the model "echo what I typed" — assert the *transformed* text reached it |
| Memory across turns | Send X, follow up requiring recall, paired positive + negative regex |
| Abort/steer | After disruption, next turn references both topics correctly |
| Tool/session flow | Next turn uses cached results without re-calling the tool |

**The negative-regex rule (always):** without a negative pattern, "I don't recall X" passes a positive check for "X". Pair them. See `scn_assert_response` in the lib.

## Completion-signal-based waiting (no sleeps)

`tmux send-keys ... Enter` returns immediately. `sleep N` is flaky and slow. Watch a signal that fires **exactly once per turn**:

| Signal | When it works | How |
|---|---|---|
| Pane idle marker | Any provider/extension | Wait for "esc to interrupt" footer to disappear |
| Custom marker in response | When you can prompt for it | Ask: "End your reply with `DONE-MARKER-9F2A`." |
| Provider debug log | When provider writes one log line per turn | Pre-count occurrences, send keys, poll until count grows. claude-bridge writes `caching session=<id>`. |
| File-system mtime | When the extension writes per event | Stat mtime; poll until it changes |

The lib defaults to pane-idle. Override via `SCN_PROVIDER_DEBUG_LOG`/`SCN_COMPLETION_SIGNAL_REGEX`/`SCN_IDLE_REGEX`. For pre-submit assertions (no Enter), no wait needed — just `capture-pane` after a small fixed settle (≤500 ms).

## Tmux session hygiene

**Private tmux server per scenario** (the architectural keystone). The default tmux server is shared across the user's whole session — sequential or parallel scenarios on it interfere via `kill-server` arms races and stray pi processes. Each scenario must run on its own server via `tmux -L <socket>`:

```bash
: "${SCN_TMUX_SOCKET:=pi-scn-$$}"
TMUX_CMD=(tmux -L "$SCN_TMUX_SOCKET")
"${TMUX_CMD[@]}" new-session ...   # `kill-server` later only kills *this* server
```

`scenario-lib.sh` wires every helper through `${TMUX_CMD[@]}`. Once private, `scn_pi_stop` is just `kill-server` — no broad `pkill` (which would kill parallel siblings).

**Symptom of getting it wrong:** in a batch, ~10–30% of scenarios silently hang; bridge log shows `provider: registered` with no `fresh query`.

Other essentials:
- One scenario = one fresh session named `pi-scn-<scenario>-$$`. Never reuse.
- `trap 'scn_pi_stop' EXIT` so failed scripts still clean up.
- Per-script timeout (default 5 min) — Pi can hang on subtle bugs.
- `--no-session` keeps your test runs out of `~/.pi/agent/sessions/`.
- **Wait for pi readiness, never `sleep N`.** A fixed sleep loses keystrokes when startup is slow (opus boot, contention). Poll `capture-pane` for the bottom-status `(<provider>) <model>` marker — that's the unambiguous "input ready" signal. Implementation in `scn_pi_start`.

## Parallel execution

With private servers, `run-all-scenarios.sh` supports concurrency:

```bash
SCENARIO_PARALLEL=4 ./run-all-scenarios.sh
SCENARIO_FILTER='^s(0|1|18)$' SCENARIO_PARALLEL=3 ./run-all-scenarios.sh
```

Each child gets `SCN_TMUX_SOCKET=pi-scn-<name>-<dispatcher-pid>` so no two share a server. The dispatcher polls `<name>.done` marker files for completion — **not** `kill -0`, which returns 0 for zombies and would loop forever.

Tuning: haiku tolerates ~4 concurrent scenarios per Anthropic account; opus 2–3. Watch scenario `.run.log` for HTTP 429s and back off. Don't parallelize scenarios that mutate the same files — namespace outputs by scenario name or filter them out.

## Writing a new scenario

1. State the user story (one sentence) and pick `S<N>`.
2. Identify the regression class this catches that nothing else does.
3. Tier: **pre-submit pane** (cheap, no model) vs **submit + coherence probe** (real model call).
4. Write steps as literal send-text with timing constraints.
5. List mechanical assertions (pane, file, log).
6. Write the coherence probe if needed (positive + negative regex).
7. Copy `examples/scripts/run-scenario-template.sh` → fill in.
8. Add a scenario block to your project's `SCENARIOS.md`.

`examples/SCENARIOS.md` has 18 provider/bridge scenarios (text, tools, abort, steer, resume, fork, tree, compaction, subagents). Copy-and-adapt rather than starting blank.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| `C-c` for abort | Clears editor, model never sees interrupt | Use `Escape` |
| `sleep 10` after send | Flaky on slow turns, slow on fast | Completion signal |
| Positive-only coherence | "Don't recall X" passes a check for "X" | Pair positive + negative |
| Reusing tmux sessions | State leak between scenarios | Fresh session + `trap` |
| Asserting only on pane for provider/bridge changes | Cache/session-id bugs invisible there | Also assert provider debug log |
| Asserting on bridge log for extension-only changes | Doesn't tell you what the user saw | Also assert pane / file state |
| Default tmux key handling | `M-Enter` → `Enter`; Alt+Enter scenarios pass falsely | Enable extended keys |
| Pre-submit scenario uses Enter + completion wait | Adds model latency for nothing | `scn_send_no_enter` + capture |
| Sharing the default tmux server across scenarios | Cross-scenario interference; ~10–30% of batch hangs | `tmux -L pi-scn-<name>-$$` per scenario |
| `sleep 3` after `new-session` | Loses keystrokes when pi startup is slow | Poll pane for `(provider)` ready marker |
| `pkill -9 -f "pi --no-session"` between scenarios | Kills parallel siblings' pi | Private tmux servers; `kill-server` only |
| `kill -0 $pid` to detect "child running" | Zombies pass kill -0 — dispatcher loops forever | File-marker completion signaling (`<name>.done`) |
| `grep -c P \| head \| tr \|\| echo 0` | grep returns 1 with no match → pipefail concatenates "0\\n0" → `(( var ))` errors `bad math expression: 00` | Single `grep -c ... \|\| true`, then `${var:-0}` |

## Red flags — STOP

- "Just sleep a bit longer" → flaky, never converges
- "Pane text contains the topic, good enough" → false-pass risk; add negative regex
- "Don't need the bridge log, user only sees the pane" → for provider-side changes, silent corruption hides in the bridge log
- "Don't need the pane, user gets the model response" → for extension-side changes, the user's typed buffer is the source of truth
- "This is the same as S\<X\>, skip it" → scenarios are catalogued by the regression class they catch, not the prompt's words

## Reference layout

```
pi-tui-scenario-tests/
  SKILL.md
  examples/
    SCENARIOS.md                # 18-scenario provider/bridge template catalog
    scripts/
      scenario-lib.sh           # drop-in shared helpers (private tmux server, signal-based wait, parallel-safe)
      run-scenario-template.sh  # per-scenario runner skeleton
      run-all-scenarios.sh      # batch runner with timeouts, parallel mode, summary
```

Harvested from `pi-claude-bridge`. Copy `examples/scripts/` into your project's `scripts/` or `tests/scenarios/` and adapt from `examples/SCENARIOS.md`.
