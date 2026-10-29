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
        prior = os.environ.get("AGENT_EVENTS_STATE_DIR")  # a manual build takes a lock in the state dir
        os.environ["AGENT_EVENTS_STATE_DIR"] = str(Path(self._tmp.name) / "state-base")
        self.addCleanup(lambda: os.environ.__setitem__("AGENT_EVENTS_STATE_DIR", prior) if prior is not None
                        else os.environ.pop("AGENT_EVENTS_STATE_DIR", None))

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

    def test_a_wait_inside_codemode_is_owner_wait_not_active_or_tool_time(self):
        f = Fixture(session_id="ownnest")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["w"])
        f.tool("w", "codemode", T + 2500, T + 12500,
               nested=[("ask_user_question", 6000, "q"), ("notify_owner", 10, "n"), ("bash", 1000, "b")])
        f.llm(T + 12600, T + 13600, stop="stop")
        f.write(self.top())
        self.build()
        s = self.q("SELECT * FROM sessions")[0]
        t = self.q("SELECT * FROM turns")[0]
        self.assertEqual(s["owner_wait_ms"], 6010)            # was 0: the wait was booked to codemode
        self.assertEqual(t["owner_ms"], 6010)                 # the phase breakdown already agreed
        self.assertEqual(s["tool_ms"], 10000 - 6010)          # the wrapper minus the wait
        self.assertEqual(s["active_ms"], 1000 + 10000 + 1000 - 6010)

    def test_direct_and_nested_waits_add_up_once(self):
        f = Fixture(session_id="ownboth")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["w", "q"])
        f.tool("w", "codemode", T + 2500, T + 7500, nested=[("ask_user_question", 4000, "q")])
        f.tool("q", "ask_user_question", T + 7500, T + 9500)
        f.llm(T + 9600, T + 10600, stop="stop")
        f.write(self.top())
        self.build()
        s = self.q("SELECT * FROM sessions")[0]
        self.assertEqual(s["owner_wait_ms"], 4000 + 2000)
        self.assertEqual(s["tool_ms"], 1000)
        self.assertEqual(s["active_ms"], 1000 + 5000 + 1000 - 4000)

    def test_a_nested_wait_cannot_push_time_below_zero(self):
        f = Fixture(session_id="ownover")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["w"])
        f.tool("w", "codemode", T + 2500, T + 3500, nested=[("ask_user_question", 5000, "q")])  # longer than the wrapper
        f.write(self.top())
        self.build()
        s = self.q("SELECT * FROM sessions")[0]
        self.assertEqual(s["tool_ms"], 0)
        self.assertEqual(s["active_ms"], 1000)                # only the LLM call: the wrapper is all wait
        self.assertEqual(s["owner_wait_ms"], 5000)

    def test_a_nested_wait_under_an_owner_call_does_not_take_time_from_other_work(self):
        f = Fixture(session_id="ownparent")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["q"])
        f.tool("q", "ask_user_question", T + 2500, T + 8500, nested=[("ask_user_question", 4000, "q")])
        f.write(self.top())
        self.build()
        s = self.q("SELECT * FROM sessions")[0]
        self.assertEqual(s["active_ms"], 1000)      # the disjoint LLM call is untouched: the parent is already owner time
        self.assertEqual(s["owner_wait_ms"], 6000 + 4000)

    def test_a_nested_wait_with_no_duration_leaves_owner_active_and_tool_time_unknown(self):
        f = Fixture(session_id="ownunk")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, calls=["w"])
        f.tool("w", "codemode", T + 2500, T + 8500, nested=[("ask_user_question", None, "q")])
        f.llm(T + 8600, T + 9000, stop="stop")
        f.write(self.top())
        self.build()
        s = self.q("SELECT * FROM sessions")[0]
        self.assertIsNone(s["owner_wait_ms"])
        self.assertIsNone(s["active_ms"])
        self.assertIsNone(s["tool_ms"])

    def test_the_schema_bump_forces_a_full_rebuild(self):
        standard_session().write(self.top())
        self.build()
        con = sqlite3.connect(self.db)
        con.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
        con.execute("UPDATE sessions SET owner_wait_ms=1")        # a value computed by the old rule
        con.commit()
        con.close()
        res = self.build()
        self.assertEqual(res["parsed"], 1)                         # re-parsed, not skipped as unchanged
        self.assertEqual(self.q("SELECT owner_wait_ms FROM sessions")[0][0], 60000)

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

    def test_meta_table_without_version_row_is_reset(self):
        standard_session().write(self.top())
        self.build()
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM meta")                      # interrupted init: tables exist, no version published
        con.execute("ALTER TABLE turns DROP COLUMN prompt_ms")  # and they are an older shape
        con.commit()
        con.close()
        res = self.build()
        self.assertEqual((res["parsed"], res["sessions"]), (1, 1))
        self.assertIn("prompt_ms", [r[1] for r in self.q("PRAGMA table_info(turns)")])

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


# ---------------------------------------------------------------- always-on, metrics, drill-down

import agent_events_metrics as am  # noqa: E402
import agent_events_show as ash  # noqa: E402
import gzip  # noqa: E402
import http.server  # noqa: E402
import threading  # noqa: E402
import fcntl  # noqa: E402
import time  # noqa: E402

ALLOWED_LABELS = {"project", "kind", "provider", "model", "outcome", "type", "tool", "nested", "phase", "event", "detail"}


class Collector:
    """A throwaway OTLP/HTTP endpoint that records what it is sent."""

    def __init__(self, status=200, body=b'{"partialSuccess":{}}'):
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append({"path": self.path, "encoding": self.headers.get("Content-Encoding"),
                                       "body": json.loads(gzip.decompress(raw) if self.headers.get("Content-Encoding") == "gzip" else raw)})
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/metrics"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Tick(Base):
    def setUp(self):
        super().setUp()
        self.state = Path(self._tmp.name) / "state"
        self._env = {k: os.environ.get(k) for k in ("AGENT_EVENTS_STATE_DIR", "AGENT_EVENTS_OTLP_ENDPOINT",
                                                      "AGENT_EVENTS_PROJECTS", "AGENT_EVENTS_MACHINE")}
        os.environ["AGENT_EVENTS_STATE_DIR"] = str(self.state)
        os.environ["AGENT_EVENTS_PROJECTS"] = "proj"  # the synthetic project is an approved workstream
        os.environ["AGENT_EVENTS_MACHINE"] = "test-mac"  # nothing is sent without a machine label (MachineLabel)
        os.environ.pop("AGENT_EVENTS_OTLP_ENDPOINT", None)
        self.addCleanup(self._restore)
        standard_session().write(self.top())

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def collector(self, **kw):
        c = Collector(**kw)
        self.addCleanup(c.close)
        os.environ["AGENT_EVENTS_OTLP_ENDPOINT"] = c.url
        return c

    def status(self):
        return json.loads((self.state / "status.json").read_text())


