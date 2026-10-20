# agent-alert

A small way for a coordinator to learn that a worker (an agent in a terminal pane,
a build, anything that can run a command) has finished, is waiting on a question,
is blocked, or has gone.
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
| `adapters/claude-doorbell/` | Sink: rings a Claude cloud session ([section](#claude-doorbell-sink)) |
| Pi extension `notify-owner` | Source: a worker calls `notify_owner` (or opens `ask_user_question`) to emit `question`; Pi's clean exit emits `exited` ([section](#pi-source-notify-owner)) |
| `examples/` | A worked source and a worked consumer, also in [SPEC.md](./SPEC.md#worked-examples) |
| `tests/` | Tests; source-only, not deployed |

## Install

The directory is a chezmoi source tree. Apply it on a desktop profile (the phone
profile does not get it):

```
chezmoi apply
```

It deploys to `~/.local/share/agent-alert`. Nothing runs until you enable an
adapter: see the [Pi source](#pi-source-notify-owner) and
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

## Pi source: notify-owner

The only source in use is the Pi extension `notify-owner` (in the dotfiles repo:
`dot_pi/private_agent/extensions/notify-owner/`, with its own README; it is deployed with Pi's other extensions,
not into this directory). It runs `agent-alert emit` for the worker's Herdr pane
(the pane id from `HERDR_PANE_ID` is the worker name) and nothing else; it needs no Herdr plugin, status event or screen read:

| What happens in Pi | Emitted |
|---|---|
| The worker calls the `notify_owner(question)` tool | `question` |
| An `ask_user_question` dialog opens | `question` |
| Pi exits cleanly (the quit command, SIGTERM, SIGHUP: closing the pane) | `exited` |
| Anything else: a finished turn, progress, a Herdr `blocked` status | nothing |

The context carries `agent=pi` and, when Herdr gives it, `workspace_id`. Events carry no message text: the
worker states its question in its reply and the coordinator reads the named pane itself:

```sh
herdr pane read "$PANE" --source recent-unwrapped --lines 40
```

- **Explicit only.** A worker that needs the owner must call the tool (the personal profile's Pi
  `AGENTS.md` says so). A worker that forgets is silent when its turn ends; the coordinator's own periodic
  check of its panes is the backstop. Nothing is inferred from status, labels or screen text.
- **A hard kill (`kill -9`, out of memory) is not reported** as `exited`: no code runs. The same backstop applies.
- **Not for subagents.** A Pi subagent child (`PI_SUBAGENT_CHILD=1`) and a Pi run with no `HERDR_PANE_ID` register
  nothing.
- **Deploy.** A running Pi session gets the tool after its reload command or a restart.
- **Removed: the Herdr plugin.** An earlier adapter turned Herdr status events into events by inference (status
  mapping, subagent labels, a marker line, transcript parsing). It is gone. A machine that still has it linked
  should run `herdr plugin disable agent-alert` and `herdr plugin unlink agent-alert` (see `herdr plugin --help`)
  around the apply that removes `~/.local/share/agent-alert/adapters/herdr`.

## Claude doorbell sink

A sink that rings a Claude cloud session when an event arrives, by running
`claude --safe-mode --no-session-persistence -p "<message>" --cloud <session-id>`.
The message is one short line, for example `agent-alert: pane-3 finished #7`
(about 30 bytes), or for several events at once `agent-alert: 2 events: w15:p3V finished #134,
w19:p1 question #133`. The ring is best effort and may be lost. The doorbell always
exits 0.

What it costs and what it skips:

- **Lean start.** `--cloud <id>` with `-p` posts one message into the existing cloud
  session and exits; it starts no model turn of its own. `--safe-mode` also skips
  CLAUDE.md, skills, plugins, hooks, MCP servers and auto-memory on the machine that
  runs it, and keeps the login working (`--bare` would not: it never reads the login).
  `--no-session-persistence` saves no local transcript. The command runs from the
  directory of the operator log (`~/.local/state/agent-alert` by default), which holds
  no CLAUDE.md.
- **At most one ring per 30 seconds, and none is dropped.** The first event rings at
  once. An event that arrives inside the next 30 seconds is held, and one combined ring for
  everything held is sent when the window ends (it names the first four events, then
  "+N more (latest #S)"). The window starts at an attempt, so a failed ring also opens it,
  and a held ring that fails is logged and not retried (the inbox has the events).
  The state is in `claude-doorbell.last` beside the operator log
  (`AGENT_ALERT_DOORBELL_STATE` overrides the path): the time of the last ring, and the
  worker, kind and seq of what is held; never message text.
- **The held ring has one short-lived process.** The first held event starts
  `doorbell.py --flush` in its own session, so the core's kill of the sink does not reach
  it and `emit` does not wait for it. It sleeps until the window ends, rings, and exits as
  soon as nothing is held (at the latest after 5 minutes). Only one exists at a time; it
  is not a daemon and nothing restarts it. If it is killed, what it held waits for the
  next event, which then rings it together with its own event. Look for it with
  `pgrep -fl 'doorbell.py --flush'`.
- **Cloud sessions only.** `--cloud` takes a cloud session id (`session_…` or `cse_…`)
  or a claude.ai/code URL. It cannot ring a local terminal session.

Configure it in two steps, taken by you; install never enables it and the session
id is never stored in the repository.

1. Name it as the core's sink, in `~/.config/agent-alert/config.json`:

   ```json
   { "sink": ["~/.local/share/agent-alert/adapters/claude-doorbell/doorbell.py"] }
   ```

2. Write the session id to the doorbell's own file, `~/.config/agent-alert/claude-doorbell.json`
   (the path in `AGENT_ALERT_DOORBELL_CONFIG` if set; the environment variable
   `AGENT_ALERT_DOORBELL_SESSION` overrides the file). The file is read on every
   ring, so you can change the session at any time with no reinstall and no restart:

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
| Held | nothing is logged | An event inside the 30-second window is rung once, combined with the others, when the window ends. |
| Held ring fails | the same line as the ring it replaces | The same fix as for an immediate ring; the held events are not retried. |
| Cannot start the held-ring process | `cannot start the held-ring process: …` | The event stays held and rings with the next event. |
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
| **Pi not restarted**: you signed in, or installed a tool, after the Pi session started, or Pi was started from an SSH or other background session | The doorbell runs inside the Pi process's environment and session: it does not see a new login or `PATH`, and a login kept in the macOS Keychain may not be readable from a background session, so `claude` fails or is not found | Start Pi again from a normal terminal session, then check the operator log. |
| **Unwritable inbox** (bad path, unwritable directory, full disk) | `emit` exits nonzero and writes nothing; the event is **lost**; the extension and the core log to the operator log. Nothing is retried; later events are delivered once the inbox works again | Fix the path or free the space. If you need the lost event, the source has to emit it again. |
| **A Pi that is killed hard** (`kill -9`, out of memory) | No `exited` event: no code runs | Accepted. Check panes with `herdr pane list`. |
| **A partial line** in the inbox (a media fault, or a disk filled by another process mid-write) | Readers skip it; the next `emit` ends it with a newline and writes on its own line | Nothing; [SPEC.md](./SPEC.md#writer-guarantees) explains. |
| **A worker that forgets `notify_owner`** | Silent when its turn ends: nothing is inferred | The coordinator's periodic check of its panes. |

## Tests

The tests are source-only and are not deployed (`.chezmoiignore`). From the
repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/agent-alert/tests
```

They never apply anything and never touch the live Herdr, home or `claude` (the pane procedure tests start a scratch Herdr server); see
the test module headers for what each runs.
