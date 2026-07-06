# Tasks — add-opsx-design-fidelity-gate

## 1. Gate: design-fidelity check

- [ ] 1.1 Add the `design-fidelity` cheap-phase check to `opsx gate` in `dot_local/bin/executable_opsx`: WHERE the change carries design.md (committed main-root content), require a sealed `design-fidelity.md`; parse own-line fields (`Fidelity`, judge provenance, `Attested HEAD`, per-file digest fields, optional `Human Waiver`) from COMMITTED integration-checkout content (`git -C <main-root> show HEAD:…`, reuse `opsx_repo_main_root`); fail closed on absent artifact, missing/unparseable fields, `violated` without non-empty waiver, present-but-empty waiver, provenance `review_mode` outside `blind-single-judge|adversarial-multimodel`. Emit unconditionally in the guidance order between analyze and tasks (plain sequential fail emission — NOT the doneness `rc == 0`-gated block); never join the missing-required-artifact short-circuit.
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false
- [ ] 1.2 Digest bindings: recompute sha256 (reuse `sha256_file` on `git show` output or hash blob content) of intent.md, design.md, and EVERY `specs/**/spec.md` from committed main-root change-dir content; locate digest lines by LITERAL string comparison against lines built from the enumerated spec-file set (never interpolate paths into regex); fail closed on any mismatch AND on set difference between enumerated files and recorded digest fields (added or removed delta spec file stales the seal, waived seals included).
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false
- [ ] 1.3 Mode-field committed-read split: source ALL review.md front-matter switchboard fields the gate reads (`scale`, `full_rigor`, `doneness_mode`, `code_review_mode`, `verification_mode`, `validation_source_mode`, …) from committed integration-checkout content, never live disk and never the worktree-reassigned `$REVIEW`; keep verify.md/code-review.md/doneness.md/tasks.md worktree-read; update the `ARTIFACT SOURCE RESOLUTION` comment block (~582–596) to document the deliberate field-source split (D8).
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false

## 2. Gate + CLI: worktree-mandatory enforcement

