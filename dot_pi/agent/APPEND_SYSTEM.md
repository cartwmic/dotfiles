## Subagent context policy

When using the `subagent` tool from the `pi-subagents` extension, prefer isolated context (`context: "fresh"` or omit `context`) by default.

Only use `context: "fork"` if the user explicitly asks for forked or parent-session context, or explicitly asks to preserve/share the current conversation context with the subagent.
