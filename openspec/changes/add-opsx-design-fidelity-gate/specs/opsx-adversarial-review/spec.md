# opsx-adversarial-review (delta)

## ADDED Requirements

### Requirement: Design Fidelity Judge

WHERE a change carries a `design.md`, THE workflow SHALL obtain a blind design-fidelity judgment BEFORE tasks generation: for EVERY delta acceptance criterion of the change, the judge SHALL answer whether the design mechanism cited (or discoverable) for that AC semantically entails the AC's guarantee AS WRITTEN, recording one verdict row per AC — `entailed | not-entailed | not-covered` — with evidence; an AC whose only design coverage is a nominal citation to a section that does not address the guarantee SHALL be `not-covered`. THE judge SHALL apply a bounded contract mirroring the baseline-bounded reviewer contract: a `not-entailed`/`not-covered` row blocks ONLY on clear non-entailment of the AC as written; WHERE the AC's guarantee is ambiguous, the judge SHALL route an advisory clarify-class finding instead of blocking. Intent-mandate violations (a design decision rejecting or weakening something the frozen intent mandates) and rationale↔mechanism contradictions within a design decision ARE in scope and fall out of the per-AC sweep as evidence. Dispatch channel: WHILE `full_rigor: true`, the fidelity judgment SHALL ride the existing blind analyze dispatch as a REQUIRED section of that dispatch, with the verdict STILL sealed to the separate `design-fidelity.md`; at plain Scale M or a design-bearing Scale S/XS, one narrow post-design blind mini-dispatch SHALL produce the same sealed artifact. Re-judgments SHALL be full sweeps (never delta-scoped, no cross-round finding matching). The fidelity dispatch SHALL follow the reviewer tree-identity attestation and read-only dispatch window protocols under the pre-worktree carve-out: fidelity is judged before worktree creation, so the dispatched tree IS the integration checkout and the judge attests its HEAD and root (Reviewer Tree Identity Attestation, pre-worktree dispatches). Each sealed fidelity verdict SHALL be recorded as a round-ledger entry in the `Fidelity Round Ledger` section of review.md (the fidelity-type host defined by Orchestrator Round Ledger — append-only, present at every Scale, available pre-worktree, orchestrator-sealed), and THE escalation valve SHALL count consecutive `violated` entries from that ledger — persisting across sessions and across design-fidelity.md re-seals — not from any state inside the re-sealed artifact. WHEN two consecutive sealed `violated` verdicts land — regardless of which rows failed; no per-row cross-round comparison is performed, consistent with the full-sweep rule — THE orchestrator SHALL route to the decision-audit landing for a human ruling rather than looping unbounded; a human waiver SHALL be recorded in the artifact by the ruling, never self-authored.

#### Scenario: Oxide D3 shape judged not-entailed
- **WHILE** a delta AC guarantees a structural property ("safe by construction") and the design's cited mechanism is manual per-site handling
- **WHEN** the fidelity judge sweeps that AC
- **THEN** the row SHALL be `not-entailed` with evidence naming the mechanism/guarantee gap, and the overall verdict SHALL be `violated`

#### Scenario: Nominal citation is not coverage
- **WHILE** an AC cites a design section that does not substantively address the AC's guarantee
- **WHEN** the judge sweeps that AC
- **THEN** the row SHALL be `not-covered`, not `entailed`

#### Scenario: Ambiguous guarantee routes to clarify, not a block
- **WHILE** an AC's guarantee admits materially divergent readings
- **WHEN** the judge cannot rule non-entailment for the AC as written
- **THEN** it SHALL record an advisory clarify-class finding for that AC rather than a blocking `not-entailed` row

#### Scenario: full_rigor rides the analyze dispatch
- **WHILE** the change declares `full_rigor: true`
- **WHEN** the blind analyze dispatch runs
- **THEN** the dispatch SHALL include the fidelity sweep as a required section and the fidelity verdict SHALL be sealed to `design-fidelity.md` (separate from analyze.md)

#### Scenario: Plain-M design-bearing change gets the mini-dispatch
- **WHILE** the change is plain Scale M (no full_rigor) and carries design.md
- **WHEN** design authoring completes
- **THEN** a narrow blind fidelity mini-dispatch SHALL produce the sealed `design-fidelity.md` before tasks generation

#### Scenario: Escalation valve after two consecutive violated verdicts
- **IF** the round ledger records two consecutive sealed `violated` fidelity verdicts, regardless of which rows failed in each
- **THEN** the orchestrator SHALL route to the decision-audit landing with the fidelity history rather than dispatching a third judgment automatically, and SHALL NOT attempt per-row matching across the two sealed verdicts

