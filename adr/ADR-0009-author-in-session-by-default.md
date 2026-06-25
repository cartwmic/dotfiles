# ADR-0009: Author opsx artifacts in the parent session by default

**Status:** Accepted
**Date:** 2026-06-25
**Source change:** `openspec/changes/archive/2026-06-25-add-opsx-model-config/`

## Context

The observed bug that motivated `add-opsx-model-config`: artifact authoring was
silently delegated to a subagent running a different model (gpt-5.5) than the
parent session (opus 4.8). Configuring an `author` model alone does not fix this —
the root cause is *delegation* plus an un-passed model. We had to decide the default
authoring locus for the opsx workflow.

## Decision Drivers

- Fix the observed surprise at the SOURCE, not via post-hoc detection.
- Constitution II (canonical tooling) + the workflow's harness-neutral posture.
- A post-hoc gate cannot force a model against a same-UID agent (see ADR-0010), so
  prevention beats detection for the authoring path.

## Considered Options

### Option A: Author in the parent session by default; delegate only on opt-out
Authoring runs in the parent session (whatever model the user is on) unless
`author_in_session: false`. A cheap self-attested `<!-- authored: in-session -->`
marker is written and gate-checked when an `author` role is configured.

**Pros:** the bug becomes definitionally impossible under the default — authoring is
not delegated, so it cannot run on a subagent's model. Cheap. Harness-neutral.
**Cons:** the marker is self-attested (a worker that both delegates AND forges the
marker is out of the threat model); the exact in-session model id is not verified.

### Option B: Always allow delegated authoring, enforce the model via the gate
Delegate authoring to the `author` model and have `opsx-gate` verify the model that
actually ran.

**Pros / Cons:** rejected — verification is unachievable against a same-UID actor
(ADR-0010), so this would be enforcement theatre.

## Decision Outcome

**Chosen option:** A.

**Rationale:** prevention at the source is deterministic where detection is not. The
default (no authoring delegation) closes the observed bug by construction; the
self-attested marker is an honest, cheap tripwire for recurrence, scoped to when an
`author` role is configured (so the bootstrap change does not self-gate).

## Consequences

**Positive:** the gpt-5.5 surprise cannot recur under the default; harness-neutral
(works from pi, Codex, Claude, bash); no companion dependency.
**Negative:** in-session model id is unverified (marker is self-attested) — accepted
residual, disclosed in the spec.
**Neutral:** opt-in delegation (`author_in_session: false`) remains available on the
configured `author` model, best-effort.

## Links

- Source design discussion: `openspec/changes/archive/2026-06-25-add-opsx-model-config/design.md` (Decision D2, D4)
- Related ADRs: ADR-0010 (no post-hoc model-provenance gate), ADR-0005 (harness-neutral CLI tooling)

---
<!-- MADR 4.0 short form. Once Accepted, do not edit the body; supersede with a new ADR. -->
