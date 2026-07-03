# Intent: simplify-and-parallelize-opsx-workflow

<!-- FROZEN at loop arm. Distilled from the 2026-07-03 explore session
     (parallel-loops collision analysis + independent simplicity audit).
     Supporting evidence: audit.md in this change dir (blind opus audit,
     verdict: mixed). -->

## Intent

Make the opsx workflow safely support **multiple concurrent loops on the same
repo** (different changes, different pi sessions, git worktrees) using the
*minimum* machinery that survives an over-engineering audit — and, in the same
coordinated schema-surgery pass, **simplify the workflow itself** where the
audit showed complexity that does not pay under the grounding assumptions.

Two coupled outcomes:

1. **Parallel-safe loops, audit-lean.** Prevent the collision classes that are
   real for a solo developer running 1–3 concurrent loops (stale-base landing,
   index-sweep commits, ADR-number collisions, mismatched worktree reuse) with
   deterministic, model-free checks — and make the fleet *visible* (read-only
   `opsx status` across all changes/sessions) instead of locking blindly.
2. **A thinner workflow.** Fold the M-tier review stack down (doneness into
   the code-review dispatch, clarify into proposal open-questions, analyze
   thinned to its deterministic checks — full stack retained at the top tier),
   collapse Scale 5→3 gate-real tiers with an explicit flag for
   ADR/adversarial/retrospective extras, and consolidate the opsx spec surface
   from 12 capabilities toward ~7–8.

## Grounding assumptions (judge all scope against these)

- **Solo developer.** One human; no team, no external PRs, no shared CI.
- Usually one machine; repo doubles as the workflow's own source (chezmoi).
- Real parallelism ambition: 2–3 loops, different changes, multiple pi
  sessions, worktrees per change. Simultaneous propose phases are possible but
  are **path-disjoint by construction** (each writes only
  `openspec/changes/<change>/`), so the only real propose-overlap mechanism is
  the shared git index — not textual conflict.
- Agents are fallible; the deterministic gate + blind adversarial review are
  the antidote. "Trust the agent" is never a simplification.

## In scope (settled decisions)

### A. Concurrency (audit-lean)

- **A1 — land-base-current:** landing/archive requires
  `merge-base(opsx/<change>, main) == main HEAD`. Forces rebase before land;
  the rebase staleness-fires a fresh review — **accepted cost** (second lander
  pays a fresh review). Deterministic git plumbing; gate check or archive
  precondition.
- **A2 — path-scoped main commits:** all loop-driven commits on the
  integration checkout use `git commit -- <paths>` (never bare `commit`, never
  `add -A`). Backstop the discipline with a small deterministic detector that
  flags any main commit touching more than one `openspec/changes/<change>/`
  dir (detection, not prevention; ~5 lines).
- **A3 — duplicate-ADR-number scan at archive** (trivial grep-class check).
- **A4 — worktree ensure refuse/reuse rules:** reuse iff the existing worktree
  validates on branch `opsx/<change>` (`opsx_wt_valid_for_change`); refuse
  loudly otherwise; never auto-delete.
