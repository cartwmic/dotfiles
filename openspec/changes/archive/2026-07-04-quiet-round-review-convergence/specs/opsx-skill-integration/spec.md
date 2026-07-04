# opsx-skill-integration (delta)

## MODIFIED Requirements

### Requirement: openspec-loop orchestrator skill exists

A new skill SHALL be created at `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md` implementing the single-orchestrator loop that advances an opsx-superpowers change until opsx gate is green, delegating review steps to subagents per the consolidated `opsx-loop` capability (which absorbs the retired `opsx-loop-orchestration` capability under B3), and the skill's review-convergence section SHALL express the quiet-round budget semantics (quiet round → seal; converging with landed fixes → continue autonomously; thrash/no-progress → land; hard cap → land) as the default with `review_budget_mode: land-on-stop` as the documented opt-out, SHALL direct the orchestrator to run `opsx sweep <change>` BEFORE dispatching review round 1 for any change that declares a sweep.txt (rename/retire/migration-class changes), and SHALL direct the orchestrator and its dispatched reviewers/judges to FILL the schema's shipped verify/code-review/doneness templates (by path) rather than free-writing verdict artifacts.

#### Scenario: Skill metadata complete
- **WHEN** the skill is loaded by a harness
- **THEN** its frontmatter SHALL include `name: openspec-loop`, a one-line `description`, `license`, and `compatibility`, and the body SHALL describe the gate-driven cycle and the subagent-review-against-baseline rule

#### Scenario: Skill deploys cross-harness
- **WHEN** `chezmoi apply` runs followed by the harness-config apply step
- **THEN** the skill SHALL be symlinked into every harness skills directory as `openspec-loop`, consistent with the canonical-skill deployment pattern

#### Scenario: Kickoff adapter carries no workflow logic
- **WHEN** a harness-specific kickoff (such as a pi extension command) invokes the loop
- **THEN** that adapter SHALL only wire the worker to the openspec-loop skill and the judge to opsx gate, and removing the adapter SHALL NOT remove any workflow logic

#### Scenario: Skill expresses quiet-round semantics
- **WHEN** the skill's review-convergence stop-condition table is read
- **THEN** it SHALL present the ordered quiet-round evaluation (quiet → seal; converging → continue; thrash → land; cap → land) as the default and land-on-stop as the explicit opt-in

#### Scenario: Sweep runs before round 1
- **WHERE** the change directory declares a sweep.txt
- **WHEN** the orchestrator prepares to dispatch the first gating review round
- **THEN** the skill SHALL direct it to run `opsx sweep <change>` first and resolve all hits before the dispatch

#### Scenario: Verdicts are filled templates
- **WHEN** the skill directs authoring of verify.md, code-review.md, or doneness.md
- **THEN** it SHALL point at the schema's shipped template paths to be filled, not describe free-form authoring of gate-parsed fields
