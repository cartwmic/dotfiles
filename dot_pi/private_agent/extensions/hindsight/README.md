# hindsight — pi extension

Automatic long-term memory for pi backed by a self-hosted
[Hindsight](https://hindsight.vectorize.io) server
(`hindsight-api.internal.cartwmic.com`). Bank is profile-gated:
`axon-work-computer` → `work`, otherwise → `cartwmic`.

This is the **reliable** path Hindsight recommends — hooks, not relying on the
model to call MCP tools. The `hindsight` MCP server (registered in
`agent-harness/canonical/mcp/servers.json.tmpl`) still gives the model explicit
`recall` / `reflect` / `retain` tools; this extension makes the common case
automatic, mirroring the official Claude Code plugin's hook design.

## Behavior

| Hook | Trigger | Action |
|------|---------|--------|
| Auto-recall | `before_agent_start` (once per user prompt) | `recall` relevant memories, inject as a hidden `role:"custom"` `<hindsight_memories>` message — model sees it, transcript doesn't |
| Auto-retain | `agent_end` (per response cycle) | Buffer that run's messages; every `retainEveryNTurns` cycles, append them to the session document (fire-and-forget) |
| Final flush | `session_shutdown` | One awaited retain of anything still buffered |

- **Recall query:** the prompt, then the first 300 characters of the previous
  assistant reply as context, so prompts like "is this rule fine?" or
  "continue" find the current topic. The prompt stays first so a topic switch
  still wins. Prompts sent by an extension (for example the compaction
  "continue" message) are boilerplate, so only the context is searched.
- **Retain:** `agent_end` carries only that run's messages, so runs are
  buffered and appended (`update_mode: "append"`, which also creates a
  missing document) to `pi-session-<id>`. Never replace a session document
  with partial messages: replace deletes every earlier memory from it. Sends
  run one at a time; each batch keeps its `operation_id` across retries, so a
  lost acknowledgement is not appended twice. Outages, timeouts, 408/429 and
  5xx are retried later; only a batch rejected as invalid (other 4xx) three
  times is dropped. Shutdown waits for an in-flight send, then ships the rest.
- **Subagents and workers:** children (`PI_SUBAGENT_CHILD=1`) and headless
  print/JSON runs (no UI, such as Loop Engine workers) neither recall nor
  retain. The parent session captures their outcome; their transcripts used
  to flood the bank. Explicit MCP `recall`/`retain` still work everywhere.

- **Transport:** Hindsight REST directly (`POST …/banks/<bankId>/memories/recall`,
  `…/memories`). No per-turn MCP handshake.
- **Feedback-loop guard:** injected `<hindsight_memories>` blocks are stripped
  from both the recall query and the retained transcript.
- **Scoping:** retains are tagged `session:<id>` + `project:<repo>`, where
  `<repo>` is the main git checkout's directory name (worktrees and
  subdirectories share it; outside git, the cwd basename). Retains use
  `observation_scopes: "shared"` so observations consolidate across sessions
  instead of one scope per session tag. Recall is semantic (no tag filter) so
  global preferences still surface.
- **Resilience:** every network path is wrapped — a memory failure never blocks
  or crashes a turn.

## Commands

- `/hindsight [on | off | toggle | status]` — runtime toggle. The override is
  persisted to a sidecar `state.json` (not chezmoi-managed) so live toggling
  never drifts the source.

## Config

`config.json.tmpl` (chezmoi-managed). Every value also overridable via env:
`HINDSIGHT_API_URL`, `HINDSIGHT_API_TOKEN`, `HINDSIGHT_BANK_ID`,
`HINDSIGHT_AUTO_RECALL=false`, `HINDSIGHT_AUTO_RETAIN=false`,
`HINDSIGHT_DEBUG=true`.

| Key | Default | Notes |
|-----|---------|-------|
| `apiUrl` | `https://hindsight-api.internal.cartwmic.com` | Base REST URL |
| `bankId` | profile-gated | `work` when `.profile == axon-work-computer`, else `cartwmic` |
| `apiToken` | `""` | Bearer; empty = no auth (current state). Set when server auth lands. |
| `autoRecall` / `autoRetain` | `true` | Master switches |
| `recallBudget` | `mid` | `low`/`mid`/`high` — search effort vs latency |
| `recallTypes` | `["observation","world","experience"]` | Observations plus raw facts; recall sends `prefer_observations: true`, so a fact already merged into a returned observation is dropped and only unmerged facts appear |
| `recallMaxTokens` | `1024` | Injected block size cap |
| `retainEveryNTurns` | `10` | Ship cadence (response cycles) |
| `retainToolCalls` | `false` | Include tool calls in transcript |
| `requestTimeoutMs` | `30000` | Per-call timeout |

## Auth (when the server gets it)

Set `apiToken` (or `HINDSIGHT_API_TOKEN`) — sent as `Authorization: Bearer …`.
Prefer wiring the token through the chezmoi 1Password flow rather than committing
it to `config.json`.

## Tests

```bash
node --test dot_pi/private_agent/extensions/hindsight/index.test.ts
```
