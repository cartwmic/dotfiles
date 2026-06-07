## Why

When pi runs on a remote PC (phone → Termux → SSH → zellij → pi), the assistant finishes a turn and silently waits for input; the user on Android has no signal that a session is awaiting them, nor which session it is. A local pi extension on the `agent_end` hook can push an [ntfy](https://ntfy.sh) notification carrying the session identity and a content excerpt, decoupled from SSH/zellij liveness via a separate push channel.

## What Changes

- Add a local pi extension at `dot_pi/agent/extensions/ntfy/index.ts` (auto-discovered like the existing `web-search`/`subagent` extensions; no `settings.json` entry needed).
- Subscribe to `agent_end`; on **every** turn end, POST to a self-hosted ntfy topic via Node's global `fetch` (no `curl` subprocess, no runtime deps).
- Notification carries: title = pi session name (fallback to short session id) + zellij session name; body = excerpt of the last assistant message (truncated, text-only).
- Read the ntfy URL from an extension config file (`config.json` beside `index.ts`); extension no-ops cleanly when unconfigured/missing.
- The ntfy URL (`https://ntfy.internal.cartwmic.com/pi`) is an internal-only, non-externally-reachable host — **not a secret** — so it is committed directly as a plain value in `config.json`. No 1Password/secret injection needed (Constitution **Principle III** is not engaged). Extension still lives under chezmoi (**Principle I**).
- Guards: skip when `!ctx.hasUI` (print/json mode) and when `event.willRetry` (auto-retry ≠ awaiting input). All network calls fire-and-forget with error swallow so they never block or crash a turn.
- Self-hosted ntfy server (`ntfy.internal.cartwmic.com`); excerpts contain conversation text and never leave the internal network.

## Capabilities

### New Capabilities
- `pi-ntfy-notify`: A local pi extension that, on each assistant turn end, pushes a self-hosted ntfy notification identifying the session and excerpting the assistant's last message, so a remote user knows when and which pi session awaits input.
<!-- Note: requirement "Channel Secret Excluded From Source" was dropped after the user confirmed the internal-only ntfy URL is not a secret. -->

### Modified Capabilities
<!-- None. Additive standalone extension; no existing capability spec changes. -->

## Impact

- **New files**:
  - `dot_pi/agent/extensions/ntfy/index.ts` → deploys to `~/.pi/agent/extensions/ntfy/index.ts`.
  - `dot_pi/agent/extensions/ntfy/config.json` → deploys to `~/.pi/agent/extensions/ntfy/config.json`; plain committed value `{ "url": "https://ntfy.internal.cartwmic.com/pi", "maxExcerptChars": 200 }`.
- **Dependencies**: none new. Type-only `import type { ExtensionAPI } from "@mariozechner/pi-coding-agent"` (erased at runtime, matches repo convention); Node 24 global `fetch`.
- **Runtime**: one `agent_end` handler; one HTTP POST per turn while configured; negligible cost; failures non-fatal.
- **External systems**: the self-hosted ntfy server at `ntfy.internal.cartwmic.com` (alongside `mcp-memory.internal.cartwmic.com`) and the ntfy Android app subscribed to topic `pi`. Server provisioning is **out of scope** (assumed available).
- **Constitution**: Principle I (extension under chezmoi). Principle III not engaged (URL is internal-only, not a secret). Principle VII (Termux not chezmoi-deployed) — no Termux-side files; phone uses the GUI ntfy app.
- **Affects which projects**: dotfiles repo only; benefits any remote pi session on a host with the rendered config.
- **Out of scope / non-goals**: provisioning the ntfy server; secret/credential handling (URL is non-secret); per-session notification dedup/replace; walked-away/elapsed-threshold suppression (user chose every-turn); click-to-attach deep-linking; tap actions.
