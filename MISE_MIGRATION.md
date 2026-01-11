# Migration from Bootstrap Script to mise

This document explains how to migrate from `run_onchange_bootstrap_env.sh` to mise for environment management.

## Overview

The mise configuration provides similar functionality to the bootstrap script but with these advantages:

- **Declarative configuration**: All tools in one TOML file
- **Parallel installation**: mise installs tools concurrently
- **Version pinning**: Easy to lock specific versions
- **Automatic updates**: `mise upgrade` updates everything
- **Per-project overrides**: Can have project-specific versions

## Critical Differences

### Tools Installed to Original Locations

The mise config replicates the bootstrap script's behavior for tools that need specific installation paths:

- **nvm**: `$HOME/.config/nvm` (via git clone + install script)
- **antidote**: `$HOME/.antidote` (via git clone)
- **fzf**: `$HOME/.fzf` (via git clone with shell integration)
- **fzf-tab**: `$HOME/fzf-tab` (via git clone)
- **SDKMAN**: Standard SDKMAN installation
- **uv**: Standard uv installation

This ensures your existing shell configurations (zshrc) continue to work.

### Tools Managed by mise

These tools are installed to mise's tool directory (typically `~/.local/share/mise/installs`):

- Language runtimes: rust, python
- CLI tools: kubectl, helm, k9s, terraform, starship, zellij, lazygit, etc.
- cargo packages: just, rage
- npm packages: @mermaid-js/mermaid-cli, @zed-industries/claude-code-acp

### Tools Still Requiring Manual Installation

- **gvm**: Must be installed manually (mise has go support, but gvm offers more Go-specific features)
- **XQuartz** (macOS): Must be added as a login item

## Chezmoi Integration

### File Structure

```
~/.local/share/chezmoi/
├── dot_config/
│   └── mise/
│       └── config.toml              # The mise.toml configuration
├── run_once_install_mise.sh         # Installs mise on new machines
└── run_onchange_mise_bootstrap.sh.tmpl  # Runs when mise config changes
```

### Setup Steps

1. **Copy mise.toml to chezmoi source**:
   ```bash
   mkdir -p ~/.local/share/chezmoi/dot_config/mise
   cp mise.toml.example ~/.local/share/chezmoi/dot_config/mise/config.toml
   ```

2. **Create the run_once script**:
   ```bash
   cp run_once_install_mise.sh.example ~/.local/share/chezmoi/run_once_install_mise.sh
   chmod +x ~/.local/share/chezmoi/run_once_install_mise.sh
   ```

3. **Create the run_onchange script**:
   ```bash
   cp run_onchange_mise_bootstrap.sh.tmpl.example \
      ~/.local/share/chezmoi/run_onchange_mise_bootstrap.sh.tmpl
   chmod +x ~/.local/share/chezmoi/run_onchange_mise_bootstrap.sh.tmpl
   ```

4. **Update your zshrc to activate mise**:

   Add to `~/.local/share/chezmoi/private_dot_zshrc` (or equivalent):
   ```bash
   # Activate mise
   if command -v mise &> /dev/null; then
     eval "$(mise activate zsh)"
   fi
   ```

5. **Optional: Disable the old bootstrap script**:
   ```bash
   # Rename to prevent it from running
   cd ~/.local/share/chezmoi
   git mv run_onchange_bootstrap_env.sh run_onchange_bootstrap_env.sh.disabled
   ```

### How It Works

1. **First-time setup** (new machine):
   - `chezmoi init` clones your dotfiles
   - `run_once_install_mise.sh` installs mise
   - `dot_config/mise/config.toml` is deployed to `~/.config/mise/config.toml`
   - `run_onchange_mise_bootstrap.sh.tmpl` runs `mise install && mise run bootstrap`
   - All tools and configs are installed

2. **Updating tools**:
   - Edit `dot_config/mise/config.toml` in chezmoi source
   - Run `chezmoi apply`
   - The hash in `run_onchange_mise_bootstrap.sh.tmpl` detects the change
   - Script re-runs automatically, installing/updating tools

3. **Syncing to another machine**:
   - `chezmoi update` pulls latest dotfiles
   - If `config.toml` changed, the run_onchange script re-runs
   - Environment stays in sync across machines

## Migration Checklist

- [ ] Copy `mise.toml.example` to `~/.local/share/chezmoi/dot_config/mise/config.toml`
- [ ] Copy `run_once_install_mise.sh.example` to chezmoi source
- [ ] Copy `run_onchange_mise_bootstrap.sh.tmpl.example` to chezmoi source
- [ ] Add mise activation to your zshrc
- [ ] Test on current machine: `mise install && mise run bootstrap`
- [ ] Verify all tools are installed: `mise ls` and check each tool's command
- [ ] Disable old bootstrap script once satisfied
- [ ] Commit changes to dotfiles repo
- [ ] Test on a fresh machine or VM

## Comparison: Bootstrap vs mise

| Feature | Bootstrap Script | mise |
|---------|-----------------|------|
| Configuration | Shell script | TOML file |
| Installation | Sequential | Parallel |
| Version management | Limited | Full support |
| Updates | Reinstall all | `mise upgrade` |
| Per-project versions | No | Yes |
| Idempotency | Yes | Yes |
| Platform detection | Yes | Yes |
| Custom tasks | Yes | Yes (tasks) |

## Troubleshooting

### mise command not found

Add to your shell PATH:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Tools not activating

Ensure mise is activated in your shell:
```bash
eval "$(mise activate zsh)"
```

### npm packages failing

Make sure nvm is installed and sourced before mise tries to install npm packages:
```bash
mise run install-nvm
source ~/.zshrc
mise install
```

### Conflict with existing installations

mise can coexist with existing tool installations. The PATH order determines which version is used. To prefer mise versions:
```bash
# In ~/.zshrc, ensure mise activation comes early
eval "$(mise activate zsh)"  # This should come before nvm, sdkman, etc.
```

## Rollback Plan

If you need to rollback to the bootstrap script:

1. Re-enable the bootstrap script:
   ```bash
   cd ~/.local/share/chezmoi
   git mv run_onchange_bootstrap_env.sh.disabled run_onchange_bootstrap_env.sh
   ```

2. Remove mise integration:
   ```bash
   rm -rf dot_config/mise
   rm run_once_install_mise.sh
   rm run_onchange_mise_bootstrap.sh.tmpl
   ```

3. Apply changes:
   ```bash
   chezmoi apply
   ```

## Additional Resources

- [mise Documentation](https://mise.jdx.dev/)
- [mise Registry](https://mise.jdx.dev/registry.html)
- [chezmoi Documentation](https://www.chezmoi.io/)
- [chezmoi with mise Guide](https://www.chezmoi.io/user-guide/tools/mise/)
