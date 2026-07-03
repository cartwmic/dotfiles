<!-- authored: delegate blind analyze -->
# Analyze: simplify-and-parallelize-opsx-workflow

**Verdict: BLOCKED** — 1 blocker, 2 major, 3 minor. Round 1, blind.

Blind cross-artifact analyze (no authoring context; review.md Execution Notes,
code-review.md, /tmp, and archive contents NOT read). Baselines: frozen intent.md,
proposal.md, clarify.md, design.md, audit.md, all 13 delta specs, every touched live
`openspec/specs/<cap>/spec.md` + untouched interplay specs, constitution.md, domain.md.
Code grounding: `dot_local/bin/executable_opsx` (1103 lines), `dot_pi/agent/extensions/
opsx-loop/{index.ts,helpers.ts}`.

The consolidation spine is sound: tiling name-sets are EXACT (verified header-by-header
against the live spec-of-record — loop 12+9=21 ADDED; adversarial 11+8+5 REMOVED +1 new
=25 ADDED), the gate/schema/adversarial per-tier stack agree, and the deterministic-gate
achievability holds for D1–D3, D6–D8. Findings below are cross-artifact contradictions and
consolidation-hygiene defects that survive into the archived spec-of-record.

## Findings

| ID | Sev | Check | File(s) | Finding | Failure scenario |
|----|-----|-------|---------|---------|------------------|
| F1 | BLOCKER | a/d/f | `specs/opsx-model-config/spec.md:12,89` vs live `openspec/specs/opsx-cli/spec.md:69` (Model Config Write Surface — NOT in change) | B4 retires the project layer: opsx-model-config *Layered Resolution* says `openspec/opsx-models.yaml` "SHALL NOT participate in resolution" and *Config Conventions* says "the schema SHALL NOT define it." But the surviving opsx-cli **Model Config Write Surface** requirement (untouched by any delta) still fully defines `opsx models set/get --layer project` writing/reading `openspec/opsx-models.yaml`, including scenarios "Layer flag targets the project file" and "Project layer with no discoverable root is rejected." Post-archive, two surviving capabilities contradict on whether the project layer exists. The change is **missing an opsx-cli Model Config Write Surface delta** to reconcile. | After archive, opsx-model-config says the project yaml is undefined/ignored while opsx-cli says `opsx models set impl x --layer project` MUST write it. A task author cannot tell whether to strip `--layer project` from the write surface + the bash `case "$LAYER" in user\|project)` (`executable_opsx:81`) + usage strings, or keep a write-only-then-ignored footgun. No decision exists in intent/design/clarify. |
| F2 | MAJOR | d/f | `specs/opsx-loop/spec.md:542,570`; `specs/opsx-adversarial-review/spec.md:256,300` | Four verbatim carry-over cross-references inside the SURVIVING consolidated capabilities still name the RETIRED `opsx-review-convergence` capability: opsx-loop "under the opsx-review-convergence discipline" (542) and "the opsx-review-convergence scope-widening protocol (as specified by that capability)" (570); opsx-adversarial-review "the single opsx-review-convergence disclosure round" (256) and "under the opsx-review-convergence baseline-bounded contract" (300). Clarify I-2 established the remap discipline and fixed the skill-integration reference but MISSED these. opsx-adversarial-review 256/300 are self-referential (the capability referencing its own retired predecessor's content that now lives INSIDE it). | Post-archive, opsx-review-convergence no longer exists; a reader/future change resolving "…scope-widening protocol (as specified by that capability)" finds a dangling capability. Violates B3 ("every surviving reference names the surviving capability") and the clarify's own I-1/I-2 "no stray retired semantics left live" discipline. `openspec validate` does not catch cross-capability prose refs, so it passed green. |
| F3 | MAJOR | a/e/g | `specs/opsx-loop/spec.md:80` (Budget from review front-matter) vs `design.md` D3+D10 vs `specs/opsx-workflow-schema/spec.md:57` | The budget-default HOME is contradictory. opsx-loop AC: "WHEN `loop_max_iterations` is absent or unparseable the budget SHALL be unset… **No built-in numeric default SHALL be applied**" (extension → unbounded; confirmed in `helpers.ts:399-405`). workflow-schema *Loop Max Iterations defaults by tier*: an XS/S/M-keyed default (XS=10,S=20,M=40; full_rigor=80) is written into front-matter at AUTHORING. design D3 lists these as gate-side "Budget defaults (when absent)"; design D10 lists "**Extension** bun tests: budget-default keying (XS/S/M/full_rigor)." The extension-keying reading directly violates the opsx-loop AC. | An implementer following D10 modifies `parseLoopBudget` to key defaults by scale → breaks the retained AC "No built-in numeric default SHALL be applied" and the "Unset budget runs unbounded" scenario. An implementer following the specs writes the keyed default only in the propose skill and leaves the extension unbounded-on-absent. Two divergent implementations; needs a one-line reconciliation of where the keyed default lives (recommend: propose-skill authoring only; extension contract unchanged; fix D3/D10 wording). |
| F4 | MINOR | e | `design.md` D4 vs `executable_opsx:835-838` | D4 says the plain-M doneness path means the gate's "accepted provenance set gains `review_mode: blind-single-judge`." The gate ALREADY accepts `blind-single-judge\|adversarial-multimodel` (line 835). D4 overstates the needed gate change — no vocab edit is required at plain M; only the skill dispatch shape (D9) changes. Positive for achievability; wording should be corrected so a task author doesn't add a redundant gate change. | Implementer adds a no-op gate edit "to add blind-single-judge," wasting effort / risking regression on an already-correct check. |
| F5 | MINOR | c | `specs/goal-loop/spec.md` (Removal is out of scope scenario) | EARS shape nit: the scenario is `**WHILE** … **THEN**` with no `**WHEN**` trigger. Passes `openspec validate --strict` but breaks the WHEN/THEN testability shape. | A strict EARS lint (analyze deterministic check) flags a triggerless scenario; harmless to behavior. |
| F6 | MINOR | f/e | clarify I-3 (accepted); `executable_opsx:910` | Two documented residuals: (i) stray "Scale M or above / and above" phrasing survives in opsx-adversarial-review + opsx-workflow-schema (clarify I-3 accepted it as evaluating correctly since M is top) — flag for future readers so no hidden tier-above-M is inferred; (ii) the bash headless `opsx loop` driver keeps a FLAT `${MAX_ITERS:=40}` default (`executable_opsx:910`) unchanged under the new scale-keyed budgets — divergent from XS=10/S=20 for same-tree XS/S changes run headless. | A headless XS change run via `opsx loop` (no `loop_max_iterations` authored) gets budget 40, not the XS=10 the schema advertises. Low impact (extension is the primary host); note it so D-level tasks address the bash default if scale-keyed budgets are meant to be uniform. |

## Per-check notes

**(a) Artifact contradictions.** intent ↔ proposal ↔ clarify ↔ design ↔ deltas are largely
coherent. Two real contradictions: F1 (model-config retirement vs surviving opsx-cli write
surface) and F3 (budget-default home: opsx-loop AC vs design D10). All other B1/B2/B3/B4
mappings trace cleanly (former L/XL ⇒ "M + full_rigor" is consistent across
gate-enforcement, workflow-schema, skill-integration, adversarial-review).

**(b) Constitution/domain.** II — deltas cite canonical skill paths
(`dot_local/share/agent-harness/canonical/skills/…`); OK. VIII — design D3 migration
wrinkle correctly handles openspec/ not being chezmoi-deployed (this change stays `scale: XL`
under the deployed 5-tier gate for its whole life; new gate goes live only at post-archive
`chezmoi apply`). IX — intent acknowledges skill edits at Scale ≥ M require adversarial
review for THIS change; satisfied by its own full stack. No violations found.

**(c) EARS quality.** Delta ACs are strong — SHALL-led, WHEN/THEN/WHILE/IF shaped, testable.
Only nit is F5 (one triggerless goal-loop scenario). Severity rubric / verdict-contract ACs
in opsx-adversarial-review are precise and preserve the load-bearing 2-model review.

**(d) MODIFIED superset + consolidation tiling.** Tiling name-sets EXACT (verified against
live spec-of-record): opsx-loop ADDED 21 = kickoff 12 REMOVED + orchestration 9 REMOVED;
opsx-adversarial-review ADDED 25 = review-convergence 11 + post-impl-review 8 +
doneness-judge 5 REMOVED (=24) + 1 new *M-Tier Review Stack Thinning*. No requirement dropped
or duplicated. MODIFIED restatements (gate Required-Artifact-By-Scale, model-config Layered
Resolution, cli Worktree Lifecycle, skill-integration propose/analyze) are faithful supersets
with only intent-mandated edits. **But** consolidation faithfulness is violated by F2 — body
prose carries dangling retired-capability names that verbatim-preservation should have
remapped to the surviving capability.

**(e) Achievability vs code.** D1 `--cheap`: the gate HAS a two-phase structure (cheap
short-circuit at `executable_opsx:582`; expensive validations after), but the verdict checks
(verify/code-review/freshness/doneness at 700-860) live in the SECOND phase intermixed with
`run_in_impl` execution — so `--cheap` must guard only the `run_in_impl` executions + the
`have_required_source` validation-source requirement, not exit at the existing short-circuit
(else status's gate(cheap) would skip code-review/doneness state). Achievable, finer-grained
than D1's "just skip validations" wording implies. D2 archive-check verb: clean new dispatch
slot (`executable_opsx:1094` case has no `status`/`archive-check`); achievable. D3 tier
collapse: `case "$SCALE"` at 522/528/679/814 all need `XS S M` + full_rigor branching;
straightforward. D4 doneness provenance: `blind-single-judge` already accepted (835) — see
F4. D6 worktree derivation, D7 project-layer removal (reads at 245/277; but see F1 for the
write-surface remnant), D8 archive mechanics: all achievable. A4 `opsx_wt_valid_for_change`
helper exists (377); ensure refuse/reuse hardening implementable. Budget-defaults home is
NOT cleanly real — see F3.

**(f) Interplay + guards.** hold/latch/stall/locator/verdict-freshness/ADR-0014 confirm are
provably untouched (design D4/D10: `readDoneness`/`classifyDoneness` and hold/latch/stall
unchanged; deltas carry Stall/Loop-hold/Worktree-fallback requirements verbatim). No
surviving spec references retired capability names EXCEPT: the accepted opsx-cli exemption
list (identifier substrings, clarify I-2, non-normative) and the F2 dangling refs. The five
retired specs become empty stubs via REMOVED deltas + D8 dir-deletion.

**(g) Readiness for tasks.** A task list with file contracts is ~90% writable directly from
design D1–D10 + deltas. Blocked on: F1 (missing opsx-cli write-surface decision/delta), and
gated by F3 (budget-default home decision) before the extension/propose/gate tasks can be
written without ambiguity. F2 is a delta-edit before archive. F4–F6 are cleanups.

## Round Ledger

| Round | Mode | Blocker | Major | Minor | Reviewed HEAD |
|-------|------|---------|-------|-------|---------------|
| 1 | blind | 1 (F1) | 2 (F2,F3) | 3 (F4,F5,F6) | c3eec37daa722687e42690405a2e35eecf218c22 |
