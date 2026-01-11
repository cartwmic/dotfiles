# mise + Chezmoi Integration

This document explains how mise is integrated with chezmoi for automatic environment setup.

## Overview

**Drop-in replacement for the existing bootstrap workflow.**

The setup is designed so that **a single command sets up everything**:

```bash
chezmoi apply
```

This is identical to the previous bootstrap workflow - just run `chezmoi apply` and everything happens automatically.

What happens:
1. Installs mise (if not already installed) via `run_once_install_mise.sh`
2. Deploys mise configuration to `~/.config/mise/config.toml`
3. Deploys updated `~/.zshrc` with mise integration
4. Runs `run_onchange_mise_bootstrap.sh.tmpl` which:
   - Installs all tools via `mise install` (parallel)
   - Runs `mise run bootstrap` for custom tasks
5. Everything is ready after shell restart

## File Structure

```
~/.local/share/chezmoi/
├── dot_config/
│   └── mise/
│       └── config.toml                    # mise tool configuration
├── private_dot_zshrc                      # zsh config with mise integration
├── run_once_install_mise.sh               # Installs mise once
└── run_onchange_mise_bootstrap.sh.tmpl    # Runs when mise config changes
```

## How It Works

### First Time Setup (New Machine)

1. **Install chezmoi** (if not already):
   ```bash
   sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply <your-github-username>
   ```

2. **Chezmoi automatically runs**:
   - `run_once_install_mise.sh` → Installs mise
   - Deploys `dot_config/mise/config.toml` → `~/.config/mise/config.toml`
   - Deploys `private_dot_zshrc` → `~/.zshrc`
   - `run_onchange_mise_bootstrap.sh.tmpl` → Runs `mise install && mise run bootstrap`

3. **Restart your shell**:
   ```bash
   exec zsh
   ```

4. **Everything is installed** and ready to use!

### Updating Tools

When you update the mise configuration:

1. **Edit the config**:
   ```bash
   chezmoi edit ~/.config/mise/config.toml
   ```

2. **Apply changes**:
   ```bash
   chezmoi apply
   ```

3. **Chezmoi detects the change** (via sha256sum hash in the template) and automatically re-runs `run_onchange_mise_bootstrap.sh.tmpl`

### Syncing Across Machines

1. **On machine A**: Make changes and commit
   ```bash
   cd ~/.local/share/chezmoi
   git add .
   git commit -m "Update mise config"
   git push
   ```

2. **On machine B**: Update and apply
   ```bash
   chezmoi update
   # This automatically re-runs bootstrap if config changed
   ```

## Idempotency

All scripts are idempotent and safe to run multiple times:

- ✅ `run_once_install_mise.sh` - Only installs if `mise` command not found
- ✅ `run_onchange_mise_bootstrap.sh.tmpl` - Only runs when config hash changes
- ✅ `mise install` - Only installs missing tools
- ✅ `mise run bootstrap` - All tasks have conditions to check if already done

Running `chezmoi apply` multiple times is safe and won't reinstall everything.

## What Gets Installed

### Tools Managed by mise

These install to `~/.local/share/mise/installs/<tool>/<version>/`:

- **Languages**: rust, python, node
- **Shell**: starship, zellij, zoxide, antidote, fzf, fzf-tab
- **Dev**: neovim, lazygit, ripgrep, just, rage, go-task
- **Kubernetes**: kubectl, k9s, helm, kustomize, kubeseal
- **Infrastructure**: terraform, jq, yq
- **AI/Productivity**: mmdc, claude-code-acp (via npm)

### Tools Installed via Tasks

These install to their standard locations:

- **uv**: `~/.local/bin/uv` (Python package installer)
- **SDKMAN**: `~/.sdkman/` (Java/JVM tools)
- **kitty**: `~/.local/kitty.app/` (Terminal emulator)
- **claude**: Custom installer location
- **vectorcode, mistral-vibe**: Via uv tool install
- **Fonts**: `~/.local/share/fonts/` (Ubuntu) or system (macOS)

### Manual Installation Required

- **gvm**: Must install manually (same as bootstrap script)
- **XQuartz login item**: Must configure manually on macOS

## Installation Paths

### mise Tools

All mise-managed tools go to:
```
~/.local/share/mise/installs/<tool>/<version>/
```

Access paths with:
```bash
mise where <tool>         # Get installation path
mise ls                   # List all installed tools
mise which node           # Show which node binary is used
```

### GitHub Backend Tools

Tools installed via `github:owner/repo`:
```
~/.local/share/mise/installs/github-owner-repo/<version>/
```

Examples:
- `github:mattmc3/antidote` → `~/.local/share/mise/installs/github-mattmc3-antidote/latest/`
- `github:junegunn/fzf` → `~/.local/share/mise/installs/github-junegunn-fzf/latest/`

