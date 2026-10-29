# Pi extensions

## Overview

This directory (`dot_pi/private_agent/extensions/`) is the chezmoi **source**
for Pi coding-agent extensions shipped by this dotfiles tree. Each extension
is one subdirectory and deploys to `~/.pi/agent/extensions/<name>`. This README
is shared authoring procedure for that layout. Chezmoi also deploys it to
`~/.pi/agent/extensions/README.md` (Pi does not auto-load README files).

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

## System One Git package

[System One](./system-one/README.md) is included once in personal and
axon-work-computer settings. Its local directory is docs-only, not a loader;
Termux excludes `.pi`. Native macOS delivery targets Pi 0.99.2+ / Node.js
22.19+. Pi owns provider/auth setup and classifier selection independently
of the CLI catalog (CLI Node.js 20+ macOS/Linux support is unchanged).
`/so off` gates only `system_one`; private manual use and direct native
codemode are separate. See the guide for native typed forms, selection
lifecycle, separate accounting and the 30-second deadline / per-operation
`maxRetries:2`. Source reconciliation does not authorize apply or installation.

## Setup

Work in the chezmoi source tree. From any cwd, list this directory:

```sh
cd ~/.local/share/chezmoi/dot_pi/private_agent/extensions && ls -1 .
```

You should see one directory per extension plus this README. The live
`~/.pi/agent/extensions/herdr-agent-state.ts` is written by
`herdr integration install pi` and is not tracked here; do not add it back
or use it as a template.

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
dot_pi/private_agent/extensions/<name>/  →  ~/.pi/agent/extensions/<name>
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

[goal](./goal/) evaluates a completed attempt at `agent_end` and treats an error as terminal only at
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
[openrouter-gate/create_config.json](./openrouter-gate/create_config.json). After the first apply,
interactive edits to that dest file stay machine-local. Do not expect
`chezmoi apply` to reset them.

[web-search/modify_config.json.tmpl](./web-search/modify_config.json.tmpl) instead
manages the personal profile's search provider, Codex model, and reasoning effort
on every apply, preserving other config fields and existing work-profile settings.

### Codex Fast

