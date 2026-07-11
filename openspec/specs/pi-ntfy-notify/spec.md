# pi-ntfy-notify Specification

## Purpose
A local pi extension that pushes an ntfy notification on every `agent_end` (the awaiting-input boundary), identifying the session (name + zellij) and excerpting the assistant's last response, so a user reaching a remote pi via phone/Termux/SSH/zellij knows when and which session awaits input. Self-hosted ntfy; on/off toggle via `/ntfy` command and `enabled` config.
## Requirements
### Requirement: Notify On Turn End

WHEN an assistant turn ends in an interactive session, THE extension SHALL deliver a push notification to the configured channel.

#### Scenario: Interactive turn completes
- **WHEN** an assistant turn ends and the session is interactive and a channel is configured
- **THEN** a single push notification is delivered to the configured channel

#### Scenario: Auto-retry in progress
- **IF** the turn ends with a pending automatic retry (the agent is not yet awaiting user input)
- **THEN** the extension SHALL NOT deliver a notification

#### Scenario: Non-interactive session
- **IF** the session is non-interactive (print or json mode)
- **THEN** the extension SHALL NOT deliver a notification

### Requirement: Notification Identifies Session

THE notification SHALL identify the originating session by including the pi session name and the active terminal-multiplexer session name.

#### Scenario: Named pi session
- **WHEN** a notification is delivered for a session that has a display name
- **THEN** the notification includes that pi session name and the multiplexer session name

#### Scenario: Unnamed pi session
- **IF** the pi session has no display name
- **THEN** the notification includes a stable short session identifier in place of the name

### Requirement: Notification Includes Content Excerpt

THE notification SHALL include a length-bounded, text-only excerpt of the assistant's last message.

#### Scenario: Assistant message has text
- **WHEN** a notification is delivered and the last assistant message contains text
- **THEN** the notification body includes an excerpt of that text truncated to the configured maximum length

#### Scenario: Excerpt exceeds maximum length
- **IF** the assistant's last message text exceeds the configured maximum excerpt length
- **THEN** the excerpt SHALL be truncated to the maximum length with a truncation indicator

#### Scenario: Assistant message has no text
- **IF** the last assistant message contains no renderable text
- **THEN** the notification SHALL still be delivered with an empty or placeholder excerpt

### Requirement: No-op When Unconfigured

WHILE no notification channel is configured, THE extension SHALL take no action and SHALL NOT raise an error.

#### Scenario: Missing configuration
- **IF** no channel configuration is present or the configuration omits the channel target
- **THEN** the extension SHALL register without delivering notifications and SHALL NOT error

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

### Requirement: Notifications Can Be Toggled

THE extension SHALL expose an on/off setting; WHILE notifications are disabled, no notification SHALL be delivered. The default state is on, and a runtime toggle SHALL override the default and persist across restarts.

#### Scenario: Disabled by default setting
- **WHILE** the on/off setting is off
- **WHEN** an assistant turn ends
- **THEN** no notification is delivered

#### Scenario: Runtime toggle off then on
- **WHEN** the user toggles notifications off and a later turn ends
- **THEN** no notification is delivered until the user toggles them back on

#### Scenario: Toggle persists across restarts
- **WHEN** the user toggles notifications off
- **THEN** the off state persists for subsequent sessions until toggled on again

#### Scenario: Status query
- **WHEN** the user requests the current state without an on/off argument
- **THEN** the extension reports whether notifications are on or off without changing the state

<!-- Requirement "Channel Secret Excluded From Source" removed: the ntfy URL
(https://ntfy.internal.cartwmic.com/pi) is an internal-only, non-externally-
reachable host and is not a secret; it is committed as a plain config value. -->

---

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

