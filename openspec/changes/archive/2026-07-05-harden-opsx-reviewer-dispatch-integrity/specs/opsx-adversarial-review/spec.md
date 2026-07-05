# opsx-adversarial-review (delta)

## ADDED Requirements

### Requirement: Reviewer Tree Identity Attestation

THE blind reviewer/judge dispatch prompt SHALL require the subagent, BEFORE reviewing, to attest the tree it is actually executing in — record the verbatim output of `git rev-parse HEAD` (a full 40-hex SHA; any other form is a missing attestation) and of `git rev-parse --show-toplevel`, as machine-readable own-line fields at the top of its findings output (`Attested HEAD: <40-hex sha>` and `Attested Path: <toplevel path>`) — and THE orchestrator SHALL count a reviewer verdict toward gating ONLY WHEN the attested HEAD literal equals the full SHA of the dispatched range head AND the attested path, canonicalized (realpath), equals the canonicalized root of the dispatched tree (in same-tree mode the dispatched tree is the integration checkout, so the path check is satisfied by that equality and the HEAD check carries the discrimination). A verdict with a missing or mismatched attestation SHALL be treated as INVALID — distinct from fail: it SHALL NOT satisfy multi-model gating, SHALL NOT enter the round ledger as a reviewer verdict, and SHALL NOT count toward the `review_max_rounds` trajectory — and the orchestrator SHALL record the incident and re-dispatch the reviewer (or repair the reviewer set) rather than sealing. WHEN two consecutive dispatch attempts of the same round yield NO countable verdict (all reviewers INVALID), THE orchestrator SHALL stop re-dispatching and route to the decision-audit landing with a dispatch-integrity error rather than retrying unbounded. WHEN sealing `code-review.md` (and `doneness.md` when an independently dispatched judge produced it), THE orchestrator SHALL record the single `**Attested HEAD:**` value only when every counted reviewer's attestation matches it.

#### Scenario: Attestation preamble required in every dispatch
- **WHEN** a blind reviewer or judge subagent is dispatched
- **THEN** the dispatch prompt SHALL instruct it to record `Attested HEAD: <git rev-parse HEAD output>` and `Attested Path: <resolved working directory>` as its first findings-output lines before any review content

#### Scenario: Wrong-tree verdict is invalid, not fail
- **IF** a returned verdict's attested HEAD does not rev-parse equal to the dispatched range head, or its attested path does not resolve to the dispatched tree
- **THEN** the orchestrator SHALL treat the verdict as INVALID — excluded from multi-model gating, absent from the round ledger's reviewer verdicts, and not counted toward `review_max_rounds` — record the incident, and re-dispatch

#### Scenario: Missing attestation is invalid
- **IF** a returned findings output carries no attestation fields, or an `Attested HEAD` that is not a full 40-hex SHA literal
- **THEN** the verdict SHALL be treated as INVALID with the same exclusions

#### Scenario: All-invalid rounds terminate at the landing
- **IF** two consecutive dispatch attempts of the same review round produce zero countable verdicts (every reviewer INVALID)
- **THEN** the orchestrator SHALL stop re-dispatching and route to the decision-audit landing with a dispatch-integrity error

#### Scenario: Sealed artifact carries the matched attestation
- **WHEN** the orchestrator seals code-review.md (or doneness.md produced by an independently dispatched judge)
- **THEN** it SHALL record `**Attested HEAD:**` equal to the value every counted reviewer attested, and SHALL NOT seal while counted reviewers' attestations disagree

### Requirement: Read Only Reviewer Dispatch

THE orchestrator SHALL capture a deterministic snapshot of the reviewed tree immediately before dispatching a review round's reviewer/judge subagents and an identically captured snapshot immediately after the last of them returns — the tree's `git rev-parse HEAD` plus its `git status --porcelain=v1` output with the change's own `openspec/changes/<change>/` paths excluded from the comparison (they are orchestrator-sealed bookkeeping, the only in-window writes permitted) — and THE orchestrator SHALL NOT write to the reviewed tree outside that exclusion while the round window is open. IF the snapshots differ, mutation cannot be attributed among concurrently dispatched reviewers, so THE orchestrator SHALL treat ALL of that round's verdicts as INVALID (with the same exclusions as a mismatched attestation), restore the reviewed tree to its pre-dispatch state surgically — `git restore` only tracked paths whose porcelain status changed across the window; delete only untracked paths present in the post-window snapshot and absent from the pre-window snapshot; NEVER a blanket `git clean` and NEVER ignored or pre-existing untracked state — and record the incident in the round ledger / Execution Notes before proceeding. The snapshot and restore SHALL use plain git commands only (deterministic, model-free) and SHALL work in both worktree and same-tree modes.

#### Scenario: Reviewer mutation voids the round
- **IF** the post-window snapshot differs from the pre-window snapshot for a review round (after excluding the change's own `openspec/changes/<change>/` paths)
- **THEN** all of that round's verdicts SHALL be INVALID, the tree SHALL be restored to the pre-dispatch state, and the incident SHALL be recorded

#### Scenario: Restore is surgical
- **WHEN** the orchestrator restores after a snapshot delta
- **THEN** it SHALL `git restore` only tracked paths whose status changed across the window and delete only untracked paths introduced during the window, never pre-existing untracked or ignored state

#### Scenario: Clean dispatch counts normally
- **WHILE** the pre- and post-window snapshots are identical
- **WHEN** a verdict's attestation also matches
- **THEN** the verdict SHALL be counted normally toward gating and the ledger

#### Scenario: Deterministic in both tree modes
- **WHEN** the snapshot is captured for a same-tree change or a worktree change
- **THEN** the same plain-git capture-and-compare procedure SHALL apply, keyed to the tree named by the dispatch
