---
name: herdr
description: "Control Herdr, a terminal multiplexer for coding agents. Use only when the user explicitly mentions Herdr or asks to use Herdr to inspect or control panes, tabs, workspaces, commands, or another agent. Do not use merely because a task could benefit from a background terminal, delegation, or parallel work. Requires HERDR_ENV=1."
---

# Herdr

Herdr organizes terminals into workspaces, tabs, and panes, recognizes coding agents running inside panes, and exposes the current session through the `herdr` CLI.

Before issuing any control command, verify that this agent is running inside a Herdr-managed pane:

```bash
test "${HERDR_ENV:-}" = 1
```

If the check fails, say that you are not running inside Herdr and stop. Do not inspect or control the focused Herdr session from outside Herdr.

When the check passes, the `herdr` binary in `PATH` talks to the current session. Use it to inspect neighboring work, create terminal layout, start agents and commands, read output, and wait for state changes.

## Learn the current CLI

The installed binary is the authority for command syntax. Start with:

```bash
herdr --help
```

Then print the relevant command group by running the group without a subcommand:

```bash
herdr agent
herdr pane
herdr workspace
herdr tab
herdr worktree
herdr terminal
herdr notification
herdr integration
herdr session
```

Do not run bare `herdr` for discovery; it launches or attaches the TUI. Do not probe a mutating nested command by omitting arguments. Commands such as `herdr workspace create` are valid with defaults and will execute.

Most control commands return JSON. Read identifiers and state from those responses instead of predicting them.

## Overview, names, recaps, and passage review

On the desktop profiles, the source-managed Herdr Overview plugin targets Herdr
**0.9.1 / protocol 22**. Termux is only an SSH client; it is not a Herdr plugin
host. The plugin starts with a compatible server start. Linking/installing it
does not run startup and applying dotfiles never restarts the owner's main
server. `overview.reconcile` loads/refreshes the linked plugin on a compatible
running server without opening a view; any server restart remains owner-controlled.

Open the temporary native map with `prefix+shift+o` or `herdr plugin action
invoke overview.open --plugin overview`. It is one shared 100% pane-canvas
popup, not a persistent tab. Another modal returns `ui_busy`; clients share
its geometry. Owner-tab deletion dismisses it natively; reopen ordinarily from
a surviving pane, without an anchor or resurrection. Startup/events/reconcile
never open it automatically.

The map keeps native workspace/tab/pane order, shared compact singleton rows
and grouped multi-pane tabs, adapting to narrow cards or wide workspace columns.
`j`/`k` and `[`/`]` select panes; Enter expands full tab/pane detail, `d` opens
the separate dated verified-UUID digest, `n` selects the next blocked pane and
`r` refreshes passively. Detail keys scroll; Esc backs out through disclosures
then dismisses, and `q` dismisses. `f` rechecks and focuses the exact live selected
terminal, closing only on success; vanished/conflicting targets cannot focus
an unrelated pane. The native map reads supplied prompts, dated latest-good
recaps and separate newer failures/digests without transcript scraping or
viewer generation. Missing content leaves native state/navigation available.

