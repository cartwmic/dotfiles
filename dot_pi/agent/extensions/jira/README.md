# jira — pi extension (work profile)

Standalone Jira session helper for pi. **Not** coupled to opsx-loop / opsx gate.

## Deploy

Chezmoi deploys this directory only when `.profile == axon-work-computer`
(see `.chezmoiignore`). After `chezmoi apply`, restart pi.

## Commands

| Command | Effect |
|---------|--------|
| `/jira on\|off\|toggle\|status` | Master toggle (nudges) + state |
| `/jira bind KEY` / `clear` / `show` | Session-only binding |
| `/jira search <text\|jql>` | Search → select → bind |
| `/jira create [summary]` | Confirm → create → bind |
| `/jira sync [note]` | Confirm → comment on bound issue |
| `/jira transition [name\|id]` | Confirm → workflow transition |
| `/jira context` | Queue one-shot hidden `<jira_context>` inject |

## Transport

Own stdio MCP client using the resolved `jira` command and arguments from
`~/.pi/agent/mcp.json`. Run `apply_harness_config` after changing MCP settings.
The client reuses `~/.mcp-auth` OAuth cache. Raw tool names
(`get_jira_issue`, …) — not `jira_*` aliases. Never injects an agent turn
solely for Jira I/O.

## Nudges

While ON, every `nudgeEveryNTurns` (default 5) `agent_end` events → UI notify
only. Never mutates Jira; never auto-injects context.

## Secrets

Errors are sanitized (Bearer / access_token / refresh_token / Authorization).
Tokens stay in `~/.mcp-auth` only. The Jira MCP URL is resolved from
1Password into the generated `~/.pi/agent/mcp.json`; it is not stored in this
extension's chezmoi source.

## Tests

```bash
bun test dot_pi/agent/extensions/jira/
```