#### Scenario: Valve count persists across sessions
- **WHILE** one sealed `violated` fidelity verdict is recorded in review.md's `Fidelity Round Ledger` section
- **WHEN** a fresh orchestrator session seals a second consecutive `violated`
- **THEN** the valve SHALL fire from the ledger's record — the count never resets merely because design-fidelity.md was re-sealed (a full-sweep re-seal overwrites the artifact, never the ledger) or the session restarted

### Requirement: Findings File Sole Verdict Source

FOR every reviewer/judge dispatch (code review, doneness, design fidelity, and judged clarify/analyze passes), THE orchestrator SHALL derive the verdict, the findings, and the attestation EXCLUSIVELY from the subagent's findings output file; the subagent's conversational reply SHALL never be a verdict input. A findings file that is absent, or lacks the required verdict line/fields, SHALL consolidate as INVALID (per the invalid-not-fail semantics: excluded from gating, the round ledger, and the round budget; incident recorded; re-dispatch or reviewer-set repair) regardless of any claim in the conversational reply.

#### Scenario: Reply claims pass but file is absent
- **IF** a dispatched reviewer's reply asserts a verdict while its findings output file is absent
- **THEN** the orchestrator SHALL consolidate that reviewer as INVALID, record the incident, and re-dispatch — never counting the reply's claim

#### Scenario: Reply contradicts the findings file
- **WHILE** a findings file records findings and a verdict
- **IF** the reviewer's conversational reply summarizes them differently
- **THEN** the orchestrator SHALL use the file's content exclusively and ignore the reply's characterization

#### Scenario: Verdict-less findings file is invalid
- **IF** a findings file exists but lacks the required verdict line or attestation fields
- **THEN** the orchestrator SHALL treat that reviewer as INVALID with the standard exclusions rather than inferring a verdict from partial content

## MODIFIED Requirements

### Requirement: Reviewer Tree Identity Attestation

THE blind reviewer/judge dispatch prompt SHALL require the subagent, BEFORE reviewing, to attest the tree it is actually executing in — record the verbatim output of `git rev-parse HEAD` (a full 40-hex SHA; any other form is a missing attestation) and of `git rev-parse --show-toplevel`, as machine-readable own-line fields at the top of its findings output (`Attested HEAD: <40-hex sha>` and `Attested Path: <toplevel path>`) — and THE orchestrator SHALL count a reviewer verdict toward gating ONLY WHEN the attested HEAD literal equals the full SHA of the dispatched range head AND the attested path, canonicalized (realpath), equals the canonicalized root of the dispatched tree. FOR post-implementation dispatches (code review, doneness) the dispatched tree is the change's `opsx/<change>` worktree — worktree execution is the only implementation model, so the path check always discriminates the reviewed worktree from the integration checkout and every other tree. FOR judgments dispatched before worktree creation (clarify, analyze, design fidelity — pre-worktree by definition), the dispatched tree IS the integration checkout: the attested path SHALL equal the canonicalized integration-checkout root and the attested HEAD SHALL equal the integration-checkout HEAD at dispatch — the HEAD check carries discrimination for those dispatches; this carve-out is scoped strictly to pre-worktree judgments and never applies once an `opsx/<change>` worktree exists for the dispatched purpose. A verdict with a missing or mismatched attestation SHALL be treated as INVALID — distinct from fail: it SHALL NOT satisfy multi-model gating, SHALL NOT enter the round ledger as a reviewer verdict, and SHALL NOT count toward the `review_max_rounds` trajectory — and the orchestrator SHALL record the incident and re-dispatch the reviewer (or repair the reviewer set) rather than sealing. WHEN two consecutive dispatch attempts of the same round yield NO countable verdict (all reviewers INVALID), THE orchestrator SHALL stop re-dispatching and route to the decision-audit landing with a dispatch-integrity error rather than retrying unbounded. WHEN sealing `code-review.md` (and `doneness.md` or `design-fidelity.md` when an independently dispatched judge produced them), THE orchestrator SHALL record the single `**Attested HEAD:**` value only when every counted reviewer's attestation matches it.

#### Scenario: Attestation preamble required in every dispatch
- **WHEN** a blind reviewer or judge subagent is dispatched
- **THEN** the dispatch prompt SHALL instruct it to record `Attested HEAD: <git rev-parse HEAD output>` and `Attested Path: <resolved working directory>` as its first findings-output lines before any review content

