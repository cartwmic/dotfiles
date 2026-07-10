## Why

Incident 2026-07-08→10: every ntfy tap ran `termux/zellij-jump`, whose remote
`zellij pipe --name jump_pane` client hung forever (harpoon missing
`ReadCliPipes` → client never released). Each hung client held one ssh
side-channel session on the phone's single ControlMaster connection; sshd
default `MaxSessions 10` was exhausted after ~9 taps ("Session open refused")
and notification jumps went completely dead at the transport layer. The jump
itself always completed at payload delivery — only the post-delivery release
handshake hung, and nothing in this chain consumes its output. This change
makes that failure class unrepeatable phone-side (Constitution IV, VII; the
harpoon-side root fix is the separate `request-read-cli-pipes-permission`
change in ~/git/harpoon).

## What Changes

- `termux/zellij-jump`: wrap the ssh side-channel invocation in a finite
  timeout (order 15s — generous vs connect + payload delivery, backstop only)
  plus ssh keepalive/connect options (`ConnectTimeout`, `ServerAliveInterval`,
  `ServerAliveCountMax`) so a hung remote pipe client can hold a ControlMaster
  session slot for bounded seconds, never forever.
- `termux/zellij-jump`: target the warm keybind-launched harpoon instance —
  `--plugin-configuration` matching the plugin configuration of the
  `LaunchOrFocusPlugin` harpoon block in `dot_config/zellij/config.kdl.tmpl`
  (value derived from that ground truth, not guessed; broadcast pipes remain
  forbidden per harpoon pane-pipe-api "Targeted Pipe Delivery"). This is the
  follow-up explicitly deferred to this repo by the harpoon
  `fix-cross-tab-fullscreen-normalization` frozen scope (item 8).
- `termux/README.md`: document the new transport bounds and re-sync step.
- `ntfy-jump-wiring` spec delta: side-channel invocations SHALL have a bounded
  session hold; tap pipes SHALL target the warm plugin instance.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `ntfy-jump-wiring`: ADDED requirements — bounded side-channel session hold
  (a hung remote client cannot permanently occupy a ControlMaster session
  slot) and warm-instance pipe targeting.

## Impact

Affected files:
- `termux/zellij-jump` (staged, ADB `sync.sh` delivery — NOT chezmoi-applied,
  Constitution VII)
- `termux/README.md`
- `openspec/changes/harden-zellij-jump-transport/specs/ntfy-jump-wiring/spec.md`
  (delta)

Affects which projects: chezmoi only. Complements (does not touch) the harpoon
`request-read-cli-pipes-permission` change; no termux-app fork changes
(session routing explicitly out of scope per intent.md Non-goals). Deployment
to the phone (running `termux/sync.sh`) is operational and outside this
change's gate.
