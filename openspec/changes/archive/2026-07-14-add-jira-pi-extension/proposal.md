<!-- authored: in-session -->
# Proposal — add-jira-pi-extension

## Why

Work-profile coding sessions forget Jira: no ticket bind, stale status, missing
session comments. Soft opsx prompts die under loop autonomy; hard opsx gate
coupling was rejected. Need a standalone pi extension that nudges + manages
Jira via its own MCP client (Constitution I deploy path; domain carve-out for
work-profile workstation helper only).

## What Changes

- New pi extension `dot_pi/agent/extensions/jira/` — commands, session bind,
  own mcp-remote client, UI nudges, on-demand `<jira_context>` inject.
- `.chezmoiignore` profile gate: deploy only when `.profile == axon-work-computer`.
- Amend `openspec/domain.md` Out-of-scope: carve in work-profile Jira session
  helper; keep stakeholder tracker / status-page surfaces out.
- Unit tests (mock MCP) + README; no opsx gate / opsx-loop / schema changes.

## Capabilities

### New Capabilities
- `pi-jira-extension`: Standalone work-profile pi Jira session helper
  (bind/search/create/sync/transition/context + configurable UI nudge).

### Modified Capabilities
- (none — domain.md prose amend is project doc, not a capability delta)

## Impact

**Affected files (expected):**
- `dot_pi/agent/extensions/jira/` (index, client, config, commands, tests, README)
- `.chezmoiignore` (work-profile-only deploy)
- `openspec/domain.md` (carve-out)
- `openspec/opsx-gates.yaml` only if a new unit-test gate entry is added for
  the extension (prefer extension-local `bun test` / `node --test` wired into
  existing gate pattern)

**Dependencies:** `@modelcontextprotocol/sdk` (stdio client; resolve via
pi-mcp-adapter or explicit dep), `npx mcp-remote`, existing `~/.mcp-auth`.

**Systems:** Atlassian Jira MCP transport resolved from 1Password into the
generated Pi MCP configuration — consume only.

## Open Questions (plain-M clarify-in-proposal)

### Q1: Default `nudgeEveryNTurns`?
- **A (chosen):** `5` — frequent enough to catch forgetfulness, not spammy.
- B: `10` — quieter.
- **Resolution:** A. Configurable in config.json; `/jira status` shows value.

### Q2: Sync summary source when user omits `[note]`?
- **A (chosen):** Bound-ticket key + cwd basename + last N user/assistant
  turn excerpts (capped chars) + optional note — never secrets.
- B: Require explicit note always.
- **Resolution:** A with confirm dialog before post.

### Q3: Create defaults (project key / issue type)?
- **A (chosen):** Prompt via `ui` select from `get_jira_projects` + issue types
  from `get_single_project`; no hardcoded project in source.
- B: Config default project key.
- **Resolution:** A for v1; optional config default deferred (non-goal).

### Q4: MCP client lifecycle?
- **A (chosen):** Lazy connect on first Jira I/O; keep-alive for session;
  close on `session_shutdown`.
- B: Connect at extension load.
- **Resolution:** A — matches spike + avoids cold-start OAuth noise when unused.

## Deterministic analyze (plain-M, inline)

| Check | Result |
|---|---|
| 1 Tiling | New capability `pi-jira-extension` covers intent verbs; domain amend separate |
| 2 Traceability | Each intent constraint maps to ≥1 ADDED requirement (see specs) |
| 7 EARS lint | Event/state/unwanted patterns used; IF…THEN for errors |

No blockers. Outstanding risk: mcp-remote token expiry mid-session → surface
UI warning, never crash turn (R1 in design).

## Assumptions recorded

- Raw MCP tool names without `jira_` prefix (spike-confirmed).
- Extension auto-loads from `~/.pi/agent/extensions/` like siblings; no
  settings.json packages entry required.
- Profile gate via `.chezmoiignore` is sufficient (source stays in git).
