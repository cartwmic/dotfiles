<!-- authored: in-session -->

# Design: quiet-round-review-convergence

Decisions for Q1–Q4, traced to the frozen intent and the clarify resolutions
(A1, I1, I2, I3, C1 edits already landed in the delta specs).

## D1 — Quiet-round evaluation algorithm (Q1)

**Decision.** After each completed gating round (post-apply code-review AND
analyze-type rounds), the orchestrator evaluates IN ORDER, from four
deterministic inputs only — the round ledger's per-round consolidated P0+P1
counts (max across reviewers), the ledger's per-round reviewed HEADs, the
**change-scoped progress signal**, and `review_max_rounds`
(+ `review_budget_mode`). The progress signal is per round type (analyze F3,
R2-B2):

- **Post-apply rounds:** reviewed worktree branch HEAD moved past the
  round's reviewed HEAD. Honest because verdict/ledger seals land on the
  INTEGRATION checkout (Verdict Freshness already forbids staling the sealed
  range) — only implementation fix commits move the worktree branch. That
  invariant is now spec'd ("Post-apply seals stay off the reviewed branch").
- **Analyze-type rounds (pre-apply, no worktree):** ≥1 commit in
  `reviewedHEAD..HEAD` touching `openspec/changes/<change>/**` through paths
  OTHER than the round-ledger artifact. Raw integration HEAD is dishonest
  here — ledger-seal commits and sibling-change commits on the shared main
  branch move it without any finding being fixed, which would make analyze
  rounds always-converging and disable the thrash guard (R2-B2). Git
  plumbing: `git log --name-only` over the range, filtered to the change
  dir minus the ledger file — deterministic, model-free.

| # | Condition | Predicate | Action |
|---|---|---|---|
| a | quiet round | latest round P0+P1 == 0 | seal `Verdict: pass`, stop |
| b | converging | P0+P1 > 0 AND progress signal holds AND completed rounds < cap | dispatch next round, NO ruling |
| c | thrash guard | P0+P1 > 0 AND progress signal does NOT hold | disclosure/landing |
| d | hard cap | completed rounds ≥ cap | disclosure/landing |

The (b) guard `rounds < cap` is load-bearing (clarify I1): without it,
converging-at-the-cap dispatches forever and (d) never fires.

**Fix-before-evaluate ordering is load-bearing (analyze F4).** After a round
concludes with findings, the orchestrator attempts and COMMITS the fixes
FIRST, then evaluates (b)/(c). Evaluating immediately at round end would
find HEAD == reviewed HEAD on every first-findings round, making (b)
unreachable and (c) fire always — the feature would be dead on arrival.
Thrash therefore means "the fix attempt landed nothing", and the skill's
cycle prose states this ordering explicitly.

**Round type under (b) is not always blind** (clarify I3): (b) decides
WHETHER to continue; the untouched Disclosure Round requirement decides the
TYPE — if 2 consecutive split rounds accrued, the continuation IS the single
disclosure round. Converging never suppresses the disclosure trigger.

**Rejected alternatives.**
- *Cross-round finding-identity matching* ("new" vs "re-reported" findings):
  semantic, model-dependent — violates the intent constraint and ADR-0007
  lineage. Per-round counts suffice because blind full-diff re-review
  re-reports the full open set each round (clarify A2: new == open == count).
- *Trajectory slope* (shrinking counts ⇒ continue): the archived 8-round
  change ran flat at 1×P1/round while healthy — slope cannot distinguish it
  from thrash. HEAD-moved is the honest progress signal and already exists
  (loop stall guard uses the same primitive).

**Why the thrash guard catches crypt-log but not simplify.** Crypt-log-class
thrash = rounds re-dispatched with findings while no fixes land (fixer
failure / recirculation without landing) → HEAD unmoved → (c) lands.
Simplify-class convergence = a fix commit landed every round → (b) continues.
Recirculation WITH landed commits (fix-revert churn) is bounded by (d).

## D2 — `review_budget_mode` front-matter key (Q1 opt-in)

**Decision.** New orchestrator-read key, vocabulary `quiet-round |
land-on-stop`, absent ⇒ `quiet-round`, unknown value ⇒ `land-on-stop`
(fail toward the stricter human-in-the-loop mode — same fail-closed posture
as scale/full_rigor parsing). `opsx gate` does not read it.
`review_max_rounds` semantics unchanged (absent/invalid ⇒ 5); under
quiet-round it is the hard cap, and a decision-audit resume ruling may still
extend it (ledger-recorded), unchanged.

**Rejected:** defaulting to `land-on-stop` and opting IN to quiet-round.
The intent names quiet-round "the new default"; land-on-stop survives as the
paranoid opt-in.

**Not a fail-open divergence (analyze F7).** Absent ⇒ `quiet-round` is the
LESS human-in-the-loop posture by deliberate intent ("the new default") — it
automates CONTINUE only, never SEAL ("a stop never forges a green" holds
under both modes). The Q4 fail-open audit (D5) SHALL NOT flag this key: its
documented promise IS the autonomy default, and the unknown-value parse
already fails toward the stricter mode.

## D3 — Migration sweep (Q2)

**Declaration.** `sweep.txt` in the change dir: one extended-regex pattern
per line, `#` comments + blank lines ignored. Zero effective patterns ⇒
clean pass (clarify C1). No YAML — grep-native, zero parsing machinery.

