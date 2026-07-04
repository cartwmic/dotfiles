# Plan: quiet-round-review-convergence

## Order

1. Worktree creation (`opsx worktree ensure`), locator publication to the
   integration checkout, Diff Base SHA + Worktree Path recorded in review.md —
   the locator commit path-scoped.
2. Phase 1 (CLI + gate) — sweep subcommand (1.1) before dispatch/usage wiring
   (1.2, names the verb) before the gate conditional check (1.3, calls the
   same implementation); Q4 riders (1.4) last in the file since the fail-open
   audit wants the final key set; pins (1.5) alongside each.
3. Phase 2 (schema/templates) — after 1.x so the documented key/format names
   match the implemented ones exactly.
4. Phase 3 (skill prose) — after CLI verbs exist so the skill names a real
   `opsx sweep`; SKILL.md is the Constitution IX trigger surface.
5. Phase 4 — verify.md, then gating 2-model blind code review (pinned
   `[claude-bridge/claude-opus-4-8, claude-bridge/claude-sonnet-5]`, blind,
   convergence discipline — this change reviews under the CURRENT deployed
   protocol, land-on-stop per its own review.md `review_max_rounds: 5`
   default semantics), doneness (full_rigor ⇒ independent blind judge), gate
   green, loop_hold landing. Loop never archives.

## Risks

- **Self-referential semantics:** this change SPECS quiet-round semantics
  while being REVIEWED under the currently deployed protocol. The two must
  not be conflated: its own review rounds obey the deployed stop rules
  (budget 5, decision-audit landings); the NEW rules ship for successor
  changes. Tests pin the worktree binary/skill text, never the deployed
  copies.
- **Sweep false-negatives via exclusion breadth:** excluding all
  `openspec/**` means a stale token in live specs is NOT swept — by design
  (specs migrate at archive), but verify.md must note the residual class so
  nobody assumes spec coverage.
- **Fail-open audit scope creep:** 1.4's audit could balloon into refactors.
  Contract: assert-or-fix ONLY divergences between documented promise and
  absent-key behavior; anything else routes to follow-ups.md.
- **Skill-prose drift:** 3.2 grep pins are the enforcement for every new
  directive (quiet-round table, sweep trigger, template-fill); pins target
  the canonical skill path.
- **Gate check ordering:** the conditional sweep check must respect Cheap
  Before Expensive Ordering and not run validations; gate tests pin that a
  sweep-hitting change short-circuits cheaply.

## Validation gates (opsx-gates.yaml + change-specific)

- `openspec validate quiet-round-review-convergence --strict`
- `openspec validate --specs --strict`
- `bash -n dot_local/bin/executable_opsx`
- `bun test dot_pi/agent/extensions/opsx-loop/`
- `bash tests/opsx-cli/test_opsx_cli.sh`
- `bash tests/opsx-gate/test_opsx_gate.sh`
- `bash tests/opsx-models/test_opsx_models.sh`
- `bash tests/opsx-review-convergence/test_review_convergence_surfaces.sh`
- `bash tests/opsx-gate/test_author_marker.sh`
