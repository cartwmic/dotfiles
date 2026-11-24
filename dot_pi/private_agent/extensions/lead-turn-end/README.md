# lead-turn-end (Pi extension)

A lead's turn may end only when something will wake it (a child, a job, a PR watch or a thread wait), an ask that names it is open, or a state note was accepted for the current run.
This extension asks the coordinator on each clean end of a Pi session's turn. When the answer is a refusal, the refusal text goes back to the lead as a follow-up message and the
next turn starts. The message names the ways out: do the work, start a waker, `ledger open`, or `coordinator t3 state-note PATH`. Claude Code runs the same check as a Stop hook
(`lead_turn_end.py`) and Cursor from the coordinator's stop hook; Pi comes first.

The rule, and every read behind it, is `coordinator t3 turn-end` in the configured coordinator checkout (`src/t3-hook/turn-end.ts`). This extension holds no rule, no list of wakers and no T3 reader.
It does two things the coordinator cannot: it counts this session's running jobs (`stop_running_jobs.py --count`, the hook the builder seat's stop already uses) and passes the number as `--jobs N`; and it knows
whether this end follows its own refusal.

- **One refusal per user turn.** The first bare end is refused once. After the follow-up has run, the next end is asked again with `--continued`: the coordinator then lets it through and
  reports it to the inbox (source `lead-turn-end`). If the coordinator were to refuse that end too, the extension does not send a second refusal: it lets the end through and writes a line
  (`cause: "after-refusal"`). The "I refused already" memory is this process's: only a real user input clears it, never the extension's own follow-up (`source: "extension"`) and never an input
  whose text is the refusal itself. Nothing but the log line is stored on disk.
- **No message text is read.** The decision is on facts only.
- **Which sessions:** a Pi session with `T3CODE_THREAD_ID` set (T3 starts `pi` and `pi-lead` sessions with it). The coordinator itself answers "not a lead" (allow) for any other seat.
- **Only clean ends:** an end whose last assistant message did not stop cleanly (abort, error) is left alone.
- **Where the checkout and state are:** `config.json`, rendered per profile from [config.json.tmpl](./config.json.tmpl): personal `instances.coordinator.repo` (else `~/git/coordinator`) with state
  `~/.local/share/coordinator`; `axon-work-computer` `~/coordinator-work` with state `~/.local/share/coordinator-work`. `agentHost.removeCoordinatorHook` renders it off.
  The session's `COORDINATOR_STATE_DIR` wins when set.
- **Fails open:** no `T3CODE_THREAD_ID`, no `config.json` or switched off lets the end stand without a trace (this is not a lead session, or it is not set up). Once a thread and an enabled config are there,
  an end that stands because the check could not run (no checkout or state directory, a command that times out, is missing or prints something unreadable) writes one JSON line to
  `<state>/t3-hook/turn-end-adapter.jsonl`: `ts`, `adapter` (`pi-extension`), `thread`, `outcome` (`allowed`), `cause` (`check-failed` or `after-refusal`), `reason`, `duration_ms`. The coordinator's own command
  fails open too and says "not checked" when a read it needs fails; it logs that in its own `turn-end.jsonl`.
- **Needs the coordinator command.** Until `coordinator t3 turn-end` is on the coordinator checkout's main branch, every end is let through and the log says the command gave no readable answer.
- **Does not count a Cursor lead's jobs** (Cursor's stop hook has no job count; named in the coordinator PR).
- **Restart Pi** after an apply so it loads the extension.

Tests: `node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/lead-turn-end/index.test.ts` (a fake `run`, no coordinator) and
`python3 -m unittest discover -s tests/lead-turn-end -v` (renders `config.json` for both profiles).
