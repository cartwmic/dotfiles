# Plan: harden-opsx-repo-portability

<!-- authored: in-session -->

Scale S — simple ordered list (worktree_mode tier-derived: same-tree).

1. Add `opsx_integration_branch()` resolver to `dot_local/bin/executable_opsx`
   (locator field after trim, `<detected-at-capture>` sentinel excluded →
   `origin/HEAD` short name → local `main` → local `master` → named error for
   blocking invokers). Pure git plumbing + file read; BSD-safe.
2. Route the three functional `main` sites through it: `opsx status`
   staleness (degrade to placeholder + exit 0 when unresolvable), archive-check
   base-currency (messages name the resolved branch), multi-dir detector range.
3. Gate preflight: `test -s openspec/constitution.md` + `test -s
   openspec/domain.md` in the cheap-check block, every Scale; GATE-FAIL
   directive names constitution-template.md / domain-template.md.
4. Template: review.md `**Integration Branch:**` → `<detected-at-capture>`
   sentinel; audit skill-reference prose asserting literal `main` for these
   checks.
5. Tests (opsx-cli + opsx-gate suites): resolver order incl. sentinel skip,
   master-only, fail-loud, status degrade; preflight red/green per artifact;
   non-main base-currency pass/fail.
6. Verify sweep: all suites + both `openspec validate --strict`; verify.md
   filled from shipped template. Then advisory code review (S tier-derived
   mode) per loop procedure.

## Analyze (Scale S — checks 1, 2, 7 only; deterministic, inline)

- Check 1 (constitution): resolver + preflight are deterministic/model-free
  (ADR-0007 lineage) — no conflict; fail-closed posture matches gate
  principles; no legacy entrypoints touched. PASS.
- Check 2 (domain): no domain invariant touches branch naming or artifact
  preflight; locator field already domain-established (worktree lifecycle
  ownership). PASS.
- Check 7 (traceability/readiness): every delta AC traces to intent Q1/Q2/D1-D5;
  tasks below tile the six delta requirements; no orphan AC, no orphan task.
  AC IDs: opsx-cli.integration-branch-resolution,
  opsx-cli.status-fleet-view, opsx-cli.multi-dir-integration-commit-detector,
  opsx-gate-enforcement.project-artifact-preflight,
  opsx-gate-enforcement.land-base-currency,
  opsx-workflow-schema.integration-branch-locator-default-detected. PASS.
