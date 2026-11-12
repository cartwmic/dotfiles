"""ci-main-status against a fake `gh` and real git.

The fake gh answers `gh run list` from a fixture and `gh api` from a real git repo: branches/main is the real
head, commits/SHA is `git rev-list --parents -n 1`, the commit and its parents the commits API returns, and compare
is kept for the older script the mutation checks run against. Each test states one row of the exit-code table in
the script's docstring.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dot_local/bin/executable_ci-main-status"
GH_FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, subprocess, sys
    fixture = json.load(open(os.environ["FAKE_GH_FIXTURE"]))
    args = sys.argv[1:]
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(" ".join(args) + "\\n")
    def fail(msg):
        print(msg, file=sys.stderr); sys.exit(1)
    def git(path, *a):
        return subprocess.run(["git", "-C", path, *a], capture_output=True, text=True, check=True).stdout
    if args[:2] == ["run", "list"]:
        repo = args[args.index("-R") + 1]
        wf = args[args.index("--workflow") + 1]
        if repo in fixture.get("fail", []):
            fail("HTTP 502 from fake api")
        print(json.dumps(fixture["runs"].get(repo + "|" + wf, [])))
    elif args[0] == "api":
        path = args[1]
        repo = path.split("/")[1] + "/" + path.split("/")[2]
        if repo in fixture.get("fail", []):
            fail("HTTP 502 from fake api")
        src = fixture["repos"][repo]
        if path.endswith("/branches/main"):
            print(json.dumps({"commit": {"sha": git(src, "rev-parse", "main").strip()}}))
        elif "/compare/" in path:
            base, head = path.split("/compare/")[1].split("...")
            lines = git(src, "rev-list", "--parents", f"{base}..{head}").split("\\n")
            commits = []
            for line in filter(None, lines):
                sha, *parents = line.split()
                subject = git(src, "log", "-1", "--format=%s", sha).strip()
                commits.append({"sha": sha, "parents": [{"sha": p} for p in parents], "commit": {"message": subject}})
            print(json.dumps({"status": "ahead", "total_commits": len(commits), "commits": commits}))
        elif "/commits/" in path:
            sha = path.split("/commits/")[1]
            parents = git(src, "rev-list", "--parents", "-n", "1", sha).split()[1:]
            subject = git(src, "log", "-1", "--format=%s", sha).strip()
            print(json.dumps({"sha": sha, "parents": [{"sha": p} for p in parents], "commit": {"message": subject}}))
        elif "/actions/runs/" in path:
            run_id, n = path.split("/actions/runs/")[1].split("/attempts/")
            attempt = fixture.get("attempts", {}).get(run_id, {}).get(n)
            if attempt is None:
                fail(f"HTTP 404: no fixture for run {run_id} attempt {n}")
            print(json.dumps(attempt))
        else:
            fail("fake gh: unhandled " + path)
    else:
        fail("fake gh: unhandled " + " ".join(args))
''')
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True, env=GIT_ENV).stdout.strip()


def commit(path, msg):
    git(path, "commit", "--allow-empty", "-q", "-m", msg)
    return git(path, "rev-parse", "HEAD")


def run(run_id, sha, conclusion=None, status="completed", event="push", age=0, attempt=1, started_age=None):
    """One gh run list row. Newer runs have a larger age. A rerun keeps its created time; its started time
    (started_age, default age) is when the latest attempt started."""
    started = age if started_age is None else started_age
    return {"databaseId": run_id, "event": event, "headSha": sha, "status": status,
            "conclusion": conclusion if status == "completed" else "", "attempt": attempt,
            "createdAt": f"2026-11-11T10:{age:02d}:00Z", "startedAt": f"2026-11-11T10:{started:02d}:00Z",
            "url": ""}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.src = t / "src"
        self.src.mkdir()
        git(self.src, "init", "-q", "-b", "main")
        self.c1 = commit(self.src, "c1")
        self.c2 = commit(self.src, "c2 first parent")
        git(self.src, "switch", "-q", "-c", "side", self.c2)
        self.s1 = commit(self.src, "s1 side branch")
        git(self.src, "switch", "-q", "main")
        git(self.src, "merge", "--no-ff", "-q", "-m", "Merge side branch", "side")
        self.m = git(self.src, "rev-parse", "HEAD")
        self.c3 = commit(self.src, "c3 squash")
        self.runs = {}
        self.failing = []
        self.attempts = {}                           # run id -> {attempt number -> attempts API row}
        self.journal = t / "journal.jsonl"           # absent unless a test writes it
        self.lock = t / "lock.d"
        self.log = t / "gh.log"
        bindir = t / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(GH_FAKE)
        (bindir / "gh").chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                    "FAKE_GH_LOG": str(self.log), "FAKE_GH_FIXTURE": str(t / "fixture.json"),
                    "CI_MAIN_STATUS_JOURNAL": str(self.journal), "CI_MAIN_STATUS_LOCK": str(self.lock)}

    def tearDown(self):
        self.tmp.cleanup()

    def write_fixture(self):
        repos = {r: str(self.src) for r in ("cartwmic/dotfiles", "cartwmic/loop-engine", "cartwmic/agent-kit", "cartwmic/coordinator")}
        Path(self.env["FAKE_GH_FIXTURE"]).write_text(json.dumps(
            {"repos": repos, "runs": self.runs, "fail": self.failing, "attempts": self.attempts}))

    def dotfiles_runs(self, runs):
        self.runs = {"cartwmic/dotfiles|ci.yml": runs}
        self.write_fixture()

    def status(self, *args):
        rc, out, err = self.streams(*args)
        return rc, out + err

    def streams(self, *args):
        self.write_fixture()
        r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def walked_commits(self):
        """The commits API calls the script made, as SHAs."""
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return [c.split("/commits/")[1] for c in calls if "/commits/" in c]

    def range_lines(self, out):
        return [line.strip() for line in out.splitlines() if re.match(r"^    [0-9a-f]{7} ", line)]


class GithubStateTable(Fixture):
    def test_green_and_tested_exits_0(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)
        self.assertIn("main tip is tested", out)

    def test_green_with_untested_commits_and_no_run_exits_2_and_counts_first_parent_only(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("2 main commit(s)", out, "M and c3; the side commit s1 is not on main's first-parent line")
        self.assertIn("Start one", out)

    def test_first_attempt_run_going_over_untested_commits_exit_0(self):
        # A new run on c3 with no red before it: the green on c2 stands, and the run is going.
        self.dotfiles_runs([run(2, self.c3, status="queued", age=5), run(1, self.c2, "success", age=1)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("2 main commit(s) not tested yet, a run is going", out)

    def test_rerun_of_a_red_run_going_over_untested_commits_exit_1(self):
        # Same run id, attempt 2 in progress, after attempt 1 failed. It must not read as the older green.
        self.attempts = {"2": {"1": {"status": "completed", "conclusion": "failure"}}}
        self.dotfiles_runs([run(2, self.c3, status="in_progress", age=5, attempt=2), run(1, self.c2, "success", age=1)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 2 attempt 1 failed on " + self.c3[:7] + "  (a rerun is going)", out)
        self.assertIn("last green: " + self.c2[:7], out)
        expected = git(self.src, "log", "--first-parent", "--oneline", f"{self.c2}..{self.c3}").splitlines()
        self.assertEqual(self.range_lines(out), expected)

    def test_rerun_of_a_red_run_with_no_earlier_green_exit_1(self):
        self.attempts = {"2": {"1": {"status": "completed", "conclusion": "failure"}}}
        self.dotfiles_runs([run(2, self.c3, status="in_progress", age=5, attempt=2)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 2 attempt 1 failed on " + self.c3[:7], out)
        self.assertIn("no earlier green run", out)

    def test_rerun_of_a_green_run_is_green_and_names_the_rerun(self):
        self.attempts = {"2": {"1": {"status": "completed", "conclusion": "success"}}}
        self.dotfiles_runs([run(2, self.c3, status="in_progress", age=5, attempt=2), run(1, self.c2, "success", age=1)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  run 2 attempt 1 passed on " + self.c3[:7] + "; main tip is tested", out)

    def test_a_red_rerun_is_not_hidden_by_a_newer_run_at_the_same_tip(self):
        # Run 3 failed at c3, a dispatch (run 4) then passed at c3, and run 3 was rerun. The rerun started last.
        self.attempts = {"3": {"1": {"status": "completed", "conclusion": "failure"}}}
        self.dotfiles_runs([run(4, self.c3, "success", age=4, event="workflow_dispatch"),
                            run(3, self.c3, status="in_progress", age=3, attempt=2, started_age=6),
                            run(1, self.c2, "success", age=1)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 3 attempt 1 failed on " + self.c3[:7] + "  (a rerun is going)", out)

    def test_rerun_reads_the_last_conclusive_attempt_past_a_cancelled_one(self):
        self.attempts = {"2": {"1": {"status": "completed", "conclusion": "failure"},
                               "2": {"status": "completed", "conclusion": "cancelled"}}}
        self.dotfiles_runs([run(2, self.c3, status="in_progress", age=5, attempt=3)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 2 attempt 1 failed on " + self.c3[:7], out)

    def test_red_exits_1_with_first_parent_range_and_ignores_cancelled_and_running(self):
        self.dotfiles_runs([
            run(4, self.c3, status="in_progress", age=4),
            run(3, self.c3, "failure", age=3),
            run(2, self.c3, "cancelled", age=2),
            run(1, self.c2, "success", age=1)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 3 failed on " + self.c3[:7], out)
        self.assertIn("a newer run is going", out)
        self.assertIn("last green: " + self.c2[:7], out)
        expected = git(self.src, "log", "--first-parent", "--oneline", f"{self.c2}..{self.c3}").splitlines()
        self.assertEqual(self.range_lines(out), expected,
                         "the printed range equals git log --first-parent --oneline last_green..red_tip")
        self.assertNotIn(self.s1[:7], out, "a side-branch commit is not in the first-parent range")

    def test_red_without_an_earlier_green_exits_1(self):
        self.dotfiles_runs([run(1, self.c3, "failure")])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("no earlier green run", out)

    def test_no_conclusive_run_exits_2_with_or_without_a_run_going(self):
        self.dotfiles_runs([run(1, self.c3, "cancelled"), run(2, self.c3, "skipped", age=1)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("Start one", out)
        self.dotfiles_runs([run(3, self.c3, status="in_progress", age=2)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("A run is going; wait for it", out)

    def test_unreadable_state_exits_1_never_0(self):
        self.failing = ["cartwmic/dotfiles"]
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("cannot read state", out)

    def test_reviewer_sequence_a_rerun_passes_and_the_newer_commit_fails_is_red(self):
        # Run 1 on c2 failed, run 2 on c3 waited. Run 1 was rerun and passed (its rerun started last), then run 2
        # failed. Commit order decides: c3 is the newest conclusive commit. Its created time is the older one.
        self.dotfiles_runs([run(2, self.c3, "failure", age=1, started_age=1),
                            run(1, self.c2, "success", attempt=2, age=5, started_age=9)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 2 failed on " + self.c3[:7], out)
        self.assertIn("last green: " + self.c2[:7] + " (run 1)", out)
        expected = git(self.src, "log", "--first-parent", "--oneline", f"{self.c2}..{self.c3}").splitlines()
        self.assertEqual(self.range_lines(out), expected)

    def test_reviewer_sequence_with_a_dispatch_in_progress_at_the_newer_commit_is_still_red(self):
        self.dotfiles_runs([run(3, self.c3, status="in_progress", event="workflow_dispatch", age=8),
                            run(2, self.c3, "failure", age=2),
                            run(1, self.c2, "success", attempt=2, age=1, started_age=9)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 2 failed on " + self.c3[:7] + "  (a newer run is going)", out)

    def test_a_rerun_of_an_older_commit_under_a_green_tip_is_green(self):
        self.attempts = {"1": {"1": {"status": "completed", "conclusion": "failure"}}}
        self.dotfiles_runs([run(1, self.c2, status="in_progress", attempt=2, age=1, started_age=9),
                            run(2, self.c3, "success", age=2)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  run 2 passed on " + self.c3[:7] + "; main tip is tested", out)

    def test_a_rerun_that_passed_under_a_green_tip_is_green_with_no_extra_run(self):
        self.dotfiles_runs([run(1, self.c2, "success", attempt=2, age=1, started_age=9),
                            run(2, self.c3, "success", age=2)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  run 2 passed on " + self.c3[:7] + "; main tip is tested", out)

    def test_a_rerun_going_on_red_holds_the_freeze_while_a_newer_commit_waits(self):
        self.attempts = {"1": {"1": {"status": "completed", "conclusion": "failure"}}}
        self.dotfiles_runs([run(2, self.c3, status="queued", age=2),
                            run(1, self.c2, status="in_progress", attempt=2, age=1, started_age=9)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 1 attempt 1 failed on " + self.c2[:7] + "  (a rerun is going)", out)
        self.assertIn("no earlier green run", out)

    def test_the_walk_stops_at_the_newest_conclusive_commit(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.walked_commits(), [self.c3, self.m, self.c2],
                         "the walk reads the tip, M and c2, then stops at the green; c1 is never read")

    def test_no_run_on_main_means_no_commit_walk(self):
        self.dotfiles_runs([])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.walked_commits(), [], "no run to place, so no commit is read")

    def test_an_unexpected_error_is_one_stdout_line_and_the_traceback_on_stderr(self):
        run_without_attempt = run(1, self.c3, "success")
        del run_without_attempt["attempt"]          # a row gh did not promise: a KeyError in the script
        self.dotfiles_runs([run_without_attempt])
        rc, out, err = self.streams("dotfiles")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("dotfiles: ERROR  cannot read state: unexpected KeyError", out)
        self.assertEqual(len([line for line in out.splitlines() if "ERROR" in line]), 1, out)
        self.assertIn("Traceback (most recent call last)", err)
        self.assertNotIn("Traceback", out)

    def test_green_base_off_first_parent_history_exits_1(self):
        self.dotfiles_runs([run(1, self.s1, "success")])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("not on the first-parent history", out)


class AllAndHomelab(Fixture):
    def test_all_exit_code_red_beats_untested(self):
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c3, "failure")],
                     "cartwmic/loop-engine|ci.yml": [run(2, self.c2, "success")]}
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        rc, out = self.status("--all")
        self.assertEqual(rc, 1, out)
        self.assertIn("dotfiles: RED", out)
        self.assertIn("loop-engine: UNTESTED", out)
        self.assertIn("agent-kit: UNTESTED", out)
        self.assertIn("coordinator: GREEN", out)
        self.assertIn("homelab: n/a", out)

    def test_all_untested_without_red_exits_2(self):
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c3, "success")],
                     "cartwmic/loop-engine|ci.yml": [run(2, self.c2, "success")],
                     "cartwmic/agent-kit|unit.yml": [run(3, self.c3, "success")]}
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        rc, out = self.status("--all")
        self.assertEqual(rc, 2, out)

    def test_homelab_makes_no_gh_call(self):
        self.write_fixture()
        rc, out = self.status("homelab")
        self.assertEqual(rc, 0, out)
        self.assertIn("homelab: n/a", out)
        calls = self.log.read_text() if self.log.exists() else ""
        self.assertEqual(calls, "", "homelab must not call gh")

    def test_missing_gh_is_one_error_line_per_repo_and_all_keeps_going(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.env["PATH"] = str(empty)
        rc, out = self.status("--all")
        self.assertEqual(rc, 1, out)
        for name in ("dotfiles", "loop-engine", "agent-kit", "coordinator"):
            self.assertIn(f"{name}: ERROR  cannot read state: gh could not start", out)
        self.assertIn("homelab: n/a", out)
        self.assertNotIn("Traceback", out)


class CoordinatorJournal(Fixture):
    def write_journal(self, *rows):
        self.journal.write_text("".join(json.dumps({"tip": tip, "verdict": v, "started": "t", "ended": "t",
                                                    "receipts": {}, "again": False}) + "\n" for tip, v in rows))

    def dead_pid(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def take_lock(self, pid):
        self.lock.mkdir()
        (self.lock / "pid").write_text(str(pid))

    def test_pass_at_tip_exits_0(self):
        self.write_journal((self.c3, "pass"))
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)

    def test_pass_behind_tip_with_no_live_lock_exits_2(self):
        self.write_journal((self.c2, "pass"))
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)
        self.assertIn("2 main commit(s)", out)

    def test_pass_behind_tip_with_live_lock_exits_0(self):
        self.write_journal((self.c2, "pass"))
        self.take_lock(os.getpid())
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("a run is going", out)

    def test_dead_lock_pid_is_not_a_run(self):
        self.write_journal((self.c2, "pass"))
        self.take_lock(self.dead_pid())
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)

    def test_newest_fail_is_red_with_range_from_last_pass(self):
        self.write_journal((self.c2, "pass"), (self.c3, "fail"))
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)
        expected = git(self.src, "log", "--first-parent", "--oneline", f"{self.c2}..{self.c3}").splitlines()
        self.assertEqual(self.range_lines(out), expected)

    def test_the_last_journal_line_for_a_tip_is_its_verdict(self):
        self.write_journal((self.c3, "fail"), (self.c3, "pass"))
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  journal line 2 passed on " + self.c3[:7], out)

    def test_no_journal_is_untested(self):
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)
        self.assertIn("no journal record", out)
        self.assertIn("no conclusive journal line on main", out)

    def test_malformed_journal_line_exits_1(self):
        self.journal.write_text("{not json\n")
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 1, out)

    def test_journal_row_with_a_verdict_and_no_tip_exits_1_in_one_line(self):
        self.journal.write_text(json.dumps({"verdict": "pass"}) + "\n")
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 1, out)
        self.assertIn("has a pass verdict and no tip", out)
        self.assertNotIn("Traceback", out)

    def test_journal_path_follows_xdg_state_home_without_an_override(self):
        state = Path(self.tmp.name) / "xdg"
        (state / "coordinator-ci").mkdir(parents=True)
        (state / "coordinator-ci" / "main-journeys.jsonl").write_text(
            json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        del self.env["CI_MAIN_STATUS_JOURNAL"]
        self.env["XDG_STATE_HOME"] = str(state)
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)


if __name__ == "__main__":
    unittest.main()
