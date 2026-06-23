# Capability: opsx-skill-integration

## ADDED Requirements

### Requirement: openspec-loop orchestrator skill exists

A new skill SHALL be created at `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md` implementing the single-orchestrator loop that advances an opsx-superpowers change until opsx-gate is green, delegating review steps to subagents per the opsx-loop-orchestration capability.

#### Scenario: Skill metadata complete
- **WHEN** the skill is loaded by a harness
- **THEN** its frontmatter SHALL include `name: openspec-loop`, a one-line `description`, `license`, and `compatibility`, and the body SHALL describe the gate-driven cycle and the subagent-review-against-baseline rule

#### Scenario: Skill deploys cross-harness
- **WHEN** `chezmoi apply` runs followed by the harness-config apply step
- **THEN** the skill SHALL be symlinked into every harness skills directory as `openspec-loop`, consistent with the canonical-skill deployment pattern

#### Scenario: Kickoff adapter carries no workflow logic
- **WHEN** a harness-specific kickoff (such as a pi extension command) invokes the loop
- **THEN** that adapter SHALL only wire the worker to the openspec-loop skill and the judge to opsx-gate, and removing the adapter SHALL NOT remove any workflow logic

### Requirement: openspec-explore freezes intent

The `openspec-explore` skill SHALL, on conclusion of an explore session for an opsx-superpowers change, write the agreed intent, constraints, and invariants to `intent.md` in the change directory so the loop and review subagents can treat it as the baseline.

#### Scenario: Intent written on explore conclusion
- **WHEN** an explore session concludes with user-confirmed intent under schema opsx-superpowers
- **THEN** `intent.md` SHALL be written to the change directory containing intent, constraints, and invariants

#### Scenario: Spec-driven projects unaffected
- **WHEN** explore concludes for a project whose schema is `spec-driven`
- **THEN** no `intent.md` SHALL be required and the skill SHALL behave as before this change

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-skill-integration.openspec-loop-orchestrator-skill-exists | [x] | [x] | [x] | [x] | [x] |
| opsx-skill-integration.openspec-explore-freezes-intent | [x] | [x] | [x] | [x] | [x] |
