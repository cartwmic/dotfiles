# opsx-superpowers — Worktree-default + Drive-to-completion Loop + Post-impl Adversarial Review

**Status:** Exploration (pre-proposal)
**Date:** 2026-06-19
**Schema touched:** `dot_local/share/openspec/schemas/opsx-superpowers/`

## The unifying idea

The three requested updates are not independent features — they compose into a
single autonomous, resumable lifecycle:

```
explore (human ideation, precedes loop)
  │
  ▼
┌─────────────────── opsx drive loop (invoke repeatedly) ───────────────────┐
│  propose ─► pre-impl review gate ─► apply (in worktree) ─► post-impl       │
│            (clarify/analyze +        self-heal until        review gate     │
│             adversarial if L)        verify green          (adversarial     │
│                                                             over the DIFF)  │
│                                              │                   │          │
│                                              └──── fix ◄─────────┘          │
│                                                                            │
│                                                 ─► archive (merge worktree, │
│                                                     sync specs, ADR/retro)  │
└────────────────────────────────────────────────────────────────────────────┘
```

- **Worktree** isolates the whole change (your answer: default for all sizes).
- **Post-impl review** reviews the actual diff inside that worktree, gating archive.
- **Loop** is the macro driver that advances the change through every stage and
  re-runs the two review gates until an objective judge says "done" — reusing the
  `goal` extension as the loop engine.

---

## Update 1 — Worktree default for all sizes

### Today
`Worktree Mode: same-tree` is the default. Apply already does pre-flight commit +
Worktree Base SHA capture when `worktree-*` is selected. Hook
`file-isolation-via-worktree` → `pi-subagents worktree:true` or raw `git worktree`.
No create/merge/cleanup *lifecycle* — worktree is a per-apply-session concern only.

### Proposed
Flip the default and own the full lifecycle.

