# System One in Pi

## Purpose

This directory documents the [System One Git package](https://github.com/cartwmic/system-one-tools) enabled by the `personal` Pi settings template. Pi loads its `system_one` tool and `/so` commands from that repository. This chezmoi directory contains no loader or copy of the package code. The work and Termux profiles skip these files. [AGENTS.md](AGENTS.md) covers maintenance here; the [repo-root guide](https://github.com/cartwmic/dotfiles/blob/main/AGENTS.md) owns chezmoi apply and secret handling.

## Setup

From the dotfiles source root, inspect the three targeted destinations. Run the
dry-run first:

```sh
chezmoi --source "$PWD" apply --dry-run --verbose ~/.pi/agent/settings.json ~/.pi/agent/extensions/system-one/README.md ~/.pi/agent/extensions/system-one/AGENTS.md
```

Follow the [scoped maintenance guide](AGENTS.md) and the repo-root guide
above for drift inspection and approval. Once that check is complete, apply
the three destinations:

```sh
chezmoi --source "$PWD" apply ~/.pi/agent/settings.json ~/.pi/agent/extensions/system-one/README.md ~/.pi/agent/extensions/system-one/AGENTS.md
pi list
```

Pi clones the Git package and builds its shared connection runtime when it is
installed. It needs Node.js 22.19+; the Pi extension was tested with Pi 0.87.1.
The packages are unpublished to npm, and the source is `UNLICENSED`. Restart
Pi, then run `/so status` to check that the extension loaded. The Git URL is
unpinned; `pi update https://github.com/cartwmic/system-one-tools` can move it to a later commit.
[AGENTS.md](AGENTS.md) covers that maintenance boundary.

This checkout supplies no decision service or model. A generic
chat-completions endpoint cannot answer typed System One requests. For a
compatible OpenRouter Decisions route, use `/so settings` to save a connection
in `${XDG_CONFIG_HOME:-$HOME/.config}/system-one/connections.json`: select the
OpenRouter adapter, base URL `https://openrouter.ai/api/v1`, model
`~typesafe/jev-latest`, and credential variable name `OPENROUTER_API_KEY`.
For agent calls, select it as the catalog default or run
`/so use <connection-id>`; until then, `/so status` may report `not selected`.
`/so ask` prompts for a connection and optional model for that call, so a
manual request can use a saved connection without a default. The catalog
stores the variable name only. Supply the value to the Pi process at runtime. On `personal`,
`/openrouter on` can inject the stashed key when the
[OpenRouter gate](https://github.com/cartwmic/dotfiles/blob/main/dot_pi/private_agent/extensions/openrouter-gate/README.md) has a stashed key and nonempty
allowlist; that command also enables allowed OpenRouter models. A separately
supplied process environment variable works for a one-off Pi session. The
[package guide](https://github.com/cartwmic/system-one-tools#usage) covers
native System One endpoints and the connection format. Pi's tool and `/so ask`
use the SDK's 10-second evaluation deadline with no timeout override; choose
a responsive service or use the CLI's `--timeout-ms` for slower endpoints.
The published live calls establish the OpenRouter Decisions route with the
Jev latest alias; direct TypeSafe authentication, other models, and local-model
calibration remain unverified.

## Usage

`/so ask` submits a manual Choice, Boolean, or Score request while agent
access is off. Its editor and result are terminal-only; neither request nor
result enters agent context. `/so on` enables the `system_one` tool for the
current session; `/so off` disables it. Use the tool for atomic judgments
backed by relevant evidence. Factual lookup, exact calculations, open-ended
generation, and substantial multi-step reasoning need other tools. The agent
tool submits only the state and questions given to it; it does not attach a
transcript or choose a connection. Results and probabilities are advisory.
These commands and the tool are the owner-facing surface; the package's
in-process session API is internal. See the
[package's Pi guide](https://github.com/cartwmic/system-one-tools/tree/main/packages/pi-system-one)
for command details and request shape.

## Validation

After targeted apply and a Pi restart, check the configured package and extension command:

```sh
pi list
```

`pi list` should show `https://github.com/cartwmic/system-one-tools`. In Pi, `/so status` should report the loaded extension and either a selected connection or `not selected` until one is chosen; it does not make a provider call. A live `/so ask` verifies the connection chosen for that call and may cost money. The shipped System One repository has scripted CLI, Pi TUI, cross-caller, and package-consumer checks. This dotfiles directory does not run those tests or publish that package.

## Troubleshooting

- `/so` is unknown: check `pi list`, install or update the Git package, then restart Pi. The docs-only directory here cannot register a command.
- Missing credential (CLI code `MISSING_CREDENTIAL`): Pi reports the missing environment variable named by `apiKeyEnv`. Check the OpenRouter gate's stash and allowlist before `/openrouter on`, or provide the variable when starting Pi. Keep its value out of settings and transcripts.
- Missing or invalid catalog/selection (CLI codes `CONNECTION_CATALOG_ERROR` and `CONNECTION_SELECTION_ERROR`): open `/so settings` and check the saved catalog and default. The extension does not choose another connection on failure.
- Evaluation failures (CLI codes `TIMEOUT`, `NETWORK_ERROR`, `PROVIDER_REJECTED`, and `MALFORMED_RESPONSE`): Pi shows error messages; see the [package troubleshooting guide](https://github.com/cartwmic/system-one-tools#troubleshooting) for route, latency, model, and response checks.
