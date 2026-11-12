"""Launcher for the browser-use MCP server (agent-harness README, "Agent browser").

Run it as:  uvx --from browser-use==1.0.2 python -I server.py   (servers.json.tmpl does).

It starts `browser-use --cli-mcp` (tools: browser_exec, browser_screenshot, browser_login, browser_feedback) and changes four things,
each found failing when several agents shared one Chrome:

1. Own tab. The stock server uses one daemon, named "default", for every MCP process on the machine, and the daemon keeps ONE current
   tab. A second agent's new_tab or switch_tab moved every other agent's tab. Here each MCP process gets its own daemon (BU_NAME
   mcp-<pid>) and its own tab, and stops that daemon when it exits (daemons left by a killed process are stopped at the next start).
2. Real clicks on a background tab. Chrome drops mouse and key input to a hidden tab with no error, so click_at_xy answered success and
   the page never saw it. Focus emulation makes the page visible and focused to itself, so input arrives with no tab or window change.
   It is turned on for the current tab before every browser_exec and browser_screenshot, and the moment new_tab or switch_tab returns
   (Chrome takes a moment to show the page, and a click sent in the same breath would still be dropped).
3. A closed tab fails loudly. When the tab this session was using is closed (from outside, or by its own close_tab) the stock daemon
   quietly attaches to a fresh about:blank and the next click_at_xy answers ok on nothing. Here every call that acts on a tab refuses with
   a message that names the closed tab until the agent opens or switches to a tab (new_tab, switch_tab). The check runs before each
   browser_exec and browser_screenshot, and again inside every CDP call the helpers make: a tab that closes in the middle of one long
   call (wait_for_load, wait_for_element) can still make that one call answer on the replacement page; the next call is refused.
   A dead daemon that is restarted is not detected (it attaches to a fresh about:blank).
4. ensure_real_tab() no longer switches tabs. The server's own startup instructions tell agents "if the current tab is stale or internal, call
   ensure_real_tab()", and the stock helper attaches to the first real page in Chrome: another agent's tab, or one a person has open. It also
   goes through switch_tab, which would lift the closed-tab refusal. Here it reports the current tab, and refuses like every other call when
   that tab is closed.

The patches reach into private names of browser-use (CLIMCPServer._attach, _ensure_namespace) and browser-harness (helpers.cdp, new_tab,
switch_tab, close_tab, current_tab, ensure_real_tab, _send). They hold only while the two packages stay pinned together as below. At start the launcher
checks that the installed versions equal the pins and that every one of those names exists (browser_harness._ipc.identify too); if not it exits 1 at once and names what is
missing, so a bump fails when the MCP server starts and not as a silently dropped click. After a bump, change PINS and re-run
tests/agent-browser.
"""
import atexit
import importlib.metadata
import os
import signal
import sys
import threading

PINS = {"browser-use": "1.0.2", "browser-harness": "0.1.13"}  # servers.json.tmpl pins browser-use; it pins browser-harness itself
PATCHED = (("browser_use.mcp.cli_mcp", "CLIMCPServer._attach"), ("browser_use.mcp.cli_mcp", "CLIMCPServer._ensure_namespace"),
           ("browser_harness.helpers", "cdp"), ("browser_harness.helpers", "new_tab"), ("browser_harness.helpers", "switch_tab"),
           ("browser_harness.helpers", "close_tab"), ("browser_harness.helpers", "current_tab"), ("browser_harness.helpers", "ensure_real_tab"),
           ("browser_harness.helpers", "_send"), ("browser_harness._ipc", "identify"))

NAME = os.environ.setdefault("BU_NAME", "mcp-%d" % os.getpid())  # before browser_harness is imported: it reads BU_NAME at import
OWN = NAME == "mcp-%d" % os.getpid()


def missing():
    """What the pinned packages must have and do not: wrong versions, then patched names."""
    found = []
    for package, pin in PINS.items():
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = None
        if version != pin:
            found.append("%s==%s is required, installed: %s" % (package, pin, version))
    if found:
        return found
    for module_name, dotted in PATCHED:
        try:
            owner = __import__(module_name, fromlist=["_"])
            for part in dotted.split("."):
                owner = getattr(owner, part)
        except (ImportError, AttributeError):
            found.append("%s.%s is missing" % (module_name, dotted))
    return found


problems = missing()
if problems:
    sys.exit("browser-use launcher: cannot patch the installed packages, nothing started.\n  " + "\n  ".join(problems) +
             "\n  Fix: re-pin %s and re-run tests/agent-browser (dot_local/share/browser-harness-mcp/server.py)." % ", ".join(
                 "%s==%s" % kv for kv in PINS.items()))

from browser_harness import _ipc, admin, helpers, paths  # noqa: E402
from browser_use.mcp import cli_mcp  # noqa: E402

