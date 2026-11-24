"""ci-main-status --threads REPO PR on GitHub, against a fake `gh` that answers the reviewThreads GraphQL query from a fixture.

The check is the unresolved-review-thread gate (playbook 580f3e02 step 3). Each test is one row of its decision table: a thread
counts when it is not resolved and not outdated; an unreadable or malformed answer is ERROR, never a pass.
The Gitea half is in tests/ci-main-status-gitea; the shim that runs the check before a merge is in tests/pr-body-check.

    python3 -m unittest discover -s tests/ci-main-status-threads -v
"""
import json
import os
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
    import json, os, sys
    args = sys.argv[1:]
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(json.dumps({"args": args, "urgent": os.environ.get("GH_URGENT"), "caller": os.environ.get("GH_CALLER")}) + "\\n")
    if args[:2] != ["api", "graphql"]:
        print("fake gh: unhandled " + " ".join(args), file=sys.stderr); sys.exit(1)
    fields = {args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1] for i, a in enumerate(args) if a in ("-f", "-F")}
    fixture = json.load(open(os.environ["FAKE_GH_FIXTURE"]))
    page = fixture["pages"].get(fields.get("after", ""))
    if page is None:
        print("fake gh: no page for cursor " + fields.get("after", ""), file=sys.stderr); sys.exit(1)
    if isinstance(page, str):
        print(page, file=sys.stderr); sys.exit(1)
    print(json.dumps(page))
