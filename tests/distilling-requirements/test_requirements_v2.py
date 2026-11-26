"""requirements/2: the snapshot header, the quality lens, the inferred kind, history evidence (check_shape.py, check_truth.py, surface_coverage.py),
and the two history scripts (check_history_refs.py, history_signals.py) run as the skill runs them. No network: a fake `gh` on PATH stands in for GitHub.
Run: python3 -I tests/distilling-requirements/test_requirements_v2.py"""
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

STATE = tempfile.mkdtemp(prefix="state-")
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

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
    if a[2] == "12":
        print("Retry the upload on timeout")
        sys.exit(0)
    print("GraphQL: Could not resolve to a PullRequest with the number of %%s." %% a[2], file=sys.stderr)
    sys.exit(1)
if a[:2] == ["pr", "list"]:
    print(open(os.environ["FAKE_GH_PRS"]).read())
    sys.exit(0)
sys.exit(2)
"""


def doc(rows, header=None, line=LINE, tail="## Run log\n\n- first pass\n"):
    h = {"shape": "requirements/2", "repo": "demo", "commit": SHA, "snapshot": "2026-11-26 at " + SHA, "scope": "whole repo", "repo-wide": "yes", "interview": "none",
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


def fake_gh(tmp, prs=None):
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
    return str(with_gh), str(without), dict(os.environ, FAKE_GH_PRS=str(Path(tmp, "prs.json")))


class ShapeTest(unittest.TestCase):
    def test_a_requirements_2_file_with_a_quality_inferred_row_and_history_evidence_is_ok(self):
        rows = [row(1, lens="quality", kind="inferred", evidence="src/a.py:1; commit:abcdef1; pr:12; issue:7"), row(2, lens="quality", kind="inferred", evidence="commit:abcdef1234567"),
                row(3, kind="explicit", status="accepted", evidence="owner:interview 2026-11-26 Q1")]
        self.assertEqual(shape(doc(rows, {"interview": "interview.md"})), (0, "ok\n"))

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
        self.assertEqual(shape(doc([row(1)], {"commit": "no-git", "snapshot": "2026-11-26 at no-git", "source": "archive"}, line=line)), (0, "ok\n"))

    def test_a_requirements_file_needs_a_run_log_and_no_longer_a_changelog(self):
        self.assertIn("missing section ## Run log", shape(doc([row(1)], tail="## Changelog\n\n- x\n"))[1])

    def test_the_enums_take_quality_and_inferred_and_refuse_others(self):
        self.assertIn("lens='speed'", shape(doc([row(1, lens="speed")]))[1])
        self.assertIn("kind='guessed'", shape(doc([row(1, kind="guessed")]))[1])

    def test_an_inferred_row_stays_proposed_and_accepted_needs_owner_evidence(self):
        self.assertIn("an inferred row has status proposed", shape(doc([row(1, kind="inferred", status="disputed", evidence="commit:abcdef1", note="Q-1")]))[1])
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


class HistoryRefsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = Path(self.tmp, "repo")
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.sha = commit(self.repo, {"a.py": "x\n"}, "fix: retry the upload on timeout")
        self.with_gh, self.no_gh, self.env = fake_gh(self.tmp)

    def resolve(self, evidence, path=None):
        Path(self.tmp, "R.md").write_text(doc([row(1, kind="inferred", evidence=evidence)]))
        return script("check_history_refs.py", Path(self.tmp, "R.md"), self.repo, env=self.env, path=path or self.with_gh)

    def test_a_real_commit_resolves_with_its_subject_and_a_fake_one_exits_1(self):
        code, out, _ = self.resolve("commit:" + self.sha[:9])
        self.assertEqual(code, 0)
        self.assertIn("R-1 | commit:%s | resolved | fix: retry the upload on timeout" % self.sha[:9], out)
        self.assertIn("resolved, claim not read-checked: R-1", out)
        code, out, _ = self.resolve("commit:%s; commit:deadbeef0" % self.sha[:9])
        self.assertEqual(code, 1)
        self.assertIn("R-1 | commit:deadbeef0 | UNRESOLVED | no such commit", out)
        self.assertIn("resolved, claim not read-checked: none", out)
        self.assertIn("unresolved: R-1 commit:deadbeef0", out)

    def test_a_pr_and_an_issue_resolve_through_gh_with_their_titles(self):
        code, out, _ = self.resolve("pr:12; issue:12")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("| resolved | Retry the upload on timeout"), 2)

    def test_a_pr_gh_does_not_find_is_listed_unresolved_without_failing_the_run(self):
        code, out, _ = self.resolve("pr:99")
        self.assertEqual(code, 0)
        self.assertIn("R-1 | pr:99 | UNRESOLVED | gh could not read it: GraphQL: Could not resolve to a PullRequest with the number of 99.", out)

    def test_without_gh_a_pr_is_listed_unresolved_and_a_commit_still_resolves(self):
        code, out, _ = self.resolve("pr:12; commit:" + self.sha[:9], path=self.no_gh)
        self.assertEqual(code, 0)
        self.assertIn("R-1 | pr:12 | UNRESOLVED | gh is not available", out)
        self.assertIn("| resolved |", out)

    def test_bad_usage_exits_2(self):
        self.assertEqual(script("check_history_refs.py")[0], 2)


class HistorySignalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = Path(self.tmp, "repo")
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, {"core/a.py": "1\n", "core/b.py": "1\n", "core/old.py": "1\n", "web/w.py": "1\n", "core/moved.py": "same text\n" * 5}, "initial import")
        commit(self.repo, {"core/a.py": "2\n"}, "fix: handle a timeout in a")
        commit(self.repo, {"core/a.py": "3\n", "web/w.py": "2\n"}, "perf: cache the lookup")
        commit(self.repo, {"core/a.py": "4\n"}, "Revert the cache")
        commit(self.repo, {"core/a.py": "5\n", "core/b.py": "2\n"}, "tidy a")
        commit(self.repo, {}, "drop old.py", remove=["core/old.py"])
        git(self.repo, "mv", "core/moved.py", "core/renamed.py")
        git(self.repo, "commit", "-q", "-m", "rename moved")
        self.head = git(self.repo, "rev-parse", "HEAD")
        commit(self.repo, {"core/a.py": "6\n"}, "fix a crash after the snapshot")
        self.with_gh, self.no_gh, self.env = fake_gh(self.tmp)

    def signals(self, *args, path=None, env=None):
        code, out, err = script("history_signals.py", self.repo, "--rev", self.head, *args, env=env or self.env, path=path or self.no_gh)
        self.assertEqual(code, 0, err)
        return json.loads(out) if "json" in args else out

    def test_signal_commits_are_matched_by_message_and_read_from_the_rev_not_the_working_tree(self):
        r = self.signals("--format", "json")
        by = {c["subject"]: c["signals"] for c in r["signal_commits"]["rows"]}
        self.assertEqual(by, {"fix: handle a timeout in a": ["fix", "timeout"], "perf: cache the lookup": ["perf"], "Revert the cache": ["revert"]})
        self.assertNotIn("fix a crash after the snapshot", by)
        self.assertEqual(r["rev"], self.head)

    def test_the_scope_keeps_only_history_that_touches_it(self):
        r = self.signals("--scope", "web", "--format", "json")
        self.assertEqual([c["subject"] for c in r["signal_commits"]["rows"]], ["perf: cache the lookup"])
        self.assertEqual(r["signal_commits"]["rows"][0]["files"], ["web/w.py"])
        self.assertEqual(r["scope"], ["web"])

    def test_churn_counts_files_that_still_exist_and_a_rename_is_not_a_deletion(self):
        r = self.signals("--churn-min", "3", "--format", "json")
        self.assertEqual(r["churn"]["rows"], [{"path": "core/a.py", "commits": 5}])
        self.assertEqual([d["path"] for d in r["deleted"]["rows"]], ["core/old.py"])
        self.assertEqual(r["deleted"]["rows"][0]["subject"], "drop old.py")

    def test_markdown_is_the_default_and_names_each_section(self):
        out = self.signals()
        self.assertTrue(out.startswith("# History signals for repo at %s\n" % self.head[:7]))
        for h in ("## Signal commits (3)", "## High-churn files (1)", "## Deleted paths (1): skip rows whose code was here", "## Merged PRs (0)", "- unavailable: gh is not available"):
            self.assertIn(h, out)
        self.assertIn("[fix,timeout] fix: handle a timeout in a | files: core/a.py", out)

    def test_limit_cuts_a_list_and_says_how_many(self):
        out = self.signals("--limit", "1")
        self.assertIn("(signal_commits: 2 more rows cut by --limit)", out)
        self.assertEqual(self.signals("--limit", "1", "--format", "json")["signal_commits"]["cut"], 2)

    def test_merged_prs_come_from_gh_filtered_by_scope_and_the_snapshot_date(self):
        prs = [{"number": 5, "title": "Cache lookups", "labels": [{"name": "perf"}], "mergedAt": "2000-01-02T00:00:00Z", "files": [{"path": "web/w.py"}]},
               {"number": 6, "title": "Core only", "labels": [], "mergedAt": "2000-01-03T00:00:00Z", "files": [{"path": "core/a.py"}]},
               {"number": 7, "title": "After the snapshot", "labels": [], "mergedAt": "2999-01-01T00:00:00Z", "files": [{"path": "web/w.py"}]}]
        with_gh, _, env = fake_gh(self.tmp, prs)
        r = self.signals("--scope", "web", "--format", "json", path=with_gh, env=env)
        self.assertEqual(r["merged_prs"]["rows"], [{"number": 5, "title": "Cache lookups", "labels": ["perf"], "merged": "2000-01-02"}])
        self.assertTrue(r["merged_prs"]["available"])
        self.assertIn("- #5 Cache lookups [perf] merged 2000-01-02", self.signals("--scope", "web", path=with_gh, env=env))
        self.assertEqual(self.signals("--scope", "web", "--no-prs", "--format", "json", path=with_gh, env=env)["merged_prs"]["reason"], "--no-prs")

    def test_a_gh_that_fails_is_reported_not_fatal(self):
        r = self.signals("--format", "json", path=self.with_gh, env=dict(self.env, FAKE_GH_PRS="/nonexistent"))
        self.assertFalse(r["merged_prs"]["available"])
        self.assertIn("gh could not list PRs", r["merged_prs"]["reason"])

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

    def test_the_description_names_the_new_scope_and_stays_under_the_limit(self):
        import re
        desc = re.search(r"^description: (.*)$", self.TEXT, re.M).group(1)
        self.assertLessEqual(len(desc), 1024)
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

    def test_the_interview_reference_asks_four_at_a_time_and_names_the_evidence_form(self):
        text = (self.SKILL / "references/interview.md").read_text(encoding="utf-8")
        self.assertIn("at most 4 questions at a time", text)
        self.assertIn("owner:interview <YYYY-MM-DD> Q<n>", text)
        for area in ("performance", "reliability and availability", "security and privacy", "maintainability", "operability and observability", "portability", "cost", "data retention"):
            self.assertIn("| " + area + " |", text)


if __name__ == "__main__":
    unittest.main()
