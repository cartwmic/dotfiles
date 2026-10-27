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

All of it is **personal profile only** (`.chezmoiignore`). The work and Termux profiles get none of it, and the
`run_onchange_after_10_mise_bootstrap` hash covers the new mise file so `mise install` reruns once.

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
qmd-refresh [--wait SECONDS] [--no-embed] [--no-export] [--reembed] [--dry-run]
qmd-refresh status        # when the last refresh finished, and whether one is running
```

One blocking command. It runs `qmd-export`, `qmd update` then `qmd embed` as a single `nice -n 10 heavy-gate --wait 7200 --` job (one slot,
waits for a quiet Mac). Nothing schedules it; the owner or an agent the owner asked runs it.

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
    corpus, estimated from 13.8 chunks/s). It records `reembed` first; if it is interrupted, the next plain `qmd-refresh` embeds
    what is missing (without clearing again) and records `506`. It only runs when the pinned model file exists, so a missing model
    never leaves an empty index. `--reembed` with `--no-embed` is a usage error; with another embed model it is ignored.
- **Vector count** is read with `sqlite3` (ships with macOS); if it cannot be read, the index is treated as having old vectors.
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

## Cost (measured 2026-10-26, this Mac, other jobs running)

`qmd search` 0.2-1 s, 120-180 MB. `qmd query` cold 23-28 s and 5-5.5 GB RSS, repeat 5-10 s and 1.1-2.2 GB. Models 2.1 GB
on disk. No daemon runs unless someone starts `qmd mcp --http`. QMD calls do not coordinate: concurrent calls each load their own
models (upstream issue tobi/qmd#942), so the skill forbids parallel use.

## Other harnesses

The skill is canonical, so Claude and Codex list it too (one name and description line each, a fixed text; it does not change
between sessions, so it does not affect prompt caching). Neither gets an MCP entry or a hook.
