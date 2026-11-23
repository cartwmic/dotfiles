"""Tests for dot_local/bin/executable_kgate-split.

The pure parts (the deal, the limits, the settings, the verdict of a run directory) are called directly. The tool also runs as a real process
against a fake `kgate` first on PATH: the fake runs the pod command on this machine, with $KGATE_OUT as /out, writes a job record the way kgate
does, and can be told to never start a pod or to hang. The pod worker is the real one: it is fetched from the real queue server over HTTP.
Ports: every run uses an ephemeral port (KGATE_SPLIT_PORTS=0), never the range the host firewall opens.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_kgate-split"


def load():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("kgate_split_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader("kgate_split_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


K = load()

FAKE_KGATE = '''#!/usr/bin/env python3
"""A kgate that runs the pod command here. FAKE_KGATE_NOSTART=<pod> makes that pod's first job end 75; FAKE_KGATE_HANG=1 makes jobs wait for TERM."""
import json, os, signal, subprocess, sys, time
args = sys.argv[1:]
cmd = args[args.index("--") + 1:]
state = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "kgate")
os.makedirs(state, exist_ok=True)
kid = "kgate-%d-%d" % (time.time(), os.getpid())
print("kgate: pod %s on fake" % kid, flush=True)
pod = next((w.split("=", 1)[1] for w in cmd if w.startswith("KGATE_SPLIT_POD=")), "?")
def record(code, ran=True):
    with open(os.path.join(state, "log.jsonl"), "a") as f:
        f.write(json.dumps({"id": kid, "exit": code, "ran": ran, "node": "fake-node"}) + "\\n")
def on_term(*_):
    open(os.path.join(state, "termed-" + kid), "w").write("x")
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except Exception:
        pass
    record(143)
    sys.exit(143)
signal.signal(signal.SIGTERM, on_term)
marker = os.path.join(state, "attempt-" + pod)
if os.environ.get("FAKE_KGATE_NOSTART") == pod and not os.path.exists(marker):
    open(marker, "w").write("1")
    record(75, ran=False)
    sys.exit(75)
if os.environ.get("FAKE_KGATE_HANG"):
    child = subprocess.Popen(["sleep", "300"], start_new_session=True)
    open(os.path.join(state, "hanging-" + kid), "w").write("x")   # the TERM handler is set and the job is up: safe to stop
    child.wait()
    sys.exit(0)
