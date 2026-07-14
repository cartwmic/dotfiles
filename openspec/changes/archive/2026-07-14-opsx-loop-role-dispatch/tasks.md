<!-- authored: in-session -->
# Tasks — opsx-loop-role-dispatch

## 1. Armed-loop tool mute + opsx_dispatch surface

- [x] 1.1 Register `opsx_dispatch` tool on the opsx-loop extension; on arm snapshot active tools, drop `subagent`, activate `opsx_dispatch`; on clear/stop restore snapshot exactly
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [x] 1.2 Implement `opsx_dispatch` execute: refuse when loop not armed; resolve role via `opsx models` / `OPSX_*`; unset = actionable refuse (no session fallback); configured role forces model (ignore caller `model`); `review` auto fan-out one spawn per list entry in order
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [x] 1.3 Wire spawn through pi-subagents programmatic library API (`runSync` or equivalent export) with forced model; keep one-way dep (no OPSX knowledge in pi-subagents)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 2. Skill routing (armed vs disarmed)

- [x] 2.1 Update `openspec-loop` skill (+ related refs that dispatch role-bound subagents) to require `opsx_dispatch` for review/impl/(opt-in author) while loop armed; document disarmed generic `subagent` path and unset-role refuse on armed path
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/**
      - dot_local/share/agent-harness/canonical/skills/openspec-propose/**
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/**
  - allow_new_files: false

## 3. Agent-independent tests

- [x] 3.1 Add hermetic tests for arm/clear tool-set swap citing `opsx-loop.armed-loop-mutes-generic-subagent-tool`
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [x] 3.2 Add hermetic tests for refuse-when-unset, role-forced model into spawn stub, and review fan-out count citing `opsx-loop.opsx-dispatch-forces-resolved-role-model`, `opsx-loop.review-role-auto-fan-out`, `opsx-loop.dispatch-spawns-via-subagent-library` (stub spawn; no live network)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
