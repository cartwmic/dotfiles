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
- **THEN** opsx gate SHALL emit the missing-artifact failures in lifecycle dependency order (review, intent, proposal, specs, clarify, design, analyze, design-fidelity, tasks, plan, verify, code-review, doneness) so a first-red-wins consumer selects the earliest unmet dependency, not merely the cheapest check (review.md is ordered first because Scale is read from it before the ordered set is derived; design-fidelity is ordered after analyze and before tasks so a first-red-wins consumer resolves the fidelity verdict before tasks generation, matching the pre-tasks gating; doneness is ordered last because it is the intent-satisfaction check evaluated after all mechanical checks pass). `doneness.md` is a mode-conditioned verdict check (like verify.md and code-review.md), NOT a structural required artifact; its absence is governed solely by the Doneness Verdict Enforcement requirement — evaluated only when required and only as the sole remaining failure — and SHALL NOT trigger a cheap-phase missing-required-artifact short-circuit. `design-fidelity.md` is likewise a design-conditioned verdict check, NOT a structural required artifact: its absence, staleness, or failure is governed solely by the Design Fidelity Verdict Enforcement requirement (required only WHERE the change carries design.md), it occupies the design-fidelity slot in the guidance order above, and it SHALL NOT trigger a cheap-phase missing-required-artifact short-circuit

#### Scenario: Design-fidelity guidance slots before tasks
- **WHILE** a design-bearing change has no sealed design-fidelity.md and tasks.md is also absent
- **WHEN** opsx gate emits its report
- **THEN** the design-fidelity failure SHALL be reported ahead of the tasks failure, so an autonomous first-red-wins consumer seals the fidelity verdict before generating tasks

#### Scenario: Structural validation is per artifact type
- **WHEN** opsx gate validates an artifact
- **THEN** it SHALL apply `openspec validate --strict` to OpenSpec-tracked artifacts and the artifact's own documented field checks to skill-managed artifacts (verify.md, code-review.md, doneness.md, design-fidelity.md), and SHALL NOT apply `openspec validate --strict` to artifacts OpenSpec does not track

### Requirement: Manifest Validation Execution

WHERE an `openspec/opsx-gates.yaml` manifest exists, THE opsx gate command SHALL execute each declared gate command and SHALL treat a non-zero exit from a `required: true` command as a failed check; and WHERE the `OPSX_VALIDATE` environment value supplies additional commands, it SHALL execute those as well. THE opsx gate command SHALL run every validation command with the working directory set to the located implementation worktree (worktree execution is the only model) and SHALL export `OPSX_CHANGE`, `OPSX_CHANGE_DIR`, `OPSX_WORKTREE`, `OPSX_DIFF_BASE`, and `OPSX_HEAD`, so validations run against the same checkout whose verdict freshness is computed.

#### Scenario: Validations run in the located worktree
- **WHEN** opsx gate reaches the validation stage
- **THEN** each command SHALL run with cwd set to the located worktree and the `OPSX_*` variables exported, and IF no valid worktree can be located for a change past its Diff Base capture THEN opsx gate SHALL fail before running any validation command (before capture, the missing-artifact guidance governs — the no-worktree state is not misreported)

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

