<!-- authored: in-session -->

## Why

The cross-repo `ntfy-harpoon-jump` feature lets a phone ntfy tap jump the live
remote zellij session to the exact pane of the alerting process. The `harpoon`
slice (pane-pipe-api) and `termux-app` slice (notification-jump) already shipped
GATE-PASS; this chezmoi slice owns the connective tissue: the remote-side notify
wrapper that stamps the stable pane id into the notification, and the phone-side
SSH `ControlMaster` config that lets the tap-time side-channel `ssh` ride the
existing interactive connection. Motivated by the frozen `intent.md`; bounded by
Constitution III (no secrets), IV (idempotent installs), VII (Termux config is
not chezmoi-deployed), and I/VIII (source-path + workspace rules).

## What Changes

- Add a **remote notify wrapper** script (deployed to the homelab remote) that the
  alerting process calls to publish an ntfy notification stamped with its zellij
  location. It reads `$ZELLIJ_PANE_ID` (stable, form `terminal_N`) and
  `$ZELLIJ_SESSION_NAME`, optionally queries harpoon `slot_for_pane` for a display
  hint, and embeds the pane id as the jump key so the phone can drive `jump_pane`.
- Add a **phone-side SSH `ControlMaster` config** snippet (`ControlMaster auto` +
  `ControlPath` + `ControlPersist`) so the persistent interactive `ssh → zellij`
  session becomes the reusable master and side-channel `ssh` invocations reuse it
  with no fresh login. It lives in the chezmoi repo's `termux/` staging dir and
  reaches the phone via the ADB `sync.sh` path — **never** `dot_termux/`, never
  `chezmoi apply` (Constitution VII).
- Wire an **idempotent install/sync path** for both artifacts: re-running produces
  no diff (Constitution IV). Config values (ntfy topic/token, remote host, server
  URL) are sourced from environment/1Password, never literals (Constitution III).

## Capabilities

### New Capabilities
- `ntfy-jump-wiring`: the chezmoi-owned remote notify wrapper + phone
  `ControlMaster` config that connects the alerting process to the phone's
  tap-time side-channel jump, plus their idempotent, secret-free install path.

### Modified Capabilities
<!-- none — this is net-new connective config; pi-ntfy-notify (agent_end pi
extension notifications) is a distinct capability and is not modified. -->

## Impact

- **Affects which projects:** chezmoi slice only. Sibling behavior lives in
  `harpoon` (pane-pipe-api) and `termux-app` (notification-jump), already shipped.
- **Affected files (anticipated):**
  - `termux/ssh-controlmaster.config` (new) — the phone `~/.ssh/config`
    ControlMaster snippet, staged (not chezmoi-deployed).
  - `termux/sync.sh` (modified) — extend to push the ControlMaster snippet into
    the phone `~/.ssh/config` idempotently (append-once / marker-guarded).
  - `termux/README.md` (modified) — document the ControlMaster snippet + push step.
  - remote notify wrapper script at the homelab-machine chezmoi source path
    (new) — the wrapper the alerting process calls.
- **Dependencies:** relies on the shipped harpoon `jump_pane` / `slot_for_pane`
  pipes and the existing shared ed25519 key already on the phone. No new secrets.
