# Intent: harden-opsx-repo-portability

<!-- FROZEN at loop arm. Distilled from the 2026-07-04 conversation
     (user-approved scope: one combined change, Scale S, spec-anchored,
     fail-closed preflight chosen over auto-scaffold/opt-out). First loop
     dogfood run after quiet-round-review-convergence archived. -->

## Intent

Make the opsx toolchain work in repositories that are not shaped like this
one: (1) stop hardcoding `main` as the integration branch — resolve the
repo's actual default/integration branch deterministically everywhere the
CLI compares against it; (2) stop silently running the loop in repos that
lack `openspec/constitution.md` / `openspec/domain.md` — the propose skill
requires them but the gate never checks, so autonomous runs proceed with a
review baseline that silently doesn't exist. The gate must fail closed with
a scaffolding remedy instead.

## Grounding (observed, 2026-07-04)

- A repo whose default branch is not `main` failed archive state: the
  archive gate's base-currency check hardcodes `main`.
- `dot_local/bin/executable_opsx` hardcodes `main` in three functional
  surfaces: `opsx status` Diff-Base staleness (`base..main`, lines
  ~1315/1364-1370), `archive-check` base-currency
  (`merge-base(branch, main) == main HEAD`, ~1414-1427), and the
  duplicate-ADR first-parent scan (`DIFF_BASE..main`, ~1452-1464).
- The review.md locator already carries an `**Integration Branch:**` field
  (template line 104, captured/printed by apply + `opsx` line ~1227) — but
  every hardcoded check ignores it, and the template defaults it to the
  literal `main` instead of the detected branch.
- Constitution/domain enforcement exists only as an interactive A/B/C
  prompt in the openspec-propose skill reference. The autonomous loop never
  pauses there; `opsx` CLI, gate, and opsx-loop extension have zero
  constitution/domain checks. Review dispatch templates cite
  "constitution/domain" as blind-review baseline inputs that may not exist.

## In scope

- **Q1 — integration-branch portability.** A single helper in
  `executable_opsx` resolves the integration branch; every functional
  `main` hardcode (status staleness, archive-check base-currency,
  duplicate-ADR scan) uses it. Resolution order, first hit wins, all
  deterministic:
  1. The change's committed review.md `**Integration Branch:**` field
     (per-change, already the locator's source of truth) — when a change
     context exists and the field is non-empty/non-placeholder.
  2. `git symbolic-ref refs/remotes/origin/HEAD` (short name).
  3. Local branch `main` exists.
  4. Local branch `master` exists.
  5. Fail loud (named error, no guessing) — never a silent fallback.
  The review.md template's `**Integration Branch:**` default becomes
  capture-time detected (steps 2-4), not literal `main`. Error/status
  messages name the resolved branch instead of the literal `main`.
- **Q2 — project-artifact preflight (fail-closed).** A new deterministic
  gate check: `openspec/constitution.md` and `openspec/domain.md` must both
  exist (non-empty) in the integration checkout for the gate to pass, at
  every Scale. Failure message is a directive naming the shipped templates
  (`constitution-template.md`, `domain-template.md`) as the scaffolding
  remedy. No auto-scaffold, no waiver key (explicitly rejected options).
- Prose surfaces that assert `main` as the integration branch (skill
  references, schema/template comments) updated to "integration branch
  (resolved)" language where they describe the checks above.
- Tests: branch-resolution order (including override-field, origin/HEAD,
  master-only, and fail-loud cases), non-`main` repo archive-check
  base-currency pass/fail, gate preflight red on each missing artifact and
  green when both present.

## Out of scope

- Auto-scaffolding constitution/domain content (rejected: writes generic
  unreviewed content).
- A waiver/opt-out key for the preflight (rejected: fail-closed only).
- Renaming this repo's branch or migrating existing worktrees/locators.
- The opsx-loop extension (`dot_pi/agent/extensions/opsx-loop/*`) — it has
  no `main` references and no artifact checks today; keyword grammar and
  extension behavior unchanged.
- The interactive propose-skill A/B/C prompt (stays as-is for interactive
  sessions; the gate check is the autonomous backstop).

## Frozen decisions

- D1: One helper (`opsx_default_branch()` or equivalent), resolution order
  exactly as Q1 — review.md field > origin/HEAD symbolic-ref > `main` >
  `master` > loud failure. No config-file override key in this change.
- D2: All three functional hardcode sites route through the helper; comment-
  only mentions may stay but must not contradict it.
- D3: Preflight is a gate check (fail-closed, every Scale), not a loop-
  extension check and not a skill-prose-only rule.
- D4: Both preflight artifacts required; empty file counts as missing.
- D5: Everything stays deterministic and model-free (ADR-0007 lineage);
  BSD/macOS tool compatibility (no GNU-only flags).

## Doneness outcomes

- A repo with default branch `trunk` (or any non-`main`) passes
  archive-check base-currency, `opsx status` staleness, and the dup-ADR
  scan when current, and fails them with branch-correct messages when not.
- A repo missing constitution.md or domain.md gates red with the
  template-scaffold directive; adding both files turns that check green.
- This repo's behavior is unchanged (resolution lands on `main` here).
- All existing suites stay green; new tests cover Q1 order + Q2 red/green.
