"""Tests for agent-events. Fixtures are synthetic Pi session files; nothing real is read."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CLI = HERE / "agent_events.py"
sys.path.insert(0, str(HERE))
import agent_events as ae  # noqa: E402

T = 1_790_000_000_000
SENTINEL = "SENTINEL-hunter2-Zq9"


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat().replace("+00:00", "Z")


class Fixture:
    """Builds one Pi v3 session file."""

    def __init__(self, session_id="sess-1", cwd="/work/proj", start=T):
        self.entries = []
        self.n = 0
        self.entry({"type": "session", "id": session_id, "cwd": cwd, "version": 3}, start, eid=session_id)

    def entry(self, body, ts, eid=None):
        self.n += 1
        e = dict(body)
        e.setdefault("id", eid or f"{self.entries[0]['id'] if self.entries else 'x'}-e{self.n}")
        e["timestamp"] = iso(ts)
        self.entries.append(e)
        return e["id"]

    def user(self, ts, text=f"please do {SENTINEL}"):
        return self.entry({"type": "message", "message": {"role": "user", "timestamp": ts, "content": text}}, ts)

    def llm(self, ts, end=None, cost=0.01, stop="toolUse", out=100, fresh=10, cr=0, cw=0, calls=(),
            model="m-1", err=None, stamp=True, duration=None, first=None, eid=None):
        content = [{"type": "text", "text": f"answer {SENTINEL}"}]
        content += [{"type": "toolCall", "id": c, "name": "bash", "arguments": {"command": SENTINEL}} for c in calls]
        msg = {"role": "assistant", "timestamp": ts, "provider": "p", "model": model, "api": "a",
               "stopReason": stop, "content": content,
               "usage": {"input": fresh, "output": out, "cacheRead": cr, "cacheWrite": cw,
                         "totalTokens": fresh + out + cr + cw,
                         "cost": {"total": cost, "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}}
        if err:
            msg["errorMessage"] = err
        if duration is not None:
            msg["durationMs"] = duration
        i = self.entry({"type": "message", "message": msg}, end or ts, eid=eid)
        if stamp and end:
            d = {"version": 5, "role": "assistant", "timestamp": ts, "completedAt": end,
                 "metadata": {"provider": "p", "model": model}}
            if first is not None:
                d["firstContentAt"] = first
            self.entry({"type": "custom", "customType": "pi-stamp", "data": d}, end)
        return i

    def tool(self, call_id, name, start, end, error=False, nested=(), details=None, stamp=True, duration=True):
        msg = {"role": "toolResult", "toolCallId": call_id, "toolName": name, "isError": error,
               "timestamp": end, "content": [{"type": "text", "text": f"output {SENTINEL}"}]}
        if duration:
            msg["durationMs"] = end - start
        if details is not None:
            msg["details"] = details
        if nested:
            msg["nestedCalls"] = {"complete": True, "calls": [
                {"id": f"{call_id}/{i + 1}", "name": n, "status": "ok", "durationMs": d,
                 "arguments": {"command": cmd}} for i, (n, d, cmd) in enumerate(nested)]}
        i = self.entry({"type": "message", "message": msg}, end)
        if stamp:
            self.entry({"type": "custom", "customType": "pi-stamp", "data": {
                "version": 1, "kind": "tool", "toolCallId": call_id, "toolName": name,
                "startedAt": start, "completedAt": end, "outcome": "error" if error else "success"}}, end)
        return i

    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(e) for e in self.entries) + "\n")
        return path


def standard_session():
    f = Fixture()
    f.entry({"type": "session_info", "name": f"name {SENTINEL}"}, T + 10)
    f.user(T + 1000)
    f.llm(T + 1500, T + 4500, cost=0.10, cr=1000, cw=50, calls=["c1"], first=T + 3000)
    f.tool("c1", "codemode", T + 4500, T + 14500,
           nested=[("bash", 6000, f"sleep 5 && echo {SENTINEL}"), ("read", 100, "x"), ("edit", 50, "y")])
    f.llm(T + 14600, T + 17600, cost=0.05, calls=["c2"])
    f.tool("c2", "ask_user_question", T + 17600, T + 77600, details={"cancelled": False})
    f.llm(T + 77700, T + 79700, cost=0.02, stop="stop", out=100)
    f.user(T + 200000)
    f.llm(T + 200500, T + 201500, cost=0.01, stop="error", out=0, err=f"429 rate limit {SENTINEL}")
    return f


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "sessions"
        self.db = Path(self._tmp.name) / "data" / "events.sqlite"

    def top(self, name="--work-proj--/2026-10-01T00-00-00-000Z_sess-1.jsonl"):
        return self.root / name

    def build(self, **kw):
        return ae.build(self.root, self.db, **kw)

    def q(self, sql, *params):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()


class StampedRollups(Base):
    def test_session_turn_and_phase_numbers(self):
        standard_session().write(self.top())
        res = self.build()
        self.assertEqual(res["sessions"], 1)
        s = self.q("SELECT * FROM sessions")[0]
        self.assertEqual(s["timing_quality"], "stamped")
        self.assertEqual((s["turns"], s["llm_calls"], s["tool_calls"], s["nested_calls"]), (2, 4, 2, 3))
        self.assertEqual(s["wall_ms"], 201500)
        self.assertEqual(s["active_ms"], 3000 + 10000 + 3000 + 2000 + 1000)
        self.assertEqual(s["owner_wait_ms"], 60000)
        self.assertEqual(s["llm_ms"], 3000 + 3000 + 2000 + 1000)
        self.assertEqual(s["unaccounted_ms"], 201500 - (3000 + 10000 + 3000 + 60000 + 2000 + 1000))
        self.assertAlmostEqual(s["notional_cost_usd"], 0.18)
        self.assertEqual((s["fresh_input_tokens"], s["cache_read_tokens"], s["cache_write_tokens"]), (40, 1000, 50))
        self.assertEqual(s["input_tokens"], 40 + 1000 + 50)
        self.assertEqual((s["llm_errors"], s["tool_errors"]), (1, 0))
        t1, t2 = self.q("SELECT * FROM turns ORDER BY turn_idx")
        self.assertEqual(t1["wall_ms"], 79700 - 1000)
        self.assertEqual(t1["llm_ms"], 8000)
        self.assertEqual(t1["owner_ms"], 60000)
        self.assertEqual((t1["run_ms"], t1["explore_ms"], t1["edit_ms"]), (6000, 100, 50))
        self.assertEqual(t1["other_ms"], 10000 - 6150)  # codemode time not covered by its nested calls
        self.assertEqual(t1["idle_after_ms"], 200000 - 79700)
        self.assertEqual(t1["active_ms"], 18000)
        self.assertAlmostEqual(t1["notional_cost_usd"], 0.17)
        self.assertEqual(t2["last_stop_reason"], "error")
        self.assertIsNone(t2["idle_after_ms"])

    def test_call_rows_carry_timing_source_and_first_content(self):
        standard_session().write(self.top())
        self.build()
        llm = self.q("SELECT * FROM calls WHERE kind='llm' ORDER BY seq")[0]
        self.assertEqual((llm["start_ms"], llm["end_ms"], llm["dur_ms"], llm["timing_source"]),
                         (T + 1500, T + 4500, 3000, "stamp"))
        self.assertEqual(llm["ttfc_ms"], 1500)
        nested = self.q("SELECT * FROM calls WHERE kind='nested' AND name='bash'")[0]
        self.assertEqual((nested["parent_call_id"], nested["dur_ms"], nested["phase"]), ("c1", 6000, "run"))

    def test_duration_only_and_untimed_sessions_are_labelled(self):
        d = Fixture(session_id="dur")
        d.user(T + 1000)
        d.llm(T + 2000, T + 5000, calls=["x"], stamp=False, duration=3000)
        d.tool("x", "bash", T + 5000, T + 9000, stamp=False)
        d.write(self.top("--work-proj--/2026-10-02T00-00-00-000Z_dur.jsonl"))
        n = Fixture(session_id="none")
        n.user(T + 1000)
        n.llm(T + 2000, None, cost=0.5, stamp=False)
        n.tool("y", "bash", T + 3000, T + 3000, stamp=False, duration=False)
        n.write(self.top("--work-proj--/2026-10-03T00-00-00-000Z_none.jsonl"))
        self.build()
        dur = self.q("SELECT * FROM sessions WHERE session_id='dur'")[0]
        self.assertEqual(dur["timing_quality"], "duration")
        self.assertEqual(dur["active_ms"], 7000)
        tool = self.q("SELECT * FROM calls WHERE path LIKE '%dur.jsonl' AND kind='tool'")[0]
        self.assertEqual((tool["start_ms"], tool["timing_source"]), (T + 5000, "duration"))
        none = self.q("SELECT * FROM sessions WHERE session_id='none'")[0]
        self.assertEqual(none["timing_quality"], "none")
        self.assertIsNone(none["active_ms"])
        self.assertIsNone(none["llm_ms"])
        self.assertAlmostEqual(none["notional_cost_usd"], 0.5)
        self.assertEqual(none["calls_timed"], 0)
        self.assertGreater(none["calls_untimed"], 0)

    def test_malformed_lines_are_skipped_and_counted(self):
        p = standard_session().write(self.top())
        with open(p, "a") as fh:
            fh.write("{not json\n[1,2]\n")
        res = self.build()
        self.assertEqual(res["malformed_lines"], 1)
        self.assertEqual(self.q("SELECT llm_calls FROM sessions")[0][0], 4)


class Children(Base):
    def test_child_runs_link_to_parent_and_roll_into_family(self):
        parent_stem = "2026-10-01T00-00-00-000Z_parent-uuid"
        proj = self.root / "--work-proj--"
        p = Fixture(session_id="parent-uuid")
        p.user(T + 1000)
        p.llm(T + 1500, T + 2500, cost=1.0, stop="stop")
        p.write(proj / f"{parent_stem}.jsonl")
        c0 = Fixture(session_id="child-a-0")
        c0.user(T + 3000)
        c0.llm(T + 3500, T + 4500, cost=0.25, stop="stop", eid="child-a0-llm")
        c0.write(proj / parent_stem / "child-a" / "run-0" / "session.jsonl")
        c1 = Fixture(session_id="child-a-1")
        c1.user(T + 5000)
        c1.llm(T + 5500, T + 6500, cost=0.5, stop="stop", eid="child-a1-llm")
        c1.write(proj / parent_stem / "child-a" / "run-1" / "session.jsonl")
        art = proj / "subagent-artifacts" / "x_worker_transcript.jsonl"
        art.parent.mkdir(parents=True)
        art.write_text('{"unrelated": true}\n')
        self.build()
        self.assertEqual(self.q("SELECT COUNT(*) FROM sessions")[0][0], 3)  # artifact skipped
        kids = self.q("SELECT * FROM sessions WHERE kind='child' ORDER BY run_index")
        self.assertEqual([(k["parent_session_id"], k["child_id"], k["run_index"]) for k in kids],
                         [("parent-uuid", "child-a", 0), ("parent-uuid", "child-a", 1)])
        fam = self.q("SELECT * FROM family")[0]
        self.assertEqual(fam["child_runs"], 2)
        self.assertAlmostEqual(fam["family_cost_usd"], 1.75)
        retry = self.q("SELECT * FROM events WHERE kind='subagent.retry'")
        self.assertEqual(len(retry), 1)
        self.assertEqual(json.loads(retry[0]["attrs"]), {"run_index": 1})


class Dedupe(Base):
    def test_forked_file_does_not_double_count_copied_history(self):
        a = Fixture(session_id="orig")
        a.user(T + 1000, "q")
        a.llm(T + 1500, T + 2500, cost=2.0, stop="stop", eid="shared-llm")
        a.write(self.top("--work-proj--/2026-10-01T00-00-00-000Z_orig.jsonl"))
        b = Fixture(session_id="fork", start=T + 10_000)
        b.entries.append(dict(a.entries[1]))  # copied user entry, same id
        b.entries.append(dict(a.entries[2]))  # copied assistant entry, same id
        b.user(T + 20_000)
        b.llm(T + 20_500, T + 21_500, cost=0.5, stop="stop", eid="fork-new")
        b.write(self.top("--work-proj--/2026-10-02T00-00-00-000Z_fork.jsonl"))
        self.build()
        orig = self.q("SELECT * FROM sessions WHERE session_id='orig'")[0]
        fork = self.q("SELECT * FROM sessions WHERE session_id='fork'")[0]
        self.assertAlmostEqual(orig["notional_cost_usd"], 2.0)
        self.assertAlmostEqual(fork["notional_cost_usd"], 0.5)
        self.assertAlmostEqual(fork["inherited_cost_usd"], 2.0)
        self.assertEqual(fork["turns"], 1)
        self.assertEqual(self.q("SELECT SUM(notional_cost_usd) FROM sessions")[0][0], 2.5)
        inherited = self.q("SELECT inherited FROM turns WHERE path LIKE '%fork.jsonl' ORDER BY turn_idx")
        self.assertEqual([r[0] for r in inherited], [1, 0])


class Events(Base):
    def test_rule_derived_events(self):
        f = Fixture()
        f.entry({"type": "model_change", "provider": "p", "modelId": "m-1"}, T + 1)
        f.entry({"type": "thinking_level_change", "thinkingLevel": "high"}, T + 2)
        f.user(T + 1000)
        f.entry({"type": "model_change", "provider": "p", "modelId": "m-2"}, T + 1100)
        f.entry({"type": "thinking_level_change", "thinkingLevel": "low"}, T + 1200)
        f.llm(T + 2000, T + 3000, stop="error", err="connection reset: ECONNRESET")
        f.llm(T + 3100, T + 4100, stop="error", err="overloaded 529")
        f.llm(T + 4200, T + 5200, stop="aborted")
        f.llm(T + 5300, T + 6300, stop="length")
        f.llm(T + 6400, T + 7400, stop="stop", out=3)
        f.llm(T + 7500, T + 8500, stop="stop", out=2)
        f.llm(T + 8600, T + 9600, stop="toolUse", out=5, calls=["s1", "s2", "e1", "q1"])
        f.tool("s1", "codemode", T + 9600, T + 19600, nested=[("bash", 5000, "sleep 25"), ("bash", 4000, "cd x && sleep 3")])
        f.tool("s2", "codemode", T + 19600, T + 29600, nested=[("bash", 5000, "sleep 20")])
        f.tool("e1", "bash", T + 29600, T + 29700, error=True)
        f.tool("q1", "ask_user_question", T + 29700, T + 39700, details={"cancelled": True})
        f.entry({"type": "usage", "kind": "cache_warm", "provider": "p", "model": "m-1",
                 "usage": {"input": 1, "output": 0, "cacheRead": 5, "cacheWrite": 0, "cost": {"total": 0.07}}}, T + 40000)
        f.entry({"type": "compaction", "tokensBefore": 1234, "fromHook": False,
                 "usage": {"input": 1, "output": 1, "cost": {"total": 0.03}}}, T + 41000)
        f.write(self.top())
        self.build()
        kinds = {r["kind"]: r["n"] for r in self.q("SELECT kind, COUNT(*) n FROM events GROUP BY kind")}
        self.assertEqual(kinds["llm.error"], 2)
        self.assertEqual(kinds["llm.retry_loop"], 1)
        self.assertEqual((kinds["llm.aborted"], kinds["llm.length_cutoff"]), (1, 1))
        self.assertEqual(kinds["model.switch"], 1)      # the first model_change is the initial selection
        self.assertEqual(kinds["thinking.change"], 1)
        self.assertEqual(kinds["reply.minimal"], 2)
        self.assertEqual(kinds["tool.sleep_poll"], 2)   # 'sleep 25' and 'sleep 20'; 'cd x && sleep 3' is not a first token
        self.assertEqual(kinds["tool.error"], 1)
        self.assertEqual(kinds["owner.asked"], 1)
        self.assertEqual(kinds["spend.cache_warm"], 1)
        self.assertEqual(kinds["context.compaction"], 1)
        buckets = sorted(json.loads(r["attrs"])["bucket"] for r in self.q("SELECT attrs FROM events WHERE kind='llm.error'"))
        self.assertEqual(buckets, ["network", "rate_limit"])
        streak = [json.loads(r["attrs"])["streak"] for r in self.q("SELECT attrs FROM events WHERE kind='reply.minimal' ORDER BY seq")]
        self.assertEqual(streak, [1, 2])
        owner = json.loads(self.q("SELECT attrs FROM events WHERE kind='owner.asked'")[0]["attrs"])
        self.assertEqual((owner["cancelled"], owner["wait_ms"]), (True, 10000))
        s = self.q("SELECT * FROM sessions")[0]
        self.assertAlmostEqual(s["overhead_cost_usd"], 0.10)
        attrs = " ".join(r["attrs"] for r in self.q("SELECT attrs FROM events"))
        self.assertNotIn("cd x", attrs)  # command text never survives; only the sleep length does
        self.assertNotIn("sleep 25", attrs)


class Incremental(Base):
    def test_unchanged_files_are_skipped_and_changes_reingested(self):
        p = standard_session().write(self.top())
        self.assertEqual(self.build()["parsed"], 1)
        again = self.build()
        self.assertEqual((again["parsed"], again["unchanged"]), (0, 1))
        with open(p, "a") as fh:
            fh.write(json.dumps({"type": "message", "id": "late", "timestamp": iso(T + 300000),
                                 "message": {"role": "user", "timestamp": T + 300000, "content": "x"}}) + "\n")
        self.assertEqual(self.build()["parsed"], 1)
        self.assertEqual(self.q("SELECT turns FROM sessions")[0][0], 3)
        p.unlink()
        self.assertEqual(self.build()["removed"], 1)
        self.assertEqual(self.q("SELECT COUNT(*) FROM sessions")[0][0], 0)
        self.assertEqual(self.q("SELECT COUNT(*) FROM calls")[0][0], 0)


class Privacy(Base):
    def test_no_content_reaches_the_database(self):
        standard_session().write(self.top())
        self.build()
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
        blob = b"".join(p.read_bytes() for p in self.db.parent.iterdir())
        self.assertNotIn(SENTINEL.encode(), blob)
        self.assertNotIn(b"hunter2", blob)
        self.assertNotIn(b"rate limit", blob)


class CliJourney(Base):
    def run_cli(self, *args, ok=True):
        proc = subprocess.run([sys.executable, str(CLI), "--db", str(self.db), *args],
                              capture_output=True, text=True, env={**os.environ, "PI_CODING_AGENT_DIR": str(self.root.parent / "none")})
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def tree_hash(self):
        h = hashlib.sha256()
        for p in sorted(self.root.rglob("*")):
            if p.is_file():
                h.update(str(p).encode() + p.read_bytes())
        return h.hexdigest()

    def test_build_then_report_leaves_sessions_untouched_and_labels_cost(self):
        standard_session().write(self.top())
        untimed = Fixture(session_id="untimed")
        untimed.user(T + 1000)
        untimed.llm(T + 1500, None, stamp=False)
        untimed.write(self.top("--work-proj--/2026-10-05T00-00-00-000Z_untimed.jsonl"))
        before = self.tree_hash()
        built = self.run_cli("build", "--sessions-dir", str(self.root))
        self.assertIn("2 sessions", built.stdout)
        self.assertIn("read-only", built.stdout)
        listing = self.run_cli("sessions", "--sort", "cost").stdout
        self.assertIn("notional", listing)
        self.assertIn("not a bill", listing)
        self.assertIn("stamped", listing)
        self.assertIn("unknown", listing)       # untimed session shows unknown, not zero
        detail = self.run_cli("session", "sess-1").stdout
        for needle in ("owner-wait", "nested:bash", "codemode", "notional USD 0.18", "events:", "llm.error"):
            self.assertIn(needle, detail)
        self.assertIn("tool.sleep_poll", self.run_cli("events").stdout)
        self.assertIn("codemode", self.run_cli("tools").stdout)
        rows = self.run_cli("sql", "SELECT COUNT(*) AS n FROM calls WHERE kind='llm'").stdout.split()
        self.assertEqual(rows, ["n", "5"])
        for out in (built.stdout, listing, detail):
            self.assertNotIn(SENTINEL, out)
        self.assertEqual(self.tree_hash(), before)

    def test_failures_are_closed(self):
        missing = self.run_cli("sessions", ok=False)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("build", missing.stderr)
        standard_session().write(self.top())
        self.run_cli("build", "--sessions-dir", str(self.root))
        write = self.run_cli("sql", "DELETE FROM calls", ok=False)
        self.assertEqual(write.returncode, 2)
        self.assertEqual(self.q("SELECT COUNT(*) FROM calls WHERE kind='llm'")[0][0], 4)
        nomatch = self.run_cli("session", "does-not-exist", ok=False)
        self.assertNotEqual(nomatch.returncode, 0)
        badsince = self.run_cli("sessions", "--since", "soon", ok=False)
        self.assertNotEqual(badsince.returncode, 0)

    def test_since_limits_which_files_are_read(self):
        old = standard_session().write(self.top())
        os.utime(old, (1_000_000_000, 1_000_000_000))
        fresh = Fixture(session_id="fresh")
        fresh.user(T + 1000)
        fresh.llm(T + 1500, T + 2500, stop="stop")
        fresh.write(self.top("--work-proj--/2026-10-09T00-00-00-000Z_fresh.jsonl"))
        self.assertEqual(self.build(since_ms=ae.parse_since("2d"))["sessions"], 1)


class ReviewFixes(Base):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), "--db", str(self.db), *args], capture_output=True, text=True)

    def test_sql_subcommand_cannot_write_or_create_files(self):
        standard_session().write(self.top())
        self.build()
        before = sorted(p.name for p in self.db.parent.iterdir())
        for stmt in (f"ATTACH DATABASE '{self.db.parent}/attached.sqlite' AS aux",
                     f"VACUUM INTO '{self.db.parent}/copy.sqlite'",
                     "PRAGMA writable_schema=1", "DELETE FROM calls", "DROP TABLE calls",
                     "SELECT 1; DELETE FROM calls", "SELECT load_extension('x')",
                     "WITH x AS (SELECT 1) DELETE FROM calls"):
            proc = self.run_cli("sql", stmt)
            self.assertNotEqual(proc.returncode, 0, stmt)
        self.assertEqual(sorted(p.name for p in self.db.parent.iterdir()), before)
        self.assertEqual(self.q("SELECT COUNT(*) FROM calls WHERE kind='llm'")[0][0], 4)
        ok = self.run_cli("sql", "SELECT COUNT(*) AS n FROM calls WHERE kind='llm'")
        self.assertEqual(ok.stdout.split(), ["n", "4"])

    def test_unrecognised_status_and_name_text_never_stored(self):
        f = Fixture()
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["c"], model=f"model {SENTINEL}")
        f.tool("c", f"tool {SENTINEL}", T + 2500, T + 4000, nested=[("bash", 100, "x")])
        for e in f.entries:
            msg = e.get("message") or {}
            if msg.get("nestedCalls"):
                msg["nestedCalls"]["calls"][0]["status"] = SENTINEL
            if e.get("customType") == "pi-stamp" and e["data"].get("kind") == "tool":
                e["data"]["outcome"] = SENTINEL
        f.write(self.top())
        self.build()
        statuses = {r[0] for r in self.q("SELECT status FROM calls")}
        self.assertLessEqual(statuses, {"ok", "error", "aborted", "timeout", "unfinished", "length", "unknown"})
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
        blob = b"".join(p.read_bytes() for p in self.db.parent.iterdir())
        self.assertNotIn(SENTINEL.encode(), blob)
        self.assertEqual(self.q("SELECT status FROM calls WHERE kind='nested'")[0][0], "unknown")
        self.assertEqual(self.q("SELECT status FROM calls WHERE kind='tool'")[0][0], "ok")

    def test_untimed_tool_makes_totals_unknown_not_zero(self):
        f = Fixture(session_id="mix")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["b"])
        f.tool("b", "bash", T + 2500, T + 9000, stamp=False, duration=False)
        f.llm(T + 9100, T + 9500, stop="stop")
        f.write(self.top())
        self.build()
        s = self.q("SELECT * FROM sessions")[0]
        self.assertEqual(s["timing_complete"], 0)
        self.assertIsNone(s["tool_ms"])
        self.assertIsNone(s["active_ms"])
        self.assertIsNone(s["unaccounted_ms"])
        self.assertEqual(s["llm_ms"], 1400)       # LLM calls were all timed
        t = self.q("SELECT * FROM turns")[0]
        self.assertIsNone(t["run_ms"])
        self.assertIsNone(t["wall_ms"])
        self.assertEqual(t["explore_ms"], 0)      # no explore calls at all: a known zero
        self.assertEqual(t["timing_complete"], 0)
        detail = subprocess.run([sys.executable, str(CLI), "--db", str(self.db), "session", "mix"],
                                capture_output=True, text=True).stdout
        self.assertIn("partial", detail)

    def test_untimed_llm_turn_has_unknown_wall_time(self):
        f = Fixture(session_id="u")
        f.user(T + 1000)
        f.llm(T + 1500, None, stamp=False, stop="stop")
        f.write(self.top())
        self.build()
        t = self.q("SELECT * FROM turns")[0]
        self.assertIsNone(t["wall_ms"])
        self.assertIsNone(t["llm_ms"])
        self.assertIsNone(t["idle_after_ms"])

    def test_parallel_codemode_nested_durations_stay_inclusive(self):
        f = Fixture(session_id="par")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["w"])
        f.tool("w", "codemode", T + 2500, T + 8500, nested=[("bash", 6000, "a"), ("read", 6000, "b")])
        f.write(self.top())
        self.build()
        t = self.q("SELECT * FROM turns")[0]
        self.assertEqual((t["run_ms"], t["explore_ms"], t["other_ms"]), (6000, 6000, 0))
        self.assertEqual(self.q("SELECT tool_ms FROM sessions")[0][0], 6000)  # wrapper time, not the phase sum

    def test_interrupted_finalize_is_repaired_by_next_build(self):
        from unittest import mock
        standard_session().write(self.top())
        with mock.patch.object(ae, "finalize", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.build()
        res = self.build()
        self.assertEqual((res["parsed"], res["unchanged"]), (0, 1))
        self.assertTrue(res["refinalized"])
        s = self.q("SELECT * FROM sessions")[0]
        self.assertEqual(s["wall_ms"], 201500)
        self.assertAlmostEqual(s["notional_cost_usd"], 0.18)
        again = self.build()
        self.assertFalse(again["refinalized"])

    def test_fork_turn_keeps_its_own_work_when_the_prompt_was_copied(self):
        o = Fixture(session_id="orig")
        o.user(T + 1000)
        o.llm(T + 1500, T + 2500, cost=1.0, stop="stop", eid="o-llm")
        o.write(self.top("--work-proj--/2026-10-02T00-00-00-000Z_orig.jsonl"))
        b = Fixture(session_id="fork", start=T + 10_000)
        b.entries.append(dict(o.entries[1]))  # copied prompt, no new user message afterwards
        b.llm(T + 20_000, T + 21_000, cost=0.5, stop="stop", eid="f-llm")
        b.write(self.top("--work-proj--/2026-10-03T00-00-00-000Z_fork.jsonl"))
        self.build()
        s = self.q("SELECT * FROM sessions WHERE session_id='fork'")[0]
        t = self.q("SELECT * FROM turns WHERE path LIKE '%fork.jsonl'")[0]
        self.assertEqual(s["turns"], 1)
        self.assertEqual((t["llm_calls"], t["wall_ms"]), (1, 1000))
        self.assertAlmostEqual(t["notional_cost_usd"], s["notional_cost_usd"])
        self.assertAlmostEqual(s["notional_cost_usd"], 0.5)

    def test_incremental_build_matches_a_fresh_build_when_ownership_moves(self):
        o = Fixture(session_id="orig")
        o.user(T + 1000)
        o.llm(T + 1500, T + 2500, cost=2.0, stop="stop", eid="shared-llm")
        b = Fixture(session_id="fork", start=T + 10_000)
        b.entries.append(dict(o.entries[1]))
        b.entries.append(dict(o.entries[2]))
        b.user(T + 20_000)
        b.llm(T + 20_500, T + 21_500, cost=0.5, stop="stop", eid="fork-new")
        b.write(self.top("--work-proj--/2026-10-02T00-00-00-000Z_fork.jsonl"))
        self.build()   # only the fork exists: it owns the shared entries
        self.assertAlmostEqual(self.q("SELECT notional_cost_usd FROM sessions")[0][0], 2.5)
        o.write(self.top("--work-proj--/2026-10-01T00-00-00-000Z_orig.jsonl"))
        self.build()   # the fork file is unchanged, but ownership moves to the earlier file
        incremental = self.q("SELECT session_id, notional_cost_usd, inherited_cost_usd, turns, wall_ms FROM sessions ORDER BY session_id")
        fork = [r for r in incremental if r["session_id"] == "fork"][0]
        self.assertAlmostEqual(fork["notional_cost_usd"], 0.5)
        self.assertAlmostEqual(fork["inherited_cost_usd"], 2.0)
        fresh = Path(self._tmp.name) / "fresh.sqlite"
        ae.build(self.root, fresh)
        con = sqlite3.connect(fresh)
        con.row_factory = sqlite3.Row
        expected = [tuple(r) for r in con.execute("SELECT session_id, notional_cost_usd, inherited_cost_usd, turns, wall_ms FROM sessions ORDER BY session_id")]
        con.close()
        self.assertEqual([tuple(r) for r in incremental], expected)

    def test_error_event_attrs_use_the_sanitised_model(self):
        f = Fixture()
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, stop="error", err="boom", model=f"model {SENTINEL}")
        f.write(self.top())
        self.build()
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
        blob = b"".join(p.read_bytes() for p in self.db.parent.iterdir())
        self.assertNotIn(SENTINEL.encode(), blob)
        self.assertEqual(json.loads(self.q("SELECT attrs FROM events WHERE kind='llm.error'")[0]["attrs"])["model"], "unknown")

    def test_untimed_nested_call_makes_its_phase_unknown(self):
        f = Fixture(session_id="nest")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["w"])
        f.tool("w", "codemode", T + 2500, T + 8500, nested=[("bash", 4000, "a"), ("read", None, "b")])
        f.llm(T + 8600, T + 9000, stop="stop")
        f.write(self.top())
        self.build()
        t = self.q("SELECT * FROM turns")[0]
        self.assertIsNone(t["explore_ms"])       # the read had no duration: unknown, not 0
        self.assertEqual(t["run_ms"], 4000)      # the bash is known
        self.assertIsNone(t["other_ms"])         # residual wrapper time cannot be derived
        self.assertEqual(t["timing_complete"], 0)
        self.assertEqual(t["wall_ms"], 9000 - 1000)   # top-level intervals are all known
        s = self.q("SELECT * FROM sessions")[0]
        self.assertEqual(s["timing_complete"], 0)
        self.assertEqual(s["tool_ms"], 6000)
        self.assertIsNotNone(s["active_ms"])

    def test_untimed_wrapper_keeps_known_nested_durations(self):
        f = Fixture(session_id="wrap")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["w"])
        f.tool("w", "codemode", T + 2500, T + 8500, nested=[("bash", 4000, "a")], stamp=False, duration=False)
        f.write(self.top())
        self.build()
        t = self.q("SELECT * FROM turns")[0]
        self.assertEqual(t["run_ms"], 4000)
        self.assertIsNone(t["other_ms"])
        self.assertIsNone(self.q("SELECT tool_ms FROM sessions")[0][0])

    def test_ownership_reversal_restores_the_original_prompt_time(self):
        o = Fixture(session_id="orig")
        o.user(T + 1000)
        o.llm(T + 1500, T + 2500, cost=1.0, stop="stop", eid="o-llm")
        origin = self.top("--work-proj--/2026-10-02T00-00-00-000Z_orig.jsonl")
        o.write(origin)
        b = Fixture(session_id="fork", start=T + 10_000)
        b.entries.append(dict(o.entries[1]))
        b.llm(T + 20_000, T + 21_000, cost=0.5, stop="stop", eid="f-llm")
        b.write(self.top("--work-proj--/2026-10-03T00-00-00-000Z_fork.jsonl"))
        self.build()
        self.assertEqual(self.q("SELECT wall_ms FROM turns WHERE path LIKE '%fork.jsonl'")[0][0], 1000)
        origin.unlink()
        self.build()                      # fork now owns the prompt: its start is the prompt's own time
        incremental = self.q("SELECT started_at_ms, wall_ms, inherited FROM turns WHERE path LIKE '%fork.jsonl'")[0]
        self.assertEqual((incremental["inherited"], incremental["wall_ms"]), (0, 20_000))
        fresh = Path(self._tmp.name) / "fresh.sqlite"
        ae.build(self.root, fresh)
        con = sqlite3.connect(fresh)
        self.assertEqual(con.execute("SELECT wall_ms FROM turns").fetchone()[0], 20_000)
        con.close()

    def test_schema_reset_interrupted_midway_is_atomic(self):
        standard_session().write(self.top())
        self.build()
        con = sqlite3.connect(self.db)
        con.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
        con.commit()
        con.close()
        original = ae.SCHEMA_STATEMENTS
        ae.SCHEMA_STATEMENTS = original + ["THIS IS NOT SQL"]
        try:
            with self.assertRaises(sqlite3.Error):
                ae.connect(self.db)
        finally:
            ae.SCHEMA_STATEMENTS = original
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "0")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)  # old data intact
        con.close()
        res = self.build()                # a retry completes the reset
        self.assertEqual((res["parsed"], res["sessions"]), (1, 1))
        self.assertEqual(self.q("SELECT value FROM meta WHERE key='schema_version'")[0][0], str(ae.SCHEMA_VERSION))
        self.assertIn("timing_complete", [r[1] for r in self.q("PRAGMA table_info(turns)")])

    def test_schema_version_change_discards_derived_data(self):
        standard_session().write(self.top())
        self.build()
        con = sqlite3.connect(self.db)
        con.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
        con.commit()
        con.close()
        res = self.build()
        self.assertEqual((res["parsed"], res["unchanged"]), (1, 0))

    def test_wrapper_runs_the_cli(self):
        wrapper = HERE.parents[1] / "bin" / "executable_agent-events"
        if not wrapper.exists():
            self.skipTest("wrapper not present")
        standard_session().write(self.top())
        env = {**os.environ, "AGENT_EVENTS_IMPLEMENTATION": str(CLI)}
        proc = subprocess.run(["sh", str(wrapper), "--db", str(self.db), "build", "--sessions-dir", str(self.root)],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("1 sessions", proc.stdout)


class Helpers(unittest.TestCase):
    def test_union_and_phases(self):
        self.assertEqual(ae.union_ms([(0, 10), (5, 20), (30, 40)]), 30)
        self.assertEqual(ae.union_ms([]), 0)
        self.assertEqual(ae.phase_of("bash"), "run")
        self.assertEqual(ae.phase_of("some_mcp_tool"), "other")
        self.assertEqual(ae.error_bucket("HTTP 429 Too Many"), "rate_limit")
        self.assertEqual(ae.error_bucket("totally new failure"), "other")


if __name__ == "__main__":
    unittest.main()
