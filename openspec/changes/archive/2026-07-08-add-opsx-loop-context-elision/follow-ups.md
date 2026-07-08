# Follow-ups

**Change:** add-opsx-loop-context-elision
**Created:** 2026-07-08 (first out-of-scope routing)

## Queue

| # | Finding | Severity | Origin (review type, round) | Routing reason | Status |
|---|---|---|---|---|---|
| 1 | Whole-pass fail-closed when ANY tool_result (incl. recent) has non-array `content` — if pi ever emitted string-content tool results, elision would go permanently inert (`helpers.ts` structural pre-scan). | P2 | code-review round 3 | Not required for the frozen intent: degrade-safe no-op, and pi's typed `ToolResultMessage.content` is always an array, so the case is theoretical. A future refinement could skip only the malformed message once pairing is still provable. | open |
| 2 | `session.elided` is consumed only on the worker-mode `continueWorker` path, not literally "at run start"; abnormal/distill agent_end paths can defer the coupled compaction by one turn (never double-compacts, never misses). | P3 | code-review round 3 | Harmless one-turn deferral; distill turns rarely reach the elision band. Not required for the intent's outcomes. | open |
| 3 | Elision replaces the entire tool_result `content` with a single text stub, dropping any non-text (image) blocks rather than only the text body. | P3 | code-review round 3 | Within the intent (whole stale output is the bloat); over-elision is the safe direction and the re-run recovery valve covers it. | open |

## Waivers

<!-- none -->

## Promotion

<!-- filled at archive if pursued -->
