<!-- authored: in-session -->
## Context

The opsx gate (`opsx_gate` subshell in `dot_local/bin/executable_opsx`) is a deterministic
field-reader: it derives required artifacts from Scale, runs manifest validations by exit
code, and reads sealed `Verdict`/`Completion Decision` fields from `code-review.md` /
`verify.md` with provenance + freshness checks. It performs **no** model call. The
openspec-loop skill drives the loop and delegates review judgments to blind subagents; the
pi `opsx-loop` extension is the pi kickoff adapter and owns stall detection.

The gap: mechanical green ≠ intent satisfied. This change adds a **semantic doneness judge**
whose verdict is produced upstream by a blind subagent, sealed into `doneness.md`, and read
by the gate exactly like `code-review.md`. It respects constitution II (canonical chezmoi
sources, deploy via chezmoi), V (no new dev-tool install; reuse `yq`/`sed`), IX (skill edits
→ multi-model adversarial code-review), and ADR-0006/0007 (goal extension untouched;
harness-neutral config/enforcement owns the rule, extension is a consumer).

## Goals / Non-Goals

**Goals:**
- Gate enforces intent-satisfaction without ever running a model inside the gate.
- Reuse the existing sealed-verdict + provenance + freshness machinery (`code-review.md`).
- Bound the loop under an unbounded budget via doneness-aware stall detection.
- Reuse the `review` role model; no new model role.

**Non-Goals:**
- A live per-turn LLM judge inside the loop (non-deterministic stop, per-turn cost).
- A separate numeric veto cap distinct from stall detection.
- Making doneness advisory / archive-only (it gates loop-stop).
- Changing mechanical gate checks, the `goal` extension, or the bash `opsx loop` driver's
  core judge contract.

## Decisions

### D1: Sealed doneness verdict, gate reads it (no model in gate)

**Choice:** The gate reads a `Doneness: satisfied | not` field from `doneness.md`; the LLM
judgment is produced upstream by a blind subagent. The gate performs no model call.

**Alternatives considered:**
- **Live in-loop LLM judge (goal-style).** Model call every `agent_end` deciding stop.
  Cons: non-deterministic stop condition, per-turn latency/cost, flip-flop between turns,
  self-judgment bias. Rejected in intent.
- **Gate spawns the judge on demand.** Puts a model inside the gate path → destroys
  reproducibility and violates the "gate stays deterministic" constraint. Rejected.

**Rationale:** Keeps the gate's reproducible exit-code decision logic intact while adding
the intent axis. Mirrors the proven `code-review.md` pattern; zero new enforcement shape.

**4-point test:** multiple approaches ✓; lasting ✓; reasonable disagreement ✓; constrains
future ✓ → **ADR candidate YES** (also reverses the prior "no LLM doneness judge" stance).

### D2: Dedicated `doneness.md` artifact + dedicated blind judge

**Choice:** A new skill-managed artifact `doneness.md` and an independent blind judge
subagent, distinct from `code-review.md` and its reviewer.

**Alternatives considered:**
- **Fold doneness into the code-review Verdict.** Leanest — no new artifact/field. Cons:
  collapses two orthogonal axes (is the *code* correct vs did we accomplish the *intent*)
  into one bit; the gate can't tell "code bad" from "intent unmet"; a reviewer optimizing
  for code correctness may under-weight intent coverage.
- **Separate `Doneness` field inside code-review.md.** Keeps axes separable but couples the
  judge's context and dispatch to the code reviewer.

**Rationale:** Intent-satisfaction and code-correctness are independent axes; a change can be
well-reviewed code that misses the intent. A dedicated artifact keeps the gate's per-axis
failure legible and lets the judge run with an intent-anchored baseline (not a diff-quality
baseline).

**4-point test:** multiple approaches ✓; lasting ✓; disagreement ✓; constrains future ✓ →
**ADR candidate YES**.

### D3: Doneness gates loop-stop (not archive-only)

**Choice:** Doneness is a required gate check at Scale ≥ M; the gate is not green — and the
loop does not stop — until the verdict is `satisfied`.

**Alternatives considered:**
- **Archive-only guard.** Loop stops at mechanical-green; doneness checked as an archive
  precondition. Safer under ∞ budget but lets the loop declare "done" while intent is unmet,
  defeating the point of an autonomous drive-to-*intent* loop.

