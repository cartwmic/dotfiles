# VPN keepalive

The work Mac's VPN (a Viscosity OpenVPN connection) sometimes sits Connected while the tunnel no longer carries traffic; a manual reconnect fixed it every time. The VPN keepalive notices that state and, in the default mode, asks Viscosity to reconnect on its own.

## Deployment

The keepalive runs on the `axon-work-computer` profile on macOS only. Personal is left out: that profile has no such VPN. The gate is the `vpnKeepalive` data block (local data, never in this public repo; `example.chezmoi.yaml` shows the shape):

| Key | Meaning |
|---|---|
| `connection` | The Viscosity connection name, exactly as Viscosity lists it. A letter or digit, then up to 63 of letters, digits, space, dot, underscore, hyphen: no comma (the tick reads Viscosity's comma-joined name/state list) and no quote (the name goes into AppleScript source). |
| `host` | The host probed over HTTPS through the tunnel. Any HTTP status counts as reachable. |
| `mode` | `reconnect` (the default, the owner's decision) or `alert`. |
| `intervalSeconds` | The launchd `StartInterval`, 30 to 3600. Default 120. |
| `alertCommand` | Optional extra command run through `sh -c` on alert, with `VPN_KEEPALIVE_REASON` in its environment. |

The block's presence turns the feature on. Leave it out (or remove it) and nothing is deployed, or the agent is unloaded and its plist removed on the next apply (`run_onchange_after_79_vpn_keepalive_launchd.sh.tmpl`). Any key or value the table does not allow fails the whole render, so a typo applies nothing (`.chezmoitemplates/vpn_keepalive_config`).

## One tick

Every `intervalSeconds` launchd runs `~/.local/bin/vpn-keepalive` once:

1. Viscosity not running, or the connection not `Connected` (AppleScript `get {name, state} of connections`): log it and do nothing. The owner may have quit or disconnected on purpose; the tick never starts Viscosity and never touches a connection that is not Connected.
2. Connected: probe `https://<host>` with `curl --max-time 8`. Any HTTP status counts as reachable.
3. Two failures in a row: the tunnel is stale (the streak lives in `state.json`). One failure waits for a second probe, so a single dropped probe does nothing.

## Stale tunnel

- `reconnect` (default): at most once per 15 minutes, tell Viscosity to `disconnect` and then `connect` the connection by name (its AppleScript dictionary takes the name as the direct parameter). reconnect can open the connection's browser sign-in, which holds the owner's credentials — that is why the mode is the owner's choice and why the rate limit exists. After reconnecting, re-probe for up to 2 minutes; if the host is still unreachable, alert. A reconnect that did not bring the host back doubles the wait before the next one (15, 30, 60 minutes, at most 1 hour); a probe that answers resets it to 15 minutes. The reconnect time is saved before reconnecting, so a crash cannot undo the wait.
- `alert`: alert at once and touch nothing.

An alert is a macOS notification plus the optional `alertCommand` (run with a 30-second timeout), each at most once per stale episode. A part that failed is logged as `alert-failed` and only that part is tried again on the next stale tick. A probe that answers again ends the episode and is logged as a recovery, so a tunnel that goes stale again later alerts again.

## State and logs

Everything lands in `~/.local/state/vpn-keepalive/`: `log.jsonl` (one JSON line per tick: time, connection state, probe result, action: `none`, `idle`, `alert`, `alert-failed`, `reconnected`, `recovered` or `error`; a tick that reconnected also carries the exit codes of its disconnect and connect calls), `state.json` (failure streak, current episode, last reconnect attempt, reconnects in a row that did not help; a file that is not valid is a fresh start) and `launchd.log` (stray output only).

## Tests

`python3 -m unittest discover -s tests/vpn-keepalive` — black-box tests of the tick with fake `osascript`, `curl` and `pgrep` on PATH (nothing calls the real Viscosity or the real network), plus a render test that the work profile renders the agent and personal does not. The suite is in `scripts/ci-linux.sh`. The live proof on the real Mac (a real stale tunnel, a real reconnect) is done by hand, never by CI.
