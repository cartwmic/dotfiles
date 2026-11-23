# Daily pull of the work coordinator checkout

Work profile, macOS only (row in [profiles.md](./profiles.md)). Source: `Library/LaunchAgents/local.coordinator-pull-main.plist.tmpl` and `run_onchange_after_92_coordinator_pull_main_launchd.sh.tmpl`. Tracked in cartwmic/coordinator#1083.

- **What runs:** `sh scripts/pull-main.sh` with the work coordinator checkout as the working directory. The script's own rules (on `main`, clean, the pass ref on origin, not minute :00 to :02 Pacific, `deploy-preflight.sh` clear) are in cartwmic/coordinator `docs/deploy.md`, "Upgrading a running instance". A refusal is a normal outcome and shows up as exit 1 in the log.
- **Checkout:** local data `instances.coordinator.repo`, else `~/coordinator-work` (`.chezmoitemplates/instance_repo`). `instances.coordinator.extraPath` starts the job's `PATH`, as it does for `local.coordinatord.work`.
- **When:** every day at 07:15 in the Mac's local time. A run missed while the Mac sleeps happens on wake. Loading the job (an apply, a login) runs nothing.
- **Log:** `~/Library/Logs/coordinator-work/pull-main.log`. Each run adds `<UTC time> start <checkout>`, then what `pull-main.sh` printed, then `<UTC time> exit <status>`. `pull-main.launchd.log` in the same folder holds only what launchd itself reports. The load script appends its own lines (loaded, or why not) to `pull-main.log` too, each with a UTC time and the tag `[coordinator_pull_main_launchd]`. `pull-main.sh` also keeps its own record in `~/.local/state/coordinator-ci/pull-main.jsonl`.
- **Effect of a pull:** when `src` or the lockfiles change, the work daemon restarts itself 30 to 60 seconds later (cartwmic/coordinator `docs/deploy.md`).
- **First run:** a checkout that does not yet have `scripts/pull-main.sh` is pulled by hand once (same section of `docs/deploy.md`); until then each run logs `cannot enter` or a missing-script error.
- **Run it now:** `launchctl kickstart gui/$(id -u)/local.coordinator-pull-main`.
- **Turn it off:** `launchctl bootout gui/$(id -u)/local.coordinator-pull-main`; the next apply loads it again only if the rendered plist changed (the schedule, the checkout path, `instances.coordinator.extraPath` or the log path).

Tests: `tests/coordinator-pull-main`.
