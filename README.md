# Dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/) and [mise](https://mise.jdx.dev/).

## Overview

This repository is the **chezmoi source** for one person's machines (macOS,
Ubuntu/WSL, and Termux). Chezmoi maps these files onto `$HOME`; mise installs
and versions the tools. Profiles (`personal`, `axon-work-computer`, `termux`)
select what gets deployed.

Two baseline agent-instruction files exist on purpose and must stay different:

- [AGENTS.md](./AGENTS.md) — repo-only guide for work **in this tree**. Listed
  in `.chezmoiignore`; never deployed. Chezmoi matches ignore rules against
  **destination** names, so this file cannot coexist with a source that deploys
  to `~/AGENTS.md` (same target; `inconsistent state`).
- [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl) — deploys to
  `~/.pi/agent/AGENTS.md`. Pi loads that agent-directory file first on every
  session, then walks ancestors from the cwd. Source is `literal_AGENTS.md.tmpl` so
  a session whose cwd is under `dot_pi/private_agent/` does not also load the source
  (same text, two paths). Do not also create `~/AGENTS.md`.

Humans start at [Quick Start](#quick-start). Agents working in this repo start
at [AGENTS.md](./AGENTS.md). Phone setup is in [termux/README.md](./termux/README.md).
Harness internals are in [dot_local/share/agent-harness/README.md](./dot_local/share/agent-harness/README.md).
Zellij plugin/fork notes are in [dot_config/zellij/README.md](./dot_config/zellij/README.md).
Pi-global agent instructions are in [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl).

## Quick Start

This unmodified setup is for the owner's fresh `personal` machine. It needs
access to the owner's 1Password references and internal services (including
SSH provisioning, Hindsight, and ntfy). On another machine, adapt or disable
those integrations before applying. On macOS, [install Homebrew](https://brew.sh/)
first: the mise installer uses it. On WSL, the chezmoi pre-hook needs `op`
or the Windows `op.exe` on PATH; install one before init if missing. On
Ubuntu/WSL, install zsh and set it as the default shell:

```sh
sudo apt-get update && sudo apt-get install -y zsh
sudo chsh "$USER" -s /usr/bin/zsh
```

For a fresh personal installation, create the profile config once and clone
the source **without applying**. An existing `~/.config/chezmoi/chezmoi.yaml`
needs its own review; the command below refuses to replace it.

```sh
set -eu
mkdir -p ~/.config/chezmoi
[ ! -e ~/.config/chezmoi/chezmoi.yaml ] || { printf '%s\n' 'Existing chezmoi profile; inspect it first' >&2; exit 1; }
curl -fsSL https://raw.githubusercontent.com/cartwmic/dotfiles/main/example.chezmoi.yaml -o ~/.config/chezmoi/chezmoi.yaml
installer=$(curl -fsLS https://get.chezmoi.io)
sh -c "$installer" -- -b "$HOME/.local/bin" init cartwmic
```

Before the **first** apply, inspect the cloned [removal list](./.chezmoiremove),
especially `~/termux`, and ask the owner if any persistent directory contains
unrelated data. Preview the effects:

```sh
"$HOME/.local/bin/chezmoi" apply --dry-run --verbose
```

Apply only when that output matches intent. Bootstrap runs the configured
profile tasks; check their results before assuming a tool installed. On a fresh
macOS host, the first RustDesk configuration may stop until RustDesk has been
launched once to create its local identity; launch and quit it, then rerun
`chezmoi apply`. If personal SSH later reports `Permission denied (publickey)`,
authenticate 1Password or run `~/.local/user_scripts/refresh_op_service_account_token.sh`,
then reapply to provision the key. Other [manual steps](#manual-steps) remain:

```sh
"$HOME/.local/bin/chezmoi" apply && exec zsh
```

### Termux (Android)

Termux is a first-class profile (`profile: "termux"`) — thin SSH jump host,
`.termux` UI config, and ntfy jump handlers. It does **not** install the full
desktop/agent stack. See [Termux setup](./termux/README.md). On a fresh phone,
create the profile once and clone before applying:

```bash
set -eu
pkg install -y chezmoi git openssh coreutils termux-api python vim
mkdir -p ~/.config/chezmoi
[ ! -e ~/.config/chezmoi/chezmoi.yaml ] || { printf '%s\n' 'Existing chezmoi profile; inspect it first' >&2; exit 1; }
printf 'data:\n  profile: "termux"\n' > ~/.config/chezmoi/chezmoi.yaml
chezmoi init https://github.com/cartwmic/dotfiles.git
```

Inspect [`.chezmoiremove`](./.chezmoiremove) in the cloned source before the
first apply, check ownership of persistent paths, then preview and apply only
if the output matches intent:

```bash
chezmoi apply --dry-run --verbose
```

```bash
chezmoi apply
```

## What's Included

**Shell & Terminal:**

- Zsh with [antidote](https://getantidote.github.io/) plugin manager
- Kitty terminal with Zellij multiplexer
- Starship prompt, fzf fuzzy finder, zoxide smart cd

**Development Tools:**

- Editor: Neovim (LazyVim)
- Git: lazygit TUI
- Languages: Node.js, Python (managed by mise); Rust (managed by rustup)
- Version Management: mise (replaces nvm), rustup (Rust), SDKMAN, gvm

**DevOps/Cloud:**

- Kubernetes: kubectl, k9s, helm, kustomize, kubeseal
- Containers: Docker Desktop on macOS; Docker Engine, Compose, and Buildx on Ubuntu
- Infrastructure: terraform
- Utilities: ripgrep, jq, yq, task, dagu

**AI Tools:**

- Pi coding agent, claude, claude-code-acp, vectorcode, mistral-vibe, mermaid-cli
- Herdr **0.9.1 / protocol 22** with a desktop-only overview plugin on `personal` and `axon-work-computer`
- Portable `session-recap` and `passage-review` workflows; Termux stays an SSH client and has no Herdr plugin

**Remote access:**

- RustDesk client on macOS and native Ubuntu/Debian
- Self-hosted rendezvous and relay configuration
- Shared unattended-access password loaded from `op://developer/RustDesk/password`

## Docker Provisioning

On `personal` profile hosts, `mise run bootstrap` installs Docker Desktop on macOS or Docker Engine from Docker's official apt repository on native Ubuntu. Work profiles, Termux, WSL, and unsupported Linux distributions are skipped. On macOS, provisioning repairs inaccessible legacy `/usr/local/bin` permissions when needed and verifies the Docker and Compose CLIs after installation. Docker Desktop requires one interactive launch to accept its license and finish setup.

On Ubuntu, provisioning refuses to remove conflicting distribution packages automatically. After those are removed explicitly, it installs Docker CE, containerd, Compose, and Buildx, then adds the current user to the `docker` group. Group membership takes effect after logout/login and grants root-equivalent access through the Docker daemon. Docker-published ports can bypass `ufw`; enforce host policy through Docker's `DOCKER-USER` chain where needed.

## RustDesk Provisioning

On `personal` profile hosts, `mise run bootstrap` installs RustDesk when missing. Other chezmoi profiles skip RustDesk. A chezmoi onchange script then applies portable settings from `.chezmoidata.toml`: rendezvous server, relay server, public server key, password approval mode, permanent-password verification, and service-enabled state. It removes RustDesk's `stop-service` option. Device identity, trusted-device data, proxy credentials, local IP state, UI state, and hardware-codec state remain machine-local.

On macOS, the same helper installs pinned RustDesk 1.4.9 launchd definitions that write daemon logs under `/Library/Logs/RustDesk`: a root LaunchDaemon for the machine service and a LoginWindow/Aqua LaunchAgent for screen capture and input. Do not put those logs under `/tmp`. Root service identity is seeded once from existing user identity, never from chezmoi source. After password rotation, only encrypted password storage and its salt are synchronized between Aqua and LoginWindow identity profiles. This lets RustDesk start at macOS login window after FileVault has been unlocked; nothing can start before FileVault unlock. A service first installed while machine is already at login window becomes available after next reboot. Fresh machines must first log in and launch RustDesk once to initialize identity.

The permanent password lives only in 1Password. Rotate it there, then apply it again with:

```bash
~/.local/user_scripts/configure_rustdesk.sh
```

The helper updates these platform paths:

- macOS user: `~/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml`
- macOS service: `/var/root/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml`
- Linux user: `~/.config/rustdesk/RustDesk2.toml`
- Linux service: `/root/.config/rustdesk/RustDesk2.toml`

On macOS, portable-setting changes require RustDesk to be fully stopped. If LoginWindow server is active, log in graphically before changing those settings; password-only reapplication may run while RustDesk is open. Helper installs and enables `/Library/LaunchDaemons/com.carriez.RustDesk_service.plist` and `/Library/LaunchAgents/com.carriez.RustDesk_server.plist` using `sudo`. First installation from an existing LoginWindow session defers password verification until reboot starts the new agent. On Linux, configuration briefly restarts `rustdesk.service`. Do not run helper through the RustDesk session being reconfigured.

Shared passwords increase blast radius: compromise of one machine or this 1Password item affects every managed RustDesk host.

## Harness Config Adapters

Canonical harness-agnostic configuration lives under:

- `dot_local/share/agent-harness/canonical/skills/`
- `dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl`

Edit these chezmoi source paths. Chezmoi deploys them under
`~/.local/share/agent-harness/`; harness-specific adapters then project them
into supported harnesses.

Current supported harnesses:

- `claude`
- `codex`
- `pi`

Current supported configuration domains:

- `skills`
- `mcp`

[Harness adapter maintenance](./dot_local/share/agent-harness/README.md)
covers applying skills and MCP configuration, including the interactive skill
sync and each harness's projection.

Notes:

- Harness-specific MCP secrets can be mapped in adapter metadata under `~/.local/share/agent-harness/adapters/<harness>/mcp-secrets.json`.
- Secret-backed adapter metadata is resolved through the 1Password CLI via `op read`.
- Harness instruction files are hand-maintained and split: repo [AGENTS.md](./AGENTS.md) stays in chezmoi source and is ignored on deployment; Pi-global [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl) deploys to `~/.pi/agent/AGENTS.md`. Claude still uses `~/.claude/CLAUDE.md`; Codex still uses `~/.codex/AGENTS.md`.
- `furi` is installed by the `mise` bootstrap task, and bootstrap registers and starts `ashwwwin/automation-mcp` so the canonical `furi` MCP entry works for both Claude and Codex after apply.
- On macOS, `automation-mcp` also needs Accessibility and Screen Recording permissions in System Settings > Privacy & Security before its tools can fully control the machine.

## System One in Pi

The `personal` profile lists the unpinned
[`system-one-tools` Git package](https://github.com/cartwmic/system-one-tools)
for Pi. It loads one `system_one` tool and `/so` commands for evidence-backed
Choice, Boolean, and Score judgments. This checkout supplies no decision
service or model; generic chat-completions endpoints cannot serve its typed
requests. The package's in-process session API is internal. The Git checkout
can move to a later commit on `pi update https://github.com/cartwmic/system-one-tools`;
results and probabilities are advisory, and live calls may cost money. [Setup, use, and troubleshooting](./dot_pi/private_agent/extensions/system-one/README.md)
live in a docs-only chezmoi directory alongside its scoped
[maintenance instructions](./dot_pi/private_agent/extensions/system-one/AGENTS.md).
The work and Termux profiles receive neither the package entry nor these docs.

## Herdr overview and phone route

The personal and work desktop profiles pin Herdr **0.9.1**, whose client and
server use protocol 22, and link the source-managed overview plugin from
`dot_local/share/herdr-overview/`. The Pi publication adapter is
`dot_pi/private_agent/extensions/herdr-overview/`; it publishes the current
real-user prompt separately from a recap generated after a response settles.
The overview is a passive display of native Herdr pane state, those supplied
prompts, and published recaps. It does not parse transcripts or produce
summaries. Panes and tabs can be auto-named from available metadata and
eligible published Pi-session recaps; manually published pane-source recaps
appear in pane detail but do not drive automatic names. After publishing one,
run `herdr plugin action invoke overview.reconcile --plugin overview` while its
source pane is live; the overview then follows that terminal if `pane.move`
rekeys it, without changing the recap's source attribution. Workspaces are not
auto-named, and manual pane/tab labels remain until explicitly returned to
automatic naming. Reconciliation rechecks each target label immediately before
an automatic rename, but Herdr 0.9.1 has no atomic conditional rename, so a
manual edit in the final snapshot-to-write interval can still race.

The overview uses Herdr's active configured theme. At the configured
`[ui].mobile_width_threshold` (64 by default), it presents a summary-first
Board; wider terminals show the all-pane Mosaic. Both navigate the same one
Herdr session. `j`/`k` moves through workspaces or panes, `[`/`]` selects tabs,
`Enter` opens the next level, `Esc` returns, and `f` focuses the selected native
pane. Pane detail keeps recent output, the current Pi prompt, live agent state,
and the latest published recap distinct. Each overview-pane entry reads recent
native output before its first frame, so output produced while the view was
closed appears without waiting for another output event. A missing or failed
recap does not hide live pane information. See
[the Herdr plugin guide](./dot_local/share/herdr-overview/README.md).

The `install-herdr-overview` mise task (also part of desktop bootstrap)
verifies Herdr 0.9.1 and links/enables the source manifest. Linking does **not**
run its server-start hook, start a server, or restart the owner's main Herdr
server. Applying dotfiles never restarts that process. A compatible server
start/restart is owner-controlled; until then, the already-running server has
not loaded newly linked plugin code. If the plugin is already loaded, the
explicit `herdr plugin action invoke overview.reconcile --plugin overview`
action reconciles its pane/model without restarting the server.

On Android, Termux remains the phone-owned `termux` chezmoi profile and an SSH
client. It does not install the native Herdr plugin. From the phone, run
`ssh macbook`, then `herdr` in the desktop shell to attach to that same session.
The actual phone PTY width selects Board or Mosaic; shrinking a local
terminal is not phone proof. See [Termux phone setup](./termux/README.md) for
the route and acceptance-proof status.

## Portable recaps

`session-recap` works independently of Pi and Herdr. It accepts supplied stdin
for one input or a related group, runs the configured argv directly, rejects
blank/nonzero output, and stores dated results under
`${XDG_DATA_HOME:-$HOME/.local/share}/session-recap/records/YYYY-MM-DD/`:

```sh
printf '%s\n' 'Parser is fixed; migration is the next step.' | session-recap create --kind single
printf '%s\n' '{"members":[{"label":"api","text":"API work is complete."},{"text":"Tests remain."}]}' | \
  session-recap create --kind group --label "Release work"
```

The personal and work desktop configs default to `claude -p`; both editable
prompt templates and the host-local `~/.config/session-recap/config.local.toml`
argv override are documented in
[`dot_local/share/session-recap/README.md`](./dot_local/share/session-recap/README.md).
Pi's adapter prepares then publishes settled recaps. Successful Pi publications
start/restart a 30-second workspace quiet period; when it expires, the group uses
latest published recaps for panes currently in that native workspace, including
manual pane-source recaps for non-Pi panes. A successful workspace group can
trigger a Herdr-session group from workspaces still live in the native snapshot.
Failed recaps do not replace the last good record or reset that interval. Dated
history remains outside Herdr.

## Passage review

`passage-review` freezes a selected file or supplied snapshot, stores multiple
passage comments separately, and can reopen them later. Export only selected
pending note IDs as quoted, attributed feedback; export neither edits the
source nor changes note state or sends text to an agent:

```sh
passage-review new --file notes.md
passage-review open REVIEW_ID
passage-review export REVIEW_ID --note NOTE_ID
```

Its local library works with Pi and Herdr stopped and stays on the viewing
machine. On Termux, the phone's own profile installs the CLI and local library;
phone-to-desktop SSH output can be reviewed in the phone UI when direct remote
selection capture is unavailable. See
[`dot_local/share/passage-review/README.md`](./dot_local/share/passage-review/README.md).

## Tool Management with mise

mise handles Node.js and Python version switching; rustup selects Rust toolchains:

```bash
# Install multiple Node versions
mise install node@20 node@18

# Switch versions globally or per-project
mise use -g node@20              # Global default
mise use node@18                 # Current project

# Automatic switching via .nvmrc
cd project/
echo "18" > .nvmrc
cd .                             # Auto-switches to Node 18
```

mise reads `.nvmrc`, `.node-version`, and `mise.toml` files automatically.

**Common commands:**

- `mise ls` - List installed tools
- `mise upgrade` - Update all tools
- `mise install` - Install missing tools
- `mise doctor` - Check setup

## Structure

```
dot_config/
  ├── mise/config.toml           # Tool versions & installation
  ├── nvim/                      # Neovim configuration
  ├── kitty/                     # Kitty terminal
  ├── lazygit/                   # Lazygit TUI
  └── zellij/                    # Zellij multiplexer (see dot_config/zellij/README.md for plugin/fork notes)
run_once_after_00_install_mise.sh          # Installs mise first in post-apply phase
run_onchange_after_10_mise_bootstrap.sh.tmpl # Installs tools after mise is available
private_dot_zshrc                # Zsh configuration
dot_zsh_plugins.txt              # Antidote plugin list
```

## Platform Support

- **macOS**: Homebrew + mise
- **Ubuntu/WSL**: apt + mise

`chezmoi apply` runs the configured profile tasks. Inspect their results;
[manual steps](#manual-steps) and host-specific limits still apply.

## Usage

Edit **source** in this repository (or via `chezmoi edit` on a destination
path). Apply to materialize `$HOME`. Onchange scripts re-run when their
inputs change (mise bootstrap, harness apply, Pi patches, RustDesk, and so on).
In a worktree, pass its path with `--source`; otherwise chezmoi uses the base
checkout. Inspect the dry-run and live destination before an approved apply.

```bash
REPO="$(git rev-parse --show-toplevel)"
chezmoi --source "$REPO" edit ~/.zshrc
chezmoi --source "$REPO" edit ~/.config/mise/config.toml
chezmoi --source "$REPO" apply --dry-run --verbose ~/.zshrc
# After approval and inspection:
chezmoi --source "$REPO" apply ~/.zshrc
```

For template and drift traps, use the repo [AGENTS.md](./AGENTS.md) before
changing the source or taking one side of a live conflict.

## Docs map

This README covers installation and what each profile contains. Agents editing
this source use [AGENTS.md](./AGENTS.md) for repository procedure. The
[Pi-global source](./dot_pi/private_agent/literal_AGENTS.md.tmpl) deploys to
`~/.pi/agent/AGENTS.md`; the [System One scoped guide](./dot_pi/private_agent/extensions/system-one/AGENTS.md)
applies only inside its docs directory. Shared instruction fragments and
harness adapter procedure are in the [agent-harness guide](./dot_local/share/agent-harness/README.md).

Other subtree guides: [Termux](./termux/README.md),
[Zellij](./dot_config/zellij/README.md), [Pi extensions](./dot_pi/private_agent/extensions/README.md),
[Pi patches](./dot_local/share/pi-patches/README.md),
[Herdr overview](./dot_local/share/herdr-overview/README.md),
[session-recap](./dot_local/share/session-recap/README.md),
[passage-review](./dot_local/share/passage-review/README.md),
[Neovim](./dot_config/nvim/README.md), and
[session-search](./dot_pi/session-search/README.md).

## Validation

After editing source, confirm mapping and that apply would not surprise you:

```bash
REPO="$(git rev-parse --show-toplevel)"
chezmoi --source "$REPO" doctor
chezmoi --source "$REPO" verify
chezmoi --source "$REPO" apply --dry-run --verbose
```

`chezmoi doctor` should stay `ok` for source-dir and dest-dir. A dirty
working tree warning is expected while editing. `chezmoi verify` reports
live destinations that differ from source. Review the dry-run before any
real apply; [AGENTS.md](./AGENTS.md) owns the conflict and non-TTY procedure.

## Manual Steps

After `chezmoi apply`, some first-run steps still need the owner:

- Install gvm: `bash < <(curl -LSs 'https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer')`
- Install Go 1.21 with `gvm install go1.21`, then set it as default: `gvm use go1.21 --default`
- [macOS] Add XQuartz as a login item; launch Docker Desktop once to accept its license ([Docker provisioning](#docker-provisioning)).
- [macOS] If the first apply stops on RustDesk identity, log in, launch and quit RustDesk once, then reapply. Grant Accessibility, Screen Recording, and, if needed, Input Monitoring permissions ([RustDesk provisioning](#rustdesk-provisioning)).
- [personal] Configure a System One connection and restart Pi after its package is installed ([System One setup](./dot_pi/private_agent/extensions/system-one/README.md)).

See [AGENTS.md](./AGENTS.md) for repository agent instructions (not deployed).
See [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl) for Pi-global agent instructions.
