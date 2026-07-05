# Plan — harden-opsx-reviewer-dispatch-integrity (Scale S)

## Approach

Two enforcement layers, shipped together:

1. **Gate (deterministic)** — `executable_opsx`: when `code_review_mode` is
   gating-required, `code-review.md` must carry own-line `**Attested HEAD:**`
   whose value is a full 40-hex literal equal to the full SHA of the recorded
   Reviewed Range head (symbolic/short forms unparseable → fail-closed).
   Same binding on `doneness.md` only when doneness is required AND
   `full_rigor` is true (independent judge). Extends the existing
   `cr_field`/`freshness_check` machinery; no new subcommand.
2. **Orchestrator procedure (skill prose + templates)** — dispatch preamble
   (reviewer records verbatim `git rev-parse HEAD` + `git rev-parse
   --show-toplevel` as first findings lines), invalid-verdict consolidation
   rule (mismatch/missing = INVALID, excluded from gating/ledger/trajectory;
   2 consecutive all-invalid attempts → decision-audit landing), and the
   per-round read-only snapshot window (HEAD + `status --porcelain=v1`,
   change-dir paths excluded; delta voids the round; surgical restore).

Order: gate + tests first (deterministic core), then templates, then skill
prose, then full validation sweep.

## Inline analyze record (Scale S: checks 1, 2, 7)

- **Check 1 — artifact contradictions:** intent G2/G3 ↔ proposal ↔ 3 delta
  specs cross-read after clarify patches; the C3 resolution (round-window,
  exclusion set) supersedes intent's per-dispatch phrasing as an evidence-
  grounded mechanism refinement — intent's outcome (delta voids verdict,
  restore, record) preserved. No contradictions. PASS.
- **Check 2 — constitution/domain:** gate stays deterministic/model-free
  (ADR-0007 lineage); Constitution IX honored via explicit gating-required
  CR mode; no autonomous archive/deploy surface touched. PASS.
- **Check 7 — readiness for tasks:** all surfaces named with anchors
  (executable_opsx cr_field ~915 / freshness_check ~950 / doneness block
  ~1046; both templates; two skill files; two test suites). PASS.

## Validation

- `bash -n dot_local/bin/executable_opsx`
- `tests/opsx-gate/test_opsx_gate.sh` (currently 128)
- `tests/opsx-cli/test_opsx_cli.sh` (67), `tests/opsx-models/test_opsx_models.sh` (34)
- `tests/opsx-review-convergence/test_review_convergence_surfaces.sh` (152)
- `tests/opsx-gate/test_author_marker.sh` (4)
- `openspec validate harden-opsx-reviewer-dispatch-integrity --strict`; `openspec validate --specs --strict`
