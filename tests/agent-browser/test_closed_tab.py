"""A closed tab fails loudly (dot_local/share/browser-harness-mcp/server.py).

The stock browser-use daemon, when the tab its session is using is closed from outside, quietly attaches to a fresh about:blank and the
next click_at_xy answers ok on nothing. The launcher refuses every call that acts on a tab, in browser_exec and browser_screenshot alike,
with a message naming the closed tab until the agent opens or switches to a tab.

Red control: the stock server (own daemon name, own tab) answers ok on about:blank. Green: the launcher raises, does nothing on the
replacement page, and recovers with new_tab. The tab is closed with Chrome's own /json/close/<exact id>; a local page logs every mouse event.
"""
import unittest

from support import JourneyCase, StockMcp, close_from_outside


class ClosedTab(JourneyCase):
    def test_red_control_the_stock_server_answers_ok_on_about_blank(self):
        stock = StockMcp(self.chrome, name="repro-red")
        self.sessions.append(stock)
        tab = self.open_page(stock, "RED")
        close_from_outside(self.cdp, tab)
        stock.click()   # no error: silent success on nothing
        self.assertEqual(stock.run("print(js('location.href'))").strip(), "about:blank")
        self.assertEqual(self.clicks("RED"), [])

    def test_green_the_launcher_refuses_until_the_agent_picks_a_tab(self):
        server = self.mcp()
        tab = self.open_page(server, "GREEN")
        server.click()
        self.wait_until(lambda: self.clicks("GREEN"), "the first click")
        close_from_outside(self.cdp, tab)
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
        self.assertEqual(len(self.clicks("GREEN")), 1)   # nothing reached any page
        # Recovery: open a tab, and the very next click lands on it.
        tab2 = self.open_page(server, "GREEN2")
        self.assertNotEqual(tab2, tab)
        server.click()
        self.wait_until(lambda: self.clicks("GREEN2"), "a click on the new tab")
        self.assertTrue(self.clicks("GREEN2")[0]["isTrusted"])
        failed, _ = server.tool("browser_screenshot")
        self.assertFalse(failed)

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
