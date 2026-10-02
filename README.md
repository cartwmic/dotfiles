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
access to the item in 1Password; this repository does not create it. When the
RustDesk onchange helper runs on a supported personal desktop, it stops if the
item cannot be read. Confirm access before each personal desktop apply even
when unchanged inputs will skip the helper. Keep the token outside this repository.

The commands below are for a **fresh installation** and stop if a chezmoi
config already exists. On an existing host, preserve that config, inspect its
profile and hooks, and use the [preview/update path](#usage). Do not overwrite
it with an example.

The optional [example config](./example.chezmoi.yaml) includes a source-read
hook. On WSL it needs Windows 1Password CLI `op.exe` on PATH or a working `op`;
otherwise it stops before apply. Even dry-runs invoke configured source-read
hooks; see [hook preflight](./AGENTS.md#workflow). The minimal config below
omits that hook.

```bash
(
set -eu
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/chezmoi"
for existing in "$config_dir"/chezmoi.*; do
  if [ -e "$existing" ] || [ -L "$existing" ]; then
    printf 'Existing config or backup: %s; preserve it and follow Usage.\n' "$existing" >&2
    exit 1
  fi
done
config="$config_dir/chezmoi.yaml"
printf 'Desktop profile (personal or axon-work-computer): '
read -r profile
case "$profile" in
  personal|axon-work-computer) ;;
  *) printf 'Choose a supported desktop profile.\n' >&2; exit 1 ;;
esac
# Ubuntu/WSL needs zsh; modern macOS already provides it.
if [ "$(uname -s)" = Linux ]; then
  sudo apt-get update && sudo apt-get install -y zsh
  sudo chsh "$USER" -s /usr/bin/zsh
fi
mkdir -p "$(dirname "$config")"
printf 'data:\n  profile: "%s"\n' "$profile" > "$config"
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin" init --apply cartwmic
) && exec zsh
```

Complete the applicable [manual steps](#manual-steps) after installation.

### Termux (Android)

Termux is a first-class profile (`profile: "termux"`) — thin SSH jump host,
`.termux` UI config, and ntfy jump handlers. It does **not** install the full
desktop/agent stack. Basic SSH works in stock Termux. Notification jumping and
named-session helpers require the owner's custom signed Termux fork and matching
Termux:API/Boot apps. Preconfigured SSH aliases require the owner's private
network and provisioned keys. See [Termux setup](./termux/README.md) for app,
key, and host configuration before applying this profile.

This fresh-install block also refuses to replace an existing config:

```bash
(
set -eu
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/chezmoi"
for existing in "$config_dir"/chezmoi.*; do
  if [ -e "$existing" ] || [ -L "$existing" ]; then
    printf 'Existing config or backup: %s; preserve it and follow Usage.\n' "$existing" >&2
    exit 1
  fi
done
config="$config_dir/chezmoi.yaml"
pkg install -y chezmoi git openssh coreutils termux-api python vim
mkdir -p "$(dirname "$config")"
printf 'data:\n  profile: "termux"\n' > "$config"
chezmoi init --apply https://github.com/cartwmic/dotfiles.git
)
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

On `personal` macOS and native Ubuntu/Debian hosts, `mise run bootstrap`
installs RustDesk when missing. WSL and other profiles skip it. A chezmoi
onchange helper applies rendezvous, relay, server key, password approval, and
service settings when its tracked inputs change. Device identity and trust
data stay machine-local.

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

Author canonical harness-agnostic configuration in this repository:

- `dot_local/share/agent-harness/canonical/skills/`
- `dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl`

Chezmoi deploys these under `~/.local/share/agent-harness/canonical/`, rendering
`servers.json` from its template. Edit the repository sources; harness-specific
adapters project the deployed configuration into supported harnesses.

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

## Reading a streaming Pi session

Desktop Pi settings use regular mode on personal and work machines.
`/inspect-session` and **Ctrl+Alt+E** require fullscreen mode: change
`tuiMode` to `"fullscreen"` in the managed Pi settings template, apply the
settings after approval, and start a new Pi process. In fullscreen, they open
a read-only conversation snapshot in the configured external editor, even
during streaming. Closing it returns to the same session; editor changes are
discarded. System instructions, thinking, and abandoned branches are excluded.
Herdr's `prefix+e` remains the scrollback reader for non-Pi panes.

`/inspect-prompt` separately opens the assembled system prompt while Pi is
idle. See the [inspector guide](./dot_pi/private_agent/extensions/inspect-prompt/README.md)
for editor configuration and limits. `/inspect-session` depends on Pi 0.87.1's
private fullscreen layout and may refuse to open after an upgrade until the
reader is updated and revalidated. The isolated Pi/Herdr proofs pin Pi 0.87.1
and Herdr 0.9.1.

## Learnings monitor in Pi

The desktop-only Learnings monitor starts off. `/learnings on` enables a
read-only observer for the current saved Pi session; `/learnings flush` asks
it to catch up, `/learnings-review` opens local editable Markdown, and
`/learnings off` stops observation. Advice stays machine-local unless you
explicitly confirm promotion to Hindsight. It does not edit project files.
The observer can read any file accessible to your user without an extra
outside-workspace prompt. Inputs and read results can reach the selected model
provider; privacy filtering can miss secrets, and model spending has no
product-enforced cap. Review these limits before enabling it.

For work machines, install both the extension and Hindsight config, check the
effective bank in the environment that launches Pi, and restart Pi. Missing
settings or environment overrides can select personal bank `cartwmic`; there
is no runtime fail-closed guard. See the
[Learnings guide](./dot_pi/private_agent/extensions/learnings-monitor/README.md)
for configuration, review, promotion, and scripted-backend proofs. Termux
does not deploy the extension.

## Standing reminder in Pi

On desktop profiles, `/reminder` edits one current reminder for the saved Pi
session. Successful editor close activates it; canceled or failed edits leave
the prior value unchanged. Each operator message receives the value current
when Pi processes it, including queued steering. `/tree` keeps the session's
current value; `/fork` and `/clone` copy it into independent sessions. Selected
completed `ask_user_question` results refresh it by default; saved edits or clears
affect the next normal agent request. Unchanged ordinary tool continuations and
unselected extension-generated messages do not independently refresh it. No
control forces a request; transcript/history, private storage, session lifecycle,
and editor handoff rules remain unchanged.

The extension needs the source-managed input-origin runtime patch. Apply both
only after approval, then restart Pi. Its isolated proof currently pins Pi
0.99.2; rerun it after checking patch anchors on upgrades. See the
[extension guide](./dot_pi/private_agent/extensions/standing-reminder/README.md)
and [proof commands](./tests/standing-reminder/README.md). Termux excludes Pi.

## System One in Pi

The `personal` and `axon-work-computer` profiles include
[cartwmic/system-one-tools](https://github.com/cartwmic/system-one-tools)
as one Git package, not an npm package. Termux excludes `.pi`. The local
[System One directory](./dot_pi/private_agent/extensions/system-one/README.md)
is docs-only; there is no second loader. Source reconciliation is not deployment.
Native first-delivery targets are macOS, Pi 0.99.2+ and Node.js 22.19+;
the independent CLI retains Node.js 20+ and macOS/Linux support.

Pi owns native classifier providers and authentication. `/so settings` selects
a default provider/id independently of the chat model and CLI catalog;
`/so use` sets a session override, and `/so ask` selects for one private call.
Agent access starts off. `/so off` governs only `system_one`, not direct native
codemode classification; manual use remains available with separate accounting.
Each evaluation has one 30-second deadline and `maxRetries:2` per native HTTP
operation, not a global three-request cap. See the linked guide for native
object/choice/bool/score inputs and selection lifecycle.

Apply, package installation/update and paid provider tests require separate
approval. The Git URL is unpinned. The scoped
[agent guide](./dot_pi/private_agent/extensions/system-one/AGENTS.md) covers
isolated source checks and rollout. Rendering does not prove a provider call.

### Local Winnow (no API key)

[Winnow-12B](https://huggingface.co/EldanRing/Winnow-12B) is a local Jev-class
model that serves both System One and Pi's native classifier calls. One-time
setup and the catalog entry are in the
[winnow-local guide](./dot_pi/private_agent/extensions/winnow-local/README.md).
Launch it in a terminal you keep open, then check with `/winnow` in Pi:

```sh
cd ~/git/winnow-inference
python3 scripts/serve.py --profile apple-silicon --text-only --alias winnow-12b
```

Nothing starts it at login. It listens on `http://127.0.0.1:8091` and holds
about 13 GB of memory while running; Ctrl+C stops it.

## Herdr command palette

Both desktop profiles (`personal` and `axon-work-computer`) install
[vjeantet/herdr-palette](https://github.com/vjeantet/herdr-palette) **v0.2.2**
through `mise run install-herdr-palette`, also included in desktop bootstrap.
The task uses the normal upstream installer:

```sh
herdr plugin install vjeantet/herdr-palette --ref v0.2.2 --yes
```

It skips an already installed, enabled, runnable copy at that pin. Installation
uses a private nonexistent socket, leaving the running server untouched. After
applying the shared Herdr config, run `herdr server reload-config` to activate it.
Open with **Ctrl+B, Space**, type to search, Enter to select, and Esc to cancel.
Existing tab-navigation and pane-rename bindings stay intact. In Termux, swipe
up on **CTRL** to send that sequence; swipe up on **ALT** sends **Ctrl+O**.
Normal taps still act as modifiers.

The palette starts with upstream built-ins and installed plugin actions,
including Overview; no custom commands or prompts are configured. Its checkout,
binary and last-used state stay machine-local, outside chezmoi. Termux does not
install it; its prefix shortcut works over SSH to a configured desktop.

## Herdr overview and phone route

The personal and work desktop profiles pin Herdr **0.9.1 / protocol 22** and
link the source-managed overview plugin. The Pi adapter publishes a real-user
prompt and, when opted in, a separate recap after the response settles. The overview reads
native Herdr pane state and those supplied records. It does not parse a
transcript or generate a summary. Manual pane/tab labels remain under owner
control; workspaces are never auto-named. Herdr 0.9.1 has no atomic
conditional rename, so a manual edit can still race the final automatic write.

`prefix+shift+o` opens a responsive shared pane-canvas popup map; it creates no
background tab or pane ID. It is a temporary 100% native session-singleton;
modal `ui_busy` and owner-tab deletion/dismissal are native. Reopen normally
from a surviving pane; no startup/event/reconcile auto-open. Single-pane tabs combine beneath their workspace; multi-pane
tabs remain groups. Enter expands full names/recap; `d` opens the separate dated
digest; `n` selects the next blocked pane; `f` focuses the verified live target.
Stable current session/native subjects drive automatic names, not recap/digest
bodies. Latest-good recap, later failure, digest and live agent state stay distinct.
See the [Herdr plugin guide](./dot_local/share/herdr-overview/README.md) for
navigation, manual pane-source recaps, naming policy, and move behavior. The
[Pi adapter guide](./dot_pi/private_agent/extensions/herdr-overview/README.md)
covers publication.

The `install-herdr-overview` mise task (also part of desktop bootstrap)
verifies Herdr 0.9.1 and links/enables the source manifest. Linking leaves the
running server untouched. On a compatible running server,
`herdr plugin action invoke overview.reconcile --plugin overview` loads the
linked action and reconciles without opening a view. Invoke `overview.open`
separately for the popup.
`herdr server reload-config` separately applies the new keybinding. A later
owner-controlled server start also runs the plugin's startup hook.

On Android, Termux remains the phone-owned `termux` chezmoi profile and an SSH
client. It does not install the native Herdr plugin. From the phone, run
`ssh macbook`, then `herdr` in the desktop shell to attach to that same session.
The map adapts to the actual phone PTY width; shrinking a local terminal is
not phone proof. The combined isolated `map_journey.py --scenario all` checks
interactions and real Pi identity/publication together; use its private pinned
pyte interpreter. Physical phone and live rollout remain owner-pending; no
physical-phone popup receipt is claimed. See [Termux phone setup](./termux/README.md) for
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
run_onchange_after_10_mise_bootstrap.sh.tmpl # Installs tools after mise is available
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

- [gvm users] Follow [gvm's installation and platform prerequisites](https://github.com/moovweb/gvm#installing), then load it and install a Go version before selecting a default. See the sequence below.
- [macOS] Add XQuartz as a login item.
- [personal macOS] Launch Docker Desktop once to accept its license and finish setup. See [Docker Provisioning](#docker-provisioning).
- [personal macOS] Log in and launch RustDesk once on a fresh machine; grant Accessibility, Screen Recording, and, if needed, Input Monitoring permissions. See [RustDesk Provisioning](#rustdesk-provisioning).
- [desktop Herdr] On an existing compatible server, invoke the overview reconcile action after linking; otherwise use a later owner-controlled server start. Reload config only to pick up the keybinding. See [Herdr overview and phone route](#herdr-overview-and-phone-route) for commands.
- [recap users] Set a host-local recap command; opt in to automatic Pi publication if wanted. See [Portable recaps](#portable-recaps).

After installing gvm, use a fresh zsh or load its script in the current shell.
Select a supported version from `gvm listall` when prompted:

```sh
source "$HOME/.gvm/scripts/gvm"
gvm listall
printf 'Go version to install (from the list above): '
read -r GO_VERSION
gvm install "$GO_VERSION" && gvm use "$GO_VERSION" --default
```

See [AGENTS.md](./AGENTS.md) for repository agent instructions (not deployed).
See [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl) for Pi-global agent instructions.

Herdr Overview uses bordered, padded, word-wrapped cards in native workspace
order, with two singleton columns and separate multi-pane groups. `M` marks
manual names; headings show counts; clipped collapsed titles end in an ellipsis.
`d` enters the dated digest (idempotent there); Esc restores the prior recap
passage and `q` dismisses immediately. The card floor is actual popup width 32,
not outer width: outer 40/48/120/180 yield 38/46/92/152; outer32 yields30 and
may clip. Simultaneously attached clients share one PTY geometry; a wide peer
can clip the narrow peer. Use one attached client for readable geometry.
