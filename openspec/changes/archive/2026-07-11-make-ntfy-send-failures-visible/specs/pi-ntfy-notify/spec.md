<!-- authored: in-session -->
# Capability: pi-ntfy-notify

## MODIFIED Requirements

### Requirement: Delivery Failures Are Non-Fatal

IF notification delivery fails for any reason, THEN THE extension SHALL
surface the failure through the visibility surfaces (warning, status, send
log) and SHALL NOT block, delay, or abort the assistant turn. A response
with a non-2xx HTTP status SHALL be treated as a delivery failure.

#### Scenario: Channel unreachable
- **IF** the configured channel cannot be reached, times out, or the send
  throws
- **THEN** the failure SHALL be recorded (status state + send log) and
  surfaced as a warning when a UI is available
- **AND** the turn SHALL complete normally

#### Scenario: Non-2xx response is a failure
- **WHEN** the channel responds with a non-2xx HTTP status
- **THEN** the send SHALL be treated as a delivery failure carrying that
  status
- **AND** SHALL NOT be recorded as a success

#### Scenario: Delivery never blocks the turn
- **WHEN** a notification is dispatched
- **THEN** dispatch SHALL be fire-and-forget and SHALL NOT delay turn
  completion

## ADDED Requirements

### Requirement: Send Failures Are Warned In The UI

WHEN a notification send fails and a UI is available, THE extension SHALL
emit a warning identifying the failure reason for EVERY failed send.

#### Scenario: Failure warns with reason
- **WHEN** a send fails (throw, timeout, or non-2xx)
- **AND** the session has a UI
- **THEN** a warning naming the failure reason SHALL be shown

#### Scenario: No UI still records
- **IF** no UI is available (e.g. print mode)
- **THEN** the failure SHALL still be recorded in the status state and send
  log

### Requirement: Status Reports Send Outcomes

THE `/ntfy` status output SHALL report, for the current session: the last
successful send time, the last failed send time with its error or HTTP
status, and the counts of successful and failed sends.

#### Scenario: Status after a failure
- **WHEN** at least one send has failed this session
- **THEN** status SHALL show the last failure's time and reason and the
  failure count

#### Scenario: Status with no sends
- **WHEN** no send has been attempted this session
- **THEN** status SHALL indicate that no sends have occurred

### Requirement: Capped Send Log

THE extension SHALL append one line per send attempt (timestamp, outcome,
HTTP status or error) to a send log in the extension directory, SHALL cap
the log's size with a truncate-or-rotate policy, and SHALL NOT write
notification body content beyond bounded metadata nor any credential or
auth header value.

#### Scenario: Attempt is logged
- **WHEN** a send settles (success or failure)
- **THEN** one log line with timestamp and outcome SHALL be appended

#### Scenario: Log is capped
- **WHEN** the log exceeds the size cap
- **THEN** the extension SHALL truncate or rotate it so it does not grow
  unbounded

#### Scenario: No secrets in the log
- **WHEN** any log line is written
- **THEN** it SHALL NOT contain credential values or auth header contents
