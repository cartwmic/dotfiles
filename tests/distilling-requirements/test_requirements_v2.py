"""requirements/2: the snapshot header, the quality lens, the inferred kind, history evidence (check_shape.py, check_truth.py, surface_coverage.py),
and the two history scripts (check_history_refs.py, history_signals.py) run as the skill runs them. No network: a fake `gh` on PATH stands in for GitHub.
Run: python3 -m unittest discover -s tests/distilling-requirements"""
import runlog_support  # first: keeps the run out of the real log
import atexit
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = runlog_support.STATE  # runlog_support keeps these runs out of the real log

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
SCRIPTS = SKILLS / "distilling-requirements/scripts"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
SHA = "a" * 40
LINE = "Snapshot of demo at aaaaaaa on 2026-11-26. Not maintained: it records the code at that commit, not today's."
COLS = "| id | lens | kind | durability | status | requirement | evidence | check | fit | enforced | note |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
GH = """#!%s
import json, os, sys
a = sys.argv[1:]
if a[:2] in (["pr", "view"], ["issue", "view"]):
    views = json.load(open(os.environ["FAKE_GH_VIEWS"])) if os.environ.get("FAKE_GH_VIEWS") else {}
    if a[0] + ":" + a[2] in views:
        print(json.dumps(views[a[0] + ":" + a[2]]))
        sys.exit(0)
    if a[2] == "77":
        print("To get started with GitHub CLI, please run:  gh auth login", file=sys.stderr)
        sys.exit(4)
    # the exact text real gh prints for a number that does not exist (`gh issue view 99999999` and `gh pr view 99999999`)
    what = "a PullRequest" if a[0] == "pr" else "an issue or pull request"
    print("GraphQL: Could not resolve to %%s with the number of %%s. (repository.%%s)" %% (what, a[2], "pullRequest" if a[0] == "pr" else "issue"), file=sys.stderr)
    sys.exit(1)
if a[0] in ("pr", "issue") and a[1] == "list":
    open(os.environ["FAKE_GH_LOG"], "a").write(json.dumps(a) + "\\n")
    items = json.load(open(os.environ["FAKE_GH_PRS" if a[0] == "pr" else "FAKE_GH_ISSUES"]))
    field, window = a[a.index("--search") + 1].split(":", 1)
    lo, hi = window.split("..")
    key = "mergedAt" if a[0] == "pr" else "createdAt"
    hits = [i for i in items if lo <= i[key][:10] <= hi]
    print(json.dumps(hits[:min(int(a[a.index("--limit") + 1]), 1000)]))  # GitHub search never returns more than 1,000
    sys.exit(0)
sys.exit(2)
"""


def doc(rows, header=None, line=LINE, tail="## Run log\n\n- first pass\n"):
    h = {"shape": "requirements/2", "repo": "demo", "commit": SHA, "snapshot": "2026-11-26 at " + SHA, "history": SHA, "scope": "whole repo", "repo-wide": "yes", "interview": "none",
         "date": "2026-11-26", "not-read": "none", "counts": "R=%d SM=0 I=0 U=0 F=0 Q=0" % len(rows)}
    h.update(header or {})
    head = "```text\n" + "".join("%s: %s\n" % kv for kv in h.items() if kv[1] is not None) + "```\n\n# Requirements: demo\n\n"
    return head + (line + "\n\n" if line else "") + "## 1. Requirements register\n\n" + COLS + "\n".join(rows) + "\n\n## 2. State machines\n\nNone.\n\n## 3. Unenforced invariants\n\nNone.\n\n## 4. Findings\n\nNone.\n\n## 5. Open questions\n\nNone.\n\n" + tail


def row(n, lens="product", kind="explicit", status="proposed", evidence="src/a.py:1", note=""):
    return "| R-%d | %s | %s | enduring | %s | A thing shall hold. | %s | none | none | yes | %s |" % (n, lens, kind, status, evidence, note)


def script(name, *args, env=None, path=None):
    e = dict(env or os.environ)
    if path is not None:
        e["PATH"] = path
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True, env=e)
    return r.returncode, r.stdout, r.stderr


