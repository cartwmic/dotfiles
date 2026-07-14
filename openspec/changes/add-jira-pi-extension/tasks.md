<!-- authored: in-session -->
# Tasks — add-jira-pi-extension

## 1. Deploy gate + domain carve-out

- [ ] 1.1 Amend `.chezmoiignore` so `.pi/agent/extensions/jira/**` deploys only when `.profile == axon-work-computer`
  - intent: infra
  - files_allowed:
      - .chezmoiignore
  - allow_new_files: false
- [ ] 1.2 Amend `openspec/domain.md` Out-of-scope: carve in work-profile Jira session helper; keep stakeholder tracker surfaces out
  - intent: infra
  - files_allowed:
      - openspec/domain.md
  - allow_new_files: false

## 2. Extension scaffold + MCP client

- [ ] 2.1 Scaffold `dot_pi/agent/extensions/jira/` (index entry, config defaults, README stub, package/tsconfig as needed for bun test)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/**
  - allow_new_files: true
- [ ] 2.2 Implement lazy-connect mcp-remote StdioClientTransport client (D1) with D8 sanitize/error boundary; session close on `session_shutdown`
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/**
  - allow_new_files: true

## 3. Session state + commands

- [ ] 3.1 Session bind state machine (D5): bind/clear/show + unbound guards for sync/transition/context
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/**
  - allow_new_files: true
- [ ] 3.2 `/jira on|off|toggle|status` + search→select→bind + create (confirm) (D6)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/**
  - allow_new_files: true
- [ ] 3.3 `/jira sync` + `/jira transition` with confirm; `/jira context` one-shot latch inject (D3/D4)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/**
  - allow_new_files: true

## 4. Nudge hooks

- [ ] 4.1 `agent_end` nudge cadence gated by enabled (D7); never mutate Jira / never set context latch from nudge
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/**
  - allow_new_files: true

## 5. Tests + gate wiring

- [ ] 5.1 Unit tests with mock MCP: parsing, bind/clear, nudge cadence, call shaping; offline only (D9)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/**
  - allow_new_files: true
- [ ] 5.2 Add required `jira-extension-tests` entry to `openspec/opsx-gates.yaml`
  - intent: infra
  - files_allowed:
      - openspec/opsx-gates.yaml
  - allow_new_files: false
- [ ] 5.3 Finish README (commands, transport, profile deploy, no-secrets notes)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/jira/README.md
  - allow_new_files: true
