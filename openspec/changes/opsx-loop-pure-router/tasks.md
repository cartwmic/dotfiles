<!-- authored: in-session -->
# Tasks — opsx-loop-pure-router

## 1. Armed mute: edit/write + bookkeep exposure

- [ ] 1.1 Extend `applyArmedToolSet` / `restoreToolSetAfterClear` to drop `edit`, `write`, and `subagent`, ensure `opsx_dispatch` + `opsx_bookkeep` present while armed; restore exact pre-arm snapshot on clear (armed-only tools absent unless pre-arm). Cite `opsx-loop.armed-loop-mutes-generic-subagent-tool`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 1.2 Wire arm/clear in `index.ts` so `ensureOpsxBookkeepTool` registers alongside `opsx_dispatch`; bash/read retained from snapshot. Cite `opsx-loop.armed-loop-mutes-generic-subagent-tool`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 2. opsx_bookkeep structured meta tool

- [ ] 2.1 Implement pure bookkeep helpers: path resolve to INTEGRATION `openspec/changes/<armedChange>/{review,follow-ups}.md`; refuse matrix (not-armed, wrong change, worktree-only path, unknown op, empty set-hold reason, agent `clear_hold`). Cite `opsx-loop.opsx-bookkeep-structured-meta-tool`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 2.2 Implement enum ops `append_ledger`, `set_hold`, `append_followup`, `append_execution_note` (text transforms + single `writeFileSync` on resolved INTEGRATION path); `clear_hold` always refuses. Sibling allowlist empty at v1. Cite `opsx-loop.opsx-bookkeep-structured-meta-tool`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 2.3 Register `opsx_bookkeep` tool on extension (schema + execute + thin render); armed-only. Cite `opsx-loop.opsx-bookkeep-structured-meta-tool`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 3. Armed author override

- [ ] 3.1 In `planOpsxDispatch`, WHILE armed + `role: author`, ignore `authorInSession` refuse branch; configured author → accept + force model; unset → refuse, no session fallback. Disarmed path unchanged. Cite `opsx-loop.armed-loop-forces-author-role-dispatch`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: false

## 4. Skill routing (armed MUST-dispatch + bookkeep)

- [ ] 4.1 Rewrite `openspec-loop`, `openspec-propose`, `openspec-apply-change` armed sections: judged author/impl/review → `opsx_dispatch`; integration meta → `opsx_bookkeep`; remove in-session author / "implement the next task" while armed; document bash residual + disarmed `author_in_session` unchanged. Cite `opsx-skill-integration.skills-honor-configured-role-models`, `opsx-skill-integration.worktree-always-skill-discipline`.
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/**
      - dot_local/share/agent-harness/canonical/skills/openspec-propose/**
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/**
  - allow_new_files: false

## 5. Agent-independent tests

- [ ] 5.1 Hermetic tests: armed mute drops edit/write/subagent, exposes dispatch+bookkeep, clear restores snapshot; bash retained when in pre-arm. Cite `opsx-loop.armed-loop-mutes-generic-subagent-tool`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 5.2 Hermetic tests: bookkeep allow/refuse matrix (append ledger/followup/execution note, set_hold, empty reason, clear_hold refuse, wrong change, not-armed). Cite `opsx-loop.opsx-bookkeep-structured-meta-tool`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true
- [ ] 5.3 Hermetic tests: armed author dispatch allowed when `authorInSession` true/unset; unset author still refuses; prior mute/unset/sole-source/transparent suite stays green. Cite `opsx-loop.armed-loop-forces-author-role-dispatch`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## Assumptions

- Host tool names are literal `edit` / `write` (design D5).
- Bookkeep ledger/Execution-Notes append format matched to current skill template examples during apply (design Open Question).
- Sibling meta allowlist stays empty at v1.
