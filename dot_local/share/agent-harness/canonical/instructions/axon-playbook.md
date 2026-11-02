## Axon playbook

Applies in a git repo whose remote is `git.taservs.net` or `github.com/axon-*`. Elsewhere, ignore this section.

If `~/.local/share/agent-harness/external-skills/axon-agents-playbook` does not exist, ignore this section.

- At session start, run `~/.local/share/agent-harness/external-skills/axon-agents-playbook/bin/playbook-context` and follow what it prints. Claude Code does this for you in a SessionStart hook, so do not run it again there.
- Before you open a PR, mark one ready, push to a PR branch, or ask for review, use the `axon-pr-preflight` skill.
