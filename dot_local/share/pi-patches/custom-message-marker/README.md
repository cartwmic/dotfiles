# pi-patch: custom-message-marker

Wraps extension-injected `custom` messages in `<injected-context>` … `</injected-context>`
tags inside pi-core's `convertToLlm()`, so stateful provider adapters can tell
injected context apart from real user turns — and (v2) passes turn-prompt custom
messages through **unwrapped**.

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
the whole array each turn. But **turn-oriented** adapters that translate the
message array into Cursor's protobuf/turn protocol cannot cope. The
[`cartwmic/pi-cursor`](https://github.com/cartwmic/pi-cursor) fork (of
[Rahularya01/pi-cursor](https://github.com/Rahularya01/pi-cursor)) parses the
**last** user message as the current prompt and demotes everything before it
into history. Result without the marker: the injected context block is sent as
the prompt and the **real user message is silently lost** — every first turn
and every post-compaction turn. (The retired
`cartwmic/pi-cursor-provider` proxy had the same last-user-wins parsing.)

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
guessing per-extension header strings. The cursor fork's context
normalization treats any `<injected-context>`-marked user message as
side-channel context and folds it into the system prompt, while genuine
consecutive user messages (e.g. an interrupt: "interrupt me" then "continue")
are **not** wrapped and keep the normal last-turn-wins behavior. Stateless
providers just see the bracketed text — cosmetically clarifying, functionally
inert.

`convertToLlm` throws away.

## v2: turn-prompt custom messages pass through unwrapped

Async subagent completion notifications are **turn prompts**, not injected
context: pi-subagents sends them with `triggerTurn: true`, pi-core starts a
new LLM turn whose only prompt message is the notification. Wrapping them
made the cursor fork classify the wake turn's only user message as side-channel
context and drop it, erroring `No user message found` (`native-core.ts:530`).

v2 fixes this at the source: `sendCustomMessage` persists the delivery intent
on the message as `promptIntent` (computed to match the delivery branch —
`nextTurn` → false, steer/followUp while streaming → `triggerTurn !== false`,
otherwise `triggerTurn === true`), and `convertToLlm` skips the wrap when
`promptIntent === true`. Context injections (`before_agent_start` messages,
no-trigger sends) keep the wrapping, so the original demotion fix is untouched.

Validated: a real pi session (claude-haiku-4-5) ran an async subagent; the
completion notification triggered a wake turn that completed with the parent
reporting the subagent's result, and zero `No user message found` errors.

## Scope

- **Targets:** `@earendil-works/pi-coding-agent/dist/core/messages.js` (SDK,
  solely owned — backup restore is safe), `dist/core/agent-session.js` (SDK,
  **shared** with settlement-abort/headless-drain/prompt-start-race/
  standing-reminder-origin), and the `dist/bundle/chunks/*.js` chunk holding
  `convertToLlm` and `sendCustomMessage` (the `pi` CLI runs the bundle; also
  **shared**).
- **Shared-file guard:** v2 never restores a shared target from backup — that
  would silently drop the other patches' edits. A stale revision on a shared
  target is transformed in place by alternative anchors (the bundle
  `convertToLlm` edit accepts both the original and the v1-patched minified
  form); only `messages.js` is restored from backup.
- **Profiles:** all (no profile gate). The wrapping is safe for every provider.
- **Anchors:** the `const content = typeof m.content === "string" …` line in
  `convertToLlm`'s `case "custom"` (SDK + bundle), the `appMessage` literal in
  `sendCustomMessage` (SDK + bundle), and the minified `case"custom":return{…}`
  (bundle, original or v1-patched form).

## Failure modes

- **anchor-not-found (0 or >1 matches):** upstream changed the `convertToLlm`
  custom-case shape. Update the anchor in `patch.mjs` and bump
  `PATCH_REVISION`. If upstream started preserving `customType` through the LLM
  boundary (making this unnecessary), delete this patch and the fork companion.
- **stale revision, no backup:** reinstall pi-coding-agent, then
  `chezmoi apply`.

## Related

- Fork: <https://github.com/cartwmic/pi-cursor> (companion side-channel fold;
  fork of <https://github.com/Rahularya01/pi-cursor>).
- Retired: <https://github.com/cartwmic/pi-cursor-provider> (previous proxy
  provider; carried the original coalesce companion in `proxy.ts`).
- Upstream candidate: preserve `customType` (or a marker) through
  `convertToLlm` so stateful adapters don't need this — would obsolete both
  halves.
