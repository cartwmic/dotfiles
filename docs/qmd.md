# QMD search

[QMD](https://github.com/tobi/qmd) (MIT, Tobi Lütke) is a local markdown search engine: SQLite FTS5 (BM25), sqlite-vec vectors,
a query-expansion model and a reranker, all run on this Mac through node-llama-cpp. Michael chose it as the one search index
for notes, repo docs, Pi session recaps and Pi sessions, with hybrid (semantic) search as the default query path
(ask #159 = C, ask #160 = default; 2026-10-26). Research and measurements: `~/tmp/qmd/PLAN.md` (scratch, not in the repo).

## What is in the repo

| Step | Source | Lands at |
|---|---|---|
| Install, pinned | `dot_config/mise/conf.d/qmd.toml` | `~/.config/mise/conf.d/qmd.toml`; `mise install` fetches `@tobilu/qmd@2.8.3` (200 MB, no models) |
| Collections | `dot_config/qmd/index.yml.tmpl` | `~/.config/qmd/index.yml` |
| Skill | `dot_local/share/agent-harness/canonical/skills/searching-with-qmd` | skill sync links it into Claude, Codex and Pi |
| Refresh wrapper | `dot_local/bin/executable_qmd-refresh` | `~/.local/bin/qmd-refresh` |
| Exporter | `dot_local/bin/executable_qmd-export` | `~/.local/bin/qmd-export`; writes `~/.local/share/qmd-corpus/{sessions,recaps}` |
| `qmd` on PATH | `dot_local/bin/executable_qmd` | `~/.local/bin/qmd`, a 20-line wrapper around the mise shim ([qmd on PATH](#qmd-on-path)) |
| Scheduled refresh (macOS) | `Library/LaunchAgents/local.qmd-refresh.plist.tmpl`, `dot_local/bin/executable_qmd-refresh-scheduled`, `run_onchange_after_71_qmd_refresh_launchd.sh.tmpl`, `.chezmoitemplates/qmd_refresh_minutes` | `~/Library/LaunchAgents/local.qmd-refresh.plist`, `~/.local/bin/qmd-refresh-scheduled` ([Scheduled refresh](#scheduled-refresh)) |
| Daily cleanup switch | `dot_config/qmd/refresh.conf.tmpl`, `.chezmoitemplates/qmd_refresh_cleanup` | `~/.config/qmd/refresh.conf` (`cleanup=on` or `off`; [Daily cleanup](#daily-cleanup)) |

All of it is on the **personal and work (`axon-work-computer`) profiles**, not Termux (`.chezmoiignore`; decision 303: QMD on both). The
`run_onchange_after_10_mise_bootstrap` hash covers the mise file on both, so a full apply reruns `mise install` once. See
[The work profile](#the-work-profile-axon-work-computer).

## index.yml is written in qmd's own format

qmd rewrites `index.yml` (dropping comments and re-serialising) when its `models:` block is missing or incomplete,
and on `qmd collection add` / `qmd context add`. A chezmoi-managed file that qmd rewrote would show as drifted, and a
non-TTY `chezmoi apply` stops on a destination that changed since chezmoi wrote it. We saw this directly: a commented
template without `models:` was rewritten by the first `qmd` call. So the template is plain (no comments, no blank lines,
unquoted scalars where qmd would not quote them) and carries the full 2.8.3 `models:` block, and qmd leaves it
byte-identical. Checked after `status`, `update`, `search`, `collection list`, `get` and `query` (tests/qmd/proof.sh).
Do **not** use `qmd collection add` or `qmd context add`: edit the template. After bumping the pin, rerun the proof
script and compare qmd's default `models:` block with the template's.

qmd also picks a project-local `.qmd/index.yaml` from the current directory or an ancestor over the global config unless
`--index` is given. None exist today; do not create one under a repo you search from, or pass `--index index`.

Repo-docs collections (`repo-*`) list only checkouts that exist on the machine at apply time (`stat` in the template).
Pattern: `**/README.md,**/AGENTS.md,docs/**/*.md`. Add a repo by adding its name to the `range` list.

## First use on a machine

```sh
qmd pull      # downloads the three models, about 2.1 GB, once, into ~/.cache/qmd/models
```

## Refreshing the index: `qmd-refresh`

```sh
qmd-refresh [--wait SECONDS] [--no-embed] [--no-export] [--no-cleanup] [--reembed] [--dry-run]
qmd-refresh status        # when the last refresh and the last cleanup finished, and whether one is running
```

One blocking command. It runs `qmd-export`, `qmd update`, `qmd embed` and, at most once a day, `qmd cleanup` ([Daily cleanup](#daily-cleanup)) as a single `nice -n 10 heavy-gate --wait 7200 --` job (one slot,
waits for a quiet Mac). On macOS a launchd agent runs it every hour ([Scheduled refresh](#scheduled-refresh)); the owner, or an agent the
owner asked, can also run it by hand.

- Embed uses `QMD_EMBED_PARALLELISM=1 --timeout 0 --max-docs-per-batch 50 --max-batch-mb 8`: 1.9 GB RSS instead of 4.5 GB at
  qmd's defaults, same speed; `--timeout 0` removes qmd's hard 30-minute cap (tobi/qmd#673). Only changed documents are
  embedded, so an interrupted run resumes.
- One refresh at a time: an `flock(2)` on `~/.local/state/qmd-refresh/lock`, taken before heavy-gate starts and inherited by
  every process of the job. A second run exits 75. The kernel drops the lock when the last process of the job exits, so there is
  no pid file to go stale or be reused, and a wrapper killed with SIGKILL does not free the lock while its job still runs.
- TERM, INT or HUP: the wrapper polls (no blocking wait, so a signal at any moment is handled), sends TERM leaves first, re-snapshots
  the job's tree for up to `QMD_REFRESH_GRACE` seconds (default 10), then KILLs it, and exits 143. It has to do this because
  heavy-gate runs its job in the foreground and would otherwise defer the signal until a 45-minute embed ended. Not handled: a
  SIGKILL of the wrapper itself, or a process that escapes the tree; the job lives on and keeps the lock until it is gone
  (the wrapper says so when it sees a survivor).
- qmd has no offline switch and downloads a missing model by itself, and which model it picks depends on `QMD_EMBED_MODEL`,
  `index.yml` and a project-local config. So embed runs only for the **pinned** model
  (`embeddinggemma-300M-Q8_0`, as in `index.yml.tmpl`): if `QMD_EMBED_MODEL` is set or `index.yml` names another embed model,
  only `update` runs. The pinned file (`hf_ggml-org_embeddinggemma-300M-Q8_0.gguf` under `~/.cache/qmd/models`) must also exist,
  checked after the gate wait, just before embedding; otherwise only `update` runs and it says to run `qmd pull`. The job runs
  in `~/.local/state/qmd-refresh` so a `.qmd/index.yaml` in the caller's directory is not picked up. To change the model, edit the
  template and the wrapper together.
- `--wait` is how long heavy-gate may wait for a quiet Mac, not a run-time limit. Exit: 0 ok, 75 another refresh is running
  (reported out of band) , 127 qmd, heavy-gate or perl missing, 143 stopped by a signal, otherwise the job's or heavy-gate's own status
  unchanged (heavy-gate's 75 means it gave up waiting). The last success is stamped in `~/.local/state/qmd-refresh/last-success`.

Verified live (2026-10-27, personal Mac, after `qmd pull`): `qmd-refresh` updated 9 collections and embedded 2,085 chunks from 411
documents in 2 min 31 s (3 min 8 s wall, 1.6 GB peak RSS), and `~/.config/qmd/index.yml` stayed identical to the chezmoi source
(`chezmoi diff` empty) — the first proof on the real applied file.

## Scheduled refresh

On macOS (personal and work profiles) a launchd user agent, `local.qmd-refresh`, runs a plain `qmd-refresh` every 60 minutes. Never
`--reembed`. It is set in **local chezmoi data**, `qmd.refresh.enabled` and `qmd.refresh.intervalMinutes`
(`~/.config/chezmoi/chezmoi.yaml`, not the repo):

```yaml
data:
  qmd:
    refresh:
      enabled: true          # false: no agent (chezmoi removes the plist; the apply unloads it)
      intervalMinutes: 60    # whole minutes, 15 to 1440
```

Both keys are optional; the defaults are `true` and `60`. Change a value and run `chezmoi apply`: the plist is rewritten and
`run_onchange_after_71_qmd_refresh_launchd.sh` runs again (its hash covers the plist template and the setting). It does
`launchctl bootout gui/$UID/local.qmd-refresh`, then `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/local.qmd-refresh.plist`,
or, when disabled, removes the plist and loads nothing. If launchd does not end up as the setting asks (the unload or load fails;
loading needs a GUI login session, so an apply over ssh alone fails here), the script fails the apply and chezmoi runs it again on the
next apply. Any other value (`5`, `90.5`, `hourly`, `enabled: "yes"`) fails the render,
so a typo applies nothing rather than scheduling something else. A bootout stops a run in progress (qmd-refresh stops its job tree
on TERM); the next run starts one interval after the load.

| Piece | Does |
|---|---|
| `Library/LaunchAgents/local.qmd-refresh.plist.tmpl` | `StartInterval` = interval; `RunAtLoad` false, so an apply or a login does not start a heavy job; `PATH` with the mise shims first (qmd, node, python3) |
| `~/.local/bin/qmd-refresh-scheduled` | what the agent runs: `qmd-refresh --wait <interval in seconds>`, and the log |
| `.chezmoitemplates/qmd_refresh_minutes` | reads and checks the setting; used by the plist and the load script |
| `run_onchange_after_71_qmd_refresh_launchd.sh.tmpl` | `print` (is it loaded?), bootout, then bootstrap (or remove when off). No other `launchctl` verb |

**No second gate.** The agent adds no heavy-gate, `nice`, lock or launchd `Nice` of its own: `qmd-refresh` already runs its job as
`nice -n 10 heavy-gate --wait N --` under its `flock`. heavy-gate may wait up to one interval for a quiet Mac, then gives up (75)
and the next tick tries again. launchd never starts a second copy of a running agent, and the lock refuses one started by hand,
so runs cannot pile up. Not `ProcessType` Background: macOS throttles such a job to a near stop on a busy Mac (see
`local.agent-events`), and this one holds a heavy-gate slot while it runs.

**Log:** `~/Library/Logs/qmd-refresh/qmd-refresh-YYYY-MM-DD.log`, one block per run between `== <time> start` and `== <time> end rc=N
after Ns`. It keeps qmd-refresh's own lines and qmd's counts (documents written, indexed, chunks embedded) and collection paths: no
document text, no environment, no secrets. Status 75 (lock held, or heavy-gate gave up) is one `skipped` line. Dropped: terminal
escapes, progress bars, heavy-gate's echo of the job script, and the per-chunk "truncated to fit embedding context" warnings (one
count line instead; they are expected, see below). A run is about 3 KB. Bounded: day files older than 14 days are deleted; a day file
never grows past 2 MB (output is filtered as it is read, a run's output is cut to the room left, and a full file gets nothing more
that day); `launchd.log` (the runner's own stray output) is emptied when over 2 MB.

```sh
tail -n 30 ~/Library/Logs/qmd-refresh/qmd-refresh-$(date +%F).log
launchctl print gui/$(id -u)/local.qmd-refresh | grep -E 'state|last exit|run interval'
qmd-refresh status
```

Turn it off: set `enabled: false` and apply (as above). By hand, until the next apply: `launchctl bootout gui/$(id -u)/local.qmd-refresh`.

### What an hourly run costs (measured 2026-10-27, personal Mac, other jobs running)

| Run | Wall | CPU (user+sys) | Peak RSS | Work |
|---|---|---|---|---|
| after about 2 h | 172 s | 38 s | 1.9 GB | 297 docs exported, 333 docs and 2,374 chunks embedded |
| 15 min after that | 145 s | 30 s | 1.96 GB | 32 docs exported, 33 docs and 1,689 chunks embedded |

- **It will nearly always have work.** Over the last 24 hours every hour had changed sessions (1 to 36 per hour), recaps (6 to 81) or
  notes. qmd embeds per document, so a session that changed is embedded again whole: one long Pi session that stays open (the
  coordinator's, 1,025 chunks) alone means about 1,000 chunks every hour, and busy hours reach about 1,800. The embed runs on the GPU
  (Metal); hence the low CPU. Expect 2 to 3 minutes and about 2 GB each hour, at `nice 10`, inside one heavy-gate slot.
- **Disk:** the index (`~/.cache/qmd/index.sqlite`, 557 MB now) keeps the vectors of a document's old version: `qmd update` drops
  old content but not old vectors (`qmd cleanup` does). About 3 KB per chunk, so 3 to 5 MB per run, roughly 70 to 120 MB a day.
  `qmd cleanup` on a copy of today's index removed 4,820 such chunks in 4.7 s (115 MB RSS) and shrank it by 15 MB. `qmd-refresh`
  now runs it once a day: [Daily cleanup](#daily-cleanup).

## Daily cleanup

`qmd update` replaces a changed document's text but leaves the vectors of its old version in the index, so the index grows by every
chunk that is embedded again (3 to 5 MB per hourly run, 70 to 120 MB a day here). `qmd-refresh` therefore ends its job with
`qmd cleanup`, **at most once per 24 hours**, inside the same lock and the same `nice -n 10 heavy-gate` job as the refresh: no second
gate, no second lock, no extra launchd agent. It runs only after export, update and embed succeeded (also when embed was skipped for
a missing model, or with `--no-embed`).

What `qmd cleanup` (2.8.3, `runCleanup` in `store.js`) does, in this order:

- empties qmd's LLM response cache (query expansion and rerank answers, now and then pruned to the newest 1,000 rows; it was empty here). The next hybrid
  query with the same words computes them again.
- deletes the vectors whose content no **active** document refers to: old versions of changed documents, and documents whose file
  is gone. A vector an active document uses is never touched (`WHERE NOT EXISTS (… d.hash = cv.hash AND d.active = 1)`).
- deletes inactive document records (files that were removed; `qmd update` only marks them) and content rows nothing refers to.
- compacts the full-text index and runs `VACUUM`, which rewrites the file: it briefly needs free disk about the size of the index
  (550 MB). A `qmd search` or `qmd query` started meanwhile waits (qmd's SQLite busy timeout is 120 s) rather than failing.

**Guard: a missing or emptied collection folder.** `qmd update` does not check that a collection's folder exists: if the
`/Volumes/Workshop` disk is not mounted, say, it marks that collection's documents inactive, and a cleanup would then drop their
vectors, so they would be embedded again once the disk is back. So the cleanup is skipped, with one line in the log, and tried
again on the next refresh, when:

- a collection folder is missing. The folders are read from the index's `store_collections` table, which qmd fills from its own
  parse of `index.yml` and which `qmd update` globs, so no YAML is parsed here;
- a collection has inactive documents and no active one left (a folder that exists but is empty, such as an empty mount point);
- the index or its collection list cannot be read, or the list is empty.

A collection whose files were all really deleted also holds the cleanup off until it is removed from `index.yml` (then qmd drops
it from the table) or `qmd cleanup` is run by hand.

**When it runs.** `~/.local/state/qmd-refresh/last-cleanup` holds the time of the last successful cleanup. A refresh 24 h or more after
it runs the cleanup; earlier it skips quietly. A held lock exits 75 as before (nothing runs). A failed cleanup is logged
(`qmd cleanup failed (status N)`) but does not fail the refresh, and the next refresh tries again. The scheduled log and
`qmd-refresh` say `update + embed + cleanup` on the run that did it; `qmd-refresh status` prints the last cleanup.

**Switch.** Local chezmoi data `qmd.refresh.cleanup`, default on:

```yaml
data:
  qmd:
    refresh:
      cleanup: true          # false: qmd-refresh never runs qmd cleanup
```

It renders `~/.config/qmd/refresh.conf` (`cleanup=on` or `cleanup=off`), which `qmd-refresh` reads on every run, scheduled or by hand;
a missing file means on. It is independent of `qmd.refresh.enabled`. Any other value fails the render (`"yes"`, `1`). A file that
exists must hold exactly one line besides comments and blank lines, `cleanup=on` or `cleanup=off`; anything else (`cleanup=yes`,
`cleanup=`, `cleanup =off`, two lines, an empty or unreadable file) makes `qmd-refresh` exit 2 before it runs anything. `--no-cleanup` skips it for one run.

**Measured** (2026-10-27/28, personal Mac, on a `.backup` copy of the live index, never the index itself):

| | Before | After |
|---|---|---|
| index file | 556.5 MB | 541.1 MB |
| vectors (chunks) | 63,950 | 59,130 (4,820 orphaned removed) |
| active documents without vectors | 0 | 0 |
| time, peak RSS | | 3.5 s (0.9 s user, 2.3 s sys), 117 MB; a first copy earlier the same day took 4.7 s and 115 MB |

**There is no undo.** The removed vectors belong to text no current document has, so nothing a search can find goes away. To get
them back you would have to re-embed: a plain `qmd-refresh` embeds every active document that lacks vectors (only those), at about
18 chunks a second and 1.9 GB RSS; a full `qmd-refresh --reembed` redoes everything, about 55 to 80 minutes for this corpus. The
code itself rolls back with `git revert` and an apply, or `cleanup: false`.

## qmd on PATH

mise puts qmd's install directory on PATH only in a shell where mise is activated, at the moment it activates
(`private_dot_zshrc`). A non-interactive shell does not activate it, and a process keeps the PATH it started with. Pi's bash tool
runs `bash -c` with the environment of the Pi that started it, so Pi sessions and the coordinator pane often had no `qmd`.

`~/.local/bin/qmd` (`dot_local/bin/executable_qmd`) fixes that: `~/.local/bin` is on PATH in every zsh (`~/.zshenv`), so the one file
reaches every Pi, its children and sessions already running. It runs the mise shim
(`${MISE_DATA_DIR:-~/.local/share/mise}/shims/qmd`), which picks the pinned version and puts node on PATH. In an activated shell
mise's directory comes first and the wrapper is not used. If mise cannot resolve qmd the shim would search PATH and find the wrapper
again; `QMD_PATH_WRAPPER` stops that loop (exit 127 with a hint), as does a missing shim.

Checked 2026-10-27: a `pi -p` child started with only a running Pi's PATH (no mise directory) could not find `qmd`; with the wrapper
on that PATH, the same child's bash tool printed `qmd 2.8.3 (facd35e)` in 0.3 s. Not changed: `~/.zshenv`, the mise setup, Pi.

## Long chunks: `QMD_EMBED_CONTEXT_SIZE=506` (stop-gap for tobi/qmd#897)

QMD 2.8.3 makes chunks of about 900 tokens but builds its embedding context with a 512-token physical batch (open issue
tobi/qmd#897; fix proposed in #993, unmerged). A chunk of 511+ tokens is then embedded from its last micro-batch only, so the
vector describes the end of the chunk. Measured on the live index (2026-10-27, read-only, copy of the index): 76.6% of 2,085 chunks
were 511+ tokens, and their stored vectors had cosine 0.2-0.8 against the same text embedded whole. Chunks up to 510 tokens were
identical. BM25 and the reranker see the full text and are not affected; only the vector half of `qmd query` and `qmd vsearch`.

`qmd-refresh` therefore runs the embed step with `QMD_EMBED_CONTEXT_SIZE=506` (the update step is not given it). QMD then clips every
input to its first ~500 tokens, which fit one batch.

- **What it costs:** the vector covers the first ~500 tokens of a chunk (title included); the rest of a long chunk is found by keyword
  search only. Better than today (end only), not as good as the whole chunk.
- **Old vectors are not redone by a plain `qmd embed`** (the embedding fingerprint does not include the context size). So
  `qmd-refresh` records in `~/.local/state/qmd-refresh/embed-context` what made the vectors:
  - no index or no vectors yet: everything is made with the setting; it records `506`.
  - an index that already has vectors and no record: they may be wrong. `qmd-refresh` still does the normal refresh, then prints
    a `NOTE` (every run) and `qmd-refresh status` says "may predate". It never clears vectors by itself.
  - `qmd-refresh --reembed` runs `qmd embed -f`: clears every vector, then embeds everything (about 80 minutes for the session
    corpus, estimated from 13.8 chunks/s). It only runs when the pinned model file exists, so a missing model never leaves an empty
    index. It records `reembed <UTC start time>` first. **`506` is recorded only when it is shown**: after the embed, no vector row
    (`content_vectors.embedded_at`) may be older than that start. An exit status is not proof (qmd exits 0 without doing anything
    when another embed holds its lock, and it clears the vectors only later, after taking it). If the clear never happened, the
    marker stays, the NOTE keeps appearing and `status` says "not confirmed"; run `--reembed` again. If it was interrupted after the
    clear, the next plain `qmd-refresh` embeds what is missing (no second clear) and then confirms it the same way.
    `--reembed` with `--no-embed` is a usage error; with another embed model it is ignored.
- **Vector rows** are read with `sqlite3` (ships with macOS); if they cannot be read, the index is treated as having old vectors. They are read with a plain open, not `sqlite3 -readonly`: qmd's index is in WAL mode, and a read-only open of it fails when no `-wal`/`-shm` files exist, which is the state after qmd exits (found on the first real full re-embed, 2026-10-27).
- **When to remove this:** once the pinned QMD contains the #897 fix, drop the variable and the bookkeeping, bump the pin, and do one
  `--reembed` (vectors made from clipped input differ from whole-chunk ones).

### Later decision: the proper fix (not part of this change)

Two ways, both Michael's call:
1. **Wait for upstream #993, then bump the pin** in `dot_config/mise/conf.d/qmd.toml`. Nothing to maintain; no date.
2. **Install a patched fork** whose `createEmbeddingContext` calls pass `batchSize: contextSize` (llm.js:842-845 in 2.8.3). mise can
   install npm packages from Git: its npm backend docs (mise.jdx.dev/dev-tools/backends/npm.html, "Install from Git") show
   `mise use 'npm:github:owner/repo@v1.2.0'` or `npm:git+https://github.com/owner/repo`, the version being a tag, branch or commit.
   So the pin line would become a fork ref. **Not verified:** that it works with the mise on this Mac (2026.7.18; the docs read are
   current), and that the build runs on a Git install. tobi/qmd git-ignores `dist/` and builds it in its `prepare` script
   (`node scripts/build.mjs`), which needs devDependencies; an install that skips `prepare` would give a package with no `dist`.
   It must be tried once before relying on it. The work Mac would then fetch a fork from GitHub instead of the npm registry,
   which the work-profile PR would have to disclose.

## The session corpus: `qmd-export`

QMD indexes markdown files, so the Pi sessions and session-recap records are exported to markdown first (`qmd-refresh` does
this as the first step of its job; `qmd-export` also runs alone). Stdlib Python 3.9+, no network.

| Reads | Writes |
|---|---|
| `~/.pi/agent/sessions/**/*.jsonl` | `~/.local/share/qmd-corpus/sessions/<day>/<session-id>.md` |
| `~/.local/share/session-recap/records/<day>/<record>.json` | `~/.local/share/qmd-corpus/recaps/<day>/<record-id>.md` |

Everything is relative to the machine's own home directory, so it is identical on every profile (a work Mac exports its own
sessions and recaps; nothing is copied between machines).

- **What goes in:** user and assistant text (4000 characters per message), compaction summaries (8000), recap summaries, with
  the session id, cwd and start time as frontmatter. Tool results, thinking, system and custom entries stay out. Headings
  inside message text are escaped so they do not split chunks. Sub-agent sessions (`.../run-0/session.jsonl`) are included;
  two files with one session id get a hash suffix.
- **Incremental:** a source whose output exists and is not older than it is skipped without reading it (a session's id and day
  come from its first line). A source with nothing to export is remembered by mtime in `.qmd-export-state.json`.
  Measured here: first run 48 s, 203 MB RSS, 8,359 sessions and 8,777 recaps -> 135 MB; second run 2.3 s.
- **90 days:** sources last modified more than `--days` (default 90) days ago are not exported and their outputs are deleted,
  as are outputs whose source is gone. This bounds the index. It is by modification time, so a session you resume comes back.
- **Safe to run:** one exporter at a time (a lock in the output directory; a second one exits 3, so `qmd-refresh` fails clearly if a
  standalone export is running). An output is reused only if it was rendered from the same source file (the state file records
  which), so when one of two files with the same session id goes away the other is re-rendered, not mixed up. A source that
  cannot be stat-ed counts as an error and suppresses pruning. Nothing is pruned from a source root that is missing or unreadable (an unmounted disk does not wipe the
  corpus), and the program refuses a non-empty output directory that it did not create (`.qmd-corpus` marker). Files are
  written whole and renamed into place. `--dry-run` changes nothing.
- The file names are what `qmd get qmd://sessions/<day>/<id>.md` and the skill's hits show.

## The work profile (axon-work-computer)

The same files land on the work Mac as on the personal one (the pin, `qmd-refresh`, `qmd-export`, the skill, the same models, the `qmd` wrapper and the scheduled refresh). Only `index.yml.tmpl` renders differently:
`notes` only if `~/tmp` exists there, and the repo collections are the checkouts that exist under `~/git` (`coordinator`, `retro`) instead of `/Volumes/Workshop/macbook/git`. `repo-dotfiles`, `sessions`, `recaps` are on both. The sessions and
recaps are the work Mac's own; nothing moves between machines. Termux gets none of it.

**What leaves the machine.** Checked in the pinned `@tobilu/qmd@2.8.3` package (the unpacked `dist/`), on 2026-10-27:
- The only network call in qmd's own code is `getRemoteEtag` (`dist/llm.js:158-171`): a `HEAD` request to `huggingface.co/<repo>/resolve/main/<file>`, called from `pullModels` (`qmd pull`)
  to compare a model's ETag. It sends no document or query text. The URL is fixed to huggingface.co in qmd; `HF_ENDPOINT` is honoured only by the model downloader of the dependency.
- Model files are downloaded by `node-llama-cpp` from the same `hf:` URIs (the three in `index.yml`) during `qmd pull`, or by `embed`/`query` if a model file is
  missing. After that, search, embed and query run on the Mac; the index never leaves it.
- A search of `dist/` for telemetry, analytics, crash-report or similar code finds none. The only server code is `qmd mcp --http` (`dist/mcp/server.js`): it binds to `localhost`
  unless `QMD_HOST` says otherwise and checks `Origin`/`Host` against loopback (`origin-guard.js`, against DNS rebinding). Nothing starts it; the skill tells agents not to.
- Observed, not just read: while a real `qmd query` ran (models cached, 48 s), `lsof -i` was sampled every 0.3 s on the qmd processes (33 samples, 2 pids): **no sockets at all**.
- Not covered: the dependencies' own code beyond one look. `node-llama-cpp` can fetch llama.cpp release data from GitHub and compile when no prebuilt binary fits the machine; the Apple Silicon
  prebuilt (`@node-llama-cpp/mac-arm64-metal`) is in the package here, so that path did not run. Whether the work Mac is Apple Silicon is not known to this change.

**What the work Mac downloads.** All from public hosts, once:
- `mise install`: the npm package `@tobilu/qmd@2.8.3` and its dependencies from the npm registry (129 packages, about 200 MB unpacked; MIT/ISC/Apache/BlueOak licences). Install scripts run for
  `node-llama-cpp` (`postinstall`) and five `tree-sitter-*` grammars (`node-gyp-build`, which uses a shipped prebuild and only compiles if there is none).
- `qmd pull`: the three GGUF models from huggingface.co, 2.1 GB (`embeddinggemma-300M-Q8_0`, `qmd-query-expansion-1.7B-q4_k_m`, `qwen3-reranker-0.6b-q8_0`).
- If a corporate proxy re-signs TLS, `qmd pull` can fail on the certificate; `NODE_EXTRA_CA_CERTS` is the usual fix. Not tried on the work network.
  The model files can also be copied into `~/.cache/qmd/models` by hand under the same file names.

**What is stored on the work Mac, in plain text.** `qmd-export` copies the user and assistant text of Pi sessions (90 days) and the recaps to `~/.local/share/qmd-corpus`, and the index
(with embeddings) is `~/.cache/qmd/index.sqlite`. Neither is in the dotfiles repo or synced. Work conversations are therefore in one more place than before.

**The hourly job.** The work Mac gets the same launchd agent (`local.qmd-refresh`, [Scheduled refresh](#scheduled-refresh)): a recurring
background job on the employer laptop, on by default once the plist is applied, first run one interval after it is loaded.
- What it runs: `qmd-export`, `qmd update`, only if the pinned model file is already there `qmd embed`, and once a day `qmd cleanup`
  ([Daily cleanup](#daily-cleanup); local SQLite work, no model, no network), as one `nice -n 10`
  heavy-gate job that waits for a quiet Mac. It never downloads: without the model it skips embedding (qmd downloads a model only in
  `qmd pull` or an embed/query that runs without it, and `qmd-refresh` checks the file first). No network, no new data leaves the Mac.
- What it costs: on the personal Mac 2 to 3 minutes, about 30 to 40 s of CPU and 1.9 to 2 GB peak RSS per hourly run, nearly every hour
  (long open Pi sessions are re-embedded whole). Disk: the daily `qmd cleanup` removes the old vectors that would otherwise add
  roughly 70 to 120 MB a day (on the personal Mac 3.5 s and 117 MB RSS once a day; it rewrites the index, so it needs free disk
  about the index size for a moment). The work Mac's numbers depend on its own sessions. The first run after `qmd pull` embeds the whole corpus
  (55 min on the personal Mac); run `qmd-refresh` by hand once, as in the steps below, so it is not left to a background tick.
- What it logs: `~/Library/Logs/qmd-refresh/`, one short block per run with qmd's counts and collection paths (no document text,
  no environment, no secrets), 14 days, 2 MB a day at most.
- Turn it off: `qmd: {refresh: {enabled: false}}` in `~/.config/chezmoi/chezmoi.yaml` (before the first apply, so it is never
  loaded, or later), then apply; `launchctl bootout gui/$(id -u)/local.qmd-refresh` stops it at once. The daily cleanup alone:
  `qmd: {refresh: {cleanup: false}}`, then apply `~/.config/qmd/refresh.conf`.

**Cost.** Same as above, per machine. The first `qmd-refresh` embeds the whole corpus: on the personal Mac 58,056 chunks took 55 min (about 18 chunks/s, 1.9 GB peak RSS). The work
corpus is its own size; `qmd-export --dry-run` and then the `qmd update` line of the first run show the document count. Everything above about `QMD_EMBED_CONTEXT_SIZE=506` applies unchanged:
a fresh work index has no old vectors, so the first `qmd-refresh` records `506` itself and no `--reembed` is needed. If the fork route (above) is chosen later, the work Mac would fetch from GitHub
instead of npm: that needs a fresh look from the work side.

**Apply on the work Mac** (Michael; scoped, as usual):

```sh
git -C ~/.local/share/chezmoi pull --ff-only
chezmoi --source ~/.local/share/chezmoi apply --dry-run --verbose ~/.config/mise/conf.d/qmd.toml ~/.config/qmd/index.yml ~/.config/qmd/refresh.conf \
  ~/.local/bin/qmd-refresh ~/.local/bin/qmd-export ~/.local/share/agent-harness/canonical/skills/searching-with-qmd \
  ~/.local/bin/qmd ~/.local/bin/qmd-refresh-scheduled ~/Library/LaunchAgents/local.qmd-refresh.plist ~/71_qmd_refresh_launchd.sh
chezmoi --source ~/.local/share/chezmoi apply ~/.config/mise/conf.d/qmd.toml ~/.config/qmd/index.yml ~/.config/qmd/refresh.conf \
  ~/.local/bin/qmd-refresh ~/.local/bin/qmd-export ~/.local/share/agent-harness/canonical/skills/searching-with-qmd \
  ~/.local/bin/qmd ~/.local/bin/qmd-refresh-scheduled ~/Library/LaunchAgents/local.qmd-refresh.plist ~/71_qmd_refresh_launchd.sh
                                      # the last two load the hourly agent (omit them, or set enabled: false, to leave it off)
mise install                          # npm package, about 200 MB
mise exec -- ~/.local/user_scripts/apply_harness_config.sh   # links the skill into Claude, Codex and Pi (needed after a full apply too)
qmd pull                              # 2.1 GB of models, once
qmd-export --dry-run                  # how many sessions and recaps it would write
qmd-refresh                           # export, update, embed in one gate job; the first one is long
qmd-refresh status
qmd search "something you know is in your notes"
```

A full `chezmoi apply` also works and re-runs the bootstrap once (the new work hash line in `run_onchange_after_10_mise_bootstrap`), which includes `mise install`. It does **not** reliably link the skill: the harness-config script hashes skill names from the source tree, where this skill has existed since #81, so on an up-to-date work Mac it is skipped. Run the `apply_harness_config.sh` line either way.

## Cost (measured 2026-10-26, this Mac, other jobs running)

`qmd search` 0.2-1 s, 120-180 MB. `qmd query` cold 23-28 s and 5-5.5 GB RSS, repeat 5-10 s and 1.1-2.2 GB. Models 2.1 GB
on disk. No daemon runs unless someone starts `qmd mcp --http`; the scheduled refresh is a launchd job that exits after each run. QMD calls do not coordinate: concurrent calls each load their own
models (upstream issue tobi/qmd#942), so the skill forbids parallel use.

## Other harnesses

The skill is canonical, so Claude and Codex list it too (one name and description line each, a fixed text; it does not change
between sessions, so it does not affect prompt caching). Neither gets an MCP entry or a hook.