THE opsx gate command SHALL require verify.md and code-review.md to record the immutable `Diff Base SHA` and the implementation HEAD they were produced against, plus a reviewer-provenance field, and SHALL treat a verdict as failed if the recorded range does not equal `Diff Base SHA..<implementation-HEAD>` recomputed from the worktree opsx gate locates, so an agent cannot mark a verdict pass and then continue mutating the diff. WHEN Code Review Mode is gating-required, code-review.md SHALL additionally carry an own-line `**Attested HEAD:**` field — the reviewer-attested tree HEAD — whose value SHALL be a full 40-hex SHA literal (any other form, including a short SHA or a symbolic ref such as `HEAD`, is unparseable) equal to the full SHA the gate computes for the recorded Reviewed Range head; an absent or unparseable `Attested HEAD` SHALL be a failed check, never a pass (fail-closed). The same attestation binding SHALL apply to doneness.md WHEN the doneness verdict is required and was produced by the independently dispatched full_rigor judge. FOR design-fidelity.md WHEN required, the `Attested HEAD` binding SHALL be the integration-checkout HEAD the judgment was dispatched against (fidelity is judged before worktree creation, so there is no Reviewed Range or implementation HEAD to bind); fidelity's freshness mechanism is its digest bindings, not a range recompute. Attestation SHALL be enforced only where a verdict artifact is evaluated by the gate (active changes) — archived changes are never re-gated. WHEN the recorded Worktree Path locator is absent, empty, or fails validation, THE gate SHALL probe the canonical convention path and use it iff valid; WHEN locator and convention path both fail for a change past Diff Base capture, THE gate SHALL fail the verdict evaluation loudly (Worktree Mandatory Gate Enforcement) rather than proceeding without a worktree.

#### Scenario: Worktree located deterministically with convention fallback
- **WHEN** opsx gate needs the implementation HEAD
- **THEN** it SHALL locate the change's worktree from the `Worktree Path` recorded in review.md (validating it is a git worktree on branch `opsx/<change>`), or accept an explicit `--worktree <path>`; IF the recorded locator is absent, empty, or fails validation, THEN it SHALL probe the canonical `opsx worktree` convention path and use it iff that path is a valid git worktree on branch `opsx/<change>`; when locator and convention path both fail for a change past Diff Base capture it SHALL fail the verdict evaluation loudly naming the missing worktree

#### Scenario: Stale verdict fails the gate
- **WHILE** code-review.md or verify.md records a reviewed range
- **IF** that recorded `Diff Base SHA..HEAD` range does not equal the range opsx gate recomputes from the located worktree HEAD
- **THEN** opsx gate SHALL report the verdict as stale, fail that check, and exit non-zero

#### Scenario: Provenance is adapter-stamped, not agent-written
- **WHEN** opsx gate reads a code-review.md verdict under gating-required
- **THEN** the file SHALL carry a reviewer-provenance field stamped by the subagent-dispatch adapter (identifying the review subagent and `review_mode`), and a verdict lacking that field, or whose `review_mode` is `degraded-single-model` on a change that triggers Constitution IX, SHALL be treated as a failed check

#### Scenario: Attested HEAD required and bound under gating-required
- **WHILE** Code Review Mode is gating-required
- **IF** code-review.md omits `**Attested HEAD:**`, or its value is not a full 40-hex SHA literal, or that literal does not equal the full SHA of the recorded Reviewed Range head
- **THEN** opsx gate SHALL report the code-review check as failed and exit non-zero

#### Scenario: Symbolic or short attestation is unparseable
- **WHILE** Code Review Mode is gating-required
- **IF** code-review.md records `Attested HEAD` as a symbolic ref (e.g. `HEAD`) or a short SHA
- **THEN** opsx gate SHALL treat the field as unparseable and fail the check, never resolving the symbol in the located worktree

#### Scenario: Matching attestation passes
- **WHILE** Code Review Mode is gating-required
- **WHEN** code-review.md carries `**Attested HEAD:**` as a full 40-hex literal equal to the Reviewed Range head's full SHA (alongside the existing freshness and provenance requirements)
- **THEN** the attestation binding SHALL NOT fail the code-review check

#### Scenario: Attestation not demanded where code review is advisory
- **WHILE** Code Review Mode is advisory or none
- **WHEN** opsx gate evaluates the code-review check
- **THEN** a missing `Attested HEAD` SHALL NOT by itself cause a non-zero exit

#### Scenario: Independent-judge doneness carries the binding
- **WHILE** doneness is required and `full_rigor` is true (independently dispatched judge)
- **IF** doneness.md omits `**Attested HEAD:**` or its value is not a full 40-hex literal equal to the recorded Diff Base–bound implementation HEAD it judged
- **THEN** opsx gate SHALL report the doneness check as failed and exit non-zero

