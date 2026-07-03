## 1. Prose surfaces

- [x] 1.1 Add the ledger-repair red-flag line to the openspec-loop skill (Review convergence section) and the apply-mode reference (convergence bullet): a sealed multi-round Verdict with no ledger row is a provenance defect — repair the ledger before archive
  - intent: fix
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md
  - allow_new_files: false
- [x] 1.2 Rename code-review template heading `## Convergent findings` → `## Findings`, preserving the mandatory gate-manifest check comment beneath it
  - intent: fix
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/code-review.md
  - allow_new_files: false

## 2. Test

- [x] 2.1 Surface test: add `set -e`-omission comment; add assertions pinning the red-flag line (both skill surfaces) and the neutral `## Findings` heading, citing opsx-review-convergence.prose-surface-fidelity
  - intent: fix
  - files_allowed:
      - tests/opsx-review-convergence/test_review_convergence_surfaces.sh
  - allow_new_files: false
- [ ] 2.2 Run the full opsx-gates.yaml validator set; all required gates green
  - intent: infra
  - files_allowed:
      - openspec/changes/polish-review-convergence-surfaces/**
  - allow_new_files: false
