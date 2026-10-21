# Herdr control MCP tunnel (opt-in)

A per-user macOS (arm64) bridge that lets a ChatGPT custom app control the local
Herdr server through an OpenAI Secure MCP Tunnel. It lives in the dotfiles repo,
not the homelab repo, because it is a client-side launcher for one Mac user, not
a hosted service.

**Opt-in only.** `.chezmoiignore` excludes `herdr-mcp/`, so `chezmoi apply` never
deploys or runs any of it. Nothing installs, stores a credential, or starts at
login until you run the commands below.

## Pieces

| File | Role |
|---|---|
| `herdr_control_mcp.py` | stdio MCP server. Python 3.9 stdlib, run by `/usr/bin/python3 -I -B`. |
| `herdr_control_mcp_child.sh` | What tunnel-client launches. Removes `CONTROL_PLANE_*`, `OPENAI_*`, `ANTHROPIC_*`, `AWS_*`, `CLOUDFLARED*`, `TUNNEL_CLIENT_*`, `MCP_*`, `HEALTH_*` and admin-UI variables, then execs the bridge. |
| `herdr-mcp-tunnel` | zsh CLI: install-client, configure, key, check, start, run, status, stop, agent. |
| `herdr_send_report.py` | Read-only report: text sends in the audit log with no matching landing in a Pi session (see Send report). Python 3.9 stdlib. |
| `install.sh` | Copies the files above and this README to `~/.local/share/herdr-mcp/` and links `~/.local/bin/herdr-mcp-tunnel`. Idempotent. |
| `claude-plugin/`, `build-claude-plugin.sh` | Optional Claude Desktop plugin (see Claude Desktop local plugin). Not installed. |
| `tests/` | Temp-HOME tests (see Tests). Not installed. |

Seven tools:

| Tool | Effect |
|---|---|
| `herdr_status`, `herdr_snapshot`, `herdr_list`, `herdr_get`, `herdr_read` | Read only. `herdr_read` returns at most 200 lines. `agent_session.value` (a private session-store path) is removed from results. |
| `herdr_request` | Forwards one native JSON request (`method`, `params`, optional `timeout_ms` of 100 to 310000) over the Herdr socket. Full native authority: input, close, server stop, integrations, worktrees. No shell. |
| `herdr_cli` | Runs one finite `herdr` argv with `shell=False`, cwd `$HOME`, stdin closed, scrubbed environment and the executable SHA-256 pinned by `configure`. It refuses bare/default launch, `server`, `attach` and `--remote`. Each output stream is capped at 1 MiB. |

## Security boundary

- tunnel-client runs with `--health.listen-addr 127.0.0.1:0`, `--cloudflared.managed=false` and `--allow-remote-ui=false`. Only `tunnel-client` is extracted from the release zip; the bundled `cloudflared` is not.
- The runtime key is never in argv, files in this repo, the plist, the config file or any log. `start` reads it at a hidden prompt; `run` reads it from the login keychain. The CLI exports it only into the tunnel-client process environment, and the child wrapper removes it again.
- Pins: release zip `a160820d45089b5253d8d671fe2a689bde0f73d78c135d1497a7b33f28a3ac62` (matches the release `SHA256SUMS.txt` for `tunnel-client-v0.0.16-darwin-arm64.zip`), extracted `tunnel-client` `6f1e8d5494d6c4d6c45cd4f6e07b5291459c0b23f4b8cd8266c7a64be3d9a2a0`, plus the bridge and wrapper hashes in `herdr-mcp-tunnel`. `check`, `start` and `run` refuse on any mismatch. For provenance beyond the checksum, run the official `gh attestation verify` steps in the tunnel-client README before `install-client`.
- The CLI refuses a second client for the same tunnel id (`pgrep` on `--control-plane.tunnel-id`), and refuses to run under shell tracing.
- Anything ChatGPT can reach through these tools crosses to OpenAI: pane output, metadata, and the effects of mutations.

## Setup

Steps marked **owner** need a browser login, permissions or a secret. No script does them.