- **A5 — `opsx status` fleet view (the audit's top under-investment):**
  read-only, deterministic, model-free scan of `openspec/changes/*` printing
  per change: gate red/green summary + last failing check, Scale, worktree
  path + health, `loop_hold` state + reason, Diff Base vs main HEAD staleness
  (commits behind). Subsumes what a lock was reaching for: see collisions,
  don't lock against them. Also serves recovery ergonomics after a
  stall/budget stop.

### B. Simplification (audit findings, acted on)

- **B1 — M-tier thinning:** at Scale M, the doneness judgment rides the
  code-review dispatch (same blind reviewer, no separate dispatch) but its
  verdict is still written to a **separate doneness.md** file — the gate's
  doneness artifact requirement, freshness/provenance binding, and the
  standing every-Scale≥M-change-requires-doneness.md policy are unchanged;
  only the extra dispatch is eliminated at M. Fold clarify into the proposal's
  open-questions section; thin analyze to its deterministic checks (no
  separate blind dispatch at M). The full independent stack (standalone blind
  clarify, analyze, independently-dispatched doneness judge) is retained at
  the top tier. The doneness gap-set ratchet remains valid at all tiers
  (doneness.md exists at every tier ≥ M).
- **B2 — Scale collapse 5→3:** XS / S / M as gate-real tiers (the gate already
  distinguishes only these three — M/L/XL share one required-artifact set).
  ADR promotion, adversarial-on-analyze, and retrospective become an explicit
  opt-in flag (review.md front-matter) instead of a hidden consequence of the
  L/XL labels. The former L/XL full-stack requirements map to "M + flag".
- **B3 — spec consolidation 12 → ~7–8 opsx capabilities:** merge
  opsx-loop-kickoff + opsx-loop-orchestration (one loop capability); merge
  opsx-review-convergence + opsx-post-impl-review (one adversarial-review
  capability); fold opsx-doneness-judge per B1. No behavior change from
  consolidation itself — documentation topology only; every surviving
  requirement/scenario must be preserved or explicitly retired with rationale.
- **B4 — riders:**
  - XS/S auto-downgrade to `same-tree` worktree mode unless overridden
    (worktree-required stays the default at M+).
  - Drop the project-layer models yaml (resolution becomes env >
    front-matter > user > default).
  - goal-loop spec gains an explicit deprecation/fallback status note
    relative to the opsx-loop extension (no removal in this change).

## Constraints

- Extension + gate stay **deterministic and model-free** (ADR-0007 lineage).
  No LLM calls in gate/extension paths; no semantic matching.
- The loop **never archives or deploys**; human retains archive/deploy.
- Keyword grammar unchanged: `goal <text>` | `goal` | `<change-name>` |
  status/clear/models.
- **ADR-scarred guards preserved untouched:** loop_hold landing channel
  (ADR-0022), explicit-resume-only latch (ADR-0021), distill one-shot human
  confirm (ADR-0014), trajectory stop + review_max_rounds (ADR-0017), single
  late disclosure round (ADR-0018), locator publication + single-sourced
  convention fallback (ADR-0023), verdict freshness/provenance binding,
  fail-closed mode validation, turn budget + stall detection, verify.md
  AC↔test gate.
- The **2-model blind adversarial code review is load-bearing — do not
  weaken it** at any tier. B1 moves *where* the doneness question is asked at
  M; it does not reduce code-review rigor.
- Constitution VIII (openspec/ not chezmoi-deployed), IX (skill changes at
  Scale ≥ M require adversarial review — applies to this change), II (skills
  live at the canonical path) all apply.
- Backward compatibility at cutover: existing archived changes and their
  review records are historical — no rewriting of archive contents. The
  schema/template/tier migration applies to changes created after this lands.

## Audit findings record (from audit.md, incorporated by reference)

- Verdict: **mixed** — deterministic-gate + blind-review spine is
  proportionate and ADR-scarred (keep); M-tier stacking and the pre-audit
  concurrency plan were the over-engineering; fleet visibility was the top
  under-investment.
- KEEP verdicts (untouched by this change): code review, trajectory stop,
  disclosure round, loop_hold, latch, distill confirm, locator single-source,
  verdict freshness, fail-closed modes, budgets/stall, AC↔test gate.
- Acted on: M-tier thinning (B1), Scale collapse (B2), spec consolidation
  (B3), riders (B4), fleet status (A5), land-base-current (A1), commit
  discipline + detector (A2), ADR scan (A3), ensure refuse/reuse (A4).
- Rejected/cut per audit: per-change flock + PID stale-heal (double-driving
  one change is already gated by explicit human-only arming); distill nonce
  (cross-adopt is caught at the ADR-0014 confirm pause).
- Deferred per audit: branch-first authoring + `.opsx-control` file (churns
  ADR-0022/0023 landed 2026-07-03; the prevented failure — a review.md merge
  conflict at land — is a seconds-long manual fix; revisit only on observed
  pain).

## Non-goals

- Per-change advisory flock / lock files / PID stale-lock healing (cut).
- Distill session nonce (cut).
- Branch-first artifact authoring and a separate `.opsx-control` control file
  (deferred — not in this change; review.md merge conflicts at land stay an
  accepted manual resolution).
- In-session multi-loop (one loop per pi session is a feature).
- Goal-text↔change-name semantic matching of any kind.
- Weakening or reducing rounds/models of the adversarial code review.
- Automating archive, merge, push, or deploy.
- Removing the goal-loop capability or extension (deprecation note only).
- Rewriting archived changes or historical review records to the new tiers.
- Multi-user/team coordination features of any kind.

## Scale

**XL** (schema-surgery migration across most workflow capabilities +
concurrency machinery + spec consolidation). Under the B2 collapse this
change itself ships, XL maps to "M + full flag set"; it is gated under the
*current* 5-tier schema (M+ artifact set, gating-required code review,
worktree-required).
