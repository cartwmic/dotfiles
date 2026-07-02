<!-- authored: in-session -->
# opsx-gate-enforcement (delta)

## ADDED Requirements

### Requirement: Doneness Verdict Enforcement

THE opsx gate command SHALL require a `doneness.md` whose `Doneness` field is `satisfied`, whose reviewed range equals `Diff Base SHA..<implementation-HEAD>` recomputed from the located worktree, whose recorded Diff Base SHA equals the immutable Diff Base SHA in review.md, whose recorded frozen-intent hash equals `sha256(intent.md)`, and which carries an adapter-stamped reviewer-provenance field whose review mode is not `degraded-single-model`, WHILE the change declares Scale M or above and `doneness_mode` is `required` (default), and SHALL treat a doneness verdict that is absent, not `satisfied`, stale, judged against a mismatched intent hash or diff base, unprovenanced, or provenance-degraded as a failed check, determining the doneness outcome solely by parsing `doneness.md` fields (no language-model judgment in the gate).

#### Scenario: Missing or not-satisfied doneness fails at Scale >= M
- **WHILE** the change declares Scale M or above and `doneness_mode` is `required`
- **IF** `doneness.md` is absent or its `Doneness` field is not `satisfied`
- **THEN** opsx gate SHALL report `doneness` as a failed check and exit non-zero

#### Scenario: Stale doneness verdict fails the gate
- **WHILE** `doneness.md` records a reviewed range
- **IF** that recorded `Diff Base SHA..HEAD` does not equal the range opsx gate recomputes
  from the located worktree HEAD
- **THEN** opsx gate SHALL report the doneness verdict as stale, fail that check, and exit
  non-zero

#### Scenario: Verdict judged against a mutated intent or wrong diff base fails the gate
- **IF** the frozen-intent hash recorded in `doneness.md` does not equal `sha256(intent.md)`,
  OR the Diff Base SHA recorded in `doneness.md` does not equal the immutable Diff Base SHA
  in review.md
- **THEN** opsx gate SHALL treat the doneness verdict as judged against the wrong baseline,
  fail that check, and exit non-zero

#### Scenario: Unprovenanced or self-authored doneness verdict fails the gate
- **IF** `doneness.md` carries a `satisfied` verdict but lacks the adapter-stamped
  reviewer-provenance field, or that field records review mode `degraded-single-model`
  (no independent blind judge)
- **THEN** opsx gate SHALL treat the doneness verdict as a failed check and exit non-zero

#### Scenario: Waived (with rationale) or sub-M doneness does not block
- **WHILE** `doneness_mode` is `waived` with a recorded non-empty `doneness_waiver_rationale`, or the change declares Scale below M
- **WHEN** opsx gate evaluates the doneness check
- **THEN** a missing or non-satisfied `doneness.md` SHALL NOT by itself cause a non-zero exit

#### Scenario: Waiver without a rationale fails at Scale >= M
- **WHILE** the change declares Scale M or above and `doneness_mode` is `waived`
- **IF** no non-empty `doneness_waiver_rationale` is recorded in review.md front-matter
- **THEN** opsx gate SHALL treat the doneness check as failed and exit non-zero, so a bare
  waiver cannot bypass the semantic judge

#### Scenario: Doneness is emitted only as the sole remaining failure
- **WHEN** opsx gate evaluates checks
- **THEN** it SHALL read and emit the `doneness` check ONLY after the structural,
  required-artifact, task-completion, manifest-validation, verify, and code-review checks all
  pass, and WHILE any of those checks is still failing it SHALL suppress the `doneness`
  failed-check line, so `doneness` appears in the `GATE-FAIL` set if and only if it is the
  sole remaining failure (the load-bearing precondition the stall detector's gap-set signal
  depends on)

## MODIFIED Requirements

### Requirement: Gate Exit Code Contract

THE opsx gate command SHALL exit with status 0 if and only if every check required for the change's declared Scale passes, and SHALL exit non-zero otherwise, writing a machine-readable report of each failed check to standard error.

#### Scenario: All checks pass
- **WHEN** opsx gate is run for a change whose required artifacts exist and validate, whose tasks are all checked, whose validation commands all exit 0, whose verify and code-review verdicts are green, and whose doneness verdict is satisfied when required
- **THEN** the command SHALL exit 0 and print a single `GATE-PASS: <change> (<scale>)` line

