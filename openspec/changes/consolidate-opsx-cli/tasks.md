<!-- authored: in-session -->
# Tasks — consolidate-opsx-cli

## 1. `opsx` multitool dispatcher + cutover

- [x] 1.1 Create `dot_local/bin/executable_opsx`: a `case "$1"` dispatcher with subcommand
  bodies `gate_*`, `models_*`, `loop_*` ported near-verbatim from the three source scripts;
  top-level `exit`→`return`, prefixed/localized globals, subcommand-specific `usage`/`PROG`;
  unknown/missing subcommand → usage + non-zero. The gate's internal model resolution calls
  the in-file `models_*` function (no self-exec of a legacy name).
  (opsx-cli.unified-subcommand-dispatch)
  - intent: refactor
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: true
- [x] 1.2 `git rm` the three legacy source scripts and add `.chezmoiremove` listing the
  deployed targets so `chezmoi apply` deletes them.
  (opsx-cli.hard-cutover-no-legacy-entrypoints)
  - intent: infra
  - files_allowed:
      - dot_local/bin/executable_opsx-gate
      - dot_local/bin/executable_opsx-models
      - dot_local/bin/executable_opsx-loop
      - .chezmoiremove

## 2. `opsx models` write surface

- [x] 2.1 Add `set <role> <value>` / `get <role>` / `list` to the `models_*` body: settable
  roles `author|review|impl|author-in-session` (hyphen→`author_in_session` key, boolean
  coercion + reject non-boolean); reserved verbs shadow role-read first-arg; `--layer
  user|project` (project root = `$OPSX_ROOT` → git toplevel w/ `openspec/` → error); atomic
  temp-in-target-dir + rename, create-if-absent, comment/order preserving via `yq -i`;
  failed write leaves original intact + cleans temp; `get --layer` raw read; `set review`
  warns on list replace; invalid role/layer → error no write.
  (opsx-cli.model-config-write-surface)
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx

## 3. Migrate canonical skills + schema/templates

- [x] 3.1 Migrate `opsx-gate`/`opsx-models`/`opsx-loop`-driver invocations to `opsx <sub>`
  across canonical skills (openspec-loop SKILL.md; openspec-propose/apply-change/explore/
  archive-change superpowers-mode refs) and schema (README, capability-hooks, opsx-PROMPT,
  schema.yaml, templates/*). Document the new `opsx models` write surface + `/opsx-loop
  models` where model config is described. Preserve capability names + filenames.
  (opsx-cli.hard-cutover-no-legacy-entrypoints, opsx-skill-integration.skills-honor-configured-role-models,
   opsx-skill-integration.openspec-loop-orchestrator-skill-exists, opsx-loop-orchestration.single-orchestrator-loop,
   opsx-loop-orchestration.harness-neutral-core-with-adapters, opsx-workflow-schema.mode-switchboard-in-review-md,
   opsx-workflow-schema.worktree-lifecycle-ownership, opsx-workflow-schema.validation-gates-manifest-reference)
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/**
      - dot_local/share/openspec/schemas/opsx-superpowers/**

## 4. Migrate pi extensions + bug fixes

- [x] 4.1 opsx-loop extension: spawn `opsx gate`/`opsx models` (was `opsx-gate`/`opsx-models`);
  rework `parseLoopArg` to route leading keywords (`status`/`clear`/`models`) with full
  remaining tokens + surface ignored-trailing-token note (no truncation); add `/opsx-loop
  models` wrapper (bare→list; pass repo cwd/`OPSX_ROOT` for `--layer project`); re-resolve
  `Worktree Path` from review.md each `agent_end` (blank/stale→no-worktree gate); stall
  detection (normalized `check_id` set + HEAD-or-change-dir-edit progress, default 3,
  preserve+notify). Update goal extension test's spawn-name reference only.
  (opsx-loop-kickoff.single-command-guaranteed-loop, opsx-loop-kickoff.argument-parsing-preserves-full-input, opsx-loop-kickoff.stall-detection-stops-the-loop,
   opsx-loop-kickoff.model-config-subcommand, opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts
      - dot_pi/agent/extensions/goal/helpers.test.ts

## 5. Tests

- [x] 5.1 Retarget `tests/opsx-gate/*` and `tests/opsx-models/*` to invoke `opsx gate` /
  `opsx models`; add `tests/opsx-cli/test_opsx_cli.sh` covering dispatch (known/unknown/
  missing subcommand, exit-code passthrough) + write surface (set/get/list, layers,
  atomicity+failure, comment preservation, author-in-session boolean, set-review warn,
  project-root discovery).
  (opsx-cli.unified-subcommand-dispatch, opsx-cli.model-config-write-surface)
  - intent: feature
  - files_allowed:
      - tests/opsx-gate/**
      - tests/opsx-models/**
      - tests/opsx-cli/**

## 6. Verify + gate

- [x] 6.1 Run all suites + `bash -n` + extension bun test/transpile + token-level legacy
  scan + `openspec validate --strict`; author verify.md (6 checks green). Then dispatch blind
  multi-model code-review (Constitution IX), author code-review.md, and run
  `opsx gate consolidate-opsx-cli --worktree <path>` to GATE-PASS.
  - intent: infra
  - files_allowed:
      - openspec/changes/consolidate-opsx-cli/**
