<!-- authored: in-session -->
# Design — add-jira-pi-extension

## Context

Frozen intent: standalone work-profile Jira helper. Pi `ExtensionAPI` has no
`callMcp` — agent MCP session is unreachable from extension handlers. Spike
2026-07-14 proved a second mcp-remote stdio client reuses `~/.mcp-auth` and
calls raw tools (`get_jira_projects`, …) without an agent turn.

Constitution I (chezmoi SoT), III (no secrets), VIII (`openspec/` not deployed).
Domain Out-of-scope currently bans tracker integrations — carve-out required.

## Goals / Non-Goals

**Goals:**
- Session bind + full v1 `/jira` verbs via own MCP client
- On-demand context inject; interval UI nudges only
- Work-profile-only deploy; unit tests with mock MCP

**Non-Goals:**
- Opsx gate/loop coupling; auto-inject; auto-sync; Confluence; REST dual-stack;
  persistent bind; personal-profile deploy

## Decisions

### D1: Extension-owned mcp-remote stdio client

**Choice:** Lazy-connect StdioClientTransport → `npx -y mcp-remote <JIRA_URL>`;
keep-alive for session; close on `session_shutdown`. Call raw tool names.

**Alternatives considered:**
- **Agent-turn inject:** no new auth; burns turn; model can ignore — rejected
  (intent: no turn for Jira I/O).
- **Atlassian REST + API token:** deterministic; second secret stack — rejected
  for v1 (intent: reuse mcp-auth).
- **Pi ExtensionAPI callTool:** does not exist.

**Rationale:** Spike PASS; matches intent transport constraint.

**4-point test:** multiple approaches Y; lasting Y; disagreement Y; constrains
future (auth path) Y → ADR candidate Y (promote at archive if dogfood holds).

### D2: `.chezmoiignore` profile gate for deploy

**Choice:** Ignore `.pi/agent/extensions/jira/**` unless
`.profile == axon-work-computer`. Source remains in git for all profiles.

**Alternatives considered:**
- **Empty stub on personal:** noise.
- **settings.json package toggle:** extensions here are filesystem-loaded, not
  packages list.

**Rationale:** Matches existing profile patterns (hindsight bank, auth sync).

**4-point test:** Y/Y/N/Y → ADR candidate N.

### D3: Hidden custom message for `/jira context`

**Choice:** Mirror hindsight: return/inject `{ customType: "jira_context",
content: "<jira_context>…", display: false }` from the command path (append
via available ExtensionAPI message injection used by hindsight-style custom
entries — prefer the same `before_agent_start` *return shape* is NOT used;
use `pi.sendMessage` / documented custom-entry inject if command handlers
expose it, else queue one-shot inject on next `before_agent_start` only when
a command-set latch is true).

**Clarified implementation rule:** No standing auto-inject. A
`pendingContextInject` latch set by `/jira context` may be consumed exactly
once on the next `before_agent_start` to deliver the hidden message, then
cleared. That is command-triggered, not auto.

**Alternatives considered:**
- **sendUserMessage follow-up:** visible + burns turn — rejected.
- **UI-only print:** agent never sees ticket — rejected (user chose inject).

**Rationale:** Matches locked explore choice (hidden msg) without perpetual
auto-inject.

**4-point test:** Y/Y/Y/Y → ADR candidate Y.

### D4: Default nudgeEveryNTurns = 5; writes confirm-gated

**Choice:** Config default 5; sync/create/transition confirm before MCP write.

**Alternatives considered:** Nudge 0 by default; silent writes — rejected.

**4-point test:** Y/N/N/N → ADR candidate N.

### D5: In-memory session bind + unbound guards

**Choice:** `boundKey: string | null` in extension closure memory. `/jira bind`
sets it; `/jira clear` and process exit clear it (no disk). `/jira sync`,
`/jira transition`, and `/jira context` refuse with TUI warning and skip MCP
writes/inject when `boundKey` is null. `/jira show` fetches `get_jira_issue`
for the bound key (or warns if unbound).