**Rationale:** The whole value is that the loop converges on *intent*, not just mechanics.
The ∞-budget risk is handled by D4, not by demoting doneness.

**4-point test:** ✓✓✓✓ → **ADR candidate YES** (bundled with D1 in the ADR).

### D4: Doneness-aware stall detection is the sole backstop

**Choice:** Extend the existing stall detector: WHILE the only failing check is `doneness`
with a `not`/absent/unparseable verdict (classified by the extension parsing `doneness.md`
directly, NOT the gate's free-text message), "progress" is the judge's normalized gap set
**strictly shrinking against a running minimum** `min_gaps` (the smallest set seen since the
streak began) — a per-prior-eval comparison is defeatable by asymmetric oscillation
({a,b}→{a}→{a,b}→{a} would reset forever), so progress = proper subset of `min_gaps` with
fewer members, updating `min_gaps` on each reduction. Growth, equal-cardinality swap,
oscillation down-swing to a seen set, or reword → NOT progress → counter advances.
`min_gaps`+counter reset only when the failed-check-id set changes, the worktree changes, or
the gate goes green. Absent/unparseable `doneness.md` → empty-set sentinel, which SHALL NOT
count as progress and SHALL NOT overwrite `min_gaps` (only a NON-EMPTY proper-subset
reduction is progress), so a transient parse flake cannot manufacture a spurious reset
(round-3 DJ-2). A `satisfied`-but-**stale** failure is re-judged BEFORE the stall check
(fresh verdict resolves it) → ordinary content/HEAD signal. To keep the ∞-budget backstop
total, the orchestration NEVER seals a `degraded-single-model`-stamped `satisfied` adapterless
(round-3 DJ-1): the no-adapter path leaves `doneness.md` absent or seals `Doneness: not`, so
the adapterless Scale≥M state maps to the bounded gap-set/∅ signal and STALLS rather than
spinning on a re-reproducible degraded `satisfied` that a content/HEAD signal could not
bound.

**Alternatives considered:**
- **Separate numeric veto cap** (N re-judge attempts then defer). A second bounding
  mechanism to reason about; intent explicitly rejects it.
- **Keep the content/HEAD progress signal.** Under ∞ budget an agent thrashing files each
  turn changes the content hash → counter never trips → true infinite loop. Rejected — this
  is the load-bearing hole.

**Rationale:** Reuses the one stall mechanism; makes the progress signal *semantic* exactly
where a semantic judge can otherwise be gamed by churn.

**4-point test:** ✓✓✓✓ → **ADR candidate YES** (may be folded into the same ADR).

### D5: Reuse the `review` role model; no new role

**Choice:** The doneness judge resolves its model via `opsx models review`.

**Alternatives:** a dedicated `doneness` role — more config surface, more to keep in sync,
no demonstrated need. Rejected per intent.

**4-point test:** lasting? weak; disagreement? low → **ADR not warranted** (config reuse).

### D6: Scale-gated with `doneness_mode` waiver

**Choice:** Required at Scale ≥ M; `doneness_mode: waived` (with rationale) or Scale < M
skips it. Mirrors `validation_source_mode`.

**Alternatives:** always-on. Rejected — trivial changes shouldn't pay a judge dispatch.

**4-point test:** lasting? moderate; disagreement? low → **ADR not warranted** (mirrors an
existing, already-decided waiver pattern).

## How (implementation sketch)

- **`doneness.md` format** (skill-managed, gate-read fields):
  ```
  **Doneness:** satisfied            # or: not
  **Judge:** <review-role model id>  # ADAPTER-STAMPED reviewer-provenance
  **Review-Mode:** adversarial-single | degraded-single-model
  **Frozen-Intent SHA:** <sha256 of intent.md>
  **Diff Base SHA:** <base>
  **Reviewed Range:** <base>..<head>
  ## Gaps                            # present only when Doneness: not
  - <short stable gap phrase>
  ```
  The `**Judge:**` / `**Review-Mode:**` provenance is stamped by the subagent-dispatch
  adapter, NOT written in-band by the orchestrator or judge — mirroring adapter-stamped
  code-review provenance. This is a tripwire against accidental self-marking, NOT proof
  against a same-UID actor that bypasses dispatch AND forges the stamp (out of threat model,
  matching the live in-session authoring marker). A `degraded-single-model` review-mode (no
  adapter → inline) is treated by the gate as a failed check, never a pass. Harness-neutral
  guarantee: ENFORCEMENT persists adapterless (the gate still evaluates), but a green verdict
  is reachable only via a dispatch-capable harness or a rationaled `doneness_mode: waived` —
  manual production in an adapterless harness does NOT reach green.
- **Gate (`opsx_gate`):** after mechanical + verify + code-review checks pass, read
  `doneness_mode` and `scale` from review.md front-matter. WHILE `scale >= M` and
  `doneness_mode == required`: require `doneness.md`; parse `**Doneness:**` (must be
  `satisfied`); require the adapter-stamped provenance (`**Judge:**` + `**Review-Mode:**` ≠
  `degraded-single-model`); recompute and compare `sha256(intent.md) == **Frozen-Intent
  SHA:**` and the review.md immutable `**Diff Base SHA:**`; and validate
  `Reviewed Range == Diff Base SHA..<worktree HEAD>` (reuse the existing freshness helper
  used for code-review). `doneness_mode == waived` at Scale ≥ M requires a non-empty
  `doneness_waiver_rationale`, else `GATE-FAIL`. Any miss → `GATE-FAIL doneness 1 <reason>`.
  Doneness is emitted ONLY as the sole remaining failure (suppressed while any mechanical /
  verify / code-review check is still red), so the stall detector's `{doneness}`-only
  precondition holds. `doneness.md` is a mode-conditioned verdict, not a structural required
  artifact — its absence never short-circuits the cheap phase.
- **Extension (`helpers.ts`/`index.ts`):** add a pure `parseDonenessGaps(donenessMd)` →
  normalized `Set<string>` (absent/unparseable ⇒ empty-set sentinel). In `agent_end` stall
  logic, WHILE the parsed blocking failed-check set is exactly `{doneness}` AND the verdict
  is `not`, progress ⇒ gap set **strictly shrinks** (proper subset, fewer members) vs the
  prior evaluation; anything else (grow / swap / oscillate / reword / identical) ⇒ no
  progress → advance the counter. Mixed/other failures, or a stale/unprovenanced `satisfied`,
  keep the current content/HEAD token.
- **Skill (`openspec-loop/SKILL.md`):** add a doneness step — after mechanical gate checks
  pass and no fresh satisfied verdict exists, dispatch a blind subagent on the `review`
  model with baseline = frozen intent + `Diff Base..HEAD` diff + delta ACs; the subagent
  authors `doneness.md` (verdict + gaps + range), and the dispatch adapter stamps the
  provenance (`**Judge:**` + `**Review-Mode:**`). When no dispatch adapter is registered,
  the verdict is marked `degraded-single-model` (gate-fail) with a recorded notice that a
  green verdict needs a dispatch-capable harness or a rationaled waiver — enforcement (not
  green) is what survives adapter removal. Then re-run `opsx gate`.

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | Judge false-negative loops under ∞ budget | Medium | High | D4 doneness-aware stall (gap-set-shrink); identical gaps ⇒ stall halts + notifies |
| R2 | Judge false-positive seals `satisfied` on an unmet intent | Medium | Medium | Blind, scope-anchored charter; freshness re-judge on every new commit; provenance traceable |
| R3 | Gap-set parse brittle to `doneness.md` formatting drift | Medium | Medium | Fixed `## Gaps` + bullet format in the template; normalize (lowercase/collapse); absent/unparseable ⇒ treated as `not` (fail-safe, never permissive) |
| R4 | Existing Scale ≥ M changes now blocked (BREAKING) | High | Low | `doneness_mode: waived` escape with rationale; only applies to loop-driven Scale ≥ M |
| R5 | Judge dispatch cost each convergence attempt | Medium | Low | Dispatched only after mechanical green; freshness avoids re-judging an unchanged HEAD |

## Migration Plan

- Additive: new artifact + one front-matter field + gate check gated on `doneness_mode`.
- Existing archived changes are untouched (deltas apply to live specs only).
- In-flight Scale ≥ M changes gain the requirement on their next gate run; `doneness_mode:
  waived` is the documented escape.
- Rollback: set `doneness_mode: waived` (or revert the gate block) — the field read is the
  only new gate dependency.

## Open Questions

- (none blocking) — model-selection sub-choice resolved: reuse `review` role (D5).