1. **owner (Platform):** in Platform > Settings > Organization > Tunnels, create a tunnel. You need Tunnels Read+Manage to create it and Read+Use to run it, and the tunnel must include your ChatGPT workspace. Note the `tunnel_id` (not secret).
2. **owner (Platform):** create a restricted runtime API key with Tunnels Read+Use only. Keep it out of chat, argv and files.
3. Install the files: `sh ~/.local/share/chezmoi/herdr-mcp/install.sh`.
4. Install the client: `herdr-mcp-tunnel install-client` downloads the pinned release over HTTPS and verifies it. `install-client --zip PATH` uses a zip you already downloaded. Both verify both hashes before placing `~/.local/state/herdr-mcp/tc-v0.0.16/tunnel-client`.
5. `herdr-mcp-tunnel configure --tunnel-id tunnel_<32 chars>` writes `~/.config/herdr-mcp/config` (mode 600): the tunnel id, the real `herdr` binary (found with `mise which herdr`; a mise shim is rejected) and that binary's SHA-256. Rerun it after an intended Herdr upgrade.
6. `herdr-mcp-tunnel check` verifies everything offline. No key, no network.
7. Start the tunnel in one of two ways:
   - Interactive: `herdr-mcp-tunnel start` prompts for the key (hidden) and runs in the foreground. Stop with Ctrl-C or `herdr-mcp-tunnel stop`.
   - At login: see LaunchAgent below.
8. **owner (ChatGPT):** add a custom MCP app (Plugins > Add > custom MCP server > Connection: Tunnel), select the tunnel, choose no authentication, and confirm the seven tool names. Only a successful call from ChatGPT proves the deployment; local tests do not.

`herdr-mcp-tunnel status` prints the launcher and child pids, the run id and the loopback health address. It ends with `LOCAL-READY` when `/readyz` passes: local health only, not authentication and not end-to-end. For a LaunchAgent run it counts control-plane auth errors (401/403) after this run's `run-start run=<id>` marker in `agent.log`; any found gives `AUTH-FAILED` and exit 4. Only a parent MCP round trip proves the tunnel works.

## LaunchAgent (start at login)

The LaunchAgent runs `herdr-mcp-tunnel run`, which needs the key in the login keychain.

1. **owner:** `herdr-mcp-tunnel key set`. It reads the key twice at a hidden zsh prompt (no length limit), accepts only 20 to 400 characters of `A-Z a-z 0-9 _ -` starting alphanumeric, and passes `add-generic-password -U -s herdr-mcp-tunnel -a <tunnel_id> -w <key>` to `security -i` on stdin through the `print` builtin, so the key is in no argv, environment, file or shell history. All `security` output is discarded. It then reads the item back into memory and prints only `stored and verified` or a mismatch error.

   Why not `security add-generic-password -w` with its own prompt: that prompt uses `getpass(3)`, which silently keeps only the first 128 characters (measured with dummy input: 129 and 164 typed characters both gave 128). An earlier version of this tool used it, and the first cutover failed with 401; truncation is the likely cause but was not confirmed against the real key. `/usr/bin/security add-generic-password -U -s herdr-mcp-tunnel -a <tunnel_id> -w` prompts twice for the key in your terminal; the key is never an argument. `key status` reports presence without reading the value; `key delete` removes the item.
2. `herdr-mcp-tunnel agent install` checks the setup and the keychain item, writes `~/Library/LaunchAgents/local.herdr-mcp-tunnel.plist` (`RunAtLoad`, restart on non-zero exit, 60 s throttle, log `~/.local/state/herdr-mcp/agent.log`) and loads it with `launchctl bootstrap gui/$UID`. `--no-load` writes the plist only; it then starts at next login.
3. `herdr-mcp-tunnel agent status` shows plist, launchd and tunnel state. `agent uninstall` unloads the agent, waits up to 30 s for the launcher pid to exit (it fails and keeps the plist if it does not), then removes the plist. `stop` refuses the pid launchd reports for the agent, because launchd would restart it.

Restart behavior: launchd restarts `run` after any non-zero exit (client crash, signal, missing or locked keychain item, another client holding the tunnel), at most once per 60 s, indefinitely. A clean client exit (status 0) is not restarted.

Single instance: each launcher holds `~/.local/state/herdr-mcp/run/launcher.lock` for its lifetime, so concurrent starts cannot both claim the pointer. zsh opens the lock close-on-exec, so tunnel-client does not inherit it; a client orphaned by a killed launcher is still caught by the `pgrep` tunnel-id check. The small window between that check and the new client starting is not covered against a launcher that does not use this lock, such as the earlier hand-run one.

Keychain access is unverified. The item is created by `/usr/bin/security`, so its default access list trusts that tool, and `run` reads it with the same tool. Whether macOS shows an access prompt at first unattended read, or after OS or keychain changes, has not been tested on a real keychain. Check `agent status` and `agent.log` after first activation. Any process running as you can run the same `security` command; that is the accepted local trust boundary.

## Logs