#### Scenario: Fidelity attestation binds to the integration-checkout HEAD, not a range
- **WHILE** a design-bearing change requires design-fidelity.md
- **WHEN** opsx gate evaluates the fidelity artifact's `Attested HEAD`
- **THEN** the gate SHALL require a full 40-hex literal (unparseable otherwise, fail-closed) recording the integration-checkout HEAD at judgment, SHALL NOT demand equality with any Reviewed Range head (no worktree or implementation HEAD exists at fidelity-seal time), and staleness SHALL be carried by the digest bindings alone — the field is provenance for audit; tree-identity discrimination for fidelity lives at seal time via Reviewer Tree Identity Attestation, not at the gate

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

THE archive/land path SHALL require that `merge-base(opsx/<change>, <integration branch>)` equals the current integration-branch HEAD before landing or archiving a change, where the integration branch is obtained via the deterministic resolver (`opsx-cli` `Integration Branch Resolution` — committed review.md locator field, then `origin/HEAD`, then `main`, then `master`, else loud failure), computed with deterministic git plumbing (no language-model judgment), so a change built on a stale base cannot land over intervening integration-branch commits; WHEN the merge-base is not equal to the integration-branch HEAD, the archive/land SHALL be refused with a failure message that names the resolved branch and the rebase remedy (rebase `opsx/<change>` onto the resolved branch's HEAD, which staleness-fires a fresh review) rather than proceeding. WHERE no `opsx/<change>` branch exists, the precondition SHALL FAIL naming the worktree-mandatory execution model and the remedy (`opsx worktree ensure <change>`) — a change is never landed from commits made directly on the integration checkout.

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

#### Scenario: Missing branch refuses landing under worktree-mandatory
- **IF** no `opsx/<change>` branch exists when the archive/land path evaluates the base-currency precondition
- **THEN** the precondition SHALL fail with a message naming worktree-mandatory execution and the `opsx worktree ensure <change>` remedy, and the change SHALL NOT be archived

#### Scenario: Non-main default branch passes when current
- **WHILE** the repository's integration branch resolves to a name other than `main` (e.g. `trunk`) AND `merge-base(opsx/<change>, trunk)` equals `trunk` HEAD
- **WHEN** the archive/land path evaluates the base-currency precondition
- **THEN** the precondition SHALL pass rather than failing because no `main` branch exists

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

### Requirement: Migration Sweep Gate Check

WHERE a change directory contains a `sweep.txt` declaration, THE `opsx gate` SHALL run the migration-completeness sweep as one of its cheap deterministic checks, grepping the SAME resolved artifact root the gate resolves for its other checks (the validated `opsx/<change>` worktree — worktree execution is the only model; WHEN no valid worktree can be located for a change past its Diff Base capture, the sweep check fails loudly naming the missing worktree, mirroring Worktree Mandatory Gate Enforcement), and SHALL emit a `GATE-FAIL sweep` line when the sweep reports hits, and WHERE no declaration exists the gate SHALL NOT run or require the sweep, so undeclared changes are unaffected.

#### Scenario: Declared sweep enforced by the gate
- **WHEN** a change with a sweep.txt has a declared pattern matching a shipped surface
- **THEN** opsx gate SHALL fail with a GATE-FAIL sweep line naming the check

#### Scenario: Clean declared sweep passes the gate check
- **WHEN** a change with a sweep.txt has no pattern hits
- **THEN** the sweep check SHALL pass and not appear as a GATE-FAIL

#### Scenario: Undeclared changes unaffected
- **IF** a change has no sweep.txt
- **THEN** the gate SHALL run no sweep check for it and its exit code SHALL be unaffected

#### Scenario: Sweep reads the resolved worktree
- **WHILE** the sweep-relevant fixes exist only on the worktree branch
- **WHEN** opsx gate runs with the worktree resolved
- **THEN** the sweep check SHALL grep the worktree's tracked files and pass, never false-failing against the integration root's stale copies

### Requirement: Project Artifact Preflight

THE `opsx gate` SHALL require that `openspec/constitution.md` and `openspec/domain.md` both exist and are non-empty — size greater than zero bytes, `test -s` semantics (clarify C2) — in the integration checkout, at EVERY Scale (XS, S, and M, with or without `full_rigor`), and IF either file is absent or empty, THEN the gate SHALL fail closed with a directive naming the shipped scaffolding templates (`constitution-template.md` and `domain-template.md` under the opsx-superpowers schema templates directory) as the remedy; the gate SHALL NOT auto-scaffold either file and SHALL offer NO waiver key for this check. The check SHALL be a deterministic file-existence/size test with no model call.

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

### Requirement: Design Fidelity Verdict Enforcement

WHERE a change carries a `design.md`, THE opsx gate command SHALL require a sealed `design-fidelity.md` verdict artifact — at every Scale, with no waiver key — carrying an own-line `**Fidelity:**` field (`delivered | violated`), a judge-provenance field stamped by the subagent-dispatch adapter whose `review_mode` SHALL be a blind-dispatch mode (`blind-single-judge | adversarial-multimodel`) — a `degraded-single-model` or otherwise inline/non-dispatched provenance SHALL fail the check (doneness parity), an `**Attested HEAD:**` field per the attestation binding, and digest-binding fields recording the sha256 of intent.md, design.md, and EVERY delta spec file under `specs/`; THE gate SHALL read the design-fidelity.md artifact AND its recorded fields from, and SHALL recompute each recorded digest against, the COMMITTED tree content of the change directory `openspec/changes/<change>/` in the integration checkout — the repository's main worktree, resolved deterministically with git plumbing and addressed explicitly (`git -C <main-root> show HEAD:…`-equivalent, never a cwd-relative read, never the gate's invocation cwd when that cwd is a change worktree, and never the worktree-reassigned artifact root the range-freshness locator resolves; one committed tree of record for both the artifact fields and the hash inputs, so an uncommitted `Fidelity` flip or input edit can never move the check in either direction) — SHALL enumerate the actual set of `specs/**/spec.md` files under the change directory and treat the check as failed WHEN that set differs from the set of recorded digest fields (a delta spec file added or removed after sealing), and SHALL treat the check as failed WHEN the artifact is absent, any recorded digest does not equal the recomputed digest (stale — edit means re-judge), the `Fidelity` value is `violated` with no human-waiver field, or any required field is absent or unparseable (fail-closed, never a permissive default). WHILE the `Fidelity` value is `violated` AND a non-empty human-waiver field naming the human ruling AND its decision-audit landing entry is present (written only at the decision-audit landing, per the escalation valve), THE gate SHALL treat the fidelity check as satisfied (waived) — the deterministic analogue of `doneness_mode: waived` plus rationale — with the digest bindings, the spec-file set-equality check, and the fail-closed parsing rules still enforced identically for waived seals, so a waiver does not survive post-waiver edits or a post-waiver delta-spec-file addition/removal. The check SHALL be deterministic and model-free: field parsing plus sha256 recomputation only, and digest field keys SHALL be located by literal string comparison against lines constructed from the enumerated spec-file set — never by interpolating path text into an unescaped regular expression (paths carry `(`, `)`, `.`, `/`). WHERE the change has no `design.md`, the check SHALL NOT be required. A human waiver recorded in the artifact after the escalation-valve procedure (opsx-adversarial-review Design Fidelity Judge) SHALL be readable as a distinct own-line field naming the human ruling — never a self-authored `delivered`.

