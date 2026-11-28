"""ci-main-status against a fake `gh` and real git.

The fake gh answers `gh run list` from a fixture and `gh api` from a real git repo: branches/main is the real
head, commits/SHA is `git rev-list --parents -n 1`, the commit and its parents the commits API returns, and compare
lists oldest first with GitHub's status, ahead_by and cap. Each test states one row of the exit-code table in
the script's docstring.
"""
import datetime
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
    import datetime, json, os, subprocess, sys
    fixture = json.load(open(os.environ["FAKE_GH_FIXTURE"]))
    args = sys.argv[1:]
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(" ".join(args) + "\\n")
    with open(os.environ["FAKE_GH_ENV_LOG"], "a") as env_log:   # what each call's environment said: the caller and urgency tests read it
        env_log.write(json.dumps({"args": args, "caller": os.environ.get("GH_CALLER"), "urgent": os.environ.get("GH_URGENT")}) + "\\n")
    def fail(msg):
        print(msg, file=sys.stderr); sys.exit(1)
    for needle, message in fixture.get("fail_path", {}).items():   # a call whose arguments hold the needle always fails with this message
        if needle in " ".join(args):
            fail(message)
    for needle, raw in fixture.get("reply", {}).items():   # a call whose arguments hold the needle gets this exact output
        if needle in " ".join(args):
            print(raw); sys.exit(0)
    once = os.environ["FAKE_GH_LOG"] + ".once"   # a call whose arguments hold one of these fails once with a 502, then works
    for needle in fixture.get("fail_once", []):
        if needle in " ".join(args) and needle not in (open(once).read().split("\\n") if os.path.exists(once) else []):
            with open(once, "a") as f:
                f.write(needle + "\\n")
            fail("HTTP 502 (once)")
    def git(path, *a):
        return subprocess.run(["git", "-C", path, *a], capture_output=True, text=True, check=True).stdout
    if args[:2] == ["run", "list"]:
        repo = args[args.index("-R") + 1]
        wf = args[args.index("--workflow") + 1]
        if repo in fixture.get("fail", []):
            fail("HTTP 502 from fake api")
        rows = fixture["runs"].get(repo + "|" + wf, [])
        if "--commit" in args:   # the real filters: --commit SHA, --event NAME
            rows = [r for r in rows if r["headSha"] == args[args.index("--commit") + 1]]
        if "--event" in args:
            rows = [r for r in rows if r["event"] == args[args.index("--event") + 1]]
        if "--status" in args:   # failure: a finished run that failed; any other state: the run's status
            want = args[args.index("--status") + 1]
            rows = [r for r in rows if (r["status"] == "completed" and r["conclusion"] == "failure" if want == "failure" else r["status"] == want)]
        if "--created" in args:   # the real filter, on createdAt: ">=TIME" or "TIME..TIME" (both ends in), newest first as GitHub lists
            spec = args[args.index("--created") + 1]
            lo, hi = (spec[2:], "9999") if spec.startswith(">=") else spec.split("..")
            rows = sorted((r for r in rows if lo <= r["createdAt"] <= hi), key=lambda r: (r["createdAt"], r["databaseId"]), reverse=True)
        if "--branch" in args:   # a row with no headBranch is a run on main
            rows = [r for r in rows if r.get("headBranch", "main") == args[args.index("--branch") + 1]]
        if "--limit" in args:   # with --created, gh returns at most 1,000 runs whatever --limit says; without it, as many as asked (recorded/run_list_ceiling.json)
            rows = rows[:min(int(args[args.index("--limit") + 1]), 1000 if "--created" in args else 10**9)]
        if "--json" in args:   # as gh: only the fields asked for. A field the script reads and does not ask for is missing, not silently there.
            wanted = args[args.index("--json") + 1].split(",")
            rows = [{k: r[k] for k in wanted if k in r} for r in rows]
        print(json.dumps(rows))
    elif args[:2] == ["run", "view"]:
        attempt = args[args.index("--attempt") + 1] if "--attempt" in args else None
        jobs = fixture.get("jobs", {}).get(args[2] + "/" + str(attempt))   # a jobs fixture for one attempt, else for the run
        if jobs is None:
            jobs = fixture.get("jobs", {}).get(args[2])
        if jobs is None:   # a run with no jobs fixture failed in a real job
            jobs = [{"databaseId": 1, "name": "tests", "conclusion": "failure", "steps": []}]
        print(json.dumps({"jobs": jobs}))
    elif args[:2] == ["pr", "checks"]:
        repo = args[args.index("-R") + 1]
        checks = (fixture.get("pr_checks") or {}).get(repo, {}).get(args[2])
        if checks is None:
            fail("fake gh: no pr checks fixture " + repo + " " + args[2])
        print(json.dumps(checks))
    elif args[:2] == ["pr", "view"]:
        if args[args.index("-R") + 1] in fixture.get("fail_pr", []):
            fail("HTTP 502 from fake api")
        pull = fixture.get("prs", {}).get(args[2])
        if pull is None:
            fail("fake gh: no PR fixture " + args[2])
        if "--json" in args:   # as gh: only the fields asked for. A field the script reads and does not ask for is missing, not silently there.
            wanted = args[args.index("--json") + 1].split(",")
            pull = {k: pull[k] for k in wanted if k in pull}
        print(json.dumps(pull))
    elif args[0] == "api":
        path = args[1]
        repo = path.split("/")[1] + "/" + path.split("/")[2]
        if repo in fixture.get("fail", []):
            fail("HTTP 502 from fake api")
        src = fixture["repos"][repo]
        if path.endswith("/branches/main"):
            bp = (fixture.get("branch_protection") or {}).get(repo)
            if isinstance(bp, str):   # a named failure, such as a rate limit on the branch read
                fail(bp)
            out = {"commit": {"sha": git(src, "rev-parse", "main").strip()}}
            out.update(bp or {})   # protected + protection, as the real branch response carries them
            print(json.dumps(out))
        elif "/compare/" in path:   # status, ahead_by, and the commits oldest first, per_page a page, at most compare_cap of them (GitHub's 10,000)
            spec, _, query = path.split("/compare/")[1].partition("?")
            base, head = spec.split("...")
            params = dict(kv.split("=") for kv in query.split("&") if kv)
            per, page = int(params.get("per_page", 30)), int(params.get("page", 1))
            def ancestor(a, b):
                return subprocess.run(["git", "-C", src, "merge-base", "--is-ancestor", a, b]).returncode == 0
            status = "identical" if base == head else "ahead" if ancestor(base, head) else "behind" if ancestor(head, base) else "diverged"
            shas = git(src, "rev-list", "--reverse", "--topo-order", f"{base}..{head}").split() if status in ("ahead", "diverged") else []
            drop = fixture.get("compare_drop", [])
            listed = [c for c in shas[:fixture.get("compare_cap", 10000)] if c not in drop]
            rows = [{"sha": c, "commit": {"message": git(src, "log", "-1", "--format=%B", c).rstrip("\\n")}} for c in listed[(page - 1) * per:page * per]]
            print(json.dumps({"status": status, "ahead_by": len(shas), "total_commits": len(listed), "commits": rows}))
        elif path.split("?")[0].endswith("/commits"):   # the commits listing: newest first, per_page a page, from `sha`, committer date at or after `since`, side branches included as GitHub does
            params = dict(kv.split("=") for kv in path.partition("?")[2].split("&") if kv)
            per, page = int(params["per_page"]), int(params.get("page", 1))
            def when(c):
                return datetime.datetime.fromisoformat(git(src, "log", "-1", "--format=%cI", c).strip().replace("Z", "+00:00"))
            floor = datetime.datetime.fromisoformat(params["since"].replace("Z", "+00:00")) if "since" in params else None
            shas = [c for c in git(src, "rev-list", "--topo-order", params.get("sha", "main")).split()
                    if (floor is None or when(c) >= floor) and c not in fixture.get("listing_drop", [])]
            print(json.dumps([{"sha": c, "commit": {"message": git(src, "log", "-1", "--format=%B", c).rstrip("\\n")}} for c in shas[(page - 1) * per:page * per]]))
        elif "/commits/" in path and "/check-runs" in path.split("/commits/")[1]:
            sha = path.split("/commits/")[1].split("/")[0]
            page = int(path.split("&page=")[1]) if "&page=" in path else 1
            rows = (fixture.get("check_runs") or {}).get(repo, {}).get(sha) or []
            print(json.dumps({"total_count": len(rows), "check_runs": rows[(page - 1) * 100:page * 100]}))
        elif "/commits/" in path and path.split("/commits/")[1].split("?")[0].endswith("/status"):
            sha = path.split("/commits/")[1].split("/status")[0]
            page = int(path.split("&page=")[1]) if "&page=" in path else 1
            st = (fixture.get("statuses") or {}).get(repo, {}).get(sha) or []
            print(json.dumps({"state": "pending", "total_count": len(st), "statuses": st[(page - 1) * 100:page * 100]}))
        elif "/commits/" in path:
            sha = path.split("/commits/")[1]
            parents = git(src, "rev-list", "--parents", "-n", "1", sha).split()[1:]
            subject = git(src, "log", "-1", "--format=%B", sha).rstrip("\\n")
            print(json.dumps({"sha": sha, "parents": [{"sha": p} for p in parents], "commit": {"message": subject, "tree": {"sha": git(src, "rev-parse", sha + "^{tree}").strip()}, "committer": {"date": git(src, "log", "-1", "--format=%cI", sha).strip()}}}))
        elif "/issues/" in path:   # an issue, as the REST API returns it: body, labels, and a pull_request key when the number is a PR
            n = path.split("/issues/")[1].split("?")[0]
            issue = (fixture.get("issues") or {}).get(repo, {}).get(n)
            if issue is None:
                fail("HTTP 404: no issue fixture " + n)
            print(json.dumps(issue))
        elif "/check-runs/" in path:
            notes = fixture.get("annotations", {}).get(path.split("/check-runs/")[1].split("/")[0])
            if notes is None:
                fail("HTTP 404: no annotations fixture for " + path)
            print(json.dumps(notes))
        elif path == "repos/" + repo:
            print(json.dumps({"default_branch": "main"}))
        elif "/pulls/" in path:
            n = path.split("/pulls/")[1].split("?")[0].split("/")[0]
            pull = fixture.get("prs", {}).get(n)
            if pull is None:
                fail("HTTP 404: no PR fixture " + n)
            print(json.dumps({"base": {"ref": pull.get("baseRefName")}}))
        elif path.endswith("/protection/required_status_checks"):
            prot = (fixture.get("protection") or {}).get(repo)
            if prot is None:
                fail("HTTP 404: no protection fixture for " + repo)
            if prot is False:
                fail("HTTP 403: forbidden")
            if isinstance(prot, str):   # a named failure, such as a rate limit
                fail(prot)
            print(json.dumps(prot))
        elif "/rules/branches/" in path:
            rules = (fixture.get("branch_rules") or {}).get(repo)
            if rules is None:
                fail("HTTP 404: no branch-rules fixture for " + repo)
            if rules is False:
                fail("HTTP 403: forbidden")
            if isinstance(rules, str):
                fail(rules)
            print(json.dumps(rules))
        elif path.endswith("/rulesets"):
            sets = (fixture.get("rulesets") or {}).get(repo)
            if sets is None:
                fail("HTTP 404: no rulesets fixture for " + repo)
            if sets is False:
                fail("HTTP 403: forbidden")
            print(json.dumps(sets))
        elif "/rulesets/" in path:
            rid = path.split("/rulesets/")[1]
            full = next((s for s in (fixture.get("rulesets") or {}).get(repo) or [] if str(s.get("id")) == rid), None)
            if full is None:
                fail("HTTP 404: no ruleset " + rid)
            print(json.dumps(full))
        elif "/actions/runs/" in path:
            run_id, n = path.split("/actions/runs/")[1].split("/attempts/")
            attempt = fixture.get("attempts", {}).get(run_id, {}).get(n)
            if attempt is None:
                fail(f"HTTP 404: no fixture for run {run_id} attempt {n}")
            made = [r["createdAt"] for rows in fixture["runs"].values() for r in rows if str(r["databaseId"]) == run_id]
            print(json.dumps({**({"created_at": made[0]} if made else {}), **attempt}))   # a rerun keeps the run's creation time
        else:
            fail("fake gh: unhandled " + path)
    else:
        fail("fake gh: unhandled " + " ".join(args))
