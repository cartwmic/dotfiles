## 1. Spec delta

- [ ] 1.1 Author the `pi-ntfy-notify` delta spec: MODIFIED "Delivery
  Failures Are Non-Fatal" (surface-not-suppress, non-fatal + non-blocking
  retained), ADDED failure-visibility surfaces (every-failure TUI warning,
  `/ntfy status` reporting) and capped send-log requirements; non-2xx SHALL
  count as delivery failure
  - intent: feature
  - files_allowed:
      - openspec/changes/make-ntfy-send-failures-visible/specs/**
  - allow_new_files: true

## 2. Implementation

- [ ] 2.1 `sendNotification`: check `r.ok`; non-2xx becomes a failure
  carrying the HTTP status; keep the 5s abort; never log/record auth header
  values
  - intent: fix
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/index.ts
  - allow_new_files: false
- [ ] 2.2 Send-state tracking + failure reaction: in-memory per-session
  state (last success, last failure + error, counts); on every settled send
  update state, append a capped log line (extension dir, ~200KB truncate/
  rotate, metadata only), and on failure fire `ctx.ui.notify("ntfy send
  failed: <reason>", "warning")` when UI is available — dispatch stays
  fire-and-forget on the turn path (both call sites: agent_end and
  ask_user_question tool_execution_start)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/index.ts
  - allow_new_files: false
- [ ] 2.3 `/ntfy status`: report enabled/URL state plus last success, last
  failure + error, and session success/failure counts
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/index.ts
  - allow_new_files: false

## 3. Tests + validation

- [ ] 3.1 Extend `index.test.ts`: ok path, non-2xx path, thrown/timeout
  path, status-state updates, log capping behavior; suite green via
  `bun test dot_pi/agent/extensions/ntfy/` (agent-independent validation
  source)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/index.test.ts
      - dot_pi/agent/extensions/ntfy/index.ts
  - allow_new_files: false
