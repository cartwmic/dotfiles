## 1. opsx CLI (single-source path + gate fallback)

- [x] 1.1 Add read-only `opsx worktree path <change>` subcommand emitting the convention path with no side effects; refactor `worktree ensure` to share the one derivation. (AC: opsx-cli.read-only-worktree-path-emit)
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false
- [x] 1.2 Gate worktree resolution: probe the shared convention derivation when the recorded locator is absent/invalid; explicit `--worktree` failures stay loud. (AC: opsx-gate-enforcement.verdict-freshness-and-provenance)
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false
- [x] 1.3 CLI/gate tests: path emit is side-effect-free, fallback resolves convention worktree, both-fail degrades to no-worktree. (AC: opsx-cli.read-only-worktree-path-emit, opsx-gate-enforcement.worktree-locator-published-to-the-integration-checkout)
  - intent: test
  - files_allowed:
      - tests/opsx-cli/**
      - tests/opsx-gate/**
  - allow_new_files: true

## 2. opsx-loop extension

- [x] 2.1 Pure helpers: `loop_hold`/`loop_hold_reason` front-matter parse, active-change inventory builder (committed-intent filter + status), convention-path shell wrapper; unit tests. (AC: opsx-loop-kickoff.loop-hold-blocks-continuation, opsx-loop-kickoff.goal-and-conversation-kickoff)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts
  - allow_new_files: false
- [x] 2.2 Distill directive: embed inventory + distill-scoped autonomy text (drive-to-green blurb stays on worker/continuation only). (AC: opsx-loop-kickoff.goal-and-conversation-kickoff)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false
- [x] 2.3 Stall baseline seeded from `preChangeDirs` at arm; notify count stays truthful (3 turns = 3 turns). (AC: opsx-loop-kickoff.goal-and-conversation-kickoff)
  - intent: fix
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false
- [x] 2.4 `loop_hold` check at agent_end before continuation injection (integration-checkout copy; honored even with empty reason); clear-on-named-re-arm BEFORE Guard-1 with reason surfacing + Execution Notes line; goal kickoff never clears; `resolveWorktree` convention fallback via `opsx worktree path`. (AC: opsx-loop-kickoff.loop-hold-blocks-continuation, opsx-loop-kickoff.worktree-resolution-convention-fallback, opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false
- [x] 2.5 Extension behavior tests: hold lands/clears per contract, inventory in kickoff directive only, seeded stall count, fallback resolution, no-hold unchanged. (AC: opsx-loop-kickoff.loop-hold-blocks-continuation, opsx-loop-kickoff.goal-and-conversation-kickoff, opsx-loop-kickoff.worktree-resolution-convention-fallback)
  - intent: test
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 3. Skills + templates (Constitution IX surfaces)

- [x] 3.1 openspec-loop SKILL.md: landing prose sets `loop_hold` on the integration-checkout review.md (never clears it); stall-burn demoted to no-hold-support fallback. (AC: opsx-loop-orchestration.terminal-landings-set-the-loop-hold, opsx-loop-orchestration.review-dispatch-bound-by-convergence-discipline)
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md
  - allow_new_files: false
- [x] 3.2 apply-mode reference: locator publication step — commit `Worktree Path` + `Diff Base SHA` to the integration checkout at worktree creation. (AC: opsx-gate-enforcement.worktree-locator-published-to-the-integration-checkout)
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md
  - allow_new_files: false
- [x] 3.3 review.md template: commented `loop_hold`/`loop_hold_reason` keys with set/clear contract; gate ignores them. (AC: opsx-workflow-schema.loop-hold-front-matter-keys)
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md
  - allow_new_files: false

## 4. Validation

- [x] 4.1 Full validator sweep per openspec/opsx-gates.yaml; iterate until green. (AC: all)
  - intent: fix
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
      - dot_local/bin/executable_opsx
      - tests/**
  - allow_new_files: false
- [x] 4.2 AC↔test citation check: every canonical AC id above literally present in a test file touched by the diff. (AC: all)
  - intent: test
  - files_allowed:
      - tests/**
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: false
