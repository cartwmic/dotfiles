# opsx-gate-enforcement Specification

## Purpose
TBD - created by archiving change add-opsx-loop-harness. Update Purpose after archive.
## Requirements
### Requirement: Gate Exit Code Contract

THE opsx-gate command SHALL exit with status 0 if and only if every check required for the change's declared Scale passes, and SHALL exit non-zero otherwise, writing a machine-readable report of each failed check to standard error.

#### Scenario: All checks pass
- **WHEN** opsx-gate is run for a change whose required artifacts exist and validate, whose tasks are all checked, whose validation commands all exit 0, and whose verify and code-review verdicts are green
- **THEN** the command SHALL exit 0 and print a single `GATE-PASS: <change> (<scale>)` line

#### Scenario: A required check fails
- **IF** any required check fails
- **THEN** the command SHALL exit non-zero and SHALL print one stable-format line per failed check, `GATE-FAIL <check_id> <blocking> <message>` (machine consumers rely on `check_id`, the blocking flag, and line ordering; the trailing message is human context)

#### Scenario: Unknown change
- **IF** opsx-gate is invoked with a change name that has no directory under `openspec/changes/`
- **THEN** the command SHALL exit non-zero and SHALL report that the change was not found, without creating any files

### Requirement: Cheap Before Expensive Ordering

THE opsx-gate command SHALL evaluate structural and artifact-presence checks before executing any validation command declared in the manifest, and IF a structural, required-artifact, or task-completion check fails, THEN it SHALL report the failure and exit without running the validation commands.

#### Scenario: Cheap check short-circuits expensive commands
- **WHILE** a required artifact is missing
- **WHEN** opsx-gate runs
- **THEN** it SHALL report the missing artifact and SHALL NOT execute any validation command from the manifest

#### Scenario: Validation commands run only when cheap checks pass
- **WHEN** structure, required artifacts, and task completion all pass
- **THEN** opsx-gate SHALL proceed to execute the manifest validation commands

### Requirement: Required Artifact By Scale

THE opsx-gate command SHALL derive the set of required artifacts from the change's declared Scale, read from the machine-readable front-matter of review.md, and SHALL fail if any artifact in that set is absent or fails the structural validation appropriate to its type. WHILE Scale is M or above, the required set SHALL include intent.md (the loop's frozen baseline).

#### Scenario: Missing Scale-required artifact fails the gate
- **WHILE** the change declares Scale M
- **IF** intent.md, clarify.md, analyze.md, or review.md is absent
- **THEN** opsx-gate SHALL report the missing artifact as a failed check and exit non-zero

#### Scenario: Absent or unparseable Scale fails the gate
- **IF** review.md is absent, or its front-matter omits Scale, or Scale cannot be parsed
- **THEN** opsx-gate SHALL report the missing Scale as a failed check and exit non-zero, rather than assuming a permissive Scale that could bypass required artifacts

#### Scenario: Missing-artifact failures emit in lifecycle dependency order
- **WHEN** more than one required artifact is missing
- **THEN** opsx-gate SHALL emit the missing-artifact failures in lifecycle dependency order (review, intent, proposal, specs, clarify, design, analyze, tasks, plan, verify, code-review) so a first-red-wins consumer selects the earliest unmet dependency, not merely the cheapest check (review.md is ordered first because Scale is read from it before the ordered set is derived)

#### Scenario: Structural validation is per artifact type
- **WHEN** opsx-gate validates an artifact
- **THEN** it SHALL apply `openspec validate --strict` to OpenSpec-tracked artifacts and the artifact's own documented field checks to skill-managed artifacts (verify.md, code-review.md), and SHALL NOT apply `openspec validate --strict` to artifacts OpenSpec does not track

### Requirement: Manifest Validation Execution

WHERE an `openspec/opsx-gates.yaml` manifest exists, THE opsx-gate command SHALL execute each declared gate command and SHALL treat a non-zero exit from a `required: true` command as a failed check; and WHERE the `OPSX_VALIDATE` environment value supplies additional commands, it SHALL execute those as well. For worktree-required changes, opsx-gate SHALL run every validation command with the working directory set to the located implementation worktree and SHALL export `OPSX_CHANGE`, `OPSX_CHANGE_DIR`, `OPSX_WORKTREE`, `OPSX_DIFF_BASE`, and `OPSX_HEAD`, so validations run against the same checkout whose verdict freshness is computed.

