"""Launcher for the browser-harness MCP server (agent-harness README, "Agent browser").

Run it as:  uvx --from "browser-harness[mcp]==0.1.13" python -I server.py   (servers.json.tmpl does).

It starts the stock server and changes four things, found when several agents shared one Chrome:

1. Own tab. The stock server uses one daemon, named "default", for every MCP process on the machine, and the daemon
   keeps ONE current tab. A second agent's browser_new_tab or browser_switch_tab moved every other agent's tab, and
   when a tab went stale the daemon silently re-attached to the first page in Chrome (a person's tab). Here each
   MCP process gets its own daemon (BU_NAME mcp-<pid>) and its own tab, and stops that daemon when it exits.
2. Real clicks on a background tab. Chrome drops mouse and key input to a hidden tab with no error, so
   browser_click answered success and the page never saw it. Focus emulation makes the page visible and focused
   to itself, so input arrives with no tab or window change. It is turned on for the current tab before every tool call.
3. browser_ensure_real_tab no longer switches tabs (the stock one attaches to the first real page in Chrome); it reports the current tab.
4. A closed tab fails loudly. When the tab this session was using is closed (from outside, or by its own browser_close_tab), the stock daemon
   quietly attaches to a fresh about:blank and the next browser_click answers {"ok": true} on nothing. Here every action tool refuses with
   a message that names the closed tab until the agent opens or switches to a tab (browser_new_tab, browser_switch_tab). The check runs before
   each tool call: a tab that closes in the middle of one long call (wait_for_load, wait_for_element, fill) can still make that one call
   answer on the replacement page; the next call is refused. A dead daemon that is restarted is not detected (it attaches to a fresh about:blank).
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


class Tab:
    """The tab this session is using, as the agent last chose it: a target id; None before the first tool call; CLOSED after the agent closed
    it; or LOST plus the id once it vanished (closed from outside)."""

    expected = None
    lost_id = None


CLOSED, LOST = "closed", "lost"


def _tab_exists(target_id):
    # Target.getTargets takes no session, so asking cannot make the daemon re-attach to another page (a session command would).
    return any(t["targetId"] == target_id and t["type"] == "page" for t in helpers.cdp("Target.getTargets")["targetInfos"])


def ensure_daemon(*args, **kwargs):
    result = _stock_ensure_daemon(*args, **kwargs)
    if Tab.expected not in (None, CLOSED, LOST) and not _tab_exists(Tab.expected):
        Tab.lost_id, Tab.expected = Tab.expected, LOST
    if Tab.expected in (CLOSED, LOST):
        return result  # no session command until the agent picks a tab: it would only attach the daemon to a replacement page
    # A failure here reaches the agent as the tool's error: swallowing it would bring back the silent dropped click.
    # With a native dialog open the page's thread is frozen, so leave the tab alone until the agent handles the dialog.
    if not helpers._send({"meta": "pending_dialog"}).get("dialog"):
        helpers.cdp("Emulation.setFocusEmulationEnabled", enabled=True)
    if Tab.expected is None:
        Tab.expected = helpers.current_tab()["targetId"]
    return result


def _require_tab():
    if Tab.expected == LOST:
        raise RuntimeError("The tab this session was using (%s) was closed, so nothing was done. Open a tab with browser_new_tab, or attach to an "
                           "open one with browser_switch_tab, then retry." % Tab.lost_id)
    if Tab.expected == CLOSED:
        raise RuntimeError("This session has no tab: its tab was closed. Open one with browser_new_tab, or attach to an open one with "
                           "browser_switch_tab.")


def _guarded(function):
    def call(*args, **kwargs):
        _require_tab()
        return function(*args, **kwargs)
    call.__name__ = getattr(function, "__name__", "guarded")
    call.__doc__ = function.__doc__
    return call


def _remember_tab_after(function, closes=False):
    def call(*args, **kwargs):
        target = args[0] if args else kwargs.get("target")
        target_id = (target.get("targetId") or target.get("target_id")) if isinstance(target, dict) else target
        result = function(*args, **kwargs)
        if closes:
            if target_id in (None, Tab.expected):
                Tab.expected = CLOSED
        else:
            Tab.expected = target_id if function.__name__ == "switch_tab" and target_id else helpers.current_tab()["targetId"]
            # Done here, not only before the next tool call: Chrome takes a moment to make the page visible, and a click sent in the same
            # breath as the first emulation call would reach a page still hidden and be dropped.
            helpers.cdp("Emulation.setFocusEmulationEnabled", enabled=True)
        return result
    call.__name__ = getattr(function, "__name__", "remember")
    call.__doc__ = function.__doc__
    return call


def ensure_real_tab():
    """Report the tab this agent is on. The stock tool switches to the first real page in Chrome when the current tab
    looks internal, and that page can be a signed-in tab that belongs to a person or another agent."""
    return helpers.current_tab()


mcp_server.ensure_daemon = ensure_daemon
mcp_server.ensure_real_tab = ensure_real_tab
for _name in ("capture_screenshot", "click_at_xy", "fill_input", "goto_url", "js", "page_info", "press_key", "scroll", "type_text", "upload_file",
              "wait_for_element", "wait_for_load", "start_recording", "stop_recording"):
    setattr(mcp_server, _name, _guarded(getattr(mcp_server, _name)))
_stock_cdp = mcp_server.cdp


def cdp(method, params=None, **kwargs):
    if not str(method).startswith("Target."):  # raw browser-level calls need no tab; the rest act on the current one
        _require_tab()
    return _stock_cdp(method, params, **kwargs) if params is not None else _stock_cdp(method, **kwargs)


mcp_server.cdp = cdp
mcp_server.new_tab = _remember_tab_after(mcp_server.new_tab)
mcp_server.switch_tab = _remember_tab_after(mcp_server.switch_tab)
mcp_server.close_tab = _remember_tab_after(mcp_server.close_tab, closes=True)


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
