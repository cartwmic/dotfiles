# Plan — add-opsx-loop-harness

Fine-grained execution driver for `openspec-apply-change`. Order respects the
migration plan in design.md: harness-neutral core first, then the generic
runtime, then schema, then skills, then adapter.

## Step 1 — Core CLI + skill (the spine)
- **Covers:** T1.0, T1.1, T1.2, T1.3, T1.4, T1.5
- **Pre-conditions:** worktree created; `yq` installed (T1.0) and `.gitignore` allowlist for `dot_local/bin/` (T1.1) committed first, so the gate can parse `opsx-gates.yaml` on its first self-run. review.md front-matter is parsed dependency-free (sed/awk), so the gate's mode read has no yq dependency.
- **Action:**
  1. Write failing test asserting `opsx-gate <change>` exits non-zero with `GATE-FAIL` when a required artifact is missing (AC opsx-gate-enforcement.gate-exit-code-contract).
  2. Run test → FAIL.
  3. Implement `opsx-gate`: parse review.md front-matter (scale/modes); ordered checks structure→artifacts→tasks→validations→verdicts with short-circuit; mode-aware verify/code-review.
  4. Run test → PASS; add cases for absent-Scale-fails, advisory-non-block, manifest non-zero.
  5. Add `opsx-loop` bash fallback + `opsx-PROMPT.md`; author `openspec-loop` skill.
  6. Commit (subject ≤72).
- **Verification:** `tests/opsx-gate/**` green; `opsx-gate` self-run against this change exits non-zero on the still-incomplete state.
- **Rollback:** `git worktree remove` + delete `opsx/<change>` branch; no deployed state touched (chezmoi not applied).

## Step 2 — Generic command-judge in goal extension
- **Covers:** T2.1, T2.2
- **Pre-conditions:** Step 1 merged (opsx-gate exists to be the judge).
- **Action:** TDD the command-judge: failing test for met (exit 0) / not-met (non-zero, output as reason) / exec-failure (non-fatal) / model-default; implement; keep extension opsx-agnostic; PASS; commit.
- **Verification:** `dot_pi/agent/extensions/goal/**` tests green; existing goal-loop tests still pass (model-judge default unchanged).
- **Rollback:** revert the extension commit; model-judge path is unaffected.

## Step 3 — Schema templates + docs
- **Covers:** T3.1, T3.2, T3.3
- **Pre-conditions:** Steps 1-2 merged.
- **Action:** edit `review.md` template (front-matter + new modes + worktree default); add `code-review.md` + `opsx-gates.yaml` templates; update `schema.yaml`, `capability-hooks.md`, `README.md`. Run `openspec validate --schema` equivalents.
- **Verification:** `openspec schemas` lists opsx-superpowers; a scratch change scaffolds review.md with front-matter; templates resolve via `openspec templates`.
- **Rollback:** revert template/schema commits; schema reverts to prior behavior.

## Step 4 — Skill edits (apply / archive / explore)
- **Covers:** T4.1, T4.2, T4.3
- **Pre-conditions:** Steps 1-3 merged; this change's adversarial review already satisfies Constitution IX for these edits.
- **Action:** edit the three opsx-mode references: apply (worktree lifecycle + code-review production + opsx-gate run), archive (code-review hard-gate + worktree merge/cleanup), explore (freeze intent.md). Guard all new behavior behind `schemaName == opsx-superpowers`.
- **Verification:** spec-driven projects unaffected (run an apply on a spec-driven scratch change → unchanged); opsx-superpowers apply produces code-review.md (authored by the review subagent) when mode ≠ none. This change's own gating code-review.md over the apply/archive/explore diffs is the Constitution IX satisfaction point; if it degrades to single-model, IX is unmet and archive stays blocked.
- **chezmoi guard:** deploy-affecting checks (symlinks, `chezmoi apply`, `openspec templates/schemas`, mise) run post-merge or with `CHEZMOI_SOURCE_DIR`/`--source <worktree>`; never `chezmoi apply` real home from the loop worktree (design D10).
- **Rollback:** revert per-skill; behavior falls back to current opsx-mode.

## Step 5 — Kickoff adapter + docs
- **Covers:** T5.1, T5.2
- **Pre-conditions:** Steps 1-4 merged (yq already installed at T1.0).
- **Action:** add thin `/opsx-loop` kickoff (wires worker=openspec-loop, judge=opsx-gate, worktree, maps loop_max_iterations onto the goal turn budget); document the AGENT_CMD bash fallback. Verify the delete-the-extension litmus: disable the adapter, run via `opsx-loop` bash fallback → workflow still advances.
- **Verification:** `/opsx-loop <scratch>` advances a change; litmus passes.
- **Rollback:** remove the adapter; bash fallback remains.

## Step 6 — E2E + docs
- **Covers:** T6.1, T6.2
- **Pre-conditions:** Steps 1-5 merged.
- **Action:** explore→loop dry-run on a throwaway change; confirm red→green gate progression and archive gate refuses until code-review pass; update README + design doc reference.
- **Verification:** the throwaway change reaches GATE-PASS only after all gates green; archive blocked while code-review absent under gating-required.
- **Rollback:** delete the throwaway change; docs revert.

## Notes
- **Verdict-freshness vs commit ordering (dogfood at T6.1):** committing verify.md/code-review.md advances worktree HEAD and could self-stale the recorded range. Resolution: the reviewer records the current HEAD, and verdict artifacts stay uncommitted until the gate passes; archive commits/merges after green. Confirm explicitly during the T6.1 dry-run.
- `opsx-gate` report format is the stable line protocol `GATE-FAIL <check_id> <blocking> <message>` (decided round-3 REV3-007); a JSONL payload MAY be added later as an additive option. `required:false` = advisory warning, `required:true` = blocking (decided). These are no longer deferred.
