# Tasks — harden-opsx-reviewer-dispatch-integrity

## 1. Gate enforcement (executable_opsx)

- [x] 1.1 code-review check: when `CR_MODE=gating-required`, require own-line
      `**Attested HEAD:**` in code-review.md; value must match `^[0-9a-f]{40}$`
      (else unparseable → failed check, message names the remedy) and equal the
      full SHA the gate computes for the recorded Reviewed Range head. Never
      resolve symbolic refs from the field.
      (opsx-gate-enforcement.verdict-freshness-and-provenance)
- [x] 1.2 doneness check: same 40-hex + equality binding on doneness.md ONLY
      when doneness is required AND `full_rigor` is true (independent judge);
      plain-M combined dispatch demands nothing on doneness.md.
      (opsx-gate-enforcement.verdict-freshness-and-provenance)

## 2. Schema templates

- [x] 2.1 templates/code-review.md: add `**Attested HEAD:**` own-line field +
      header-comment (gate-read verbatim, full 40-hex, must equal Reviewed
      Range head); extend the embedded verdict-contract/dispatch text with the
      attestation preamble (verbatim `git rev-parse HEAD` +
      `git rev-parse --show-toplevel` as reviewer's first findings lines).
      (opsx-workflow-schema.convergence-template-support)
- [x] 2.2 templates/doneness.md: add `**Attested HEAD:**` field with
      independent-judge (full_rigor) scoping note.
      (opsx-workflow-schema.convergence-template-support)

## 3. Skill prose (dispatch procedure)

- [x] 3.1 openspec-loop SKILL.md: attestation preamble requirement in every
      blind dispatch; INVALID-verdict consolidation rule (mismatch/missing →
      excluded from gating/ledger/`review_max_rounds`; re-dispatch; 2
      consecutive all-invalid attempts → decision-audit landing with
      dispatch-integrity error); per-round read-only snapshot window
      (capture HEAD + `git status --porcelain=v1` before first dispatch /
      after last return, exclude `openspec/changes/<change>/` paths, no other
      orchestrator in-window writes; delta → void ALL round verdicts, surgical
      restore, record incident).
      (opsx-adversarial-review.reviewer-tree-identity-attestation,
       opsx-adversarial-review.read-only-reviewer-dispatch)
- [x] 3.2 openspec-apply-change references/opsx-superpowers-mode.md: same
      three additions in the post-impl review dispatch contract.
      (opsx-adversarial-review.reviewer-tree-identity-attestation,
       opsx-adversarial-review.read-only-reviewer-dispatch)

## 4. Tests

- [x] 4.1 tests/opsx-gate/test_opsx_gate.sh: attestation present+matching →
      green; absent → red; short SHA → red (unparseable); symbolic `HEAD` →
      red; mismatched 40-hex → red; advisory (S, derived) missing field →
      no block; doneness binding red/green under full_rigor; plain-M doneness
      without the field → not demanded.
      (opsx-gate-enforcement.verdict-freshness-and-provenance)
- [x] 4.2 tests/opsx-review-convergence/test_review_convergence_surfaces.sh:
      surface pins — both templates carry the field, code-review template
      dispatch text carries the preamble tokens, both skill files carry the
      attestation/INVALID/snapshot tokens.
      (opsx-workflow-schema.convergence-template-support,
       opsx-adversarial-review.reviewer-tree-identity-attestation,
       opsx-adversarial-review.read-only-reviewer-dispatch)

## 5. Verify

- [ ] 5.1 Full validation sweep (plan.md list) green; author verify.md from
      the shipped template with Diff Base SHA + Reviewed Range freshness
      fields.
