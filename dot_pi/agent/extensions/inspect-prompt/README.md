# inspect-prompt

Slash command: `/inspect-prompt`.

Opens a **snapshot** of Pi's currently assembled system prompt
(`ctx.getSystemPrompt()` at invoke time) in the same external editor Pi uses
for the user-query box (`settings.externalEditor`, else `$VISUAL`, else
`$EDITOR`, else `nano` / `notepad`).

The document includes agents files, appendments, skills, and other prompt
contributions already loaded into that assembly. It is **not** the
conversation transcript and **not** the raw provider HTTP payload after
per-request rewrites.

Edits in the editor are discarded. Closing the editor returns to the Pi TUI.
The command does not submit a user query or start an agent turn.

If there is no interactive UI (`pi --print` / json), the command returns
without waiting on an editor. If the agent is still running, it notifies and
returns without opening the editor.
