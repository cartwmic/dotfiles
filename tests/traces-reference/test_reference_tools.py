"""Traces stage 2, S0: the Python reference tooling in dot_local/share/agent-events.

parity_dump.py, rollback_drill.py, freeze.sh, shadow_py_run.py, cache_ref.py and reference.sha256. Everything runs on
synthetic session files in a scratch directory with a scratch HOME; the live agent-events directories are never read or
written. Needs python3, sh; the deployment tests need chezmoi.
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "dot_local/share/agent-events"
SYNTH = Path(__file__).resolve().parent / "synth_corpus.py"
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True
import reference_common as rc  # noqa: E402

FROZEN = ("agent_events.py", "agent_events_metrics.py", "agent_events_review.py", "agent_events_show.py")
NOW = (1_790_000_600, 1_790_001_800, 1_790_003_000)  # T+10 min, T+30 min, T+50 min of the builder corpus


class Scratch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="s0-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()

    def env(self, **extra):
        base = {k: v for k, v in os.environ.items() if not k.startswith(("AGENT_EVENTS_", "AGENT_TRACES_", "XDG_"))}
        base.update(HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1", TZ="UTC", AGENT_EVENTS_PROJECT_ROOTS=str(self.tmp / "roots"),
                    AGENT_TRACES_DIR=str(self.tmp / "no-traces"))
        (self.tmp / "roots").mkdir(exist_ok=True)
        base.update(extra)
        return base

    def run_py(self, script, *args, directory=TOOLS, env=None, check=False):
        return subprocess.run([sys.executable, str(Path(directory) / script), *map(str, args)], capture_output=True, text=True,
                              env=env or self.env(), timeout=300, check=check)

    def corpus(self, kind, **kw):
        out = self.tmp / kind
        subprocess.run([sys.executable, str(SYNTH), kind, str(out)], check=True, capture_output=True,
                       env=self.env(), cwd=self.tmp)
        return out

    def tamper_copy(self, name, suffix="#"):
        """A scratch copy of the tool directory with one byte appended to a frozen file."""
        d = self.tmp / ("tampered-" + name)
        shutil.copytree(TOOLS, d, ignore=shutil.ignore_patterns("__pycache__", "fixtures", "test_*"))
        with open(d / name, "a") as fh:
            fh.write(suffix)
        return d

    def tree_hash(self, root):
        h = hashlib.sha256()
        for p in sorted(Path(root).rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes())
        return h.hexdigest()


class PinnedDumps(Scratch):
    def test_reference_dumps_match_the_pinned_list(self):
        """The dumps handed to S1: rebuilt from the corpora here, they must hash to the committed list."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import reference_dumps
        got = reference_dumps.make(self.tmp / "dumps")
        want = (Path(__file__).resolve().parent / "reference-dumps.sha256").read_text().splitlines()
        self.assertEqual(got, want)


