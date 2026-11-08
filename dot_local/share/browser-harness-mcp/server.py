"""Launcher for the browser-harness MCP server (agent-harness README, "Agent browser").

Run it as:  uvx --from "browser-harness[mcp]==0.1.13" python -I server.py   (servers.json.tmpl does).

It starts the stock server and changes three things, both found when several agents shared one Chrome:

1. Own tab. The stock server uses one daemon, named "default", for every MCP process on the machine, and the daemon
   keeps ONE current tab. A second agent's browser_new_tab or browser_switch_tab moved every other agent's tab, and
   when a tab went stale the daemon silently re-attached to the first page in Chrome (a person's tab). Here each
   MCP process gets its own daemon (BU_NAME mcp-<pid>) and its own tab, and stops that daemon when it exits.
2. Real clicks on a background tab. Chrome drops mouse and key input to a hidden tab with no error, so
   browser_click answered success and the page never saw it. Focus emulation makes the page visible and focused
   to itself, so input arrives with no tab or window change. It is turned on for the current tab before every tool call.
3. browser_ensure_real_tab no longer switches tabs (the stock one attaches to the first real page in Chrome); it reports the current tab.
"""
import atexit
import os
import signal
import sys

NAME = os.environ.setdefault("BU_NAME", "mcp-%d" % os.getpid())  # before browser_harness is imported: it reads BU_NAME at import
OWN = NAME == "mcp-%d" % os.getpid()

import mcp_server  # noqa: E402  (from the browser-harness[mcp] install)
from browser_harness import admin, helpers, paths  # noqa: E402

_stock_ensure_daemon = mcp_server.ensure_daemon


def ensure_daemon(*args, **kwargs):
    result = _stock_ensure_daemon(*args, **kwargs)
    # A failure here reaches the agent as the tool's error: swallowing it would bring back the silent dropped click.
    # With a native dialog open the page's thread is frozen, so leave the tab alone until the agent handles the dialog.
    if not helpers._send({"meta": "pending_dialog"}).get("dialog"):
        helpers.cdp("Emulation.setFocusEmulationEnabled", enabled=True)
    return result


def ensure_real_tab():
    """Report the tab this agent is on. The stock tool switches to the first real page in Chrome when the current tab
    looks internal, and that page can be a signed-in tab that belongs to a person or another agent."""
    return helpers.current_tab()


mcp_server.ensure_daemon = ensure_daemon
mcp_server.ensure_real_tab = ensure_real_tab


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_orphans():
    """Stop mcp-<pid> daemons whose MCP process is gone (it was killed and could not stop its own)."""
    try:
        for pid_file in paths.runtime_dir().glob("bu-mcp-*.pid"):
            pid = pid_file.stem.removeprefix("bu-mcp-")
            if pid.isdigit() and not _alive(int(pid)):
                admin.restart_daemon(pid_file.stem.removeprefix("bu-"))
    except Exception:
        pass


def stop_own_daemon():
    if OWN:
        try:
            admin.restart_daemon(NAME)
        except Exception:
            pass


if OWN:
    stop_orphans()
    atexit.register(stop_own_daemon)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))

if __name__ == "__main__":
    mcp_server.main()
