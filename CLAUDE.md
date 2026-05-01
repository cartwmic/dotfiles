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
│   ├── zellij/              # Zellij terminal multiplexer config (see dot_config/zellij/README.md for plugin/fork notes)
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
- go-task (Task runner)

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
- OpenAI Codex CLI
- Pi coding agent (with pi-mcp-adapter extension)
- VectorCode for semantic code search
- CodeCompanion plugin in Neovim (configured with GPT and Claude models)

### pi runtime patches

Not every fix lands upstream on our timeline. The `dot_local/share/pi-patches/` tree holds idempotent runtime patches against the user's installed `@mariozechner/pi-coding-agent` / `@mariozechner/pi-ai` files.

- **Apply script**: `dot_local/user_scripts/executable_apply_pi_patches.sh` (auto-runs on `chezmoi apply` via the onchange template below)
- **Onchange trigger**: `run_onchange_apply_pi_patches.sh.tmpl` — embeds sha256 of each `patch.mjs`, the apply script, and the currently installed pi-coding-agent / pi-ai versions. Re-runs on any change.
- **State**: `~/.local/state/chezmoi-pi-patches/<patch-name>.json` (last-applied revision, fingerprints, backup path)
- **Backup**: each patched file is backed up alongside as `<file>.orig.chezmoi-pi-patch` on first patch.

**User-facing rule**: after `npm update -g @mariozechner/pi-coding-agent` (or any mise/npm reinstall), run `chezmoi apply` to re-apply patches.

**Active patches**:

- `anthropic-idle-watchdog` — adds an SSE per-chunk idle watchdog and forwards Anthropic `ping` events through pi-ai's event stream. Fixes the "working… stuck" stall on the native anthropic provider. Tracks upstream issue [pi-mono#3020](https://github.com/badlogic/pi-mono/issues/3020). See its `README.md` for failure modes (anchor-not-found, stale revision, etc.) and resolution.

**Adding a patch**: create `dot_local/share/pi-patches/<name>/patch.mjs` (and ideally a `README.md`). The apply script auto-discovers any directory containing `patch.mjs` and invokes it.

### Agent Harness

Skills and MCP servers are managed centrally via the **agent-harness** system:

- **Canonical source**: `dot_local/share/agent-harness/canonical/` (skills and MCP config)
- **External skills**: `~/.local/share/agent-harness/external-skills/` (git repos pulled by chezmoi)
- **Adapters**: `dot_local/share/agent-harness/adapters/{claude,codex,pi}/` (per-agent secrets)
- **Apply script**: `dot_local/user_scripts/executable_apply_harness_config.sh` (auto-runs on `chezmoi apply`)
- **Sync script**: `dot_local/user_scripts/executable_sync_harness_skills.sh` (manual, interactive)
- **External repos**: `.chezmoiexternal.toml` (declares git repos chezmoi clones/pulls)

When `chezmoi apply` runs, the apply script:
1. Symlinks canonical skills → `~/.claude/skills/`, `~/.codex/skills/`, `~/.pi/agent/skills/`, `~/.agents/skills/`
2. Symlinks external skills (from cloned repos) → same agent skill directories
3. Generates MCP config for each agent in its native format
4. Resolves secrets via 1Password where available

**Skill precedence**: Canonical skills are linked first and win on name collisions with external skills.

**Syncing skills**: Run `~/.local/user_scripts/sync_harness_skills.sh` to compare chezmoi source skills against what's deployed. It shows a color-coded diff (additions, removals, content changes) and prompts before applying. Flags: `--dry-run` (preview only), `--yes` (skip prompt). This also cleans up stale symlinks across all harnesses. Note: the sync script only manages canonical skills; external skills are updated automatically by `chezmoi apply` via git pull.

**Adding a new skill**: Create a directory under `dot_local/share/agent-harness/canonical/skills/<name>/SKILL.md` and run `sync_harness_skills.sh` or `chezmoi apply`. It will be available in all agents.

**Adding external skill repos**: Add a `["path"]` entry to `.chezmoiexternal.toml` with `type = "git-repo"`. The repo is cloned to `~/.local/share/agent-harness/external-skills/<name>/` and any top-level directories containing `SKILL.md` are automatically symlinked into all agent skill directories on `chezmoi apply`. Use `refreshPeriod` to control how often chezmoi re-pulls (e.g., `"168h"` for weekly).

**Adding a new MCP server**: Edit `dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl` and add secrets to each adapter's `mcp-secrets.json.tmpl` if needed.

When working with this repository, prefer:

- Editing existing files over creating new ones
- Testing changes before applying
- Following existing patterns and conventions
- Maintaining cross-platform compatibility where possible
