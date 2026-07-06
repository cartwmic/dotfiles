# opsx-gate-enforcement (delta)

## ADDED Requirements

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
- **IF** review.md front-matter carries a `worktree_mode` key with any value
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

THE workflow SHALL permit orchestrator bookkeeping after a verdict artifact is sealed at the final reviewed head — setting/clearing the loop landing signal (`loop_hold`) on the integration-checkout review.md, routing findings to `follow-ups.md`, and appending Execution-Notes-class entries — WITHOUT staling any sealed verdict, BECAUSE sealed verdicts are bound to the `opsx/<change>` worktree branch HEAD which bookkeeping commits on the integration checkout never move; AND any file content the gate reads for verdict or mode decisions SHALL remain protected — the gate SHALL NOT allowlist review.md wholesale; THE gate SHALL source review.md front-matter mode fields from the COMMITTED tree content of the integration checkout (`git show HEAD:openspec/changes/<change>/review.md`-equivalent), never live working-tree content, so an uncommitted edit to a gate-read mode field can never flip a gate decision; and a post-seal edit to gate-read decision inputs that feed an already-sealed verdict evaluation SHALL still fail closed or stale per the existing freshness rules. A COMMITTED mode change is an ordinary auditable bookkeeping-class commit — a self-authored post-seal downgrade (e.g. `doneness_mode: required → waived`) is the same integrity-breach class as a self-authored waiver, surfaced by history audit rather than sandboxing (non-goal).

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
