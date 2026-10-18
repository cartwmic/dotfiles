# agent-alert

A small way for a coordinator to learn that a worker (an agent in a terminal pane,
a build, anything that can run a command) has finished, is blocked, or has gone.
Every such event is appended as one line to an **inbox** file. An event is only a
nudge: it names the worker and says what happened, and carries no message text.
A **sink** may also ring the coordinator, but the ring is best effort; the inbox
is what you can rely on.

Three layers, one direction of dependency: a **source** turns some system's events
into `agent-alert emit` calls; the **core** (`core/agent-alert`) is the only
program that writes the inbox; a **sink** is started after each event and nudges
the coordinator. The core knows no source and no sink by name. Python 3 standard
library only.

The inbox format, the commands, the configuration, the exit codes and the source
and sink contracts are in **[SPEC.md](./SPEC.md)**. This file does not restate
them; it says how to install and use the tool, how to add an adapter, and what
goes wrong. Each adapter has a section here.

| Part | What it is |
|---|---|
| `core/agent-alert` | `emit`, `tail`, `ack` ([SPEC.md](./SPEC.md)) |
| `adapters/herdr/` | Source: a Herdr plugin ([section](#herdr-source-adapter)) |
| `adapters/claude-doorbell/` | Sink: rings a Claude cloud session ([section](#claude-doorbell-sink)) |
| `examples/` | A worked source and a worked consumer, also in [SPEC.md](./SPEC.md#worked-examples) |
| `tests/` | Tests; source-only, not deployed |

## Install

The directory is a chezmoi source tree. Apply it on a desktop profile (the phone
profile does not get it):

```
chezmoi apply
```

It deploys to `~/.local/share/agent-alert`. Nothing runs until you enable an
adapter: see the [Herdr](#herdr-source-adapter) and
[doorbell](#claude-doorbell-sink) sections. The inbox is
`~/.local/share/coordinator/inbox.jsonl` unless
`~/.config/agent-alert/config.json` says otherwise.

## Usage

Record an event, read what is new, and say what you have handled:

```sh
AGENT_ALERT="$HOME/.local/share/agent-alert/core/agent-alert"
"$AGENT_ALERT" emit --worker my-pane --kind finished
"$AGENT_ALERT" tail --since 0
"$AGENT_ALERT" ack 1
```

`emit` exits 0 only when the event is in the inbox. `tail` prints the inbox lines
after a sequence number, unchanged; without `--since` it starts after your last
`ack`. [SPEC.md](./SPEC.md#commands) has the commands and
[exit codes](./SPEC.md#exit-codes).

### Watch the inbox in a pane

The core has no follow command and no daemon. To watch the inbox in a Herdr pane,
run the system `tail -F` there yourself; the pane is only a view. Pick the pane
(`herdr pane list`), keep its id in `PANE`, and start the follower in it:

```sh
herdr pane run "$PANE" 'tail -n 20 -F "$HOME/.local/share/coordinator/inbox.jsonl"'
```

The inbox is append-only, so `tail -F` never loses its place, and it starts by
showing the last 20 lines.

### Wait for the next event

Say `NEXT` is one more than the `seq` of the last event you handled. This blocks
until the pane shows a line for that sequence number, or fails after 30 seconds:

```sh
herdr pane wait-output "$PANE" --source recent-unwrapped --timeout 30000 --regex '^\{"version":1,"seq":'"$NEXT"',.*\}$'
```

The expression is `^\{"version":1,"seq":N,.*\}$` ([SPEC.md](./SPEC.md#waiting-for-one-event-line)).
A match is a wake-up: the expression cannot validate JSON, so the reader must
parse the line and acknowledge only parsed events. A pane that is not running the
follower never satisfies the wait; read the inbox with `tail` instead, which needs
no pane.

A coordinator should also read the inbox on its own schedule with
`agent-alert tail`, since a wait can time out and a ring can be lost.

### Reading in a program

`examples/consumer-example.py` reads `agent-alert tail` output, skips lines that
are not events and accepts kinds it does not know. It is shown in
[SPEC.md](./SPEC.md#a-consumer).

## Add an adapter

**A source** is any program that runs `agent-alert emit` with a worker and a kind
for each event it is told about. Follow the [source contract](./SPEC.md#source-contract);
the [worked source example](./SPEC.md#a-source-30-lines-or-fewer) is
`examples/source-example.py`, a stand-in for an adapter to another multiplexer
that uses nothing from Herdr. Put a real adapter in `adapters/<name>/`, find the
core as `../../core/agent-alert` from there, and add a section here.

**A sink** is a program that reads one event on standard input and nudges the
coordinator. Follow the [sink contract](./SPEC.md#sink-contract), name it in the
`sink` list of `~/.config/agent-alert/config.json` (or in the environment variable
`AGENT_ALERT_SINK`), and keep it failing soft: log problems to the operator log,
exit quickly, never write the inbox.

Neither kind changes the core. A reader of the inbox follows the
[reader rules](./SPEC.md#reader-rules).

## Herdr source adapter

A Herdr plugin that turns Herdr 0.9.1's agent events into `agent-alert emit`
calls. Install it by linking and enabling the plugin, then check that Herdr
accepted it:

```sh
herdr plugin link "$HOME/.local/share/agent-alert/adapters/herdr"
herdr plugin enable agent-alert
herdr plugin log list
```

Herdr runs the hook as `python3`, with the environment of the **running Herdr
server**. After the first agent event, `herdr plugin log list` should show the run
as `succeeded` with empty `stderr`; a hook's own errors are kept there.

The hook acts on each event's own status and keeps no history:

| Herdr event | Emitted |
|---|---|
| `pane.agent_status_changed`, status `blocked` | `blocked` |
| `pane.agent_status_changed`, status `idle` or `done` | `finished` |
| `pane.agent_status_changed`, status `working`, `unknown` or anything else | nothing |
| `pane.agent_detected` | nothing |
| `pane.exited` or `pane.closed` for a pane that was seen with an agent | `exited` |
| `pane.exited` or `pane.closed` for any other pane | nothing |

The worker is the Herdr pane id (for example `w1:p2`); the context carries
`workspace_id`, `workspace_label` and `agent`. The only state is a marker file per
pane in the plugin's state directory, which is how an exit knows the pane had an
agent.

- **`errored` is never emitted.** Herdr 0.9.1 has no error status, so a turn that
  ended on an error arrives as an ordinary `finished`.
- **Events carry no message text.** The hook never reads a pane. The worker is the
  pane id, so the coordinator reads the named pane itself:

  ```sh
  herdr pane read "$PANE" --source recent-unwrapped --lines 40
  ```

- **Duplicate and late events are accepted.** Herdr gives no ordering between its
  hooks, so a `finished` can be duplicated or late; never missing a completion is
  chosen over never repeating one. When an agent's process exits, Herdr also sends
  a late `done`, which gives a `finished` next to the `exited`.
- **A missed `exited`** is accepted when the exit hook runs before any other hook
  of that pane has recorded that it had an agent.

## Claude doorbell sink

A sink that rings a Claude cloud session after each event, by running
`claude -p "<message>" --cloud <session-id>`. The message is one line, for example
`agent-alert: worker pane-3 finished (event 7). Check the inbox.` The ring is best
effort and may be lost. The doorbell always exits 0.

Configure it in two steps, taken by you; install never enables it and the session
id is never stored in the repository.

1. Name it as the core's sink, in `~/.config/agent-alert/config.json`:

   ```json
   { "sink": ["~/.local/share/agent-alert/adapters/claude-doorbell/doorbell.py"] }
   ```

2. Write the session id to the doorbell's own file, `~/.config/agent-alert/claude-doorbell.json`
   (the path in `AGENT_ALERT_DOORBELL_CONFIG` if set; the environment variable
   `AGENT_ALERT_DOORBELL_SESSION` overrides the file):

   ```sh
   mkdir -p ~/.config/agent-alert
   printf '{"session_id": "%s"}\n' "PASTE-THE-SESSION-ID-HERE" > ~/.config/agent-alert/claude-doorbell.json
   chmod 600 ~/.config/agent-alert/claude-doorbell.json
   ```

The doorbell kills `claude` after a fixed 4 seconds, below the core's sink bound
([SPEC.md](./SPEC.md#sink-contract)); it has no setting for that. Every failure is
a line in the operator log, `~/.local/state/agent-alert/agent-alert.log` unless
configured otherwise, as `<UTC time> claude-doorbell: <cause>`. None of them
changes `emit`'s exit status or loses the event.

| Cause | Log line | What to do |
|---|---|---|
| No session id | `no session id configured; no nudge sent` | Write the session id file or set the variable. |
| `claude` not found | `claude command not found on PATH; no nudge sent` | Put `claude` on the `PATH` of the process that runs `emit`. |
| `claude` exits nonzero | `claude exited with status N` | A missing or expired login is the usual cause: sign in to `claude` in a terminal. |
| Timeout | `claude timed out after 4 seconds and was killed` | The call was slow or hung; the ring may not have been sent. |
| Cannot start `claude` | `cannot start claude: …` | Fix the error shown. |
| Not an event | `event line is not a JSON object; skipped` | Nothing; the line is not rung. |

A ring can also fail silently: `claude` exits 0 but the session does not wake, for
example when the session id is wrong. The doorbell cannot tell.

## Failure modes

None of these corrupts the inbox. The operator log is
`~/.local/state/agent-alert/agent-alert.log` unless configured otherwise.

| What happens | Effect | What to do |
|---|---|---|
| **Lost ring**: the ring is not sent, not delivered, or the session does not wake | The event is in the inbox; the coordinator is not told | Read the inbox on a schedule (`tail`, or the wait above). Never treat the ring as the record. |
| **Login expired or missing** (`claude` signed out) | The doorbell logs `claude exited with status N`; no ring | Sign in to `claude` in a terminal. |
| **Herdr not relaunched**: you signed in, or installed a tool, after Herdr started | Hooks started by the running Herdr do not see the new login or `PATH`: `claude` or `python3` fails or is not found | Relaunch Herdr, then check `herdr plugin log list` and the operator log. |
| **Unwritable inbox** (bad path, unwritable directory, full disk) | `emit` exits nonzero and writes nothing; the event is **lost**; the hook logs `event was not delivered` and the core logs to the operator log. Nothing is retried; later events are delivered once the inbox works again | Fix the path or free the space. If you need the lost event, the source has to emit it again. |
| **A hook that ran before presence was recorded**: Herdr's `pane.exited` or `pane.closed` hook runs before any other hook of that pane has shown the adapter that the pane had an agent | No `exited` event for that pane | Accepted. The inbox still has the pane's earlier events; check panes with `herdr pane list`. |
| **A partial line** in the inbox (a media fault, or a disk filled by another process mid-write) | Readers skip it; the next `emit` ends it with a newline and writes on its own line | Nothing; [SPEC.md](./SPEC.md#writer-guarantees) explains. |
| **A turn that ended on an error in Herdr** | Arrives as an ordinary `finished` event | Read the pane. |

## Tests

The tests are source-only and are not deployed (`.chezmoiignore`). From the
repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/agent-alert/tests
```

They never apply anything and never touch the live Herdr, home or `claude`; see
the test module headers for what each runs.
