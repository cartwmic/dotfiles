# pi-mcp-lazy

Pi starts every enabled MCP server when a session opens and never stops one. For the three local servers
that costs most of an idle session's memory (cartwmic/dotfiles#14). `pi-mcp-lazy` (deployed to
`~/.local/bin/pi-mcp-lazy`) sits in front of one local server so it runs only while it is used.

Pi's built-in MCP client is unchanged. It still reads `~/.pi/agent/mcp.json` and still starts one stdio process per
server, but for `playwright` and `rea` that process is the stand-in:

- **Handshake and tool list come from a saved copy.** Pi sees the same tools (`mcp__<server>__<tool>`) and the
  `mcp_servers` listing in the system prompt, and `searchTools`, `describeTool`, `describeNamespace` and `ALL_TOOLS`
  work, with no real server running.
- **The first request that needs the real server starts it** (a tool call, or a resource or prompt request). It runs in
  the stand-in's own process group (Pi starts each stand-in as the leader of a group of its own), receives Pi's own `initialize`, and everything after that is forwarded unchanged, including the
  server's own requests to Pi (for example `roots/list`).
- **After the idle period with no request in flight** the whole process tree is stopped (stdin closed, SIGTERM, a
  short grace, SIGKILL, signalled by process id: the server's pid and its descendants, found before anything is signalled, so
  also a browser the server detached into its own session; never a group, because the stand-in shares the server's group). A later request starts it again. A call that runs
  longer than the idle period is never interrupted: the clock runs only while nothing is in flight.
- **A cancelled call is not in flight.** Pi cancels a call when the user aborts it or it times out, and some servers (rea) then
  send no reply at all. The stand-in forgets a request as soon as Pi cancels it, so an unanswered cancelled call cannot keep the
  server up past the idle period.
- **A server that cannot start** answers the waiting request with an error that names the server and carries the
  tail of its stderr. The stand-in stays up and the next request tries again.
- Closing Pi's stdin, SIGTERM and SIGHUP stop the real server too, so exiting Pi or `/reload` leaves nothing behind.

Which servers: `~/.local/share/pi-mcp-lazy/servers.list` (`playwright` and `rea` on every profile, plus `jira` on
`axon-work-computer`; the source is `servers.list.tmpl`, which renders the `jira` line only on that profile). The remote HTTP
servers (`hindsight`, `context7`, `ticktick`) are not touched.

### jira (work profile)

`jira` is `npx -y mcp-remote <URL>`, a local stdio proxy to a remote server. It has **no shipped seed**: its tool list can
only be captured on the work computer, where the URL (a 1Password secret) and the sign-in exist. The **first apply on the work
computer populates it**: the apply refreshes `jira` and saves its handshake and tool list to
`~/.local/state/pi-mcp-lazy/jira.json`. Every later apply refreshes it again.

If that refresh fails (not signed in, offline, `mcp-remote` cannot start) and no saved list exists, the apply **leaves the `jira`
entry as rendered**. Pi then starts it at session start exactly as before this change, so `jira` never shows up with zero tools.
The apply logs `jira has no saved tool list; left as rendered`; fix the cause and apply again. A refresh that fails while an
older saved list exists keeps the entry wrapped and serves that list.

The saved copy's `key` field is the command line, which for `jira` includes the resolved URL. The state directory is mode 0700
and the same URL is already in `~/.pi/agent/mcp.json`. The apply log hides URLs and env values from a failed refresh's output.

## Where the saved tool list comes from

Pi runs `initialize` and `tools/list` as soon as it connects, so a list must exist before the session starts or the
server would have to be started just to answer. A list always exists:

1. **State copy**: `~/.local/state/pi-mcp-lazy/<server>.json`, written by `pi-mcp-lazy --refresh` (below) and
   rewritten by every real start in a session when the tool list differs (Pi is told with
   `notifications/tools/list_changed`).
2. **Seed**: `~/.local/share/pi-mcp-lazy/seed/<server>.json`, shipped by this repository, read when there is no state
   copy (the apply-time refresh failed, or the file was deleted). `jira` has none (see above).

A copy saved for a different command line (a version bump of `rea`, say) is still served and noted on stderr; the next
apply or real start replaces it. A stale list never starts a server. Only if neither file exists (an incomplete
installation) does the connect fail, with an error naming the server and the repair command.

Copies hold only what the server publishes (protocol version, capabilities, name, instructions, tool definitions), never
credentials.

## Defaults and commands

- Idle period: 600 seconds, written into each rendered entry as its second argument. Change it for one server by editing
  that entry's argument in `~/.pi/agent/mcp.json`, or for all by exporting `PI_MCP_LAZY_IDLE` when applying.
- Rebuild a copy by hand: `pi-mcp-lazy --refresh NAME -- COMMAND [ARGS...]` (starts the real server once, saves, stops).
- Ask whether serving would show Pi any tools: `pi-mcp-lazy --check NAME -- COMMAND [ARGS...]` (exit 0 if the state copy, else
  the seed, holds at least one tool; starts nothing). The apply uses it after each refresh.
- Regenerate the seeds from the real servers (do this when preparing a change that bumps a server):
  `mkdir -p dot_local/share/pi-mcp-lazy/seed && PI_MCP_LAZY_STATE_DIR=dot_local/share/pi-mcp-lazy/seed pi-mcp-lazy --refresh playwright -- npx @playwright/mcp`
  and likewise for `rea` (`npx -y rea-agents@6.4.0 mcp`).
- Environment: `PI_MCP_LAZY_STATE_DIR`, `PI_MCP_LAZY_SEED_DIR`, `PI_MCP_LAZY_GRACE` (seconds between SIGTERM and SIGKILL,
  default 1.0), `PI_MCP_LAZY_START_TIMEOUT` (default 120).

## How it is rendered

`apply_harness_config.sh` (Pi path only) runs the refresh for each name in `servers.list` and then rewrites that
entry in `~/.pi/agent/mcp.json` to `{"command": "~/.local/bin/pi-mcp-lazy", "args": [NAME, "600", "--", <original command and
args>]}`, keeping any other keys of the entry. A failed refresh is logged by name with the stderr tail (URLs and env values
hidden). The entry is still wrapped when `--check` finds a saved list with tools (an older state copy, or the seed); otherwise it is
left as rendered and Pi starts the server at session start. The canonical `servers.json`, and therefore the Claude and Codex renderings,
are unchanged.

## Accepted limits

- Stopping `playwright` when idle closes its browser, so open pages and signed-in state are gone on the next use. Raise
  the idle period for that entry if that matters.
- A cold first call can take seconds (`npx` start). Pi's per-request timeout is 60 seconds by default; add a larger
  `"timeout"` to the entry if a cold start is ever slower.
- **Exit and /reload.** The server shares the stand-in's process group. Pi's shutdown (close stdin, SIGTERM to the group after
  0.5 s, SIGKILL to the group after 2.5 s) reaches the server and every same-group helper while the stand-in is still running. Pi
  cancels those timers when the stand-in exits and then sends the group one last SIGTERM only, so on the normal path the stand-in's own
  tidy-up (stdin close, SIGTERM, 1 s grace, SIGKILL by process id) is what stops a server that ignores SIGTERM. A helper a server
  detaches into its own session (a browser) is outside any group signal: the stand-in reaches it from its process-tree walk at stop time.
- **Known limits, accepted by the owner** (Michael, 2026-10-18: "Accept limits, go to validation"): the stand-in finds the server's
  helpers by walking the process tree with `ps`. It walks just before it closes the server's stdin, before the SIGKILL round and every 0.2 s while it waits, and signals
  anything new, so a process a helper starts mid-stop is caught while its parent lives. A walk is still a snapshot: a failed or
  timed-out walk, a group or terminal signal that kills the server before the first walk, a server that crashes before the walk, a
  process that is started and orphaned within one walk interval, and a stale process id can leave a detached or re-parented helper
  behind; a SIGKILLed stand-in cannot tidy up at all. Continuous tracking of the server's tree while it runs would close most of these
  and is a separate follow-up.
- A helper left behind by a server that crashes outright (the server dies before the stand-in can walk its process tree) is re-parented
  and is not reached by the stand-in; it stays until something stops it, as it would under a direct launch.
- If the stand-in itself is killed with SIGKILL it cannot tidy up, but its group-mates die with it when Pi's group kill is the
  cause, and the server sees its stdin close either way. The lifecycle test prints what it observed.
- A seed can be out of date until the next apply or real start; a tool that was removed since then returns the server's
  own unknown-tool error.

## Roll back

Remove a name from `~/.local/share/pi-mcp-lazy/servers.list` (source: `dot_local/share/pi-mcp-lazy/servers.list.tmpl`) and
apply again: that entry returns to its canonical form. Removing the file returns all of them. Reload or restart a
Pi session to pick the change up.

## Measured effect (2026-10-18, #14 procedure, throwaway home, scripted backend, medians)

| fresh full-configuration session | samples | Pi RSS | owned-set RSS | owned-set footprint | MCP processes |
|---|---|---|---|---|---|
| before (d6118aba) | 3 | 292 MB | 1257 MB | 975 MB | 5 real servers/wrappers |
| after, all lazy variants pooled (state copy, seed only, refresh failed) | 21 | 335 MB | **385 MB** (334-417) | about 270 MB | 3 stand-ins, 0 real |

Owned-set RSS falls by about 70% (69% at the median, 67% in the worst session; the acceptance line set by the owner is a cut of at
least 65%), and no real MCP process runs at the settled point. The three stand-ins are a fixed 48 MB (16 MB each); the rest is the Pi
process, whose RSS alone varied between 283 and 367 MB from launch to launch (two modes, about 285 and about 345 MB), whatever the
variant. That variation is reported and not judged. An earlier target of 350 MB owned-set RSS was met in only 5 of 21 sessions; the
owner replaced it with the 65% cut. Early three-sample runs happened to land in the low mode (334 MB with a state copy, 341 MB after a
failed refresh, 357-359 MB seed only); an interleaved rerun (three rounds of each variant, alternating) landed in the high mode for all
variants (385-417 MB), so the variants do not differ from each other. Small aged session (one compaction, one /reload): owned-set
footprint after /reload 269 MB with no real MCP process at any stage; the baseline had 5 processes and 1001 MB.

The stand-ins read 16 MB each here because the measurement home has no Python bytecode cache; with a warm cache one idles at
about 12 MB. A stand-in runs on the system Python (`/usr/bin/python3`) when the macOS command-line tools are present, because it
is about 10 MB smaller than a current mise Python, and on `python3` from PATH otherwise. The first call to a stopped server
costs the server's own start time (rea about 2 s, playwright about 1 s here) plus about 0.04 s for the stand-in.

## Tests and measurement

- `python3 -m unittest discover -s tests/pi-mcp-lazy -v`: protocol, saved copies, start failure, idle lifecycle, rendering.
- `python3 tests/pi-mcp-lazy/proof.py`: a real Pi session with a scripted model (discovery without starting a server,
  first use, idle stop, restart, long call, failure and retry, six servers).
- `python3 tests/pi-idle-rss/pi_idle_rss.py measure --variants full,full-lazy ...`: idle memory before and after, with the
  MCP processes listed (see `tests/pi-idle-rss/README.md`).
