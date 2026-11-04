# agent-events

Read-only, metadata-only tables over Pi session files. It answers "where did this
session's time and tokens go" without a backend, a collector or any new capture.

Phase 0 of the traces research (dotfiles issue #10) built the tables. Phase 1 (below) runs
it in the background, exports aggregate metrics to Grafana, and adds a local drill-down.
Spans in a trace viewer and an emitter extension remain separate, later decisions.
Scope: Pi sessions, plus the review log (section "Review log").

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

## Always on (macOS, chezmoi data `agentEvents`)

A LaunchAgent, `local.agent-events` (source `Library/LaunchAgents/local.agent-events.plist.tmpl`, loaded by
`run_onchange_after_70_agent_events_launchd.sh.tmpl`), runs `agent-events run` every 2 minutes on a Mac where `agentEvents.enabled` is true (nice 10; not launchd's Background class, which macOS throttles to a standstill on a busy machine):

1. an incremental `build` (a few seconds; the first full build takes about 80 s; ticks and manual `agent-events build` runs take one lock, so they wait for each other instead of racing);
2. an aggregate-metrics push to the homelab OTel collector, when `AGENT_EVENTS_OTLP_ENDPOINT` is set. It also needs
   `AGENT_EVENTS_MACHINE`, a slug (a lowercase letter, then up to 31 lowercase letters, digits or hyphens): without one the tick
   builds but sends nothing and logs that once. Both come from the plist (settings below), so a shell does not have them:
   `agent-events status` shows the label the last scheduled run used, not the shell's;
3. a 20-minute watchdog (`AGENT_EVENTS_TICK_LIMIT_S`, a positive number of seconds) that stops a stuck tick so it releases the lock. It is a soft deadline (a SIGALRM handler runs when SQLite or a network call returns), not a hard kill;
4. `status.json`, `agent.log` (rotated at 1 MB) and a lock file in `~/.local/state/agent-events/`.

Self-healing: a database that is corrupt (not a busy or locked one) or three failed builds in a row set it aside as
`events.sqlite.corrupt`, and it is rebuilt from the session files; the database holds only derived data. A failed
push never stops the build and is logged once per distinct failure. Logs and `status.json` hold only an exception
type and an error code, never a path or message text. While the last build failed or the database is dirty, nothing is
recollected: the last accounted business values are sent again, unchanged, with the health gauges.

`agent-events status` prints the age of the last successful build and push and exits 1 when the build is older
than 15 minutes. The same age is in Grafana (`pi_agent_events_last_build_success_timestamp_seconds`, "Data age" on the overview).
Settings, in the machine's local chezmoi config (`~/.config/chezmoi/chezmoi.yaml`):

```yaml
data:
  agentEvents:
    enabled: true    # default: true on personal, false on every other profile
    machine: work    # the machine label on every series; default personal (personal), work (axon-work-computer)
    endpoint: https://otel-collector.internal.cartwmic.com/v1/metrics   # default http://otel-collector.internal.cartwmic.com/v1/metrics
```

- `.chezmoitemplates/agent_events_config` checks them: `enabled` is true or false; `machine` is a slug (a lowercase letter, then up to
  31 lowercase letters, digits or hyphens) and required when enabled; `endpoint` is an http or https URL ending in `/v1/metrics`.
  Any other key or value fails the render of the plist, its load script and `.chezmoiignore`, so a typo applies nothing.
- The plist takes `AGENT_EVENTS_OTLP_ENDPOINT` and `AGENT_EVENTS_MACHINE` from them.
- `.chezmoiignore` gates the agent on macOS and `enabled`, not on the profile. Set `enabled: false` and apply: chezmoi leaves the
  plist alone and the load script unloads the job, then removes the plist. A failed unload fails the apply and keeps the plist, so the
  next apply tries again.
- The work profile is off by default: until `agentEvents` is set there it gets no plist and no load script, as before (the
  `agent-events` CLI is on both). Before turning it on, check the work Mac reaches the collector (the name resolves only through
  the home router's DNS): `curl -so /dev/null -w '%{http_code}\n' https://otel-collector.internal.cartwmic.com/v1/metrics`
  must print `405`.

## Metrics (Grafana)

The scheduled `agent-events run` is the only sender; it sends **aggregates only**: counters of sessions, turns, LLM and tool calls,
seconds (active, LLM, tool, waiting on you, per phase), tokens, notional cost and rule-derived events, plus duration
histograms for LLM and tool calls. Labels: `project` (the repository the cwd belongs to, folding worktrees and run directories into it;
only repositories found under `~/git` and `/Volumes/Workshop/macbook/git` or listed in `AGENT_EVENTS_PROJECTS`
(colon-separated) are named, anything else is `other`), `kind` (`top` or `subagent`), `provider`, `model`, `tool`, `outcome`, `phase`, `event`, `detail` (error class).
Provider, model and tool names must look like an identifier (a path becomes `other`).
Every series also carries `machine` (`AGENT_EVENTS_MACHINE`; a resource attribute, which the collector turns into a label), so two Macs
never write the same series.
No path, prompt, tool argument, result or error text. The only session identifier is the whole session id (a UUID; anything else is not exported) on the four cache gauges below. `agent-events export` previews the series per metric (about 1,600) and
sends nothing (`--dry-run` is accepted and has no effect).

**Prompt-cache gauges (the cache alerts).** Four gauges per session and model, over the trailing 30 minutes, for sessions with a call in that window only:
`pi_cache_hit_ratio_30m` (cacheRead / (cacheRead + cacheWrite + fresh input), token weighted), `pi_cache_calls_30m` (LLM calls that report usage) and
`pi_cache_full_miss_calls_30m` (calls with cacheWrite above 50,000 tokens while under 20% of the prompt came from cache) and
`pi_cache_uncached_tokens_30m` (cacheWrite + fresh input: prompt tokens not served from cache; the low-hit-ratio alert ignores sessions where this is small). Labels: `session` (the whole session id; a session whose id is not a UUID is skipped, so no free text can leave through it; look it up with `agent-events session <id>`), `project`, `model`.
They are gauges, so the window is the whole state: they skip the counter accounting, a finished session's series expire, and they are not sent when a build fails.
A fifth gauge, `pi_cache_miss_streak` (same labels), counts back-to-back full misses in one session and model: consecutive
full-miss calls, each starting less than an hour (`CACHE_TTL_S`, the `PI_CACHE_RETENTION=long` cache lifetime) after the previous
call ended. A call that is not a full miss resets it to 0; so does an idle gap of an hour or more, because after such a gap the
cache may simply have expired, and that first miss counts as 1. It is sent while the session's last call ended under an hour ago.
It never adds calls from different sessions together.
The homelab `PrometheusRule` `pi-cache` alerts on them.

Counters are monotonic by construction. The database is recomputed on every build, so a total can fall (a removed file,
a moved dedupe owner, an unknown duration). The exporter keeps its own accounting in `export_state.json`: an exported value only
rises by the positive change since the last tick, so a recomputation never looks like a Prometheus counter reset. The first push,
a lost or unusable state file, and a changed project map, schema or machine label all start a baseline: current totals become the reference,
so history is never counted as activity. Series new at that point start at 0; known ones keep their exported value and grow from there
(a lost state file starts every series at 0 with a new start time). Growth during the baseline tick itself is not counted. After that a new
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

## Review log

Every build also reads `${AGENT_TRACES_DIR:-~/.local/share/agent-traces}/emitted/review/<item>/findings.jsonl` and the `report.json`
beside it (both defined in `~/.local/share/agent-harness/findings-contract.md`). `agent-traces review` writes the log and the report; a
log kept by hand has no report until `report --all` runs. **The reader computes no trigger.** The stuck trigger, relations, dispositions,
skipped redesigns and state all come from `report.json`.

Tables (`review_items`, `review_rounds`, `review_findings`, `review_redesigns`, `review_escapes`, `review_problems`) hold what is on disk
now: the item, log round, review round, stage, model name, enumerated values, a demoted flag, cost, duration, the report's counts, and a hash
`key` per event. They never hold a free-text field, a session id, a head or a component name. They are rebuilt in one transaction when a log or
report changed in size or mtime, and are for local queries (`agent-events sql`); the exported totals do not come from them directly (see Accounting).

**Strict.** Each of these is counted per item and shows in `status.json` as `review_reader: {ok, problems: {reason: items}}` (no item names), in
`agent-events status`, in one `agent.log` line per change, and in the gauge `pi_review_reader_problem_items{reason}` (0 when none):

| reason | when |
|---|---|
| `findings_schema` | `report.json` has a `findings_schema` that is not 1 |
| `report_schema` | a `report_schema` that is not 1, a report that does not parse or is not a v1 report, or one for another item |
| `unknown_event` | a log line whose `event` is not one of the seven kinds the reader knows (a kind the report lists but the reader does not is still unknown) |
| `bad_line` | a line that does not parse, has a value outside its vocabulary, repeats a round or a finding, or names a round that has no line; also a final line with no newline that is still unfinished on the next look |
| `report_missing` | an item with a `round` event and no `report.json` (every hand-kept log, by design); confirmed on the second look |
| `report_stale` | the report's `log.lines`, or the sum of its `log.events`, differs from the lines counted; or a logged kind is not in `summarises.events`; or its finding ids differ from the log's; confirmed on the second look |
| `orphan_ref` | a `label` or `disposition` whose id names no finding in the log |
| `stray_entry` | a file (not a folder) directly under `emitted/review/` (counted per entry, not per item) |
| `reader_error` | reading an item failed in a way the reader did not expect (counted per item), or the folder could not be listed (1) |

Entries whose name starts with `.` (`.DS_Store`, a hidden folder) are ignored, and say nothing. A log id is `r<N>.` followed by the
return's own id, which the contract allows to be any non-blank string, so the reader accepts spaces, `#` and the like. A line with
deep nesting is a bad line and a report with deep nesting is `report_schema`; nothing in the review folder can fail the Pi build: an
unexpected failure while reading an item is that item's `reader_error`. An unreadable `findings.jsonl` is a `bad_line`.

**Accounting: a ledger, so a total never falls.** The exported totals are sums over a ledger kept in `export_state.json` (`review`), saved in the
same atomic write as the series. An event is counted once, under a key that is a hash of its repo (the part of the item before `#`), the head and
round number or finding id it is about, and what tells two real events about the same thing apart: the line's own `at` (every kind), an escape's
`found_by` and `text`, a redesign's component, action and `makes_impossible`. The key is never removed.
Each tick counts into the ledger what the tables hold that it has not counted yet, then exports the ledger's totals through the usual
`account()`. So however the files change (a broken or lost line, a truncated log, a report that is stale, missing or malformed, a folder moved away
or renamed, a rebuilt database), a total cannot fall and what comes back is not counted again; `account()` never sees a fall from a review series. A
report's relation or outcome is counted the first time a *fresh* report gives it. The two gauges (`pi_review_items`, `pi_review_skipped_redesigns`)
show the folders present now, with each one's last values from a fresh report. The ledger holds hashes, labels and numbers only.

What it cannot guarantee: a counted line whose key field (head, round, id, `at`, component, action, `found_by`, `text`) is edited into a different
valid value counts again, since the key is its meaning; the same line written twice counts once; a finding is counted under the relation or outcome first seen in a fresh report, so a later relabel does not move
it; a lower cost is ignored and a higher one adds the difference; two events whose key fields are all equal (same repo, head, round or id, and the same `at` to the second) are one; a blank or missing
`head` hashes as empty. The golden pairs reuse synthetic heads and timestamps, so the tests tag them; the ledger never shrinks; it is per
machine, so a dashboard summing machines counts a folder once per machine; events in a baseline tick are not counted (see Baseline).

**Staleness counts looks, not time.** `report_stale`, `report_missing` and an unfinished last line are confirmed on the second consecutive *build that looks at the
folder*, whether or not that build rebuilt the tables. One tick that lands between a writer's log append and its report rename sees one stale look and
reports nothing; a hand-appended line stays stale and is reported by the next build, even though that build finds nothing changed and rebuilds nothing. I
chose this over wall-clock age against the log's mtime because it needs no time limit to choose, and "two builds in a row" is what a tick means. A
manual `agent-events build` is a look too.

Series (names start `pi_` because the collector filters on it): counters `pi_review_rounds_total{project,verdict,stage,model}`,
`pi_review_findings_total{project,review_round,effective,stage}`, `pi_review_demoted_total{project}`, `pi_review_redesigns_total{project,action,makes_impossible}`,
`pi_review_escapes_total{project}`, `pi_review_cost_usd_total{project,stage,model}`, `pi_review_relations_total{project,relation}`,
`pi_review_dispositions_total{project,outcome}`; gauges `pi_review_skipped_redesigns{project}`, `pi_review_items{project,state}`,
`pi_review_reader_problem_items{reason}`. `project` is the part of the item before `#`, lower-cased, if it is an approved project, else `other`.
`model` is `unknown` when the round has none and `other` when it is not an identifier.

**Baseline.** The review counters have their own one-time baseline, set by a versioned marker (`seeded_families: ["pi_review@1"]`) and not by
the fingerprint, so no Pi series is touched. On the first tick that runs the ledger while the marker is absent, the review series take their
current totals as the reference and export 0, and the marker is set whether or not any review data existed. A missing or bad ledger (wrong shape, a negative or non-finite total, a label key that is not the JSON of an object of strings) is replaced by one
rebuilt from the files and clears only that marker: the review series baseline again (what they already sent is kept, nothing falls) and the state is
not treated as lost. After the baseline a new series is real activity, so a log first created later counts. Changing what the ledger counts bumps the
marker (`pi_review@2`), which baselines the review series again and nothing else.

The golden pairs in `fixtures/review-golden/` (a `findings.jsonl` and its `report.json`, in the contract's canonical bytes) are the kit's, copied byte for byte
from agent-kit v0.17.0 (`src/traces/fixtures/golden/`), and pinned by `MANIFEST.sha256`, whose own sha256 is in `test_agent_events_review.py`. Change both
copies in one change set. The code deploys to both
profiles; on the work profile its LaunchAgent is off unless `agentEvents` is turned on there.

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
  `sessions.tool_ms` is the sum of top-level tool durations, minus owner questions (top-level ones, and ones made inside a `codemode` script). `active_ms` is the union of LLM and tool intervals (parallel
  work counted once) and excludes owner-wait; a wait inside a `codemode` script is subtracted as a duration, because nested calls carry no timestamps, so `active_ms` is an approximation that can read low. Parallel `codemode` wrappers that each wait are subtracted separately from one interval union, so overlapping waits can remove time that belongs to unrelated work, down to zero (two overlapping 10 s wrappers that each wait 10 s, plus a separate 5 s LLM call, read 0 s active instead of 5 s; the interval union before the subtraction is 15 s). `owner_wait_ms` is the union of top-level owner intervals plus the nested owner durations, while the `owner` phase sums every call's own duration, so two coincident direct 10 s waits read 10 s owner-wait but 20 s of owner phase. `unaccounted_ms` is wall time with no call
  running: idle panes, waiting for you, gaps between steps.
- **Owner wait** is the duration of `ask_user_question` / `notify_owner` tool calls, whether made directly or from inside a `codemode` script (before schema 4 only the direct ones counted, so a wait of hours read as milliseconds). Idle time
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

## Frozen from traces stage 2 (reference tooling)

`agent_events.py`, `agent_events_metrics.py`, `agent_events_review.py` and `agent_events_show.py` are the reference the
kit's `traces` port is compared to, so they do not change while that work runs. `reference.sha256` (sha256sum format) records
their hashes; a unit test fails if a file and its line differ. If a Python fix is unavoidable: make it, re-record the file
(`sha256sum agent_events*.py > reference.sha256`), regenerate `tests/traces-reference/reference-dumps.sha256`, and treat every
parity, replay and shadow result recorded under the old hashes as void.

Tools beside the collector (all exit 2 unless the frozen files match `reference.sha256`):

- `shadow_py_run.py` runs the collector as `agent_events.py` does with the five `pi_cache_*` gauges switched off in memory (the
  Python control arm of the shadow run). `cache_ref.py --scratch DIR --db DIR/events.sqlite --now EPOCH...` prints what
  `cache_gauges` and `miss_streaks` return for a database, as JSON. Both deploy next to the frozen files, with `reference.sha256`,
  when chezmoi data `agentTracesShadow.enabled` is true (default: personal only).
- Source-only (listed in `.chezmoiignore`): `parity_dump.py` (the canonical dump of a corpus; `fp` prints the approved-project
  list and fingerprint), `rollback_drill.py` (can Python load a state file the TS port wrote), `freeze.sh` (a frozen copy of the
  corpus and state for the parity and replay runs), and `reference_common.py` (shared helpers).

Tests: `python3 -m unittest discover -s tests/traces-reference`. Synthetic corpora only.
