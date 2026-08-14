# Dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/) and [mise](https://mise.jdx.dev/).

## Overview

This repository is the **chezmoi source** for one person's machines (macOS,
Ubuntu/WSL, and Termux). Chezmoi maps these files onto `$HOME`; mise installs
and versions the tools. Profiles (`personal`, `axon-work-computer`, `termux`)
select what gets deployed.

Two agent-instruction files exist on purpose and must stay different:

- [AGENTS.md](./AGENTS.md) — repo-only guide for work **in this tree**. Listed
  in `.chezmoiignore`; never deployed. Chezmoi matches ignore rules against
  **destination** names, so this file cannot coexist with a source that deploys
  to `~/AGENTS.md` (same target; `inconsistent state`).
- [dot_pi/agent/literal_AGENTS.md](./dot_pi/agent/literal_AGENTS.md) — deploys to
  `~/.pi/agent/AGENTS.md`. Pi loads that agent-directory file first on every
  session, then walks ancestors from the cwd. Source is `literal_AGENTS.md` so
  a session whose cwd is under `dot_pi/agent/` does not also load the source
  (same text, two paths). Do not also create `~/AGENTS.md`.

Humans start at [Quick Start](#quick-start). Agents working in this repo start
at [AGENTS.md](./AGENTS.md). Phone setup is in [termux/README.md](./termux/README.md).
Harness internals are in [dot_local/share/agent-harness/README.md](./dot_local/share/agent-harness/README.md).
Zellij plugin/fork notes are in [dot_config/zellij/README.md](./dot_config/zellij/README.md).
Pi-global agent instructions are in [dot_pi/agent/literal_AGENTS.md](./dot_pi/agent/literal_AGENTS.md).

## Quick Start

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

# Install chezmoi and apply dotfiles (automatically installs mise + all tools)
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin" init --apply cartwmic

# That's it! Restart your shell
exec zsh
```

### Termux (Android)

Termux is a first-class profile (`profile: "termux"`) — thin SSH jump host,
`.termux` UI config, and ntfy jump handlers. It does **not** install the full
desktop/agent stack. See `termux/README.md`.

```bash
pkg install -y chezmoi git openssh coreutils
mkdir -p ~/.config/chezmoi
printf 'data:\n  profile: "termux"\n' > ~/.config/chezmoi/chezmoi.yaml
chezmoi init --apply git@github.com:cartwmic/dotfiles.git
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
- Utilities: ripgrep, jq, yq, task

**AI Tools:**

- Pi coding agent, claude, claude-code-acp, vectorcode, mistral-vibe, mermaid-cli

**Remote access:**

- RustDesk client on macOS and native Ubuntu/Debian
- Self-hosted rendezvous and relay configuration
- Shared unattended-access password loaded from `op://developer/RustDesk/password`

## Docker Provisioning

On `personal` profile hosts, `mise run bootstrap` installs Docker Desktop on macOS or Docker Engine from Docker's official apt repository on native Ubuntu. Work profiles, Termux, WSL, and unsupported Linux distributions are skipped. On macOS, provisioning repairs inaccessible legacy `/usr/local/bin` permissions when needed and verifies the Docker and Compose CLIs after installation. Docker Desktop requires one interactive launch to accept its license and finish setup.

On Ubuntu, provisioning refuses to remove conflicting distribution packages automatically. After those are removed explicitly, it installs Docker CE, containerd, Compose, and Buildx, then adds the current user to the `docker` group. Group membership takes effect after logout/login and grants root-equivalent access through the Docker daemon. Docker-published ports can bypass `ufw`; enforce host policy through Docker's `DOCKER-USER` chain where needed.

## RustDesk Provisioning

On `personal` profile hosts, `mise run bootstrap` installs RustDesk when missing. Other chezmoi profiles skip RustDesk. A chezmoi onchange script then applies portable settings from `.chezmoidata.toml`: rendezvous server, relay server, public server key, password approval mode, permanent-password verification, and service-enabled state. It removes RustDesk's `stop-service` option. Device identity, trusted-device data, proxy credentials, local IP state, UI state, and hardware-codec state remain machine-local.

On macOS, the same helper installs pinned RustDesk 1.4.9 launchd definitions, hardened to write daemon logs under `/Library/Logs/RustDesk` instead of `/tmp`: a root LaunchDaemon for the machine service and a LoginWindow/Aqua LaunchAgent for screen capture and input. Root service identity is seeded once from existing user identity, never from chezmoi source. After password rotation, only encrypted password storage and its salt are synchronized between Aqua and LoginWindow identity profiles. This lets RustDesk start at macOS login window after FileVault has been unlocked; nothing can start before FileVault unlock. A service first installed while machine is already at login window becomes available after next reboot. Fresh machines must first log in and launch RustDesk once to initialize identity.

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
- Harness instruction files are hand-maintained and split: repo [AGENTS.md](./AGENTS.md) (chezmoi source, not deployed), Pi-global [dot_pi/agent/literal_AGENTS.md](./dot_pi/agent/literal_AGENTS.md) (`~/.pi/agent/AGENTS.md`). Claude still uses `~/.claude/CLAUDE.md`; Codex still uses `~/.codex/AGENTS.md`.
- `furi` is installed by the `mise` bootstrap task, and bootstrap registers and starts `ashwwwin/automation-mcp` so the canonical `furi` MCP entry works for both Claude and Codex after apply.
- On macOS, `automation-mcp` also needs Accessibility and Screen Recording permissions in System Settings > Privacy & Security before its tools can fully control the machine.

## Tool Management with mise

mise handles version management for Node.js, Python, and Rust with automatic version switching:

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
run_onchange_after_10_mise_bootstrap.sh    # Installs tools after mise is available
private_dot_zshrc                # Zsh configuration
dot_zsh_plugins.txt              # Antidote plugin list
```

## Platform Support

- **macOS**: Homebrew + mise
- **Ubuntu/WSL**: apt + mise

All tools install automatically via `chezmoi apply`.

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

Root [README.md](./README.md) is the product doc (ignored from `$HOME`). Nested
docs belong only where the subtree has its own audience or procedure.

Pi auto-loads `AGENTS.md` / `AGENTS.override.md` / `CLAUDE.md` from
`~/.pi/agent/` first, then every ancestor of the cwd (path-deduped). It does
**not** auto-load `README.md`. Nested `AGENTS.md` in a source dir therefore
stacks on [AGENTS.md](./AGENTS.md) and the Pi-global file whenever cwd is in
that subtree. Use README for subtree procedure. Do not add `~/AGENTS.md`. Do
not add a second Pi-global copy besides
[dot_pi/agent/literal_AGENTS.md](./dot_pi/agent/literal_AGENTS.md).

### Instruction files (exactly these)

| File | Audience | Deployed |
| --- | --- | --- |
| [AGENTS.md](./AGENTS.md) | Chezmoi source operations | No |
| [dot_pi/agent/literal_AGENTS.md](./dot_pi/agent/literal_AGENTS.md) | Every Pi session | `~/.pi/agent/AGENTS.md` |
| [dot_claude/CLAUDE.md.tmpl](./dot_claude/CLAUDE.md.tmpl) | Every Claude Code session | `~/.claude/CLAUDE.md` |
| [dot_codex/modify_AGENTS.md.tmpl](./dot_codex/modify_AGENTS.md.tmpl) | Codex (managed Hindsight block only) | `~/.codex/AGENTS.md` |

Harness-agnostic skill/MCP procedure stays in
[dot_local/share/agent-harness/README.md](./dot_local/share/agent-harness/README.md).
Skills use `SKILL.md`, not `AGENTS.md`.

Do not add nested `AGENTS.md`. The only agent-instruction files are the four
in the table above.

### Already present (keep)

- [termux/README.md](./termux/README.md) — Termux profile / phone jump host
- [dot_config/zellij/README.md](./dot_config/zellij/README.md) — plugins/forks
- [dot_local/share/agent-harness/README.md](./dot_local/share/agent-harness/README.md) — skills/MCP adapters
- [dot_local/share/pi-patches/README.md](./dot_local/share/pi-patches/README.md) — add a `patch.mjs`, `PI_CHEZMOI_PROFILE=personal` gate, state/backup paths, re-apply after `npm update -g` / mise reinstall
- Per-patch READMEs under `dot_local/share/pi-patches/` (failure modes)
- [dot_pi/agent/extensions/README.md](./dot_pi/agent/extensions/README.md) — authoring: tests, never capture `ctx`, `create_` vs managed files, profile gates in `.chezmoiignore`. Deploys to `~/.pi/agent/extensions/README.md` (safe: Pi ignores README).
- Per-extension READMEs: [auto-compact](./dot_pi/agent/extensions/auto-compact/README.md), [hindsight](./dot_pi/agent/extensions/hindsight/README.md), [issue](./dot_pi/agent/extensions/issue/README.md), [ntfy](./dot_pi/agent/extensions/ntfy/README.md), [openrouter-gate](./dot_pi/agent/extensions/openrouter-gate/README.md), [pi-patch-guard](./dot_pi/agent/extensions/pi-patch-guard/README.md), [catalog-overlay-nudge](./dot_pi/agent/extensions/catalog-overlay-nudge/README.md), [goal](./dot_pi/agent/extensions/goal/README.md), [subagent](./dot_pi/agent/extensions/subagent/README.md), [web-search](./dot_pi/agent/extensions/web-search/README.md)
- [dot_config/nvim/README.md](./dot_config/nvim/README.md) — local LazyVim overlay, not the stock starter: plugins in `lua/plugins/`, do not vendor LazyVim, refresh `lazy-lock.json` via [prompts/git-commit-chezmoi-lazylock.md](./dot_config/nvim/prompts/git-commit-chezmoi-lazylock.md)
- [dot_pi/session-search/README.md](./dot_pi/session-search/README.md) — personal/homelab only (`ollama.internal` + claude-bridge digest). Ignored on work/termux. Do not copy onto `axon-work-computer`.

### Leave without their own doc

`dot_config/mise` (comments in `config.toml`), `dot_config/kitty`,
`dot_config/lazygit`, `dot_config/herdr`, `dot_config/mcphub` (nvim MCPHub
plugin, not agent-harness MCP), `private_dot_ssh`, `dot_local/user_scripts`,
`Library/`, `docs/plans/` (historical), `bin/` (covered by
[termux/README.md](./termux/README.md)), `dot_vibe/` (not a first-class
harness), `dot_local/share/loop-engine-providers/` (untracked / incomplete).


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
any real apply; from a non-TTY agent shell, apply needs `--force` if chezmoi
refuses `/dev/tty`.

## Manual Steps

After `chezmoi apply`, only these require manual setup:

- Install gvm: `bash < <(curl -LSs 'https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer')`
- Set default Go version: `gvm use go1.21 --default`
- [macOS] Add XQuartz as login item
- [macOS] Grant RustDesk Accessibility, Screen Recording, and, if needed, Input Monitoring permissions

See [AGENTS.md](./AGENTS.md) for repository agent instructions (not deployed).
See [dot_pi/agent/literal_AGENTS.md](./dot_pi/agent/literal_AGENTS.md) for Pi-global agent instructions.
