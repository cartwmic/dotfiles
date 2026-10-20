# agent-alert specification, format version 1

This file is the only authoritative statement of the inbox format, the core's
configuration, and the source and sink contracts. Other documents link here and
do not restate it. The key words MUST, MUST NOT, SHOULD and MAY are used as in
RFC 2119.

## Layers

- **Core** (`core/agent-alert`): the only program that writes the inbox. Three
  commands: `emit`, `tail --since N`, `ack N`. It knows no source and no sink by
  name.
- **Source**: any program that turns some system's events into `agent-alert emit`
  calls.
- **Sink**: the one program the core may be configured to run after an append. It
  receives the event on its standard input and nudges a coordinator to read the
  inbox. A sink may be lossy; the inbox is the source of truth.

An event is only a nudge: it carries no message text. A coordinator that wants to
know more reads the worker itself.

## Inbox file

The inbox is a UTF-8 text file with one JSON object per line (JSON Lines). Its
default path is `~/.local/share/coordinator/inbox.jsonl`; see
[Configuration](#configuration).

### Event line (format version 1)

Every line that a successful `emit` writes is one complete, newline-terminated
JSON object on a single line, with these members in this order, with no
whitespace between tokens:

| Member | Type | Meaning |
|---|---|---|
| `version` | integer | The format version. `1` for this specification. |
| `seq` | integer | Sequence number. Starts at 1 and rises by exactly 1 for each line `emit` writes into that inbox. |
| `time` | string | UTC ISO-8601 time taken when `emit` runs, `YYYY-MM-DDTHH:MM:SS.mmmZ`. |
| `worker` | string | Worker id chosen by the source. Any string that is not blank. |
| `kind` | string | One of the kinds below. |
| `context` | object | Optional. An object whose values are all strings. Omitted when the source gave none. |

`emit` stores `worker` and `context` as given and writes no message member.

Context members are the source's own. A reader or sink MUST ignore a member it does not know.
A sink MAY act on a member it does know: the Herdr adapter sets `awaiting` to `none` on a
`finished` event whose pane's last `AWAITING-OWNER:` marker is a status filler (`none`,
`none yet`), and the Claude doorbell does not ring for such an event. The value is fixed and
never text from the worker.

Example (wrapped here for reading; in the file it is one line):

```
{"version":1,"seq":7,"time":"2026-10-17T12:30:05.123Z","worker":"pane-3","kind":"finished","context":{"workspace":"main"}}
```

### Waiting for one event line

Because the prefix `{"version":1,"seq":` is fixed and `seq` is followed by `,`, a
pane-watcher can wake on one event line with a regular expression that anchors the
fixed prefix and the closing brace. The writer emits compact JSON on one line, and
every complete line ends with `}`. For the event with `seq` 12 the expression is

```
^\{"version":1,"seq":12,.*\}$
```

The opening brace is escaped (`\{`) because Herdr's regex engine reads a bare `{`
as the start of a repeat count. Herdr matches the expression against one line of
the pane at a time.

A match is a wake-up and not proof of a complete event: the expression cannot
validate JSON, and a torn line that happens to end in `}` can match. The reader
MUST parse the line and acknowledge only events that parse.

### Kinds

Format version 1 defines exactly these kinds:

| Kind | Meaning |
|---|---|
| `finished` | The agent's turn ended normally. A source that cannot tell that a turn ended by asking the owner something sends `finished` for it; the event never carries the question. |
| `question` | The agent's turn ended waiting on the owner's answer. How a source knows is its own business (the Herdr adapter looks for a marker line the worker prints, and ignores a status filler such as `AWAITING-OWNER: none yet`). A source never holds or drops a `question`. The event does not carry the question. |
| `blocked` | The agent is waiting on an approval or input before it can continue. A source may leave out a block that the agent's own supervisor answers (the Herdr adapter drops one caused by a Pi async subagent) and may hold a `finished` while the agent still has work running in a helper (the Herdr adapter holds it until the helper ends). |
| `errored` | The agent's turn ended on a failure such as an API error or a rate limit, and the agent did not complete its work. |
| `exited` | The agent's process or session is gone. |

`emit` accepts only a kind defined by the format version it implements. It
rejects any other kind with exit status 2 and appends nothing.

### Writer guarantees

- Each successful `emit` appends exactly one line and exits 0 only after that
  line is in the file and has been synced. `emit` never suppresses, merges or
  drops a call, however soon it follows another call with the same worker and
  kind.
- The file is append-only: the core never truncates, rewrites, rolls back or
  replaces it, so a follower such as `tail -F` never sees it shrink.
- Writers are serialized with an exclusive lock on the file `<inbox>.lock`. The
  next `seq` is one more than the `seq` of the last line of the inbox that
  parses (1 for a new inbox), read under that lock, so sequence numbers are
  consecutive and continue across process runs.
- If the file is non-empty and does not end in a newline (a fragment), `emit`
  first writes one newline, which ends the fragment as a line of its own, and
  then its event. The new event therefore always stands alone on a line.