''')
COMMIT_TIME = "2026-11-01T00:00:00+00:00"   # every fixture commit is dated here, before every run's createdAt (run() below): the suite does not depend on the clock
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_AUTHOR_DATE": COMMIT_TIME, "GIT_COMMITTER_DATE": COMMIT_TIME}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True, env=GIT_ENV).stdout.strip()


def commit(path, msg, when=None):
    """A commit on the checked-out branch, dated COMMIT_TIME unless `when` (an ISO time) says otherwise."""
    env = {**GIT_ENV, "GIT_AUTHOR_DATE": when or COMMIT_TIME, "GIT_COMMITTER_DATE": when or COMMIT_TIME}
    subprocess.run(["git", "-C", str(path), "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-q", "-m", msg], capture_output=True, text=True, check=True, env=env)
    return git(path, "rev-parse", "HEAD")


REPOS_GITHUB = {"dotfiles": "cartwmic/dotfiles", "loop-engine": "cartwmic/loop-engine", "agent-kit": "cartwmic/agent-kit",
                "alert-steward": "cartwmic/alert-steward", "storycraft": "StoryCraftTW/storycraft", "retro": "cartwmic/retro"}


def names(*shas, body=None, in_body=False, issue=50):
    """The `gh pr view --json commits,body` fields of a PR whose commit message (or, with in_body, its description) carries a `Handles:` line for each sha,
    and, unless `issue` is None, a `Closes #<issue>` line (the issue a repo with `handles_labels` asks for: see backing)."""
    text = "\n".join(f"Handles: {sha}" for sha in shas) + (f"\nCloses #{issue}" if issue and shas else "")
    if in_body:
        return {"commits": [{"messageHeadline": "the fix", "messageBody": ""}], "body": text}
    return {"commits": [{"messageHeadline": "the fix", "messageBody": text}], "body": body or "a description"}


def backing(*shas, labels=("flaky test",), body=None, pull=False):
    """An issue as the REST API returns it, for the fake gh: its body holds each sha (or `body`), carrying `labels`; `pull` makes it a pull request."""
    return {"body": body if body is not None else "The red run failed on " + " and ".join(shas), "state": "open",
            "labels": [{"name": label} for label in labels], **({"pull_request": {}} if pull else {})}


def run(run_id, sha, conclusion=None, status="completed", event="push", age=0, attempt=1, started_age=None, branch="main"):
    """One gh run list row. Newer runs have a larger age. A rerun keeps its created time; its started time
    (started_age, default age) is when the latest attempt started."""
    started = age if started_age is None else started_age
    return {"databaseId": run_id, "event": event, "headSha": sha, "status": status,
            "conclusion": conclusion if status == "completed" else "", "attempt": attempt,
            "createdAt": f"2026-11-11T10:{age:02d}:00Z", "startedAt": f"2026-11-11T10:{started:02d}:00Z",
            "updatedAt": f"2026-11-11T10:{age:02d}:30Z",
            "headBranch": branch, "url": f"https://example.invalid/runs/{run_id}"}


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
        self.jobs = {}                               # run id -> the jobs `gh run view --json jobs` returns
        self.annotations = {}                        # job id (str) -> the check run's annotations
        self.prs = {}                                # PR number -> `gh pr view --json files,headRefOid`
        self.failing_pr = []                         # repos whose `gh pr view` fails
        self.issues = {"cartwmic/dotfiles": {"50": backing(self.c3)}}   # repo -> {issue number -> issue}: #50, the one names() cites, is on record for c3
        self.journal = t / "journal.jsonl"           # absent unless a test writes it
        self.lock = t / "lock.d"
        self.log = t / "gh.log"
        bindir = t / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(GH_FAKE)
        (bindir / "gh").chmod(0o755)
        self.env_log = t / "gh.env.jsonl"
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                    "FAKE_GH_LOG": str(self.log), "FAKE_GH_ENV_LOG": str(self.env_log), "FAKE_GH_FIXTURE": str(t / "fixture.json"),
                    "CI_MAIN_STATUS_JOURNAL": str(self.journal), "CI_MAIN_STATUS_LOCK": str(self.lock),
                    "CI_MAIN_STATUS_SINCE": self.c3, "CI_MAIN_STATUS_RETRY_SLEEP": "0",
                    "XDG_STATE_HOME": str(t / "state"),   # the hidden-red cache and the logs land here, never in the real state folder
                    "CI_MAIN_STATUS_HIDDEN_LOG": str(t / "hidden-red.jsonl")}   # grandfather every commit by default: a test of the hidden-red rule sets an earlier one
        for name in ("GH_CALLER", "GH_URGENT"):   # each test sets these itself; an inherited value must not leak in
            self.env.pop(name, None)

    def tearDown(self):
        self.tmp.cleanup()

    def write_fixture(self):
        repos = {r: str(self.src) for r in ("cartwmic/dotfiles", "cartwmic/loop-engine", "cartwmic/agent-kit", "cartwmic/coordinator",
                                            "cartwmic/alert-steward", "StoryCraftTW/storycraft", "cartwmic/retro")}
        repos.update(getattr(self, "extra_repos", {}))
        Path(self.env["FAKE_GH_FIXTURE"]).write_text(json.dumps(
            {"repos": repos, "runs": self.runs, "fail": self.failing, "attempts": self.attempts,
             "jobs": self.jobs, "annotations": self.annotations, "prs": self.prs, "fail_pr": self.failing_pr,
             "protection": getattr(self, "protection", {}), "rulesets": getattr(self, "rulesets", {}),
             "branch_rules": getattr(self, "branch_rules", {}), "pr_checks": getattr(self, "pr_checks", {}),
             "branch_protection": getattr(self, "branch_protection", {}),
             "check_runs": getattr(self, "check_runs", {}), "statuses": getattr(self, "statuses", {}),
             "fail_once": getattr(self, "fail_once", []), "compare_cap": getattr(self, "compare_cap", 10000),
             "compare_drop": getattr(self, "compare_drop", []), "listing_drop": getattr(self, "listing_drop", []),
             "fail_path": getattr(self, "fail_path", {}), "reply": getattr(self, "reply", {}),
             "issues": getattr(self, "issues", {})}))

    def dotfiles_runs(self, runs):
        self.runs = {"cartwmic/dotfiles|ci.yml": runs}
        self.write_fixture()

    def status(self, *args):
        rc, out, err = self.streams(*args)
        return rc, out + err

    def streams(self, *args):
        self.write_fixture()
        r = subprocess.run([sys.executable, str(getattr(self, "script_path", SCRIPT)), *args], capture_output=True, text=True, env=self.env, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def walked_commits(self):
        """The commits API calls the script made, as SHAs."""
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return [c.split("/commits/")[1].split()[0] for c in calls if "/commits/" in c]

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
        self.assertEqual(self.walked_commits(), [self.c3, self.m, self.c2, self.c3],
                         "the walk reads the tip, M and c2, then stops at the green; c1 is never read. The last read is the date of `since` (here c3), once, for the hidden-red floor")

    def test_among_one_commits_runs_the_highest_run_id_wins(self):
        # Review note dotfiles#323 round 3 n1(a). Listed oldest first so the script must order them itself: run 2 passed,
        # a later dispatch run 5 failed on the same commit, so the commit is red.
        self.dotfiles_runs([run(2, self.c3, "success", age=1), run(5, self.c3, "failure", age=5, event="workflow_dispatch")])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 5 failed on " + self.c3[:7], out)

    def test_the_walk_stops_at_the_first_pass_even_when_older_commits_have_verdicts(self):
        # Review note dotfiles#323 round 3 n1(b). c1 holds a verdict too, so the walk is not stopped by running out of
        # pending verdicts at the first pass. Only the early stop keeps c2 and c1 unread.
        self.dotfiles_runs([run(1, self.c1, "failure", age=1), run(2, self.m, "success", age=2)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.walked_commits(), [self.c3, self.m, self.c3], "the walk stops at the pass on M; c2 and c1 are never read. The last read is the date of `since` (here c3)")

    def test_no_run_on_main_means_no_commit_walk(self):
        self.dotfiles_runs([])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertEqual(self.walked_commits(), [self.c3], "no run to place, so the walk reads nothing; the one read is the date of `since` (here c3)")

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


class TipFlag(Fixture):
    """--tip: exit 0 only when main's tip itself has a conclusive pass. The default is unchanged."""

    def test_tip_tested_green_exits_0(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out = self.status("--tip", "dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("main tip is tested", out)

    def test_green_below_untested_commits_with_a_run_going_is_2_under_tip_and_0_without(self):
        self.dotfiles_runs([run(2, self.c3, status="queued", age=5), run(1, self.c2, "success", age=1)])
        rc, out = self.status("--tip", "dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("UNTESTED", out)
        self.assertIn("A run is going", out)
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)

    def test_green_below_untested_commits_with_no_run_is_2_and_says_to_start_one(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        rc, out = self.status("--tip", "dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("no run is going", out)

    def test_red_is_1(self):
        self.dotfiles_runs([run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1)])
        rc, out = self.status("--tip", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_tip_green_line_has_the_full_sha_and_the_default_does_not(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out = self.status("--tip", "dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"; tip {self.c3}", out)
        self.assertEqual(len(self.c3), 40)
        rc, out = self.status("dotfiles")
        self.assertNotIn(self.c3, out)

    def test_flag_may_follow_the_repo(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out = self.status("dotfiles", "--tip")
        self.assertEqual(rc, 0, out)

    def test_all_with_tip_is_2_when_one_repo_is_untested_at_the_tip(self):
        runs = {f"cartwmic/{r}|{w}": [run(1, self.c3, "success")]
                for r, w in (("dotfiles", "ci.yml"), ("loop-engine", "ci.yml"), ("agent-kit", "unit.yml"),
                             ("alert-steward", "image.yml"))}
        runs["cartwmic/dotfiles|ci.yml"] = [run(2, self.c3, status="queued", age=5), run(1, self.c2, "success", age=1)]
        runs["StoryCraftTW/storycraft|ci.yml"] = [run(1, self.c3, "success")]
        runs["cartwmic/retro|unit.yml"] = [run(1, self.c3, "success")]
        self.runs = runs
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        rc, out = self.status("--all")
        self.assertEqual(rc, 0, out)
        rc, out = self.status("--all", "--tip")
        self.assertEqual(rc, 2, out)
        self.assertIn("dotfiles: UNTESTED", out)
        self.assertIn("loop-engine: GREEN", out)

    def test_all_with_tip_red_beats_untested(self):
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c2, "success")],
                     "cartwmic/loop-engine|ci.yml": [run(1, self.c3, "failure")],
                     "cartwmic/agent-kit|unit.yml": [run(1, self.c3, "success")]}
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        rc, out = self.status("--all", "--tip")
        self.assertEqual(rc, 1, out)

    def test_journal_pass_behind_tip_with_live_lock_is_2_under_tip(self):
        self.journal.write_text(json.dumps({"tip": self.c2, "verdict": "pass"}) + "\n")
        self.lock.mkdir()
        (self.lock / "pid").write_text(str(os.getpid()))
        self.assertEqual(self.status("coordinator")[0], 0)
        rc, out = self.status("--tip", "coordinator")
        self.assertEqual(rc, 2, out)
        self.assertIn("A run is going", out)

    def test_journal_pass_at_tip_is_0_under_tip(self):
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        rc, out = self.status("--tip", "coordinator")
        self.assertEqual(rc, 0, out)


class CallerAndCache(Fixture):
    """Commit reads are cached for an hour, and nothing else is. Every gh call names its caller. Only the merge gate and
    the deploy check mark their reads urgent for the gh wrapper (GH_URGENT=1)."""

    def gh_calls(self):
        return [json.loads(line) for line in self.env_log.read_text().splitlines()] if self.env_log.exists() else []

    def test_commit_reads_are_cached_for_an_hour_and_run_list_and_branch_are_not(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        self.status("dotfiles")
        calls = self.log.read_text().splitlines()
        commit_reads = [c for c in calls if "/commits/" in c]
        self.assertEqual(len(commit_reads), 4, calls)   # c3, M, c2: the walk stops at the green; then the date of `since` (c3 again)
        for c in commit_reads:
            self.assertRegex(c, r"^api repos/cartwmic/dotfiles/commits/[0-9a-f]{40} --cache 1h$")
        others = [c for c in calls if "/commits/" not in c]
        self.assertTrue(any(c.startswith("run list ") for c in others), others)
        self.assertIn("api repos/cartwmic/dotfiles/branches/main", others)
        self.assertEqual([c for c in others if "--cache" in c], [], others)

    def test_every_gh_call_names_the_caller(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        self.status("dotfiles")
        calls = self.gh_calls()
        self.assertTrue(calls)
        self.assertEqual({c["caller"] for c in calls}, {"ci-main-status"})

    def test_plain_mode_is_not_urgent(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        self.status("dotfiles")
        self.assertEqual({c["urgent"] for c in self.gh_calls()}, {None})

    def test_merge_gate_and_tip_mark_every_call_urgent_run_list_included(self):
        for flag in ("--merge-gate", "--tip"):
            with self.subTest(flag=flag):
                self.dotfiles_runs([run(1, self.c3, "success")])
                self.env_log.unlink(missing_ok=True)
                self.status(flag, "dotfiles")
                calls = self.gh_calls()
                self.assertTrue(any(c["args"][0] == "run" for c in calls), "run list is one of the calls")
                self.assertEqual({c["urgent"] for c in calls}, {"1"})


class MergeGateFlag(Fixture):
    """--merge-gate: for `ci-main-status --merge-gate REPO && gh pr merge`. Only RED or unreadable blocks a merge (fab9b713)."""

    def test_untested_is_0_and_still_prints_the_untested_line(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        self.assertEqual(self.status("dotfiles")[0], 2)
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("UNTESTED", out)

    def test_no_conclusive_run_is_0(self):
        self.dotfiles_runs([])
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("UNTESTED", out)

    def test_red_is_1(self):
        self.dotfiles_runs([run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1)])
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_unreadable_is_1(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        self.failing = ["cartwmic/dotfiles"]
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)

    def test_green_is_0(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)

    def test_flag_may_follow_the_repo(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        self.assertEqual(self.status("dotfiles", "--merge-gate")[0], 0)

    def test_all_with_merge_gate_is_red_beats_untested_and_untested_is_0(self):
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c2, "success")],
                     "cartwmic/loop-engine|ci.yml": [run(1, self.c3, "success")],
                     "cartwmic/agent-kit|unit.yml": [run(1, self.c3, "success")]}
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        self.assertEqual(self.status("--all")[0], 2)
        self.assertEqual(self.status("--all", "--merge-gate")[0], 0)
        self.runs["cartwmic/loop-engine|ci.yml"] = [run(1, self.c3, "failure")]
        self.assertEqual(self.status("--all", "--merge-gate")[0], 1)

    def test_alert_steward_reads_its_image_workflow(self):
        self.runs = {"cartwmic/alert-steward|image.yml": []}
        rc, out = self.status("--merge-gate", "alert-steward")
        self.assertEqual(rc, 0, out)
        self.assertIn("alert-steward: UNTESTED", out)
        self.runs = {"cartwmic/alert-steward|image.yml": [run(1, self.c3, "failure")]}
        rc, out = self.status("--merge-gate", "alert-steward")
        self.assertEqual(rc, 1, out)
        self.assertIn("alert-steward: RED", out)

    def test_storycraft_reads_its_ci_workflow_on_main(self):
        self.runs = {"StoryCraftTW/storycraft|ci.yml": []}
        rc, out = self.status("--merge-gate", "storycraft")
        self.assertEqual(rc, 0, out)
        self.assertIn("storycraft: UNTESTED", out)
        self.runs = {"StoryCraftTW/storycraft|ci.yml": [run(1, self.c3, "failure")]}
        rc, out = self.status("--merge-gate", "storycraft")
        self.assertEqual(rc, 1, out)
        self.assertIn("storycraft: RED", out)

    def test_retro_reads_its_unit_workflow_on_main(self):
        self.runs = {"cartwmic/retro|unit.yml": []}
        rc, out = self.status("--merge-gate", "retro")
        self.assertEqual(rc, 0, out)
        self.assertIn("retro: UNTESTED", out)
        self.runs = {"cartwmic/retro|unit.yml": [run(1, self.c3, "failure")]}
        rc, out = self.status("--merge-gate", "retro")
        self.assertEqual(rc, 1, out)
        self.assertIn("retro: RED", out)

    def test_the_coordinators_full_name_is_its_table_entry(self):
        # `--merge-gate cartwmic/coordinator` once took the any-repo path and died on a private free-plan repo's
        # rulesets 403 (and has no required checks to read anyway); its OWNER/REPO now gives the journal verdict.
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        rc, out = self.status("--merge-gate", "coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("coordinator: GREEN", out)
        self.assertEqual(self.status("--merge-gate", "cartwmic/coordinator"), (rc, out))
        self.assertEqual(self.status("--merge-gate", "CartWmic/Coordinator"), (rc, out))
        self.assertEqual(self.status("--tip", "cartwmic/coordinator"), self.status("--tip", "coordinator"))

    def test_dotfiles_full_name_reads_the_whole_run_and_is_red_when_a_non_required_job_failed(self):
        # The real state of dotfiles main at 8a47043 (2026-11-21): the run failed on job mise-tests while the job
        # GitHub requires, "tests", passed. `--merge-gate cartwmic/dotfiles` once took the any-repo path, read only
        # "tests" and said GREEN; dotfiles#689 merged into that red main.
        self.dotfiles_runs([run(44873557728, self.c3, "failure")])
        self.jobs = {"44873557728": [{"name": "tests", "conclusion": "success", "steps": []},
                                     {"name": "mise-tests", "conclusion": "failure", "steps": []}]}
        # GitHub's own view, were the any-repo path taken: the one required check, "tests", passed on the tip.
        self.extra_repos = {"cartwmic/dotfiles": str(self.src)}
        self.protection = {"cartwmic/dotfiles": {"contexts": ["tests"], "checks": [{"context": "tests", "app_id": 1}]}}
        self.branch_protection = {"cartwmic/dotfiles": {"protected": True, "protection": {"enabled": True, "required_status_checks": {
            "checks": [{"context": "tests", "app_id": 1}], "contexts": ["tests"]}}}}
        self.branch_rules = {"cartwmic/dotfiles": []}
        self.check_runs = {"cartwmic/dotfiles": {self.c3: [{"id": 1, "name": "tests", "status": "completed", "conclusion": "success",
                                                            "started_at": "2026-11-21T06:00:00Z", "completed_at": "2026-11-21T06:01:00Z"}]}}
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("dotfiles: RED  run 44873557728 failed on " + self.c3[:7], out)
        self.assertEqual(self.status("--merge-gate", "cartwmic/dotfiles"), (rc, out))
        self.assertNotIn("required checks passed", out)

    def test_every_table_repos_full_name_is_its_table_entry(self):
        # --merge-gate, plain status, --tip and --pr give the same answer for the full name as for the short name,
        # for every table repo that has a GitHub workflow, in any letter case.
        wf = {"dotfiles": "ci.yml", "loop-engine": "ci.yml", "agent-kit": "unit.yml", "alert-steward": "image.yml",
              "storycraft": "ci.yml", "retro": "unit.yml"}
        for short, workflow in wf.items():
            github = REPOS_GITHUB[short]
            for verdict in ("success", "failure"):
                self.runs = {f"{github}|{workflow}": [run(1, self.c3, verdict)]}
                for args in ((["--merge-gate"], [], ["--tip"], ["--merge-gate", "--pr", "7"]) if short == "dotfiles" else (["--merge-gate"],)):   # the name lookup is the same for every mode: each mode once, on one repo
                    with self.subTest(repo=short, verdict=verdict, args=args):
                        want = self.status(*args, short)
                        self.assertEqual(self.status(*args, github), want)
                        self.assertEqual(self.status(*args, github.upper()), want)
                        self.assertIn("run 1 " + ("passed" if verdict == "success" else "failed"), want[1])

    def test_with_tip_is_a_usage_error(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out = self.status("--tip", "--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("usage", out)

    def test_plain_and_tip_keep_their_meaning(self):
        self.dotfiles_runs([run(1, self.c2, "success")])
        self.assertEqual(self.status("dotfiles")[0], 2)
        self.assertEqual(self.status("--tip", "dotfiles")[0], 2)


PINS_STEP_FULL = "Release pins: fail when a Loop Engine or agent-kit pin lags the latest release (playbook 7c57de5a)"
KIT_FILES = ["dot_local/share/agent-kit/package.json", "dot_local/share/agent-kit/package-lock.json"]
LE_FILES = ["dot_config/mise/config.toml", "dot_local/share/agent-harness/canonical/skills/loop-engine/SKILL.md"]
PR_HEAD = "81b63016555d0346d97e03934ced3abe0e7dc93f"


def steps(**conclusions):
    """The steps of one run, as ci_jobs splits them between the two jobs. Keys: pins, linux (the step after it), other (an earlier step)."""
    return [{"name": "Set up job", "conclusion": "success"},
            {"name": "Some other step", "conclusion": conclusions.get("other", "success")},
            {"name": PINS_STEP_FULL, "conclusion": conclusions.get("pins", "success")},
            {"name": "Linux checks: scripts/ci-linux.sh", "conclusion": conclusions.get("linux", "success")}]


def ci_jobs(step_list):
    """ci.yml's jobs for those steps: the release-pins step in its own job `release-pins`, every other step in `tests`."""
    def job(name, job_steps):
        failed = any(s["conclusion"] not in ("success", "skipped") for s in job_steps)
        return {"name": name, "conclusion": "failure" if failed else "success", "steps": job_steps}
    pins = [s for s in step_list if s["name"] == PINS_STEP_FULL]
    jobs = [job("tests", [s for s in step_list if s not in pins])]
    return jobs + [job("release-pins", pins)] if pins else jobs


NO_HEAD_RUN = run(3, "f" * 40, "success", event="pull_request", age=7)   # a run, but not of the PR head or of a commit with its tree


class PinFixException(Fixture):
    """--merge-gate dotfiles --pr N: the fix PR for a red release-pins step may merge into that red main (issue 429).

    The shape is the 2026-11-15 case: main's tip failed only the release-pins step, and the bump PR's own run passed it.
    """

    def setUp(self):
        super().setUp()
        git(self.src, "switch", "-q", "-c", "fix", self.c3)   # a real head, so the general rule the gate falls back to can read it
        (self.src / "pins.txt").write_text("pins\n")
        git(self.src, "add", "pins.txt")
        self.head = commit(self.src, "the pin fix")
        git(self.src, "switch", "-q", "main")
        self.set_world()

    def set_world(self, red_steps=None, red_extra_jobs=(), files=KIT_FILES, own_run=None, own_steps=None):
        """Run 2 on main's tip c3 is red; PR 7's head has its own pull_request run 3."""
        own_run = own_run or run(3, self.head, "success", event="pull_request", age=7, branch="fix")
        self.dotfiles_runs([run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1), own_run])
        red_steps = red_steps or steps(pins="failure", linux="skipped")
        self.jobs = {"2": [*ci_jobs(red_steps), {"name": "mise-tests", "conclusion": "success", "steps": []}, *red_extra_jobs],
                     str(own_run["databaseId"]): [*ci_jobs(own_steps or steps()), {"name": "mise-tests", "conclusion": "skipped", "steps": []}]}
        self.prs = {"7": {"files": [{"path": f} for f in files], "changedFiles": len(files), "headRefOid": self.head, "headRefName": "fix", **names(self.c3)}}

    def gate(self, *extra):
        self.write_fixture()
        r = subprocess.run([sys.executable, str(SCRIPT), "--merge-gate", "dotfiles", *extra], capture_output=True, text=True,
                           env=self.env, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def assert_stays_red(self, why, *args):
        """The same exit code and stdout as the gate without --pr; the reason goes to stderr."""
        rc0, out0, _ = self.gate()
        self.assertEqual(rc0, 1, out0)
        rc, out, err = self.gate(*args or ("--pr", "7"))
        self.assertEqual((rc, out), (rc0, out0), err)
        self.assertIn(why, err)

    def test_pass_case_only_pins_step_failed_pin_files_only_and_the_prs_own_run_passed_it(self):
        rc0, out0, _ = self.gate()
        self.assertEqual(rc0, 1, out0)
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(out.startswith(out0), "the RED lines print as before:\n" + out)
        self.assertIn("merge-gate: PR #7 is the pin fix for this red", out)
        self.assertIn("its own run 3 passed that step", out)
        self.assertEqual(err, "")
        calls = self.log.read_text().splitlines()
        self.assertIn("run view 2 -R cartwmic/dotfiles --attempt 1 --json jobs", calls, "the red run's own attempt is the one read")
        self.assertTrue(any(c.startswith("run list") and f"--commit {self.head}" in c and "--event pull_request" in c for c in calls))

    def test_pass_case_for_a_loop_engine_bump_the_mise_config_and_skills(self):
        self.set_world(files=LE_FILES)
        self.assertEqual(self.gate("--pr", "7")[0], 0)

    def test_pass_case_for_a_combined_bump_both_agent_kit_pins_and_the_loop_engine_files(self):
        """dotfiles#573: one PR carried the Loop Engine bump and the agent-kit pin, so neither blocked the other."""
        self.set_world(files=LE_FILES + KIT_FILES)
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("is the pin fix for this red", out)

    def test_no_pr_given_stays_red(self):
        rc, out, err = self.gate()
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)
        self.assertNotIn("merge-gate:", out)
        self.assertFalse([c for c in self.log.read_text().splitlines() if c.startswith("pr view")],
                         "without --pr nothing about a PR is read")

    def test_another_step_failed_in_the_red_run_stays_red(self):
        self.set_world(red_steps=steps(other="failure", pins="skipped"), own_run=NO_HEAD_RUN)
        self.assert_stays_red("failed on more than the release-pins step")

    def test_the_pins_step_and_another_step_failed_stays_red(self):
        self.set_world(red_steps=steps(pins="failure", linux="failure"), own_run=NO_HEAD_RUN)
        self.assert_stays_red("failed on more than the release-pins step")

    def test_another_job_failed_in_the_red_run_stays_red(self):
        self.set_world(red_extra_jobs=[{"name": "mise-tests", "conclusion": "failure", "steps": steps(linux="failure")}])
        self.assert_stays_red("failed on more than the release-pins step")

    def test_a_cancelled_job_in_the_red_run_stays_red(self):
        self.set_world(red_extra_jobs=[{"name": "mise-tests", "conclusion": "cancelled", "steps": []}])
        self.assert_stays_red("failed on more than the release-pins step")

    def test_an_extra_file_in_the_diff_stays_red(self):
        self.set_world(files=KIT_FILES + ["README.md"], own_run=NO_HEAD_RUN)
        self.assert_stays_red("its diff is not exactly the pin files: " + ", ".join(KIT_FILES + ["README.md"]))

    def test_a_file_list_shorter_than_the_changed_file_count_stays_red(self):
        self.set_world(own_run=NO_HEAD_RUN)
        self.prs["7"]["changedFiles"] = 150   # gh returned the pin files but not the other 148
        self.assert_stays_red("gh listed 2 of its 150 changed files")

    def test_half_the_agent_kit_pin_files_stays_red(self):
        self.set_world(files=KIT_FILES[:1], own_run=NO_HEAD_RUN)
        self.assert_stays_red("its diff is not exactly the pin files")

    def test_loop_engine_skills_without_the_mise_config_stays_red(self):
        self.set_world(files=LE_FILES[1:], own_run=NO_HEAD_RUN)
        self.assert_stays_red("its diff is not exactly the pin files")

    def test_a_loop_engine_diff_with_a_file_outside_the_skills_stays_red(self):
        self.set_world(files=LE_FILES + ["dot_local/bin/executable_pr-body-check"], own_run=NO_HEAD_RUN)
        self.assert_stays_red("its diff is not exactly the pin files")

    def test_the_prs_own_run_failing_the_pins_step_stays_red(self):
        self.set_world(own_run=run(3, self.head, "failure", event="pull_request", age=7), own_steps=steps(pins="failure", linux="skipped"))
        self.assert_stays_red("its own run 3 is failure, not success")

    def test_the_prs_own_run_passing_the_step_but_failing_the_run_stays_red(self):
        self.set_world(own_run=run(3, self.head, "failure", event="pull_request", age=7), own_steps=steps(linux="failure"))
        self.assert_stays_red("its own run 3 is failure, not success")

    def test_the_prs_own_run_not_finished_stays_red(self):
        self.set_world(own_run=run(3, self.head, status="in_progress", event="pull_request", age=7))
        self.assert_stays_red("its own run 3 is in_progress, not success")

    def test_the_prs_own_run_without_the_pins_step_stays_red(self):
        self.set_world(own_steps=[s for s in steps() if not s["name"].startswith("Release pins")])
        self.assert_stays_red("did not pass the release-pins step")

    def test_a_run_on_another_commit_is_not_the_prs_own_run(self):
        self.set_world(own_run=run(3, "f" * 40, "success", event="pull_request", age=7))
        self.assert_stays_red(f"no pull_request run of {self.head[:7]}")

    def test_a_push_run_on_the_pr_head_is_not_the_prs_own_run_for_the_pin_rule_but_the_general_rule_takes_it(self):
        self.set_world(own_run=run(3, self.head, "success", event="push", age=7))
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("passed as a red-main fix", out)           # the general rule: any run of the workflow on the head
        self.assertIn(f"no pull_request run of {self.head[:7]}", err)   # the pin rule said no first
        self.assertNotIn("pin fix", out)

    def test_every_pin_refusal_above_falls_through_to_the_general_rule_when_the_head_has_a_green_full_run(self):
        """The refusals above hold only because those worlds give the head no run (NO_HEAD_RUN). With a green run on the head that ran
        and passed what failed in main, the general rule passes the PR: the pin rule is an extra path, not a limit."""
        worlds = {"another step failed": dict(red_steps=steps(other="failure", pins="skipped")),
                  "pins step and another step failed": dict(red_steps=steps(pins="failure", linux="failure")),
                  "extra file in the diff": dict(files=KIT_FILES + ["README.md"]),
                  "half the agent-kit pin files": dict(files=KIT_FILES[:1]),
                  "loop-engine skills without the mise config": dict(files=LE_FILES[1:]),
                  "loop-engine diff with a file outside the skills": dict(files=LE_FILES + ["dot_local/bin/executable_pr-body-check"])}
        for label, kwargs in worlds.items():
            with self.subTest(label):
                self.set_world(**kwargs)
                rc, out, err = self.gate("--pr", "7")
                self.assertEqual(rc, 0, out + err)
                self.assertIn("passed as a red-main fix: its own full-suite run 3", out)
                self.assertNotIn("pin fix", out)

    def test_a_gh_failure_in_the_check_stays_red_with_the_same_stdout(self):
        self.set_world()
        self.failing_pr = ["cartwmic/dotfiles"]
        self.assert_stays_red("could not read it")

    def test_a_green_main_with_pr_prints_what_it_prints_without_it(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        self.assertEqual(self.gate("--pr", "7")[:2], self.gate()[:2])

    def test_pr_needs_a_number_merge_gate_and_dotfiles_alone(self):
        self.set_world()
        script = [sys.executable, str(SCRIPT)]
        for args in (["--merge-gate", "dotfiles", "--pr"], ["--merge-gate", "dotfiles", "--pr", "x"], ["--merge-gate", "dotfiles", "--pr", "0"],
                     ["dotfiles", "--pr", "7"], ["--tip", "--merge-gate", "dotfiles", "--pr", "7"], ["--merge-gate", "--all", "--pr", "7"],
                     ["--merge-gate", "no-such-repo", "--pr", "7"], ["--merge-gate", "dotfiles", "--pr", "7", "--pr", "8"],
                     ["--merge-gate", "dotfiles", "--pr=7"]):
            with self.subTest(args=args):
                r = subprocess.run(script + args, capture_output=True, text=True, env=self.env, timeout=120)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("usage", r.stderr)


UNIT_STEP = "unit tests (not on pull requests)"
FLOOR_STEP = "Run npx vitest run"


def red_unit_jobs():
    """main's red run: both jobs failed, the unit job in its full-suite step, node-floor in vitest."""
    return [{"databaseId": 11, "name": "unit", "conclusion": "failure", "steps": [
                {"name": "Set up job", "conclusion": "success"}, {"name": UNIT_STEP, "conclusion": "failure"},
                {"name": "Run npm run build", "conclusion": "skipped"}]},
            {"databaseId": 12, "name": "node-floor", "conclusion": "failure", "steps": [
                {"name": "Set up job", "conclusion": "success"}, {"name": FLOOR_STEP, "conclusion": "failure"}]}]


def full_suite_jobs(unit="success", floor="success", unit_step="success"):
    """A run that ran the whole suite: workflow_dispatch on a branch."""
    return [{"databaseId": 21, "name": "unit", "conclusion": unit, "steps": [
                {"name": "Set up job", "conclusion": "success"}, {"name": UNIT_STEP, "conclusion": unit_step}]},
            {"databaseId": 22, "name": "node-floor", "conclusion": floor,
             "steps": [] if floor == "skipped" else [{"name": FLOOR_STEP, "conclusion": "success" if floor == "success" else floor}]}]


def pull_request_jobs():
    """What unit.yml does on a pull_request: the job runs, its full-suite step and node-floor are skipped."""
    return full_suite_jobs(floor="skipped", unit_step="skipped")


class RedMainFix(Fixture):
    """--merge-gate REPO --pr N: a red main passes when PR N's own full-suite run on its head tree passed.

    The shape is agent-kit on 2026-11-16: unit.yml fails main in `unit` and `node-floor`; the PR's pull_request run skips both
    (so it proves nothing) and its workflow_dispatch run is the full suite.
    """
    WF = "cartwmic/agent-kit|unit.yml"

    def setUp(self):
        super().setUp()
        git(self.src, "switch", "-q", "-c", "fix", self.c3)
        (self.src / "f.txt").write_text("fix\n")
        git(self.src, "add", "f.txt")
        self.head = commit(self.src, "the fix")
        git(self.src, "switch", "-q", "main")
        self.world()

    def world(self, *head_runs, jobs_of=None):
        """Main's tip c3 is red (run 2); PR 7's branch `fix` is at self.head. head_runs are (run row, its jobs) pairs."""
        rows = [run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1)]
        self.jobs = {"2": red_unit_jobs()}
        for row, jobs in head_runs:
            rows.append(row)
            self.jobs[str(row["databaseId"])] = jobs
        self.runs = {self.WF: rows}
        self.prs = {"7": {"headRefOid": self.head, "headRefName": "fix", **names(self.c3)}}

    def dispatch(self, run_id, conclusion="success", sha=None, **jobs):
        return run(run_id, sha or self.head, conclusion, event="workflow_dispatch", age=run_id, branch="fix"), full_suite_jobs(**jobs)

    def pull_request(self, run_id, sha=None, conclusion="success"):
        return run(run_id, sha or self.head, conclusion, event="pull_request", age=run_id, branch="fix"), pull_request_jobs()

    def gate(self, *extra, repo="agent-kit"):
        self.write_fixture()
        r = subprocess.run([sys.executable, str(SCRIPT), "--merge-gate", repo, *extra], capture_output=True, text=True,
                           env=self.env, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def assert_stays_red(self, why):
        """The same exit code and stdout as the gate without --pr; the reason goes to stderr."""
        rc0, out0, _ = self.gate()
        self.assertEqual(rc0, 1, out0)
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual((rc, out), (rc0, out0), err)
        self.assertIn(why, err)

    def test_a_green_full_suite_run_on_the_head_passes_and_the_line_names_the_run(self):
        self.world(self.dispatch(4))
        rc0, out0, _ = self.gate()
        self.assertEqual(rc0, 1, out0)
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(out.startswith(out0), "the RED lines print as before:\n" + out)
        line = [l for l in out.splitlines() if "merge-gate:" in l]
        self.assertEqual(len(line), 1, out)
        for text in ("passed as a red-main fix", "run 4 (https://example.invalid/runs/4)", "run 2"):
            self.assertIn(text, line[0])
        self.assertEqual(err, "")

    def test_a_newer_pull_request_run_that_skipped_the_suite_does_not_hide_the_full_suite_run(self):
        self.world(self.dispatch(4), self.pull_request(5))
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("run 4 (", out)
        self.assertNotIn("run 5", out.split("merge-gate:")[1])

    def test_no_run_on_the_head_stays_red(self):
        self.world()
        self.assert_stays_red("no unit.yml run of")

    def test_only_a_pull_request_run_that_skipped_the_suite_stays_red(self):
        self.world(self.pull_request(5))
        self.assert_stays_red(f'run 5 skipped step "{UNIT_STEP}" in job unit')

    def test_a_job_that_passed_with_its_failing_step_skipped_stays_red(self):
        self.jobs = {}
        self.world(self.dispatch(4, unit_step="skipped"))
        self.jobs["2"] = red_unit_jobs()[:1]   # only `unit` failed in main
        self.assert_stays_red(f'run 4 skipped step "{UNIT_STEP}" in job unit')

    def test_a_failed_full_suite_run_stays_red(self):
        self.world(self.dispatch(4, "failure", unit="failure", unit_step="failure"))
        self.assert_stays_red("run 4 did not pass unit")

    def test_a_run_that_skipped_the_job_that_failed_in_main_stays_red(self):
        self.world(self.dispatch(4, floor="skipped"))
        self.assert_stays_red("run 4 skipped job node-floor")

    def test_a_failed_run_is_not_hidden_by_an_older_passing_one(self):
        self.world(self.dispatch(4), self.dispatch(6, "failure", floor="failure"))
        self.assert_stays_red("run 6 did not pass node-floor")

    def test_a_full_suite_run_still_going_stays_red(self):
        row, jobs = self.dispatch(4)
        row.update(status="in_progress", conclusion="")
        self.world((row, jobs))
        self.assert_stays_red("run 4 is in_progress, not success")

    def test_a_run_on_a_commit_with_another_tree_stays_red(self):
        git(self.src, "switch", "-q", "fix")
        (self.src / "f.txt").write_text("another\n")
        git(self.src, "add", "f.txt")
        other = commit(self.src, "later change")   # no --amend: the PR head stays self.head
        git(self.src, "switch", "-q", "main")
        self.world(self.dispatch(4, sha=other))
        self.assert_stays_red("no unit.yml run of")

    def test_a_run_on_another_commit_with_the_same_tree_counts(self):
        git(self.src, "switch", "-q", "fix")
        again = commit(self.src, "same tree, new commit")   # an empty commit: the tree is the head's
        git(self.src, "switch", "-q", "main")
        self.world(self.dispatch(4, sha=again))
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("same tree as its head", out)

    def test_the_coordinator_journal_is_not_a_github_run_and_stays_red(self):
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "fail"}) + "\n")
        rc0, out0, _ = self.gate(repo="coordinator")
        self.assertEqual(rc0, 1, out0)
        rc, out, err = self.gate("--pr", "7", repo="coordinator")
        self.assertEqual((rc, out), (rc0, out0), err)
        self.assertIn("the red verdict is not a GitHub run", err)

    def test_a_gh_failure_in_the_check_stays_red(self):
        self.world(self.dispatch(4))
        self.failing_pr = ["cartwmic/agent-kit"]
        self.write_fixture()
        self.assert_stays_red("could not read it")

    def test_a_green_main_with_pr_prints_what_it_prints_without_it(self):
        self.runs = {self.WF: [run(1, self.c3, "success")]}
        self.assertEqual(self.gate("--pr", "7")[:2], self.gate()[:2])

    def test_a_run_still_queued_with_no_steps_listed_is_passed_over_and_an_older_green_run_decides(self):
        """Documented behaviour (review note n1): nothing has run yet, so it says nothing; it does not refuse."""
        queued = run(6, self.head, status="queued", event="workflow_dispatch", age=6, branch="fix")
        self.world(self.dispatch(4), (queued, [{"databaseId": 31, "name": "unit", "conclusion": "", "steps": []}]))
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("run 4 (", out)

    def test_a_queued_run_with_no_steps_listed_and_no_older_green_run_stays_red(self):
        queued = run(6, self.head, status="queued", event="workflow_dispatch", age=6, branch="fix")
        self.world((queued, [{"databaseId": 31, "name": "unit", "conclusion": "", "steps": []}]))
        self.assert_stays_red("no full-suite run of its head tree: run 6 skipped step")

    def test_a_pull_request_run_still_going_whose_red_job_is_listed_as_skipped_is_passed_over(self):
        row, jobs = self.pull_request(5)
        row.update(status="in_progress", conclusion="")
        self.world(self.dispatch(4), (row, jobs))
        rc, out, err = self.gate("--pr", "7")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("run 4 (", out)

    def dotfiles_world(self, *head_runs, red_step="Linux checks: scripts/ci-linux.sh"):
        """Main's tip c3 is red in dotfiles' `tests` job on a step that is not the release-pins step (that step is its own job). PR 7's diff is not the pin files."""
        rows = [run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1)]
        self.jobs = {"2": ci_jobs([{"name": "Set up job", "conclusion": "success"}, {"name": red_step, "conclusion": "failure"}])}
        for row, conclusion in head_runs:
            rows.append(row)
            self.jobs[str(row["databaseId"])] = ci_jobs([{"name": "Set up job", "conclusion": "success"}, {"name": red_step, "conclusion": conclusion}])
        self.runs = {"cartwmic/dotfiles|ci.yml": rows}
        self.prs = {"7": {"files": [{"path": "dot_local/bin/executable_ci-main-status"}], "changedFiles": 1,
                          "headRefOid": self.head, "headRefName": "fix", **names(self.c3)}}

    def test_dotfiles_red_on_another_step_passes_on_a_green_full_head_run_of_the_same_tree(self):
        self.dotfiles_world((run(3, self.head, "success", event="pull_request", age=7, branch="fix"), "success"))
        rc0, out0, _ = self.gate(repo="dotfiles")
        self.assertEqual(rc0, 1, out0)
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(out.startswith(out0), out)
        self.assertIn("passed as a red-main fix: its own full-suite run 3", out)
        self.assertNotIn("pin fix", out)
        self.assertIn("failed on more than the release-pins step", err)   # the pin rule said no first

    def test_dotfiles_red_on_another_step_stays_red_with_no_head_run(self):
        self.dotfiles_world()
        rc0, out0, _ = self.gate(repo="dotfiles")
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual((rc, out), (rc0, out0), err)
        self.assertEqual(rc, 1)
        self.assertIn("failed on more than the release-pins step", err)
        self.assertIn("no ci.yml run of", err)

    def test_dotfiles_red_on_another_step_stays_red_when_the_head_run_failed_that_step(self):
        self.dotfiles_world((run(3, self.head, "failure", event="pull_request", age=7, branch="fix"), "failure"))
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("run 3 did not pass tests", err)

    # -- a red main takes only the change that names it (a flaky red must not let every green PR through)
    def flaky_red_with_unrelated_pr(self, repo="dotfiles"):
        """The real case: main's run failed in one test; PR 7 has nothing to do with it, and its own run is green and passed that test."""
        self.dotfiles_world((run(3, self.head, "success", event="pull_request", age=7, branch="fix"), "success"))
        self.prs["7"].update(names())   # it names no red

    def test_an_unrelated_green_pr_is_refused_on_a_red_main_with_a_sentence_that_says_what_it_lacks(self):
        self.flaky_red_with_unrelated_pr()
        rc0, out0, _ = self.gate(repo="dotfiles")
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual((rc, out), (rc0, out0), err)   # same stdout as without --pr
        self.assertEqual(rc, 1)
        self.assertIn("does not name this red", err)
        self.assertIn(f"put `Handles: {self.c3}` in the fix's commit message", err)
        self.assertIn("No flake ruling is recorded", err)
        self.assertNotIn("merge-gate:", out)

    def test_the_same_pr_passes_once_a_commit_message_names_the_red(self):
        self.flaky_red_with_unrelated_pr()
        self.prs["7"].update(names(self.c3))
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"it names {self.c3} with a Handles line", out)

    def test_a_revert_line_names_the_red_too(self):
        self.flaky_red_with_unrelated_pr()
        self.prs["7"]["commits"] = [{"messageHeadline": "Revert the cause", "messageBody": f"This reverts commit {self.c3}."}]
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"it names {self.c3}", out)

    def test_a_line_naming_another_commit_a_short_sha_or_a_free_text_mention_does_not_name_the_red(self):
        self.flaky_red_with_unrelated_pr()
        for text in (f"Handles: {self.c2}", f"Handles: {self.c3[:12]}", f"fixes the red on {self.c3}", f"see Handles: {self.c3}"):
            with self.subTest(text=text):
                self.prs["7"]["commits"] = [{"messageHeadline": "the fix", "messageBody": text}]
                rc, out, err = self.gate("--pr", "7", repo="dotfiles")
                self.assertEqual(rc, 1, out + err)
                self.assertIn("does not name this red", err)

    def test_a_pr_that_names_the_red_still_needs_its_own_run_to_have_passed_what_failed(self):
        self.dotfiles_world((run(3, self.head, "failure", event="pull_request", age=7, branch="fix"), "failure"))   # names(c3) is the fixture default
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("run 3 did not pass tests", err)

    def test_the_refusal_is_one_read_of_the_pr_before_its_own_run_is_read(self):
        self.flaky_red_with_unrelated_pr()
        self.gate("--pr", "7", repo="dotfiles")
        calls = self.log.read_text().splitlines()
        self.assertEqual(len([c for c in calls if c.startswith("pr view 7")]), 1, calls)   # the PR is read once, for its commits and description
        self.assertFalse([c for c in calls if c.startswith("run view 3")], calls)   # the PR's own run is never read: no tie, no need

    def storycraft_world(self):
        """storycraft squashes from the PR body: the line counts there, not in a commit."""
        rows = [run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1),
                run(3, self.head, "success", event="pull_request", age=7, branch="fix")]
        self.runs = {"StoryCraftTW/storycraft|ci.yml": rows}
        self.jobs = {"2": red_unit_jobs(), "3": full_suite_jobs()}
        self.prs = {"7": {"headRefOid": self.head, "headRefName": "fix"}}

    def test_storycraft_reads_the_line_in_the_pr_description_not_in_a_commit(self):
        self.storycraft_world()
        self.prs["7"].update(names(self.c3, in_body=True))
        rc, out, err = self.gate("--pr", "7", repo="storycraft")
        self.assertEqual(rc, 0, out + err)
        self.prs["7"].update(names(self.c3))   # the line in a commit only: the squash would not carry it
        rc, out, err = self.gate("--pr", "7", repo="storycraft")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"put `Handles: {self.c3}` in the PR description (storycraft squashes from the PR body)", err)

    def test_the_log_line_for_a_pass_on_a_red_main_names_the_rule(self):
        self.flaky_red_with_unrelated_pr()
        log = Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"])
        self.gate("--pr", "7", repo="dotfiles")   # refused
        self.prs["7"].update(names(self.c3))
        self.gate("--pr", "7", repo="dotfiles")   # passed by the named-red rule
        self.gate(repo="dotfiles")                # no --pr
        rows = [json.loads(l) for l in log.read_text().splitlines()]
        self.assertEqual([(r["pr"], r["exit"], r["passed_by"]) for r in rows], [(7, 1, None), (7, 0, ["named-red+own-run"]), (None, 1, None)])

    def test_the_log_line_for_a_refusal_says_which_rule_said_no_and_why(self):
        self.flaky_red_with_unrelated_pr()
        self.gate("--pr", "7", repo="dotfiles")   # refused: the pin rule (more than the pins step failed) and the named-red rule
        self.gate(repo="dotfiles")                # no --pr: refused for being red, no rule asked
        refused = [json.loads(l)["refused"] for l in Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).read_text().splitlines()]
        self.assertEqual([r["rule"] for r in refused[0]], ["pin-fix", "named-red+own-run"])
        self.assertIn("does not name this red", refused[0][1]["why"])
        self.assertIsNone(refused[1])

    def test_dotfiles_pin_fix_still_gets_the_pin_line_not_the_general_one(self):
        """The pin rule runs first: a pin fix is named as one even though its own run would also satisfy the general rule."""
        pins = PINS_STEP_FULL
        self.dotfiles_world((run(3, self.head, "success", event="pull_request", age=7, branch="fix"), "success"), red_step=pins)
        self.prs["7"]["files"] = [{"path": f} for f in KIT_FILES]
        self.prs["7"]["changedFiles"] = len(KIT_FILES)
        rc, out, err = self.gate("--pr", "7", repo="dotfiles")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("is the pin fix for this red", out)
        self.assertEqual(err, "")


NOT_ACQUIRED = "The job was not acquired by Runner of type hosted even after multiple attempts"
CAPACITY = "Due to capacity constraints, jobs targeting macOS arm64 runners may experience longer queue times."


def note(message, level="failure"):
    """One check-run annotation, with the fields GitHub returns."""
    return {"path": ".github", "start_line": 1, "end_line": 1, "annotation_level": level, "title": "", "message": message, "raw_details": ""}


NO_RUNNER_NOTES = [note(NOT_ACQUIRED), note(CAPACITY, "notice"), note(CAPACITY, "notice"), note(CAPACITY, "notice")]   # the real payload
TIMEOUT_NOTES = [note("The job running on runner GitHub Actions 7 has exceeded the maximum execution time of 30 minutes.")]
ORDINARY_CANCEL_NOTES = [note("The operation was canceled.")]
MISE_JOB = 22   # the macOS job's id in these fixtures


def jobs(mise, tests="success"):
    """The two jobs of a run. `mise` is the macOS job's conclusion; it never ran when it was cancelled for want of a runner."""
    return [{"databaseId": 11, "name": "tests", "conclusion": tests, "steps": [{"name": "Set up job", "conclusion": "success"}]},
            {"databaseId": MISE_JOB, "name": "mise-tests", "conclusion": mise, "steps": []}]


class NoRunnerCancel(Fixture):
    """A job cancelled because no runner picked it up is untested: never green, never red. Every other failure stays red."""

    def world(self, runs, jobs_of=None, notes=NO_RUNNER_NOTES, attempts=None):
        self.dotfiles_runs(runs)
        self.jobs = jobs_of if jobs_of is not None else {str(runs[0]["databaseId"]): jobs("cancelled")}
        self.annotations = {str(MISE_JOB): notes}
        self.attempts = attempts or {}

    def test_a_job_no_runner_picked_up_is_untested_with_its_name_and_reason(self):
        self.world([run(1, self.c3, "failure")])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("dotfiles: UNTESTED  run 1 on", out)
        self.assertIn("job mise-tests untested, no runner picked it up", out)
        self.assertIn("Not a pass", out)
        self.assertNotIn("RED", out)
        self.assertNotIn("GREEN", out)

    def test_it_is_untested_even_when_the_other_job_passed_and_an_older_commit_is_green(self):
        self.world([run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1)], {"2": jobs("cancelled")})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("UNTESTED  run 2 on", out)
        self.assertNotIn("GREEN", out)

    def test_merge_gate_lets_it_through_and_tip_does_not(self):
        self.world([run(1, self.c3, "failure")])
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("job mise-tests untested", out)
        rc, out = self.status("--tip", "dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("job mise-tests untested", out)

    def test_a_run_going_is_told_to_wait(self):
        self.world([run(1, self.c3, "failure"), run(2, self.c3, status="queued", age=5)], {"1": jobs("cancelled")})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("A run is going; wait for it.", out)

    def test_a_real_failure_next_to_the_no_runner_cancel_is_red(self):
        self.world([run(1, self.c3, "failure")], {"1": jobs("cancelled", tests="failure")})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)
        self.assertNotIn("UNTESTED", out)

    def test_a_failed_job_alone_is_red(self):
        self.world([run(1, self.c3, "failure")], {"1": jobs("success", tests="failure")})
        self.assertEqual(self.status("dotfiles")[0], 1)

    def test_a_timeout_after_the_job_started_is_red(self):
        self.world([run(1, self.c3, "failure")], notes=TIMEOUT_NOTES)
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_a_timed_out_job_is_red(self):
        self.world([run(1, self.c3, "failure")], {"1": jobs("timed_out")})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_an_ordinary_cancel_is_red(self):
        self.world([run(1, self.c3, "failure")], notes=ORDINARY_CANCEL_NOTES)
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_a_cancel_with_no_annotation_is_red(self):
        self.world([run(1, self.c3, "failure")], notes=[])
        self.assertEqual(self.status("dotfiles")[0], 1)

    def test_one_no_runner_cancel_does_not_excuse_another_cancel(self):
        both = jobs("cancelled")
        both[0]["conclusion"] = "cancelled"
        self.world([run(1, self.c3, "failure")], {"1": both})
        self.annotations["11"] = ORDINARY_CANCEL_NOTES
        self.assertEqual(self.status("dotfiles")[0], 1)

    def test_two_jobs_no_runner_picked_up_are_both_named(self):
        both = jobs("cancelled")
        both[0]["conclusion"] = "cancelled"
        self.world([run(1, self.c3, "failure")], {"1": both})
        self.annotations["11"] = NO_RUNNER_NOTES
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("jobs tests, mise-tests untested, no runner picked them up", out)

    def test_untested_above_a_red_commit_leaves_it_red(self):
        self.world([run(2, self.c3, "failure", age=5), run(1, self.c2, "failure", age=1)], {"2": jobs("cancelled"), "1": jobs("success", tests="failure")})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 1", out)

    def test_a_rerun_that_passed_is_green(self):
        self.world([run(1, self.c3, "success", attempt=2)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)

    def test_an_earlier_real_failure_is_not_hidden_by_a_no_runner_rerun(self):
        # Attempt 1 failed for real; the rerun never got a runner. The failure still stands.
        self.world([run(1, self.c3, "failure", attempt=2)],
                   {"1/2": jobs("cancelled"), "1/1": jobs("success", tests="failure")}, attempts={"1": {"1": {"conclusion": "failure"}}})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 1 attempt 1", out)

    def test_an_earlier_pass_is_not_hidden_by_a_no_runner_rerun(self):
        self.world([run(1, self.c3, "failure", attempt=2)], {"1/2": jobs("cancelled")}, attempts={"1": {"1": {"conclusion": "success"}}})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  run 1 attempt 1", out)

    def test_a_no_runner_attempt_with_a_rerun_going_is_not_red(self):
        self.world([run(1, self.c3, status="in_progress", attempt=2)], {"1/1": jobs("cancelled")}, attempts={"1": {"1": {"conclusion": "failure"}}})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 2, out)
        self.assertIn("UNTESTED  run 1 attempt 1", out)
        self.assertIn("A run is going; wait for it.", out)

    def test_a_real_pass_at_the_commit_wins_over_a_newer_no_runner_run(self):
        self.world([run(2, self.c3, "failure", age=5), run(1, self.c3, "success", age=1)], {"2": jobs("cancelled")})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  run 1", out)

    def test_a_real_failure_at_the_commit_wins_over_a_newer_no_runner_run(self):
        self.world([run(2, self.c3, "failure", age=5), run(1, self.c3, "failure", age=1)],
                   {"2": jobs("cancelled"), "1": jobs("success", tests="failure")})
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  run 1", out)

    def test_the_jobs_of_a_failed_run_below_the_first_pass_are_not_read(self):
        self.world([run(2, self.c3, "success", age=5), run(1, self.c2, "failure", age=1)])
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 0, out)
        # The walk itself never reads them. The hidden-red rule judges the failed run once, to tell a real red from a no-runner one.
        self.assertEqual([c for c in self.log.read_text().splitlines() if c.startswith("run view") or "/check-runs/" in c],
                         ["run view 1 -R cartwmic/dotfiles --attempt 1 --json jobs"])

    def test_an_annotation_that_cannot_be_read_is_an_error_not_untested(self):
        self.world([run(1, self.c3, "failure")])
        self.annotations = {}
        rc, out = self.status("dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR  cannot read state", out)
        self.assertNotIn("UNTESTED", out)


class ContainsGreen(Fixture):
    """--tip REPO --contains SHA: is there a main commit whose own run finished green and that contains SHA? 0 yes, 1 no, 2 wrong usage.

    First-parent history, oldest to newest: c1, c2, m (a merge of a side branch into c2), c3 (the tip)."""

    def ask(self, sha, repo="dotfiles"):
        return self.streams("--tip", repo, "--contains", sha)

    def test_a_cancelled_tip_with_a_later_green_commit_than_x_approves_that_commit_for_x(self):
        self.dotfiles_runs([run(3, self.c3, "cancelled", age=3), run(2, self.m, "success", age=2), run(1, self.c1, "success", age=1)])
        self.assertEqual(self.streams("--tip", "dotfiles")[0], 2)   # plain --tip: the tip has no finished run, so nothing is approved
        rc, out, _ = self.ask(self.c2)
        self.assertEqual(rc, 0, out)
        self.assertIn(f"commit {self.m}", out)
        self.assertIn(f"which contains {self.c2[:7]}", out)
        self.assertEqual(self.ask(self.c3)[0], 1)   # the cancelled tip itself is not covered by any green run

    def test_no_green_run_past_x_does_not_approve_x(self):
        self.dotfiles_runs([run(2, self.c3, "cancelled", age=2), run(1, self.c2, "success", age=1)])
        rc, out, _ = self.ask(self.m)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"newest green commit {self.c2[:7]}", out)
        self.assertIn(f"does not contain {self.m[:7]}", out)
        self.assertNotIn("commit " + self.c2, out)

    def test_the_green_commit_itself_counts_and_the_answer_names_its_full_sha(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out, _ = self.ask(self.c3[:10])
        self.assertEqual(rc, 0, out)
        self.assertIn(f"commit {self.c3}", out)

    def test_a_red_run_on_the_tip_does_not_hide_the_older_green_commit_that_contains_x(self):
        self.dotfiles_runs([run(2, self.c3, "failure", age=2), run(1, self.m, "success", age=1)])
        self.assertEqual(self.ask(self.c1)[0], 0)
        self.assertEqual(self.ask(self.c3)[0], 1)

    def test_no_green_run_at_all_is_no(self):
        self.dotfiles_runs([run(1, self.c3, "failure")])
        rc, out, _ = self.ask(self.c1)
        self.assertEqual(rc, 1, out)
        self.assertIn("no main commit has a finished green run", out)

    def test_wrong_usage_is_exit_2_and_reads_nothing(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        for args in (("--tip", "dotfiles", "--contains"), ("--tip", "dotfiles", "--contains", "xyz"), ("--tip", "dotfiles", "--contains", "abc12"),
                     ("--contains", self.c1, "dotfiles"), ("--merge-gate", "dotfiles", "--contains", self.c1),
                     ("--tip", "--all", "--contains", self.c1), ("--tip", "dotfiles", "loop-engine", "--contains", self.c1),
                     ("--tip", "nonesuch", "--contains", self.c1), ("--tip", "coordinator", "--contains", self.c1), ("--tip", "budget-steward", "--contains", self.c1),
                     ("--tip", "dotfiles", "--pr", "5", "--contains", self.c1), ("--tip", "dotfiles", "--contains", self.c1, "--owner-approved", "5"),
                     ("--tip", "dotfiles", "--contains", self.c1, "--owner-approved"), ("--tip", "dotfiles", f"--contains={self.c1}"),
                     ("--threads", "dotfiles", "5", "--contains", self.c1), ("--tip", "dotfiles", "--contains", self.c1, "--contains", self.c2),
                     ("--tip", "--tip", "dotfiles", "--contains", self.c1)):
            with self.subTest(args=args):
                rc, out, err = self.streams(*args)
                self.assertEqual(rc, 2, out + err)
                self.assertIn("usage: ci-main-status --tip REPO --contains SHA", err)
        self.assertFalse(self.log.exists(), "a wrong call makes no gh call")

    def test_a_refused_call_leaves_one_log_line_and_an_owner_ask_leaves_its_refusal(self):
        self.env["OWNER_APPROVED_LOG"] = str(Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).with_name("owner.jsonl"))
        self.assertEqual(self.streams("--tip", "dotfiles", "--contains", "xyz")[0], 2)
        self.assertEqual(self.streams("--tip", "dotfiles", "--contains", self.c1, "--owner-approved", "ask-17")[0], 2)
        self.assertEqual(self.streams("--tip", "budget-steward", "--contains", self.c1)[0], 2)   # a Gitea repo has no "github" entry
        rows = [json.loads(l) for l in Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).read_text().splitlines()]
        self.assertEqual([(r["action"], r["verdict"], r["exit"], r["reads"]) for r in rows], [("contains", "USAGE", 2, 0)] * 3)
        asked = [json.loads(l) for l in Path(self.env["OWNER_APPROVED_LOG"]).read_text().splitlines()]
        self.assertEqual([(a["ask"], a["outcome"]) for a in asked], [("ask-17", "refused")])
        self.assertFalse(self.log.exists(), "a wrong call makes no gh call")

    def test_a_rate_limit_on_the_compare_call_is_exit_1_even_when_a_sha_holds_404(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        self.fail_path = {"/compare/": "HTTP 403: API rate limit exceeded"}
        for sha in (self.c1, "abc404d"):
            with self.subTest(sha=sha):
                rc, out, _ = self.ask(sha)
                self.assertEqual(rc, 1, out)
                self.assertIn("rate limit", out)
                self.assertNotIn("is not a commit", out)

    def test_a_sha_that_is_no_commit_of_the_repo_is_exit_2(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        self.fail_path = {"/compare/": "HTTP 404: Not Found"}
        rc, out, _ = self.ask("deadbeef")
        self.assertEqual(rc, 2, out)
        self.assertIn("is not a commit of cartwmic/dotfiles", out)

    def test_an_unreadable_main_is_no_with_an_error_line(self):
        self.failing = ["cartwmic/dotfiles"]
        rc, out, _ = self.ask(self.c1)
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR  cannot read state", out)

    def test_every_call_appends_one_log_line_with_the_question_and_the_answer(self):
        self.dotfiles_runs([run(2, self.c3, "cancelled", age=2), run(1, self.m, "success", age=1)])
        self.ask(self.c2)
        self.ask(self.c3)
        yes, no = [json.loads(l) for l in Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).read_text().splitlines()]
        self.assertEqual((yes["action"], yes["contains"], yes["answer"], yes["exit"], yes["verdict"]), ("contains", self.c2, self.m, 0, "GREEN"))
        self.assertEqual((no["contains"], no["answer"], no["exit"], no["verdict"]), (self.c3, None, 1, "NO"))


def lag_issue(title, ago):
    """What `gh issue list --json title,createdAt,url` prints for the one open pin-lag issue, opened `ago` ago."""
    made = datetime.datetime.now(datetime.timezone.utc) - ago
    return json.dumps([{"title": title, "createdAt": made.strftime("%Y-%m-%dT%H:%M:%SZ"), "url": "https://github.com/cartwmic/dotfiles/issues/1019"}])


class PinLagLine(Fixture):
    """--merge-gate dotfiles prints one `pin-lag:` warning while the pin-lag issue is open, and never changes the exit code."""
    TITLE = "Pin lag: loop-engine 0.70.0 -> 0.72.2, agent-kit 0.85.0 -> 0.86.0"

    def lines(self, out):
        return [line for line in out.splitlines() if line.startswith("pin-lag:")]

    def test_an_open_issue_prints_one_line_naming_the_pins_the_age_and_the_issue_and_the_exit_stays_0(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        self.reply = {"issue list": lag_issue(self.TITLE, datetime.timedelta(hours=3, minutes=12, seconds=30))}
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.lines(out), ["pin-lag: loop-engine 0.70.0 -> 0.72.2, agent-kit 0.85.0 -> 0.86.0, open 3h 12m (https://github.com/cartwmic/dotfiles/issues/1019)"])
        self.assertIn("GREEN", out)
        self.assertIn("--label pin-lag --state open", self.log.read_text())
        (record,) = [json.loads(l) for l in Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).read_text().splitlines()]
        self.assertEqual(record["pin_lag"], self.lines(out)[0])   # the log keeps the warning after the terminal is gone

    def test_the_log_line_of_a_call_with_no_lag_carries_a_null_pin_lag(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        self.reply = {"issue list": "[]"}
        self.status("--merge-gate", "dotfiles")
        (record,) = [json.loads(l) for l in Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).read_text().splitlines()]
        self.assertIsNone(record["pin_lag"])
        self.assertIsNone(record["pin_lag_error"])

    def test_the_age_reads_in_minutes_hours_and_days(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        for ago, want in ((datetime.timedelta(minutes=45, seconds=20), "open 45m "), (datetime.timedelta(hours=26, minutes=5, seconds=20), "open 26h 5m "),
                          (datetime.timedelta(days=3, hours=4, seconds=20), "open 3d 4h ")):
            with self.subTest(ago=ago):
                self.reply = {"issue list": lag_issue(self.TITLE, ago)}
                self.assertIn(want, self.status("--merge-gate", "dotfiles")[1])

    def test_a_red_main_still_refuses_and_still_shows_the_lag(self):
        self.dotfiles_runs([run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1)])
        self.reply = {"issue list": lag_issue(self.TITLE, datetime.timedelta(hours=1, seconds=30))}
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)
        self.assertEqual(len(self.lines(out)), 1)

    def test_no_open_issue_prints_no_line(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        self.reply = {"issue list": "[]"}
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual((rc, self.lines(out)), (0, []))

    def test_an_unreadable_issue_list_prints_no_line_and_changes_no_exit_code(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        for broken in ({"fail_path": {"issue list": "HTTP 403: API rate limit exceeded"}}, {"reply": {"issue list": "not json"}},
                       {"reply": {"issue list": json.dumps([{"title": "Pin lag: x"}])}}, {"reply": {"issue list": json.dumps({"a": 1})}}):
            with self.subTest(broken=broken):
                self.fail_path, self.reply = broken.get("fail_path", {}), broken.get("reply", {})
                rc, out = self.status("--merge-gate", "dotfiles")
                self.assertEqual((rc, self.lines(out)), (0, []), out)
                self.assertIn("GREEN", out)
                last = json.loads(Path(self.env["CI_MAIN_STATUS_HIDDEN_LOG"]).read_text().splitlines()[-1])
                self.assertIsNone(last["pin_lag"])
                self.assertTrue(last["pin_lag_error"], "a failed read leaves its reason in the run log, unlike a read that found no issue")

    def test_only_the_merge_gate_of_dotfiles_reads_the_issue(self):
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c3, "success")], "cartwmic/loop-engine|ci.yml": [run(1, self.c3, "success")]}
        self.reply = {"issue list": lag_issue(self.TITLE, datetime.timedelta(hours=1))}
        for args in (("dotfiles",), ("--tip", "dotfiles"), ("--merge-gate", "loop-engine")):
            with self.subTest(args=args):
                rc, out = self.status(*args)
                self.assertEqual(self.lines(out), [], out)
        self.assertNotIn("issue list", self.log.read_text())
        self.assertEqual(len(self.lines(self.status("--all", "--merge-gate")[1])), 1)


class PinFixCopiesMatchTheirSources(unittest.TestCase):
    """The exception copies the pin step's name and the bump scripts' file lists; they must not drift apart."""

    @staticmethod
    def load(name, path):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader(name, str(REPO / path))
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_file_lists_and_step_name(self):
        gate = self.load("gate_under_test", "dot_local/bin/executable_ci-main-status")
        kit = self.load("agent_kit_bump_under_test", "dot_local/user_scripts/executable_agent_kit_bump.py")
        engine = self.load("loop_engine_bump_under_test", "dot_local/user_scripts/executable_loop_engine_bump.py")
        self.assertEqual(gate.AGENT_KIT_PIN_FILES, {f"{kit.KIT}/{name}" for name in kit.PIN_FILES})
        self.assertEqual(gate.LOOP_ENGINE_MISE_CONFIG, engine.MISE_CONFIG)
        self.assertEqual(gate.LOOP_ENGINE_SKILLS, engine.SKILLS + "/")
        # Each bump script also carries a copy of the other's files, for a combined bump PR.
        self.assertEqual(set(engine.AGENT_KIT_PINS), gate.AGENT_KIT_PIN_FILES)
        self.assertEqual(kit.LOOP_ENGINE_MISE_CONFIG, engine.MISE_CONFIG)
        self.assertEqual(kit.LOOP_ENGINE_SKILLS, engine.SKILLS)
        workflow = (REPO / ".github/workflows/ci.yml").read_text()
        self.assertIn(f"name: \"{gate.PINS_STEP} (playbook 7c57de5a)\"", workflow)
        self.assertIn("\n  release-pins:\n", workflow)   # the step lives in its own job, which `tests` does not wait for or depend on
        self.assertNotIn(gate.PINS_STEP, workflow.split("\n  release-pins:\n")[0].split("\n  tests:\n")[1])


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
        self.assertIn("amazon-itemizer: n/a", out)
        self.assertIn("alert-steward: UNTESTED", out)
        self.assertIn("storycraft: UNTESTED", out)
        self.assertIn("retro: UNTESTED", out)

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

    def test_amazon_itemizer_merge_gate_is_0_and_makes_no_gh_call(self):
        rc, out = self.status("--merge-gate", "amazon-itemizer")
        self.assertEqual(rc, 0, out)
        self.assertIn("amazon-itemizer: n/a", out)
        calls = self.log.read_text() if self.log.exists() else ""
        self.assertEqual(calls, "", "amazon-itemizer must not call gh")

    def test_missing_gh_is_one_error_line_per_repo_and_all_keeps_going(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.env["PATH"] = str(empty)
        rc, out = self.status("--all")
        self.assertEqual(rc, 1, out)
        for name in ("dotfiles", "loop-engine", "agent-kit", "coordinator", "alert-steward", "storycraft", "retro"):
            self.assertIn(f"{name}: ERROR  cannot read state: gh could not start", out)
        self.assertIn("homelab: n/a", out)
        self.assertIn("amazon-itemizer: n/a", out)
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

    def test_malformed_journal_line_before_the_last_good_one_exits_1(self):
        # A bad line in the middle is not a torn tail: it is still unreadable state, as it was before the tail rule.
        self.journal.write_text(json.dumps({"tip": self.c2, "verdict": "pass"}) + "\n" + "{not json\n"
                                + json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n")
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 1, out)
        self.assertIn("line 2 is not JSON", out)

    def test_a_nul_tail_is_skipped_and_the_last_good_line_decides(self):
        self.journal.write_text(json.dumps({"tip": self.c2, "verdict": "fail"}) + "\n"
                                + json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n" + "\x00" * 409)
        rc, out, err = self.streams("coordinator")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("GREEN  journal line 2 passed on " + self.c3[:7], out)
        self.assertIn(f"skipped a torn tail of 409 bytes in {self.journal}; using the last complete line", err)
        self.assertNotIn("Traceback", err)

    def test_a_half_line_after_a_good_line_is_skipped(self):
        half = '{"tip": "abc", "verd'   # cut off before its newline landed
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n" + half)
        rc, out, err = self.streams("coordinator")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("GREEN  journal line 1 passed on " + self.c3[:7], out)
        self.assertIn(f"skipped a torn tail of {len(half)} bytes in {self.journal}; using the last complete line", err)

    def test_a_file_with_no_complete_line_has_no_result(self):
        self.journal.write_text("\x00" * 409)
        rc, out, err = self.streams("coordinator")
        self.assertEqual(rc, 2, out + err)
        self.assertIn("no conclusive journal line on main", out)
        self.assertIn(f"skipped a torn tail of 409 bytes in {self.journal}; no complete line is left", err)

    def test_blank_lines_after_the_last_line_are_not_a_torn_tail(self):
        self.journal.write_text(json.dumps({"tip": self.c3, "verdict": "pass"}) + "\n\n  \n")
        rc, out, err = self.streams("coordinator")
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn("torn tail", err)

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


class JournalTreeAndFlake(Fixture):
    """Journal lines with "tree", and the flake verdict. c4 and c5 share a tree; c6 has another."""

    def setUp(self):
        super().setUp()
        (self.src / "f").write_text("one")
        git(self.src, "add", "f")
        self.c4 = commit(self.src, "c4 adds f")
        self.c5 = commit(self.src, "c5 same tree as c4")
        (self.src / "g").write_text("two")
        git(self.src, "add", "g")
        self.c6 = commit(self.src, "c6 adds g")
        self.tree4 = git(self.src, "rev-parse", self.c4 + "^{tree}")
        self.tree6 = git(self.src, "rev-parse", self.c6 + "^{tree}")
        self.assertEqual(self.tree4, git(self.src, "rev-parse", self.c5 + "^{tree}"))
        self.assertNotEqual(self.tree4, self.tree6)

    def rows(self, *rows):
        self.journal.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_a_pass_on_the_tip_matches_by_tip(self):
        self.rows({"tip": self.c6, "tree": self.tree6, "verdict": "pass"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  journal line 1 passed on " + self.c6[:7] + "; main tip is tested", out)
        self.assertNotIn("same tree", out)

    def test_a_pass_with_the_same_tree_as_the_tip_tests_the_tip_and_names_the_line_and_tip(self):
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"})
        self.git_move_main_to(self.c5)
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"GREEN  journal line 1 (tip {self.c4[:7]}, same tree) passed on {self.c5[:7]}; main tip is tested", out)

    def test_tip_flag_on_a_tree_match_ends_with_the_full_main_tip(self):
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"})
        self.git_move_main_to(self.c5)
        rc, out = self.status("--tip", "coordinator")
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.strip().endswith("; tip " + self.c5), out)

    def test_the_walk_back_takes_a_tree_match_on_an_earlier_commit(self):
        # The tip c6 has no pass. Walking back, c5 has the tree of the passed c4, so the walk stops there.
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)
        self.assertIn("1 main commit(s) after journal line 1 (tip " + self.c4[:7] + ", same tree) (" + self.c5[:7] + ")", out)
        self.assertEqual(self.walked_commits(), [self.c6, self.c5])

    def test_a_different_tree_is_not_tested(self):
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"})
        rc, out = self.status("--tip", "coordinator")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("GREEN", out)

    def test_an_old_line_without_a_tree_matches_by_tip_only(self):
        self.rows({"tip": self.c4, "verdict": "pass"})
        self.git_move_main_to(self.c5)
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("GREEN", out)
        self.rows({"tip": self.c5, "verdict": "pass"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  journal line 1 passed on " + self.c5[:7], out)

    def test_a_flake_with_nothing_after_it_is_untested_in_plain_mode_and_names_the_issue(self):
        self.rows({"tip": self.c6, "tree": self.tree6, "verdict": "flake", "issue": "cartwmic/dotfiles#999", "ruled": "t"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("RED", out)
        self.assertNotIn("GREEN", out)
        self.assertIn("cartwmic/dotfiles#999", out)
        self.assertIn("Start a run", out)

    def test_a_flake_followed_by_a_pass_on_the_tip_is_green(self):
        self.rows({"tip": self.c6, "tree": self.tree6, "verdict": "flake", "issue": "cartwmic/dotfiles#999"},
                  {"tip": self.c6, "tree": self.tree6, "verdict": "pass"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  journal line 2 passed on " + self.c6[:7], out)

    def test_a_flake_never_makes_the_tip_green_under_tip(self):
        self.rows({"tip": self.c6, "tree": self.tree6, "verdict": "flake", "issue": "cartwmic/dotfiles#999"})
        rc, out = self.status("--tip", "coordinator")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("GREEN", out)

    def test_a_flake_above_an_older_pass_is_still_untested(self):
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"},
                  {"tip": self.c6, "tree": self.tree6, "verdict": "flake", "issue": "cartwmic/dotfiles#999"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)
        self.assertIn("cartwmic/dotfiles#999", out)

    def test_a_flake_ruling_cannot_make_the_tip_tested_through_an_older_same_tree_pass(self):
        # Review dotfiles#342 b1: c4 pass, c5 (same tree) fail, c5 flake. Main at c5. Without the flake line this is RED.
        self.git_move_main_to(self.c5)
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"},
                  {"tip": self.c5, "tree": self.tree4, "verdict": "fail"})
        rc, out = self.status("--tip", "coordinator")
        self.assertEqual(rc, 1, out)
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"},
                  {"tip": self.c5, "tree": self.tree4, "verdict": "fail"},
                  {"tip": self.c5, "tree": self.tree4, "verdict": "flake", "issue": "cartwmic/dotfiles#999"})
        rc, out = self.status("--tip", "coordinator")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("GREEN", out)
        self.assertIn("cartwmic/dotfiles#999", out)

    def test_a_same_tree_pass_after_a_flake_or_fail_tests_the_commit(self):
        self.git_move_main_to(self.c5)
        for own in ("fail", "flake"):
            self.rows({"tip": self.c5, "tree": self.tree4, "verdict": own, "issue": "cartwmic/dotfiles#999"},
                      {"tip": self.c4, "tree": self.tree4, "verdict": "pass"})
            rc, out = self.status("--tip", "coordinator")
            self.assertEqual(rc, 0, own + out)

    def test_a_commits_own_fail_beats_an_earlier_same_tree_pass(self):
        # Review dotfiles#342 n1.
        self.git_move_main_to(self.c5)
        self.rows({"tip": self.c4, "tree": self.tree4, "verdict": "pass"},
                  {"tip": self.c5, "tree": self.tree4, "verdict": "fail"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  journal line 2 failed on " + self.c5[:7], out)

    def test_a_flake_does_not_hide_a_red_below_it(self):
        self.rows({"tip": self.c5, "tree": self.tree4, "verdict": "fail"},
                  {"tip": self.c6, "tree": self.tree6, "verdict": "flake", "issue": "cartwmic/dotfiles#999"})
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_a_flake_with_a_run_going_says_wait(self):
        self.rows({"tip": self.c6, "tree": self.tree6, "verdict": "flake", "issue": "cartwmic/dotfiles#999"})
        self.lock.mkdir()
        (self.lock / "pid").write_text(str(os.getpid()))
        rc, out = self.status("coordinator")
        self.assertEqual(rc, 2, out)
        self.assertIn("A run is going; wait for it.", out)

    def git_move_main_to(self, sha):
        git(self.src, "reset", "-q", "--hard", sha)


class AnyRepoFixture(Fixture):
    """The world of an OWNER/REPO outside the table: a repo with protection requiring tests and lint, and the helpers that set its check runs."""

    def setUp(self):
        super().setUp()
        self.any_repo = "example-org/example-repo"
        self.extra_repos = {self.any_repo: str(self.src)}
        self.protection = {self.any_repo: {"contexts": ["tests", "lint"],
                                           "checks": [{"context": "tests", "app_id": 1}, {"context": "lint", "app_id": 1}]}}
        self.branch_rules = {self.any_repo: []}   # rules/branches/main: no active ruleset applies
        self.branch_protection = {self.any_repo: {"protected": True,
                                                  "protection": {"enabled": True, "required_status_checks": {
                                                      "checks": [{"context": "tests", "app_id": 1},
                                                                 {"context": "lint", "app_id": 1}],
                                                      "contexts": ["tests", "lint"]}}}}
        self.rulesets = {}     # the old rulesets-list endpoints, which the pre-union script read instead
        self.check_runs = {}   # {sha: [check run rows, newest first as GitHub lists them]}
        self.statuses = {}     # {sha: [commit status rows]}
        self.pr_checks = {}    # {repo: {pr: [gh pr checks --required rows]}}

    def check_row(self, name, conclusion="success", status="completed", rid=1,
                  completed="2026-11-18T10:01:00Z", started="2026-11-18T10:00:00Z"):
        return {"id": rid, "name": name, "status": status,
                "conclusion": conclusion if status == "completed" else None,
                "started_at": started, "completed_at": completed if status == "completed" else None}

    def set_tip_checks(self, *rows):
        self.check_runs = {self.any_repo: {self.c3: list(rows) or [self.check_row("tests"), self.check_row("lint", rid=2)]}}


class AnyRepo(AnyRepoFixture):
    """A GitHub repo not in the table, named OWNER/REPO: the checks GitHub requires on the default branch — branch
    protection union the branch's active rulesets — and, with --pr, what GitHub computes for the PR, cross-checked
    against the base branch. The tip (or PR head) must pass them; anything unreadable fails closed."""

    def test_green_exits_0(self):
        self.set_tip_checks()
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{self.any_repo}: GREEN  all 2 required checks passed on main tip {self.c3[:7]}", out)
        self.assertIn("lint, tests", out)

    def test_red_exits_1_and_names_the_check(self):
        self.set_tip_checks(self.check_row("tests"), self.check_row("lint", "failure", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"{self.any_repo}: RED  required check(s) failed on main tip {self.c3[:7]}: lint", out)

    def test_a_pending_required_check_fails_the_merge_gate(self):
        self.set_tip_checks(self.check_row("tests"), self.check_row("lint", status="in_progress", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 2, out)
        self.assertIn(f"{self.any_repo}: UNTESTED  required check(s) pending on main tip {self.c3[:7]}: lint (in_progress)", out)
        self.assertIn("Not a pass.", out)
        rc, out = self.status("--merge-gate", self.any_repo)
        self.assertEqual(rc, 2, out + " (a pending required check never passes the gate)")
        self.assertIn("Not a pass.", out)

    def test_protection_plus_a_ruleset_is_the_union(self):
        # Protection requires only "tests" (passing); an active ruleset adds "lint", which failed. The union is red;
        # a script that reads protection alone prints GREEN here.
        self.protection = {self.any_repo: {"contexts": ["tests"], "checks": [{"context": "tests", "app_id": 1}]}}
        self.branch_protection = {self.any_repo: {"protected": True,
                                                  "protection": {"enabled": True, "required_status_checks": {
                                                      "checks": [{"context": "tests", "app_id": 1}],
                                                      "contexts": ["tests"]}}}}
        self.branch_rules = {self.any_repo: [{"type": "required_status_checks",
                                              "parameters": {"required_status_checks": [{"context": "lint"}]}}]}
        self.set_tip_checks(self.check_row("tests"), self.check_row("lint", "failure", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  required check(s) failed on main tip " + self.c3[:7] + ": lint", out)

    def test_a_non_admin_sees_protection_through_the_branch(self):
        # A non-admin gets 404 from the /protection endpoints; the branch response still shows the protection and
        # its required check, which failed. The old /protection read printed an error or a wrong GREEN here.
        self.protection = None
        self.branch_protection = {self.any_repo: {"protected": True,
                                                  "protection": {"enabled": True, "required_status_checks": {
                                                      "checks": [{"context": "tests", "app_id": 1}],
                                                      "contexts": ["tests"]}}}}
        self.set_tip_checks(self.check_row("tests", "failure"))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  required check(s) failed on main tip " + self.c3[:7] + ": tests", out)

    def test_protection_only_works_for_a_non_admin(self):
        self.protection = None
        self.branch_protection = {self.any_repo: {"protected": True,
                                                  "protection": {"enabled": True, "required_status_checks": {
                                                      "checks": [{"context": "tests", "app_id": 1},
                                                                 {"context": "lint", "app_id": 1}],
                                                      "contexts": ["tests", "lint"]}}}}
        self.set_tip_checks()
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 0, out)
        self.assertIn(f"GREEN  all 2 required checks passed on main tip {self.c3[:7]}", out)

    def test_protected_with_a_malformed_protection_fails_closed(self):
        # protection present but enabled missing: a missing field is malformed, never a default -- ERROR, never
        # C = {} and never the checks read anyway.
        self.protection = None
        self.branch_protection = {self.any_repo: {"protected": True, "protection": {}}}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("protection.enabled is missing or not a bool", out)
        self.assertIn("failing closed", out)

    def test_an_older_success_and_a_newer_queued_run_is_not_green(self):
        self.set_tip_checks(self.check_row("tests", rid=100, completed="2026-11-18T10:05:00Z"),
                            self.check_row("tests", status="queued", rid=200, started=None),
                            self.check_row("lint", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 2, out + " (a newer queued run must not read green)")
        self.assertIn("tests (queued)", out)

    def test_an_older_success_and_a_newer_in_progress_run_is_not_green(self):
        self.set_tip_checks(self.check_row("tests", rid=100, completed="2026-11-18T10:05:00Z"),
                            self.check_row("tests", status="in_progress", rid=200, started="2026-11-18T10:01:00Z"),
                            self.check_row("lint", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 2, out + " (a newer in-progress run must not read green)")
        self.assertIn("tests (in_progress)", out)

    def test_a_newer_success_over_an_older_failure_is_green(self):
        # The newer run was created later but finished sooner; the id, not the timestamp, says it is newest.
        self.set_tip_checks(self.check_row("tests", rid=20, completed="2026-11-18T10:04:00Z",
                                           started="2026-11-18T10:03:00Z"),
                            self.check_row("tests", "failure", rid=10, completed="2026-11-18T10:05:00Z",
                                           started="2026-11-18T10:00:00Z"),
                            self.check_row("lint", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 0, out + " (the newest run, by id, passed)")
        self.assertIn(f"GREEN  all 2 required checks passed on main tip {self.c3[:7]}", out)

    def test_a_ruleset_for_another_branch_is_not_required(self):
        # The old rulesets-list read would require "extra" here; rules/branches/main answers [] because the
        # ruleset applies to another branch, so nothing is required and the read fails closed.
        self.protection = None
        self.branch_protection = {self.any_repo: {"protected": False}}
        self.rulesets = {self.any_repo: [{"id": 11, "enforcement": "active",
                                          "rules": [{"type": "required_status_checks",
                                                     "parameters": {"required_status_checks": [{"context": "extra"}]}}]}]}
        self.set_tip_checks(self.check_row("tests"), self.check_row("extra", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("no required checks readable on main", out)
        self.assertIn("failing closed", out)
        self.assertNotIn("extra", out)

    def test_a_ruleset_error_fails_closed(self):
        self.branch_rules = {self.any_repo: False}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("HTTP 403", out)

    def test_two_runs_with_one_name_the_newest_decides(self):
        # GitHub lists the newest run first; the older success below it must not win.
        self.set_tip_checks(self.check_row("tests", "failure", rid=200, completed="2026-11-18T10:05:00Z"),
                            self.check_row("tests", "success", rid=100, completed="2026-11-18T10:01:00Z"),
                            self.check_row("lint", rid=2))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  required check(s) failed on main tip " + self.c3[:7] + ": tests", out)

    def test_pagination_reads_past_page_one(self):
        rows = [self.check_row(f"job{i}", rid=1000 + i) for i in range(100)]
        rows += [self.check_row("tests", rid=2000), self.check_row("lint", rid=2001)]
        self.check_runs = {self.any_repo: {self.c3: rows}}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 0, out)
        self.assertIn(f"GREEN  all 2 required checks passed on main tip {self.c3[:7]}", out)

    def test_the_calls_page_and_filter(self):
        self.set_tip_checks()
        self.status(self.any_repo)
        calls = self.log.read_text().splitlines()
        rules = [c for c in calls if "rules/branches/main?per_page=100" in c]
        self.assertEqual(len(rules), 1, calls)
        self.assertIn("--paginate", rules[0])
        runs = [c for c in calls if "/check-runs" in c]
        self.assertEqual(len(runs), 1, calls)
        self.assertIn("filter=latest", runs[0])
        self.assertIn("per_page=100", runs[0])

    def test_a_403_rate_limit_fails_closed_loudly(self):
        self.branch_protection = {self.any_repo: "HTTP 403: API rate limit exceeded"}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("rate limit", out)
        self.assertNotIn("no required checks readable", out)

    def test_no_permission_fails_closed(self):
        self.branch_protection = {self.any_repo: "HTTP 403: Resource not accessible by integration"}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("HTTP 403", out)

    def test_no_protection_fails_closed(self):
        self.protection = None
        self.branch_protection = {self.any_repo: {"protected": False}}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"{self.any_repo}: ERROR  cannot read state: no required checks readable on main", out)
        self.assertIn("failing closed", out)

    def test_protection_with_no_required_checks_fails_closed(self):
        # Enabled, but neither source requires anything: nothing could be proved, so ERROR (row 9), never GREEN.
        self.branch_protection = {self.any_repo: {"protected": True,
                                                  "protection": {"enabled": True,
                                                                 "required_status_checks": {"contexts": [], "checks": []}}}}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("protected, but no required checks in protection or rulesets", out)
        self.assertIn("nothing for this gate to verify", out)

    def test_pr_checks_the_pr_head_commit(self):
        self.prs = {"7": {"headRefOid": self.c2, "headRefName": "fix", "baseRefName": "main"}}
        self.pr_checks = {self.any_repo: {"7": [{"name": "tests"}, {"name": "lint"}]}}
        self.check_runs = {self.any_repo: {self.c2: [self.check_row("tests"), self.check_row("lint", rid=2)]}}
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{self.any_repo}: GREEN  all 2 required checks passed on PR #7 head {self.c2[:7]}", out)

    def test_pr_red_exits_1(self):
        self.prs = {"7": {"headRefOid": self.c2, "headRefName": "fix", "baseRefName": "main"}}
        self.pr_checks = {self.any_repo: {"7": [{"name": "tests"}, {"name": "lint"}]}}
        self.check_runs = {self.any_repo: {self.c2: [self.check_row("tests", "failure"), self.check_row("lint", rid=2)]}}
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"RED  required check(s) failed on PR #7 head {self.c2[:7]}: tests", out)

    def test_a_pr_required_check_missing_from_the_rollup_is_still_verified(self):
        # The gate verifies the computed base set on the PR head, never the rollup: lint is required on main but
        # never started on the PR, so gh pr checks --required does not list it -- and the gate is not GREEN.
        self.prs = {"7": {"headRefOid": self.c2, "headRefName": "fix", "baseRefName": "main"}}
        self.pr_checks = {self.any_repo: {"7": [{"name": "tests"}]}}
        self.check_runs = {self.any_repo: {self.c2: [self.check_row("tests")]}}
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "7")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("GREEN", out)
        self.assertIn("lint (not reported)", out)

    def test_a_pr_rollup_name_the_base_set_lacks_fails_closed(self):
        # gh pr checks --required lists "extra", which the base branch's computed set does not: an under-report.
        self.prs = {"7": {"headRefOid": self.c2, "headRefName": "fix", "baseRefName": "main"}}
        self.pr_checks = {self.any_repo: {"7": [{"name": "tests"}, {"name": "extra"}]}}
        self.check_runs = {self.any_repo: {self.c2: [self.check_row("tests"), self.check_row("extra", rid=2)]}}
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertIn("extra", out)
        self.assertIn("failing closed", out)

    def test_pr_without_merge_gate_is_a_usage_error(self):
        self.set_tip_checks()
        rc, out = self.status(self.any_repo, "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("usage:", out)

    def test_a_required_check_nothing_reports_is_pending(self):
        self.set_tip_checks(self.check_row("tests"))
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 2, out)
        self.assertIn("lint (not reported)", out)

    def test_a_missing_check_falls_back_to_the_commit_status(self):
        self.set_tip_checks(self.check_row("tests"))
        self.statuses = {self.any_repo: {self.c3: [{"context": "lint", "state": "success"}]}}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)

    def test_a_failing_status_is_red(self):
        self.set_tip_checks(self.check_row("tests"))
        self.statuses = {self.any_repo: {self.c3: [{"context": "lint", "state": "failure"}]}}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_a_failing_status_behind_a_passing_check_run_is_red(self):
        self.set_tip_checks(self.check_row("tests"), self.check_row("lint", rid=2))
        self.statuses = {self.any_repo: {self.c3: [{"context": "lint", "state": "failure"}]}}
        rc, out = self.status(self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  required check(s) failed on main tip " + self.c3[:7] + ": lint", out)

    def test_skipped_and_neutral_required_checks_pass_as_github_passes_them(self):
        # GitHub's merge box accepts a required check whose run concluded success, skipped or neutral.
        for conclusion in ("skipped", "neutral"):
            with self.subTest(conclusion):
                self.set_tip_checks(self.check_row("tests"), self.check_row("lint", conclusion, rid=2))
                rc, out = self.status(self.any_repo)
                self.assertEqual(rc, 0, out)
                self.assertIn("GREEN  all 2 required checks passed on main tip " + self.c3[:7], out)

    def test_other_completed_conclusions_fail_a_required_check(self):
        for conclusion in ("failure", "cancelled", "timed_out", "action_required", "stale", "startup_failure"):
            with self.subTest(conclusion):
                self.set_tip_checks(self.check_row("tests"), self.check_row("lint", conclusion, rid=2))
                rc, out = self.status(self.any_repo)
                self.assertEqual(rc, 1, out)
                self.assertIn("RED  required check(s) failed on main tip " + self.c3[:7] + ": lint", out)

    def test_tip_flag_is_a_usage_error(self):
        self.set_tip_checks()
        rc, out = self.status("--tip", self.any_repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("usage:", out)

    def test_a_short_name_not_in_the_table_is_still_a_usage_error(self):
        rc, out = self.status("no-such-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("usage:", out)

    def test_a_table_repo_by_full_name_does_not_use_this_path(self):
        # A table repo's full name is its table entry (the whole CI run), not a required-checks read: see
        # GithubStateTable.test_dotfiles_full_name_reads_the_whole_run_and_is_red_when_a_non_required_job_failed.
        self.set_tip_checks()
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c3, "failure")]}
        rc, out = self.status("cartwmic/dotfiles")
        self.assertEqual(rc, 1, out)
        self.assertIn("dotfiles: RED  run 1 failed", out)
        self.assertNotIn("required check", out)

    def test_a_non_table_owner_repo_still_takes_the_required_checks_path_beside_a_red_table_repo(self):
        # dotfiles' whole-run read must not leak to any other OWNER/REPO: its required checks pass, so it is GREEN
        # even though a table repo's run is red, and the calls are the required-checks reads, not run list.
        self.set_tip_checks()
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c3, "failure")]}
        rc, out = self.status("--merge-gate", self.any_repo)
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{self.any_repo}: GREEN  all 2 required checks passed on main tip {self.c3[:7]}", out)
        self.assertFalse(any(c.startswith("run list") for c in self.log.read_text().splitlines()))
        for lookalike in ("cartwmic/dotfiles-fork", "other-org/dotfiles"):   # a name that only resembles a table repo's
            self.extra_repos = {lookalike: str(self.src)}
            self.protection = {lookalike: {"contexts": ["tests"], "checks": [{"context": "tests", "app_id": 1}]}}
            self.branch_protection = {lookalike: {"protected": True, "protection": {"enabled": True, "required_status_checks": {
                "checks": [{"context": "tests", "app_id": 1}], "contexts": ["tests"]}}}}
            self.branch_rules = {lookalike: []}
            self.check_runs = {lookalike: {self.c3: [self.check_row("tests")]}}
            rc, out = self.status("--merge-gate", lookalike)
            self.assertEqual(rc, 0, out)
            self.assertIn(f"{lookalike}: GREEN  all 1 required checks passed on main tip {self.c3[:7]}: tests", out)

    def test_gh_caller_is_set_on_every_call(self):
        self.set_tip_checks()
        self.status(self.any_repo)
        for line in self.env_log.read_text().splitlines():
            self.assertEqual(json.loads(line)["caller"], "ci-main-status", line)


LEDGER_FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, sys
    with open(os.environ["FAKE_LEDGER_LOG"], "a") as log:
        log.write(" ".join(sys.argv[1:]) + "\\n")
    if sys.argv[1:2] != ["approves-pr"]:
        print("ledger: unknown command " + (sys.argv[1] if len(sys.argv) > 1 else ""), file=sys.stderr)
        sys.exit(1)
    ask, pr = sys.argv[2], sys.argv[3]
    if os.environ.get("FAKE_LEDGER_SAYS"):
        print(os.environ["FAKE_LEDGER_SAYS"], file=sys.stderr)
        sys.exit(1)
    if os.environ.get("FAKE_LEDGER_APPROVES") == ask + " " + pr:
        print("approves-pr: ask #" + ask + " holds Michael's go-ahead for " + pr)
        sys.exit(0)
    print("approves-pr: Michael's words on ask #" + ask + " do not name " + pr + ".", file=sys.stderr)
    sys.exit(1)
''')


