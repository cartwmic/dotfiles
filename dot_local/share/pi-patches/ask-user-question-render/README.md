# ask-user-question-render

Keeps a resumed session from crashing Pi when it holds an `ask_user_question`
call whose `questions` argument was sent as a JSON string.

## Why

`@juicesharp/rpiv-ask-user-question` 2.15.0 added a transcript renderer
(`view/transcript.ts`). It reads `args.questions` straight from session
history. The tool's own `prepareArguments` hook decodes double-encoded
arguments, but Pi runs that hook only at execution, not when it redraws old
calls. A string `questions` has `length > 1`, so the result renderer takes the
table path and calls `args.questions.map`. The renderer builds its lines lazily,
so the throw escapes Pi's renderer `try/catch` and Pi exits with
`uncaughtException: TypeError: args.questions.map is not a function`.

The patch runs history args through the same `prepareQuestionArguments` before
both renderers, drops non-object questions, and defaults a missing header to
`""`. Decoded calls render with their real headers and answers.

## Scope

- Target: `~/.pi/agent/npm/node_modules/@juicesharp/rpiv-ask-user-question/view/transcript.ts`.
  Override the package root with `PI_ASK_USER_QUESTION_PACKAGE`.
- All profiles. Absent package: nothing to patch.
- Anchor-gated: on drift it fails with exit 1 and writes nothing.
- `--check` verifies every block. `--rollback` restores the stock text.

The onchange script also hashes the installed extension version, so a
`pi update` that replaces the package re-triggers the patch on the next
`chezmoi apply`. Between that update and the apply, the stock file is live.

Remove this patch once upstream guards the renderer.