| Aspect | Change |
|---|---|
| Default mode | `Worktree Mode` default `same-tree` → **`worktree-required`** (applies to XS/S too, since those Scales "assume defaults"). `same-tree` remains an explicit opt-out. |
| Branch | `opsx/<change-name>` created off the integration branch at loop/apply start. |
| Location | `<repo>/../.opsx-worktrees/<change-name>` (sibling, outside the tree; avoids `.gitignore` noise). Decision needed — see Open Questions. |
| Create | At **apply** start (today's pre-flight commit step), or earlier at **propose** start if we want artifacts authored in isolation too (heavier). Recommend: create at apply, artifacts authored in main tree, committed pre-flight, present in both checkouts. |
| Base SHA | Already captured into `review.md`. Unchanged. |
| Merge | At **archive**, gated on verify green + code-review pass: merge `opsx/<change-name>` → integration branch (squash) **or** open PR (repo uses PRs to `main`). Decision needed. |
| Cleanup | `git worktree remove` + branch delete after successful merge/archive. |

### Cost note
XS (typo fix) in a worktree is ceremony-heavy. Honoring "default for all sizes"
as requested, but `same-tree` stays one keystroke away for trivial fixes. Could
add a heuristic: XS auto-downgrades to `same-tree` unless overridden. Flagged as
an Open Question.

### Files touched
- `templates/review.md` — default value + Manual Adjustments guidance.
- `schema.yaml` review artifact instruction — change documented default.
- `schema.yaml` apply instruction — worktree creation already documented; add
  branch-naming + location convention.
- `references/opsx-superpowers-mode.md` (apply + archive) — add merge/cleanup steps.
- `capability-hooks.md` — tighten `file-isolation-via-worktree` (already maps right).

---

## Update 2 — Drive-to-completion loop (the big one)

### What you do today
You manually set the `goal` extension's completion condition to something like
"drive change X through propose→apply→archive with reviews," and the goal-loop's
worker/judge cycle grinds until met or the 25-turn budget exhausts. ADR-0002
already gives the loop a **separate judge model** so validation is objective.

### What you want
That, but **codified and repeatably invocable** as a first-class part of the
openspec workflow — not hand-written each time.

### Proposed: reuse the engine, standardize the directive + predicate

Do **not** build a new loop engine. The `goal` extension already provides:
worker turns, a separate judge, per-turn evaluation, turn budget, interrupt
handling, status indicator. Add two things on top:

**(a) New skill `openspec-loop`** (canonical worker directive)
- Detects current stage from `openspec status --change <name> --json` + file
  presence (which artifacts exist, tasks checked, verify.md / code-review.md
  verdicts, archived?).
- Advances exactly one stage (or one task) per invocation, then yields.
- Idempotent / resumable: re-invoking always resumes from the current stage.
  This is the key property that makes "invoke repeatedly" work.
- Stages: `propose → pre-impl-review → apply → post-impl-review → archive`.

**(b) Canonical completion predicate** (what the judge evaluates)
Objective, transcript/repo-checkable:
1. All required artifacts (per declared Scale) report `done`.
2. Pre-impl gate clean: `analyze.md` has no unresolved blockers; if Scale ≥ L,
   `review.md` Review Status = `resolved`.
3. All `tasks.md` checkboxes `[x]`.
4. `verify.md` Completion Decision = **green**.
5. `code-review.md` Verdict = **pass** (Update 3).
6. Change moved to `openspec/changes/archive/`.

When all 6 true → judge returns met → loop stops, notifies "change archived."

**(c) Invocation surface**
- `/opsx-loop <change>` slash command → sets the goal-loop condition to the
  canonical predicate for `<change>` and kicks the first worker turn.
- The worker turn's directive = "invoke `openspec-loop` skill for `<change>`."
- Budget: 25 is likely too low for a full lifecycle. Make per-loop budget
  configurable (goal extension already reads config + env override); document a
  recommended budget by Scale (e.g., S=15, M=30, L=60).

### Why this shape
- Zero new loop machinery; leans on a battle-tested extension you already maintain.
- Judge stays a separate model (ADR-0002) → objective validation, no worker
  marking its own homework.
- Resumability falls out of stage-detection, so partial progress + interrupts +
  re-invocation all just work.

### Decisions needed
- New skill vs. pure goal-condition preset (skill recommended — gives stage
  detection a home). See Open Questions.
- Does the loop ever pause for human input mid-flight (e.g., clarify blockers,
  adversarial 🔴-tier decisions)? Tension: full autonomy vs. owner checkpoints.
  The `adversarial-review-cycle` skill has owner checkpoints by design (Step 6).

### Files touched
- New `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`
  (+ symlinked to all harnesses per Constitution II).
- New `.claude/commands/opsx/loop.md` (slash command).
- `schema.yaml` — document the loop as the recommended driver (prose, not a new
  artifact; the loop orchestrates existing artifacts).
- `README.md` — add loop to the capability table + a "Driving a change" section.
- Possibly `dot_pi/agent/extensions/goal/create_config.json` — recommended budget.

---

## Update 3 — Post-implementation adversarial review (new gating artifact)

### Today
`adversarial-review-cycle` fires at the **analyze** artifact (Scale ≥ L) — but
that reviews **plan artifacts before execution**. `retrospective.md` is
learning-capture, not code review. Nothing adversarially reviews the **actual
implemented diff**.

### Proposed: `code-review.md`, skill-managed + gating
Mirror the `verify.md` / `retrospective.md` pattern: template lives in the
schema, NOT declared in `schema.yaml artifacts:` (same existence-only-isComplete
rationale), produced by the skill at the right lifecycle moment.

| Aspect | Design |
|---|---|
| Target | `git diff <worktree-base-sha>..HEAD` — the real code, not the plan. |
| Engine | `adversarial-review-cycle`: blind multi-model, autonomous loop (its Steps 1–5) until P0+P1 convergent. |
| Sub-skill | `review-plans` is plan-oriented. Post-impl review needs a **diff/code** lens — either a new `review-diff` companion sub-skill or generalize the reviewer prompt. **Design tension — see below.** |
| Timing | After apply yields `verify.md` green, before archive. Findings feed the apply self-heal loop (review → fix → re-verify → re-review). |
| Gating | New mode `Code Review Mode: none \| advisory \| gating-required`. Default **gating-required** at M+; advisory at S; none at XS. Archive HARD-GATES on Verdict = pass when gating-required. |
| Template | header (base SHA, diff scope, models), round tracker, convergent findings, applied-fixes log, residual risks, **Verdict: pass \| fail**. |

### Design tensions to resolve
1. **`adversarial-review-cycle` is marked "User-invoked only. Do not
   auto-select."** Having the schema/loop auto-invoke it contradicts that. Two
   outs: (a) treat the loop invocation as a transitive user invocation (the user
   ran `/opsx-loop`), documenting code-review as an explicit invocation path; or
   (b) fork a leaner post-impl-review variant that's allowed to auto-fire.
   Recommend (a) + a one-line description tweak.
2. **`review-plans` vs reviewing a diff.** The reviewer sub-skill assumes plan
   artifacts. Reviewing code needs different heuristics (correctness, security,
   regressions, test coverage of ACs). Likely need `review-diff` (or
   `review-implementation`) as a sibling skill.
3. **Constitution Principle IX** already mandates adversarial review for skill
   *edits* at Scale ≥ M — but that's the *pre-impl* analyze path. This new
   artifact is the *post-impl* complement. IX may need extending, or a new
   principle, so the constitution reflects both gates.

### Files touched
- New `templates/code-review.md` in the schema.
- `templates/review.md` + `schema.yaml` review instruction — add `Code Review
  Mode` to the switchboard.
- `capability-hooks.md` — new/parameterized `adversarial-review` (post-impl) hook.
- `references/opsx-superpowers-mode.md` (apply) — produce code-review.md after
  verify green; (archive) — HARD-GATE on Verdict when gating-required.
- New `review-diff` sub-skill (if we go that route).
- `README.md` — artifact table + Scale-tier table updates.
- `openspec/constitution.md` — possibly extend Principle IX.

---

## Scale interaction (proposed defaults after all three updates)

| Scale | Worktree | Loop | Pre-impl adversarial | Post-impl code-review |
|---|---|---|---|---|
| XS | required (or auto-downgrade?) | optional | — | none |
| S | required | recommended | — | advisory |
| M | required | recommended | — | **gating-required** |
| L | required | recommended | **yes (analyze)** | **gating-required** |
| XL | required | recommended | **yes (analyze)** | **gating-required** |

---

## Open questions (need owner calls before proposal)

1. **Worktree location** — sibling `../.opsx-worktrees/<name>` vs inside
   `.git/`? Sibling is simpler to inspect; `.git/` avoids any chance of stray
   tracking.
2. **Merge strategy at archive** — squash-merge to integration branch directly,
   or open a PR to `main`? (Repo convention is PRs to `main`.)
3. **XS in a worktree** — honor literally, or auto-downgrade XS to `same-tree`
   with override? You said "default for all sizes" — confirm XS is included.
4. **Loop autonomy vs checkpoints** — fully autonomous to archive, or pause at
   clarify blockers and adversarial 🔴-tier decisions? Affects whether the loop
   is truly fire-and-forget.
5. **Loop realization** — new `openspec-loop` skill (recommended) vs a documented
   goal-condition preset only?
6. **Post-impl reviewer** — new `review-diff` sub-skill vs generalize
   `review-plans`?
7. **`adversarial-review-cycle` "user-invoked only"** — relax description to
   permit loop invocation, or fork a post-impl variant?
8. **Loop budget by Scale** — confirm recommended turn budgets (S=15/M=30/L=60?).

## Suggested next step

Formalize as an opsx-superpowers change (this repo dogfoods the schema). Scale
**L** (cross-capability: schema + skills + extension config + constitution),
which auto-triggers pre-impl `adversarial-review-cycle` per Principle IX — fitting,
since this change edits existing skills.
