# Plan — add-opsx-model-config

## Step 1 — opsx-models resolver (TDD)
- **Covers:** T1.1, T1.2, T1.3
- **Action:** helpers (layered resolution + source tag + review-list parse + exact/alias compare) with failing tests; CLI wrapper (empty-when-unset, --json {value,source}, --with-default, --change, project-root discovery); opsx-models.yaml template. `tests/opsx-models` green.
- **Verification:** unset→empty stdout; env>front-matter>project>user; --json source field; invalid role/root exit non-zero.

## Step 2 — Gate model-provenance check (TDD)
- **Covers:** T2.1
- **Action:** opsx-gate resolves each role via `opsx-models --json --change`; for configured roles, fail-closed on missing/unverifiable/mismatch; review required-set; author marker rule; resolver-absent fail-closed. Regression tests: configured+missing→fail, configured+mismatch→fail, configured+match→pass, unconfigured→skip, review subset→fail, delegated-stamp-on-author→fail.
- **Verification:** `tests/opsx-gate` extended suite green; existing 26 still green.

## Step 3 — Consumers (extension + skills + schema)
- **Covers:** T3.1, T3.2, T3.3
- **Action:** opsx-loop exports the four OPSX_* vars via opsx-models; skill edits (author-in-session default, delegated dispatch passes model + stamps provenance); template provenance fields; review.md front-matter + schema docs. Constitution IX satisfied by the post-impl adversarial code-review over the skill diffs.
- **Verification:** opsx-loop bun tests green; goal untouched; spec-driven projects unaffected.

## Step 4 — Verify + close
- **Covers:** T4.1
- **Action:** all suites green; produce verify.md + post-impl code-review (adversarial-multimodel, IX); seal uncommitted; gate green.
- **Verification:** `opsx-gate add-opsx-model-config --worktree <wt>` → GATE-PASS.