- If `emit` cannot write (an unwritable inbox, a failed write), it exits nonzero with a message on standard error and a line in the
  operator log. It does not undo anything it already wrote.

The guarantee is exactly this: every line a successful `emit` wrote is a
complete, newline-terminated JSON object. A line that does not parse can still
appear, because a media fault or a full disk can leave a fragment. That is why
readers MUST skip such lines.

### Reader rules

- A reader (a `tail` consumer, `ack`, a sink, a coordinator, a pane-watcher) MUST
  skip a line that does not parse as a JSON object with an integer `seq`. It MUST
  NOT stop, fail or lose its place because of one.
- A reader MUST accept and tolerate a `kind` it does not know. It MAY show or
  ignore such an event, but MUST NOT treat it as an error and MUST NOT drop the
  events after it.
- A reader MUST ignore members it does not know.
- A reader MUST NOT write to the inbox.

### Unknown kinds

Adding a kind does not change `version`, which is why every reader MUST accept an
unknown kind (see the reader rules). `emit` accepts only the kinds defined above.

## Commands

```
agent-alert emit --worker ID --kind KIND [--context KEY=VALUE]... [--context-json OBJECT]
agent-alert tail [--since N]
agent-alert ack N
```

`emit`
: Validates the input, builds the line, appends it as described above, then runs
  the configured sink. There is no option for message text. `--context` may be
  repeated; `--context-json` takes a JSON object whose values
  are all strings (a number, nested object or array value is rejected). Writes
  nothing to standard output.

`tail --since N`
: Prints, in file order and unchanged (the raw line, one per output line), every
  event whose `seq` is greater than N, whatever its kind. Prints nothing and
  exits 0 when there are none or when the inbox does not exist. Without
  `--since`, N is the latest acknowledgment (0 if none).

`ack N`
: Records that events through N have been handled, in `<inbox>.ack` (a small JSON
  object `{"acked": N}`, replaced atomically under the lock). It never alters or
  removes an inbox line. An N not above the stored acknowledgment is accepted and
  ignored (the acknowledgment never moves backwards). An N above the latest
  sequence number in the inbox is refused with exit 2 and changes nothing.

`tail` and `ack` skip lines that do not parse.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. For `emit`, the event is in the inbox, whatever its sink did. |
| 2 | Bad input or bad configuration: unknown kind, blank worker, a context that is not an object of strings, an unknown command or option (including `--summary`), an unreadable or invalid config file, an unusable `sink_timeout_seconds`, `ack` beyond the latest sequence number. Nothing is written. |
| 3 | The inbox, its lock or its acknowledgment file could not be used: unwritable path, unreadable file, or failed write. |

## Configuration

The core reads settings in this order: an environment variable, then the JSON
config file, then the default. A missing config file means all defaults. A config
file that is not a JSON object, or has a `sink_timeout_seconds` that is not a
number above 0, makes every command exit 2. Unknown keys are ignored. A leading
`~` in a path, and in the first element of `sink`, is expanded.

Config file: `~/.config/agent-alert/config.json`, or the path in
`AGENT_ALERT_CONFIG`.

| Key | Type | Default | Environment override |
|---|---|---|---|
| `inbox_path` | string | `~/.local/share/coordinator/inbox.jsonl` | `AGENT_ALERT_INBOX` |
| `log_path` | string | `~/.local/state/agent-alert/agent-alert.log` | `AGENT_ALERT_LOG` |
| `sink` | list of strings | none (no sink) | `AGENT_ALERT_SINK`, a JSON list of strings; when set it replaces the `sink` key |
| `sink_timeout_seconds` | number above 0 | `5` | none |

`sink` is the one sink command: a program followed by its arguments. The inbox
directory is created on demand. Files beside the inbox are
`<inbox>.lock` and `<inbox>.ack`.

