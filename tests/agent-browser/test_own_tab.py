"""Two MCP processes on one Chrome each keep their own tab (server.py: BU_NAME mcp-<pid>, a daemon per process).

The stock server gives every process the daemon "default" with one current tab: B's new_tab moved A's tab, and A's next js or click
landed on B's page. Here A's tab stays A's through everything B does, B can still attach to A's tab on purpose without moving A, and
each process's daemon is gone when the process exits.
"""
import time
import unittest
from pathlib import Path

from support import JourneyCase, StockMcp


class OwnTab(JourneyCase):
    def where(self, server):
        return server.run("print(js('location.search'))").strip()

    def test_a_process_keeps_its_tab_whatever_the_other_does(self):
        a, b = self.mcp(), self.mcp()
        tab_a = self.open_page(a, "A")
        tab_b = self.open_page(b, "B")
        self.assertEqual((a.current_tab(), b.current_tab()), (tab_a, tab_b))
        self.assertEqual((self.where(a), self.where(b)), ("?page=A", "?page=B"))
        # B attaches to A's tab on purpose: B moves, A does not.
        b.run("switch_tab(%r)" % tab_a)
        self.assertEqual(b.current_tab(), tab_a)
        self.assertEqual(a.current_tab(), tab_a)
        # B opens another tab: A is still on its own.
        self.open_page(b, "B2")
        self.assertEqual(self.where(a), "?page=A")
        a.click()
        self.wait_until(lambda: self.clicks("A"), "A's click on A's page")
        self.assertEqual(self.clicks("B2") + self.clicks("B"), [], self.events)

    def test_red_control_the_stock_server_shares_one_tab_between_processes(self):
        a, b = StockMcp(self.chrome), StockMcp(self.chrome)
        self.sessions += [a, b]
        tab_a = self.open_page(a, "A")
        self.open_page(b, "B")
        self.assertNotEqual(a.current_tab(), tab_a)   # B's new_tab moved A's tab
        self.assertEqual(self.where(a), "?page=B")

    def test_red_control_the_stock_ensure_real_tab_moves_a_fresh_session_onto_another_processes_tab(self):
        owner = self.mcp()
        user_tab = self.open_page(owner, "USER")
        stock = StockMcp(self.chrome, name="repro-red")
        self.sessions.append(stock)
        stock.run("ensure_real_tab()")   # the server's instructions: "if the current tab is stale or internal, call ensure_real_tab()"
        self.assertEqual(stock.current_tab(), user_tab)
        stock.click()
        self.wait_until(lambda: self.clicks("USER"), "the stray click")

    def test_ensure_real_tab_reports_the_sessions_own_tab_and_never_switches(self):
        owner = self.mcp()
        user_tab = self.open_page(owner, "USER")
        fresh = self.mcp()   # on its dedicated blank tab, which counts as "internal" to the stock helper
        reported = fresh.run("print('TID=' + ensure_real_tab()['targetId'])").split("TID=")[1].split()[0]
        self.assertNotEqual(reported, user_tab)
        self.assertEqual(fresh.current_tab(), reported)   # it reported where it already was
        fresh.click()
        own = self.open_page(fresh, "OWN")
        fresh.run("ensure_real_tab()")
        self.assertEqual(fresh.current_tab(), own)   # on a real page of its own, still there
        fresh.click()
        self.wait_until(lambda: self.clicks("OWN"), "the click on its own page")
        time.sleep(0.5)
        self.assertEqual(self.clicks("USER"), [], self.events)

    def test_each_process_runs_its_own_daemon_and_stops_it_at_exit(self):
        a, b = self.mcp(), self.mcp()
        self.open_page(a, "A")
        self.open_page(b, "B")
        runtime = Path(self.chrome.env["BH_RUNTIME_DIR"])
        names = {s: s.run("import os; print(os.environ['BU_NAME'])").strip() for s in (a, b)}
        self.assertNotEqual(names[a], names[b])
        self.assertTrue(all(n.startswith("mcp-") for n in names.values()), names)
        pid_file = {s: runtime / ("bu-%s.pid" % n) for s, n in names.items()}   # a daemon's pid file is named after its BU_NAME
        pids = {s: f.read_text().strip() for s, f in pid_file.items()}
        self.assertEqual(len(set(pids.values())), 2, pids)   # two daemons, two pids
        a.close()
        self.wait_until(lambda: not pid_file[a].exists(), "A's daemon to stop with A")
        self.assertTrue(pid_file[b].exists())   # B's stays
        self.assertEqual(self.where(b), "?page=B")


if __name__ == "__main__":
    unittest.main()
