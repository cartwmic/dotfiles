# opsx-gate-enforcement — delta for harden-opsx-repo-portability

<!-- authored: in-session -->

## ADDED Requirements

### Requirement: Project Artifact Preflight

THE `opsx gate` SHALL require that `openspec/constitution.md` and `openspec/domain.md` both exist and are non-empty in the integration checkout, at EVERY Scale (XS, S, and M, with or without `full_rigor`), and IF either file is absent or empty, THEN the gate SHALL fail closed with a directive naming the shipped scaffolding templates (`constitution-template.md` and `domain-template.md` under the opsx-superpowers schema templates directory) as the remedy; the gate SHALL NOT auto-scaffold either file and SHALL offer NO waiver key for this check. The check SHALL be a deterministic file-existence/size test with no model call.

#### Scenario: Missing constitution fails the gate with the template remedy
- **IF** `openspec/constitution.md` is absent or empty in the integration checkout
- **THEN** `opsx gate` SHALL emit a GATE-FAIL naming `constitution.md` and the `constitution-template.md` scaffolding remedy, and the gate SHALL NOT pass

#### Scenario: Missing domain fails the gate with the template remedy
- **IF** `openspec/domain.md` is absent or empty in the integration checkout
- **THEN** `opsx gate` SHALL emit a GATE-FAIL naming `domain.md` and the `domain-template.md` scaffolding remedy, and the gate SHALL NOT pass

#### Scenario: Both artifacts present turn the check green
- **WHILE** both `openspec/constitution.md` and `openspec/domain.md` exist non-empty
- **WHEN** `opsx gate` evaluates the project-artifact preflight
- **THEN** the check SHALL pass

#### Scenario: Preflight applies at every Scale
- **WHILE** a change declares Scale XS, S, or M (any `full_rigor` value)
- **WHEN** `opsx gate` runs for that change
- **THEN** the project-artifact preflight SHALL be evaluated identically — no Scale skips it and no front-matter key waives it

#### Scenario: Preflight is deterministic and never scaffolds
- **WHEN** the project-artifact preflight runs
- **THEN** it SHALL be a file-existence/non-empty test with no model call, and it SHALL NOT create or modify either artifact

## MODIFIED Requirements

### Requirement: Land Base Currency

THE archive/land path SHALL require that `merge-base(opsx/<change>, <integration branch>)` equals the current integration-branch HEAD before landing or archiving a change, where the integration branch is obtained via the deterministic resolver (`opsx-cli` `Integration Branch Resolution` — committed review.md locator field, then `origin/HEAD`, then `main`, then `master`, else loud failure), computed with deterministic git plumbing (no language-model judgment), so a change built on a stale base cannot land over intervening integration-branch commits; WHEN the merge-base is not equal to the integration-branch HEAD, the archive/land SHALL be refused with a failure message that names the resolved branch and the rebase remedy (rebase `opsx/<change>` onto the resolved branch's HEAD, which staleness-fires a fresh review) rather than proceeding. WHERE no `opsx/<change>` integration branch exists (a same-tree change — the XS/S auto-downgrade default under B4 — whose commits land directly on the integration checkout), the precondition SHALL be treated as satisfied (there is no divergent base to rebase, so the stale-base failure class does not apply), never refused as a missing-ref error.

#### Scenario: Current base permits landing
- **WHILE** `merge-base(opsx/<change>, <resolved integration branch>)` equals the resolved branch's HEAD
- **WHEN** the archive/land path evaluates the base-currency precondition
- **THEN** the precondition SHALL pass and landing MAY proceed subject to the other archive gates

#### Scenario: Stale base refuses landing and names the remedy
- **IF** `merge-base(opsx/<change>, <resolved integration branch>)` does not equal the resolved branch's HEAD (the integration branch advanced since the branch's base)
- **THEN** the archive/land SHALL be refused and the failure message SHALL name the resolved branch and the rebase remedy (rebase `opsx/<change>` onto that branch's HEAD, re-running review afterward), and the change SHALL NOT be landed or moved to the archive directory

#### Scenario: Base check is deterministic git plumbing
- **WHEN** the base-currency precondition is evaluated
- **THEN** it SHALL be computed solely from git plumbing (merge-base vs. the resolved integration branch's HEAD) with no model call, matching the gate's deterministic, model-free posture

#### Scenario: Same-tree change with no integration branch is not blocked
- **WHILE** the change was authored same-tree (no `opsx/<change>` branch exists) so its commits landed directly on the integration checkout
- **WHEN** the archive/land path evaluates the base-currency precondition
- **THEN** the precondition SHALL be treated as satisfied (there is no divergent base) and archive MAY proceed subject to the other archive gates, rather than the missing `opsx/<change>` ref being reported as a stale/failed base

#### Scenario: Non-main default branch passes when current
- **WHILE** the repository's integration branch resolves to a name other than `main` (e.g. `trunk`) AND `merge-base(opsx/<change>, trunk)` equals `trunk` HEAD
- **WHEN** the archive/land path evaluates the base-currency precondition
- **THEN** the precondition SHALL pass rather than failing because no `main` branch exists
