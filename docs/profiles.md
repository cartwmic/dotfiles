# Profile coverage

Chezmoi deploys every file to every profile unless `.chezmoiignore` leaves it out. A dotfiles feature targets both desktop profiles, `personal` and `axon-work-computer`, unless its design says in one line why one is left out (rule in [AGENTS.md](../AGENTS.md)).

The table lists every path that `chezmoi managed` gives to one desktop profile and not the other, with the reason. `tests/profiles/test_coverage.py` keeps it current. It fails when a one-profile path has no row, or when a row names a path that is not one-profile any more. Rows marked `reason needed (owner)` pass; the test prints how many there are.

How to read a row:

- A path covers itself and everything under it.
- `(macOS)` in the profiles column: the gate also needs `.chezmoi.os == "darwin"`. The Linux CI job skips those rows; the macOS CI job checks them.
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
| `.local/user_scripts/loop_engine_bump.py` | personal | It merges the Loop Engine bump PR and applies it on the machine it runs on, and an agent never applies on the work Mac, so it has no use there. The work Mac takes the merged pins and skills with the owner's own `chezmoi update`. |
| `.local/share/agent-events/shadow_py_run.py`, `.local/share/agent-events/cache_ref.py`, `.local/share/agent-events/reference.sha256` | personal | Gated on the `agentTracesShadow.enabled` setting, which defaults on only on personal. They are the Python control arm's entry and the cache-gauge oracle for the traces stage 2 shadow run, deployed beside the frozen collector. Nothing runs on the work Mac until the owner starts a work arm (his call, after he decides to install the kit there), so it gets none of them until he sets the setting. |
| `Library/LaunchAgents/local.agent-traces-shadow.plist`, `Library/LaunchAgents/local.agent-traces-shadow-py.plist`, `Library/LaunchAgents/local.agent-traces-seed.plist`, `73_agent_traces_shadow_launchd.sh` | personal (macOS) | Gated on the `agentTracesShadow.enabled` setting (and its `arm` list), which defaults on only on personal. They are the TS arm, the Python control arm and the throwaway seed arm of the traces stage 2 shadow run, each sending under its own `test-` label to the collector. Nothing runs on the work Mac until the owner sets the setting there and starts a work arm himself (his call, after he decides to install the kit there). The TS and seed arms also need `agentKit.enabled`; the render fails if `arm` names one without it. |
| `65_agent_kit_install.sh`, `.local/user_scripts/agent_kit_bump.py` | personal | Gated on the `agentKit.enabled` setting, which defaults on only on personal. The install is `npm ci` of a private GitHub Packages package and needs a GitHub token, which the work Mac does not have set up, so it gets the `agent-traces` wrapper (it exits 3) and the pin files but no install until that setting is turned on there (owner's call). The bump script only serves that install. |
| `.local/user_scripts/configure_rustdesk.sh` | personal | The homelab remote-access setup and its personal vault item do not belong on the work Mac. |
| `.pi/agent/extensions/openrouter-gate` | personal | The work profile keeps its own OpenRouter posture, not the personal setup. |
| `.pi/agent/extensions/claude-compat-guard` | personal | It rides on the personal Claude login; work uses its own provider. |
| `.local/bin/kgate`, `.config/kgate` | personal | It runs jobs on the personal homelab Kubernetes cluster, which the work Mac has no business reaching. |
| `80_spotlight_off_workshop.sh` | personal | `/Volumes/Workshop` exists only on the personal Mac; the work Mac has no such volume. |
| `.t3`, `.config/t3-hub-claude-settings.json` | personal (macOS) | The T3 `claude-hub` and `codex-hub` provider instances route through the homelab CLIProxy hub, which is reachable only from the home LAN or WireGuard, and Michael scoped them to his personal Mac. Linux and WSL personal hosts do not get them. (The matching Codex provider block in `.codex/config.toml` is gated the same way inside `modify_private_config.toml.tmpl`.) After T3 updates its bundled Codex, re-apply `~/.t3/userdata/settings.json`: the `binaryPath` of the `codex` instance names a version. |
| `.pi/agent/extensions/anthropic-stall-retry` | axon-work-computer | Anthropic stalls are only seen on the work profile. |
| `.pi/agent/extensions/axon-playbook` | axon-work-computer | It injects Axon's private playbook notes, which only the work profile clones. |

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
| `privatePiProviderRef` | The `work-anthropic` Pi provider, read from 1Password (work profile). | No `work-anthropic` provider. |
| `axonPlaybook.repo` | Clones the Axon playbook (work profile; see `example.chezmoi.yaml`). | Nothing is cloned. |
| `workGitHost`, `workAwsProfile` on the personal profile | The host appears in the gitlinker map, the playbook text and the skill; the AWS default is used in `~/.zshrc`. | Left out; the AWS default is `default`. |

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
