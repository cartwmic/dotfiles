<!-- authored: in-session -->
# Capability: ntfy-jump-wiring

## ADDED Requirements

### Requirement: Bounded side-channel session hold

THE phone-side jump script SHALL bound the lifetime of each tap-time
side-channel invocation with a finite timeout and ssh keepalive options, so a
remote `zellij pipe` client that hangs after payload delivery can occupy a
ControlMaster session slot for at most the bounded interval and can never
permanently exhaust the connection's session capacity.

#### Scenario: Remote pipe client hangs after delivery
- **WHEN** the remote `zellij pipe` invocation delivers its payload and then
  fails to terminate (client never released)
- **THEN** the side-channel invocation SHALL be terminated within the bounded
  interval
- **AND** the ControlMaster session slot it held SHALL be freed

#### Scenario: Backstop never preempts delivery
- **WHEN** the side-channel invocation is progressing normally (connection
  establishment plus payload delivery)
- **THEN** the bound SHALL be generous relative to that path (order tens of
  seconds), so the timeout only ever reaps a client whose jump work already
  completed

#### Scenario: Unreachable remote does not hold a slot indefinitely
- **IF** the remote is unreachable or the connection stalls mid-handshake
- **THEN** connect-timeout and keepalive options SHALL terminate the attempt
  within the bounded interval

### Requirement: Warm-instance pipe targeting

THE phone-side jump script SHALL target the `jump_pane` pipe at the harpoon
plugin instance launched by the zellij keybind (the warm instance), passing an
explicit `--plugin` target with the plugin configuration derived from the
keybind's `LaunchOrFocusPlugin` ground truth, and SHALL NOT broadcast the pipe.

#### Scenario: Tap pipe reaches the warm instance
- **WHEN** a tap-time `jump_pane` pipe is invoked while the keybind-launched
  harpoon instance is loaded
- **THEN** the pipe SHALL be delivered to that instance rather than spawning a
  second instance with a different configuration

#### Scenario: Broadcast remains forbidden
- **WHEN** the jump script invokes `zellij pipe`
- **THEN** it SHALL pass an explicit `--plugin` target (never a broadcast
  pipe), per the harpoon pane-pipe-api Targeted Pipe Delivery requirement
