# Intent — ntfy-harpoon-jump (chezmoi slice)

Part of the cross-repo `ntfy-harpoon-jump` feature: tapping an ntfy notification
on the phone jumps the live remote zellij session to the exact tab/pane of the
alerting process. This slice owns the config + scripts. Sibling slices live in
`harpoon` (pipe primitives) and `termux-app` (phone-side intent + foreground).

Schema: opsx-superpowers. This intent.md is the frozen baseline; do not edit
without explicit human authorization.

## Intent

Provide the config and scripts that connect the alerting process to the phone:

1. **Remote notify wrapper** (deployed to the homelab remote): a script the
   alerting process calls to publish an ntfy notification stamped with its zellij
   location. It reads `$ZELLIJ_PANE_ID` and `$ZELLIJ_SESSION_NAME`, optionally
   queries harpoon `slot_for_pane` for display, and embeds the **stable pane id**
   so the phone can drive `jump_pane` on tap.
2. **Phone-side SSH ControlMaster config**: so the interactive `ssh → zellij`
   session becomes a reusable master connection, letting the tap-time side-channel
   exec ride the existing connection (no fresh login).

## Constraints

- The remote notify wrapper carries the stable pane id (not slot) as the jump key.
- ControlMaster config: `ControlMaster auto` + a `ControlPath` + `ControlPersist`
  so the interactive session is the master and side-channel `ssh` reuses it.
- Idempotent install: any deploy/install script re-run MUST be a no-op when
  already applied (Constitution IV).

## Invariants honored

- **Constitution VII — Termux config is NOT chezmoi-deployed.** The phone-side
  `~/.ssh/config` ControlMaster snippet MUST NOT ship as `dot_termux/` (rejected).
  It lives in the chezmoi repo's `termux/` staging dir and reaches the phone via
  the ADB-push `sync.sh` path, matching `termux/setup-ssh-key.sh`. It is
  intentionally NOT applied by `chezmoi apply`.
- **Constitution III — No secrets in source.** ntfy topic/token, remote host, and
  any credentials MUST come from env/1Password/templates, never literal values in
  the repo. Reference storage location only.
- **Constitution IV — idempotent install scripts** (`run_once_*`/`run_onchange_*`
  safe to re-run; second run produces no diff).
- **Constitution I** — remote-side config the user wants to persist is added to
  chezmoi at the correct source path for the homelab machine.
- **Constitution VIII** — the `openspec/` workspace itself is not chezmoi-deployed.

## Non-goals

- No harpoon plugin code (harpoon slice).
- No Android/termux-app fork code (termux-app slice).
- No new secret material; reuse the existing shared ed25519 key already on the phone.
- No change to Termux sshd/boot persistence behavior.