CLOSED, LOST = "closed", "lost"


class Tab:
    """The tab this session is using, as the agent last chose it: a target id; None before the first call; CLOSED after the agent closed
    it; or LOST (with lost_id) once it vanished (closed from outside)."""

    state = None
    lost_id = None


_raw_cdp = helpers.cdp


CDP_TIMEOUT = 20.0  # what browser-use's own cdp wrapper waits (browser_use.repl.capture.CDP_TIMEOUT_S); harness's raw call gives up after 5 s


def _exists(target_id):
    # Target.getTargets takes no session, so asking cannot make the daemon re-attach to another page (a session command would).
    return any(t["targetId"] == target_id and t["type"] == "page"
               for t in _raw_cdp("Target.getTargets", _response_timeout=CDP_TIMEOUT)["targetInfos"])


def _refuse():
    if Tab.state == LOST:
        raise RuntimeError("The tab this session was using (%s) was closed, so nothing was done. Open a tab with new_tab(url), or attach to an "
                           "open one with switch_tab(id), then retry." % Tab.lost_id)
    if Tab.state == CLOSED:
        raise RuntimeError("This session has no tab: its tab was closed. Open one with new_tab(url), or attach to an open one with switch_tab(id).")


def cdp(method, *args, **kwargs):
    if not str(method).startswith("Target.") and (args[0] if args else kwargs.get("session_id")) is None:
        _refuse()  # browser-level calls need no tab; the rest act on the current one
    return _raw_cdp(method, *args, **kwargs)


def _emulate():
    # With a native dialog open the page's thread is frozen, so leave the tab alone until the agent handles the dialog.
    if not helpers._send({"meta": "pending_dialog"}).get("dialog"):
        _raw_cdp("Emulation.setFocusEmulationEnabled", enabled=True, _response_timeout=CDP_TIMEOUT)


def ensure_real_tab():
    """Report the tab this agent is on. The stock helper switches to the first real page in Chrome when the current tab looks internal
    (about:blank counts), and that page can belong to another agent or a person. current_tab() asks the daemon, not CDP, so refuse here."""
    _refuse()
    return helpers.current_tab()


def _remember(name, closes=False):
    original = getattr(helpers, name)

    def call(*args, **kwargs):
        target = args[0] if args else kwargs.get("target")
        target_id = (target.get("targetId") or target.get("target_id")) if isinstance(target, dict) else target
        before = Tab.state
        if not closes:
            Tab.state = None  # the agent is choosing a tab: lift the refusal for the helper's own calls
        try:
            result = original(*args, **kwargs)
        except BaseException:
            Tab.state = before
            raise
        if closes:
            if target_id in (None, Tab.state):
                Tab.state = CLOSED
        else:
            Tab.state = target_id if name == "switch_tab" and target_id else helpers.current_tab()["targetId"]
            _emulate()
        return result
    call.__name__, call.__doc__ = original.__name__, original.__doc__
    setattr(helpers, name, call)


_stock_attach = cli_mcp.CLIMCPServer._attach


def _attach(self):
    """browser_exec reaches this through _ensure_daemon; browser_screenshot calls it directly, so it is the one seam for both."""
    _stock_attach(self)
    if Tab.state not in (None, CLOSED, LOST) and not _exists(Tab.state):
        Tab.lost_id, Tab.state = Tab.state, LOST
    if Tab.state in (CLOSED, LOST):
        return  # no session command until the agent picks a tab: it would only attach the daemon to a replacement page
    _emulate()  # a failure here reaches the agent as the tool's error: swallowing it would bring back the silent dropped click
    if Tab.state is None:
        Tab.state = helpers.current_tab()["targetId"]


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


def _reap(pid):
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass


def stop_own_daemon():
    if OWN:
        try:
            pid = _ipc.identify(NAME, timeout=2.0)
            if pid:  # the daemon is this process's child: until it is waited for it stays a zombie, and restart_daemon waits 15 s for it to go
                threading.Thread(target=_reap, args=(pid,), daemon=True).start()
            admin.restart_daemon(NAME)
        except Exception:
            pass


# Installed before the first browser_exec: cli_mcp builds the exec namespace then, and star-imports helpers (cdp, new_tab, ...) into it.
helpers.cdp = cdp
helpers.ensure_real_tab = ensure_real_tab
for _name in ("new_tab", "switch_tab"):
    _remember(_name)
_remember("close_tab", closes=True)
cli_mcp.CLIMCPServer._attach = _attach

if OWN:
    stop_orphans()
    atexit.register(stop_own_daemon)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))

if __name__ == "__main__":
    from browser_use.cli import main

    sys.argv = ["browser-use", "--cli-mcp"]
    sys.exit(main())
