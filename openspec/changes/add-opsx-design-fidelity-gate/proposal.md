## Why

The oxide-clone `crypt-secret-structural-hardening` run (session
`019f2d9f-6550-76da-8980-8d8cfc5eaeb2`) proved the pre-implementation quality
stack has a semantic hole: design.md silently swapped the frozen intent's
type-level guarantee for manual per-site redaction while its rationale still
claimed the guarantee, and the analyze artifact's nominal AC↔design coverage
check (Check 3) passed it. The defect cost three post-impl P0 review rounds and
an owner escalation to root-cause. Three residual dispatch-integrity defects
from the same evidence base remain unfixed (reply-trusted verdicts, integration-
checkout reviewer writes, post-seal bookkeeping staling), and `worktree_mode`
same-tree execution is the root enabler of the staling family while blocking
parallel development. Constitution: fail-closed gate lineage (ADR-0007
model-free gate; doneness-judge precedent for sealed judged verdicts).

## What Changes

- **New sealed artifact `design-fidelity.md`** (shipped template): blind
  per-AC entailment sweep over every delta AC — `entailed | not-entailed |
  not-covered` rows with evidence, overall `Fidelity: delivered | violated`,
  judge provenance, tree-identity attestation, and digest binding (sha256 of
  intent.md + design.md + every delta spec file). Bounded judge contract:
  blocks only on clear non-entailment of the AC as written; ambiguity routes
  to clarify-class advisories.
- **New gate check `design-fidelity`** in `executable_opsx`: design-conditioned
  (design.md present ⇒ required at any Scale), fail-closed on absent / stale
  (digest mismatch, recomputed by the gate) / `violated` / unparseable.
  Deterministic, model-free: parses sealed fields + recomputes sha256 only.
- **Dispatch channels**: full_rigor — fidelity rides the existing blind
  analyze dispatch as a REQUIRED section, sealed to the separate artifact;
  plain M / design-bearing S — one narrow post-design blind mini-dispatch.
  Escalation valve: two consecutive `violated` verdicts with fixes landing
  (or unfixable rows) route to the decision-audit landing.
- **Findings file = sole verdict source** (all judged dispatches): verdict,
  findings, attestation derived exclusively from the subagent's output file;
  conversational reply never trusted; absent/verdict-less file consolidates
  INVALID.
- **Dual-tree read-only window**: when reviewed tree ≠ integration checkout,
  the pre/post round snapshot covers BOTH trees; a delta in either voids the
  round (same surgical-restore + incident-record procedure).
- **BREAKING — worktree-mandatory execution**: `worktree_mode` key, tier
  derivation, and every same-tree code path removed (same-tree Diff Base
  capture, archive-check same-tree exemption, same-tree freshness handling,
  attestation path-check carve-out, skills/templates/tests branches). A
  declared `worktree_mode` key fails closed naming the removal. Every change
  at every Scale (incl. XS) runs ensure → locator → apply → review → merge →
  cleanup in an isolated worktree.
- **Post-seal bookkeeping without staling**: subsumed by worktree-mandatory
  (bookkeeping lands on the integration checkout; reviewed HEAD never moves);
  outcome test-pinned — post-seal loop_hold/follow-ups/Execution-Notes edits
  stale nothing, while gate-read decision inputs stay freshness-protected.

## Impact

- `dot_local/bin/executable_opsx` — new design-fidelity check; same-tree
  branch removal (Diff Base capture, archive-check exemption, freshness,
  attestation carve-out); worktree_mode fail-closed rejection.
- `dot_local/share/openspec/schemas/opsx-superpowers/` — new
  `templates/design-fidelity.md`; `templates/review.md` (mode key removed),
  `templates/analyze.md` (full_rigor fidelity section), `schema.yaml`,
  `README.md`.
- `dot_local/share/agent-harness/canonical/skills/` — openspec-loop SKILL.md
  (fidelity dispatch, verdict-source rule, dual-tree window, worktree-always),
  openspec-apply-change + openspec-propose + openspec-archive-change
  references, openspec-explore SKILL.md (scale guidance mentions worktree).
- Tests — `tests/opsx-gate/test_opsx_gate.sh` (fidelity states × channels,
  worktree_mode rejection, post-seal bookkeeping cases, same-tree fixture
  migration), `tests/opsx-cli/test_opsx_cli.sh` (same-tree exemption removal),
  `tests/opsx-review-convergence/test_review_convergence_surfaces.sh`
  (surface pins).
- Specs — deltas on `opsx-gate-enforcement`, `opsx-adversarial-review`,
  `opsx-workflow-schema`, `opsx-skill-integration` (opsx-cli untouched: worktree
  lifecycle commands, locator emit, and resolver are reused as-is; the removal
  surface is mode/derivation/exemptions, which live in the other four).
  Touched requirements (clarify C1 + analyze R1/R2 — every surviving same-tree
  surface is in the delta set): gate-enforcement ADDED Design Fidelity Verdict
  Enforcement / Worktree Mandatory Gate Enforcement / Post Seal Bookkeeping
  Non Staling, MODIFIED Verdict Freshness And Provenance / Land Base Currency /
  Migration Sweep Gate Check; adversarial-review ADDED Design Fidelity Judge /
  Findings File Sole Verdict Source, MODIFIED Reviewer Tree Identity
  Attestation / Read Only Reviewer Dispatch / Orchestrator Round Ledger / Post
  Apply Code Review Artifact; workflow-schema ADDED Design Fidelity Artifact
  Template, MODIFIED Mode switchboard in review.md / Worktree Lifecycle
  Ownership / Per-task file contracts / Apply-time writeback and workspace
  discipline; skill-integration ADDED Worktree Always Skill Discipline,
  MODIFIED Mode-driven openspec-apply-change / Analyze gates tasks generation;
  opsx-loop MODIFIED Worktree resolution convention fallback.
- **BREAKING**: in-flight same-tree changes must be re-homed to worktrees or
  archived before deployment; none active besides this change (verified:
  `openspec list` shows only add-opsx-design-fidelity-gate).
