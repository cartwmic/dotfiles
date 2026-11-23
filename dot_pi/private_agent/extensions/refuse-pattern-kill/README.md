# refuse-pattern-kill (Pi extension)

Blocks an agent's `bash` tool call that runs `pkill` or `killall`, and tells the model to use `kill-mine '<pattern>'` (kills only processes its own session started), kill an exact PID (`kill <pid>`) or use
`kgate cancel <id>` for a kgate job. The text comes from the shared script, so it is the same as in Claude Code. It also blocks what the script's five bash rules refuse (a sleep-poll loop, an unquoted heredoc with a
backtick, kubectl/helm on another cluster's context, a bare `gh pr merge`, a local `docker run`, `docker build` or `docker compose up`; the last three on the personal profile only, the docker one on Linux only) with the fix named in the reason. It runs the shared classifier `~/.local/share/agent-harness/hooks/refuse_pattern_kill.py`
(the same script Claude Code's hook runs); see the agent-harness README, "Pattern-kill guard", for the design, what it covers and what it does not.

- **Door rule:** it adds `session_id` (Pi's session id) and `adapter: "pi"` to what it sends the classifier, so a playbook rule that names a shell command in its `At:` line is told once per Pi session (agent-harness README, "Door delivery"). The refusal text starts with "refused in agent sessions", which is what this extension blocks on.
- **Fails open:** a missing script, a missing `python3`, a timeout or any other exit code allows the command.
- **Does not touch** the `!` / `!!` commands you type yourself (a different event, `user_bash`).
- **Does not cover** foreground `pi-subagents` children: they are launched with extension discovery off.
- **Restart Pi** after an apply so it loads the extension.

Test: `node --test dot_pi/private_agent/extensions/refuse-pattern-kill/index.test.ts`.
