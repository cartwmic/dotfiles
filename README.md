# Dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/) and [mise](https://mise.jdx.dev/).

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
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply cartwmic

# That's it! Restart your shell
exec zsh
```

## What's Included

**Shell & Terminal:**

- Zsh with [antidote](https://getantidote.github.io/) plugin manager
- Kitty terminal with Zellij multiplexer
- Starship prompt, fzf fuzzy finder, zoxide smart cd

**Development Tools:**

- Editor: Neovim (LazyVim)
- Git: lazygit TUI
- Languages: Node.js, Python, Rust (managed by mise)
- Version Management: mise (replaces nvm/rustup), SDKMAN, gvm

**DevOps/Cloud:**

- Kubernetes: kubectl, k9s, helm, kustomize, kubeseal
- Infrastructure: terraform
- Utilities: ripgrep, jq, yq, task

**AI Tools:**

- claude, claude-code-acp, vectorcode, mistral-vibe, mermaid-cli

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
- Top-level harness instruction files such as `AGENTS.md` and `CLAUDE.md` remain hand-maintained.
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
run_once_install_mise.sh         # Installs mise once
run_onchange_mise_bootstrap.sh   # Runs when mise config changes
private_dot_zshrc                # Zsh configuration
dot_zsh_plugins.txt              # Antidote plugin list
```

## Platform Support

- **macOS**: Homebrew + mise
- **Ubuntu/WSL**: apt + mise

All tools install automatically via `chezmoi apply`.

## Making Changes

```bash
# Edit config files
chezmoi edit ~/.zshrc
chezmoi edit ~/.config/mise/config.toml

# Apply changes (auto-runs mise bootstrap if config changed)
chezmoi apply
```

## Manual Steps

After `chezmoi apply`, only these require manual setup:

- Install gvm: `bash < <(curl -LSs 'https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer')`
- Set default Go version: `gvm use go1.21 --default`
- [macOS] Add XQuartz as login item

See [CLAUDE.md](./CLAUDE.md) for project-specific documentation.