#### Scenario: Wrong-tree verdict is invalid, not fail
- **IF** a returned verdict's attested HEAD does not rev-parse equal to the dispatched range head, or its attested path does not resolve to the dispatched worktree root
- **THEN** the orchestrator SHALL treat the verdict as INVALID — excluded from multi-model gating, absent from the round ledger's reviewer verdicts, and not counted toward `review_max_rounds` — record the incident, and re-dispatch

#### Scenario: Integration-checkout path fails the attestation
- **IF** a reviewer dispatched against a change worktree (any post-implementation dispatch) attests the integration checkout's toplevel path
- **THEN** the verdict SHALL be INVALID — the path check discriminates unconditionally for post-implementation dispatches now that no same-tree mode exists

#### Scenario: Pre-worktree judgment attests the integration checkout
- **WHILE** a clarify, analyze, or design-fidelity judgment is dispatched before any `opsx/<change>` worktree exists
- **WHEN** the judge attests the integration checkout's HEAD and canonicalized root
- **THEN** the attestation SHALL be countable — the integration checkout is the dispatched tree for pre-worktree judgments, and the HEAD equality check carries the discrimination

#### Scenario: Pre-worktree judgment attesting the wrong tree is invalid
- **WHILE** a pre-worktree judgment is dispatched against the integration checkout at a recorded HEAD
- **IF** the returned attestation's HEAD does not equal the integration-checkout HEAD at dispatch, or its canonicalized path does not equal the integration-checkout root
- **THEN** the verdict SHALL be INVALID with the standard exclusions — the carve-out changes which tree is attested, never whether the equality checks discriminate

#### Scenario: Missing attestation is invalid
- **IF** a returned findings output carries no attestation fields, or an `Attested HEAD` that is not a full 40-hex SHA literal
- **THEN** the verdict SHALL be treated as INVALID with the same exclusions

#### Scenario: All-invalid rounds terminate at the landing
- **IF** two consecutive dispatch attempts of the same review round produce zero countable verdicts (every reviewer INVALID)
- **THEN** the orchestrator SHALL stop re-dispatching and route to the decision-audit landing with a dispatch-integrity error

#### Scenario: Sealed artifact carries the matched attestation
- **WHEN** the orchestrator seals code-review.md (or doneness.md / design-fidelity.md produced by an independently dispatched judge)
- **THEN** it SHALL record `**Attested HEAD:**` equal to the value every counted reviewer attested, and SHALL NOT seal while counted reviewers' attestations disagree

### Requirement: Read Only Reviewer Dispatch

THE orchestrator SHALL capture a deterministic snapshot immediately before dispatching a review round's reviewer/judge subagents and an identically captured snapshot immediately after the last of them returns — covering the REVIEWED WORKTREE and, WHEN the integration checkout is a different tree (the worktree-always norm), ALSO the integration checkout: each tree's `git rev-parse HEAD` plus its `git status --porcelain=v1` output with the change's own `openspec/changes/<change>/` paths excluded from the comparison (they are orchestrator-sealed bookkeeping, the only in-window writes permitted) — and THE orchestrator SHALL NOT write to either covered tree outside that exclusion while the round window is open. IF the snapshots differ in EITHER tree, mutation cannot be attributed among concurrently dispatched reviewers, so THE orchestrator SHALL treat ALL of that round's verdicts as INVALID (with the same exclusions as a mismatched attestation), restore the mutated tree to its pre-dispatch state surgically — `git restore` only tracked paths whose porcelain status changed across the window; delete only untracked paths present in the post-window snapshot and absent from the pre-window snapshot; NEVER a blanket `git clean` and NEVER ignored or pre-existing untracked state — and record the incident in the round ledger / Execution Notes before proceeding. The snapshot and restore SHALL use plain git commands only (deterministic, model-free).

