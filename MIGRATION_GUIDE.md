# Migration Guide: Bootstrap Script → mise

This guide shows how to migrate from `run_onchange_bootstrap_env.sh` to mise.

## TL;DR - It's a Drop-In Replacement

**Before (with bootstrap script):**
```bash
chezmoi apply
# run_onchange_bootstrap_env.sh executes automatically
# Tools get installed
# Restart shell
```

**After (with mise):**
```bash
chezmoi apply
# run_once_install_mise.sh executes (installs mise)
# run_onchange_mise_bootstrap.sh.tmpl executes (installs tools)
# Restart shell
```

**It's the same workflow!** Just run `chezmoi apply` and everything happens.

## What's Different?

### Installation Method

| Aspect | Bootstrap Script | mise |
|--------|-----------------|------|
| Trigger | `run_onchange_bootstrap_env.sh` | `run_onchange_mise_bootstrap.sh.tmpl` |
| Execution | Sequential | Parallel (faster) |
| Configuration | Shell script | TOML file |
| When it runs | When script changes | When mise config changes |

### File Changes in Chezmoi Source

**Removed/Replaced:**
- ❌ `run_onchange_bootstrap_env.sh` → Replaced by mise

**Added:**
- ✅ `run_once_install_mise.sh` → Installs mise once
- ✅ `run_onchange_mise_bootstrap.sh.tmpl` → Runs when config changes
- ✅ `dot_config/mise/config.toml` → Tool configuration
- ✅ `private_dot_zshrc` → Updated for mise paths

### Command Changes

**Version Manager Commands:**

| Tool | Old Command | New Command | Notes |
|------|-------------|-------------|-------|
| Node | `nvm use 20` | `mise use node@20` | Full version switching supported |
| Node | `nvm install 18` | `mise install node@18` | Install any version |
| Node | `nvm list` | `mise ls node` | List installed versions |
| Rust | `rustup default stable` | `mise use rust@stable` | mise replaces rustup |
| Upgrade tools | Re-run bootstrap script | `mise upgrade` | Update all tools at once |

**Other Tools (unchanged):**
- SDKMAN: `sdk` command still works
- uv: `uv` command still works
- gvm: `gvm` command still works (manual install)

## Migration Steps

### Option 1: On Existing Machine (Recommended)

This lets you test mise while keeping your current setup:

1. **Pull the latest changes:**
   ```bash
   cd ~/.local/share/chezmoi
   git pull origin main
   ```

2. **Apply with chezmoi:**
   ```bash
   chezmoi apply
   ```

   This will:
   - Install mise
   - Deploy mise config
   - Update your zshrc
   - Install all tools via mise

3. **Restart your shell:**
   ```bash
   exec zsh
   ```

4. **Verify everything works:**
   ```bash
   mise doctor              # Check mise setup
   mise ls                  # List installed tools
   node --version           # Test node
   kubectl version --client # Test kubectl
   ```

5. **Optional: Remove old bootstrap script:**
   ```bash
   cd ~/.local/share/chezmoi
   git rm run_onchange_bootstrap_env.sh
   git commit -m "Remove old bootstrap script, using mise now"
   git push
   ```

### Option 2: Fresh Machine Setup

If you're setting up a brand new machine:

1. **Install chezmoi and apply:**
   ```bash
   sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply <your-github-username>
   ```

2. **Restart shell:**
   ```bash
   exec zsh
   ```

That's it! Everything is installed.

## Rollback Plan

If you need to go back to the bootstrap script:

1. **Revert the changes:**
   ```bash
   cd ~/.local/share/chezmoi
   git revert <commit-hash>  # Revert the mise migration commit
   chezmoi apply
   ```

2. **Or manually restore:**
   ```bash
   # Remove mise files
   git rm run_once_install_mise.sh
   git rm run_onchange_mise_bootstrap.sh.tmpl
   git rm -r dot_config/mise

   # Restore old bootstrap script
   git checkout main -- run_onchange_bootstrap_env.sh

   # Restore old zshrc
   git checkout main -- private_dot_zshrc

   chezmoi apply
   ```

## Verification Checklist

