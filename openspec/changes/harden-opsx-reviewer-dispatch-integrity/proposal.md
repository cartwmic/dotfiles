## Why

Two mechanically undetected reviewer-dispatch integrity failures were observed
in a live opsx-loop run (oxide-clone `crypt-secret-structural-hardening`,
2026-07-05, session `019f2d9f`): a blind reviewer reviewed the wrong tree in
two rounds (dispatch omitted `cwd`; its verdicts were plausible-looking
artifacts), and the same reviewer slot later edited five worktree files
mid-review and self-declared "pass". A verdict is only meaningful if computed
read-only against the exact tree in the recorded Reviewed Range; today nothing
enforces either property (Constitution IX's gating review depends on both).

## What Changes

- **G2 — tree-identity attestation.** Every blind reviewer/judge dispatch
  prompt requires the subagent to attest, before reviewing, the tree it is
  actually in: record `git rev-parse HEAD` output and the resolved working
  directory as machine-readable lines in its findings output. The orchestrator
  treats a verdict with a missing or mismatched attestation as **INVALID**
  (distinct from fail): it never satisfies multi-model gating, never enters the
  round ledger as a reviewer verdict, and never counts toward
  `review_max_rounds` trajectory; the round is re-dispatched (or the reviewer
  set repaired).
- **G2 — sealed-artifact field.** `code-review.md` (and `doneness.md` when an
  independent judge is dispatched) gains a required own-line field
  `**Attested HEAD:** <sha>` — the tree HEAD all counted reviewers attested.
  The orchestrator seals it only when every counted reviewer's attestation
  matches; per-reviewer detail stays in the round ledger.
- **G2 — gate check (fail-closed).** When code review is `gating-required`,
  `opsx gate` requires `Attested HEAD` in `code-review.md` and fails the check
  unless it rev-parses equal to the recorded Reviewed Range head. Same binding
  for `doneness.md` when doneness is enforced with an independent judge
  (full_rigor). Absent/unparseable field = failed check. Enforced for newly
  sealed verdicts only (archived changes are never re-gated).
- **G3 — read-only dispatch enforcement.** The orchestrator captures a
  deterministic snapshot of the reviewed tree immediately before each
  reviewer/judge dispatch (`git rev-parse HEAD` + `git status --porcelain=v1`
  output) and compares immediately after the subagent returns. Any delta
  attributable to the dispatch voids that reviewer's verdict (INVALID), the
  orchestrator restores the pre-dispatch state (`git restore` for tracked
  modifications; delete untracked paths introduced by the delta), and the
  incident is recorded in the round ledger / Execution Notes. Plain git only;
  works in same-tree and worktree modes.
- Skill prose + dispatch templates updated so the attestation preamble, the
  invalid-verdict consolidation rule, and the snapshot/compare/restore
  procedure are part of the documented dispatch procedure (openspec-loop
  SKILL, openspec-apply-change opsx-superpowers-mode reference, code-review.md
  and doneness.md templates).
- Tests: opsx-gate suite covers attestation present+matching (green), absent
  (red), mismatched (red); template/skill surface pins in the
  review-convergence suite.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `opsx-adversarial-review`: ADDED requirements — reviewer tree-identity
  attestation (dispatch preamble + invalid-verdict consolidation semantics)
  and read-only dispatch enforcement (snapshot/compare/void/restore).
- `opsx-gate-enforcement`: MODIFIED — mode-aware verdict reading gains the
  fail-closed `Attested HEAD` field requirement bound to the Reviewed Range
  head (code-review.md when gating-required; doneness.md for the independent
  full_rigor judge).
- `opsx-workflow-schema`: MODIFIED — code-review.md and doneness.md template
  field surface gains `Attested HEAD` (gate-read verbatim).

## Impact

Affected files:
- `dot_local/bin/executable_opsx` — gate: attestation field checks + binding
  to Reviewed Range head (extends existing `freshness_check`/field machinery;
  no new subcommand, keyword grammar unchanged).
- `dot_local/share/openspec/schemas/opsx-superpowers/templates/code-review.md`
  — `**Attested HEAD:**` field + header-comment contract; dispatch-prompt
  contract text gains the attestation preamble.
- `dot_local/share/openspec/schemas/opsx-superpowers/templates/doneness.md` —
  same field for the independent judge path.
- `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md` —
  dispatch procedure: attestation preamble requirement, invalid-verdict rule,
  pre/post snapshot + restore procedure.
- `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`
  — post-impl review dispatch contract: same three additions.
- `tests/opsx-gate/test_opsx_gate.sh`, `tests/opsx-review-convergence/test_review_convergence_surfaces.sh`
  — new cases + surface pins.

Affects this repo only (workflow tooling); no runtime product code.

## Open Questions

- (none — mechanism decisions recorded above; ambiguities resolved in specs
  via the clarify pass)
