# Execution Plan — add-opsx-design-fidelity-gate (Scale M + full_rigor)

<!--
Execution Mode: standard (ordered actions, not TDD micro-tasks); tests land
in dedicated phase-5 steps with fixtures written against the delta ACs.
Worktree preamble: this change is the FIRST CONSUMER of its own
worktree-always mandate — apply begins with `opsx worktree ensure
add-opsx-design-fidelity-gate`, records the locator into review.md, and every
implementation step below executes inside that worktree. Change-dir artifact
writes (task checkboxes, follow-ups.md, Execution Notes, ledgers) land on the
integration checkout per the writeback-owner discipline.
-->

## Plan step 0: Worktree ensure + locator capture

- **Covers:** (lifecycle precondition for all tasks)
- **Pre-conditions:** clean change-dir state committed (pre-flight commit); no `opsx/add-opsx-design-fidelity-gate` branch yet.
- **Action:**
  1. `opsx worktree ensure add-opsx-design-fidelity-gate`
  2. Record `Diff Base SHA` (integration merge-base), `Worktree Path`, `Integration Branch` into review.md on the integration checkout; commit.
- **Verification:** `git -C <wt> rev-parse --abbrev-ref HEAD` = `opsx/add-opsx-design-fidelity-gate`; review.md locator fields non-empty.
- **Rollback:** `opsx worktree remove` + delete branch (no implementation commits yet).

## Plan step 1: Gate design-fidelity check (committed-read core)

- **Covers:** T1.1, T1.2, T1.3
- **Pre-conditions:** step 0; `opsx_repo_main_root` + `sha256_file` helpers present (shipped).
- **Action:**
  1. Add `main_root_show()` helper (`git -C <main-root> show HEAD:<path>`, empty-safe) beside `opsx_repo_main_root`.
  2. Re-source ALL gate-read front-matter switchboard fields (`scale`, `full_rigor`, `doneness_mode`, `code_review_mode`, `verification_mode`, `validation_source_mode`, loop budget) through committed main-root content BEFORE the `ART_ROOT` worktree reassignment; leave verify/code-review/doneness/tasks reads on `$CDIR` (worktree). Update the `ARTIFACT SOURCE RESOLUTION` comment to document the split (D8).
  3. New `design-fidelity` check block, emitted unconditionally in the cheap phase between the analyze and tasks checks (plain `fail` emission, no rc-gating): committed-read design.md presence → committed-read design-fidelity.md → parse `Fidelity` / provenance `review_mode` (case-statement `blind-single-judge|adversarial-multimodel`) / `Attested HEAD` (40-hex) / `Human Waiver` (violated + non-empty waiver = satisfied; empty waiver never waives) → enumerate committed `specs/**/spec.md` set, build expected `**Digest sha256 (<path>):**` lines, literal-match (grep -F) each recorded field, recompute sha256 over `git show` blobs, fail on mismatch or set difference.
  4. Commit per sub-step (`feat(opsx-gate): …`).
- **Verification:** `bash -n dot_local/bin/executable_opsx`; ad-hoc fixture run: this change's own committed design-fidelity.md passes; a tampered digest fails.
- **Rollback:** revert the gate commits on the worktree branch; no other surface touched.

## Plan step 2: Worktree-mandatory enforcement (gate + sweep CLI)

- **Covers:** T2.1, T2.2, T2.3
- **Pre-conditions:** step 1 (committed-read helpers in place).
- **Action:**
  1. Key-presence detector: front-matter scan flags `worktree_mode` KEY via first-colon key extraction (comment lines never match; empty value still a key); fail-closed with delete-the-key remedy. Fixture = this change's own comment-bearing review.md.
  2. Delete tier-derivation and every same-tree branch: locator/convention both-fail past Diff Base capture → loud fail naming missing worktree + `opsx worktree ensure` remedy (covers key-less migration shape); wire the same past-capture-guarded loud fail into Manifest Validation (fail before any validation command) and Migration Sweep; pre-capture states keep missing-artifact guidance (no wrong-reason no-worktree error).
  3. Land Base Currency: absent `opsx/<change>` branch → refuse landing, name worktree-mandatory + re-home remedy.
  4. `opsx sweep`: drop the `SWEEP_ROOT="$ROOT"` integration default for changes past capture — resolve worktree-only, loud fail otherwise; retain `--worktree` loud validation + SWEEP-ERROR.
  5. Commit per sub-step.
- **Verification:** `bash -n`; fixture runs: key-bearing review.md fails, comment-only passes; branchless past-capture change fails loudly in gate + sweep.
- **Rollback:** revert enforcement commits; gate retains step-1 fidelity check independently.

## Plan step 3: Schema surfaces

