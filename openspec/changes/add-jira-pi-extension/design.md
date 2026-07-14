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

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | OAuth token expiry mid-session | Medium | Medium | Surface warning; user re-auth via existing mcp-remote flow; never crash |
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
