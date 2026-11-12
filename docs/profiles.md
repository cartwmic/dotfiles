# Profile coverage

Chezmoi deploys every file to every profile unless `.chezmoiignore` leaves it out. A dotfiles feature targets both desktop profiles, `personal` and `axon-work-computer`, unless its design says in one line why one is left out (rule in [AGENTS.md](../AGENTS.md)).

The table lists every path that `chezmoi managed` gives to one desktop profile and not the other, with the reason. `tests/profiles/test_coverage.py` keeps it current. It fails when a one-profile path has no row, or when a row names a path that is not one-profile any more. Rows marked `reason needed (owner)` pass; the test prints how many there are.

How to read a row:

- A path covers itself and everything under it.
- `(macOS)` in the profiles column: the gate also needs `.chezmoi.os == "darwin"`; `(Linux)`: it also needs `.chezmoi.os == "linux"`. The CI job on the other OS skips those rows; the job on the matching OS checks them.
- Termux is out of scope here; it has its own block in `.chezmoiignore`.
- Not covered: profile branches inside templates (`{{ if eq .profile ... }}` in about two dozen templates) and run scripts that skip themselves by profile, such as `60_configure_rustdesk.sh`. The PR body's `Profiles:` line covers those. The T3 hook in `~/.claude/settings.json` is one of them: it lands on both profiles (each with its own coordinator repo and state dir), so it needs no row.

