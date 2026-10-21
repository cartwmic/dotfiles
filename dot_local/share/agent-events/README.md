# agent-events

Read-only, metadata-only tables over Pi session files. It answers "where did this
session's time and tokens go" without a backend, a collector or any new capture.

This is Phase 0 of the traces research (dotfiles issue #10). Spans in a trace
viewer, an emitter extension and a backend are separate, later decisions.

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
agent-events sql "SELECT ..."   # read-only
```

Python 3.11 or newer, standard library only. A rebuild skips files whose size and
mtime did not change; a changed file is parsed again in full. `--since` builds are
partial and never delete rows for files they did not look at.

Run it whenever you want fresh numbers: `agent-events build` is safe to repeat, incremental and cheap.
Nothing runs on a schedule. `agent-events` is a small wrapper (`dot_local/bin`) around
`agent_events.py`; it picks a Python 3.11+ (override with `AGENT_EVENTS_PYTHON`).
A build that is interrupted marks the database dirty and the next build repairs it.
`sql` accepts only `SELECT`/`WITH` queries under a read-only authorizer (no `ATTACH`, `VACUUM INTO`, `PRAGMA`).

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
