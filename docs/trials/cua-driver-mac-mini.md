# Cua Driver trial on the Mac mini: host changes as code

Trial of trycua/cua `libs/cua-driver` 0.51.5 (release tag `cua-driver-rs-v0.51.5`) on Michael's personal Mac mini (macOS 27.0.1 arm64), 2026-11-15. Workstream `read-agent-desktop`, ask #1037. Playbook 47638ebe asks that every host change be code. This is a trial, not adoption: the script is run by hand and is not wired into `chezmoi apply`.

**Profile coverage:** personal profile only. The work profile is left out because this is a trial on a personal machine, and the work Mac is never touched.

Script: `scripts/cua-driver-mac-mini-trial.sh` (`install`, `grant`, `status`, `undo`). Proof level: the steps were done by hand on the mini and the results checked (see `poc-cua/mac-mini.md` in the workstream folder). The script is the same steps written down. Its syntax was checked with `bash -n`; it was not run end to end, because running `install` would replace the working copy.

## Host changes and undo

| # | Change | Reproduce | Undo |
|---|---|---|---|
| 1 | `/Applications/CuaDriver.app` (Developer ID, team `YCK386LBJ7`, bundle id `com.trycua.driver`), copied with `ditto` from the release tarball after the SHA256 matched `SHA256SUMS` | `scripts/cua-driver-mac-mini-trial.sh install` | `rm -rf /Applications/CuaDriver.app` |
| 2 | Accessibility grant for CuaDriver ("Device Control and Data Access" pane on macOS 27) | `grant`, then switch CuaDriver on in the pane (admin password from 1Password) | `tccutil reset All com.trycua.driver` (not run), or switch it off in the pane |
| 3 | Screen Recording grant for CuaDriver (tile dragged into the list, then on) | same | same |
| 4 | Direct-capture consent (clears `direct_capture_consent_required`), stored in `~/.cua-driver/direct-capture-verification.json` | `cua-driver permissions grant` ("All set") | `rm -rf ~/.cua-driver` |
| 5 | Daemon `cua-driver serve` started by `permissions grant`, socket `~/Library/Caches/cua-driver/cua-driver.sock`. No launchd job, no LaunchAgent. | starts on demand | `cua-driver stop`, then `rm -rf ~/Library/Caches/cua-driver` |
| 6 | `~/.cua-driver/` state dir, telemetry turned off with `cua-driver telemetry disable` | `install` | `rm -rf ~/.cua-driver` |
| 7 | Scratch dir `~/.cache/cua-poc/` (tarball, test harness, Swift pointer tools, logs) | the trial scripts under `poc-cua/mac-mini/scripts/` | `rm -rf ~/.cache/cua-poc` |
| 8 | LaunchServices registration of the app (`lsregister -f`) | `install` | `lsregister -u /Applications/CuaDriver.app` |

One command removes all of it: `scripts/cua-driver-mac-mini-trial.sh undo`.

Not changed: `~/.local/bin/agent-desktop`, PATH, `~/.cache/agent-desktop-poc`, the pending Reminders prompt.

Left pending on the mini's screen: a macOS prompt "CuaDriver is requesting to bypass the system private window picker and directly access your screen and audio" (Allow / Open System Settings). Capture works without it, so it was not answered.
