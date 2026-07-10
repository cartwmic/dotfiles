## 1. Spec delta

- [ ] 1.1 Author the `ntfy-jump-wiring` delta spec (ADDED requirements:
  bounded side-channel session hold; warm-instance pipe targeting), tracing
  to intent.md constraints
  - intent: feature
  - files_allowed:
      - openspec/changes/harden-zellij-jump-transport/specs/**
  - allow_new_files: true

## 2. Implementation

- [ ] 2.1 Harden `termux/zellij-jump`: finite timeout (order 15s) wrapping the
  ssh invocation plus `ConnectTimeout`/`ServerAliveInterval`/
  `ServerAliveCountMax` options — backstop must be generous relative to
  connect + payload delivery (never plausibly fires before delivery)
  - intent: fix
  - files_allowed:
      - termux/zellij-jump
  - allow_new_files: false
- [ ] 2.2 Add warm-instance targeting to the pipe invocation:
  `--plugin-configuration` derived from the ground truth of the harpoon
  `LaunchOrFocusPlugin` block in `dot_config/zellij/config.kdl.tmpl` (if
  ground truth shows an empty plugin configuration, record that in review.md
  Execution Notes and implement the minimal explicit targeting that reaches
  the warm instance). Keep the explicit `--plugin` target; never broadcast
  - intent: fix
  - files_allowed:
      - termux/zellij-jump
  - allow_new_files: false
- [ ] 2.3 Update `termux/README.md`: document the transport bounds and the
  re-sync step (`termux/sync.sh`) needed to deliver the updated script
  - intent: feature
  - files_allowed:
      - termux/README.md
  - allow_new_files: false

## 3. Validation

- [ ] 3.1 Agent-independent validation: `sh -n termux/zellij-jump` and
  `shellcheck termux/zellij-jump` pass; record the commands as the validation
  source
  - intent: fix
  - files_allowed:
      - termux/zellij-jump
  - allow_new_files: false