- [ ] 2.1 `worktree_mode` key rejection: fail closed when the COMMITTED integration-checkout review.md front-matter declares a `worktree_mode` KEY with any value (including empty) — key-PRESENCE detection via front-matter key parse (first-colon split flag on key match), never substring grep (a YAML comment mentioning `worktree_mode` must not trip it; this change's own review.md is the fixture). Message names the delete-the-key remedy.
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false
- [ ] 2.2 Remove every same-tree gate path: for a change past Diff Base capture with no valid locator/convention worktree, fail verdict evaluation loudly naming the missing worktree and the `opsx worktree ensure <change>` re-home remedy (covers the key-less tier-default migration shape: Diff Base present, empty Worktree Path, no branch); Manifest Validation and Migration Sweep gain the same past-capture-guarded loud fail (never silent integration fallback, wrong-reason pre-capture messages avoided); Land Base Currency refuses landing when no `opsx/<change>` branch exists; delete the tier-derivation of worktree mode and all same-tree freshness/exemption branches.
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false
- [ ] 2.3 `opsx sweep <change>`: resolve the grep root worktree-only (as the gate resolves it); past Diff Base capture with no valid worktree → loud fail naming the missing worktree, never silently grepping the integration checkout; keep `--worktree` loud validation and SWEEP-ERROR semantics.
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false

## 3. Schema: templates + docs

- [ ] 3.1 Ship `templates/design-fidelity.md`: per-AC verdict table (`entailed | not-entailed | not-covered`), own-line `**Fidelity:**`, judge-provenance + `**Attested HEAD:**` fields, per-file digest fields in the pinned grammar `**Digest sha256 (<change-dir-relative path>):** <64-hex>`, optional `**Human Waiver:**`, `Advisory Findings` section, template comments documenting the bounded judge contract + full-sweep re-judge rule; multi-line-only HTML comments.
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/design-fidelity.md
  - allow_new_files: true
- [ ] 3.2 Purge Worktree Mode from `templates/review.md` (front-matter comment lines 11/13 and prose table row 85 — no worktree mode presented anywhere) and sync `README.md` + `schema.yaml`: worktree-always at every Scale, `worktree_mode` key rejected fail-closed, design-fidelity artifact + dispatch documented (Artifact graph + Per-Tier Review Stack doc deferral lands here), Fidelity Round Ledger described.
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md
      - dot_local/share/openspec/schemas/opsx-superpowers/README.md
      - dot_local/share/openspec/schemas/opsx-superpowers/schema.yaml
  - allow_new_files: false

## 4. Skills: dispatch + discipline surfaces

- [ ] 4.1 openspec-propose reference: fidelity dispatch wiring — full_rigor rides the blind analyze dispatch as a REQUIRED section of every judge's prompt; plain-M / design-bearing S/XS gets the narrow post-design blind mini-dispatch; judge model resolution via the `review` role; canonical AC enumeration handed to every judge (absent AC ⇒ `not-covered`); key-indexed worst-of consolidation, any-block-wins; seal to design-fidelity.md; fidelity `delivered`-or-waiver gates tasks generation; Fidelity Round Ledger append (pinned columns, `waived` rows break the valve streak); escalation valve routes two consecutive `violated` ledger rows to the decision-audit landing.
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-propose/references/opsx-superpowers-mode.md
  - allow_new_files: false
- [ ] 4.2 openspec-loop SKILL.md + openspec-apply-change reference: worktree-always (ensure → locator → apply → review → merge → cleanup at every Scale, XS included; no same-tree guidance survives); findings-file-sole-verdict-source consolidation; dual-tree read-only window with the narrow bookkeeping exclusion (review.md + follow-ups.md only), concurrency carve-outs (sibling path-scoped commits, sibling uncommitted authoring, own bookkeeping committed-or-not) and symmetric surgical restore (sibling dirs never touched); purpose-keyed integration-checkout attestation carve-out for proposal-phase judgments (post-worktree fidelity re-judge included); judged-inputs-committed-before-fidelity-dispatch pin (analyze residual 1); bookkeeping lands on the integration checkout (misplacement = staling backstop, fail-closed).
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md
      - dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md
  - allow_new_files: false
- [ ] 4.3 openspec-archive-change reference: worktree-mandatory landing (no `opsx/<change>` branch ⇒ refuse with re-home remedy); ADR promotion for D7 fills `Supersedes: ADR-0008` and annotates ADR-0008 `Superseded by:` (analyze residual 3 — extend HARD-GATE 3 promotion procedure to search prior ADRs for superseded decisions).
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-archive-change/references/opsx-superpowers-mode.md
  - allow_new_files: false

## 5. Tests

- [ ] 5.1 Gate fidelity fixtures (`tests/opsx-gate/test_opsx_gate.sh`, new `tests/opsx-design-fidelity/` if cleaner): design-bearing change without design-fidelity.md fails; delivered + matching digests passes; digest mismatch stales; violated without waiver fails; violated + non-empty waiver + matching digests + set-equality passes; empty waiver fails; new/removed delta spec file stales (waived seal included); provenance `review_mode: degraded-single-model` fails; uncommitted `Fidelity` flip and uncommitted mode-field edit are invisible (committed-read); guidance order reports design-fidelity ahead of tasks; no design.md ⇒ no fidelity requirement.
  - intent: feature
  - files_allowed:
      - tests/opsx-gate/**
      - tests/opsx-design-fidelity/**
  - allow_new_files: true
- [ ] 5.2 Worktree-mandatory fixtures: migrate/delete same-tree fixtures in `tests/opsx-gate/test_opsx_gate.sh` + `tests/opsx-cli/test_opsx_cli.sh`; add: `worktree_mode` key (any value, and empty value) fails closed; comment-bearing review.md (this change's own) does NOT trip the key check; key-less tier-default same-tree locator shape fails with re-home remedy; sweep loud-fails on missing worktree past capture; Land Base Currency refuses landing without the branch.
  - intent: feature
  - files_allowed:
      - tests/opsx-gate/**
      - tests/opsx-cli/**
  - allow_new_files: true

## 6. Wrap-up

- [ ] 6.1 Create `follow-ups.md` routing the analyze residuals not consumed by tasks 4.2/4.3/3.2: pre-worktree `.git/index.lock` contention retry note (residual 4); Manifest-Validation-cwd mechanism naming (residual 6); R9 window incident carve-out candidate (operator commits disjoint from every change's blast radius).
  - intent: feature
  - files_allowed:
      - openspec/changes/add-opsx-design-fidelity-gate/follow-ups.md
  - allow_new_files: true
- [ ] 6.2 Full validation: `openspec validate add-opsx-design-fidelity-gate --strict` green; `bash tests/opsx-gate/test_opsx_gate.sh`, `bash tests/opsx-cli/test_opsx_cli.sh`, and new fidelity suite green; grep-sweep shipped surfaces for `worktree_mode`/same-tree remnants (mirrors the acceptance sketch: no gate, skill, template, or test surface retains a reachable same-tree path).
  - intent: fix
  - files_allowed:
      - tests/**
      - dot_local/**
  - allow_new_files: false