#### Scenario: Validations run in the located worktree
- **WHILE** the change is worktree-required
- **WHEN** opsx-gate reaches the validation stage
- **THEN** each command SHALL run with cwd set to the located worktree and the `OPSX_*` variables exported, and IF no valid worktree can be located THEN opsx-gate SHALL fail before running any validation command

#### Scenario: Failing required manifest command fails the gate
- **WHEN** a manifest gate command with `required: true` exits non-zero
- **THEN** opsx-gate SHALL report that gate's id and command as a failed check and exit non-zero

#### Scenario: Failing advisory manifest command warns only
- **WHEN** a manifest gate command with `required: false` exits non-zero
- **THEN** opsx-gate SHALL surface a warning for that gate and SHALL NOT fail the gate on its account

#### Scenario: User-supplied validation commands run
- **WHERE** `OPSX_VALIDATE` contains one or more commands
- **WHEN** opsx-gate reaches the validation stage
- **THEN** each user-supplied command SHALL be executed and a non-zero exit SHALL fail the gate

#### Scenario: No validations declared
- **IF** no manifest exists and `OPSX_VALIDATE` is empty
- **THEN** opsx-gate SHALL skip the validation stage without failing on its account

### Requirement: Verdict Freshness And Provenance

THE opsx-gate command SHALL require verify.md and code-review.md to record the immutable `Diff Base SHA` and the implementation HEAD they were produced against, plus a reviewer-provenance field, and SHALL treat a verdict as failed if the recorded range does not equal `Diff Base SHA..<implementation-HEAD>` recomputed from the worktree opsx-gate locates, so an agent cannot mark a verdict pass and then continue mutating the diff.

#### Scenario: Worktree located deterministically
- **WHEN** opsx-gate needs the implementation HEAD
- **THEN** it SHALL locate the change's worktree from the `Worktree Path` recorded in review.md (validating it is a git worktree on branch `opsx/<change>`), or accept an explicit `--worktree <path>`, rather than guessing the current directory

#### Scenario: Stale verdict fails the gate
- **WHILE** code-review.md or verify.md records a reviewed range
- **IF** that recorded `Diff Base SHA..HEAD` range does not equal the range opsx-gate recomputes from the located worktree HEAD
- **THEN** opsx-gate SHALL report the verdict as stale, fail that check, and exit non-zero

#### Scenario: Provenance is adapter-stamped, not agent-written
- **WHEN** opsx-gate reads a code-review.md verdict under gating-required
- **THEN** the file SHALL carry a reviewer-provenance field stamped by the subagent-dispatch adapter (identifying the review subagent and `review_mode`), and a verdict lacking that field, or whose `review_mode` is `degraded-single-model` on a change that triggers Constitution IX, SHALL be treated as a failed check

### Requirement: Mode Aware Verdict Reading

THE opsx-gate command SHALL determine verify and code-review outcomes solely by parsing the verdict fields of the respective artifact files (no language-model judgment), and SHALL apply those checks conditioned on the change's Verification Mode and Code Review Mode read from review.md front-matter, so that the gate never blocks on a check that the declared mode treats as advisory.

#### Scenario: Verify enforced only when retained-required
- **WHILE** Verification Mode is retained-required
- **IF** verify.md is absent or its Completion Decision is not green
- **THEN** opsx-gate SHALL report verify as a failed check and exit non-zero

#### Scenario: Verify advisory does not block
- **WHILE** Verification Mode is retained-recommended or inline-only
- **WHEN** opsx-gate evaluates the verify check
- **THEN** a missing or non-green verify.md SHALL NOT by itself cause a non-zero exit

#### Scenario: Code review enforced only when gating-required
- **WHILE** Code Review Mode is gating-required
- **IF** code-review.md is absent or its Verdict is not pass
- **THEN** opsx-gate SHALL report code-review as a failed check and exit non-zero, keeping the gate consistent with the archive gate

#### Scenario: Code review advisory or none does not block
- **WHILE** Code Review Mode is advisory or none
- **WHEN** opsx-gate evaluates the code-review check
- **THEN** the code-review verdict SHALL NOT cause a non-zero exit

---

