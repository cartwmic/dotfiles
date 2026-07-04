<!-- authored: delegate blind clarify -->

# Clarify: quiet-round-review-convergence

Blind three-pass clarify over the 5 delta specs against the FROZEN `intent.md`
baseline (never edited). Autonomous mode: every finding self-resolved with the
option best grounded in intent.md / constitution.md / domain.md; rationale cites
the anchor line. Scope: `--delta-only`.

**Validation before:** `openspec validate quiet-round-review-convergence --strict` → GREEN
**Validation after:** `openspec validate quiet-round-review-convergence --strict` → GREEN

---

## Pass 1 — Ambiguity (paraphrase divergence)

| # | AC ref | Severity | Question | Option A | Option B | Resolution + rationale | Edit |
|---|---|---|---|---|---|---|---|
| A1 | opsx-cli.migration-completeness-sweep-command | major | The cli req says the sweep "greps **every git-tracked file** outside the excluded history surfaces" while the schema req says "all git-tracked **shipped surfaces**". Do these two phrasings name the same set? | A: every tracked file minus `openspec/changes/**`+`adr/**` (cli literal — broader) | B: only deployed/shipped surfaces, i.e. the whole `openspec/**` workspace excluded (schema intent) | **B.** Intent Q2 says "greps ALL **shipped** surfaces"; Constitution VIII + domain #3 make the entire `openspec/` workspace non-deployed (gitignored from apply), so it is not a shipped surface. Reworded the cli req to "every git-tracked shipped surface — every git-tracked file outside the excluded OpenSpec workspace (`openspec/**`) and ADR history (`adr/**`)", aligning it to the schema req and the same exclusion set. | y |
| A2 | opsx-adversarial-review.trajectory-stop-and-round-budget | low | "Quiet round" is phrased three ways: intent "0 **new** P0/P1", req "consolidated P0+P1 count is zero", scenario "0 **open** P0/P1". Do they diverge? | A: equivalent (blind full-diff re-review ⇒ every round re-reports all open findings; no dedup ⇒ new==open==round count) | B: "new" implies cross-round diffing of finding identity | **A.** intent Constraints forbid "cross-round finding matching of any kind"; each blind round re-reports the full current-HEAD finding set, so per-round count == open count == "new this round". No semantic divergence; no edit. | n |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC ref | Severity | Question | Option A | Option B | Resolution + rationale | Edit |
|---|---|---|---|---|---|---|---|
| I1 | opsx-adversarial-review.trajectory-stop-and-round-budget | major | Conditions evaluate "IN ORDER (a) quiet (b) converging (c) thrash (d) hard cap". At `rounds == review_max_rounds` with findings AND fixes landed, (b) matches first and dispatches another round — so (d) hard cap never fires. Does hard cap really bind "regardless"? | A: guard (b) on `completed rounds < review_max_rounds` so (d) is reachable (matches the scenario's own `WHILE below review_max_rounds`) | B: leave (b) unguarded — converging wins at the cap | **A.** intent Q1 cond 4: "completed rounds ≥ `review_max_rounds` → decision-audit landing **regardless**"; the delta's own "Converging" scenario already carries `WHILE the completed round count is below review_max_rounds` while the requirement prose omitted it — an internal contradiction. Added `AND the completed round count is below review_max_rounds` to condition (b) prose. Order preserved; hard cap now reachable when fixes land at the cap. | y |
| I2 | opsx-workflow-schema.migration-sweep-declaration | major | The swept-surface exclusion names only `openspec/changes/**` and `adr/**`, implying `openspec/specs/**` IS swept. The live specs still carry the outgoing (retired) tokens until this change archives its deltas — so a rename-class sweep would SWEEP-HIT the live specs pre-round-1 and the skill's "resolve all hits before dispatch" becomes unsatisfiable (specs are updated only at archive). | A: exclude the entire `openspec/**` workspace (specs + change artifacts) | B: keep excluding only `changes/**`+`adr/**`, sweep the live specs | **A.** Constitution VIII + domain #3: all of `openspec/` is non-deployed (not a shipped surface); the sibling opsx-cli "Hard Cutover" legacy-token scan already exempts `openspec/specs/**`, `openspec/changes/**`, `adr/**` for exactly this reason (specs migrate at archive, not in the working tree). Broadened the exclusion to `openspec/**` in the schema req + "History surfaces excluded" scenario, and mirrored it in the cli req + "History surfaces never hit" scenario. Coverage of the target class (stale SHIPPED prose surfaces under `dot_local/**`,`dot_pi/**`) is unaffected. | y |
| I3 | opsx-adversarial-review.trajectory-stop-and-round-budget | medium | Under quiet-round default, the "converging" path continues autonomously. The unchanged live Disclosure Round req fires on "two consecutive split rounds" independent of trajectory. When both hold (splits for 2 rounds AND fixes landed), (b) says "dispatch next **blind** round" but Disclosure Round says "dispatch the **disclosure** round" — conflict on the next round's type. | A: converging governs WHETHER to continue; the unchanged Disclosure Round req governs the round TYPE (disclosure when its trigger fired, else blind) | B: converging always dispatches a blind round, suppressing the mid-loop disclosure trigger | **A.** intent Constraints: "single disclosure round ... carry over **unchanged**"; Non-goals: "Changing ... the disclosure-round limit." Option B would silently disable the 2-consecutive-split disclosure trigger during convergence. Added a prose clause + a "Converging continuation respects the disclosure trigger" scenario making converging defer to the unchanged Disclosure Round req for round type. | y |

## Pass 3 — Completeness (priority-bounded enumeration)

| # | AC ref | Severity | Question | Option A | Option B | Resolution + rationale | Edit |
|---|---|---|---|---|---|---|---|
| C1 | opsx-cli.migration-completeness-sweep-command | medium | A `sweep.txt` that EXISTS but contains only comment/blank lines (zero effective patterns) is uncovered: "Missing declaration is a soft pass" covers absent-file; "Declaration format parsed" covers mixed content; neither states the zero-pattern outcome. | A: clean pass — grep nothing, zero hits, exit zero | B: treat as missing declaration (print the "no declaration" notice) | **A.** The req already says "exits ... zero [when no hits]"; zero patterns ⇒ nothing forbidden ⇒ no hits ⇒ deterministic exit zero (intent Q2 "deterministic ... fails on hits"). Fail-safe and consistent with "Clean sweep passes". Added explicit "Empty declaration is a clean pass" scenario to the cli delta so the edge is pinned. | y |
| C2 | opsx-adversarial-review.trajectory-stop-and-round-budget | low | Round-1 edge: converging/thrash compare against "the latest round's reviewed HEAD" — does round 1 lack a prior HEAD to compare? | A: covered — comparison is (just-completed round's reviewed HEAD) vs (current worktree HEAD); round 1's own reviewed HEAD exists | B: gap — needs a special round-1 rule | **A.** intent Q1: signal is "fix commits ... landed since the previous round (worktree HEAD moved)". The just-completed round (incl. round 1) always has a recorded reviewed HEAD in the ledger (opsx-adversarial-review Orchestrator Round Ledger); after round 1, fixing moves HEAD → converging. No gap; no edit. | n |
| C3 | opsx-adversarial-review.trajectory-stop-and-round-budget | low | Disclosure-round interaction with a STOP (thrash/hard cap) while a split is present — is the live "trajectory/budget stop fires while split present → disclosure" arm preserved under quiet-round mode? | A: covered — thrash (c) and hard cap (d) both route to "disclosure/landing handling", preserving that arm | B: gap | **A.** delta conditions (c)/(d) route to "the split-verdict and decision-audit handling", which is the existing disclosure/landing path; the live Disclosure Round req is untouched (intent: disclosure unchanged). No gap; no edit. | n |

---

## Outstanding (status != answered)

None. All 8 findings self-resolved in autonomous mode (no escalation to the user).

## Summary

- Pass 1 — Ambiguity: 2 findings (1 major, 1 low)
- Pass 2 — Inconsistency: 3 findings (2 major, 1 medium)
- Pass 3 — Completeness: 3 findings (1 medium, 2 low)
- **Total: 8 findings — 8 resolved, 0 unresolved.**
- **Edits applied: 5 findings drove spec edits (A1, I1, I2, I3, C1); 3 confirmed already-covered (A2, C2, C3).**
- Files edited: `specs/opsx-adversarial-review/spec.md`, `specs/opsx-workflow-schema/spec.md`, `specs/opsx-cli/spec.md`. Never edited: `intent.md`, any live `openspec/specs/**`.
- Validation before: GREEN. Validation after: GREEN.
- **Gate Status: READY for design (0 unanswered findings).**
