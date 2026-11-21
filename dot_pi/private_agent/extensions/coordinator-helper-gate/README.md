# coordinator-helper-gate (Pi extension)

Runs the coordinator's helper gate on a Pi session's `subagent` calls. The gate refuses a helper (a sub-agent) that would run on a model
stronger than Haiku 5.5 unless the first line of its task declares a matching `Seat: <seat>, <model> <effort>.` Claude Code and Cursor run the
same gate as hooks; the coordinator daemon's own Pi session runs it from `coordinator-session/index.ts`. This extension covers every other Pi
session: the ones T3 starts on the `pi` and `pi-lead` instances, and Pi sessions opened in a terminal.

The decision stays in the coordinator repo. This extension has no model list, no seat table and no rule text: on each `subagent` call it starts
`node <coordinator>/src/t3-hook/hook.ts --pi` with the call, the working directory and the session's model on stdin, and returns
`{ block: true, reason }` when the hook says so. Every other tool passes through.

- **Where the checkout and state are:** `config.json`, rendered per profile from [config.json.tmpl](./config.json.tmpl), the same places the Claude hook install uses
  (`dot_claude/modify_settings.json.tmpl`): personal `instances.coordinator.repo` (else `~/git/coordinator` on Linux) with state `~/.local/share/coordinator`;
  `axon-work-computer` `~/coordinator-work` with state `~/.local/share/coordinator-work`. `agentHost.removeCoordinatorHook` renders it off, as it takes the hook out of Claude's settings.
- **State directory:** the session's `COORDINATOR_STATE_DIR` when set (`pi-lead` sets it; plain `pi` does not), else the one in `config.json`.
- **Which sessions:** all of them. Like the Claude hook (installed for every session, gate runs when a state directory is set), it does not look for `T3CODE_THREAD_ID`.
- **No double check:** the daemon's Pi starts with `-e <repo>/src/coordinator-session/index.ts`, and global extensions load there too. When that argument is in the process's
  command line, this extension stands down.
- **Fails open, quietly:** no `config.json`, switched off, no checkout, no `hook.ts`, no state directory, a spawn error, a 30 s timeout, a non-zero exit or output it cannot read
  all let the call through, and print nothing to the session. When the hook was started and failed, it adds one line to `<state>/t3-hook/helper-gate.log` (the coordinator's own
  log, same format). It never creates a state directory.
- **Turned off for everyone** the way the coordinator does it: create `<state>/helper-gate.off`; the hook then answers nothing.
- **Does not cover** foreground `pi-subagents` children (launched with extension discovery off; the gate is on the call that starts them), a `workflow` script's children (the hook cannot
  read them), or the `!` commands you type.
- **Restart Pi** after an apply so it loads the extension.

Tests: `node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/coordinator-helper-gate/index.test.ts`
(a stub `hook.ts`, not the coordinator checkout) and `python3 -m unittest discover -s tests/coordinator-helper-gate -v` (renders `config.json` for both profiles).
