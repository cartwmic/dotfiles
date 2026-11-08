"""A closed tab fails loudly (dot_local/share/browser-harness-mcp/server.py).

The stock browser-harness daemon, when the tab its session is using is closed from outside, quietly attaches to a fresh about:blank and
the next browser_click answers {"ok": true} on nothing. The launcher refuses every action tool with a message naming the closed tab until
the agent opens or switches to a tab.

Red control: the stock server (own daemon name, own tab) answers ok on about:blank. Green: the launcher raises, does nothing on the replacement
page, and recovers with browser_new_tab. The tab is closed with Chrome's own /json/close/<exact id> on the agent Chrome (127.0.0.1:9333);
a local page logs every mouse event. Skips without macOS and the agent Chrome.
"""
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

import test_click_journey as journey

STOCK_NAME = "repro-red-%d" % os.getpid()


class StockMcp(journey.Mcp):
    """The unmodified server, in a daemon of its own so it never touches the shared one."""

    def __init__(self):
        env = dict(os.environ, BU_CDP_URL=journey.CDP, BU_NAME=STOCK_NAME)
        self.p = subprocess.Popen(["uvx", "--from", "browser-harness[mcp]==0.1.13", "browser-harness-mcp"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd="/tmp")
        self.n = 0
        self.call_raw("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "closed-tab", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def close(self):
        super().close()
        subprocess.run(["uvx", "--from", "browser-harness[mcp]==0.1.13", "python", "-I", "-c",
                        "from browser_harness.admin import restart_daemon; restart_daemon(%r)" % STOCK_NAME],
                       env=dict(os.environ, BU_CDP_URL=journey.CDP), capture_output=True, timeout=60, cwd="/tmp")


def close_from_outside(target_id):
    urllib.request.urlopen("%s/json/close/%s" % (journey.CDP, target_id), timeout=10).read()
    deadline = time.time() + 10
    while time.time() < deadline:  # wait until Chrome no longer lists it
        listing = json.loads(urllib.request.urlopen(journey.CDP + "/json/list", timeout=10).read())
        if all(t["id"] != target_id for t in listing):
            return
        time.sleep(0.1)
    raise AssertionError("tab %s did not close" % target_id)


@unittest.skipUnless(sys.platform == "darwin" and journey.chrome_up(), "needs macOS and the agent Chrome on 127.0.0.1:9333")
class ClosedTab(journey.ClickJourney):
    """Reuses the local page and logging server of the click journey (its own test is not repeated here)."""

    test_each_agent_clicks_its_own_tab = None

    def setUp(self):
        super().setUp()
        self.opened = []

    def tearDown(self):
        super().tearDown()
        for tab in self.opened:  # belt and braces: close each tab this test opened, by its exact id
            try:
                urllib.request.urlopen("%s/json/close/%s" % (journey.CDP, tab), timeout=10).read()
            except Exception:
                pass

    def open_page(self, server, name):
        tab = server.tool("browser_new_tab", url=self.base + "?page=" + name)["targetId"]
        self.opened.append(tab)
        self.wait_until(lambda: self.events_of(name, "load"), "the page to load")
        return tab

    def test_red_control_the_stock_server_answers_ok_on_about_blank(self):
        stock = StockMcp()
        self.sessions.append(stock)
        tab = self.open_page(stock, "RED")
        close_from_outside(tab)
        answer = stock.tool("browser_click", x=200, y=140)  # no error: silent success on nothing
        self.assertEqual(answer, {"ok": True})
        self.assertEqual(self.clicks("RED"), [])

    def test_green_the_launcher_refuses_until_the_agent_picks_a_tab(self):
        server = journey.Mcp()
        self.sessions.append(server)
        tab = self.open_page(server, "GREEN")
        server.tool("browser_click", x=200, y=140)
        self.wait_until(lambda: self.clicks("GREEN"), "the first click")
        close_from_outside(tab)
        for name, args in (("browser_click", {"x": 200, "y": 140}), ("browser_page_info", {}), ("browser_js", {"expression": "document.title"}),
                           ("browser_type", {"text": "x"}), ("browser_cdp", {"method": "Page.reload"})):
            with self.subTest(tool=name):
                with self.assertRaises(AssertionError) as raised:
                    server.tool(name, **args)
                self.assertIn("was closed, so nothing was done", str(raised.exception))
                self.assertIn(tab, str(raised.exception))  # names the tab that is gone
        self.assertEqual(len(self.clicks("GREEN")), 1)  # nothing reached any page
        # Recovery: open a tab, and the very next click lands on it.
        tab2 = self.open_page(server, "GREEN2")
        self.assertNotEqual(tab2, tab)
        server.tool("browser_click", x=200, y=140)
        self.wait_until(lambda: self.clicks("GREEN2"), "a click on the new tab")
        self.assertTrue(self.clicks("GREEN2")[0]["isTrusted"])
        server.tool("browser_close_tab", target=tab2)

    def test_green_closing_its_own_tab_also_leaves_no_silent_about_blank(self):
        server = journey.Mcp()
        self.sessions.append(server)
        tab = self.open_page(server, "OWN")
        server.tool("browser_close_tab", target=tab)
        with self.assertRaises(AssertionError) as raised:
            server.tool("browser_click", x=200, y=140)
        self.assertIn("has no tab", str(raised.exception))
        tab2 = self.open_page(server, "OWN2")
        server.tool("browser_click", x=200, y=140)
        self.wait_until(lambda: self.clicks("OWN2"), "a click after reopening")
        server.tool("browser_close_tab", target=tab2)


if __name__ == "__main__":
    unittest.main()