#### Scenario: Design-bearing change without fidelity verdict fails
- **WHILE** the change contains design.md
- **IF** design-fidelity.md is absent
- **THEN** opsx gate SHALL report the design-fidelity check as failed and exit non-zero

#### Scenario: Delivered verdict with matching digests passes
- **WHILE** design-fidelity.md records `Fidelity: delivered`, judge provenance, a bound attestation, and digests equal to the recomputed sha256 of intent.md, design.md, and every delta spec file
- **WHEN** opsx gate evaluates the design-fidelity check
- **THEN** the check SHALL pass

#### Scenario: Digest mismatch stales the verdict
- **IF** intent.md, design.md, or any delta spec file is edited after sealing so a recorded digest no longer equals the recomputed digest
- **THEN** opsx gate SHALL report the design-fidelity verdict as stale and exit non-zero until a fresh full-sweep re-judgment is sealed

#### Scenario: Violated verdict fails the gate
- **WHILE** design-fidelity.md records `Fidelity: violated` with no human-waiver field
- **THEN** opsx gate SHALL report the design-fidelity check as failed and exit non-zero

#### Scenario: Human waiver satisfies the check deterministically
- **WHILE** design-fidelity.md records `Fidelity: violated` AND a non-empty human-waiver field naming the ruling recorded at the decision-audit landing
- **WHEN** opsx gate evaluates the design-fidelity check with all recorded digests matching their recomputation and the enumerated spec-file set equal to the recorded digest-field set
- **THEN** the check SHALL be treated as satisfied (waived), and a subsequent edit to intent.md, design.md, or any delta spec file — or the addition or removal of a delta spec file — SHALL stale the waived verdict like any other seal