def shape(text):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "R.md").write_text(text)
        code, out, err = script("check_shape.py", Path(d, "R.md"))
    return code, out + err


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def commit(repo, files, msg, remove=()):
    for rel, text in files.items():
        p = Path(repo, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for rel in remove:
        Path(repo, rel).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def build_fixture_repo(build):
    """Build a fixture repo once, for setUpClass: `build(repo)` makes the commits and returns what the tests need (shas). Returns (folder, what build returned).
    Each test then takes its own copy with copy_fixture_repo, so a test that adds commits or checks out a branch cannot touch another's."""
    base = tempfile.mkdtemp(prefix="fixture-")
    atexit.register(shutil.rmtree, base, True)
    repo = Path(base, "repo")
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    return repo, build(repo)


def copy_fixture_repo(template, tmp):
    shutil.copytree(template, Path(tmp, "repo"), symlinks=True)
    return Path(tmp, "repo")


def fake_gh(tmp, prs=None, issues=None, views=None):
    """A bin folder with a fake gh first, and one with git only (gh absent); returns (with_gh PATH, without_gh PATH, env for the PR list)."""
    with_gh, without = Path(tmp, "with-gh"), Path(tmp, "no-gh")
    for d in (with_gh, without):
        d.mkdir(exist_ok=True)
        if not (d / "git").exists():
            (d / "git").symlink_to(shutil.which("git"))
    gh = with_gh / "gh"
    gh.write_text(GH % sys.executable)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    Path(tmp, "prs.json").write_text(json.dumps(prs or []))
    Path(tmp, "issues.json").write_text(json.dumps(issues or []))
    Path(tmp, "views.json").write_text(json.dumps(views or {}))
    return str(with_gh), str(without), dict(os.environ, FAKE_GH_VIEWS=str(Path(tmp, "views.json")), FAKE_GH_PRS=str(Path(tmp, "prs.json")), FAKE_GH_ISSUES=str(Path(tmp, "issues.json")), FAKE_GH_LOG=str(Path(tmp, "gh.log")))


class ShapeTest(unittest.TestCase):
    def test_a_requirements_2_file_with_a_quality_inferred_row_and_history_evidence_is_ok(self):
        rows = [row(1, lens="quality", kind="inferred", evidence="src/a.py:1; commit:abcdef1; pr:12; issue:7"), row(2, lens="quality", kind="inferred", evidence="commit:abcdef1234567"),
                row(3, kind="explicit", status="accepted", evidence="owner:interview 2026-11-26 Q1")]
        self.assertEqual(shape(doc(rows, {"interview": "interview.md"})), (0, "ok\n"))

    def test_a_citation_into_a_snapshot_is_an_error_by_folder_and_by_the_not_maintained_line(self):
        self.assertIn("cites a snapshot", shape(doc([row(1, evidence="docs/snapshots/2026-01-01-aaaaaaa/REQUIREMENTS.md:3")]))[1])
        self.assertIn("cites a snapshot", shape(doc([row(1, evidence="src/a.py:1; ./docs/snapshots/x/GUIDE.md:9-12")]))[1])
        self.assertEqual(shape(doc([row(1, evidence="docs/snapshots-notes.md:3")])), (0, "ok\n"))  # a look-alike name is not the folder
        with tempfile.TemporaryDirectory() as d:
            Path(d, "kept").mkdir()
            Path(d, "kept", "OLD.md").write_text("# T\n\n" + LINE + "\n\nbody\n")
            Path(d, "kept", "LIVE.md").write_text("# T\n\nbody\n")
            Path(d, "R.md").write_text(doc([row(1, evidence="kept/OLD.md:5"), row(2, evidence="kept/LIVE.md:3")]))
            code, out, _ = script("check_shape.py", Path(d, "R.md"), d)
            self.assertEqual(code, 1)
            self.assertIn("line", out)
            self.assertEqual(out.count("cites a snapshot"), 1)
            self.assertIn("kept/OLD.md:5", out)
            self.assertEqual(script("check_shape.py", Path(d, "R.md"))[0], 0)  # without REPO only the folder rule can fire

    def test_requirements_1_is_refused_with_a_message_to_rerun_the_skill(self):
        code, out = shape(doc([row(1)], {"shape": "requirements/1"}))
        self.assertEqual(code, 1)
        self.assertIn("requirements/1 is the old shape: rerun the distilling-requirements skill", out)

    def test_the_header_needs_snapshot_repo_wide_and_interview(self):
        for key in ("snapshot", "repo-wide", "interview"):
            self.assertIn("header: missing " + key, shape(doc([row(1)], {key: None}))[1])
        self.assertIn("repo-wide must be yes or no", shape(doc([row(1)], {"repo-wide": "maybe"}))[1])

    def test_the_snapshot_key_must_repeat_the_date_and_the_commit(self):
        for bad in ("2026-11-27 at " + SHA, "2026-11-26 at " + "b" * 40, "2026-11-26"):
            self.assertIn("header: snapshot must be", shape(doc([row(1)], {"snapshot": bad}))[1], bad)

    def test_the_line_under_the_title_is_fixed_text_built_from_the_header(self):
        for bad in (None, LINE.replace("aaaaaaa", "bbbbbbb"), LINE.replace("2026-11-26", "2026-11-27"), LINE.replace("Not maintained", "Kept current"), LINE.replace("demo", "other")):
            code, out = shape(doc([row(1)], line=bad))
            self.assertEqual(code, 1, bad)
            self.assertIn("snapshot line: the first line under the title must be exactly", out)

    def test_an_archive_writes_no_git_for_the_sha(self):
        line = "Snapshot of demo at no-git on 2026-11-26. " + LINE.split(". ", 1)[1]
        self.assertEqual(shape(doc([row(1)], {"commit": "no-git", "snapshot": "2026-11-26 at no-git", "history": "no-git", "source": "archive"}, line=line)), (0, "ok\n"))

    def test_a_requirements_file_needs_a_run_log_and_no_longer_a_changelog(self):
        self.assertIn("missing section ## Run log", shape(doc([row(1)], tail="## Changelog\n\n- x\n"))[1])

    def test_the_enums_take_quality_and_inferred_and_refuse_others(self):
        self.assertIn("lens='speed'", shape(doc([row(1, lens="speed")]))[1])
        self.assertIn("kind='guessed'", shape(doc([row(1, kind="guessed")]))[1])

    def test_an_inferred_row_stays_proposed_and_accepted_needs_owner_evidence(self):
        self.assertEqual(shape(doc([row(1, kind="inferred", status="disputed", evidence="commit:abcdef1", note="Q-1")]).replace("Q=0", "Q=0").replace("None.\n\n## Run log", "- Q-1: is it enduring? Blocks R-1.\n\n## Run log").replace("Q=0", "Q=1")), (0, "ok\n"))
        self.assertIn("an inferred row has status proposed or disputed, never accepted", shape(doc([row(1, kind="inferred", status="accepted", evidence="commit:abcdef1; owner:interview 2026-11-26 Q1")], {"interview": "interview.md"}))[1])
        self.assertIn("status=accepted needs owner: evidence", shape(doc([row(1, status="accepted")]))[1])

    def test_a_malformed_history_ref_is_refused_and_owner_interview_needs_an_interview_file(self):
        for bad in ("commit:xyz", "commit:abc12", "pr:twelve", "issue:#7"):
            self.assertIn("is not commit:<7+ hex>, pr:<number> or issue:<number>", shape(doc([row(1, evidence=bad)]))[1], bad)
        self.assertIn("header says interview: none", shape(doc([row(1, evidence="owner:interview 2026-11-26 Q1")]))[1])

    def test_a_pr_ref_is_not_read_as_line_12_of_a_file_called_pr(self):
        self.assertIn("evidence needs path:line, commit:<sha>, pr:<n>, issue:<n> or owner:<source>", shape(doc([row(1, evidence="see the notes")]))[1])


class TruthPrepareTest(unittest.TestCase):
    def prepare(self, rows):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "R.md").write_text(doc(rows))
            code, out, err = script("check_truth.py", "prepare", Path(d, "R.md"), "--out", Path(d, "work"))
            return code, out, Path(d, "work/register-claims.md").read_text(), json.loads(Path(d, "work/rows.json").read_text())

    def test_history_evidence_does_not_fail_a_row_and_never_reaches_the_line_checker(self):
        code, out, claims, meta = self.prepare([row(1, evidence="src/a.py:4; commit:abcdef1; pr:12"), row(2, kind="inferred", evidence="commit:abcdef1; issue:7"), row(3, evidence="owner:interview 2026-11-26 Q2")])
        self.assertEqual(code, 0, out)
        self.assertEqual([r["id"] for r in meta["rows"]], ["R-1"])
        self.assertEqual(meta["rows"][0]["cited"], ["src/a.py:4"])
        self.assertNotIn("pr:12", claims)
        self.assertNotIn("abcdef1", claims)
        self.assertEqual([s["id"] for s in meta["not_checked"]], ["R-2", "R-3"])
        self.assertIn("history refs only", meta["not_checked"][0]["reason"])
        self.assertEqual(meta["failed"], [])