After migration, verify these tools work:

### Core Tools
- [ ] `node --version` (via mise)
- [ ] `npm --version` (comes with node)
- [ ] `python --version` (via mise)
- [ ] `cargo --version` (via mise rust)
- [ ] `rustc --version` (via mise rust)

### Shell Tools
- [ ] `starship --version`
- [ ] `zellij --version`
- [ ] `z --help` (zoxide)
- [ ] `fzf --version`
- [ ] Ctrl+R for fzf history search
- [ ] Tab completion with fzf-tab

### Dev Tools
- [ ] `nvim --version`
- [ ] `lazygit --version`
- [ ] `rg --version` (ripgrep)
- [ ] `just --version`
- [ ] `task --version`

### Kubernetes
- [ ] `kubectl version --client`
- [ ] `k9s version`
- [ ] `helm version`
- [ ] `kustomize version`
- [ ] `kubeseal --version`

### Infrastructure
- [ ] `terraform version`
- [ ] `yq --version`
- [ ] `jq --version`

### AI/Productivity
- [ ] `mmdc --version` (mermaid-cli)
- [ ] `claude --version`
- [ ] `claude-code-acp --version`
- [ ] `vectorcode --version`
- [ ] `vibe --version` (mistral-vibe)

### Version Managers
- [ ] `sdk version` (SDKMAN)
- [ ] `uv --version`
- [ ] `gvm version` (if installed)

### Platform-Specific
- [ ] `kitty --version`
- [ ] Fonts installed (check terminal)

## Common Questions

### Q: Do I need to uninstall the old tools?

**A:** No! mise installs tools to its own directory (`~/.local/share/mise/installs/`). Your old installations remain untouched. mise's tools take precedence because mise modifies PATH when activated.

### Q: What if I have projects with .nvmrc files?

**A:** mise automatically reads `.nvmrc` files! Just `cd` into the directory and mise switches to the specified Node version automatically.

### Q: Can I use both mise and nvm?

**A:** Technically yes, but not recommended. They'll conflict in PATH. Choose one. mise is designed as a complete nvm replacement.

### Q: What about my existing global npm packages?

**A:** You'll need to reinstall them:
```bash
# List packages from old nvm installation
npm list -g --depth=0

# Reinstall with mise's node
mise use -g node@20
npm install -g <package-name>
```

Alternatively, npm packages like `mmdc` and `claude-code-acp` are in the mise config and will be installed automatically.

### Q: How do I update tools?

**Before:** Re-run bootstrap script
**After:**
```bash
mise upgrade              # Update all tools to latest
mise upgrade node         # Update specific tool
mise use node@20.11.1     # Switch to specific version
```

### Q: Where are tools installed?

**mise tools:** `~/.local/share/mise/installs/<tool>/<version>/`
**uv tools:** `~/.local/share/uv/tools/` (managed by uv)
**SDKMAN:** `~/.sdkman/` (same as before)
**kitty:** `~/.local/kitty.app/` (same as before)

## Support

If you encounter issues:

1. **Check mise status:**
   ```bash
   mise doctor
   ```

2. **Check tool installation:**
   ```bash
   mise ls
   mise which node    # See which node binary is used
   ```

3. **Reinstall a tool:**
   ```bash
   mise uninstall node
   mise install node@lts
   ```

4. **Check PATH:**
   ```bash
   echo $PATH | tr ':' '\n'  # Should show mise's bin directory early
   ```

5. **Re-run bootstrap:**
   ```bash
   mise run bootstrap
   ```

## Advantages of mise Over Bootstrap Script

1. ✅ **Faster** - Parallel installation instead of sequential
2. ✅ **Declarative** - Easy to see all tools in one TOML file
3. ✅ **Version Management** - Switch between tool versions easily
4. ✅ **Automatic Switching** - Changes versions based on directory
5. ✅ **Easy Updates** - `mise upgrade` updates everything
6. ✅ **Per-Project Versions** - Different versions per project
7. ✅ **Better Error Handling** - mise handles dependencies better
8. ✅ **Maintained** - Active project with regular updates
9. ✅ **Same Workflow** - Still just `chezmoi apply`
