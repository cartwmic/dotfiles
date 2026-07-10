# Intent — merge-opsx-compact-percent-only

## Intent

Collapse the opsx-loop between-turns compaction (Lever A) trigger configuration from two
terms — `OPSX_COMPACT_AT_PERCENT` (default 33) and `OPSX_COMPACT_AT_TOKENS` (default
100000), combined as `max(percent × window, tokenFloor)` — to a single percent-of-window
knob, mirroring the percent-only style the context-elision lever adopted in
`refine-opsx-elision-token-budget`. `OPSX_COMPACT_AT_TOKENS` and the absolute-token floor
are removed entirely; `OPSX_COMPACT_AT_PERCENT` becomes the sole configuration variable
with a new default of **50**.

The default moves 33 → 50 deliberately: on 200k-token windows the 100k floor dominated
the old max() formula, making the effective trigger 50% of window — so 50 preserves
today's observed behavior on the dominant window size. It also keeps the trigger above
the elision keep-recent budget (`OPSX_ELIDE_KEEP_RECENT_PERCENT`, default 40) so the two
levers layer (elide first, compact when elision can no longer hold total context down)
rather than contend.

Additionally, this change closes a spec-of-record gap: the compaction guard currently has
zero coverage in `openspec/specs/` (no capability mentions `OPSX_COMPACT_*` or the
threshold formula). A new capability spec for the compaction guard is added covering the
percent-only trigger, disable semantics, and the garbage-fallback safety contract.

## Constraints

- `OPSX_COMPACT_AT_PERCENT` accepts an integer 1–100; the exact tokens
  `off`/`none`/`false`/`0` (case-insensitive, trimmed) disable the compaction guard
  entirely (single-step disable replaces the old both-terms-off two-step contract).
- Garbage or out-of-range values MUST fall back to the default 50 — the guard is
  default-on and must never be silently disabled by misconfiguration.
- `OPSX_COMPACT_AT_TOKENS` is removed: no code path reads it, and it must not silently
  alter behavior if still set in the environment.
- Threshold computation becomes `ceil(percent/100 × contextWindow)`; a non-positive or
  unknown context window with no other term now means the guard cannot compute a
  threshold (degrade to no-compaction for that measurement, as the old code did when both
  terms were off).
- `describeCompactPolicy` (loop-arm notify line) reflects the single-term policy.
- Existing behavior outside the threshold formula is untouched: re-entrancy guard
  (`loop.compacting`), overflow-only compact-and-retry recovery, elision-to-compaction
  coupling (elided-flag → between-turns compaction), and compaction instructions.
- Ripple is confined to `dot_pi/agent/extensions/opsx-loop/helpers.ts`
  (`resolveCompactTokens` removed, `resolveCompactThresholdTokens` signature shrinks,
  `resolveCompactPercent` default 33→50, `describeCompactPolicy` simplified), `index.ts`
  call sites (~L428–431, ~L691), and the compaction describe block in `helpers.test.ts`.
- Scale: M. `full_rigor: false`.

## Invariants honored

- Compaction guard remains DEFAULT-ON: the loop is the operator's sole compaction path
  (pi global auto-compaction is disabled), so absence of configuration must yield an
  active guard.
- Elision-before-compaction layering: compaction trigger percent (50) stays above the
  elision keep-recent budget (40) by default.
- Spec-of-record discipline (opsx-superpowers): behavior being changed must be captured
  as capability specs; this change adds the missing compaction-guard capability rather
  than leaving the safety contract unwritten.
- No mutation of stored history semantics, provider pairing, or prompt-cache-stability
  properties established by the elision capability.

## Non-goals

- No change to elision configuration (`OPSX_ELIDE_KEEP_RECENT_PERCENT`,
  `OPSX_ELIDE_BAND_PERCENT`) or the token-budget elision algorithm.
- No shared/unified variable driving both compaction and elision — the levers stay
  independently tunable.
- No renaming of `OPSX_COMPACT_AT_PERCENT`.
- No change to overflow detection patterns or overflow-recovery flow.
- No change to compaction instructions (`OPSX_COMPACT_INSTRUCTIONS`) or the
  `ctx.compact()` integration.
