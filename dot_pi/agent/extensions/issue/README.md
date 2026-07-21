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
| `/issue create [summary]` | Create issue (prompts if multi-provider) |
| `/issue create jira [summary]` | Create Jira issue (project from bound key, or specify `PROJ` prefix) |
| `/issue create github [summary]` | Create GitHub issue (current repo) |
| `/issue sync [note]` | Comment on all bound issues |
| `/issue sync jira [note]` | Comment on bound Jira issue |
| `/issue sync github [note]` | Comment on bound GitHub issue |
| `/issue transition [name\|id]` | Transition bound Jira issue |
| `/issue context` | Queue context inject for all bound issues |
| `/issue context jira` | Queue context inject for Jira |

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
