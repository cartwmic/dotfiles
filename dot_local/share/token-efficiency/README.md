# token-efficiency

Measures what the Claude Code agent fleet costs at list price, from the session logs in `~/.claude/projects`. Python 3, standard library only. Personal Linux only (`docs/profiles.md`).

```sh
session-cost                         # list-price $/day per seat: last 7 days next to the 7 days before
session-cost --days 3                # windows of 3 days
session-cost --refresh               # run collect.py first (about 10 seconds), so the last hour is in
session-cost --since ISO --until ISO # one window, e.g. the published baseline below
session-cost workstreams --since 2026-11-21   # list-price spend per coordinator workstream (below)
```

"List price" is what the tokens would cost at public per-token rates (the table at the top of `analyze.py`). It is a weight for comparing seats and windows, not the subscription bill.

## Spend per workstream

`session-cost workstreams --since DATE [--until DATE]` prints, for every coordinator workstream, requests, input, output, cache-read and cache-write tokens and list-price dollars, by model, with each row's share of the total. `DATE` is a day (UTC midnight) or an ISO UTC time; `--until` defaults to now. It runs `collect.py` first (`--no-collect` skips that), so one run by hand or from any scheduler is enough: this is the way to get fresh numbers on the agent host pod, which has no systemd and so no timer. No model is called.

How a request gets its workstream: its transcript file belongs to a Claude session (a helper file belongs to its parent's session); T3's database says which thread owns that session; the nearest thread at or above it (lineage parent) that a ledger workstream names as its `pane` or `conversation` is the workstream. (The walk up the thread tree is `t3_lineage.py` in `share/workstream-rank`, which `workstream-rank` uses too.) A thread named by two workstreams shows under both names ("A / B"). Requests with no T3 thread, and threads with no workstream above them, have their own `(unmapped)` rows, each with its share and what is inside it (the project folder, or the root thread's title). Nothing is dropped: the rows add up to the `TOTAL`, which equals `session-cost --since X --until Y` over the same window.

- `--t3-db` and `--ledger` default to `~/.t3/userdata/statev2.sqlite` and `~/.local/share/coordinator/ledger.sqlite`. Both are opened read-only.
- Collection rebuilds `usage.sqlite` from the logs this host still has. On the agent host pod that is everything since the pod's first session (2026-11-21T14:06Z); older rows came from the omarchy desktop and live in that desktop's copy of the database.
- Threads that ran on another host are not in this host's T3 database and show as unmapped. Pi, Codex and advisor-tool calls are not counted.
- Every run appends one JSON line to `~/.local/state/token-efficiency/log.jsonl` (run id, window, outcome, seconds, sessions, requests, list $, unmapped share).

## What runs when

- `session-cost.timer` (systemd user timer, daily at midnight PST = 08:00 UTC, `Persistent`) runs `session-cost.service`: `collect.py`, then `session_cost.py --snapshot`.
- `collect.py` reads the logs (read-only) and rebuilds `~/.local/state/token-efficiency/usage.sqlite` (numbers only).
- `session_cost.py --snapshot` writes `~/.local/share/token-efficiency-snapshots/YYYY-MM-DD.json` (PST day). Snapshots are never deleted or rewritten except a rerun on the same day, which replaces that day's file. Each holds the two windows per seat and a per-day, per-seat table, so two dates compare with `jq` even after Claude Code prunes old logs.
- On the agent host pod there is no systemd user manager, so the timer and units are left out (`docs/container-mode.md`); the command and code folder are installed there.
- The unit logs to the journal: `journalctl --user -u session-cost`. Run it now: `systemctl --user start session-cost.service`.

## Counting rules

- One API request is one assistant message id. Streaming writes several records per id (one per content block); the last wins. An id copied into another file (resumed or moved sessions) is counted once, in the file where it first appears.
- Token kinds stay apart: fresh input, cache write (1-hour and 5-minute), cache read, output. Each kind is priced at its list rate; Haiku has a short-context and a long-context rate (over 100K prompt tokens).
- Seat comes from the `Seat:` line of a session's first prompt, then from known brief openings. Agent-tool helpers with no seat line are "helper of <seat of their session>".
- Days are PST (UTC-8).
- `$/day` = a window's list $ divided by the days between its first and last request. That is the divisor `analyze.py` uses for "per day", so `session-cost --since ... --until ...` matches a published baseline.
- Advisor-tool calls sit outside the normal usage fields; `analyze.py` reports them in their own table and `session-cost` leaves them out.

## Coverage

- Logs are complete from 2026-11-11 18:00Z (`COMPLETE_FROM` in `analyze.py`), when the fleet moved to this Linux machine. The first complete PST day is 2026-11-12. `session-cost` counts nothing before that and says so.
- Before that the fleet ran on the Mac. Only sessions that were moved over are here (roughly 40% of requests).
- Pi and Codex are outside `collect.py`.

## Full tables (`analyze.py`, `rereads.py`)

```sh
python3 collect.py                                   # logs -> ~/.local/state/token-efficiency/usage.sqlite
python3 analyze.py --since ISO --until ISO           # every table: by seat, model, day, prompt size, cache rewrites, tool results...
python3 analyze.py --since ISO --until ISO --json out.json > out.md
python3 rereads.py --json rereads.json > rereads.md  # cache read split by what is re-read, and avoidable re-reading
```

`baseline-linux-era.md` is the published baseline: 2026-11-11T18:00Z to 2026-11-13T01:14Z (31.1 hours, 1.30 days), made with `analyze.py --since 2026-11-11T18:00:00Z --until 2026-11-13T01:14:00Z`. Its "per day" figures are the window divided by 1.30, not calendar days. Compare a later run on whole PST days (`--since`/`--until` at 08:00Z) or on per-request figures (average prompt, cache read per request, median smallest prompt per seat).

- The tool-result, Bash, hook and repeat-read tables count whole transcript files of sessions active in the window. They shift when `collect.py` is re-run on sessions that are still going. The request-level tables do not.
- Tables that size text convert characters to tokens at a fixed ratio named in the table title. The true ratio measured on two real first requests was about 2.85 characters per token, so chars/4 figures understate by about 40%.
- `rereads.py` rebuilds what was in the prompt at each request and shares that request's real cache-read tokens over the pieces by size (text at 3 characters per token, model output at its real token count). Totals add up to the real cache read; shares inside a request are estimates. "Avoidable" rows are proxies (age in requests, size over 2K tokens, repeats, one-reply acknowledgements) and overlap.

## Tests

`tests/session-cost` (run: `python3 -m unittest discover -s tests/session-cost`) builds a small hand-written set of Claude Code logs, runs `collect.py` and `session-cost` on it and checks hand-computed dollars. `test_workstreams.py` adds a small T3 database and ledger and checks which workstream each session lands on; its red control runs the same check against the old rule (the workstream of the lineage root) and expects it to fail.