#### Scenario: Reviewer mutation voids the round
- **IF** the post-window snapshot differs from the pre-window snapshot for a review round in the reviewed worktree (after excluding the change's own `openspec/changes/<change>/` paths)
- **THEN** all of that round's verdicts SHALL be INVALID, the tree SHALL be restored to the pre-dispatch state, and the incident SHALL be recorded

#### Scenario: Integration-checkout mutation also voids the round
- **WHILE** the reviewed worktree and the integration checkout are different trees
- **IF** the integration checkout's post-window snapshot differs from its pre-window snapshot (same change-dir exclusion discipline)
- **THEN** all of that round's verdicts SHALL be INVALID, the integration checkout SHALL be restored surgically, and the incident SHALL be recorded

#### Scenario: Restore is surgical
- **WHEN** the orchestrator restores after a snapshot delta
- **THEN** it SHALL `git restore` only tracked paths whose status changed across the window and delete only untracked paths introduced during the window, never pre-existing untracked or ignored state

#### Scenario: Clean dispatch counts normally
- **WHILE** the pre- and post-window snapshots are identical in every covered tree
- **WHEN** a verdict's attestation also matches
- **THEN** the verdict SHALL be counted normally toward gating and the ledger

### Requirement: Orchestrator Round Ledger

THE orchestrator SHALL maintain a per-review-type round ledger — round number, per-severity finding counts (P0/P1/P2/P3), per-reviewer verdicts, and the HEAD reviewed — sealed into the review artifact for that review type (code-review.md for post-apply diff-review rounds; an appended `Round Ledger` section of analyze.md for analyze-type gating rounds; an appended `Fidelity Round Ledger` section of review.md for design-fidelity judgment rounds — review.md exists at every Scale and before worktree creation, and a design-fidelity.md full-sweep re-seal overwrites that artifact so it can never host its own history), and the ledger, prior-round findings, and other reviewers' output SHALL NOT appear in any blind reviewer prompt. The `Fidelity Round Ledger` section SHALL be append-only orchestrator bookkeeping: sealing or re-sealing design-fidelity.md SHALL never remove or rewrite prior rows. A round's consolidated per-severity count SHALL be the maximum count reported by any single reviewer in that round (no cross-reviewer finding matching), so counts are deterministic and comparable across rounds without normalizing free-text findings.

#### Scenario: Ledger row per round
- **WHEN** a gating review round completes
- **THEN** the orchestrator SHALL append one ledger row recording the round number, the consolidated severity counts (max across reviewers per severity), each reviewer's verdict, and the reviewed HEAD SHA

#### Scenario: Blindness preserved
- **IF** a blind reviewer dispatch prompt would include the round ledger, prior-round findings, or another reviewer's output
- **THEN** the dispatch SHALL NOT proceed as a blind round; only the explicitly marked disclosure round may disclose findings

#### Scenario: Fidelity rounds ledger into review.md
- **WHEN** a design-fidelity judgment round seals (any overall verdict)
- **THEN** the orchestrator SHALL append one row to review.md's `Fidelity Round Ledger` section recording the round number, the sealed `Fidelity` value, each judge's verdict, and the attested integration-checkout HEAD — and a later design-fidelity.md re-seal SHALL NOT remove that row

### Requirement: Post Apply Code Review Artifact

WHILE Code Review Mode is advisory or gating-required, WHEN the implementation checks required before diff review are green (tasks complete, structural checks pass, required validation commands pass, and any retained-required verify is green), THE openspec-apply-change skill SHALL cause a `code-review.md` artifact to be produced by the review subagent (not self-authored by the orchestrator), reviewing the implemented diff against the change's intent and plan, distinct from the pre-implementation analyze review.

#### Scenario: Code review produced when pre-review checks are green
- **WHILE** Code Review Mode is advisory or gating-required
- **WHEN** tasks are complete, structural + required validation checks pass, and any retained-required verify is green
- **THEN** the review subagent SHALL author code-review.md (its body, Verdict, `Diff Base SHA`, reviewed range, `review_mode`, and adapter-stamped provenance field), and the orchestrator skill SHALL only trigger and collect it

#### Scenario: Gating-required does not deadlock under advisory verify
- **WHILE** Code Review Mode is gating-required and Verification Mode is retained-recommended or inline-only
- **WHEN** the pre-review checks (excluding the advisory verify) are green
- **THEN** code-review production SHALL still trigger, so the gate's code-review requirement cannot deadlock waiting on a verify state that the mode does not require

#### Scenario: None mode suppresses production
- **WHILE** Code Review Mode is none
- **WHEN** apply reaches a green verify state
- **THEN** the skill SHALL NOT produce code-review.md

#### Scenario: Diff base resolves from the worktree
- **WHEN** the code review computes its diff
- **THEN** the base SHALL be the immutable `Diff Base SHA` recorded in review.md, which apply sets at `opsx/<change>` worktree creation before the first implementation task — worktree execution is the only model, so no other diff-base source exists

#### Scenario: Review baseline is intent plus the full plan
- **WHEN** the code review is performed
- **THEN** the diff SHALL be judged against intent.md together with the proposal, specs, design, plan, and tasks status, so the reviewer can check the implementation followed the approved execution and verification path
