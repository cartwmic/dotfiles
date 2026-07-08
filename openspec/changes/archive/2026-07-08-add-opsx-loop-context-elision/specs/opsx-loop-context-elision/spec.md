# Capability: opsx-loop-context-elision

<!-- Mid-run, per-request context view that elides stale tool-result bodies while
an opsx loop is armed. All ACs are solution-free behavioral guarantees over the
pi `context`-event transform; message-level mechanics live in tasks/plan. -->

## ADDED Requirements

### Requirement: Active Loop Scoped Elision

THE extension SHALL apply the context-elision transform ONLY while an opsx loop is
armed, and SHALL pass every message through unchanged otherwise.

#### Scenario: no loop armed
- **WHEN** the context event fires and no opsx loop is armed
- **THEN** THE extension SHALL return the messages unchanged (byte-identical view)

#### Scenario: loop armed and over the elision band
- **WHILE** an opsx loop is armed and context usage is at or above the elision band
- **WHEN** the context event fires
- **THEN** THE extension SHALL return a pruned view with stale tool-result bodies elided

### Requirement: Stale Tool Result Body Elision

WHILE eliding, THE extension SHALL replace the text body of each tool-result message
older than the recent-K window with a fixed stub, and SHALL leave the recent-K
tool results, all tool calls, and all assistant/user text in full.

#### Scenario: old tool result elided to stub
- **WHEN** a tool-result message is older than the recent-K window
- **THEN** THE extension SHALL replace its text body with the stub `[output elided to conserve context — re-run to view]`

#### Scenario: recent tool results preserved
- **WHEN** a tool-result message is within the recent-K window
- **THEN** THE extension SHALL leave its text body unchanged

#### Scenario: non-tool-result content preserved
- **WHEN** a message is assistant text, user text, a tool call, or a thinking block
- **THEN** THE extension SHALL leave it unchanged

### Requirement: Structural Integrity Fail Closed

THE extension SHALL preserve `tool_call ↔ tool_result` pairing, retain every
tool-result message (eliding only its body), preserve the newest turn in full, and
never remove or alter the system prompt.

#### Scenario: pairing preserved
- **WHEN** the transform elides an old tool-result body
- **THEN** THE emitted view SHALL still contain that tool-result message paired with its originating tool call

#### Scenario: newest turn preserved
- **WHEN** the transform runs
- **THEN** THE most recent turn's messages SHALL be emitted in full

#### Scenario: structural guard trips
- **IF** the transform cannot produce a paired, structurally valid view
- **THEN** THE extension SHALL return the original messages unchanged (fail-closed no-op)

### Requirement: Threshold Band Gating

WHILE context usage is below the resolved elision threshold, THE extension SHALL NOT
elide, and WHILE at or above it THE extension SHALL elide against a band-quantized
boundary so the slim prefix stays stable across consecutive requests.

#### Scenario: below the band
- **WHILE** context usage is below the elision threshold
- **WHEN** the context event fires
- **THEN** THE extension SHALL return the messages unchanged

#### Scenario: band-quantized boundary stable across requests
- **WHILE** context usage stays within one band across consecutive requests
- **WHEN** the context event fires on each request
- **THEN** THE elision boundary SHALL be identical across those requests

### Requirement: No History Mutation

THE extension SHALL never mutate stored session history; the elided view SHALL exist
only as the transform's return value for that single provider request.

#### Scenario: stored history untouched
- **WHEN** the transform elides bodies for a request
- **THEN** THE persisted session and `agent.state.messages` SHALL retain the full untrimmed content

### Requirement: Elision To Compaction Coupling

WHEN elision has fired at least once during a worker run, THE extension SHALL treat
that run's `agent_end` as an additional between-turns compaction trigger.

#### Scenario: elided run compacts at end
- **WHEN** a worker run in which elision fired reaches `agent_end`
- **THEN** THE extension SHALL request a between-turns compaction before injecting the next worker directive

#### Scenario: non-elided run unaffected
- **WHEN** a worker run in which elision never fired reaches `agent_end`
- **THEN** THE extension SHALL apply only the existing L1 threshold decision (no elision-driven compaction)

### Requirement: Safe Degradation

IF the running host lacks the `context` event hook or the context-usage API, THEN THE extension SHALL preserve prior behavior with the elision layer inert.

#### Scenario: host lacks usage API
- **IF** `getContextUsage` is unavailable when the context event fires
- **THEN** THE extension SHALL return the messages unchanged

#### Scenario: host lacks context hook
- **IF** the host never emits the context event
- **THEN** THE extension SHALL continue to drive the loop exactly as before this change

### Requirement: Deterministic No Model Call

THE elision transform SHALL complete deterministically without invoking any model or
performing any network/LLM call.

#### Scenario: no model call in transform
- **WHEN** the transform runs for a request
- **THEN** THE extension SHALL produce the elided view using only in-process pure computation

## Five-Property Checklist

| Requirement | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| Active Loop Scoped Elision | ✓ | ✓ | ✓ | ✓ | ✓ |
| Stale Tool Result Body Elision | ✓ | ✓ | ✓ | ✓ | ✓ |
| Structural Integrity Fail Closed | ✓ | ✓ | ✓ | ✓ | ✓ |
| Threshold Band Gating | ✓ | ✓ | ✓ | ✓ | ✓ |
| No History Mutation | ✓ | ✓ | ✓ | ✓ | ✓ |
| Elision To Compaction Coupling | ✓ | ✓ | ✓ | ✓ | ✓ |
| Safe Degradation | ✓ | ✓ | ✓ | ✓ | ✓ |
| Deterministic No Model Call | ✓ | ✓ | ✓ | ✓ | ✓ |
