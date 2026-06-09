# hindsight — pi extension

Automatic long-term memory for pi backed by a self-hosted
[Hindsight](https://hindsight.vectorize.io) server
(`hindsight-api.internal.cartwmic.com`, bank `cartwmic`).

This is the **reliable** path Hindsight recommends — hooks, not relying on the
model to call MCP tools. The `hindsight` MCP server (registered in
`agent-harness/canonical/mcp/servers.json.tmpl`) still gives the model explicit
`recall` / `reflect` / `retain` tools; this extension makes the common case
automatic, mirroring the official Claude Code plugin's hook design.

## Behavior

| Hook | Trigger | Action |
|------|---------|--------|
| Auto-recall | `before_agent_start` (once per user prompt) | `recall` relevant memories, inject as a hidden `role:"custom"` `<hindsight_memories>` message — model sees it, transcript doesn't |
| Auto-retain | `agent_end` (per response cycle) | Every `retainEveryNTurns` cycles, ship a full-session transcript (fire-and-forget) |
| Final flush | `session_shutdown` | One awaited retain so the last cycles are captured |

- **Transport:** Hindsight REST directly (`POST …/banks/cartwmic/memories/recall`,
  `…/memories`). No per-turn MCP handshake.
- **Feedback-loop guard:** injected `<hindsight_memories>` blocks are stripped
  from both the recall query and the retained transcript.
- **Scoping:** retains are tagged `session:<id>` + `project:<cwd-basename>`.
  Recall is semantic (no tag filter) so global preferences still surface.
- **Resilience:** every network path is wrapped — a memory failure never blocks
  or crashes a turn.

## Commands

- `/hindsight [on | off | toggle | status]` — runtime toggle. The override is
  persisted to a sidecar `state.json` (not chezmoi-managed) so live toggling
  never drifts the source.

## Config

`config.json` (chezmoi-managed). Every value also overridable via env:
`HINDSIGHT_API_URL`, `HINDSIGHT_API_TOKEN`, `HINDSIGHT_BANK_ID`,
`HINDSIGHT_AUTO_RECALL=false`, `HINDSIGHT_AUTO_RETAIN=false`,
`HINDSIGHT_DEBUG=true`.

| Key | Default | Notes |
|-----|---------|-------|
| `apiUrl` | `https://hindsight-api.internal.cartwmic.com` | Base REST URL |
| `bankId` | `cartwmic` | Path-pinned bank |
| `apiToken` | `""` | Bearer; empty = no auth (current state). Set when server auth lands. |
| `autoRecall` / `autoRetain` | `true` | Master switches |
| `recallBudget` | `mid` | `low`/`mid`/`high` — search effort vs latency |
| `recallTypes` | `["observation"]` | Consolidated, deduped beliefs |
| `recallMaxTokens` | `1024` | Injected block size cap |
| `retainEveryNTurns` | `10` | Ship cadence (response cycles) |
| `retainToolCalls` | `false` | Include tool calls in transcript |
| `requestTimeoutMs` | `12000` | Per-call timeout |

## Auth (when the server gets it)

Set `apiToken` (or `HINDSIGHT_API_TOKEN`) — sent as `Authorization: Bearer …`.
Prefer wiring the token through the chezmoi 1Password flow rather than committing
it to `config.json`.

## Tests

```bash
node --test dot_pi/agent/extensions/hindsight/index.test.ts
```
