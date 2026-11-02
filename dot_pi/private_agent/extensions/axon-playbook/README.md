# axon-playbook (Pi extension)

Work profile only (`axon-work-computer`; gated in the repo-root `.chezmoiignore`, row in `docs/profiles.md`).

Pi's counterpart of the Claude Code SessionStart hook that runs the private Axon playbook's `bin/playbook-context`. It puts the
playbook's per-repo notes in the model's context without anyone asking.

## Behavior

- **When:** the first `before_agent_start` of a session. `session_start` fires once per session too, but cannot add context, so the
  script runs on the first turn instead, for `ctx.cwd`.
- **What runs:** `~/.local/share/agent-harness/external-skills/axon-agents-playbook/bin/playbook-context <cwd>` via `execFile` (no shell),
  3 s timeout, output capped at 256 KiB.
- **How it is injected:** the trimmed output goes into a hidden custom message (`customType: "axon_playbook"`, `display: false`), wrapped in
  `<axon_playbook>...</axon_playbook>`. This is the same mechanism the [hindsight](../hindsight/README.md) extension uses.
- **Once per session:** the message is stored in the session, so later turns do not repeat it, and a resumed or forked session that already
  holds it is not injected again. Unlike hindsight's per-prompt recall, nothing is re-sent each turn.
- **Compaction:** the summary replaces the message, so the extension injects it once more on the first turn after a compaction (unless the
  compaction kept the message).
- **Failure is silent:** script missing or not executable, non-zero exit, timeout, or empty output injects nothing. It is not retried until
  the next compaction. The script prints nothing outside a git repo or when no fragment matches.
- **Subagent children** (`PI_SUBAGENT_CHILD=1`) register nothing, as with Claude Code, whose SessionStart hook does not fire for subagents.
- Headless runs are not skipped (hindsight skips them): the playbook is rules for working in the repo, so workers need it.

The `axon-playbook.md` instruction fragment tells Pi and Claude Code the notes arrive on their own; only Codex runs the script by hand.

## Validation

```sh
cd dot_pi/private_agent/extensions/axon-playbook && node --test
```

Tests use scripts written to a temp dir; they never read the real playbook.
