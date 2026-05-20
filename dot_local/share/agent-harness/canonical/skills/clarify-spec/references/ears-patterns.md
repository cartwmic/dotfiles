# EARS notation reference

EARS = Easy Approach to Requirements Syntax. Mavin et al., RE'09.

Five patterns + compound. Each pattern shapes a complete acceptance criterion.

## The five patterns

### 1. Ubiquitous (always true)

```
THE <system> SHALL <response>
```

Use for invariants that hold regardless of state or trigger.

**Example:** `THE Platform SHALL log every authenticated request to the audit table.`

### 2. Event-driven (nominal trigger)

```
WHEN <trigger>, THE <system> SHALL <response>
```

Use for behaviors initiated by a discrete event. The trigger MUST describe a successful or expected event.

**Example:** `WHEN a user submits valid credentials, THE Platform SHALL issue a session token.`

### 3. State-driven (precondition)

```
WHILE <state>, THE <system> SHALL <response>
```

Use for behaviors that only apply during a particular system state.

**Example:** `WHILE an order is in "canceled-and-refunded" state, THE Platform SHALL NOT accept resubmission of the same line items.`

### 4. Optional (feature gate)

```
WHERE <feature is present / enabled>, THE <system> SHALL <response>
```

Use for behaviors that only apply when a configurable feature is enabled.

**Example:** `WHERE the "advanced search" feature is enabled, THE Platform SHALL surface a "Search by tag" input on the dashboard.`

### 5. Unwanted-behavior (error / exception)

```
IF <unwanted condition>, THEN THE <system> SHALL <response>
```

Use for errors, faults, invalid inputs, or any unwanted condition.

**HARD RULE:** error / unwanted conditions MUST use `IF…THEN`. They MUST NOT use `WHEN`. The analyze artifact's check 2 surfaces violations.

**Example:** `IF the request contains an invalid signature, THEN THE Platform SHALL reject the request with HTTP 401 and increment the fraud-attempt counter.`

## Compound chains

You may chain a `WHILE` and a `WHEN`:

```
WHILE <state>, WHEN <trigger>, THE <system> SHALL <response>
```

**Example:** `WHILE the user has unsaved changes, WHEN they navigate away, THE Platform SHALL prompt to confirm discard.`

Compound chains MAY also include `WHERE`:

```
WHERE <feature>, WHILE <state>, WHEN <trigger>, THE <system> SHALL <response>
```

`IF…THEN` does NOT chain — it stands alone as a complete error AC.

## Mapping to formal logic (for clarify Pass 2)

Each AC formalizes as `antecedent → consequent`:

- Ubiquitous:    `true → <response>`
- Event-driven:  `<trigger event> → <response>`
- State-driven:  `<state predicate> → <response>`
- Optional:      `<feature flag> → <response>`
- Unwanted:      `<unwanted condition> → <response>`
- Compound:      `<state> ∧ <trigger> → <response>`

Pass 2 (inconsistency) checks: for each pair of ACs, can their antecedents both be true simultaneously? If yes, do their consequents conflict on any shared observable output?

## Common errors

| Anti-pattern | Why wrong | Fix |
|---|---|---|
| `WHEN user submits invalid form` | Error condition under WHEN | `IF user submits invalid form, THEN…` |
| `WHEN user is logged in, THE…` | State expressed as event | `WHILE user is logged in, THE…` |
| `IF user successfully logs in` | Nominal event under IF | `WHEN user logs in, THE…` |
| `THE system shall be fast` | No measurable response | `THE system SHALL respond within 200ms p95` |
| `WHEN possible, THE system…` | Trigger not observable | restate with a concrete trigger |

## See also

- Mavin et al., RE'09 paper: <https://ieeexplore.ieee.org/document/5328509/>
- Alistair Mavin's reference: <https://alistairmavin.com/ears/>
- Kiro's EARS usage in production: <https://kiro.dev/blog/deep-spec-analysis/>
