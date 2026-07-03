# Tasks: simplify-and-parallelize-opsx-workflow

File contracts per task. All implementation in the `opsx/<change>` worktree
(worktree-required). Integration-checkout commits stay path-scoped
(`git commit -- openspec/changes/simplify-and-parallelize-opsx-workflow`).

## Phase 1 — CLI (gate + new verbs), D1/D2/D3/D6/D7

- [x] 1.1 `opsx gate --cheap` mode (D1): flag guards ONLY validation-command
      execution + validation-source enforcement; does NOT exit at the
      cheap-checks short-circuit; report labels the run `gate(cheap)`.
      Files: `dot_local/bin/executable_opsx`.
- [x] 1.2 `opsx status` fleet view (D1, opsx-cli.Status Fleet View): scan
      non-archive `openspec/changes/*`; per change print Scale(+full_rigor),
      gate(cheap) summary + earliest failing check, worktree path +
      valid|invalid|none on `opsx/<change>`, loop_hold + reason, Diff Base
      commits-behind-main; placeholders when review.md/branch absent; no side
      effects; exit 0 always. Files: `dot_local/bin/executable_opsx`.
- [x] 1.3 `opsx archive-check <change>` (D2, opsx-gate-enforcement.Land Base
      Currency + Duplicate ADR Number Scan, opsx-cli.Multi-Dir Integration
      Commit Detector): land-base-currency (same-tree exemption), ADR-dup
      scan, advisory multi-dir detector over `<Diff Base>..main`; exit
      non-zero iff check 1 or 2 fails. Files: `dot_local/bin/executable_opsx`.
- [x] 1.4 Tier collapse in gate (D3, opsx-workflow-schema.Scale-adaptive
      gating): scale vocabulary `XS S M`; `full_rigor` boolean parse
      (fail-closed); artifact table keyed (scale, full_rigor) — plain M drops
      clarify.md/analyze.md, keeps doneness.md; L/XL fail closed with relabel
      message. Files: `dot_local/bin/executable_opsx`.
- [x] 1.5 Worktree-mode default derivation (D6): absent `worktree_mode` ⇒
      XS/S same-tree, M worktree-required; explicit wins.
      Files: `dot_local/bin/executable_opsx`.
- [x] 1.6 Model-config project layer removal (D7, opsx-model-config.Layered
      Resolution Order + opsx-cli.Model Config Write Surface): resolver skips
      project yaml + one-time stderr warning when file exists; JSON source
      enum drops `project`; `set/get --layer project` rejected with removal
      message. Files: `dot_local/bin/executable_opsx`.
- [x] 1.7 Bash `opsx loop` budget alignment (analyze F6): read
      `loop_max_iterations` from front-matter when present; flat 40 only as
      absent-value fallback. Files: `dot_local/bin/executable_opsx`.

## Phase 2 — Schema + templates, D3/D4/D6/D7

- [x] 2.1 README Scale table 5→3 + `full_rigor` extras + migration note
      (in-flight relabel guidance; archived changes never rewritten).
      Files: `dot_local/share/openspec/schemas/opsx-superpowers/README.md`.
- [x] 2.2 review.md template: tier vocabulary, `full_rigor` key + comment,
      authoring-time budget defaults XS=10/S=20/M=40/full_rigor=80,
      worktree-mode derivation comment. Files:
      `dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md`.
- [x] 2.3 opsx-models.yaml template: project layer removed from documented
      resolution order. Files:
      `dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-models.yaml`.
- [x] 2.4 doneness template/prose: designated-reviewer combined dispatch at
      plain M (`review_mode: blind-single-judge`, first review model);
      independent judge at full_rigor. Files:
      `dot_local/share/openspec/schemas/opsx-superpowers/templates/doneness.md`
      (or the template that documents doneness provenance).

## Phase 3 — Skills (Constitution IX surfaces), D4/D5/D9

- [x] 3.1 openspec-loop SKILL.md: tier vocabulary; plain-M combined doneness
      dispatch (designated reviewer = first review model, separate
      doneness.md); A2 path-scoped-commit rule for loop-driven integration
      commits. Files:
      `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`.
- [x] 3.2 openspec-archive-change: run + quote `opsx archive-check <change>`
      before `openspec archive`; refuse on non-zero; delete now-empty
      `openspec/specs/<cap>/` dirs post-archive and re-validate specs (D8).
      Files:
      `dot_local/share/agent-harness/canonical/skills/openspec-archive-change/SKILL.md`.
- [x] 3.3 openspec-propose + apply-mode reference: tier vocabulary; plain-M
      clarify-in-proposal (Open Questions inline, 2-option discipline) and
      deterministic-only analyze at plain M. Files:
      `dot_local/share/agent-harness/canonical/skills/openspec-propose/SKILL.md`,
      `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`.

## Phase 4 — Tests (D10)

- [x] 4.1 `tests/opsx-gate/test_opsx_gate.sh`: 3-tier vocab; full_rigor
      artifact matrix (plain-M drops clarify/analyze, keeps doneness);
      fail-closed L/XL + relabel message; non-boolean full_rigor; worktree-mode
      derivation; `--cheap` (skips validations, still reports verdict-state
      checks).
- [x] 4.2 `tests/opsx-cli/test_opsx_cli.sh`: `opsx status` (fleet block,
      placeholders, exit 0, read-only); `opsx archive-check` (current base
      passes, stale base refuses + remedy text, same-tree exemption, ADR-dup
      fails with both paths, multi-dir advisory does not affect exit).
- [x] 4.3 `tests/opsx-models/test_opsx_models.sh`: project yaml ignored +
      one-time warning; source enum without `project`; `--layer project`
      write rejected.
- [ ] 4.4 `tests/opsx-review-convergence/test_review_convergence_surfaces.sh`:
      prose pins for 3.1–3.3 surfaces (tier vocab, combined dispatch,
      archive-check invocation, path-scoped-commit rule).
- [ ] 4.5 Extension bun tests: confirm NO behavior change required
      (budget=front-matter-only, absent=unbounded); add/adjust only if a pin
      references retired capability names.
      Files: `dot_pi/agent/extensions/opsx-loop/*.test.ts` (as needed).

## Phase 5 — Verification

- [ ] 5.1 Full validator sweep per `openspec/opsx-gates.yaml` + both openspec
      validations; author verify.md (retained-required) with AC↔test map.
