# pi-mcp-lazy

Pi starts every enabled MCP server when a session opens and never stops one. For the three local servers
that costs most of an idle session's memory (cartwmic/dotfiles#14). `pi-mcp-lazy` (deployed to
`~/.local/bin/pi-mcp-lazy`) sits in front of one local server so it runs only while it is used.

Pi's built-in MCP client is unchanged. It still reads `~/.pi/agent/mcp.json` and still starts one stdio process per
server, but for `furi`, `playwright` and `rea` that process is the stand-in:

- **Handshake and tool list come from a saved copy.** Pi sees the same tools (`mcp__<server>__<tool>`) and the
  `mcp_servers` listing in the system prompt, and `searchTools`, `describeTool`, `describeNamespace` and `ALL_TOOLS`
  work, with no real server running.
- **The first request that needs the real server starts it** (a tool call, or a resource or prompt request). It runs in
  its own process group, receives Pi's own `initialize`, and everything after that is forwarded unchanged, including the
  server's own requests to Pi (for example `roots/list`).
- **After the idle period with no request in flight** the whole process tree is stopped (stdin closed, SIGTERM, a
  short grace, SIGKILL, plus any descendant that left the group). A later request starts it again. A call that runs
  longer than the idle period is never interrupted: the clock runs only while nothing is in flight.
- **A server that cannot start** answers the waiting request with an error that names the server and carries the
  tail of its stderr. The stand-in stays up and the next request tries again.
- Closing Pi's stdin, SIGTERM and SIGHUP stop the real server too, so exiting Pi or `/reload` leaves nothing behind.

Which servers: `~/.local/share/pi-mcp-lazy/servers.list` (`furi`, `playwright`, `rea`). The remote HTTP servers
(`hindsight`, `context7`, `ticktick`) are not touched.

## Where the saved tool list comes from

Pi runs `initialize` and `tools/list` as soon as it connects, so a list must exist before the session starts or the
server would have to be started just to answer. A list always exists:

1. **State copy**: `~/.local/state/pi-mcp-lazy/<server>.json`, written by `pi-mcp-lazy --refresh` (below) and
   rewritten by every real start in a session when the tool list differs (Pi is told with
   `notifications/tools/list_changed`).
2. **Seed**: `~/.local/share/pi-mcp-lazy/seed/<server>.json`, shipped by this repository, read when there is no state
   copy (the apply-time refresh failed, or the file was deleted).

A copy saved for a different command line (a version bump of `rea`, say) is still served and noted on stderr; the next
apply or real start replaces it. A stale list never starts a server. Only if neither file exists (an incomplete
installation) does the connect fail, with an error naming the server and the repair command.

Copies hold only what the server publishes (protocol version, capabilities, name, instructions, tool definitions), never
credentials.

## Defaults and commands

- Idle period: 600 seconds, written into each rendered entry as its second argument. Change it for one server by editing
  that entry's argument in `~/.pi/agent/mcp.json`, or for all by exporting `PI_MCP_LAZY_IDLE` when applying.
- Rebuild a copy by hand: `pi-mcp-lazy --refresh NAME -- COMMAND [ARGS...]` (starts the real server once, saves, stops).
- Regenerate the seeds from the real servers (do this when preparing a change that bumps a server):
  `mkdir -p dot_local/share/pi-mcp-lazy/seed && PI_MCP_LAZY_STATE_DIR=dot_local/share/pi-mcp-lazy/seed pi-mcp-lazy --refresh furi -- furi connect`
  and likewise for `playwright` (`npx @playwright/mcp`) and `rea` (`npx -y rea-agents@6.4.0 mcp`).
- Environment: `PI_MCP_LAZY_STATE_DIR`, `PI_MCP_LAZY_SEED_DIR`, `PI_MCP_LAZY_GRACE` (seconds between SIGTERM and SIGKILL,
  default 3), `PI_MCP_LAZY_START_TIMEOUT` (default 120).

## How it is rendered

`apply_harness_config.sh` (Pi path only) runs the refresh for each name in `servers.list` and then rewrites that
entry in `~/.pi/agent/mcp.json` to `{"command": "~/.local/bin/pi-mcp-lazy", "args": [NAME, "600", "--", <original command and
args>]}`, keeping any other keys of the entry. A failed refresh is logged by name with the stderr tail and the entry is
still wrapped (sessions then serve the seed). The canonical `servers.json`, and therefore the Claude and Codex renderings,
are unchanged.

## Accepted limits

- Stopping `playwright` when idle closes its browser, so open pages and signed-in state are gone on the next use. Raise
  the idle period for that entry if that matters.
- A cold first call can take seconds (`npx` start). Pi's per-request timeout is 60 seconds by default; add a larger
  `"timeout"` to the entry if a cold start is ever slower.
- If the stand-in itself is killed with SIGKILL it cannot clean up. The real server sees its stdin close and normally
  exits, but a process it spawned can be left behind (the lifecycle test prints what it observed).
- A seed can be out of date until the next apply or real start; a tool that was removed since then returns the server's
  own unknown-tool error.

## Roll back

Remove a name from `~/.local/share/pi-mcp-lazy/servers.list` (source: `dot_local/share/pi-mcp-lazy/servers.list`) and
apply again: that entry returns to its canonical form. Removing the file returns all of them. Reload or restart a
Pi session to pick the change up.

## Tests and measurement

- `python3 -m unittest discover -s tests/pi-mcp-lazy -v`: protocol, saved copies, start failure, idle lifecycle, rendering.
- `python3 tests/pi-mcp-lazy/proof.py`: a real Pi session with a scripted model (discovery without starting a server,
  first use, idle stop, restart, long call, failure and retry, six servers).
- `python3 tests/pi-idle-rss/pi_idle_rss.py measure --variants full,full-lazy ...`: idle memory before and after, with the
  MCP processes listed (see `tests/pi-idle-rss/README.md`).
