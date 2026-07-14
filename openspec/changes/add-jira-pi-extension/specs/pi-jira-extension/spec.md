<!-- authored: in-session -->
# Capability: pi-jira-extension

## ADDED Requirements

### Requirement: Extension Is Standalone From Opsx

THE pi-jira-extension SHALL NOT modify opsx gate checks, opsx-loop behavior,
opsx schema artifacts, or require a `jira_key` in change review.md.

#### Scenario: Opsx workflows unchanged
- **WHEN** the extension is installed and enabled
- **THEN** `opsx gate` and `/opsx-loop` SHALL behave identically to a tree
  without the extension for opsx-related checks

### Requirement: Own Mcp Client Transport

THE extension SHALL perform all Jira reads and writes through its own
mcp-remote stdio MCP client to the configured Jira MCP URL, without injecting
an agent turn solely to drive Jira tools.

#### Scenario: Command completes without agent turn
- **WHEN** the user runs a `/jira` verb that needs Jira I/O while the agent is idle
- **THEN** the extension SHALL call MCP tools via its own client and return
  results through the command UI path

#### Scenario: Transport failure surfaces warning
- **IF** the MCP client fails to connect or a tool call errors
- **THEN** THE extension SHALL notify via TUI warning and SHALL NOT crash the
  pi process or block unrelated turns

### Requirement: Session Only Ticket Binding

THE extension SHALL keep the bound Jira issue key in process memory only for
the current pi session.

#### Scenario: Bind and clear
- **WHEN** the user runs `/jira bind PROJ-123`
- **THEN** subsequent `/jira status` and `/jira show` SHALL report that key
- **WHEN** the user runs `/jira clear` or the pi process exits
- **THEN** the binding SHALL be absent

### Requirement: Master Toggle And Status

THE extension SHALL expose `/jira on|off|toggle|status` controlling whether
nudges run and reflecting bind/sync/nudge state.

#### Scenario: Status reports state
- **WHEN** the user runs `/jira status`
- **THEN** THE extension SHALL report enabled flag, bound key (or unbound),
  last sync age if any, and nudge interval

### Requirement: Search Bind Show Create Sync Transition Commands

THE extension SHALL expose `/jira search`, `/jira bind`, `/jira show`,
`/jira create`, `/jira sync`, and `/jira transition` operating on the bound
ticket (or creating/binding as specified), using raw MCP tool names
(`search_jira_issues`, `get_jira_issue`, `create_jira_issue`,
`add_jira_comment`, `get_jira_transitions`, `transition_jira_issue`).

#### Scenario: Search then bind
- **WHEN** the user runs `/jira search <text-or-jql>` and selects a result
- **THEN** THE extension SHALL set the session binding to that issue key

#### Scenario: Sync requires confirm
- **WHEN** the user runs `/jira sync` with a bound ticket
- **THEN** THE extension SHALL present a confirm step before posting a comment

#### Scenario: Sync refuses when unbound
- **IF** `/jira sync` or `/jira transition` is invoked with no bound key
- **THEN** THE extension SHALL warn and SHALL NOT call write MCP tools

### Requirement: On Demand Context Inject Only

THE extension SHALL inject Jira ticket context into the agent only when the
user runs `/jira context`, as a hidden `role:"custom"` message with
`customType` identifying jira context, and SHALL NOT register a
`before_agent_start` handler that auto-injects Jira context.

#### Scenario: Explicit context inject
- **WHEN** a ticket is bound and the user runs `/jira context`
- **THEN** THE extension SHALL fetch issue details and inject a hidden
  `<jira_context>` custom message for subsequent agent turns

#### Scenario: Context refuses when unbound
- **IF** `/jira context` is invoked with no bound key
- **THEN** THE extension SHALL warn and SHALL NOT inject

### Requirement: Configurable Ui Nudge Only

WHILE the extension is enabled, THE extension SHALL on every N `agent_end`
turns (configurable `nudgeEveryNTurns`, default 5) show a TUI notify reminding
the user about unbound or stale-sync state, and SHALL NOT mutate Jira or inject
context from the nudge path.

#### Scenario: Nudge when unbound
- **WHEN** the extension is on, N agent_end cycles elapse, and no ticket is bound
- **THEN** THE extension SHALL UI-notify a bind/search reminder

#### Scenario: Nudge disabled when off
- **WHILE** the extension is off
- **WHEN** agent_end fires
- **THEN** THE extension SHALL NOT emit Jira nudges

### Requirement: Work Profile Only Deploy

THE chezmoi source SHALL gate deployment of the jira extension directory so it
materializes under `~/.pi/agent/extensions/jira/` only when the chezmoi profile
is `axon-work-computer`.

#### Scenario: Personal profile skips deploy
- **WHEN** `chezmoi apply` runs with profile not equal to `axon-work-computer`
- **THEN** the jira extension path SHALL NOT be written to the target home

### Requirement: No Secrets In Logs Or Source

THE extension SHALL NOT log, print, or commit OAuth access/refresh tokens;
errors MAY mention `~/.mcp-auth` as the token cache location only.

#### Scenario: Failure message has no token material
- **IF** an MCP auth or tool failure occurs
- **THEN** any user-visible message SHALL omit token values and raw Authorization headers

### Requirement: Agent Independent Unit Tests

THE extension directory SHALL include agent-independent unit tests that exercise
command parsing, bind state, nudge cadence, and MCP client call shaping against
a mock transport, without requiring live network.

#### Scenario: Tests pass offline
- **WHEN** the extension test suite runs offline
- **THEN** all unit tests SHALL pass without contacting the Jira MCP URL
