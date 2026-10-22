# agent-events

Read-only, metadata-only tables over Pi session files. It answers "where did this
session's time and tokens go" without a backend, a collector or any new capture.

Phase 0 of the traces research (dotfiles issue #10) built the tables. Phase 1 (below) runs
it in the background, exports aggregate metrics to Grafana, and adds a local drill-down.
Spans in a trace viewer and an emitter extension remain separate, later decisions.
Scope: Pi sessions only.

## What it does

`agent_events.py build` reads `~/.pi/agent/sessions` (or `$PI_CODING_AGENT_DIR/sessions`)
and writes a rebuildable SQLite database at
`${XDG_DATA_HOME:-~/.local/share}/agent-events/events.sqlite`. Nothing under the
session store is modified. There is no network access.

It stores ids, timestamps, durations, token counts, notional cost, tool and model
names, and rule-derived event kinds. It does **not** store prompts, assistant text,
tool arguments, tool results, error text or session names. A tool-argument string is
read only to recognise `sleep N` and only `N` is kept; error text is reduced to a bucket
(`rate_limit`, `network`, `timeout`…). This holds for every agent, including
budget-steward and any other financial agent: the tool has no content to exclude.
Tests plant a sentinel string in every content field and assert it never reaches the
database or any report.

## Use

```sh
agent-events build            # first run: ~75 s for ~7.7k files; later runs re-read only changed files (~5 s)
agent-events build --since 7d # only look at recently modified files
agent-events sessions --since 7d --sort cost
agent-events session <path-fragment-or-session-id>
agent-events tools --since 7d
agent-events events --since 7d
agent-events events --kind llm.error --list --since 1d   # individual events, newest first
agent-events projects --since 1d                         # spend by project (by when each call happened)
agent-events show <session> --turn 3                     # content of one turn, read from the session file
agent-events show <session> --errors                     # the error calls, with their error text
agent-events sql "SELECT project(cwd), ... FROM sessions"   # read-only; project(cwd) is the workstream slug
```

Python 3.11 or newer, standard library only. A rebuild skips files whose size and
mtime did not change; a changed file is parsed again in full. `--since` builds are
partial and never delete rows for files they did not look at.

`agent-events build` is safe to repeat, incremental and cheap. `agent-events` is a small wrapper (`dot_local/bin`) around
`agent_events.py`; it picks a Python 3.11+ (override with `AGENT_EVENTS_PYTHON`).
A build that is interrupted marks the database dirty and the next build repairs it.
`sql` accepts only `SELECT`/`WITH` queries under a read-only authorizer (no `ATTACH`, `VACUUM INTO`, `PRAGMA`).

## Always on (personal macOS)

A LaunchAgent, `local.agent-events` (source `Library/LaunchAgents/local.agent-events.plist.tmpl`, loaded by
`run_onchange_after_70_agent_events_launchd.sh.tmpl`), runs `agent-events run` every 2 minutes at low priority:

1. an incremental `build` (a few seconds; the first full build takes about 80 s; ticks and manual `agent-events build` runs take one lock, so they wait for each other instead of racing);
2. an aggregate-metrics push to the homelab OTel collector, when `AGENT_EVENTS_OTLP_ENDPOINT` is set;
3. `status.json`, `agent.log` (rotated at 1 MB) and a lock file in `~/.local/state/agent-events/`.

Self-healing: a database that is corrupt (not a busy or locked one) or three failed builds in a row set it aside as
`events.sqlite.corrupt`, and it is rebuilt from the session files; the database holds only derived data. A failed
push never stops the build and is logged once per distinct failure. Logs and `status.json` hold only an exception
type and an error code, never a path or message text. While the last build failed or the database is dirty, only the
health gauges are sent, not business totals.

`agent-events status` prints the age of the last successful build and push and exits 1 when the build is older
than 15 minutes. The same age is in Grafana (`pi_agent_events_last_build_success_timestamp_seconds`, "Data age" on the overview).
The work profile has neither the plist nor an endpoint, so no work data can reach the homelab.

## Metrics (Grafana)

The scheduled `agent-events run` is the only sender; it sends **aggregates only**: counters of sessions, turns, LLM and tool calls,
seconds (active, LLM, tool, waiting on you, per phase), tokens, notional cost and rule-derived events, plus duration
histograms for LLM and tool calls. Labels: `project` (the repository the cwd belongs to, folding worktrees and run directories into it;
only repositories found under `~/git` and `/Volumes/Workshop/macbook/git` or listed in `AGENT_EVENTS_PROJECTS`
(colon-separated) are named, anything else is `other`), `kind` (`top` or `subagent`), `provider`, `model`, `tool`, `outcome`, `phase`, `event`, `detail` (error class).
Provider, model and tool names must look like an identifier (a path becomes `other`).
No session id, path, prompt, tool argument, result or error text. `agent-events export` previews the series per metric (about 1,600) and
sends nothing (`--dry-run` is accepted and has no effect).

Counters are monotonic by construction. The database is recomputed on every build, so a total can fall (a removed file,
a moved dedupe owner, an unknown duration). The exporter keeps its own accounting in `export_state.json`: an exported value only
rises by the positive change since the last tick, so a recomputation never looks like a Prometheus counter reset. The first push,
a lost or unusable state file, and a changed project map or schema all start a baseline: current totals become the reference and the
exported values start at 0 (a lost state file also starts a new start time), so history is never counted as activity. After that a new
series is sent as 0 until that POST succeeds and its growth is added afterwards, so the first error of a new kind is counted. Values are
checkpointed to disk before each POST, and every known series is sent on every tick, so a series that vanishes keeps its value.
Known limit: when copied history moves between sessions (forks) a drop in one series and a rise in another can both occur; the rise is
counted. Dashboards show activity from the first push onward; `agent-events projects` / `sql` give full history locally. Tool metrics
have no project label (cardinality), so the project and kind variables do not filter tool panels.

Path: OTLP/HTTP (gzip JSON) to `otel-collector.internal.cartwmic.com`, its `metrics/pi` pipeline (`pi_*` names, port 8890),
Prometheus job `pi-agent-events`, and the four `Pi agents: ...` dashboards in the homelab repo (`k8s/kube-prometheus-stack/pi-*-dashboard.yaml`):
overview, errors and retries, tools and models, workstream drill-down.

Content-level questions ("what was that error?", "what was the prompt?") are answered locally by `agent-events show`, which
re-reads the original session file. Nothing it prints is stored or exported.

## Tables

- **sessions**: one row per Pi session file (`kind` is `top` or `child`). Wall, active, LLM,
  tool and owner-wait time; counts; tokens; `notional_cost_usd`; `timing_quality`.
  The `family` view adds subagent child runs to their parent.
- **turns**: one row per user prompt, with phase milliseconds (`llm, explore, edit, run, delegate, owner, other`),
  active time, idle time before the next prompt, tokens and cost.
- **calls**: one row per LLM call, tool call and nested call (a call made inside a
  `codemode` script), plus overhead spend (cache warms, compactions). Every row has the
  `entry_id` of the source entry so the original can be found; no body is copied.
- **events**: rule-derived kinds: `llm.error`, `llm.retry_loop`, `llm.aborted`, `llm.length_cutoff`, `reply.minimal`, `model.switch`, `thinking.change`, `context.compaction`, `spend.cache_warm`, `owner.asked`, `tool.error`, `tool.sleep_poll`, `subagent.retry`.

## Reading the numbers

- **Cost is notional.** It is Pi's price-table figure for the tokens used, not money
  spent. Most traffic here is subscription-backed. Every report says so.
- **Time is inclusive.** Phase times add each call's own duration, so parallel calls can
  sum to more than wall time. A `codemode` call reports each nested call's duration under its own
  phase, unscaled; `other` is a lower bound on wrapper time no nested call accounts for.
  `sessions.tool_ms` is the sum of top-level tool durations (owner questions excluded). `active_ms` is the union of LLM and tool intervals (parallel
  work counted once) and excludes owner-wait. `unaccounted_ms` is wall time with no call
  running: idle panes, waiting for you, gaps between steps.
- **Owner wait** is the duration of `ask_user_question` / `notify_owner` tool calls. Idle time
  between prompts is separate (`idle_after_ms`).
- **codemode** time is split by its nested calls; the part no nested call covers is `other`.
- **Unknown stays unknown.** If any call in a turn or session has no recorded duration, the
  totals it feeds (that phase, `active_ms`, `wall_ms` for a turn, `unaccounted_ms`) are NULL and
  `timing_complete` is 0; a phase with no calls at all is a known zero.
  On the author's history 13 of about 2,500 timed sessions are partial.
- **Timing quality:** `stamped` sessions have exact intervals (from the pi-stamp extension),
  `duration` sessions have Pi's own `durationMs` (since 2026-10-09), and `none` sessions have
  no timing: their time columns are NULL and reports print `unknown`, never zero.
  Tokens, cost and counts are present for all of them.
- `ttfc_ms` is time to first content block, not time to first token.
- **No double counting.** An entry copied into another file (a fork, copied child
  history) is counted in the shallowest, earliest file only, keyed on entry id like
  pi-token-usage. `inherited_cost_usd` shows what was left out. A turn whose prompt was
  copied from another file keeps the calls that are its own; only a turn with nothing of its own
  left is blanked.
- Statuses are a fixed vocabulary (`ok, error, aborted, timeout, unfinished, length, unknown`) and
  tool/model/provider names that are not plain identifiers are stored as `unknown`.

## Known limits

- `subagent-artifacts/*.jsonl` are copies of child-run history and are skipped.
- A session tree with abandoned branches is read in file order, not by branch.
- Only wall-clock times Pi or pi-stamp recorded are available. Missing HTTP retries,
  inputs that never became messages (for example after `/reload`), and exact parallel
  overlap on old sessions cannot be recovered from these files.
- `reply.minimal` is a usage-only guess (stop, no tool call, at most 12 output tokens);
  confirm any hit by hand.
- The database is about 0.46 GB for the full history. It is derived: delete it and rebuild.

## Develop

```sh
cd dot_local/share/agent-events && python3 -m unittest -v test_agent_events
```

Fixtures are synthetic; no real session is read. `test_agent_events.py` is source-only
and is listed in `.chezmoiignore`.
