"""Journey: two agents drive a Chrome through the real browser-use MCP launcher (server.py), each in its own tab, and each click
reaches the page the agent opened.

The agents work as they will: browser_exec with new_tab, current_tab and click_at_xy. Before the launcher, Chrome dropped a click to a
background tab with no error (red control below: the stock server answers ok and the page sees nothing) and one shared daemon kept
one current tab. A local page logs every mouse event it receives (isTrusted included). Scratch Chrome and profile: see support.py.
"""
import time
import unittest

from support import JourneyCase, StockMcp

class ClickJourney(JourneyCase):
    def test_each_agent_clicks_its_own_tab(self):
        a, b = self.mcp(), self.mcp()
        tab_a = self.open_page(a, "A")
        tab_b = self.open_page(b, "B")   # on a shared daemon this moves A's current tab
        self.assertNotEqual(tab_a, tab_b)
        self.assertEqual(a.current_tab(), tab_a)
        a.click()
        b.click()
        self.wait_until(lambda: self.clicks("A") and self.clicks("B"), "a click on each page")
        time.sleep(0.5)   # a stray second click on either page would show up here
        self.assertEqual(len(self.clicks("A")), 1, self.events)
        self.assertEqual(len(self.clicks("B")), 1, self.events)
        for page in ("A", "B"):
            self.assertTrue(self.clicks(page)[0]["isTrusted"])
            self.assertEqual(self.clicks(page)[0]["vis"], "visible")   # the page saw itself visible and focused: focus emulation is on
            self.assertTrue(self.clicks(page)[0]["focus"])

    def test_red_control_the_stock_server_drops_the_click_on_a_background_tab(self):
        stock = StockMcp(self.chrome, name="repro-red")
        self.sessions.append(stock)
        self.open_page(stock, "RED")
        self.assertEqual(self.events_of("RED", "load")[0]["vis"], "hidden")
        stock.click()   # answers ok
        time.sleep(1.0)
        self.assertEqual(self.clicks("RED"), [], self.events)


if __name__ == "__main__":
    unittest.main()
