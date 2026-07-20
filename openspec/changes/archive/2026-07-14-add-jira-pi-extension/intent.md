# Intent — add-jira-pi-extension

**Status:** FROZEN (explore concluded 2026-07-14)
**Recommended Scale:** M, `full_rigor: false`

Schema: opsx-superpowers. This intent.md is the frozen baseline; do not edit
without explicit human authorization.

## Intent

Ship a standalone pi extension (`dot_pi/agent/extensions/jira/`) that helps the
work profile keep Jira in the loop during coding sessions — without changing
opsx gate, opsx-loop, or any opsx workflow schema.

The extension owns: session-only ticket binding; slash commands to search /
create / bind / show / sync (comment) / transition; on-demand context injection
when the user asks; and configurable interval UI nudges so the user does not
forget to update the ticket. Jira I/O goes through the extension's **own**
mcp-remote MCP client (no agent turn, no `before_agent_start` auto-inject).
Deploy only on `axon-work-computer`.

Transport spike (2026-07-14): PASS — second `npx mcp-remote` stdio client
reused `~/.mcp-auth` OAuth cache, listed 21 tools, called `get_jira_projects`
successfully in ~2.6s with no browser prompt and no agent turn.

## Constraints

- **Standalone extension.** No coupling to opsx-loop, opsx gate, `review.md`
  jira_key, or change-artifact binding. Opsx workflows stay unchanged.
- **Code home:** `dot_pi/agent/extensions/jira/` (+ tests + README). Profile
  deploy gate (`.chezmoiignore` and/or settings/extension load) so
  non-`axon-work-computer` profiles do not receive the extension.
- **Transport:** extension spawns/reuses its own stdio client using the
  1Password-resolved `jira` transport in `~/.pi/agent/mcp.json`, calling raw
  MCP tool names (`get_jira_issue`, `search_jira_issues`, … — not the
  pi-prefixed `jira_*` aliases). Reuse existing `~/.mcp-auth` tokens; no second OAuth
  secret store; no Atlassian REST dual-stack in v1; never inject a turn solely
  to drive Jira MCP.
- **No `before_agent_start` hook.** Context enters the agent only via an
  explicit command (e.g. `/jira context`) that fetches the bound ticket and
  injects a hidden `role:"custom"` `<jira_context>` message (hindsight-style).
- **Session-only bind.** Bound key lives in memory for the pi process; cleared
  by `/jira clear` or process exit. No cwd sidecar, no change-artifact write.
- **Nudge = UI notify only.** When extension is on, every N `agent_end` turns
  (configurable; default non-zero) show a TUI notify if unbound or sync is
  stale — never mutates Jira, never injects context.
- **Writes are command-driven.** Comments, transitions, and create happen only
  when the user runs the matching `/jira` verb (confirm on create /
  transition / sync as appropriate). No silent `session_shutdown` auto-sync
  in v1.
- **Full v1 command surface:**
  - `/jira on|off|toggle|status` — master enable + state
  - `/jira bind <KEY>` / `/jira clear` / `/jira show` — identity
  - `/jira search <text|jql>` — find candidates; user picks → bind
  - `/jira create …` — confirm → create → bind
  - `/jira sync [note]` — post session/work summary comment on bound ticket
  - `/jira transition <name|id>` — discover allowed transitions, move
  - `/jira context` — on-demand hidden `<jira_context>` inject
- **Secrets (Constitution III):** never log access/refresh tokens, never commit
  OAuth material; reference `~/.mcp-auth` location only.
- **Domain carve-out:** amend `openspec/domain.md` Out-of-scope so
  stakeholder-facing tracker artifacts remain out-of-scope, while a
  work-profile developer-workstation Jira session helper is explicitly
  in-scope. Do not broaden to status pages / opsx-gated ticket binding.
- **Validation:** agent-independent unit tests under the extension dir (mock
  MCP client); live mcp-remote smoke stays manual/spike, not a required gate
  flake source.
- **Deploy reality:** `chezmoi apply` + pi restart required for running
  sessions to load the extension.

## Invariants honored

- Constitution I — extension lives at chezmoi source path
  `dot_pi/agent/extensions/jira/` and deploys via `chezmoi apply`.
- Constitution III — no secrets in source or logs; OAuth stays in
  `~/.mcp-auth` managed by mcp-remote.
- Constitution VIII — `openspec/` workspace not chezmoi-deployed.
- Domain (amended) — tracker *stakeholder* surfaces stay out-of-scope;
  this change is personal workstation tooling on the work profile only.
- Existing opsx-loop / opsx-gate / goal / hindsight / ntfy extensions remain
  behaviorally independent (same independence pattern as opsx-loop vs goal).

## Non-goals

- Opsx gate checks for `jira_key`, live ticket existence, or status allowlists.
- Auto-inject of Jira context every turn / on `before_agent_start`.
- Auto-post comments or transitions without an explicit `/jira` command.
- Persistent bind across pi restarts (cwd sidecar / branch parse / change
  artifact) — deferred; session-only for v1.
- Confluence tools (listed by the same MCP server) — Jira issue verbs only.
- Duplicate Atlassian REST client or a second API-token secret path.
- `opsx-flow` (does not exist in this repo) integration.
- Personal-profile deploy or always-on global Jira requirement.
- Changing the org Jira MCP server URL/auth beyond consuming the existing
  mcp-remote + `~/.mcp-auth` setup.
