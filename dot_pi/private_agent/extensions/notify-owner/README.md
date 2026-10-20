# notify-owner (Pi extension)

The explicit way a Pi worker rings the owner's doorbell. Nothing is inferred from
status, labels or screen text.

- **`notify_owner(question)`**: a tool. It runs `agent-alert emit --worker $HERDR_PANE_ID --kind question`
  and returns at once; it does not block the turn. The worker then states the question in its reply
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

## Old hook, double rings

The Herdr marker hook ([agent-alert](../../../../dot_local/share/agent-alert/README.md#herdr-source-adapter)) is
still installed during the transition, so:

- Workers keep ending replies with `AWAITING-OWNER: none` (the rule says so), which silences the hook; the
  tool is the only ring for a question.
- An `ask_user_question` dialog also turns the pane `blocked` (the herdr-overview bridge), and the hook still
  emits `blocked` for it. That is two inbox events (`question`, `blocked`) for one dialog, in either order, and
  possibly two rings; the doorbell's 30 second throttle decides whether they are one combined ring or two. The
  `blocked` goes away when the hook is removed.
- The hook also still emits `exited` for a pane that closes, next to this extension's `exited`: a second `exited`
  event for the same pane. That goes away with the hook.
- A worker that forgets the tool and ends with a real `AWAITING-OWNER: <question>` still rings through the hook.

## Tests

```sh
node --test dot_pi/private_agent/extensions/notify-owner/helpers.test.ts
```

A scripted core in a scratch HOME; no Pi, Herdr or doorbell. Source-only (`.chezmoiignore`).
