"""The call log of the gh wrapper (scripts/gh-wrapper-lib/gh_log.py), driven the way a caller drives it: the installed wrapper runs a fake real gh and writes
its log under a throwaway HOME. The pure tests check the record's rules alone. The data is invented (test_gh_wrapper's guarded repository and markers).
"""
import contextlib
import json
import os
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

from test_gh_wrapper import LIB, ROOT, WrapperBase

sys.path.insert(0, str(LIB))
import gh_layers as L      # noqa: E402
import gh_log as G         # noqa: E402

DOCS = (ROOT / "docs/gh-wrapper.md").read_text()
TOP_CALLERS = 'map(select(.event=="exit")) | group_by(.class,.who) | map({class:.[0].class,who:.[0].who,n:length,secs:(map(.dur_s)|add)}) | sort_by(-.n) | .[:10][] | @json'
Class = namedtuple("Class", "klass bucket write")


def call(args, klass, bucket="core", write=False):
    return L.Call(args, Class(klass, bucket, write))


class Pure(unittest.TestCase):
    def test_a_calling_process_is_its_program_and_an_existing_file_given_first_and_nothing_else(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        run_sh, ci = os.path.join(tmp, "run.sh"), os.path.join(tmp, "ci-main-status")
        for path in (run_sh, ci):
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
                ([], None)):
            with self.subTest(argv):
                self.assertEqual(G.caller(argv), want)

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
            f.write("#!%s\nimport time\ntime.sleep(60)\n" % sys.executable)
        os.chmod(script, 0o755)
        child = subprocess.Popen([script, "--token=MARKER"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        ppid, argv = G.proc(child.pid)                  # the child ran the script: argv is the interpreter, the script, the token
        self.assertEqual(ppid, os.getpid())
        self.assertEqual(G.caller(argv), os.path.basename(sys.executable) + " ci-main-status")

    def test_on_macos_the_parent_comes_from_ps_and_only_its_program_is_kept(self):
        done = subprocess.CompletedProcess([], 0, stdout="  4242 zsh -c gh api -f body=MARKER\n", stderr="")
        with mock.patch.object(G.sys, "platform", "darwin"), mock.patch.object(G.subprocess, "run", return_value=done):
            ppid, argv = G.proc(7)
        self.assertEqual((ppid, G.caller(argv)), (4242, "zsh"))


def lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


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