class FrozenSet(Scratch):
    def test_manifest_matches_the_four_frozen_files(self):
        """The freeze, enforced: change a frozen file and this fails until the reference is re-recorded on purpose."""
        lines = [l.split() for l in (TOOLS / "reference.sha256").read_text().splitlines() if l.strip()]
        self.assertEqual(sorted(n for _, n in lines), sorted(FROZEN))
        for sha, name in lines:
            self.assertEqual(hashlib.sha256((TOOLS / name).read_bytes()).hexdigest(), sha, name)

    def test_one_changed_byte_makes_every_tool_exit_2(self):
        corpus = self.corpus("builder")
        for name in ("agent_events_metrics.py", "agent_events.py", "agent_events_review.py"):
            d = self.tamper_copy(name)
            with self.subTest(changed=name):
                cases = [("shadow_py_run.py", ["status"]),
                         ("cache_ref.py", ["--db", self.tmp / "x.sqlite", "--scratch", self.tmp, "--now", "1"]),
                         ("parity_dump.py", ["dump", "--sessions-dir", corpus, "--out", self.tmp / ("o-" + name)])]
                (self.tmp / "x.sqlite").write_bytes(b"")
                for script, args in cases:
                    r = self.run_py(script, *args, directory=d)
                    self.assertEqual(r.returncode, 2, (script, r.stderr))
                    self.assertIn("refusing to run", r.stderr)
                    self.assertIn(name, r.stderr)

    def test_missing_or_bad_manifest_exits_2(self):
        d = self.tamper_copy("agent_events.py", "")
        (d / "reference.sha256").unlink()
        r = self.run_py("shadow_py_run.py", "status", directory=d)
        self.assertEqual(r.returncode, 2, r.stderr)
        (d / "reference.sha256").write_text("not a sha line\n")
        self.assertEqual(self.run_py("shadow_py_run.py", "status", directory=d).returncode, 2)

    def test_untouched_copy_runs(self):
        d = self.tamper_copy("agent_events.py", "")
        r = self.run_py("shadow_py_run.py", "status", directory=d, env=self.env(AGENT_EVENTS_STATE_DIR=str(self.tmp / "st")))
        self.assertIn(r.returncode, (0, 1), r.stderr)  # status answers; it is stale here
        self.assertIn("last successful build", r.stdout)


