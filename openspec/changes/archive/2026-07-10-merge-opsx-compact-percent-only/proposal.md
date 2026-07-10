## Why

The opsx-loop between-turns compaction guard (Lever A) still uses a legacy two-term
trigger — `max(OPSX_COMPACT_AT_PERCENT × window, OPSX_COMPACT_AT_TOKENS)` — while the
context-elision lever went percent-only in `refine-opsx-elision-token-budget`
(archived 2026-07-08). The asymmetry confuses configuration, the absolute floor does
hidden work (on 200k windows the 100k floor, not the percent, sets the effective
trigger), and the compaction guard has zero spec-of-record coverage despite being the
operator's sole compaction path (pi global auto-compaction is disabled).

## What Changes

- Remove `OPSX_COMPACT_AT_TOKENS` and the absolute-token floor term entirely; no code
  path reads it.
- `OPSX_COMPACT_AT_PERCENT` becomes the sole compaction-trigger knob; threshold =
  `ceil(percent/100 × contextWindow)`.
- Default moves 33 → **50**: preserves today's effective trigger on 200k windows
  (where the 100k floor dominated: `max(33%×200k, 100k) = 100k = 50%`) and stays above
  the elision keep-recent budget (default 40%) so the levers layer (elide first,
  compact later) instead of contending.
- Disable semantics become single-step: the exact tokens `off`/`none`/`false`/`0`
  (case-insensitive, trimmed) disable the guard; garbage/out-of-range values fall back
  to the default 50 — the guard is never silently disabled by misconfiguration.
- `resolveCompactTokens` is deleted; `resolveCompactThresholdTokens` and
  `describeCompactPolicy` lose their token-floor parameter; `resolveCompactPercent`
  default changes to 50.
- New spec capability `opsx-loop-compaction-guard` closes the Lever A spec gap
  (percent-only trigger, disable semantics, garbage-fallback safety contract,
  elision-layering default).

Not **BREAKING** for any spec-of-record capability (none covered this surface), but a
behavioral env-config change: an environment still setting `OPSX_COMPACT_AT_TOKENS`
will see it ignored.

## Clarifications (folded, plain Scale M)

Resolved with the owner during the explore session (2026-07-09):

1. **Merge scope** — drop `OPSX_COMPACT_AT_TOKENS` only; no renames, no shared var
   across compaction/elision. (Chosen over rename-for-symmetry and single-shared-var.)
2. **New default percent** — 50, for 200k-window behavior preservation and
   elide-before-compact layering. (Owner delegated: "whichever makes the most sense";
   40 was considered and rejected because it equals the elision keep budget and the
   levers would contend.)
3. **Disable semantics** — single `off`/`none`/`false`/`0` disables; garbage still
   falls back to default. (Chosen over a no-disable-path design to keep an
   operational escape hatch.)
4. **Spec coverage** — yes, add the compaction-guard capability in this change.

## Capabilities

### New Capabilities
- `opsx-loop-compaction-guard`: percent-only between-turns compaction trigger for the
  opsx-loop extension — default-on, single env knob (`OPSX_COMPACT_AT_PERCENT`,
  default 50), explicit-off-only disable, garbage-falls-back-to-default safety
  contract, and the policy notify line.

### Modified Capabilities
<!-- opsx-loop-context-elision references "the existing L1 threshold" generically and
needs no delta; no other capability mentions the compaction trigger. -->

## Impact

**Affected files (this repo, chezmoi source):**
- `dot_pi/agent/extensions/opsx-loop/helpers.ts` — `resolveCompactTokens` removed;
  `resolveCompactPercent` default 33→50; `resolveCompactThresholdTokens(window, pctRaw)`
  signature shrinks; `describeCompactPolicy(pctRaw)` simplifies; Lever A comment block
  updated.
- `dot_pi/agent/extensions/opsx-loop/index.ts` — call sites (~L428–431 threshold
  computation, ~L691 policy notify) drop the `OPSX_COMPACT_AT_TOKENS` argument.
- `dot_pi/agent/extensions/opsx-loop/helpers.test.ts` — compaction-threshold describe
  block rewritten for percent-only semantics (floor cases removed, default-50 cases,
  disable cases, garbage-fallback cases).
- `openspec/specs/opsx-loop-compaction-guard/spec.md` — new capability (via delta in
  this change).

**Validation source (agent-independent):** `bun test` in
`dot_pi/agent/extensions/opsx-loop/`.

**Runtime note:** live extension at `~/.pi/agent/extensions/opsx-loop` picks up the
change only after `chezmoi apply`. Constitution VIII: `openspec/` itself is not
chezmoi-deployed.

**Affects which projects:** this repo only (pi opsx-loop extension).
