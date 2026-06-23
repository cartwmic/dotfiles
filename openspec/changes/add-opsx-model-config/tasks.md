# Tasks — add-opsx-model-config

## 1. opsx-models resolver

- [ ] 1.1 Pure helpers: layered role resolution (env > front-matter > project > user > default), source tagging, review list parse (newline/comma), exact+alias compare
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-models
      - "tests/opsx-models/**"
- [ ] 1.2 `opsx-models <role|author-in-session> [--change] [--json] [--with-default]` CLI: empty stdout when unset, JSON {value,source}, `author-in-session` boolean surface (default true, OPSX_AUTHOR_IN_SESSION), project-root discovery, invalid-role/root exit non-zero
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-models
      - "tests/opsx-models/**"
- [ ] 1.3 `templates/opsx-models.yaml` (roles + author_in_session + aliases + resolution order)
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-models.yaml

## 2. Gate model-provenance check

- [ ] 2.1 opsx-gate: add fail-closed model-provenance check (resolve role via opsx-models --json --change; missing/mismatch/unverifiable = fail; review required-set; resolver-absent fail-closed; author marker check) + regression tests
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-gate
      - "tests/opsx-gate/**"

## 3. Consumers

- [ ] 3.1 opsx-loop extension: resolve via `opsx-models --json --change` on loop start, export OPSX_AUTHOR_MODEL/REVIEW_MODELS/IMPL_MODEL/AUTHOR_IN_SESSION; reuse opsx-gate self via PATH; tests
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/opsx-loop/**"
- [ ] 3.2 Skill edits: openspec-loop/propose/apply read role env, author-in-session default (the in-session authoring STEP writes the `authored: in-session` marker — not a dispatch adapter), delegated dispatch passes model + the adapter stamps provenance; review/code-review/verify templates carry the provenance-stamp fields, while the `authored: in-session` marker is written at RUNTIME by the in-session authoring step onto authoring artifacts (proposal/intent/specs/design/clarify/tasks/plan) — not seeded into review/verify templates
  - intent: feature
  - files_allowed:
      - "dot_local/share/agent-harness/canonical/skills/openspec-loop/**"
      - "dot_local/share/agent-harness/canonical/skills/openspec-propose/**"
      - "dot_local/share/agent-harness/canonical/skills/openspec-apply-change/**"
      - "dot_local/share/openspec/schemas/opsx-superpowers/templates/**"
- [ ] 3.3 Schema: review.md front-matter model fields + author_in_session; schema.yaml + README docs
  - intent: feature
  - files_allowed:
      - "dot_local/share/openspec/schemas/opsx-superpowers/**"

## 4. Verify

- [ ] 4.1 bun test (opsx-loop) + tests/opsx-models + tests/opsx-gate all green; transpile; opsx-gate self-run green
  - intent: feature