Automatic pane/tab names use verified stable Pi session names or honest native
subjects, never prompt/recap/digest bodies. One-pane tabs use their subject;
short two-subject tabs combine, otherwise use the first useful subject + N more.
Manual labels win; workspaces and Pi identity stay owner-controlled. A
manually published single recap with `--source-id` equal to the native pane ID
appears in that pane's detail after `herdr plugin action invoke
overview.reconcile --plugin overview`; reconcile while the source pane is live
to retain its terminal identity through a later `pane.move`. Failed-attempt
status is displayed, but a manual recap does not drive Pi automatic naming.
Preserve any manual pane or tab label. Only the
owner's explicit return-to-automatic action for that exact pane/tab allows
naming automation to resume. A tab containing unrelated agents should
represent both available tasks. Pi session names and identities are not
renamed. Non-Pi labels must not claim more than native metadata supports.

The portable `session-recap` command works without Pi or Herdr. It accepts
single stdin input or related group JSON and invokes the configured command
with the rendered prompt on stdin. Nonzero or blank output is failure and must
not replace the last good recap. Earlier dated records live outside Herdr.
Pi publishes a settled-session recap; a successful in-workspace Pi publication
starts/restarts a 30-second quiet interval. At expiry, the coordinator groups
the latest published recaps for panes currently in that native workspace,
including manually source-attributed non-Pi panes. A moved pane may join its
new workspace's group, but a pane no longer present in the original workspace
and a closed pane are omitted. After a successful workspace group, it can
publish the all-workspaces session recap from latest workspace records whose
workspace IDs are still live in the native snapshot. Failed recap attempts do not reset the
interval. The overview only reads/displays these records.

`passage-review` is also standalone. Use `new --file PATH` or pipe a supplied
snapshot to `new --title TITLE`, then `open REVIEW_ID` to add/revisit passage
comments. `export REVIEW_ID --note NOTE_ID` exports only selected pending notes
as quoted, attributed feedback. Export neither edits the source, archives the
notes, nor sends feedback to an agent. Its library and export work while Pi and
Herdr are stopped; on a phone, review saved whole replies or select recent pane
output inside the reviewer when direct SSH selection capture is unavailable.

## Understand layout, panes, and agents

Choose the primitive that matches the job:

- Workspace, tab, and pane topology organize terminal locations.
- Pane commands control raw terminals, shells, tests, servers, input, and output.
- Agent commands control the recognized coding agent currently occupying a pane.

A pane exists whether or not it contains an agent. `agent start` requires an existing available shell pane and never creates, splits, or moves layout. Use pane commands for ordinary processes. Use agent commands when Herdr must validate agent identity or interpret `idle`, `working`, `blocked`, `done`, and `unknown` lifecycle states.

Agent commands accept either a unique live agent name or the pane ID currently hosting that agent. They do not accept terminal IDs or bare agent-kind labels. Names must match `[a-z][a-z0-9_-]{0,31}` and be unique among live agents. A name follows the current pane occupant and is cleared when that agent exits, is released, or is replaced.

`idle` means the agent is ready for input and its tab has been seen in the focused Herdr UI. `done` is the same underlying idle state after unseen background work finishes. Focusing the tab or targeting the pane or agent with a focus command marks it seen. CLI reads do not mark it seen. `blocked` means Herdr recognized an approval or question UI. `unknown` means an agent is present but Herdr cannot classify it confidently; it does not prove completion.

## Use IDs and caller context

Public IDs are opaque stable handles:

- workspace: `w1`
- tab: `w1:t1`
- pane: `w1:p1`

Closed tab and pane IDs are not reused. A pane moved into another workspace receives a new workspace-qualified pane ID. After `pane move`, continue with `.result.move_result.pane.pane_id` or the live agent name. The old value is reported as `.result.move_result.previous_pane_id`; only the moved process's inherited caller context keeps resolving that old ID, so do not use it as a general agent target.

Herdr injects the caller's context into each managed pane:

```bash
printf '%s\n' "$HERDR_WORKSPACE_ID" "$HERDR_TAB_ID" "$HERDR_PANE_ID"
```

Prefer `--current` when a pane command should target the calling pane. Omitting a target may use the UI-focused pane, which can belong to the user or another client.

Discover live state with:

```bash
herdr workspace list
herdr tab list --workspace "$HERDR_WORKSPACE_ID"
herdr pane current --current
herdr pane list --workspace "$HERDR_WORKSPACE_ID"
herdr agent list
```

Creation responses expose the IDs to use next. `workspace create` returns `.result.workspace`, `.result.tab`, and `.result.root_pane`. `tab create` returns `.result.tab` and `.result.root_pane`. `pane split` returns the new pane as `.result.pane`.

## Start and coordinate an agent

Default to a sibling pane in the current tab and the current working directory. Do not create a workspace, tab, worktree, or different cwd unless the user explicitly requests that topology or location.

Honor a direction requested by the user. Otherwise inspect the caller pane:

```bash
herdr pane layout --pane "$HERDR_PANE_ID"
```

Split a wide pane to the right and a narrow or tall pane down. Avoid repeated same-direction splits that create unusably narrow columns or short rows. Keep the user's focus in the calling pane and explicitly preserve the caller's working directory:

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
```

Replace `right` with `down` when appropriate. Read the new pane ID from `.result.pane.pane_id`.

An available shell pane must be at its interactive prompt, with the shell itself in the foreground and no foreground command, editor, or agent running. Start a supported agent in that pane with a useful unique name:

```bash
herdr agent start reviewer --kind codex --pane <returned-pane-id>
```

