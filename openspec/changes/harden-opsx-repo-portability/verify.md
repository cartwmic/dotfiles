# Verify

<!--
Filled from the shipped template
~/.local/share/openspec/schemas/opsx-superpowers/templates/verify.md (Q3
discipline). Six hard-gate checks; Verification Mode = retained-recommended.
-->

**Generated:** 2026-07-04 by openspec-loop orchestrator (in-session, deterministic checks)
**Change:** harden-opsx-repo-portability

**Diff Base SHA:** a8c52af74a7ec8c81ce8367e2a124b433164bd3d
**Reviewed Range:** a8c52af..4b5064f

<!--
Same-tree change; range includes 3 change commits (59e2168 locator capture,
e2fe3e3 implementation, 27a0993 AC-ID coverage) interleaved with concurrent
ntfy-harpoon-jump fleet commits (visibility-over-locking, ADR-0024). This
change's own file set: dot_local/bin/executable_opsx, templates/review.md,
archive+propose skill references, tests/opsx-{cli,gate}/,
tests/opsx-review-convergence/, openspec/changes/harden-opsx-repo-portability/.
-->

## Completion Decision

**Status:** green

## Checks

| # | Check | Status | Details |
|---|---|---|---|
| 1 | Structural validation (`openspec validate --strict --json`) | pass | change valid; `--specs --strict` 11/11 |
| 2 | Task completion (zero `- [ ]` in tasks.md) | pass | 11/11 checked |
| 3 | Delta vs current spec coherence | pass | opsx-cli: 1 ADDED + 2 MODIFIED (restated fully, supersets); opsx-gate-enforcement: 1 ADDED + 1 MODIFIED (superset, adds non-main scenario); opsx-workflow-schema: 1 ADDED |
| 4 | Commit hygiene (subject ≤72; body explains why) | pass | 3 change commits, all conformant |
| 5 | AC↔test mapping (canonical IDs) | pass | forward 6/6, reverse 3/3 (below) |
| 6 | Constitution compliance audit (sampling) | pass | 8 change files audited (100%); deterministic/model-free preserved, fail-closed posture, no legacy entrypoints |

## Check 5 detail — AC↔test mapping (canonical ID format)

### Forward coverage (each AC has ≥1 test)

| AC ID | Test references | Status |
|---|---|---|
| opsx-cli.integration-branch-resolution | tests/opsx-cli/test_opsx_cli.sh (resolver section header + case cites) | covered |
| opsx-cli.status-fleet-view | tests/opsx-cli/test_opsx_cli.sh (behind-trunk staleness case) | covered |
| opsx-cli.multi-dir-integration-commit-detector | tests/opsx-cli/test_opsx_cli.sh (evil-merge comment, un-split) | covered |
| opsx-gate-enforcement.project-artifact-preflight | tests/opsx-gate/test_opsx_gate.sh (4-case preflight section) | covered |
| opsx-gate-enforcement.land-base-currency | tests/opsx-cli/test_opsx_cli.sh (archive-check header); tests/opsx-review-convergence/test_review_convergence_surfaces.sh (prose pins) | covered |
| opsx-workflow-schema.integration-branch-locator-default-detected | tests/opsx-review-convergence/test_review_convergence_surfaces.sh (sentinel pins) | covered |

### Reverse coverage (each changed test references ≥1 AC)

| Test file | AC references | Status |
|---|---|---|
| tests/opsx-cli/test_opsx_cli.sh | opsx-cli.integration-branch-resolution, opsx-cli.status-fleet-view, opsx-gate-enforcement.land-base-currency, … | referenced |
| tests/opsx-gate/test_opsx_gate.sh | opsx-gate-enforcement.project-artifact-preflight, … | referenced |
| tests/opsx-review-convergence/test_review_convergence_surfaces.sh | opsx-workflow-schema.integration-branch-locator-default-detected, … | referenced |

## Check 6 detail — Constitution sampling

| Sampled file | Principles checked | Status | Notes |
|---|---|---|---|
| dot_local/bin/executable_opsx | determinism, fail-closed, no-legacy | compliant | resolver = git plumbing + file read; preflight `test -s`; no model calls; BSD-safe (`show-ref`, `symbolic-ref --short`, no GNU-only flags) |
| dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md | prose-surface fidelity | compliant | sentinel + resolver comment; mode table untouched |
| .../openspec-archive-change/references/opsx-superpowers-mode.md | prose-surface fidelity | compliant | resolved-branch language, cites AC |
| .../openspec-propose/references/opsx-superpowers-mode.md | prose-surface fidelity | compliant | option B mirrors every-Scale gate posture (Scope Expansion, review.md) |
| tests/opsx-cli/test_opsx_cli.sh | hermetic tests | compliant | new fixtures self-contained under $TMP |
| tests/opsx-gate/test_opsx_gate.sh | hermetic tests | compliant | fixture artifacts + restore between cases |
| tests/opsx-review-convergence/test_review_convergence_surfaces.sh | pins | compliant | positive + negative (literal-gone) pins |
| openspec/changes/harden-opsx-repo-portability/** | artifact discipline | compliant | intent untouched since freeze |

**Sampling coverage:** 8 audited of 8 change-owned changed = 100% (foreign fleet commits in range excluded — not this change's work product)

## Validator evidence (all green at 27a0993)

- `bash -n dot_local/bin/executable_opsx` — clean
- opsx-cli 67/0 (+7) · opsx-gate 128/0 (+4) · opsx-models 34/0 · surfaces 152/0 (+7) · author-marker 4/0
- `bun test dot_pi/agent/extensions/opsx-loop/` 60/0 (108 expects)
- `openspec validate harden-opsx-repo-portability --strict` valid · `openspec validate --specs --strict` 11/11

## Summary

- Pass count: 6/6
- Decision: green
- **Archive gate:** READY (subject to remaining gate checks)