**Swept surface.** `git ls-files` minus `openspec/**` and `adr/**`
(clarify I2/A1): the OpenSpec workspace is non-deployed (Constitution VIII,
domain #3) and live specs legitimately carry retired tokens until archive —
sweeping them would make pre-round-1 resolution unsatisfiable. (Rationale
stands on Constitution VIII / domain #3 alone; analyze F5 removed a false
precedent citation.) The target class (stale shipped prose under
`dot_local/**`, `dot_pi/**`, `tests/**`) is fully covered.

**Tree resolution (analyze F2).** The sweep greps the change's RESOLVED
implementation checkout, exactly as the gate resolves it: recorded worktree
locator / convention path when worktree-required, integration checkout
otherwise; explicit `--worktree` validated loudly. Without this, stale-token
fixes landing on the worktree branch would false-fail (or false-pass) a
sweep run against the integration root — the same split-brain the gate's
ART_ROOT resolution exists to prevent. The gate's conditional sweep check
greps ART_ROOT.

**CLI.** `opsx sweep <change>`: `SWEEP-HIT <pattern> <file>:<line>` per hit,
exit 1 on any hit, exit 0 clean; missing sweep.txt ⇒ notice + exit 0.
Malformed-pattern grep error (exit ≥ 2) ⇒ `SWEEP-ERROR <pattern>` + exit
non-zero — loud, distinct from hit and pass, never silent (analyze F6).
Implemented with `git ls-files -z` + `grep -nE` in the resolved checkout —
deterministic, model-free.

**Gate integration.** Cheap-check tier, CONDITIONAL: runs only when
sweep.txt exists; emits `GATE-FAIL sweep`. Undeclared changes: zero new
obligations, zero output. This makes the sweep enforced (not merely
skill-suggested) exactly and only where a change opted in.

**Skill trigger.** openspec-loop directs: for changes declaring sweep.txt,
run `opsx sweep <change>` and resolve all hits BEFORE dispatching review
round 1. (The gate conditional makes forgetting non-fatal — the gate still
fails — but the pre-round-1 trigger is what saves review rounds.)

**Rejected:** always-on sweep with auto-derived tokens (cannot derive
"retired vocabulary" deterministically from a diff); declaration in review.md
front-matter (multi-line regex lists don't belong in YAML front-matter the
gate parses cheaply).

## D4 — Verdicts from templates (Q3)

**Decision.** openspec-loop's verdict-authoring directives point at the
shipped template PATHS
(`dot_local/share/openspec/schemas/opsx-superpowers/templates/{verify,code-review,doneness}.md`
as deployed) with "fill, don't free-write". No gate change — the gate already
parses the field formats the templates carry; this closes the archaeology gap
at the source.

## D5 — Q4 riders

| Rider | Treatment |
|---|---|
| review.md template Code Review Mode row shows literal `advisory` | fix row to "derived (gating-required at M, advisory below)" — spec'd (Template Mode Table Mirrors Derived Defaults) |
| duplicate `gate` line in `opsx_usage()` | delete one line; pin with a uniqueness grep test |
| stray empty `tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp` | `git rm`; pin absence in the surfaces test |
| fail-open-by-omission audit of remaining mode keys | enumerate every derived/defaulted key read by executable_opsx + skills (worktree_mode, code_review_mode, doneness_mode, validation_source_mode, review_budget_mode, review_max_rounds, loop_hold, full_rigor, scale); assert each absent-key default matches documented promise; fix + pin any fail-open divergence found. Findings recorded in verify.md; spec deltas added only if a divergence exists. `review_budget_mode` absent⇒quiet-round is pre-cleared as an INTENTIONAL autonomy default (analyze F7), not a divergence |

## Replay validation (success criterion 1)

Table-top replay, cap as ultimately authorized:

| Case | History | Under Q1 (cap 10) | Rulings |
|---|---|---|---|
| simplify-and-parallelize | R1–R7 each: findings, fix landed same round; R8: 0 P0/P1 | R1–R7 → (b) converging, autonomous; R8 → (a) quiet, seal pass | **0** (was 3) |
| simplify with default cap 5 | same | R1–R4 (b); after R5 → (d) landing; one resume ruling extends; R6–R7 (b); R8 (a) | 1 (was 3) |
| crypt-log-redaction class | repeated rounds, findings, fixes not landing | first no-progress evaluation → (c) thrash landing | 1, early (was ~4.5h treadmill) |

## Constitution compliance

- **I (source wins):** all edits in chezmoi source; deploy via chezmoi apply
  post-archive (human).
- **II (real paths):** skill at
  `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`;
  extension untouched (no opsx-loop extension logic changes — orchestrator
  semantics live in the skill; the extension stays a kickoff adapter).
- **VII (deterministic gate):** sweep + budget-mode parsing are grep/count
  logic; gate stays model-free.
- **IX (existing-skill edits):** openspec-loop SKILL.md edited ⇒ gating
  2-model blind adversarial code review (already forced by Scale M derived
  code_review_mode).

## ADR candidates (full_rigor ⇒ promotion at archive)

- Quiet-round convergence semantics: progress-signal continuation supersedes
  count-trajectory stopping (extends/supersedes ADR-0017).
- Declared-token migration sweep: deterministic whole-class validation
  before sampled review.
