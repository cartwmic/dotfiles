## 1. <Phase name — e.g., "Scaffolding">

- [ ] 1.1 <Task description>
- [ ] 1.2 <Task with contract fields>
  - intent: feature
  - files_allowed:
      - src/foo/**/*.ts
      - tests/foo/**/*.ts
  - files_forbidden:
      - "**/*.bak"
  - allow_new_files: true

## 2. <Phase name — e.g., "Core implementation">

- [ ] 2.1 <Task description>
- [ ] 2.2 <Task description>
  - intent: fix
  - files_allowed:
      - src/parser/**/*.py
  - allow_new_files: false

## 3. <Phase name — e.g., "Tests">

- [ ] 3.1 <Task description>
  - intent: feature
  - files_allowed:
      - tests/**/*.py

<!--
Per-task contract fields (all optional; appear as sub-bullets under
the task line):

  - intent: fix | feature | refactor | infra
      fix      — repair prompt CONSTRAINTS: "Fix only failing
                 validators. Do NOT refactor unrelated code.
                 Do NOT add new features."
      feature  — minimal constraints
      refactor — permits unrelated cleanup within files_allowed
      infra    — permits dependency / build / CI changes

  - files_allowed:   minimatch globs of permitted paths
  - files_forbidden: minimatch globs of explicitly disallowed paths
  - allow_new_files: true (default) | false

Enforcement: at task wrap-up (or subagent completion when
Delegation Mode is subagent-*), `git diff --name-only HEAD`
is checked against these globs. Violations are reported as
scope_violation findings that BLOCK task completion.
-->