out = os.path.join(state, kid + ".out")
os.makedirs(out)
child = subprocess.Popen(cmd, env=dict(os.environ, KGATE_OUT=out), start_new_session=True)
code = child.wait()
record(code)
sys.exit(code)
'''


def write_repo(tmp, tests, split_extra=""):
    repo = Path(tmp) / "repo"
    (repo / "tests").mkdir(parents=True)
    for name, body in tests.items():
        (repo / "tests" / name).write_text(body)
    (repo / "kgate.toml").write_text('image = "x"\n[split]\nlist = "ls tests"\nrun = "sh tests/$(cat {items})"\n' + split_extra)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "kgate").write_text(FAKE_KGATE)
        (self.bin / "kgate").chmod(0o755)
        self.state = self.tmp / "state"
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", XDG_STATE_HOME=str(self.state), KGATE_SPLIT_HOST="127.0.0.1",
                        KGATE_SPLIT_PORTS="0", PYTHONDONTWRITEBYTECODE="1")
        K.STAGGER_S = 0

    def run_split(self, repo, *args, env=None, timeout=60):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, capture_output=True, text=True, env=dict(self.env, **(env or {})), timeout=timeout)

    def rundir(self):
        dirs = sorted((self.state / "kgate").glob("split-*-*"))
        self.assertEqual(len(dirs), 1)
        return dirs[0]


class Deal(unittest.TestCase):
    IDS = [f"t{i:02d}" for i in range(20)]
    DUR = {f"t{i:02d}": float(20 - i) for i in range(20)}

    def test_longer_than_the_median_come_first(self):
        order, est, median = K.deal(self.IDS, self.DUR, 1)
        self.assertEqual(median, 10.5)
        self.assertEqual(set(order[:10]), {f"t{i:02d}" for i in range(10)})

    def test_a_test_far_longer_than_the_rest_is_always_first(self):
        dur = dict(self.DUR, t00=400.0)
        for seed in range(100):
            with self.subTest(seed=seed):
                self.assertEqual(K.deal(self.IDS, dur, seed)[0][0], "t00")

    def test_the_seed_changes_the_order_even_when_every_id_has_a_record(self):
        a = K.deal(self.IDS, self.DUR, 1)[0]
        b = K.deal(self.IDS, self.DUR, 2)[0]
        self.assertNotEqual(a, b)
        self.assertEqual(set(a[:10]), set(b[:10]))
        self.assertEqual(sorted(a), sorted(self.IDS))

    def test_the_seed_also_moves_the_long_half_with_distinct_recorded_times(self):
        # the long half has no tied times here (20..11 s), so the order would be the same for every seed if the seed only broke ties
        orders = {tuple(K.deal(self.IDS, self.DUR, seed)[0][:10]) for seed in range(30)}
        self.assertGreater(len(orders), 15)

    def test_the_same_seed_gives_the_same_order_whatever_order_the_list_came_in(self):
        self.assertEqual(K.deal(self.IDS, self.DUR, 7)[0], K.deal(list(reversed(self.IDS)), self.DUR, 7)[0])

    def test_with_one_id_or_no_records_it_still_deals_every_id_once(self):
        self.assertEqual(K.deal(["only"], {}, 3)[0], ["only"])
        order, est, median = K.deal(self.IDS, {}, 3)
        self.assertEqual(sorted(order), self.IDS)
        self.assertEqual(set(est.values()), {median})

    def test_an_unknown_id_counts_as_the_median_and_is_shuffled_with_the_short_ones(self):
        order, est, median = K.deal(self.IDS + ["new"], self.DUR, 1)
        self.assertEqual(est["new"], median)
        self.assertGreater(order.index("new"), 9)


class Limits(unittest.TestCase):
    def test_ten_times_the_record_with_a_floor_of_120_s(self):
        self.assertEqual(K.stuck_limit(30, 5), (300, 30))
        self.assertEqual(K.stuck_limit(4, 5), (120, 4))

    def test_an_unknown_id_is_judged_against_the_median(self):
        self.assertEqual(K.stuck_limit(None, 20), (200, 20))

    def test_the_kill_message_names_the_time_and_the_record(self):
        self.assertEqual(K.killed_message(121.4, 4.0, 5), "killed after 121 s; its recorded time is 4 s")
        self.assertIn("no recorded time", K.killed_message(200, None, 20))


class Settings(unittest.TestCase):
    def test_defaults_and_overrides(self):
        s = K.parse_settings('[split]\nlist = "a"\nrun = "b {items}"\n')
        self.assertEqual((s["pods"], s["lanes"], s["setup"], s["claim_seconds"]), (1, 1, "", 0))
        s = K.parse_settings('[split]\nlist = "a"\nrun = "b {items}"\npods = 6\nlanes = 4\n', pods=2)
        self.assertEqual((s["pods"], s["lanes"]), (2, 4))

    def test_files_is_a_table_of_names_and_paths(self):
        s = K.parse_settings('[split]\nlist = "a"\nrun = "b {items}"\n[split.files]\ncore = "~/x/core"\n')
        self.assertEqual(s["files"], {"core": "~/x/core"})
        self.assertEqual(K.parse_settings('[split]\nlist = "a"\nrun = "b {items}"\n')["files"], {})
        for text, why in (('[split]\nlist = "a"\nrun = "b {items}"\nfiles = "x"\n', "table"), ('[split]\nlist = "a"\nrun = "b {items}"\n[split.files]\n"a/b" = "x"\n', "name"),
                          ('[split]\nlist = "a"\nrun = "b {items}"\n[split.files]\n"-x" = "x"\n', "name"), ('[split]\nlist = "a"\nrun = "b {items}"\n[split.files]\ncore = 3\n', "path")):
            with self.subTest(text):
                with self.assertRaises(ValueError) as e:
                    K.parse_settings(text)
                self.assertIn(why, str(e.exception))

    def test_bad_settings_are_refused_with_the_reason(self):
        for text, why in (("", "no [split]"), ('[split]\nlist = "a"\n', "run"), ('[split]\nlist = "a"\nrun = "b"\n', "{items}"),
                          ('[split]\nlist = "a"\nrun = "b {items}"\npods = 0\n', "pods"), ('[split]\nlist = "a"\nrun = "b {items}"\nwhat = 1\n', "unknown")):
            with self.subTest(why):
                with self.assertRaises(ValueError) as e:
                    K.parse_settings(text)
                self.assertIn(why, str(e.exception))


class QueueTest(unittest.TestCase):
    def queue(self, cap=0, pods=2):
        import io
        return K.Queue(["a", "b", "c"], {i: (120, None) for i in "abc"}, pods, cap, io.StringIO())

    def test_every_id_is_handed_out_once_in_order_and_then_none(self):
        q = self.queue()
        self.assertEqual([q.claim(1)["item"] for _ in range(4)], ["a", "b", "c", None])
        self.assertTrue(q.drained())

    def test_a_capped_pod_gets_nothing_after_its_cap_but_the_leftover_pod_does(self):
        q = self.queue(cap=0.05)
        self.assertEqual(q.claim(1)["item"], "a")
        time.sleep(0.1)
        self.assertIsNone(q.claim(1)["item"])
        self.assertEqual(q.claim(3)["item"], "b")   # pod 3 is the leftover pod of a 2-pod run: no cap


class Verdict(Base):
    """The verdict is read from a run directory alone, so these build one by hand."""

    def make(self, ids=("a", "b", "c"), pods=((1, 0), (2, 0)), handed=None, results=None):
        d = self.tmp / "run"
        shutil.rmtree(d, True)
        (d / "pods").mkdir(parents=True)
        order = list(ids)
        (d / "plan.json").write_text(json.dumps({"ids": sorted(ids), "order": order, "est": {i: 1 for i in ids}, "median": 1, "pods": 2, "lanes": 1,
                                                 "seed": 5, "repo": "r", "head": "h" * 40, "recorded": 0, "queue": "q", "rerun": ["kgate-split", "run", "--seed", "5"]}))
        (d / "pods.json").write_text(json.dumps({"elapsed_s": 9, "pods": [{"pod": k, "exit": code, "id": f"kgate-{k}"} for k, code in pods]}))
        handed = handed if handed is not None else {"a": 1, "b": 2, "c": 1}
        (d / "queue.jsonl").write_text("".join(json.dumps({"item": i, "pod": k, "at": "t"}) + "\n" for i, k in handed.items()))
        results = results if results is not None else {1: [("a", 0), ("c", 0)], 2: [("b", 0)]}
        for k, rs in results.items():
            (d / "pods" / str(k)).mkdir(exist_ok=True)
            (d / "pods" / str(k) / "results.jsonl").write_text("".join(json.dumps({"id": i, "pod": k, "exit": code, "seconds": 1, "start": 1}) + "\n" for i, code in rs))
        return d

    def test_every_id_once_and_every_pod_ended_is_a_pass(self):
        got = K.check(self.make())
        self.assertEqual((got["exit"], got["verdict"]), (0, "PASS"))

    def test_an_id_removed_from_the_outputs_is_incomplete_and_exit_1(self):
        got = K.check(self.make(results={1: [("a", 0)], 2: [("b", 0)]}))
        self.assertEqual((got["exit"], got["verdict"]), (1, "INCOMPLETE"))
        self.assertIn("INCOMPLETE: lost: c handed out to pod 1, no result", got["lines"])

    def test_an_id_reported_twice_is_incomplete(self):
        got = K.check(self.make(results={1: [("a", 0), ("c", 0)], 2: [("b", 0), ("a", 0)]}))
        self.assertEqual(got["exit"], 1)
        self.assertTrue(any(l.startswith("INCOMPLETE: dup: a reported 2 times") for l in got["lines"]))

    def test_an_id_that_is_not_in_the_list_is_incomplete(self):
        got = K.check(self.make(results={1: [("a", 0), ("c", 0), ("zzz", 0)], 2: [("b", 0)]}))
        self.assertEqual(got["exit"], 1)
        self.assertTrue(any("extra: zzz" in l for l in got["lines"]))

    def test_ids_lost_with_a_pod_that_did_not_run_to_its_end_are_not_run_not_failed(self):
        got = K.check(self.make(pods=((1, 69), (2, 0)), results={1: [], 2: [("b", 0)]}))
        self.assertEqual((got["exit"], got["verdict"]), (69, "NOT RUN"))

    def test_a_failure_wins_over_a_pod_that_did_not_run(self):
        got = K.check(self.make(pods=((1, 69), (2, 1)), results={1: [], 2: [("b", 1)]}))
        self.assertEqual(got["exit"], 1)

    def test_a_pod_that_never_started_and_took_nothing_is_dropped_when_the_others_ran_everything(self):
        got = K.check(self.make(pods=((1, 0), (2, 75)), handed={"a": 1, "b": 1, "c": 1}, results={1: [("a", 0), ("b", 0), ("c", 0)], 2: []}))
        self.assertEqual(got["exit"], 0)
        self.assertTrue(any(l.startswith("note: pod 2 did not run") for l in got["lines"]))

    def test_ids_nobody_took_because_a_pod_did_not_run_are_not_run(self):
        got = K.check(self.make(pods=((1, 0), (2, 69)), handed={"a": 1}, results={1: [("a", 0)], 2: []}))
        self.assertEqual(got["exit"], 69)

    def test_ids_nobody_took_though_every_pod_ended_are_incomplete(self):
        got = K.check(self.make(handed={"a": 1}, results={1: [("a", 0)], 2: []}))
        self.assertEqual(got["exit"], 1)

    def test_the_check_command_reads_only_the_directory(self):
        d = self.make(results={1: [("a", 0)], 2: [("b", 0)]})
        done = self.run_split(self.tmp, "check", str(d))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("VERDICT: INCOMPLETE", done.stdout)
        self.assertIn("rerun with: kgate-split run --seed 5", done.stdout)


class PodWorker(Base):
    def test_a_test_over_its_limit_is_killed_with_the_message_and_its_group_ends(self):
        out = self.tmp / "out"
        (out / "logs").mkdir(parents=True)
        marker = self.tmp / "survivor"
        claimed = {"item": "stuck", "limit_s": 1, "recorded_s": 0.5}
        t0 = time.time()
        r = K.run_one(claimed, 1, 0, 1, out, self.tmp, f"sh -c 'sleep 1.5; touch {marker}' & sleep 60", 1.0)
        self.assertLess(time.time() - t0, 20)
        self.assertEqual((r["exit"], r["killed"]), (124, True))
        self.assertRegex(r["message"], r"^killed after \d+ s; its recorded time is 0\.5 s$")
        time.sleep(2)
        self.assertFalse(marker.exists(), "a child of the killed test survived")

    def test_the_command_gets_the_id_in_the_file_and_its_pod_and_lane_in_the_environment(self):
        out = self.tmp / "out"
        (out / "logs").mkdir(parents=True)
        r = K.run_one({"item": "my id", "limit_s": 30, "recorded_s": None}, 3, 2, 1, out, self.tmp, 'echo "$(cat {items}) $KGATE_SPLIT_ID $KGATE_SPLIT_POD $KGATE_SPLIT_LANE"', 1.0)
        self.assertEqual(r["exit"], 0)
        self.assertEqual((out / r["log"]).read_text().strip(), "my id my id 3 2")


class Runs(Base):
    def test_a_green_run_over_two_pods_and_two_lanes_reports_every_id_once(self):
        repo = write_repo(self.tmp, {f"t{i}.sh": "sleep 0.2\n" for i in range(8)}, "pods = 2\nlanes = 2\n")
        done = self.run_split(repo, "run", "--seed", "11")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("VERDICT: PASS: 8 PASS, 0 FAIL of 8", done.stdout)
        self.assertIn("seed: 11", done.stdout)
        self.assertIn("rerun with: kgate-split run --seed 11", done.stdout)
        got = K.check(self.rundir())
        self.assertEqual(sorted(r["id"] for r in got["results"]), sorted(f"t{i}.sh" for i in range(8)))
        self.assertEqual(len(got["pods"]), 2)

    def test_a_failing_test_is_reported_with_its_output_and_exit_1(self):
        repo = write_repo(self.tmp, {"ok.sh": "exit 0\n", "bad.sh": "echo why-it-broke\nexit 3\n"})
        done = self.run_split(repo, "run")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("FAIL bad.sh", done.stdout)
        self.assertIn("why-it-broke", done.stdout)
        self.assertIn("VERDICT: FAILED", done.stdout)

    def test_the_same_seed_hands_the_tests_out_in_the_same_order_and_another_seed_does_not(self):
        orders = {}
        for name, seed in (("a", "5"), ("b", "5"), ("c", "6")):
            repo = write_repo(self.tmp / name, {f"t{i:02d}.sh": "exit 0\n" for i in range(12)})
            shutil.rmtree(self.state, True)
            self.assertEqual(self.run_split(repo, "run", "--seed", seed).returncode, 0)
            orders[name] = [h["item"] for h in K.read_jsonl(self.rundir() / "queue.jsonl")]
        self.assertEqual(orders["a"], orders["b"])
        self.assertNotEqual(orders["a"], orders["c"])

    def test_the_rerun_line_keeps_the_pods_and_lanes_it_was_given(self):
        repo = write_repo(self.tmp, {"t.sh": "exit 0\n"})
        done = self.run_split(repo, "run", "--seed", "9", "--pods", "1", "--lanes", "2")
        self.assertIn("rerun with: kgate-split run --seed 9 --pods 1 --lanes 2", done.stdout)

    def test_a_pod_that_never_started_is_started_once_more(self):
        repo = write_repo(self.tmp, {f"t{i}.sh": "exit 0\n" for i in range(4)}, "pods = 2\n")
        done = self.run_split(repo, "run", env={"FAKE_KGATE_NOSTART": "2"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("never started (kgate exit 75", done.stdout)

    def test_a_failing_setup_means_the_pod_did_not_run_and_the_run_is_not_run_not_failed(self):
        repo = write_repo(self.tmp, {"t.sh": "exit 0\n"}, 'setup = "exit 7"\n')
        done = self.run_split(repo, "run")
        self.assertEqual(done.returncode, 69, done.stdout + done.stderr)
        self.assertIn("setup failed (exit 7)", done.stdout)
        self.assertIn("VERDICT: NOT RUN", done.stdout)

    def test_a_host_file_is_served_to_every_pods_setup_and_tests_by_name(self):
        core = self.tmp / "host-core"
        core.write_bytes(b"core\x00bytes\n")
        repo = write_repo(self.tmp, {"t.sh": 'cmp "$KGATE_SPLIT_FILES/core" "' + str(core) + '" && echo ok > /dev/null\n'},
                          f'pods = 2\nsetup = \'test -s "$KGATE_SPLIT_FILES/core" && cp "$KGATE_SPLIT_FILES/core" "$KGATE_OUT/core-seen"\'\n[split.files]\ncore = "{core}"\n')
        done = self.run_split(repo, "run", "--seed", "3")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        plan = json.loads((self.rundir() / "plan.json").read_text())
        self.assertEqual(list(plan["files"]), ["core"])
        self.assertEqual(len(plan["files"]["core"]), 64)
        for pod in (1,):
            self.assertEqual((self.rundir() / "pods" / str(pod) / "core-seen").read_bytes(), b"core\x00bytes\n")

    def test_a_host_file_that_is_missing_stops_the_run_before_any_pod_starts(self):
        repo = write_repo(self.tmp, {"t.sh": "exit 0\n"}, '[split.files]\ncore = "' + str(self.tmp / "nope") + '"\n')
        done = self.run_split(repo, "run")
        self.assertEqual(done.returncode, 69, done.stdout + done.stderr)
        self.assertIn("files.core: cannot read", done.stderr)
        self.assertIn("No kgate job was started", done.stderr)
        self.assertEqual(list((self.state / "kgate").glob("kgate-*.out")), [])

    def test_a_relative_host_file_is_read_next_to_the_profile(self):
        repo = write_repo(self.tmp, {"t.sh": 'test -s "$KGATE_SPLIT_FILES/core"\n'}, '[split.files]\ncore = "core.bin"\n')
        (repo / "core.bin").write_text("x")
        done = self.run_split(repo, "run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_pod_stops_claiming_after_the_cap_and_a_leftover_pod_runs_the_rest(self):
        repo = write_repo(self.tmp, {f"t{i}.sh": "sleep 0.6\n" for i in range(6)}, "claim_seconds = 1\n")
        done = self.run_split(repo, "run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("leftover pod 2", done.stdout)

    def test_a_removed_report_in_a_saved_run_is_found_by_check(self):
        repo = write_repo(self.tmp, {f"t{i}.sh": "exit 0\n" for i in range(5)})
        self.assertEqual(self.run_split(repo, "run").returncode, 0)
        run = self.rundir()
        results = run / "pods" / "1" / "results.jsonl"
        lines = results.read_text().splitlines()
        results.write_text("\n".join(lines[1:]) + "\n")
        done = self.run_split(repo, "check", str(run))
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("VERDICT: INCOMPLETE", done.stdout)

    def test_a_list_that_prints_an_id_twice_or_nothing_is_refused_before_any_pod(self):
        repo = write_repo(self.tmp, {"t.sh": "exit 0\n"})
        (repo / "kgate.toml").write_text('[split]\nlist = "echo a; echo a"\nrun = "true {items}"\n')
        done = self.run_split(repo, "run")
        self.assertEqual(done.returncode, 64, done.stderr)
        (repo / "kgate.toml").write_text('[split]\nlist = "true"\nrun = "true {items}"\n')
        self.assertEqual(self.run_split(repo, "run").returncode, 64)

    def test_term_stops_every_pod_and_merges_nothing(self):
        repo = write_repo(self.tmp, {"t.sh": "exit 0\n"}, "pods = 2\n")
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "run"], cwd=repo, env=dict(self.env, FAKE_KGATE_HANG="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Stop only once both fake pods are up and hold their TERM handler; a pod still starting up would be killed by the default action, unrecorded.
        deadline = time.time() + 20
        while time.time() < deadline and len(list((self.state / "kgate").glob("hanging-*"))) < 2:
            time.sleep(0.05)
        self.assertEqual(len(list((self.state / "kgate").glob("hanging-*"))), 2, "both pods should be up before TERM")
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 143, out + err)
        self.assertEqual(len(list((self.state / "kgate").glob("termed-*"))), 2)
        self.assertFalse((self.rundir() / "receipt.txt").exists())
        self.assertIn("stopped by SIGTERM", err)


class Durations(Base):
    def test_it_refits_the_file_from_green_runs_with_the_median_per_id(self):
        repo = write_repo(self.tmp, {"slow.sh": "sleep 0.6\n", "fast.sh": "exit 0\n"}, 'durations = "d.json"\n')
        for _ in range(2):
            self.assertEqual(self.run_split(repo, "run").returncode, 0)
            time.sleep(1.1)   # run directories are named by the second
        done = self.run_split(repo, "durations")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        fitted = json.loads((repo / "d.json").read_text())
        self.assertEqual(list(fitted), ["slow.sh", "fast.sh"])
        self.assertGreater(fitted["slow.sh"], 0.5)
        self.assertIn("plan against actual", done.stdout)
        self.assertIn("pod 1/1", done.stdout)


if __name__ == "__main__":
    unittest.main()
