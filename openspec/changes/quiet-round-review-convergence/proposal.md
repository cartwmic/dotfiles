# Proposal: quiet-round-review-convergence

## Why

The review budget's stop conditions cannot tell healthy convergence from
thrash. `simplify-and-parallelize-opsx-workflow` (archived 2026-07-04) took 8
gating rounds and THREE human budget rulings while findings were monotonically
shrinking and every fix landed same-round: the flat-or-rising
severity-trajectory rule (ADR-0017) reads "one new P1 per round" as a
treadmill, because it was written for the crypt-log-redaction recirculation
incident and counts severities without a progress signal. The user's ARC
(adversarial-review-cycle) skill never had this problem — its stop condition is
finding-oriented ("quiet round"), not count-oriented — and the user has asked
for those semantics, expressed deterministically (intent.md, frozen at arm).

Two mechanical gaps from the same 8-round experience compound the cost:

- Blind rounds SAMPLE scattered prose surfaces instead of sweeping them — six
  of eight in-diff P0/P1s were one defect class (a stale instruction on one of
  ~12 shipped prose surfaces contradicting the change's own matrix). A
  deterministic contradiction sweep run before round 8 converged the review
  immediately; it should have run before round 1.
- Verdict sealing required gate archaeology (discovering `**Verdict:** pass`,
  `**Doneness:** satisfied`, `reviewer-provenance:` formats by reading the
  gate source) although filled-in templates carrying exactly those formats
  ship with the schema.

## What Changes

### Q1 — Quiet-round budget semantics (new default)

After each gating review round, the orchestrator evaluates IN ORDER:

1. **Quiet round** — latest round yields 0 new P0/P1 across ALL reviewers →
   seal `Verdict: pass`, stop rounds (converged). Unchanged from today.
2. **Converging** — findings present AND fix commits have landed since the
   previous round (worktree HEAD moved between reviewed HEADs) → fix and
   dispatch the next round autonomously. NO human ruling. **This is the new
   path** — today this lands for a per-round ruling once the budget stop or
   flat-trajectory rule fires.
3. **Thrash guard** — findings present and NO progress since the previous
   round (HEAD unmoved) → decision-audit landing (current behavior; catches
   the crypt-log-redaction class).
4. **Hard cap** — completed rounds ≥ `review_max_rounds` → decision-audit
   landing regardless of trajectory.

All conditions are per-round severity counts + the existing HEAD-moved
progress signal. NO cross-round finding-identity matching of any kind
(deterministic, model-free, ADR-0007 lineage). The current
land-on-every-budget-stop behavior remains available as an explicit opt-in
front-matter mode. A stop with open P0/P1 still NEVER seals pass — Q1 changes
only when the loop may CONTINUE, never when it may SEAL.

- Capability: **opsx-adversarial-review** (stop-condition requirement
  rewritten), **opsx-workflow-schema** (new front-matter mode key + template
  documentation), **opsx-skill-integration** / openspec-loop skill prose
  (the cycle table the orchestrator executes).

### Q2 — Migration-completeness sweep

A change MAY declare retired tokens / forbidden patterns in a machine-readable
list inside the change directory. A deterministic validator (`opsx` CLI
subcommand) greps ALL shipped surfaces for the declared patterns and fails on
hits. The openspec-loop skill runs the sweep BEFORE dispatching review round 1
for rename/retire/migration-class changes, so the whole defect class dies in
one deterministic pass instead of one instance per blind round.

- Capability: **opsx-cli** (new subcommand), **opsx-gate-enforcement** (gate
  integration where applicable), **opsx-workflow-schema** (declaration file
  format), **opsx-skill-integration** (skill trigger prose).

### Q3 — Verdict artifacts from templates

The openspec-loop skill directs the orchestrator (and its dispatched
reviewers/judges) to FILL the schema's shipped verify/code-review/doneness
templates — which already carry the gate-parsed field formats — rather than
free-writing verdict artifacts.

- Capability: **opsx-skill-integration** / openspec-loop skill prose.

### Q4 — Riders (follow-up seeds from the archived change's warnings)

- Fix the review.md template prose-table Code Review Mode row (stale literal
  `advisory` where the front-matter ships the key commented/derived).
- Remove the duplicate `gate` line in `opsx_usage()`.
- Delete the stray empty
  `tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp`.
- Audit remaining mode keys for fail-open-by-omission; derive fail-closed
  defaults where the docs promise them.

- Capability: **opsx-workflow-schema** (template), **opsx-cli** (usage), plus
  repo hygiene.

## Non-goals (from intent)

- Semantic/LLM-based finding deduplication or cross-round matching.
- Changing reviewer counts, models, or the single-disclosure-round limit.
- Reworking the doneness judge or the M-tier dispatch shapes (ADR-0026
  stands).
- Retroactive changes to archived review records.
- Auto-archive/auto-deploy (human retains archive + deploy).

## Constraints carried from intent

- Extension + gate + convergence logic stay deterministic and model-free.
- The 2-model blind adversarial code review is untouched in rigor: reviewer
  set stability, verdict contract, severity rubric, round ledger, single
  disclosure round, freshness/provenance binding all carry over unchanged.
- Thrash guard must catch the crypt-log-redaction class.
- ADR-scarred guards (loop_hold, latch, distill confirm, locator, budgets,
  stall detection) untouched.
- Constitution IX applies (existing-skill edits → gating multi-model review).

## Impact

| Surface | Change |
|---|---|
| `openspec/specs/opsx-adversarial-review/spec.md` | Q1 stop-condition requirement rewritten (delta) |
| `openspec/specs/opsx-workflow-schema/spec.md` | Q1 mode key; Q2 declaration format; Q4 template row (delta) |
| `openspec/specs/opsx-cli/spec.md` | Q2 sweep subcommand; Q4 usage dedup (delta) |
| `openspec/specs/opsx-gate-enforcement/spec.md` | Q2/Q4 gate-side checks as needed (delta) |
| `openspec/specs/opsx-skill-integration/spec.md` | Q1 cycle prose, Q2 trigger, Q3 templates directive (delta) |
| `dot_local/bin/executable_opsx` | Q2 validator; Q4 usage dedup + fail-open audit |
| `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md` | Q1 cycle table; Q2 pre-round-1 trigger; Q3 fill-templates directive |
| `dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md` | Q1 mode key docs; Q4 table row fix |
| `dot_local/share/openspec/schemas/opsx-superpowers/{schema.yaml,README.md}` | Q1/Q2 key + format documentation |
| `tests/opsx-gate`, `tests/opsx-cli`, `tests/opsx-review-convergence` | pins for every new behavior |
| `tests/opsx-review-convergence/*.tmp` | stray file deleted (Q4) |

## Success Criteria

1. Replaying the simplify-and-parallelize round history under Q1 semantics
   yields ZERO human rulings on rounds 1–8 (every round had fixes landing)
   and the same convergence point; replaying crypt-log-redaction still lands
   at the thrash guard. (Table-top replay recorded in design.md/verify.md.)
2. The Q2 sweep validator, given a declaration listing retired tokens,
   fails on a planted stale surface and passes after cleanup — proven by
   shell-test pins.
3. Q3: the openspec-loop skill contains no instruction to free-write verdict
   artifacts; it points at the shipped templates by path.
4. Q4 riders verified by grep/test pins (no duplicate usage line, no `.tmp`
   stray, template row shows derived semantics, audited mode keys fail
   closed).
5. All existing validator suites stay green; both openspec strict validations
   pass.

## Open Questions

None blocking — full_rigor tier: ambiguities route to the standalone
clarify.md pass (next artifact in the graph).
