# Pi extensions

## Overview

This directory is the chezmoi **source** for Pi coding-agent extensions shipped
by this dotfiles tree. It is for people adding or changing those extensions.
Each extension is one subdirectory and deploys to
`~/.pi/agent/extensions/<name>`. This README is shared authoring procedure for
that layout. Chezmoi also deploys it to `~/.pi/agent/extensions/README.md`
(Pi does not auto-load README files).

Edit sources here. Live files under `~/.pi/agent/extensions/` are generated.
Chezmoi apply, secrets, and profile mechanics live in the repo-root
`AGENTS.md` (three levels up from this folder). Do not treat this file as a
second copy of that guide. Clickable links here stay inside this folder;
repo-root files are named by path because they sit outside it.

OpenSpec, `opsx`, and the ADR change workflow are retired; follow the rules
below instead of reviving those processes.

The `termux` profile skips `.pi` entirely, so none of these extensions deploy
there. Remaining machines use `personal` or `axon-work-computer`, plus the
gates in the Profile gates section.

## Setup

Work in the chezmoi source tree. From any cwd, list this directory:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions && ls -1 .
```

You should see one directory per extension plus this README. The Herdr-managed
`herdr-agent-state.ts` at this folder root is not a chezmoi-authored
extension; do not use it as a template.

Chezmoi destination mapping is `./<name>/` → `~/.pi/agent/extensions/<name>`.
Profile gates that omit an extension from a machine live in the repo-root
`.chezmoiignore`, not inside the extension.

After source changes, apply using the procedure in repo-root `AGENTS.md`
(do not apply from this README). Restart Pi so it reloads extensions.

## Usage

### Layout

One directory per extension under this folder. Add a new one as `./<name>/`
with the files Pi loads (typically `index.ts`). Keep tests next to the
extension: `index.test.ts` or `helpers.test.ts`.

```text
dot_pi/agent/extensions/<name>/     →  ~/.pi/agent/extensions/<name>
```

### Never capture `ctx`

Pi passes `ExtensionContext` (`ctx`) into each command handler and event
callback. Do **not** stash `ctx` from `session_start` (or any other hook) in a
long-lived closure.

Hold only the `pi` API object plus serializable state. Every handler must use
the `ctx` argument it is given on that call.

A captured `ctx` is stale after `newSession`, `fork`, `switchSession`,
`reload`, or teardown. Accessing it throws: `This extension ctx is stale after
session replacement or reload.`

```ts
export default function (pi: ExtensionAPI) {
  let enabled = true; // serializable state only
  pi.on("agent_settled", (_event, ctx) => {
    if (enabled && ctx.hasUI) ctx.ui.notify("settled"); // per-call ctx
  });
}
```

Wrong: `let savedCtx; pi.on("session_start", (_e, ctx) => { savedCtx = ctx; });`

### Lifecycle events

Prefer `agent_end` / `agent_settled` when the question is “awaiting the user”
or “evaluate the goal.” `turn_end` is per internal LLM turn (including retries
and continuations). It is the wrong default for notify and for goal
evaluation.

[ntfy](./ntfy/README.md) notifies on `agent_settled`. [goal](./goal/) evaluates
a completed attempt at `agent_end` and treats an error as terminal only at
`agent_settled` after Pi has exhausted retries. Some extensions (for example
[auto-compact](./auto-compact/README.md)) still listen on `turn_end` for
mid-run work; that does not make `turn_end` the notify/goal hook.

### Goal loop

[`goal`](./goal/) is a generic completion loop: worker turn, then a separate
judge model (or optional command judge) decides whether the condition is met.
It is not an OpenSpec/`opsx` runner. Do not couple goal to that retired
workflow.

### `create_` files

Chezmoi `create_` sources write the destination only when it does not already
exist. Examples: [auto-compact/create_config.json](./auto-compact/create_config.json),
[goal/create_config.json](./goal/create_config.json),
[openrouter-gate/create_config.json](./openrouter-gate/create_config.json),
[web-search/create_config.json](./web-search/create_config.json). After the first apply,
interactive edits to that dest file stay machine-local. Do not expect
`chezmoi apply` to reset them.

### Profile gates

Gates live in the repo-root `.chezmoiignore`:

| Path | Who receives it |
| --- | --- |
| [openrouter-gate](./openrouter-gate/README.md) | `personal` only |
| [issue](./issue/README.md) | `axon-work-computer` only |
| `dot_pi/session-search/` (sibling of `agent/`, not this folder) | `personal` only |

Do not deploy personal/homelab-only extensions onto `axon-work-computer`.

### Per-extension docs

READMEs already in this tree:

- [auto-compact](./auto-compact/README.md)
- [hindsight](./hindsight/README.md)
- [issue](./issue/README.md)
- [ntfy](./ntfy/README.md)
- [openrouter-gate](./openrouter-gate/README.md)
- [pi-patch-guard](./pi-patch-guard/README.md)
- [catalog-overlay-nudge](./catalog-overlay-nudge/README.md)
- [codex-fast-luna](./codex-fast-luna/README.md)
- [goal](./goal/README.md)
- [inspect-prompt](./inspect-prompt/README.md)
- [subagent](./subagent/README.md)
- [web-search](./web-search/README.md)

`subagent` is currently a config overlay (`config.json` with
`maxSubagentDepth`); it has no `index.ts` yet.

## Validation

From this directory, run tests of an extension that already has them. Prefer
`node --test` **from that extension directory** so relative imports match
runtime:

```sh
cd ./pi-patch-guard && node --test
```

Other in-tree suites today: `auto-compact/index.test.ts`,
`goal/helpers.test.ts`, `hindsight/index.test.ts`, `inspect-prompt/index.test.ts`,
`issue/index.test.ts`, `ntfy/index.test.ts`, `openrouter-gate/index.test.ts`,
`codex-fast-luna/index.test.ts`, `web-search/config.test.ts`.
`catalog-overlay-nudge` and `subagent` do not have tests yet.

Chezmoi apply and secret handling are not validated here; use repo-root
`AGENTS.md`.
