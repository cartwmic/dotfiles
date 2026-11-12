"""A closed tab fails loudly (dot_local/share/browser-harness-mcp/server.py).

The stock browser-use daemon, when the tab its session is using is closed from outside, quietly attaches to a fresh about:blank and the
next click_at_xy answers ok on nothing. The launcher refuses every call that acts on a tab, in browser_exec and browser_screenshot alike,
with a message naming the closed tab until the agent opens or switches to a tab.

Red control: the stock server (own daemon name, own tab) answers ok on about:blank. Green: the launcher raises, does nothing on the
replacement page, and recovers with new_tab. The tab is closed with Chrome's own /json/close/<exact id>; a local page logs every mouse event.
"""
import time
import unittest

from support import JourneyCase, StockMcp, close_from_outside, tabs


class ClosedTab(JourneyCase):
    def test_red_control_the_stock_server_answers_ok_on_about_blank(self):
        stock = StockMcp(self.chrome, name="repro-red")
        self.sessions.append(stock)
        tab = self.open_page(stock, "RED")
        close_from_outside(self.cdp, tab)
        before = {t["id"] for t in tabs(self.cdp)}
        stock.click()   # no error: silent success on nothing
        self.assertEqual(stock.run("print(js('location.href'))").strip(), "about:blank")
        self.assertEqual(self.clicks("RED"), [])
        self.assertTrue({t["id"] for t in tabs(self.cdp)} - before, "the stock daemon attaches a fresh about:blank")

    def test_green_the_launcher_refuses_until_the_agent_picks_a_tab(self):
        server = self.mcp()
        tab = self.open_page(server, "GREEN")
        server.click()
        self.wait_until(lambda: self.clicks("GREEN"), "the first click")
        close_from_outside(self.cdp, tab)
        after_close = {t["id"] for t in tabs(self.cdp)}
        for what, code in (("click_at_xy", "click_at_xy(200, 140)"), ("page_info", "print(page_info())"), ("js", "print(js('document.title'))"),
                           ("type_text", "type_text('x')"), ("cdp", "cdp('Page.reload')")):
            with self.subTest(call=what):
                with self.assertRaises(AssertionError) as raised:
                    server.run(code)
                self.assertIn("was closed, so nothing was done", str(raised.exception))
                self.assertIn(tab, str(raised.exception))   # names the tab that is gone
        failed, text = server.tool("browser_screenshot")   # its own path through the server: it skips browser_exec's daemon check
        self.assertTrue(failed)
        self.assertIn("was closed, so nothing was done", text)
        self.assertEqual(len(self.clicks("GREEN")), 1)
        self.assertEqual({t["id"] for t in tabs(self.cdp)}, after_close)   # the refused calls attached nothing: no fresh about:blank appeared
        # Recovery: open a tab, and the very next click lands on it.
        tab2 = self.open_page(server, "GREEN2")
        self.assertNotEqual(tab2, tab)
        server.click()
        self.wait_until(lambda: self.clicks("GREEN2"), "a click on the new tab")
        self.assertTrue(self.clicks("GREEN2")[0]["isTrusted"])
        failed, _ = server.tool("browser_screenshot")
        self.assertFalse(failed)

    def test_red_control_the_stock_ensure_real_tab_moves_a_closed_tab_session_onto_another_tab(self):
        owner = self.mcp()
        user_tab = self.open_page(owner, "USER")   # a page this session does not own
        stock = StockMcp(self.chrome, name="repro-red")
        self.sessions.append(stock)
        tab = self.open_page(stock, "RED")
        close_from_outside(self.cdp, tab)
        stock.click()   # answers ok on the fresh about:blank
        stock.run("ensure_real_tab()")   # what the server's own instructions say to do on a stale or internal tab
        self.assertEqual(stock.current_tab(), user_tab, [(t["id"][:6], t["url"][:30]) for t in tabs(self.cdp)])
        stock.click()
        self.wait_until(lambda: self.clicks("USER"), "the stray click")

    def test_green_ensure_real_tab_after_a_close_is_refused_and_attaches_nothing(self):
        owner = self.mcp()
        self.open_page(owner, "USER")
        server = self.mcp()
        tab = self.open_page(server, "GREEN")
        close_from_outside(self.cdp, tab)
        with self.assertRaises(AssertionError):
            server.click()   # the refusal
        with self.assertRaises(AssertionError) as raised:
            server.run("ensure_real_tab()")   # the server's instructions say to call it on a stale tab
        self.assertIn("was closed, so nothing was done", str(raised.exception))
        self.assertIn(tab, str(raised.exception))
        with self.assertRaises(AssertionError) as raised:
            server.click()   # still refused: ensure_real_tab did not lift it
        self.assertIn("was closed, so nothing was done", str(raised.exception))
        time.sleep(0.5)
        self.assertEqual(self.clicks("USER"), [], self.events)
        self.open_page(server, "GREEN2")   # new_tab still recovers
        server.click()
        self.wait_until(lambda: self.clicks("GREEN2"), "a click on the new tab")

    def test_green_switch_tab_also_recovers(self):
        server = self.mcp()
        tab = self.open_page(server, "SW")
        other = self.mcp()
        tab2 = self.open_page(other, "SW2")
        close_from_outside(self.cdp, tab)
        with self.assertRaises(AssertionError):
            server.click()
        server.run("switch_tab(%r)" % tab2)
        server.click()
        self.wait_until(lambda: self.clicks("SW2"), "a click on the tab it switched to")

    def test_green_closing_its_own_tab_also_leaves_no_silent_about_blank(self):
        server = self.mcp()
        tab = self.open_page(server, "OWN")
        server.run("close_tab(%r)" % tab)
        with self.assertRaises(AssertionError) as raised:
            server.click()
        self.assertIn("has no tab", str(raised.exception))
        self.open_page(server, "OWN2")
        server.click()
        self.wait_until(lambda: self.clicks("OWN2"), "a click after reopening")


if __name__ == "__main__":
    unittest.main()
