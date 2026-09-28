# Dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/) and [mise](https://mise.jdx.dev/).

## Overview

This repository is the **chezmoi source** for one person's machines (macOS,
Ubuntu/WSL, and Termux). Chezmoi maps these files onto `$HOME`; mise installs
and versions the tools. Profiles (`personal`, `axon-work-computer`, `termux`)
select what gets deployed. This Git repository is public. A chezmoi
`private_*` source sets the destination's file mode; it does not hide source
content from Git. Keep secret values outside this tree and read them from
1Password at runtime.

Two agent-instruction files exist on purpose and must stay different:

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

On macOS, install [Homebrew](https://brew.sh/) first; the mise install script
stops if `brew` is missing. On a `personal` desktop, prepare an authenticated
1Password CLI (`op`) that can read `op://developer/RustDesk/password` before
applying. The RustDesk post-apply helper reads that item using desktop-app
authentication or a host-local service-account token. The owner must provision
access to the item in 1Password; this repository does not create it. A
`personal` apply stops at the helper if the item cannot be read. Keep the token
outside this repository.

```bash
# Install zsh and set as default shell (required before running chezmoi)
# Ubuntu/WSL:
sudo apt-get update && sudo apt-get install -y zsh
sudo chsh "$USER" -s /usr/bin/zsh

# macOS (zsh is already default on modern macOS)
# Skip this step

# Create chezmoi config directory
mkdir -p ~/.config/chezmoi

# Copy example config (download from repo or create manually)
# Option 1: Download from GitHub
curl -fsSL https://raw.githubusercontent.com/cartwmic/dotfiles/main/example.chezmoi.yaml -o ~/.config/chezmoi/chezmoi.yaml

# Option 2: Create manually
cat > ~/.config/chezmoi/chezmoi.yaml << 'EOF'
data:
  profile: "personal"
EOF

# Install chezmoi and apply dotfiles (runs profile-gated mise bootstrap)
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin" init --apply cartwmic

# Restart your shell, then complete the applicable manual steps below
exec zsh
```

### Termux (Android)

Termux is a first-class profile (`profile: "termux"`) — thin SSH jump host,
`.termux` UI config, and ntfy jump handlers. It does **not** install the full
desktop/agent stack. See `termux/README.md`.

```bash
pkg install -y chezmoi git openssh coreutils termux-api python vim
mkdir -p ~/.config/chezmoi
printf 'data:\n  profile: "termux"\n' > ~/.config/chezmoi/chezmoi.yaml
chezmoi init --apply https://github.com/cartwmic/dotfiles.git
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
- Portable `session-recap` and `passage-review` workflows; Termux stays an SSH client. It does not host the Herdr plugin.

**Remote access:**

- RustDesk client on macOS and native Ubuntu/Debian
- Self-hosted rendezvous and relay configuration
- Shared unattended-access password loaded from `op://developer/RustDesk/password`

## Docker Provisioning

On `personal` profile hosts, `mise run bootstrap` installs Docker Desktop on macOS or Docker Engine from Docker's official apt repository on native Ubuntu. Work profiles, Termux, WSL, and unsupported Linux distributions are skipped. On macOS, provisioning repairs inaccessible legacy `/usr/local/bin` permissions when needed and verifies the Docker and Compose CLIs after installation. Docker Desktop requires one interactive launch to accept its license and finish setup.

On Ubuntu, provisioning refuses to remove conflicting distribution packages automatically. After those are removed explicitly, it installs Docker CE, containerd, Compose, and Buildx, then adds the current user to the `docker` group. Group membership takes effect after logout/login and grants root-equivalent access through the Docker daemon. Docker-published ports can bypass `ufw`; enforce host policy through Docker's `DOCKER-USER` chain where needed.

## RustDesk Provisioning

On `personal` hosts, `mise run bootstrap` installs RustDesk when missing. Other
profiles skip it. A chezmoi onchange helper applies rendezvous, relay, server
key, password approval, and service settings. Device identity and trust data
stay machine-local.

On macOS, the helper installs pinned RustDesk 1.4.9 launchd jobs for service
and login-window capture. Daemon logs go under `/Library/Logs/RustDesk`. The
service identity starts from the existing user identity; password rotation
synchronizes only encrypted password storage and salt. RustDesk can start at
the login window after FileVault unlock. A fresh machine needs one graphical
login and RustDesk launch to initialize identity. A first install at the login
window becomes available after the next reboot.

The permanent password lives only in 1Password. Rotate it there, then
reapply with:

```bash
~/.local/user_scripts/configure_rustdesk.sh
```

On macOS, stop RustDesk before changing portable settings. If its LoginWindow
server is active, log in graphically first; a password-only reapplication may
run while RustDesk is open. On Linux, configuration briefly restarts
`rustdesk.service`. Do not run the helper through the RustDesk session being
reconfigured. For service file paths and source maintenance, see
[AGENTS.md](./AGENTS.md) and
`dot_local/user_scripts/executable_configure_rustdesk.sh.tmpl`.

Shared passwords increase blast radius: compromise of one machine or this
1Password item affects every managed RustDesk host.

## Harness Config Adapters

Canonical harness-agnostic configuration lives under:

- `~/.local/share/agent-harness/canonical/skills/`
- `~/.local/share/agent-harness/canonical/mcp/servers.json`

These are the authoring sources of truth. Harness-specific adapters project them into supported harnesses.

Current supported harnesses:

- `claude`
- `codex`
- `pi`

Current supported configuration domains:

- `skills`
- `mcp`

Maintenance and extension documentation lives in [dot_local/share/agent-harness/README.md](./dot_local/share/agent-harness/README.md).

Apply all supported adapters:

```bash
~/.local/user_scripts/apply_harness_config.sh
```

Apply a single harness:

```bash
~/.local/user_scripts/apply_harness_config.sh claude
~/.local/user_scripts/apply_harness_config.sh codex
~/.local/user_scripts/apply_harness_config.sh pi
```

Interactively sync canonical skills (shows diff, prompts before applying):

```bash
~/.local/user_scripts/sync_harness_skills.sh            # interactive
~/.local/user_scripts/sync_harness_skills.sh --dry-run   # preview only
~/.local/user_scripts/sync_harness_skills.sh --yes        # no prompt
```

Behavior:

- Skills are linked into harness skill directories from the canonical `SKILL.md` bundles.
- `sync_harness_skills.sh` compares chezmoi source against deployed canonical skills, showing additions, removals (orphans), and content changes before applying.
- Claude MCP is generated as a managed setup script and applied through the Claude CLI when available.
- Codex MCP is rendered into a managed block inside `~/.codex/config.toml`.
- Canonical MCP entries are authored in `dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl`.

Notes:

- Harness-specific MCP secrets can be mapped in adapter metadata under `~/.local/share/agent-harness/adapters/<harness>/mcp-secrets.json`.
- Secret-backed adapter metadata is resolved through the 1Password CLI via `op read`.
- Harness instruction files are hand-maintained and split: repo [AGENTS.md](./AGENTS.md) (chezmoi source, not deployed), Pi-global [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl) (`~/.pi/agent/AGENTS.md`). Claude still uses `~/.claude/CLAUDE.md`; Codex still uses `~/.codex/AGENTS.md`.
- `furi` is installed by the `mise` bootstrap task, and bootstrap registers and starts `ashwwwin/automation-mcp` so the canonical `furi` MCP entry works for both Claude and Codex after apply.
- On macOS, `automation-mcp` also needs Accessibility and Screen Recording permissions in System Settings > Privacy & Security before its tools can fully control the machine.

## System One in Pi

The `personal` profile loads [cartwmic/system-one-tools](https://github.com/cartwmic/system-one-tools)
as a Git package, not an npm package. Work and Termux omit it. The local
[System One directory](./dot_pi/private_agent/extensions/system-one/README.md)
contains documentation, not another extension loader.

After approving a targeted settings apply, restart Pi and run `/so status`.
Agent access starts off; `/so on` enables the current session. Use `/so settings`
to select a machine-local connection and adapter. Keep credentials in the
runtime environment, not this public repository. The Git URL is unpinned;
package updates and paid provider tests need separate approval. The scoped
[agent guide](./dot_pi/private_agent/extensions/system-one/AGENTS.md) covers
isolated tests and rollout. Rendering settings alone does not prove a provider call.

## Herdr overview and phone route

The personal and work desktop profiles pin Herdr **0.9.1 / protocol 22** and
link the source-managed overview plugin. The Pi adapter publishes a real-user
prompt and, when opted in, a separate recap after the response settles. The overview reads
native Herdr pane state and those supplied records. It does not parse a
transcript or generate a summary. Manual pane/tab labels remain under owner
control; workspaces are never auto-named. Herdr 0.9.1 has no atomic
conditional rename, so a manual edit can still race the final automatic write.

At `[ui].mobile_width_threshold` (64 by default), the view selects the narrow
Board; wider terminals get Mosaic. Both navigate the same native session.
Pane detail keeps recent output, prompt, live agent state, and published recap
distinct, and native details remain visible when a recap is missing or failed.
See the [Herdr plugin guide](./dot_local/share/herdr-overview/README.md) for
navigation, manual pane-source recaps, naming policy, and move behavior. The
[Pi adapter guide](./dot_pi/private_agent/extensions/herdr-overview/README.md)
covers publication.

The `install-herdr-overview` mise task (also part of desktop bootstrap)
verifies Herdr 0.9.1 and links/enables the source manifest. Linking leaves the
running server untouched. On a compatible running server,
`herdr plugin action invoke overview.reconcile --plugin overview` loads the
linked action and opens or reconciles an overview tab in the background.
`herdr server reload-config` separately applies the new keybinding. A later
owner-controlled server start also runs the plugin's startup hook.

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

Desktop installs default to `auto_publish = false` with no recap command.
Configure an unmanaged `~/.config/session-recap/config.local.toml` with an
executable argv for manual recaps; add `auto_publish = true` to opt in to Pi
publication. The editable prompt templates and local configuration are
covered in [`dot_local/share/session-recap/README.md`](./dot_local/share/session-recap/README.md).
When enabled, Pi's adapter prepares then publishes settled recaps. Successful Pi publications
start/restart a 30-second workspace quiet period; when it expires, the group uses
latest published recaps for panes currently in that native workspace, including
manual pane-source recaps for non-Pi panes. A successful workspace group can
trigger a Herdr-session group from workspaces still live in the native snapshot.
Failed recaps do not replace the last good record or reset that interval. With
`auto_publish = false`, pending group deadlines stay stored without group
model calls or wake-ups; a later reconcile after opt-in can catch up. Dated
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

mise selects Node.js and Python versions. rustup selects Rust toolchains:

```bash
# Install multiple Node versions
mise install node@20 node@18

# Switch versions globally or per-project
mise use -g node@20              # Global default
mise use node@18                 # Current project

# In a project whose .nvmrc contains "18"
cd project/
node --version                   # mise selects that project's Node version
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
run_onchange_after_10_mise_bootstrap.sh    # Installs tools after mise is available
private_dot_zshrc                # Zsh configuration
dot_zsh_plugins.txt              # Antidote plugin list
```

## Platform Support

- **macOS**: Homebrew + mise
- **Ubuntu/WSL**: apt + mise

Desktop tool installation runs through the profile-gated mise bootstrap after `chezmoi apply`. Termux uses its own package setup in `termux/README.md`.

## Usage

Edit **source** in this repository (or via `chezmoi edit` on a destination
path). Apply to materialize `$HOME`. Onchange scripts re-run when their
inputs change (mise bootstrap, harness apply, Pi patches, RustDesk, and so on).

```bash
# Edit config files
chezmoi edit ~/.zshrc
chezmoi edit ~/.config/mise/config.toml

# Preview, then apply (auto-runs mise bootstrap if config changed)
chezmoi apply --dry-run --verbose
chezmoi apply
```

`chezmoi re-add` is a silent no-op on templated source files — change the
`.tmpl` in this tree instead. `chezmoi diff` shows live destination on the
**a/** side and source on **b/** (inverted from a usual source→target diff).

## Docs map

Start here for machine setup and user workflows. For work in this source tree,
read [AGENTS.md](./AGENTS.md); it links the component-local agent guides
and controls apply. Pi's global instructions are a separate source file at
[dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl).
Component READMEs cover setup and use:

- [Termux and phone SSH](./termux/README.md)
- [Herdr overview](./dot_local/share/herdr-overview/README.md) and its [Pi adapter](./dot_pi/private_agent/extensions/herdr-overview/README.md)
- [session-recap](./dot_local/share/session-recap/README.md)
- [passage-review](./dot_local/share/passage-review/README.md) and its [Pi `/review` entry point](./dot_pi/private_agent/extensions/passage-review/README.md)
- [Pi extensions](./dot_pi/private_agent/extensions/README.md) (index for the other extension guides)
- [Harness skills and MCP](./dot_local/share/agent-harness/README.md), [Pi patches](./dot_local/share/pi-patches/README.md), [Neovim](./dot_config/nvim/README.md), and [Zellij](./dot_config/zellij/README.md)
- [session-search](./dot_pi/session-search/README.md) for the personal profile

## Validation

After editing source, confirm mapping and that apply would not surprise you:

```bash
chezmoi doctor
chezmoi verify
chezmoi apply --dry-run --verbose
```

`chezmoi doctor` should stay `ok` for source-dir and dest-dir. Treat a dirty
working tree warning as informational while you still have uncommitted edits.
`chezmoi verify` reports destinations that drifted from source. Dry-run before
any real apply. If a non-TTY apply cannot open `/dev/tty`, stop and follow the
source/live inspection and owner-approval procedure in
[AGENTS.md](./AGENTS.md#workflow). Use `--force` only for an approved
source-side choice in a specific conflict.

## Manual Steps

After `chezmoi apply`, complete the steps that apply to this host:

- Install gvm: `bash < <(curl -LSs 'https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer')`
- Set default Go version: `gvm use go1.21 --default`
- [macOS] Add XQuartz as a login item.
- [personal macOS] Launch Docker Desktop once to accept its license and finish setup. See [Docker Provisioning](#docker-provisioning).
- [personal macOS] Log in and launch RustDesk once on a fresh machine; grant Accessibility, Screen Recording, and, if needed, Input Monitoring permissions. See [RustDesk Provisioning](#rustdesk-provisioning).
- [desktop Herdr] Start or restart a compatible server after linking the overview plugin. An existing server has not loaded the new startup hook. See [Herdr overview and phone route](#herdr-overview-and-phone-route).
- [recap users] Set a host-local recap command; opt in to automatic Pi publication if wanted. See [Portable recaps](#portable-recaps).

See [AGENTS.md](./AGENTS.md) for repository agent instructions (not deployed).
See [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl) for Pi-global agent instructions.
