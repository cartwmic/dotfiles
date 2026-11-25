"""`session-cost workstreams` end to end: a hand-written set of Claude Code logs, a small T3 database and a small ledger in a scratch HOME,
the real command (which runs the real collect.py first), and dollars worked out by hand from the list prices in analyze.py.
Run: python3 -m unittest discover -s tests/session-cost

The T3 thread tree (a thread's lineage parent is the one above it) and who is a ledger workstream:

  T-coord  "Coordinator"      ledger workstream "Coordinator ops" (the umbrella: every lead below was launched under it)
    T-a    lead of A          ledger workstream "Alpha"
      T-b  builder under A    (no ledger row)  has a helper (Agent-tool subagent) file
    T-bb   lead of B          ledger workstream "Beta" (named in the `conversation` column, not `pane`)
  T-g      shared thread      ledger workstreams "Gamma" and "Delta" both point at it
  T-side   "Side thread"      no ledger workstream above it
  (a session with no T3 thread at all)

Requests, all opus unless noted, output tokens only (opus output is $20 per million):
  coord 50K = $1.00   leadA 100K = $2.00   builder 200K = $4.00   helper of builder (haiku, 1M output, short prompt) = $0.50
  leadB 300K = $6.00  shared 10K = $0.20   side 5K = $0.10        no-thread 25K = $0.50
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_session_cost import HAIKU, OPUS, SHARE, msg, user  # noqa: E402

sys.path.insert(0, str(SHARE))
import workstreams  # noqa: E402

COMMAND = SHARE / "session_cost.py"
T = "2026-11-15T10:00:00Z"


def session_file(sid, out, model=OPUS):
    return [user("2026-11-15T09:59:00Z", "do the work")] + msg("msg_" + sid, model, T, out=out)


LOGS = {   # path under ~/.claude/projects/-proj -> (session id, records)
    "s-coord.jsonl": ("s-coord", session_file("coord", 50_000)),
    "s-a.jsonl": ("s-a", session_file("a", 100_000)),
    "s-b.jsonl": ("s-b", session_file("b", 200_000)),
    "s-b/subagents/agent-h.jsonl": ("agent-h", session_file("h", 1_000_000, HAIKU)),
    "s-bb.jsonl": ("s-bb", session_file("bb", 300_000)),
    "s-g.jsonl": ("s-g", session_file("g", 10_000)),
    "s-side.jsonl": ("s-side", session_file("side", 5_000)),
    "s-none.jsonl": ("s-none", session_file("none", 25_000)),
}
THREADS = {   # thread -> (title, parent thread, claude session id)
    "T-coord": ("Coordinator", None, "s-coord"),
    "T-a": ("Lead A", "T-coord", "s-a"),
    "T-b": ("Builder", "T-a", "s-b"),
    "T-bb": ("Lead B", "T-coord", "s-bb"),
    "T-g": ("Shared", None, "s-g"),
    "T-side": ("Side thread", None, "s-side"),
}
LEDGER = [("Coordinator ops", "t3:T-coord", None), ("Alpha", "t3:T-a", "t3:T-a"), ("Beta", "w1:p2", "t3:T-bb"),
          ("Gamma", "t3:T-g", None), ("Delta", None, "t3:T-g"), ("Old tmux one", "w9:p1", "ws-old-head")]


def write_t3(path):
    db = sqlite3.connect(path)
    db.execute("create table orchestration_v2_projection_threads(thread_id text, title text, payload_json text)")
    db.execute("create table orchestration_v2_projection_provider_threads(payload_json text)")
    for thread, (title, parent, session) in THREADS.items():
        db.execute("insert into orchestration_v2_projection_threads values(?,?,?)",
                   (thread, title, json.dumps({"lineage": {"parentThreadId": parent, "rootThreadId": thread}})))
        db.execute("insert into orchestration_v2_projection_provider_threads values(?)",
                   (json.dumps({"appThreadId": thread, "nativeThreadRef": {"nativeId": session}}),))
    db.commit()
    db.close()


def write_ledger(path):
    db = sqlite3.connect(path)
    db.execute("create table workstreams(name text, pane text, conversation text)")
    db.executemany("insert into workstreams values(?,?,?)", LEDGER)
    db.commit()
    db.close()


def run(args, home):
    env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(COMMAND), *args], capture_output=True, text=True, env=env, timeout=120)


def parse(stdout):
    """label -> list $ for every top-level row (not the indented model rows)."""
    rows = {}
    for line in stdout.splitlines():
        m = re.match(r"^(\S.*?)\s{2,}[\d,]+\s+.*\$(\d+\.\d\d)\s+[\d.]+%$", line)
        if m:
            rows[m.group(1)] = float(m.group(2))
    return rows


class WorkstreamsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.home = cls.tmp / "home"
        proj = cls.home / ".claude/projects/-proj"
        for rel, (session, records) in LOGS.items():
            path = proj / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(dict(rec, sessionId=session)) + "\n" for rec in records))
        cls.t3, cls.ledger = cls.tmp / "t3.sqlite", cls.tmp / "ledger.sqlite"
        write_t3(cls.t3)
        write_ledger(cls.ledger)
        cls.args = ["workstreams", "--since", "2026-11-15", "--until", "2026-11-16", "--t3-db", str(cls.t3), "--ledger", str(cls.ledger)]
        cls.result = run(cls.args, cls.home)   # no usage.sqlite exists yet: the command has to collect first
        cls.rows = parse(cls.result.stdout)

    def test_the_command_collects_first_and_prints_the_report(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        self.assertTrue((self.home / ".local/state/token-efficiency/usage.sqlite").exists())

    # The attribution check, kept as a function so the RED control below can run it against the old rule.
    def check_attribution(self, rows):
        rows = {k: rows.get(k, 0.0) for k in ("Alpha", "Beta", "Coordinator ops", "Delta / Gamma", workstreams.NO_WORKSTREAM, workstreams.NO_THREAD)}
        self.assertAlmostEqual(rows["Alpha"], 2.00 + 4.00 + 0.50)    # lead, its builder, and the builder's helper
        self.assertAlmostEqual(rows["Beta"], 6.00)                    # named by `conversation`, not `pane`
        self.assertAlmostEqual(rows["Coordinator ops"], 1.00)         # only its own session: the leads under it are not its spend
        self.assertAlmostEqual(rows["Delta / Gamma"], 0.20)           # two workstreams on one thread: shown under both names
        self.assertAlmostEqual(rows[workstreams.NO_WORKSTREAM], 0.10)
        self.assertAlmostEqual(rows[workstreams.NO_THREAD], 0.50)

    def test_each_session_lands_on_the_nearest_ledger_workstream_above_it(self):
        self.check_attribution(self.rows)

    def test_old_rule_red_control_attributing_to_the_lineage_root_fails_the_check(self):
        def root_rule(thread, parent, ledger):   # the old behaviour: the workstream of the top of the tree
            top = workstreams.root_of(thread, parent)
            return ' / '.join(ledger[top]) if top in ledger else None
        real = workstreams.workstream_of
        workstreams.workstream_of = root_rule
        try:
            db = str(self.home / ".local/state/token-efficiency/usage.sqlite")
            rep = workstreams.build(db, workstreams.load_t3(str(self.t3)), workstreams.load_ledger(str(self.ledger)),
                                    "2026-11-15T00:00:00.000Z", "2026-11-16T00:00:00.000Z")
            wrong = {name: g["total"]["usd"] for name, g in rep["groups"].items()}
        finally:
            workstreams.workstream_of = real
        self.assertAlmostEqual(wrong["Coordinator ops"], 1.00 + 2.00 + 4.00 + 0.50 + 6.00)   # everything under the coordinator
        with self.assertRaises(AssertionError):
            self.check_attribution(wrong)

    def test_every_dollar_is_in_a_row_and_matches_the_per_seat_report(self):
        total = 1.00 + 2.00 + 4.00 + 0.50 + 6.00 + 0.20 + 0.10 + 0.50
        self.assertAlmostEqual(self.rows["TOTAL"], total)
        self.assertAlmostEqual(sum(v for k, v in self.rows.items() if k != "TOTAL"), total)
        snap = self.tmp / "snap"
        r = run(["--now", "2026-11-20T00:00:00Z", "--since", "2026-11-15T00:00:00Z", "--until", "2026-11-16T00:00:00Z", "--snapshot", str(snap)], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        window = json.loads(next(snap.glob("*.json")).read_text())["windows"][0]
        self.assertAlmostEqual(window["total"]["list_usd"], self.rows["TOTAL"])

    def test_tokens_are_split_by_model_and_kind(self):
        self.assertRegex(self.result.stdout, r"(?m)^    claude-opus-5-5\s+2\s+0\s+300\.00K\s+0\s+0\s+\$6\.00\s+")     # Alpha: lead + builder, 100K + 200K output
        self.assertRegex(self.result.stdout, r"(?m)^    claude-haiku-5-5\s+1\s+0\s+1\.00M\s+0\s+0\s+\$0\.50\s+")      # the helper

    def test_unmapped_rows_show_their_share_and_what_is_inside(self):
        self.assertIn("    in: Side thread", self.result.stdout)
        self.assertIn("    in: -proj", self.result.stdout)
        share = re.search(r"unmapped (\d+\.\d)%", self.result.stdout)
        self.assertEqual(share.group(1), "%.1f" % (100 * 0.60 / 14.30))

    def test_the_run_is_logged_as_one_json_line(self):
        lines = (self.home / ".local/state/token-efficiency/log.jsonl").read_text().splitlines()
        rec = json.loads(lines[0])
        self.assertEqual((rec["action"], rec["outcome"], rec["collected"], rec["requests"]), ("workstreams", "ok", True, 8))
        self.assertAlmostEqual(rec["list_usd"], 14.30)
        self.assertAlmostEqual(rec["unmapped_share"], 0.60 / 14.30, places=3)

    def test_a_missing_database_fails_the_run_and_the_log_says_so(self):
        r = run(self.args[:-2] + ["--ledger", str(self.tmp / "nope.sqlite"), "--no-collect"], self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ledger not found", r.stderr)
        rec = json.loads((self.home / ".local/state/token-efficiency/log.jsonl").read_text().splitlines()[-1])
        self.assertEqual((rec["action"], rec["outcome"]), ("workstreams", "failed"))

    def test_the_databases_are_opened_read_only(self):
        before = (self.t3.stat().st_mtime_ns, self.ledger.stat().st_mtime_ns)
        self.assertEqual(run(self.args + ["--no-collect"], self.home).returncode, 0)
        self.assertEqual((self.t3.stat().st_mtime_ns, self.ledger.stat().st_mtime_ns), before)
        with self.assertRaises(sqlite3.OperationalError):
            workstreams.readonly(str(self.ledger)).execute("insert into workstreams values('x', null, null)")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)


class WalkTest(unittest.TestCase):
    def test_a_loop_in_the_lineage_ends_and_finds_nothing(self):
        self.assertIsNone(workstreams.workstream_of("a", {"a": "b", "b": "a"}, {}))
        self.assertEqual(workstreams.root_of("a", {"a": "b", "b": "a"}) in ("a", "b"), True)


if __name__ == "__main__":
    unittest.main()
