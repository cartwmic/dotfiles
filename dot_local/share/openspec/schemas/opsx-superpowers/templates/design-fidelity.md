<!--
Design-fidelity verdict — the SEALED per-AC entailment judgment opsx gate reads
BEFORE tasks generation whenever the change carries a design.md.

Skill-managed (NOT in the schema artifact graph) — produced by the openspec-loop
orchestration by filling THIS template (never free-written), authored by a BLIND
fidelity JUDGE SUBAGENT on the resolved `review` role model (no dedicated
`fidelity` role — review-class blind judgment reuses the review pool). The gate
reads the own-line fields verbatim; it runs NO language model.

BOUNDED JUDGE CONTRACT (mirrors the baseline-bounded reviewer contract):
for EVERY delta acceptance criterion the judge answers whether the design
mechanism cited (or discoverable) for that AC semantically ENTAILS the AC's
guarantee AS WRITTEN, recording one row per AC in the table below —
`entailed | not-entailed | not-covered`. A row blocks ONLY on clear
non-entailment of the AC as written; WHERE the guarantee is ambiguous (materially
divergent readings) the judge routes an advisory clarify-class finding to the
`## Advisory Findings` section INSTEAD of a blocking row — advisory outcomes
never occupy the three-value verdict column and never affect the gate-read
`Fidelity` field. An AC whose only design coverage is a nominal citation to a
section that does not substantively address the guarantee is `not-covered`
(never `entailed`). Intent-mandate violations (a decision rejecting/weakening
something the frozen intent mandates) and rationale-vs-mechanism contradictions
within a decision are IN scope and fall out of the sweep as evidence.

FULL-SWEEP RE-JUDGE RULE: every re-judgment is a FULL sweep over the whole
canonical AC enumeration — NEVER delta-scoped, NO cross-round finding matching.
A re-seal OVERWRITES this artifact; it never carries its own history (the
append-only Fidelity Round Ledger in review.md is the escalation valve's
substrate — this file is stateless across rounds).

CANONICAL AC ENUMERATION + CONSOLIDATION: the dispatch prompt hands EVERY judge
the SAME canonical AC key set — requirement name + scenario title enumerated from
the change's delta spec files. WHEN the dispatch resolves multiple judge models
the orchestrator consolidates deterministically and fail-closed: per AC the
consolidated row is the WORST verdict across counted judges for that AC key
(`not-entailed`/`not-covered` outrank `entailed` — key-indexed worst-of, no
free-text matching); an AC present in the canonical enumeration but ABSENT from a
counted judge's table consolidates as `not-covered` (fail-closed, so key drift
can never surface a permissive row). The sealed overall `Fidelity` is `violated`
IFF any counted judge's overall is `violated` OR any consolidated row blocks
(any-block-wins, mirroring the severity-floor posture).

ATTESTATION = INTEGRATION-CHECKOUT HEAD: fidelity is a proposal-phase judgment
class whose dispatched tree IS the integration checkout (purpose-keyed carve-out,
not temporal — the judgment never receives its own worktree, so it attests the
integration checkout ALWAYS, including a re-judge dispatched AFTER an
implementation worktree exists). `Attested HEAD` is the integration-checkout HEAD
at dispatch — PROVENANCE, not a reviewed RANGE (no range exists); the gate binds
it as a 40-hex literal and NEVER demands range equality. Freshness is carried by
the DIGESTS alone.

DIGEST FRESHNESS (edit => re-judge): one own-line sha256 digest field per bound
file — intent.md, design.md, and EVERY `specs/**/spec.md` under the change dir —
in the EXACT pinned grammar `**Digest sha256 (<change-dir-relative path>):**
<64-hex>`. The gate enumerates the actual `specs/**/spec.md` set on the
integration checkout and enforces SET-EQUALITY IN BOTH DIRECTIONS against the
recorded digest fields (a spec added or removed after seal fails closed), recomputes
each digest from the integration-checkout change dir, and fails on any mismatch —
so editing any bound file stales the seal and forces a full-sweep re-judge. This
holds for a human-WAIVED seal too: a post-waiver edit to a bound file stales the
waived seal like any other.