#### Scenario: New delta spec file after seal stales the verdict
- **WHILE** design-fidelity.md is sealed with digest fields for the then-present delta spec files
- **IF** a new `specs/**/spec.md` file is added under the change directory (or a recorded one is removed) after sealing
- **THEN** opsx gate SHALL report the fidelity check as failed because the enumerated file set differs from the recorded digest-field set — an AC set change always forces a fresh full-sweep re-judgment

#### Scenario: Digests recomputed from the integration checkout
- **WHEN** opsx gate recomputes the fidelity digest bindings — including when it is invoked from inside a change worktree
- **THEN** it SHALL hash intent.md, design.md, and the delta spec files from the COMMITTED content of `openspec/changes/<change>/` under the repository's main-worktree root (resolved via git plumbing, e.g. the first entry of `git worktree list --porcelain`, and addressed with an explicit `-C <main-root>` tree qualifier), independent of the worktree locator used for range freshness, of any worktree-reassigned artifact root, and of uncommitted working-tree edits (change-dir artifacts are committed on the integration checkout; the worktree may hold stale or absent copies)

#### Scenario: No design.md means no fidelity requirement
- **WHILE** the change contains no design.md
- **WHEN** opsx gate runs
- **THEN** the absence of design-fidelity.md SHALL NOT be a failed check

#### Scenario: Unparseable fidelity artifact fails closed
- **IF** design-fidelity.md exists but omits the `Fidelity` field, records a value outside `delivered | violated` without a human-waiver field, records `Fidelity: violated` with a present-but-EMPTY human-waiver field, omits a digest-binding field, or carries a judge-provenance `review_mode` outside `blind-single-judge | adversarial-multimodel` (inline/degraded judgment)
- **THEN** opsx gate SHALL treat the check as failed rather than assuming a permissive value — an empty waiver field never waives and an inline self-judgment never seals

#### Scenario: Fidelity artifact and fields read from the main root
- **WHILE** an `opsx/<change>` worktree exists and the gate has located it for range freshness
- **WHEN** the gate evaluates the design-fidelity check
- **THEN** it SHALL read design-fidelity.md and every recorded field from the COMMITTED main-worktree change-directory content — never the worktree-reassigned artifact root, never live disk — so a post-worktree re-seal committed on the integration checkout is evaluated against itself, a stale worktree copy can neither pass nor permanently redden the check, and an uncommitted verdict-field flip is invisible to the gate

### Requirement: Worktree Mandatory Gate Enforcement

THE opsx gate command SHALL treat worktree execution as the only execution model at every Scale: a `worktree_mode` key declared in the front-matter of the COMMITTED integration-checkout review.md — the sole mode source the gate ever reads; a divergent worktree-branch copy of review.md is never consulted for modes, and a stray worktree-branch commit touching it is surfaced by the misplaced-bookkeeping staling backstop — SHALL be a failed check whose message names the key's removal and the remedy (delete the key; the workflow is worktree-always), and WHEN the gate cannot locate a valid worktree for an active change past its Diff Base capture (recorded locator invalid AND convention path invalid), it SHALL fail the affected verdict checks loudly naming the missing worktree rather than silently evaluating the integration checkout as the implementation tree.

