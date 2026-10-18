# Herdr source adapter

A Herdr plugin that turns Herdr's agent events into `agent-alert emit` calls.
The inbox format, the `emit` contract and the source rules are in
[SPEC.md](../../SPEC.md); this file covers only what is specific to Herdr 0.9.1.

Files:

- `herdr-plugin.toml` — the plugin manifest: four `[[events]]` hooks, all running
  `python3 hook.py`.
- `hook.py` — the hook and the last-message extractor. Python 3 standard
  library only. It finds the core relative to its own path
  (`../../core/agent-alert`), so keep the deployed layout.

## Install

Herdr plugins are linked from a directory. After `chezmoi apply` the adapter is at
`~/.local/share/agent-alert/adapters/herdr`:

```sh
herdr plugin link ~/.local/share/agent-alert/adapters/herdr
herdr plugin enable agent-alert
herdr plugin log list
```

`herdr plugin log list` keeps each hook run with its exit code and its standard
error. Look at it after the first agent event: a clean run shows `succeeded` with an
empty `stderr`. Hooks run with the environment of the running Herdr server, so
a `python3` that is not on that server's `PATH` is not found (see Failure modes). To use another inbox or log,
set them in `~/.config/agent-alert/config.json` (see SPEC.md); the hook reads no
setting of its own.

## What is emitted, and when

Herdr sends every hook the event name in `HERDR_PLUGIN_EVENT` and a payload in
`HERDR_PLUGIN_EVENT_JSON` that holds only the pane id, the workspace id, the agent
name and, for a status change, the status. It carries no time and no message
text. The hook takes the time when it runs (the core does) and reads the message
from the pane.

| Herdr event | Condition | Emitted |
|---|---|---|
| `pane.agent_status_changed` | payload names an agent, status `blocked` | `blocked` |
| `pane.agent_status_changed` | payload names an agent, status `idle` or `done` | `finished` |
| `pane.agent_status_changed` | status `working` or `unknown` | nothing (the pane is only remembered as having an agent) |
| `pane.agent_status_changed` | payload names no agent | nothing |
| `pane.agent_detected` | payload names an agent | nothing (the pane is remembered as having an agent), unless the payload says `released` |
| `pane.exited`, `pane.closed` | this pane was remembered as having an agent | `exited` |
| `pane.exited`, `pane.closed` | not remembered | nothing |

The worker id is the Herdr pane id (for example `w1:p2`). The context carries
`workspace_id`, `workspace_label` (from `HERDR_PLUGIN_CONTEXT_JSON`) and `agent`.
The summary is the pane's last message (below), or `(last message unavailable)`
when it cannot be read or has no text; an `exited` event has an empty summary
because the pane is gone.

