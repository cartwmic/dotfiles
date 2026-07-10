# Follow-ups

**Change:** merge-opsx-compact-percent-only
**Created:** 2026-07-09 (first out-of-scope routing)

## Queue

| # | Finding | Severity | Origin (review type, round) | Routing reason | Status |
|---|---|---|---|---|---|
| 1 | Future changes should declare gate-unblocking collateral edits (e.g. stale validation-surface assertions) in tasks.md file contracts up front, not only in Scope Expansions — process advisory from the round-1 review | P2 | code-review round 1 (claude-fable-5) | Process improvement for future changes; the frozen intent's outcomes were met via the recorded Scope Expansion | open |
| 2 | `helpers.test.ts` retired-term test uses arity reflection (`resolveCompactThresholdTokens.length === 2`) — brittle proxy; consider a source-level lint/grep assertion inside the bun suite instead | P3 | code-review rounds 1–2 (claude-fable-5) | Advisory nit; guarantee already carried by zero-grep completion check + shrunk signature | open |
| 3 | `index.ts` Lever A comment (~L386–388) has an awkward mid-sentence line break left by the comment refresh; content accurate | P3 | code-review round 2 (claude-fable-5) | Formatting-only nit, no baseline element violated | open |
| 4 | Convergence surface assertion `DEFAULTS to` is loose standing alone; kept because assertions 2–4 pin the specific doctrine phrases | P3 | code-review round 2 (claude-fable-5) | Advisory nit on a strengthened (1→4 assertions) validation surface | open |
