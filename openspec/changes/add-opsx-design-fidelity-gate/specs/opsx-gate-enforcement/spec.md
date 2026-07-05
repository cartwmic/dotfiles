# opsx-gate-enforcement (delta)

## ADDED Requirements

### Requirement: Design Fidelity Verdict Enforcement

WHERE a change carries a `design.md`, THE opsx gate command SHALL require a sealed `design-fidelity.md` verdict artifact — at every Scale, with no waiver key — carrying an own-line `**Fidelity:**` field (`delivered | violated`), a judge-provenance field stamped by the subagent-dispatch adapter, an `**Attested HEAD:**` field per the attestation binding, and digest-binding fields recording the sha256 of intent.md, design.md, and EVERY delta spec file under `specs/`; THE gate SHALL recompute each recorded digest from the change directory `openspec/changes/<change>/` in the integration checkout (the tree opsx gate is invoked from) — never from the worktree the range-freshness locator resolves — SHALL enumerate the actual set of `specs/**/spec.md` files under the change directory and treat the check as failed WHEN that set differs from the set of recorded digest fields (a delta spec file added or removed after sealing), and SHALL treat the check as failed WHEN the artifact is absent, any recorded digest does not equal the recomputed digest (stale — edit means re-judge), the `Fidelity` value is `violated` with no human-waiver field, or any required field is absent or unparseable (fail-closed, never a permissive default). WHILE the `Fidelity` value is `violated` AND a non-empty human-waiver field naming the human ruling is present (written only at the decision-audit landing, per the escalation valve), THE gate SHALL treat the fidelity check as satisfied (waived) — the deterministic analogue of `doneness_mode: waived` plus rationale — with the digest bindings still enforced, so a waiver does not survive post-waiver edits. The check SHALL be deterministic and model-free: field parsing plus sha256 recomputation only. WHERE the change has no `design.md`, the check SHALL NOT be required. A human waiver recorded in the artifact after the escalation-valve procedure (opsx-adversarial-review Design Fidelity Judge) SHALL be readable as a distinct own-line field naming the human ruling — never a self-authored `delivered`.

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
- **WHEN** opsx gate evaluates the design-fidelity check with all recorded digests matching their recomputation
- **THEN** the check SHALL be treated as satisfied (waived), and a subsequent edit to intent.md, design.md, or any delta spec file SHALL stale the waived verdict like any other seal

#### Scenario: New delta spec file after seal stales the verdict
- **WHILE** design-fidelity.md is sealed with digest fields for the then-present delta spec files
- **IF** a new `specs/**/spec.md` file is added under the change directory (or a recorded one is removed) after sealing
- **THEN** opsx gate SHALL report the fidelity check as failed because the enumerated file set differs from the recorded digest-field set — an AC set change always forces a fresh full-sweep re-judgment

#### Scenario: Digests recomputed from the integration checkout
- **WHEN** opsx gate recomputes the fidelity digest bindings
- **THEN** it SHALL hash intent.md, design.md, and the delta spec files from `openspec/changes/<change>/` in the integration checkout it is invoked from, independent of the worktree locator used for range freshness (change-dir artifacts are committed on the integration checkout; the worktree may hold stale or absent copies)

#### Scenario: No design.md means no fidelity requirement
- **WHILE** the change contains no design.md
- **WHEN** opsx gate runs
- **THEN** the absence of design-fidelity.md SHALL NOT be a failed check

#### Scenario: Unparseable fidelity artifact fails closed
- **IF** design-fidelity.md exists but omits the `Fidelity` field, records a value outside `delivered | violated` without a human-waiver field, or omits a digest-binding field
- **THEN** opsx gate SHALL treat the check as failed rather than assuming a permissive value

### Requirement: Worktree Mandatory Gate Enforcement

THE opsx gate command SHALL treat worktree execution as the only execution model at every Scale: a review.md front-matter declaring a `worktree_mode` key SHALL be a failed check whose message names the key's removal and the remedy (delete the key; the workflow is worktree-always), and WHEN the gate cannot locate a valid worktree for an active change past its Diff Base capture (recorded locator invalid AND convention path invalid), it SHALL fail the affected verdict checks loudly naming the missing worktree rather than silently evaluating the integration checkout as the implementation tree.

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

THE workflow SHALL permit orchestrator bookkeeping after a verdict artifact is sealed at the final reviewed head — setting/clearing the loop landing signal (`loop_hold`) on the integration-checkout review.md, routing findings to `follow-ups.md`, and appending Execution-Notes-class entries — WITHOUT staling any sealed verdict, BECAUSE sealed verdicts are bound to the `opsx/<change>` worktree branch HEAD which bookkeeping commits on the integration checkout never move; AND any file content the gate reads for verdict or mode decisions SHALL remain protected — the gate SHALL NOT allowlist review.md wholesale, and a post-seal edit to gate-read decision inputs that feed an already-sealed verdict evaluation SHALL still fail closed or stale per the existing freshness rules.

#### Scenario: Post-seal landing signal stales nothing
- **WHILE** code-review.md is sealed `pass` at the worktree branch HEAD
- **WHEN** the orchestrator commits `loop_hold: true` with a reason to the integration-checkout review.md
- **THEN** no gate check that was green before the commit SHALL turn red

#### Scenario: Post-seal follow-up routing stales nothing
- **WHILE** verdicts are sealed at the worktree branch HEAD
- **WHEN** the orchestrator commits a follow-ups.md entry on the integration checkout
- **THEN** the sealed verdicts SHALL remain fresh and the gate SHALL remain green

## MODIFIED Requirements

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
- **THEN** the gate SHALL require a full 40-hex literal (unparseable otherwise, fail-closed) recording the integration-checkout HEAD at judgment, SHALL NOT demand equality with any Reviewed Range head (no worktree or implementation HEAD exists at fidelity-seal time), and staleness SHALL be carried by the digest bindings alone

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
