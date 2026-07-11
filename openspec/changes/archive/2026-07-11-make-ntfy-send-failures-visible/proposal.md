## Why

The pi ntfy extension makes send failures invisible twice over: both
dispatch call sites use `void sendNotification().catch(() => {})`, and
`sendNotification` never checks `r.ok`, so a non-2xx server reply counts as
success. On 2026-07-10 this cost ~3 hours of misdirected diagnosis — missing
phone notifications produced zero client-side evidence of whether sends were
attempted, failed, or succeeded. The existing `pi-ntfy-notify` spec
requirement "Delivery Failures Are Non-Fatal" currently mandates *swallowing*
the error; the frozen intent modifies it to *surface* failures while keeping
them non-fatal and non-blocking.

## What Changes

- `dot_pi/agent/extensions/ntfy/index.ts`:
  - `sendNotification` treats non-2xx responses as failures (check `r.ok`).
  - Every failed send (throw, timeout, or non-2xx) fires a pi TUI warning
    `ntfy send failed: <reason>` via `ctx.ui.notify(..., "warning")`
    (owner-settled every-failure policy); when no UI is available, the
    status/log surfaces still record it.
  - In-memory per-session send state: last success time, last failure time +
    error, success/failure counts — reported by `/ntfy status`.
  - Capped append-only send log in the extension directory (one line per
    attempt: timestamp, ok/fail, HTTP status or error; ~200KB order cap with
    simple truncate/rotate). Metadata only — no notification bodies beyond
    bounded metadata, no credentials or auth header values (Constitution
    III).
  - Fire-and-forget dispatch preserved: the turn path never awaits the
    network; only the reaction to the settled promise changes.
- `dot_pi/agent/extensions/ntfy/index.test.ts`: cover ok / non-2xx / throw
  paths, status state updates, and log capping.
- `pi-ntfy-notify` spec delta: MODIFIED "Delivery Failures Are Non-Fatal"
  (suppress → surface; non-fatal + non-blocking retained), ADDED
  requirements for failure-visibility surfaces and the capped send log.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `pi-ntfy-notify`: MODIFIED — "Delivery Failures Are Non-Fatal" becomes
  surface-not-suppress (failures remain non-fatal, non-blocking). ADDED —
  failure visibility surfaces (TUI warning on every failure, `/ntfy status`
  reporting) and capped send-log requirements; non-2xx responses SHALL count
  as delivery failures.

## Impact

Affected files:
- `dot_pi/agent/extensions/ntfy/index.ts`
- `dot_pi/agent/extensions/ntfy/index.test.ts`
- `openspec/changes/make-ntfy-send-failures-visible/specs/pi-ntfy-notify/spec.md`

Affects which projects: chezmoi only (extension source of truth,
Constitution I). Deployment is operational and outside the gate:
`chezmoi apply` then restart running pi sessions (they cache the extension
in memory). Non-goals per frozen intent: cross-provider excerpt extraction
(superseded), server-side ntfy work, retry/backoff, content/routing changes.