opsx gate reads (required WHILE the change carries a design.md):
  - Fidelity          delivered | violated   (gating: violated-without-waiver or
                      absent => failed check)
  - Judge Provenance  adapter-stamped judge identity carrying review_mode; the
                      review_mode value must be in the blind-dispatch vocabulary
                      `blind-single-judge | adversarial-multimodel` — an inline,
                      degraded-single-model, absent, or unknown value FAILS the
                      gate (never seals).
  - Attested HEAD     integration-checkout HEAD at dispatch — verbatim full
                      40-hex `git rev-parse HEAD`; symbolic refs (`HEAD`) and
                      short SHAs are UNPARSEABLE => failed check (fail-closed).
  - Digest sha256 (…) one own-line field per bound file in the pinned grammar;
                      set-equality both directions + recompute-and-compare.
  - Human Waiver      OPTIONAL; present + NON-EMPTY only when a human ruling at
                      the decision-audit landing waived a `violated` verdict.
                      An empty field NEVER waives; NEVER self-authored by the loop.
-->

# Design Fidelity

**Fidelity:** violated

**Judge Provenance:** <fidelity judge id(s) stamped by the subagent-dispatch adapter>; review_mode: <blind-single-judge | adversarial-multimodel>
**Attested HEAD:** <integration-checkout HEAD at dispatch — verbatim full 40-hex `git rev-parse HEAD`>
**Attested Path:** <integration-checkout root — verbatim `git rev-parse --show-toplevel`>

<!--
One own-line digest field per BOUND file: intent.md, design.md, and EVERY
specs/**/spec.md under the change dir. Exact grammar (parser + template never
diverge): `**Digest sha256 (<change-dir-relative path>):** <64-hex>`. Add one
line for every delta spec file — the gate enforces set-equality both directions
against the actual specs/**/spec.md set on the integration checkout.
-->
**Digest sha256 (intent.md):** <64-hex sha256 of intent.md>
**Digest sha256 (design.md):** <64-hex sha256 of design.md>
**Digest sha256 (specs/<capability>/spec.md):** <64-hex sha256 of each delta spec file — one line per file>

<!--
**Human Waiver:** <ruling reference + decision-audit landing entry> — written
ONLY by a human ruling at the decision-audit landing that waives a `violated`
verdict; reviewed inputs (digests) stay enforced. An EMPTY field never waives.
NEVER self-authored by the loop.
-->

## Per-AC verdict table

<!--
One CONSOLIDATED row per canonical AC (requirement name + scenario title from
the delta spec files). Verdict is the three-value column ONLY —
`entailed | not-entailed | not-covered` (key-indexed worst-of across counted
judges). Evidence NAMES the design section (e.g. "D3") whose mechanism entails
(or fails to entail) the AC's guarantee. Ambiguity-routed clarify-class findings
go to `## Advisory Findings`, NEVER here. The gate trusts the sealed `Fidelity`
summary field and does not re-scan this table (doneness-summary precedent);
correctness of consolidation is vested in the orchestrator sealing procedure.
-->

| # | Capability / Requirement / Scenario (AC key) | Verdict | Evidence (design section) |
|---|---|---|---|
| 1 | <capability / requirement name / scenario title> | entailed \| not-entailed \| not-covered | <design section naming the mechanism/guarantee link or gap> |

## Advisory Findings

<!--
Ambiguity-routed clarify-class findings, per AC — recorded here when the judge
cannot rule non-entailment for the AC as written (materially divergent readings).
Advisory outcomes NEVER occupy the three-value verdict column above and NEVER
affect the gate-read `Fidelity` field. Omit rows when there are none.
-->

- <AC key> — <clarify-class ambiguity: the divergent readings, why non-entailment cannot be ruled>

## Verdict rationale

<!--
1-3 sentences: why the overall Fidelity is delivered or violated against the
frozen baseline (intent + delta ACs + design). `violated` iff any counted judge's
overall is `violated` or any consolidated row blocks (any-block-wins).
-->
