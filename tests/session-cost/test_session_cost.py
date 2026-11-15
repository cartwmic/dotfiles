"""session-cost end to end: a hand-written set of Claude Code logs in a scratch HOME, the real collect.py, the real
`session-cost` command, and dollars worked out by hand from the list prices in analyze.py.
Run: python3 -m unittest discover -s tests/session-cost

The logs (all times UTC, now = 2026-11-20T00:00Z, so "last 7d" is 11-13..11-20 and "prior 7d" is 11-06..11-13;
logs are complete from 2026-11-11T18:00Z, so the prior window is cut there):

  lead1.jsonl      Seat: Lead.  msg_A opus, written as 3 records (one per content block; the last one carries the real
                   usage, the first two a smaller output): cache write 1h 100K, cache read 1M, output 50K  = 0.80+0.20+1.00 = $2.00
                   msg_B opus: fresh input 250K, cache read 500K                                           = 1.00+0.10      = $1.10
                   a <synthetic> record with huge usage (must be ignored)
  lead1-copy.jsonl a resumed copy of lead1: carries msg_A again (counted once) and a new msg_C sonnet:
                   cache write 5m 100K, cache read 2M, output 10K                                          = 0.25+0.20+0.10 = $0.55
  lead1/subagents/agent-h.jsonl   no Seat line, so "helper of lead"; haiku:
                   msg_H1 prompt 100K (short-context rates): cache read 100K, output 1M  = 0.001+0.50 = $0.501
                   msg_H2 prompt 100,001 (long-context rates): cache read 100,001, output 1M = 0.00500005+2.50 = $2.50500005
  b1.jsonl         Seat: builder.  msg_S sonnet: fresh input 1M, output 100K                                = 2.00+1.00 = $3.00
                   msg_old opus on 2026-11-10 (before logs are complete): output 1M = $20, must not be counted anywhere
  r1.jsonl         Seat: Reviewer.  msg_P 2026-11-12T12:00 opus: fresh input 250K, output 25K = 1.00+0.50 = $1.50
                   msg_Q 2026-11-12T18:00 opus: output 50K = $1.00      (prior window: $2.50 over 6h = 0.25 day = $10/day)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARE = ROOT / "dot_local/share/token-efficiency"
COMMAND = ROOT / "dot_local/bin/executable_session-cost"
NOW = "2026-11-20T00:00:00Z"


def msg(mid, model, ts, *, inp=0, cw1h=0, cw5m=0, cr=0, out=0, blocks=1, partial_out=10):
    """The assistant records of one API request: `blocks` records with the same message id, the last with the final usage."""
    recs = []
    for i in range(blocks):
        last = i == blocks - 1
        usage = {"input_tokens": inp, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw1h + cw5m,
                 "cache_creation": {"ephemeral_1h_input_tokens": cw1h, "ephemeral_5m_input_tokens": cw5m},
                 "output_tokens": out if last else partial_out}
        block = [{"type": "thinking"}, {"type": "text", "text": "x"}, {"type": "tool_use", "id": "t%s%d" % (mid, i), "name": "Read", "input": {}}][i % 3]
        recs.append({"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": model, "usage": usage, "content": [block]}})
    return recs


def user(ts, text):
    return {"type": "user", "timestamp": ts, "entrypoint": "cli", "cwd": "/x", "message": {"role": "user", "content": text}}


OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"

FILES = {
    "lead1.jsonl": ("lead1", [user("2026-11-15T09:59:00Z", "Seat: Lead. Model: Opus 5.5 medium. Do the thing.")]
                    + msg("msg_A", OPUS, "2026-11-15T10:00:00Z", cw1h=100_000, cr=1_000_000, out=50_000, blocks=3)
                    + msg("msg_B", OPUS, "2026-11-15T11:00:00Z", inp=250_000, cr=500_000)
                    + msg("msg_syn", "<synthetic>", "2026-11-15T11:30:00Z", inp=9_000_000, out=9_000_000)),
    "lead1-copy.jsonl": ("lead1b", [user("2026-11-15T09:59:00Z", "Seat: Lead. Model: Opus 5.5 medium. Do the thing.")]
                         + msg("msg_A", OPUS, "2026-11-15T10:00:00Z", cw1h=100_000, cr=1_000_000, out=50_000, blocks=3)
                         + msg("msg_C", SONNET, "2026-11-15T12:00:00Z", cw5m=100_000, cr=2_000_000, out=10_000)),
    "lead1/subagents/agent-h.jsonl": ("lead1", [user("2026-11-15T10:20:00Z", "Read this file and say what it does.")]
                                      + msg("msg_H1", HAIKU, "2026-11-15T10:30:00Z", cr=100_000, out=1_000_000)
                                      + msg("msg_H2", HAIKU, "2026-11-15T10:45:00Z", cr=100_001, out=1_000_000)),
    "b1.jsonl": ("b1", [user("2026-11-10T11:00:00Z", "Seat: builder, Sonnet 5.5 (effort high). Build it.")]
                 + msg("msg_old", OPUS, "2026-11-10T12:00:00Z", out=1_000_000)
                 + msg("msg_S", SONNET, "2026-11-16T10:00:00Z", inp=1_000_000, out=100_000)),
    "r1.jsonl": ("r1", [user("2026-11-12T11:00:00Z", "Seat: Reviewer. Model: Opus 5.5 medium. Review it.")]
                 + msg("msg_P", OPUS, "2026-11-12T12:00:00Z", inp=250_000, out=25_000)
                 + msg("msg_Q", OPUS, "2026-11-12T18:00:00Z", out=50_000)),
}


def write_logs(home):
    proj = Path(home) / ".claude/projects/-proj"
    for rel, (session, records) in FILES.items():
        path = proj / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            for rec in records:
                fh.write(json.dumps(dict(rec, sessionId=session)) + "\n")


def run(args, home, **kw):
    env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=120, **kw)


class SessionCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.home = cls.tmp / "home"
        write_logs(cls.home)
        r = run([sys.executable, str(SHARE / "collect.py")], cls.home)   # default output: ~/.local/state/token-efficiency
        assert r.returncode == 0, r.stderr
        cls.collect_out = r.stdout
        cls.db = cls.home / ".local/state/token-efficiency/usage.sqlite"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def snapshot(self, *args, directory=None):
        d = directory or self.tmp / "snaps"
        r = run([sys.executable, str(SHARE / "session_cost.py"), "--now", NOW, "--snapshot", str(d), *args], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        return d

    def report(self, *args):
        d = self.snapshot(*args, directory=Path(tempfile.mkdtemp(dir=self.tmp)))
        return json.loads(next(d.glob("*.json")).read_text())

    def test_collect_counts_each_message_id_once(self):
        # A (written 3 times, and copied into a second file), B, C, H1, H2, S, old, P, Q: 9 requests; <synthetic> is not one
        self.assertIn("requests 9", self.collect_out)

    def test_last_window_dollars_per_seat_by_hand(self):
        w = self.report()["windows"][0]
        seats = w["seats"]
        self.assertAlmostEqual(seats["lead"]["list_usd"], 2.00 + 1.10 + 0.55)
        self.assertAlmostEqual(seats["builder"]["list_usd"], 3.00)
        self.assertAlmostEqual(seats["helper of lead"]["list_usd"], 0.501 + 2.50500005)   # haiku: short rate up to 100,000 prompt tokens, long rate above
        self.assertAlmostEqual(w["total"]["list_usd"], 3.65 + 3.00 + 0.501 + 2.50500005)
        # first request 11-15T10:00, last 11-16T10:00: exactly one day, so $/day equals the window $
        self.assertAlmostEqual(w["days"], 1.0)
        self.assertAlmostEqual(seats["lead"]["usd_per_day"], 3.65)
        self.assertAlmostEqual(w["total"]["usd_per_day"], 3.65 + 3.00 + 0.501 + 2.50500005)
        # average prompt = input + cache tokens: A 1.1M, B 750K, C 2.1M
        self.assertAlmostEqual(seats["lead"]["avg_prompt"], (1_100_000 + 750_000 + 2_100_000) / 3)
        self.assertEqual(seats["lead"]["requests"], 3)

    def test_prior_window_starts_where_logs_are_complete(self):
        w = self.report()["windows"][1]
        self.assertTrue(w["clipped"])
        self.assertEqual(list(w["seats"]), ["reviewer"])   # the $20 request on 11-10 is not here
        self.assertAlmostEqual(w["total"]["list_usd"], 2.50)
        self.assertAlmostEqual(w["days"], 0.25)
        self.assertAlmostEqual(w["total"]["usd_per_day"], 10.0)

    def test_table_says_list_price_and_the_first_complete_day(self):
        r = run([sys.executable, str(SHARE / "session_cost.py"), "--now", NOW], self.home, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("list-price cost per agent seat", out)
        self.assertIn("NOT subscription billing", out)
        self.assertIn("first complete PST day: 2026-11-12", out)
        self.assertIn("complete from 2026-11-11T18:00Z", out)
        row = next(line for line in out.splitlines() if line.startswith("lead "))
        self.assertIn("$3.65", row)
        self.assertIn("starts where complete logs start", out)   # the prior window was cut
        self.assertNotIn("$20", out)

    def test_window_with_no_requests_is_printed(self):
        r = run([sys.executable, str(SHARE / "session_cost.py"), "--now", "2026-12-30T00:00:00Z"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("no requests counted"), 2)

    def test_single_window_for_a_baseline(self):
        r = run([sys.executable, str(SHARE / "session_cost.py"), "--since", "2026-11-15T10:00:00Z", "--until", "2026-11-15T11:30:00Z"], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("window", r.stdout)
        self.assertNotIn("prior", r.stdout)
        lead = next(line for line in r.stdout.splitlines() if line.startswith("lead "))
        self.assertIn("$3.10", lead)   # A + B only; C is at 12:00

    def test_snapshot_is_dated_and_a_rerun_replaces_only_that_day(self):
        d = self.tmp / "snaps-days"
        for now in ("2026-11-19T12:00:00Z", "2026-11-20T12:00:00Z"):
            run([sys.executable, str(SHARE / "session_cost.py"), "--now", now, "--snapshot", str(d)], self.home)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["2026-11-19.json", "2026-11-20.json"])
        day19, day20 = (d / "2026-11-19.json").read_bytes(), (d / "2026-11-20.json").read_bytes()
        run([sys.executable, str(SHARE / "session_cost.py"), "--now", "2026-11-20T18:00:00Z", "--days", "1", "--snapshot", str(d)], self.home)
        self.assertEqual((d / "2026-11-19.json").read_bytes(), day19)           # an earlier day is never touched
        self.assertNotEqual((d / "2026-11-20.json").read_bytes(), day20)        # the same day is replaced
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["2026-11-19.json", "2026-11-20.json"])   # no temp file left

    def test_snapshot_keeps_a_per_day_per_seat_table(self):
        days = self.report()["days"]
        self.assertEqual(sorted(days), ["2026-11-12", "2026-11-15", "2026-11-16"])   # 11-10 is before complete logs
        self.assertAlmostEqual(days["2026-11-12"]["reviewer"]["list_usd"], 2.50)
        self.assertAlmostEqual(days["2026-11-15"]["lead"]["list_usd"], 3.65)
        self.assertAlmostEqual(days["2026-11-16"]["builder"]["list_usd"], 3.00)

    def test_timer_fires_at_the_moment_the_snapshot_day_changes(self):
        # Snapshots are named by PST day (UTC-8 all year). The timer must fire at PST midnight, 08:00 UTC, in winter and summer alike,
        # so the run's file is the new day and never the previous one.
        timer = (ROOT / "dot_config/systemd/user/session-cost.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 08:00:00 UTC", timer)
        sys.path.insert(0, str(SHARE))
        from datetime import datetime, timezone
        from session_cost import pst_day
        for month in (7, 12):   # summer (PDT) and winter (PST) in California
            before = datetime(2026, month, 15, 7, 59, 59, tzinfo=timezone.utc)
            at = datetime(2026, month, 15, 8, 0, 0, tzinfo=timezone.utc)
            self.assertNotEqual(pst_day(before), pst_day(at))
            self.assertEqual(pst_day(at), "2026-%02d-15" % month)
        d = self.snapshot(directory=self.tmp / "snaps-timer")   # NOW is 2026-11-20T00:00Z, which is PST day 11-19
        self.assertEqual([p.name for p in d.iterdir()], ["2026-11-19.json"])

    def test_database_is_replaced_whole(self):
        home = self.tmp / "home3"
        write_logs(home)
        for _ in range(2):
            self.assertEqual(run([sys.executable, str(SHARE / "collect.py")], home).returncode, 0)
        self.assertEqual(sorted(p.name for p in (home / ".local/state/token-efficiency").iterdir()), ["usage.sqlite"])

    def test_command_runs_from_path_with_default_database(self):
        r = run(["sh", str(COMMAND), "--now", NOW], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lead", r.stdout)

    def test_missing_database_says_what_to_do(self):
        empty = self.tmp / "empty-home"
        empty.mkdir()
        r = run(["sh", str(COMMAND)], empty)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--refresh", r.stderr)

    def test_refresh_rebuilds_the_database(self):
        home = self.tmp / "home2"
        write_logs(home)
        r = run(["sh", str(COMMAND), "--refresh", "--now", NOW], home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("$3.65", r.stdout)


if __name__ == "__main__":
    unittest.main()
