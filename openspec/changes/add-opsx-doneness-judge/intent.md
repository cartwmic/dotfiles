# Intent — add-opsx-doneness-judge

## Intent

Add a **semantic doneness judge** on top of the existing deterministic opsx gate. The
gate today proves only *mechanical* doneness (build/test/lint exit 0, required artifacts
present, review verdict present); it cannot tell whether the diff actually accomplished
what the frozen `intent.md` asked. A change can be mechanically green while missing the
intent or drifting scope.

Introduce a **blind LLM judge** that rules whether the frozen intent is satisfied by the
actual diff, and have the gate enforce that verdict. Crucially, the gate stays
deterministic: the judgment is produced upstream by an independent subagent, sealed into a
new `doneness.md` artifact with provenance, and the gate merely **reads the field** — it
never runs a model. This layers intent-satisfaction judgment onto the loop without
sacrificing the gate's reproducible, exit-code-based decision logic.

## Design decisions (frozen)

- **Sealed verdict, gate reads it.** The gate performs no model call. It reads a
  `Doneness: satisfied | not` field from `doneness.md`, exactly as it already reads
  `Verdict: pass` from `code-review.md`.
- **Dedicated artifact + dedicated blind subagent.** A new `doneness.md` artifact, produced
  by an independent blind judge subagent (fresh context, no orchestrator memory) that reads
  the frozen `intent.md` + the full `Diff Base..HEAD` diff + delta ACs and rules
  `satisfied | not` with the specific unmet gaps enumerated when `not`.
- **Doneness gates loop-stop.** Doneness is a required gate check: the gate is not green —
  and therefore the loop does not stop — until the doneness verdict is `satisfied`. It is
  NOT merely an archive precondition.
- **Backstop = doneness-aware stall detection only** (no separate veto cap). The existing
  stall detector is extended so that, for the doneness check, *progress* is defined as the
  judge's normalized **gap set shrinking**, not file content changing. If the judge keeps
  returning the same unmet gaps, it counts as no-progress even when files changed each turn,
  so a thrashing agent trips stall instead of looping forever under an unbounded budget.
- **Reuse the `review` role model.** The doneness judge runs on the model resolved for the
  `review` role (`opsx models review`); no new model role is introduced.
- **Freshness-bound verdict.** A doneness verdict is valid only when its Reviewed Range HEAD
  equals the current HEAD. New commits invalidate the prior verdict and force a re-judge,
  preventing a stale `satisfied` from passing after further changes.
- **Scale-gated with waiver.** The doneness requirement applies at Scale >= M and can be
  waived via a `doneness_mode: waived` field in `review.md` front-matter, mirroring the
  existing validation-source waiver. Trivial changes skip it.
- **Scope-anchored charter.** "Satisfied" means the frozen intent's stated outcomes are met
  and NOTHING MORE. The judge is explicitly forbidden from demanding gold-plating or
  beyond-scope work, to keep false-negatives (and loop thrash) low.
- **Sequencing.** The orchestrator (openspec-loop skill) dispatches the blind doneness judge
  after the mechanical checks pass, writes `doneness.md`, then the loop's `opsx gate` reads
  all verdicts. Cheap deterministic checks precede the expensive judge.
- **Anti-self-forge provenance.** `doneness.md` carries a provenance marker (judge identity +
  frozen-intent hash + Diff Base SHA + Reviewed Range) that the orchestrator cannot self-mark
  in normal flow; the gate validates the marker and freshness, matching the code-review
  provenance pattern.

## Constraints

- **Gate stays deterministic.** No model invocation inside the `opsx gate` code path; the gate
  only reads sealed fields and validates provenance/freshness by exit-code logic.
- **Reuse existing machinery.** Build on the current blind-subagent + provenance + freshness
  pattern used by `code-review.md`; do not invent a parallel review system.
- **Harness-neutral.** Doneness config/enforcement lives in the `opsx` CLI + artifacts +
  review.md front-matter, not inside the pi extension, so every harness enforces it equally
  (consumer-not-owner, ADR-0007).
- **Do NOT modify the `goal` extension** (ADR-0006).
- **No new dev-tool install** (Constitution V); reuse `yq`/`sed` for field/front-matter reads.
- **No secrets** (Constitution III).

## Invariants honored

- Constitution II (sources at canonical chezmoi paths, deploy via chezmoi), III, V, IX
  (adversarial review for skill-touching changes).
- ADR-0006 (goal extension untouched), ADR-0007 (harness-neutral config/resolver owns
  enforcement; extension is a consumer).
- The gate's deterministic decision logic over exit codes / sealed fields is preserved.

## Non-goals

- A live per-turn LLM judge inside the loop (rejected: non-deterministic stop, per-turn cost,
  self-judgment bias). The judgment is sealed and read, not run in-loop.
- A new model role for doneness (reuse `review`).
- A separate numeric veto cap distinct from stall detection.
- Making doneness merely advisory or archive-only (it gates loop-stop).
- Changing the mechanical gate checks, the `goal` extension, or the bash `opsx loop` driver's
  core judge contract.

## Supersedes

- The prior design stance that opsx doneness is judged *solely* by deterministic exit codes
  with "no LLM judgment." This change deliberately reintroduces an LLM verdict for
  intent-satisfaction — sealed, blind, provenance-stamped, and gate-read — and is therefore
  ADR-worthy.
