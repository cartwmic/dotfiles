<!-- authored: in-session -->
# Capability: opsx-gate-enforcement

## MODIFIED Requirements

### Requirement: Verdict Freshness And Provenance

THE opsx gate command SHALL require verify.md and code-review.md to record the immutable `Diff Base SHA` and the implementation HEAD they were produced against, plus a reviewer-provenance field, and SHALL treat a verdict as failed if the recorded range does not equal `Diff Base SHA..<implementation-HEAD>` recomputed from the worktree opsx gate locates, so an agent cannot mark a verdict pass and then continue mutating the diff.

#### Scenario: Worktree located deterministically with convention fallback
- **WHEN** opsx gate needs the implementation HEAD
- **THEN** it SHALL locate the change's worktree from the `Worktree Path` recorded in review.md (validating it is a git worktree on branch `opsx/<change>`), or accept an explicit `--worktree <path>`; IF the recorded locator is absent, empty, or fails validation, THEN it SHALL probe the canonical `opsx worktree` convention path and use it iff that path is a valid git worktree on branch `opsx/<change>`; when locator and convention path both fail it SHALL proceed without a worktree rather than guessing the current directory

#### Scenario: Stale verdict fails the gate
- **WHILE** code-review.md or verify.md records a reviewed range
- **IF** that recorded `Diff Base SHA..HEAD` range does not equal the range opsx gate recomputes from the located worktree HEAD
- **THEN** opsx gate SHALL report the verdict as stale, fail that check, and exit non-zero

#### Scenario: Provenance is adapter-stamped, not agent-written
- **WHEN** opsx gate reads a code-review.md verdict under gating-required
- **THEN** the file SHALL carry a reviewer-provenance field stamped by the subagent-dispatch adapter (identifying the review subagent and `review_mode`), and a verdict lacking that field, or whose `review_mode` is `degraded-single-model` on a change that triggers Constitution IX, SHALL be treated as a failed check

## ADDED Requirements

### Requirement: Worktree locator published to the integration checkout

THE apply workflow SHALL record the `Worktree Path` and `Diff Base SHA` locator fields in
review.md COMMITTED TO THE INTEGRATION CHECKOUT at worktree-creation time, not solely on
the change branch, so that opsx gate and the loop extension — both of which resolve
review.md from the integration checkout — observe the same locator the apply worktree
uses and cannot split-brain (gate-from-main and gate-from-worktree disagreeing about the
same change). The convention-path fallback is the backstop for locators that predate this
rule, not a substitute for publication.

#### Scenario: Locator visible from the integration checkout after worktree creation
- **WHEN** the apply workflow creates the change worktree and records the locator
- **THEN** a review.md read from the integration checkout SHALL contain the recorded `Worktree Path` and `Diff Base SHA` (via a commit on the integration branch), and gate runs from the integration checkout and from the worktree SHALL locate the same worktree

#### Scenario: Pre-rule changes fall back instead of split-braining
- **WHILE** a change's integration-checkout review.md predates locator publication (locator empty)
- **WHEN** opsx gate runs from the integration checkout
- **THEN** the convention-path fallback SHALL resolve the worktree when it exists, rather than reporting artifact state from the integration checkout tree