**Alternatives considered:** cwd sidecar / change-artifact — rejected (intent:
session-only).

**4-point test:** Y/Y/N/Y → ADR candidate N.

### D6: Command surface + search→bind selection

**Choice:** Single `/jira` command with subcommands:
`on|off|toggle|status|bind|clear|show|search|create|sync|transition|context`.
`/jira search` calls `search_jira_issues` (text wrapped as JQL
`summary ~ "…" OR description ~ "…"` when not already JQL-like); presents
results via `ui` select; selection sets `boundKey`. `/jira create` prompts
project (from `get_jira_projects`) + issue type (from `get_single_project`) +
summary, confirms, calls `create_jira_issue`, then binds the new key.
`/jira status` reports: enabled, boundKey|unbound, lastSyncAt age|never,
nudgeEveryNTurns, pendingContextInject latch bool.

**Alternatives considered:** separate slash commands per verb — rejected
(matches `/hindsight` / `/ntfy` single-command pattern).

**4-point test:** Y/N/N/N → ADR candidate N.

### D7: Nudge on agent_end cadence gated by enabled

**Choice:** While `enabled===true`, count `agent_end` events; every
`nudgeEveryNTurns` (default 5) emit `ui.notify` only — unbound reminder or
"bound KEY, last sync … — /jira sync | /jira context". Never call MCP write
tools and never set `pendingContextInject` from the nudge path. While
`enabled===false`, skip nudge entirely (commands that mutate Jira still work
so the user can manage manually when nudges are off — status reflects both).

**Clarification:** Master off disables nudges only, not the command surface
(matches hindsight/ntfy: toggle controls the automatic hook behavior).

**Alternatives considered:** Off disables all `/jira` verbs — rejected
(manual manage-as-fit requires commands always available when extension
loaded).

**4-point test:** Y/Y/N/N → ADR candidate N.

### D8: Transport error boundary + secret-safe messages

**Choice:** Every MCP connect/callTool path wrapped try/catch. On failure:
`ui.notify(..., "warning")` with sanitized message (strip bearer tokens,
`access_token`/`refresh_token` substrings, Authorization headers); never
rethrow into the agent turn; never log raw tokens. OAuth expiry is one case
of this general boundary (user re-auths via existing mcp-remote flow).

**Alternatives considered:** Fail closed / crash extension — rejected.

**4-point test:** Y/Y/N/Y → ADR candidate N.

### D9: Offline unit tests with mock MCP

**Choice:** Colocate `*.test.ts` under `dot_pi/agent/extensions/jira/` run via
`bun test` (same pattern as opsx-loop / ntfy). Tests cover: command arg
parsing, bind/clear state machine, nudge cadence + enabled gate, MCP client
call shaping (tool name + args) against an in-memory mock transport. Suite
MUST NOT open network sockets to the Jira MCP URL (mock only). Wire a
required gate entry `jira-extension-tests` running
`bun test dot_pi/agent/extensions/jira/`.

**Alternatives considered:** Live smoke as required gate — rejected (flake;
intent: manual/spike only).

**4-point test:** Y/N/N/N → ADR candidate N.

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | OAuth/connect/tool failure mid-session | Medium | Medium | D8: warn + sanitize; never crash; never block unrelated turns |
| R2 | Second mcp-remote process cost | Low | Low | Lazy connect; single shared client |
| R3 | Tool schema drift vs MCP server | Medium | Medium | Thin wrappers; tests mock shapes; README notes raw names |
| R4 | One-shot before_agent_start latch misread as auto-inject | Low | High | Spec + code comments; latch cleared after one consume; no inject when latch false |

## Migration Plan

1. Land extension + `.chezmoiignore` + domain.md amend.
2. `chezmoi apply` on axon-work-computer; restart pi.
3. Manual smoke: `/jira search`, bind, show, context, sync (optional).
4. Rollback: remove extension dir / revert ignore rule; `chezmoi apply`.

## Open Questions

- None blocking apply — Q1–Q4 resolved in proposal.md.
