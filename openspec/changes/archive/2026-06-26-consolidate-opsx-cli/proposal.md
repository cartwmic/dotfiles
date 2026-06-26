<!-- authored: in-session -->
## Why

Three sibling bash CLIs (`opsx-gate`, `opsx-models`, `opsx-loop`) accreted one change
at a time, duplicating arg-parsing, front-matter reading, and error conventions with no
shared home. They are one tool family pretending to be three. Consolidating into a single
`opsx <subcommand>` multitool removes the proliferation, gives one place to add the
already-needed `opsx models set/get/list` write surface, and lets us fix three latent
opsx-loop correctness bugs in the same pass. Constitution I (chezmoi source of truth) and
IX (skill-edit adversarial review) govern the migration.

## What Changes

- **BREAKING:** retire `opsx-gate`, `opsx-models`, `opsx-loop` as standalone executables;
  introduce a single `opsx` dispatcher with subcommands `opsx gate`, `opsx models`,
  `opsx loop`. Hard cutover — no compatibility shims; every caller migrates.
- Add a harness-neutral **write surface** to the resolver: `opsx models set <role> <model>
  [--layer user|project]`, `opsx models get <role>`, `opsx models list`. User layer
  (`~/.config/opsx/models.yaml`) is the default write target. Atomic write; comment/key-order
  preserving (`yq -i`). YAML files remain the sole source of truth (no new owner).
- Add pi `/opsx-loop models …` subcommand to the opsx-loop extension — a thin wrapper that
  shells out to `opsx models set/get/list`. Read + write from the pi TUI.
- **Bug fix:** `parseLoopArg` truncates the `/opsx-loop` argument at the first whitespace
  token, silently dropping the rest of the user's input. Rework the parser to support
  multi-token subcommands and stop discarding input.
- **Bug fix:** the opsx-loop extension captures `Worktree Path` once at loop kickoff; for a
  from-scratch change (no `review.md` yet) it stays `undefined`, so the judge-gate runs
  against the wrong tree forever and the loop can never converge. Re-resolve the worktree
  each turn.
- **Bug fix:** no stall detection — an unfixable/identical `GATE-FAIL` re-injects every turn
  until the budget burns. Detect N consecutive identical gate reasons → stop and notify.
- Migrate all callers: canonical skills + schema/templates (Constitution IX), pi extensions
  (spawn calls), `tests/`, and chezmoi binary source names.

## Capabilities

### New Capabilities
- `opsx-cli`: the unified `opsx <subcommand>` entrypoint — dispatch contract, hard-cutover
  (no legacy names), and the `models set/get/list` write surface with layer selection and
  atomic, comment-preserving writes.

### Modified Capabilities
- `opsx-loop-kickoff`: extension spawns `opsx gate`/`opsx models`; adds `/opsx-loop models`,
  per-turn worktree re-resolution, stall detection, and the arg-parser truncation fix.
- `opsx-gate-enforcement`: normative references migrated `opsx-gate` → `opsx gate` (behavior unchanged).
- `opsx-model-config`: references migrated `opsx-models` → `opsx models`; first-arg grammar reserves
  the `set`/`get`/`list` verbs ahead of role-read shorthand.
- `opsx-workflow-schema`: references migrated `opsx-gate`/`opsx-models` → subcommand form.
- `opsx-loop-orchestration`: references migrated `opsx-gate` → `opsx gate`.
- `opsx-skill-integration`: references migrated `opsx-gate` → `opsx gate`.

<!-- Spec-of-record honesty (per adversarial review): because this is a HARD CUTOVER that
     DELETES the standalone executables, every behavior capability that names them in normative
     prose gets a MODIFIED delta migrating the command-name references to the subcommand form, so
     the archived corpus names only commands that exist. Behavior is unchanged; the `opsx-cli`
     capability owns the dispatch contract + the new model-config WRITE surface. Requirement NAMES
     (AC-ID keys) are retained verbatim where cited by code/tests (design D6). -->

## Impact

- **Affected files (source):**
  - `dot_local/bin/executable_opsx` (new dispatcher; merges the three retired scripts),
    delete `executable_opsx-gate`, `executable_opsx-models`, `executable_opsx-loop`.
  - `dot_pi/agent/extensions/opsx-loop/{index.ts,helpers.ts,helpers.test.ts}` — spawn-name
    migration, `/opsx-loop models` subcommand, parser rework, worktree-refresh, stall detect.
  - `dot_pi/agent/extensions/goal/helpers.test.ts` — spawn-name reference.
  - Canonical skills: `openspec-loop/SKILL.md`, `openspec-propose|apply-change|explore`
    superpowers-mode refs, `openspec-archive-change` ref — `opsx-gate`/`opsx-models`/`opsx-loop`
    → `opsx <sub>` (Constitution IX → adversarial-multimodel review).
  - Schema: `dot_local/share/openspec/schemas/opsx-superpowers/{README.md,capability-hooks.md,
    opsx-PROMPT.md,schema.yaml,templates/*}` — invocation references.
  - Tests: `tests/opsx-gate/*`, `tests/opsx-models/*` → retarget to `opsx`; add `tests/opsx-cli/`
    for dispatch + write-surface.
- **Not touched:** ADRs 0005-0010 (historical; a new ADR records the consolidation). The
  `opsx-loop` **pi extension** keeps its name and `/opsx-loop` slash command (it is not a CLI).
- **Dependencies:** no new deps — `yq` (mise) + `jq` already required; `yq -i` for writes.
- **Deploy:** `chezmoi apply` re-materializes `~/.local/bin/opsx`, removes old names;
  `apply_harness_config.sh` re-links canonical skills.
