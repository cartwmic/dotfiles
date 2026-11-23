# lead-turn-end (Pi extension)

A lead's turn may end only when something will wake it (a child, a job, a PR watch or a thread wait), an ask that names it is open, or a state note was accepted for the current run.
This extension asks the coordinator on each clean end of a Pi session's turn. When the answer is a refusal, the refusal text goes back to the lead as a follow-up message and the
next turn starts. The message names the ways out: do the work, start a waker, `ledger open`, or `coordinator t3 state-note PATH`. Claude Code runs the same check as a Stop hook
(`lead_turn_end.py`) and Cursor from the coordinator's stop hook; Pi is first (#1555).

The rule, and every read behind it, is `coordinator t3 turn-end` in the configured coordinator checkout (`src/t3-hook/turn-end.ts`). This extension holds no rule, no list of wakers and no T3 reader.
It does two things the coordinator cannot: it counts this session's running jobs (`stop_running_jobs.py --count`, the hook the builder seat's stop already uses) and passes the number as `--jobs N`; and it knows
whether this end follows its own refusal.

- **First end refused, second let through.** The first bare end is refused once. After the follow-up has run, the next end is asked again with `--continued`: the coordinator then lets it through and
  reports it to the inbox (source `lead-turn-end`). The "I refused last time" flag is this process's memory: it is cleared by any input that is not this extension's own follow-up
  (`input` event with `source` other than `extension`), so a new message from the coordinator or Michael starts again from a first end. Nothing is stored on disk.
- **No message text is read.** The decision is on facts only.
- **Which sessions:** a Pi session with `T3CODE_THREAD_ID` set (T3 starts `pi` and `pi-lead` sessions with it). The coordinator itself answers "not a lead" (allow) for any other seat.
- **Only clean ends:** an end whose last assistant message did not stop cleanly (abort, error) is left alone.
- **Where the checkout and state are:** `config.json`, rendered per profile from [config.json.tmpl](./config.json.tmpl): personal `instances.coordinator.repo` (else `~/git/coordinator`) with state
  `~/.local/share/coordinator`; `axon-work-computer` `~/coordinator-work` with state `~/.local/share/coordinator-work`. `agentHost.removeCoordinatorHook` renders it off.
  The session's `COORDINATOR_STATE_DIR` wins when set.
- **Fails open, quietly:** no `config.json`, switched off, no checkout or state directory, no `T3CODE_THREAD_ID`, a command that times out or prints something unreadable all let the end stand.
  The coordinator's own command fails open too and says "not checked" when a read it needs fails.
- **Does not count a Cursor lead's jobs** (Cursor's stop hook has no job count; named in the coordinator PR).
- **Restart Pi** after an apply so it loads the extension.

Tests: `node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/lead-turn-end/index.test.ts` (a fake `run`, no coordinator) and
`python3 -m unittest discover -s tests/lead-turn-end -v` (renders `config.json` for both profiles).
