## Memory: `mcp-memory` MCP server

You have access to a centralized long-term memory backend via the
`mcp-memory` MCP server (mcp-memory-service, served from
`mcp-memory.internal.cartwmic.com`). It is **shared across every agent
harness** the user runs (pi, Claude Code, Codex, future tools), so any
durable knowledge you record there will be available to your next session
*and* to other harnesses.

Treat `mcp-memory` as the canonical place for anything the user will want
remembered next time. The harness-local memory (CLAUDE.md, AGENTS.md,
APPEND_SYSTEM.md, this document) is for *instructions to you*; mcp-memory
is for *facts about the user, their projects, decisions, and environment*.

### When to retrieve (read)

- **Start of any non-trivial request**: call `mcp-memory.retrieve_memory`
  (or `mcp-memory.search_by_tag`) with terms from the user's intent before
  you answer. Surface anything material that would change your response.
- **Before making decisions with likely precedent** — architecture choices,
  library/tool preferences, naming conventions, environment quirks. Search
  first; don't relitigate something the user has already settled.
- **When the user references "the X we set up" / "remember the thing
  about Y"** — search for it explicitly rather than guessing.

### When to store (write)

Use `mcp-memory.store_memory` when:

- The user makes an explicit decision ("we're going with X over Y")
- The user expresses a stable preference ("always use ripgrep, not grep")
- You discover a non-obvious environmental fact (e.g. "this machine uses
  mise; python lives at `$HOME/.local/share/mise/...`")
- A fix or workaround required real investigation and would be wasteful
  to repeat
- The user shares context about a project, person, or tool that you'll
  plausibly want when they bring it up again

### Tagging convention

Use these prefixes consistently so future searches resolve cleanly:

- `project:<name>` — anything specific to one project
- `pref:<topic>` — user preferences (`pref:tooling`, `pref:style`)
- `decision:<topic>` — explicit decisions (`decision:memory-backend`)
- `learn:<topic>` — non-obvious facts you discovered
- `env:<machine-or-context>` — environmental specifics
- Multiple tags are fine and encouraged.

### What NOT to store

- Transient state — one-off file paths from a grep, command output, scratch
  IDs, "current branch is X" (it'll be wrong tomorrow)
- Trivia the user could re-derive in seconds
- Anything the user explicitly told you not to remember
- **Secrets, credentials, tokens, private personal info** — never. If
  recording the existence of a credential is useful, record only that it
  exists and where it's stored (e.g. "API key for X is in 1Password item
  Y"), never the secret value itself.

### Style

- Don't ask permission for routine recordings — store it and mention it
  briefly. "Noted that <x>" or "Stored: <x>" is sufficient.
- Ask only when the content is sensitive, unusually broad, or you're not
  sure whether it generalizes beyond the immediate context.
- If you're unsure whether something has been recorded already, search
  first before storing — duplicate-but-slightly-different memories are
  worse than an extra search call.
