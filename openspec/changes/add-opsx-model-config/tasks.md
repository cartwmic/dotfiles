# Tasks — add-opsx-model-config

## 1. opsx-models resolver

- [x] 1.1 Pure helpers: layered role resolution (env > front-matter > project > user > default), source tagging, review list parse (newline/comma), provider resolution (explicit `<provider>/<id>` wins > role provider > default provider > bare), per-review-entry provider
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-models
      - "tests/opsx-models/**"
- [x] 1.2 `opsx-models <role|author-in-session> [--change] [--json] [--with-default]` CLI: empty stdout when unset, JSON {value,source}, provider-qualified output (OPSX_<ROLE>_PROVIDER / OPSX_PROVIDER), `author-in-session` boolean surface (default true, OPSX_AUTHOR_IN_SESSION), project-root discovery, invalid-role/root exit non-zero
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-models
      - "tests/opsx-models/**"
- [x] 1.3 `templates/opsx-models.yaml` (roles + provider default + per-role *_provider + author_in_session + aliases + resolution order)
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-models.yaml

## 2. Gate author-marker check

- [x] 2.1 opsx-gate: add the In-Session Authoring Marker check — WHILE `author_in_session` true/unset AND the `author` role is configured (resolved via `opsx-models author --json --change`), fail an authoring artifact (`proposal.md`/`intent.md`/`design.md`/`clarify.md`/`tasks.md`/`plan.md`/`specs/**/spec.md`) that carries no `authored: in-session` marker; skip when author unconfigured or `author_in_session` false; resolver-absent = no author enforcement (author treated as unconfigured). Regression tests: configured+missing-marker→fail, configured+marker→pass, unconfigured→skip, opt-out→skip
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx-gate
      - "tests/opsx-gate/**"

## 3. Consumers

- [x] 3.1 opsx-loop extension: resolve via `opsx-models --json --change` on loop start, export OPSX_AUTHOR_MODEL/REVIEW_MODELS/IMPL_MODEL (provider-qualified) + OPSX_AUTHOR_IN_SESSION into the worker turns; consumer only (no config parsing, no run-history snapshot); tests
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/opsx-loop/**"
- [x] 3.2 Skill edits: openspec-loop/propose/apply read role env (`OPSX_*_MODEL`) for subagent dispatch (review/impl best-effort `model:` pass) and honor author-in-session default (the in-session authoring STEP writes the `authored: in-session` marker onto authoring artifacts proposal/intent/specs/design/clarify/tasks/plan; do NOT delegate authoring unless opted out)
  - intent: feature
  - files_allowed:
      - "dot_local/share/agent-harness/canonical/skills/openspec-loop/**"
      - "dot_local/share/agent-harness/canonical/skills/openspec-propose/**"
      - "dot_local/share/agent-harness/canonical/skills/openspec-apply-change/**"
- [x] 3.3 Schema: review.md front-matter model fields + provider keys (`provider`/`author_provider`/`review_provider`/`impl_provider`) + author_in_session; schema.yaml + README docs
  - intent: feature
  - files_allowed:
      - "dot_local/share/openspec/schemas/opsx-superpowers/**"

## 4. Verify

- [ ] 4.1 bun test (opsx-loop) + tests/opsx-models + tests/opsx-gate all green; transpile; opsx-gate self-run green
  - intent: feature
