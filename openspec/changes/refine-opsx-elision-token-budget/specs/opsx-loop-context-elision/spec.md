# Capability: opsx-loop-context-elision

<!-- Delta for refine-opsx-elision-token-budget: the elision boundary becomes a
token budget (maxKeep = 40% of the live context window) snapped to turn edges with
token-band hysteresis, replacing the turn-count recent-K window and the separate
percent/token activation threshold. Carried-over requirements (Structural Integrity
Fail Closed, No History Mutation, Safe Degradation, Deterministic No Model Call) are
unchanged and not restated here. -->

## ADDED Requirements

### Requirement: Token Budget Boundary

WHILE eliding, THE extension SHALL keep the most-recent turns whose cumulative estimated tokens fit a budget `maxKeep` (default 40% of the live context window) and SHALL elide stale tool-result bodies before a boundary snapped to a turn edge at or below that budget, never splitting a turn.

#### Scenario: boundary snaps to a turn edge under budget
- **WHEN** the transform elides at a token budget `maxKeep`
- **THEN** THE elision boundary SHALL fall on a turn edge such that the kept-full recent turns' cumulative estimated tokens are at or below `maxKeep` plus the band

#### Scenario: kept-full window is capped at the ceiling
- **WHILE** eliding against `maxKeep` and a band
- **WHEN** the transform runs
- **THEN** THE cumulative estimated tokens of the kept-full recent window SHALL be at or below `maxKeep + band`, except a single newest turn that alone exceeds that ceiling

#### Scenario: over-budget always elides at least one turn
- **WHILE** an opsx loop is armed and there is more than one turn and total estimated context exceeds `maxKeep + band`
- **WHEN** the transform runs
- **THEN** THE extension SHALL elide the body of at least the oldest turn (never firing yet producing an unchanged over-budget view)

#### Scenario: newest turn always kept
- **WHEN** the newest (in-flight) turn's estimated tokens alone exceed `maxKeep`
- **THEN** THE extension SHALL still emit that newest turn in full and elide only turns before it

#### Scenario: budget resolves against the live window
- **WHEN** the context event fires with a context window of size `W`
- **THEN** THE extension SHALL compute `maxKeep` as the configured percent of `W` (default 40%) with no absolute token floor

### Requirement: Token Band Hysteresis

WHILE eliding, THE extension SHALL advance the elision boundary only per token-band of growth (default 5% of the live context window) so the slim prefix stays stable across consecutive requests within one band.

#### Scenario: boundary stable within a band
- **WHILE** context usage stays within one token-band across consecutive requests
- **WHEN** the context event fires on each request
- **THEN** THE elision boundary SHALL be identical across those requests

#### Scenario: boundary advances across a band
- **WHEN** context usage grows past the next token-band edge between requests
- **THEN** THE elision boundary MAY advance to a newer turn edge

### Requirement: Elision Suppressed During Compaction

IF a between-turns compaction is in progress when the context event fires, THEN THE extension SHALL return the messages unchanged so the compaction summarizer's own request is never elided.

#### Scenario: compaction in progress
- **IF** the extension is running a between-turns compaction when the context event fires
- **THEN** THE extension SHALL return the messages unchanged (no elision)

## MODIFIED Requirements

### Requirement: Active Loop Scoped Elision

THE extension SHALL apply the context-elision transform ONLY while an opsx loop is armed, and SHALL pass every message through unchanged otherwise.

#### Scenario: no loop armed
- **WHEN** the context event fires and no opsx loop is armed
- **THEN** THE extension SHALL return the messages unchanged (byte-identical view)

#### Scenario: loop armed and over the token budget
- **WHILE** an opsx loop is armed and total context usage exceeds `maxKeep` plus the band
- **WHEN** the context event fires
- **THEN** THE extension SHALL return a pruned view with stale tool-result bodies elided

#### Scenario: loop armed but within budget
- **WHILE** an opsx loop is armed and total context usage is at or below `maxKeep` plus the band
- **WHEN** the context event fires
- **THEN** THE extension SHALL return the messages unchanged

### Requirement: Stale Tool Result Body Elision

WHILE eliding, THE extension SHALL replace the text body of each tool-result message older than the token-budget recent window with a fixed stub, and SHALL leave the kept-full recent tool results, all tool calls, and all assistant/user text in full.

#### Scenario: old tool result elided to stub
- **WHEN** a tool-result message is older than the token-budget recent window
- **THEN** THE extension SHALL replace its text body with the stub `[output elided to conserve context — re-run to view]`

#### Scenario: recent tool results preserved
- **WHEN** a tool-result message is within the token-budget recent window
- **THEN** THE extension SHALL leave its text body unchanged

#### Scenario: non-tool-result content preserved
- **WHEN** a message is assistant text, user text, a tool call, or a thinking block
- **THEN** THE extension SHALL leave it unchanged

### Requirement: Elision To Compaction Coupling

WHEN elision has fired at least once during a worker run, THE extension SHALL treat that run's end — on every continuation path, including the worker `agent_end` path and the distill (`awaitingChange`) continuation path — as an additional between-turns compaction trigger, consuming the elided flag exactly once per run.

#### Scenario: elided worker run compacts at end
- **WHEN** a worker run in which elision fired reaches `agent_end`
- **THEN** THE extension SHALL request a between-turns compaction before injecting the next worker directive

#### Scenario: elided run on the distill path compacts
- **WHEN** a run in which elision fired reaches the distill (`awaitingChange`) continuation
- **THEN** THE extension SHALL consume the elided flag and request a between-turns compaction on that path as well

#### Scenario: non-elided run unaffected
- **WHEN** a worker run in which elision never fired reaches its end
- **THEN** THE extension SHALL apply only the existing L1 threshold decision (no elision-driven compaction)

## REMOVED Requirements

### Requirement: Threshold Band Gating

**Reason:** The turn-count activation threshold (`OPSX_ELIDE_AT_PERCENT` /
`OPSX_ELIDE_AT_TOKENS`) and turn-count band (`OPSX_ELIDE_BAND_TURNS`) are superseded
by the token-budget boundary (`Token Budget Boundary`) and token-band hysteresis
(`Token Band Hysteresis`). A single `maxKeep` budget now governs both activation
(elision fires when `total > maxKeep + band`) and the boundary, so a separate
activation threshold is redundant.

**Migration:** Operators who set `OPSX_ELIDE_AT_PERCENT`, `OPSX_ELIDE_AT_TOKENS`,
`OPSX_ELIDE_KEEP_RECENT_TURNS`, or `OPSX_ELIDE_BAND_TURNS` migrate to
`OPSX_ELIDE_KEEP_RECENT_PERCENT` (default 40) and `OPSX_ELIDE_BAND_PERCENT`
(default 5). The removed knobs are ignored; defaults hold the working context near
40% of the window with a 5%-of-window band on any model.
