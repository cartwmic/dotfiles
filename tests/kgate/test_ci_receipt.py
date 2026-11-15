"""GitHub's CI run is the receipt (playbook 83fbe006): kgate refuses a suite GitHub CI already ran green on this commit.

The pure decision is called directly. The real script also runs as a process with a fake `gh` and the fake `ssh` from
test_kgate.py first on PATH: nothing reaches GitHub or a cluster, and the fake ssh's call log shows whether kgate got as far as the cluster.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_kgate as TK  # noqa: E402  (renders kgate once, and gives the fake ssh and op)

K = TK.K
TABLE = {"workflow": "ci.yml", "suites": ["tests/heavy-gate", "scripts/ci-linux.sh"]}
SHA = "a" * 40
GREEN = {"status": "completed", "conclusion": "success", "headSha": SHA, "url": "https://github.com/o/r/actions/runs/7", "databaseId": 7, "event": "push"}
SUITE_CMD = "sh -c 'python3 -m unittest discover -s tests/heavy-gate'"

# gh stand-in: logs its cwd and arguments, then prints FAKE_GH_RUNS (HEAD stands for the --commit value), or fails the way FAKE_GH_FAIL says.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
fake = os.environ["FAKE"]
with open(os.path.join(fake, "gh-calls.jsonl"), "a") as f:
    f.write(json.dumps({"cwd": os.getcwd(), "args": sys.argv[1:]}) + "\n")
if os.environ.get("FAKE_GH_FAIL"):
    sys.stderr.write(os.environ["FAKE_GH_FAIL"] + "\nsecond line\n")
    sys.exit(1)
commit = sys.argv[sys.argv.index("--commit") + 1]
print(os.environ.get("FAKE_GH_RUNS", "[]").replace("HEAD", commit))
'''


def run(status="completed", conclusion="success", sha=SHA, event="push"):
    return {"status": status, "conclusion": conclusion, "headSha": sha, "url": "https://github.com/o/r/actions/runs/9", "databaseId": 9, "event": event}


class Decision(unittest.TestCase):
    def test_a_green_run_on_head_with_a_clean_tree_and_a_named_suite_is_the_receipt(self):
        self.assertEqual(K.ci_receipt(True, SUITE_CMD, TABLE, [run("completed", "failure"), GREEN], SHA), GREEN)

    def test_a_manual_dispatch_run_counts(self):
        r = run(event="workflow_dispatch")
        self.assertEqual(K.ci_receipt(True, SUITE_CMD, TABLE, [r], SHA), r)

    def test_every_other_case_runs(self):
        for why, args in (
            ("dirty tree", (False, SUITE_CMD, TABLE, [GREEN], SHA)),
            ("no table", (True, SUITE_CMD, None, [GREEN], SHA)),
            ("cmd names no suite", (True, "sh -c 'echo hi'", TABLE, [GREEN], SHA)),
            ("no runs", (True, SUITE_CMD, TABLE, [], SHA)),
            ("failed", (True, SUITE_CMD, TABLE, [run("completed", "failure")], SHA)),
            ("cancelled", (True, SUITE_CMD, TABLE, [run("completed", "cancelled")], SHA)),
            ("in progress", (True, SUITE_CMD, TABLE, [run("in_progress", None)], SHA)),
            ("pull_request run", (True, SUITE_CMD, TABLE, [run(event="pull_request")], SHA)),
            ("schedule run", (True, SUITE_CMD, TABLE, [run(event="schedule")], SHA)),
            ("another sha", (True, SUITE_CMD, TABLE, [run(sha="b" * 40)], SHA)),
            ("no head", (True, SUITE_CMD, TABLE, [GREEN], None)),
        ):
            with self.subTest(why):
                self.assertIsNone(K.ci_receipt(*args))

    def test_suite_is_matched_in_the_joined_command(self):
        cmd = K.shlex.join(["sh", "-c", "bash scripts/ci-linux.sh"])
        self.assertTrue(K.suite_matches(TABLE, cmd))
        self.assertFalse(K.suite_matches(TABLE, K.shlex.join(["make", "test"])))


class ProfileTable(unittest.TestCase):
    def test_parses_and_is_absent_by_default(self):
        p = K.parse_profile('[github_ci]\nworkflow = "ci.yml"\nsuites = ["a", "b"]\n')
        self.assertEqual(p["github_ci"], {"workflow": "ci.yml", "suites": ["a", "b"]})
        self.assertIsNone(K.parse_profile("")["github_ci"])

    def test_a_malformed_table_is_a_profile_error(self):
        for bad in ('github_ci = "ci.yml"', '[github_ci]\nworkflow = "ci.yml"', '[github_ci]\nsuites = ["a"]',
                    '[github_ci]\nworkflow = "ci.yml"\nsuites = []', '[github_ci]\nworkflow = "ci.yml"\nsuites = "a"',
                    '[github_ci]\nworkflow = "ci.yml"\nsuites = [1]', '[github_ci]\nworkflow = "ci.yml"\nsuites = [""]',
                    '[github_ci]\nworkflow = ""\nsuites = ["a"]', '[github_ci]\nworkflow = 3\nsuites = ["a"]',
                    '[github_ci]\nworkflow = "a b"\nsuites = ["a"]', '[github_ci]\nworkflow = "ci.yml"\nsuites = ["a"]\nextra = 1'):
            with self.subTest(bad):
                with self.assertRaises(K.Unavailable):
                    K.parse_profile(bad)


class Black(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kt-ci-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin, self.fake, self.state, self.home = (self.tmp / n for n in ("bin", "fake", "state", "home"))
        for d in (self.bin, self.fake, self.home):
            d.mkdir()
        for name, text in (("ssh", TK.FAKE_SSH), ("op", TK.FAKE_OP), ("gh", FAKE_GH)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        TK.git(self.repo, "init", "-q")
        self.profile()
        (self.repo / "tracked.txt").write_text("tracked\n")
        TK.git(self.repo, "add", "-A")
        TK.git(self.repo, "commit", "-q", "-m", "init")
        self.head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()

    def profile(self, table='[github_ci]\nworkflow = "ci.yml"\nsuites = ["tests/heavy-gate", "scripts/ci-linux.sh"]\n'):
        (self.repo / "kgate.toml").write_text('image = "%s"\ncpu = 2\nmemory = "1Gi"\n\n%s' % (TK.DIGEST, table))

    def kgate(self, cmd, runs=None, gh_fail=None):
        env = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
               "XDG_CACHE_HOME": str(self.tmp / "cache"), "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", "HOME": str(self.home),
               "OP_SERVICE_ACCOUNT_TOKEN": TK.FAKE_TOKEN, "FAKE_TOKEN": TK.FAKE_TOKEN, "FAKE_GH_RUNS": json.dumps(runs or [])}
        if gh_fail:
            env["FAKE_GH_FAIL"] = gh_fail
        return subprocess.run([sys.executable, str(TK.SCRIPT), "--", "sh", "-c", cmd], cwd=self.repo, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)

    def lines(self, name):
        path = self.fake / name
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    SUITE = "echo ran-the-suite tests/heavy-gate"
    GREEN_RUNS = [{"status": "completed", "conclusion": "success", "headSha": "HEAD", "url": "https://github.com/o/r/actions/runs/7", "databaseId": 7, "event": "push"}]

    def assertRan(self, done):
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-the-suite", done.stdout)
        self.assertTrue(self.lines("calls.jsonl"))

    def test_green_run_on_a_clean_tree_refuses_before_any_ssh_call(self):
        done = self.kgate(self.SUITE, self.GREEN_RUNS)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("GitHub CI already ran this suite green on %s (https://github.com/o/r/actions/runs/7): GitHub's run is the receipt (playbook 83fbe006)" % self.head[:12], done.stdout)
        self.assertIn("exit 69, CMD was not run on this Mac", done.stdout)
        self.assertNotIn("ran-the-suite", done.stdout)
        self.assertEqual(self.lines("calls.jsonl"), [])          # not even the reachability probe
        call = self.lines("gh-calls.jsonl")[0]
        self.assertEqual(Path(call["cwd"]).resolve(), self.repo)
        self.assertEqual(call["args"], ["run", "list", "--workflow", "ci.yml", "--commit", self.head, "--json", "status,conclusion,headSha,url,databaseId,event", "-L", "20"])

    def test_a_modified_tracked_file_runs(self):
        (self.repo / "tracked.txt").write_text("changed\n")
        self.assertRan(self.kgate(self.SUITE, self.GREEN_RUNS))
        self.assertEqual(self.lines("gh-calls.jsonl"), [])      # no need to ask GitHub

    def test_an_untracked_file_runs(self):
        (self.repo / "new.txt").write_text("new\n")
        self.assertRan(self.kgate(self.SUITE, self.GREEN_RUNS))

    def test_an_ignored_file_does_not_make_the_tree_dirty(self):
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        TK.git(self.repo, "add", "-A")
        TK.git(self.repo, "commit", "-q", "-m", "ignore")
        (self.repo / "ignored.txt").write_text("x\n")
        self.head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
        self.assertEqual(self.kgate(self.SUITE, self.GREEN_RUNS).returncode, 69)

    def test_a_green_pull_request_run_at_head_does_not_refuse(self):
        self.assertRan(self.kgate(self.SUITE, [{**self.GREEN_RUNS[0], "event": "pull_request"}]))

    def test_a_failed_run_runs(self):
        self.assertRan(self.kgate(self.SUITE, [{**self.GREEN_RUNS[0], "conclusion": "failure"}]))

    def test_an_in_progress_run_runs(self):
        self.assertRan(self.kgate(self.SUITE, [{**self.GREEN_RUNS[0], "status": "in_progress", "conclusion": None}]))

    def test_a_green_run_on_another_sha_runs(self):
        self.assertRan(self.kgate(self.SUITE, [{**self.GREEN_RUNS[0], "headSha": "b" * 40}]))

    def test_no_run_at_all_runs(self):
        self.assertRan(self.kgate(self.SUITE, []))

    def test_a_cmd_no_suite_names_runs_without_asking_github(self):
        done = self.kgate("echo ran-the-suite", self.GREEN_RUNS)
        self.assertRan(done)
        self.assertEqual(self.lines("gh-calls.jsonl"), [])

    def test_a_profile_without_the_table_runs_without_asking_github(self):
        self.profile(table="")
        TK.git(self.repo, "add", "-A")
        TK.git(self.repo, "commit", "-q", "-m", "no table")
        self.assertRan(self.kgate(self.SUITE, self.GREEN_RUNS))
        self.assertEqual(self.lines("gh-calls.jsonl"), [])

    def test_a_malformed_table_is_refused_as_a_profile_error(self):
        self.profile(table='[github_ci]\nworkflow = "ci.yml"\n')
        done = self.kgate(self.SUITE, self.GREEN_RUNS)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("profile [github_ci] must be a table with exactly workflow and suites", done.stdout)
        self.assertEqual(self.lines("gh-calls.jsonl"), [])

    def test_gh_failing_prints_one_note_and_runs(self):
        done = self.kgate(self.SUITE, self.GREEN_RUNS, gh_fail="gh: To get started with GitHub CLI, please run:  gh auth login")
        self.assertRan(done)
        notes = [l for l in done.stdout.splitlines() if "could not check GitHub" in l]
        self.assertEqual(len(notes), 1, done.stdout)
        self.assertIn("kgate: could not check GitHub's CI run for this commit (gh: To get started with GitHub CLI, please run:  gh auth login)", notes[0])
        self.assertNotIn("second line", done.stdout)

    def test_gh_missing_prints_a_note_and_runs(self):
        (self.bin / "gh").unlink()
        sysbin = self.tmp / "sysbin"                 # a PATH with the tools the job needs but no gh
        sysbin.mkdir()
        for tool in ("git", "sh", "python3", "env", "tar", "cat", "echo", "mktemp", "rm", "mkdir", "sleep", "date", "ps"):
            found = shutil.which(tool)
            if found:
                (sysbin / tool).symlink_to(found)
        env_path = "%s:%s" % (self.bin, sysbin)
        env = {**os.environ, "PATH": env_path, "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state), "XDG_CACHE_HOME": str(self.tmp / "cache"),
               "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", "HOME": str(self.home), "OP_SERVICE_ACCOUNT_TOKEN": TK.FAKE_TOKEN, "FAKE_TOKEN": TK.FAKE_TOKEN}
        done = subprocess.run([sys.executable, str(TK.SCRIPT), "--", "sh", "-c", self.SUITE], cwd=self.repo, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        self.assertIn("could not check GitHub's CI run for this commit (gh is not installed)", done.stdout)
        self.assertNotIn("GitHub's run is the receipt", done.stdout)


if __name__ == "__main__":
    unittest.main()
