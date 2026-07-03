<!-- authored: in-session -->

## Why

The gating review cycle in the opsx loop has no stop condition, no convergence
tracking, no split-verdict protocol, and an open-ended reviewer verdict
contract, so review rounds can run unbounded (evidence: session 019f1ed4,
2026-07-02 — ~18-20 reviewer dispatches, 6-8 gating rounds plus an ad-hoc
5-model "convergence blitz" over ~4.5h for a pre-enumerated Scale-L scope).
Every fix commit moves HEAD, invalidates the verdict (freshness rule), and
re-opens an unbounded fresh review; the orchestrator can neither justify
stopping nor resolve a PASS/FAIL reviewer split. Constitution IX makes
multi-model gating review mandatory for skill edits, so the treadmill is a
structural cost on every such change.

## What Changes

- Add a **baseline-bounded verdict contract** for gating reviewers
  (code-review and analyze): FAIL only on frozen-baseline violation
  (intent/ACs/design/constitution/domain) or objective correctness/security
  defect; taste/style/beyond-scope demands are advisory and cannot gate.
- Add a **severity floor + calibration rubric**: `Verdict: pass` ⟺ no open
  P0/P1; the reviewer dispatch prompt embeds a P0-P3 rubric with a single
  declared severity lens.
- Add **finding routing**: in-scope blocking / in-scope advisory /
  out-of-scope → a new `follow-ups.md` artifact (template) that archive
  surfaces as explore input for a successor change.
- Add an **orchestrator-side round ledger** (structured section/front-matter
  in code-review.md): per-round severity counts, per-reviewer verdicts, HEAD
  reviewed. Blind reviewers NEVER see the ledger or prior findings.
- Add **stop conditions**: converged (round P0+P1 = 0), trajectory stop
  (P0+P1 flat/rising 2 consecutive rounds), and a `review_max_rounds`
  front-matter budget (default 5).
- Add a **split-verdict protocol**: after 2 consecutive split rounds (or a
  stop firing with a split present), run exactly ONE non-blind
  **disclosure round** (`review_mode: disclosure-consensus`) where the same
  reviewers see each other's findings and converge; max 1 per change.
- Add a **decision-audit landing**: when open P0/P1 remain after stop
  conditions and any disclosure round, the loop halts review cycling and
  presents a tiered 🔴/🟡/🟢 decision audit (open findings, autonomous fix
  decisions, scope expansions) to the user — never forced green, never
  ad-hoc extra reviewer models.
- Add **prose scope + evidence-gated widening**: intent.md states intended
  scope in prose; out-of-scope findings required to meet the frozen intent
  widen the scope with a logged `Scope Expansions` entry in review.md;
  non-required findings route to follow-ups.md. intent.md meaning is never
  edited.
- Add an **advisory surface audit** dispatched once before apply for
  property-style intents ("no X anywhere"), feeding tasks and the
  intended-scope prose; advisory reviews cannot loop.
- Add **reviewer-model stability**: all blind rounds of a change use the
  resolved `review` role model set; adding reviewer models mid-change is
  prohibited.
- Full re-review every round is retained (no delta-scoped rounds); the stop
  conditions, not review-scope narrowing, contain cost.

## Capabilities

### New Capabilities
- `opsx-review-convergence`: the gating-review convergence discipline —
  verdict contract, severity rubric/floor, round ledger, trajectory stop,
  round budget, disclosure round, decision-audit landing, finding routing,
  scope-widening protocol, reviewer-model stability, advisory surface audit.

### Modified Capabilities
- `opsx-post-impl-review`: code-review verdict semantics gain the
  baseline-bounded contract, severity floor (pass ⟺ no open P0/P1), round
  ledger fields, and the disclosure-round `review_mode` value alongside the
  existing blind/degraded modes.
- `opsx-loop-orchestration`: the loop's review dispatch gains stop
  conditions, split handling, decision-audit landing, scope-widening
  protocol, and the pre-apply advisory surface audit for property-style
  intents.
- `opsx-workflow-schema`: review.md front-matter gains `review_max_rounds`;
  templates gain the `Scope Expansions` section, the follow-ups.md template,
  and the code-review.md round-ledger fields.

## Impact

- **Specs:** `openspec/specs/opsx-post-impl-review/spec.md`,
  `openspec/specs/opsx-loop-orchestration/spec.md`,
  `openspec/specs/opsx-workflow-schema/spec.md` (delta specs in this change);
  new `openspec/specs/opsx-review-convergence/spec.md`.
- **Skills (Constitution IX — existing-skill edits):**
  `dot_pi/agent/skills/openspec-loop/SKILL.md` (stop conditions, ledger,
  disclosure round, landing, widening protocol, surface audit, model
  stability); apply-mode reference
  `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`
  (code-review production discipline).
- **Templates:** `dot_local/share/openspec/schemas/opsx-superpowers/templates/`
  — `review.md` (front-matter key + Scope Expansions), `code-review.md`
  (ledger + verdict-contract header), new `follow-ups.md`.
- **Gate:** no decision-logic change; `opsx gate` continues reading sealed
  fields only. `review_max_rounds` is orchestrator-read in this change
  (mechanization deferred per intent non-goals).
- **Affects which projects:** every repo using the opsx-superpowers schema
  (chezmoi, oxide-clone, void-ledger, pi) via deployed skills/templates;
  no repo-side migration required — new fields default sensibly when absent.
- **Not breaking:** existing changes without ledger fields or
  `review_max_rounds` continue to gate exactly as today.
