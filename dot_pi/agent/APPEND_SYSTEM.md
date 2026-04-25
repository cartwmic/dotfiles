## Bash tool usage

Do not prefix bash tool calls with `cd <project_dir> &&` or similar directory changes unless the user explicitly asks to cd. The bash tool already executes in the correct working directory (the project root). Adding unnecessary `cd` commands clutters output and wastes tokens.

## Subagent context policy

When using the `subagent` tool from the `pi-subagents` extension, prefer isolated context (`context: "fresh"` or omit `context`) by default.

Only use `context: "fork"` if the user explicitly asks for forked or parent-session context, or explicitly asks to preserve/share the current conversation context with the subagent.

Before kicking off subagents, check the current model list by running `pi --list-models` and use it to confirm the exact `<prefix>/<model-id>` value to pass in the subagent `model` field. Do not guess or hand-construct model identifiers when an exact current value can be verified from `pi --list-models`.

When the user specifies a model for a subagent invocation, always pass it via the `model` field in the `subagent()` call. Never fall back to the builtin agent's default model when the user has stated which model to use.
