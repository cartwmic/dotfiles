# Execution Plan

Execution Mode = standard. Code change (bash CLI + TypeScript extension) plus
Constitution-IX prose surfaces; ordered so each commit leaves validators green.

## Order

1. **Worktree + Diff Base** — `opsx worktree ensure harden-opsx-loop-latch-and-stop`;
   record locator in review.md and (per this change's own G-D rule, applied
   reflexively) commit it to the integration checkout.
2. **Phase 1 — CLI** (tasks 1.1→1.3): single-source derivation first (1.1) so the
   gate fallback (1.2) consumes it; tests (1.3) pin both. Bash-only diff; gate
   self-syntax + opsx-cli/gate suites stay green per commit.
3. **Phase 2 — extension** (2.1→2.5): helpers before index.ts wiring; behavior
   tests last. TypeScript transpile + extension suite green per commit.
4. **Phase 3 — skills/templates** (3.1→3.3): prose surfaces after mechanics exist
   so prose references real behavior.
5. **Phase 4 — validation** (4.1→4.2): full sweep + AC↔test citations, then
   verify.md (retained-required) and the gating review rounds.

## Commit strategy

Conventional commits, one logical unit each: CLI, extension helpers, extension
wiring, tests, skill prose, templates. Bodies explain WHY. No push.

## Review

Gating code review post-apply under the opsx-review-convergence discipline:
blind multi-model (pinned review set), full-diff rounds, round ledger in
code-review.md, `review_max_rounds: 5`, disclosure round on persistent split.
Doneness judge after mechanical green.

## Risks

- Non-ff archive merge from reflexive locator publication — accepted (D6).
- `worktree ensure` refactor regressing existing behavior — pinned by existing
  tests/opsx-cli suite before new assertions land.
- Extension `agent_end` ordering (hold check vs gate run) — hold check FIRST;
  covered by 2.5 behavior tests.