| Path or feature | Profiles | Reason the other profile is left out |
|---|---|---|
| `05_provision_ssh_keys.sh` | personal | The homelab SSH credential is personal infrastructure and must not land on a work machine. (Termux gets it too.) |
| `Library/LaunchAgents/local.agent-events.plist`, `70_agent_events_launchd.sh` | personal (macOS) | Gated on the `agentEvents.enabled` setting, which defaults on only on personal, so the work Mac sends no metrics until that setting is turned on there. |
| `.local/share/instances/launchd/local.coordinatord.plist` | personal (macOS) | The work profile runs its own coordinator unit, `local.coordinatord.work.plist` (row below). |
| `.local/share/instances/launchd/local.retrod.plist` | personal (macOS) | Work Retro is a later change (README, "Instances"). |
| `.local/share/instances/launchd/local.coordinatord.work.plist` | axon-work-computer (macOS) | The work coordinator's unit (Matrix); personal runs `local.coordinatord.plist`. |
| `.pi/agent/extensions/pi-codex-fast.json` | personal | Codex Fast is configured only in personal Pi settings. |
| `.pi/agent/extensions/auto-session-name.json` | personal | Session titles use the personal Codex login. |
| `.local/user_scripts/loop_engine_bump.py` | personal | It merges the Loop Engine bump PR and applies it on the machine it runs on, and it does so without asking, while an agent applies on the work Mac only with Michael's confirmation for that action, so it is left out there. The work Mac takes the merged pins and skills with the owner's own `chezmoi update`. |
| `65_agent_kit_install.sh`, `.local/user_scripts/agent_kit_bump.py` | personal | Gated on the `agentKit.enabled` setting, which defaults on only on personal. The install is `npm ci` of a private GitHub Packages package. It needs a gh account that can read the package: the script uses `NODE_AUTH_TOKEN` if set, else tries every logged-in gh account (the active one first) against the registry and uses the first that can; a failed install keeps the previous `node_modules`, prints an ERROR naming the accounts tried and exits 1. Without the setting the work Mac gets the `agent-traces` wrapper (it exits 3) and the pin files but no install until that setting is turned on there (owner's call). The bump script only serves that install. |
| `.local/user_scripts/configure_rustdesk.sh` | personal | The homelab remote-access setup and its personal vault item do not belong on the work Mac. |
| `.pi/agent/extensions/openrouter-gate` | personal | The work profile keeps its own OpenRouter posture, not the personal setup. |
| `.pi/agent/extensions/claude-compat-guard` | personal | It rides on the personal Claude login; work uses its own provider. |
| `.config/kgate/host` | personal | The address of the personal homelab Kubernetes cluster, which the work Mac has no business reaching. The `kgate` binary itself (`.local/bin/kgate`) lands on both profiles. |
| `.config/kgate/profiles` | axon-work-computer | The kgate profiles for the Axon KC2 cluster (`cluster = "kc2"`). The personal Mac gets no KC2 profile and no `~/.kube/kgate-cluster`, so kgate there cannot reach KC2. |
| `80_spotlight_off_workshop.sh` | personal | `/Volumes/Workshop` exists only on the personal Mac; the work Mac has no such volume. |
| `.config/agent-scratch`, `81_agent_scratch_workshop.sh`, `.local/user_scripts/agent_tmp_move.py`, `.local/share/agent-scratch` | personal (macOS) | `/Volumes/Workshop` exists only on the personal Mac; the work Mac and the Linux and WSL hosts have no such volume. The one line in `dot_zshenv` that sources the env file does nothing without it. |
| `.t3`, `.config/t3-hub-claude-settings.json` | personal (macOS) | The T3 `claude-hub` and `codex-hub` provider instances route through the homelab CLIProxy hub, which is reachable only from the home LAN or WireGuard, and Michael scoped them to his personal Mac. Linux and WSL personal hosts do not get them; personal Linux does get the settings file `.t3` without the hub (it sets only `worktreesDirectory`, to `~/t3-worktrees`, and the auto-compact window). (The matching Codex provider block in `.codex/config.toml` is gated the same way inside `modify_private_config.toml.tmpl`.) After T3 updates its bundled Codex, re-apply `~/.t3/userdata/settings.json`: the `binaryPath` of the `codex` instance names a version. The same settings script sets `worktreesDirectory` to `/Volumes/Workshop/macbook/t3-worktrees` (Workshop exists only on the personal Mac): new worktrees go there, existing ones under `~/.t3/worktrees` stay where they are and stay managed. |
| `.config/pnpm`, `Library/Preferences/pnpm` | personal (macOS) | pnpm's `storeDir` is on `/Volumes/Workshop`, which exists only on the personal Mac, so Workshop worktrees can hardlink from the store. pnpm 11 reads `~/.config/pnpm` when `XDG_CONFIG_HOME` is set (interactive shells) and `~/Library/Preferences/pnpm` when it is not (T3, launchd), so both files carry the same line (a test checks they match). With Workshop unmounted `pnpm install` fails with an error; there is no fallback to the internal disk. The old store (`~/Library/pnpm/store`) is not moved or deleted. |
| `.config/agent-docker` | personal (macOS) | Docker Desktop and its `credsStore: desktop` helper are provisioned on the personal Mac only (README, "Docker Provisioning"); the work profile skips Docker provisioning, so there is no helper of ours to avoid there. It lands only where `docker-credential-desktop` is the problem (docs/agent-docker.md). The block in `dot_zshenv` that exports `DOCKER_CONFIG` does nothing without the directory. |
| `.config/heavy-gate/volumes` | personal (macOS) | It names `/Volumes/Workshop`, which heavy-gate must find mounted with its free-space floor met before it admits a start. The work Mac has no such volume, so it gets no volumes file and heavy-gate watches only the volume that holds `$HOME` there. |
| `.config/systemd/user/t3code.service.d`, `74_t3_service_linux.sh`, `76_git_credential_linux.sh` | personal (Linux) | The PATH drop-in for the T3 service, the script that installs T3 and `t3code.service` on a Linux host, and the one that sets the portable `gh auth git-credential` helper in the global git config. The coordinator stack on Linux is personal; the work profile has no Linux desktop. |
| `.local/share/instances/systemd`, `.local/user_scripts/instances_reconcile_systemd.sh`, `75_instances_reconcile.sh` | personal (Linux) | The coordinator's systemd user unit, its reconcile script and the wrapper that runs it on apply: the Linux twin of the personal LaunchAgent. The wrapper runs on macOS for both profiles; on Linux only personal gets it, because the work coordinator (Matrix) is macOS only. |
| `.local/bin/agent-chrome`, `.local/share/browser-harness-mcp` | personal (Linux) | The agent browser (Chrome with remote debugging, plus its MCP server launcher) runs on the Omarchy box; the work profile has no Linux machine. On macOS both desktop profiles get it. |
| `.pi/agent/extensions/anthropic-stall-retry` | axon-work-computer | Anthropic stalls are only seen on the work profile. |
| `.pi/agent/extensions/axon-playbook` | axon-work-computer | It injects Axon's private playbook notes, which only the work profile clones. |

The `(Linux)` rows match every personal Linux host, personal WSL included, not only the Omarchy box: a WSL host also gets the T3 settings file, the T3 drop-in and the systemd reconcile wrapper. Most of it is inert there: the instance flag is unset by default and `74_` and the T3 install skip on WSL. Two things are not: the watchdog script only writes config, and `76_git_credential_linux.sh` replaces any GitHub credential helper the host already has (for example Windows Git Credential Manager) with `!gh auth git-credential`, so git over HTTPS on that host then needs `gh auth login`.

## Local data keys

Machine-specific values (hosts, addresses, vault items, work names) are not in this public repo. They live in the `data:` block of `~/.config/chezmoi/chezmoi.yaml` on each machine, next to `profile`. A key a profile needs fails the render with a message naming the key (`.chezmoitemplates/require_data`, and `require_work_data` for the work keys), so a machine never renders with a feature silently missing. Add the keys before you apply a change that needs them. `example.chezmoi.yaml` shows the shape with placeholder values.

### Required

| Key | Needed by | Used for |
|---|---|---|
| `workGitHost` | `axon-work-computer` | The work Git host in the lazygit host map, the gitlinker browse map, the Axon playbook text and the `reviewing-prs` skill. |
| `workGlmBaseUrl`, `workGlmKeyRef`, `workGlmModelId` | `axon-work-computer` | The `work-glm` Pi provider and its entry in the enabled models. |
| `workAwsProfile` | `axon-work-computer` | Default AWS profile in `~/.zshrc` when `AWS_PROFILE` and `AWS_DEFAULT_PROFILE` are unset. |
| `workDevportalMcpUrlRef` | `axon-work-computer` | The `work-devportal` MCP server and its 1Password reference (canonical config and the Claude, Codex and Pi adapters). |
| `rustdesk.server` | `personal` (every machine, Linux and WSL too) | The RustDesk relay address (`configure_rustdesk.sh`, `60_configure_rustdesk.sh`). |
| `sshHosts.dailyPhone` (`wgAddress`, `lanAddress`, `user`), `sshHosts.sshPhone` (same fields) | `personal` | The two phone aliases in `~/.ssh/config`: WireGuard address first, home Wi-Fi address as fallback. |
| `sshHosts.server`, `sshHosts.laptop` (`address`, `user`) | `personal`, `termux` | The `cartwmic-server` / `mac-mini` / `remote` and `laptop` aliases. |
| `sshHosts.macbook`, `sshHosts.macKvm`, `sshHosts.whonixGw`, `sshHosts.whonixWs` (`address`, `user`) | `termux` | The phone's outbound aliases (`macbook`, `mac-kvm`, `whonix-gw`, `whonix-ws`). |
| `sshHosts.kgate` (`address`, `user`) | `personal` (every machine, Linux and WSL too) | `~/.config/kgate/host`, the default for `KGATE_SSH`. `kgate` stops with a message naming the key when neither is set. |

### Optional

| Key | Effect when set | Effect when unset |
|---|---|---|
| `privatePiProviderRef` | The `work-anthropic` Pi provider, read from 1Password through the service account (work profile; see the next section). | No `work-anthropic` provider. |
| `axonPlaybook.repo` | Clones the Axon playbook (work profile; see `example.chezmoi.yaml`). | Nothing is cloned. |
| `workGitHost`, `workAwsProfile` on the personal profile | The host appears in the gitlinker map, the playbook text and the skill; the AWS default is used in `~/.zshrc`. | Left out; the AWS default is `default`. |

### 1Password service-account token

The work profile reads `privatePiProviderRef` with `op` through the service account only, never the 1Password desktop app. The token comes from `OP_SERVICE_ACCOUNT_TOKEN`, or else from `~/.config/agent-harness/op-service-token` (mode 0600, outside git). The read runs the real `op` under an empty HOME, so the app cannot answer it. With no token the render stops with a message that names the token file, and nothing calls `op`. Each render reads the secret fresh and nothing is cached, so a rotated key shows up on the next render.

### Agent jobs never reach the desktop app (playbook 78819cbd)

1Password reads use the service-account token only. Each script takes it from `OP_SERVICE_ACCOUNT_TOKEN`, else from `~/.config/agent-harness/op-service-token`. A caller that refuses without a token stops before it runs `op`, so `op` cannot fall back to the desktop app. The refusal text is `1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)`.

| Caller | Without a token | With a token |
|---|---|---|
| `~/.pi/agent/bin/op`: Pi's bash tool and `!` commands, and Retro's launchd PATH | refuses, exit 69, always | the real `op` with the service account (empty HOME; the read-only subcommands with no path option also run from that HOME, see `takes_no_path`) |
| `~/.local/share/op-shim/op`: the same file, reached by every zsh (`dot_zshenv`) | refuses (exit 69) only in an agent shell, when one of `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `T3CODE_THREAD_ID`, `HERDR_ENV`, `CODEX_SANDBOX` is set and not empty; in any other shell runs `op` unchanged (the desktop-app path) | the real `op` with the service account (same directory rule as the row above) |
| `viz publish` (`dot_local/bin/executable_viz`) | refuses (exit 4, `missing_dependency` JSON) only in an agent shell, with the same markers, and logs the refusal in `$VIZ_STATE_DIR/actions.jsonl`; other shells run `op` unchanged | the service account |
| `kgate` (profile secrets and the ghcr pull credential) | refuses (exit 69) before `op` runs, no pod created | the service account |
| `op_read_cached.sh` (pi's model keys, work GLM key) | refuses (exit 69) on a cache miss, never runs `op`; a stale cached value is served with a WARN; refusals and stale serves are logged in `$XDG_STATE_HOME/agent-harness/op-read-cached.jsonl` (reference only, no value) | a cache miss reads with the service account |
| `apply_harness_config.sh` (`resolve_secret`, during `chezmoi apply`) | the secret is unavailable and the apply goes on | the service account |
| `configure_rustdesk.sh` (the RustDesk password read) | stops with the message before the read (exit 1) | the service account |
| run-and-wake | runs the job without a token | gives the job the token from its file, never in argv, the log, the job record or the job's output; the `start` record says `op_token: env` or `file` |

**The agent-shell rule is a heuristic, and it is easy to extend.** The markers are the ones this Mac has observed. `CODEX_SANDBOX=seatbelt` was seen in the command shell of Codex's sandbox (`codex sandbox`); it is not seen in a model-driven Codex turn. Edit the `agent_shell` function in `dot_pi/private_agent/bin/executable_op` and in `dot_local/bin/executable_viz` together to add one.

Known gaps:
- A Codex run with its sandbox off sets no marker, so it gets the terminal fallback.
- A terminal started inside an agent app inherits its marker and refuses without a token. The herdr skill reads `HERDR_ENV=1` as "inside a herdr pane", so a terminal run inside herdr may be classed as an agent shell too; not checked on this Mac.
- Retro's pane shells are zsh. They refuse only if a marker is set in them; without one they keep the terminal fallback.
- A zsh started from inside Pi's bash tool (for example `zsh -c 'op whoami'`) has no marker, and `dot_zshenv` puts the zsh name first, so its `op` runs the real CLI with the desktop-app fallback. Confirmed in a scratch run: the Homebrew `op` ran (scratch HOME, no token), because `dot_zshenv` puts Homebrew ahead of the rest of the PATH.
- `viz publish` from Pi's bash tool has no marker, so viz skips its own refusal. Its `op read` reaches Pi's copy, which refuses, so no desktop path runs. viz then reports `VIZ_PUBLISH_PASSWORD is not set` and logs that outcome, not the token refusal. Confirmed in a scratch run.
- The shim's own refusal writes its message to stderr and no log record. The viz and `op_read_cached.sh` refusals are logged; the shim's is not (principle 14).
- `takes_no_path` lists six subcommands (`read`, `whoami`, `item get`, `item list`, `vault list`, `account list`) and treats five option names as path options. A flag the list does not know about that takes a relative path would resolve against the op home, not the caller's directory. The list was not checked against the full flag set of each `op` release.

The human-run flows keep their own fallbacks: fresh-machine provisioning (`run_after_05_provision_ssh_keys.sh.tmpl`), the token refresh (`refresh_op_service_account_token.sh`, biometric on purpose), and the zshrc warning block.

### Environment for the Mac-side phone helpers

`termux/router-phone.py`, `termux/wireguard-phone.py` and `termux/update-phone-alias.py` are not templates, so they read the network from the environment. Export these in the shell that runs them. A missing or invalid value stops the helper with a message naming it. `update-phone-alias.py` prints the new `sshHosts.sshPhone` entry as YAML; it edits nothing and applies nothing.

| Variable | Value |
|---|---|
| `HOMELAB_ROUTER` | The router address (OPNsense). |
| `HOMELAB_LAN_CIDR` | The home LAN, a /24. |
| `HOMELAB_WG_CIDR` | The WireGuard subnet, a /24. |

### Renamed, and one-time cleanup on the work Mac

When the work identifiers left this repo, three data keys and three names changed:

- The two data keys that held the gateway URL and key reference for the GLM provider are now `workGlmBaseUrl` and `workGlmKeyRef`; `workGlmModelId` is new. Delete the old two keys from the local data file; nothing reads them.
- The two work Pi providers are now `work-anthropic` and `work-glm`.
- The work devportal MCP server is now `work-devportal`.

The old names and the exact old-to-new key pairs are kept outside this public repo, in the owner's local data snippets. After the first apply, three leftovers stay by hand:

- Claude Code's user config still lists the old work devportal entry. The apply adds `work-devportal` and does not remove names it no longer renders for Claude. Remove the old entry once with `claude mcp remove -s user <old-name>`.
- `~/.t3/userdata/settings.json` still has the old work GLM favourite, which now points at nothing. Pick the new `work-glm` model as the favourite.
- Pi removes its recorded old MCP name by itself. Codex is different: existing `~/.codex/config.toml` files have no `# harness-servers:` line, so on the first apply after that line was added, a server the harness no longer renders (the old work devportal server is one) moves below the `END` marker and stays there. Delete its `[mcp_servers.<name>]` table (and any subtables) from `~/.codex/config.toml` once by hand; later removals are handled by the apply.