class CacheGauges(Tick):
    """Per-session prompt-cache gauges for the cache alerts."""
    NOW = (T + 3 * 3600 * 1000) / 1000.0
    MIN = 60_000

    def cache_session(self, sid, name, model, calls, cwd="/work/proj"):
        """calls: (minutes before NOW, cacheRead, cacheWrite, fresh input)."""
        f = Fixture(session_id=sid, cwd=cwd, start=int(self.NOW * 1000) - 120 * self.MIN)
        f.user(int(self.NOW * 1000) - 119 * self.MIN)
        for ago, cr, cw, fresh in calls:
            end = int(self.NOW * 1000) - int(ago * self.MIN)
            f.llm(end - 2000, end, cr=cr, cw=cw, fresh=fresh, stop="stop", model=model)
        f.write(self.root / f"--work-proj--/2026-10-01T00-00-00-000Z_{name}.jsonl")

    def gauges(self):
        self.build()
        con = ae.connect(self.db, readonly=True)
        out = {}
        for m in am.cache_gauges(con, self.NOW):
            for labels, v in m["points"]:
                out.setdefault((labels["session"], labels["project"], labels["model"]), {})[m["name"]] = v
        return out

    def test_ratio_calls_and_full_misses_over_the_window(self):
        HIT = (100_000, 0, 100)
        MISS = (0, 60_000, 50)
        self.cache_session("01a16722-a001-7000-8000-000000000001", "a", "claude-x",
                           [(40, *MISS)] +                     # older than the window: ignored
                           [(25, *MISS), (20, *HIT), (15, *MISS), (10, *HIT), (5, *MISS), (1, *HIT)])
        g = self.gauges()
        key = ("01a16722-a001-7000-8000-000000000001", "proj", "claude-x")
        self.assertEqual(list(g), [key])
        v = g[key]
        self.assertEqual(v["pi_cache_calls_30m"], 6)
        self.assertEqual(v["pi_cache_full_miss_calls_30m"], 3)
        cr, cw, fi = 3 * 100_000, 3 * 60_000, 3 * 100 + 3 * 50
        self.assertAlmostEqual(v["pi_cache_hit_ratio_30m"], cr / (cr + cw + fi))
        self.assertEqual(v["pi_cache_uncached_tokens_30m"], cw + fi)

    def test_full_miss_needs_both_a_large_write_and_a_low_read_share(self):
        self.cache_session("01a16722-a002-7000-8000-000000000002", "b", "claude-x",
                           [(10, 0, 49_000, 10),            # write not above 50k: not a full miss
                            (9, 300_000, 60_000, 10),       # large write but 83% read: a partial rebuild, not a full miss
                            (8, 11_000, 60_000, 10),        # 15% read: a full miss
                            (7, 0, 60_000, 0)])             # all write: a full miss
        v = self.gauges()[("01a16722-a002-7000-8000-000000000002", "proj", "claude-x")]
        self.assertEqual(v["pi_cache_full_miss_calls_30m"], 2)

    def test_sessions_and_models_are_separate_series_and_idle_sessions_drop_out(self):
        self.cache_session("01a16722-a003-7000-8000-000000000003", "c1", "claude-x", [(3, 100_000, 0, 10)])
        self.cache_session("01a16722-a004-7000-8000-000000000004", "d", "gpt-y", [(2, 1_000, 0, 99_000)])
        self.cache_session("01a16722-a005-7000-8000-000000000005", "e", "claude-x", [(45, 0, 90_000, 0)])  # idle for 45 min
        g = {k: v for k, v in self.gauges().items() if "pi_cache_calls_30m" in v}  # the streak gauge has its own window
        self.assertEqual(set(g), {("01a16722-a003-7000-8000-000000000003", "proj", "claude-x"), ("01a16722-a004-7000-8000-000000000004", "proj", "gpt-y")})
        self.assertAlmostEqual(g[("01a16722-a004-7000-8000-000000000004", "proj", "gpt-y")]["pi_cache_hit_ratio_30m"], 0.01)

    def test_sessions_sharing_a_start_time_prefix_stay_separate(self):
        self.cache_session("01a16722-a00b-7000-8000-000000000001", "k1", "claude-x", [(t, 0, 10_000, 0) for t in (6, 5, 4, 3, 2)])
        self.cache_session("01a16722-a00b-7000-8000-000000000002", "k2", "claude-x", [(t, 100_000, 0, 0) for t in (6, 5, 4, 3, 2)])
        g = self.gauges()
        self.assertEqual(g["01a16722-a00b-7000-8000-000000000001", "proj", "claude-x"]["pi_cache_hit_ratio_30m"], 0.0)
        self.assertEqual(g["01a16722-a00b-7000-8000-000000000002", "proj", "claude-x"]["pi_cache_hit_ratio_30m"], 1.0)

    def test_a_call_after_the_evaluation_time_is_not_counted(self):
        self.cache_session("01a16722-a006-7000-8000-00000000000a", "j", "claude-x", [(3, 100_000, 0, 10), (-5, 0, 90_000, 0)])
        v = self.gauges()[("01a16722-a006-7000-8000-00000000000a", "proj", "claude-x")]
        self.assertEqual((v["pi_cache_calls_30m"], v["pi_cache_full_miss_calls_30m"]), (1, 0))

    def streaks(self):
        return {k: v["pi_cache_miss_streak"] for k, v in self.gauges().items() if "pi_cache_miss_streak" in v}

    def test_miss_streak_counts_back_to_back_full_misses(self):
        HIT, MISS = (100_000, 0, 100), (0, 60_000, 50)
        sid = "01a16722-a00c-7000-8000-00000000000c"
        self.cache_session(sid, "s1", "claude-x", [(50, *HIT), (40, *MISS), (20, *MISS), (1, *MISS)])  # 20 and 19 min apart
        self.assertEqual(self.streaks(), {(sid, "proj", "claude-x"): 3})

    def test_a_single_miss_after_an_idle_gap_of_the_ttl_is_a_streak_of_one(self):
        MISS = (0, 60_000, 50)
        sid = "01a16722-a00d-7000-8000-00000000000d"
        # Two misses well before, then 61 min idle (the cache may have expired), then one miss.
        self.cache_session(sid, "s2", "claude-x", [(80, *MISS), (75, *MISS), (5, *MISS)])
        self.assertEqual(self.streaks(), {(sid, "proj", "claude-x"): 1})

    def test_a_gap_of_exactly_the_ttl_resets_the_streak(self):
        MISS = (0, 60_000, 50)
        sid = "01a16722-a00e-7000-8000-00000000000e"
        # Each call starts 2 s before it ends, so starting 60 min after the previous end means ending 60 min + 2 s later.
        self.cache_session(sid, "s3", "claude-x", [(70 + 2 / 60, *MISS), (10, *MISS), (5, *MISS)])
        self.assertEqual(self.streaks(), {(sid, "proj", "claude-x"): 2})

    def test_a_hit_in_between_resets_the_streak(self):
        HIT, MISS = (100_000, 0, 100), (0, 60_000, 50)
        sid = "01a16722-a00f-7000-8000-00000000000f"
        self.cache_session(sid, "s4", "claude-x", [(9, *MISS), (8, *MISS), (7, *HIT), (6, *MISS), (5, *MISS)])
        self.assertEqual(self.streaks(), {(sid, "proj", "claude-x"): 2})
        sid2 = "01a16722-a010-7000-8000-000000000010"
        self.cache_session(sid2, "s5", "claude-x", [(9, *MISS), (8, *MISS), (7, *MISS), (2, *HIT)])  # ends on a hit
        self.assertEqual(self.streaks()[(sid2, "proj", "claude-x")], 0)

    def test_sessions_and_models_keep_separate_streaks(self):
        MISS = (0, 60_000, 50)
        a, b = "01a16722-a011-7000-8000-000000000011", "01a16722-a012-7000-8000-000000000012"
        self.cache_session(a, "s6", "claude-x", [(6, *MISS)])
        self.cache_session(b, "s7", "claude-x", [(5, *MISS)])
        self.assertEqual(self.streaks(), {(a, "proj", "claude-x"): 1, (b, "proj", "claude-x"): 1})
        c = "01a16722-a013-7000-8000-000000000013"
        f = Fixture(session_id=c, cwd="/work/proj", start=int(self.NOW * 1000) - 120 * self.MIN)
        f.user(int(self.NOW * 1000) - 119 * self.MIN)
        for ago, model in ((6, "claude-x"), (5, "claude-y"), (4, "claude-x"), (3, "claude-y")):
            end = int(self.NOW * 1000) - ago * self.MIN
            f.llm(end - 2000, end, cr=0, cw=60_000, fresh=50, stop="stop", model=model)
        f.write(self.root / "--work-proj--/2026-10-01T00-00-00-000Z_s8.jsonl")
        g = self.streaks()
        self.assertEqual((g[(c, "proj", "claude-x")], g[(c, "proj", "claude-y")]), (2, 2))

    def test_miss_streak_is_exported_while_the_last_call_is_under_the_ttl_old(self):
        MISS = (0, 60_000, 50)
        live, idle = "01a16722-a014-7000-8000-000000000014", "01a16722-a015-7000-8000-000000000015"
        self.cache_session(live, "s9", "claude-x", [(100, *MISS), (70, *MISS), (45, *MISS)])  # last call 45 min ago
        self.cache_session(idle, "s10", "claude-x", [(63, *MISS), (62, *MISS), (61, *MISS)])  # last call 61 min ago
        g = self.gauges()
        self.assertEqual(self.streaks(), {(live, "proj", "claude-x"): 3})
        self.assertNotIn("pi_cache_calls_30m", g[(live, "proj", "claude-x")])  # outside the 30-minute gauges' window
        self.assertNotIn((idle, "proj", "claude-x"), g)
        both = "01a16722-a016-7000-8000-000000000016"  # one session, one model idle past the TTL, one still active
        f = Fixture(session_id=both, cwd="/work/proj", start=int(self.NOW * 1000) - 120 * self.MIN)
        f.user(int(self.NOW * 1000) - 119 * self.MIN)
        for ago, model in ((66, "claude-old"), (65, "claude-old"), (5, "claude-x")):
            end = int(self.NOW * 1000) - ago * self.MIN
            f.llm(end - 2000, end, cr=0, cw=60_000, fresh=50, stop="stop", model=model)
        f.write(self.root / "--work-proj--/2026-10-01T00-00-00-000Z_s12.jsonl")
        g = self.streaks()
        self.assertEqual(g[(both, "proj", "claude-x")], 1)
        self.assertNotIn((both, "proj", "claude-old"), g)

    def test_miss_streak_skips_a_non_uuid_session(self):
        self.cache_session("not a uuid / with spaces", "s11", "claude-x", [(3, 0, 60_000, 0), (2, 0, 60_000, 0)])
        self.assertEqual(self.streaks(), {})

    def test_calls_without_usage_are_not_counted_and_the_ratio_never_divides_by_zero(self):
        self.cache_session("01a16722-a007-7000-8000-000000000006", "f", "claude-x", [(3, 0, 0, 0), (2, 0, 0, 0)])
        self.assertEqual(self.gauges(), {})

    def test_labels_hold_no_path_or_content_and_a_non_uuid_session_is_skipped(self):
        self.cache_session("not a uuid / with spaces", "g", "claude-x", [(3, 100_000, 0, 10)])
        self.cache_session("01a16722-a008-7000-8000-000000000008", "h", "claude-x", [(3, 100_000, 0, 10)], cwd="/some/other/place")
        con = ae.connect(self.db if self.build() else self.db, readonly=True)
        payload = json.dumps(am.otlp_payload(am.cache_gauges(con, self.NOW), 1, 2))
        self.cache_session("customer-data/private", "g2", "claude-x", [(3, 100_000, 0, 10)])
        self.cache_session("customer-data-private-acme-0001", "g3", "claude-x", [(3, 100_000, 0, 10)])
        self.build()
        payload = json.dumps(am.otlp_payload(am.cache_gauges(con, self.NOW), 1, 2))
        for needle in (SENTINEL, "/work/proj", "/some/other/place", str(self.root), "with spaces", "customer", "acme"):
            self.assertNotIn(needle, payload)
        sessions = {labels["session"] for m in am.cache_gauges(con, self.NOW) for labels, _ in m["points"]}
        self.assertEqual(sessions, {"01a16722-a008-7000-8000-000000000008"})
        projects = {labels["project"] for m in am.cache_gauges(con, self.NOW) for labels, _ in m["points"]}
        self.assertEqual(projects, {"other"})

    def test_export_sends_the_gauges_and_a_failed_build_does_not(self):
        self.cache_session("01a16722-a009-7000-8000-000000000009", "i", "claude-x", [(3, 100_000, 0, 10)])
        self.build()
        con = ae.connect(self.db, readonly=True)
        c = self.collector()
        am.export(con, self.db, {"epoch_ns": 5}, c.url, now=self.NOW)
        names = {m["name"] for m in c.requests[0]["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        self.assertTrue({"pi_cache_hit_ratio_30m", "pi_cache_calls_30m", "pi_cache_full_miss_calls_30m",
                         "pi_cache_uncached_tokens_30m"} <= names)
        am.export(con, self.db, {"epoch_ns": 5}, c.url, now=self.NOW, state={}, business=False)
        names = {m["name"] for m in c.requests[1]["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        self.assertFalse(any(n.startswith("pi_cache_") for n in names))


class ProjectSlug(unittest.TestCase):
    def setUp(self):
        self._roots, self._bases = ae._GIT_ROOTS, ae._PROJECT_BASES
        ae._GIT_ROOTS = {"chezmoi", "loop-engine", "budget-steward"}
        ae._PROJECT_BASES = None
        self.addCleanup(lambda: (setattr(ae, "_GIT_ROOTS", self._roots), setattr(ae, "_PROJECT_BASES", self._bases)))

    def test_worktrees_and_run_dirs_fold_into_their_repository(self):
        base = "/Volumes/Workshop/macbook/git/"
        for cwd, want in [(base + "loop-engine", "loop-engine"), (base + "loop-engine-eval-g", "loop-engine"),
                          (base + "_chezmoi-herdr-hook", "chezmoi"), (base + "dotfiles-wt-foo", "chezmoi"),
                          (base + "budget-steward-wt-intent-1", "budget-steward"),
                          ("/private/tmp/loop-engine-c-20261011", "loop-engine"),
                          ("/Volumes/Workshop/macbook/loop-engine/runs/run-1/proto", "loop-engine"),
                          (base.rstrip("/"), "workspace"), (None, "unknown"), ("", "unknown"),
                          ("/x/Weird Name!", "other"), ("/x/20261020-1906", "other"), ("/work/proj", "proj")]:
            self.assertEqual(ae.project_of(cwd), want, cwd)

    def test_sql_can_use_project(self):
        self.addCleanup(lambda: None)
        with tempfile.TemporaryDirectory() as d:
            standard_session().write(Path(d) / "s" / "--work-proj--" / "2026-10-01T00-00-00-000Z_sess-1.jsonl")
            db = Path(d) / "e.sqlite"
            ae.build(Path(d) / "s", db)
            con = ae.connect(db, readonly=True)
            ns = type("A", (), {"query": "SELECT project(cwd) AS p FROM sessions"})
            self.assertEqual(ae.cmd_sql(con, ns).split("\n")[1], "proj")


class MetricExport(Tick):
    def test_aggregates_match_the_database_and_carry_only_allowed_labels(self):
        self.build()
        con = ae.connect(self.db, readonly=True)
        fams = {m["name"]: m for m in am.collect(con)}
        cost = sum(v for _, v in fams["pi_notional_cost_usd_total".replace("_total", "")]["points"])
        s = self.q("SELECT notional_cost_usd + COALESCE(overhead_cost_usd, 0) AS c FROM sessions")[0]["c"]
        self.assertAlmostEqual(cost, s, places=6)
        self.assertEqual(sum(v for _, v in fams["pi_llm_calls"]["points"]), 4)
        self.assertEqual(sum(v for _, v in fams["pi_sessions"]["points"]), 1)
        for fam in fams.values():
            for labels, _ in fam["points"]:
                self.assertLessEqual(set(labels), ALLOWED_LABELS, fam["name"])
        self.assertEqual({tuple(sorted(l.items())) for l, _ in fams["pi_sessions"]["points"]},
                         {(("kind", "top"), ("project", "proj"))})
        # histogram bucket counts add up to the number of timed calls
        counts, total, n = [v for l, v in fams["pi_llm_call_duration_seconds"]["points"]][0]
        self.assertEqual(sum(counts), n)
        self.assertEqual(n, 4)
        errs = {l["detail"]: v for l, v in fams["pi_events"]["points"] if l["event"] == "llm.error"}
        self.assertEqual(errs, {"rate_limit": 1})

    def test_payload_has_no_content_session_ids_or_paths(self):
        self.build()
        con = ae.connect(self.db, readonly=True)
        payload = json.dumps(am.otlp_payload(am.collect(con) + am.self_metrics(con, {}, self.db), 1, 2))
        for needle in (SENTINEL, "sess-1", "/work/proj", str(self.root)):
            self.assertNotIn(needle, payload)

    def test_post_is_gzipped_otlp_json_and_rejections_fail(self):
        self.build()
        c = self.collector()
        con = ae.connect(self.db, readonly=True)
        fams, sent = am.export(con, self.db, {"epoch_ns": 5}, c.url)
        self.assertGreater(sent, 0)
        req = c.requests[0]
        self.assertEqual((req["path"], req["encoding"]), ("/v1/metrics", "gzip"))
        names = {m["name"] for m in req["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        self.assertIn("pi_notional_cost_usd", names)
        self.assertIn("pi_agent_events_last_build_success_timestamp_seconds", names)
        bad = Collector(body=b'{"partialSuccess":{"rejectedDataPoints":"3"}}')
        self.addCleanup(bad.close)
        with self.assertRaises(RuntimeError):
            am.export(con, self.db, {}, bad.url)

    def test_cli_export_only_reports_and_never_sends(self):
        self.build()
        c = self.collector()
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state))
        out = subprocess.run([sys.executable, str(CLI), "--db", str(self.db), "export"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("nothing is sent by this command", out.stdout)
        self.assertNotIn(SENTINEL, out.stdout)
        self.assertEqual(c.requests, [])


class AlwaysOn(Tick):
    def test_tick_builds_exports_and_records_status(self):
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)
        st = self.status()
        self.assertEqual((st["consecutive_build_failures"], st["last_parsed"], st["sessions"]), (0, 1, 1))
        self.assertTrue(st["last_build_ok_ts"] and st["last_export_ok_ts"])
        self.assertEqual(len(c.requests), 1)
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.status()["last_parsed"], 0)
        self.assertEqual(self.status()["epoch_ns"], st["epoch_ns"])  # counters keep one start time

    def test_without_an_endpoint_the_tick_builds_and_never_exports(self):
        self.assertEqual(am.run_once(self.root, self.db), 0)
        st = self.status()
        self.assertTrue(st["last_build_ok_ts"])
        self.assertNotIn("last_export_ok_ts", st)

    def test_an_unreachable_collector_does_not_stop_the_build_and_logs_once(self):
        os.environ["AGENT_EVENTS_OTLP_ENDPOINT"] = "http://127.0.0.1:9/v1/metrics"
        self.assertEqual(am.run_once(self.root, self.db), 1)
        self.assertEqual(am.run_once(self.root, self.db), 1)
        st = self.status()
        self.assertTrue(st["last_build_ok_ts"])
        self.assertTrue(st["last_export_error"])
        self.assertEqual((self.state / "agent.log").read_text().count("export failed"), 1)
        self.assertEqual(self.q("SELECT COUNT(*) AS n FROM sessions")[0]["n"], 1)

    def test_a_corrupt_database_is_set_aside_and_rebuilt(self):
        self.build()
        self.db.write_bytes(b"this is not a sqlite database" * 100)
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertTrue(Path(str(self.db) + ".corrupt").exists())
        self.assertEqual(self.q("SELECT COUNT(*) AS n FROM sessions")[0]["n"], 1)
        self.assertIn("setting it aside", (self.state / "agent.log").read_text())

    def test_a_hung_tick_gives_up_and_releases_the_lock(self):
        os.environ["AGENT_EVENTS_TICK_LIMIT_S"] = "1"
        self.addCleanup(lambda: os.environ.pop("AGENT_EVENTS_TICK_LIMIT_S", None))
        real = ae.build
        ae.build = lambda *a, **k: time.sleep(30)
        self.addCleanup(lambda: setattr(ae, "build", real))
        t0 = time.time()
        self.assertEqual(am.run_once(self.root, self.db), 1)
        self.assertLess(time.time() - t0, 10)
        self.assertIn("gave up", (self.state / "agent.log").read_text())
        with am.build_lock(blocking=False) as got:
            self.assertTrue(got)

    def test_a_bad_tick_limit_falls_back_and_never_leaves_the_handler_installed(self):
        import signal
        before = signal.getsignal(signal.SIGALRM)
        for bad in ("invalid", "0", "-5"):
            os.environ["AGENT_EVENTS_TICK_LIMIT_S"] = bad
            self.assertEqual(am.run_once(self.root, self.db), 0, bad)
            self.assertIs(signal.getsignal(signal.SIGALRM), before)
        os.environ.pop("AGENT_EVENTS_TICK_LIMIT_S", None)

    def test_a_run_that_overlaps_another_is_skipped(self):
        self.state.mkdir(parents=True)
        with open(self.state / "lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertFalse(self.db.exists())
        self.assertIn("skipped", (self.state / "agent.log").read_text())

    def test_log_is_rotated_and_holds_no_content(self):
        self.state.mkdir(parents=True)
        (self.state / "agent.log").write_text("x" * (am.LOG_LIMIT + 10))
        am.run_once(self.root, self.db)
        self.assertTrue((self.state / "agent.log.1").exists())
        for p in self.state.iterdir():
            self.assertNotIn(SENTINEL, p.read_text(errors="replace"))

    def test_status_reports_fresh_stale_and_never(self):
        text, code = am.cmd_status()
        self.assertEqual(code, 1)
        self.assertIn("never", text)
        am.run_once(self.root, self.db)
        text, code = am.cmd_status()
        self.assertEqual(code, 0, text)
        self.assertIn("fresh", text)
        st = self.status()
        st["last_build_ok_ts"] = time.time() - 3600
        am.save_status(st)
        text, code = am.cmd_status()
        self.assertEqual(code, 1)
        self.assertIn("STALE", text)

    def test_the_cli_runs_a_tick_and_status(self):
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state), PI_CODING_AGENT_DIR=str(self.root.parent),
                   XDG_DATA_HOME=str(Path(self._tmp.name) / "xdg"))
        env.pop("AGENT_EVENTS_OTLP_ENDPOINT", None)
        run = subprocess.run([sys.executable, str(CLI), "run"], capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        st = subprocess.run([sys.executable, str(CLI), "status"], capture_output=True, text=True, env=env)
        self.assertEqual(st.returncode, 0, st.stdout)


class DrillDown(Base):
    def setUp(self):
        super().setUp()
        standard_session().write(self.top())
        self.build()
        self.con = ae.connect(self.db, readonly=True)

    def show(self, **kw):
        args = type("A", (), {"ref": "sess-1", "turn": None, "call": None, "chars": 400, **kw})
        return ash.cmd_show(self.con, args)

    def test_turn_prints_local_content_from_the_session_file(self):
        out = self.show(turn=1)
        self.assertIn(ash.NOTICE, out)
        self.assertIn(SENTINEL, out)  # content is shown locally, on demand
        self.assertIn("USER:", out)
        self.assertNotIn("429 rate limit", out)  # turn 2 is not part of turn 1

    def test_errors_print_the_error_text_and_nothing_is_stored_for_it(self):
        out = self.show()
        self.assertIn("429 rate limit", out)
        stored = json.dumps([tuple(r) for t in ("events", "calls", "sessions") for r in self.q(f"SELECT * FROM {t}")])
        self.assertNotIn("429 rate limit", stored)

    def test_call_by_seq_and_clipping(self):
        seq = self.q("SELECT seq FROM calls WHERE kind='llm' ORDER BY seq LIMIT 1")[0]["seq"]
        out = self.show(call=seq, chars=10)
        self.assertIn("[+", out)

    def test_events_list_and_projects_report(self):
        ns = type("A", (), {"since": None, "kind": "llm.error", "list": True, "limit": 5})
        out = ae.cmd_events(self.con, ns)
        self.assertIn("proj", out)
        self.assertIn("agent-events show", out)
        self.assertNotIn(SENTINEL, out)
        out = ae.cmd_projects(self.con, type("A", (), {"since": None, "limit": 5}))
        self.assertIn("proj", out)
        self.assertIn("not a bill", out)


class ExportSafety(Tick):
    """Round-2 review: what may leave the machine, what failure paths may write, and counter behaviour."""

    def test_unapproved_directories_and_odd_names_never_become_labels(self):
        ae._GIT_ROOTS = {"loop-engine"}
        self.addCleanup(lambda: setattr(ae, "_GIT_ROOTS", None))
        for cwd, want in [("/private/tmp/tmpabc123", "other"), ("/tmp/some scratch dir", "other"),
                          ("/Volumes/Workshop/macbook/git/loop-engine-eval-x", "loop-engine"),
                          ("/work/proj", "proj"), ("/Users/alice/private stuff", "other"), (None, "unknown")]:
            self.assertEqual(ae.export_project(cwd), want, cwd)

    def test_export_names_reject_paths(self):
        for bad in ("/Users/alice/private/model.gguf", "Users/alice/x/model", "~/m", "a b", "", None, "../x", "x" * 200):
            self.assertEqual(am.export_name(bad), "other", bad)
        for good in ("gpt-6.1-sol", "anthropic/claude-fable-5", "llama3:8b", "mcp__ticktick__create_task", "bash"):
            self.assertEqual(am.export_name(good), good)

    def test_a_path_shaped_model_does_not_reach_the_payload(self):
        f = Fixture(session_id="sess-9")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, model="/Users/alice/private/model.gguf", stop="stop")
        f.write(self.top("--work-proj--/2026-10-01T00-00-09-000Z_sess-9.jsonl"))
        self.build()
        con = ae.connect(self.db, readonly=True)
        payload = json.dumps(am.otlp_payload(am.collect(con), 1, 2))
        self.assertNotIn("alice", payload)
        self.assertNotIn("/Users", payload)

    def test_failure_diagnostics_hold_no_paths_or_text(self):
        secret = f"/Users/alice/{SENTINEL}/session.jsonl"
        for exc in (FileNotFoundError(2, "No such file", secret), PermissionError(13, "denied", secret),
                    sqlite3.OperationalError(f"unable to open {secret}"), ValueError(secret), RuntimeError(secret)):
            self.assertNotIn(SENTINEL, am.safe_error(exc))
        self.assertEqual(am.safe_error(FileNotFoundError(2, "x", secret)), "FileNotFoundError: ENOENT")

    def test_a_failing_build_logs_and_stores_no_path_text(self):
        secret = f"/Users/alice/{SENTINEL}/session.jsonl"
        real = ae.build
        ae.build = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError(2, "No such file", secret))
        self.addCleanup(lambda: setattr(ae, "build", real))
        self.assertEqual(am.run_once(self.root, self.db), 1)
        for p in self.state.iterdir():
            self.assertNotIn(SENTINEL, p.read_text(errors="replace"), p.name)
        self.assertEqual(self.status()["last_build_error"], "FileNotFoundError: ENOENT")

    def test_a_session_that_vanishes_during_a_build_is_skipped(self):
        real = ae.parse_session
        def vanish(path):
            raise FileNotFoundError(2, "gone", str(path))
        ae.parse_session = vanish
        self.addCleanup(lambda: setattr(ae, "parse_session", real))
        res = self.build()
        self.assertEqual((res["parsed"], res["sessions"]), (0, 0))

    def test_a_busy_database_is_reported_never_set_aside(self):
        self.build()
        real = ae.build
        ae.build = lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked"))
        self.addCleanup(lambda: setattr(ae, "build", real))
        for _ in range(4):
            self.assertEqual(am.run_once(self.root, self.db), 1)
        self.assertTrue(self.db.exists())
        self.assertFalse(Path(str(self.db) + ".corrupt").exists())
        self.assertIn("busy", (self.state / "agent.log").read_text())

    def test_manual_builds_wait_for_the_scheduled_one(self):
        with am.build_lock(blocking=False) as first:
            self.assertTrue(first)
            with am.build_lock(blocking=False) as second:
                self.assertFalse(second)

    def _acc(self, state, values, business=True, fp="f"):
        """values: {label: number}; returns {label: exported value}."""
        fam = [{"name": "pi_x", "type": "sum", "points": [({"a": k}, v) for k, v in values.items()]}]
        _, out = am.account(fam, state, business, fp)
        return {l["a"]: v for l, v in out[0]["points"]} if out else {}

    def test_history_is_a_baseline_and_counters_never_decrease(self):
        s = {}
        self.assertEqual(self._acc(s, {"1": 1000}), {"1": 0})      # first run: history is not activity
        self.assertEqual(self._acc(s, {"1": 1000}), {"1": 0})      # first POST not yet confirmed: no growth
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"1": 1100}), {"1": 100})    # real growth
        self.assertEqual(self._acc(s, {"1": 900}), {"1": 100})     # a recomputed lower total: nothing added, no reset
        self.assertEqual(self._acc(s, {"1": 950}), {"1": 150})     # growth continues from the corrected baseline
        self.assertEqual(self._acc(s, {"1": 950}), {"1": 150})

    def test_a_new_series_is_sent_as_zero_until_delivered_then_its_first_occurrence_counts(self):
        s = {}
        self._acc(s, {"a": 5})
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"a": 5, "b": 1}), {"a": 0, "b": 0})
        self.assertEqual(self._acc(s, {"a": 5, "b": 1}), {"a": 0, "b": 0})   # the zero POST failed: still no growth
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"a": 5, "b": 1}), {"a": 0, "b": 1})   # delivered: the first occurrence counts

    def test_a_series_that_vanishes_keeps_its_value_and_its_pending_increment(self):
        s = {}
        self._acc(s, {"a": 5})
        am.mark_delivered(s)
        self._acc(s, {"a": 5, "b": 3})
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"a": 5}), {"a": 0, "b": 3})   # b's source vanished: its increment is still sent
        self.assertEqual(self._acc(s, {"a": 5}, business=False), {"a": 0, "b": 3})

    def test_a_changed_project_map_rebases_instead_of_counting_history(self):
        s = {}
        self._acc(s, {"other": 100}, fp="one")
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"other": 100}, fp="one"), {"other": 0})
        out = self._acc(s, {"other": 0, "newproj": 100}, fp="two")      # 100 errors moved to a newly approved project
        self.assertEqual(out, {"other": 0, "newproj": 0})
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"other": 0, "newproj": 105}, fp="two"), {"other": 0, "newproj": 5})

    def test_a_schema_rebase_keeps_exported_values_and_adds_no_spike(self):
        s = {}
        self._acc(s, {"active": 105000, "owner": 90}, fp="s3")
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"active": 105500, "owner": 95}, fp="s3"), {"active": 500, "owner": 5})
        am.mark_delivered(s)
        # schema 4: 12000 s of wait moves from active to owner. Nonzero exported values survive; nothing steps.
        self.assertEqual(self._acc(s, {"active": 93500, "owner": 12095}, fp="s4"), {"active": 500, "owner": 5})
        am.mark_delivered(s)
        self.assertEqual(self._acc(s, {"active": 93600, "owner": 12195}, fp="s4"), {"active": 600, "owner": 105})

    def test_the_real_fingerprint_changes_with_the_schema_version(self):
        before = am.fingerprint()
        real = ae.SCHEMA_VERSION
        ae.SCHEMA_VERSION = real + 1
        self.addCleanup(lambda: setattr(ae, "SCHEMA_VERSION", real))
        self.assertNotEqual(before, am.fingerprint())

    def test_histograms_are_accounted_bucket_by_bucket(self):
        s = {}
        h = lambda counts, sm, n: [{"name": "pi_h", "type": "histogram", "bounds": (1, 2), "points": [({}, (counts, sm, n))]}]
        am.account(h([1, 1, 0], 3.0, 2), s, True, "f")
        am.mark_delivered(s)
        out = am.account(h([2, 1, 1], 9.0, 4), s, True, "f")[1][0]
        self.assertEqual(out["points"][0][1], ([1, 0, 1], 6.0, 2))
        self.assertEqual(out["bounds"], (1, 2))
        out = am.account(h([1, 1, 1], 5.0, 3), s, True, "f")[1][0]   # a bucket went down: baseline correction only
        self.assertEqual(out["points"][0][1], ([1, 0, 1], 6.0, 2))

    def test_unusable_state_starts_a_new_epoch_with_zeroed_values(self):
        self.state.mkdir(parents=True, exist_ok=True)
        c = self.collector()
        value = lambda: [m for m in c.requests[-1]["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
                         if m["name"] == "pi_sessions"][0]["sum"]["dataPoints"][0]
        am.run_once(self.root, self.db)
        first_start = value()["startTimeUnixNano"]
        for junk in ("null", "[1]", "{not json", '{"series":{"k":{"n":1}}}', '{"series":[]}'):
            (self.state / "export_state.json").write_text(junk)
            self.assertEqual(am.load_state(), ({}, True), junk)
            time.sleep(0.01)
            am.run_once(self.root, self.db)
            self.assertEqual(value()["asDouble"], 0, junk)           # never raw history
            self.assertGreater(int(value()["startTimeUnixNano"]), int(first_start), junk)
            first_start = value()["startTimeUnixNano"]
        self.assertEqual(am.load_state()[1], False)

    def test_values_are_checkpointed_before_the_post_and_delivery_after(self):
        self.build()
        con = ae.connect(self.db, readonly=True)
        state = {}
        os.environ["AGENT_EVENTS_STATE_DIR"] = str(self.state)
        bad = Collector(body=b'{"partialSuccess":{"rejectedDataPoints":"1"}}')
        self.addCleanup(bad.close)
        with self.assertRaises(RuntimeError):
            am.export(con, self.db, {}, bad.url, state=state, persist=True)
        saved, lost = am.load_state()
        self.assertFalse(lost)
        self.assertTrue(saved["series"])                                # checkpointed although the POST failed
        self.assertFalse(any(e["ok"] for e in saved["series"].values()))   # and nothing is marked delivered

    def test_a_failed_or_dirty_build_sends_stale_accounted_values_and_never_collects(self):
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)
        real_collect = am.collect
        am.collect = lambda con: (_ for _ in ()).throw(AssertionError("must not collect"))
        self.addCleanup(lambda: setattr(am, "collect", real_collect))
        real = ae.build
        ae.build = lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked"))
        self.addCleanup(lambda: setattr(ae, "build", real))
        self.assertEqual(am.run_once(self.root, self.db), 1)
        names = {m["name"] for m in c.requests[-1]["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        self.assertIn("pi_sessions", names)
        self.assertIn("pi_agent_events_consecutive_build_failures", names)

    def test_a_permission_error_is_a_failed_build_not_a_silent_removal(self):
        self.build()
        real = ae.parse_session
        def deny(path):
            raise PermissionError(13, "denied", str(path))
        ae.parse_session = deny
        self.addCleanup(lambda: setattr(ae, "parse_session", real))
        self.top().touch()
        os.utime(self.top(), (1, 1))
        self.top().write_text(self.top().read_text() + "\n")   # changed file forces a re-parse
        with self.assertRaises(PermissionError):
            self.build()
        self.assertEqual(self.q("SELECT COUNT(*) AS n FROM sessions")[0]["n"], 1)

    def test_extra_hyphenated_project_slugs_resolve(self):
        ae._GIT_ROOTS = set()
        self.addCleanup(lambda: setattr(ae, "_GIT_ROOTS", None))
        os.environ["AGENT_EVENTS_PROJECTS"] = "budget-steward:proj"
        self.assertEqual(ae.export_project("/work/budget-steward"), "budget-steward")
        self.assertEqual(ae.export_project("/work/budget-steward-wt-2"), "budget-steward")
        self.assertEqual(ae.export_project("/work/other-thing"), "other")

    def test_export_accepts_the_dry_run_flag_and_never_sends(self):
        self.build()
        c = self.collector()
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state))
        out = subprocess.run([sys.executable, str(CLI), "--db", str(self.db), "export", "--dry-run"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(c.requests, [])

    def test_state_validation_covers_histograms_and_bad_encoding(self):
        self.state.mkdir(parents=True, exist_ok=True)
        good = {"n": "pi_h", "t": "histogram", "l": {}, "b": [1, 2], "last": [0] * 5, "sent": [0] * 5, "seen": [0] * 5, "ok": True}
        path = self.state / "export_state.json"
        path.write_text(json.dumps({"series": {"k": good}}))
        self.assertFalse(am.load_state()[1])
        for mutate in (lambda e: e.pop("b"), lambda e: e.update(last=[0]), lambda e: e.update(b=[]),
                       lambda e: e.update(b="x"), lambda e: e.update(sent=[0] * 4)):
            bad = json.loads(json.dumps(good))
            mutate(bad)
            path.write_text(json.dumps({"series": {"k": bad}}))
            self.assertEqual(am.load_state(), ({}, True))
        path.write_bytes(b"\xff\xfe\x00 not utf8")
        self.assertEqual(am.load_state(), ({}, True))
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)      # recovers instead of failing every tick
        self.assertFalse(am.load_state()[1])

    def test_nonfinite_state_values_are_lost_state(self):
        good = {"n": "pi_h", "t": "histogram", "l": {}, "b": [1, 2], "last": [0] * 5, "sent": [0] * 5, "seen": [0] * 5, "ok": True}
        self.state.mkdir(parents=True, exist_ok=True)
        path = self.state / "export_state.json"
        for field, vec in (("sent", [0, 0, 0, 0, 1e309]), ("last", [0, 0, 0, 0, float("nan")]), ("b", [1, 1e309])):
            bad = dict(good, **{field: vec})
            path.write_text(json.dumps({"series": {"k": bad}}))   # json.dumps writes Infinity/NaN, json.loads reads them
            self.assertEqual(am.load_state(), ({}, True), field)
        path.write_text('{"series":{"k":{"n":"x","t":"sum","l":{},"b":[],"last":[0],"sent":[1e999],"seen":[0],"ok":true}}}')
        self.assertEqual(am.load_state(), ({}, True))
        self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)

    def test_huge_integers_and_overflowing_sums_are_lost_state(self):
        self.state.mkdir(parents=True, exist_ok=True)
        path = self.state / "export_state.json"
        huge = "1" + "0" * 400
        for body in ('{"series":{"k":{"n":"x","t":"sum","l":{},"b":[],"last":[%s],"sent":[0],"seen":[0],"ok":true}}}' % huge,
                     '{"series":{"k":{"n":"pi_h","t":"histogram","l":{},"b":[1,%s],"last":[0,0,0,0,0],"sent":[0,0,0,0,0],"seen":[0,0,0,0,0],"ok":true}}}' % huge,
                     '{"series":{"k":{"n":"pi_h","t":"histogram","l":{},"b":[1,2],"last":[0,0,0,0,0],"sent":[1e308,1e308,1e308,1e308,1e308],"seen":[1e308,1e308,1e308,1e308,1e308],"ok":true}}}'):
            path.write_text(body)
            self.assertEqual(am.load_state(), ({}, True), body[:60])
        self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)

    def test_a_layout_change_retires_vanished_siblings_too(self):
        s = {}
        h = lambda bounds, pts: [{"name": "pi_h", "type": "histogram", "bounds": bounds,
                                  "points": [({"a": k}, (c, sm, n)) for k, (c, sm, n) in pts.items()]}]
        am.account(h((1, 2), {"a": ([0, 0, 0], 0.0, 0), "b": ([0, 0, 0], 0.0, 0)}), s, True, "f")
        am.mark_delivered(s)
        _, fams = am.account(h((1, 2, 3), {"a": ([0, 0, 0, 1], 4.0, 1)}), s, True, "f")
        self.assertEqual(len(fams[0]["points"]), 1)               # b was retired, not left with a stale layout
        for labels, (counts, sm, n) in fams[0]["points"]:
            self.assertEqual(len(counts), len(fams[0]["bounds"]) + 1)
        self.assertTrue(am._valid_state(s))

    def test_a_changed_histogram_layout_restarts_at_zero(self):
        s = {}
        h = lambda bounds, counts, sm, n: [{"name": "pi_h", "type": "histogram", "bounds": bounds, "points": [({}, (counts, sm, n))]}]
        am.account(h((1, 2), [0, 0, 0], 0.0, 0), s, True, "f")
        am.mark_delivered(s)
        out = am.account(h((1, 2, 3), [0, 0, 0, 1], 4.0, 1), s, True, "f")[1][0]
        self.assertEqual(out["bounds"], (1, 2, 3))
        self.assertEqual(out["points"][0][1], ([0, 0, 0, 0], 0.0, 0))
        self.assertTrue(am._valid_state(s))
        am.mark_delivered(s)
        out = am.account(h((1, 2, 3), [0, 0, 0, 2], 9.0, 2), s, True, "f")[1][0]
        self.assertEqual(out["points"][0][1], ([0, 0, 0, 1], 5.0, 1))

    def test_ticks_keep_the_exported_session_count_monotonic_when_a_file_is_removed(self):
        c = self.collector()
        value = lambda: [m for m in c.requests[-1]["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
                         if m["name"] == "pi_sessions"][0]["sum"]["dataPoints"][0]["asDouble"]
        am.run_once(self.root, self.db)
        self.assertEqual(value(), 0)               # the existing session is history: baseline
        second = Fixture(session_id="sess-2")
        second.user(T + 1000)
        second.llm(T + 1500, T + 2500, stop="stop")
        path = second.write(self.top("--work-proj--/2026-10-01T00-00-02-000Z_sess-2.jsonl"))
        am.run_once(self.root, self.db)
        self.assertEqual(value(), 1)               # a new session after the baseline is activity
        path.unlink()
        am.run_once(self.root, self.db)
        self.assertEqual(value(), 1)               # the database says 1 again; the exported counter does not go backwards
        am.run_once(self.root, self.db)
        self.assertEqual(value(), 1)



class MachineLabel(Tick):
    """Every push names its machine (AGENT_EVENTS_MACHINE), so two Macs never write the same series."""

    def metrics_of(self, req):
        return req["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]

    def resource_of(self, req):
        return {a["key"]: a["value"]["stringValue"] for a in req["body"]["resourceMetrics"][0]["resource"]["attributes"]}

    def sessions_value(self, req, project="proj"):
        fam = [m for m in self.metrics_of(req) if m["name"] == "pi_sessions"][0]
        pts = {next(a["value"]["stringValue"] for a in p["attributes"] if a["key"] == "project"): p["asDouble"]
               for p in fam["sum"]["dataPoints"]}
        return pts.get(project)

    def test_only_a_slug_is_a_machine_label(self):
        for good in ("personal", "work", "test-fake", "a", "mac2", "a" + "b" * 31):
            os.environ["AGENT_EVENTS_MACHINE"] = good
            self.assertEqual(am.machine(), good, good)
        for bad in ("", "Work", "my mac", "my-mac ", " work", "a/b", "../x", "-x", "1mac", "work_mac", "mac.local",
                    "mac\n", "a" * 33, "w\u00f6rk", "\u0440ersonal"):
            os.environ["AGENT_EVENTS_MACHINE"] = bad
            self.assertIsNone(am.machine(), repr(bad))
        os.environ.pop("AGENT_EVENTS_MACHINE")
        self.assertIsNone(am.machine())

    def test_a_tick_without_a_valid_machine_label_sends_nothing_and_says_why(self):
        c = self.collector()
        for value in (None, "", "Work Mac", "../x"):
            if value is None:
                os.environ.pop("AGENT_EVENTS_MACHINE", None)
            else:
                os.environ["AGENT_EVENTS_MACHINE"] = value
            self.assertEqual(am.run_once(self.root, self.db), 1, repr(value))
            self.assertEqual(c.requests, [], repr(value))
            self.assertIn("AGENT_EVENTS_MACHINE", self.status()["last_export_error"], repr(value))
            self.assertNotIn("last_export_ok_ts", self.status(), repr(value))
            self.assertTrue(self.status()["last_build_ok_ts"], "the build still runs")
            # refused before any accounting: no checkpoint, so the first real push is still a clean baseline
            self.assertFalse((self.state / "export_state.json").exists(), repr(value))
        self.assertEqual((self.state / "agent.log").read_text().count("AGENT_EVENTS_MACHINE is unset"), 1)
        text, _ = am.cmd_status()
        self.assertIn("machine label         : not set in the scheduled run (AGENT_EVENTS_MACHINE)", text)
        os.environ["AGENT_EVENTS_MACHINE"] = "test-mac"
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(len(c.requests), 1)
        self.assertIsNone(self.status()["last_export_error"])
        self.assertIn("machine label         : test-mac", am.cmd_status()[0])

    def test_status_reports_the_scheduled_runs_label_not_the_shells(self):
        # The label lives in the LaunchAgent's environment; 'agent-events status' runs in a shell that does not have it.
        self.build()
        self.collector()
        self.assertIn("machine label         : unknown", am.cmd_status()[0])
        self.assertEqual(am.run_once(self.root, self.db), 0)   # the scheduled run, with AGENT_EVENTS_MACHINE=test-mac
        del os.environ["AGENT_EVENTS_MACHINE"]                  # the interactive shell
        self.assertIn("machine label         : test-mac", am.cmd_status()[0])
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state))
        out = subprocess.run([sys.executable, str(CLI), "--db", str(self.db), "export"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("machine: not set in this shell (AGENT_EVENTS_MACHINE)", out.stdout)
        self.assertIn("the scheduled run uses the LaunchAgent's environment (chezmoi data agentEvents); its machine label: test-mac", out.stdout)

    def test_post_refuses_a_payload_without_a_machine_label(self):
        self.build()
        c = self.collector()
        con = ae.connect(self.db, readonly=True)
        self.addCleanup(con.close)
        metrics = am.collect(con) + am.self_metrics(con, {}, self.db)
        for label in (None, "Not A Slug"):
            with self.assertRaises(RuntimeError) as cm:
                am.post(c.url, am.otlp_payload(metrics, 1, 2, label))
            self.assertIn("machine label", am.safe_error(cm.exception))
        self.assertEqual(c.requests, [])
        am.post(c.url, am.otlp_payload(metrics, 1, 2, "test-mac"))
        self.assertEqual(len(c.requests), 1)

    def test_every_push_carries_the_machine_on_the_resource_not_on_the_points(self):
        c = self.collector()
        os.environ["AGENT_EVENTS_MACHINE"] = "test-fake"
        self.assertEqual(am.run_once(self.root, self.db), 0)
        req = c.requests[0]
        self.assertEqual(self.resource_of(req), {"service.name": "agent-events", "machine": "test-fake"})
        for m in self.metrics_of(req):
            body = m.get("sum") or m.get("gauge") or m.get("histogram")
            for p in body["dataPoints"]:
                self.assertNotIn("machine", {a["key"] for a in p["attributes"]}, m["name"])
        self.assertIn("pi_agent_events_export_timestamp_seconds", {m["name"] for m in self.metrics_of(req)})

    def test_the_fingerprint_follows_the_machine_label(self):
        a = am.fingerprint()
        os.environ["AGENT_EVENTS_MACHINE"] = "other-mac"
        self.assertNotEqual(a, am.fingerprint())
        os.environ["AGENT_EVENTS_MACHINE"] = "test-mac"
        self.assertEqual(a, am.fingerprint())

    def test_a_new_machine_label_is_a_clean_baseline_not_a_history_spike(self):
        c = self.collector()
        os.environ["AGENT_EVENTS_MACHINE"] = "old-label"
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.sessions_value(c.requests[-1]), 0)   # first push: history is not activity
        # The label changes (the first run with a label, or a renamed machine). Meanwhile two sessions with history
        # appeared in a directory that becomes a new series ("other"); on the collector every series is new too.
        for i in (2, 3):
            f = Fixture(session_id=f"sess-{i}", cwd="/x/elsewhere")
            f.user(T + 1000)
            f.llm(T + 1500, T + 2500, stop="stop")
            f.write(self.top(f"--x-elsewhere--/2026-10-01T00-00-0{i}-000Z_sess-{i}.jsonl"))
        os.environ["AGENT_EVENTS_MACHINE"] = "new-label"
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.resource_of(c.requests[-1])["machine"], "new-label")
        self.assertEqual(self.sessions_value(c.requests[-1]), 0)
        self.assertEqual(self.sessions_value(c.requests[-1], "other"), 0)
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.sessions_value(c.requests[-1], "other"), 0, "the history of the new series stays out")
        # real activity after the change is counted
        f = Fixture(session_id="sess-4", cwd="/x/elsewhere")
        f.user(T + 1000)
        f.llm(T + 1500, T + 2500, stop="stop")
        f.write(self.top("--x-elsewhere--/2026-10-01T00-00-04-000Z_sess-4.jsonl"))
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.sessions_value(c.requests[-1], "other"), 1)

    def test_the_cli_preview_names_the_machine(self):
        self.build()
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state))
        for value, want in (("test-mac", "machine: test-mac"), ("Bad Label", "machine: not set in this shell (AGENT_EVENTS_MACHINE)")):
            env["AGENT_EVENTS_MACHINE"] = value
            out = subprocess.run([sys.executable, str(CLI), "--db", str(self.db), "export"], capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(want, out.stdout)


if __name__ == "__main__":
    unittest.main()
