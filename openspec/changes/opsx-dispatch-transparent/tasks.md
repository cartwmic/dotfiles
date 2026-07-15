<!-- authored: in-session -->
# Tasks — opsx-dispatch-transparent

## 1. Transparent spawn path + narrow schema

- [ ] 1.1 Widen `opsx_dispatch` params to `role` + `task` XOR `tasks[]` (+ `agent`, optional `concurrency`); refuse when both/neither; keep armed-only + unset/sole-source gates
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 1.2 Forward `onUpdate` into pi-subagents spawn; return subagent-shaped `Details`; attach `renderCall`/`renderResult` reusing pi-subagents renderers (cite `opsx-loop.opsx-dispatch-transparent-progress-and-details`)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 2. Native parallel review fan-out

- [ ] 2.1 When `role: "review"` multi-list + single `task`, expand to native parallel `tasks[]` (order preserved, models forced); replace sequential custom loop (cite `opsx-loop.review-role-auto-fan-out`)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 2.2 Caller `tasks[]`: force models (single-model stamp-all; review by index); refuse length mismatch for multi-review (cite `opsx-loop.caller-tasks-length-must-match-review-list`)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 3. Skill routing docs

- [ ] 3.1 Update openspec-loop (+ propose/apply refs) armed-path docs: one `opsx_dispatch` owns native-parallel multi-review; no N sequential calls (cite `opsx-skill-integration.skills-honor-configured-role-models`)
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/**
      - dot_local/share/agent-harness/canonical/skills/openspec-propose/**
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/**
  - allow_new_files: false

## 4. Agent-independent tests

- [ ] 4.1 Hermetic tests: onUpdate forwarded; Details non-empty vs one-liner regression; renderers present (cite `opsx-loop.opsx-dispatch-transparent-progress-and-details`, `opsx-loop.opsx-dispatch-narrow-schema`)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 4.2 Hermetic tests: review multi → parallel expansion (count/order/forced models); caller `tasks[]` length mismatch refuse; prior mute/unset/sole-source suite still green (cite `opsx-loop.review-role-auto-fan-out`, `opsx-loop.caller-tasks-length-must-match-review-list`)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
