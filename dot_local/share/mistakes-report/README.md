# mistakes-report

One script, run weekly by the coordinator's Retro lead keeper (schedule `mistakes-weekly`; since 2026-11-16 there is no systemd timer), that publishes one page on shartifacts with two tables of repeated mistakes. No new service, no join to T3. The design is the "smallest first step" in the agent-traces audit (shartifacts page 05b4024e55201cca4768a408, section 5; insights 1 and 2).

Personal profile, Linux only (`docs/profiles.md`). Nothing is read on the work Mac.

## What it reads and writes

| | Path | Notes |
|---|---|---|
| reads | `~/.local/share/agent-traces/emitted/review/*/findings.jsonl` | The review log. Contract: `~/.local/share/agent-harness/findings-contract.md`. Blocking findings (`effective: blocking`) and `escape` events. |
| reads | `~/.claude/projects/**/*.jsonl` | Claude Code session files. Failed `tool_result` blocks (`is_error`). |
| calls | `claude -p --model claude-haiku-5-5` | Headless, no hooks, no tools, no session saved. One call per 20 items. |
| writes | `~/.local/state/mistakes-report/` | State, below. |
| publishes | `https://shartifacts.internal.cartwmic.com` | One html page, created once, updated in place (POST, then GET and PUT with `base_version`; a 409 is retried up to 3 times). |

## Table 1 and 2: mistake classes

`classes.json` is the fixed list of classes (id, plain name, description) plus the model id. The classes came from reading the 27 escapes and a sample of blocking findings; replace them when the data says so. A change to the list or the model invalidates every saved answer (the next run classifies everything again; about 740 items cost about $0.16 at list price).

The model sees, per item: kind (finding or escape), item, text (1500 characters), obligation or `found_by` (300). It answers `{"<number>": "<class id>"}`. A reply with a missing number, a number outside the batch or an id outside the list is asked for again once; if items still have no class the run fails, publishes nothing and keeps the answers it has.

Counted: blocking findings by their log time, this week against last; escapes the same, plus "all records" (every escape in the log). Two examples per class: the newest.

## Table 3: failed tool calls

No model. A result counts once per `tool_use_id` (the files repeat records per content block and hold copies of resumed sessions). Rows group by tool name and the first 100 characters of the first line of the error text, with `<tool_use_error>` tags removed. When the second line is an `at [...]` pointer (which argument a check complained about) it is added to the text. Every `Invalid parameters for tool 'X'` failure of one tool is one group, whatever argument it names; the row shows the commonest wording and how many other wordings it covers. A first line that is exactly `Exit code N` is a command's own exit status: counted in one summary line under the table, not as rows. Top ten by the larger of the two weeks.

## Weeks and snapshots

This week is the 7 days up to the run; last week the 7 days before. After each run `snapshots/YYYY-MM-DD.json` keeps this week's counts. A later run takes as last week the snapshot whose week ended within 36 hours of its own week start and which was made with the same class list; otherwise (the first run, a missed week, a changed class list) it counts last week from the logs and says so on the page. A same-day rerun therefore never takes its own snapshot as last week.

## State files (`${XDG_STATE_HOME:-~/.local/state}/mistakes-report/`)

| File | Contents |
|---|---|
| `page-id` | The shartifacts page id. Delete it to publish a new page. |
| `classifications.json` | `{"classes_hash", "labels": {"<item>\|<finding id>": "<class id>"}}`. Escape keys are `<folder>\|escape\|<sha1 of item, head, text>`. |
| `snapshots/YYYY-MM-DD.json` | `{start, end, classes_hash, findings: {class: n}, escapes: {class: n}, tool_errors: [[tool, key, n]], command_exits}` for the week ending at the run. |
| `runs.jsonl` | One line per run: run id, UTC time, duration, items classified, calls, tokens, list-price cost, counts, page id and version, where last week came from. |
| `page.html` | The last page built. |

## Run it

```
mistakes-report                 # classify, build, publish; prints tokens, cost and the page URL
mistakes-report --no-publish    # write page.html in the state directory and stop; saves no snapshot
```

Tests: `python3 -m unittest discover -s tests/mistakes-report` (the model and shartifacts are replaced by fakes).

## Turning it off

Set `mistakesReport.enabled: false` in the local chezmoi data and apply: chezmoi stops managing the command and its code (they stay on disk). The keeper's schedule lives in the coordinator, not here.

## The retired timer

`mistakes-report.timer` and `mistakes-report.service` (Mondays 07:30) are gone. One apply on a host that still has them runs `run_onchange_after_78_retire_mistakes_report_timer.sh`: it runs `systemctl --user disable --now mistakes-report.timer`, removes both unit files and reloads systemd. `~/.local/state/mistakes-report/` and the published page stay. Prune that script, its `.chezmoiignore` lines and its test once every machine has applied.
