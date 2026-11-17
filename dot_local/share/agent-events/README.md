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
- `agentEvents.export: false` (chezmoi data) makes a machine build the database and send nothing: the plist and the systemd unit leave out
  `AGENT_EVENTS_OTLP_ENDPOINT`, which the kit reads as "this machine does not send", and the tick exits 0. It is for a machine whose scheduled node
  cannot reach the collector. On macOS a launchd-run node is blocked from the local network until it is granted in System Settings (Privacy &
  Security > Local Network); the symptom is `could not reach the collector (EHOSTUNREACH)` and a job that exits 1 every 2 minutes, while curl or an
  ssh session on the same machine reaches the collector. The grant is per node binary and the mise path carries the node version, so it breaks on
  each node upgrade. Default: true.
- On Linux (personal) `agent-events.timer` starts `agent-events.service` every 2 minutes with the same settings: units
  `dot_config/systemd/user/agent-events.{service.tmpl,timer}`, load script `run_onchange_after_77_agent_events_systemd.sh.tmpl`.
  Logs: `journalctl --user -u agent-events`. The load script skips WSL.
- The database is `~/.local/share/agent-traces/pi/events.sqlite`. The state directory is
  `~/.local/state/agent-events` (`export_state.json`, `status.json`, `agent.log`, the lock).
- The pinned agent-kit install is `65_agent_kit_install.sh` (chezmoi data `agentKit`).

The Python collector (`agent_events.py`) and its gate tools (freeze, parity dump, rollback drill, the
shadow runs) were retired on 2026-11-07. They are in this repo's history at the git tag
`agent-events-python-final`.
