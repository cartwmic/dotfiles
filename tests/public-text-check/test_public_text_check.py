"""Black-box test for dot_local/bin/executable_public-text-check: the check that refuses new public text carrying a private detail.

It runs the real command against the committed class table, with a made-up local terms file. Nothing reaches GitHub: `gh` is a stand-in on PATH. Every private-looking
string here is made up (10.0.0.9, host.internal.example, /home/someone, Pat Example).

    python3 -m unittest discover -s tests/public-text-check -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_public-text-check"
TABLE = ROOT / "dot_local/share/agent-harness/public-text-classes.json"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
pr = json.load(open(os.environ["FAKE_PR"]))
args = sys.argv[1:]
if args[:2] == ["api", "repos/someone/else"] or args[1] == "repos/cartwmic/hidden":
    print("true"); sys.exit(0)
if args[1] == "repos/cartwmic/unreadable":
    sys.stderr.write("HTTP 502\n"); sys.exit(1)
if args[1].count("/") == 2 and args[-1] == ".private":
    print("false"); sys.exit(0)
if args[-1].endswith("/commits"):
    print(json.dumps([[{"sha": "abcdef0123456789", "commit": {"message": m}} for m in pr["commits"]]]))
else:
    print(json.dumps({"title": pr["title"], "body": pr["body"]}))
'''

# One made-up string per class of the committed table (the second column is the class the check must name).
SAMPLES = {
    "home path": "see /home/someone/work/notes.md",
    "private address": "it listens on 10.0.0.9",
    "internal host name": "reach host.internal.example",
    "host or pod name": "the pod svc-0a1b2c3d4-x9y8z restarted",
    "runner log line": "kgate[kgate-1-2]: step one done",
    "user name": "(host h, user agent, cwd c)",
    "session folder": "saved under .t3/scratch/2026-01-01-demo-ab12cd34",
    "ledger or rule id": "approved in decision #1234",
    "email address or secret reference": "fetch op://vault/item/field",
    "owner name": "Pat Example said yes",
}

# More made-up strings, one for each other way a class can match (an alternative of its pattern), so removing any one alternative fails a test.
MORE = [
    ("home path", "/Users/pat/work"), ("home path", "/root/.ssh/config"),
    ("private address", "192.168.1.20"), ("private address", "172.16.4.4"),
    ("internal host name", "box.lan"), ("internal host name", "nas.home.arpa"), ("internal host name", "svc.ns.cluster.local"),
    ("host or pod name", "node=worker-3"),
    ("runner log line", "kgate: control plane someone-host ready"),
    ("user name", "USER=pat"), ("user name", "user=root"), ("user name", "(host h, user agent, cwd c)"),
    ("session folder", "~/.claude/projects/-home-pat-demo"), ("session folder", "~/.local/share/coordinator/state"), ("session folder", "workstreams/some-sweep"),
    ("ledger or rule id", "rule 0a1b2c3d says no"), ("ledger or rule id", "see Ask #4321"), ("ledger or rule id", "Retro #12"),
    ("email address or secret reference", "write to pat@corp.test"), ("email address or secret reference", "op://vault/item"),
]


class PublicTextCheck(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="public-text-check-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "bin").mkdir()
        (self.dir / "bin/gh").write_text(FAKE_GH)
        (self.dir / "bin/gh").chmod(0o755)
        self.terms = self.dir / "terms"
        self.terms.write_text("# a local term\nowner name\tPat Example\n")
        self.state = self.dir / "state"
        self.pr = self.dir / "pr.json"
        self.pr.write_text(json.dumps({"title": "A clean title", "body": "A clean body.\n", "commits": ["a clean message"]}))

    def run_check(self, *args, env=None, repo="cartwmic/dotfiles"):
        full = dict(os.environ, PATH="%s:%s" % (self.dir / "bin", os.environ["PATH"]), PUBLIC_TEXT_CLASSES_FILE=str(TABLE), PUBLIC_TEXT_TERMS_FILE=str(self.terms),
                    XDG_STATE_HOME=str(self.state), FAKE_PR=str(self.pr))
        full.pop("PUBLIC_TEXT_SKIP", None)
        full.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPT), "--repo", repo, *args], capture_output=True, text=True, env=full)

    def body(self, text):
        path = self.dir / "body.md"
        path.write_text(text)
        return ["--file", "body=%s" % path]

    def records(self):
        path = self.state / "public-text-check/log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_each_class_is_refused_by_name_and_line_and_the_string_is_never_printed(self):
        for name, sample in SAMPLES.items():
            with self.subTest(name):
                result = self.run_check(*self.body("first line is clean\n" + sample + "\n"))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("body:2: " + name, result.stderr)
                for piece in ("/home/someone", "10.0.0.9", "internal.example", "0a1b2c3d4", "kgate[", "user agent", "2026-01-01", "#1234", "op://", "Pat Example"):
                    self.assertNotIn(piece, result.stdout + result.stderr)
                (rec,) = self.records()[-1:]
                self.assertEqual((rec["outcome"], rec["exit"]), ("refused", 1))
                self.assertEqual(rec["classes"], {name: 1})
                self.assertNotIn(sample, json.dumps(rec))

    def test_each_way_a_class_can_match_is_refused_with_that_class_and_the_case_does_not_matter(self):
        for name, text in MORE + [(n, t.upper()) for n, t in MORE] + [(n, t) for n, t in SAMPLES.items() if n != "owner name"]:
            with self.subTest(name, text=text if name != "owner name" else "?"):
                result = self.run_check(*self.body(text + "\n"))
                self.assertEqual(result.returncode, 1)
                self.assertIn("body:1: " + name, result.stderr)

    def test_python_and_javascript_read_every_pattern_alike_on_each_sample_in_both_cases(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        rows = json.loads(TABLE.read_text())["classes"]
        lines = [t for _, t in MORE] + [t for n, t in SAMPLES.items() if n != "owner name"] + ["a clean line", "user agent strings", "Decision #1234", "alice at example.com"]
        lines = lines + [x.upper() for x in lines] + [x.lower() for x in lines]
        script = "const [p,l]=JSON.parse(process.argv[1]);console.log(JSON.stringify(l.map(x=>p.map(r=>new RegExp(r,'iu').test(x)))))"
        done = subprocess.run([node, "-e", script, json.dumps([[r["pattern"] for r in rows], lines])], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        js = json.loads(done.stdout)
        import re
        py = [[bool(re.compile(r["pattern"], re.M | re.I).search(x)) for r in rows] for x in lines]
        self.assertEqual(py, js)

    def test_clean_text_passes_and_a_runner_line_in_a_title_is_a_scope_prefix_not_a_hit(self):
        self.assertEqual(self.run_check(*self.body("Closes #12. Nothing private here.\n")).returncode, 0)
        result = self.run_check("--title", "kgate: refuse a path outside the worktree")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_title_and_commit_messages_are_read_with_their_own_labels(self):
        git = lambda *a: subprocess.run(["git", "-C", str(self.dir / "repo"), *a], check=True, capture_output=True, text=True,
                                        env=dict(os.environ, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@x.test", GIT_COMMITTER_NAME="a", GIT_COMMITTER_EMAIL="a@x.test"))
        (self.dir / "repo").mkdir()
        git("init", "-q", "-b", "main")
        git("commit", "-q", "--allow-empty", "-m", "base")
        git("commit", "-q", "--allow-empty", "-m", "clean subject\n\nand a body line in /home/someone/x")
        result = self.run_check("--title", "Pat Example's title", "--commits", "HEAD~1..HEAD", "--git-dir", str(self.dir / "repo"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("title:1: owner name", result.stderr)
        self.assertRegex(result.stderr, r"commit [0-9a-f]{8}:3: home path")

    def test_a_pull_request_is_read_whole_from_github(self):
        self.pr.write_text(json.dumps({"title": "A clean title", "body": "ok\n", "commits": ["fine", "second\n\nran on host.internal.example"]}))
        result = self.run_check("--pr", "5")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr, r"commit abcdef01:3: internal host name")

    def test_a_private_repository_is_not_read_and_one_that_cannot_be_told_is_checked(self):
        result = self.run_check(*self.body(SAMPLES["home path"]), repo="cartwmic/hidden")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.records()[-1]["outcome"], "not-checked")
        result = self.run_check(*self.body(SAMPLES["home path"] + "\n"), repo="cartwmic/unreadable")
        self.assertEqual(result.returncode, 1)
        self.assertIn("body:1: home path", result.stderr)

    def test_a_logged_way_past_with_a_reason_is_counted(self):
        result = self.run_check(*self.body(SAMPLES["home path"] + "\n"), env={"PUBLIC_TEXT_SKIP": "the path is a made-up example"})
        self.assertEqual(result.returncode, 0)
        rec = self.records()[-1]
        self.assertEqual((rec["outcome"], rec["skip_reason"], rec["classes"]), ("skipped", "the path is a made-up example", {"home path": 1}))
        clean = self.run_check(*self.body("clean\n"), env={"PUBLIC_TEXT_SKIP": "not needed"})
        self.assertEqual(clean.returncode, 0)
        self.assertEqual(self.records()[-1]["outcome"], "pass")  # no hit: the variable does nothing and is not counted as a use

    def test_nothing_is_passed_when_the_check_cannot_run(self):
        for env, why in (({"PUBLIC_TEXT_CLASSES_FILE": str(self.dir / "missing.json")}, "table-unreadable"), ({"PUBLIC_TEXT_TERMS_FILE": str(self.dir)}, "terms-unreadable")):
            with self.subTest(why):
                result = self.run_check(*self.body("clean\n"), env=env)
                self.assertEqual(result.returncode, 2)
                self.assertIn("[public-text-check] ERROR: " + why, result.stderr)
        self.assertEqual(self.run_check().returncode, 2)  # nothing to check
        self.assertEqual(self.run_check("--file", "body=%s" % (self.dir / "nope")).returncode, 2)

    def test_a_machine_without_local_terms_checks_the_table_and_says_how_many_terms_it_read(self):
        self.terms.unlink()
        result = self.run_check(*self.body(SAMPLES["owner name"] + "\n"))
        self.assertEqual(result.returncode, 0)  # the name is only in the local terms
        self.assertEqual(self.records()[-1]["local_terms"], 0)
        self.assertEqual(self.run_check(*self.body(SAMPLES["home path"] + "\n")).returncode, 1)

    def test_a_missing_terms_file_is_said_in_one_line_and_changes_no_exit_status(self):
        line = "public-text-check: note: the private-terms file %s is missing on this machine, so names cannot be checked here; the shape patterns still run." % self.terms
        with_file = self.run_check(*self.body("clean\n"))
        self.assertNotIn("private-terms file", with_file.stderr)
        self.terms.unlink()
        clean = self.run_check(*self.body("clean\n"))
        self.assertEqual((clean.returncode, clean.stderr.strip()), (0, line))
        refused = self.run_check(*self.body(SAMPLES["home path"] + "\n"))
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(refused.stderr.count("private-terms file"), 1)

    def test_a_local_term_is_literal_case_insensitive_and_named_by_its_class(self):
        self.terms.write_text("owner name\tPat Example\nprivate thing.*\n")
        hit = self.run_check(*self.body("pat example said yes\n"))
        self.assertEqual(hit.returncode, 1)
        self.assertIn("body:1: owner name", hit.stderr)
        self.assertNotIn("pat example", hit.stderr.lower())  # the term is never echoed
        self.assertEqual(self.run_check(*self.body("Pat Examples\n")).returncode, 0)  # a word edge, not a substring
        literal = self.run_check(*self.body("a private thing.* here\n"))
        self.assertIn("body:1: private term", literal.stderr)  # no class name given
        self.assertEqual(self.run_check(*self.body("a private things here\n")).returncode, 0)  # the term is not a pattern

    def test_a_comment_is_read_with_the_rules_of_a_body(self):
        path = self.dir / "comment.md"
        path.write_text("kgate[kgate-1-2]: step\n")
        result = self.run_check("--file", "comment=%s" % path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("comment:1: runner log line", result.stderr)

    def test_home_path_lets_a_placeholder_name_pass_and_refuses_a_real_looking_one(self):
        for ok in ("/Users/alice/project/file.txt", "/home/bob/x", "/home/user/.config/y", "/Users/you/z"):
            with self.subTest(ok):
                self.assertEqual(self.run_check(*self.body(ok + "\n")).returncode, 0)
        for bad in ("/Users/alicia/project", "/home/pat/git/x", "/home/username2/x", "/root/.ssh"):
            with self.subTest(bad):
                self.assertEqual(self.run_check(*self.body(bad + "\n")).returncode, 1)

    def test_every_pattern_compiles_in_javascript_with_the_flags_iu_and_uses_no_python_only_syntax(self):
        patterns = [row["pattern"] for row in json.loads(TABLE.read_text())["classes"]]
        for forbidden in ("(?i", "(?P", "(?x", "(?s", "(?m", "\\A", "\\Z"):
            for pattern in patterns:
                self.assertNotIn(forbidden, pattern)
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed; the forbidden constructs were checked")
        script = "const p=JSON.parse(process.argv[1]);for(const x of p){new RegExp(x,'iu')}"
        done = subprocess.run([node, "-e", script, json.dumps(patterns)], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_a_table_row_names_only_title_body_and_commit(self):
        for row in json.loads(TABLE.read_text())["classes"]:
            self.assertLessEqual(set(row.get("surfaces", ())), {"title", "body", "commit"})

    def test_help_writes_no_record(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, env=dict(os.environ, XDG_STATE_HOME=str(self.state)))
        self.assertEqual(result.returncode, 0)
        self.assertIn("A false hit: PUBLIC_TEXT_SKIP", result.stdout)
        self.assertEqual(self.records(), [])

    def test_the_table_is_one_file_of_named_patterns_and_nothing_else_in_the_repo_repeats_them(self):
        table = json.loads(TABLE.read_text())
        self.assertEqual(set(table), {"classes"})
        for row in table["classes"]:
            self.assertEqual(set(row) - {"surfaces"}, {"name", "pattern"})
        script = SCRIPT.read_text()
        for row in table["classes"]:
            self.assertNotIn(row["pattern"], script)

    def test_the_table_has_a_sample_for_every_class(self):
        names = {c["name"] for c in json.loads(TABLE.read_text())["classes"]} | {"owner name"}
        self.assertEqual(names, set(SAMPLES))


if __name__ == "__main__":
    unittest.main()
