# Plan — add-opsx-model-config

## Step 1 — opsx-models resolver (TDD)
- **Covers:** T1.1, T1.2, T1.3
- **Action:** helpers (layered resolution + source tag + review-list parse + provider resolution: explicit `<provider>/<id>` wins > role provider > default provider > bare) with failing tests; CLI wrapper (empty-when-unset, --json {value,source}, --with-default, --change, project-root discovery); opsx-models.yaml template (roles + provider keys). `tests/opsx-models` green.
- **Verification:** unset→empty stdout; env>front-matter>project>user; provider-qualified output; explicit-provider-wins; bare-id-qualified-by-default; --json source field; invalid role/root exit non-zero.

## Step 2 — Gate author-marker check (TDD)
- **Covers:** T2.1
- **Action:** opsx-gate resolves `author` via `opsx-models author --json --change`; WHILE author configured AND `author_in_session` true/unset, fail an authoring artifact (proposal/intent/design/clarify/tasks/plan/specs) lacking the `authored: in-session` marker; skip when unconfigured or opt-out. NO run-history reading. Regression tests: configured+missing-marker→fail, configured+marker→pass, unconfigured→skip, opt-out→skip.
- **Verification:** `tests/opsx-gate` extended suite green; existing 26 still green.

## Step 3 — Consumers (extension + skills + schema)
- **Covers:** T3.1, T3.2, T3.3
- **Action:** opsx-loop exports OPSX_*_MODEL (provider-qualified) + OPSX_AUTHOR_IN_SESSION via opsx-models (consumer only, no snapshot); skill edits (author-in-session default writes the marker; review/impl dispatch passes the resolved model+provider best-effort); review.md front-matter + provider keys + schema docs. Constitution IX satisfied by the post-impl adversarial code-review over the skill diffs.
- **Verification:** opsx-loop bun tests green; goal untouched; spec-driven projects unaffected.

## Step 4 — Verify + close
- **Covers:** T4.1
- **Action:** all suites green; produce verify.md + post-impl code-review (adversarial-multimodel, IX); seal uncommitted; gate green.
- **Verification:** `opsx-gate add-opsx-model-config --worktree <wt>` → GATE-PASS.
