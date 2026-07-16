# pi-patch: custom-message-marker

Wraps extension-injected `custom` messages in `<injected-context>` … `</injected-context>`
tags inside pi-core's `convertToLlm()`, so stateful provider adapters can tell
injected context apart from real user turns.

## Problem

pi extensions inject per-turn context via `before_agent_start` returning a
`custom` message (e.g. hindsight auto-recall memories, goals). In
`core/messages.js` `convertToLlm()`, pi flattens every `custom` message to
`role: "user"` and **drops the `customType`**:

```js
case "custom": {
    const content = typeof m.content === "string" ? [{ type: "text", text: m.content }] : m.content;
    return { role: "user", content, timestamp: m.timestamp };
}
```

pi appends this injected message **after** the real user prompt, so the wire
payload for a turn is:

```
[system, user(REAL PROMPT), user(INJECTED CONTEXT)]
```

For **stateless** providers (anthropic, openai) this is harmless — they receive
the whole array each turn. But **stateful** adapters whose upstream requires
strict `user → assistant` alternation cannot cope. The
[`pi-cursor-provider`](https://github.com/cartwmic/pi-cursor-provider) proxy
translates the OpenAI request into Cursor's protobuf/turn protocol; its
`parseMessages` treats the **last** user message as the current prompt and
demotes everything before it into history. Result: the injected context block
is sent as the prompt and the **real user message is silently lost** — every
first turn and every post-compaction turn.

The discriminator that would fix this — `customType` — is exactly what
`convertToLlm` throws away.

## Fix

Restore the signal structurally. Wrap the flattened content in a stable,
pi-owned sentinel:

```js
const content = [
  { type: "text", text: "<injected-context>\n" },
  ...inner,
  { type: "text", text: "\n</injected-context>" },
];
```

Adapters can then detect injected context by a stable marker instead of
guessing per-extension header strings. The cursor fork's `parseMessages`
coalesces any `<injected-context>`-wrapped trailing user message into the
preceding real turn, while genuine consecutive user messages (e.g. an
interrupt: "interrupt me" then "continue") are **not** wrapped and keep the
normal last-turn-wins behavior. Stateless providers just see the bracketed
text — cosmetically clarifying, functionally inert.

This is the pi-core half of the fix; the companion half lives in the cursor
fork (`INJECTED_CONTEXT_OPEN_TAG` in `proxy.ts`). **Keep the open tag
(`<injected-context>`) in sync between the two.**

## Scope

- **Target:** `@earendil-works/pi-coding-agent/dist/core/messages.js`
- **Profiles:** all (no profile gate). The wrapping is safe for every provider.
- **Anchor:** the single `const content = typeof m.content === "string" …`
  line in `convertToLlm`'s `case "custom"`.

## Failure modes

- **anchor-not-found (0 or >1 matches):** upstream changed the `convertToLlm`
  custom-case shape. Update the anchor in `patch.mjs` and bump
  `PATCH_REVISION`. If upstream started preserving `customType` through the LLM
  boundary (making this unnecessary), delete this patch and the fork companion.
- **stale revision, no backup:** reinstall pi-coding-agent, then
  `chezmoi apply`.

## Related

- Fork: <https://github.com/cartwmic/pi-cursor-provider> (companion coalesce +
  native `summarizeAction` compaction).
- Upstream candidate: preserve `customType` (or a marker) through
  `convertToLlm` so stateful adapters don't need this — would obsolete both
  halves.
