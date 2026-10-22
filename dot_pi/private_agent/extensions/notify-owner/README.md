# notify-owner (Pi extension)

The explicit way a Pi worker rings the owner's doorbell. Nothing is inferred from
status, labels or screen text.

- **`notify_owner(kind, summary, ...)`**: a tool, called when someone should look at or answer something: the owner,
  or the coordinator that asked a question. It runs `agent-alert emit --worker $HERDR_PANE_ID --kind question`
  and returns at once; it does not block the turn. The worker puts the same text in its reply
  and ends its turn. The alert text stays in the transcript: the doorbell sends no text
  ([agent-alert SPEC](../../../../dot_local/share/agent-alert/SPEC.md)). The inbox event is the same for every kind;
  the typed arguments are not added to it (see "Typed alerts").
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

## Typed alerts

The call is checked by `validateAlert` in `helpers.ts` before anything rings. Unknown properties are rejected.

| Argument | Meaning |
|---|---|
| `kind` | `report`: finished work, asks nothing. `review`: something to LOOK AT, no answer awaited (needs `attachments`). `question`: an answer is needed to continue (two-way). `decision`: the owner decides, maybe a one-way door (needs `door`). `blocked`: cannot continue until the owner does or fixes something. |
| `summary` | Required. 3 to 600 characters after trimming, no control characters except newline. Replaces `question`. |
| `scope` | `step` (default) or `workstream`; only `report` may say `workstream`, meaning the whole assignment the pane exists for is finished. A merged PR, finished phase or passed review is `step`. |
| `attachments` | At most 8, each 1 to 500 characters: a file path (absolute, `~/`, or relative to the worker's cwd; no control characters, no `..`), an http(s) URL, or `PR owner/repo#N` / `PR #N`. Required (at least 1) for `review`; allowed for `report`, `question`, `decision`, `blocked`. |
| `options` | 2 to 6 entries, each 1 to 200 characters. Required for `question` and `decision`; allowed for `blocked`; not allowed for `report` and `review`. |
| `recommendation` | 1 to 200 characters: exactly one of `options` (after trimming), or `none`. Required for `question` and `decision`; not allowed otherwise. |
| `door` | `none`, `push`, `force_push`, `delete`, `deploy`, `merge`, `spend`, `other`. Required for `decision`; not allowed otherwise. |

A malformed call returns an error result (`isError`) with one problem per line and rings nothing. On success the text is the
usual "Doorbell dispatched..." plus `Recorded as kind=<kind>.`. The tool schema makes every field optional and allows extra
properties on purpose: Pi validates parameters against it before `execute`, and `validateAlert` then lists every problem at once.
The schema still checks property types (string, array of strings), so a wrong-typed value can be rejected by Pi before
`validateAlert` runs, with a shorter error; nothing rings either way.

**Legacy path.** A call with only `question` (a string) and none of the typed arguments is still accepted as an untyped alert,
with the old success text and no `Recorded as` suffix. `question` together with `kind` is an error. The coordinator counts legacy
calls as fallbacks; when that count reaches zero, `kind` becomes required.

**Where the typed arguments go.** Nowhere new: Pi records every tool call's arguments in the worker's own session log, and the
coordinator reads them from there. `validateAlert` and the coordinator's parser agree through one shared fixture file,
[alert-fixtures.json](./alert-fixtures.json) (valid calls with their normalized form; invalid calls with error substrings),
which both test suites run. Do not edit it in one repository only.

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

A scripted core in a scratch HOME; no Pi, Herdr or doorbell. The tests and `alert-fixtures.json` are source-only (`.chezmoiignore`).
