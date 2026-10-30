# run-and-wake

`run-and-wake` runs a command detached and, when it exits, wakes the Pi session that started it with one tagged prompt. A worker can start a long or gated job and end its turn. Nobody polls.

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
- **Any exit wakes.** Exit 0, a failure, heavy-gate's 75 (gave up waiting), a signal (`killed by SIGTERM`) and a command that could not start (exit 127) all wake.
- **Right session only.** At launch it captures `HERDR_PANE_ID` and `PI_SESSION_FILE` (Pi sets both on every bash call). At exit it asks `herdr agent get <pane>` and sends only if that pane still shows the same session file. Compaction keeps the session file, so it still wakes; `/new` or a resume does not.
- **Check, then send.** herdr's prompt names a pane, not a session, so the session check and the send are two calls milliseconds apart. A `/new` landing in that window still gets the message. It can't be refused, only seen: the pane's session is read again right after the send, and the `wake` record carries `session_after` when it differs.
- **At most one attempt per job.** One `herdr agent prompt`. A refused or failed prompt is logged and not retried.
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

Not covered: SIGKILL of the watcher or a reboot. The log then shows a `start` with no `end`.

## Log

`${XDG_STATE_HOME:-~/.local/state}/run-and-wake/log.jsonl`, one JSON record per line. Every record has `ts` (UTC, milliseconds), `job` and `event`:

| Event | Fields |
|---|---|
| `start` | `cmd` (argv), `cwd`, `pane`, `session`, `pid` (null if it could not start), `output` |
| `end` | `exit` (null if killed), `signal`, `duration_s`, `error` (could not start) |
| `blocked` | none: the pane showed a dialog and the wake is waiting |
| `wake` | `result` (`sent` or `failed`), `error` if failed, `duration_s` (from job end to send), `session_after` if the pane showed another session right after the send |
| `skip` | `reason`, `detail` |

Replay one job: `grep <job-id> ~/.local/state/run-and-wake/log.jsonl`. Job output files are not pruned.

## Profiles

It lands on `personal` and `axon-work-computer`, like heavy-gate: `dot_local/bin` with no ignore rule, so no `docs/profiles.md` row. Termux already ignores `.local/bin/*` except `passage-review`, and has no herdr panes. On the work Mac, Michael applies it himself.

## Tests

`python3 -m unittest discover -s tests/run-and-wake -v` runs the real script with a fake `herdr` first on PATH, in CI. It covers the wake, exit statuses (0, 7, 75, 127, SIGTERM), the job outliving a SIGKILLed launching process group, heavy-gate composition (the real gate giving up with 75), a blocked pane, a failed wait, a refused prompt, a session swapped between check and send (`session_after`), the launcher killed before the watcher reports, and two seeded faults: the pane closed before the job ends (`pane-gone`) and the session swapped (`session-changed`). Each test reads the job back from the log alone.
