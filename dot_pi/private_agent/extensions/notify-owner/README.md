# notify-owner (Pi extension)

The explicit way a Pi worker rings the owner's doorbell. Nothing is inferred from
status, labels or screen text.

- **`notify_owner(question)`**: a tool. It runs `agent-alert emit --worker $HERDR_PANE_ID --kind question`
  and returns at once; it does not block the turn. The worker then states the question in its reply
  and ends its turn. The question text stays in the transcript: the doorbell sends no text
  ([agent-alert SPEC](../../../../dot_local/share/agent-alert/SPEC.md)).
- **`ask_user_question` dialogs ring too**, on `tool_execution_start` of that tool (with a UI only).
- **No ring** for a plain finished turn, for progress, or for a Herdr `blocked` status.
- **No-op** (the tool is not even registered) when `PI_SUBAGENT_CHILD=1` (a subagent's questions go to its
  supervisor through `contact_supervisor`) or when `HERDR_PANE_ID` is unset (no pane to name).
- If `~/.local/share/agent-alert/core/agent-alert` is missing the tool returns an error saying so; the
  worker asks in its reply anyway.

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
  emits `blocked` for it: one `question` ring at once plus a `blocked` that the doorbell holds and sends
  in one combined ring up to 30 seconds later. That pair goes away when the hook is removed.
- A worker that forgets the tool and ends with a real `AWAITING-OWNER: <question>` still rings through the hook.

## Tests

```sh
node --test dot_pi/private_agent/extensions/notify-owner/helpers.test.ts
```

A scripted core in a scratch HOME; no Pi, Herdr or doorbell. Source-only (`.chezmoiignore`).
