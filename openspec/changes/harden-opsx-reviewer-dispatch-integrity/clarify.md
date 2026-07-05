# Clarify Findings

<!--
Filled from the shipped template
~/.local/share/openspec/schemas/opsx-superpowers/templates/clarify.md.
Scale S: clarify is not a standalone gating artifact; this records the blind
ambiguity pass (delegate subagent, claude-bridge/claude-opus-4-8, report
/tmp/hrdi-clarify-r1.md) and the orchestrator's resolutions, all patched into
the delta specs same-turn. intent.md untouched (FROZEN).
-->

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 (C1) | gate-enforcement:Verdict Freshness And Provenance | "rev-parses equal" admits symbolic-`HEAD`/short-SHA bypass — `Attested HEAD: HEAD` resolves to range head in the located worktree | Rev-parse both sides in GW (reuses freshness machinery; bypass stays open) | Require full 40-hex literal; any other form unparseable → fail-closed | answered | **B** — the symbolic bypass defeats the check's purpose; reviewer preamble records verbatim `git rev-parse HEAD` output which is already 40-hex |
| A2 (C4) | adversarial-review:Reviewer Tree Identity Attestation | "attested path resolves to the dispatched tree" — pwd vs realpath vs toplevel; same-tree semantics | realpath-compare reviewer pwd; same-tree satisfied by construction | Attest `git rev-parse --show-toplevel`; realpath-compare toplevels; same-tree = equality with integration checkout root, HEAD check discriminates | answered | **B** — toplevel is git's own tree identity, immune to subdir cwd; macOS symlink variance handled by realpath |
| A3 (C2) | gate-enforcement:Independent-judge doneness scenario | Is `Attested HEAD` required on doneness.md at plain Scale M (combined dispatch)? | No — plain-M doneness rides the CR dispatch; attestation bound once via code-review.md; doneness binding is full_rigor-only | Require + bind on doneness.md in all enforced cases | answered | **A** — combined dispatch has exactly one reviewer tree, already bound via code-review.md; double-binding adds surface without discrimination |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 (C3) | adversarial-review:Read Only Reviewer Dispatch vs intent G3 "attributable" | Round window open; orchestrator seals bookkeeping or reviewers run concurrently | Delta-voiding vs "attributable to the dispatch" | Whole-tree compare; serialize dispatches; forbid in-window writes | Per-ROUND window; exclude `openspec/changes/<change>/` paths (orchestrator-sealed bookkeeping, only permitted in-window writes); delta voids ALL round verdicts (attribution impossible among concurrent reviewers) | answered | **B** — preserves parallel 2-model dispatch (wall-time) and same-tree mode; residual risk (reviewer hiding writes inside the exclusion set) accepted: those paths are orchestrator-sealed and gate-freshness-covered |

## Pass 3 — Completeness (event/state combination enumeration)

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 (C5) | Every reviewer INVALID × repeated re-dispatch | Termination when the dispatch itself is systemically broken (e.g. cwd never pinned)? | Unbounded re-dispatch (invalid never counts) | After 2 consecutive all-invalid attempts of the same round → decision-audit landing with dispatch-integrity error | answered | **B** — non-termination under a systemic dispatch bug is exactly the loop-misbehavior class this workflow guards against; bound of 2 mirrors thrash-guard philosophy |
| C2 (C6) | Snapshot delta × pre-existing untracked/dirty state | Does restore touch state that predated the dispatch? | Surgical set-diff: restore only tracked paths whose status changed; delete only untracked paths introduced in-window; never ignored/pre-existing state | Blanket `git restore . && git clean -fd` | answered | **A** — blanket clean is data loss beyond the reviewer's delta (operator scratch, build output); surgical semantics written into the AC |

## Outstanding (status != answered)

- (none — 6/6 answered, 0 deferred)

## Summary

- Pass 1 findings: 3; unanswered: 0; deferred: 0
- Pass 2 findings: 1; unanswered: 0; deferred: 0
- Pass 3 findings: 2; unanswered: 0; deferred: 0
