# Intent — make-ntfy-send-failures-visible

**Status:** FROZEN (explore concluded 2026-07-10)
**Recommended Scale:** S, `full_rigor: false`

## Intent

The pi ntfy extension (`dot_pi/agent/extensions/ntfy/index.ts`) makes send
failures invisible twice over: dispatch is `void sendNotification().catch(()
=> {})` (both call sites — `agent_end` and the `ask_user_question`
`tool_execution_start` path), and `sendNotification` never checks the
response's `r.ok`, so a non-2xx server reply counts as success. On
2026-07-10 this cost roughly three hours of misdirected diagnosis: missing
phone notifications produced zero client-side evidence of whether sends were
attempted, failed, or succeeded, forcing inference from unreliable
server-side poll reads.

Make every send failure observable — without ever blocking or delaying the
turn. Three surfaces, all settled with the owner: (1) a pi TUI warning on
EVERY failed send (owner explicitly chose every-failure over
transition-based or once-per-session), (2) `/ntfy status` enriched with last
success, last failure + error, and session counts, (3) a capped append-only
send log in the extension directory (one line per attempt: timestamp,
ok/fail, HTTP status or error). Non-2xx responses count as failures.

## Constraints

- Code confined to the ntfy extension source (`dot_pi/agent/extensions/ntfy/`
  — index.ts + index.test.ts) plus the `pi-ntfy-notify` delta spec.
- Fire-and-forget dispatch is PRESERVED: the failure-handling reaction
  changes; dispatch never awaits the network on the turn path, never blocks,
  delays, or aborts the turn (existing "Delivery never blocks the turn"
  scenario stays intact).
- Spec delta MODIFIES `pi-ntfy-notify` "Delivery Failures Are Non-Fatal":
  failures remain non-fatal and non-blocking, but "SHALL suppress/swallow"
  becomes "SHALL surface" (warning + status + log). ADDED requirements cover
  failure visibility surfaces and the capped send log. Non-2xx SHALL be
  treated as delivery failure.
- TUI warning uses the extension context notify surface (`ctx.ui.notify(...,
  "warning")`) and fires on every failure; when no UI is available (print
  mode), the log/status surfaces still record the failure.
- Send log: append-only in the extension directory, size-capped (~200KB
  order) with a simple truncate/rotate; MUST NOT record notification body
  content beyond bounded metadata and MUST NOT record credentials or auth
  header values (Constitution III).
- In-memory status state is per-session; the log is the only persistence.
- Tests: extend the existing `index.test.ts` suite (agent-independent
  validation source) covering ok/non-2xx/throw paths and log capping.
- Deployment reality documented, outside gate: `chezmoi apply` + pi session
  restart required for running sessions to pick up the new extension.

## Invariants honored

- Constitution I (chezmoi is source of truth): change lands at the
  `dot_pi/agent/extensions/ntfy/` source path, deployed by chezmoi apply.
- Constitution III (no secrets in source or logs): send log records
  metadata only, never tokens/headers.
- Constitution VIII (openspec workspace not chezmoi-deployed).
- pi-ntfy-notify existing requirements: turn-end notify, session identity,
  excerpt, no-op-when-unconfigured, toggle — all preserved; only the
  failure-suppression clause is modified as stated above.

## Non-goals

- Cross-provider excerpt extraction: SUPERSEDED as unnecessary — owner
  confirmed GPT sessions deliver correct bodies (2026-07-10); the earlier
  "(no text)" finding was stale/conflated.
- Server-side ntfy work (k8s pod confirmed healthy, zero errors since
  2026-07-04 launch; the split-brain cache observation is a separate
  operational thread).
- Notification content, routing, topics, or Click deep-link changes.
- Retry/backoff or delivery guarantees — visibility only.
- ntfy-jump-wiring / phone-side anything.