| Log | Contents | Where |
|---|---|---|
| Audit (bridge) | One `start` and one `end` JSON line per tool call, sharing a `call` uuid. Fields: `ts` (UTC), `tool`, `method` (one of the 103 request methods in the Herdr 0.9.1 protocol 22 schema, taken from `schemas.request.oneOf[*].properties.method.const` and kept in `tests/fixtures/herdr-0.9.1-request-methods.json`, else `unlisted`; for `herdr_cli` only the root command, e.g. `cli:pane`), `targets` (only values shaped like Herdr ids, e.g. `w1:p2`, `w15:p2R`; at most two trailing letters, so free text is dropped), `mcp_id`, `outcome` (`ok`, `error`, `unknown`, `not_sent`, `rejected`), `duration_ms`, and `exit_code` / `error_code` / `request_id` / `transport_error` where relevant. For `herdr_cli`, `method` is the root command (`cli:pane`) and `sub` is the subcommand word (`send-text`, `prompt`, `run`, ...), logged only when it is in a fixed per-root list, so free text never reaches it. For a text send (`agent.prompt`, `pane.send_text`, `pane.send_input`, and the CLI `agent prompt`, `pane send-text`, `pane run`), `text_hash` and `text_len`: `h1:` plus 128 bits of HMAC-SHA256 of the normalized text (CRLF to LF, outer whitespace stripped), and its length in characters. Key presses (`send-keys`) carry no text and no hash. Never args, the text itself, prompts, terminal output, error messages, keys or results. | `~/.local/state/herdr-mcp/audit.log` (dir 700, file 600). Rotates at 1 MiB, keeps `audit.log.1` to `.5`. An `audit.log.lock` flock serializes rotation across concurrent bridge processes. |
| Text-hash key | 32 random bytes, created by the bridge on the first text send (atomic, no overwrite). The hash is keyed so a copy of the log cannot confirm a guessed short message such as "yes". Losing the key only stops old hashes from matching new messages. | `~/.local/state/herdr-mcp/text-hash.key` (file 600). Never copy it off the Mac. |
| Launcher runs | One line per client exit or stop: time, pids, signal, status. | `~/.local/state/herdr-mcp/launcher-runs.log` |
| Client children | Metadata-only record of processes under tunnel-client: `event=seen` (pid, ppid, depth, class), `reclassified` (same pid exec'd another program), `unobserved` (no longer in `ps`, not a verified exit), `observe_start` / `observe_end`. `class` is fixed: `codex`, `shell` (zsh/sh/bash/path_helper), `bridge`, `client`, `other`, taken from the kernel's executable name, never argv, environment or the name itself. | `~/.local/state/herdr-mcp/children.log` (600). Rotates to `children.log.1` past 256 KiB. |
| tunnel-client | Transport and lifecycle output at `info`. No raw HTTP; payload capture off. | The `start` terminal, or `agent.log` for the LaunchAgent. `agent.log` is not rotated. |

View the audit log:

```sh
tail -f ~/.local/state/herdr-mcp/audit.log
jq -c 'select(.event=="end") | [.ts,.tool,.method,.targets,.outcome,.duration_ms]' ~/.local/state/herdr-mcp/audit.log
```

A `start` with no matching `end` means the bridge died mid-call; treat any effect as unknown. Audit write failures never block a call (fail open): that call goes unaudited, and the bridge tries to print `audit log write failed (<ErrorType>)` to its stderr. Whether tunnel-client forwards child stderr to its own output is unverified.

On the ChatGPT side, each chat shows its own tool calls. The Secure MCP Tunnel docs say the tunnel itself emits no per-request events and that app-level invocation logs belong to the workspace's compliance logging. Whether those are visible on your account is unverified.

### What the client does with Codex

Supported by evidence: `agent.log` from the failed run shows tunnel-client constructing `codexappserver.NewBridge` with OnStart/OnStop hooks under its `adminui` module, and logging `Codex detected without Tunnel MCP plugin` with `next_step="tunnel-client codex plugin install"` and a `~/.codex/plugins/cache/...` path. Its binary contains strings such as "Run a CLI assistant session through codex app-server" and `codex plugin install`.

Inference only: these suggest the client's admin-UI assistant integration probes for a local Codex. They do not prove what each spawned shell did, or that the client always does this.

### Reading `children.log` for the Codex startup attempt

The official tunnel-client v0.0.16 has been seen starting `zsh -lc "codex" "app-server"`. What the log can and cannot show:

- `class=codex`, as a new pid or as `reclassified ... to=codex`: a process whose executable name was `codex` was observed. The class is a name observation only. It is not executable identity (any file can be named `codex`, and a real Codex binary under another name would show as `other`), and it says nothing about what the process did.
- `class=shell` with no `class=codex` under it: a shell was observed and no process named `codex` was. It does not show that the shell only looked for `codex`; a short-lived, reparented or differently named executable can be missed.

The observer polls `ps` every 0.25 s for the first 120 s after the client starts, then every 5 s. It can miss processes that live less than one interval, a program exec'd and replaced again between polls, and processes reparented away from the client before a poll sees them. So the absence of a `class=codex` line is weak evidence, not proof, that nothing named `codex` ran. It sees only descendants of the tunnel-client it started.

```sh
grep -E 'class=(codex|shell)|to=' ~/.local/state/herdr-mcp/children.log
```

## Send report (dropped-message check)

```sh
/usr/bin/python3 -I -B ~/.local/share/herdr-mcp/herdr_send_report.py [--hours 24 | --since 2026-10-20T00:00:00Z] [--window 300] [--target w1:p2] [--json]
```

For each text send in the audit log it looks for a Pi user message with the same `text_hash` in `~/.pi/agent/sessions` between the start of the call and the end of the call plus `--window` seconds (default 300). A landing satisfies one send, so two identical sends need two landings. Each send is `landed`, `pending` (window still open), `unmatched`, or `not_delivered` (the bridge itself rejected it or got an error). Only `unmatched` sends are listed, with time, call id prefix, kind, method, targets, length and hash prefix.

It is read-only. It reads the audit log, the hash key and Pi session files (it hashes their user messages in memory), creates nothing, and prints no message text. It exits 2 if the key does not exist yet.

An unmatched send is a candidate, not proof of a drop: the target may not be a Pi session, the agent may have queued the message beyond the window, or the session file may be elsewhere. `pane run` sends type into shells and are counted, not checked. Sends logged before this change have no hash and are counted as `sends_without_hash`. `agent prompt` targets given as names (not `w1:p1` ids) show no target. Whether Herdr submits the text unchanged, so that the hashes match in live use, has not been observed; check the first live sends.

## Claude Desktop local plugin (opt-in)

`claude-plugin/` and `build-claude-plugin.sh` give Claude the same 7 tools through a plugin that runs the installed bridge on this Mac: `/bin/sh ~/.local/share/herdr-mcp/herdr_control_mcp_child.sh`, with the same audit log. Like the tunnel, it is opt-in: `chezmoi apply` deploys none of it, and it needs no tunnel, LaunchAgent, credential or public network endpoint. It does not depend on the OpenAI tunnel being set up.

Why a plugin: Anthropic documents that servers in `claude_desktop_config.json` are not available in Cowork or claude.ai, while a plugin's local MCP server runs on the host (not the Cowork VM) through Claude Desktop. Conversations on web or mobile can use it while Desktop is open. The verified path is this Desktop-backed plugin. Cloud-only sessions that are not backed by Desktop cannot reach it, and which surfaces get Desktop backing depends on the account's Claude version.

Setup:

1. `sh ~/.local/share/chezmoi/herdr-mcp/install.sh`
2. `sh ~/.local/share/chezmoi/herdr-mcp/build-claude-plugin.sh` writes `~/Downloads/herdr-control-plugin.zip` (or the path given as its argument). It generates `.mcp.json` with this user's absolute wrapper path, so the repo holds none, and runs `claude plugin validate` when the `claude` CLI is on PATH.
3. **owner:** in Claude Desktop, open Customize > Plugins and upload the zip. Uploading grants Claude persistent access to all 7 tools, including `herdr_request` and `herdr_cli` (commands and session control). Pane text, metadata and action results go to Anthropic. Claude's default per-tool prompts apply unless changed in Desktop.
4. **owner:** call `herdr_status` from Desktop, then from the same conversation on mobile, and check `audit.log` for the matching `herdr_status` lines.

Revoke by disabling or removing the plugin in Claude Desktop. That leaves the OpenAI tunnel unchanged. After editing the bridge, rerun `install.sh`; rebuild the plugin only if HOME changes.

Verified 2026-10-16 (Claude Desktop 2.42304.0): after upload, the bridge ran on the host as a child of Claude Desktop, separate from the tunnel-client bridge. Two `herdr_status` calls returned `ok` in `audit.log`. The owner reported one from Desktop and one from the same conversation on Android. The log does not record the device.

Limits:

- Works only while the Mac is awake and Claude Desktop is open.
- `audit.log` has no client or pid field, so it cannot tell Claude from ChatGPT calls, or Desktop from mobile. Separate them only by timing and the bridge's process parent.

## Known limits

- One request, one response. No `events.subscribe` streaming, no graphics streams, no interactive attach or remote TUI. Subscriptions end when the single-response connection closes.
- Mutations are never retried. A timeout, EOF or killed CLI returns `unknown` (`unknown_after_timeout` for `herdr_cli`): the effect may or may not have happened. Inspect state before sending any new mutation. A CLI exit status does not prove the workload finished.
- A `herdr_cli` timeout kills and waits only the original CLI process. Server-side effects and descendants are not rolled back.
- The audit method list is pinned to Herdr 0.9.1. After a Herdr upgrade, regenerate the fixture from the new schema and update `KNOWN_METHODS`, or new methods log as `unlisted`.
- Installed Herdr 0.9.1 advertises graphics methods that the cached docs say were removed; no graphics support is claimed.
- One client per tunnel id. Each interactive `start` needs the key typed again.
- The send log and report see only calls that go through this bridge. A message typed or sent from another client (Herdr's own UI, a pane script) is not in the log.
- After editing the bridge or wrapper, update `BRIDGE_SHA` / `WRAP_SHA` in `herdr-mcp-tunnel` (`tests/test_launcher.py` fails until they match), then rerun `install.sh`.
- In one isolated test run, the pinned v0.0.16 tunnel-client launched a child `zsh -lc "codex" "app-server"`. No `codex` executable is on this Mac's login PATH. `tunnel-client run --help` and the docs offer no flag to turn this off; the owner accepted this. `children.log` records it (see above). The tests use a mock client.

## Cutover from the earlier hand-run launcher

Staged ahead of time (no key, no LaunchAgent): `install.sh`, `install-client`, `configure`, `check`. Then, coordinated:

1. **owner:** `herdr-mcp-tunnel key set` and type the runtime key at both hidden prompts.
2. `herdr-mcp-tunnel agent install` writes and loads the LaunchAgent. While the old client holds the tunnel id, `run` refuses ("already running") and launchd retries every 60 s; nothing is interrupted yet.
3. Ctrl-C the old launcher in its pane and wait for its cleanup line. The agent starts within about 60 s. Access is down for that gap.
4. Check `herdr-mcp-tunnel agent status` (READY), `grep -E 'class=(codex|shell)|to=' ~/.local/state/herdr-mcp/children.log`, then make a successful call from ChatGPT.

Shorter-gap order, used by this machine's one-time scripted cutover: after `key set`, run `check`, stop the old launcher, wait for its client to exit, then `agent install` (it loads immediately), and poll `status`. If it is not READY within 90 s, `agent uninstall`. That stops the new service but leaves no tunnel running until the owner restarts the old launcher and types the key again; that step cannot be scripted. Run every step under a hard timeout so a hung Keychain prompt or `launchctl` call cannot stall the switch.

Do not write the plist before the key exists: a plist in `~/Library/LaunchAgents` loads at next login.

## Rollback

Unloading the new service does not restore access. Access returns only when the original launcher runs again, and that needs the owner to type the key privately at its hidden prompt. Give the owner the step 2 command before the switch, so the fallback is ready if the new service fails. Rollback deletes nothing (keychain item, package, config and logs stay):

1. `herdr-mcp-tunnel agent uninstall` unloads the agent, waits for its launcher to exit and removes only the plist.
2. In a fresh terminal: `/bin/zsh <path-to-original-launcher>.zsh` (the earlier hand-run launcher; its exact local path is kept in local, unpublished notes), and enter the key at its hidden prompt.
3. From another terminal: `/bin/zsh <path-to-original-launcher>.zsh --ready`.

## Tests

```sh
HERDR_MCP_TEST_ZIP=/path/to/tunnel-client-v0.0.16-darwin-arm64.zip \
  /usr/bin/python3 -B -m unittest discover -s herdr-mcp/tests -v
```

Set `HERDR_MCP_TEST_SCHEMA=/path/to/installed-herdr-protocol-22.schema.json` to also re-extract the method list from the saved schema and compare it with the fixture; without it that test is skipped.

The mock client also starts a shell that runs, and a shell that execs in place, an ad-hoc re-signed copy of `sleep` named `codex`, so the child log's `seen`, `reclassified` and `unobserved` records are exercised against real processes.

`SendLedgerTests` and `SendReportTests` in `tests/test_bridge.py` cover the send log and the report: they drive the bridge over stdio, write fake Pi session files, and run the report as installed.

Every test uses a temp HOME and TMPDIR, a fake Herdr socket, fake `herdr`, fake `security`, fake `launchctl` (which starts the plist's command as launchd would) and a mock tunnel-client that serves loopback `/readyz` and drives the real wrapper and bridge over stdio. With `HERDR_MCP_TEST_ZIP`, one extra test extracts the official zip against the production pins without executing it. No test touches a real keychain, LaunchAgent, Herdr server or the network.
