# agent-alert

A small way for a coordinator to learn that a worker (an agent in a terminal pane,
a build, anything that can run a command) has finished, is blocked, or has gone.
Every such event is appended as one line to an **inbox** file. A **sink**
may also nudge ("ring") the coordinator, but the nudge is best effort; the inbox
is what you can rely on.

Three layers, one direction of dependency: a **source** turns some system's events
into `agent-alert emit` calls; the **core** (`core/agent-alert`) is the only
program that writes the inbox; a **sink** is started after each event and nudges
the coordinator. The core knows no source and no sink by name. Python 3 standard
library only.

The inbox format, the commands, the configuration, the exit codes and the source
and sink contracts are in **[SPEC.md](./SPEC.md)**. This file does not restate
them; it says how to install and use the tool and what goes wrong.

| Part | What it is | Documentation |
|---|---|---|
| `core/agent-alert` | `emit`, `tail`, `ack` | [SPEC.md](./SPEC.md) |
| `adapters/herdr/` | Source: Herdr plugin that emits an event when an agent pane finishes, blocks or exits | [adapters/herdr/README.md](./adapters/herdr/README.md) |
| `adapters/claude-doorbell/` | Sink: nudges a Claude cloud session | [adapters/claude-doorbell/README.md](./adapters/claude-doorbell/README.md) |
| `examples/` | A worked source and a worked consumer, also shown in SPEC.md | [SPEC.md](./SPEC.md#worked-examples) |
| `tests/` | Tests; source-only, not deployed | |

## Install

The directory is a chezmoi source tree. Apply it on a desktop profile (the phone
profile does not get it):

```
chezmoi apply
```

It deploys to `~/.local/share/agent-alert`. Nothing runs until you enable an
adapter. To use it with Herdr 0.9.1, link and enable the Herdr plugin, then check
that Herdr accepted it:

```sh
herdr plugin link "$HOME/.local/share/agent-alert/adapters/herdr"
herdr plugin enable agent-alert
herdr plugin log list
```

Herdr runs the plugin's hook as `python3`, with the environment of the **running
Herdr server**. After the first agent event, `herdr plugin log list` should show
the run as `succeeded` with empty `stderr`; see the
[Herdr adapter README](./adapters/herdr/README.md) for what it reports.

The inbox is `~/.local/share/coordinator/inbox.jsonl` unless
`~/.config/agent-alert/config.json` says otherwise. The ring is off until you
configure a sink; the [doorbell README](./adapters/claude-doorbell/README.md)
has the two steps. Install never enables a sink and never stores a session id.

## Usage

The core is `~/.local/share/agent-alert/core/agent-alert`. Record an event, read
what is new, and say what you have handled:

```sh
AGENT_ALERT="$HOME/.local/share/agent-alert/core/agent-alert"
"$AGENT_ALERT" emit --worker my-pane --kind finished --summary "Should I delete the staging branch?"
"$AGENT_ALERT" tail --since 0
"$AGENT_ALERT" ack 1
```

`emit` exits 0 only when the event is in the inbox. `tail` prints the inbox lines
after a sequence number, unchanged; without `--since` it starts after your last
`ack`. [SPEC.md](./SPEC.md#commands) has the commands and
[exit codes](./SPEC.md#exit-codes).

### Watch the inbox in a pane

The core has no follow command and no daemon. To watch the inbox in a Herdr pane,
run the system `tail -F` there yourself. The pane is then only a view: nothing
writes to the inbox but `emit`. Pick the pane (`herdr pane list`), keep its id in
`PANE`, and start the follower in it:

```sh
herdr pane run "$PANE" 'tail -n 20 -F "$HOME/.local/share/coordinator/inbox.jsonl"'
```

The inbox is append-only, so `tail -F` never loses its place, and it starts by
showing the last 20 lines, so an event written just before it started is still on
the screen. `herdr pane read` shows what the pane displays:

```sh
herdr pane read "$PANE" --source recent-unwrapped --lines 20
```

### Wait for the next event

Say `NEXT` is one more than the `seq` of the last event you handled (for example
the number after your last `ack`). This blocks until the pane shows the complete
event line with that sequence number, or fails after 30 seconds:

```sh
herdr pane wait-output "$PANE" --source recent-unwrapped --timeout 30000 --regex '(?m)^\{"version":1,"seq":'"$NEXT"',.*[^\\](?:\\\\)*"\}\}?$'
```

The expression starts at the fixed beginning of an event line and ends the way
every complete line ends, with an unescaped `"` and then `}` or `}}`
([why](./SPEC.md#event-line-format-version-1)), so a partial line that merely
contains the number, or that was cut at a brace inside the summary, does not
satisfy it. The wait is a wake-up, not a check: a regular expression cannot
validate JSON. When it returns, parse the line and `ack` only events that parse
([the example below](#reading-in-a-program) skips the rest); a torn line that
happens to end like a complete one can still wake the wait, and the reader skips
it. Use `--source
recent-unwrapped`: a long event line wraps in a narrow pane, and the wrapped
source gives it back as one line. A pane that is not running the follower never
satisfies the wait; read the inbox with `tail` instead, which needs no pane. The
event is in the inbox with or without the pane.

A coordinator should also read the inbox on its own schedule with
`agent-alert tail`, since a wait can time out and a ring can be lost.

### Reading in a program

`examples/consumer-example.py` reads `agent-alert tail` output, skips lines that
are not events and accepts kinds it does not know. It is shown in
[SPEC.md](./SPEC.md#a-consumer).

## Add an adapter

**A source** is any program that runs `agent-alert emit` for each event it is
told about. Follow the [source contract](./SPEC.md#source-contract); the
[worked source example](./SPEC.md#a-source-30-lines-or-fewer) is
`examples/source-example.py`. Put a real adapter in `adapters/<name>/` and find
the core as `../../core/agent-alert` from there, so the directory still moves as
one unit. Add a short README beside it, and link it from here.

**A sink** is a program that reads one event on standard input and nudges the
coordinator. Follow the [sink contract](./SPEC.md#sink-contract), list it under
`sinks` in `~/.config/agent-alert/config.json`, and keep it failing soft: log
problems to the operator log, exit quickly, never write the inbox.

Neither kind changes the core. A reader of the inbox follows the
[reader rules](./SPEC.md#reader-rules).

## Failure modes

None of these corrupts the inbox. The operator log is
`~/.local/state/agent-alert/agent-alert.log` unless configured otherwise.

| What happens | Effect | What to do |
|---|---|---|
| **Lost ring**: the nudge is not sent, not delivered, or the cloud session does not wake | The event is in the inbox; the coordinator is not told | Read the inbox on a schedule (`tail`, or the wait above). Never treat the ring as the record. Check the operator log for a sink line. |
| **Login expired or missing** (`claude` signed out) | The doorbell logs `claude exited with status N` and exits 0; no ring | Sign in to `claude` in a terminal; see the [doorbell README](./adapters/claude-doorbell/README.md#failure-causes). |
| **Herdr not relaunched**: you signed in, or installed a tool, after Herdr started | Shells and hooks started by the running Herdr do not see the new login or `PATH`: `claude` or `python3` fails or is not found | Relaunch Herdr, then check `herdr plugin log list` and the operator log. |
| **Inbox not writable** (bad path, unwritable directory, full disk) | `emit` exits nonzero and writes nothing; the event is **lost**; the hook logs `event was not delivered` and the core logs to the operator log. It is not retried; later events are delivered once the inbox works again | Fix the path or free the space. If you need the lost event, the source has to emit it again. |
| **A hook that ran before presence was recorded**: Herdr's `pane.exited` or `pane.closed` hook runs before any other hook of that pane has shown the adapter that the pane had an agent | No `exited` event for that pane | Accepted; see [what you accept](./adapters/herdr/README.md#what-you-accept). The inbox still has the pane's earlier events, and the coordinator can check panes with `herdr pane list`. |
| **A partial line** in the inbox (a media fault, or a disk filled by another process mid-write) | Readers skip it; the next `emit` ends it with a newline and writes on its own line; a pane shows it once | Nothing; [SPEC.md](./SPEC.md#writer-guarantees) explains. |
| **A turn that ended on an error in Herdr** | Arrives as an ordinary finished event | [Herdr adapter README](./adapters/herdr/README.md#errored-is-never-emitted) explains. |

## Tests

The tests are source-only and are not deployed (`.chezmoiignore`). From the
repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/agent-alert/tests
```

They never apply anything and never touch the live Herdr, home or `claude`; see
the test module headers for what each runs. `tests/live_guard.py` (`snapshot`,
then `check`) proves the live machine untouched. It watches
`~/.local/share/agent-alert`, so run it before any approved `chezmoi apply`
that deploys this tree, not after.
