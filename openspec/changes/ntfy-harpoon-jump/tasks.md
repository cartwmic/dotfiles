<!-- authored: in-session -->

## 1. Remote notify wrapper

- [ ] 1.1 Author the remote notify wrapper that stamps the stable zellij pane id
  into an ntfy notification. Reads `$ZELLIJ_PANE_ID` + `$ZELLIJ_SESSION_NAME`,
  optionally queries harpoon `slot_for_pane` for a display hint, sources ntfy
  topic/token/server + remote host from the environment (no literals), and
  degrades to a keyless notification when not inside a zellij pane.
  (specs: ntfy-jump-wiring "Remote notify wrapper embeds the stable pane id",
  "Wrapper config is secret-free and environment-sourced")
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_ntfy-zellij-notify.sh
  - allow_new_files: true

## 2. Phone ControlMaster config (Termux staging, not chezmoi-deployed)

- [ ] 2.1 Author the phone `~/.ssh/config` `ControlMaster` snippet for the remote
  host: `ControlMaster auto` + a `ControlPath` under a phone-writable dir +
  `ControlPersist`. Host/user reference storage location only (no secrets).
  (specs: "Phone ControlMaster config enables connection reuse",
  "Phone config is staged, not chezmoi-deployed")
  - intent: feature
  - files_allowed:
      - termux/ssh-controlmaster.config
  - allow_new_files: true

- [ ] 2.2 Extend `termux/sync.sh` to idempotently deliver the snippet: create the
  `ControlPath` parent dir on the phone, marker-guard the append into the phone
  `~/.ssh/config` so a second run makes no change (Constitution IV).
  (specs: "Install and sync are idempotent",
  "Phone ControlMaster config enables connection reuse")
  - intent: feature
  - files_allowed:
      - termux/sync.sh
  - allow_new_files: false

- [ ] 2.3 Document the ControlMaster snippet + push step in `termux/README.md`.
  - intent: feature
  - files_allowed:
      - termux/README.md
  - allow_new_files: false

## 3. Verification

- [ ] 3.1 Verify idempotence + shell correctness: `bash -n` both scripts; assert
  the sync marker-guard makes a second run a no-op (dry logic check). Record the
  result in verify.md.
  - intent: infra
  - files_allowed:
      - dot_local/bin/executable_ntfy-zellij-notify.sh
      - termux/sync.sh
      - termux/ssh-controlmaster.config
      - termux/README.md
  - allow_new_files: false
