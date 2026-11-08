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
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin" init cartwmic
)
```

Then add the local data keys your profile needs to the `data:` block of `~/.config/chezmoi/chezmoi.yaml`. A missing key stops apply and names it; the list is in [Local data keys](./docs/profiles.md#local-data-keys). Then run `"$HOME/.local/bin/chezmoi" apply`, then `exec zsh`.

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
chezmoi init https://github.com/cartwmic/dotfiles.git
)
```

Then add these keys to the `data:` block of `~/.config/chezmoi/chezmoi.yaml`: `sshHosts.server`, `sshHosts.laptop`, `sshHosts.macbook`, `sshHosts.macKvm`, `sshHosts.whonixGw` and `sshHosts.whonixWs`, each with `address` and `user` (the list is in [Local data keys](./docs/profiles.md#local-data-keys)). A missing key stops apply and names it. Then run `chezmoi apply`.

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

- Pi coding agent, claude, claude-code-acp, mistral-vibe, mermaid-cli
- Herdr (pinned) with the upstream command palette plugin on `personal` and `axon-work-computer`
- Portable `session-recap` and `passage-review` workflows; Termux stays an SSH client.
- [QMD](./docs/qmd.md) (`personal` and `axon-work-computer`): local keyword and semantic search over notes, repo docs, Pi recaps and Pi, Claude Code and Codex sessions; pinned install, collections, one agent skill, `qmd` on PATH for every shell, and an hourly refresh on macOS (launchd; interval and on/off in chezmoi data `qmd.refresh`) that runs `qmd cleanup` once a day (`qmd.refresh.cleanup`).
- `workstream-rank of [--pane P]` prints a pane's priority (lower is more important; 1000 = unranked) from the coordinator's published `~/.local/share/coordinator/rank` (or `$WORKSTREAM_RANK_FILE`); `workstream-rank show` prints the stack. It never errors on a missing or corrupt file.
- [`run-and-wake -- CMD`](./docs/run-and-wake.md) runs a job detached (for example `run-and-wake -- heavy-gate --wait 7200 -- CMD`) and, when it exits, sends one tagged `herdr agent prompt` to the Pi session that started it, so a worker can end its turn instead of polling. One log record set per job in `~/.local/state/run-and-wake/log.jsonl`.
- `git-worktree-reap [--dry-run] [--min-age HOURS] [REPO]` (`personal` and `axon-work-computer`): after a merge, removes the repo's worktrees whose branch is merged (HEAD in `origin/main`, or, with `gh`, its PR merged with the branch tip as the PR head, which covers squash merges), that no process has open (`lsof +D`) and that have no modifications (`git worktree remove`, never `--force`). A worktree with no commits of its own (or a fast-forward-merged branch, which looks the same) is kept until it is older than `--min-age` hours (default 24). One line per worktree: `removed`, `would remove` or `kept` with the reason. Removing a worktree also deletes its gitignored files (a local `.env`, `node_modules`); untracked files keep it (`kept: has modifications`). It never touches the main checkout and keeps every branch ref.

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
~/.local/user_scripts/sync_harness_skills.sh --prune      # also delete unmanaged leftovers
```

Behavior:

- Skills are linked into harness skill directories from the canonical `SKILL.md` bundles.
- `sync_harness_skills.sh` deploys canonical skills with chezmoi (rendered names and contents), showing additions and content changes before applying. It lists orphan skills and leftover files chezmoi does not manage, and deletes them only with `--prune`.
- Claude MCP is generated as a managed setup script and applied through the Claude CLI when available.
- Codex MCP is rendered into a managed block inside `~/.codex/config.toml`.
- Canonical MCP entries are authored in `dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl`.

Notes:

- Harness-specific MCP secrets can be mapped in adapter metadata under `~/.local/share/agent-harness/adapters/<harness>/mcp-secrets.json`.
- Secret-backed adapter metadata is resolved through the 1Password CLI via `op read`.
- Harness instruction files are hand-maintained and split: repo [AGENTS.md](./AGENTS.md) (chezmoi source, not deployed), Pi-global [dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl) (`~/.pi/agent/AGENTS.md`). Claude still uses `~/.claude/CLAUDE.md`; Codex still uses `~/.codex/AGENTS.md`.

## Pi settings (`~/.pi/agent/settings.json`)

Pi rewrites this file itself (the changelog version, the theme, a model or thinking-level choice, `pi install` adding a package). It used to be
rendered whole from a template, so every such write was a local edit of a full-file target and the next `chezmoi update` stopped on it with
exit 1 and no TTY (work Mac, dogfood log E16). It is now a `modify_` script
(`dot_pi/private_agent/modify_private_settings.json.tmpl`) that merges what this repository wants (`.chezmoitemplates/pi_settings_desired`)
into whatever is on disk, and never collides:

| Policy | Keys |
|---|---|
| owned, set on every apply | `defaultProvider`, `defaultModel`, `tuiMode`, `defaultTools`, `codemode`, `compaction`, and on the work profile `subagents` |
| seeded, set only while absent (a choice made in Pi is kept) | `defaultThinkingLevel`, `theme`, `hideThinkingBlock`, `lastChangelogVersion`, and each `modelThinkingLevels` entry on its own |
| unioned (ours first, yours kept) | `packages` (an entry of ours replaces yours with the same source, so a pin bump arrives), `enabledModels` |
| untouched | everything else, including `deviceId` and any key a newer Pi adds |

To change a seeded default on a machine that already has it, change it in Pi (or edit the file); the source value only reaches a machine that has none.
A package or model removed from the source stays on machines that already have it (remove it in Pi), and a package written under another form of the same address (`git:github.com/x/y` and `https://github.com/x/y`) counts as a different entry.
Tests: `tests/pi-settings-modify` and `tests/pi-settings-render` (the desired-state template).

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
no custom commands or prompts are configured. Its checkout,
binary and last-used state stay machine-local, outside chezmoi. Termux does not
install it; its prefix shortcut works over SSH to a configured desktop.

## Herdr and phone route

The personal and work desktop profiles pin one Herdr release. Termux is an SSH
client: from the phone, `ssh macbook`, then `herdr` to attach to the desktop's
running session. The phone installs no Herdr plugin, server, or desktop config.
See [Termux phone setup](./termux/README.md).

The opt-in [Herdr control MCP tunnel](./herdr-mcp/README.md) lets a ChatGPT
custom app control local Herdr through an OpenAI Secure MCP Tunnel. Chezmoi
never deploys it; install it explicitly with `herdr-mcp/install.sh`.

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
executable argv for manual recaps; the editable prompt templates and local
configuration are covered in [`dot_local/share/session-recap/README.md`](./dot_local/share/session-recap/README.md).

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

## T3 hub providers (personal Mac)

**Retired 2026-11-03.** `t3Hub.enabled` now defaults to `false` in `.chezmoidata.toml`, so the next apply removes the
`claude-hub` and `codex-hub` test instances, the Claude settings file for `claude-hub` and (while `hub.enabled` is off) the
`[model_providers.cliproxy]` block. The code stays: set `t3Hub.enabled` to `true` under `data:` to bring them back. What follows
describes them while on.

Two extra provider instances in T3 Code send their traffic through the homelab CLIProxy hub
(`https://cliproxy.internal.cartwmic.com`, home LAN or WireGuard): `claude-hub` ("Claude (hub)") and
`codex-hub` ("Codex (hub)"). They exist on the personal profile on macOS only. `dot_t3/private_userdata/modify_settings.json.tmpl`
adds exactly those two ids to `~/.t3/userdata/settings.json` and leaves every other key and instance alone. Keys are read
at run time from 1Password (`op_read_cached.sh`): Claude through the `apiKeyHelper` in
`~/.config/t3-hub-claude-settings.json`, Codex through a `[model_providers.cliproxy]` block that
`dot_codex/modify_private_config.toml.tmpl` appends to `~/.codex/config.toml` (this switch leaves the default provider alone; the
instance selects it with `-c model_provider=cliproxy`). `codex-hub` is not managed, so it keeps `~/.codex` as its home and
uses T3's downloaded Codex binary; the path is written at apply time from `~/.t3/tools/codex/active.json`, so re-apply after
T3 updates its Codex. A re-apply also puts back these two instances if they were edited in the T3 UI; other instances are never touched.

The apply targets are exactly `~/.t3/userdata/settings.json`, `~/.config/t3-hub-claude-settings.json` and
`~/.codex/config.toml` (chezmoi can only target a path whose parent directory exists, so the Claude file is not in its own folder).

**Rollback.** Set `t3Hub.enabled` to `false` under `data:` in `~/.config/chezmoi/chezmoi.yaml` (the default in
`.chezmoidata.toml` is `false`) and apply those three targets. That removes both ids, strips the Codex block and deletes
the Claude settings file (a managed file that renders empty is removed). Everything else in those files stays byte for byte.
Delete the sources afterwards if you want them gone for good. Reverting the commit alone does not remove anything: chezmoi
stops managing the paths, so set the switch first.

Tests: `python3 -m unittest discover -s tests/t3-hub` (the apply tests run on macOS only).

## CLIProxy hub as the default (personal Mac)

Every Claude Code and Codex session on the personal Mac goes through the homelab CLIProxyAPI hub (`https://cliproxy.internal.cartwmic.com`,
reachable only from home): T3 threads, the coordinator, subagents, terminal sessions and scripts. One switch, `hub.enabled` (default `true`
in `.chezmoidata.toml`), drives three files, all on the personal profile on macOS only. The work profile is left out: Michael scoped this to
his personal machine, and the hub is not reachable from the work network.

| File | With the switch on | Source |
|---|---|---|
| `~/.claude/settings.json` | `env.ANTHROPIC_BASE_URL` = the hub (no `/v1`) and `apiKeyHelper` = `op_read_cached.sh` on the hub key. `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_API_KEY` are not set: either would outrank the helper. | `dot_claude/modify_settings.json.tmpl` |
| `~/.codex/config.toml` | top-level `model_provider = "cliproxy"` (the `[model_providers.cliproxy]` block it names is kept while either switch is on). | `dot_codex/modify_private_config.toml.tmpl` |
| `~/.t3/userdata/settings.json` | the T3 `codex` instance, which is managed and so ignores `~/.codex`, becomes `setupMode: existing` with T3's downloaded Codex binary (from `~/.t3/tools/codex/active.json`). Its config is left alone when that file is missing. `displayName` is set on `claudeAgent` ("Claude"), `coordinator` ("Claude (coordinator)") and `codex` ("Codex"); no other field of `claudeAgent` or `coordinator` changes (the coordinator repo owns its launchArgs). T3's Usage page reads the hub through `usageLimitSources.cliproxy-hub` (below). | `dot_t3/private_userdata/modify_settings.json.tmpl` |

**Rollback.** Set `hub.enabled` to `false` under `data:` in `~/.config/chezmoi/chezmoi.yaml`, then apply the three targets
(`chezmoi apply ~/.claude/settings.json ~/.codex/config.toml ~/.t3/userdata/settings.json`). Each file loses only what it was given:
the Claude URL only if it equals the hub URL, the helper only if it equals ours, `model_provider` only if it equals `"cliproxy"`, and the
`codex` instance goes back to `{"driver":"codex","enabled":true,"config":{"setupMode":"managed"}}` only while it still looks like ours (so an
entry edited by hand is kept). Other env keys, a different helper and every other key stay. Reverting the commit alone would leave the keys
behind, because the scripts would no longer remove them, so the switch stays in the templates. Re-apply after T3 updates its Codex.

**T3 usage from the hub.** Since the switch, T3 can no longer read Claude usage through the claude.ai sign-in. T3 has a built-in
CLIProxyAPI usage source (`docs/user/usage.md` in pingdotgg/t3code, "Connect a CLIProxyAPI hub"; schema in `packages/contracts/src/settings.ts`).
With the switch on, the apply reads the management key (`op://developer/tb36gtnaocyezjk3dslomp64he/management`) with
`~/.local/user_scripts/op_read_cached.sh`, which uses only the service-account token, and writes it as a literal string into
`usageLimitSources.cliproxy-hub.managementKey` (url = the hub, `enabled: true`). T3 moves a literal into its own secret store
(`~/.t3/userdata/secrets`) and leaves a placeholder in `settings.json`, so each apply sets it again. A 1Password reference there
would make T3 run `op` through the desktop app and prompt for unlock, so none is written, and the `secretProviders.onepassword` entry
that #158 added is removed when it still equals that one. If the read fails or does not return a `cpa_` key, the entry is left as it
is and `[modify_settings] WARN` goes to stderr. Switch-off removes the source (and the three displayNames) only while its kind,
label and url are ours.

`t3Hub.enabled` ([T3 hub providers](#t3-hub-providers-personal-mac)) is independent: it only owns the two retired test instances and the Claude
settings file for `claude-hub`.

The old `update_claude_settings.sh` and `reset_claude_settings.sh` (z.ai token and URL) are retired and removed from the personal Mac by
`.chezmoiremove`, with their shell aliases: they wrote `ANTHROPIC_AUTH_TOKEN` or deleted `ANTHROPIC_BASE_URL`, which fights `hub.enabled`.

Tests: `python3 -m unittest discover -s tests/hub -v` (the real-apply tests run on macOS only).

## Instances (Coordinator and Retro daemons)

One opt-in flag per instance in the local `~/.config/chezmoi/chezmoi.yaml` (not in git). Applying does everything: directories, first-time config, the LaunchAgent, and the start. Removing the flag stops the daemon. Design: the coordinator's `DESIGN.md` addendum (decisions G1 to G5); procedure of record per repo: the coordinator's `docs/deploy.md`, Retro's `docs/DEPLOY.md`.

```yaml
data:
  instances:
    coordinator:
      enabled: true               # absent or false: off
      repo: /path/to/coordinator  # default: /Volumes/Workshop/macbook/git/coordinator (personal), ~/coordinator-work (work profile)
    retro:
      enabled: true               # the go-live: Discord and model spend (see Retro's docs/LIVE.md). Ships off.
      repo: /path/to/retro        # default: /Volumes/Workshop/macbook/git/retro (personal), ~/git/retro (work)
      channelId: "<#retro channel id>"   # first-time config only
      opItem: op://VAULT/ITEM/bot_token  # first-time config only; a reference, never the token
```

How it works:

- The units are installed on macOS only: `local.coordinatord` and `local.retrod` on the personal profile, `local.coordinatord.work` (the Matrix coordinator) on `axon-work-computer`. Work Retro is a later change. Dotfiles never clones. The checkout must exist at `repo`; otherwise the instance is NOT READY and the apply says what is missing.
- chezmoi manages each unit only as an inert copy in `~/.local/share/instances/launchd/`. `~/.local/user_scripts/instances_reconcile.sh` (run by `run_after_75_instances_reconcile.sh.tmpl` on every apply) copies it into `~/Library/LaunchAgents` only when the instance is ready, then starts it. A file there would be loaded at next login, so a half-configured instance never gets one.
- Every apply prints one status line per instance and the script always exits 0: `READY (started | running | adopted | reloaded)`, `NOT READY: <what>`, `STOP FAILED`, `RELOAD FAILED`. A not-ready instance is retried by the next apply. The last status of an opted-in instance is also kept in `~/.local/state/instances/<name>.status`; an instance that never opted in writes no state, and opt-out removes it.
- On **both desktop profiles**, when `<repo>/src/t3-hook/hook.ts` exists at apply time, `~/.claude/settings.json` also gets the coordinator's T3 hook (`dot_claude/modify_settings.json.tmpl`, following the Settings snippet in the coordinator's `src/t3-hook/README.md`). Each profile runs its own coordinator: **personal** uses `instances.coordinator.repo` (else the personal default) with `COORDINATOR_STATE_DIR=$HOME/.local/share/coordinator`; **axon-work-computer** uses `instances.coordinator.repo` (else `$HOME/coordinator-work`) with `$HOME/.local/share/coordinator-work`. The `enabled` flag is not read, so a daemon installed outside the flag gets the hook without chezmoi managing its unit. Entries: PreToolUse, PostToolUse and PostToolUseFailure on the six gated T3 tools (each ends `|| exit 2`); SessionStart (does nothing outside a T3 session); when `hook.ts` imports `./ask-gate.ts`, a PreToolUse entry on `^AskUserQuestion$` without `|| exit 2`; when it contains `--of`, three SessionStart rules groups (`--part rules --page N --of 3`, each its own context budget), or one bare `--part rules` group when it has only `--part`. If the file is missing, or on termux, an apply removes exactly those entries and leaves other hooks alone. Applying on the work Mac needs Michael's own confirmation. Tests: `python3 -m unittest discover -s tests/t3-hook -v`.
- On the **personal** profile on macOS the CLIProxy hub is the default of Claude Code and Codex; see [CLIProxy hub as the default](#cliproxy-hub-as-the-default-personal-mac).
- First-time config runs when the instance has no config yet (and again if an earlier run did not finish), from the repo's own script (exit 0 ready, exit 3 with `NOT-READY: <what>` not ready yet). Nothing secret is read or stored by dotfiles.
- **An apply never restarts a loaded service.** The only `launchctl` calls are: `print` (read-only, once per enabled or started instance), `bootstrap` of an instance that is not loaded, `bootout` on opt-out or a reload you asked for (a reload also polls `print` until launchd has dropped the job, then retries a failed `bootstrap`; see `~/.local/share/launchd-reload/launchd_reload.sh`, the one helper that scripts 71, 72 and this one share). A changed unit on a running daemon is reported ("NOT restarted"); reload on purpose with `INSTANCES_RELOAD=coordinator chezmoi apply` (or `retro`, or `all`).
- **The coordinator upgrades itself after a pull.** Both profiles run the same coordinator code. When a pull of its checkout changes `src/`, `package.json` or `package-lock.json`, the daemon runs `npm ci` if the lockfile changed, backs up the ledger before a schema change, and exits 75; launchd restarts it (`KeepAlive` on a non-zero exit). An apply still never restarts a loaded service, and the launchd unit does not change. `coordinator config set self_restart off` turns the self-restart off. Dotfiles does not pull the checkout.
- A service that is already running when you first set `enabled: true` (this Mac's coordinator) is adopted: one `print`, the daemon is not touched, and the installed unit is only rewritten if it differs from the managed one (then reported, not reloaded). With no flag on a Mac that never opted in, an apply makes no `launchctl` call at all.
- Opt-out (flag false or removed) acts only on an instance dotfiles started or adopted (ownership is recorded before the unit is installed, so a failed start is cleaned up too). It boots the daemon out and removes the unit file; state, config, tokens, playbooks and logs are kept. The Pi pane keeps running (change `PANE_NOTE` and the opt-out branch in the script if that should change).

### The work Mac (`axon-work-computer`)

The work profile runs one instance, the Matrix coordinator (`cartwmic/coordinator`, `docs/work-instance.md`). Its flag is the same `instances.coordinator.enabled`; the profile picks the variant (instance name `coordinator-work`: unit `local.coordinatord.work`, state `~/.local/share/coordinator-work`, logs `~/Library/Logs/coordinator-work`). `retro` data is ignored on this profile.

```yaml
data:
  profile: axon-work-computer
  instances:
    coordinator:
      enabled: true                       # absent or false: off. Ships off.
      repo: /Users/you/coordinator-work   # ABSOLUTE path of your checkout; default ~/coordinator-work
      # extraPath: /opt/node/bin:/opt/herdr/bin   # optional: only if the live unit's PATH starts with tool directories (see below)
```

- **A Mac set up by hand** (the coordinator's `scripts/work-instance-setup.sh` already ran): the config, token file and playbook exist and the daemon runs. Apply once with the flag **off**: it only lays down the inert unit and prints `coordinator-work: not opted in` (no `launchctl` call). Compare it with the live file: `diff ~/.local/share/instances/launchd/local.coordinatord.work.plist ~/Library/LaunchAgents/local.coordinatord.work.plist`. It should be identical (the rendered unit equals what the setup script installs). If the program path and `WorkingDirectory` differ, set `repo` to the checkout the live unit uses; if only the start of `PATH` differs, set `extraPath` to that prefix (no trailing colon). Then set the flag and apply: one `launchctl print`, and the running daemon is **adopted, not restarted**. A unit that still differs is rewritten on disk and reported (`NOT restarted`); reload on purpose with `INSTANCES_RELOAD=coordinator-work chezmoi apply`.
- **A rebuilt Mac** (no config yet): with the flag on, apply runs the coordinator's `scripts/work-instance-setup.sh --yes-this-is-the-work-computer --config-only --rev <HEAD of the checkout> --state-dir ~/.local/share/coordinator-work` once, with `agent-alert`'s directory on its PATH for that run only. That needs the setup script to support `--config-only` and the exit contract of the instance scripts (exit 0 ready; exit 3 not ready yet, with `NOT-READY: <what>` on stdout, for example the owner has not joined the room; any other exit a failure, whose `[FAIL]` line is shown). Until the coordinator repo has `--config-only` the apply ends `NOT READY: setup script ... failed ... Unknown option --config-only` and installs and starts nothing: run the coordinator's handoff by hand, **verify it succeeded**, delete the stale marker of the failed seed (`rm ~/.local/state/instances/coordinator-work.configuring`; it exists so a half config from a failed seed is never trusted), then set the flag (adoption, above).
- `op`, a signed-in Pi, the 1Password Developer vault and every secret belong to the setup script. Dotfiles reads and prints none.
- `docs/work-mac/work-mac-instances.sh` does the "A Mac set up by hand" steps for you (preflight, local data with a backup, the limited apply, the live-unit comparison, and with `--enable` the adoption). It reads the checkout and `extraPath` from the live unit when they are not set. See `docs/work-mac/README.md`.

Tests: `python3 -m unittest discover -s tests/instances -v` (renders against golden units, the work unit against what the coordinator's setup script installs, the reconcile script against a stub `launchctl` with exact call lists, and a scratch-HOME `chezmoi apply` on macOS). `python3 tests/instances/mutate.py` checks the suite catches deliberate breaks of the safety rules, the work variant and the files that feed the script.

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
private_dot_zshrc.tmpl           # Zsh configuration
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

## Updating a machine: `dotfiles-update`

`dotfiles-update` (deployed to `~/.local/bin` on both desktop profiles) is the one command that brings a machine up to date, with no TTY.
Plain `chezmoi update` stops with exit 1 at the first file that was edited on the machine and that the source also wants to change
("has changed since chezmoi last wrote it?", then "could not open a new TTY"), and applies nothing past it. This command instead pulls the
source and decides each pending path from chezmoi's own record of what it last wrote (`chezmoi state dump`), never from a status code
(`chezmoi status` shows a blank first column for a path chezmoi never recorded even when a different file is already there, and shows
only the directory itself for a directory it would remove). **It applies a path only when that loses nothing, and holds everything else:**

| The pending path | What `dotfiles-update` does |
|---|---|
| does not exist here (a new file) | applies it |
| exactly what chezmoi last wrote (same type, bytes and permissions) | applies it |
| a directory that stays a directory | applies it as itself, never its contents |
| a directory the source drops, every file in it unedited chezmoi work | applies it (removes it) |
| edited here, or a file chezmoi never wrote is in the way, or you deleted it here | HOLDS it, with the reason and what an apply would add and remove |
| a directory the source drops that holds files chezmoi did not write (even a `.DS_Store`), a different case spelling, a symlinked parent | HOLDS it |
| a new file inside a directory that is held (for example one you deleted) | waits, listed as such; it is applied right after that directory when you `--take-source` it |
| a path the source REMOVES (`.chezmoiremove`, `remove_`, an `exact_` directory's extras) that is edited here or was never written by chezmoi | HOLDS it ("the source removes it, apply would delete it") |
| a git-repo external (`.chezmoiexternal.toml`, `type = "git-repo"`) | refreshed by name with the `git pull` its definition sets (this repo's uses `--ff-only`) when its `refreshPeriod` is due; `chezmoi status` never lists one. A failed pull prints git's last lines and exits 1 |
| `--take-source` on a path inside a held directory whose directory is not taken in the same run | stays held, and says so (its parent would be missing) |
| `run_` scripts | run only when nothing is held (a script may depend on a held-back path); a script that fails has the end of its output printed and recorded |

What it prints, every time:
- `source at <sha>, was <sha>`: the source checkout's commit after the pull and before it (`(no new commits)` when they are equal).
- Each `run_` script that ran, with its exit code: `script 65_agent_kit_install.sh   exit 0   (its output says: ...)`. The note shows the first
  output lines that say warn, error or fail (any case, so a harmless "0 failed" is flagged too), because a script can exit 0 while failing inside (the agent-kit install did). A script that exits
  non-zero stops the run: it is named with its code and `dotfiles-update` exits 1. (`chezmoi apply --verbose` shows neither. Each due script is run by chezmoi on its own, `chezmoi apply --include=scripts PATH`, into its own file, so chezmoi keeps its normal run record and nothing a script prints is ever parsed; the exit code is read from chezmoi's own last line.)
- `nothing to update.` when no file or changed script is pending. `chezmoi status` still lists every `run_after_` script after every apply (they run on
  every apply by design, for example `75_instances_reconcile.sh`); that is not a pending change, so it says `clean: N always-run script(s)` and why,
  and still runs them as `chezmoi apply` would.
- A record of every real run (not `--dry-run`): one JSON line in `~/.local/state/dotfiles-update/log.jsonl` with the source commits, what was applied, taken (and
  where your copy was saved), kept, held (with the reason), waiting, the scripts with their exit codes, and the exit code.

Exit 0: everything applied. Exit 3: something is held and needs a decision (the list is printed). Exit 1: the pull, a read or an apply failed.
Decide each held path with a flag, no prompts, then run it again: `--take-source PATH` saves your copy under
`~/.local/state/dotfiles-update/<UTC time>/` and applies the source version of that path; `--keep-local PATH` leaves it as it is for now
(it is listed again next run). There is no "take everything" flag. `--dry-run` reports only; `--no-pull` skips the pull.
A machine whose files chezmoi never recorded (a fresh state, or paths applied before chezmoi tracked them) holds every pending path that already
exists, because nothing proves it is chezmoi's own; settle each once. A `modify_` target that an app has rewritten (Claude or Codex settings) is held on a source
change for the same reason, until you take or keep it.
First install on a machine that has not got it yet (for example the work Mac, where `chezmoi update` already fails): `chezmoi update --apply=false`
then `chezmoi apply ~/.local/bin/dotfiles-update`, and from then on `dotfiles-update`.
Like `chezmoi apply`, it also deletes unmanaged files inside an `exact_` directory only when every one of them is unedited chezmoi work, and a `run_` script's output is shown when it fails (its last 15 lines).
Known limits: when a script template does not render, `chezmoi status` fails, so nothing is applied and it exits 1 with chezmoi's error (plain `chezmoi apply` would apply the files and run the earlier scripts first). `run_before_` scripts run after the files and the `run_after_` scripts, not before the files as plain `chezmoi apply` orders them (none exist in this repo). And when the source turns a plain file into a directory, `chezmoi status` itself fails (`.foo/bar: not a directory`), so `dotfiles-update` prints that error, applies nothing and exits 1. Look at the path with `chezmoi diff PATH`, then `chezmoi apply PATH` it yourself.
To keep a local edit for good, adopt it: `chezmoi re-add PATH` (plain files) or change the template.
Tests: `tests/dotfiles-update` (real chezmoi, scratch repository and HOME; the red control is plain `chezmoi apply` failing in the same state).

## Docs map

Start here for machine setup and user workflows. For work in this source tree,
read [AGENTS.md](./AGENTS.md); it links the component-local agent guides
and controls apply. Pi's global instructions are a separate source file at
[dot_pi/private_agent/literal_AGENTS.md.tmpl](./dot_pi/private_agent/literal_AGENTS.md.tmpl).
Component READMEs cover setup and use:

- [Termux and phone SSH](./termux/README.md)
- [session-recap](./dot_local/share/session-recap/README.md)
- [QMD search](./docs/qmd.md)
- [passage-review](./dot_local/share/passage-review/README.md) and its [Pi `/review` entry point](./dot_pi/private_agent/extensions/passage-review/README.md)
- [Pi extensions](./dot_pi/private_agent/extensions/README.md) (index for the other extension guides)
- [Harness skills and MCP](./dot_local/share/agent-harness/README.md), [Pi patches](./dot_local/share/pi-patches/README.md), [Neovim](./dot_config/nvim/README.md), and [Zellij](./dot_config/zellij/README.md)

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
- [macOS] Run `agent-chrome` to start the agent browser, then sign in to each site once. See [Agent browser](./dot_local/share/agent-harness/README.md#agent-browser).
- [recap users] Set a host-local CLI command for standalone recaps/Herdr groups if wanted. See [Portable recaps](#portable-recaps).

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