## Version Manager CLIs

### What mise Replaces

- **nvm** → mise has built-in node support
  - Use: `mise use node@20` instead of `nvm use 20`
  - The `nvm` CLI is NOT installed

- **rustup** → mise has built-in rust support
  - Use: `mise use rust@stable` instead of `rustup default stable`
  - The `rustup` CLI is NOT installed

### What Remains Available

- **SDKMAN** → Installed via task, `sdk` CLI available
  - Use: `sdk install java 21.0.1-tem`

- **gvm** → Manual installation (not automated)
  - Use: `gvm use go1.21`

- **uv** → Installed via task, `uv` CLI available
  - Use: `uv tool install <package>`

## Node Version Management (nvm Replacement)

mise provides **full version switching capabilities** just like nvm:

### Command Comparison

| Task | nvm | mise |
|------|-----|------|
| Install version | `nvm install 20` | `mise install node@20` |
| Switch version | `nvm use 20` | `mise use node@20` |
| Set global default | `nvm alias default 20` | `mise use -g node@20` |
| List installed | `nvm list` | `mise ls node` |
| List available | `nvm ls-remote` | `mise ls-remote node` |
| Current version | `nvm current` | `mise current node` |

### Automatic Version Switching

mise automatically switches Node versions based on:
- `.nvmrc` files (reads existing nvm configs)
- `.node-version` files
- `mise.toml` or `.mise.toml` files

**Example:**
```bash
# Install multiple versions
mise install node@20
mise install node@18
mise install node@16

# Set global default
mise use -g node@20

# In a project with .nvmrc
cd ~/my-project
echo "18" > .nvmrc
cd .                    # mise auto-switches to node 18

# Or use mise.toml for the project
mise use node@16        # Creates .mise.toml with node@16
```

### Key Advantage

With `eval "$(mise activate zsh)"` in your zshrc (already configured), version switching happens **automatically** when you cd into directories. No need to run `nvm use` manually!

## Troubleshooting

### mise command not found

If mise isn't in PATH after installation:

```bash
# For Linux
export PATH="$HOME/.local/bin:$PATH"

# For macOS with Homebrew
export PATH="/opt/homebrew/bin:$PATH"

# Restart shell
exec zsh
```

### Tools not found after mise install

Ensure mise is activated in your shell:

```bash
eval "$(mise activate zsh)"
```

This should already be in `~/.zshrc` from chezmoi, but verify it's there.

### run_onchange script not running

If you edit the mise config and chezmoi doesn't re-run the bootstrap:

```bash
# Force re-run by touching the template
touch ~/.local/share/chezmoi/run_onchange_mise_bootstrap.sh.tmpl
chezmoi apply
```

### npm packages fail to install

Ensure node is installed first:

```bash
mise install node
mise use node@lts
npm install -g @mermaid-js/mermaid-cli
```

## Customization

### Adding a New Tool

1. **Edit mise config**:
   ```bash
   chezmoi edit ~/.config/mise/config.toml
   ```

2. **Add the tool**:
   ```toml
   [tools]
   deno = "latest"    # Add this line
   ```

3. **Apply**:
   ```bash
   chezmoi apply
   # This triggers re-run of bootstrap
   ```

### Adding a Custom Task

Add to the `[tasks]` section in mise config:

```toml
[tasks."install-my-tool"]
description = "Install my custom tool"
run = 'curl -L https://example.com/install.sh | sh'
condition = '! command -v my-tool &> /dev/null'
```

Then add it to the bootstrap task dependencies:

```toml
[tasks.bootstrap]
depends = [
  # ... existing dependencies ...
  "install-my-tool"
]
```

### Pinning Versions

Change from `latest` to specific version:

```toml
[tools]
node = "20.11.0"     # Pin to specific version
terraform = "1.6.0"  # Pin to specific version
```

## Comparison: Old Bootstrap vs mise + Chezmoi

| Aspect | Bootstrap Script | mise + Chezmoi |
|--------|-----------------|----------------|
| Setup Command | `./run_onchange_bootstrap_env.sh` | `chezmoi apply` |
| Installation | Sequential | Parallel (faster) |
| Configuration | Shell script | TOML file |
| Updates | Re-run script | `mise upgrade` |
| Version Management | Limited | Full support |
| Idempotency | Yes | Yes |
| Cross-machine sync | via chezmoi | via chezmoi |
| Per-project versions | No | Yes |

## Additional Resources

- [mise Documentation](https://mise.jdx.dev/)
- [chezmoi Documentation](https://www.chezmoi.io/)
- [mise + chezmoi Integration Guide](https://www.chezmoi.io/user-guide/tools/mise/)