Settings of a source or sink (for example a sink's own credentials or target)
belong to that adapter, in its own file; the core's config never holds them.

## Operator log

An append-only text file at `log_path`, one line per problem, in the form

```
<UTC time> <component>: <cause>
```

The core writes its own failures (`core: emit failed: …`) and a failure of the sink
(`core: sink <program>: exited with status 3`, `…: cannot start: …`,
`…: timed out after 5 seconds and was killed`). A sink or source MAY append its
own lines with another component name. Logging is best effort and never changes
an exit status.

## Sink contract

After a successful append, and after releasing the lock, the core runs the one
configured sink once, whatever the kind of the event:

- The sink is started as its own process (its own process group) with the **event
  line** (the exact bytes appended, with the final newline) on its standard
  input; standard input is then closed. Standard output and standard error are
  discarded; a sink reports problems through the operator log.
- The environment is the core's environment plus `AGENT_ALERT_INBOX`,
  `AGENT_ALERT_LOG` and `AGENT_ALERT_CONFIG`, set to the resolved paths.
- The core waits for the sink for at most `sink_timeout_seconds`. A sink still
  running then is killed with its process group. `emit` therefore returns within
  that bound plus a small constant, and sooner when the sink has finished.
- The sink's exit status is ignored for `emit`'s exit status. A sink that exits
  nonzero, cannot be started (missing or not executable) or is killed at the
  bound is logged with that cause; the event stays in the inbox, and `emit`
  still exits 0. A sink never fails, delays beyond the bound, or undoes an
  `emit`.
- A sink MUST tolerate an event whose `kind` it does not know and members it does
  not know, and SHOULD ring or fail soft rather than fail. A sink MUST NOT write
  to the inbox.
- A sink MAY decide not to nudge for an event (the Claude doorbell skips a `finished` whose
  context says `awaiting=none`), or to hold it and nudge once later for
  several (the Claude doorbell rings at most once per 30 seconds and combines the
  events held in that window into one ring at its end); the event is in the inbox
  either way.
- A sink that nudges later MAY start one detached helper process (its own session, so
  the kill at the bound does not reach it) to do it. That helper MUST end by itself
  within a bounded time, MUST NOT outlive the work it was started for, MUST NOT write
  to the inbox, and MUST log its failures like the sink does. The core does not wait
  for it, track it or kill it.
- A sink MUST NOT assume the nudge is the only way the coordinator learns of the
  event: nudges may be lost.

## Source contract

A source calls the core's `emit` as a child process and does nothing else with
the inbox:

- A source MUST NOT read or write the inbox file directly or assign sequence
  numbers; `emit` does that.
- A source promises only that it calls `emit` for every completion (or other
  event) it is told about. Keeping the event is the core's guarantee.
- A source chooses a stable `worker` id for the thing it describes (for example a
  pane id) and MAY pass a small `context` of short strings.
- A source MUST treat a nonzero exit from `emit` as "this event was not
  recorded". It SHOULD report the failure where its operator can see it and MUST
  NOT crash its host because of it. Retrying is the source's choice; the core
  never retries and never queues.
- A source MAY emit duplicate or late events. Duplicates are tolerated; a missed
  event is not.
- A source finds the core relative to its own location in the installed tree
  (`../../core/agent-alert` from `adapters/<name>/`), so the directory can be
  moved as a unit.
- The [worked source example](#a-source-30-lines-or-fewer) below does all of this.

## Worked examples

Both examples are the files `examples/source-example.py` and
`examples/consumer-example.py` of this tree, included here without change. They
use the Python standard library only.

### A source (30 lines or fewer)

A source needs only to run `agent-alert emit` with a worker and a kind for each
thing it is told about, and to report, without stopping, an `emit` that failed.
This one stands in for an adapter to another multiplexer: it turns lines of the
form `PANE STATE` on standard input into events and uses nothing from Herdr.

```python
#!/usr/bin/env python3
"""Worked source: stands in for an adapter to some other multiplexer.

Reads "PANE STATE" lines on stdin (STATE is idle, waiting, failed or closed) and
emits one event per line: a worker and a kind, no message text.
"""
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core" / "agent-alert"  # found relative to this file
KINDS = {"idle": "finished", "waiting": "blocked", "failed": "errored", "closed": "exited"}

for line in sys.stdin:
    parts = line.split()
    if len(parts) != 2 or parts[1] not in KINDS:
        print("skipped: " + line.strip(), file=sys.stderr)
        continue
    result = subprocess.run([str(CORE), "emit", "--worker", parts[0], "--kind", KINDS[parts[1]]],
                            capture_output=True, text=True)
    if result.returncode != 0:  # the event was not recorded: say so, keep going
        print("not recorded (%d): %s" % (result.returncode, result.stderr.strip()), file=sys.stderr)
```

Try it, with the tree installed at `~/.local/share/agent-alert`:

```
printf 'pane-1 idle\n' | python3 ~/.local/share/agent-alert/examples/source-example.py
```

### A consumer

A consumer reads the output of `agent-alert tail`. It skips a line that is not an
event, accepts a `kind` it does not know, and ignores members it does not know,
as the [reader rules](#reader-rules) require. Events carry no message text, so it
prints the sequence number, worker and kind.

```python
#!/usr/bin/env python3
"""Worked consumer: print one line per event of `agent-alert tail` read on stdin.

    agent-alert tail --since 0 | python3 consumer-example.py
"""
import json
import sys

KNOWN_KINDS = {"finished", "question", "blocked", "errored", "exited"}

for line in sys.stdin:
    try:
        event = json.loads(line)
        seq = event["seq"]
        if type(seq) is not int:
            raise ValueError("seq is not an integer")
    except (ValueError, KeyError, TypeError):
        continue  # a line that is not an event: skip it and keep reading
    kind = event.get("kind")
    note = "" if str(kind) in KNOWN_KINDS else " (kind unknown to this reader, shown anyway)"
    print("%d %s %s%s" % (seq, event.get("worker"), kind, note))
```

Try it:

```
~/.local/share/agent-alert/core/agent-alert tail --since 0 | python3 ~/.local/share/agent-alert/examples/consumer-example.py
```
