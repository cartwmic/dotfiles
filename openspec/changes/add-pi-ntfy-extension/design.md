## Context

Pi runs on a remote PC reached via `phone → Termux → SSH → zellij → pi`. On `agent_end` pi silently awaits input; the remote user has no signal. This change adds a local, auto-discovered pi extension that pushes an [ntfy](https://ntfy.sh) notification per prompt completion, carrying session identity + a content excerpt.

Constraints from `openspec/constitution.md` and `openspec/domain.md`:
- **Principle I** (chezmoi single source of truth): the extension is deployed to `~/.pi`, so its source MUST live under `dot_pi/agent/extensions/` (domain entity: source-prefix `dot_<name>/ → ~/.<name>/`).
- **Principle III** (no secrets in source): NOT engaged. The ntfy URL `https://ntfy.internal.cartwmic.com/pi` is an internal-only, non-externally-reachable host; the user confirmed it is not a secret. It is committed as a plain value in `config.json`. (Existing `!op read` convention in `models.json.tmpl` remains available for genuine secrets but is not needed here.)
- **Principle VII** (Termux not chezmoi-deployed): nothing ships to the phone via chezmoi; the phone subscribes through the ntfy Android app (GUI). No `dot_termux/`.
- Pi-extension convention (from installed `dot_pi/agent/extensions/web-search`): type-only `import type { ExtensionAPI } from "@mariozechner/pi-coding-agent"` (erased at runtime, never resolved by jiti); Node built-ins available; Node 24 provides global `fetch`.

## Goals / Non-Goals

**Goals:**
- One push notification per `agent_end` in interactive sessions, decoupled from SSH/zellij liveness.
- Notification identifies the session (pi name + zellij name) and excerpts the last assistant response.
- Zero secrets in source; zero new runtime dependencies; never block or crash a turn.

**Non-Goals:**
- Provisioning the self-hosted ntfy server (assumed available near `*.internal.cartwmic.com`).
- Per-session dedup/replace, elapsed-threshold suppression, tap-to-attach deep-linking.
- Cross-harness reuse (claude/codex) — this is a pi extension only.

## Decisions

### D1: Trigger on `agent_end`, not `turn_end`

**Choice:** Subscribe to `agent_end` (fires once per user prompt, when the agent returns to awaiting input).

**Alternatives considered:**
- **`turn_end`**: fires per internal LLM turn including mid-tool-call. Produces multiple buzzes per prompt while pi is still working — contradicts the "awaiting input" goal.
- **`message_end` filtered to assistant**: similar over-firing; also fires mid-stream sequences.

**Rationale:** `agent_end` is the awaiting-input boundary (clarify A1). Payload `{ messages, willRetry }` gives the excerpt source and the retry guard.

**4-point test:** multiple approaches ✓; lasting (defines core behavior) ✓; reasonable disagreement ✓ ("every turn" literally); future-constraint ✓ → **ADR candidate: Y.**

### D2: Commit the ntfy URL as a plain config value (no secret handling)

**Choice:** Commit `dot_pi/agent/extensions/ntfy/config.json` with the URL as a literal value:
```json
{ "url": "https://ntfy.internal.cartwmic.com/pi", "maxExcerptChars": 200 }
```
No secret resolution, no template, no 1Password. The extension reads the value verbatim.

**Alternatives considered:**
- **`!op read` in-config / chezmoi `.tmpl` injection** (earlier draft): warranted only if the URL were a secret. The user confirmed the internal-only host is not externally reachable and not a secret, so this is unnecessary complexity.
- **Env var `PI_NTFY_URL`**: rejected — user chose a settings-config file, and a plain committed value is version-controlled and reproducible across machines (Principle I).

**Rationale:** simplest correct option once the secret constraint is gone; the URL is reproducible config, belongs in chezmoi, and needs no runtime resolution.

**4-point test:** multiple approaches ✓; lasting △; disagreement ✗; future-constraint ✗ → ADR candidate: N (now a plain config detail).

### D3: Transport via Node global `fetch`, fire-and-forget

**Choice:** `fetch(url, { method: "POST", headers, body })` with `.catch(() => {})`; no `await` that gates `agent_end` return.

**Alternatives considered:**
- **`curl` subprocess**: extra process per turn; relies on `curl` presence.
- **`node:https`**: more code than global `fetch`.

**Rationale:** Node 24 has global `fetch`; zero deps. Fire-and-forget satisfies `delivery-failures-are-non-fatal` and "never block the turn."

**4-point test:** multiple ✓; lasting △; disagreement △; future-constraint ✗ → ADR candidate: N (implementation detail).

### D4: Notification shape

**Choice:**
- ntfy headers: `Title: pi ready: <pi-session-name>`; `Priority: high`; `Tags: robot`.
- Body: `zellij:<name> · <cwd> · <excerpt>` where `<excerpt>` = last assistant **response** text (reasoning excluded per clarify A3), truncated to `maxExcerptChars` with a `…` indicator.
- pi session name from `ctx.sessionManager.getSessionName()`, fallback `getSessionId().slice(0,8)` (clarify A2). zellij segment from `process.env.ZELLIJ_SESSION_NAME`, omitted when unset.

**Alternatives considered:** title vs body field split variations; including reasoning text (rejected, clarify A3, more leak).

**Rationale:** satisfies identify-session + content-excerpt ACs; degrades gracefully without a multiplexer.

**4-point test:** multiple ✓; lasting △; disagreement △; future-constraint ✗ → ADR candidate: N.

### D5: Guards and no-op semantics

**Choice:** Skip delivery when `!ctx.hasUI` (print/json), when `event.willRetry`, and when no resolved `url` (unconfigured). Registration always succeeds.

**Rationale:** directly encodes `notify-on-turn-end` preconditions, `no-op-when-unconfigured`, and clarify I1 (unconfigured precedence). `willRetry` excludes non-awaiting boundaries.

**4-point test:** multiple ✗ → ADR candidate: N.

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | Excerpt content exposure | Low | Low | ntfy host is internal-only / not externally reachable; response-only excerpt (A3); bounded length |
| R4 | Every-turn firing is noisy in fast back-and-forth | Medium | Low | Accepted by user decision; future elapsed-threshold is a non-goal |
| R5 | `fetch` hang holds a socket | Low | Low | Fire-and-forget + `AbortSignal.timeout(5000)` on the request |
| R6 | Host on a different network can't reach the internal ntfy URL | Medium | Low | `delivery-failures-are-non-fatal`: unreachable → swallowed, turn unaffected |

## Migration Plan

1. Add `dot_pi/agent/extensions/ntfy/index.ts` + `config.json` (plain URL `https://ntfy.internal.cartwmic.com/pi`) to chezmoi source.
2. `chezmoi apply` on the remote host → extension auto-discovered on next `pi` launch.
3. Install + subscribe the ntfy Android app to topic `pi` on `ntfy.internal.cartwmic.com`.
4. **Rollback:** delete the extension dir (or blank the config `url`) → extension no-ops. No state to unwind.

## Open Questions

- None blocking. ntfy server at `ntfy.internal.cartwmic.com` assumed provisioned (out of scope).
