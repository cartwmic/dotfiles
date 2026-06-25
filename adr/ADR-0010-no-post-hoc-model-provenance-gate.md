# ADR-0010: No post-hoc model-provenance gate — a gate cannot force a model against a same-UID agent

**Status:** Accepted
**Date:** 2026-06-25
**Source change:** `openspec/changes/archive/2026-06-25-add-opsx-model-config/`

## Context

`add-opsx-model-config` originally aimed to *force* the delegated review/impl model:
`opsx-gate` would read deterministic provenance and fail the gate on a model mismatch,
the same "make it binding, not prose" posture as ADR-0005. Several mechanisms were
designed and adversarially reviewed (rounds 1–8): an agent-written artifact stamp;
then pi-subagents' native run-history (`RunEntry.model`); then run-history bound by a
role `agent` identity; then a durable per-change snapshot. Each was defeated.

## Decision Drivers

- The opsx agent runs as the user (same UID) with shell + write tools.
- The realistic threat is ACCIDENTAL wrong-model delegation (the observed bug), not a
  malicious insider.
- Proportionality: a pi-subagents companion change + snapshot + identity binding is a
  large surface for a guarantee that does not actually hold.

## Considered Options

### Option A: Ship resolver + author-in-session; NO post-hoc provenance gate (chosen)
Configure models/providers harness-neutrally (`opsx-models`), fix the authoring bug at
the source (ADR-0009), and pass the resolved model to review/impl dispatch best-effort.
Do not pretend the gate can verify the delegated model.

**Pros:** honest; small surface; harness-neutral; no companion dependency. Solves the
actual (accidental) problem.
**Cons:** a deliberate actor can run review/impl on any model — explicitly out of scope.

### Option B: Run-history provenance, bound by role agent identity + per-change snapshot
The most-evolved enforcement design.

**Cons (blocking, from review):** the per-change snapshot lives in the worker-writable
worktree (forge a line, or delete it to force the "no recorder" skip); the binding
`agent` field is chosen by the same worker (`recordRun(run.agent, …)`), so a decoy run
under the role identity plus the real work off-identity passes. Trust was *relocated*,
never closed. "Non-fakeable/force" was false on the primary harness.

### Option C: Pursue true forcing in the execution layer
Real per-role forcing needs the runtime that *picks* the model to enforce it, not a
post-hoc gate.

**Cons:** out of scope for a dotfiles gate; parked.

## Decision Outcome

**Chosen option:** A.

**Rationale:** a post-hoc gate reading filesystem/process metadata cannot force a model
against an actor that runs as the user and can write any file the gate reads. The only
deterministic guarantees available are the gate *verdict* itself and git/worktree
isolation — not model provenance. Shipping the achievable, honest scope beats a larger
mechanism that merely relocates trust.

## Consequences

**Positive:** honest enforcement boundary; no companion dependency; the bug is fixed at
the source (ADR-0009). Records WHY forcing is out of scope so it is not re-litigated.
**Negative:** delegated review/impl model is best-effort, not verified — disclosed.
**Neutral:** if a harness ever exposes runtime per-role model binding, Option C can be
revisited as a new ADR.

## Links

- Source design discussion: `openspec/changes/archive/2026-06-25-add-opsx-model-config/design.md` (Decision D3); `analyze.md` (rounds 5–8 adversarial trajectory)
- Related ADRs: ADR-0009 (author-in-session), ADR-0005 (harness-neutral exit-code/CLI enforcement — the contrasting case where binding IS achievable)

---
<!-- MADR 4.0 short form. Once Accepted, do not edit the body; supersede with a new ADR. -->
