"""t3_lineage.py (the walk up T3's thread tree) and thread_rank.py (its command line), tested on their own.

workstream-rank's own suite (test_workstream_rank.py) covers them through the shell script; these pin the modules' contracts
that token-efficiency/workstreams.py also relies on.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).resolve().parents[2] / "dot_local/share/workstream-rank"
sys.path.insert(0, str(HELPERS))
import t3_lineage  # noqa: E402

THREAD_RANK = HELPERS / "thread_rank.py"


class Nearest(unittest.TestCase):
    def test_the_thread_itself_when_it_is_an_owner(self):
        self.assertEqual(t3_lineage.nearest("a", {"a": "b"}, {"a": 1, "b": 2}), 1)

    def test_the_nearest_owner_above(self):
        self.assertEqual(t3_lineage.nearest("a", {"a": "b", "b": "c", "c": "d"}, {"c": "C", "d": "D"}), "C")

    def test_none_when_no_owner_is_above(self):
        self.assertIsNone(t3_lineage.nearest("a", {"a": "b"}, {"z": 1}))

    def test_a_loop_ends(self):
        self.assertIsNone(t3_lineage.nearest("a", {"a": "b", "b": "a"}, {}))

    def test_a_thread_with_no_name_is_not_walked(self):
        self.assertIsNone(t3_lineage.nearest("", {}, {"": 1}))


class WithDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "statev2.sqlite"
        db = sqlite3.connect(self.path)
        db.execute("create table orchestration_v2_projection_threads(thread_id text primary key, title text, payload_json text)")
        for thread, payload in (("lead", {"lineage": None}),
                                ("child", {"lineage": {"parentThreadId": "lead", "rootThreadId": "root"}}),
                                ("grandchild", {"lineage": {"parentThreadId": "child"}}),
                                ("bare", {})):
            db.execute("insert into orchestration_v2_projection_threads values(?, ?, ?)", (thread, thread, json.dumps(payload)))
        db.commit()
        db.close()

    def test_parent_from_payload(self):
        self.assertEqual(t3_lineage.parent_from_payload(json.dumps({"lineage": {"parentThreadId": "x"}})), "x")
        self.assertIsNone(t3_lineage.parent_from_payload(json.dumps({"lineage": None})))
        self.assertIsNone(t3_lineage.parent_from_payload(json.dumps({})))

    def test_parents_reads_one_thread_at_a_time(self):
        parents = t3_lineage.Parents(str(self.path))
        self.addCleanup(parents.close)
        self.assertEqual(parents.get("child"), "lead")
        self.assertIsNone(parents.get("lead"))
        self.assertIsNone(parents.get("bare"))
        self.assertEqual(parents.get("nobody", "default"), "default")

    def test_the_database_is_opened_read_only(self):
        with self.assertRaises(sqlite3.OperationalError):
            t3_lineage.readonly(str(self.path)).execute("delete from orchestration_v2_projection_threads")

    def test_nearest_walks_the_database(self):
        parents = t3_lineage.Parents(str(self.path))
        self.addCleanup(parents.close)
        self.assertEqual(t3_lineage.nearest("grandchild", parents, {"lead": "L"}), "L")

    def thread_rank(self, thread, panes, db=None):
        env = {"PATH": os.environ["PATH"], "HOME": self.tmp.name, "WORKSTREAM_RANK_T3_DB": str(db or self.path)}
        return subprocess.run([sys.executable, str(THREAD_RANK), thread], input=panes, env=env, capture_output=True, text=True, timeout=20)

    def test_thread_rank_prints_the_pane_value_of_the_nearest_owner(self):
        p = self.thread_rank("grandchild", "t3:lead\nt3:other\n-\n")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "t3:lead\n", ""))

    def test_thread_rank_prints_nothing_when_there_is_none(self):
        p = self.thread_rank("grandchild", "t3:other\nw1A:pG\n")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_thread_rank_ignores_values_that_are_not_t3_references(self):
        p = self.thread_rank("grandchild", "lead\n")
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_thread_rank_says_when_it_cannot_read_the_database(self):
        p = self.thread_rank("grandchild", "t3:lead\n", db=Path(self.tmp.name) / "missing.sqlite")
        self.assertEqual((p.returncode, p.stdout), (3, ""))
        self.assertIn("cannot read", p.stderr)

    def test_thread_rank_wants_one_argument(self):
        env = {"PATH": os.environ["PATH"], "HOME": self.tmp.name}
        p = subprocess.run([sys.executable, str(THREAD_RANK)], input="", env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 2)

    def test_thread_rank_finds_the_database_under_t3code_home(self):
        home = Path(self.tmp.name) / "t3home"
        (home / "userdata").mkdir(parents=True)
        (home / "userdata" / "statev2.sqlite").write_bytes(self.path.read_bytes())
        env = {"PATH": os.environ["PATH"], "HOME": str(Path(self.tmp.name) / "elsewhere"), "T3CODE_HOME": str(home)}
        p = subprocess.run([sys.executable, str(THREAD_RANK), "child"], input="t3:lead\n", env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual((p.returncode, p.stdout), (0, "t3:lead\n"))


if __name__ == "__main__":
    unittest.main()
