# opsx Simplicity Audit

**Auditor:** independent, fresh-context. **Date:** 2026-07-03.
**Repo:** `/Users/cartwmic/.local/share/chezmoi`.
**Judged against:** the 4-point intent (explore → frozen intent → autonomous propose/apply/verify behind a deterministic gate with blind reviews → human keeps archive/deploy) under the solo-dev / one-machine / 2-3 concurrent-loops assumptions.

Ground rule I held myself to: I only recommend cutting where the file evidence shows the complexity does not pay under those assumptions, and I checked the ADR history (`adr/ADR-0001…0023`) before calling anything speculative. Several mechanisms are scarred — they exist because a real failure happened (re-prompt treadmills: ADR-0017; machine re-prompt misread as archive authorization: ADR-0021; split-brain locator red-loop: ADR-0023). Those get steelmanned, not cut.

---

## Complexity Inventory

| # | Mechanism | Where | Failure it prevents | Real likelihood (solo, 1-3 loops, 1 machine) | Blast radius if it fires unprevented |
|---|---|---|---|---|---|
| 1 | 5 Scale tiers XS/S/M/L/XL | schema `README.md` Scale table; gate `executable_opsx:529-531` | Ceremony mismatched to change size | N/A (control knob) | Over/under-review; wrong artifact set required |
| 2 | 9 required artifacts at M+ (review, intent, proposal, specs, clarify, design, analyze, tasks, plan) | gate `executable_opsx:531` | Under-specified change; agent drift on a big feature | Medium for genuinely large changes; **low for the "typical feature" M is defined as** | Agent builds wrong thing; caught later by review/gate anyway |
| 3 | Clarify phase (blind, 3-pass) | schema README; `opsx-spec-quality` | Ambiguous/contradictory specs before impl | Medium at L/XL, low at M | Ambiguity reaches impl, surfaces at code-review/doneness |
| 4 | Analyze phase (blind, 7-check cross-artifact lint) | schema README; `opsx-loop-orchestration` §"Pre Apply Surface Audit Dispatch" | Cross-artifact inconsistency | Low-medium | Inconsistency caught downstream |
| 5 | 2-model multi-round adversarial code review + severity floor + round ledger | `opsx-post-impl-review`, `opsx-review-convergence`; gate `executable_opsx:709-724` | Agent ships buggy/self-serving diff | **High-value** — this is the core antidote to agent lying | Bad code archived; the one gate humans can't easily re-derive |
| 6 | Trajectory stop on P0+P1 counts + `review_max_rounds`=5 | ADR-0017; `opsx-review-convergence:62` | Unbounded review treadmill (real: session 019f1ed4, 6-8 rounds + 5-model blitz) | **Observed real** | Infinite review spend, agent thrash |
| 7 | Single late disclosure round | ADR-0018; `opsx-review-convergence:82` | Two blind reviewers deadlock split forever | Low-medium | One wasted deadlock, manual intervention |
| 8 | Doneness judge (blind, intent-satisfaction, sole-remaining-failure backstop) | ADR-0012; `opsx-doneness-judge`; gate `executable_opsx:820-852` | Mechanically-green-but-intent-unmet ("treadmilled to green") | Medium | Change archived that doesn't satisfy intent |
| 9 | verify.md AC↔test mapping gate | schema README; gate `executable_opsx:695-701` | Claimed-done without tests mapping to ACs | Medium | Untested ACs archived |
| 10 | Verdict freshness / provenance binding (Diff Base SHA, Reviewed Range, anti-self-forge) | gate `executable_opsx:727-763` | Stale verdict passing after code changed; agent forging a verdict | Medium — agents do re-touch code post-review | Stale/forged green |
| 11 | Turn budget (`loop_max_iterations`, S~20/M~40/L~80) | README; `executable_opsx:893-905`; `index.ts` parseLoopBudget | Runaway loop spend | Medium | Wasted turns; bounded |
| 12 | Stall detection STALL_LIMIT=3 (same failed-check set + no progress) | `index.ts:39,681-712` | Loop re-prompting on a stuck failure | Medium-high | Wasted turns until budget |
| 13 | Doneness gap-set ratchet (special stall variant) | `index.ts:684-702`; helpers `donenessRatchet` | File churn that closes no judged gap looping forever | Low-medium | Wasted turns; bounded by budget |
| 14 | loop_hold landing channel (front-matter, human-only clear) | ADR-0022; `index.ts:625-647` | Agent can't halt loop → 3 wasted stall turns; machine re-prompt misread as archive OK | **Observed real** (ADR-0021/0022, 2026-07-03) | Loop self-continues past a landing; or self-archives |
| 15 | Explicit-resume-only latch (goal kickoff never latches existing change) | ADR-0021; `index.ts` distill flow | False-latch on a green bystander; machine re-prompt = archive auth | **Observed real** | Wrong change driven / archived |
| 16 | Distill one-shot human confirm (ADR-0014) | `index.ts:604-613` | Agent authors the baseline it is later judged against | **High-value** (blind-review integrity) | Collapses the whole blind-review guarantee |
| 17 | Worktree-required default all scales + runtime-owned lifecycle | ADR-0008/0015; `executable_opsx:949-1039` | Loop blast radius on main tree | Medium | Half-finished change dirties main working tree |
| 18 | Locator publication to integration checkout + single-sourced convention fallback | ADR-0023; `executable_opsx` artifact-source resolution `~455-475` | Gate-from-main vs gate-from-worktree split-brain red-loop | **Observed real** (2026-07-03) | Correct worktree red-loops forever |
| 19 | Role-model config (4 roles, 5-layer resolution) + env export + clear-before-set | `opsx-model-config`; `executable_opsx` opsx_models; helpers `OPSX_MODEL_ENV_KEYS` | Wrong/leaked model per role across loops | Low-medium | Reviewer runs on cheap model; prior loop's model leaks |
| 20 | Fail-closed mode validation (unknown mode value → hard fail) | `executable_opsx:707-720` (validate_mode) | Typo silently disables enforcement | Medium | Enforcement silently off |
| 21 | 14 spec capabilities (12 opsx + `pi-model-visibility`, `pi-ntfy-notify`) | `openspec/specs/*` | — | N/A | Self-referential spec surface / maintenance load |
| — | **PLANNED, not yet built (cheapest to cut now):** | | | | |
| P1 | Branch-first authoring (all artifacts on `opsx/<change>`, main gets intent+control only) | active explore | Merge collisions in review.md across concurrent loops | Low-medium | review.md merge conflict on archive |
| P2 | `.opsx-control` file on main (Worktree Path, Diff Base, loop_hold) replacing review.md fields | active explore | Two-copy ambiguity / merge collision | Low | Same as P1 |
| P3 | Per-change advisory flock (gate + worktree ensure + loop armament) + PID stale-heal | active explore | Two sessions driving the SAME change | **Low** (solo dev rarely double-drives one change; ADR-0021/0022 already make arming explicit + human-only) | Two loops fight over one change dir |
| P4 | Distill nonce (parallel distills not cross-detecting new change dirs) | active explore | Loop A adopts loop B's new change | Low (mtime tiebreak already picks one) | Wrong change adopted at distill |
| P5 | land-base-current check (merge-base(branch,main)==main HEAD before land) | active explore | Landing a change built on a now-stale main | Medium **under concurrency** (another loop's archive moves main) | Stale-base merge; forces rebase+re-review |
| P6 | `git commit -- <paths>` discipline all main-side commits | active explore | Index-sweep committing unrelated staged files | Medium | Unrelated files committed to main |
| P7 | Duplicate-ADR-number scan at archive | active explore | Two changes claim same ADR-NNNN | Low-medium under concurrency | ADR number collision |
| P8 | Worktree ensure refuse/reuse rules | ADR-0023; partially built `executable_opsx:1006-1024` | Reusing a mismatched/dirty worktree | Medium | Impl against wrong branch/base |

---

## Verdicts

| Mechanism | Verdict | Why |
|---|---|---|
| 1 — 5 Scale tiers | **SIMPLIFY → 3** | The gate only distinguishes **three** buckets: `XS`, `S`, and `M\|L\|XL` collapse to one required-artifact set (`executable_opsx:529-531`). L and XL differ only in *skill-managed* extras (adr, retrospective, adversarial-on-analyze) that the deterministic gate never enforces. Five labels for three gate-observable behaviors is cognitive overhead. Collapse to XS / S / M, and make "adversarial + ADR + retrospective" an explicit mode flag rather than a hidden consequence of picking L vs M. |
| 2 — 9 required artifacts at M | **SIMPLIFY** | For the tier defined as "typical feature, single capability," requiring proposal+specs+clarify+design+analyze+tasks+plan (7 authored docs) *plus* intent+review is heavy. clarify and design overlap for single-capability work; analyze is a lint over documents that mostly re-checks what clarify already covered. Recommend: at M, fold clarify into the proposal's open-questions section and make design optional (required only when a decision passes the 4-point ADR test). Keep the full 9 at L/XL. Protection lost is low because code-review + doneness catch substantive gaps downstream. |
| 3 — Clarify (blind) | **KEEP at L/XL, DEFER at M** | Real value on ambiguous large specs; at M it is a third blind pass on top of analyze + eventual code-review. |
| 4 — Analyze (blind) | **SIMPLIFY** | 7-check cross-artifact lint is largely mechanizable; the parts that aren't (EARS quality) are already flagged "human-triage." Reduce to the deterministic checks and drop the separate blind dispatch at M. |
| 5 — 2-model adversarial code review | **KEEP** | This is the load-bearing antidote to agent lying over the actual diff. Do not weaken. The *only* review layer the human genuinely cannot cheaply re-derive. |
| 6 — Trajectory stop + budget | **KEEP** | Scar tissue from a real 6-8-round treadmill (ADR-0017). Deterministic, model-free, cheap. Exactly the kind of machinery the intent asks for. |
| 7 — Disclosure round | **KEEP** | Bounded (exactly one, ADR-0018), only fires on persistent split. Cheap insurance against deadlock. |
| 8 — Doneness judge | **SIMPLIFY (scope to L/XL) / KEEP at that scope** | Conceptually distinct from code-review (intent-satisfaction vs diff-quality) and it guards the specific "treadmilled to mechanical green but intent unmet" failure. But at M it is the **5th** blind judgment layer (clarify, analyze, code-review×2-model, disclosure, doneness). Recommend: doneness required at L/XL, *folded into the code-review dispatch* at M (same reviewer answers "does this satisfy intent.md?" as a final section). Keeps the guard, drops one dispatch + one artifact + one freshness-binding path at the most common tier. |
| 9 — verify.md AC↔test gate | **KEEP** | Cheap, mechanical, catches "done" claims with no test mapping. High value per line. |
| 10 — Verdict freshness/provenance | **KEEP** | Directly defends against the agent re-touching code after a green verdict and against forged verdicts — both real agent behaviors. Deterministic. |
| 11 — Turn budget | **KEEP** | Hard ceiling; necessary for a headless fallback with no stall guard (`executable_opsx:884-891`). |
| 12 — Stall detection | **KEEP** | Progress-based early stop; distinct role from the budget (early vs ceiling). |
| 13 — Doneness gap-set ratchet | **SIMPLIFY** | This is a special-cased second stall algorithm bolted onto the first (`index.ts:684-702`) purely because the ordinary content/HEAD progress signal is wrong while the sole failure is `doneness`. If doneness folds into code-review at M (verdict 8), the ratchet's reason to exist shrinks to L/XL only. It is the single most intricate branch in the extension for a narrow case. |
| 14 — loop_hold | **KEEP** | Scar tissue (ADR-0022): agents had no invokable stop, and a machine re-prompt was misread as archive authorization. Front-matter channel + human-only clear is the minimal correct fix. |
| 15 — Explicit-resume-only latch | **KEEP** | ADR-0021 shows green-vs-goal matching is genuinely undecidable by a model-free extension; refusing to latch is the *simplest* safe rule, not extra machinery. |
| 16 — Distill one-shot confirm | **KEEP** | Non-negotiable: without it the agent authors the baseline it is later judged against, collapsing blind-review integrity (matches the prior audit's P1). |
| 17 — Worktree-required all scales | **SIMPLIFY** | Honoring the stated "default all sizes," but the plan's own cost note concedes XS-in-a-worktree is "ceremony-heavy." Auto-downgrade XS/S to `same-tree` unless overridden; keep worktree-required at M+. Blast radius of a same-tree XS typo fix is trivially recoverable. |
| 18 — Locator publication + single-source fallback | **KEEP** | ADR-0023 scar; the divergence class is real and the fix is single-sourced (`opsx_wt_convention_path` derived once). Don't touch. |
| 19 — Role-model config | **SIMPLIFY** | 4 roles × 5 resolution layers (env > front-matter > project yaml > user yaml > default) is a lot for one human. In practice the human sets review-models and maybe impl once. Keep the resolver; consider dropping the *project* yaml layer (redundant with front-matter for a solo dev whose project == the same repo). Low urgency. |
| 20 — Fail-closed mode validation | **KEEP** | One `case` statement; prevents a silent enforcement-off typo. Textbook cheap safety. |
| 21 — 14 capabilities | **SIMPLIFY → ~7-8** | `pi-model-visibility` + `pi-ntfy-notify` are unrelated pi features, not workflow tooling — exclude them from the "own-tooling" count (it's really 12). Of the 12: `goal-loop`(13 reqs) is the generic engine the opsx loop no longer even uses as its primary path (README: opsx-loop extension is primary, goal ext is "alternative"). `opsx-loop-kickoff`(12 reqs/50 scenarios) + `opsx-loop-orchestration`(9 reqs) both describe "the loop" from extension vs harness-neutral angles — mergeable. `opsx-review-convergence`(11 reqs) + `opsx-post-impl-review`(8 reqs) share the same round-ledger/trajectory/disclosure machinery — mergeable into one "adversarial-review" capability (ADR-0016 already consolidated once). Target ~7-8 opsx capabilities. |
| P1/P2 — branch-first + `.opsx-control` | **DEFER (lean CUT)** | This re-architects fields that ADR-0022 (loop_hold on integration checkout) and ADR-0023 (locator on integration branch) *just landed on 2026-07-03*. Those ADRs deliberately single-sourced to the integration checkout to kill split-brain. Moving them into a new file one day later is churn against fresh, scarred decisions. The merge-collision it prevents is a review.md conflict on archive — low frequency, low blast radius (a 30-second manual resolve) for a solo dev. Don't build until a real collision is observed. |
| P3 — per-change flock (3 scopes) | **CUT (as spec'd) → SIMPLIFY to a read-only registry** | flock is *per-change*; two loops on *different* changes never contend on it, so it only guards two sessions driving the *same* change — which ADR-0021/0022 already made an explicit, human-only arming action. The probability a solo dev double-arms one change is low, and PID-based stale-lock healing is itself a new failure surface (stale lock wedges a legitimate loop). What the concurrency ambition actually needs isn't mutual exclusion — it's **visibility** (see Under-investments). Replace flock with a read-only "which change is armed where" registry. |
| P4 — distill nonce | **CUT** | `detectNewChange` already deterministically picks the most-recently-written intent.md (`index.ts` mtime sort). Two *simultaneous* distills in two sessions is a rare human action; the worst case (adopting the wrong new change) is caught at the one-shot human confirm (mechanism 16) before any loop arms. Nonce guards a near-zero-probability window that a human already gates. |
| P5 — land-base-current | **KEEP (this one earns concurrency's keep)** | Unlike P3/P4, this is the concurrency mechanism that pays: with 2-3 loops, one loop archiving genuinely moves main under the others, and merging a change reviewed against a stale base is a real correctness gap. The "rebase → staleness-fires fresh review" cost is the *correct* behavior. Cheapest real protection in the planned set. |
| P6 — `git commit -- <paths>` | **KEEP** | One-line discipline, prevents the index-sweep class (agent stages something, a workflow commit sweeps it onto main). Cheap, real. |
| P7 — duplicate-ADR scan at archive | **KEEP (small)** | Concurrency makes ADR-number collision plausible; a grep at archive is trivial. |
| P8 — worktree refuse/reuse | **KEEP** | Already partly built and scarred (ADR-0023 reuse rules); refusing a mismatched worktree loudly is correct. |

---

## Ranked Simplifications

Ranked by (complexity deleted) / (protection lost). Top of list = best trade.

1. **Cut the distill nonce (P4) and the per-change flock (P3) from the plan; do not build them.**
   *Deletes:* a whole locking subsystem (3 lock scopes, PID stale-heal, a new class of "stale lock wedged my loop" failures) + a nonce-write/detect handshake.
   *Protection lost:* prevention of two sessions double-driving one change / cross-adopting a distill.
   *Severity under solo assumption:* **very low** — both are already gated by explicit human-only arming (ADR-0021/0022) and the one-shot distill confirm (mechanism 16). You'd be adding machinery to defend a window a human already stands in.

2. **Defer branch-first authoring + `.opsx-control` (P1/P2).**
   *Deletes:* a repo-layout re-architecture and a second source-of-truth file.
   *Protection lost:* avoidance of occasional review.md merge conflicts across concurrent loops.
   *Severity:* **low** — a merge conflict on one markdown file at archive is a seconds-long manual fix, and building this now churns ADR-0022/0023 which landed yesterday specifically to single-source those fields.

3. **Collapse Scale to 3 tiers (XS/S/M) and make adversarial/ADR/retrospective an explicit flag.**
   *Deletes:* two tier labels and the illusion that L/XL are gate-distinct from M (they aren't: `executable_opsx:531`).
   *Protection lost:* none at the gate — the extras become an opt-in flag instead of a hidden consequence of a label.
   *Severity:* **none** (pure clarity win); mild migration cost in schema docs.

4. **Fold doneness into the code-review dispatch at M (keep standalone doneness at L/XL); this also retires the doneness gap-set ratchet at M.**
   *Deletes:* one blind dispatch, one artifact (doneness.md), one freshness/provenance-binding path, and the most intricate branch in the extension (the ratchet, `index.ts:684-702`) for the common tier.
   *Protection lost:* an *independent* intent-satisfaction judge separate from the diff reviewer, at M only.
   *Severity:* **low-medium** — at M the same blind reviewer answering "does this diff satisfy intent.md?" as a final section retains ~90% of the guard; full independence stays where stakes justify it (L/XL).

5. **Reduce pre-impl artifacts at M: fold clarify into proposal open-questions, make design decision-gated, thin analyze to its deterministic checks.**
   *Deletes:* up to 2 required artifacts + 1-2 blind dispatches at the most common tier.
   *Protection lost:* early ambiguity/consistency catches before impl.
   *Severity:* **low** — code-review + verify + (folded) doneness catch substantive gaps; you pay a little more rework risk on the occasional M that needed the design doc.

6. **Consolidate the spec surface: 14 → ~7-8 capabilities** (merge kickoff+orchestration; merge review-convergence+post-impl-review; drop `goal-loop` from the opsx count or retire it if the goal-ext path is truly deprecated; exclude the two unrelated `pi-*` specs).
   *Deletes:* ~4-5 capability files and their scenario duplication (kickoff alone is 50 scenarios).
   *Protection lost:* none functional — this is documentation topology.
   *Severity:* **none**; real maintenance-load reduction.

7. **Auto-downgrade XS/S to `same-tree` unless overridden.**
   *Deletes:* worktree create/merge/cleanup ceremony for trivial fixes.
   *Protection lost:* blast-radius isolation for XS/S.
   *Severity:* **very low** — an XS typo fix on main is trivially revertible; the plan's own cost note already flags this.

8. **Drop the project-layer models yaml (keep env > front-matter > user > default).**
   *Deletes:* one of five resolution layers.
   *Protection lost:* per-project model override distinct from per-change front-matter.
   *Severity:* **negligible** for a solo dev whose project is the same dotfiles repo.

Lower-value / do-not-cut: everything in the KEEP column, especially code-review (5), trajectory stop (6), loop_hold (14), locator single-sourcing (18), and land-base-current (P5).

---

## Under-investments (what matters more than most of the above)

1. **Cross-session loop observability — the biggest gap given the parallelism ambition.** `/opsx-loop status` reports only the *current* pi session's in-memory `loop` object (`index.ts:437-461`). With 2-3 loops in 2-3 pi sessions — the stated real requirement — there is **no way to see all active loops at once**: which changes are armed, in which session/worktree, at what turn, holding or stalled. The inventory helper (`listIntentChanges`) shows changes with intent + front-matter status but not "a loop is live on this right now, elsewhere." The planned flock (P3) tries to *prevent* collisions blindly; what the human actually needs is to *see* the fleet. **Recommend:** a read-only `opsx status` that scans `openspec/changes/*` and prints per change: gate red/green summary, Scale, worktree path + health, loop_hold state, Diff Base vs main HEAD (stale?). Deterministic, model-free, no lock. This subsumes most of what P3 was reaching for and directly serves the concurrency goal.

2. **Recovery ergonomics after a stall/budget stop.** Today a stall says "intervene manually" and preserves the worktree (`index.ts:706-712`) — good — but there's no single command that tells the human *why* it's stuck and *what to do*: the last gate report, the failing check, the worktree path, whether it's a doneness gap set. The information exists across the front-matter, the gate output, and in-memory state; it isn't collected into one recovery view. The aggregate `opsx status` above should include the last gate failure line per red change.

3. **Staleness visibility across the fleet, not just at land.** P5 (land-base-current) correctly *blocks* a stale-base land, but the human only discovers staleness at archive time. With concurrent loops, surfacing "this change's Diff Base is N commits behind main" continuously (in the status view) lets the human rebase early instead of eating a full re-review at the finish line.

4. **A documented deprecation status for the `goal-loop` / goal-extension path.** The README calls the goal extension the "alternative" and the opsx-loop extension "primary," yet `goal-loop` remains a full 13-requirement capability. If the goal path is effectively dead, saying so removes a whole spec's worth of cognitive load; if it's a real fallback, the relationship should be one sentence, not two parallel specs.

---

## Bottom Line

**Partially over-complicated — and unevenly.** The *deterministic-gate + blind-review* spine is proportionate and mostly scarred-into-existence: the gate, trajectory stop, loop_hold, locator single-sourcing, verdict freshness, and the distill confirm all trace to real observed failures in the ADRs and earn their keep for a solo dev who (correctly) does not trust the agent. Cutting those would be demolition, not simplification. Where the design has drifted heavy is (a) **at the M tier**, which stacks five blind judgment layers (clarify, analyze, 2-model code review, disclosure, doneness) and nine required documents on the change type explicitly defined as "typical feature," and (b) **in the still-unbuilt concurrency plan**, where flock + distill nonce + branch-first + `.opsx-control` add locking and re-architecture to defend low-probability same-change collisions that explicit human-only arming already gates — while the concurrency feature the human actually needs, *cross-session visibility*, is missing entirely.

Top 3 moves: **(1)** don't build the flock (P3) or distill nonce (P4), and defer branch-first/`.opsx-control` (P1/P2) — spend that budget on a read-only `opsx status` fleet view instead; **(2)** thin the M tier — fold doneness into code-review and clarify into the proposal at M, keeping the full stack at L/XL, which also retires the ratchet's common-case complexity; **(3)** collapse Scale to 3 gate-real tiers and consolidate 14 specs toward ~7-8, since the gate only ever distinguishes XS/S/M+ anyway. Keep the code review, keep land-base-current, keep every ADR-scarred guard.

SIMPLICITY-AUDIT: mixed
