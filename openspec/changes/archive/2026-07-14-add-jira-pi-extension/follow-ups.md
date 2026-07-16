# Follow-ups — add-jira-pi-extension

Advisory items from code-review round 1 (do not gate):

1. **SDK path resolution** (P2) — `client.ts` `resolveSdkRoot` hardcodes mise
   node `24.12.0` (and a non-existent `current` fallback). Prefer discovering
   via `require.resolve` / `import.meta.resolve` against `pi-mcp-adapter` or
   documenting a pin refresh when mise bumps Node.
2. **Autocomplete empty array** (P3) — return `null` when no verb matches if
   that matches sibling extensions' idiom.
3. **domain.md list blank line** (P3) — cosmetic Markdown list split.
4. Intent wording at archive: reconcile "No `before_agent_start` hook" with
   latch-gated one-shot consume (fidelity advisory).
