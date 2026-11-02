## Axon playbook

Applies in a git repo whose remote is `git.work.example` or `github.com/axon-*`. Elsewhere, ignore this section.

If `~/.local/share/agent-harness/external-skills/axon-agents-playbook` does not exist, ignore this section.

- Claude Code (a SessionStart hook) and Pi (the `axon-playbook` extension) inject the playbook notes for this repo at session start. Follow them. In any other harness (Codex), at session start run `~/.local/share/agent-harness/external-skills/axon-agents-playbook/bin/playbook-context` and follow what it prints.
- Before you open a PR, mark one ready, push to a PR branch, or ask for review, use the `axon-pr-preflight` skill.
