# Follow-ups

Advisory items surfaced during review that are OUT OF SCOPE for this change (do
not gate). Address in a future change or on re-arm.

## From code-review (adversarial-multimodel + disclosure-consensus)

- **P3 — intent.md wording (frozen-baseline doc inconsistency).** The frozen
  `intent.md` Invariants + decision 3 still assert the kept-full window is bounded
  to `[maxKeep, maxKeep + band]`, whose LOWER half is unsatisfiable given the frozen
  non-goal "never split a turn" (a straddling turn forces one bound to give). Both
  reviewers (disclosure-consensus) flagged this as a stale documentation inconsistency,
  non-gating. The delta spec already encodes the achievable bound (`≤ maxKeep + band,
  except a single newest turn`). A future change may reword the intent/spec-of-record
  Invariant to the achievable bound for future readers. NOT done here because
  `intent.md` is the frozen baseline (the loop never edits its MEANING).

- **P3 — estimate vs. real usage (documented degrade).** Elision activation and the
  boundary both run on the deterministic char/4 estimate of the messages about to be
  sent (single gate). When real context fill (system prompt / tool schemas) exceeds the
  ceiling but the message estimate does not, no elision fires — correct, since there is
  no tool-output mass to shed. Sanctioned by frozen decision 5 ("estimation error only
  shifts the boundary by at most one turn; never breaks correctness"). No action needed.
