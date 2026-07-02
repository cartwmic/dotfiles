<!-- authored: in-session -->
# Plan — add-opsx-doneness-judge

Execution driver for `openspec-apply-change`. Single-agent, worktree-required. Each step
ends with a commit (subject ≤72). Validators per step below.

## Step P1 — Gate doneness enforcement (Covers: T1.1, T1.2)
- **Pre-conditions:** worktree created; Diff Base SHA recorded in review.md; `opsx_gate`
  subshell located in `dot_local/bin/executable_opsx`.
- **Action:**
  1. Write the doneness gate tests (`tests/opsx-gate/`) citing
     `opsx-gate-enforcement.doneness-verdict-enforcement` — expect FAIL (feature absent).
  2. Run the suite → expect the new cases FAIL.
  3. Implement the doneness block in `opsx_gate`: front-matter reads (`doneness_mode`,
     `scale`, immutable Diff Base); field parse of `doneness.md`; provenance / freshness /
     intent-hash / diff-base / mode+scale gating; emit-only-as-sole-remaining suppression;
     lifecycle order last; bare-waiver fail. No model call.
  4. Run the suite → expect PASS.
  5. Commit `feat(opsx): gate enforces sealed doneness verdict at Scale>=M`.
- **Verification:** `tests/opsx-gate/*.sh`; `bash -n dot_local/bin/executable_opsx`; a live
  `opsx gate` self-run on a fixture.
- **Rollback:** revert the `opsx_gate` doneness block; tests isolate it.

## Step P2 — Schema + templates (Covers: T2.1)
- **Pre-conditions:** P1 shape known (field names the gate reads).
- **Action:**
  1. Add `templates/doneness.md` with the exact machine-read fields.
  2. Add `doneness_mode` + `doneness_waiver_rationale` to `templates/review.md`
     (front-matter + prose table).
  3. Document the doneness template contract in `schema.yaml` apply.instruction + mode docs;
     touch README/capability-hooks as needed.
  4. `openspec schema validate opsx-superpowers` (or the repo's schema check) → PASS.
  5. Commit `feat(opsx): doneness.md template + doneness_mode switchboard`.
- **Verification:** schema validate; `openspec validate --specs --strict` unaffected.
- **Rollback:** remove the template + front-matter field.

## Step P3 — openspec-loop skill dispatch (Covers: T3.1) — Constitution IX
- **Pre-conditions:** P1/P2 (gate + fields) landed.
- **Action:**
  1. Edit `openspec-loop` SKILL.md: add the doneness-judge dispatch step (review role,
     blind, after mechanical green, seal doneness.md; no-adapter → absent-or-`not`; re-judge
     stale; bare waiver resolved in-loop).
  2. Keep any deployed copy in sync via chezmoi source-of-truth.
  3. Commit `docs(opsx): openspec-loop dispatches the blind doneness judge`.
- **Verification:** prose diff review; skill referenced by `apply_harness_config` linking.
- **Rollback:** revert the SKILL.md hunk.

## Step P4 — Extension doneness-aware stall (Covers: T4.1, T4.2)
- **Pre-conditions:** doneness.md field/gaps format fixed (P2).
- **Action:**
  1. Write `helpers.test.ts` ratchet cases citing
     `opsx-loop-kickoff.stall-detection-stops-the-loop` — expect FAIL.
  2. `bun test helpers.test.ts` → expect FAIL.
  3. Implement `parseDonenessGaps` + running-min ratchet in `helpers.ts`; wire the
     doneness-blocked branch into `index.ts` `agent_end` (activation, min_gaps, empty-set
     sentinel not progress, direct doneness.md classification).
  4. `bun test helpers.test.ts` → PASS; `bun build index.ts --target node` → clean.
  5. Commit `feat(opsx-loop): doneness-aware stall (running-min gap-set ratchet)`.
- **Verification:** bun tests; transpile; deployed==source diff at apply-deploy time.
- **Rollback:** revert helpers/index hunks; tests isolate.

## Step P5 — Verify (Covers: T6.1)
- **Action:** run the full gauntlet (all gate suites, extension bun tests, transpile,
  `bash -n`, `openspec validate --strict`, forward AC↔test grep of every change-spec AC ID
  against diff files), author `verify.md` green (uncommitted per contract).
- **Verification:** the 6 verify checks.
- **Rollback:** n/a (verify is a report).

## Post-apply (skill-managed, not a plan step)
- Blind multi-model code-review (Constitution IX) over `Diff Base..HEAD` → `code-review.md`.
- `opsx gate add-opsx-doneness-judge --worktree <wt>` green (doneness waived for this
  bootstrap change).
- ADR promotion (T5.1) at archive.
