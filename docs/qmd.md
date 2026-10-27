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
| Exporter | later PR | `~/.local/share/qmd-corpus` |

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
qmd-refresh [--wait SECONDS] [--no-embed] [--dry-run]
qmd-refresh status        # when the last refresh finished, and whether one is running
```

One blocking command. It runs `qmd update` then `qmd embed` as a single `nice -n 10 heavy-gate --wait 7200 --` job (one slot,
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

## Cost (measured 2026-10-26, this Mac, other jobs running)

`qmd search` 0.2-1 s, 120-180 MB. `qmd query` cold 23-28 s and 5-5.5 GB RSS, repeat 5-10 s and 1.1-2.2 GB. Models 2.1 GB
on disk. No daemon runs unless someone starts `qmd mcp --http`. QMD calls do not coordinate: concurrent calls each load their own
models (upstream issue tobi/qmd#942), so the skill forbids parallel use.

## Other harnesses

The skill is canonical, so Claude and Codex list it too (one name and description line each, a fixed text; it does not change
between sessions, so it does not affect prompt caching). Neither gets an MCP entry or a hook.
