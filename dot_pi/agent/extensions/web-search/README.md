# web-search — pi extension

Anthropic-backed `web_search` and `web_fetch` tools for Pi. Claude runs the
lookups server-side; this extension registers the tools and formats the
results. It is not a local crawler and does not take a slash command.

Authoring layout for this folder lives in the parent `extensions/README.md`
(one directory up; not linked here because it sits outside this folder).
Implementation: [index.ts](./index.ts).

## Overview

Two tools share one Anthropic auth context:

| Tool | Anthropic type | Use when |
| --- | --- | --- |
| `web_search` | `web_search_20250305` | You need an **answer**. Claude searches (server-side `max_uses`, default 5, cap 20) and returns a synthesized reply with cited sources plus the queries it issued. |
| `web_fetch` | `web_fetch_20250910` | You already have a **URL** (often a `web_search` source) and want the extracted page, not a summary. One fetch per call. |

Adapted from [`@oh-my-pi/anthropic-websearch`](https://github.com/can1357/oh-my-pi) (MIT).

OAuth from `claude login` / `pi login` uses the Claude Code token path
(subscription usage). `ANTHROPIC_SEARCH_API_KEY` / `ANTHROPIC_API_KEY` use the
API-key path. Do not put tokens in this file or in chezmoi source.

## Setup

This directory is the chezmoi **source**. It deploys to
`~/.pi/agent/extensions/web-search`. Confirm the source is present:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/web-search && ls -1
```

You should see [index.ts](./index.ts) and this README. After apply, restart Pi
so it reloads extensions. Apply itself is the parent-tree procedure in
`dot_pi/agent/extensions/README.md`; do not apply from here. The `termux`
profile skips `.pi`, so this extension does not deploy there.

Auth is first-match-wins. Tokens are re-resolved on every tool call (60s cache)
so a mid-session keychain / `auth.json` refresh does not require reloading Pi.

| Order | Source | Notes |
| --- | --- | --- |
| 1 | `ANTHROPIC_SEARCH_API_KEY` | Optional `ANTHROPIC_SEARCH_BASE_URL` (default `https://api.anthropic.com`). |
| 2 | macOS Keychain `Claude Code-credentials` | From `claude login`. Darwin only. Ignored if `expiresAt` is set and within 5 minutes of expiry. |
| 3 | `~/.pi/agent/auth.json` | Pi-managed Anthropic OAuth (`type: oauth`, non-empty `access`, `expires` more than 5 minutes away). Populate with `pi login`. |
| 4 | `ANTHROPIC_API_KEY` | Last-resort fallback. Optional `ANTHROPIC_BASE_URL`. |

Recommended setup: `claude login` on macOS, or `pi login`, or export
`ANTHROPIC_SEARCH_API_KEY`. Never print or commit credential values.

If none of the four sources resolve, the tools still register but every call
returns an unconfigured error naming those setup paths.

Optional: `ANTHROPIC_SEARCH_MODEL` (default `claude-opus-5`).

## Usage

### Search vs fetch

- **Search** for open questions, current facts, or “what is the answer, with
  sources?” Do not search when you already have the URL you need.
- **Fetch** for a specific `http(s)` URL you want to read in full. Use it after
  search returns a source worth opening. Do not fetch to answer a vague query.

### `web_search`

| Parameter | Default | Range / notes |
| --- | --- | --- |
| `query` | required | Question or search string. |
| `system_prompt` | unset | Optional style/focus for the synthesized answer. |
| `max_tokens` | `4096` | 256–16384. |
| `max_searches` | `5` | 1–20. Anthropic enforces this server-side (`max_uses`). |

The result is natural-language text plus a searches list and numbered sources
(title, optional page age, URL). Ctrl+O expands the TUI preview.

### `web_fetch`

| Parameter | Default | Range / notes |
| --- | --- | --- |
| `url` | required | Absolute `http` or `https` URL. |
| `max_tokens` | `8192` | 1024–32768 (API response cap). |
| `max_bytes` | `200000` | 1024–1000000. Extracted page is **head-truncated** past this. |

The result is markdown with title, final URL if redirected, retrieved time, and
the page body. Claude is prompted to return content, not commentary.

### Private-gateway alias

Both `web_search` and `web_fetch` are registered. When the active model
provider is `private-anthropic`, the search tool name in the active set is
`claude_web_search` instead of `web_search` (that gateway reserves
`web_search`). Session start and model changes keep the alias in sync. Callers
still want search-vs-fetch behavior; only the search tool **name** changes.

## Validation

There is no in-tree test file yet (same as noted in parent
`extensions/README.md`). Check that the source exists and Node can
parse it. Do **not** make a live Anthropic or web call:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/web-search && test -f index.ts && node --check index.ts
```

Exit 0 means the file is present and parsed. That is not proof of auth, search
quality, or fetch extraction.
