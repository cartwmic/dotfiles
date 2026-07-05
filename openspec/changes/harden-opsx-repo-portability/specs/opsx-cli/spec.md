# opsx-cli — delta for harden-opsx-repo-portability

<!-- authored: in-session -->

## ADDED Requirements

### Requirement: Integration Branch Resolution

THE `opsx` CLI SHALL resolve the integration branch through a single deterministic helper wherever a check compares against the integration branch, with resolution order (first hit wins): (1) the change's committed review.md `**Integration Branch:**` locator field when a change context exists and the field is non-empty and non-placeholder; (2) the short name of `git symbolic-ref refs/remotes/origin/HEAD`; (3) a local branch named `main`; (4) a local branch named `master`; and IF no step resolves, THEN the CLI SHALL fail loudly with a named error identifying the unresolvable integration branch rather than silently assuming any default. The resolver SHALL be pure git plumbing plus file reads — no model call, no configuration-file override key.

#### Scenario: Locator field wins when present
- **WHILE** the change's committed review.md carries a non-empty, non-placeholder `**Integration Branch:**` value
- **WHEN** an integration-branch-dependent check resolves the branch for that change
- **THEN** the resolver SHALL return the locator field's value without consulting later steps

#### Scenario: origin/HEAD symbolic-ref resolves when no locator applies
- **WHILE** no change-scoped locator value applies AND `git symbolic-ref refs/remotes/origin/HEAD` resolves
- **WHEN** the resolver runs
- **THEN** it SHALL return the symbolic-ref's short branch name

#### Scenario: master-only repo resolves to master
- **WHILE** no locator value applies, no `refs/remotes/origin/HEAD` symbolic-ref resolves, no local `main` branch exists, and a local `master` branch exists
- **WHEN** the resolver runs
- **THEN** it SHALL return `master`

#### Scenario: Unresolvable branch fails loudly
- **IF** no resolution step yields a branch
- **THEN** the invoking check SHALL fail with a named error stating the integration branch could not be resolved, and SHALL NOT proceed against a guessed branch

#### Scenario: Resolution is deterministic and model-free
- **WHEN** the resolver runs
- **THEN** it SHALL be computed solely from the committed locator field and git plumbing, with no model call and no environment-dependent guessing beyond the declared order

## MODIFIED Requirements

### Requirement: Status Fleet View

THE `opsx` CLI SHALL provide `opsx status` as a READ-ONLY, deterministic, model-free fleet view that scans the non-archive change directories under `openspec/changes/*` and, per change, prints: the declared Scale; the gate red/green summary plus the earliest failing check; the worktree path and its validity on branch `opsx/<change>`; the `loop_hold` state and its reason; and the Diff Base SHA staleness expressed as commits behind the resolved integration branch (per `Integration Branch Resolution`), never a hardcoded branch literal. `opsx status` SHALL have NO side effects (no file, branch, or worktree creation or mutation), SHALL make NO model calls, and SHALL exit 0 always — it is a view, not a gate.

#### Scenario: Per-change fleet summary printed
- **WHEN** `opsx status` runs with one or more non-archive changes under `openspec/changes/`
- **THEN** it SHALL print, for each change, its Scale, gate red/green + earliest failing check, worktree path + validity on branch `opsx/<change>`, `loop_hold` + reason, and Diff Base staleness as commits behind the resolved integration branch

#### Scenario: Status has no side effects and always exits 0
- **WHEN** `opsx status` runs
- **THEN** it SHALL NOT create or mutate any file, branch, or worktree, SHALL NOT invoke any model, and SHALL exit 0 regardless of any change's gate being red

#### Scenario: Archive directory excluded
- **WHILE** `openspec/changes/archive/` contains archived changes
- **WHEN** `opsx status` scans the fleet
- **THEN** it SHALL scan only the non-archive change directories and SHALL NOT report archived changes

#### Scenario: Change without review.md or branch prints placeholders, never crashes
- **WHILE** a non-archive change directory has no `review.md` (e.g. a from-scratch change still in its distilling phase) so its Scale is undeclared and no `opsx/<change>` branch exists
- **WHEN** `opsx status` reports that change
- **THEN** it SHALL print a stable placeholder (for example `—`/`unknown`) for the undeclared Scale, worktree, `loop_hold`, and commits-behind fields rather than erroring, and SHALL still exit 0, since `opsx status` is a view that must never crash on an incomplete change

#### Scenario: Non-main default branch reports staleness correctly
- **WHILE** the repository's integration branch resolves to a name other than `main` (e.g. `trunk`)
- **WHEN** `opsx status` computes Diff Base commits-behind staleness
- **THEN** it SHALL count against the resolved branch and SHALL NOT print a placeholder merely because no `main` branch exists

### Requirement: Multi-Dir Integration Commit Detector

THE `opsx` CLI SHALL provide a deterministic detector that flags any integration-checkout commit touching more than one `openspec/changes/<change>/` directory, as an advisory detection surface backstopping the path-scoped-commit discipline (detection, not prevention), computed from git plumbing with no model judgment; the detector's scan range SHALL terminate at the resolved integration branch (per `Integration Branch Resolution`), never a hardcoded branch literal, so the detector functions in repositories whose integration branch is not named `main`.

#### Scenario: Multi-dir commit is flagged
- **IF** an integration-checkout commit touches paths under two or more distinct `openspec/changes/<change>/` directories
- **THEN** the detector SHALL flag that commit (naming it and the touched change directories) as an advisory finding

#### Scenario: Single-dir commit is not flagged
- **WHILE** a commit touches paths within at most one `openspec/changes/<change>/` directory
- **WHEN** the detector runs
- **THEN** it SHALL NOT flag that commit

#### Scenario: Detection is advisory, not prevention
- **WHEN** the detector flags a multi-dir commit
- **THEN** it SHALL surface the finding as advisory and SHALL NOT by itself block a commit or fail the gate, per the detection-not-prevention posture

#### Scenario: Detector runs in a non-main repository
- **WHILE** the repository's integration branch resolves to a name other than `main`
- **WHEN** the detector scans `<Diff Base SHA>..<resolved branch>`
- **THEN** it SHALL flag multi-dir commits in that range rather than silently skipping because no `main` branch exists