#### Scenario: Declared worktree_mode key fails closed
- **IF** review.md front-matter carries a `worktree_mode` KEY with any value — detected by front-matter key parsing (first-colon key extraction), never by substring grep, so a YAML comment mentioning `worktree_mode` never trips the check
- **THEN** opsx gate SHALL report a failed check naming the key's removal and the delete-the-key remedy, and exit non-zero

#### Scenario: Missing worktree fails loudly after capture
- **WHILE** the change records a Diff Base SHA in its locator
- **IF** neither the recorded Worktree Path nor the convention path validates as a git worktree on branch `opsx/<change>`
- **THEN** the gate SHALL fail the verdict-freshness evaluation naming the missing worktree, never falling back to the integration checkout HEAD

#### Scenario: Key-less tier-default same-tree change fails with the re-home remedy
- **WHILE** a change authored before this deployment recorded a same-tree-shaped locator by tier default — a `Diff Base SHA` present, `Worktree Path` empty, and no `opsx/<change>` branch — without ever declaring a `worktree_mode` key
- **WHEN** opsx gate evaluates its verdict checks
- **THEN** the gate SHALL fail those checks naming the missing worktree and the re-home remedy (`opsx worktree ensure <change>`, re-review), never silently resolving the implementation HEAD to the integration checkout HEAD

### Requirement: Post Seal Bookkeeping Non Staling

THE workflow SHALL permit orchestrator bookkeeping after a verdict artifact is sealed at the final reviewed head — setting/clearing the loop landing signal (`loop_hold`) on the integration-checkout review.md, routing findings to `follow-ups.md`, and appending Execution-Notes-class entries — WITHOUT staling any sealed verdict, BECAUSE sealed verdicts are bound to the `opsx/<change>` worktree branch HEAD which bookkeeping commits on the integration checkout never move; AND any file content the gate reads for verdict or mode decisions SHALL remain protected — the gate SHALL NOT allowlist review.md wholesale; THE gate SHALL source review.md front-matter mode fields — ALL front-matter switchboard fields the gate reads, including `scale` and `full_rigor` — from the COMMITTED tree content of the integration checkout (`git -C <main-root> show HEAD:openspec/changes/<change>/review.md`-equivalent, one source for every front-matter decision input), never live working-tree content, so an uncommitted edit to a gate-read mode field can never flip a gate decision; and a post-seal edit to gate-read decision inputs that feed an already-sealed verdict evaluation SHALL still fail closed or stale per the existing freshness rules. A COMMITTED mode change is an ordinary auditable bookkeeping-class commit — a self-authored post-seal downgrade (e.g. `doneness_mode: required → waived`) is the same integrity-breach class as a self-authored waiver, surfaced by history audit rather than sandboxing (non-goal).

#### Scenario: Post-seal landing signal stales nothing
- **WHILE** code-review.md is sealed `pass` at the worktree branch HEAD
- **WHEN** the orchestrator commits `loop_hold: true` with a reason to the integration-checkout review.md
- **THEN** no gate check that was green before the commit SHALL turn red

#### Scenario: Post-seal follow-up routing stales nothing
- **WHILE** verdicts are sealed at the worktree branch HEAD
- **WHEN** the orchestrator commits a follow-ups.md entry on the integration checkout
- **THEN** the sealed verdicts SHALL remain fresh and the gate SHALL remain green

#### Scenario: Uncommitted mode edit never drives the gate
- **WHILE** the committed review.md front-matter declares `doneness_mode: required`
- **IF** an uncommitted working-tree edit changes it to `waived` with a rationale
- **THEN** opsx gate SHALL evaluate the committed value — still requiring the doneness verdict — because mode fields are read from committed content only, never live disk

