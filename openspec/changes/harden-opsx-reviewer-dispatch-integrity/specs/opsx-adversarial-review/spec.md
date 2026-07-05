# opsx-adversarial-review (delta)

## ADDED Requirements

### Requirement: Reviewer Tree Identity Attestation

THE blind reviewer/judge dispatch prompt SHALL require the subagent, BEFORE reviewing, to attest the tree it is actually executing in — run `git rev-parse HEAD` and resolve its working directory, and record both as machine-readable own-line fields at the top of its findings output (`Attested HEAD: <sha>` and `Attested Path: <absolute path>`) — and THE orchestrator SHALL count a reviewer verdict toward gating ONLY WHEN the attested HEAD rev-parses equal to the dispatched range head AND the attested path resolves to the dispatched tree. A verdict with a missing or mismatched attestation SHALL be treated as INVALID — distinct from fail: it SHALL NOT satisfy multi-model gating, SHALL NOT enter the round ledger as a reviewer verdict, and SHALL NOT count toward the `review_max_rounds` trajectory — and the orchestrator SHALL record the incident and re-dispatch the reviewer (or repair the reviewer set) rather than sealing. WHEN sealing `code-review.md` (and `doneness.md` when an independently dispatched judge produced it), THE orchestrator SHALL record the single `**Attested HEAD:**` value only when every counted reviewer's attestation matches it.

#### Scenario: Attestation preamble required in every dispatch
- **WHEN** a blind reviewer or judge subagent is dispatched
- **THEN** the dispatch prompt SHALL instruct it to record `Attested HEAD: <git rev-parse HEAD output>` and `Attested Path: <resolved working directory>` as its first findings-output lines before any review content

#### Scenario: Wrong-tree verdict is invalid, not fail
- **IF** a returned verdict's attested HEAD does not rev-parse equal to the dispatched range head, or its attested path does not resolve to the dispatched tree
- **THEN** the orchestrator SHALL treat the verdict as INVALID — excluded from multi-model gating, absent from the round ledger's reviewer verdicts, and not counted toward `review_max_rounds` — record the incident, and re-dispatch

#### Scenario: Missing attestation is invalid
- **IF** a returned findings output carries no attestation fields
- **THEN** the verdict SHALL be treated as INVALID with the same exclusions

#### Scenario: Sealed artifact carries the matched attestation
- **WHEN** the orchestrator seals code-review.md (or doneness.md produced by an independently dispatched judge)
- **THEN** it SHALL record `**Attested HEAD:**` equal to the value every counted reviewer attested, and SHALL NOT seal while counted reviewers' attestations disagree

### Requirement: Read Only Reviewer Dispatch

THE orchestrator SHALL capture a deterministic snapshot of the reviewed tree immediately before each blind reviewer/judge dispatch — the tree's `git rev-parse HEAD` plus its full `git status --porcelain=v1` output — and compare an identically captured snapshot immediately after the subagent returns. IF the snapshots differ, THE orchestrator SHALL treat that reviewer's verdict as INVALID (with the same exclusions as a mismatched attestation), restore the reviewed tree to its pre-dispatch state (restore tracked modifications; delete untracked paths introduced by the delta), and record the incident in the round ledger / Execution Notes before proceeding. The snapshot and restore SHALL use plain git commands only (deterministic, model-free) and SHALL work in both worktree and same-tree modes.

#### Scenario: Reviewer mutation voids the verdict
- **IF** the post-dispatch snapshot differs from the pre-dispatch snapshot for a reviewer dispatch
- **THEN** that reviewer's verdict SHALL be INVALID, the tree SHALL be restored to the pre-dispatch state, and the incident SHALL be recorded

#### Scenario: Clean dispatch counts normally
- **WHILE** the pre- and post-dispatch snapshots are identical
- **WHEN** the verdict's attestation also matches
- **THEN** the verdict SHALL be counted normally toward gating and the ledger

#### Scenario: Deterministic in both tree modes
- **WHEN** the snapshot is captured for a same-tree change or a worktree change
- **THEN** the same plain-git capture-and-compare procedure SHALL apply, keyed to the tree named by the dispatch
