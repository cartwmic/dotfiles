# Intent — harden-zellij-jump-transport

**Status:** FROZEN (explore concluded 2026-07-10)
**Recommended Scale:** S, `full_rigor: false`

## Intent

Incident 2026-07-08→10: each ntfy notification tap ran
`termux/zellij-jump`, whose remote `zellij pipe --name jump_pane` client
hung forever (harpoon missing `ReadCliPipes` → client never released).
Every hung client held one ssh side-channel session open on the phone's
single ControlMaster connection; sshd default `MaxSessions 10` was
exhausted after ~9 taps ("Session open refused") and notification jumps
went completely dead at the transport layer. The jump itself always
completed at payload delivery — the hang was only the post-delivery
release handshake, whose output nothing in this chain consumes.

Harden the phone-side script so this failure class is unrepeatable: (1) a
finite timeout + ssh keepalive options bound the worst-case mux-slot hold
to seconds instead of forever; (2) pass `--plugin-configuration` so tap
pipes reach the warm keybind-launched harpoon instance instead of spawning
a configuration-less twin — the follow-up explicitly deferred to this repo
by the harpoon `fix-cross-tab-fullscreen-normalization` frozen scope
(item 8).

## Constraints

- Changes confined to the `termux/` staging directory (`zellij-jump`,
  README as needed) delivered via the ADB `sync.sh` path — NOT authored
  under `dot_termux/`, NOT applied by `chezmoi apply` (Constitution VII;
  ntfy-jump-wiring "Phone config is staged, not chezmoi-deployed").
- The timeout is a backstop, not a deadline for the jump: it must be
  generous relative to ssh connect + pipe payload delivery on a cold/slow
  link (order 15s), so it can only ever kill a client whose useful work
  (focus change at delivery) already completed. It must never plausibly
  fire before delivery.
- Warm-instance targeting: `--plugin-configuration` value is determined
  against the ground truth of the keybind `LaunchOrFocusPlugin` block in
  `dot_config/zellij/config.kdl.tmpl` (harpoon launcher), not guessed.
  Broadcast pipes (no `--plugin` target) remain forbidden — harpoon
  pane-pipe-api "Targeted Pipe Delivery" (double-instance double-toggle
  hazard).
- Spec delta required in `openspec/specs/ntfy-jump-wiring/spec.md`:
  side-channel invocations SHALL have a bounded session hold (hung remote
  client cannot permanently occupy a ControlMaster session slot), and tap
  pipes SHALL target the warm plugin instance.
- Sync/install remains idempotent (Constitution IV; existing
  ntfy-jump-wiring idempotence requirement).
- No secrets in source (Constitution III): no topics, tokens, or hosts
  hardcoded beyond the existing `remote` ssh alias indirection.

## Invariants honored

- Constitution III (No secrets in source).
- Constitution IV (Every install script is idempotent).
- Constitution VII (Termux config is not chezmoi-deployed).
- ntfy-jump-wiring existing requirements: ControlMaster reuse, staged
  delivery path, idempotent sync — all preserved; this change adds bounds,
  it does not reroute.
- harpoon pane-pipe-api "Targeted Pipe Delivery": explicit `--plugin`
  target kept, broadcast never introduced.

## Non-goals

- Session routing: parsing the `?session=` hint and passing `-s` — needs a
  matching termux-app fork handler change (handler discards the query
  today); explicitly out of scope, cross-repo.
- Harpoon plugin code or specs (separate change
  `request-read-cli-pipes-permission` in ~/git/harpoon).
- sshd `MaxSessions` or server-side ssh configuration.
- ntfy wrapper (`dot_local/bin/executable_ntfy-zellij-notify.sh`) or pi
  ntfy extension changes.
- termux-app fork changes or APK work.
