# Claude doorbell sink

A sink for [agent-alert](../../SPEC.md). After the core appends an event it starts
this program with the event line on standard input. The doorbell then runs

```
claude -p "<message>" --cloud <session-id>
```

to nudge ("ring") a Claude cloud session, which should then read the inbox. The
nudge is best effort and may be lost; the inbox is the source of truth, and the
coordinator should not rely on the ring alone.

The message is one line, for example
`agent-alert: worker pane-3 finished (event 7). Check the inbox.` It names the
worker and kind but carries no summary. An event of a kind this version does not
know, or with extra members, is rung the same way. A line that is not a JSON
object is skipped, as every reader of the inbox skips an unparseable line: no
ring, one line in the operator log (`event line is not a JSON object; skipped,
not rung`).

The doorbell always exits 0. Every failure is appended to the operator log
(`AGENT_ALERT_LOG`, default `~/.local/state/agent-alert/agent-alert.log`) as
`<UTC time> claude-doorbell: <cause>`.

## Install

The tree deploys to `~/.local/share/agent-alert`, so the program is
`~/.local/share/agent-alert/adapters/claude-doorbell/doorbell.py`. Install does
not enable it. Two steps, taken by you:

1. Add it to the core config `~/.config/agent-alert/config.json`
   (see [SPEC.md](../../SPEC.md#configuration)):

   ```json
   { "sinks": ["~/.local/share/agent-alert/adapters/claude-doorbell/doorbell.py"] }
   ```

2. Set the session id (below).

## Configuration

The doorbell has its own file, separate from the core config:
`~/.config/agent-alert/claude-doorbell.json`, or the path in
`AGENT_ALERT_DOORBELL_CONFIG`.

| Key | Type | Default | Environment override |
|---|---|---|---|
| `session_id` | string | none (no ring) | `AGENT_ALERT_DOORBELL_SESSION` |
| `timeout_seconds` | number above 0 | `4` | none |

To set the session id, write the file yourself on the machine that runs the
sink. The id is never stored in the repository:

```sh
mkdir -p ~/.config/agent-alert
printf '{"session_id": "%s"}\n' "PASTE-THE-SESSION-ID-HERE" > ~/.config/agent-alert/claude-doorbell.json
chmod 600 ~/.config/agent-alert/claude-doorbell.json
```

The environment variable wins over the file. Unknown keys are ignored. A file
that is missing means no id; one that cannot be read or is not a JSON object is
logged and treated as empty.

### Time limit

The doorbell kills `claude` (and its process group) after `timeout_seconds`
(default 4). The core kills any sink at `sink_timeout_seconds` (default 5), so
keep the doorbell limit below it: if you raise one, raise the other, with
`sink_timeout_seconds` larger. `emit` waits for its sinks up to that bound, so
raising it makes `emit` slower when the doorbell is slow.

## Failure causes

None of these changes `emit`'s exit status or loses the event; each is a line in
the operator log.

| Cause | Log line starts with | What to do |
|---|---|---|
| No session id | `claude-doorbell: no session id configured` | Set `session_id` or `AGENT_ALERT_DOORBELL_SESSION`. |
| `claude` not found | `claude-doorbell: claude command not found on PATH` | Install the Claude CLI, or put it on the `PATH` of the process that runs `emit`. |
| Nonzero exit | `claude-doorbell: claude exited with status N (login missing or expired?): <output tail>` | Read the output tail. A missing or expired login is the usual cause: run `claude` in a terminal and sign in again. |
| Timeout | `claude-doorbell: claude timed out after N seconds and was killed` | The cloud call was slow or hung; the nudge may not have been sent. Check the session id and network, or raise the limits. |
| Herdr not yet relaunched | same as a nonzero exit, or `claude` not found | Shells started by a running Herdr do not see a login made later. Relaunch Herdr so its shells pick up the login. |
| Unusable doorbell config | `claude-doorbell: cannot use config file …` | Fix the JSON; the doorbell then reports "no session id". |

A ring can also fail silently: `claude` exits 0 but the cloud session does not
wake, for example when the session id is wrong. The doorbell cannot tell. The
coordinator should still read the inbox on its own schedule (`agent-alert tail`).
