<!-- authored: delegate blind analyze -->

# Analyze: quiet-round-review-convergence

Blind adversarial ANALYZE (feasibility + coherence gate, pre-implementation).
Baseline read: intent.md (frozen), proposal.md, 5 delta specs, design.md,
constitution.md, domain.md, the 5 live capability specs the deltas touch, and
code grounding (executable_opsx, openspec-loop SKILL.md, review.md template).

## Deterministic Checks

- **DC1 — `openspec validate quiet-round-review-convergence --strict`:**
  PASS — "Change 'quiet-round-review-convergence' is valid" (exit 0).
- **DC2 — every delta names a real capability home:** PASS.
  - opsx-adversarial-review/spec.md (MODIFIED) → live spec exists.
  - opsx-cli/spec.md (ADDED) → live spec exists.
  - opsx-gate-enforcement/spec.md (ADDED) → live spec exists.
  - opsx-skill-integration/spec.md (MODIFIED) → live spec exists.
  - opsx-workflow-schema/spec.md (ADDED x3) → live spec exists.
- **DC3 — MODIFIED requirements full-restatement (domain invariant #14):** PASS
  with caveat (see F1).
  - "Trajectory Stop And Round Budget" (adversarial-review): full new text +
    8 scenarios present; live "A stop never forges a green" preserved; live
    treadmill/budget-exhaustion behavior folded into the `land-on-stop`
    opt-in + hard-cap scenarios — no scenario silently dropped. Semantics
    change is intended. **Caveat:** a SIBLING untouched requirement in the
    same capability still pins this stop as "unchanged" (F1).
  - "openspec-loop orchestrator skill exists" (skill-integration): original
    prose + all 3 original scenarios preserved verbatim; 3 new scenarios
    appended. Clean full restatement.
- **DC4 — ADDED requirements collide with nothing live:** PASS. `sweep <change>`
  is a new subcommand; `review_budget_mode` is a new OPTIONAL field explicitly
  NOT in the existing "Mode switchboard" gate-read field list and explicitly
  not read by `opsx gate`; sweep gate check is conditional on sweep.txt. No
  overlap with existing requirements.
- **DC5 — Constitution IX flag:** PASS. Change edits an existing skill
  (openspec-loop SKILL.md) → gating multi-model code review; change is
  M + `full_rigor: true` with gating code review derived. Consistent.
- **DC6 — Q4 concrete claims verified against tree:** PASS (all real).
  - Duplicate/split `gate` line in `opsx_usage()` — CONFIRMED
    (executable_opsx L24 and L27 both emit `gate` usage lines, split by the
    `models` block).
  - Stray `tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp`
    — CONFIRMED present, 0 bytes, git-tracked.
  - review.md template Code Review Mode row shows literal `advisory` —
    CONFIRMED (templates/review.md Modes table).
  - Shipped templates verify.md / code-review.md / doneness.md all EXIST
    (Q3 target paths are real; code-review.md is 5.4K).

## Findings

### F1 — BLOCKER — delta set contradicts an untouched sibling requirement that pins the stop as "unchanged"
- **Artifact:** specs/opsx-adversarial-review/spec.md (delta) vs LIVE
  openspec/specs/opsx-adversarial-review/spec.md.
- **Description:** The change's central act (Q1) rewrites the
  "Trajectory Stop And Round Budget" requirement. But the LIVE, UNTOUCHED
  "M-Tier Review Stack Thinning" requirement in the SAME capability asserts:
  "At every tier the code-review verdict contract, severity rubric, round
  ledger, **trajectory/budget stop**, disclosure round, `review_max_rounds`,
  and freshness/provenance binding SHALL be unchanged" (live L8), echoed in
  its scenario "Code-review rigor is never reduced by thinning" (live L22).
  The delta set contains NO MODIFIED delta for "M-Tier Review Stack Thinning."
  Post-archive, opsx-adversarial-review/spec.md would carry BOTH the rewritten
  quiet-round stop AND a requirement enumerating "trajectory/budget stop" as
  an invariant that "SHALL be unchanged" — a self-contradiction on the very
  element this change changes. The intent's own carry-over list (intent.md
  "Constraints") deliberately OMITS the trajectory/budget stop from the
  unchanged set, proving the authors knew it changes — but the reconciling
  delta was never authored. The stale term "trajectory/budget stop" also
  appears in the untouched Disclosure Round requirement's trigger (live L102:
  "a trajectory/budget stop fires while a split is present"), which the new
  (c)/(d) stops must satisfy but no longer literally match by name.
- **Evidence:** live spec L8, L22, L102; delta has only
  `## MODIFIED Requirements → Trajectory Stop And Round Budget`; intent.md
  Constraints list omits the stop from "carry over unchanged."
