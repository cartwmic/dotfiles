# opsx-loop-compaction-guard Specification

## Purpose
TBD - created by archiving change merge-opsx-compact-percent-only. Update Purpose after archive.
## Requirements
### Requirement: Percent Only Compaction Trigger

THE extension SHALL compute the between-turns compaction threshold as a single percent of the live context window — `ceil(percent/100 × contextWindow)` — configured solely by `OPSX_COMPACT_AT_PERCENT` (integer 1–100, default 50), with no absolute-token term.

#### Scenario: threshold from percent of the live window
- **WHEN** the loop measures context usage against a context window of size `W` with `OPSX_COMPACT_AT_PERCENT` unset
- **THEN** THE extension SHALL request a between-turns compaction when measured tokens reach or exceed `ceil(0.50 × W)`

#### Scenario: configured percent overrides the default
- **WHEN** `OPSX_COMPACT_AT_PERCENT` is set to an integer between 1 and 100
- **THEN** THE extension SHALL use that percent of the live window as the threshold

#### Scenario: absolute-token term is retired
- **WHEN** `OPSX_COMPACT_AT_TOKENS` is set in the environment
- **THEN** THE extension SHALL ignore it entirely; no code path SHALL read it or let it alter the threshold

#### Scenario: unknown window degrades safely
- **IF** the context window is non-positive or unknown
- **THEN** THE extension SHALL skip the threshold decision for that measurement (no compaction request, no error), leaving overflow recovery unaffected

### Requirement: Default On With Explicit Off Only

THE compaction guard SHALL be active by default, and SHALL be disabled only by setting `OPSX_COMPACT_AT_PERCENT` to one of the exact tokens `off`, `none`, `false`, or `0` (case-insensitive, surrounding whitespace ignored).

#### Scenario: unset means active at default
- **WHEN** `OPSX_COMPACT_AT_PERCENT` is unset or empty
- **THEN** THE guard SHALL be active with the default percent 50

#### Scenario: explicit off disables
- **WHEN** `OPSX_COMPACT_AT_PERCENT` is set to `off`, `none`, `false`, or `0` (any letter case, with or without surrounding whitespace)
- **THEN** THE extension SHALL disable the between-turns compaction guard and compute no threshold

### Requirement: Garbage Falls Back To Default

IF `OPSX_COMPACT_AT_PERCENT` holds a value that is neither an explicit off token nor an integer in 1–100, THEN THE extension SHALL fall back to the default percent 50 — misconfiguration SHALL never silently disable the guard.

#### Scenario: non-numeric garbage
- **IF** `OPSX_COMPACT_AT_PERCENT` is set to a non-numeric string (e.g. `banana`, `50%`, `1.5`)
- **THEN** THE guard SHALL remain active with the default percent 50

#### Scenario: out-of-range integer
- **IF** `OPSX_COMPACT_AT_PERCENT` is set to an integer below 1 (other than the off token `0`) or above 100
- **THEN** THE guard SHALL remain active with the default percent 50

### Requirement: Default Layers Above Elision Budget

THE default compaction-trigger percent SHALL exceed the elision keep-recent budget default so elision fires before compaction under default configuration.

#### Scenario: defaults layer elide-first
- **WHEN** both the compaction guard and context elision run with defaults (trigger 50%, keep-recent budget 40%)
- **THEN** THE compaction threshold SHALL be strictly greater than the elision keep-recent budget for the same window

### Requirement: Policy Notify Describes Single Term

THE extension SHALL surface a one-line human-readable compaction-policy description on loop arm reflecting the single percent term, or the disabled state.

#### Scenario: active policy line
- **WHEN** the loop arms with the guard active at percent `P`
- **THEN** THE policy description SHALL state compaction triggers at ≥ `P`% of the context window, with no mention of an absolute-token term

#### Scenario: disabled policy line
- **WHEN** the loop arms with the guard explicitly disabled
- **THEN** THE policy description SHALL state the compaction guard is off

---