#### Scenario: A required check fails
- **IF** any required check fails
- **THEN** the command SHALL exit non-zero and SHALL print one stable-format line per failed check, `GATE-FAIL <check_id> <blocking> <message>` (machine consumers rely on `check_id`, the blocking flag, and line ordering; the trailing message is human context)

#### Scenario: Unknown change
- **IF** opsx gate is invoked with a change name that has no directory under `openspec/changes/`
- **THEN** the command SHALL exit non-zero and SHALL report that the change was not found, without creating any files

### Requirement: Mode Aware Verdict Reading

THE opsx gate command SHALL determine verify, code-review, and doneness outcomes solely by parsing the verdict fields of the respective artifact files (no language-model judgment), and SHALL apply those checks conditioned on the change's Verification Mode, Code Review Mode, and `doneness_mode` read from review.md front-matter, so that the gate never blocks on a check that the declared mode treats as advisory or waived.

#### Scenario: Verify enforced only when retained-required
- **WHILE** Verification Mode is retained-required
- **IF** verify.md is absent or its Completion Decision is not green
- **THEN** opsx gate SHALL report verify as a failed check and exit non-zero

#### Scenario: Verify advisory does not block
- **WHILE** Verification Mode is retained-recommended or inline-only
- **WHEN** opsx gate evaluates the verify check
- **THEN** a missing or non-green verify.md SHALL NOT by itself cause a non-zero exit

#### Scenario: Code review enforced only when gating-required
- **WHILE** Code Review Mode is gating-required
- **IF** code-review.md is absent or its Verdict is not pass
- **THEN** opsx gate SHALL report code-review as a failed check and exit non-zero, keeping the gate consistent with the archive gate

#### Scenario: Code review advisory or none does not block
- **WHILE** Code Review Mode is advisory or none
- **WHEN** opsx gate evaluates the code-review check
- **THEN** the code-review verdict SHALL NOT cause a non-zero exit

#### Scenario: Doneness read by field and conditioned on mode
- **WHEN** opsx gate evaluates the doneness check
- **THEN** it SHALL determine the outcome solely by parsing `doneness.md` fields (no language-model judgment), and SHALL treat the check as required only WHILE the change is Scale M or above and `doneness_mode` is `required`, so a waived or sub-M doneness verdict never blocks — the concrete failure conditions are defined by the Doneness Verdict Enforcement requirement

### Requirement: Required Artifact By Scale

THE opsx gate command SHALL derive the set of required artifacts from the change's declared Scale, read from the machine-readable front-matter of review.md, and SHALL fail if any artifact in that set is absent or fails the structural validation appropriate to its type. WHILE Scale is M or above, the required set SHALL include intent.md (the loop's frozen baseline).

#### Scenario: Missing Scale-required artifact fails the gate
- **WHILE** the change declares Scale M
- **IF** intent.md, clarify.md, analyze.md, or review.md is absent
- **THEN** opsx gate SHALL report the missing artifact as a failed check and exit non-zero

#### Scenario: Absent or unparseable Scale fails the gate
- **IF** review.md is absent, or its front-matter omits Scale, or Scale cannot be parsed
- **THEN** opsx gate SHALL report the missing Scale as a failed check and exit non-zero, rather than assuming a permissive Scale that could bypass required artifacts

#### Scenario: Missing-artifact failures emit in lifecycle dependency order
- **WHEN** more than one required artifact is missing
- **THEN** opsx gate SHALL emit the missing-artifact failures in lifecycle dependency order (review, intent, proposal, specs, clarify, design, analyze, tasks, plan, verify, code-review, doneness) so a first-red-wins consumer selects the earliest unmet dependency, not merely the cheapest check (review.md is ordered first because Scale is read from it before the ordered set is derived; doneness is ordered last because it is the intent-satisfaction check evaluated after all mechanical checks pass). `doneness.md` is a mode-conditioned verdict check (like verify.md and code-review.md), NOT a structural required artifact; its absence is governed solely by the Doneness Verdict Enforcement requirement — evaluated only when required and only as the sole remaining failure — and SHALL NOT trigger a cheap-phase missing-required-artifact short-circuit

#### Scenario: Structural validation is per artifact type
- **WHEN** opsx gate validates an artifact
- **THEN** it SHALL apply `openspec validate --strict` to OpenSpec-tracked artifacts and the artifact's own documented field checks to skill-managed artifacts (verify.md, code-review.md, doneness.md), and SHALL NOT apply `openspec validate --strict` to artifacts OpenSpec does not track
