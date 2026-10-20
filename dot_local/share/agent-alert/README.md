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
| `pane.agent_status_changed`, status `blocked` | `blocked`, except when a [Pi subagent](#pi-subagent-noise) is the cause: nothing |
| `pane.agent_status_changed`, status `idle` or `done`, and the pane's last lines hold the [question marker](#the-question-marker) | `question` (always, even with a subagent running) |
| `pane.agent_status_changed`, status `idle` or `done`, a subagent still running in the pane | nothing (held until the subagent label clears) |
| `pane.agent_status_changed`, status `idle` or `done`, and the pane's last marker is a filler (`AWAITING-OWNER: none` or `none yet`) | `finished` with context `awaiting=none`; the [Claude doorbell](#claude-doorbell-sink) does not ring for it |
| `pane.agent_status_changed`, status `idle` or `done`, otherwise (no marker, or the pane cannot be read) | `finished` |
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
- **Events carry no message text.** Only a turn that ended (`idle` or `done`) makes the
  hook look at a pane, once, for the question marker below; it keeps the yes or no and
  nothing else. The worker is the pane id, so the coordinator reads the named pane itself:

  ```sh
  herdr pane read "$PANE" --source recent-unwrapped --lines 40
  ```

- **Duplicate and late events are accepted.** Herdr gives no ordering between its
  hooks, so a `finished` can be duplicated or late; never missing a completion is
  chosen over never repeating one. When an agent's process exits, Herdr also sends
  a late `done`, which gives a `finished` next to the `exited`.
- **A missed `exited`** is accepted when the exit hook runs before any other hook
  of that pane has recorded that it had an agent.

### The question marker

Herdr 0.9.1 reports a turn that ends with a question as plain `idle`: it has no state
for "waiting on the owner" (`blocked` is for an approval or input prompt the agent itself
raised). So the worker says it. A worker whose turn ends waiting on the owner's answer
prints one line that starts with

```
AWAITING-OWNER:
```

at the end of its last message, for example `AWAITING-OWNER: which database?`. Put the
instruction in the worker's prompt or its AGENTS.md; the adapter cannot ask for it.

Use the marker only when the owner must answer. Report progress with a line that starts
with `Status:` (for example `Status: tests running`). A marker followed by a status
filler (`none` or `none yet`, any case, with or without punctuation) is not a question:
the hook records that turn as a `finished` whose context carries `awaiting=none`, and the
[Claude doorbell](#claude-doorbell-sink) does not ring for it (owner decision: a turn that
needs nothing from the owner is silent). The personal profile's Pi `AGENTS.md` has workers end
every reply with `AWAITING-OWNER: none` when they need nothing, so those turns are silent at the
doorbell; only a real question rings as a `question`. The quiet flag is a fixed context value, never
text from the pane. Only the **last** marker line in the pane counts: an old question followed by a
later `none` is quiet, and a `none` followed by a later question is a `question`. A pane that cannot
be read, or shows no marker, is an ordinary `finished` and rings. `blocked` ignores the marker.

What the hook does with it:

- On `idle` or `done` it runs `herdr pane read <pane> --source recent-unwrapped --lines 30`
  (5 second limit), looks for a line that starts with `AWAITING-OWNER:` (a bullet or a box
  edge in front, up to 8 non-word characters, is allowed), and emits `question`
  instead of `finished` if the last such line carries a real question. The text after the
  colon is read only to recognise a status filler (see above), then dropped; the pane text
  is not stored, logged or sent: the inbox and the ring carry the kind (and the fixed
  `awaiting=none` flag) only.
- If the read fails (the pane is gone, Herdr is slow, `herdr` is not found) the hook says
  so on stderr (without pane text) and emits `finished`: the event is never lost.
  `blocked` is never read or changed.
- It looks at the last 30 lines, which include the agent's prompt box and footer.
  A marker from an earlier turn that is still in those lines gives a false `question`
  for a short later turn. That costs a look at the pane; a missed marker costs the old
  behaviour (`finished`). Print the marker only when you are waiting.
- It finds `herdr` as `HERDR_BIN_PATH` (set by Herdr for the hook) or on `PATH`.

### Pi subagent noise

A Pi worker that starts async subagents makes two kinds of noise that need no owner:
the worker's own turn ends (`idle`) while a subagent still runs, and a subagent that
calls `contact_supervisor` turns the pane `blocked` (the worker answers it itself). The
hook filters both, using only what Herdr already gives it.

Pi's subagent extension publishes the running subagents as the pane's Herdr state labels:
`⏳ 2 subagents (scout, worker)`, with a trailing `⚠` while a subagent needs attention
(a subagent waiting on `contact_supervisor` is one). Herdr puts `state_labels` in every
`pane.agent_status_changed` event and sends a new one whenever the labels change or
expire. The hook does not read pane text for this. It matches `⏳ N subagent(s)` in the
labels.

- **`finished` is held while a subagent runs.** An `idle` or `done` event whose labels show
  a running subagent emits nothing. When the subagent ends, the label clears, Herdr sends
  another status event with no label, and that one emits the `finished`. If Pi dies with a
  subagent running, the label expires (its TTL) and the same happens. There is no timer
  and no extra process. The doorbell's 30 second hold combines this `finished` with the
  worker's own, if the worker wakes and ends a turn right after.
- **`question` is never held or dropped.** The marker check runs first. A turn that ends on
  `AWAITING-OWNER:` rings at once, subagent or not. If the pane cannot be read the event is
  `finished`, not held, because it might be a question.
- **`blocked` from a subagent is dropped.** A `blocked` event whose labels show a running
  subagent flagged `⚠` emits nothing. Pi publishes its labels only under the `idle`, `done`
  and `working` keys, never `blocked`, and Herdr puts all of them in every status event, so the
  hook reads the labels of every key (a real Herdr server test covers this shape). Pi reports `blocked` a moment before it publishes the
  `⚠`, so for a `blocked` event with a running, unflagged subagent the hook asks
  `herdr pane get` every half second for up to 3 seconds. If the flag shows, it drops the
  event. If the subagent is gone, the 3 seconds pass, or the read fails, it emits `blocked`.
  A `blocked` event with no subagent label is emitted at once. Anything else rings: the parent's
  own prompt (for example `ask_user_question`) while a subagent runs is a `blocked` with an
  unflagged label, so it waits out the 3 seconds and is emitted. In Pi's subagent extension the
  `⚠` and the `blocked` come from the same step, so a `blocked` that never gets the flag
  is not caused by a subagent.
- **Limit.** The `⚠` means "a subagent needs attention", which is mostly
  `contact_supervisor` but also a stuck tool or repeated failures; the label cannot tell
  them apart. The worker handles all of those itself. A different block (for example an
  `ask_user_question` prompt) that happens while a subagent is flagged is hidden too,
  because Herdr has one `blocked` state per pane.

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
- **A `finished` that says `awaiting=none` is not rung.** The Herdr adapter sets that context
  flag when the pane's last marker is `AWAITING-OWNER: none` (or `none yet`). The doorbell skips
  such an event before the window, so it opens no window, holds nothing and starts no process;
  the inbox still has the event. Every other event rings, including a `question`, a `blocked`
  and a `finished` from an unreadable pane. This is the only sink that reads the flag; the inbox
  and any other sink see the `finished` as before.
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
   ring, so you can change the session at any time with no reinstall and no Herdr
   relaunch:

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
| **Herdr not relaunched**: you signed in, or installed a tool, after Herdr started, or Herdr was started from an SSH or other background session | Hooks started by the running Herdr keep that server's environment and session: they do not see a new login or `PATH`, and a login kept in the macOS Keychain may not be readable from a background session, so `claude` fails or is not found | Relaunch Herdr from Terminal.app (a GUI session), then check `herdr plugin log list` and the operator log. Relaunching ends the running panes (see Herdr's session-state docs); pick a safe moment. |
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
