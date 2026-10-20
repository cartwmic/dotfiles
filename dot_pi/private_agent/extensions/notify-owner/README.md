# notify-owner (Pi extension)

The explicit way a Pi worker rings the owner's doorbell. Nothing is inferred from
status, labels or screen text.

- **`notify_owner(question)`**: a tool, called when the worker needs the owner, **and** when it has answered a
  question the owner or coordinator asked (`answer ready: <topic>`): someone is waiting, so it rings. It runs `agent-alert emit --worker $HERDR_PANE_ID --kind question`
  and returns at once; it does not block the turn. The worker puts the same text in its reply
  and ends its turn. The question text stays in the transcript: the doorbell sends no text
  ([agent-alert SPEC](../../../../dot_local/share/agent-alert/SPEC.md)).
- **`ask_user_question` dialogs ring too**, on `tool_execution_start` of that tool (with a UI only). A worker
  must not call `notify_owner` for the same question; the worker rule says so.
- **A clean Pi exit reports `exited`** (`session_shutdown` with reason `quit`, in the interactive TUI only): the `/quit` command,
  SIGTERM, and SIGHUP, which is what closing the pane sends. Reload, new, resume and fork do not, and neither does a
  print-mode run (`pi -p`) or an RPC helper, though either may inherit the pane id. A second interactive Pi
  started inside the pane would count as the pane's agent: there is no way to tell it apart. A hard kill (`kill -9`, OOM) cannot be reported: nothing runs. Checked against a real
  interactive Pi on a pty for `/quit`, SIGHUP and SIGTERM.
- **No ring** for a plain finished turn, for progress, or for a Herdr `blocked` status.
- **No-op** (the tool is not even registered) when `PI_SUBAGENT_CHILD=1` (a subagent's questions go to its
  supervisor through `contact_supervisor`) or when `HERDR_PANE_ID` is unset (no pane to name).
- If `~/.local/share/agent-alert/core/agent-alert` is missing or not executable the tool returns an error saying
  so; the worker asks in its reply anyway.
- The emit runs detached and the tool does not wait for it, so "Doorbell dispatched" means it was started. A failure
  to start it, or a nonzero exit, is a line in the agent-alert operator log
  (`<time> notify-owner: …`, at the path the core uses: `AGENT_ALERT_LOG`, then `log_path` in the config, then
  `~/.local/state/agent-alert/agent-alert.log`). The exit path cannot report this: Pi exits right after starting the
  emit, so a late failure there leaves only the core's own log lines.

The ring itself is the doorbell sink configured for agent-alert (a Claude cloud session), with its
30 second throttle. This extension never talks to it directly.

## Profiles

Deploys wherever `.pi` does (personal and work; not Termux). The worker rule that tells a worker to use it
(`## Doorbell` in `literal_AGENTS.md.tmpl`) is personal-only, so on work the tool exists but is not asked for.

## Reload

Pi loads extensions at start. A running session gets the tool after `/reload` or a restart; until then it
has no `notify_owner`.

## The old Herdr hook is gone

An earlier Herdr plugin inferred rings from pane status, subagent labels, a marker line and transcripts. It was
removed once this extension had proven itself, so there are no double rings. A worker that forgets the tool is
silent; the coordinator's periodic check of its panes is the backstop.

## Tests

```sh
node --test dot_pi/private_agent/extensions/notify-owner/helpers.test.ts
```

A scripted core in a scratch HOME; no Pi, Herdr or doorbell. Source-only (`.chezmoiignore`).
