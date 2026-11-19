# session-keepalive

A general keepalive for VPNs and other sessions: a Viscosity VPN that sits Connected while its tunnel no longer carries traffic, an AWS, Azure, Grafana or Splunk session that has quietly expired. The keepalive runs a list of checks, each with a probe, an optional refresh action and a mode, and alerts (or, per check, refreshes) when a session goes stale.

The committed code is generic. Every work-specific value — connection names, hosts, AWS profiles, Grafana and Splunk URLs, alert commands, labels — lives in the local `sessionKeepalive` data block and never in this public repo; `example.chezmoi.yaml` shows the shape with placeholder examples only.

## The checks

A check is one entry of the `sessionKeepalive.checks` list (local data):

| Field | Meaning |
|---|---|
| `label` | Local name used in notifications, logs and the state filename. A letter or digit, then up to 63 of letters, digits, space, dot, underscore, hyphen (no comma, quote or slash). Unique across checks, case-insensitively. |
| `kind` | `viscosity` or `command`. |
| `mode` | `alert` (the default) or `refresh`. Refresh is always explicit in local data. |
| `intervalSeconds` | Optional per-check minimum interval between runs, 30 to 3600. Default: the tick interval (the check then runs on every tick). |
| `alertCommand` | Optional extra command run through `sh -c` on alert, with `SESSION_KEEPALIVE_REASON` and `SESSION_KEEPALIVE_CHECK` in its environment. 30-second timeout. |

Per kind:

