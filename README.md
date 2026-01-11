# Dotfiles

Personal dotfiles managed with [chezmoi](https://www.chezmoi.io/).

## Quick Start

```bash
# Install chezmoi and apply dotfiles
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply <your-github-username>

# Bootstrap development environment
chezmoi apply
```

## What's Included

- **Shell**: Zsh with [antidote](https://getantidote.github.io/) plugin manager
- **Terminal**: Kitty with Zellij multiplexer
- **Editor**: Neovim (LazyVim-based)
- **Prompt**: Starship
- **Version Managers**: nvm, SDKMAN, gvm, rustup
- **Dev Tools**: kubectl, k9s, terraform, lazygit, ripgrep, fzf, zoxide

## Structure

```
dot_config/                    # XDG config files (.config/)
  ├── nvim/                    # Neovim configuration
  ├── kitty/                   # Kitty terminal
  ├── lazygit/                 # Lazygit TUI
  └── zellij/                  # Zellij multiplexer
run_onchange_bootstrap_env.sh  # Auto-installs dev tools
private_dot_zshrc              # Zsh configuration
dot_zsh_plugins.txt            # Plugin list
```

## Platform Support

- **macOS**: Homebrew-based installation
- **Ubuntu/WSL**: apt + source builds where needed

## Making Changes

```bash
# Edit source files
chezmoi edit ~/.zshrc

# Preview changes
chezmoi apply --dry-run --verbose

# Apply changes
chezmoi apply
```

See [CLAUDE.md](./CLAUDE.md) for detailed documentation.
