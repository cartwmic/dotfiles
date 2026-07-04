<!-- authored: delegate blind clarify -->
# Capability: opsx-skill-integration

Delta for simplify-and-parallelize-opsx-workflow (B2/B3 vocabulary follow-through): the
opsx-* skill contracts still name the retired `L`/`XL` Scale tiers and the retired
`opsx-loop-orchestration` capability. This delta remaps that stray vocabulary to the
collapsed `XS | S | M` tier set with the `full_rigor` front-matter flag (former `L`/`XL`
map to "M + `full_rigor: true`") and to the consolidated `opsx-loop` capability, so a
change authored under the new schema cannot declare a Scale value the deterministic gate
fails closed on. No behavior change beyond the tier-vocabulary remap. Modified requirements
restate their full content per the MODIFIED-delta rule.

## MODIFIED Requirements

### Requirement: Schema-aware openspec-propose

The `openspec-propose` skill at `dot_local/share/agent-harness/canonical/skills/openspec-propose/SKILL.md` SHALL detect when the active change uses `schema: opsx-superpowers` and SHALL adapt its workflow to drive the new artifact graph rather than the default `spec-driven` four-artifact sequence.

#### Scenario: Schema detection at change creation
- **WHEN** the user invokes openspec-propose against a project whose `openspec/config.yaml` declares `schema: opsx-superpowers`
- **THEN** the skill SHALL pass `--schema opsx-superpowers` to `openspec new change` and SHALL follow the artifact graph returned by `openspec status --change <name> --json`

#### Scenario: Up-front Scale prompt
- **WHEN** the skill begins propose flow under `opsx-superpowers`
- **THEN** the skill SHALL ask the user to declare a Scale class from the collapsed vocabulary (`XS | S | M`) — and, for a former-`L`/`XL` change, whether to set the boolean `full_rigor` flag (which maps the former `L`/`XL` extras onto `M`) — before authoring any artifact, and SHALL record the choice in `review.md` once that artifact is reached; it SHALL NOT offer `L` or `XL` as declarable Scale values, since the deterministic gate fails closed on any Scale outside `XS | S | M`

#### Scenario: Scale-driven skipping
- **WHEN** Scale is declared `XS` and the user invokes openspec-propose
- **THEN** the skill SHALL skip authoring `specs`, `clarify`, `design`, `adr`, `analyze`, `plan`, `verify`, and `retrospective`, producing `review.md` (the mode switchboard — never skipped at any Scale) plus `proposal.md` and `tasks.md`

#### Scenario: Schema-only fallback when Superpowers absent
- **WHEN** the skill cannot resolve a referenced Superpowers-style capability skill (e.g., `verification-before-completion`)
- **THEN** the skill SHALL log the unavailability and continue using the manual fallback documented in the artifact instruction, writing to the same artifact paths and structure

### Requirement: Analyze gates tasks generation

The `openspec-propose` skill SHALL run the analyze pass before generating `tasks.md`, and SHALL refuse to produce tasks if any analyze finding is marked `blocker`. For changes carrying `full_rigor: true` (the former Scale ≥ `L` behavior), the analyze pass SHALL invoke the `adversarial-review-cycle` skill rather than relying on a single-model self-review; at plain Scale `M` without `full_rigor` the analyze pass is thinned to its deterministic checks (no separate blind analyze dispatch), per the opsx-adversarial-review M-Tier Review Stack Thinning requirement.

#### Scenario: Blocker prevents task generation
- **WHEN** `analyze.md` contains at least one finding with severity `blocker`
- **THEN** the skill SHALL halt and SHALL summarize the blockers to the user with proposed remediations

#### Scenario: Full-rigor invokes adversarial-review-cycle
- **WHEN** review.md front-matter sets `full_rigor: true` (a former `L`/`XL` change)
- **THEN** the analyze step SHALL dispatch through `adversarial-review-cycle` with multiple models per the existing skill's defaults, and SHALL record the round-by-round findings as appendices in `analyze.md`

#### Scenario: Plain M thins analyze to deterministic checks
- **WHEN** the change is Scale `M` and review.md front-matter does NOT set `full_rigor: true`
- **THEN** the analyze pass SHALL run only its deterministic checks with NO separate blind analyze dispatch, matching the opsx-adversarial-review thinning, and the 2-model blind adversarial code review SHALL remain gating-required and unweakened

### Requirement: openspec-loop orchestrator skill exists

A new skill SHALL be created at `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md` implementing the single-orchestrator loop that advances an opsx-superpowers change until opsx gate is green, delegating review steps to subagents per the consolidated `opsx-loop` capability (which absorbs the retired `opsx-loop-orchestration` capability under B3).

#### Scenario: Skill metadata complete
- **WHEN** the skill is loaded by a harness
- **THEN** its frontmatter SHALL include `name: openspec-loop`, a one-line `description`, `license`, and `compatibility`, and the body SHALL describe the gate-driven cycle and the subagent-review-against-baseline rule

#### Scenario: Skill deploys cross-harness
- **WHEN** `chezmoi apply` runs followed by the harness-config apply step
- **THEN** the skill SHALL be symlinked into every harness skills directory as `openspec-loop`, consistent with the canonical-skill deployment pattern

#### Scenario: Kickoff adapter carries no workflow logic
- **WHEN** a harness-specific kickoff (such as a pi extension command) invokes the loop
- **THEN** that adapter SHALL only wire the worker to the openspec-loop skill and the judge to opsx gate, and removing the adapter SHALL NOT remove any workflow logic
