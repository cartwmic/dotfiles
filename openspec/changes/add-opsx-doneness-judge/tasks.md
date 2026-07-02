<!-- authored: in-session -->
# Tasks — add-opsx-doneness-judge

AC coverage is cited per task (canonical `<capability>.<requirement-slug>` IDs) so the
verify gate's forward AC↔test map resolves.

## 1. Gate: doneness verdict enforcement (opsx CLI)

- [x] 1.1 Add the doneness check to the `opsx_gate` subshell in `executable_opsx`: read
  `doneness_mode`/`scale`/immutable `Diff Base SHA` from review.md front-matter; WHILE
  `scale >= M` and `doneness_mode == required`, require `doneness.md` with
  `**Doneness:** satisfied`, an adapter-stamped `**Judge:**` provenance field whose review
  mode is not `degraded-single-model`, `Frozen-Intent SHA == sha256(intent.md)`, recorded
  `Diff Base SHA == review.md Diff Base SHA`, and `Reviewed Range == Diff Base..worktree HEAD`;
  emit `doneness` ONLY as the sole remaining failure (suppress while any mechanical/verify/
  code-review check is red); order doneness last; bare waiver (no non-empty
  `doneness_waiver_rationale`) at Scale ≥ M fails; no language-model call in the gate.
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false
  - Covers: opsx-gate-enforcement.doneness-verdict-enforcement,
    opsx-gate-enforcement.gate-exit-code-contract,
    opsx-gate-enforcement.required-artifact-by-scale,
    opsx-gate-enforcement.mode-aware-verdict-reading,
    opsx-doneness-judge.freshness-bound-verdict,
    opsx-doneness-judge.anti-self-forge-provenance,
    opsx-doneness-judge.scale-gated-with-waiver,
    opsx-doneness-judge.sealed-doneness-verdict-artifact

- [x] 1.2 Add gate tests covering: satisfied-pass, not/absent-fail, stale-fail,
  mismatched-intent-hash-fail, mismatched-diff-base-fail, unprovenanced-fail,
  degraded-single-model-fail, waiver-with-rationale-pass, bare-waiver-fail, sub-M-skip,
  and doneness suppressed while a mechanical check is red (sole-remaining emit).
  - intent: feature
  - files_allowed:
      - tests/opsx-gate/**
  - Covers: opsx-gate-enforcement.doneness-verdict-enforcement,
    opsx-doneness-judge.scale-gated-with-waiver

## 2. Schema + templates

- [x] 2.1 Add `templates/doneness.md` defining the machine-read fields (`Doneness`, `Gaps`,
  `Judge` provenance, `Frozen-Intent SHA`, `Diff Base SHA`, `Reviewed Range`); add
  `doneness_mode` + `doneness_waiver_rationale` to `templates/review.md` front-matter and the
  prose mode table; document the doneness template contract in `schema.yaml`
  (`apply.instruction` + the review mode docs) and `README.md`/`capability-hooks.md` as needed.
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/**
  - Covers: opsx-workflow-schema.mode-switchboard-in-review-md,
    opsx-workflow-schema.artifact-graph-definition

## 3. openspec-loop skill: doneness judge dispatch (Constitution IX)

- [x] 3.1 Edit the `openspec-loop` skill to add the doneness-judge dispatch step: after the
  mechanical gate checks pass and no fresh satisfied verdict exists, dispatch a blind
  subagent on the resolved `review` role with baseline = frozen intent + `Diff Base..HEAD` +
  delta ACs; the subagent authors `doneness.md` (verdict + gaps + adapter-stamped provenance +
  fresh range); no-adapter → leave absent or seal `Doneness: not` (never degraded satisfied);
  re-judge a stale verdict before re-running the gate; bare waiver resolved within the loop.
  - intent: feature
  - files_allowed:
      - dot_local/share/agent-harness/canonical/skills/openspec-loop/**
  - Covers: opsx-loop-orchestration.doneness-judge-dispatch,
    opsx-loop-orchestration.subagent-review-against-baseline,
    opsx-doneness-judge.blind-scope-anchored-judge

## 4. pi opsx-loop extension: doneness-aware stall detection

- [x] 4.1 `helpers.ts`: add a pure `parseDonenessGaps(donenessMd)` → normalized `Set<string>`
  (absent/unparseable → empty-set sentinel) and a running-minimum ratchet helper; `index.ts`:
  in the `agent_end` stall path, WHILE the sole failing check is `doneness` classified by
  parsing `<change-dir>/doneness.md` directly (state ∈ {not, absent, unparseable}), use the
  gap-set signal — progress only on a NON-EMPTY proper subset of `min_gaps`; empty-set
  sentinel neither progresses nor overwrites `min_gaps`; reset `min_gaps`+counter on
  failed-set/worktree change or green.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false
  - Covers: opsx-loop-kickoff.stall-detection-stops-the-loop

- [x] 4.2 `helpers.test.ts`: cover the ratchet — shrink resets, grow/equal-swap/oscillation/
  reword advance, empty-set sentinel advances (not progress) and does not overwrite min,
  failed-set/worktree change resets.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts
  - Covers: opsx-loop-kickoff.stall-detection-stops-the-loop

## 5. ADR (archive-time)

- [x] 5.1 (archive-time) ADR candidate identified + queued: promote a single ADR reversing the "deterministic; no LLM doneness judge" stance,
  covering D1–D4 (sealed verdict + dedicated judge + loop-stop gating + doneness-aware stall
  backstop). Authored by `openspec-archive-change` at archive.
  - intent: infra
  - files_allowed:
      - adr/**

## 6. Verify

- [x] 6.1 Run the full gauntlet (gate self-syntax, opsx-gate suite, extension bun tests,
  transpile, `openspec validate --strict`, forward AC↔test map) and author `verify.md` green.
  - intent: infra
  - files_allowed:
      - openspec/changes/add-opsx-doneness-judge/verify.md
