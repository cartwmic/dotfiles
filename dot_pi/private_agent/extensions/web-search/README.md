# web-search — pi extension

Configurable `web_search` plus Anthropic-only `web_fetch` for Pi. Search can
run through Anthropic Messages (`web_search_20250305`) or Codex Responses
(`tools: [{ type: "web_search" }]`). `web_fetch` is listed only when Anthropic
is selected; Codex omits it because it has no named page-fetch tool. This is
not a local crawler.

Authoring layout for this folder lives in the parent `extensions/README.md`
(one directory up; not linked here because it sits outside this folder).
Implementation: [index.ts](./index.ts), [config.ts](./config.ts),
[codex.ts](./codex.ts). Tests: [config.test.ts](./config.test.ts).

## Overview

| Tool | Backend | Use when |
| --- | --- | --- |
| `web_search` | Anthropic (default) or Codex Responses | You need an **answer** with cited sources. |
| `web_fetch` | Anthropic only; omitted for Codex | You already have a **URL** and want the extracted page, not a summary. |

Adapted from [`@oh-my-pi/anthropic-websearch`](https://github.com/can1357/oh-my-pi) (MIT). Codex
Responses path follows the ChatGPT Codex `web_search` tool used by community
extensions such as Leechael `pi-codex-search`.

The session model (`PI_PROVIDER`) is independent of the search backend.
`private-anthropic` only aliases the search tool name to `claude_web_search`.

Do not put tokens in this file or in chezmoi source.

## Setup

This directory is the chezmoi **source**. It deploys to
`~/.pi/agent/extensions/web-search`. Confirm the source is present:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/web-search && ls -1
```

You should see [index.ts](./index.ts), [config.ts](./config.ts),
[codex.ts](./codex.ts), [create_config.json](./create_config.json), and this
README. After apply, restart Pi so it reloads extensions. Apply itself is the
parent-tree procedure in `dot_pi/agent/extensions/README.md`; do not apply
from here. The `termux` profile skips `.pi`, so this extension does not
deploy there.

`[create_config.json](./create_config.json)` is a chezmoi `create_` source.
Chezmoi writes the destination `config.json` only when that dest file does
not already exist. After the first apply, `/web-search` edits to
`~/.pi/agent/extensions/web-search/config.json` stay machine-local.

Default create contents:

```json
{
  "searchProvider": "anthropic",
  "codexModel": "gpt-5.6-luna"
}
```

Optional `anthropicModel` is also accepted in that file. Precedence for every
setting: **env var > `config.json` > built-in default**. Empty env values are
ignored.

| Setting | Env | Config key | Default |
| --- | --- | --- | --- |
| Search backend | `WEB_SEARCH_PROVIDER` | `searchProvider` | `anthropic` |
| Anthropic search/fetch model | `ANTHROPIC_SEARCH_MODEL` | `anthropicModel` | `claude-opus-5` |
| Codex search model | `CODEX_SEARCH_MODEL` | `codexModel` | `gpt-5.6-luna` |

`WEB_SEARCH_PROVIDER` accepts `anthropic` or `codex`. Unknown values fall
through to config.

### Anthropic auth (search when provider is Anthropic, and all fetch)

First-match-wins. Tokens are re-resolved on every tool call (60s cache) so a
mid-session keychain / `auth.json` refresh does not require reloading Pi.

| Order | Source | Notes |
| --- | --- | --- |
| 1 | `ANTHROPIC_SEARCH_API_KEY` | Optional `ANTHROPIC_SEARCH_BASE_URL` (default `https://api.anthropic.com`). |
| 2 | macOS Keychain `Claude Code-credentials` | From `claude login`. Darwin only. Ignored if `expiresAt` is set and within 5 minutes of expiry. |
| 3 | `~/.pi/agent/auth.json` | Pi-managed Anthropic OAuth (`type: oauth`, non-empty `access`, `expires` more than 5 minutes away). Populate with `pi login`. |
| 4 | `ANTHROPIC_API_KEY` | Last-resort fallback. Optional `ANTHROPIC_BASE_URL`. |

OAuth from `claude login` / `pi login` uses the Claude Code token path
(subscription usage). API keys use the API-key path.

### Codex auth (search when provider is Codex)

`openai-codex` OAuth in `~/.pi/agent/auth.json` (`/login openai-codex`). The
token must include a ChatGPT account id (stored `accountId` or JWT claim).
Expired tokens are skipped (5-minute skew); re-login rather than putting a
refresh token in this tree. Endpoint:
`POST https://chatgpt.com/backend-api/codex/responses`.

Recommended setup: `claude login` or `pi login` for Anthropic fetch/search,
plus `/login openai-codex` if you will switch search to Codex. Never print or
commit credential values.

If Anthropic auth is missing, Anthropic `web_search` and its listed
`web_fetch` fail at call time with an unconfigured error. Codex search still
works when `openai-codex` auth is present and does not list `web_fetch`.

## Usage

### Commands

| Command | Effect |
| --- | --- |
| `/web-search` or `/web-search status` | Show provider, models, auth sources, and config path. |
| `/web-search config` | Pick `anthropic` or `codex`; Codex omits `web_fetch`. |
| `/web-search provider anthropic\|codex` | Set the search backend without a picker. |
| `/web-search reload` | Re-read `config.json` without restarting Pi. |

If `WEB_SEARCH_PROVIDER` is set, it overrides the saved provider until unset
(and Pi is restarted if the process inherited the old env).

### Search vs fetch

- **Search** for open questions, current facts, or “what is the answer, with
  sources?” Do not search when you already have the URL you need.
- **Fetch** for a specific `http(s)` URL you want to read in full. It is listed
  only for the Anthropic search provider. Codex has no fetch twin.

### `web_search`

| Parameter | Default | Range / notes |
| --- | --- | --- |
| `query` | required | Question or search string. |
| `system_prompt` | unset | Optional style/focus for the synthesized answer. |
| `max_tokens` | `4096` | 256–16384. Anthropic only. |
| `max_searches` | `5` | 1–20. Anthropic server-side `max_uses`. Ignored on Codex. |

The result is natural-language text plus a searches list and numbered sources
(title, optional page age, URL). Ctrl+O expands the TUI preview.

### `web_fetch`

This tool is active only while Anthropic is the configured search provider.
Switching to Codex removes it from the tool listing; switching back restores it.

| Parameter | Default | Range / notes |
| --- | --- | --- |
| `url` | required | Absolute `http` or `https` URL. |
| `max_tokens` | `8192` | 1024–32768 (API response cap). |
| `max_bytes` | `200000` | 1024–1000000. Extracted page is **head-truncated** past this. |

The result is markdown with title, final URL if redirected, retrieved time, and
the page body. Claude is prompted to return content, not commentary.

### Private-gateway alias

Both search aliases and `web_fetch` are registered, but the active set omits
`web_fetch` while Codex is configured. When the active model provider is
`private-anthropic`, the search tool name in the active set is
`claude_web_search` instead of `web_search` (that gateway reserves
`web_search`). Session start and model changes keep the alias in sync. Callers
still want search-vs-fetch behavior; only the search tool **name** changes.

## Validation

From this directory:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/web-search && node --test
```

That suite covers config normalize/load/save, active-tool listing, command
parsing, Codex URL shaping, and result formatting. It does **not** make a live Anthropic, Codex,
or web call. Apply and a Pi restart are still required before a session can
use `/web-search provider codex`.