class OwnerApproved(AnyRepoFixture):
    """`--merge-gate OWNER/REPO --pr N --owner-approved ASK`: Michael's answered ask for this PR waives "no required checks" (a protected
    main with none, or an unprotected one) and nothing else. The ledger decides whether the ask holds; here it is a stub that approves one
    (ask, PR) pair. The log line a waiver leaves goes to OWNER_APPROVED_LOG."""

    def setUp(self):
        super().setUp()
        t = Path(self.tmp.name)
        (t / "ledger").write_text(LEDGER_FAKE)
        (t / "ledger").chmod(0o755)
        self.ledger_log = t / "ledger.log"
        self.bypass_log = t / "owner-approved.jsonl"
        self.env.update({"LEDGER_BIN": str(t / "ledger"), "FAKE_LEDGER_LOG": str(self.ledger_log),
                         "FAKE_LEDGER_APPROVES": f"12 {self.any_repo}#7", "OWNER_APPROVED_LOG": str(self.bypass_log)})
        self.prs = {"7": {"headRefOid": self.c2, "headRefName": "fix", "baseRefName": "main"}}
        self.pr_checks = {self.any_repo: {"7": []}}

    def protected_with_none(self):
        self.branch_protection = {self.any_repo: {"protected": True, "protection": {"enabled": True, "required_status_checks": {"contexts": [], "checks": []}}}}

    def unprotected(self):
        self.branch_protection = {self.any_repo: {"protected": False}}

    def gate(self, ask="12", pr="7"):
        return self.status("--merge-gate", self.any_repo, "--pr", pr, "--owner-approved", ask)

    def bypass_lines(self):
        return [json.loads(line) for line in self.bypass_log.read_text().splitlines()] if self.bypass_log.exists() else []

    def test_without_the_flag_a_protected_main_with_no_required_checks_still_refuses(self):
        self.protected_with_none()
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("nothing for this gate to verify", out)

    def test_a_protected_main_with_no_required_checks_passes_with_an_ask_the_ledger_vouches_for(self):
        self.protected_with_none()
        rc, out = self.gate()
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{self.any_repo}: WAIVED  no required status check", out)
        self.assertIn(f"on PR #7 head {self.c2[:7]}", out)
        self.assertIn(f"owner-approved: approves-pr: ask #12 holds Michael's go-ahead for {self.any_repo}#7", out)
        self.assertEqual(self.ledger_log.read_text().splitlines(), [f"approves-pr 12 {self.any_repo}#7"])

    def test_the_waiver_leaves_one_log_line_with_the_ask_the_pr_and_the_head(self):
        self.protected_with_none()
        self.gate()
        (line,) = self.bypass_lines()
        self.assertEqual({k: line[k] for k in ("action", "gate", "pr", "head", "ask")},
                         {"action": "owner-approved", "gate": "ci-main-status", "pr": f"{self.any_repo}#7", "head": self.c2, "ask": "12"})
        self.assertEqual(len(line["waived"]), 1)
        self.assertIn("no required status check", line["waived"][0])

    def test_the_waiver_line_says_it_was_waived(self):
        self.protected_with_none()
        self.gate()
        (line,) = self.bypass_lines()
        self.assertEqual(line["outcome"], "waived")
        self.assertRegex(line["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

    def refused_line(self):
        (line,) = self.bypass_lines()
        self.assertEqual({k: line[k] for k in ("action", "gate", "outcome")},
                         {"action": "owner-approved", "gate": "ci-main-status", "outcome": "refused"})
        self.assertRegex(line["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertNotIn("waived", line)
        return line

    def test_a_refused_ask_for_another_pr_leaves_a_refused_line_with_the_ledgers_reason(self):
        self.protected_with_none()
        self.prs["8"] = self.prs["7"]
        self.pr_checks[self.any_repo]["8"] = []
        rc, out = self.gate(pr="8")
        self.assertEqual(rc, 1, out)
        line = self.refused_line()
        self.assertEqual((line["pr"], line["ask"]), (f"{self.any_repo}#8", "12"))
        self.assertIn(f"do not name {self.any_repo}#8", line["reason"])
        self.assertNotIn("\n", line["reason"])

    def test_each_answer_the_ledger_refuses_with_leaves_a_refused_line(self):
        self.protected_with_none()
        for says in ("approves-pr: ask #12 was answered by the coordinator, not by Michael.",
                     "approves-pr: ask #12 is still open.",
                     "approves-pr: no ask #12."):
            with self.subTest(says=says):
                self.bypass_log.unlink(missing_ok=True)
                self.env["FAKE_LEDGER_SAYS"] = says + "\nsecond line"
                rc, out = self.gate()
                self.assertEqual(rc, 1, out)
                line = self.refused_line()
                self.assertEqual((line["pr"], line["ask"], line["reason"]), (f"{self.any_repo}#7", "12", says))

    def test_a_ledger_that_cannot_run_or_has_no_approves_pr_leaves_a_refused_line(self):
        self.protected_with_none()
        missing = Path(self.tmp.name) / "no-such-ledger"
        old_ledger = Path(self.tmp.name) / "old-ledger"
        old_ledger.write_text("#!/bin/sh\nexit 2\n")   # exits non-zero with no message: an older coordinator
        old_ledger.chmod(0o755)
        for bin_, words in ((missing, "could not run"), (old_ledger, "exited 2 with no message")):
            with self.subTest(ledger=bin_.name):
                self.bypass_log.unlink(missing_ok=True)
                self.env["LEDGER_BIN"] = str(bin_)
                rc, out = self.gate()
                self.assertEqual(rc, 1, out)
                line = self.refused_line()
                self.assertEqual(line["ask"], "12")
                self.assertIn(words, line["reason"])

    def test_an_ask_that_is_not_a_number_leaves_a_refused_line(self):
        self.protected_with_none()
        rc, out = self.gate(ask="michael")
        self.assertEqual(rc, 1, out)
        line = self.refused_line()
        self.assertEqual((line["pr"], line["ask"]), (f"{self.any_repo}#7", "michael"))
        self.assertIn("takes the id of an answered ledger ask", line["reason"])

    def test_the_flag_in_a_shape_it_does_not_take_leaves_a_refused_line(self):
        self.protected_with_none()
        for args, pr in ((["--merge-gate", self.any_repo, "--owner-approved", "12"], None),                         # no --pr
                         ([self.any_repo, "--pr", "7", "--owner-approved", "12"], None),                                         # no --merge-gate
                         (["--merge-gate", "dotfiles", "--pr", "7", "--owner-approved", "12"], "dotfiles#7"),         # a table repo
                         (["--merge-gate", self.any_repo, "--pr", "7", "--owner-approved"], None)):                   # no ask
            with self.subTest(args=args):
                self.bypass_log.unlink(missing_ok=True)
                rc, out = self.status(*args)
                self.assertEqual(rc, 1, f"{args}: {out}")
                line = self.refused_line()
                self.assertEqual(line.get("pr"), pr)
                self.assertEqual(line["ask"], "12" if "12" in args else "")
                self.assertTrue(line["reason"])
        self.assertFalse(self.ledger_log.exists())

    def test_a_refusal_whose_log_cannot_be_written_is_still_a_refusal(self):
        self.protected_with_none()
        blocker = Path(self.tmp.name) / "a-file"
        blocker.write_text("")
        self.env["OWNER_APPROVED_LOG"] = str(blocker / "owner-approved.jsonl")   # its folder is a file
        self.prs["8"] = self.prs["7"]
        self.pr_checks[self.any_repo]["8"] = []
        rc, out = self.gate(pr="8")
        self.assertEqual(rc, 1, out)
        self.assertIn("is refused", out)
        self.assertNotIn("WAIVED", out)

    def test_a_waiver_whose_log_cannot_be_written_says_so_on_stderr(self):
        self.protected_with_none()
        blocker = Path(self.tmp.name) / "a-file"
        blocker.write_text("")
        self.env["OWNER_APPROVED_LOG"] = str(blocker / "owner-approved.jsonl")
        rc, out = self.gate()
        self.assertEqual(rc, 0, out)
        self.assertIn("WAIVED", out)
        self.assertIn("could not write", out)

    def test_an_unprotected_main_passes_the_same_way(self):
        self.unprotected()
        rc, out = self.gate()
        self.assertEqual(rc, 0, out)
        self.assertIn("WAIVED  no required status check", out)
        self.assertEqual(len(self.bypass_lines()), 1)

    def test_an_ask_the_ledger_refuses_leaves_the_gate_refused_and_says_why(self):
        # the ask answers another PR: the stub approves only (12, example-repo#7)
        self.protected_with_none()
        self.prs["8"] = self.prs["7"]
        self.pr_checks[self.any_repo]["8"] = []
        rc, out = self.gate(pr="8")
        self.assertEqual(rc, 1, out)
        self.assertIn(f"--owner-approved 12 is refused: approves-pr: Michael's words on ask #12 do not name {self.any_repo}#8.", out)
        self.assertNotIn("WAIVED", out)
        self.assertEqual([l["outcome"] for l in self.bypass_lines()], ["refused"])

    def test_an_ask_that_is_not_a_number_is_refused_without_calling_the_ledger(self):
        self.protected_with_none()
        rc, out = self.gate(ask="michael")
        self.assertEqual(rc, 1, out)
        self.assertIn("takes the id of an answered ledger ask", out)
        self.assertFalse(self.ledger_log.exists())

    def test_the_ledger_is_found_on_PATH_when_no_variable_names_one(self):
        self.protected_with_none()
        bin_dir = Path(self.tmp.name) / "path-bin"
        bin_dir.mkdir()
        (bin_dir / "ledger").write_text(LEDGER_FAKE)
        (bin_dir / "ledger").chmod(0o755)
        del self.env["LEDGER_BIN"]
        self.env.pop("COORDINATOR_STATE_DIR", None)
        self.env["PATH"] = f"{bin_dir}{os.pathsep}{self.env.get('PATH', '')}"
        rc, out = self.gate()
        self.assertEqual(rc, 0, out)
        self.assertIn("WAIVED", out)
        self.assertIn("approves-pr 12 " + self.any_repo + "#7", self.ledger_log.read_text())

    def test_a_ledger_that_cannot_run_or_has_no_approves_pr_is_a_refusal_never_a_pass(self):
        self.protected_with_none()
        self.env["LEDGER_BIN"] = str(Path(self.tmp.name) / "no-such-ledger")
        rc, out = self.gate()
        self.assertEqual(rc, 1, out)
        self.assertIn("could not run", out)
        self.assertIn("nothing was approved", out)
        self.assertEqual([l["outcome"] for l in self.bypass_lines()], ["refused"])

    def test_a_failing_required_check_stays_red_with_the_flag(self):
        self.pr_checks = {self.any_repo: {"7": [{"name": "tests"}, {"name": "lint"}]}}
        self.check_runs = {self.any_repo: {self.c2: [self.check_row("tests", "failure"), self.check_row("lint", rid=2)]}}
        rc, out = self.gate()
        self.assertEqual(rc, 1, out)
        self.assertIn("RED  required check(s) failed", out)
        self.assertNotIn("WAIVED", out)
        line = self.refused_line()
        self.assertEqual((line["pr"], line["ask"]), (f"{self.any_repo}#7", "12"))
        self.assertIn('RED  required check(s) failed', line["reason"])
        self.assertNotIn("\n", line["reason"])

    def test_a_pending_required_check_stays_untested_with_the_flag(self):
        self.pr_checks = {self.any_repo: {"7": [{"name": "tests"}, {"name": "lint"}]}}
        self.check_runs = {self.any_repo: {self.c2: [self.check_row("tests"), self.check_row("lint", status="in_progress", rid=2)]}}
        rc, out = self.gate()
        self.assertEqual(rc, 2, out)
        self.assertIn("UNTESTED", out)
        line = self.refused_line()
        self.assertEqual((line["pr"], line["ask"]), (f"{self.any_repo}#7", "12"))
        self.assertIn('UNTESTED', line["reason"])
        self.assertNotIn("\n", line["reason"])

    def test_a_rule_type_the_gate_cannot_verify_stays_unreadable_with_the_flag(self):
        self.protected_with_none()
        self.branch_rules = {self.any_repo: [{"type": "workflows", "parameters": {}}]}
        rc, out = self.gate()
        self.assertEqual(rc, 1, out)
        self.assertIn("which this gate cannot verify", out)
        line = self.refused_line()
        self.assertEqual((line["pr"], line["ask"]), (f"{self.any_repo}#7", "12"))
        self.assertIn('which this gate cannot verify', line["reason"])
        self.assertNotIn("\n", line["reason"])

    def test_a_required_check_the_computed_set_lacks_stays_unreadable_with_the_flag(self):
        self.protected_with_none()
        self.pr_checks = {self.any_repo: {"7": [{"name": "extra"}]}}
        rc, out = self.gate()
        self.assertEqual(rc, 1, out)
        self.assertIn("failing closed", out)
        line = self.refused_line()
        self.assertEqual((line["pr"], line["ask"]), (f"{self.any_repo}#7", "12"))
        self.assertIn('failing closed', line["reason"])
        self.assertNotIn("\n", line["reason"])

    def test_the_equals_form_is_read_like_the_two_word_form(self):
        self.protected_with_none()
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "7", "--owner-approved=12")
        self.assertEqual(rc, 0, out)
        self.assertIn("WAIVED", out)
        self.assertEqual(self.ledger_log.read_text().splitlines(), [f"approves-pr 12 {self.any_repo}#7"])
        (line,) = self.bypass_lines()
        self.assertEqual((line["outcome"], line["ask"]), ("waived", "12"))

    def test_a_refused_equals_form_leaves_a_refused_line_too(self):
        self.protected_with_none()
        self.prs["8"] = self.prs["7"]
        self.pr_checks[self.any_repo]["8"] = []
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "8", "--owner-approved=12")
        self.assertEqual(rc, 1, out)
        line = self.refused_line()
        self.assertEqual((line["pr"], line["ask"]), (f"{self.any_repo}#8", "12"))
        self.bypass_log.unlink()
        rc, out = self.status("--merge-gate", self.any_repo, "--pr", "7", "--owner-approved=")   # no ask after the equals sign
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.refused_line()["ask"], "")

    def test_the_flag_is_for_the_merge_gate_with_a_pr_on_a_repo_outside_the_table_only(self):
        self.protected_with_none()
        for args in (["--merge-gate", self.any_repo, "--owner-approved", "12"],              # no --pr
                     [self.any_repo, "--pr", "7", "--owner-approved", "12"],                  # no --merge-gate
                     ["--merge-gate", "dotfiles", "--pr", "7", "--owner-approved", "12"],      # a table repo has nothing to waive
                     ["--merge-gate", self.any_repo, "--pr", "7", "--owner-approved"]):       # no ask
            rc, out = self.status(*args)
            self.assertEqual(rc, 1, f"{args}: {out}")
            self.assertNotIn("WAIVED", out)
        self.assertFalse(self.ledger_log.exists())


STEP_FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, sys
    with open(os.environ["FAKE_STEP_LOG"], "a") as log:
        log.write(os.path.basename(sys.argv[0]) + " " + " ".join(sys.argv[1:]) + "\\n")
    code = int(os.environ.get("FAKE_" + os.path.basename(sys.argv[0]).upper().replace("-", "_") + "_EXIT", "0"))
    print(("OK: " if code == 0 else "refused: ") + os.path.basename(sys.argv[0]) + " said so", file=sys.stdout if code == 0 else sys.stderr)
    sys.exit(code)
''')
NO_CI_HEAD = "c" * 40


class NoCiRepo(Fixture):
    """A table repo marked no_ci (eval-cases: private, no CI, no required checks possible): its merge gate is the PR's
    `agent-traces review verify` at its head plus `pr-body-check`, both run, both must exit 0."""

    def setUp(self):
        super().setUp()
        bindir = Path(self.env["PATH"].split(os.pathsep)[0])
        for tool in ("agent-traces", "pr-body-check"):
            (bindir / tool).write_text(STEP_FAKE)
            (bindir / tool).chmod(0o755)
        self.steps = Path(self.tmp.name) / "steps.log"
        self.env["FAKE_STEP_LOG"] = str(self.steps)
        self.prs = {"1": {"headRefOid": NO_CI_HEAD}}

    def calls(self):
        return self.steps.read_text().splitlines() if self.steps.exists() else []

    def test_both_steps_pass_exit_0_and_the_line_says_no_ci_and_names_both(self):
        rc, out = self.status("--merge-gate", "eval-cases", "--pr", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("eval-cases: no CI", out)
        self.assertIn("review verify: OK", out)
        self.assertIn("pr-body-check: OK", out)
        self.assertIn(NO_CI_HEAD, out)
        self.assertEqual(self.calls(), [f"agent-traces review verify --item eval-cases#1 --head {NO_CI_HEAD} --require-block",
                                        "pr-body-check cartwmic/eval-cases 1"])

    def test_the_owner_repo_form_is_the_same_gate(self):
        rc, out = self.status("--merge-gate", "cartwmic/eval-cases", "--pr", "1")
        self.assertEqual(rc, 0, out)
        self.assertIn("eval-cases: no CI", out)
        self.assertEqual(len(self.calls()), 2)

    def test_a_failed_review_verify_is_1_and_names_it_and_the_body_check_still_runs(self):
        self.env["FAKE_AGENT_TRACES_EXIT"] = "1"
        rc, out = self.status("--merge-gate", "eval-cases", "--pr", "1")
        self.assertEqual(rc, 1, out)
        self.assertIn("review verify: FAILED  exit 1", out)
        self.assertIn("agent-traces said so", out)
        self.assertIn("pr-body-check: OK", out)
        self.assertEqual(len(self.calls()), 2)

    def test_a_failed_pr_body_check_is_1_and_names_it_and_review_verify_still_runs(self):
        self.env["FAKE_PR_BODY_CHECK_EXIT"] = "2"   # any non-zero exit is a failure, and the gate's own exit is 1
        rc, out = self.status("--merge-gate", "eval-cases", "--pr", "1")
        self.assertEqual(rc, 1, out)
        self.assertIn("pr-body-check: FAILED  exit 2", out)
        self.assertIn("review verify: OK", out)

    def test_a_tool_that_cannot_start_is_1(self):
        bindir = Path(self.env["PATH"].split(os.pathsep)[0])
        (bindir / "agent-traces").unlink()
        pydir = Path(self.tmp.name) / "py"   # python3 only (the fake gh needs it), so no real agent-traces can be found on PATH
        pydir.mkdir()
        (pydir / "python3").symlink_to(sys.executable)
        self.env["PATH"] = f"{bindir}{os.pathsep}{pydir}"
        rc, out = self.status("--merge-gate", "eval-cases", "--pr", "1")
        self.assertEqual(rc, 1, out)
        self.assertIn("review verify: FAILED  agent-traces could not start", out)
        self.assertIn("pr-body-check: OK", out)

    def test_without_pr_it_refuses_with_the_fix_and_runs_nothing(self):
        rc, out = self.status("--merge-gate", "eval-cases")
        self.assertEqual(rc, 1, out)
        self.assertIn("--pr N", out)
        self.assertEqual(self.calls(), [])

    def test_a_pr_it_cannot_read_is_1(self):
        rc, out = self.status("--merge-gate", "eval-cases", "--pr", "9")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertEqual(self.calls(), [])

    def test_plain_tip_and_all_say_no_ci_and_exit_0_without_running_a_step(self):
        for args in (["eval-cases"], ["--tip", "eval-cases"], ["cartwmic/eval-cases"]):
            with self.subTest(args=args):
                rc, out = self.status(*args)
                self.assertEqual(rc, 0, out)
                self.assertIn("eval-cases: n/a (no CI", out)
        self.runs = {"cartwmic/dotfiles|ci.yml": [run(1, self.c3, "success")]}
        for args in (["--all"], ["--all", "--merge-gate"]):
            with self.subTest(args=args):
                rc, out = self.status(*args)
                self.assertIn("eval-cases: n/a (no CI", out)
                self.assertNotIn("eval-cases: ERROR", out)
        self.assertEqual(self.calls(), [])

    def test_the_usage_line_names_eval_cases_among_the_repos(self):
        rc, out = self.status("--merge-gate")   # no repo: a usage error, printed on stderr
        self.assertEqual(rc, 1, out)
        self.assertIn("usage:", out)
        self.assertIn("eval-cases", out)

    def test_pr_with_plain_status_is_still_a_usage_error(self):
        rc, out = self.status("eval-cases", "--pr", "1")
        self.assertEqual(rc, 1, out)
        self.assertIn("usage:", out)

    def test_another_repo_is_unchanged_and_runs_neither_step(self):
        self.dotfiles_runs([run(1, self.c3, "success")])
        rc, out = self.status("--merge-gate", "dotfiles")
        self.assertEqual((rc, "GREEN" in out, "no CI" in out), (0, True, False), out)
        self.runs = {"cartwmic/loop-engine|ci.yml": [run(2, self.c3, "failure", age=5), run(1, self.c2, "success", age=1)]}
        rc, out = self.status("--merge-gate", "loop-engine")
        self.assertEqual(rc, 1, out)
        self.assertIn("loop-engine: RED", out)
        self.assertEqual(self.calls(), [])


def is_ancestor(path, a, b):
    return subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0


class RecordedSamples(Fixture):
    """The fake `gh` copies three behaviours of real GitHub. Each is recorded once from real `gh` (recorded/record_samples.py) and the fake must
    give the same fields and relations, so the fake cannot drift from GitHub between the live smokes."""
    RECORDED = Path(__file__).resolve().parent / "recorded"
    RECORDED_FIELDS = "databaseId,attempt,createdAt,startedAt,updatedAt,conclusion,status,event,headSha,headBranch"   # what record_samples.py asks real gh for

    def sample(self, name):
        return json.loads((self.RECORDED / name).read_text())

    def gh_out(self, *args):
        self.write_fixture()
        r = subprocess.run(["gh", *args], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_a_rerun_keeps_the_runs_created_time_and_the_fields_are_the_real_ones(self):
        real = self.sample("rerun_keeps_created_at.json")
        self.assertEqual(real["row"]["createdAt"], real["attempt_1"]["created_at"], "recorded: a rerun keeps createdAt")
        self.assertNotEqual(real["row"]["startedAt"], real["row"]["createdAt"], "recorded: the rerun started later")
        self.attempts = {"1": {"1": {"status": "completed", "conclusion": "failure"}}}
        self.dotfiles_runs([run(1, self.c2, "success", attempt=2, age=1, started_age=9)])
        row = self.gh_out("run", "list", "-R", "cartwmic/dotfiles", "--workflow", "ci.yml", "--json", self.RECORDED_FIELDS)[0]
        self.assertEqual(set(row), set(real["row"]), "the fake gives the fields asked for, as real gh does")
        self.assertEqual({k: type(v) for k, v in row.items()}, {k: type(real["row"][k]) for k in row})
        gate = PinFixCopiesMatchTheirSources.load("gate_fields_under_test", "dot_local/bin/executable_ci-main-status")
        self.assertLessEqual(set(gate.RUN_FIELDS.split(",")) - {"url"}, set(real["row"]), "the script asks for a field real gh does not have")
        self.assertIn("createdAt", gate.RUN_FIELDS.split(","), "the floor and the window are read from createdAt")
        first = self.gh_out("api", "repos/cartwmic/dotfiles/actions/runs/1/attempts/1")
        self.assertEqual(first["created_at"], row["createdAt"], "the fake's rerun keeps createdAt as the recorded one does")
        self.assertNotEqual(row["startedAt"], row["createdAt"])
        self.assertLessEqual({"created_at", "status", "conclusion"}, set(real["attempt_1"]) | {"status", "conclusion"})
        self.assertLessEqual({"created_at", "status", "conclusion"}, set(first))

    def test_a_list_with_created_stops_at_1000_rows_and_one_without_does_not(self):
        real = self.sample("run_list_ceiling.json")
        self.assertEqual((real["requested"], real["got"], real["got_without_created"]), (1100, 1000, 1100), "recorded")
        base = datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc)
        rows = [{**run(n, self.c3, "success"), "createdAt": (base + datetime.timedelta(seconds=n)).strftime("%Y-%m-%dT%H:%M:%SZ")} for n in range(1, 1101)]
        self.dotfiles_runs(rows)
        listed = self.gh_out("run", "list", "-R", "cartwmic/dotfiles", "--workflow", "ci.yml", "--created", ">=2020-01-01", "--limit", "1100", "--json", "databaseId,createdAt")
        self.assertEqual(len(listed), real["got"])
        self.assertEqual([r["createdAt"] for r in listed], sorted((r["createdAt"] for r in listed), reverse=True), "newest first, as recorded" if real["newest_first"] else "")
        plain = self.gh_out("run", "list", "-R", "cartwmic/dotfiles", "--workflow", "ci.yml", "--limit", "1100", "--json", "databaseId,createdAt")
        self.assertEqual(len(plain), real["got_without_created"])
        self.assertLessEqual(set(listed[0]) & {"databaseId", "createdAt"}, set(real["keys"]))

    def test_compare_says_how_far_ahead_and_lists_commits_with_the_fields_the_script_reads(self):
        real = self.sample("compare_ahead_by.json")
        self.assertEqual((real["status"], real["ahead_by"], real["total_commits"], real["listed"]), ("ahead", 3, 3, 3), "recorded: under the cap, ahead_by is the count listed")
        a = commit(self.src, "extra 1")
        commit(self.src, "extra 2")
        b = commit(self.src, "extra 3")
        self.dotfiles_runs([])
        got = self.gh_out("api", f"repos/cartwmic/dotfiles/compare/{self.c3}...{b}?per_page=100")
        self.assertEqual(got["status"], real["status"])
        self.assertEqual((got["ahead_by"], got["total_commits"], len(got["commits"])), (3, 3, 3))
        self.assertLessEqual(set(got), set(real["top_keys"]), "the fake gives a field real gh does not")
        self.assertLessEqual({"status", "ahead_by", "commits"}, set(got))
        self.assertLessEqual(set(got["commits"][0]), set(real["commit_keys"]))
        self.assertLessEqual(set(got["commits"][0]["commit"]), set(real["commit_commit_keys"]))
        self.assertEqual(got["commits"][0]["sha"], a, "oldest first, as real compare lists")


if __name__ == "__main__":
    unittest.main()
