# ADR-0020: Intent scope is prose; the loop widens it only on cited evidence

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/add-opsx-review-convergence/`

## Context

Property-style intents ("no X anywhere", "impossible via code") give blind
reviewers an unbounded hunting license — every fresh round can fail the change
on newly discovered adjacent surface. The frozen-intent invariant forbids the
loop from editing intent meaning, but the scope of work must be able to grow
toward satisfying it.

## Decision Drivers

- Frozen-intent invariant (meaning never edited autonomously)
- Unknown-unknowns must not become designed blind spots
- Accountability trail for every autonomous scope decision

## Considered Options

### Option A: Prose scope in intent.md + evidence-gated widening logged in review.md `Scope Expansions`; non-required findings route to follow-ups.md
### Option B: Machine-readable surface manifest (files/globs) bounding gating findings
### Option C: No scope concept — verdict contract alone

## Decision Outcome

**Option A.** WHEN a finding falls outside the stated scope: required to meet
the frozen intent's outcomes (evidence cited) → widen, log the entry BEFORE
committing the fix, treat as in-scope; otherwise → follow-ups.md (advisory,
promoted to a successor change at archive). Every widening surfaces at the
landing or gate-green. B converts a wrong manifest into a permanent blind spot
and taxes explore; C repeats the silent widening-by-review observed 2026-07-02.
Pairs with the pre-apply advisory surface audit for property-style intents.

## Consequences

- ARC's scope-discipline rule adapted for autonomy: expand only when required
  for the original goal — but log-and-continue instead of pause-and-ask.
- intent.md authoring should state intended scope explicitly in prose.