The personal profile loads the [pi-codex-fast fork](https://github.com/cartwmic/pi-codex-fast)
instead of the retired Luna-only extension.
[create_pi-codex-fast.json](./create_pi-codex-fast.json) seeds
`defaultEnabled: false` with only `openai-codex/gpt-6.1-sol` eligible.

Use `/fast on`, `/fast off`, and `/fast status` for the current session branch.
The choice survives reload and resume in the session history; it does not
change other sessions. New sessions start from the user default.

Use `/fast default on|off|status` to edit or inspect the default for new
sessions. Defaults, model eligibility, and style live in
`~/.pi/agent/extensions/pi-codex-fast.json`; later applies leave them alone.
The old global `enabled` toggle is ignored, so it cannot silently become
a default. Native provider streaming is unchanged, including its existing
advanced-request-option limitations. Status styles render static frames
without retaining a Pi context in animation timers.

Pi does not save a session file until it contains a conversation message.
A pre-chat toggle survives reload in memory, but cannot be resumed after
quitting an empty session. Historical branches without a Fast snapshot
initialize from the current default when first visited.

### Auto session name

The personal profile loads [patlux/pi-auto-session-name](https://github.com/patlux/pi-auto-session-name),
pinned to commit `19a8355` (0.1.1, 2026-09-01, MIT). It replaces the
pane titles that pi-session-search used to set. When a session has no name,
it sends one naming request to the configured model after the first run
settles. The prompt is a bounded excerpt (by default at most 12,000
characters: the earliest six useful user and assistant messages, plus any
compaction summary). A failed or empty attempt is retried when the excerpt
changes or after a 5-minute cooldown; the first success ends automatic
naming. It leaves names set by `/name` or `--name` alone. It writes no index,
cache or other file of its own (the name is stored the normal way, as session
info). Its only timer is a 60 s one-shot (default) that names a first run that
is still active. It does not follow topic changes: `/auto-name` regenerates the
name on demand from the same earliest-messages excerpt.

Known limit: the naming call runs before Pi reports the run as settled, and
its `timeoutMs` covers the response headers, not a stalled stream. A hung
provider can therefore hold off the settled state of an unnamed session.
Shutdown or renaming aborts it.

What the package installs: a git checkout at
`~/.pi/agent/git/github.com/patlux/pi-auto-session-name`. It has no runtime
dependencies and no `install`, `postinstall` or `prepare` script; Pi runs
`npm install --omit=dev --legacy-peer-deps` in the checkout, which installs nothing. Updates do not move
the pin. To change the pin, review the new diff first: the code runs with Pi's
full permissions.

[create_auto-session-name.json](./create_auto-session-name.json) seeds
`~/.pi/agent/extensions/auto-session-name.json` once with
`openai-codex/gpt-6-luna` (the model the digest used); later applies leave it
alone. `ticketPrefix` is off on purpose: the package's ticket pattern is
case-insensitive and would prefix titles with things like `GPT-6`. The title
shows in the footer and the terminal title (`π - <name> - <cwd>`).

### `op` in Pi shells

Not an extension: `dot_pi/private_agent/bin/executable_op` deploys to `~/.pi/agent/bin/op`, which Pi puts first on the
PATH of its bash tool and `!` commands (unless that directory is already on the PATH Pi started with; then it keeps its
place). When a 1Password service-account token is available (`OP_SERVICE_ACCOUNT_TOKEN`,
or `~/.config/agent-harness/op-service-token`), it runs the real `op` with an empty HOME, so a worker's `op` uses the
service account and never hangs on a locked desktop app; otherwise it runs `op` unchanged. Terminals outside Pi do not
have that directory on PATH and are unaffected. Not covered: `op` called by absolute path, Claude Code and Codex
workers. An `!op …` typed inside Pi uses the service account too. Tests: `python3 -m unittest discover -s tests/pi-op-shim -v` (fake op);
`python3 tests/pi-op-shim/proof.py` runs a real Pi with a scripted model (needs `pi` on PATH).

### Profile gates

Gates live in the repo-root `.chezmoiignore`:

| Path | Who receives it |
| --- | --- |
| [system-one](./system-one/README.md) (docs only) | `personal` and `axon-work-computer` |
| [openrouter-gate](./openrouter-gate/README.md) | `personal` only |
| [claude-compat-guard](./claude-compat-guard/README.md) | `personal` only |
| [anthropic-stall-retry](./anthropic-stall-retry/README.md) | `axon-work-computer` only |
| [auto session name](#auto-session-name) (package in settings) | `personal` only |
| [standing-reminder](./standing-reminder/README.md) | `personal` and `axon-work-computer`; Termux skips `.pi` |
| [learnings-monitor](./learnings-monitor/README.md) | `personal` and `axon-work-computer`; Termux skips `.pi` |
| [system-one](./system-one/README.md) (docs; package in settings) | `personal` and `axon-work-computer`; Termux skips `.pi` |
| [winnow-local](./winnow-local/README.md) | `personal` and `axon-work-computer`; Termux skips `.pi` |

Do not deploy personal/homelab-only extensions onto `axon-work-computer`.

### Per-extension docs

READMEs already in this tree:

- [anthropic-stall-retry](./anthropic-stall-retry/README.md)
- [auto-compact](./auto-compact/README.md)
- [claude-compat-guard](./claude-compat-guard/README.md)
- [hindsight](./hindsight/README.md)
- [openrouter-gate](./openrouter-gate/README.md)
- [pi-patch-guard](./pi-patch-guard/README.md)
- [catalog-overlay-nudge](./catalog-overlay-nudge/README.md)
- [goal](./goal/README.md)
- [inspect-prompt](./inspect-prompt/README.md)
- [learnings-monitor](./learnings-monitor/README.md)
- [subagent](./subagent/README.md)
- [passage-review](./passage-review/README.md)
- [web-search](./web-search/README.md)
- [standing-reminder](./standing-reminder/README.md)
- [system-one](./system-one/README.md)
- [winnow-local](./winnow-local/README.md) (local Winnow server: setup and launch)

`subagent` is currently a config overlay (`config.json` with
`maxSubagentDepth`); it has no `index.ts` yet.

## Validation

From this directory, run tests of an extension that already has them. Prefer
`node --test` **from that extension directory** so relative imports match
runtime:

```sh
cd ./pi-patch-guard && node --test
```

Other in-tree suites today: `anthropic-stall-retry/index.test.ts`, `auto-compact/index.test.ts`,
`goal/helpers.test.ts`, `hindsight/index.test.ts`, `inspect-prompt/index.test.ts`,
`openrouter-gate/index.test.ts`,
`web-search/config.test.ts`, `web-search/codex.test.ts`, and
`learnings-monitor/` (`node --test`).
`catalog-overlay-nudge` and `subagent` do not have tests yet. `passage-review`
and `standing-reminder` have `index.test.ts`. The standing
reminder also has an isolated real-Pi journey and a separate capped live cache
proof; see its [README](./standing-reminder/README.md).
