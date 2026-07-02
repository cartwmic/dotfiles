# opsx-doneness-judge Specification

## Purpose
A sealed `doneness.md` verdict authored by an independent blind LLM judge against the frozen intent, read (never generated) by the gate as the semantic-doneness backstop that can only block, never pass, a change (ADR-0012).
## Requirements
### Requirement: Sealed Doneness Verdict Artifact

THE doneness judge SHALL record its verdict in a `doneness.md` artifact in the change
directory carrying a machine-readable `Doneness` field whose value is exactly `satisfied`
or `not`, and WHILE the value is `not` THE artifact SHALL enumerate the specific unmet
gaps as a list, so downstream consumers (the gate and the stall detector) read the verdict
and the gap set by field parse rather than model judgment.

#### Scenario: Satisfied verdict is a sealed field
- **WHEN** the doneness judge concludes the frozen intent's outcomes are met by the diff
- **THEN** `doneness.md` SHALL contain the line `**Doneness:** satisfied` and SHALL carry
  its provenance and reviewed-range fields

#### Scenario: Not-satisfied verdict enumerates gaps
- **WHEN** the doneness judge concludes one or more intent outcomes are unmet
- **THEN** `doneness.md` SHALL contain `**Doneness:** not` and SHALL list each unmet gap as
  a distinct bullet under a `Gaps` heading, each gap being a short stable phrase a consumer
  can normalize and compare across turns

#### Scenario: Absent or unparseable verdict is treated as not-satisfied
- **IF** `doneness.md` is absent, or its `Doneness` field is missing or holds a value other
  than `satisfied` or `not`
- **THEN** consumers SHALL treat doneness as not established (equivalent to `not`), never as
  a permissive pass

### Requirement: Blind Scope-Anchored Judge

THE doneness judge SHALL be an independent blind subagent dispatched on the resolved
`review` role model, judging the frozen `intent.md` against the actual `Diff Base SHA..HEAD`
diff and the change's delta acceptance criteria, and SHALL rule `satisfied` only when the
intent's stated outcomes are met and NOTHING beyond them is demanded.

#### Scenario: Judge runs blind on the review role
- **WHEN** the orchestrator dispatches the doneness judge
- **THEN** the subagent SHALL be dispatched with fresh context (no orchestrator reasoning)
  on the model resolved for the `review` role, and SHALL read the frozen intent, the diff,
  and the delta ACs as its baseline

#### Scenario: Scope anchor forbids gold-plating
- **WHILE** the judge is ruling on satisfaction
- **IF** the diff meets every stated outcome of the frozen intent
- **THEN** the judge SHALL rule `satisfied` even if further beyond-scope improvements are
  imaginable, and SHALL NOT record gaps that demand work outside the frozen intent

#### Scenario: No new model role is introduced
- **WHEN** the doneness judge resolves its model
- **THEN** it SHALL use the existing `review` role via `opsx models review`, and no
  `doneness` model role SHALL be added to the model-config surface

### Requirement: Freshness Bound Verdict

THE doneness verdict SHALL be valid only WHILE (a) its recorded reviewed range equals
`Diff Base SHA..<current-HEAD>` recomputed from the located worktree, (b) its recorded Diff
Base SHA equals the immutable Diff Base SHA recorded in review.md, AND (c) its recorded
frozen-intent content hash equals `sha256(intent.md)` recomputed from the change directory,
so a `satisfied` verdict recorded against an earlier HEAD, a different diff base, or a
mutated intent cannot pass.

#### Scenario: Stale doneness verdict is invalid
- **WHILE** `doneness.md` records a reviewed range
- **IF** that recorded `Diff Base SHA..HEAD` does not equal the range recomputed from the
  current located worktree HEAD
- **THEN** the verdict SHALL be treated as stale and not established, forcing a re-judge