class ParityDump(Scratch):
    def dump(self, corpus, out, *extra):
        r = self.run_py("parity_dump.py", "dump", "--sessions-dir", corpus, "--out", out, "--home", "/home/parity", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return Path(out)

    def test_second_run_is_byte_identical_and_complete(self):
        corpus = self.corpus("builder")
        args = ["--now", *map(str, NOW), "--replay-ticks", "3"]
        a, b = self.dump(corpus, self.tmp / "a", *args), self.dump(corpus, self.tmp / "b", *args)
        self.assertEqual(self.tree_hash(a), self.tree_hash(b))
        names = {str(p.relative_to(a)) for p in a.rglob("*") if p.is_file()}
        for want in ("meta.json", "collect.json", "project-map.json", "tables/calls.jsonl", "tables/files.jsonl",
                     "gauges-1790000600.json", "gauges-1790003000.json", "tick-0/state.json", "tick-2/payload.json"):
            self.assertIn(want, names)
        meta = json.loads((a / "meta.json").read_text())
        self.assertEqual(meta["schema_version"], 4)
        self.assertGreater(meta["row_counts"]["calls"], 20)

    def test_normalised_paths_and_sorted_rows(self):
        out = self.dump(self.corpus("builder"), self.tmp / "o")
        files = [json.loads(l) for l in (out / "tables/files.jsonl").read_text().splitlines()]
        self.assertTrue(all(not f["path"].startswith("/") and f["mtime_ns"] == 0 for f in files))
        self.assertEqual([f["path"] for f in files], sorted(f["path"] for f in files))
        calls = [json.loads(l) for l in (out / "tables/calls.jsonl").read_text().splitlines()]
        keys = [(c["path"], c["seq"]) for c in calls]
        self.assertEqual(keys, sorted(keys))

    def test_gauges_by_window_and_the_streak_only_family(self):
        out = self.dump(self.corpus("builder"), self.tmp / "o", "--now", *map(str, NOW))
        by = lambda now: {f["name"]: f["points"] for f in json.loads((out / f"gauges-{now}.json").read_text())["families"]}
        early, late = by(NOW[0]), by(NOW[2])
        self.assertTrue(early["pi_cache_calls_30m"] and early["pi_cache_miss_streak"])
        self.assertTrue(any(p["value"] >= 3 for p in early["pi_cache_miss_streak"]))
        # at T+50 min every call is more than 30 minutes old: the four window families are empty, the streak family is not
        self.assertEqual([late[n] for n in late if n != "pi_cache_miss_streak"], [[]] * 4)
        self.assertTrue(late["pi_cache_miss_streak"])

    def test_odd_inputs_dump_identically_from_two_corpus_locations(self):
        """The fallback dedupe_key of an untimed call carries the file path: the dump must not carry the corpus location."""
        first, second = self.corpus("odd"), self.tmp / "elsewhere" / "odd"
        subprocess.run([sys.executable, str(SYNTH), "odd", str(second)], check=True, capture_output=True, env=self.env())
        a, b = self.dump(first, self.tmp / "a"), self.dump(second, self.tmp / "b")
        self.assertNotIn(str(self.tmp), "".join(p.read_text() for p in a.rglob("*.json*")))
        self.assertEqual(self.tree_hash(a), self.tree_hash(b))
        self.assertEqual(json.loads((a / "meta.json").read_text())["malformed_lines"] >= 1, True)

    def test_refuses_a_dirty_out_and_a_live_state_dir(self):
        corpus = self.corpus("builder")
        (self.tmp / "dirty").mkdir()
        (self.tmp / "dirty/x").write_text("x")
        r = self.run_py("parity_dump.py", "dump", "--sessions-dir", corpus, "--out", self.tmp / "dirty")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not empty", r.stderr)
        live = Path(os.path.expanduser("~")) / ".local/state/agent-events"
        r = self.run_py("parity_dump.py", "dump", "--sessions-dir", corpus, "--out", self.tmp / "ok",
                        env=self.env(AGENT_EVENTS_STATE_DIR=str(live)))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("live directory", r.stderr)

    def test_replay_state_is_one_the_collector_accepts_and_pins_the_clock(self):
        out = self.dump(self.corpus("builder"), self.tmp / "o", "--replay-ticks", "2", "--replay-start", "1790000600")
        body = json.loads((out / "tick-1/payload.json").read_text())
        gauges = {m["name"]: m for m in body["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        stamp = gauges["pi_agent_events_export_timestamp_seconds"]["gauge"]["dataPoints"][0]
        self.assertEqual(stamp["asDouble"], 1790000720.0)
        self.assertEqual(stamp["timeUnixNano"], str(1790000720 * 10**9))


def fresh_run_env(test, kind="fresh"):
    """A scratch Pi home with a fresh-activity corpus; returns (env builder, sessions)."""
    pi = test.tmp / "pi"
    sessions = pi / "sessions"
    subprocess.run([sys.executable, str(SYNTH), kind, str(sessions)], check=True, capture_output=True, env=test.env())

    def env(name, receiver):
        return test.env(PI_CODING_AGENT_DIR=str(pi), XDG_DATA_HOME=str(test.tmp / name / "data"),
                        AGENT_EVENTS_STATE_DIR=str(test.tmp / name / "state"), AGENT_EVENTS_MACHINE="test-parity-py",
                        AGENT_EVENTS_OTLP_ENDPOINT=receiver.url)
    return env, sessions


class ControlArm(Scratch):
    def test_shadow_sends_no_cache_names_and_the_collector_does(self):
        env, _ = fresh_run_env(self)
        with rc.Receiver() as shadow, rc.Receiver() as plain:
            r = self.run_py("shadow_py_run.py", "run", env=env("shadow", shadow))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self.run_py("agent_events.py", "run", env=env("plain", plain))
            self.assertEqual(r.returncode, 0, r.stderr)
        cache = lambda rec: sorted(n for n in rec.names() if n.startswith("pi_cache_"))
        self.assertEqual(cache(plain), ["pi_cache_calls_30m", "pi_cache_full_miss_calls_30m", "pi_cache_hit_ratio_30m",
                                        "pi_cache_miss_streak", "pi_cache_uncached_tokens_30m"])
        self.assertEqual(cache(shadow), [], "the control arm must send no pi_cache_* name")
        # nothing else is dropped: every other name the plain run sent, the shadow sent too
        self.assertEqual([n for n in plain.names() if not n.startswith("pi_cache_")], shadow.names())
        self.assertIn("pi_sessions", shadow.names())

    def test_shadow_exits_2_with_one_byte_changed_beside_it(self):
        env, _ = fresh_run_env(self)
        d = self.tamper_copy("agent_events_metrics.py")
        with rc.Receiver() as shadow:
            r = self.run_py("shadow_py_run.py", "run", directory=d, env=env("shadow", shadow))
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertEqual(shadow.bodies, [], "nothing may be sent")
        self.assertFalse((self.tmp / "shadow/state").exists())

    def test_shadow_shows_the_same_verbs_as_the_collector(self):
        r = self.run_py("shadow_py_run.py", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("build", r.stdout)


class CacheRef(Scratch):
    def build_db(self):
        """A scratch database from the fresh corpus, and the in-process frozen modules to call directly."""
        _, sessions = fresh_run_env(self)
        db = self.tmp / "scratch" / "events.sqlite"
        r = self.run_py("agent_events.py", "--db", db, "build", "--sessions-dir", sessions,
                        env=self.env(AGENT_EVENTS_STATE_DIR=str(self.tmp / "scratch/state")))
        self.assertEqual(r.returncode, 0, r.stderr)
        return db

    def direct(self, db, nows):
        code = ("import json,sys; sys.path.insert(0, %r); import shadow_py_run as s; ae, m = s.load_frozen(%r);"
                "con = ae.connect(%r, readonly=True); out = []\n"
                "for now in %r:\n"
                "    g = m.cache_gauges(con, now); st = m.miss_streaks(con, now)\n"
                "    out.append({'gauges': {x['name']: sorted(([l, v] for l, v in x['points']), key=lambda p: json.dumps(p[0], sort_keys=True)) for x in g},\n"
                "                'streaks': sorted(([l, v] for l, v in st), key=lambda p: json.dumps(p[0], sort_keys=True))})\n"
                "print(json.dumps(out))") % (str(TOOLS), str(TOOLS), str(db), list(nows))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=self.env(), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_returns_what_the_functions_return(self):
        db = self.build_db()
        now = time.time()
        nows = [now, now + 600, now + 31 * 60, now + 75 * 60]  # in window; 10 min on; windows closing; past the streak hour
        r = self.run_py("cache_ref.py", "--db", db, "--scratch", self.tmp / "scratch", "--now", *map(repr, nows))
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        want = self.direct(db, nows)
        self.assertEqual(len(got["results"]), 4)
        for g, w in zip(got["results"], want):
            self.assertEqual({x["name"]: [[p["labels"], p["value"]] for p in x["points"]] for x in g["gauges"]}, w["gauges"])
            self.assertEqual([[p["labels"], p["value"]] for p in g["miss_streaks"]], w["streaks"])
            self.assertEqual(g["gauges"][-1]["name"], "pi_cache_miss_streak")
        first = {x["name"]: x["points"] for x in got["results"][0]["gauges"]}
        self.assertEqual(len(first["pi_cache_calls_30m"]), 2)  # S1 holds calls of two models in the window; S2 is out of it
        self.assertTrue(any(p["value"] == 3.0 for p in first["pi_cache_miss_streak"]))
        self.assertTrue(got["results"][3]["gauges"][0]["points"] == [] and got["results"][3]["miss_streaks"] == [])
        self.assertEqual(got["reference_sha256"], hashlib.sha256((TOOLS / "reference.sha256").read_bytes()).hexdigest())

    def test_refuses_a_db_outside_its_scratch_and_exits_2_on_a_changed_module(self):
        db = self.build_db()
        other = self.tmp / "elsewhere"
        other.mkdir()
        r = self.run_py("cache_ref.py", "--db", db, "--scratch", other, "--now", "1")
        self.assertEqual(r.returncode, 64, r.stderr)
        self.assertIn("not inside --scratch", r.stderr)
        live = Path(os.path.expanduser("~")) / ".local/share/agent-events/events.sqlite"
        r = self.run_py("cache_ref.py", "--db", live, "--scratch", other, "--now", "1")
        self.assertEqual(r.returncode, 64, r.stderr)
        r = self.run_py("cache_ref.py", "--db", db, "--scratch", self.tmp / "scratch", "--now", "1",
                        directory=self.tamper_copy("agent_events_metrics.py"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(r.stdout, "")


DRILL_ARGS = ("--machine", "personal", "--home", "/home/parity")


class RollbackDrill(Scratch):
    def setUp(self):
        super().setUp()
        self.corpus_dir = self.corpus("builder")
        seed = self.tmp / "seed"
        r = self.run_py("parity_dump.py", "dump", "--sessions-dir", self.corpus_dir, "--out", seed, "--home", "/home/parity",
                        "--replay-ticks", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.state = json.loads((seed / "tick-0/state.json").read_text())
        for e in self.state["series"].values():  # an aged state: half of what was seen has been sent, so `sent` is not all zeros
            n = len(e["seen"])
            e["sent"] = [v / 2 if e["t"] == "sum" or i == n - 2 else float(int(v) // 2) for i, v in enumerate(e["seen"])]  # histogram counts stay whole
        self.py_db = self.tmp / "py.sqlite"
        r = self.run_py("agent_events.py", "--db", self.py_db, "build", "--sessions-dir", self.corpus_dir,
                        env=self.env(AGENT_EVENTS_STATE_DIR=str(self.tmp / "pystate")))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.n = 0

    def inputs(self, state=None, status_text='{"epoch_ns": 1790000000123456789, "last_build_ok_ts": 1790000500}'):
        self.n += 1
        d = self.tmp / f"in{self.n}"
        d.mkdir()
        (d / "export_state.json").write_text(json.dumps(state if state is not None else self.state, separators=(",", ":")))
        (d / "status.json").write_text(status_text)
        return d

    def drill(self, d, *extra):
        self.n += 1
        return self.run_py("rollback_drill.py", "--state", d / "export_state.json", "--status", d / "status.json",
                           "--py-db", self.py_db, "--sessions-dir", self.corpus_dir, "--scratch", self.tmp / f"scratch{self.n}",
                           "--out", self.tmp / f"result{self.n}.json", *DRILL_ARGS, *extra), self.tmp / f"result{self.n}.json"

    def test_a_python_written_state_passes(self):
        r, out = self.drill(self.inputs())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = json.loads(out.read_text())
        self.assertTrue(res["ok"])
        self.assertEqual(list(res["steps"]), ["0 catch-up within limit", "1 load_state is not lost",
                                              "2-3 tick 1 keeps keys, fp, seeded, sent, epoch_ns", "4 tick 2 adds only seen - last"])

    def test_tick_two_adds_exactly_the_increment_when_the_corpus_grew(self):
        d = self.inputs()
        grow = ("import json, sys, types; sys.path.insert(0, %r); import rollback_drill as rd; from pathlib import Path\n"
                "import os\n"
                "p = next(Path(%r).glob('--git-dotfiles--/*.jsonl'))\n"
                "def between():\n"
                "    lines = p.read_text().splitlines()\n"
                "    e = [x for x in map(json.loads, lines) if x.get('message', {}).get('role') == 'assistant'][-1]; e = dict(e, id='extra-1')\n"
                "    e['message'] = dict(e['message'], usage=dict(e['message']['usage'], output=777))\n"
                "    p.write_text('\\n'.join(lines + [json.dumps(e)]) + '\\n')\n"
                "a = types.SimpleNamespace(state=%r, status=%r, machine='personal', py_db=%r, sessions_dir=%r, scratch=%r, out='', roots=None,\n"
                "                          projects=None, home='/home/parity', catchup_limit=600.0, now=None, now2=None)\n"
                "res = rd.drill(a, between)\n"
                "print(json.dumps(res))\n") % (str(TOOLS), str(self.corpus_dir), str(d / "export_state.json"), str(d / "status.json"),
                                               str(self.py_db), str(self.corpus_dir), str(self.tmp / "scratch-grow"))
        r = subprocess.run([sys.executable, "-c", grow], capture_output=True, text=True, env=self.env(), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout.splitlines()[-1])
        self.assertTrue(res["ok"], res)
        self.assertNotIn(", 0 moved", res["steps"]["4 tick 2 adds only seen - last"]["detail"])

    def test_m9_compact_keys_load_but_fail_the_key_set(self):
        """Python loads the state (not lost), but every key is new and the whole history would land as one tick."""
        state = copy.deepcopy(self.state)
        state["series"] = {k.replace('", "', '","').replace('], [', '],['): v for k, v in state["series"].items()}
        self.assertNotEqual(set(state["series"]), set(self.state["series"]))
        r, out = self.drill(self.inputs(state))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        res = json.loads(out.read_text())
        self.assertTrue(res["steps"]["1 load_state is not lost"]["ok"])
        self.assertIn("key set changed", res["steps"]["2-3 tick 1 keeps keys, fp, seeded, sent, epoch_ns"]["detail"])

    def test_m13_a_state_without_ok_is_lost(self):
        state = copy.deepcopy(self.state)
        for e in state["series"].values():
            del e["ok"]
        r, out = self.drill(self.inputs(state))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        steps = json.loads(out.read_text())["steps"]
        self.assertFalse(steps["1 load_state is not lost"]["ok"])

    def test_m14_epoch_ns_through_a_float_fails(self):
        r, out = self.drill(self.inputs(status_text='{"epoch_ns": 1.790000000123457e18, "last_build_ok_ts": 1790000500}'))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("epoch_ns", json.loads(out.read_text())["steps"]["2-3 tick 1 keeps keys, fp, seeded, sent, epoch_ns"]["detail"])

    def test_a_wrong_machine_label_starts_a_baseline_and_fails_on_fp(self):
        d = self.inputs()
        self.n += 1
        r = self.run_py("rollback_drill.py", "--state", d / "export_state.json", "--status", d / "status.json", "--py-db", self.py_db,
                        "--sessions-dir", self.corpus_dir, "--scratch", self.tmp / "s-wrong", "--out", self.tmp / "r-wrong.json",
                        "--machine", "work", "--home", "/home/parity")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("fp/seeded changed", r.stdout)

    def test_histogram_bounds_that_python_does_not_share_reset_sent_and_fail(self):
        """A state written with other bucket bounds: Python retires the series and restarts it at 0, below the state's sent."""
        state = copy.deepcopy(self.state)
        key = next(k for k, e in state["series"].items() if e["t"] == "histogram" and e["sent"][-1] > 0)
        b = state["series"][key]["b"]
        b[0], b[1] = b[1], b[0]  # swapped bounds (M2)
        r, out = self.drill(self.inputs(state))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("below the state's sent", r.stdout)

    def test_catchup_over_the_limit_exits_1(self):
        r, out = self.drill(self.inputs(), "--catchup-limit", "-1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(json.loads(out.read_text())["steps"]["0 catch-up within limit"]["ok"])

    def test_refuses_live_inputs_and_a_dirty_scratch(self):
        d = self.inputs()
        live = Path(os.path.expanduser("~")) / ".local/state/agent-events"
        self.n += 1
        r = self.run_py("rollback_drill.py", "--state", live / "export_state.json", "--status", d / "status.json", "--py-db", self.py_db,
                        "--sessions-dir", self.corpus_dir, "--scratch", self.tmp / "s-live", "--out", self.tmp / "r.json", *DRILL_ARGS)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("live directory", r.stderr)
        (self.tmp / "dirty").mkdir()
        (self.tmp / "dirty/x").write_text("x")
        r = self.run_py("rollback_drill.py", "--state", d / "export_state.json", "--status", d / "status.json", "--py-db", self.py_db,
                        "--sessions-dir", self.corpus_dir, "--scratch", self.tmp / "dirty", "--out", self.tmp / "r.json", *DRILL_ARGS)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not empty", r.stderr)

    def test_the_live_python_database_is_not_written(self):
        before = hashlib.sha256(self.py_db.read_bytes()).hexdigest()
        r, _ = self.drill(self.inputs())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(hashlib.sha256(self.py_db.read_bytes()).hexdigest(), before)

    def test_exits_2_when_a_frozen_file_changed(self):
        d = self.inputs()
        r = self.run_py("rollback_drill.py", "--state", d / "export_state.json", "--status", d / "status.json", "--py-db", self.py_db,
                        "--sessions-dir", self.corpus_dir, "--scratch", self.tmp / "s-t", "--out", self.tmp / "r.json", *DRILL_ARGS,
                        directory=self.tamper_copy("agent_events_metrics.py"))
        self.assertEqual(r.returncode, 2, r.stderr)


class Freeze(Scratch):
    def freeze(self, state_dir, *extra, out=None, corpus=None):
        out = out or self.tmp / "frozen"
        env = self.env()
        return subprocess.run(["sh", str(TOOLS / "freeze.sh"), "--out", str(out), "--sessions-src", str(corpus or self.corpus("builder")),
                               "--state-src", str(state_dir), "--roots", str(self.tmp / "roots"), *extra],
                              capture_output=True, text=True, env=env, timeout=300), out

    def state_dir(self, fp=None):
        d = self.tmp / "livecopy"
        d.mkdir(exist_ok=True)
        r = self.run_py("parity_dump.py", "fp", "--roots", self.tmp / "roots", "--machine", "personal")
        self.assertEqual(r.returncode, 0, r.stderr)
        real = json.loads(r.stdout)["fp"]
        (d / "export_state.json").write_text(json.dumps({"series": {}, "fp": fp or real, "seeded": True}))
        (d / "status.json").write_text('{"epoch_ns": 1790000000123456789}')
        return d, real

    def test_freeze_writes_the_inputs_and_leaves_the_source_alone(self):
        d, fp = self.state_dir()
        src_before = self.tree_hash(self.tmp / "livecopy")
        r, out = self.freeze(d)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        rec = json.loads((out / "FREEZE.json").read_text())
        self.assertEqual(rec["fp"], fp)
        self.assertEqual(rec["reference_files"], dict(reversed(l.split()) for l in (TOOLS / "reference.sha256").read_text().splitlines()))
        self.assertEqual(rec["approved_projects"], ["chezmoi", "loop-engine"])
        for want in ("sessions", "strata.txt", "state/personal/export_state.json", "state/personal/status.json",
                     "roots/chezmoi/.git", "roots/loop-engine/.git", "versions.txt", "approved.txt"):
            self.assertTrue((out / want).exists(), want)
        self.assertEqual(self.tree_hash(self.tmp / "livecopy"), src_before)
        listed = (out / "strata.txt").read_text().split()
        self.assertTrue(all((out / "sessions" / p).is_file() for p in listed))
        self.assertTrue(any("/run-0/session.jsonl" in p for p in listed))
        self.assertTrue(any(p.endswith("-fork.jsonl") for p in listed))
        self.assertIn("forks=1", rec["strata_counts"])
        self.assertIn("python:", (out / "versions.txt").read_text())

    def test_big_line_codemode_and_untimed_strata(self):
        d, _ = self.state_dir()
        corpus = self.corpus("builder")
        proj = corpus / "--big--"
        proj.mkdir()
        (proj / "big.jsonl").write_text(json.dumps({"type": "x", "pad": "a" * 2_100_000}) + "\n")
        (proj / "many-short-lines.jsonl").write_text((json.dumps({"type": "x", "pad": "a" * 100}) + "\n") * 25000)  # over 2 MB, no long line
        (proj / "code.jsonl").write_text('{"name":"codemode"}\n' * 3)
        r, out = self.freeze(d, corpus=corpus)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads((out / "FREEZE.json").read_text())
        counts = dict(kv.split("=") for kv in rec["strata_counts"].split())
        self.assertEqual(counts["bigline"], "1")
        self.assertEqual(counts["codemode"], "1")
        listed = (out / "strata.txt").read_text().split()
        self.assertIn("--big--/big.jsonl", listed)
        self.assertGreaterEqual(int(counts["untimed"]), 2)

    def test_a_failed_freeze_leaves_no_temp_files(self):
        d, _ = self.state_dir(fp="000000000000")
        r, out = self.freeze(d)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(out.exists() and any(out.iterdir()))

    def test_a_fingerprint_that_is_not_the_recorded_one_says_re_freeze(self):
        d, _ = self.state_dir(fp="000000000000")
        r, out = self.freeze(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("re-freeze", r.stderr)
        self.assertFalse((out / "sessions").exists())

    def test_refuses_a_non_empty_out(self):
        d, _ = self.state_dir()
        out = self.tmp / "frozen"
        out.mkdir()
        (out / "x").write_text("x")
        r, _ = self.freeze(d, out=out)
        self.assertEqual(r.returncode, 64)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["x"])


class Deployment(Scratch):
    """Which of the new files chezmoi deploys, per profile (real chezmoi, scratch destination)."""

    SHADOW = {".local/share/agent-events/shadow_py_run.py", ".local/share/agent-events/cache_ref.py",
              ".local/share/agent-events/reference.sha256"}
    SOURCE_ONLY = {".local/share/agent-events/parity_dump.py", ".local/share/agent-events/rollback_drill.py",
                   ".local/share/agent-events/freeze.sh", ".local/share/agent-events/reference_common.py"}

    def managed(self, profile, extra=""):
        if not shutil.which("chezmoi"):
            self.skipTest("no chezmoi")
        cfg = self.tmp / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n%s" % (profile, extra))
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "--destination",
                            str(self.home), "managed"], capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)))
        return r

    def test_personal_deploys_the_three_and_work_none(self):
        personal = set(self.managed("personal").stdout.split())
        work = set(self.managed("axon-work-computer").stdout.split())
        self.assertTrue(self.SHADOW <= personal)
        self.assertFalse(self.SHADOW & work)
        self.assertFalse((self.SOURCE_ONLY | {".local/share/agent-events/test_agent_events.py"}) & (personal | work))
        for name in FROZEN:
            self.assertIn(".local/share/agent-events/" + name, personal & work)

    def test_the_setting_switches_both_ways_and_a_bad_value_fails_the_render(self):
        on = set(self.managed("axon-work-computer", "  agentTracesShadow: {enabled: true}\n").stdout.split())
        off = set(self.managed("personal", "  agentTracesShadow: {enabled: false}\n").stdout.split())
        self.assertTrue(self.SHADOW <= on)
        self.assertFalse(self.SHADOW & off)
        for bad in ("  agentTracesShadow: {enabled: maybe}\n", "  agentTracesShadow: {version: 1}\n"):
            with self.subTest(bad=bad):
                self.assertNotEqual(self.managed("personal", bad).returncode, 0)

    def test_deployed_files_are_identical_to_the_source(self):
        """The reference hashes are of the deployed bytes: chezmoi must not template or change any of them."""
        if not shutil.which("chezmoi"):
            self.skipTest("no chezmoi")
        cfg = self.tmp / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: personal\n")
        dest = self.tmp / "dest"
        dest.mkdir()
        target = dest / ".local/share/agent-events"
        target.parent.mkdir(parents=True)
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "--destination", str(dest),
                            "--persistent-state", str(self.tmp / "st.boltdb"), "--no-tty", "apply", str(target)],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in sorted(FROZEN) + ["shadow_py_run.py", "cache_ref.py", "reference.sha256"]:
            self.assertEqual((target / name).read_bytes(), (TOOLS / name).read_bytes(), name)
        # the deployed set verifies itself and runs the control arm's refusal check from where it is deployed
        r = subprocess.run([sys.executable, str(target / "shadow_py_run.py"), "--help"], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
