## Memory: `mcp-memory` MCP server

You have access to a centralized long-term memory backend via the
`mcp-memory` MCP server (mcp-memory-service, served from
`mcp-memory.internal.cartwmic.com`). It is **shared across every agent
harness** the user runs (pi, Claude Code, Codex, future tools), so any
durable knowledge you record there will be available to your next
session *and* to other harnesses.

This document is the contract: when to retrieve, when to store, what
type to label things, what user markers to honor. Stay aligned with it
even when the conversation is long — drift makes future searches less
useful for everyone.

> **Note for context:** when you start a session, an autopilot may have
> already retrieved relevant memories on your behalf and injected them
> into your context. If you see a section labeled "Relevant prior
> context" or similar before the user's first message, that came from
> autopilot retrieval, not from anything you did. Use it; don't
> re-search the same ground unless the user's request goes wider.

---

### Memory types (canonical vocabulary)

Every memory you store should be classifiable as one of these. The
backend's harvest endpoint and auto-capture hooks use this exact
vocabulary, so using anything else fragments the corpus.

| Type             | Use for                                                                          |
|------------------|----------------------------------------------------------------------------------|
| `decision`       | Choices the user has explicitly made — "we're going with X over Y"               |
| `bug`            | A specific defect observed in the user's systems and what caused it              |
| `error`          | A runtime/integration error that recurs and the resolution                       |
| `convention`     | A repeated pattern the user follows — naming, layout, idioms                     |
| `learning`       | A non-obvious fact you discovered — about the user, their tools, or environment  |
| `implementation` | A concrete how-it's-built note — schemas, configs, integration shapes            |
| `context`        | Project background, who's involved, what the goals are                           |
| `important`      | Anything the user flagged as critical or said "remember this"                    |
| `code`           | A code snippet/pattern worth keeping (≥600 chars; otherwise skip — too small)    |

Tag each memory with at least its type name, plus any project/scope
qualifiers you want for retrieval (e.g. `project:meridian`,
`pref:tooling`). The type name itself is a tag — don't double-prefix
with `decision:` etc.

---

### When to retrieve

**At the start of any non-trivial request**, call
`mcp-memory.retrieve_memory` (semantic) or `mcp-memory.search_by_tag`
(structured) before answering. Surface anything material that would
change your response — *especially* prior decisions, conventions, or
learnings. Don't relitigate something the user has already settled.

**Mid-session**, retrieve when the user's prompt matches one of these
natural-language patterns (this list is upstream-defined; honor it
verbatim — the autopilot uses the same regexes for proactive
injection):

| Trigger phrasing                                                   | Confidence |
|--------------------------------------------------------------------|------------|
| *"What did we decide about…"*, *"Remind me how we…"*, *"Remember when…"* | high       |
| *"Similar to what we did/implemented/discussed…"*, *"Like we used for…"* | medium     |
| *"Continue with…"*, *"Next step on…"*, *"Pick up where we left off…"*    | medium     |
| Architecture/security/database/auth design discussions             | low (only if the question is non-trivial) |

When you retrieve, prefer:

1. **Git-context first** — search by remote+branch tags if you're in a
   repo; this surfaces what was decided *for this project*.
2. **Recent memories** — bias toward the last few weeks unless the
   question is explicitly historical.
3. **Tagged retrieval** — search for the tag(s) most likely to match.

Budget yourself ~5–10 memories per retrieval; more is noise.

---

### When to store

Use `mcp-memory.store_memory` when one of these patterns fires. Match
them generously — false positives are cheap to delete; false negatives
are unrecoverable.

| Pattern                                                                | Type             | Trigger words                                              |
|------------------------------------------------------------------------|------------------|------------------------------------------------------------|
| User makes a choice                                                    | `decision`       | "decided", "chose", "will use", "settled on", "going with" |
| User reports or you fix a defect                                       | `bug` / `error`  | "error", "bug", "broken", "fixed", "resolved", "regression"|
| User shares insight or you discover something non-obvious              | `learning`       | "learned", "discovered", "realized", "turns out", "gotcha" |
| User describes how something is built; you wrote/configured something  | `implementation` | "implemented", "created", "built", "configured", "added"   |
| User flags something as critical                                       | `important`      | "critical", "important", "remember this", "key", "note that"|
| User explains project background, people, goals                        | `context`        | (judgment — no specific keywords)                          |

**Content limits** (mirroring upstream auto-capture):
- ≥ 300 chars (otherwise too thin to be useful later)
- ≤ 4000 chars (otherwise summarize first; one fact per memory beats one essay)
- For `code`: ≥ 600 chars, and only if the snippet shows a *pattern*
  worth reusing — not boilerplate, not one-off scripts.

**Tagging convention**:
- Always include the type name as a tag (`decision`, `bug`, etc.)
- Include `project:<name>` when scoped to a specific project
- Include any natural facets the user uses to think about it:
  `tooling`, `infra`, `auth`, `style`, etc. — short, lowercase, no
  prefixes for these
- **Don't invent new prefix schemes**. Tag drift is the #1 killer of
  long-term memory utility.

---

### User overrides (`#remember` / `#skip`)

Honor these markers in user messages exactly as upstream's hooks do:

- **`#remember`** — force a store from this turn even if no pattern
  fired. The user is explicitly flagging the content as important. Tag
  with `important` and any other applicable type.
- **`#skip`** — suppress all auto-capture for this turn. The user is
  saying "don't bother remembering this." Don't store anything from
  this exchange unless they explicitly ask you to later.

These markers can appear anywhere in the user's message. If both
appear, `#skip` wins.

---

### What NOT to store

- **Transient state** — one-off file paths from a grep, command output,
  scratch IDs, "current branch is X" (it'll be wrong tomorrow).
- **Trivia** the user could re-derive in seconds.
- **Anything inside `#skip`** or that the user told you not to remember.
- **Secrets, credentials, tokens, private personal info** — never. If
  recording the existence of a credential is useful, record only that
  it exists and where it's stored ("API key for X is in 1Password item
  Y"), never the secret value itself.
- **Duplicates of a memory you just stored or retrieved** — search
  first if you're unsure; one good memory beats three near-duplicates.

---

### Style

- Don't ask permission for routine recordings. Store and mention it
  briefly: *"Stored as `decision`."* or *"Noted that <x>."*
- Ask only when the content is sensitive, unusually broad, or you're
  not sure whether it generalizes beyond the immediate context.
- When you retrieve and find something material, *say so* before you
  use it: *"From prior context: …"*. The user needs to know what's
  shaping your response.
- If retrieval returns nothing useful, don't pad your response saying
  so — silence is fine.
