# Tasks — add-opsx-loop-harness

## 1. Harness-neutral core

- [x] 1.0 Install `yq` as a mise task (Constitution V) so opsx-gate can parse opsx-gates.yaml on its first self-run; document jq+JSON manifest fallback (review.md front-matter is sed/awk-parsed, no yq)
  - intent: infra
  - files_allowed:
      - dot_config/mise/config.toml
- [x] 1.1 Add `dot_local/bin/` gitignore allowlist so `executable_*` deploy (domain invariant 8)
  - intent: infra
  - files_allowed:
      - .gitignore
- [x] 1.2 Implement `opsx-gate` CLI: dependency-free sed/awk front-matter reader as the SOLE mode source (never parse the prose table), cheap→expensive short-circuit, required-artifact-by-Scale (incl. intent.md at M+) emitted in lifecycle dependency order, manifest(yq) execution with required:true=fail / required:false=warn + OPSX_VALIDATE, Scale≥M agent-independent-source = FAIL unless validation_source_mode:waived, mode-aware verify/code-review verdicts, verdict-freshness against immutable Diff Base SHA with deterministic worktree locator (Worktree Path / --worktree), adapter-stamped provenance + degraded-review-fails-IX, stable `GATE-FAIL <check_id> <blocking> <message>` report contract
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-gate
      - "tests/opsx-gate/**"
- [x] 1.5 Author a live `openspec/opsx-gates.yaml` for this repo so the E2E dry-run exercises a real agent-independent gate (not just the template)
  - intent: infra
  - files_allowed:
      - openspec/opsx-gates.yaml
- [x] 1.3 Implement `opsx-loop` Ralph fallback driver (AGENT_CMD-parameterized, worktree sandbox, gate as stop condition)
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-loop
      - dot_local/share/openspec/schemas/opsx-superpowers/opsx-PROMPT.md
- [x] 1.4 Author `openspec-loop` orchestrator skill (gate-driven cycle, subagent-review-against-baseline, harness-neutral core + adapter hooks)
  - intent: feature
  - files_allowed:
      - "dot_local/share/agent-harness/canonical/skills/openspec-loop/**"

## 2. Generic loop runtime (goal extension)

- [x] 2.1 Add pluggable command-judge to the goal extension (exit 0 = met; config precedence file→env→model default; non-fatal on exec failure); keep model-judge default; stay opsx-agnostic
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 2.2 Unit tests for command-judge met/not-met/exec-failure/model-default paths
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"

## 3. Schema edits

- [ ] 3.1 `templates/review.md`: YAML front-matter block, `Code Review Mode`, `Loop Max Iterations`, worktree-required default
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md
- [ ] 3.2 New `templates/code-review.md` (diff scope, base SHA, round tracker, applied-fixes, Verdict) + `templates/opsx-gates.yaml` example
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/code-review.md
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-gates.yaml
- [ ] 3.3 `schema.yaml`: document worktree-required default + lifecycle, Code Review Mode, Loop Max Iterations, opsx-gates.yaml manifest, front-matter; `capability-hooks.md`: post-impl adversarial-review hook + subagent-dispatch as a port; `README.md`: artifact/Scale tables
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/schema.yaml
      - dot_local/share/openspec/schemas/opsx-superpowers/capability-hooks.md
      - dot_local/share/openspec/schemas/opsx-superpowers/README.md

## 4. Skill edits (Constitution IX: covered by this change's adversarial review)

- [ ] 4.1 openspec-apply-change opsx-mode: worktree create/reuse/abort lifecycle, base-SHA capture, produce code-review.md after verify green (mode-gated), run opsx-gate
  - intent: feature
  - files_allowed:
      - "dot_local/share/agent-harness/canonical/skills/openspec-apply-change/**"
- [ ] 4.2 openspec-archive-change opsx-mode: hard-gate on code-review Verdict when gating-required, worktree merge + cleanup only after gate green, preserve on non-green
  - intent: feature
  - files_allowed:
      - "dot_local/share/agent-harness/canonical/skills/openspec-archive-change/**"
- [ ] 4.3 openspec-explore: freeze `intent.md` (intent + constraints + invariants) on conclusion under opsx-superpowers; no-op for spec-driven
  - intent: feature
  - files_allowed:
      - "dot_local/share/agent-harness/canonical/skills/openspec-explore/**"

## 5. Kickoff adapter + dependency

- [ ] 5.1 Thin pi `/opsx-loop` kickoff (wires worker=openspec-loop, judge=opsx-gate, worktree); zero workflow logic (delete-the-extension litmus must still run via bash fallback)
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
      - ".claude/commands/opsx/loop.md"
- [ ] 5.2 (Adapter docs) document the `/opsx-loop` kickoff + AGENT_CMD bash fallback in README; yq install is handled at T1.0
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/README.md

## 6. Verification + docs

- [ ] 6.1 End-to-end dry-run: explore→loop on a throwaway change; confirm gate red→green progression and archive gate
  - intent: feature
- [ ] 6.2 Update the consolidated design doc reference + README "Driving a change" section
  - intent: feature
  - files_allowed:
      - "docs/plans/**"
      - dot_local/share/openspec/schemas/opsx-superpowers/README.md
