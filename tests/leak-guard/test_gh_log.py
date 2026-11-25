"""The call log of the gh wrapper (scripts/gh-wrapper-lib/gh_log.py), driven the way a caller drives it: the installed wrapper runs a fake real gh and writes
its log under a throwaway HOME. The pure tests check the record's rules alone. The data is invented (test_gh_wrapper's guarded repository and markers).
"""
import ast
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

from test_gh_wrapper import LIB, ROOT, WrapperBase, spawn_ready

sys.path.insert(0, str(LIB))
import gh_layers as L      # noqa: E402
import gh_log as G         # noqa: E402

DOCS = (ROOT / "docs/gh-wrapper.md").read_text()
TOP_CALLERS = 'map(select(.event=="exit")) | group_by(.class,.who) | map({class:.[0].class,who:.[0].who,n:length,secs:(map(.dur_s)|add)}) | sort_by(-.n) | .[:10][] | @json'
Class = namedtuple("Class", "klass bucket write")


def call(args, klass, bucket="core", write=False):
    return L.Call(args, Class(klass, bucket, write))


READS = re.compile(r"\bG\.(?:proc|named|proc_cwd)\((\w+)\.pid\)")


def unready_reads(source):
    """The functions in `source` that read the process table for a process they started and did not get from spawn_ready()."""
    bad = []
    for fn in ast.walk(ast.parse(source)):
        if isinstance(fn, ast.FunctionDef):
            text = ast.get_source_segment(source, fn)
            bad += [fn.name for m in READS.finditer(text) if not re.search(r"\b%s = spawn_ready\(" % m.group(1), text)]
    return bad


OLD_SHAPE = """
def test_a_real_extensionless_script_parent():
    child = subprocess.Popen([script, "--token=MARKER"], stdin=subprocess.DEVNULL)
    ppid, argv = G.proc(child.pid)
"""