| Field | Kind | Meaning |
|---|---|---|
| `connection` | `viscosity` | The Viscosity connection name, exactly as Viscosity lists it. Same charset as `label`: no comma (the tick reads Viscosity's comma-joined name/state list) and no quote (the name goes into AppleScript source). |
| `host` | `viscosity` | The host probed over HTTPS through the tunnel. Any HTTP status counts as reachable. The certificate is not verified (`curl --insecure`): the probe tests reachability only, sends no credentials and reads no content, and hosts inside a VPN often use a private certificate authority. |
| `probe` | `command` | Required shell command, run through `/bin/sh -c`; exit 0 is healthy. |
| `refresh` | `command` | Optional shell command; required when the check sets `mode: refresh`. |
| `probeTimeoutSeconds` | `command` | 5 to 120. Default 20. |
| `refreshTimeoutSeconds` | `command` | 10 to 600. Default 120. |

`command` covers the cloud and web sessions: `aws sts get-caller-identity --profile <p>`, `az account get-access-token ...`, or an authenticated `curl` against Grafana or Splunk are each one command whose exit code says healthy. A missing or wedged command is a failed probe or failed refresh (exit 124), never a crash.

## Mode: alert by default, refresh per check

`alert` is the default for every kind. A check with a refresh action may set `mode: refresh`; one without may not (the render fails).

Refresh is for sessions that renew silently: the Viscosity reconnect, or `aws sso login` while the SSO session is still valid (and even that pops a browser when it is not, so alert-only is recommended for it too until the owner asks otherwise). A refresh can open a browser sign-in holding the owner's credentials, so the mode is always explicit in local data. MFA- or Okta-gated sessions are configured `mode: alert`: the tool never types, stores or pipes a password, and a refresh command that would need one must not be configured. Turning `refresh` on for any check other than the VPN reconnect is a new owner decision (the VPN reconnect itself is decision #1220).

## Deployment

The keepalive runs on any macOS profile with the `sessionKeepalive` data block; a profile without it deploys nothing. The gate is the block (local data, never in this public repo):

| Key | Meaning |
|---|---|
| `intervalSeconds` | The launchd `StartInterval` of the one agent, 30 to 3600. Default 120. |
| `checks` | A non-empty list of checks (the tables above). |

The block's presence turns the feature on. Leave it out (or remove it) and nothing is deployed, or the agent is unloaded and its plist removed on the next apply (`run_onchange_after_79_session_keepalive_launchd.sh.tmpl`). Any key or value the tables do not allow fails the whole render, so a typo applies nothing (`.chezmoitemplates/session_keepalive_config`).

**Leak note.** `chezmoi diff` DOES show the rendered plist's `SESSION_KEEPALIVE_CHECKS` with every command and URL. That diff is local to this machine — never paste it into a PR, an issue or a chat. The load script embeds only a SHA-256 of the rendered setting (to trigger `run_onchange`), never the setting itself. The rendered plist under `~/Library/LaunchAgents` carries the commands and URLs because launchd needs them; it is a local file, never in the repo. To show which checks are configured without printing commands or hosts (the redacted form for a live proof):

    plutil -extract EnvironmentVariables.SESSION_KEEPALIVE_CHECKS raw -o - \
      ~/Library/LaunchAgents/local.session-keepalive.plist \
      | python3 -c 'import json,sys; [print(c["label"], c["kind"], c.get("mode", "alert")) for c in json.load(sys.stdin)["checks"]]'

## One tick

Every `intervalSeconds` launchd runs `~/.local/bin/session-keepalive` once. The tick takes its start time once, then runs the checks serially — viscosity checks first, then command checks in data order — so a slow cloud probe can never delay a VPN check within a tick.

- A check without `intervalSeconds` runs on every tick.
- A check with `intervalSeconds` runs when `tickStart - lastRunStart >= intervalSeconds - 10` (a fixed 10 seconds of slack, so it never runs more often than its interval: a 300 s interval on a 120 s tick runs every 360 s), or when the clock moved back (`tickStart < lastRunStart`), which makes it due at once.
- Viscosity check: Viscosity not running, or the connection not `Connected` (AppleScript `get {name, state} of connections`): log it and do nothing. The owner may have quit or disconnected on purpose; the tick never starts Viscosity and never touches a connection that is not Connected. Connected: probe `https://<host>` with `curl --max-time 8`; any HTTP status counts as reachable.
- Command check: run `probe` through `/bin/sh -c` with `probeTimeoutSeconds`.
- Two failures in a row: the session is stale (the streak lives in the check's state file). One failure waits for a second probe, so a single dropped probe does nothing.

The worst tick is bounded: a refreshing command check can hold it for about 5 minutes with the default timeouts (a 120 s refresh plus the 2-minute re-probe window), a viscosity reconnect for up to about 2 minutes of re-probe; launchd does not start a new tick while one runs.

## Stale session

- `refresh`: at most once per 15 minutes, run the refresh action — viscosity: tell Viscosity to `disconnect` and then `connect` the connection by name; command: run `refresh` through `/bin/sh -c` with `refreshTimeoutSeconds`. After refreshing, re-probe for up to 2 minutes (once immediately, then every 10 seconds); if the probe still fails, alert. A refresh that did not bring the probe back doubles the wait before the next one (15, 30, 60 minutes, at most 1 hour); a probe that answers resets it to 15 minutes. The refresh time is saved before refreshing, so a crash cannot undo the wait. The rate limit and backoff are per check.
- `alert`: alert at once and touch nothing.

An alert is a macOS notification (title "Session keepalive", subtitle the check's label, message "VPN tunnel is not passing traffic" for a viscosity check or "session check failing" for a command check) plus the optional per-check `alertCommand` (30-second timeout), each at most once per stale episode. A part that failed is logged as `alert-failed` and only that part is tried again on the next stale tick. A probe that answers again ends the episode and is logged as a recovery, so a session that goes stale again later alerts again.

If the clock moves back, a pending refresh waits until the clock passes the last refresh time again: it errs on the
side of fewer sign-in prompts. (An interval check, by contrast, becomes due at once.)

## Children and their environment

Every child — probe, refresh, alert command, `osascript`, `curl` — runs in its own process group: on timeout the whole group gets `SIGTERM`, then `SIGKILL` after up to 2 s whether or not the first process already exited; reading its output afterwards is bounded too, so a child that ignores `SIGTERM` or left the group while holding the pipe cannot hold the tick, so a wedged helper or an orphaned child cannot outlive the tick. A probe that exits but leaves a child holding its stdout pipe is bounded by the timeout and the group kill the same way.

Each child's environment is this process's environment minus `SESSION_KEEPALIVE_CHECKS` (the check list is config for the tick alone, not for children), plus that call's own variables: the alert command gets `SESSION_KEEPALIVE_REASON` and `SESSION_KEEPALIVE_CHECK`. `os.environ` is never mutated.

## State and logs

Everything lands in `~/.local/state/session-keepalive/`: `log.jsonl` (one JSON line per check per tick: time, check label, kind, connection state, probe result, action: `none`, `idle`, `skipped`, `alert`, `alert-failed`, `refreshed`, `recovered` or `error`; a tick that refreshed also carries the exit codes of its refresh calls), `state/<label>.json` per check (run start, failure streak, current episode, last refresh attempt, refreshes in a row that did not help; a file that is not valid is a fresh start for that check only) and `launchd.log` (stray output only). Logs carry the label, kind, exit codes and timing — never a command string or command output.

## Tests

`python3 -m unittest discover -s tests/session-keepalive` — black-box tests of the tick with fake `osascript`, `curl` and `pgrep` on PATH (nothing calls the real Viscosity or the real network); a command check's probe and refresh are scripts the test writes itself, so they double as slow, failing, leaking and one-shot variants. Render tests cover the plist, its load script, the setting template and `.chezmoiignore` for work and personal, with and without the block. The suite is in `scripts/ci-linux.sh`. The live proof on the real Mac (a real stale session, a real refresh, the redacted check list above) is done by hand, never by CI.
