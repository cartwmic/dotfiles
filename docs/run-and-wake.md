# run-and-wake

`run-and-wake` runs a command detached and, when it exits, wakes the Pi session or T3 Code thread that started it with one tagged prompt or message. A worker can start a long or gated job and end its turn. Nobody polls.

```sh
run-and-wake -- heavy-gate --wait 7200 -- npm test
run-and-wake -- sh -c 'make build && make proof'
```

It returns at once and prints the job id, the job's pid, its output file and the log path. When the job exits, the pane that started it gets one line like:

```
[run-and-wake k:20261030T013613Z-86e5e7] job finished: exit 7 after 47m03s: heavy-gate --wait 7200 -- npm test. Output: ~/.local/state/run-and-wake/jobs/20261030T013613Z-86e5e7.log
```

Source: `dot_local/bin/executable_run-and-wake` (Python 3, standard library only), installed as `~/.local/bin/run-and-wake`. heavy-gate is unchanged; the two compose through argv.

## Contract

- **Detached.** A watcher process in its own session (`fork` plus `setsid`) starts the job and waits for it. Ending the launching tool call, which kills that call's process group, ends neither, even if it happens before the watcher reports the pid to the launcher. The job's stdout and stderr go to `jobs/<id>.log`; a watcher crash prints its traceback there too.
- **Its own systemd scope (Linux).** `setsid` leaves the caller's process group but not its cgroup. T3 runs each Claude session in a user scope (`t3code-claude-<id>.scope`) and stops it when it releases the session, which kills every process in it: a job started with plain `setsid` died with no `end` record and no wake (durable-leads kgate job `20261112T082346Z-841136`). On Linux with a working `systemd-run --user`, the launcher therefore re-runs itself as `systemd-run --user --scope --quiet --collect --expand-environment=no --property=OOMPolicy=continue <placement> --unit=run-and-wake-<job> -- run-and-wake --scoped <job> …` (`<placement>` is under Resources) (an exec in place: same environment, cwd and stdio, no new process to wait on). The watcher and the job live in `run-and-wake-<job>.scope`, which only they own; the `start` record names it (`scope`) and the launcher prints it. It runs a probe first (the same options with `-- true`, as T3 does), because an exec cannot fall back: where the probe fails (`--expand-environment` needs systemd 254), or there is no `systemd-run` (macOS, the work Mac), the launcher takes the old path unchanged. `--expand-environment=no` is there because systemd-run expands `$VAR` in the command's arguments, and only since systemd 258 not in `--scope` mode: with it, a `$` reaches the job as typed on every version. `OOMPolicy=continue` means a kernel OOM kill takes the job (the `end` record then says `SIGKILL`), not the watcher that must record it. `--scoped` is internal.
- **A stop that signals the watcher too.** The watcher forwards SIGTERM, SIGHUP and SIGINT to the job and keeps waiting, so stopping the job's own scope (`systemctl --user stop run-and-wake-<job>.scope`) or signalling its whole group still ends in an `end` record with the job's signal and a wake, not silence. A signal the watcher was started ignoring stays ignored and the job inherits it, as before (`nohup run-and-wake …` still keeps SIGHUP off the job). When the whole scope is stopped, the job gets SIGTERM twice (from systemd and from the watcher); the second changes nothing for a job that exits on the first. Nothing in the setup stops a job's scope in practice: T3's stops match `t3code-*.scope` only (see Resources); what does is `systemctl --user stop` by hand and the user manager at logout or shutdown. Then the wake must be sent before the scope's stop timeout (systemd's default, 90 s) or SIGKILL takes the watcher; a send takes milliseconds, a wake held back by a blocked pane may not make it, and the stop timeout is left at the default.
- **The job knows its id.** The job's environment has `RUN_AND_WAKE_JOB=<job id>`, so a tool it runs (kgate) can key its own record by the same id.
- **The job can read 1Password with the service account.** When this process has no `OP_SERVICE_ACCOUNT_TOKEN`, the job gets the token from `~/.config/agent-harness/op-service-token` in its environment. The token is never in argv, the log, the job record or the job's output; the `start` record says only where it came from (`op_token`: `env`, `file` or null). Without a token the job runs without one, so `op` cannot reach the desktop app in a job (playbook 78819cbd).
- **Any exit wakes.** Exit 0, a failure, heavy-gate's 75 (gave up waiting) and 76 (refused for disk: a watched volume under the floor, or `/Volumes/Workshop` not mounted), a signal (`killed by SIGTERM`) and a command that could not start (exit 127) all wake.
- **Starting session, best effort.** At launch it captures `HERDR_PANE_ID` and `PI_SESSION_FILE` (Pi sets both on every bash call). At exit it asks `herdr agent get <pane>` and sends only if, at check time, that pane shows the same session file. Compaction keeps the session file, so it still wakes; a `/new` or a resume before the check does not.
- **The check/send window (accepted by Michael, ask #347, 2026-10-29).** herdr's prompt targets a pane, not a session, so the check and the send are two calls milliseconds apart. A `/new` in that window can put the message in the new session. This is not prevented. The pane's session is read again right after the send, and the `wake` record carries `session_after` when it differs.
- **T3 Code thread.** A worker started as a T3 thread has no Herdr pane. If `T3CODE_THREAD_ID` is set and there is no pane with a Pi session, the wake is one `t3 thread send <thread> -` with the same one-line text on stdin (CLI: `$T3CODE_CLI_PATH`, else `~/.t3/bin/t3`; the same form the coordinator's deliverer uses). A busy thread takes it as its next turn; an idle one starts a turn. The launcher says "T3 thread X gets one message". A failed send is logged and not retried, and a missing CLI is a failed wake. If both a pane with its Pi session and a thread id are set, the pane wins: Pi sets `HERDR_PANE_ID` and `PI_SESSION_FILE` on every bash call, so that pair names the real caller, while `T3CODE_THREAD_ID` can be inherited from the app that launched the shell. A delegated child (a thread id starting `thread:delegated-task:`) also gets one line at the end of its wake text asking it to message its lead, because T3 does not notify a lead for runs woken this way (pingdotgg/t3code#33432); remove it when that is fixed.
- **At most one attempt per job.** One `herdr agent prompt` or one `t3 thread send`. A refused or failed prompt is logged and not retried.
- **Blocked pane.** If the pane shows a dialog, it waits with `herdr agent wait` until herdr reports another state, re-checks the session, then sends. A failed wait ends the wake as `pane-gone` or `herdr-error`.
- **Busy pane.** Herdr submits the text; Pi takes it as a queued message after the current tool call.
- **Every skip is logged with its reason:**

| Reason | When |
|---|---|
| `no-pane` | No `HERDR_PANE_ID` at launch (a plain terminal). The launcher says so: "nothing will wake you". |
| `no-session` | No `PI_SESSION_FILE` at launch (not started from Pi). Also said at launch. |
| `pane-gone` | herdr no longer has an agent in that pane. |
| `session-changed` | The pane shows a different session; `detail` names it. |
| `herdr-error` | Any other herdr error; `detail` has its code and message. |

Not covered: SIGKILL of the watcher (for instance a scope stop that outlasts its timeout) or a reboot. The log then shows a `start` with no `end`.

**Why a job in a T3 session died (evidence, 2026-11-12).** Read from the bundled T3 server (0.1.10-nightly.20261111.4529): it releases a Claude session when it has had no turn for 30 minutes (`DEFAULT_IDLE_TIMEOUT_MS = 1_800_000`); it keeps one up to 4 hours past that only while Claude itself reports background tasks or subagents, and a run-and-wake job is neither. On release the Claude process exits and T3 runs `systemctl --user stop t3code-claude-<id>.scope`. It stops scopes in other ways too: a thread force-stop (`forceStopThread`), a runtime error, and `stopLeftoverAgents` at server start. The lost kgate job's thread (resumed in scope `t3code-claude-36716fbb`, matched by `--session-id` in the journal) completed its last run at `08:24:35.761Z`; the scope was stopped at `08:54:36`, 30 min 0.2 s later. The other scope stopped that second, `t3code-claude-03faff1d`, resumed the launch thread whose last run completed at `08:24:38.3Z`. Of the 200 `t3code-claude-*` scopes the user journal has stopped since 2026-11-11 00:00, 70 lived 30 to 35 minutes (one short turn, then the idle release). A restart does it faster: `systemctl --user restart t3code` at 2026-11-11 21:24:15 stopped about 20 session scopes within 9 seconds (which of T3's stop paths did each one is not shown by the journal). So a job that outlives its session by 30 minutes is lost without this scope, whatever the thread does.

**Resources.** A job must not escape the memory limit the agents have: this host has already had an out-of-memory kill, and it runs coordinatord and T3. T3 sets `MemoryHigh` (total RAM minus 6 GiB) and `MemoryMax` (minus 4 GiB) on `app-t3code-agents.slice` at server start, and `CPUWeight=10` on its parent `app-t3code.slice`, so agents get 10 against the server's 1000 when the CPU is contended. The scope is therefore started with `--slice=app-t3code-agents.slice`: it shares exactly the agents' budget and CPU weight, one pool rather than two. A separate `run-and-wake.slice` with copied limits was rejected: jobs and agents would each get the full budget, so the worst case is twice the limit, and the host would hit the kernel's global OOM killer instead of the slice's. In the shared slice a runaway job is throttled with the agents at `MemoryHigh` and killed inside the slice at `MemoryMax`.

Why that slice is safe to put a job in (T3 0.1.10-nightly.20261111.4529, `src/process/agentScope.ts`): T3 puts a session's scope in `app-t3code-agents-<sha256(stateDir)[0:12]>.slice`, a child of the agents slice (the dash in the name), and puts a scope that must survive a server restart (`survivesRestart`) directly in `app-t3code-agents.slice`, where the job's scope sits. Its stops are narrow. The server-start sweep `stopLeftoverAgents` stops only that per-state-dir slice, not the agents slice. `AgentScope.stop` (session release) returns unless the unit name starts `t3code-` and ends `.scope`. `AgentScope.kill` (force-stop) acts only on the unit it tracks for that thread. Nothing stops `app-t3code-agents.slice` itself. A job placed in the per-state-dir slice would be killed by the sweep: do not use it. (The lines are in `~/.local/share/coordinator-workspace/raw-scope-fix/t3-strings.txt`, the bundled server's text, lines 2134770-2135060; a T3 release that widens a stop would show in the live proof.) The proof reads the slice from `/proc/self/cgroup` into the `start` record (`slice`), not from what was asked.

When T3 has not run since boot, the agents slice has no limit (`systemctl --user show app-t3code-agents.slice -p MemoryMax` says `infinity`) and no agents run either. The launcher then puts `MemoryHigh` and `MemoryMax` on the scope itself, with T3's formula, in `app.slice`: a lone job is still capped below the host's RAM. Placing the scope in a slice that does not exist would make an unlimited one. The work Mac has no `systemd-run` and none of this.

**Interim wrap.** Before this change a lead could run `systemd-run --user --scope --quiet --collect -- run-and-wake -- <cmd>` (Linux host only; it fails where there is no `systemd-run`). With this change the wrap is unnecessary and harmless (two scopes; the job ends in `run-and-wake-<job>.scope`).

## Log

`${XDG_STATE_HOME:-~/.local/state}/run-and-wake/log.jsonl`, one JSON record per line. Every record has `ts` (UTC, milliseconds), `job` and `event`:

| Event | Fields |
|---|---|
| `start` | `cmd` (argv), `cwd`, `pane`, `session`, `thread` (null unless woken through T3), `pid` (null if it could not start), `output`, `op_token` (`env`, `file` or null: where the job's 1Password token came from; the value is never logged), `scope` (the job's systemd scope, `run-and-wake-<job>.scope`; null on the plain path) |
| `end` | `exit` (null if killed), `signal`, `duration_s`, `error` (could not start) |
| `blocked` | none: the pane showed a dialog and the wake is waiting |
| `wake` | `target` (`herdr` or `t3`), `result` (`sent` or `failed`), `error` if failed, `duration_s` (from job end to send), `session_after` if the pane showed another session right after the send (herdr only) |
| `skip` | `reason`, `detail` |

Replay one job: `grep <job-id> ~/.local/state/run-and-wake/log.jsonl`. Job output files are not pruned.

## Profiles

It lands on `personal` and `axon-work-computer`, like heavy-gate: `dot_local/bin` with no ignore rule, so no `docs/profiles.md` row. Termux already ignores `.local/bin/*` except `passage-review`, and has no herdr panes. On the work Mac, Michael applies it himself.

| Profile | Path that runs |
|---|---|
| `personal` (this Linux desktop, user manager present) | the probe passes, so the launcher execs `systemd-run --user --scope` and the job runs in `run-and-wake-<job>.scope` inside `app-t3code-agents.slice` (or `app.slice` with its own limits when T3 has not set the slice's) |
| `personal` where `systemd-run --user` fails (a shell with no user manager, a kgate pod) | the probe fails: today's path, fork and `setsid` only. A scope stop still takes the job. |
| `axon-work-computer` (macOS) | no `systemd-run`: today's path, unchanged. No T3-in-systemd scope exists there, so nothing is lost. The signal-forwarding in the watcher applies on every path. |
| `termux` | not deployed |

## Tests

`python3 -m unittest discover -s tests/run-and-wake -v` runs the real script with a fake `herdr` and a fake `t3` (records argv and stdin) first on PATH, and a fake `systemd-run` that fails by default, so every test takes the plain path whatever the host is. (The suite is not in `.github/workflows/ci.yml`; it runs on the dev machine, and the heavy suites go to kgate per AGENTS.md.) It covers the wake, exit statuses (0, 7, 75, 127, SIGTERM), the job outliving a SIGKILLed launching process group, heavy-gate composition (the real gate giving up with 75), a blocked pane, a failed wait, a refused prompt, a session swapped between check and send (`session_after`), the launcher killed before the watcher reports, a T3 thread woken with the same text, a failed or missing T3 CLI, the pane-over-thread choice, the 1Password token given to the job from its file, from the environment, or not at all (the value kept out of the log and output), and two seeded faults: the pane closed before the job ends (`pane-gone`) and the session swapped (`session-changed`). Scope tests: a recording `systemd-run` (which refuses a call without `--expand-environment=no`) shows the probe, the exec with the same options and the agents slice, and the cwd and environment arriving in the scope; with the slice unlimited, or no `systemctl`, the limits go on the scope; `$` and `%` reach the job as typed, with the fake and with the real `systemd-run`; a failing `systemd-run` and a PATH with none keep the plain path; and, only where a real user manager exists, a scope of the test's own (`raw-test-outer-<id>`) is stopped the way T3 stops a session's and the job must still finish, write `end` and wake. Signal tests: the watcher's group signalled together (as a scope stop does), the watcher alone, a job SIGKILLed, the job not inheriting a signal the watcher handles, and a signal ignored at launch (nohup) staying ignored for the job. Each test reads the job back from the log alone.
