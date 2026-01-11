# Chezmoi Dotfiles Configuration

## Project Overview

This is a personal dotfiles repository managed by [chezmoi](https://www.chezmoi.io/) and [mise](https://mise.jdx.dev/). Chezmoi manages the dotfiles and configuration sync, while mise handles development tool installation and version management.

## Repository Structure

```
.
├── dot_config/               # XDG config directory files
│   ├── mise/config.toml     # mise tool configuration
│   ├── nvim/                # Neovim configuration (LazyVim-based)
│   ├── kitty/               # Kitty terminal configuration
│   ├── lazygit/             # Lazygit TUI configuration
│   ├── zellij/              # Zellij terminal multiplexer config
│   ├── mcphub/              # MCP Hub configuration
│   └── zsh-completions/     # Custom zsh completion scripts
├── run_once_install_mise.sh      # Installs mise once
├── run_onchange_mise_bootstrap.sh.tmpl  # Runs when mise config changes
├── private_dot_zshrc        # Main zsh configuration
├── dot_zsh_plugins.txt      # Antidote plugin list
├── dot_zshenv               # Zsh environment variables
└── utils.sh                 # Shared utility functions
```

## Key Technologies

### Shell Environment
- **Shell**: Zsh with antidote plugin manager
- **Terminal**: Kitty
- **Multiplexer**: Zellij
- **Prompt**: Starship
- **Completions**: Custom zsh-completions with fzf-tab integration

### Development Tools
- **Editor**: Neovim (LazyVim distribution)
- **Git UI**: Lazygit
- **Tool Management**: mise (manages Node.js, Python, Rust, and 40+ dev tools)
- **Version Managers**:
  - mise (Node.js, Python, Rust - replaces nvm/rustup)
  - SDKMAN (Java/JVM)
  - gvm (Go - manual install)
- **Package Managers**:
  - uv (Python)
  - cargo (Rust, via mise)
  - npm (Node.js, via mise)

### DevOps/Cloud Tools
- kubectl, k9s, kustomize, kubeseal (Kubernetes)
- helm (Kubernetes package manager)
- terraform (Infrastructure as Code)
- just/go-task (Task runners)

### Utilities
- ripgrep, fzf, zoxide (CLI productivity)
- rage (Age encryption)
- yq (YAML processor)
- imagemagick, mermaid-cli (Image/diagram processing)
- vectorcode (AI code tool)
- claude, claude-code-acp (AI assistants)

## Important Conventions

### File Naming (chezmoi)
- `dot_*` → becomes `.filename` in home directory
- `private_*` → not included in git (for secrets)
- `run_onchange_*` → executes when file changes
- `.tmpl` suffix → template file processed by chezmoi

### Code Style
- Shell scripts: POSIX-compatible when possible, use `set -eu`
- Use utility functions from `utils.sh` (`is_macos`, `is_ubuntu`)
- Log with consistent prefixes: `[script_name] LEVEL: message`
- Always clean up temp directories with traps

### Tool Installation with mise
- **Automatic**: `chezmoi apply` triggers mise installation
- **Idempotent**: safe to run multiple times
- **Parallel**: tools install concurrently for speed
- **Cross-platform**: mise handles platform differences
- Tool categories:
  - **mise-managed**: Node.js, Python, Rust, kubectl, terraform, etc. (installed to `~/.local/share/mise/installs/`)
  - **Custom tasks**: uv, SDKMAN, kitty, claude, fonts, imagemagick
  - **Manual**: gvm (Go version manager)

## Working with This Repository

### Making Changes
1. Edit files in the chezmoi source directory (`~/.local/share/chezmoi`)
2. Test changes with `chezmoi apply --dry-run --verbose`
3. Apply changes with `chezmoi apply`
4. Commit and push to version control

### Adding New Tools

**For tools in mise registry:**
1. Edit `~/.local/share/chezmoi/dot_config/mise/config.toml`
2. Add tool to `[tools]` section: `newtool = "latest"`
3. Run `chezmoi apply` to install

**For custom installations:**
1. Add a task to `dot_config/mise/config.toml` under `[tasks]`
2. Add task to bootstrap dependencies
3. Ensure task has a condition for idempotency
4. Run `chezmoi apply` to test

Example:
```toml
[tasks."install-mytool"]
description = "Install my custom tool"
run = 'curl -L https://example.com/install.sh | sh'
condition = '! command -v mytool &> /dev/null'
```

### Configuration Files
- Prefer editing template files (`.tmpl`) over target files
- Use chezmoi data variables for profile-specific configs (see `example.chezmoi.yaml`)
- Test templates with `chezmoi execute-template`

## Security Notes
- Never commit API keys or secrets to version control
- Use `private_*` prefix for files containing sensitive data
- 1Password CLI integration available but currently commented out in zshrc
- Use rage/age for encrypting sensitive files if needed

## Known Manual Steps
After `chezmoi apply`, these require manual setup:
- Install gvm: `bash < <(curl -LSs 'https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer')`
- Set default Go version: `gvm use go1.21 --default`
- [macOS only] Add XQuartz as a login item (for imagemagick)

## Platform-Specific Notes

### macOS
- mise installed via Homebrew
- XQuartz required for imagemagick X11 support
- Display management aliases available for multi-monitor setups

### Ubuntu/WSL
- mise installed via curl script to `~/.local/bin/mise`
- Base packages installed via apt (build-essential, git, etc.)
- mise handles platform-specific tool installation automatically
- Font installation includes Nerd Fonts (Source Code Pro)

## AI Assistant Integration
This repository includes configurations for:
- Claude Code (with ACP support)
- VectorCode for semantic code search
- CodeCompanion plugin in Neovim (configured with GPT and Claude models)

When working with this repository, prefer:
- Editing existing files over creating new ones
- Testing changes before applying
- Following existing patterns and conventions
- Maintaining cross-platform compatibility where possible
