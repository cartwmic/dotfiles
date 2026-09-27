# inspect-prompt

This extension provides two local editor snapshots:

- `/inspect-prompt` opens the assembled system prompt.
- `/inspect-session` or **Ctrl+Alt+E** opens the current conversation.

## System prompt snapshot

`/inspect-prompt` opens a **snapshot** of Pi's currently assembled system
prompt (`ctx.getSystemPrompt()` at invoke time) in the same external editor Pi
uses for the user-query box (`settings.externalEditor`, else `$VISUAL`, else
`$EDITOR`, else `nano` / `notepad`). The document includes agents files,
appendments, skills, and other prompt contributions already loaded into that
assembly. It is **not** the conversation transcript and **not** the raw
provider HTTP payload after per-request rewrites.

Edits in the editor are discarded. Closing the editor returns to the Pi TUI.
The command does not submit a user query or start an agent turn. If there is no
interactive UI (`pi --print` / json), it returns without waiting on an editor;
if the agent is still running, it notifies and returns without opening the
system-prompt editor.

## Conversation snapshot

Use `/inspect-session` or **Ctrl+Alt+E** to open the active conversation in
Pi's configured external editor (`externalEditor`, then `$VISUAL`, `$EDITOR`,
then Pi's platform default). The command and shortcut work while the agent is
streaming. The snapshot includes finalized messages on the current session
branch, assistant/tool progress already emitted to Pi, and user `!` / `!!`
Bash output currently displayed in chat or pending. Completed chat components are
reconciled against saved branch results by command and output occurrence. Running
components are kept even when an older identical command remains in history.
Completed pending components are reconciled only against matching Bash results
appended after the latest user message. That includes the interval after agent
settlement when Pi has flushed a deferred result into the branch but has not yet
moved its UI component out of the pending area; an older identical result before
the current turn will not suppress still-deferred output. This avoids duplicates
without dropping a new repeated command after compaction.

The snapshot excludes system instructions and abandoned branches, does not
include tool/system-prompt internals, and stays static while Pi continues
working. Pi pauses its fullscreen TUI while the editor is open and resumes the
same session on exit. The editor file is private and temporary; edits are
removed and never applied to the conversation. The live-component reader is
verified against Pi 0.87.1's fullscreen layout and fails closed on an
unrecognized layout rather than silently omitting Bash output.

The implementation is source-managed in this chezmoi tree. Do not hand-edit
generated `~/.pi` files, apply this change to the live home, or restart/handoff
the running Herdr server without separate rollout approval. Use the repository
procedure for a targeted chezmoi dry-run before any separately approved apply.

## Interactive scenario proof

Run the outer-path scenario from the chezmoi source checkout:

```sh
python3 dot_pi/private_agent/extensions/inspect-prompt/scenario.py
```

It starts a private named Herdr server and PTY-attached client, launches Pi in a
Herdr pane with a scripted faux provider and configured dummy editor, and
writes synthetic editor receipts and screen captures to a private temporary
directory. Pass `--artifact-dir PATH` to retain them at a chosen location. The
Ctrl+Alt+E press/release bytes go through the attached client PTY (not the pane
input API); before each shortcut the scenario selects the Pi pane through that
client and verifies focus at editor open and return. It proves bottom-follow
independently, then scrolls up during active assistant text and active tool
updates, requiring further streamed progress while the same passage remains
nearby and the latest-message affordance stays visible. It captures partial
assistant/tool output plus idle, running, deferred-complete, and
post-settlement `!` output.
A fixture-only TUI probe confirms the completed pending-dock component and
persisted Bash result coexist after agent settlement without sending another
normal user prompt; the actual shortcut receipt must contain its command and
unique output exactly once. It also
checks a repeated `!` command after real Pi compaction: that receipt asserts
both repeated outputs and the finalized `scenario_stream_tool` assistant call
exactly once, then checks branch exclusion and a subsequent turn in the same Pi
process. It fails closed if the client route or any snapshot assertion misses;
the outcome receipt lists receipts, transcript, and cleanup result. It never
contacts a live model or controls the default Herdr session.

## Herdr scrollback

The Pi-specific shortcut does not remap Herdr. Herdr's source config still
assigns `prefix+e` for non-Pi pane scrollback; the isolated host result below
distinguishes that config from verified key routing.

The isolated non-Pi host check is reproducible with:

```sh
python3 dot_pi/private_agent/extensions/inspect-prompt/herdr-scenario.py
```

It creates a private named Herdr 0.9.1 session, attaches a real client to a
PTY, and checks next/previous-tab and left/right-pane navigation. Its dummy
editor expects `T4_NONPI_SCROLLBACK_FIRST`, then
`T4_NONPI_SCROLLBACK_MIDDLE`, then `T4_NONPI_SCROLLBACK_LAST` exactly once
in the selected non-Pi pane's scrollback; markers from another pane and tab
must be absent. It stops and deletes only its own named session and removes
its temporary root.

Host result (Herdr 0.9.1 / protocol 22): **PASS**. The real PTY-attached client
used `prefix+n` and `prefix+p` to navigate tabs, then `prefix+l` and
`prefix+h` to move between panes. From the selected non-Pi pane, `prefix+e`
launched the configured dummy editor through the client key path (not the API
substitute) exactly once. The editor contained
`T4_NONPI_SCROLLBACK_FIRST`, `T4_NONPI_SCROLLBACK_MIDDLE`, and
`T4_NONPI_SCROLLBACK_LAST` exactly once and in that order; markers from the
other pane and tab were absent. Herdr returned to the same pane, navigation
still worked, and Herdr removed its temporary scrollback file.

The test detached its client, stopped and deleted only its private named
session, removed its private temporary root, and did not touch the owner's
server. Herdr bindings remain unchanged. This non-Pi `prefix+e` path opens the
selected pane's Herdr scrollback; Pi's **Ctrl+Alt+E** alternative above opens a
static snapshot of the Pi conversation instead.
