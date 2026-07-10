# ntfy-jump-wiring Specification

## Purpose
TBD - created by archiving change ntfy-harpoon-jump. Update Purpose after archive.
## Requirements
### Requirement: Remote notify wrapper embeds the stable pane id

THE remote notify wrapper SHALL publish an ntfy notification that embeds the
pane's stable identifier read from `$ZELLIJ_PANE_ID` as the jump key when invoked
from inside a zellij pane, so the phone can drive harpoon `jump_pane` on tap.

#### Scenario: Invoked inside a zellij pane
- **WHEN** the wrapper runs with `$ZELLIJ_PANE_ID` set (form `terminal_N`)
- **THEN** the delivered notification carries that pane id as the jump key
- **AND** the notification carries `$ZELLIJ_SESSION_NAME` as the target session

#### Scenario: Invoked outside zellij
- **IF** `$ZELLIJ_PANE_ID` is unset (the process is not inside a zellij pane)
- **THEN** the wrapper SHALL still deliver the notification without a jump key
- **AND** SHALL NOT fail solely because the pane id is absent

#### Scenario: Optional harpoon slot display hint
- **WHEN** a harpoon `slot_for_pane` lookup for the current pane id succeeds
- **THEN** the wrapper MAY include the returned slot number as a display hint
- **AND** the absence or failure of that lookup SHALL NOT block delivery

### Requirement: Wrapper config is secret-free and environment-sourced

THE remote notify wrapper SHALL read the ntfy topic, any auth token, the ntfy
server URL, and the remote host from the environment or an external secret store,
and SHALL NOT contain any literal credential or topic value in the repository
(Constitution III).

#### Scenario: Configuration present
- **WHEN** the required configuration is available in the environment
- **THEN** the wrapper SHALL publish to the configured ntfy server and topic

#### Scenario: Required configuration missing
- **IF** a required configuration value is absent
- **THEN** the wrapper SHALL exit non-zero with a diagnostic naming the missing
  value and SHALL NOT emit a partially-formed notification

### Requirement: Phone ControlMaster config enables connection reuse

THE phone-side `~/.ssh/config` SHALL declare `ControlMaster auto`, a `ControlPath`,
and a `ControlPersist` value for the remote host, so the persistent interactive
`ssh → zellij` session is the master connection and tap-time side-channel `ssh`
invocations reuse it without a fresh login.

#### Scenario: Side-channel exec while the master is live
- **WHEN** the interactive master session to the remote host is active
- **AND** a tap-time side-channel `ssh` to the same host runs the `jump_pane` pipe
- **THEN** the side-channel connection SHALL multiplex over the existing master
- **AND** SHALL NOT establish a new authenticated login

#### Scenario: ControlPath parent directory absent
- **IF** the directory holding the `ControlPath` socket does not yet exist
- **THEN** the install path SHALL create it so the master socket can bind

### Requirement: Phone config is staged, not chezmoi-deployed

THE phone `ControlMaster` snippet SHALL live under the repository's `termux/`
staging directory and reach the device via the ADB `sync.sh` path, and SHALL NOT
be authored under `dot_termux/` nor applied by `chezmoi apply` (Constitution VII).

#### Scenario: Snippet delivery path
- **WHEN** the phone config is delivered to the device
- **THEN** it SHALL be pushed by the `termux/` ADB sync mechanism
- **AND** no `dot_termux/` source path SHALL be introduced

### Requirement: Install and sync are idempotent

THE install/sync path SHALL be idempotent for both the remote wrapper and the
phone `ControlMaster` snippet: a second run against an already-applied target
SHALL produce no diff and SHALL exit success without duplicating configuration
(Constitution IV).

#### Scenario: Re-run against applied state
- **WHEN** the sync/install runs a second time with the target already applied
- **THEN** it SHALL make no change and SHALL exit success

#### Scenario: Managed block already present in phone config
- **IF** the sync's managed, sentinel-fenced `ControlMaster` block is already
  present in the phone `~/.ssh/config` from a prior run of this script
- **THEN** the sync SHALL NOT append a duplicate block

<!-- Scope note: idempotence is bounded to THIS script's own prior application
(Constitution IV: "no-op when already applied"). Detecting and reconciling an
UNMANAGED, hand-written pre-existing ControlMaster stanza for the host is a
non-goal here — robustly parsing arbitrary ssh config from an adb run-as toybox
shell is disproportionate and defect-prone; routed to follow-ups.md, surfaced to
the user via termux/README.md. -->

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

