# Plan: simplify-and-parallelize-opsx-workflow

## Order

1. Worktree creation (`opsx worktree ensure`), locator publication to the
   integration checkout (ADR-0023 pattern), Diff Base SHA recorded in
   review.md — the locator commit itself path-scoped (A2, practiced live).
2. Phase 1 (CLI) — gate `--cheap` first (1.1) since status (1.2) consumes it;
   then archive-check (1.3); tier collapse (1.4) + derivation (1.5) together
   (same parsing region); model-config (1.6); loop budget read (1.7).
3. Phase 2 (schema/templates) — after 1.4 fixes the vocabulary the templates
   must document.
4. Phase 3 (skills) — after CLI verbs exist so prose can name real commands.
5. Phase 4 (tests) — alongside each phase where practical; sweep at end.
6. Phase 5 — verify.md, then gating code review (2 pinned models, blind,
   convergence discipline), doneness (XL under the OLD deployed gate ⇒
   independent blind judge), gate green, loop_hold landing.

## Risks

- **Self-referential migration:** this change is judged by the DEPLOYED
  (5-tier) gate while its worktree tests pin the NEW (3-tier) gate binary.
  Keep the two views distinct in tests (tests invoke the worktree's
  `executable_opsx`, never the deployed `opsx`). Its own `scale: XL` stays
  valid for its whole lifecycle (design D3 migration wrinkle).
- **`--cheap` correctness:** guarding the wrong block silently weakens the
  full gate. Tests must pin that a full `opsx gate` run still executes
  validation commands after this change (regression pin), and that `--cheap`
  is label-visible in output.
- **Write-surface regression (R2-1):** atomic-write/comment-preservation
  behavior must survive the project-layer removal — the restated scenarios
  are pinned in 4.3.
- **Skill-prose drift:** 4.4 surface pins are the enforcement for D9 prose;
  every new rule (path-scoped commits, archive-check, combined dispatch) gets
  a grep-level pin.
- **Consolidation at archive (D8):** retired spec dirs are deleted at archive
  time by skill prose, not by this change's code — nothing to implement now;
  the archive-change skill edit (3.2) carries it.

## Validation gates (opsx-gates.yaml + change-specific)

- `openspec validate simplify-and-parallelize-opsx-workflow --strict`
- `openspec validate --specs --strict`
- `bash -n dot_local/bin/executable_opsx`
- `bun test dot_pi/agent/extensions/opsx-loop/`
- `bash tests/opsx-cli/test_opsx_cli.sh`
- `bash tests/opsx-gate/test_opsx_gate.sh`
- `bash tests/opsx-models/test_opsx_models.sh`
- `bash tests/opsx-review-convergence/test_review_convergence_surfaces.sh`
