# Capability: opsx-loop

## MODIFIED Requirements

### Requirement: Interrupt or error stops the loop

WHILE an opsx loop is active, THE extension SHALL stop immediately for an explicit user interrupt, SHALL preserve the same active loop across Pi-managed continuation after an errored low-level worker attempt, and SHALL stop visibly only when an error remains unresolved after Pi reports the agent settled. THE extension MUST NOT treat a failed low-level attempt as loop progress or start an independent provider retry.

#### Scenario: User interrupt halts the loop
- **WHILE** an opsx loop is active
- **IF** the user interrupts the current worker turn
- **THEN** the extension SHALL clear the loop immediately, SHALL NOT inject another turn, and SHALL inform the user that the loop stopped

#### Scenario: Errored attempt preserves active loop during native continuation
- **WHILE** an opsx loop is active
- **IF** a low-level worker attempt ends with an error and Pi can still retry, compact-and-retry, or drain a queued continuation
- **THEN** the extension SHALL keep the same loop active, SHALL NOT increment its turn or stall budgets, SHALL NOT run the gate, and SHALL NOT inject its own retry

#### Scenario: Successful native retry returns to normal gate flow once
- **WHILE** an opsx loop remains active after an errored low-level attempt
- **WHEN** Pi's native continuation later completes a clean worker attempt
- **THEN** the extension SHALL discard the pending error, count one completed worker turn, evaluate `opsx gate` exactly once, and continue or stop according to that gate result

#### Scenario: Settled unresolved error stops visibly
- **WHILE** an opsx loop is active with a pending worker error
- **IF** Pi reports that the agent is settled with no retry, compaction/retry, or queued continuation remaining
- **THEN** the extension SHALL clear the loop, preserve the worktree, and inform the user of the final error without starting an extension-owned transport retry

#### Scenario: Final context overflow retains bounded recovery
- **WHILE** an opsx loop is active with an unresolved context-overflow error
- **IF** Pi reports the agent settled and the loop has not used its existing overflow-recovery allowance
- **THEN** the extension SHALL perform one compact-and-retry continuation under the same active loop

#### Scenario: Persistent context overflow stops after allowance
- **WHILE** an opsx loop has already used its overflow-recovery allowance
- **IF** a context-overflow error remains unresolved when Pi next reports the agent settled
- **THEN** the extension SHALL clear the loop, preserve the worktree, and inform the user that context overflow persisted

#### Scenario: Deferred error cannot affect replacement loop
- **WHILE** a worker error is awaiting final settlement
- **IF** the user clears, replaces, or re-arms the loop before the corresponding settled signal
- **THEN** the old deferred outcome SHALL NOT clear, compact, notify for, increment, evaluate, or continue the current loop

#### Scenario: Goal extension is not modified
- **WHEN** the opsx-loop extension is deployed
- **THEN** the `goal` extension's files SHALL be unchanged, and both extensions SHALL operate independently

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop.interrupt-or-error-stops-the-loop | [x] | [x] | [x] | [x] | [x] |

<!-- authored: in-session -->