class SurfaceCoverageTest(unittest.TestCase):
    def test_a_history_ref_is_not_a_citation(self):
        sys.path.insert(0, str(SCRIPTS))
        sys.dont_write_bytecode = True
        import surface_coverage
        self.assertEqual(surface_coverage.cited("pr:12; commit:1234567; issue:5; src/a.py:3-4"), {("src/a.py", 3, 4)})

    def test_scope_lists_only_the_surfaces_under_the_scope_and_no_scope_lists_all(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = Path(tmp, "repo")
        for d, flag in (("a", "--alpha"), ("b", "--beta")):
            (repo / d).mkdir(parents=True)
            (repo / d / "cli.py").write_text('import argparse\np = argparse.ArgumentParser()\np.add_argument("%s")\n' % flag)
        git(repo, "init", "-q", "-b", "main")
        commit(repo, {"a/cli.py": (repo / "a/cli.py").read_text()}, "init")
        Path(tmp, "R.md").write_text(doc([], {"commit": git(repo, "rev-parse", "HEAD")}))
        _, everything, _ = script("surface_coverage.py", Path(tmp, "R.md"), repo)
        self.assertIn("--alpha", everything)
        self.assertIn("--beta", everything)
        _, scoped, _ = script("surface_coverage.py", Path(tmp, "R.md"), repo, "--scope", "a")
        self.assertIn("--alpha", scoped)
        self.assertNotIn("--beta", scoped)
        self.assertEqual(script("surface_coverage.py", Path(tmp, "R.md"), repo, "--scope")[0], 2)
        _, both, _ = script("surface_coverage.py", Path(tmp, "R.md"), repo, "--scope", "a", "--scope", "b")
        self.assertTrue("--alpha" in both and "--beta" in both)  # repeatable
        _, comma, _ = script("surface_coverage.py", Path(tmp, "R.md"), repo, "--scope", "a,b")
        self.assertTrue("--alpha" in comma and "--beta" in comma)  # comma-separated
        _, whole, _ = script("surface_coverage.py", Path(tmp, "R.md"), repo, "--scope", ".")
        self.assertTrue("--alpha" in whole and "--beta" in whole)  # `.` is the whole repo
        _, absolute, _ = script("surface_coverage.py", Path(tmp, "R.md"), repo, "--scope", str(repo / "b"))
        self.assertTrue("--beta" in absolute and "--alpha" not in absolute)  # an absolute path inside the repo
        self.assertEqual(script("surface_coverage.py", Path(tmp, "R.md"), repo, "--scope", tmp)[0], 2)  # outside the repo
        _, after, _ = script("surface_coverage.py", Path(tmp, "R.md"), "--scope", "a", repo)  # --scope takes one value, not the positionals after it
        self.assertTrue("--alpha" in after and "--beta" not in after)


class HistoryRefsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def build(repo):
            return commit(repo, {"a.py": "x\n"}, "fix: retry the upload on timeout"), commit(repo, {"a.py": "y\n"}, "after the snapshot")
        cls.template, (cls.sha, cls.later) = build_fixture_repo(build)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = copy_fixture_repo(self.template, self.tmp)
        T = "Retry the upload on timeout"
        pr = lambda state, oid, n: {"title": T, "state": state, "mergeCommit": {"oid": oid} if oid else None, "url": "https://github.com/o/r/pull/%d" % n}
        views = {"pr:12": pr("MERGED", self.sha, 12), "pr:229": pr("MERGED", self.later, 229), "pr:225": pr("CLOSED", None, 225),
                 "issue:12": {"title": T, "createdAt": "2000-01-01T00:00:00Z", "url": "https://github.com/o/r/issues/12"},
                 "issue:229": {"title": T, "createdAt": "2000-01-01T00:00:00Z", "url": "https://github.com/o/r/pull/229"},
                 "issue:300": {"title": T, "createdAt": "2999-01-01T00:00:00Z", "url": "https://github.com/o/r/issues/300"}}
        self.with_gh, self.no_gh, self.env = fake_gh(self.tmp, views=views)

    def resolve(self, evidence, path=None, header=None, *extra):
        Path(self.tmp, "R.md").write_text(doc([row(1, kind="inferred", evidence=evidence)], header or {"commit": self.later}))
        return script("check_history_refs.py", Path(self.tmp, "R.md"), self.repo, *extra, env=self.env, path=path or self.with_gh)

    def test_a_real_commit_resolves_with_its_subject_and_a_fake_one_exits_1(self):
        code, out, _ = self.resolve("commit:" + self.sha[:9], None, None, "--commit", self.later)
        self.assertEqual(code, 0)
        self.assertIn("R-1 | commit:%s | resolved | fix: retry the upload on timeout" % self.sha[:9], out)
        self.assertIn("resolved, claim not read-checked: R-1", out)
        code, out, _ = self.resolve("commit:%s; commit:deadbeef0" % self.sha[:9], None, None, "--commit", self.later)
        self.assertEqual(code, 1)
        self.assertIn("R-1 | commit:deadbeef0 | UNRESOLVED | no such commit", out)
        self.assertIn("resolved, claim not read-checked: none", out)
        self.assertIn("unresolved: R-1 commit:deadbeef0", out)

    def test_a_commit_must_be_an_ancestor_of_the_snapshot_commit_given_or_in_the_header(self):
        code, out, _ = self.resolve("commit:" + self.later[:9], None, None, "--commit", self.sha)
        self.assertEqual(code, 1)
        self.assertIn("not an ancestor of the snapshot commit %s" % self.sha[:7], out)
        code, out, _ = self.resolve("commit:" + self.later[:9], None, {"commit": self.sha})
        self.assertEqual(code, 1)
        self.assertIn("snapshot commit: " + self.sha, out)
        self.assertEqual(self.resolve("commit:" + self.sha[:9], None, {"commit": self.later})[0], 0)

    def test_an_archive_has_no_snapshot_commit_so_a_commit_is_checked_for_existence_only(self):
        code, out, _ = self.resolve("commit:" + self.later[:9], None, {"commit": "no-git"})
        self.assertEqual(code, 0)
        self.assertIn("none (archive): commits are checked for existence only", out)

    def test_a_pr_and_an_issue_resolve_through_gh_with_their_titles(self):
        code, out, _ = self.resolve("pr:12; issue:12")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("| resolved | Retry the upload on timeout"), 2)

    def test_a_pr_must_be_merged_with_its_merge_commit_an_ancestor_of_the_snapshot(self):
        code, out, _ = self.resolve("pr:229", None, None, "--commit", self.sha)
        self.assertEqual(code, 1)
        self.assertIn("R-1 | pr:229 | UNRESOLVED | pull request 229 was merged at %s, which is not an ancestor of the snapshot commit %s" % (self.later[:7], self.sha[:7]), out)
        code, out, _ = self.resolve("pr:225", None, None, "--commit", self.later)
        self.assertEqual(code, 1)
        self.assertIn("R-1 | pr:225 | UNRESOLVED | pull request 225 is closed, not merged", out)
        self.assertEqual(self.resolve("pr:229", None, None, "--commit", self.later)[0], 0)  # merged at the snapshot commit itself: fine

    def test_an_issue_must_be_an_issue_and_created_by_the_snapshot_commit_time(self):
        code, out, _ = self.resolve("issue:229")
        self.assertEqual(code, 1)
        self.assertIn("R-1 | issue:229 | UNRESOLVED | 229 is a pull request, not an issue (cite it as pr:229)", out)
        code, out, _ = self.resolve("issue:300")
        self.assertEqual(code, 1)
        self.assertIn("R-1 | issue:300 | UNRESOLVED | issue 300 was created 2999-01-01T00:00:00Z, after the snapshot commit", out)

    def test_a_pr_gh_says_does_not_exist_is_unresolved_and_fails_the_run(self):
        code, out, _ = self.resolve("pr:99")
        self.assertEqual(code, 1)
        self.assertIn("R-1 | pr:99 | UNRESOLVED | gh says it does not exist: GraphQL: Could not resolve to a PullRequest with the number of 99.", out)

    def test_an_issue_gh_says_does_not_exist_is_unresolved_and_fails_the_run(self):
        code, out, _ = self.resolve("issue:99")
        self.assertEqual(code, 1)
        self.assertIn("R-1 | issue:99 | UNRESOLVED | gh says it does not exist: GraphQL: Could not resolve to an issue or pull request with the number of 99.", out)
        self.assertNotIn("NOT CHECKED", out)

    def test_a_gh_that_is_not_signed_in_or_absent_is_not_checked_and_does_not_fail_the_run(self):
        code, out, _ = self.resolve("pr:77")
        self.assertEqual(code, 0)
        self.assertIn("R-1 | pr:77 | NOT CHECKED | gh cannot run here (not signed in, no network or no GitHub remote)", out)
        code, out, _ = self.resolve("pr:12; commit:" + self.sha[:9], path=self.no_gh)
        self.assertEqual(code, 0)
        self.assertIn("R-1 | pr:12 | NOT CHECKED | gh is not available", out)
        self.assertIn("not checked (gh could not run): R-1 pr:12", out)
        self.assertIn("| resolved |", out)

    def test_a_repo_gh_cannot_read_is_not_checked_not_unresolved(self):
        gh = Path(self.with_gh, "gh")
        gh.write_text(gh.read_text().replace('if a[2] == "77":', 'if a[2] == "88":\n        print("GraphQL: Could not resolve to a Repository with the name \'o/r\'.", file=sys.stderr)\n        sys.exit(1)\n    if a[2] == "77":'))
        code, out, _ = self.resolve("pr:88")
        self.assertEqual(code, 0)
        self.assertIn("R-1 | pr:88 | NOT CHECKED", out)
        self.assertNotIn("UNRESOLVED", out)
        self.assertEqual(self.resolve("pr:99")[0], 1)  # a real not-found still fails

    def test_bad_usage_exits_2(self):
        self.assertEqual(script("check_history_refs.py")[0], 2)


class HistorySignalsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def build(repo):
            commit(repo, {"core/a.py": "1\n", "core/b.py": "1\n", "web/w.py": "1\n", "docs/snapshots/2026-01-01-aaaaaaa/REQUIREMENTS.md": "x\n"}, "initial import")
            commit(repo, {"core/a.py": "2\n"}, "fix: handle a timeout in a")
            perf = commit(repo, {"core/a.py": "3\n", "web/w.py": "2\n"}, "perf: cache the lookup")
            commit(repo, {"core/a.py": "4\n"}, "Revert the cache")
            commit(repo, {"core/a.py": "5\n", "core/b.py": "2\n", "docs/snapshots/2026-01-01-aaaaaaa/REQUIREMENTS.md": "y\n"}, "tidy a")
            head = git(repo, "rev-parse", "HEAD")
            return perf, head, commit(repo, {"core/a.py": "6\n"}, "fix a crash after the snapshot")
        cls.template, (cls.perf, cls.head, cls.after) = build_fixture_repo(build)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = copy_fixture_repo(self.template, self.tmp)
        self.with_gh, self.no_gh, self.env = fake_gh(self.tmp)

    def signals(self, *args, path=None, env=None):
        code, out, err = script("history_signals.py", self.repo, "--rev", self.head, *args, env=env or self.env, path=path or self.no_gh)
        self.assertEqual(code, 0, err)
        return json.loads(out) if "json" in args else out

    def test_scope_dot_is_the_whole_repo_and_an_absolute_path_inside_the_repo_is_accepted(self):
        whole = self.signals("--format", "json")
        self.assertEqual(self.signals("--format", "json", "--scope", ".")["scope"], [])
        self.assertEqual(self.signals("--format", "json", "--scope", ".")["signal_commits"], whole["signal_commits"])
        self.assertEqual(self.signals("--format", "json", "--scope", str(self.repo / "web"))["scope"], ["web"])
        self.assertEqual(self.signals("--format", "json", "--scope", "core", "--scope", "web")["scope"], ["core", "web"])
        for bad in (self.tmp, ""):
            self.assertEqual(script("history_signals.py", self.repo, "--scope", bad, path=self.no_gh)[0], 2, bad)

    def test_a_pr_and_an_issue_around_the_commit_are_found_whatever_timezone_it_was_committed_in(self):
        # Committed 2020-01-01 17:04 -0800 = 2020-01-02 01:04 UTC. GitHub search dates are UTC, so a PR merged at 01:05 UTC on 2020-01-02 (this commit's own PR) must be found:
        # the committer's local date (2020-01-01) would have cut it off.
        repo = Path(self.tmp, "tz")
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.py").write_text("1\n")
        git(repo, "add", "-A")
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "fix: a"], check=True, env=dict(ENV, GIT_COMMITTER_DATE="2020-01-01T17:04:00-08:00", GIT_AUTHOR_DATE="2020-01-01T17:04:00-08:00"))
        sha = git(repo, "rev-parse", "HEAD")
        self.assertEqual(git(repo, "log", "-1", "--format=%cs"), "2020-01-01")
        prs = [{"number": 229, "title": "Own PR", "labels": [], "mergedAt": "2020-01-02T01:05:00Z", "mergeCommit": {"oid": sha}}]
        issues = [{"number": n, "title": "I%d" % n, "state": "OPEN", "labels": [], "createdAt": at, "body": ""}
                  for n, at in ((1, "2020-01-02T00:30:00Z"), (2, "2020-01-02T02:00:00Z"), (3, "2020-01-04T00:00:00Z"))]
        with_gh, _, env = fake_gh(self.tmp, prs, issues)
        code, out, err = script("history_signals.py", repo, "--format", "json", env=env, path=with_gh)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual([p["number"] for p in r["merged_prs"]["rows"]], [229])
        self.assertEqual([i["number"] for i in r["issues"]["rows"]], [1])  # #2 was created after the commit, #3 is outside the UTC-day-plus-one window
        issue_call = next(json.loads(l) for l in Path(self.tmp, "gh.log").read_text().splitlines() if json.loads(l)[0] == "issue")
        self.assertEqual(issue_call[issue_call.index("--search") + 1].split("..")[1], "2020-01-03")

    def test_a_two_parent_merge_commit_is_scoped_by_the_branch_changes_only(self):
        git(self.repo, "checkout", "-q", "-b", "feat", self.head)
        commit(self.repo, {"web/w.py": "9\n"}, "feature work")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #9 from x/feat", "feat")
        merged = git(self.repo, "rev-parse", "HEAD")
        sys.path.insert(0, str(SCRIPTS))
        sys.dont_write_bytecode = True
        import history_signals
        self.assertEqual(history_signals.commit_files(str(self.repo), merged), ["web/w.py"])
        self.assertEqual(history_signals.commit_files(str(self.repo), self.perf), ["core/a.py", "web/w.py"])

    def test_signal_commits_are_matched_by_message_and_read_from_the_rev_not_the_working_tree(self):
        r = self.signals("--format", "json")
        by = {c["subject"]: c["signals"] for c in r["signal_commits"]["rows"]}
        self.assertEqual(by, {"fix: handle a timeout in a": ["fix", "timeout"], "perf: cache the lookup": ["perf"], "Revert the cache": ["revert"]})
        self.assertEqual(r["rev"], self.head)
        self.assertNotIn("deleted", r)

    def test_the_scope_keeps_only_history_that_touches_it_and_is_normalised(self):
        for spelling in ("web", "./web", "web/"):
            r = self.signals("--scope", spelling, "--format", "json")
            self.assertEqual([c["subject"] for c in r["signal_commits"]["rows"]], ["perf: cache the lookup"], spelling)
            self.assertEqual(r["scope"], ["web"])
        self.assertEqual(r["signal_commits"]["rows"][0]["files"], ["web/w.py"])

    def test_a_scope_that_is_not_in_the_rev_is_an_error(self):
        code, out, err = script("history_signals.py", self.repo, "--rev", self.head, "--scope", "nowhere", path=self.no_gh)
        self.assertEqual(code, 2)
        self.assertIn("scope nowhere does not exist at", err)

    def test_a_snapshot_folder_is_never_a_signal_or_churn(self):
        r = self.signals("--churn-min", "1", "--format", "json")
        self.assertEqual([c["path"] for c in r["churn"]["rows"] if "snapshots" in c["path"]], [])
        self.assertTrue(all("snapshots" not in f for c in r["signal_commits"]["rows"] for f in c["files"]))

    def test_churn_counts_files_that_exist_at_the_rev(self):
        r = self.signals("--churn-min", "3", "--format", "json")
        self.assertEqual(r["churn"]["rows"], [{"path": "core/a.py", "commits": 5}])

    def test_markdown_is_the_default_and_names_each_section(self):
        out = self.signals()
        self.assertTrue(out.startswith("# History signals for repo at %s\n" % self.head[:7]))
        for h in ("leads, not requirements", "## Signal commits (3)", "## High-churn files (1)", "## Merged PRs (0)", "## Issues (0)", "- unavailable: gh is not available"):
            self.assertIn(h, out)
        self.assertNotIn("Deleted", out)
        self.assertIn("[fix,timeout] fix: handle a timeout in a | files: core/a.py", out)

    def test_limit_cuts_a_list_and_says_how_many(self):
        out = self.signals("--limit", "1")
        self.assertIn("(2 more rows cut by --limit)", out)
        self.assertEqual(self.signals("--limit", "1", "--format", "json")["signal_commits"]["cut"], 2)

    def test_merged_prs_are_kept_by_ancestry_not_date_and_the_cap_is_reported(self):
        prs = [{"number": 5, "title": "Cache lookups", "labels": [{"name": "perf"}], "mergedAt": "2020-01-02T00:00:00Z", "mergeCommit": {"oid": self.perf}, "files": [{"path": "web/w.py"}]},
               {"number": 6, "title": "Core only", "labels": [], "mergedAt": "2020-01-03T00:00:00Z", "mergeCommit": {"oid": self.head}, "files": [{"path": "core/a.py"}]},
               {"number": 7, "title": "After the snapshot", "labels": [], "mergedAt": "2020-01-04T00:00:00Z", "mergeCommit": {"oid": self.after}, "files": [{"path": "web/w.py"}]},
               {"number": 8, "title": "No merge commit", "labels": [], "mergedAt": "2020-01-04T00:00:00Z", "mergeCommit": None, "files": [{"path": "web/w.py"}]}]
        with_gh, _, env = fake_gh(self.tmp, prs)
        r = self.signals("--scope", "web", "--format", "json", path=with_gh, env=env)
        self.assertEqual(r["merged_prs"]["rows"], [{"number": 5, "title": "Cache lookups", "labels": ["perf"], "merged": "2020-01-02"}])  # #7 is not an ancestor, #8 has no merge commit
        self.assertEqual((r["merged_prs"]["fetched"], r["merged_prs"]["cap"], r["merged_prs"]["cap_hit"], r["merged_prs"]["total"]), (4, 1000, False, 1))
        out = self.signals("--scope", "web", path=with_gh, env=env)
        self.assertIn("gh returned 4 (searches split by date, each under the cap of 1000), cap hit: no", out)
        self.assertIn("- #5 Cache lookups [perf] merged 2020-01-02", out)
        self.assertEqual(self.signals("--no-gh", "--format", "json", path=with_gh, env=env)["merged_prs"]["reason"], "--no-gh")
        calls = [json.loads(l) for l in Path(self.tmp, "gh.log").read_text().splitlines()]
        pr_call = next(c for c in calls if c[0] == "pr")
        self.assertIn("merged:2008-01-01..", pr_call[pr_call.index("--search") + 1])
        self.assertGreater(pr_call[pr_call.index("--search") + 1].split("..")[1], git(self.repo, "log", "-1", "--format=%cs", self.head))  # no cut at the commit's date
        self.assertIn("number,title,labels,mergedAt,mergeCommit", pr_call)
        self.assertNotIn("files", pr_call[-1])  # a scope is matched on the files git reports for the merge commit, not on gh's

    def many(self, per_day):
        """PRs, `per_day` for each (day, ...) given, every one merged at a commit that is an ancestor of the rev."""
        out, n = [], 0
        for day, count in per_day:
            for _ in range(count):
                n += 1
                out.append({"number": n, "title": "PR %d" % n, "labels": [], "mergedAt": day + "T00:00:00Z", "mergeCommit": {"oid": self.perf}})
        return out

    def test_a_search_that_returns_exactly_1000_is_split_by_date_until_every_window_is_under_the_cap(self):
        with_gh, _, env = fake_gh(self.tmp, self.many([("2020-01-01", 500), ("2020-01-02", 500)]))
        r = self.signals("--format", "json", path=with_gh, env=env)["merged_prs"]
        self.assertEqual((r["total"], r["fetched"], r["cap_hit"]), (1000, 1000, False))
        calls = [json.loads(l) for l in Path(self.tmp, "gh.log").read_text().splitlines() if json.loads(l)[0] == "pr"]
        self.assertGreater(len(calls), 1)  # the first, whole-range search came back with 1,000 and was split
        self.assertTrue(all(c[c.index("--limit") + 1] == "1000" for c in calls))

    def test_more_than_1000_in_all_are_found_by_splitting_and_none_is_counted_twice(self):
        with_gh, _, env = fake_gh(self.tmp, self.many([("2020-01-01", 600), ("2020-01-02", 600), ("2021-05-05", 3)]))
        r = self.signals("--format", "json", "--limit", "5", path=with_gh, env=env)["merged_prs"]
        self.assertEqual((r["total"], r["fetched"], r["cap_hit"], len(r["rows"])), (1203, 1203, False, 5))
        self.assertIn("## Merged PRs (1203)", self.signals(path=with_gh, env=env))

    def test_one_day_with_1000_or_more_still_says_the_cap_was_hit(self):
        with_gh, _, env = fake_gh(self.tmp, self.many([("2020-01-01", 1005)]))
        r = self.signals("--format", "json", path=with_gh, env=env)["merged_prs"]
        self.assertEqual((r["fetched"], r["cap_hit"]), (1000, True))
        self.assertIn("cap hit: yes: one day holds that many, so some are missing", self.signals(path=with_gh, env=env))

    def test_issues_are_split_the_same_way(self):
        issues = [{"number": n, "title": "I %d" % n, "state": "OPEN", "labels": [], "createdAt": ("2020-01-01" if n % 2 else "2020-01-02") + "T00:00:00Z", "body": ""} for n in range(1, 1201)]
        with_gh, _, env = fake_gh(self.tmp, None, issues)
        r = self.signals("--format", "json", path=with_gh, env=env)["issues"]
        self.assertEqual((r["total"], r["cap_hit"]), (1200, False))

    def test_issues_come_from_gh_and_a_scope_keeps_those_that_name_it(self):
        issues = [{"number": 3, "title": "web/w.py loses data", "state": "CLOSED", "labels": [], "createdAt": "2026-01-02T00:00:00Z", "body": ""},
                  {"number": 4, "title": "Slow start", "state": "OPEN", "labels": [{"name": "perf"}], "createdAt": "2026-01-03T00:00:00Z", "body": "see core/a.py"}]
        with_gh, _, env = fake_gh(self.tmp, None, issues)
        r = self.signals("--scope", "web", "--format", "json", path=with_gh, env=env)
        self.assertEqual([i["number"] for i in r["issues"]["rows"]], [3])
        self.assertEqual([i["number"] for i in self.signals("--format", "json", path=with_gh, env=env)["issues"]["rows"]], [4, 3])
        self.assertIn("- #3 web/w.py loses data (closed) [] created 2026-01-02", self.signals("--scope", "web", path=with_gh, env=env))
        call = next(json.loads(l) for l in Path(self.tmp, "gh.log").read_text().splitlines() if json.loads(l)[0] == "issue")
        self.assertIn("--state", call)
        self.assertEqual(call[call.index("--state") + 1], "all")

    def test_a_gh_that_fails_is_reported_not_fatal(self):
        r = self.signals("--format", "json", path=self.with_gh, env=dict(self.env, FAKE_GH_PRS="/nonexistent"))
        self.assertFalse(r["merged_prs"]["available"])
        self.assertIn("gh could not list prs", r["merged_prs"]["reason"])

    def test_a_folder_with_no_git_prints_no_git_history_and_exits_0(self):
        plain = Path(self.tmp, "plain")
        plain.mkdir()
        code, out, err = script("history_signals.py", plain, path=self.no_gh)
        self.assertEqual((code, out), (0, "no git history\n"))
        self.assertEqual(json.loads(script("history_signals.py", plain, "--format", "json", path=self.no_gh)[1]), {"history": "no git history"})

    def test_bad_usage_and_an_unknown_rev_exit_2(self):
        self.assertEqual(script("history_signals.py")[0], 2)
        self.assertEqual(script("history_signals.py", self.repo, "--rev", "nope", path=self.no_gh)[0], 2)
        self.assertEqual(script("history_signals.py", self.repo, "--format", "xml")[0], 2)
        self.assertEqual(script("history_signals.py", self.repo, "--scope")[0], 2)


