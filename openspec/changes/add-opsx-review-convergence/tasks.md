## 1. Templates (opsx-superpowers schema)

- [x] 1.1 Extend `templates/review.md`: add commented `review_max_rounds` front-matter key (default-5 semantics documented) and a `Scope Expansions` section with evidence-entry format
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md
  - allow_new_files: false
- [x] 1.2 Extend `templates/code-review.md`: verdict-contract + severity-rubric header (baseline-bounded contract, single lens, P0-P3 definitions), round-ledger fields on the existing Round tracker (per-reviewer verdicts + reviewed HEAD + consolidated max-across-reviewers counts), `review_mode` vocabulary gains `disclosure-consensus`, and a `waived_by_user` field slot
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/code-review.md
  - allow_new_files: false
- [x] 1.3 Add new `templates/follow-ups.md`: out-of-scope finding queue (finding, severity, origin round/review-type, routing reason, user-waived marker), authored on first routing, surfaced at archive
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/follow-ups.md
  - allow_new_files: true

## 2. Orchestrator skill (canonical source)

- [ ] 2.1 Extend `openspec-loop/SKILL.md` with the convergence discipline: round ledger maintenance (consolidated counts = max across reviewers), stop conditions (converged / flat-or-rising 2 rounds / `review_max_rounds` default 5), single disclosure round trigger + marking, decision-audit landing (tiered audit, waiver semantics incl. `waived_by_user` re-seal + budget extension on resume, halt loop continuation), scope-widening protocol (evidence-gated, `Scope Expansions` logging, follow-ups.md routing), advisory surface audit for property-style intents, reviewer-model stability rule, and red-flag list (no ledger/prior findings in blind prompts; no mid-change model additions; no second disclosure round)
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md
  - allow_new_files: false

## 3. Apply-mode reference (canonical source)

- [ ] 3.1 Extend `openspec-apply-change/references/opsx-superpowers-mode.md`: code-review production runs under the convergence discipline — reviewer dispatch prompt embeds the verdict contract + rubric, verdict computed under the severity floor (pass ⟺ no open P0/P1), ledger sealed in code-review.md covering every round including disclosure, follow-ups.md authored on first out-of-scope routing
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md
  - allow_new_files: false

## 4. Consistency + validation

- [ ] 4.1 Cross-check pass: grep the edited skill/templates for contradictions with the delta specs (stop-condition wording, default budget value, disclosure trigger, waiver field name) and reconcile; confirm no edit touches `opsx gate` decision logic or the opsx-loop extension
  - intent: fix
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/*.md
  - allow_new_files: false
- [ ] 4.2 Run the full opsx-gates.yaml validator set (openspec validate --changes --strict, gate/CLI/models/extension tests, shell syntax) and confirm all required gates green with zero regressions
  - intent: infra
  - files_allowed:
      - openspec/changes/add-opsx-review-convergence/**
  - allow_new_files: false
