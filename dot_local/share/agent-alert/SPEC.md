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
- **Sink**: any program that receives one event on its standard input and nudges
  a coordinator to read the inbox. A sink may be lossy; the inbox is the source
  of truth.

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
| `worker` | string | Worker id chosen by the source: not blank, at most 128 characters, no control or line-break characters. |
| `kind` | string | One of the kinds below. |
| `summary` | string | One line, at most 200 characters, masked (see [Summary](#summary)). May be empty. |
| `context` | object | Optional. At most 8 members; each key is at most 32 characters and each value is a string of at most 100 characters, masked like the summary. Omitted when the source gave none. |

Example (wrapped here for reading; in the file it is one line):

```
{"version":1,"seq":7,"time":"2026-10-17T12:30:05.123Z","worker":"pane-3","kind":"finished","summary":"…Should I delete the staging branch now?","context":{"workspace":"main"}}
```

Because the prefix `{"version":1,"seq":` is fixed and `seq` is followed by `,`, a
reader or a pane-watcher can match one complete event line by a regular expression
that anchors the fixed prefix and the closing brace, for example
`^\{"version":1,"seq":12,.*\}$` for the event with `seq` 12. A fragment that
merely contains the number does not match it.

### Kinds

Format version 1 defines exactly these kinds:

| Kind | Meaning |
|---|---|
| `finished` | The agent's turn ended normally. This includes a turn that ends by asking a question or reporting a gate; the question or gate is carried in the summary. |
| `blocked` | The agent is waiting on an approval or input before it can continue. |
| `errored` | The agent's turn ended on a failure such as an API error or a rate limit, and the agent did not complete its work. |
| `exited` | The agent's process or pane is gone. |

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
- Before writing, `emit` checks the free space available on the inbox's
  filesystem. If it is below the length of the line plus `free_space_margin_bytes`
  (default 1048576), `emit` exits 3 and writes nothing, so an ordinary full disk
  cannot leave a partial line.
- If the file is non-empty and does not end in a newline (a fragment), `emit`
  first writes one newline, which ends the fragment as a line of its own, and
  then its event. The new event therefore always stands alone on a line.
- If `emit` cannot write (an unwritable inbox, too little space, a failed
  write), it exits nonzero with a message on standard error and a line in the
  operator log. It does not undo anything it already wrote.

The guarantee is exactly this: every line a successful `emit` wrote is a
complete, newline-terminated JSON object. A line that does not parse can still
appear, because a media fault, or another process filling the disk between the
free-space check and the write, can leave a fragment. That is why readers MUST
skip such lines.

### Reader rules

- A reader (a `tail` consumer, `ack`, a sink, a coordinator, a pane-watcher) MUST
  skip a line that does not parse as a JSON object with an integer `seq`. It MUST
  NOT stop, fail or lose its place because of one.
- A reader MUST accept and tolerate a `kind` it does not know. It MAY show or
  ignore such an event, but MUST NOT treat it as an error and MUST NOT drop the
  events after it.
- A reader MUST ignore members it does not know.
- A reader MUST NOT write to the inbox.

### Compatibility rules

The format version is the integer `version`. Within one version:

- Adding a kind is a backward-compatible change and does not change `version`.
  This is why every reader MUST accept an unknown kind.
- Adding an optional member to an event, or a key to `context`, is
  backward-compatible and does not change `version`.
- Removing or renaming a member, changing the type or meaning of a member, or
  changing how `seq` is assigned is a breaking change and MUST increase
  `version`.

A reader that sees a `version` higher than it knows SHOULD still read the members
it knows and MUST still skip, not fail on, a line it cannot use. `emit` writes
only the version it implements and accepts only the kinds that version defines.

## Summary

The core applies these rules to the `summary` of every `emit`, whatever the
source, and the masking rules to every value in `context`:

1. **Mask** token-shaped strings with `***`: API keys of the shapes `sk-…`,
   `ghp_…` (and `gho_`, `ghu_`, `ghs_`, `ghr_`), `github_pat_…`, `AKIA…` and
   `xox[abprs]-…`; `Bearer` tokens; and the value in `name=value`, `name: value`
   or `"name": "value"` where the name ends in `token`, `secret`, `password`,
   `passwd`, `api_key`/`api-key`/`apikey`, or is `key` (alone or after `_`, `.` or
   `-`). Masking covers common shapes only and is not a guarantee against every
   secret format.
2. **Collapse** every run of whitespace, newlines and control characters into one
   space and trim.
3. **Keep the end**: if more than 200 characters remain, keep the last 199
   characters and put `…` (U+2026) in front. The end is kept because a question
   or request for a decision usually closes a message.

Masking runs before the cut, so a secret that the cut would split cannot survive.
`emit` also refuses a `worker` or a context key that is itself token-shaped (exit
2), so no token-shaped secret is stored anywhere in the inbox.

## Commands

```
agent-alert emit --worker ID --kind KIND [--summary TEXT|-] [--context KEY=VALUE]... [--context-json OBJECT]
agent-alert tail [--since N]
agent-alert ack N
```

`emit`
: Validates the input, builds the line, appends it as described above, then runs
  the configured sinks. `--summary -` reads the text from standard input.
  `--context` may be repeated; `--context-json` takes a JSON object whose values
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
| 0 | Success. For `emit`, the event is in the inbox, whatever its sinks did. |
| 2 | Bad input or bad configuration: unknown kind, blank or secret-shaped worker, a non-string or oversized context, an unknown command or option, an unreadable or invalid config file, `ack` beyond the latest sequence number. Nothing is written. |
| 3 | The inbox, its lock or its acknowledgment file could not be used: unwritable path, unreadable file, failed write, or free space below the margin. |

## Configuration

The core reads settings in this order: an environment variable, then the JSON
config file, then the default. A missing config file means all defaults. A config
file that is not a JSON object, or has a value of the wrong type, makes every
command exit 2. Unknown keys are ignored. A leading `~` in a path is expanded.

Config file: `~/.config/agent-alert/config.json`, or the path in
`AGENT_ALERT_CONFIG`.

| Key | Type | Default | Environment override |
|---|---|---|---|
| `inbox_path` | string | `~/.local/share/coordinator/inbox.jsonl` | `AGENT_ALERT_INBOX` |
| `log_path` | string | `~/.local/state/agent-alert/agent-alert.log` | `AGENT_ALERT_LOG` |
| `sinks` | list | `[]` | none |
| `sink_timeout_seconds` | number above 0 | `5` | none |
| `free_space_margin_bytes` | integer, 0 or more | `1048576` | none |

Each `sinks` entry is either a string (the path of a program, run with no
arguments) or a non-empty list of strings (a program followed by its arguments).
The inbox directory is created on demand. Files beside the inbox are
`<inbox>.lock` and `<inbox>.ack`.

Settings of a source or sink (for example a sink's own credentials or target)
belong to that adapter, in its own file; the core's config never holds them.

## Operator log

An append-only text file at `log_path`, one line per problem, in the form

```
<UTC time> <component>: <cause>
```

The core writes its own failures (`core: emit failed: …`) and each sink failure
(`core: sink <program>: exited with status 3`, `…: cannot start: …`,
`…: timed out after 5 seconds and was killed`). A sink or source MAY append its
own lines with another component name. Logging is best effort and never changes
an exit status.

## Sink contract

After a successful append, and after releasing the lock, the core invokes **each**
configured sink once, whatever the kind of the event:

- The sink is started as its own process (its own process group) with the **event
  line** (the exact bytes appended, with the final newline) on its standard
  input; standard input is then closed. Standard output and standard error are
  discarded; a sink reports problems through the operator log.
- The environment is the core's environment plus `AGENT_ALERT_INBOX`,
  `AGENT_ALERT_LOG` and `AGENT_ALERT_CONFIG`, set to the resolved paths.
- All sinks are started at once and share one deadline of `sink_timeout_seconds`
  counted from just before the sinks are started. A sink still running at the deadline
  is killed with its process group. `emit` therefore returns within the
  deadline plus a small constant, and sooner when every sink has finished.
- The sink's exit status is ignored for `emit`'s exit status. A sink that exits
  nonzero, cannot be started (missing or not executable) or is killed at the
  deadline is logged with that cause; the event stays in the inbox, and `emit`
  still exits 0. A sink never fails, delays beyond the bound, or undoes an
  `emit`.
- A sink MUST tolerate an event whose `kind` it does not know and members it does
  not know, and SHOULD ring or fail soft rather than fail. A sink MUST NOT write
  to the inbox.
- A sink MUST NOT assume the nudge is the only way the coordinator learns of the
  event: nudges may be lost.

## Source contract

A source calls the core's `emit` as a child process and does nothing else with
the inbox:

- A source MUST NOT read or write the inbox file directly or assign sequence
  numbers; `emit` does that.
- A source promises only that it calls `emit` for every completion (or other
  event) it is told about. Keeping the event is the core's guarantee.
- A source passes the raw text it wants summarized as `--summary` (or
  `--summary -` with the text on standard input); the core masks and shortens it,
  so a source MUST NOT rely on its own masking and need not do any.
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

A source needs only to run `agent-alert emit` for each thing it is told about,
and to report, without stopping, an `emit` that failed. This one turns lines of
the form `WORKER STATUS free text` on standard input into events.

```python
#!/usr/bin/env python3
"""Worked source: read "WORKER STATUS free text" lines on stdin, emit one event each.

STATUS is done, waiting, failed or gone. The core masks and shortens the text.
"""
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core" / "agent-alert"  # found relative to this file
KINDS = {"done": "finished", "waiting": "blocked", "failed": "errored", "gone": "exited"}

for line in sys.stdin:
    parts = line.split(None, 2)
    if len(parts) < 2 or parts[1] not in KINDS:
        print("skipped: " + line.strip(), file=sys.stderr)
        continue
    command = [str(CORE), "emit", "--worker", parts[0], "--kind", KINDS[parts[1]],
               "--context", "source=example", "--summary", "-"]
    result = subprocess.run(command, input=parts[2] if len(parts) > 2 else "",
                            text=True, capture_output=True)
    if result.returncode != 0:  # the event was not recorded: say so, keep going
        print("not recorded (%d): %s" % (result.returncode, result.stderr.strip()), file=sys.stderr)
```

Try it, with the tree installed at `~/.local/share/agent-alert`:

```
printf 'job-1 done Build finished. Deploy now?\n' | python3 ~/.local/share/agent-alert/examples/source-example.py
```

### A consumer

A consumer reads the output of `agent-alert tail`. It skips a line that is not an
event, accepts a `kind` it does not know, and ignores members it does not know,
as the [reader rules](#reader-rules) require.

```python
#!/usr/bin/env python3
"""Worked consumer: print one line per event of `agent-alert tail` read on stdin.

    agent-alert tail --since 0 | python3 consumer-example.py
"""
import json
import sys

KNOWN_KINDS = {"finished", "blocked", "errored", "exited"}

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
    print("%d %s %s%s: %s" % (seq, event.get("worker"), kind, note, event.get("summary", "")))
```

Try it:

```
~/.local/share/agent-alert/core/agent-alert tail --since 0 | python3 ~/.local/share/agent-alert/examples/consumer-example.py
```
