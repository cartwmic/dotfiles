# Profile coverage

Chezmoi deploys every file to every profile unless `.chezmoiignore` leaves it out. A dotfiles feature targets both desktop profiles, `personal` and `axon-work-computer`, unless its design says in one line why one is left out (rule in [AGENTS.md](../AGENTS.md)).

The table lists every path that `chezmoi managed` gives to one desktop profile and not the other, with the reason. `tests/profiles/test_coverage.py` keeps it current. It fails when a one-profile path has no row, or when a row names a path that is not one-profile any more. Rows marked `reason needed (owner)` pass; the test prints how many there are.

How to read a row:

- A path covers itself and everything under it.
- `(macOS)` in the profiles column: the gate also needs `.chezmoi.os == "darwin"`. The Linux CI job skips those rows; the macOS CI job checks them.
- Termux is out of scope here; it has its own block in `.chezmoiignore`.
- Not covered: profile branches inside templates (`{{ if eq .profile ... }}` in about two dozen templates) and run scripts that skip themselves by profile, such as `60_configure_rustdesk.sh`. The PR body's `Profiles:` line covers those.

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
| `.local/user_scripts/configure_rustdesk.sh` | personal | The homelab remote-access setup and its personal vault item do not belong on the work Mac. |
| `.pi/agent/extensions/openrouter-gate` | personal | The work profile keeps its own OpenRouter posture, not the personal setup. |
| `.pi/agent/extensions/claude-compat-guard` | personal | It rides on the personal Claude login; work uses its own provider. |
| `.pi/agent/extensions/anthropic-stall-retry` | axon-work-computer | Anthropic stalls are only seen on the work profile. |
