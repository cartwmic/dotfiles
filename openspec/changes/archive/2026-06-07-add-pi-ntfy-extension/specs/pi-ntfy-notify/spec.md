# Capability: pi-ntfy-notify

## ADDED Requirements

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

IF notification delivery fails for any reason, THEN THE extension SHALL suppress the failure and SHALL NOT block, delay, or abort the assistant turn.

#### Scenario: Channel unreachable
- **IF** the configured channel cannot be reached or returns an error
- **THEN** the extension SHALL swallow the error and the turn SHALL complete normally

#### Scenario: Delivery never blocks the turn
- **WHEN** a notification is dispatched
- **THEN** dispatch SHALL be fire-and-forget and SHALL NOT delay turn completion

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

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| pi-ntfy-notify.notify-on-turn-end | [x] | [x] | [x] | [x] | [x] |
| pi-ntfy-notify.notification-identifies-session | [x] | [x] | [x] | [x] | [x] |
| pi-ntfy-notify.notification-includes-content-excerpt | [x] | [x] | [x] | [x] | [x] |
| pi-ntfy-notify.no-op-when-unconfigured | [x] | [x] | [x] | [x] | [x] |
| pi-ntfy-notify.delivery-failures-are-non-fatal | [x] | [x] | [x] | [x] | [x] |
| pi-ntfy-notify.notifications-can-be-toggled | [x] | [x] | [x] | [x] | [x] |