''')


def node(resolved=False, outdated=False, path="a.py", line=3, body="Fix this\nlonger text", url="https://github.com/o/r/pull/5#discussion_r1", original=None):
    return {"isResolved": resolved, "isOutdated": outdated, "path": path, "line": line, "originalLine": original,
            "comments": {"nodes": [{"body": body, "url": url}]}}


def page(nodes, more=False, cursor=None):
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {"pageInfo": {"hasNextPage": more, "endCursor": cursor}, "nodes": nodes}}}}}


class Threads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "bin").mkdir()
        (t / "bin/gh").write_text(GH_FAKE.replace("\\\\\\\\n", "\\n"))
        (t / "bin/gh").chmod(0o755)
        self.log = t / "gh.log"
        self.fixture = t / "fixture.json"
        self.env = {**os.environ, "PATH": f"{t / 'bin'}:{os.environ['PATH']}", "FAKE_GH_LOG": str(self.log), "FAKE_GH_FIXTURE": str(self.fixture),
                    "HOME": str(t)}
        self.env.pop("GH_URGENT", None)
        self.env["CI_MAIN_STATUS_THREADS_LOG"] = str(t / "threads.jsonl")
        self.threads_log = t / "threads.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_threads(self, pages, *args):
        self.fixture.write_text(json.dumps({"pages": pages}))
        r = subprocess.run([sys.executable, str(SCRIPT), "--threads", *(args or ("o/r", "5"))], capture_output=True, text=True, env=self.env, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_no_threads_is_green(self):
        rc, out = self.run_threads({"": page([])})
        self.assertEqual((rc, out.strip()), (0, "o/r#5: GREEN  no unresolved review threads"))

    def test_only_resolved_threads_is_green_outdated_or_not(self):
        rc, out = self.run_threads({"": page([node(resolved=True), node(resolved=True, outdated=True)])})
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)

    def test_an_unresolved_outdated_thread_still_counts(self):
        # GitHub marks a thread outdated when the lines under it change, not when the finding is answered: only resolving it clears it.
        rc, out = self.run_threads({"": page([node(outdated=True, path="moved.py", line=None, original=12), node(resolved=True, outdated=True)])})
        self.assertEqual(rc, 1, out)
        self.assertIn("1 unresolved review thread", out)
        self.assertIn("moved.py:12", out)

    def test_an_unresolved_thread_is_red_and_names_path_line_first_line_and_url(self):
        rc, out = self.run_threads({"": page([node(resolved=True), node(path="src/x.py", line=42, body="\n  Use the helper\nmore", url="https://github.com/o/r/pull/5#discussion_r9")])})
        self.assertEqual(rc, 1, out)
        self.assertIn("o/r#5: RED  1 unresolved review thread:", out)
        self.assertIn("    src/x.py:42  Use the helper  https://github.com/o/r/pull/5#discussion_r9", out)
        self.assertNotIn("more", out)   # only the first line of the first comment

    def test_each_unresolved_thread_is_listed_and_counted(self):
        rc, out = self.run_threads({"": page([node(path="a.py", line=1), node(path="b.py", line=2)])})
        self.assertEqual(rc, 1, out)
        self.assertIn("2 unresolved review threads", out)
        self.assertIn("a.py:1", out)
        self.assertIn("b.py:2", out)

    def test_a_thread_on_a_line_that_moved_uses_the_original_line_and_a_file_level_thread_has_the_path_alone(self):
        rc, out = self.run_threads({"": page([node(path="a.py", line=None, original=7), node(path="b.py", line=None)])})
        self.assertEqual(rc, 1, out)
        self.assertIn("    a.py:7  ", out)
        self.assertRegex(out, r"    b\.py  Fix this")

    def test_a_later_page_is_read(self):
        rc, out = self.run_threads({"": page([node(resolved=True)], more=True, cursor="c1"), "c1": page([node(path="late.py", line=9)])})
        self.assertEqual(rc, 1, out)
        self.assertIn("late.py:9", out)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn("after=c1", self.calls()[1]["args"])

    def test_more_pages_without_a_cursor_fail_closed(self):
        rc, out = self.run_threads({"": page([], more=True, cursor=None)})
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)

    def test_graphql_errors_fail_closed_even_with_data(self):
        body = page([])
        body["errors"] = [{"message": "boom"}]
        rc, out = self.run_threads({"": body})
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR  cannot read review threads", out)

    def test_a_missing_pr_fails_closed(self):
        rc, out = self.run_threads({"": {"data": {"repository": {"pullRequest": None}}}})
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)

    def test_a_failing_gh_fails_closed(self):
        rc, out = self.run_threads({"": "HTTP 502: bad gateway"})
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR  cannot read review threads", out)
        self.assertIn("502", out)

    def test_a_thread_with_no_resolved_flag_fails_closed(self):
        broken = node()
        del broken["isResolved"]
        rc, out = self.run_threads({"": page([broken])})
        self.assertEqual(rc, 1, out)
        self.assertIn("malformed", out)

    def test_a_table_name_and_a_bare_name_name_their_repo_and_the_read_is_urgent_and_named(self):
        rc, out = self.run_threads({"": page([])}, "storycraft", "5")
        self.assertEqual((rc, out.split(":")[0]), (0, "StoryCraftTW/storycraft#5"))
        rc, out = self.run_threads({"": page([])}, "other", "5")
        self.assertEqual((rc, out.split(":")[0]), (0, "cartwmic/other#5"))
        for call in self.calls():
            self.assertEqual((call["urgent"], call["caller"]), ("1", "ci-main-status"))

    def logged(self):
        return [json.loads(line) for line in self.threads_log.read_text().splitlines()] if self.threads_log.exists() else []

    def test_every_run_leaves_one_log_line_with_the_repo_pr_forge_and_result(self):
        self.run_threads({"": page([])})
        self.run_threads({"": page([node(path="src/x.py", line=42, url="https://github.com/o/r/pull/5#discussion_r9"), node(path="y.py", line=1)])})
        self.run_threads({"": "HTTP 502: bad gateway"})
        passed, refused, errored = self.logged()
        for row in (passed, refused, errored):
            self.assertEqual(sorted(row), ["detail", "duration_ms", "exit", "forge", "pr", "repo", "result", "threads", "ts", "unresolved"])
            self.assertEqual((row["repo"], row["pr"], row["forge"]), ("o/r", 5, "github"))
        self.assertEqual((passed["result"], passed["unresolved"], passed["exit"], passed["threads"]), ("pass", 0, 0, []))
        self.assertEqual((refused["result"], refused["unresolved"], refused["exit"]), ("refused", 2, 1))
        self.assertEqual(refused["threads"][0], {"where": "src/x.py:42", "url": "https://github.com/o/r/pull/5#discussion_r9"})
        self.assertEqual((errored["result"], errored["unresolved"], errored["exit"]), ("error", None, 1))
        self.assertIn("502", errored["detail"])

    def test_a_usage_error_reads_nothing_and_logs_nothing(self):
        self.run_threads({"": page([])}, "o/r", "x")
        self.assertEqual(self.logged(), [])

    def test_a_log_that_cannot_be_written_is_a_note_and_the_verdict_stands(self):
        self.env["CI_MAIN_STATUS_THREADS_LOG"] = str(self.threads_log.parent / "no-such-dir-file" / "x" / ".." / "threads.jsonl")
        (self.threads_log.parent / "no-such-dir-file").write_text("a file where a directory is needed")
        rc, out = self.run_threads({"": page([node()])})
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)
        self.assertIn("could not write", out)

    def test_bad_arguments_are_a_usage_error(self):
        for args in (("o/r",), ("o/r", "x"), ("o/r", "0"), ("--pr", "5"), ("o/r", "5", "6")):
            rc, out = self.run_threads({"": page([])}, *args)
            self.assertEqual(rc, 1, (args, out))
            self.assertIn("usage: ci-main-status --threads", out)
        self.assertFalse(self.log.exists())   # no read was made

    def test_the_general_usage_line_names_threads(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("| --threads REPO PR", r.stderr)


if __name__ == "__main__":
    unittest.main()