- **Covers:** T3.1, T3.2
- **Pre-conditions:** none beyond step 0 (independent of gate steps).
- **Action:**
  1. Author `templates/design-fidelity.md` to the Design Fidelity Artifact Template AC: per-AC table, own-line gate-read fields, pinned digest grammar, `Advisory Findings`, bounded-contract + full-sweep comments (multi-line HTML comments only).
  2. review.md template: delete front-matter `worktree_mode` comment lines and the `Worktree Mode` prose row; add `Fidelity Round Ledger` section stub (pinned columns) + design-fidelity mention where the verdict artifacts are listed.
  3. README.md + schema.yaml: worktree-always at every Scale (no mode), key rejection documented, design-fidelity artifact/dispatch in the artifact graph + per-tier review-stack docs (closes the R5/R8 doc deferral).
  4. Commit per surface.
- **Verification:** grep template/README/schema for `worktree_mode|same-tree|Worktree Mode` → only fail-closed-rejection mentions remain; template fields match the AC list 1:1.
- **Rollback:** revert schema commits (templates are additive/self-contained).

## Plan step 4: Skill surfaces

- **Covers:** T4.1, T4.2, T4.3
- **Pre-conditions:** step 3 (template names/fields referenced by skills exist).
- **Action:**
  1. openspec-propose reference: fidelity dispatch section (full_rigor rides analyze as REQUIRED section of every judge prompt; plain-M/S/XS mini-dispatch; `review` role; canonical AC enumeration; key-indexed worst-of + any-block-wins; seal + digest recording; `delivered`-or-waiver gates tasks; ledger append incl. `waived` rows; valve = two consecutive `violated` rows not separated by `waived|delivered` → decision-audit landing).
  2. openspec-loop SKILL.md + openspec-apply-change reference: worktree-always lifecycle at every Scale; findings-file-sole-verdict; dual-tree window (narrow review.md+follow-ups.md exclusion, sibling carve-outs committed AND uncommitted, judged-inputs always void-eligible, symmetric surgical restore); purpose-keyed attestation carve-out; judged-inputs-committed-before-fidelity-dispatch pin; bookkeeping on integration checkout + staling backstop note.
  3. openspec-archive-change reference: branch-required landing; ADR promotion fills `Supersedes:` by searching prior ADRs (D7 ⇒ `Supersedes: ADR-0008`, annotate ADR-0008 `Superseded by:`).
  4. Commit per skill surface.
- **Verification:** grep the four canonical surfaces for `same-tree|worktree-eligible|Worktree Mode` → zero guidance hits; fidelity dispatch text names the canonical-enumeration + worst-of rules.
- **Rollback:** revert skill commits; gate/schema remain consistent (skills are guidance, gate is arbiter).

## Plan step 5: Tests

- **Covers:** T5.1, T5.2
- **Pre-conditions:** steps 1–2 (gate behavior implemented).
- **Action:**
  1. New `tests/opsx-design-fidelity/test_design_fidelity_gate.sh`: the 12 fidelity cases from T5.1 (absence, pass, digest stale, violated, waiver matrix, set-equality add/remove, provenance vocab, uncommitted-flip invisibility, committed-mode-read, guidance order, no-design exemption).
  2. `tests/opsx-gate/test_opsx_gate.sh` + `tests/opsx-cli/test_opsx_cli.sh`: migrate/delete same-tree fixtures; add key-presence cases (value/empty/comment), key-less migration locator shape, sweep loud-fail, Land Base Currency branchless refusal.
  3. Commit per suite.
- **Verification:** all three suites exit 0 in the worktree.
- **Rollback:** revert test commits; suites are additive.

## Plan step 6: Follow-ups + full validation

- **Covers:** T6.1, T6.2
- **Pre-conditions:** steps 1–5 complete.
- **Action:**
  1. Author `follow-ups.md` (integration checkout): index.lock retry note (residual 4), Manifest-Validation cwd mechanism naming (residual 6), R9 operator-commit window carve-out candidate.
  2. Run: `openspec validate add-opsx-design-fidelity-gate --strict`; all three test suites; remnant grep-sweep of shipped surfaces (`worktree_mode|same-tree|worktree-eligible` outside fail-closed-rejection/test-fixture mentions).
  3. Check task boxes in tasks.md (integration checkout), commit.
- **Verification:** gate reaches the verdict-artifact phase (code-review/verify next rails), zero remnant hits.
- **Rollback:** n/a (validation only).

## Completion Verification

- `opsx gate add-opsx-design-fidelity-gate` → tasks check green (15/15), validations green.
- `bash tests/opsx-gate/test_opsx_gate.sh && bash tests/opsx-cli/test_opsx_cli.sh && bash tests/opsx-design-fidelity/test_design_fidelity_gate.sh` → all exit 0.
- Remnant sweep: `git grep -nE 'worktree_mode|same-tree|worktree-eligible' -- 'dot_local/**'` → only fail-closed rejection text, key-purge docs, and test fixtures.

## Manual Adjustments

- Execution Mode standard (no TDD micro-task expansion); tests consolidated in
  phase 5 rather than per-step failing-test-first, matching the shell-fixture
  test idiom of the existing suites.
- Step 0 added beyond tasks.md: worktree lifecycle is apply-owned (Worktree
  Lifecycle Ownership), not a task — recorded here so the loop's first
  implementation turn runs `opsx worktree ensure` before task 1.1.
- Deploy (`chezmoi apply`) is NOT part of this plan — owner-gated after
  archive, per session precedent.
