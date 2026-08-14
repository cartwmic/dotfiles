# session-search (personal / homelab)

Chezmoi source for Pi session-search's **global** config. Destination is
`~/.pi/session-search`. This tree is personal-profile only: repo-root
`.chezmoiignore` drops `.pi/session-search` and `.pi/session-search/**` when
`.profile` is not `personal`. Do not copy these files onto `axon-work-computer`
or Termux. Work stays fts-raw.

The `pi-session-search` package itself is installed from Pi settings on every
non-Termux machine. These two files are the homelab opt-in that switches
**personal** Pi from FTS-raw keyword search to digest-hybrid (Ollama embeddings
plus claude-bridge summaries).

## Overview

[config.json](./config.json) is the embedder. [digest.json](./digest.json) is
the digest LLM. Together they select `digest-hybrid`: cosine over digest-body
embeddings plus BM25 over digest body and raw content.

| File | Role | Values in this tree |
| --- | --- | --- |
| [config.json](./config.json) | OpenAI-compatible embedder (`POST <baseUrl>/v1/embeddings`) | model `nomic-embed-text:latest`, baseUrl `https://ollama.internal.cartwmic.com` |
| [digest.json](./digest.json) | Explicit digest model (never auto-selected) | provider `claude-bridge`, model `claude-haiku-4-5` |

Remaining digest fields are the package defaults already filled in:
`debounceSeconds` 60, `resummarizeTokenThreshold` 10000, `maxTokens` 1500,
`showWidget` false, `verbose` false.

`apiKey` in [config.json](./config.json) is the dummy string `ollama` that
Ollama's OpenAI-compatible endpoint expects. It is not a credential. The
internal hostname is already in the JSON and is not a secret.

Runtime artifacts (`index/`, `digests/`) live only at the destination. They are
not source and must not be added here.

Without both a working embedder and a digest model that resolves in the live
registry, the package stays `fts-raw` (no digest.json) or enters a
**misconfigured** verdict (digest.json present but embedder or model missing).
That is why work and Termux must not receive this tree: they do not have
`ollama.internal` or the personal-only `claude-bridge` package.

## Setup

Confirm you are in chezmoi **source**, not the live dest:

```sh
cd ~/.local/share/chezmoi/dot_pi/session-search && ls -1
```

You should see [config.json](./config.json), [digest.json](./digest.json), and
this README. Destination mapping:

```sh
chezmoi source-path ~/.pi/session-search
```

That must print this directory. Confirm the active profile before any apply
(apply is the parent-tree procedure; do not apply from here):

```sh
chezmoi execute-template '{{ .profile }}'
```

Expected on this machine: `personal`. If that prints `axon-work-computer` or
`termux`, stop — this tree is ignored there on purpose.

After apply on personal, restart Pi so session-search reloads dest files.
Interactive `/session:embedder` and `/session:summarizer` write the dest copies;
the next `chezmoi apply` overwrites dest from this source (these are ordinary
files, not `create_`).

## Usage

On personal, after dest exists, Pi auto-detects `digest-hybrid` when the
embedder constructs and `claude-bridge/claude-haiku-4-5` is in the model
registry.

| Surface | What it does |
| --- | --- |
| `session_search` tool | Hybrid search over past sessions |
| `/find-session [query]` | Interactive session picker |
| `/session:sync` | Incremental re-sync of the dest index |
| `/session:backfill` | Digest historical sessions that lack a digest |

Do not copy [config.json](./config.json) or [digest.json](./digest.json) onto
`axon-work-computer` or Termux. Work Pi should stay fts-raw (no homelab
embedder, no claude-bridge digest). Termux does not run the Pi agent surface.

## Validation

From **this directory**, both files must parse and match the homelab values:

```sh
jq -e '.embedder.baseUrl == "https://ollama.internal.cartwmic.com" and .embedder.model == "nomic-embed-text:latest"' config.json
jq -e '.provider == "claude-bridge" and .model == "claude-haiku-4-5"' digest.json
```

Both commands must print `true`. Confirm the dest is managed only on personal:

```sh
chezmoi managed ~/.pi/session-search
```

On personal this lists dest files under `~/.pi/session-search`. On other
profiles the path is unmanaged because `.chezmoiignore` drops it. Dry-run and
apply stay with the parent tree; do not apply from here.
