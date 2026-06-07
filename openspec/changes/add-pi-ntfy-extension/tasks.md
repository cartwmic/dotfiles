## 1. Scaffolding

- [x] 1.1 Create extension dir `dot_pi/agent/extensions/ntfy/` with `index.ts` exporting a default factory `(pi: ExtensionAPI) => void` and a type-only import `import type { ExtensionAPI } from "@mariozechner/pi-coding-agent"`.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**
  - allow_new_files: true
- [x] 1.2 Add committed `dot_pi/agent/extensions/ntfy/config.json` with the plain URL value: `{ "url": "https://ntfy.internal.cartwmic.com/pi", "maxExcerptChars": 200 }`. (Non-secret: internal-only host.)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/config.json
  - allow_new_files: true

## 2. Config loading

- [x] 2.1 Implement `loadConfig()`: read `config.json` beside `index.ts`; if missing/unreadable, return a disabled config (no throw). (AC: pi-ntfy-notify.no-op-when-unconfigured)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**
  - allow_new_files: true
- [x] 2.2 Read `url` from config at extension init; treat empty/absent `url` as disabled (no throw). No secret resolution needed — the value is a plain URL (design D2). (AC: pi-ntfy-notify.no-op-when-unconfigured)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**

## 3. Notification assembly

- [x] 3.1 Implement `extractExcerpt(message, maxChars)`: take the last assistant message's response text only (exclude reasoning/thinking), collapse whitespace, truncate to `maxChars` with `…` indicator; empty/placeholder when no renderable text. (AC: pi-ntfy-notify.notification-includes-content-excerpt; clarify A3)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**
- [x] 3.2 Implement `buildNotification(ctx)`: title `pi ready: <getSessionName() ?? getSessionId().slice(0,8)>`; body `zellij:<ZELLIJ_SESSION_NAME> · <cwd> · <excerpt>`, omitting the zellij segment when the env var is unset. (AC: pi-ntfy-notify.notification-identifies-session; clarify A2, design D4)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**

## 4. Event wiring + delivery

- [x] 4.1 Register `pi.on("agent_end", ...)`. Guard: return early when `!ctx.isInteractive()`, when `event.willRetry`, or when config is disabled (no resolved url). (AC: pi-ntfy-notify.notify-on-turn-end, pi-ntfy-notify.no-op-when-unconfigured; design D1, D5; clarify I1)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**
- [x] 4.2 Deliver via global `fetch(url, { method:"POST", headers:{Title, Priority:"high", Tags:"robot"}, body, signal: AbortSignal.timeout(5000) })`, fire-and-forget with `.catch(() => {})`; never await in a way that delays `agent_end` return. (AC: pi-ntfy-notify.delivery-failures-are-non-fatal; design D3, R5)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**

## 5. Unit tests (pure helpers)

- [x] 5.1 Test `extractExcerpt` (truncation + indicator, whitespace collapse, no-text placeholder, reasoning excluded) and `buildNotification` (title fallback, zellij segment omitted when env unset). Cite AC IDs `pi-ntfy-notify.notification-includes-content-excerpt` and `pi-ntfy-notify.notification-identifies-session` in test names/comments.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**
      - "**/*.test.ts"

## 6. Manual verification + docs

- [x] 6.1 Author `verify.md`: `chezmoi apply` on remote, run `pi` interactively, complete a turn, confirm the phone ntfy app (subscribed to topic `pi` at `ntfy.internal.cartwmic.com`) receives a notification with correct session name + excerpt; plus the unconfigured no-op check (blank/missing url → no notification, no error).
  - intent: infra
  - files_allowed:
      - openspec/changes/add-pi-ntfy-extension/verify.md
- [x] 6.2 Note in the extension dir (header comment or short README) the prerequisites: ntfy server reachable at `ntfy.internal.cartwmic.com`, ntfy Android app subscribed to topic `pi`. (design Migration Plan, R1, R6)
  - intent: infra
  - files_allowed:
      - dot_pi/agent/extensions/ntfy/**