class SkillDocsTest(unittest.TestCase):
    SKILL = SKILLS / "distilling-requirements"
    TEXT = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    QUOTE = ("> Find the app's explicit and implicit state machines and document their states, invariants, and transition tables in one file. Identify invalid states or transitions "
             "the code can actually reach, with evidence, including through retries and concurrency. Prioritize confirmed bugs by impact, group related fixes into issues, then fix them "
             "with regression tests and keep the document updated.")

    def test_check_history_refs_runs_in_the_write_step_not_only_in_the_truth_check(self):
        lines = self.TEXT.splitlines()
        step10 = "\n".join(lines[next(i for i, l in enumerate(lines) if l.startswith("10. ")):][:4])
        self.assertEqual(sum(1 for l in lines[:next(i for i, l in enumerate(lines) if l.startswith("11. "))] if l.startswith("    - `python3 -I")), 3)  # three scripts, three sub-bullets
        self.assertIn("check_history_refs.py", step10)
        self.assertIn("only checker rounds count", (self.SKILL / "references" / "truth-check.md").read_text())
        self.assertNotIn("SKILL.md step 9", (self.SKILL / "scripts" / "check_truth.py").read_text())

    def test_the_description_names_the_new_scope_and_stays_under_the_limit(self):
        import re
        desc = re.search(r"^description: (.*)$", self.TEXT, re.M).group(1)
        self.assertLessEqual(len(desc), 850)
        for word in ("non-functional", "inferred", "snapshot", "history", "interview"):
            self.assertIn(word, desc)

    def test_every_reference_the_skill_links_exists_and_the_scripts_it_runs_exist(self):
        import re
        for ref in re.findall(r"\]\((references/[\w.-]+)\)", self.TEXT):
            self.assertTrue((self.SKILL / ref).is_file(), ref)
        for name in re.findall(r"<skill dir>/scripts/([\w]+\.py)", self.TEXT + (self.SKILL / "references/truth-check.md").read_text() + (self.SKILL / "references/history.md").read_text()):
            self.assertTrue((self.SKILL / "scripts" / name).is_file(), name)

    def test_the_quoted_prompt_is_word_for_word_and_the_keep_updated_part_is_replaced(self):
        self.assertIn(self.QUOTE + "\n", self.TEXT)
        self.assertIn("The \"keep the document updated\" part is replaced here by writing a new snapshot.", self.TEXT)

    def test_the_skill_says_the_snapshot_is_never_edited_and_never_a_root_file(self):
        self.assertIn("Do not edit the snapshot afterwards", self.TEXT)
        self.assertIn("Never write a root-level `REQUIREMENTS.md`", self.TEXT)
        self.assertIn("docs/snapshots/<YYYY-MM-DD>-<sha7>/REQUIREMENTS.md", self.TEXT)

    def test_the_other_two_snapshot_skills_say_the_same(self):
        design = (SKILLS / "designing-the-smallest-version/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("requirements/1", design.replace("including `requirements/1`", ""))
        self.assertIn("docs/snapshots/<YYYY-MM-DD>-<sha7>/DESIGN.md", design)
        self.assertIn("never write a root-level `DESIGN.md`", design)
        guide = (SKILLS / "deriving-readable-docs/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("docs/snapshots/<YYYY-MM-DD>-<sha7>/GUIDE.md", guide)
        for skill in ("deriving-readable-docs", "designing-the-smallest-version"):
            import re
            self.assertLessEqual(len(re.search(r"^description: (.*)$", (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"), re.M).group(1)), 1024)

    def test_a_row_is_classified_by_what_told_you_with_one_precedence_in_the_skill_and_the_shape(self):
        shape_md = (self.SKILL / "references/output-shape.md").read_text(encoding="utf-8")
        self.assertIn("A fix commit for behaviour the code still shows, with no doc, test, issue or owner stating it, is `inferred`", shape_md)
        self.assertIn("whether worded as an obligation or as a description", shape_md)
        self.assertIn("`inferred`: no such source says it; you conclude it from a pattern", shape_md)
        self.assertIn("`implicit`: only the code shows it", shape_md)
        # the rule is written once: SKILL.md links to it and does not restate it
        self.assertIn("apply the one rule in [references/output-shape.md]", self.TEXT)
        self.assertNotIn("first match wins", self.TEXT.lower())
        self.assertNotIn("A fix commit for behaviour", self.TEXT)
        self.assertNotIn("issue text and docs", self.TEXT.lower())
        self.assertIn("Pull what the repo's own words say the system does or must do", self.TEXT)  # step 2 matches the rule: description counts, not only obligation
        self.assertIn("- **Status** is", self.TEXT)

    def test_history_runs_before_the_interview_and_the_interview_asks_every_area_in_outcome_words(self):
        self.assertLess(self.TEXT.index("3. **History (mandatory)"), self.TEXT.index("4. **Interview (optional)"))
        text = (self.SKILL / "references/interview.md").read_text(encoding="utf-8")
        for phrase in ("Ask every area", "propose nothing and ask open", "solution-neutral outcome", "Do not list mechanisms", "| compatibility |", "disputed", "gains the `owner:` evidence and keeps its history refs", "in the caller's output folder", "answers at <sha7>"):
            self.assertIn(phrase, text)

    def test_history_md_says_leads_open_the_diff_one_row_per_behaviour_and_fold_signals(self):
        text = (self.SKILL / "references/history.md").read_text(encoding="utf-8")
        for phrase in ("Read the list as leads, not rows", "open the commit diff or the PR body", "one row per behaviour, not per commit", "add its ref to that row's `evidence`", "only picks leads", "changed your view"):
            self.assertIn(phrase, text)

    def test_all_three_skills_say_a_snapshot_is_never_evidence_and_a_stale_sha_means_leads_only(self):
        for skill in ("distilling-requirements", "deriving-readable-docs", "designing-the-smallest-version"):
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("docs/snapshots/", text)
            self.assertIn("is never evidence or a stated source", text, skill)
        self.assertIn("is stale: say so and use it only as leads", self.TEXT)
        self.assertIn("derived-docs/<repo-name>/<date>-<sha7>/GUIDE.md", (SKILLS / "deriving-readable-docs/SKILL.md").read_text(encoding="utf-8"))

    def test_the_interview_reference_asks_four_at_a_time_and_names_the_evidence_form(self):
        text = (self.SKILL / "references/interview.md").read_text(encoding="utf-8")
        self.assertIn("at most 4 questions at a time", text)
        self.assertIn("owner:interview <YYYY-MM-DD> Q<n>", text)
        for area in ("performance", "reliability and availability", "security and privacy", "maintainability", "operability and observability", "portability", "cost", "data retention"):
            self.assertIn("| " + area + " |", text)


if __name__ == "__main__":
    unittest.main()
