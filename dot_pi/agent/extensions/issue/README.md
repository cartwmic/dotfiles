# issue — pi extension (work profile)

Multi-provider issue tracking helper for pi. Supports **Jira** (via MCP client)
and **GitHub** (via `gh` CLI). **Not** coupled to opsx-loop / opsx gate.

## Deploy

Chezmoi deploys this directory only when `.profile == axon-work-computer`
(see `.chezmoiignore`). After `chezmoi apply`, restart pi.

## Commands

| Command | Effect |
|---------|--------|
| `/issue on\|off\|toggle\|status` | Master toggle (nudges) + state |
| `/issue bind <key>` | Auto-detect provider from key format, bind |
| `/issue bind jira PROJ-123` | Explicit Jira bind |
| `/issue bind github 123` | Explicit GitHub bind (current repo) |
| `/issue bind github owner/repo#123` | Explicit GitHub bind (specific repo) |
| `/issue clear` | Clear all binds |
| `/issue clear jira` | Clear Jira bind only |
| `/issue show` | Show all bound issues |
| `/issue show jira` | Show Jira bound issue |
| `/issue search <query>` | Search all available providers |
| `/issue search jira <jql-or-text>` | Search Jira |
| `/issue search github <query>` | Search GitHub |
| `/issue create [input]` | Generate a templated issue draft from the session plus optional input (prompts if multi-provider) |
| `/issue create jira [input]` | Generate a Jira issue (project from bound key, or specify `PROJ` prefix) |
| `/issue create github [input]` | Generate a GitHub issue in the current repo |
| `/issue sync` | **Checkpoint**: auto-summarize session progress since last sync → comment on all bound issues |
| `/issue sync <note>` | Comment `<note>` verbatim on all bound issues |
| `/issue sync jira [note]` | Sync bound Jira issue (checkpoint if no note) |
| `/issue sync github [note]` | Sync bound GitHub issue (checkpoint if no note) |
| `/issue transition [name\|id]` | Transition bound Jira issue |
| `/issue context` | Queue context inject for all bound issues |
| `/issue context jira` | Queue context inject for Jira |

## Issue creation

`/issue create` sends the current session transcript, the managed
`issue-template.md`, and any command input to the **current session model**. The
model generates both the title and a concise body containing **Summary** and
**Acceptance Criteria**. User input is optional and takes priority over older
session context.

Creation is fail-closed: it requires interactive UI and an active session model,
opens the generated title and body in an editor, and asks for final confirmation
before calling Jira or GitHub. Cancelling, an invalid draft, no active model, or
an unavailable template creates nothing.

For unbound Jira creation, the first input token remains the project key, for
example `/issue create jira PROJ focus on timeout handling`. When a Jira issue is
already bound, its project is reused and the full input is drafting guidance.

## Providers

### Jira

Backed by an MCP-remote stdio client using the resolved `jira` command and
arguments from `~/.pi/agent/mcp.json`. Run `apply_harness_config` after
changing MCP settings. Raw tool names (`get_jira_issue`, `search_jira_issues`,
etc.) — not `jira_*` aliases.

### GitHub

Backed by the `gh` CLI. No MCP config needed. Auth is handled by
`gh auth login`. Supports account switching via `gh auth switch`.

Issue references:
- `123` — issue in current git repository
- `owner/repo#123` — issue in any repository

## Multi-provider binds

You can bind to one Jira issue and one GitHub issue simultaneously. Commands
without an explicit provider target all bound issues (e.g., `/issue sync` comments
on both). Commands with an explicit provider target only that provider
(e.g., `/issue sync jira note`).

## Checkpoint summaries (`/issue sync` with no note)

Running `/issue sync` with no note generates a **checkpoint comment**: it reads
the bound issue's intent (title + description via `getIssue`) and the session
transcript since the last checkpoint, then asks the **current session model** to
summarize progress against that intent.

The span is anchored on a **session-entry cursor** (`ps.lastSyncEntryId`, the id
of the last entry the previous checkpoint covered) rather than a wall-clock
timestamp — this avoids equal-millisecond double-counting, clock-skew skips, and
missing-timestamp drops. The transcript includes everything in context that
evidences progress: user + assistant text, assistant **tool calls**, and **tool
results** (marked on error). Thinking blocks are excluded. There is no size
bound — the whole span is sent.

- **Model**: the current session model (`ctx.model`) is used **in-process** via
  the model registry — routing bridge/custom providers (cursor, claude-bridge,
  …) through their own `streamSimple`. There is no child `pi` process and no
  model to configure; if there is no active session model, `sync` (no note)
  warns and aborts. (A child `pi -p` was rejected: with extensions disabled it
  can't resolve bridge-provided models like `cursor/*`.)
- **Approval (required, fail-closed)**: the generated summary opens in an
  editable multi-line editor; edit and submit (or cancel) before it is posted,
  then a final confirm gate. Checkpoint **requires interactive UI** — in a
  headless/no-UI run (`pi -p`) it warns and posts nothing, so unvetted model
  output can never auto-post. Use `/issue sync <note>` for a headless comment.
- **Privacy**: the whole since-last-checkpoint transcript is sent to the session
  model's provider. Issue creation similarly sends the whole current session.
- Passing a note (`/issue sync <note>`) posts it verbatim (whitespace preserved).

## Config + runtime state

Layered, later wins: **defaults → `config.json` → `state.json`**.

- `config.json` — chezmoi-managed defaults (`enabled`, `nudgeEveryNTurns`).
- `state.json` — a sidecar beside `config.json` that is **not** chezmoi-managed
  and is created at runtime. Holds the runtime `on`/`off`/`toggle` state. It is
  never a chezmoi source file and the deployed dir is not `exact_`, so
  `chezmoi apply` never creates, tracks, or removes it — runtime edits survive
  `apply`. Mirrors the ntfy / hindsight sidecar idiom.

## Nudges

While ON, every `nudgeEveryNTurns` (default 5) `agent_end` events → UI notify
only. Never mutates issues; never auto-injects context.

## Secrets

Errors are sanitized (Bearer / access_token / refresh_token / Authorization).
Jira tokens stay in `~/.mcp-auth` only. The Jira MCP URL is resolved from
1Password into the generated `~/.pi/agent/mcp.json`; it is not stored in this
extension's chezmoi source.

## Tests

```bash
bun test dot_pi/agent/extensions/issue/
```
