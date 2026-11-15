# refuse-pattern-kill (Pi extension)

Blocks an agent's `bash` tool call that runs `pkill` or `killall`, and tells the model to kill an exact PID (`kill <pid>`) or use
`kgate cancel <id>` for a kgate job. It also blocks what the script's four bash rules refuse (a sleep-poll loop, an unquoted heredoc with a
backtick, kubectl/helm on another cluster's context, a bare `gh pr merge`; the last two on the personal profile only) with the fix named in the reason. It runs the shared classifier `~/.local/share/agent-harness/hooks/refuse_pattern_kill.py`
(the same script Claude Code's hook runs); see the agent-harness README, "Pattern-kill guard", for the design, what it covers and what it does not.

- **Fails open:** a missing script, a missing `python3`, a timeout or any other exit code allows the command.
- **Does not touch** the `!` / `!!` commands you type yourself (a different event, `user_bash`).
- **Does not cover** foreground `pi-subagents` children: they are launched with extension discovery off.
- **Restart Pi** after an apply so it loads the extension.

Test: `node --test dot_pi/private_agent/extensions/refuse-pattern-kill/index.test.ts`.
