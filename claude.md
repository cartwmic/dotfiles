# Chezmoi Dotfiles Configuration

## Project Overview

This is a personal dotfiles repository managed by [chezmoi](https://www.chezmoi.io/), a dotfile manager that helps maintain configuration files across multiple machines. The repository contains shell configurations, editor settings, and automated environment setup scripts.

## Repository Structure

```
.
├── dot_config/               # XDG config directory files
│   ├── nvim/                # Neovim configuration (LazyVim-based)
│   ├── kitty/               # Kitty terminal configuration
│   ├── lazygit/             # Lazygit TUI configuration
│   ├── zellij/              # Zellij terminal multiplexer config
│   ├── mcphub/              # MCP Hub configuration
│   └── zsh-completions/     # Custom zsh completion scripts
├── run_onchange_bootstrap_env.sh  # Environment bootstrap script
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
- **Version Managers**: 
  - nvm (Node.js)
  - SDKMAN (Java/JVM)
  - gvm (Go)
  - rustup (Rust)
- **Package Managers**: 
  - uv (Python)
  - cargo (Rust)
  - npm (Node.js)

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

### Bootstrap Script Behavior
- Idempotent: safe to run multiple times
- Cross-platform: detects macOS/Ubuntu and installs accordingly
- Prerequisites first: installs rust/cargo and uv before other tools
- Package categories:
  - **Cross-platform**: handled by language package managers or curl scripts
  - **macOS**: installed via Homebrew
  - **Ubuntu**: apt packages or special installation procedures

## Working with This Repository

### Making Changes
1. Edit files in the chezmoi source directory (`~/.local/share/chezmoi`)
2. Test changes with `chezmoi apply --dry-run --verbose`
3. Apply changes with `chezmoi apply`
4. Commit and push to version control

### Adding New Tools
1. Add installation logic to `run_onchange_bootstrap_env.sh`
2. Classify as cross-platform, macOS-specific, or Ubuntu-specific
3. Add executable check to the `missing_executables` section
4. Ensure installation is idempotent

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
The bootstrap script requires some manual intervention:
- Install and configure gvm (Go version manager)
- Set a default Go version after gvm installation
- On macOS: Add XQuartz as a login item (for imagemagick)

## Platform-Specific Notes

### macOS
- Uses Homebrew for most packages
- XQuartz required for imagemagick X11 support
- Display management aliases available for multi-monitor setups

### Ubuntu/WSL
- Updates apt repositories before installing packages
- Compiles some tools from source (starship, zellij)
- Downloads binaries directly for some tools (lazygit, k9s)
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
