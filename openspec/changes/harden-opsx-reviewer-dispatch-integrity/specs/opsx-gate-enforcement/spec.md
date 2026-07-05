# opsx-gate-enforcement (delta)

## MODIFIED Requirements

### Requirement: Verdict Freshness And Provenance

THE opsx gate command SHALL require verify.md and code-review.md to record the immutable `Diff Base SHA` and the implementation HEAD they were produced against, plus a reviewer-provenance field, and SHALL treat a verdict as failed if the recorded range does not equal `Diff Base SHA..<implementation-HEAD>` recomputed from the worktree opsx gate locates, so an agent cannot mark a verdict pass and then continue mutating the diff. WHEN Code Review Mode is gating-required, code-review.md SHALL additionally carry an own-line `**Attested HEAD:**` field — the reviewer-attested tree HEAD — and the gate SHALL fail the code-review check unless that value rev-parses equal to the recorded Reviewed Range head; an absent or unparseable `Attested HEAD` SHALL be a failed check, never a pass (fail-closed). The same attestation binding SHALL apply to doneness.md WHEN the doneness verdict is required and was produced by the independently dispatched full_rigor judge. Attestation SHALL be enforced only where a verdict artifact is evaluated by the gate (active changes) — archived changes are never re-gated.

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

#### Scenario: Attested HEAD required and bound under gating-required
- **WHILE** Code Review Mode is gating-required
- **IF** code-review.md omits `**Attested HEAD:**`, or its value does not rev-parse equal to the recorded Reviewed Range head
- **THEN** opsx gate SHALL report the code-review check as failed and exit non-zero

#### Scenario: Matching attestation passes
- **WHILE** Code Review Mode is gating-required
- **WHEN** code-review.md carries `**Attested HEAD:**` rev-parsing equal to the Reviewed Range head (alongside the existing freshness and provenance requirements)
- **THEN** the attestation binding SHALL NOT fail the code-review check

#### Scenario: Attestation not demanded where code review is advisory
- **WHILE** Code Review Mode is advisory or none
- **WHEN** opsx gate evaluates the code-review check
- **THEN** a missing `Attested HEAD` SHALL NOT by itself cause a non-zero exit

#### Scenario: Independent-judge doneness carries the binding
- **WHILE** doneness is required and `full_rigor` is true (independently dispatched judge)
- **IF** doneness.md omits `**Attested HEAD:**` or its value does not rev-parse equal to the recorded Diff Base–bound implementation HEAD it judged
- **THEN** opsx gate SHALL report the doneness check as failed and exit non-zero
