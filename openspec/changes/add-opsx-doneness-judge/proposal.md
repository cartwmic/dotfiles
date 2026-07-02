<!-- authored: in-session -->
## Why

The opsx gate proves only *mechanical* doneness — build/test/lint exit 0, required
artifacts present, a review verdict exists — but cannot tell whether the diff actually
accomplished what the frozen `intent.md` asked. A change can be mechanically green while
missing the intent or silently drifting scope, and under an unbounded loop budget the
orchestrator will happily stop at that false green. This change layers a **semantic
doneness judge** onto the gate: a blind LLM verdict on intent-satisfaction, sealed into a
new artifact and read deterministically by the gate — so the gate never runs a model yet
still enforces "did we build the right thing". It deliberately supersedes the prior
"deterministic; no LLM doneness judgment" stance (ADR-worthy).

## What Changes

- **NEW** `doneness.md` skill-managed artifact carrying a `Doneness: satisfied | not`
  verdict, enumerated unmet **gaps** when `not`, plus provenance (judge identity +
  frozen-intent hash) and a fresh `Diff Base SHA..HEAD` reviewed range — mirroring the
  `code-review.md` sealed-verdict + provenance + freshness pattern.
- **BREAKING** `opsx gate` gains a required **doneness check**: WHILE `doneness_mode` is
  `required` (default at Scale ≥ M), a missing / non-`satisfied` / stale / unprovenanced
  `doneness.md` fails the gate. Changes at Scale ≥ M that were previously green now stay
  red until a doneness verdict is produced.
- New `doneness_mode: required | waived` field in the `review.md` mode switchboard
  front-matter (mirrors `validation_source_mode`); `waived` (with rationale) lets Scale ≥ M
  pass without a doneness verdict.
- The **openspec-loop skill** dispatches an independent blind doneness judge (on the
  resolved **`review`** role model — no new role) after the mechanical checks pass, and
  authors `doneness.md`. The gate reads the sealed field; no model runs inside the gate.
- The **pi opsx-loop extension** stall detector becomes **doneness-aware**: when the
  earliest blocking failure is `doneness`, *progress* is the judge's normalized **gap set
  shrinking**, not file-content changing — so an agent thrashing files without closing
  gaps trips stall instead of looping forever under an unbounded budget.
- A new **ADR** records the reversal of the "no LLM doneness judge" stance.

## Capabilities

### New Capabilities
- `opsx-doneness-judge`: the sealed doneness-verdict artifact contract, the blind judge's
  scope-anchored charter, and the provenance / freshness / waiver / scale-gating rules.

### Modified Capabilities
- `opsx-gate-enforcement`: gate reads and enforces the sealed doneness verdict
  (freshness + provenance + mode-conditioned), and orders it in the artifact lifecycle.
- `opsx-workflow-schema`: `doneness_mode` (+ `doneness_waiver_rationale`) added to the
  review.md mode switchboard, and `templates/doneness.md` added to the skill-managed
  template set in the artifact-graph definition.
- `opsx-loop-orchestration`: the orchestrator dispatches the blind doneness judge (review
  role) after mechanical checks and seals `doneness.md`.
- `opsx-loop-kickoff`: the extension's stall detection is doneness-aware (gap-set-shrink
  progress signal on a doneness-blocked turn).

## Impact

- **Code:** `dot_local/bin/executable_opsx` (`opsx_gate` subshell — doneness read /
  provenance / freshness / mode gating / lifecycle order). `dot_pi/agent/extensions/opsx-loop/`
  (`helpers.ts` gap-set parse + stall signal; `index.ts` wiring; `helpers.test.ts`).
- **Schema/templates:** `dot_local/share/openspec/schemas/opsx-superpowers/templates/`
  (new `doneness.md`; `review.md` gains `doneness_mode`); `schema.yaml` mode docs;
  `README.md` / `capability-hooks.md` as needed.
- **Skills:** `openspec-loop/SKILL.md` (dispatch the doneness judge; provenance/freshness);
  `openspec-archive-change` / `openspec-apply-change` references as needed. Constitution IX
  → skill edits require multi-model adversarial code-review.
- **Tests:** `tests/opsx-gate/` (doneness read / provenance / freshness / waiver / scale
  gating / lifecycle order); extension `helpers.test.ts` (gap-set stall).
- **Docs:** new ADR under `adr/`.
- **Dependencies:** none new (Constitution V) — `yq`/`sed` for field/front-matter reads.