The hook acts on the event's own status and keeps no history, so the order in
which Herdr's separate hook processes run cannot make it skip a completion.
The only state is a marker file per pane in `$HERDR_PLUGIN_STATE_DIR/panes/` (the
plugin's own state directory, under the Herdr state directory of the user), which
holds the agent name. The first of `pane.exited` and `pane.closed` that removes the
marker emits `exited`; the other finds no marker and does nothing.

Herdr fires no hook for a status report that repeats the current status, so
a repeated identical report gives one event. Every real status change fires its
hook, so a new turn is never suppressed, however soon it follows the last.

### What you accept

- A `finished` event can be duplicated, late, or raised for an `idle` report on a
  pane that did not visibly work first. The adapter never tries to prove "idle
  after working" because Herdr gives no ordering, and four earlier designs that
  tried lost a completion under reordering. Never missing a completion is chosen
  over never repeating one; the coordinator reads the summary.
- An `exited` event is missed when the exit hook runs before any other hook of that
  pane has shown the adapter that the pane had an agent.
- When an agent's process exits, Herdr also sends a late `done` status for the
  pane, which gives a `finished` event next to the `exited` event. Its summary is
  usually the placeholder, since the pane is gone by then.
- A stale marker (a status event that arrives after the pane exited) can give one
  `exited` event when a later pane close arrives.

## `errored` is never emitted

Herdr 0.9.1's agent status is exactly `idle`, `working`, `blocked`, `done` or
`unknown`. It has no error status, so a turn that ended on an API failure or a
rate limit reaches the hook as an ordinary `idle` or `done`, and the status
alone cannot tell it from a normal finish. The adapter has no other reliable
indicator, and it does not guess from words such as "error" in the text (a
message that merely mentions an error would be reported wrongly). So **every
finished turn is a `finished` event**, including a turn that ended on an error;
the error text is usually the end of the last message and arrives in the summary.
The format still has the `errored` kind for other sources and for a future Herdr
that reports one.

## Last message extractor

On `finished` and `blocked` the hook runs
`herdr agent read <pane> --source recent-unwrapped --lines 120` (the `herdr`
binary named by `HERDR_BIN_PATH`, else `herdr` on `PATH`; the call times out
after 10 seconds), removes terminal escape sequences and control characters, and
reads the last message out of the text:

1. The text is cut into segments at **boundary lines**; the boundary line itself is
   a separator and is not kept. A boundary is:
   - a chrome line: only box-drawing or block characters (U+2500 to U+259F) and
     spaces, or a run of ten or more `-`, `=` or `_`;
   - a prompt line: it starts with `❯`, `›` or `$ ` (after leading spaces);
   - a line framed by `│` (or `┃`) at both ends;
   - a status line: a spinner line (a Braille character first), `Working…` or
     `Thinking…` with an ellipsis, a timing line (`Took`, `Worked for` or
     `Elapsed` plus a number), or a token counter (`↑ 12k …`). These are written
     against fixtures in the tests, not checked against a live Pi.
   - a run of two or more blank lines. A single blank line stays inside a segment
     as a paragraph break.
2. If the text ends with an input box (a prompt line followed by a rule), whatever
   comes below the box (directory and token footer) is dropped first.
3. The last segment that has text is the message. At most its last 40 lines are
   kept. The core then collapses whitespace, masks token-shaped strings and keeps
   the last 200 characters (SPEC.md, "Summary").

So an earlier message behind a prompt or a chrome line cannot reach the summary.
This is a best-effort reading of a terminal: two messages with no boundary line
and no double blank line between them cannot be told apart and are read as one,
and a line that starts with `$ ` or `❯` inside a message ends the segment there.
A wrong block only degrades the summary; the event is always emitted.

## Failure modes

The hook catches every error, writes it to standard error (kept in
`herdr plugin log list`) and exits 0, so it cannot fail Herdr's event or hold up
another plugin's hook for the same event. It does not retry.

| Failure | Result |
|---|---|
| The inbox cannot be written (bad path, full disk) | `emit` exits nonzero; the event is **lost**, the hook logs `… event was not delivered …` with the core's message; the core also logs to its operator log. Later events are delivered once the inbox works again. |
| The pane is gone or its text cannot be read | The event is still emitted, with the placeholder summary; the plugin log shows `cannot read the last message of pane …`. |
| `emit` runs longer than 30 seconds | The hook gives up and logs it; the event may or may not be in the inbox. |
| The core cannot be found (the deployed layout was broken) | The hook logs `cannot find the core at …` and exits 0; nothing is emitted. |
| `python3` is not on the `PATH` of the running Herdr | Herdr cannot start the hook: the plugin log shows the run as `failed` (`No such file or directory`), the hook never runs, and the server and other plugins are unaffected. Check `herdr plugin log list` after linking. |
| `HERDR_PLUGIN_STATE_DIR` is missing or unwritable | Presence is not recorded, a note is logged; `finished` and `blocked` events are still emitted, an `exited` event cannot be. |
| The event JSON is missing or not JSON | A note is logged; nothing is emitted. |

## Tests

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s dot_local/share/agent-alert/tests -p 'test_herdr.py'
```

from the repository root. The tests run the deployed-layout copy that chezmoi
archives (nothing is applied). Most start a scratch Herdr 0.9.1 server of their
own (own home, config path and sockets under `/tmp`), drive it with
`herdr pane report-agent` and `herdr pane close`, and stop it again; they never
touch the live Herdr. Reordered and concurrent events are run against `hook.py`
directly because Herdr cannot be told in which order to start two hooks.
