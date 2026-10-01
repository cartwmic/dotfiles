# Standing reminder

One exact multiline reminder belongs to the current Pi session. Permanent rules
belong in agent instructions. The reminder is advisory, not enforcement.

## Usage

- `/reminder` opens Pi's external editor in the TUI, including during streaming.
  A successful changed close saves the exact final contents. Intermediate writes
  are drafts; failed/cancelled closes preserve the previous value. An unchanged
  close is view-only. Empty contents clear the reminder.
- `/reminder-clear` clears without starting a request.
- The compact widget previews the current value. A saved edit or clear remains
  pending for the **next normal request**, not just the next operator message.

No control forces a turn, aborts a tool, or restarts a response. A request already
in flight cannot be changed. If work ends before another request, the saved
change waits. Editor terminal handoff/redraw behavior remains unchanged.

## Delivery

Known interactive/RPC operator messages, including queued steering, each receive
one hidden projection with the latest exact wording. Extension-origin messages
are not operator input. Missing/unknown provenance warns and omits that trigger;
text is never used to infer origin. Equal timestamps are paired by occurrence.
The `standing-reminder-origin` patch is required for operator provenance.

A selected completed tool result queues a refresh, including native nested
completions and error results. The refresh is projected after the complete batch
at the next ordinary context assembly, not when a questionnaire tab changes.
A changed save independently queues the latest value at that same boundary.
Multiple saves/results coalesce; fresh operator delivery satisfies coincident
causes while preserving one projection per distinct operator input.

Edits retire superseded owned projections at the next normal request. Clears
remove them without a model-visible clear instruction. Unchanged ordinary tool
continuations reuse the same in-memory projection objects and canonical anchors;
selected refreshes may append a fresh projection. No stable system prefix or
ordinary conversation content is rewritten. Idle cache warming is excluded.
Compaction summaries bypass Pi's normal context hook; compaction drops anchors
without consuming pending saves or independently refreshing the reminder.

## Configuration

`create_config.json` seeds `~/.pi/agent/extensions/standing-reminder/config.json`
once; subsequent local edits are preserved by chezmoi. Defaults:

```json
{"triggers":["tool-result:ask_user_question"]}
```

Add one exact `tool-result:NAME` or `message:CUSTOM_TYPE` entry to select another
tool completion or model-visible custom message. No wildcard, UI-notification,
usage, or default subagent trigger exists. Custom messages are counted by type,
timestamp and occurrence, with existing history baselined at startup, tree
navigation and compaction using `SessionManager.buildSessionContext().messages`,
not raw branch entries (`custom_message` is normalized to role `custom` by Pi).
Historical replay is not a fresh handoff.

Missing config uses the default. `{"triggers":[]}` disables event refreshes,
not operator/edit delivery. Invalid JSON, shape or selectors warn and disable
only event refreshes. Config is loaded at session start; use `/reload` after
changing it. It does not block ordinary work or reminder editing.

## Storage and lifecycle

Only current reminder/pending state is saved in the private sidecar
`standing-reminder/<session-id>.json` under Pi's session directory (0600 file,
0700 directory). A non-text restore marker may be saved in the session. There
are no saved reminder messages, reminder history, or durable trigger backlogs.
Treat sidecar plaintext as private.

Reload/resume preserve the current value and pending save/clear. `/tree` keeps
that value and rebaselines event admission. `/fork` and `/clone` copy current
state into independent sessions, not runtime causes. Unrelated/child sessions
start empty. Missing marked or unreadable state warns and proceeds without stale
text; a successful `/reminder` save replaces unavailable state. Noninteractive
modes deliver but do not open an editor; warnings use stderr or RPC UI routing.

## Setup and validation

Personal and axon-work-computer profiles deploy the extension and origin patch
together; Termux excludes Pi. Preview source and obtain separate approval before
live apply. Do not hand-edit installed Pi.

```sh
node --test dot_pi/private_agent/extensions/standing-reminder/index.test.ts
```

Focused tests are internal regression evidence only. The outer proof uses
isolated Pi **0.99.2**, a scripted provider and the actual question UI, including
builtin codemode nested/error paths. A separate matched live comparison uses
`openai-codex/gpt-6.1-sol`. One designated proof owner runs the complete matrix
on the stable tree; live requests require explicit approval and a finite cap.
The cache driver reserves native context/output capacity and stages private
configuration. The backend rejects the artificial short-token override; no
enforced 256-token ceiling is claimed.
See `tests/standing-reminder/README.md` for commands, rate-dependent
reservation and the distinction between deterministic live fixtures and actual
question/editor UI proof. No live apply or Git commit is included. Genuine
provider input/cacheRead counters are required; prompt shape alone is not cache
proof. No universal cache hit guarantee applies, especially after edits,
refreshes or compaction.
