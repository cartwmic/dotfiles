<!-- authored: delegate spec-consolidation -->
# Capability: opsx-gate-enforcement

Delta for simplify-and-parallelize-opsx-workflow: the per-Scale required-artifact set moves
to the XS|S|M tier vocabulary with a `full_rigor` front-matter flag (former L/XL artifact
sets map to "M + full_rigor"), and two deterministic concurrency guards are added — a
land-base-currency precondition (A1) and a duplicate-ADR-number scan at archive (A3). The
gate stays deterministic and model-free. Modified requirements restate their full content
per the MODIFIED-delta rule.

## MODIFIED Requirements

### Requirement: Required Artifact By Scale

THE opsx gate command SHALL derive the set of required artifacts from the change's declared Scale — one of the tier vocabulary `XS | S | M` read from the machine-readable front-matter of review.md, together with the optional boolean `full_rigor` flag — and SHALL fail if any artifact in that set is absent or fails the structural validation appropriate to its type. WHILE Scale is M (with or without `full_rigor`), the required set SHALL include intent.md (the loop's frozen baseline). At Scale M WITHOUT `full_rigor`, the required set SHALL NOT include a standalone clarify.md, a standalone blind analyze verdict, or design.md (clarify open questions live in the proposal's `## Open Questions`; analyze is thinned to its deterministic checks; design authoring is decision-gated — authored only when a decision warrants it — not gate-required). WHILE `full_rigor: true` is set, the required set SHALL include the full former M/L/XL artifact set — clarify.md, analyze.md carrying its blind verdict, design.md (the former L/XL full set always carried design), and an independently dispatched doneness verdict — in addition to intent.md. The former L and XL labels map to "M + full_rigor"; a review.md declaring an unknown Scale value or an unparseable `full_rigor` value SHALL fail closed (reported as a failed check, never assumed permissive).

#### Scenario: Missing Scale-required artifact fails the gate at plain M
- **WHILE** the change declares Scale M WITHOUT `full_rigor`
- **IF** intent.md or review.md is absent
- **THEN** opsx gate SHALL report the missing artifact as a failed check and exit non-zero, and it SHALL NOT require a standalone clarify.md, a standalone blind analyze verdict, or design.md at this tier (design authoring is decision-gated, not gate-required)

#### Scenario: Full-rigor requires the full former L/XL artifact set
- **WHILE** the change declares Scale M with `full_rigor: true`
- **IF** intent.md, clarify.md, analyze.md (with its blind verdict), design.md, or review.md is absent
- **THEN** opsx gate SHALL report the missing artifact as a failed check and exit non-zero

#### Scenario: Absent or unparseable Scale fails the gate
- **IF** review.md is absent, or its front-matter omits Scale, or Scale is not one of `XS`, `S`, or `M`
- **THEN** opsx gate SHALL report the missing/unknown Scale as a failed check and exit non-zero, rather than assuming a permissive Scale that could bypass required artifacts

#### Scenario: Unparseable full_rigor flag fails closed
- **IF** review.md front-matter carries a `full_rigor` value that is not a parseable boolean
- **THEN** opsx gate SHALL treat it as a failed check and exit non-zero rather than silently defaulting it either way

#### Scenario: Missing-artifact failures emit in lifecycle dependency order
- **WHEN** more than one required artifact is missing
- **THEN** opsx gate SHALL emit the missing-artifact failures in lifecycle dependency order (review, intent, proposal, specs, clarify, design, analyze, tasks, plan, verify, code-review, doneness) so a first-red-wins consumer selects the earliest unmet dependency, not merely the cheapest check (review.md is ordered first because Scale is read from it before the ordered set is derived; doneness is ordered last because it is the intent-satisfaction check evaluated after all mechanical checks pass). `doneness.md` is a mode-conditioned verdict check (like verify.md and code-review.md), NOT a structural required artifact; its absence is governed solely by the Doneness Verdict Enforcement requirement — evaluated only when required and only as the sole remaining failure — and SHALL NOT trigger a cheap-phase missing-required-artifact short-circuit

#### Scenario: Structural validation is per artifact type
- **WHEN** opsx gate validates an artifact
- **THEN** it SHALL apply `openspec validate --strict` to OpenSpec-tracked artifacts and the artifact's own documented field checks to skill-managed artifacts (verify.md, code-review.md, doneness.md), and SHALL NOT apply `openspec validate --strict` to artifacts OpenSpec does not track

## ADDED Requirements

### Requirement: Land Base Currency

THE archive/land path SHALL require that `merge-base(opsx/<change>, main)` equals the current `main` HEAD before landing or archiving a change, computed with deterministic git plumbing (no language-model judgment), so a change built on a stale base cannot land over intervening main commits; WHEN the merge-base is not equal to `main` HEAD, the archive/land SHALL be refused with a failure message that names the rebase remedy (rebase `opsx/<change>` onto `main` HEAD, which staleness-fires a fresh review) rather than proceeding. WHERE no `opsx/<change>` integration branch exists (a same-tree change — the XS/S auto-downgrade default under B4 — whose commits land directly on the integration checkout), the precondition SHALL be treated as satisfied (there is no divergent base to rebase, so the stale-base failure class does not apply), never refused as a missing-ref error.

#### Scenario: Current base permits landing
- **WHILE** `merge-base(opsx/<change>, main)` equals `main` HEAD
- **WHEN** the archive/land path evaluates the base-currency precondition
- **THEN** the precondition SHALL pass and landing MAY proceed subject to the other archive gates

#### Scenario: Stale base refuses landing and names the remedy
- **IF** `merge-base(opsx/<change>, main)` does not equal `main` HEAD (main advanced since the branch's base)
- **THEN** the archive/land SHALL be refused and the failure message SHALL name the rebase remedy (rebase `opsx/<change>` onto `main` HEAD, re-running review afterward), and the change SHALL NOT be landed or moved to the archive directory

#### Scenario: Base check is deterministic git plumbing
- **WHEN** the base-currency precondition is evaluated
- **THEN** it SHALL be computed solely from git plumbing (merge-base vs. main HEAD) with no model call, matching the gate's deterministic, model-free posture

#### Scenario: Same-tree change with no integration branch is not blocked
- **WHILE** the change was authored same-tree (no `opsx/<change>` branch exists) so its commits landed directly on the integration checkout
- **WHEN** the archive/land path evaluates the base-currency precondition
- **THEN** the precondition SHALL be treated as satisfied (there is no divergent base) and archive MAY proceed subject to the other archive gates, rather than the missing `opsx/<change>` ref being reported as a stale/failed base

### Requirement: Duplicate ADR Number Scan

THE archive path SHALL scan the repository's `adr/` directory for duplicate ADR numbers and SHALL fail archive WHEN two or more files claim the same `ADR-NNNN` number, naming both (all) offending paths in the failure message, so a number collision cannot silently land two decisions under one identifier; the scan SHALL be a deterministic filename/number check (no model judgment).

#### Scenario: Duplicate ADR number fails archive
- **IF** two files under `adr/` both claim the number `ADR-NNNN`
- **THEN** archive SHALL be refused and the failure message SHALL name both (all) offending paths so the collision can be resolved

#### Scenario: Unique ADR numbers permit archive
- **WHILE** every `ADR-NNNN` number under `adr/` is claimed by at most one file
- **WHEN** the duplicate-ADR scan runs at archive
- **THEN** the scan SHALL pass and archive MAY proceed subject to the other archive gates

#### Scenario: Scan is deterministic
- **WHEN** the duplicate-ADR-number scan runs
- **THEN** it SHALL derive the number from each ADR filename deterministically (no model call) and compare for collisions
