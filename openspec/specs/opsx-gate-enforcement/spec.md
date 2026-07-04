# opsx-gate-enforcement Specification

## Purpose
The deterministic exit-code gate (`opsx gate <change>`): the single source of enforcement truth for opsx-superpowers changes — required-artifacts-by-Scale, validation manifest execution, and mode-aware verdict/freshness/provenance checks, exit 0 = ready to archive.
## Requirements
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

### Requirement: Cheap Before Expensive Ordering

THE opsx gate command SHALL evaluate structural and artifact-presence checks before executing any validation command declared in the manifest, and IF a structural, required-artifact, or task-completion check fails, THEN it SHALL report the failure and exit without running the validation commands.

#### Scenario: Cheap check short-circuits expensive commands
- **WHILE** a required artifact is missing
- **WHEN** opsx gate runs
- **THEN** it SHALL report the missing artifact and SHALL NOT execute any validation command from the manifest

#### Scenario: Validation commands run only when cheap checks pass
- **WHEN** structure, required artifacts, and task completion all pass
- **THEN** opsx gate SHALL proceed to execute the manifest validation commands

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

### Requirement: Manifest Validation Execution

WHERE an `openspec/opsx-gates.yaml` manifest exists, THE opsx gate command SHALL execute each declared gate command and SHALL treat a non-zero exit from a `required: true` command as a failed check; and WHERE the `OPSX_VALIDATE` environment value supplies additional commands, it SHALL execute those as well. For worktree-required changes, opsx gate SHALL run every validation command with the working directory set to the located implementation worktree and SHALL export `OPSX_CHANGE`, `OPSX_CHANGE_DIR`, `OPSX_WORKTREE`, `OPSX_DIFF_BASE`, and `OPSX_HEAD`, so validations run against the same checkout whose verdict freshness is computed.

#### Scenario: Validations run in the located worktree
- **WHILE** the change is worktree-required
- **WHEN** opsx gate reaches the validation stage
- **THEN** each command SHALL run with cwd set to the located worktree and the `OPSX_*` variables exported, and IF no valid worktree can be located THEN opsx gate SHALL fail before running any validation command

#### Scenario: Failing required manifest command fails the gate
- **WHEN** a manifest gate command with `required: true` exits non-zero
- **THEN** opsx gate SHALL report that gate's id and command as a failed check and exit non-zero

#### Scenario: Failing advisory manifest command warns only
- **WHEN** a manifest gate command with `required: false` exits non-zero
- **THEN** opsx gate SHALL surface a warning for that gate and SHALL NOT fail the gate on its account

#### Scenario: User-supplied validation commands run
- **WHERE** `OPSX_VALIDATE` contains one or more commands
- **WHEN** opsx gate reaches the validation stage
- **THEN** each user-supplied command SHALL be executed and a non-zero exit SHALL fail the gate

#### Scenario: No validations declared
- **IF** no manifest exists and `OPSX_VALIDATE` is empty
- **THEN** opsx gate SHALL skip the validation stage without failing on its account

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

### Requirement: Mode Aware Verdict Reading

THE opsx gate command SHALL determine verify, code-review, and doneness outcomes solely by parsing the verdict fields of the respective artifact files (no language-model judgment), and SHALL apply those checks conditioned on the change's Verification Mode, Code Review Mode, and `doneness_mode` read from review.md front-matter, so that the gate never blocks on a check that the declared mode treats as advisory or waived. WHEN `code_review_mode` is ABSENT from the front-matter, the gate SHALL derive the documented fail-closed default before enforcement — `gating-required` at Scale M (with or without `full_rigor`), `advisory` below M — so an omitted key can never read as "not gating-required" and let a Scale-M change pass without a code-review verdict (fail-open by omission).

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

#### Scenario: Absent code_review_mode derives the fail-closed default at Scale M
- **WHILE** a change declares Scale M and its review.md front-matter OMITS `code_review_mode`
- **IF** code-review.md is absent or its Verdict is not pass
- **THEN** opsx gate SHALL enforce the derived `gating-required` default and report code-review as a failed check with a non-zero exit, never treating the omitted key as non-gating

#### Scenario: Absent code_review_mode below Scale M defaults to advisory
- **WHILE** a change declares Scale XS or S and its review.md front-matter OMITS `code_review_mode`
- **WHEN** opsx gate evaluates the code-review check
- **THEN** the derived default SHALL be `advisory` and a missing code-review.md SHALL NOT by itself cause a non-zero exit

#### Scenario: Doneness read by field and conditioned on mode
- **WHEN** opsx gate evaluates the doneness check
- **THEN** it SHALL determine the outcome solely by parsing `doneness.md` fields (no language-model judgment), and SHALL treat the check as required only WHILE the change is Scale M or above and `doneness_mode` is `required`, so a waived or sub-M doneness verdict never blocks — the concrete failure conditions are defined by the Doneness Verdict Enforcement requirement

### Requirement: In-Session Authoring Marker Check

WHILE the effective `author_in_session` is true or unset AND the `author` role specifically has a configured model, THE opsx gate command SHALL fail an authoring artifact that carries no `authored: in-session` marker. The marker SHALL be the literal line `<!-- authored: in-session -->` present anywhere in the artifact file (an HTML comment so it is inert in rendered Markdown); the gate detects it by a plain substring/line scan of the file. The marker is written in-session by the authoring step; it is a cheap, SELF-ATTESTED tripwire for the observed bug (authoring silently delegated, which would NOT run the in-session marker step) — it is NOT proof of the session model, and a worker that both delegates AND forges the marker is out of the threat model (a post-hoc gate cannot force a model against a same-UID actor). The authoring-artifact set the marker check scans SHALL be exactly: `proposal.md`, `intent.md`, `design.md`, `clarify.md`, `tasks.md`, `plan.md`, and the change's `specs/**/spec.md` (NOT `review.md`, `verify.md`, `code-review.md`, `analyze.md`, or `retrospective.md`). WHILE `author_in_session` is false (opt-in delegation), the marker is not required.

#### Scenario: Missing marker fails only when author role configured and in-session
- **WHILE** the `author` role has a configured model and `author_in_session` is true/unset
- **IF** an authoring artifact lacks the literal line `<!-- authored: in-session -->`
- **THEN** opsx gate SHALL report a failed check and exit non-zero

#### Scenario: No author marker check when author role unconfigured
- **IF** the `author` role has no configured model (source unset/default)
- **THEN** opsx gate SHALL NOT require an `authored: in-session` marker

#### Scenario: Opt-out delegation does not require the marker
- **WHILE** `author_in_session` is false
- **WHEN** authoring is delegated
- **THEN** opsx gate SHALL NOT require an `authored: in-session` marker on the authoring artifacts

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