class Pure(unittest.TestCase):
    def test_a_calling_process_is_its_program_and_an_existing_file_given_first_and_nothing_else(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        run_sh, ci = os.path.join(tmp, "run.sh"), os.path.join(tmp, "ci-main-status")
        for path in (run_sh, ci, os.path.join(tmp, "-x")):      # "-x" is a file, and still an option
            open(path, "w").close()
        for argv, want in (
                (["zsh", "-c", "gh api -f body=MARKER repos/a/b/issues; true"], "zsh"),
                (["sh", run_sh, "--token=abc"], "sh run.sh"),
                (["node", "--enable-source-maps", "/x/index.js", "--token=abc"], "node"),
                (["python3", ci, "--token=abc"], "python3 ci-main-status"),      # no extension, still a script
                (["python3", os.path.join(tmp, "merge-pr.py")], "python3"),      # not an existing file
                (["python3", tmp], "python3"),                                   # a directory
                (["bash", "./deploy.sh x y"], "bash"),
                (["bash", "--rcfile", "x.sh"], "bash"),
                (["bash", "-x"], "bash"),                                        # an option, though a file of that name exists
                (["python3", "ci-main-status"], "python3 ci-main-status"),       # relative: looked up in the caller's directory
                ([], None)):
            with self.subTest(argv):
                self.assertEqual(G.caller(argv, tmp), want)

    def test_the_interval_is_the_number_gh_gets(self):
        self.assertEqual(G.interval_of(["run", "watch", "9", "--interval", "30"]), 30)
        self.assertEqual(G.interval_of(["pr", "checks", "5", "-i", "60"]), 60)
        self.assertEqual(G.interval_of(["run", "watch", "9", "--interval=5"]), 5)
        self.assertEqual(G.interval_of(["run", "watch", "9", "-i", "soon"]), "soon")
        self.assertIsNone(G.interval_of(["run", "watch", "9"]))
        self.assertIsNone(G.interval_of(["run", "watch", "9", "--interval"]))

    def test_a_watch_is_run_watch_or_anything_with_watch(self):
        self.assertTrue(G.is_watch(call(["run", "watch", "9"], "run watch")))
        self.assertTrue(G.is_watch(call(["pr", "checks", "5", "--watch"], "pr checks", "graphql")))
        self.assertFalse(G.is_watch(call(["run", "list"], "run list")))

    def test_the_record_has_no_arguments_bodies_or_tokens(self):
        c = call(["api", "-f", "body=SECRETBODY", "repos/o/r/issues"], "api POST repos/o/r/issues", write=True)
        c.notes.update(urgent="write", budget="unchecked")
        with mock.patch.dict(os.environ, {"GH_TOKEN": "TOKENVALUE", "COORDINATOR_WHO": "who-test"}):
            entry = G.record(c, "exit", "python3", None)
        text = json.dumps(entry)
        self.assertNotIn("SECRETBODY", text)
        self.assertNotIn("TOKENVALUE", text)
        self.assertEqual((entry["class"], entry["urgent"], entry["budget"], entry["who"]), ("api POST repos/o/r/issues", "write", "unchecked", "who-test"))
        self.assertNotIn("interval", entry)                 # only a watch carries one

    def test_on_linux_a_process_reads_its_parent_from_proc(self):
        ppid, argv = G.proc(os.getpid())
        self.assertEqual(ppid, os.getppid())
        self.assertTrue(argv and argv[0])

    def test_a_real_extensionless_script_parent_is_named_by_its_file_name_and_nothing_else(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        script = os.path.join(tmp, "ci-main-status")
        with open(script, "w") as f:
            f.write("#!%s\nimport time\nprint('ready', flush=True)\ntime.sleep(60)\n" % sys.executable)
        os.chmod(script, 0o755)
        child = spawn_ready(self, [script, "--token=MARKER"])
        ppid, name = G.named(child.pid)                 # the child ran the script: argv is the interpreter, the script, the token
        self.assertEqual(ppid, os.getpid())
        self.assertEqual(name, os.path.basename(sys.executable) + " ci-main-status")

    @unittest.skipUnless(sys.platform.startswith("linux"), "the calling process's directory comes from /proc")
    def test_a_relative_script_is_looked_up_in_the_calling_processs_directory_not_the_wrappers(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(tmp, "merge-pr.py"), "w") as f:
            f.write("import time\nprint('ready', flush=True)\ntime.sleep(60)\n")
        child = spawn_ready(self, [sys.executable, "merge-pr.py", "--token=MARKER"], cwd=tmp)
        _, argv = G.proc(child.pid)
        self.assertEqual(G.caller(argv), os.path.basename(sys.executable))           # from here the file is not there
        self.assertEqual(G.named(child.pid)[1], os.path.basename(sys.executable) + " merge-pr.py")

    def test_a_test_reads_the_process_table_for_a_process_it_started_only_after_spawn_ready(self):
        self.assertEqual(unready_reads(OLD_SHAPE), ["test_a_real_extensionless_script_parent"])
        for path in sorted(Path(__file__).parent.glob("test_gh_*.py")):
            with self.subTest(path.name):
                self.assertEqual(unready_reads(path.read_text()), [], "start the process with spawn_ready(): until its exec finishes /proc/<pid>/cmdline reads as empty")

    def test_on_macos_the_parent_comes_from_ps_and_only_its_program_is_kept(self):
        done = subprocess.CompletedProcess([], 0, stdout="  4242 zsh -c gh api -f body=MARKER\n", stderr="")
        with mock.patch.object(G.sys, "platform", "darwin"), mock.patch.object(G.subprocess, "run", return_value=done):
            ppid, argv = G.proc(7)
        self.assertEqual((ppid, G.caller(argv)), (4242, "zsh"))


def lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


class UrgentDocs(unittest.TestCase):
    def test_every_bin_wrapper_that_sets_gh_urgent_is_named_in_who_sets_it(self):
        """docs/gh-wrapper.md, "Who sets GH_URGENT=1", names each command in dot_local/bin that exports GH_URGENT=1 (dotfiles #690 found two left out)."""
        para = DOCS.split("**Who sets `GH_URGENT=1`.**", 1)[1].split("\n\n", 1)[0]
        setters = sorted(f.name.replace("executable_", "", 1) for f in (ROOT / "dot_local/bin").glob("executable_*")
                         if re.search(r"^export GH_URGENT=1\b", f.read_text(errors="replace"), re.M))
        self.assertTrue(setters)
        for name in setters:
            self.assertIn("`%s`" % name, para, "%s exports GH_URGENT=1 but the docs' list does not name it" % name)


class LogFile(WrapperBase):
    """The installed layout with the budget switched on, so the log layer is loaded. The log goes under the throwaway HOME."""

    def setUp(self):
        super().setUp()
        # These tests check the log alone. A real budget layer runs before the log and reads the rate limit first, so a watch killed then
        # would leave no start line, and its notes would change the exit fields. The budget facts have their own test with a fake layer.
        for name in L.LAYERS:
            if name != "gh_log":      # the log layer under test stays
                (self.tmp / "lib" / (name + ".py")).unlink(missing_ok=True)
        (self.home / ".config" / "gh-wrapper").mkdir(parents=True)
        (self.home / ".config" / "gh-wrapper" / "budget").write_text("on\n")
        self.state = self.home / ".local" / "state" / "gh-wrapper"
        self.log = self.state / "calls.jsonl"

    def records(self):
        return lines(self.log)

    def layer(self, name, source):
        (self.tmp / "lib" / (name + ".py")).write_text(source)

    def test_one_exit_line_per_call_with_the_fields_the_design_names(self):
        done = self.gh("pr", "view", "5", cwd=self.other_cwd, env={"COORDINATOR_WHO": "who-test", "FAKE_GH_EXIT": "3"})
        self.assertEqual((done.returncode, done.stdout), (3, "real gh out\n"), done.stderr)
        [r] = self.records()
        self.assertEqual({k: r[k] for k in ("event", "class", "bucket", "action", "rc", "who", "cwd")},
                         {"event": "exit", "class": "pr view", "bucket": "graphql", "action": "pass", "rc": 3, "who": "who-test", "cwd": str(self.other_cwd)})
        self.assertEqual((r["urgent"], r["budget"], r["budget_left"], r["rewrite"]), (None, None, None, None))      # no budget layer installed
        self.assertTrue(r["utc"].endswith("Z") and r["dur_s"] >= 0 and isinstance(r["id"], int))
        self.assertTrue(r["parent"].startswith("python"), r["parent"])
        self.assertNotIn("interval", r)

    def test_who_is_coordinator_who_then_gh_caller_then_null(self):
        for env, want in (({"COORDINATOR_WHO": "w", "GH_CALLER": "g"}, "w"), ({"COORDINATOR_WHO": "", "GH_CALLER": "g"}, "g"),
                          ({"COORDINATOR_WHO": "", "GH_CALLER": ""}, None)):
            with self.subTest(env):
                self.log.unlink(missing_ok=True)
                self.gh("pr", "view", "5", cwd=self.other_cwd, env=env)
                self.assertEqual(self.records()[-1]["who"], want)

    def test_a_shell_parent_contributes_its_program_name_and_never_the_command_text(self):
        """An agent shell runs gh as `sh -c "<whole command>"`. The command's body and the token in the environment must not reach the log."""
        cmd = '%s api -f body=MARKERBODY repos/o/r/issues; true' % (self.wbin / "gh")
        # stdin is closed: the fake gh reads its standard input, and an open one (a terminal, a runner's pipe) would hang the test.
        done = subprocess.run(["sh", "-c", cmd], cwd=str(self.other_cwd), env=self.env({"GH_TOKEN": "MARKERTOKEN"}), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("MARKERBODY", self.log.read_text())
        self.assertNotIn("MARKERTOKEN", self.log.read_text())
        self.assertEqual((self.records()[-1]["class"], self.records()[-1]["parent"]), ("api POST repos/o/r/issues", "sh"))

    def test_a_watch_writes_a_start_line_then_an_exit_line_with_the_same_id(self):
        done = self.gh("run", "watch", "9", "-i", "30", cwd=self.other_cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        start, end = self.records()
        self.assertEqual((start["event"], start["rc"], start["dur_s"], start["class"]), ("start", None, None, "run watch"))
        self.assertEqual((end["event"], end["rc"]), ("exit", 0))
        self.assertEqual(start["id"], end["id"])
        self.assertEqual((start["interval"], end["interval"]), (30, 30))

    def test_pr_checks_with_watch_is_a_watch_too(self):
        self.gh("pr", "checks", "5", "--watch", cwd=self.other_cwd)
        self.assertEqual([(r["event"], r["class"], r["interval"]) for r in self.records()], [("start", "pr checks", None), ("exit", "pr checks", None)])

    def test_a_watch_killed_hard_leaves_its_start_line_and_no_exit_line(self):
        # No pipes: the gh child a hard kill leaves behind would hold them open and the wait would hang on it.
        proc = subprocess.Popen([str(self.wbin / "gh"), "run", "watch", "9"], cwd=str(self.other_cwd), env=self.env({"FAKE_GH_SLEEP": "60"}),
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pidfile = self.fake / "gh.pid"
        deadline = time.time() + 20
        while not pidfile.exists() and time.time() < deadline:
            time.sleep(0.02)
        gh_pid = int(pidfile.read_text())
        try:
            proc.kill()
            proc.wait(timeout=20)
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.kill(gh_pid, signal.SIGKILL)
        self.assertEqual([r["event"] for r in self.records()], ["start"])

    def test_a_refused_call_logs_its_exit_with_the_budget_facts_and_no_start_line(self):
        self.layer("gh_budget", "from gh_layers import Stop\ndef before(call):\n"
                   "    call.notes.update(urgent='no', budget='refused', budget_left=212)\n"
                   "    raise Stop(75, 'gh-wrapper: refused for the test')\n")
        done = self.gh("run", "watch", "9", cwd=self.other_cwd)
        self.assertEqual((done.returncode, done.stderr.strip()), (75, "gh-wrapper: refused for the test"))
        [r] = self.records()
        self.assertEqual((r["event"], r["action"], r["rc"], r["urgent"], r["budget"], r["budget_left"]), ("exit", "refused", 75, "no", "refused", 212))

    def test_the_log_rotates_at_the_limit_and_keeps_one_old_file(self):
        for _ in range(30):
            self.assertEqual(self.gh("pr", "view", "5", cwd=self.other_cwd, env={"GH_WRAPPER_LOG_MAX": "2000"}).returncode, 0)
        old = self.state / "calls.jsonl.1"
        self.assertTrue(old.exists())
        self.assertFalse((self.state / "calls.jsonl.2").exists())
        kept = lines(old) + lines(self.log)
        self.assertTrue(kept and all(r["class"] == "pr view" for r in kept))
        longest = max(len(l) for l in self.log.read_text().splitlines())
        self.assertLess(self.log.stat().st_size, 2000 + longest + 1)

    def test_a_log_that_cannot_be_written_never_changes_the_call(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("a file where the log directory goes\n")
        done = self.gh("run", "watch", "9", cwd=self.other_cwd, env={"FAKE_GH_EXIT": "3"})
        self.assertEqual((done.returncode, done.stdout), (3, "real gh out\n"), done.stderr)
        self.assertIn("gh-wrapper: layer gh_log failed", done.stderr)
        self.assertIn("real gh err", done.stderr)

    def test_with_the_budget_off_nothing_is_logged(self):
        (self.home / ".config" / "gh-wrapper" / "budget").write_text("off\n")
        self.assertEqual(self.gh("pr", "view", "5", cwd=self.other_cwd).returncode, 0)
        self.assertFalse(self.log.exists())

    @unittest.skipUnless(shutil.which("jq"), "jq is needed for the documented command")
    def test_the_documented_top_callers_command_counts_a_watch_once(self):
        self.assertIn(TOP_CALLERS, DOCS)
        self.gh("run", "watch", "9", cwd=self.other_cwd)
        self.gh("pr", "view", "5", cwd=self.other_cwd)
        done = subprocess.run(["jq", "-sr", TOP_CALLERS, str(self.log)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        counts = {row["class"]: row["n"] for row in map(json.loads, done.stdout.splitlines())}
        self.assertEqual(counts, {"run watch": 1, "pr view": 1})


if __name__ == "__main__":
    unittest.main()
