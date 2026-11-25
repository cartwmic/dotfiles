"""The hidden-red rule of ci-main-status (loop-engine issue 215), against the same fake `gh` and real git as test_ci_main_status.py.

Its own file so the untested-hunks check can run it first (its name sorts before test_ci_main_status.py) and so each file stays short.
"""
import datetime
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import test_ci_main_status as base
from test_ci_main_status import (SCRIPT, REPOS_GITHUB, git, commit, run, is_ancestor, steps, ci_jobs, red_unit_jobs, full_suite_jobs, pull_request_jobs, UNIT_STEP, FLOOR_STEP, KIT_FILES)


class HiddenRed(base.Fixture):
    """A red run an older push left under a newer green one stays visible until a later commit on main links it (loop-engine issue 215).

    main (first-parent): c1, c2, M (merge of the side commit s1), c3. `since` is c1: the red commit c2 is after it. Each test names the
    scenario of the design it proves. Every scenario that drives the script runs through three_ways, which runs it cold (no cache). Four
    representative scenarios (a red nobody handled, a red a later commit handled, a green one and a run list over the 1,000-run limit) pass
    matrix=True: then it also runs warm (a cache written at an earlier tip) and read-only (the cache folder cannot be written), and stdout and
    exit code must be the same in all three. The other scenarios prove their rule once, cold, because each extra run costs seconds.
    """
    WF = "cartwmic/dotfiles|ci.yml"

    def setUp(self):
        super().setUp()
        self.env["CI_MAIN_STATUS_SINCE"] = self.c1

    # -- helpers
    def state(self):
        return Path(self.env["XDG_STATE_HOME"])

    def cache_file(self, slug="cartwmic/dotfiles"):
        return self.state() / "ci-main-status/hidden-red" / (slug.replace("/", "__") + ".json")

    def log_lines(self):
        path = Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def calls(self):
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        self.log.write_text("")
        return calls

    def red_below_green(self):
        self.dotfiles_runs([run(2, self.c3, "success", age=2), run(1, self.c2, "failure", age=1)])

    def tip_after(self, message, conclusion="success", status="completed", **kw):
        """A new commit on main with `message`, and a run on it (the newest run)."""
        sha = commit(self.src, message)
        rows = self.runs[self.WF]
        self.dotfiles_runs([run(max(r["databaseId"] for r in rows) + 1, sha, conclusion, status=status, age=len(rows) + 1, **kw)] + rows)
        return sha

    def prime(self, repo):
        """The call that leaves a cache behind: main one commit back (the tip itself when that is before `since`), with only the runs that existed then."""
        since, tip = self.env["CI_MAIN_STATUS_SINCE"], git(self.src, "rev-parse", "main")
        earlier = git(self.src, "rev-parse", "main~1") if is_ancestor(self.src, since, "main~1") else tip
        saved = self.runs
        self.runs = {k: [r for r in rows if is_ancestor(self.src, r["headSha"], earlier)] for k, rows in saved.items()}
        git(self.src, "update-ref", "refs/heads/main", earlier)
        try:
            self.streams("--merge-gate", repo, "--pr", "99")   # --pr makes it read the hidden reds even when the newest commit is red
        finally:
            git(self.src, "update-ref", "refs/heads/main", tip)
            self.runs = saved

    def three_ways(self, *args, matrix=False):
        """(exit code, stdout) of the call run cold. With matrix=True it is also run warm and read-only, and the three must be the same;
        the warm run must really have read a cache and the read-only run must really have failed to write one."""
        repo = [a for a in args if not a.startswith("-") and not a.isdigit()][-1]
        slug = REPOS_GITHUB.get(repo, repo)
        def fresh():
            shutil.rmtree(self.state(), ignore_errors=True)
            Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).unlink(missing_ok=True)
        fresh()
        cold = self.streams(*args)[:2]
        self.assertEqual(self.log_lines()[-1]["cache"], "cold")
        if not matrix:
            return cold
        fresh()
        self.prime(repo)
        self.assertTrue(self.cache_file(slug).exists(), "the prime call wrote no cache, so the warm run would be a cold one")
        Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).unlink(missing_ok=True)
        warm = self.streams(*args)[:2]
        self.assertEqual(self.log_lines()[-1]["cache"], "warm")
        fresh()
        folder = self.state() / "ci-main-status"
        folder.mkdir(parents=True)
        (folder / "hidden-red").write_text("a file where the cache folder should be")
        read_only = self.streams(*args)[:2]
        self.assertEqual(self.log_lines()[-1]["cache"], "unwritable")
        self.assertEqual(warm, cold, "a warm call must print what a cold one prints")
        self.assertEqual(read_only, cold, "a call that cannot write its cache must print what a cold one prints")
        return cold

    def patched(self, **constants):
        """A copy of the script with some module constants changed (a ceiling of 3 runs instead of 1,000, say)."""
        text = SCRIPT.read_text()
        for name, value in constants.items():
            text, n = re.subn(rf"^{name} = \d+", f"{name} = {value}", text, flags=re.M)
            self.assertEqual(n, 1, name)
        path = Path(self.tmp.name) / "patched_gate.py"
        path.write_text(text)
        return path

    def run_script(self, script, *args):
        self.write_fixture()
        r = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=self.env, timeout=120)
        return r.returncode, r.stdout, r.stderr

    # -- the rule
    def test_an_older_red_run_under_a_newer_green_one_is_refused_in_every_mode(self):
        self.red_below_green()
        for args in (["dotfiles"], ["--tip", "dotfiles"], ["--merge-gate", "dotfiles"]):
            with self.subTest(args=args):
                rc, out = self.three_ways(*args, matrix=args == ["--merge-gate", "dotfiles"])
                self.assertEqual(rc, 1, out)
                self.assertTrue(out.startswith("dotfiles: RED  1 unhandled red(s) on main\n"), out)
                self.assertIn(f"  run 1 failed on {self.c2[:7]} c2 first parent: no later commit on main links it, no rerun passed", out)
                self.assertIn("Handles: <full 40-character sha>", out)
                self.assertIn("  dotfiles: GREEN", out)   # the line that would have come first follows, indented

    def test_a_later_commit_with_a_handles_line_clears_it_once_its_own_run_is_green_and_not_while_it_is_going(self):
        self.red_below_green()
        handler = self.tip_after(f"Fix c2\n\nHandles: {self.c2}")
        for args in (["dotfiles"], ["--merge-gate", "dotfiles"], ["--tip", "dotfiles"]):
            with self.subTest(args=args):
                rc, out = self.three_ways(*args, matrix=args == ["--merge-gate", "dotfiles"])
                self.assertEqual(rc, 0, out)
                self.assertIn(f"GREEN  run 3 passed on {handler[:7]}", out)
        git(self.src, "reset", "-q", "--hard", self.c3)
        self.red_below_green()
        self.tip_after(f"Fix c2\n\nHandles: {self.c2}", status="in_progress")   # its run is going: the answer for a tip with a run going
        for args, want in ((["dotfiles"], 0), (["--merge-gate", "dotfiles"], 0), (["--tip", "dotfiles"], 2)):
            with self.subTest(going=args):
                rc, out = self.three_ways(*args)
                self.assertEqual(rc, want, out)
                self.assertIn("a run is going" if want == 0 else "UNTESTED", out)
                self.assertNotIn("unhandled red", out)

    def test_git_s_own_revert_line_clears_it(self):
        self.red_below_green()
        self.tip_after(f'Revert "c2 first parent"\n\nThis reverts commit {self.c2}.')
        rc, out = self.three_ways("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)

    def test_a_handler_that_is_a_branch_commit_inside_a_merge_commit_clears_it(self):
        self.red_below_green()
        git(self.src, "switch", "-q", "-c", "fix", self.c3)
        commit(self.src, f"fix\n\nHandles: {self.c2}")
        git(self.src, "switch", "-q", "main")
        git(self.src, "merge", "--no-ff", "-q", "-m", "Merge fix", "fix")
        tip = git(self.src, "rev-parse", "HEAD")
        self.dotfiles_runs([run(3, tip, "success", age=3)] + self.runs[self.WF])
        rc, out = self.three_ways("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)

    def test_the_marker_is_exact(self):
        clears = {"a bullet in a squash body": f"Fix (#9)\n\n* fix c2\n\n* Handles: {self.c2}\n\nCo-Authored-By: x <x@example.invalid>",
                  "the key in capitals": f"fix\n\nHANDLES: {self.c2}",
                  "two lines, one of them ours": f"fix\n\nHandles: {self.c1}\nHandles: {self.c2}"}
        stays = {"a 7-character prefix": f"fix\n\nHandles: {self.c2[:7]}", "a 39-character prefix": f"fix\n\nHandles: {self.c2[:39]}",
                 "Handled:": f"fix\n\nHandled: {self.c2}", "no colon": f"fix\n\nhandles {self.c2}", "mid-line": f"fix\n\nthis Handles: {self.c2}",
                 "another commit": f"fix\n\nHandles: {self.c1}", "a sha that is not a commit": f"fix\n\nHandles: {'e' * 40}"}
        for label, message in {**clears, **stays}.items():
            with self.subTest(label):
                self.red_below_green()
                self.tip_after(message)
                rc, out = self.three_ways("dotfiles")
                self.assertEqual(rc, 0 if label in clears else 1, out)
                git(self.src, "reset", "-q", "--hard", self.c3)

    def test_a_red_run_that_a_rerun_turned_green_is_not_red(self):
        self.attempts = {"1": {"1": {"status": "completed", "conclusion": "failure"}}}
        self.dotfiles_runs([run(2, self.c3, "success", age=2), run(1, self.c2, "success", age=1, attempt=2)])
        rc, out = self.three_ways("--merge-gate", "dotfiles", matrix=True)
        self.assertEqual(rc, 0, out)

    def test_a_rerun_that_is_going_or_ended_without_a_verdict_leaves_the_commit_red(self):
        self.attempts = {"1": {"1": {"status": "completed", "conclusion": "failure"}}}
        for conclusion in (None, "failure", "cancelled", "timed_out", "startup_failure", "skipped", "neutral", "stale", "action_required"):
            with self.subTest(conclusion=conclusion):
                second = run(1, self.c2, conclusion, status="completed" if conclusion else "in_progress", age=1, attempt=2)
                self.dotfiles_runs([run(2, self.c3, "success", age=2), second])
                rc, out = self.three_ways("--merge-gate", "dotfiles")
                self.assertEqual(rc, 1, out)
                self.assertIn(f"failed on {self.c2[:7]}", out)

    def test_an_old_green_run_that_is_rerun_and_fails_is_red_on_the_next_call(self):
        self.dotfiles_runs([run(2, self.c3, "success", age=2), run(1, self.c2, "success", age=1)])
        self.assertEqual(self.streams("--merge-gate", "dotfiles")[0], 0)
        self.assertTrue(self.cache_file().exists())
        self.attempts = {"1": {"1": {"status": "completed", "conclusion": "success"}}}   # the rerun: same run, attempt 2, failed
        self.dotfiles_runs([run(2, self.c3, "success", age=2), run(1, self.c2, "failure", age=1, attempt=2)])
        rc, out, _ = self.streams("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"failed on {self.c2[:7]}", out)

    def test_a_red_before_since_or_on_it_is_not_held_against_main_and_the_first_commit_after_it_is(self):
        self.dotfiles_runs([run(3, self.c3, "success", age=3), run(2, self.c2, "failure", age=2), run(1, self.c1, "failure", age=1)])
        self.env["CI_MAIN_STATUS_SINCE"] = self.c2
        self.assertEqual(self.three_ways("--merge-gate", "dotfiles")[0], 0)   # c2 is on `since`, c1 before it
        self.env["CI_MAIN_STATUS_SINCE"] = self.c1   # c2 is the first commit after it
        rc, out = self.three_ways("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"failed on {self.c2[:7]}", out)
        self.assertNotIn(f"failed on {self.c1[:7]}", out)

    # -- cost, ceilings, history
    def history(self, dates):
        """A new main: since (dates[0]), the red commit, a green commit, and a tip; each committed at the given time. Returns the four shas."""
        shutil.rmtree(self.src)
        self.src.mkdir()
        git(self.src, "init", "-q", "-b", "main")
        shas = [commit(self.src, f"commit {n}", when) for n, when in enumerate(dates)]
        self.env["CI_MAIN_STATUS_SINCE"] = shas[0]
        return shas

    def test_a_red_400_days_old_with_no_link_is_still_red_and_holds_the_floor(self):
        since, red, green, tip = self.history(["2025-09-01T00:00:00+00:00", "2025-10-01T00:00:00+00:00", "2025-10-02T00:00:00+00:00", "2026-11-10T00:00:00+00:00"])
        old = lambda n, sha, conclusion, day: {**run(n, sha, conclusion, age=n), "createdAt": f"{day}T10:00:00Z"}
        self.dotfiles_runs([old(4, tip, "success", "2026-11-11"), old(3, green, "success", "2025-10-06"), old(2, red, "failure", "2025-10-05")])
        rc, out = self.three_ways("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"failed on {red[:7]}", out)
        shutil.rmtree(self.state())
        self.streams("--merge-gate", "dotfiles")
        self.assertLessEqual(json.loads(self.cache_file().read_text())["floor"], "2025-10-05T10:00:00Z")

    def test_old_handled_reds_cost_nothing_on_a_warm_call(self):
        def warm_calls():
            shutil.rmtree(self.state(), ignore_errors=True)
            self.assertEqual(self.streams("--merge-gate", "dotfiles")[0], 0)   # cold: writes the cache
            cold = self.calls()
            self.assertEqual(self.streams("--merge-gate", "dotfiles")[0], 0)
            return cold, self.calls()
        rows, n = [], 0
        for i in range(120):   # 240 commits: three compare pages on a cold call
            bad = commit(self.src, f"work {i}")
            fix = commit(self.src, f"fix {i}\n\nHandles: {bad}")
            rows += [{**run(n + 1, bad, "failure", age=1), "createdAt": "2026-11-02T10:00:00Z"}, {**run(n + 2, fix, "success", age=1), "createdAt": "2026-11-02T10:01:00Z"}]
            n += 2
        tip = commit(self.src, "tip")
        self.dotfiles_runs([{**run(n + 1, tip, "success", age=1), "createdAt": "2026-12-20T10:00:00Z"}] + rows[::-1])
        cold_reds, warm_reds = warm_calls()
        git(self.src, "reset", "-q", "--hard", self.c3)
        self.dotfiles_runs([{**run(1, self.c3, "success", age=1), "createdAt": "2026-12-20T10:00:00Z"}])
        cold_none, warm_none = warm_calls()
        self.assertEqual(len(cold_reds) - len(cold_none), 2, "the cold call pages through the 245 commits: three compare pages, not one")
        self.assertEqual(len(warm_reds), len(warm_none), f"old handled reds changed the cost of a warm call:\n{warm_reds}\n{warm_none}")
        window = [c for c in warm_reds if "--created" in c]
        self.assertEqual(len(window), 1, warm_reds)
        floor = window[0].split("--created ")[1].split()[0]
        self.assertTrue(floor.startswith(">=2026-11-"), floor)
        self.assertGreater(floor[2:], "2026-11-02T10:01:00Z", "the floor moved past the old reds: they are not listed again")

    def test_a_run_list_that_fills_the_ceiling_is_split_and_never_read_as_complete(self):
        ids = {1: self.c2, 2: self.s1, 3: self.m, 4: self.c3}
        rows = [run(n, sha, "failure" if n == 1 else "success", age=n) for n, sha in ids.items()]
        tip = commit(self.src, "tip")
        self.dotfiles_runs([run(5, tip, "success", age=5)] + rows[::-1])
        script = self.patched(RUN_CEILING=3)
        self.script_path = script
        rc, out = self.three_ways("--merge-gate", "dotfiles", matrix=True)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"failed on {self.c2[:7]}", out)   # the oldest run is past the first 3: found by splitting
        self.assertTrue([c for c in self.calls() if ".." in c.split("--created ")[-1]], "the range was split")
        self.dotfiles_runs([run(n, sha, "success", age=1) for n, sha in ids.items()] + [run(5, tip, "success", age=1)])   # all in one second
        rc, out, err = self.run_script(script, "--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR  cannot read state", out)
        self.assertIn("were created in the second", out)

    def test_a_range_of_many_days_is_split_at_its_middle_so_the_calls_stay_few(self):
        """3,000 runs over 40 days, with gh keeping to its 1,000-run limit: about 7 run-list calls, not hundreds and not a RecursionError."""
        base = datetime.datetime(2026, 11, 2, tzinfo=datetime.timezone.utc)
        rows = [{**run(n, self.c3, "success", age=1), "createdAt": (base + datetime.timedelta(seconds=n * 1152)).strftime("%Y-%m-%dT%H:%M:%SZ")} for n in range(1, 3001)]
        self.dotfiles_runs(rows[::-1])
        self.assertGreater((datetime.datetime.fromisoformat(rows[-1]["createdAt"].replace("Z", "+00:00")) - base).days, 39)
        rc, out, err = self.streams("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out + err)
        lists = [c for c in self.calls() if "run list" in c and "--created" in c]
        self.assertTrue(5 <= len(lists) <= 10, f"{len(lists)} run-list calls:\n" + "\n".join(lists[:12]))

    def test_past_the_compare_cap_the_commits_list_is_read_and_a_dropped_commit_is_an_error(self):
        self.red_below_green()
        for n in range(6):
            commit(self.src, f"work {n}")
        handler = commit(self.src, f"fix\n\nHandles: {self.c2}")
        tip = commit(self.src, "last")
        self.dotfiles_runs([run(3, tip, "success", age=3)] + self.runs[self.WF])
        self.compare_cap = 4   # compare lists 4 of the 11 commits and says ahead_by 11
        script = self.patched(COMPARE_CAP=4)
        rc, out, err = self.run_script(script, "--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out + err)
        self.assertTrue([c for c in self.calls() if "/commits?sha=" in c], "read through the commits list")
        self.listing_drop = [handler]
        shutil.rmtree(self.state(), ignore_errors=True)
        rc, out, err = self.run_script(script, "--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("the commits list gave", out)
        self.listing_drop, self.compare_cap = [], 10000
        self.compare_drop = [handler]   # a compare that leaves a commit out of its own count
        shutil.rmtree(self.state(), ignore_errors=True)
        rc, out, err = self.run_script(SCRIPT, "--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("is empty with", out)

    def test_a_cursor_that_main_no_longer_contains_drops_the_cache_and_the_red_is_back(self):
        self.red_below_green()
        self.tip_after(f"Fix c2\n\nHandles: {self.c2}")
        self.assertEqual(self.streams("--merge-gate", "dotfiles")[0], 0)   # the handler is in the cache's links, the cursor is the handler
        git(self.src, "reset", "-q", "--hard", self.c3)   # main is rewritten: the handler is gone
        tip = commit(self.src, "another commit")
        self.dotfiles_runs([run(3, tip, "success", age=3), run(2, self.c3, "success", age=2), run(1, self.c2, "failure", age=1)])
        rc, out, _ = self.streams("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.log_lines()[-1]["cache"], "dropped:main's history was rewritten")
        shutil.rmtree(self.state())
        self.assertEqual((rc, out), self.streams("--merge-gate", "dotfiles")[:2], "the same as a cold call")

    def test_a_since_that_is_not_on_main_is_an_error(self):
        git(self.src, "switch", "-q", "-c", "other", self.c1)
        elsewhere = commit(self.src, "not on main")
        git(self.src, "switch", "-q", "main")
        self.red_below_green()
        self.env["CI_MAIN_STATUS_SINCE"] = elsewhere
        rc, out, _ = self.streams("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR  cannot read state: the grandfather commit", out)
        self.assertFalse(self.cache_file().exists())

    def test_a_cache_that_is_wrong_or_cannot_be_used_gives_the_cold_answer(self):
        self.red_below_green()
        self.assertEqual(self.streams("--merge-gate", "dotfiles")[0], 1)
        good = json.loads(self.cache_file().read_text())
        shutil.rmtree(self.state())
        cold = self.streams("--merge-gate", "dotfiles")[:2]
        broken = {"not json": "{", "wrong version": {**good, "version": 2}, "other since": {**good, "since": self.c2},
                  "other workflow": {**good, "workflow": "other.yml"}, "other repo": {**good, "repo": "cartwmic/loop-engine"},
                  "cursor not a sha": {**good, "cursor": "abc"}, "a link not a sha": {**good, "links": [["abc", "def"]]}, "a list": [1]}
        for label, content in broken.items():
            with self.subTest(label):
                self.cache_file().write_text(content if isinstance(content, str) else json.dumps(content))
                self.assertEqual(self.streams("--merge-gate", "dotfiles")[:2], cold)
                self.assertTrue(self.log_lines()[-1]["cache"].startswith("dropped:"), self.log_lines()[-1])
                self.assertEqual(json.loads(self.cache_file().read_text())["version"], 1, "the call wrote a good cache back")

    # -- reads that fail
    def test_a_gateway_error_is_asked_again_and_any_other_failure_is_an_error(self):
        self.red_below_green()
        self.fail_once = ["compare/", "--created"]
        rc, out, _ = self.streams("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertNotIn("ERROR", out)
        self.fail_once = []
        for message, tries in (("HTTP 503 (always)", 3), ("HTTP 403: rate limit", 1), ("HTTP 404: not found", 1)):
            with self.subTest(message=message):
                shutil.rmtree(self.state(), ignore_errors=True)
                self.fail_path = {"/compare/": message}
                self.calls()
                rc, out, _ = self.streams("--merge-gate", "dotfiles")
                self.assertEqual(rc, 1, out)
                self.assertIn("ERROR  cannot read state", out)
                self.assertEqual(len([c for c in self.calls() if "/compare/" in c]), tries)
                self.assertFalse(self.cache_file().exists(), "an error writes no cache")
        self.fail_path = {}
        for label, raw in (("not JSON", "<html>"), ("a missing field", '{"status": "ahead"}')):
            with self.subTest(label):
                self.reply = {"/compare/": raw}
                rc, out, _ = self.streams("--merge-gate", "dotfiles")
                self.assertEqual(rc, 1, out)
                self.assertIn("ERROR  cannot read state", out)

    # -- --pr
    AK = "cartwmic/agent-kit|unit.yml"

    def fix_pr(self):
        git(self.src, "switch", "-q", "-c", "fix", self.c3)
        (self.src / "f.txt").write_text("fix\n")
        git(self.src, "add", "f.txt")
        head = commit(self.src, "the fix")
        git(self.src, "switch", "-q", "main")
        self.prs = {"7": {"headRefOid": head, "headRefName": "fix"}}
        return head

    def test_a_pr_whose_full_suite_run_passed_what_failed_passes_a_hidden_red(self):
        head = self.fix_pr()
        self.runs = {self.AK: [run(2, self.c3, "success", age=2), run(1, self.c2, "failure", age=1)]}
        self.jobs = {"1": red_unit_jobs()}
        rc, out = self.three_ways("--merge-gate", "agent-kit")
        self.assertEqual(rc, 1, out)
        for jobs, want in ((full_suite_jobs(), 0), (full_suite_jobs(unit="failure"), 1), (pull_request_jobs(), 1)):
            with self.subTest(want=want, jobs=jobs[0]["conclusion"]):
                self.runs[self.AK] = [run(4, head, "success" if jobs[0]["conclusion"] == "success" else "failure", event="workflow_dispatch", age=4, branch="fix")] + self.runs[self.AK][-2:]
                self.jobs["4"] = jobs
                rc, out = self.three_ways("--merge-gate", "agent-kit", "--pr", "7")
                self.assertEqual(rc, want, out)
                if want == 0:
                    self.assertIn("its own full-suite run 4", out)
                    self.assertIn("unhandled red(s)", out)   # the RED lines print as without --pr

    def test_two_reds_that_failed_in_different_jobs_need_a_run_that_passed_both(self):
        head = self.fix_pr()
        second = commit(self.src, "second red")
        tip = commit(self.src, "tip")
        node_floor_red = [{"databaseId": 31, "name": "unit", "conclusion": "success", "steps": [{"name": UNIT_STEP, "conclusion": "success"}]},
                          {"databaseId": 32, "name": "node-floor", "conclusion": "failure", "steps": [{"name": FLOOR_STEP, "conclusion": "failure"}]}]
        unit_red = [{"databaseId": 11, "name": "unit", "conclusion": "failure", "steps": [{"name": UNIT_STEP, "conclusion": "failure"}]},
                    {"databaseId": 12, "name": "node-floor", "conclusion": "success", "steps": [{"name": FLOOR_STEP, "conclusion": "success"}]}]
        self.runs = {self.AK: [run(5, tip, "success", age=5), run(4, head, "success", event="workflow_dispatch", age=4, branch="fix"),
                               run(3, second, "failure", age=3), run(1, self.c2, "failure", age=1)]}
        self.jobs = {"1": unit_red, "3": node_floor_red}
        self.jobs["4"] = [{"databaseId": 21, "name": "unit", "conclusion": "success", "steps": [{"name": UNIT_STEP, "conclusion": "success"}]},
                          {"databaseId": 22, "name": "node-floor", "conclusion": "skipped", "steps": []}]   # passes unit, skips node-floor
        rc, out = self.three_ways("--merge-gate", "agent-kit", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("2 unhandled red(s)", out)
        self.jobs["4"] = [{"databaseId": 21, "name": "unit", "conclusion": "skipped", "steps": []},   # the other way round: node-floor passes, unit is skipped
                          {"databaseId": 22, "name": "node-floor", "conclusion": "success", "steps": [{"name": FLOOR_STEP, "conclusion": "success"}]}]
        rc, out = self.three_ways("--merge-gate", "agent-kit", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.jobs["4"] = full_suite_jobs()
        rc, out = self.three_ways("--merge-gate", "agent-kit", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("failed in run 3, run 1", out.replace("run 1, run 3", "run 3, run 1"))

    def test_dotfiles_the_pin_rule_clears_one_red_the_union_rule_the_other_and_only_the_pin_red_is_printed(self):
        git(self.src, "switch", "-q", "-c", "fix", self.c3)
        (self.src / "pins.txt").write_text("pins\n")
        git(self.src, "add", "pins.txt")
        head = commit(self.src, "the pin fix")
        git(self.src, "switch", "-q", "main")
        tip = commit(self.src, "tip")
        own = run(5, head, "success", event="pull_request", age=5, branch="fix")
        self.dotfiles_runs([run(4, tip, "success", age=4), own, run(3, self.c3, "failure", age=3), run(1, self.c2, "failure", age=1)])
        mise = {"name": "mise-tests", "conclusion": "success", "steps": []}
        self.jobs = {"1": [*ci_jobs(steps(pins="failure", linux="skipped")), mise], "3": [*ci_jobs(steps(linux="failure")), mise],
                     "5": [*ci_jobs(steps()), {**mise, "conclusion": "skipped"}]}
        self.prs = {"7": {"files": [{"path": f} for f in KIT_FILES], "changedFiles": 2, "headRefOid": head, "headRefName": "fix"}}
        rc, out = self.three_ways("--merge-gate", "dotfiles", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertEqual([l for l in out.splitlines() if "pin-fix-red:" in l], [f"  pin-fix-red: {self.c2}"], out)
        self.assertIn("is the pin fix for this red", out)
        self.assertIn("passed as a red-main fix", out)
        rc, out = self.three_ways("--merge-gate", "dotfiles")   # no --pr: refused, and no pin-fix-red line
        self.assertEqual(rc, 1, out)
        self.assertNotIn("pin-fix-red", out)
        self.jobs["5"] = [*ci_jobs(steps(linux="failure")), {**mise, "conclusion": "skipped"}]   # the PR's own run fails: neither red passes
        self.dotfiles_runs([run(4, tip, "success", age=4), run(5, head, "failure", event="pull_request", age=5, branch="fix"), run(3, self.c3, "failure", age=3), run(1, self.c2, "failure", age=1)])
        rc, out = self.three_ways("--merge-gate", "dotfiles", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertNotIn("pin-fix-red", out)

    # -- the rest
    def test_a_newest_red_stays_red_whatever_names_it(self):
        self.dotfiles_runs([run(1, self.c3, "failure", age=1)])
        commit(self.src, f"fix\n\nHandles: {self.c3}")   # untested, above the red tip
        rc, out, _ = self.streams("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"RED  run 1 failed on {self.c3[:7]}", out)
        self.assertEqual(self.log_lines()[-1]["skipped"], "newest red")
        self.assertFalse(self.cache_file().exists())
        self.assertEqual([c for c in self.calls() if "/compare/" in c or "--created" in c], [])

    def test_a_red_handler_is_shown_in_place_of_the_red_it_links(self):
        self.red_below_green()
        handler = self.tip_after(f"Fix c2\n\nHandles: {self.c2}", "failure")
        self.assertEqual(self.streams("--merge-gate", "dotfiles")[0], 1)   # the handler is the newest red
        self.assertIn(f"failed on {handler[:7]}", self.streams("--merge-gate", "dotfiles")[1])
        self.tip_after("above the handler")   # now the handler is a hidden red
        rc, out = self.three_ways("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"failed on {handler[:7]}", out)
        self.assertNotIn(f"failed on {self.c2[:7]}", out)

    def test_a_failure_that_ran_nothing_or_that_a_later_run_of_the_commit_answered_is_not_red(self):
        self.jobs = {"1": [{"databaseId": 7, "name": "tests", "conclusion": "cancelled", "steps": []}]}
        self.annotations = {"7": [{"message": "The job was not acquired by Runner of type hosted even after multiple attempts"}]}
        self.dotfiles_runs([run(2, self.c3, "success", age=2), run(1, self.c2, "failure", age=1)])
        self.assertEqual(self.three_ways("--merge-gate", "dotfiles")[0], 0)
        self.jobs, self.annotations = {}, {}
        self.dotfiles_runs([run(3, self.c3, "success", age=3), run(2, self.c2, "success", event="workflow_dispatch", age=2), run(1, self.c2, "failure", age=1)])
        self.assertEqual(self.three_ways("--merge-gate", "dotfiles")[0], 0)

    def test_a_failed_run_on_a_commit_that_is_not_on_main_or_is_newer_than_the_tip_is_ignored(self):
        git(self.src, "switch", "-q", "-c", "elsewhere", self.c1)
        off_main = commit(self.src, "not on main")
        git(self.src, "switch", "-q", "-c", "ahead", self.c3)
        newer = commit(self.src, "newer than main's tip")
        git(self.src, "switch", "-q", "main")
        for label, sha in (("not on main", off_main), ("newer than the tip", newer)):
            with self.subTest(label):
                self.dotfiles_runs([run(3, self.c3, "success", age=3), run(2, sha, "failure", age=2)])
                rc, out = self.three_ways("--merge-gate", "dotfiles")
                self.assertEqual(rc, 0, out)

    def test_every_call_of_a_repo_with_since_leaves_one_log_line(self):
        self.red_below_green()
        self.assertEqual(self.streams("--merge-gate", "dotfiles")[0], 1)
        self.assertEqual(self.streams("--tip", "dotfiles")[0], 1)
        first, second = self.log_lines()
        self.assertEqual((first["repo"], first["action"], first["pr"], first["verdict"], first["exit"], first["cache"], first["skipped"]),
                         ("cartwmic/dotfiles", "merge-gate", None, "RED", 1, "cold", None))
        self.assertEqual((second["action"], second["cache"]), ("tip", "warm"))
        self.assertEqual(first["hidden"], [{"sha": self.c2, "run": 1, "attempt": 1}])
        self.assertRegex(first["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsInstance(first["duration_ms"], int)
        self.assertGreater(first["reads"], second["reads"], "the warm call read less")
        self.dotfiles_runs([run(1, self.c3, "success", age=1)])   # a green call logs too
        self.assertEqual(self.streams("dotfiles")[0], 0)
        self.assertEqual((self.log_lines()[-1]["verdict"], self.log_lines()[-1]["hidden"]), ("GREEN", []))
        Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).unlink()
        Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).mkdir()   # a log that cannot be written: a stderr note, the same verdict
        self.red_below_green()
        rc, out, err = self.streams("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("could not write", err)
        self.assertIn("1 unhandled red(s)", out)

    def test_two_calls_at_once_leave_one_whole_cache_and_print_the_same(self):
        self.red_below_green()
        self.write_fixture()
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), "--merge-gate", "dotfiles"], stdout=subprocess.PIPE, text=True, env=self.env) for _ in range(2)]
        outs = [p.communicate(timeout=120)[0] for p in procs]
        self.assertEqual(outs[0], outs[1])
        self.assertEqual([p.returncode for p in procs], [1, 1])
        self.assertEqual(json.loads(self.cache_file().read_text())["version"], 1)
        self.assertEqual([f.name for f in self.cache_file().parent.iterdir()], [self.cache_file().name], "no temp file is left")

    def test_repos_without_since_and_the_journal_keep_their_old_behaviour(self):
        self.red_below_green()
        no_since = Path(self.tmp.name) / "no_since_gate.py"
        no_since.write_text(re.sub(r', "since": "[0-9a-f]{40}"', "", SCRIPT.read_text()))
        self.env.pop("CI_MAIN_STATUS_SINCE")
        rc, out, _ = self.run_script(no_since, "--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)   # the red under the green is not looked for
        self.assertEqual([c for c in self.calls() if "/compare/" in c or "--created" in c], [])
        self.assertEqual(self.log_lines(), [])
        self.env["CI_MAIN_STATUS_SINCE"] = self.c1
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass", "tree": git(self.src, "rev-parse", self.c3 + "^{tree}")}) + "\n")
        rc, out, _ = self.streams("--merge-gate", "--all")
        self.assertEqual(rc, 1, out)
        self.assertIn("coordinator: GREEN", out)   # the journal repo is judged from the journal, as before
        self.assertNotIn("cartwmic/coordinator", {l["repo"] for l in self.log_lines()})
        self.assertEqual({l["repo"] for l in self.log_lines()}, {"cartwmic/dotfiles", "cartwmic/loop-engine", "cartwmic/agent-kit", "cartwmic/alert-steward",
                                                                "StoryCraftTW/storycraft", "cartwmic/retro"})

    def test_the_since_table_gives_every_gated_workflow_repo_a_full_sha_and_the_journal_none(self):
        gate = base.PinFixCopiesMatchTheirSources.load("gate_since_under_test", "dot_local/bin/executable_ci-main-status")
        for name, spec in gate.REPOS.items():
            if spec and "workflow" in spec:
                self.assertRegex(spec.get("since", ""), r"^[0-9a-f]{40}$", name)
        self.assertNotIn("since", gate.REPOS["coordinator"])


if __name__ == "__main__":
    unittest.main()
