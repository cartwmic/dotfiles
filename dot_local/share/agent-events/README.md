# agent-events

`agent-events` is an alias for `agent-traces pi`, the agent-kit port. `~/.local/bin/agent-events`
always runs `~/.local/bin/agent-traces pi "$@"`, so `agent-events run` is `agent-traces pi run`
and `agent-events status` is `agent-traces pi status`.

- The contract (tables, verbs, the exporter, the status file) is `src/traces/CONTRACT.md` in
  the agent-kit repo, and the README of the `@cartwmic/agent-kit` package.
- The LaunchAgent `local.agent-events` still runs `agent-events run` every 2 minutes. Its plist and
  load script are `Library/LaunchAgents/local.agent-events.plist.tmpl` and
  `run_onchange_after_70_agent_events_launchd.sh.tmpl`; the settings are chezmoi data `agentEvents`
  (`.chezmoitemplates/agent_events_config`).
- The database is `~/.local/share/agent-traces/pi/events.sqlite`. The state directory is
  `~/.local/state/agent-events` (`export_state.json`, `status.json`, `agent.log`, the lock).
- The pinned agent-kit install is `65_agent_kit_install.sh` (chezmoi data `agentKit`).

The Python collector (`agent_events.py`) and its gate tools (freeze, parity dump, rollback drill, the
shadow runs) were retired on 2026-11-07. They are in this repo's history at the git tag
`agent-events-python-final`.
