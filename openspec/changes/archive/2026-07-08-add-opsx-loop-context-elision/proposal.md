<!-- authored: in-session -->

## Why

opsx-loop worker runs balloon to context-rot levels *within a single agent run*
(evidence: session `019f3d32-76d6-7469-b42d-d05cd51c8d28` peaked >80% context,
71% of it stale `toolResult` text). The two shipped compaction layers cannot help
mid-run: L1 between-turns compaction (`42dc012`) only fires at `agent_end`, and
L2 overflow recovery (`a8275a0`) only fires on a hard overflow error. Benchmarks
(Lost-in-the-Middle, NoLiMa, context-rot) show accuracy degrading well before the
window fills, so a run that climbs to ~80% mid-flight makes worse decisions on
every step after the climb.

## What Changes

- Add a mid-run, per-request **context elision** layer in the opsx-loop extension:
  register the pi `context` event (`transformContext`), and before each provider
  request within an armed loop present the model a slimmer *view* that drops stale
  tool-output bodies — without aborting the turn and without mutating stored
  history.
- Elision replaces the *text* of `toolResult` messages older than a recent-K
  window with a short stub, keeping the message itself (pairing intact), all tool
  calls, all assistant/user text, and the recent-K tool results in full.
- The transform is threshold-band gated (fires only above an elision band, with a
  band-quantized boundary for prompt-cache stability) and is a strict no-op when no
  loop is armed or when the host lacks the `context`/usage APIs.
- Couple elision to compaction: when elision fires during a run, that run's
  `agent_end` treats it as an additional between-turns (L1) compaction trigger, so
  the ephemeral trim is durably consolidated.
- **Non-breaking.** Interactive / non-loop sessions and existing L1/L2 behavior are
  untouched; pi general auto-compaction stays off.

## Capabilities

### New Capabilities

- `opsx-loop-context-elision`: mid-run, active-loop-only, per-request context view
  that elides stale tool-result bodies deterministically, preserves structural
  integrity, and couples to between-turns compaction.

### Modified Capabilities

<!-- none — this adds a new runtime capability to the opsx-loop extension; no
existing spec-level behavior changes. -->

## Impact

- **Affected files:**
  - `dot_pi/agent/extensions/opsx-loop/helpers.ts` — pure elision helpers
    (threshold resolution, band boundary, tool-result body elision over an
    `AgentMessage[]` view, pairing/structural guards).
  - `dot_pi/agent/extensions/opsx-loop/index.ts` — register the `context` event
    handler (no-op unless `loop.active`), track an `elided` flag on `LoopState`,
    and wire the elision→compaction coupling into `agent_end`.
  - `dot_pi/agent/extensions/opsx-loop/helpers.test.ts` — unit tests for the new
    pure helpers.
- **APIs / dependencies:** consumes the pi `context` event / `transformContext`
  hook and `getContextUsage()`; both accessed behind `typeof` guards so absent
  support degrades to a no-op. No new npm dependencies.
- **Composition:** layers above L1 (between-turns compaction) and L2 (overflow
  recovery); does NOT re-enable pi built-in auto-compaction (`compaction.enabled`
  stays `false`).

## Deterministic analyze (plain-M, inline)

- **Tiling / traceability:** every proposal bullet maps to a
  `opsx-loop-context-elision` requirement (elision view, stale-body elision,
  structural integrity, threshold-band gating, no-history-mutation, coupling,
  safe-degrade, determinism). No orphan requirement; no uncovered bullet.
- **EARS lint:** error/unwanted ACs use `IF…THEN` (structural-check failure,
  missing host APIs); nominal ACs use `WHILE`/`WHEN`/`WHERE`. No `should`/`may`
  in normative lines.
- **Blockers:** none.

## Open Questions

Clarify-in-proposal (plain-M): each resolved in place under a 2-option discipline.

1. **Elision band default vs L1 threshold.** Decision: default
   `OPSX_ELIDE_AT_PERCENT=25` and `OPSX_ELIDE_AT_TOKENS=60000`, threshold =
   `max(pct×window, tokens)` — mirroring L1's shape but strictly at/below L1's
   `max(33%, 100k)` for every window size (200k: 60k<100k; 1M: 250k<333k; 128k:
   60k<100k). *(A) lower fixed band ≤ L1 (chosen — keeps the mid-run view slim
   before the between-turns bar); (B) fraction-of-L1 multiplier (rejected —
   couples two knobs, harder to reason about).*
2. **Recent-K default.** Decision: `OPSX_ELIDE_KEEP_RECENT_TURNS=3` full tool
   results as active working memory. *(A) K=3 (chosen — enough working set without
   re-bloating); (B) K=1 (rejected — too aggressive, risks eliding the just-read
   file the model is mid-reasoning on).*
3. **Coupling gating (decision-5 deferred item).** Decision: the elision→compaction
   coupling is **unconditional** — any run in which elision fired flags
   `agent_end` as a compaction trigger. *(A) unconditional (chosen — already
   self-rate-limited: compaction shrinks history → next run starts slim → elision
   won't re-fire; worst case ≈ once per run = L1 cadence); (B) gate behind a
   secondary stored-context floor (rejected — adds a knob for no benefit given the
   self-rate-limit).*
4. **Cache-stability boundary banding.** Decision: quantize the elision boundary to
   bands of `OPSX_ELIDE_BAND_TURNS=5` so the slim prefix stays stable across turns
   and re-caches after the first eliding turn. *(A) band-quantized boundary
   (chosen — bounds cache misses to boundary-advance events); (B) continuous
   boundary (rejected — new prefix every turn nukes prompt caching).*
