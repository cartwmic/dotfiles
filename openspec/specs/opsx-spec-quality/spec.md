# opsx-spec-quality Specification

## Purpose
TBD - created by archiving change add-opsx-superpowers-schema. Update Purpose after archive.
## Requirements

### Requirement: EARS notation for acceptance criteria

Acceptance criteria authored under `opsx-superpowers` SHALL use EARS notation (Mavin et al., RE'09). The specs artifact instruction SHALL define and require one of five EARS patterns per criterion: ubiquitous (`THE <system> SHALL <response>`), event-driven (`WHEN <trigger>, THE <system> SHALL <response>`), state-driven (`WHILE <state>, THE <system> SHALL <response>`), optional (`WHERE <feature>, THE <system> SHALL <response>`), or unwanted-behavior (`IF <condition>, THEN THE <system> SHALL <response>`).

Every acceptance criterion SHALL have a canonical AC ID derived from its parent capability and the requirement name: `<capability>.<requirement-slug>` where `<requirement-slug>` is the requirement name lowercased with non-alnum chars replaced by `-`, repeated `-` collapsed, leading/trailing `-` stripped. This canonical ID is the contract used by the verify gate's AC↔test mapping check.

#### Scenario: Error path uses IF-THEN, not WHEN
- **WHEN** an acceptance criterion describes an error or unwanted condition (e.g., "user submits invalid input")
- **THEN** the criterion SHALL be written with the `IF ... THEN THE <system> SHALL ...` pattern, AND the analyze artifact's EARS pattern check SHALL flag any error-path AC written with `WHEN` as a **major finding requiring human triage** (not an auto-blocker, because the regex has known false-positive modes when error keywords appear as substrings of entity names or in non-error context); confirmed true-positive matches SHALL block tasks generation

#### Scenario: Nominal trigger uses WHEN
- **WHEN** an acceptance criterion describes a nominal event (e.g., "user submits valid credentials")
- **THEN** the criterion SHALL be written with the `WHEN ... THE <system> SHALL ...` pattern

#### Scenario: Preconditions use WHILE
- **WHEN** an acceptance criterion only applies during a particular system state (e.g., "while an order is in canceled-and-refunded state")
- **THEN** the criterion SHALL be written with the `WHILE ... THE <system> SHALL ...` pattern

#### Scenario: Feature-gated behavior uses WHERE
- **WHEN** an acceptance criterion only applies when a configurable feature is enabled
- **THEN** the criterion SHALL be written with the `WHERE ... THE <system> SHALL ...` pattern

#### Scenario: Compound conditions are permitted
- **WHEN** a criterion needs to combine a state precondition and an event trigger
- **THEN** the criterion MAY chain `WHILE <state>, WHEN <trigger>, THE <system> SHALL <response>` and the EARS pattern check SHALL accept this compound form

### Requirement: Five quality properties per acceptance criterion

The specs artifact instruction SHALL require each acceptance criterion to satisfy five quality properties — Testable, Solution-free, Unambiguous, Consistent, Complete — and SHALL include these as an explicit checklist at the bottom of every `spec.md`.

#### Scenario: Testable property
- **WHEN** the author drafts an acceptance criterion
- **THEN** the criterion SHALL name explicit inputs, explicit outputs, and an explicit condition relating them, such that a reader can identify at least one observable input/output pair satisfying or failing the criterion

#### Scenario: Solution-free property
- **WHEN** the author drafts an acceptance criterion
- **THEN** the criterion SHALL describe observable behavior rather than implementation mechanisms; the analyze artifact's "Implementation language in specs" check SHALL flag criteria that prescribe a specific technology, schema, or algorithm without behavioral justification

#### Scenario: Unambiguous property
- **WHEN** the clarify artifact's ambiguity pass paraphrases a criterion three times
- **THEN** the three paraphrases SHALL converge on a single semantic interpretation, OR the criterion SHALL be flagged with a 2-option clarification question for the user

#### Scenario: Consistent property
- **WHEN** the clarify artifact's inconsistency pass identifies a pair of criteria whose antecedents can hold simultaneously
- **THEN** the consequents SHALL NOT prescribe conflicting system behavior on a shared observable output, OR the pair SHALL be flagged with a 2-option resolution question

#### Scenario: Complete property
- **WHEN** the clarify artifact's completeness pass enumerates event and state combinations declared by the spec
- **THEN** every reachable combination SHALL be covered by at least one acceptance criterion, OR the gap SHALL be flagged with a 2-option question asking whether the silence is intentional or whether a new criterion is required

### Requirement: Constitution and domain referenced by every artifact

Every artifact instruction in the `opsx-superpowers` schema SHALL require the author (human or agent) to read `openspec/constitution.md` and `openspec/domain.md` before drafting the artifact, and SHALL require artifacts to cite specific constitution principles or domain invariants when they constrain the artifact's content.

#### Scenario: Constitution check in analyze
- **WHEN** the analyze artifact runs its constitution-check pass
- **THEN** for each principle in `openspec/constitution.md`, the pass SHALL report `compliant`, `violated`, or `inapplicable` with a one-line rationale referencing the change's proposal, specs, design, or tasks

#### Scenario: Domain knowledge consumed by clarify
- **WHEN** the clarify artifact runs its inconsistency or completeness passes
- **THEN** the passes SHALL treat invariants in `openspec/domain.md` as ground truth that constrains which event/state combinations are reachable

#### Scenario: Missing constitution file
- **WHEN** a project opts into `schema: opsx-superpowers` and `openspec/constitution.md` is absent or empty
- **THEN** `openspec-propose` SHALL prompt the project owner to fill in the constitution from the schema's `constitution-template.md` before producing the first non-XS change

### Requirement: Three-pass clarify procedure (delta-scoped, bounded)

The `clarify.md` artifact SHALL execute three passes — ambiguity, inconsistency, completeness — over the current change's delta spec content only (not the merged current+delta corpus), and SHALL record each finding as a numbered 2-option question with status `unanswered | answered | deferred`. Findings with status `unanswered` SHALL block progression to design. Findings with status `deferred` SHALL be referenced from `analyze.md` as outstanding risks. Each pass SHALL be bounded to keep cost tractable in brownfield changes with many existing ACs.

#### Scenario: Ambiguity pass via paraphrase divergence
- **WHEN** the clarify pass paraphrases each acceptance criterion three times and any pair of paraphrases is semantically divergent (different inputs, different outputs, or different relations)
- **THEN** the divergence SHALL be recorded as an ambiguity finding with text "Q: <description>. A) keep as-is meaning X. B) change to meaning Y."

#### Scenario: Inconsistency pass with N-bounded prioritization
- **WHEN** any pair of acceptance criteria has antecedents that can hold simultaneously
- **THEN** the consequents SHALL be checked for conflict on each shared observable output; AT counts above 20 ACs in a single change, the clarify pass SHALL prioritize pairs within the same Requirement and pairs sharing entity names rather than enumerating the full N² pairwise space; conflicting pairs SHALL be recorded as inconsistency findings with the minimal contradicting set named

#### Scenario: Completeness pass with priority cap
- **WHEN** the clarify pass enumerates event/state combinations declared in the change's delta specs
- **THEN** the pass SHALL NOT enumerate the full cartesian product (which produces combinatorial noise); the pass SHALL list the events and states declared in the change, identify which combinations are realistic given `openspec/domain.md` invariants, and record up to 10 highest-impact uncovered combinations per spec file as completeness findings

### Requirement: AC↔test ID mapping as a hard verify gate (skill-produced)

The `verify.md` artifact (produced by `openspec-apply-change` post-apply; not declared in the schema's artifact graph) SHALL enforce a mapping between EARS acceptance criteria and test artifacts using the canonical AC ID format `<capability>.<requirement-slug>`: every AC SHALL be referenced by at least one test by literal canonical ID match, and every test SHALL reference at least one AC by literal canonical ID match. Archive SHALL be blocked if mapping coverage is incomplete and Verification Mode is `retained-required`.

#### Scenario: Every AC has a test (forward, canonical ID grep)
- **WHEN** `verify.md` runs the AC→test forward coverage check
- **THEN** for every `### Requirement` block in `specs/<capability>/spec.md`, the check SHALL compute the canonical AC ID `<capability>.<slug-of-requirement-name>` and grep the change's diff for the literal ID string; at least one test file (heuristic: paths matching `/(^|/)tests?/` or `/\.(test|spec)\.[^.]+$/`) SHALL contain the ID; unreferenced ACs SHALL be reported as failures of check 5

#### Scenario: Every test cites an AC (reverse, canonical ID grep)
- **WHEN** `verify.md` runs the test→AC reverse check
- **THEN** every test file added or modified in the change's diff SHALL contain at least one canonical AC ID matching `<capability>\.[a-z0-9-]+`; tests with no AC reference SHALL be reported as orphans

#### Scenario: Reverse-check exemptions
- **WHEN** a test is purely infrastructural (e.g., a fixture builder, a test helper, a CI smoke test that asserts only environment correctness)
- **THEN** it MAY declare an exemption marker `# spec-exempt: <reason>` AND the reverse-check SHALL honor the exemption without raising a finding

#### Scenario: Completion Decision is binary green/red
- **WHEN** the 6 verify checks complete
- **THEN** the Completion Decision SHALL be one of `green` (all 6 pass) or `red` (any check fails); there SHALL NOT be a "yellow" decision that defers responsibility (this defeats Fowler's "false sense of control" critique and removes ambiguity for the archive gate)
