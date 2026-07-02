<!-- authored: in-session -->
# Clarify Findings

Three passes over the EARS acceptance criteria in this change's `specs/**/spec.md` (delta
content only). Findings resolved in-session against the frozen `intent.md` per the
autonomous drive-to-green directive; each records the assumption taken.

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | loop-kickoff:Stall | "gap set differing" — does a *growing* or *reordered* gap set count as progress, or only a *shrinking* one? | Any difference (shrunk/grown/reordered) resets the counter | Only a strictly shrinking gap set resets | answered | **B** — the frozen intent's load-bearing rule is progress = gap set *shrinking*. Treating any difference as progress reopens the ∞-loop hole: a thrashing agent whose gap set grows, swaps members, oscillates, or is reworded resets the counter forever while closing no original gap. Resolution: progress = gap set **strictly shrinks against a running minimum `min_gaps`** (proper subset of the smallest set seen this streak, fewer members) OR gate green; a per-prior-eval comparison is defeatable by asymmetric oscillation ({a,b}→{a}→{a,b}), so the ratchet is against the running minimum. Growth/swap/oscillation/rework = no-progress → stall advances. Reorder neutralized by set-normalization. |
| A2 | doneness-judge:Sealed | Does the gate itself invoke the judge, or only read a pre-sealed field? | Gate only READS `doneness.md`; the openspec-loop skill dispatches the judge upstream | Gate spawns the judge on demand | answered | **A** — intent constraint "no model invocation inside the opsx gate code path". Gate is a deterministic field reader; orchestration dispatches. |
| A3 | doneness-judge:Sealed | Is a gap "phrase" free text or a normalized token? | A short stable phrase per bullet, normalized (lowercased, whitespace-collapsed) by consumers before comparison | Structured id per gap | answered | **A** — mirrors the GATE-FAIL check-id normalization already used by stall detection; no new id scheme needed. |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | gate:Doneness-evaluated-after-mechanical ↔ gate:Missing-artifact-lifecycle-order | gate evaluating checks | ordering of `doneness` | Both place doneness last | — | answered | **A** — consistent: doneness ordered last in both the evaluation sequence and the lifecycle failure emit order. |
| I2 | schema:Doneness-Mode-waiver ↔ gate:Waived-does-not-block | `doneness_mode: waived` | whether a verdict is required | Both: waived ⇒ not required | — | answered | **A** — consistent across schema (records rationale) and gate (does not block). |
| I3 | doneness-judge:Freshness ↔ gate:Doneness-Verdict-Enforcement (stale) | reviewed range mismatch | verdict validity | Both: stale ⇒ not established / failed | — | answered | **A** — consistent; the judge capability defines "not established", the gate defines the resulting failed check. |

## Pass 3 — Completeness (event/state combination enumeration)

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | `doneness_mode: required` × Scale < M | Does required-mode force a verdict below Scale M? | Sub-M never requires doneness regardless of mode | Add AC forcing doneness when explicitly required sub-M | answered | **A** — gate:"Below Scale M skips doneness" scenario already covers this; Scale is the primary gate, mode the secondary. Keeps trivial changes cheap. |
| C2 | doneness fails × another mechanical check also fails | Which is reported first? | Mechanical failures first, doneness last (ordering ACs) | — | answered | **A** — covered by the after-mechanical ordering + lifecycle emit order; first-red-wins picks the mechanical failure. |
| C3 | `doneness.md` present, satisfied, fresh, but no provenance | Pass or fail? | Fail — treated as not established | — | answered | **A** — doneness-judge:Anti-Self-Forge + gate:Unprovenanced scenarios cover this. |
| C4 | stall × failing set = {doneness, code-review} | Which progress signal applies? | Gap-set signal applies ONLY when `doneness` is the *sole* failing check; otherwise content/HEAD signal | — | answered | **A** — but the mixed set is UNREACHABLE by construction: gate:"Doneness is emitted only as the sole remaining failure" suppresses the `doneness` line while any mechanical/verify/code-review check is red, so `{doneness, code-review}` can never be emitted. The gap-set signal therefore applies iff `{doneness}` is the sole emitted failure — the only reachable doneness-blocked state; the content/HEAD fallback for a hypothetical mixed set is vacuous but harmless (safe regardless). |

## Outstanding (status != answered)

- (none)

## Summary

- Pass 1 findings: 3; unanswered: 0; deferred: 0
- Pass 2 findings: 3; unanswered: 0; deferred: 0
- Pass 3 findings: 4; unanswered: 0; deferred: 0
- **Gate status:** READY for design
