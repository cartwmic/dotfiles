# Tasks: quiet-round-review-convergence

File contracts per task. All implementation in the `opsx/<change>` worktree
(worktree-required, M tier). Integration-checkout commits stay path-scoped
(`git commit -- openspec/changes/quiet-round-review-convergence`).

## Phase 1 — CLI + gate (Q2 sweep, Q4 riders)

- [x] 1.1 `opsx sweep <change>` subcommand (D3, opsx-cli.Migration Completeness
      Sweep Command): read `openspec/changes/<change>/sweep.txt` (one ERE per
      line, `#` comments + blanks ignored; zero effective patterns = clean
      pass); resolve the implementation checkout exactly as the gate does
      (recorded locator / convention path when worktree-required, integration
      otherwise; explicit `--worktree` validated loudly, hard-fail on invalid);
      `git ls-files -z` in the resolved checkout minus `openspec/**` and
      `adr/**`; `grep -nE` per pattern; emit `SWEEP-HIT <pattern> <file>:<line>`
      per hit → exit 1; grep error (exit ≥2) → `SWEEP-ERROR <pattern>` → exit
      non-zero; missing sweep.txt → one-line notice → exit 0.
      - files_allowed:
        - dot_local/bin/executable_opsx
- [x] 1.2 Dispatch + usage wiring (opsx-cli.Unified Subcommand Dispatch): add
      `sweep` case arm; add usage line; MERGE the two `gate` usage lines into
      an adjacent consolidated entry preserving both option forms (R3-A2).
      - files_allowed:
        - dot_local/bin/executable_opsx
- [x] 1.3 Gate conditional sweep check (opsx-gate-enforcement.Migration Sweep
      Gate Check): WHEN sweep.txt exists in the change dir, run the sweep as a
      cheap deterministic check against the SAME resolved ART_ROOT the gate
      uses; hits → `GATE-FAIL sweep`; no sweep.txt → check absent, exit code
      unaffected.
      - files_allowed:
        - dot_local/bin/executable_opsx
- [x] 1.4 Q4 hygiene riders (D5): `git rm`
      `tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp`
      (stray empty file); fail-open-by-omission audit over derived/defaulted
      mode keys read by executable_opsx + skills (worktree_mode,
      code_review_mode, doneness_mode, validation_source_mode,
      review_budget_mode, review_max_rounds, loop_hold, full_rigor, scale) —
      assert each absent-key default matches its documented promise, fix any
      divergence (review_budget_mode absent⇒quiet-round is pre-cleared
      intentional, F7); record audit table in verify.md.
      - files_allowed:
        - dot_local/bin/executable_opsx
        - tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp
- [x] 1.5 Shell-test pins for 1.1–1.4 (proposal success criteria 2, 4):
      cli tests — sweep dispatch, SWEEP-HIT exit 1 on planted stale surface,
      clean pass after cleanup, empty/missing declaration soft passes,
      SWEEP-ERROR on malformed ERE, history-surface non-hit, usage gate-forms
      grep; gate tests — GATE-FAIL sweep on declared hit, conditional absence
      without sweep.txt, worktree-resolved sweep (fix landed only in worktree
      passes).
      - files_allowed:
        - tests/opsx-cli/test_opsx_cli.sh
        - tests/opsx-gate/test_opsx_gate.sh

## Phase 2 — Schema + templates (Q1 key, Q2 declaration, Q4 row)

- [ ] 2.1 review.md template (opsx-workflow-schema.Review Budget Mode Front
      Matter + Template Mode Table Mirrors Derived Defaults): document
      `review_budget_mode` (commented) alongside `review_max_rounds` with the
      quiet-round default + land-on-stop opt-in + unknown-fails-strict note;
      fix the Code Review Mode prose-table row to "derived (gating-required at
      M, advisory below)" (Q4).
      - files_allowed:
        - dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md
- [ ] 2.2 schema.yaml + README (opsx-workflow-schema.Migration Sweep
      Declaration): document sweep.txt format (ERE per line, comments/blanks,
      empty = clean), the swept-surface exclusion (`openspec/**`, `adr/**`),
      the conditional gate check, and the review_budget_mode key.
      - files_allowed:
        - dot_local/share/openspec/schemas/opsx-superpowers/schema.yaml
        - dot_local/share/openspec/schemas/opsx-superpowers/README.md
- [ ] 2.3 Surfaces-test pins for 2.1–2.2: template carries commented
      review_budget_mode key; Code Review Mode row shows derived semantics
      (never literal `advisory`); README/schema document sweep.txt; stray
      `.tmp` absence pin (1.4).
      - files_allowed:
        - tests/opsx-review-convergence/test_review_convergence_surfaces.sh

## Phase 3 — Skill prose (Q1 cycle, Q2 trigger, Q3 templates)

- [ ] 3.1 openspec-loop SKILL.md (opsx-skill-integration.openspec-loop
      orchestrator skill exists): replace the Stop-conditions table with the
      ordered quiet-round evaluation — (a) quiet → seal pass; (b) converging
      (findings + change-scoped progress + rounds<cap) → continue autonomously,
      round TYPE still governed by the disclosure trigger; (c) thrash (no
      fix landed) → decision-audit landing; (d) hard cap → landing — including
      fix-before-evaluate ordering (F4), the per-round-type progress signals
      (worktree HEAD post-apply w/ bookkeeping-off-branch invariant;
      fix-surface commits for analyze-type, R3-B1), and
      `review_budget_mode: land-on-stop` as the documented opt-in; add the
      pre-round-1 `opsx sweep <change>` directive for sweep.txt-declaring
      changes (Q2); rewrite verdict-artifact directives to FILL the shipped
      template paths (verify/code-review/doneness) instead of free-writing
      (Q3).
      - files_allowed:
        - dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md
- [ ] 3.2 Surfaces-test pins for 3.1: skill contains quiet-round ordered
      table, land-on-stop opt-in mention, sweep-before-round-1 directive,
      template-path fill directives; no free-write verdict instruction
      remains (success criterion 3).
      - files_allowed:
        - tests/opsx-review-convergence/test_review_convergence_surfaces.sh

## Phase 4 — Verification

- [ ] 4.1 Full validator sweep + verify.md: run all suites (opsx-cli, opsx-gate,
      opsx-models, opsx-review-convergence surfaces, author-marker, bun loop
      tests, both openspec stricts); record fail-open audit table (1.4) and
      the replay evidence pointer (design Replay validation); seal verify.md
      from the shipped template with Reviewed Range.
      - files_allowed:
        - openspec/changes/quiet-round-review-convergence/verify.md