Use the kind requested by the user. Run `herdr agent` to inspect the installed kind list and options. Pass native agent arguments only after `--`:

```bash
herdr agent start reviewer --kind codex --pane <returned-pane-id> -- <agent-args...>
```

`agent start` returns only after Herdr detects the expected agent in the same pane and considers it ready for interactive input. It defaults to a 30-second startup timeout.

Submit work through the agent surface:

```bash
herdr agent prompt reviewer "Review the current diff and report only actionable findings." --wait --timeout 120000
```

`agent prompt` atomically submits text and encoded Enter while honoring the pane's live bracketed-paste mode. For normal agent work, `--wait` is enough: it waits for the first settled `idle`, `done`, or `blocked` state. Do not repeat those defaults with `--until`.

A prompt sent from a non-working state must produce an observed lifecycle change within five seconds. Otherwise Herdr returns `agent_prompt_stalled` instead of waiting indefinitely. This wait tracks lifecycle state, not an individual turn; if the agent is already working, completion of the active turn may satisfy it.

Use `--until` only for a state-specific workflow, such as waiting for an already-running agent to request input:

```bash
herdr agent wait reviewer --until blocked --timeout 120000
```

Without `--until`, standalone `agent wait` uses the same settled-state defaults as `agent prompt --wait`.

Use logical keys for interactive agent UI controls:

```bash
herdr agent send-keys reviewer esc
herdr agent send-keys reviewer ctrl+c
```

Herdr validates all keys before writing any bytes. Read the result through the resolved agent:

```bash
herdr agent get reviewer
herdr agent read reviewer --source recent-unwrapped --lines 120
```

If a wait fails or returns `blocked`, inspect `agent get` and `agent read` before deciding what input to send. Use the pane surface only when raw terminal control is intentional.

## Run an ordinary command in another pane

Create a sibling pane with the same geometry rule, preserve the caller's working directory, and keep user focus unchanged:

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
```

Read the new pane ID from `.result.pane.pane_id`, then run and inspect the command:

```bash
herdr pane run <returned-pane-id> "just test"
herdr pane wait-output <returned-pane-id> --match "test result" --timeout 120000
herdr pane read <returned-pane-id> --source recent-unwrapped --lines 120
```

`pane run` atomically sends command text and Enter. `pane wait-output` searches the selected snapshot immediately, so output that already exists can match. Use `--match <text>` for a literal substring or `--regex <pattern>` for a Rust regular expression. Omitting `--timeout` allows an indefinite wait.

Use the read source that matches the task:

- `visible`: the currently rendered viewport.
- `recent`: recent rendered output, including soft wraps.
- `recent-unwrapped`: recent output with soft wraps joined; prefer it for logs and transcripts.
- `detection`: the plain-text bottom-buffer snapshot used for agent detection.

Use `--format ansi` when colors and terminal styling are evidence. Otherwise use text.

Full-screen agents may use the terminal alternate screen. Rows that disappear from that screen do not enter Herdr's host scrollback, so `recent`, `recent-unwrapped`, and larger `--lines` values cannot recover them. Enlarge the pane, request concise output, use the agent's transcript controls, or scroll inside the agent and read `--source visible`.

## Safety and coordination rules

- Use `--no-focus` for background work unless the user asked to switch context.
- Use `--current`, an explicit pane ID, or a unique agent name. Do not rely on another client's focused pane.
- Parse IDs from JSON responses. Do not derive them from sidebar order or examples.
- Do not close workspaces, tabs, panes, or sessions you did not create unless the user explicitly asked.
- Never run `herdr server stop` from an active session unless the user explicitly intends to stop the server and its pane processes.
- Never kill the main Herdr process. Use named test sessions for experiments that need an isolated server.
- CLI server errors are JSON on stderr with exit status 1. CLI syntax errors exit with status 2.

Herdr Overview uses bordered, padded, word-wrapped cards in native workspace
order, with two singleton columns and separate multi-pane groups. `M` marks
manual names; headings show counts; clipped collapsed titles end in an ellipsis.
`d` enters the dated digest (idempotent there); Esc restores the prior recap
passage and `q` dismisses immediately. The card floor is actual popup width 32,
not outer width: outer 40/48/120/180 yield 38/46/92/152; outer32 yields30 and
may clip. Simultaneously attached clients share one PTY geometry; a wide peer
can clip the narrow peer. Use one attached client for readable geometry.