- **Suggested resolution:** Add a MODIFIED delta for "M-Tier Review Stack
  Thinning" that drops "trajectory/budget stop" from the tier-invariant list
  (or restates it as "the review-convergence stop discipline — quiet-round by
  default, land-on-stop opt-in — is uniform across tiers"), and reconcile the
  Disclosure Round trigger wording so (c) thrash / (d) cap stops-with-split
  are named as the disclosure triggers. Ironic but on-point: this is exactly
  the stale-prose-surface class Q2's sweep exists to kill (the sweep excludes
  openspec/**, so it cannot catch this — it must be fixed by delta).

### F2 — MAJOR — sweep tree ambiguity: integration vs worktree → split-brain false pass/fail at Scale M
- **Artifact:** specs/opsx-cli/spec.md (delta), specs/opsx-gate-enforcement/spec.md
  (delta), design.md D3.
- **Description:** Neither the CLI requirement, the gate requirement, nor D3
  pins WHICH checkout the sweep greps. `opsx sweep <change>` is specified as
  `git ls-files -z | grep -nE` with signature `opsx sweep <change>` — no
  worktree parameter. But Scale M is `worktree-required`, and the gate resolves
  ALL artifacts from the worktree (ART_ROOT) precisely to avoid the documented
  split-brain failure ("a correct worktree could red-loop forever against
  stale root copies" — executable_opsx gate header). Stale-token FIXES land in
  the worktree. A sweep (standalone CLI run pre-round-1, or the gate cheap
  check) that greps the INTEGRATION root's `git ls-files` will read stale
  pre-fix copies → GATE-FAIL sweep even after the worktree is clean (false
  fail), or pass against integration while the worktree is dirty (false pass).
- **Evidence:** cli delta "greps every git-tracked shipped surface" (no tree);
  gate delta "one of its cheap deterministic checks" (no tree); D3 CLI signature
  omits worktree; executable_opsx L398-520 gate resolves ART_ROOT/WT_PATH.
- **Suggested resolution:** Specify the gate sweep greps ART_ROOT (the resolved
  worktree), and give `opsx sweep` worktree resolution (accept `--worktree` /
  reuse `opsx_wt_convention_path`, or run `git ls-files` scoped to the resolved
  tree) so the skill's pre-round-1 run and the gate check both target the
  implementation checkout.

### F3 — MAJOR — quiet-round progress predicate ("worktree HEAD") does not generalize to analyze-type gating rounds
- **Artifact:** specs/opsx-adversarial-review/spec.md (delta), design.md D1.
- **Description:** The MODIFIED "Trajectory Stop And Round Budget" governs ALL
  "blind gating review rounds"; the untouched Orchestrator Round Ledger
  requirement explicitly covers BOTH "code-review.md for post-apply diff-review
  rounds" AND "analyze.md for analyze-type gating rounds" (the `full_rigor`
  adversarial-on-analyze path). The delta's converging/thrash predicate is
  expressed purely as "the **worktree** HEAD has moved past the latest round's
  reviewed HEAD." Analyze rounds run PRE-apply on the integration checkout with
  NO worktree — "worktree HEAD" is empty/undefined there, so converging (b) can
  never evaluate true and every analyze round with findings falls to (c) thrash
  → lands. That REGRESSES analyze convergence (which today uses the trajectory
  rule) for exactly the full_rigor tier this change is authored under.
- **Evidence:** delta condition (b)/(c) "worktree HEAD"; live Orchestrator
  Round Ledger "analyze.md for analyze-type gating rounds"; design D1 inputs
  list "the current worktree HEAD."
- **Suggested resolution:** Generalize the progress signal to "the reviewed
  HEAD of the checkout the round ran against" (integration HEAD for analyze
  rounds, worktree HEAD for post-apply code-review rounds), or explicitly scope
  quiet-round to post-apply code-review rounds and state that analyze-type
  rounds retain their existing stop rule.

### F4 — MAJOR — fix-before-evaluate sequencing is load-bearing but only implicit; naive impl makes converging (b) unreachable
- **Artifact:** specs/opsx-adversarial-review/spec.md (delta), design.md D1,
  SKILL.md cycle prose (implementation surface).
- **Description:** Converging (b) requires HEAD to have moved "since the
  previous round," i.e. the round's fixes must land BEFORE the stop-evaluation.
  Thrash (c) fires when HEAD still equals the reviewed HEAD at evaluation time.
  If an implementer evaluates the stop conditions IMMEDIATELY after a round
  concludes (before attempting/landing the fix for that round's findings), HEAD
  == reviewed HEAD on every first-findings round → (c) thrash lands
  immediately → (b) converging is DEAD and the entire quiet-round feature never
  continues autonomously. The spec conveys the required ordering only obliquely
  ("subsequently landed", "when the next dispatch is evaluated"); the current
  SKILL "Stop conditions — evaluate BEFORE dispatching the next blind round"
  table does not state that the round's fixes are attempted/landed first.
- **Evidence:** delta scenarios "Converging rounds continue" ("subsequently")
  and "Thrash guard" ("when the next dispatch is evaluated"); design D1 thrash
  definition ("no fixes land → HEAD unmoved → (c)"); SKILL.md L~118 Stop
  conditions table.
- **Suggested resolution:** Make the cycle ordering explicit in the SKILL
  review-convergence prose (and ideally a spec note): after a round with
  findings, attempt+commit the fix, THEN evaluate — (c) thrash means the fixer
  could not land any commit (fixer failure / recirculation without landing),
  not merely "findings still open right after the round."

### F5 — MINOR — design D3 cites a nonexistent "Hard Cutover legacy-token scan" as the exclusion-set precedent
- **Artifact:** design.md D3.
- **Description:** D3 justifies the openspec/** + adr/** exclusion as "Same
  exemption set as the Hard Cutover legacy-token scan." No such scan exists —
  repo-wide grep finds no legacy/cutover token scan in executable_opsx or
  tests; the only "Hard Cutover" requirement (opsx-cli "Hard Cutover No Legacy
  Entrypoints") is about retiring the standalone opsx-gate/opsx-models
  entrypoints, not a token scan. Dangling rationale an implementer may hunt for.
- **Evidence:** `grep -rn "Hard Cutover|legacy-token"` → no scan; opsx-cli
  spec L30 requirement is entrypoint-retirement.
- **Suggested resolution:** Drop the false precedent or restate as "the same
  non-deployed-workspace exclusion the constitution VIII / domain #3 rationale
  implies," which the exclusion already stands on independently.

### F6 — MINOR — sweep malformed-regex / grep-error path undefined; grep exit 2 can be conflated with a hit
- **Artifact:** specs/opsx-cli/spec.md (delta), design.md D3.
- **Description:** sweep.txt lines are user-authored EREs fed to `grep -nE`.
  An invalid ERE makes grep exit 2 (error). The CLI contract is "exit non-zero
  when one or more hits exist and zero otherwise" — an error exit 2 with no
  actual hit would surface as a failing sweep / GATE-FAIL sweep with no
  SWEEP-HIT line, or crash the cheap-check tier, with no defined behavior.
- **Evidence:** cli delta exit contract; D3 "grep -nE"; no malformed-pattern
  scenario.
- **Suggested resolution:** Define behavior for a non-matching grep error
  (exit ≥2): treat as a loud validation failure distinct from a clean pass
  (e.g. `SWEEP-ERROR <pattern>` + non-zero), never a silent exit 0.

### F7 — MINOR — new `review_budget_mode` absent-default reduces default human-in-the-loop; document the intent to preempt a later fail-open flag
- **Artifact:** specs/opsx-workflow-schema/spec.md (delta), design.md D2.
- **Description:** Absent `review_budget_mode` ⇒ `quiet-round` (autonomous
  continuation, fewer human rulings by default); unknown value ⇒ `land-on-stop`
  (stricter). The absent-default is the LESS human-in-the-loop posture, which a
  future fail-open audit (this change's own Q4 D5 rider!) could flag as
  fail-open. It is NOT a correctness fail-open — the intent constraint "a stop
  with open P0/P1 still NEVER seals pass" holds and is spec'd ("A stop never
  forges a green"), so quiet-round only automates CONTINUE, never SEAL. This is
  intentional per intent ("the new default").
- **Evidence:** workflow-schema delta "absent ⇒ quiet-round"; design D2;
  intent.md Q1 + Constraints; delta scenario "A stop never forges a green."
- **Suggested resolution:** Record explicitly (design D2 / D5 audit table) that
  `review_budget_mode` absent⇒quiet-round is an intentional autonomy default,
  NOT a fail-open divergence, so the Q4 mode-key audit does not later mis-flag
  it.

## Verdict
BLOCKED (1 blocker)

---

## Round Ledger

<!-- orchestrator-maintained; analyze-type gating rounds -->

| Round | Mode | P0+P1 (consolidated) | Verdict | Reviewed HEAD |
|---|---|---|---|---|
| 1 | blind | 4 (F1 blocker + F2/F3/F4 majors) | BLOCKED | 03bc118 |
| 2 | blind | 2 (R2-B1, R2-B2 blockers) | BLOCKED | f45dabf |
| 3 | blind | 1 (R3-B1 blocker) | BLOCKED | eee716c |

## Resolution Log (orchestrator, post-round-1)

- **F1 (blocker):** MODIFIED deltas added for `M-Tier Review Stack Thinning`
  (invariant list now names "review-convergence stop discipline (quiet-round
  default with the land-on-stop opt-in)" instead of "trajectory/budget stop")
  and `Disclosure Round` (trigger reconciled to thrash-guard/hard-cap stops,
  with trajectory/budget naming retained under land-on-stop mode). Full
  restatements per domain invariant #14.
- **F2 (major):** sweep tree pinned to the resolved implementation checkout
  (gate ART_ROOT; CLI resolves like the gate, loud `--worktree` validation) —
  cli + gate-enforcement deltas + design D3.
- **F3 (major):** progress signal generalized to "HEAD of the reviewed
  checkout" (worktree for post-apply, integration for analyze-type); new
  scenario pins analyze rounds converge instead of always-thrashing.
- **F4 (major):** fix-before-evaluate ordering made explicit in requirement
  prose + new "Fix lands before evaluation" scenario + design D1.
- **F5 (minor):** false "Hard Cutover legacy-token scan" precedent dropped
  from D3; rationale rests on Constitution VIII / domain #3.
- **F6 (minor):** SWEEP-ERROR contract added (grep exit ≥2 → loud non-zero,
  never silent pass) — cli delta + D3.
- **F7 (minor):** review_budget_mode absent-default pre-cleared as
  intentional autonomy default in D2 + D5 audit table (audit must not flag).

Round 2 (blind confirmation) required before tasks generation.

## Resolution Log (orchestrator, post-round-2)

Round 2 report: /tmp/qrrc-analyze-r2.md (blind, fresh reviewer; verified all
round-1 resolutions hold as non-findings). 2 NEW blockers, 0 majors:

- **R2-B1 (blocker):** ADDED `opsx sweep` contradicted the untouched live
  `Unified Subcommand Dispatch` enumeration (`gate|models|loop` + reject-others
  scenario). Resolved: MODIFIED delta restating the requirement with the full
  deployed dispatch set + `sweep`; unknown-subcommand scenario made
  enumeration-relative; `Sweep dispatches` scenario added. The widening beyond
  `sweep` (stale enumeration vs deployed `status`/`worktree`/`clean`/
  `archive-check` arms) is logged in review.md Scope Expansions with evidence.
  Proposal Impact row updated.
- **R2-B2 (blocker):** analyze-round progress signal (raw integration HEAD)
  was always-converging — ledger-seal + sibling-change commits on shared main
  move HEAD without fixes, disabling the thrash guard for analyze rounds
  (violates the frozen-intent crypt-log constraint). Resolved: progress signal
  redefined change-scoped — analyze rounds require a commit in
  reviewedHEAD..HEAD touching the change dir through paths OTHER than the
  round-ledger artifact; scenarios "Ledger seals never count as progress" +
  "Analyze-type rounds measure change-scoped fix commits" added. Post-apply
  invariant spec'd: verdict/ledger seals land on the integration checkout,
  never the reviewed worktree branch ("Post-apply seals stay off the reviewed
  branch"). Design D1 rewritten to match.
- **R2 minor (unnumbered, report §2 tail):** seals-off-reviewed-branch
  invariant "nowhere stated" — same fix as R2-B2 third scenario; recorded.

Round 3 (blind confirmation) required before tasks generation.

## Resolution Log (orchestrator, post-round-3)

Round 3 report: /tmp/qrrc-analyze-r3.md (blind, fresh reviewer; deterministic
table all-PASS except post-archive coherence; R2 resolutions verified clean as
non-findings, incl. dispatch-enumeration grounding against deployed case arms).
1 NEW blocker, 0 majors, 2 advisories:

- **R3-B1 (blocker):** analyze-round progress predicate ("any change-dir path
  except the ledger") counted orchestrator BOOKKEEPING as progress —
  follow-ups.md routing, review.md Scope Expansions/Execution Notes,
  clarify.md — so a crypt-log-class round that only routed an out-of-scope
  finding would false-converge past the thrash guard (frozen-intent
  violation). Resolved: predicate narrowed to a POSITIVE enumeration of
  authored fix surfaces (proposal.md, design.md, specs/**, tasks.md,
  plan.md); bookkeeping artifacts never count even when committed alongside
  a seal; scenarios rewritten ("Analyze-type rounds measure fix-surface
  commits", "Bookkeeping never counts as progress"); design D1 updated.
- **R3-A1 (advisory, accepted):** post-apply documentary fix (change-dir-only
  edit) leaves worktree HEAD unmoved → false thrash-land. Fails SAFE; rare;
  alternative reopens the bookkeeping hole. Documented in design D1, not
  spec'd.
- **R3-A2 (advisory, applied):** the two `opsx_usage()` gate lines are
  distinct option forms, not exact duplicates — Q4 rider adjusted in design
  D5 to MERGE/consolidate (both forms preserved) instead of deleting a line.

Round 4 (blind confirmation) required before tasks generation.