#### Scenario: Verdict judged against a mutated intent or wrong diff base is invalid
- **WHILE** `doneness.md` records a frozen-intent hash and a Diff Base SHA
- **IF** the recorded frozen-intent hash does not equal `sha256(intent.md)`, OR the recorded
  Diff Base SHA does not equal the immutable Diff Base SHA in review.md
- **THEN** the verdict SHALL be treated as judged against the wrong baseline and not
  established, forcing a re-judge

#### Scenario: New commit invalidates a prior satisfied verdict
- **WHILE** a prior `satisfied` verdict exists
- **WHEN** the implementation HEAD advances with a new commit
- **THEN** the recorded reviewed range no longer matches the recomputed range and the
  verdict SHALL no longer count as satisfied until re-judged against the new HEAD

### Requirement: Anti-Self-Forge Provenance

THE subagent-dispatch adapter SHALL stamp `doneness.md` with a reviewer-provenance field —
recording the judging `review`-role model identity, the review mode, the frozen-intent
content hash, and the Diff Base SHA it judged — rather than the orchestrator or the judge
subagent writing that stamp in-band itself. The review-mode vocabulary for doneness is
`blind-single-judge` (the normal case: one independent blind subagent judge) or
`adversarial-multimodel` (the optional stronger form, ≥2 distinct models); consumers SHALL
treat a verdict whose provenance is absent, or whose review mode is
`degraded-single-model` or any value outside that vocabulary, as not established,
matching the adapter-stamped code-review provenance posture: it is a tripwire against
accidental self-marking in normal flow, NOT a cryptographic guarantee — a same-UID actor
that both bypasses dispatch AND forges the stamp is out of the threat model, exactly as the
live in-session authoring-marker check concedes (a post-hoc gate cannot force a model
against a same-UID actor).

#### Scenario: Provenance is adapter-stamped, not agent-written
- **WHEN** a doneness verdict is sealed
- **THEN** the reviewer-provenance field SHALL be written by the subagent-dispatch adapter
  (not authored in-band by the orchestrator or the judge subagent), recording the
  review-role model identity, the review mode, the frozen-intent content hash, and the Diff
  Base SHA

#### Scenario: Missing or degraded provenance is not established
- **IF** `doneness.md` carries a `satisfied` verdict but lacks the adapter-stamped
  reviewer-provenance field, or that field records a review mode other than
  `blind-single-judge` or `adversarial-multimodel` (including `degraded-single-model`
  and unknown values)
- **THEN** consumers SHALL treat the verdict as not established (equivalent to `not`)

### Requirement: Scale-Gated With Waiver

THE doneness verdict SHALL be a required check WHILE the change declares Scale M or above
and `doneness_mode` is `required`, and WHERE `doneness_mode` is `waived` (with a recorded
non-empty `doneness_waiver_rationale`) or the change is below Scale M, the doneness verdict
SHALL NOT be a required check, mirroring the existing validation-source waiver.

#### Scenario: Required at Scale M and above by default
- **WHILE** the change declares Scale M or above and `doneness_mode` is absent or `required`
- **WHEN** doneness is evaluated
- **THEN** a satisfied, fresh, provenanced doneness verdict SHALL be required

#### Scenario: Waiver with rationale lets Scale M and above pass without a verdict
- **WHERE** `doneness_mode` is `waived` with a recorded non-empty `doneness_waiver_rationale`
  in review.md front-matter
- **WHEN** doneness is evaluated
- **THEN** the doneness verdict SHALL NOT be required and its absence SHALL NOT fail the
  check

#### Scenario: Waiver without a rationale does not take effect
- **WHERE** `doneness_mode` is `waived` but no non-empty `doneness_waiver_rationale` is
  recorded
- **WHILE** the change declares Scale M or above
- **THEN** the waiver SHALL NOT take effect and a satisfied, fresh, provenanced doneness
  verdict SHALL remain required

#### Scenario: Below Scale M skips doneness
- **WHILE** the change declares Scale below M
- **WHEN** doneness is evaluated
- **THEN** the doneness verdict SHALL NOT be a required check

---

