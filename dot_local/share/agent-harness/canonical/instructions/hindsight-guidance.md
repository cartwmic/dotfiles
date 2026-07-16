## Memory: `hindsight` MCP server

You have access to a centralized long-term memory backend via the
`hindsight` MCP server ([Hindsight](https://hindsight.vectorize.io),
served from `hindsight-api.internal.cartwmic.com`). It is **shared
across every agent harness** the user runs (pi, Claude Code, Codex,
future tools). The memory **bank** is selected by chezmoi profile via
the endpoint path (`axon-work-computer` → `work`, otherwise →
`cartwmic`), so durable knowledge stays available to your next session
*and* to other harnesses on the same profile. Tools never take a
`bank_id` argument — the bank is fixed by the connection.

This document is the contract: when to recall, when to retain, how to
scope, and what markers to honor. Stay aligned with it even in long
conversations — drift makes future recall worse for every harness.

> **Note on automatic recall (pi only, for now):** in the pi harness an
> extension performs **auto-recall** before your turn and injects a
> `<hindsight_memories>` block into your context, and **auto-retain**
> after your turn. If you see a `<hindsight_memories>` block, that came
> from auto-recall — use it; don't re-`recall` the same ground unless
> the request goes wider or deeper. In Claude Code and Codex there is no
> hook yet, so **the tools below are the only mechanism** — you must call
> them explicitly.

---

### The three core tools

Hindsight is not a key-value store. It *extracts* facts from what you
give it, *consolidates* them into deduplicated observations, and
*synthesizes* answers with the bank's configured personality. Three
verbs:

| Tool | Use for |
|------|---------|
| `recall` | Semantic search over stored memories. Returns relevant raw/consolidated memories. Your default retrieval. |
| `reflect` | Synthesize an *answer* across many memories using the bank's reasoning frame (skeptical, literal, flags superseded decisions). Use for "what's our convention for…", architecture/design questions, anything needing judgment over many facts. |
| `retain` | Store a conversation/text for async fact extraction. **Write is asynchronous** — facts are not searchable the instant you call it. |

`sync_retain` is the blocking variant — use it only when you must read a
fact back in the same turn (rare). Other tools (`list_memories`,
`list_tags`, `get_memory`, `list_documents`) are for browsing/debugging,
not routine work. Mental-model and directive tools are managed
out-of-band — don't touch them unless explicitly asked.

---

### When to recall

**At the start of any non-trivial request**, `recall` before answering
(unless a `<hindsight_memories>` block already covers it). Surface
anything material that would change your response — *especially* prior
decisions, conventions, and preferences. Don't relitigate something the
user already settled.

**Reach for `reflect` instead of `recall`** when the question is
synthetic rather than lookup: "what do we usually do for X", design
trade-offs, security/architecture/auth discussions, or anywhere a single
consolidated judgment beats a list of raw hits.

**Mid-session**, retrieve when the user's prompt matches these patterns:

| Trigger phrasing                                                   | Tool |
|--------------------------------------------------------------------|------|
| *"What did we decide about…"*, *"Remind me how we…"*, *"Remember when…"* | `reflect` |
| *"Similar to what we did/implemented/discussed…"*, *"Like we used for…"* | `recall` |
| *"Continue with…"*, *"Next step on…"*, *"Pick up where we left off…"*    | `recall` |
| Architecture / security / database / auth design (non-trivial)     | `reflect` |

When you recall, prefer **git-context** (search by repo / branch terms
if you're in a repo) and **recency** (bias toward recent unless the
question is explicitly historical). Budget ~5–10 results; more is noise.

---

### When to retain

In Claude Code and Codex there is no auto-retain hook yet — **you** are
responsible for storing durable knowledge. In pi, auto-retain covers the
bulk; still call `retain` explicitly for a fact the user clearly wants
preserved (or when they say `#remember`).

`retain` when one of these fires — match generously; false positives are
cheap, false negatives unrecoverable:

| Pattern | Trigger words |
|---------|---------------|
| User makes a choice (decision, trade-off) | "decided", "chose", "will use", "settled on", "going with" |
| A defect is reported or fixed | "error", "bug", "broken", "fixed", "resolved", "regression" |
| User shares insight / you discover something non-obvious | "learned", "discovered", "realized", "turns out", "gotcha" |
| Something gets built/configured (schemas, configs, integration shapes) | "implemented", "created", "built", "configured", "added" |
| User flags something critical | "critical", "important", "remember this", "key", "note that" |
| Project background, people, goals | (judgment) |

**Don't classify.** Hindsight does its own extraction and
consolidation — there is no memory-type taxonomy to set. Write the fact
plainly and let recall/reflect surface it semantically.

**Preserve exact identifiers verbatim** when you retain — commit SHAs,
version numbers, file paths, config keys/values, internal hostnames
(`*.internal.cartwmic.com`). Never paraphrase, round, or truncate them.
Capture temporal markers ("superseded the previous pin", "moved off X")
so decision evolution stays traceable.

**Async caveat:** after `retain`, the fact is not immediately
searchable. Do not `retain` then `recall` the same fact in the same
turn expecting it back — use `sync_retain` if you genuinely must.

---

### Scoping with tags

Tags are soft scoping *within* the single bank. On every `retain`:

- **`project:<name>`** — always, when the work is scoped to a repo/project.
- **`topic:<x>`** — optional domain facet (`auth`, `infra`, `tooling`, `style`).
- **No `memory_type:` tag** — there is no type taxonomy here.
- **No `harness:` tag** — one identity; which harness wrote it is irrelevant.

Keep tags short, lowercase, no invented prefix schemes. Tag drift is the
#1 killer of long-term memory utility.

---

### User overrides (`#remember` / `#skip`)

- **`#remember`** — force a `retain` from this turn even if no pattern
  fired. The user is explicitly flagging the content as important.
- **`#skip`** — suppress all capture for this turn (and, in pi, you
  should not rely on auto-retain having stored it either — note it but
  don't `retain`). Don't store anything from this exchange unless the
  user later asks.

These markers can appear anywhere in the user's message. If both appear,
`#skip` wins.

---

### What NOT to retain

- **Transient state** — current branch, scratch paths, ephemeral IDs,
  raw command/debug output. Wrong tomorrow.
- **Exploratory or abandoned approaches** that were tried and dropped.
- **Routine mechanical edits** with no decision behind them
  (reformatting, lint fixes, mechanical renames).
- **Pleasantries and meta-conversation.**
- **Trivia** the user could re-derive in seconds.
- **Anything under `#skip`**, or that the user told you not to remember.
- **Secrets, credentials, tokens, private keys** — never store the
  value. If the existence of a secret matters, record only that it
  exists and where it lives ("API key in 1Password item X"), never the
  value itself. Internal hostnames, service names, and file paths *are*
  useful context — keep them.

---

### Stale & superseded decisions

The bank is tuned to be skeptical and to flag contradictions, but help
it: when a new decision reverses an earlier one (a new pin, a version
bump, a tool swap), say so explicitly when you `retain` ("supersedes the
previous harpoon pin"). When recalled memories conflict, prefer the most
recent and call out the superseded one rather than presenting both as
current.

---

### Style

- Don't ask permission for routine retains. Store and mention it
  briefly: *"Retained that decision."*
- Ask only when the content is sensitive, unusually broad, or you're
  unsure it generalizes beyond the immediate context.
- When you recall/reflect and find something material, *say so* before
  using it: *"From prior context: …"*. The user needs to know what's
  shaping your response.
- If retrieval returns nothing useful, don't pad — silence is fine.
