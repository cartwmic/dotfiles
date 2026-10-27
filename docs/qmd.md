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
| Refresh wrapper, exporter | later PRs | `qmd-refresh`, `~/.local/share/qmd-corpus` |

All of it is **personal profile only** (`.chezmoiignore`). The work and Termux profiles get none of it, and the
`run_onchange_after_10_mise_bootstrap` hash covers the new mise file so `mise install` reruns once.

## index.yml is written in qmd's own format

qmd rewrites `index.yml` on every run: it drops comments and appends a `models:` block. A chezmoi-managed file that
differed from that output would show as drifted after the first `qmd` call, and a non-TTY `chezmoi apply` stops on a
destination that changed since chezmoi wrote it. So the template is already in qmd's format (no comments, plain
scalars, explicit `models:` with the 2.8.3 defaults) and qmd leaves it byte-identical. Checked for `status`, `update`,
`search`, `collection list`, `get` (tests/qmd/proof.sh). Because of this, **do not use `qmd collection add` or
`qmd context add`**: edit the template. After bumping the pin, rerun the proof script; if qmd's format changed, re-render
from its output.

Repo-docs collections (`repo-*`) list only checkouts that exist on the machine at apply time (`stat` in the template).
Pattern: `**/README.md,**/AGENTS.md,docs/**/*.md`. Add a repo by adding its name to the `range` list.

## First use on a machine

```sh
qmd pull      # downloads the three models, about 2.1 GB, once, into ~/.cache/qmd/models
```

Until the refresh wrapper lands, the index is built by hand: `nice -n 10 heavy-gate --wait 7200 -- qmd update`, then
`QMD_EMBED_PARALLELISM=1 qmd embed --timeout 0 --max-docs-per-batch 50 --max-batch-mb 8` under heavy-gate. Without
`QMD_EMBED_PARALLELISM=1` embedding peaks at 4.5 GB RSS instead of 1.9 GB.

## Cost (measured 2026-10-26, this Mac, other jobs running)

`qmd search` 0.2-1 s, 120-180 MB. `qmd query` cold 23-28 s and 5-5.5 GB RSS, repeat 5-10 s and 1.1-2.2 GB. Models 2.1 GB
on disk. No daemon runs unless someone starts `qmd mcp --http`. QMD calls do not coordinate: concurrent calls each load their own
models (upstream issue tobi/qmd#942), so the skill forbids parallel use.

## Other harnesses

The skill is canonical, so Claude and Codex list it too (one name and description line each, a fixed text; it does not change
between sessions, so it does not affect prompt caching). Neither gets an MCP entry or a hook.
