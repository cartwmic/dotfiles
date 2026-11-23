# coordinator-helper-gate (Pi extension)

Runs the coordinator's helper gate on a Pi session's `subagent` calls. The gate refuses a helper (a sub-agent) that would run on a model
stronger than Haiku 5.5 unless the first line of its task declares a matching `Seat: <seat>, <model> <effort>.` Claude Code and Cursor run the
same gate as hooks; the coordinator daemon's own Pi session runs it from `coordinator-session/index.ts`. This extension covers every other Pi
session: the ones T3 starts on the `pi` and `pi-lead` instances, and Pi sessions opened in a terminal.

The decision stays in the coordinator repo, and so does the code that asks for it. This extension has no model list, no seat table, no rule text and no hook launcher: on each
tool call it loads `<coordinator>/src/coordinator-session/helper-gate.ts` from the configured checkout (the file the coordinator's own Pi session uses) the first time it is needed and
calls its `helperGateReason(call, env, stateDir)`, which starts `node <coordinator>/src/t3-hook/hook.ts --pi` with the call, the working directory and the session's model on stdin.
The extension returns `{ block: true, reason }` when that gives a reason. Every other tool passes through (the coordinator's function answers nothing for it).

- **Door delivery for Pi:** the same file also carries two door routes, both the coordinator's own code. A launch tool (`delegate_task`, `t3_thread_launch`) or a tool the door index (`<state>/t3-hook/door-index.json`) names is asked of the hook;
  any other tool starts nothing. And the extension's `before_agent_start` handler gives the session's first prompt to the coordinator's `firstPromptMessage`: a brief with a `Kind:` line gets that kind's playbook rules as a hidden message, once.
  An older checkout without `firstPromptMessage` tells nothing.
- **Where the checkout and state are:** `config.json`, rendered per profile from [config.json.tmpl](./config.json.tmpl), the same places the Claude hook install uses
  (`dot_claude/modify_settings.json.tmpl`): personal `instances.coordinator.repo` (else `~/git/coordinator` on Linux) with state `~/.local/share/coordinator`;
  `axon-work-computer` `~/coordinator-work` with state `~/.local/share/coordinator-work`. `agentHost.removeCoordinatorHook` renders it off, as it takes the hook out of Claude's settings.
- **State directory:** the session's `COORDINATOR_STATE_DIR` when set (`pi-lead` sets it; plain `pi` does not), else the one in `config.json`.
- **Which sessions:** all of them. Like the Claude hook (installed for every session, gate runs when a state directory is set), it does not look for `T3CODE_THREAD_ID`.
- **No double check:** the daemon's Pi starts with `-e <repo>/src/coordinator-session/index.ts`, and global extensions load there too. When that argument is in the process's
  command line, this extension stands down.
- **Fails open, quietly:** no `config.json`, switched off, no checkout, no `src/coordinator-session/helper-gate.ts` (an old checkout), no state directory, or a gate file that cannot be loaded
  or throws all let the call through and print nothing to the session. It never creates a state directory. Past those checks the coordinator's `helperGateReason` fails open itself
  (a spawn error, a 30 s timeout, a non-zero exit or output it cannot read let the call through) and adds one line to `<state>/t3-hook/helper-gate.log`.
- **Turned off for everyone** the way the coordinator does it: create `<state>/helper-gate.off`; the hook then answers nothing.
- **Does not cover** foreground `pi-subagents` children (launched with extension discovery off; the gate is on the call that starts them), a `workflow` script's children (the hook cannot
  read them), or the `!` commands you type.
- **Restart Pi** after an apply so it loads the extension.

Tests: `node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/coordinator-helper-gate/index.test.ts`
(a stub `helper-gate.ts`, not the coordinator checkout; the coordinator repo tests its own) and `python3 -m unittest discover -s tests/coordinator-helper-gate -v` (renders `config.json` for both profiles).
