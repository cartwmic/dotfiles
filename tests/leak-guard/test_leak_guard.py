"""leak-guard, as a process, in a real git repo, with a fake `claude` on PATH and invented terms and context.

Every term here is invented ("fooco" is the pretend employer). The real terms live only in the work machine's own chezmoi data.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_leak-guard"
ZERO = "0" * 40

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
fake = os.environ["FAKE"]
json.dump(sys.argv[1:], open(os.path.join(fake, "args.json"), "w"))
open(os.path.join(fake, "stdin.txt"), "w").write(sys.stdin.read())
open(os.path.join(fake, "calls"), "a").write("x")
mode = os.environ.get("FAKE_CLAUDE", "clean")
def result(text, **kw):
    print(json.dumps([{"type": "system", "subtype": "init"}, {"type": "result", "result": text, "total_cost_usd": 0.0003, "is_error": False, **kw}]))
if mode == "clean":
    result('{"leak": false, "findings": []}')
elif mode == "leak":
    result('{"leak": true, "findings": [{"file": "notes.txt", "line": 1, "text": "the pretend employer", "why": "names the employer"}]}')
elif mode == "contradict":
    result('{"leak": false, "findings": [{"file": "notes.txt", "line": 1, "text": "x", "why": "looks like the employer"}]}')
elif mode == "badfindings":
    result('{"leak": false, "findings": "none"}')
elif mode == "nonstring":
    result(5)
elif mode == "marker":
    if "CHUNK2-MARKER" in open(os.path.join(fake, "stdin.txt")).read():
        result('{"leak": true, "findings": [{"file": "big.txt", "line": 1, "text": "marker", "why": "in this chunk"}]}')
    else:
        result('{"leak": false, "findings": []}')
elif mode == "wrapped":
    result('Sure. {"leak": false, "findings": []} Done.')
elif mode == "garbage":
    result("I think it looks fine to me.")
elif mode == "noleakkey":
    result('{"findings": []}')
elif mode == "badjson":
    print("not json at all")
elif mode == "error":
    result("Not logged in", is_error=True)
elif mode == "exit1":
    sys.stderr.write("Error: not signed in. Run claude login.\n"); sys.exit(1)
elif mode == "sleep":
    time.sleep(30)
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lg-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        (self.home / ".config" / "leak-guard").mkdir(parents=True)
        (self.home / ".config" / "leak-guard" / "terms").write_text("# invented\nfooco\nbar.*baz\n")
        (self.home / ".config" / "leak-guard" / "context").write_text("Fooco is the pretend employer. A work detail is anything naming it.\n")
        self.bin = self.tmp / "bin"
        self.fake = self.tmp / "fake"
        for d in (self.bin, self.fake):
            d.mkdir()
        (self.bin / "claude").write_text(FAKE_CLAUDE)
        (self.bin / "claude").chmod(0o755)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("hello\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args, check=True):
        env = {**os.environ, "HOME": str(self.home), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", "-C", str(self.repo), *args], check=check, capture_output=True, text=True, env=env)

    def guard(self, *args, stdin="", env=None, timeout=60):
        e = {**os.environ, "HOME": str(self.home), "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), **(env or {})}
        e.pop("XDG_STATE_HOME", None)
        e.pop("LEAK_GUARD_SKIP", None)
        e.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo, input=stdin, capture_output=True, text=True, env=e, timeout=timeout)

    def stage(self, name, text):
        (self.repo / name).write_text(text)
        self.git("add", name)

    def log(self):
        path = self.home / ".local" / "state" / "leak-guard" / "log.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def calls(self):
        return len((self.fake / "calls").read_text()) if (self.fake / "calls").exists() else 0


def load_guard():
    import importlib.machinery, importlib.util
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("leak_guard_under_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("leak_guard_under_test", loader))
    loader.exec_module(mod)
    return mod


class ParseRaw(unittest.TestCase):
    """parse_raw on synthetic `git diff-tree --pretty=raw --cc` output."""

    G = load_guard()
    SHA = "a" * 40

    def lines(self, text):
        return [(f, n, t) for f, n, t, c in self.G.parse_raw(text)[0]]

    def test_a_plain_commit_gives_headers_message_path_and_added_lines(self):
        text = ("commit %s\ntree x\nauthor A <a@a> 1 +0000\ncommitter C <c@c> 1 +0000\n\n    subject\n    body\n\n"
                "diff --git a/dir/f.txt b/dir/f.txt\nindex 1..2 100644\n--- a/dir/f.txt\n+++ b/dir/f.txt\n@@ -1,2 +1,3 @@\n keep\n-old\n+new one\n+new two\n" % self.SHA)
        got = self.lines(text)
        self.assertIn(("COMMIT-HEADER", 2, "author A <a@a> 1 +0000"), got)
        self.assertIn(("COMMIT-MESSAGE", 1, "subject"), got)
        self.assertIn(("COMMIT-MESSAGE", 2, "body"), got)
        self.assertIn(("dir/f.txt", 0, "(path) dir/f.txt"), got)
        self.assertIn(("dir/f.txt", 2, "new one"), got)
        self.assertIn(("dir/f.txt", 3, "new two"), got)
        self.assertNotIn(("dir/f.txt", 1, "keep"), got)

    def test_an_added_line_starting_with_two_pluses_is_kept_and_a_header_is_not_content(self):
        text = ("commit %s\ntree x\n\n    s\n\ndiff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -0,0 +1,2 @@\n+++ looks like a header\n++ and this\n" % self.SHA)
        got = self.lines(text)
        self.assertIn(("f", 1, "++ looks like a header"), got)
        self.assertEqual([t for f, n, t in got if f == "f" and n > 0], ["++ looks like a header", "+ and this"])

    def test_a_two_parent_merge_keeps_only_lines_new_against_both_parents(self):
        text = ("commit %s\ntree x\nparent p1\nparent p2\n\n    merge\n\ndiff --cc f\nindex 1,2..3\n--- a/f\n+++ b/f\n@@@ -1,2 -1,2 +1,3 @@@\n"
                "  both\n+ from the second parent\n +from the first parent\n++new in the merge\n- gone\n" % self.SHA)
        added = [(n, t) for f, n, t in self.lines(text) if f == "f" and n > 0]
        self.assertEqual(added, [(4, "new in the merge")])

    def test_an_octopus_merge_has_a_prefix_three_wide_and_its_own_lines_are_kept(self):
        text = ("commit %s\ntree x\nparent a\nparent b\nparent c\n\n    octopus\n\ndiff --cc f\nindex 1,2,3..4\n--- a/f\n+++ b/f\n"
                "@@@@ -1,1 -1,1 -1,1 +1,2 @@@@\n   keep\n+++x octopus own line\n++ +from two parents only\n" % self.SHA)
        added = [(n, t) for f, n, t in self.lines(text) if f == "f" and n > 0]
        self.assertEqual(added, [(2, "x octopus own line")])

    def test_function_context_after_the_hunk_header_does_not_change_the_prefix_width(self):
        text = ("commit %s\ntree x\nparent p1\nparent p2\n\n    merge\n\ndiff --cc f.py\nindex 1,2..3\n--- a/f.py\n+++ b/f.py\n"
                "@@@ -1,2 -1,2 +1,3 @@@ def work(+9, -8) @@@ trailing\n  both\n++new in the merge\n+ from one parent\n" % self.SHA)
        added = [(n, t) for f, n, t in self.lines(text) if f == "f.py" and n > 0]
        self.assertEqual(added, [(2, "new in the merge")])
        plain = ("commit %s\ntree x\n\n    s\n\ndiff --git a/g b/g\n--- a/g\n+++ b/g\n@@ -0,0 +5 @@ def f(+99)\n+line\n" % self.SHA)
        self.assertIn(("g", 5, "line"), self.lines(plain))

    def test_binary_files_are_reported_and_two_commits_are_told_apart(self):
        text = ("commit %s\ntree x\n\n    one\n\ndiff --git a/p.bin b/p.bin\nindex 1..2\nBinary files /dev/null and b/p.bin differ\n"
                "commit %s\ntree y\n\n    two\n\ndiff --git a/g b/g\n--- a/g\n+++ b/g\n@@ -0,0 +1 @@\n+line\n" % (self.SHA, "b" * 40))
        lines, binary = self.G.parse_raw(text)
        self.assertEqual(binary, ["p.bin"])
        self.assertIn(("g", 1, "line", "b" * 40), lines)
        self.assertEqual({c for f, n, t, c in lines if f == "COMMIT-MESSAGE"}, {self.SHA, "b" * 40})


class PreCommit(Base):
    def test_a_layer_1_hit_blocks_prints_file_line_term_and_never_calls_claude(self):
        self.stage("notes.txt", "fine line\nthis names FooCo here\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("notes.txt:2: fooco", done.stderr)
        self.assertIn("layer 1", done.stderr)
        self.assertEqual(self.calls(), 0)
        rec = self.log()[-1]
        self.assertEqual((rec["verdict"], rec["layer"], rec["findings"], rec["mode"]), ("block", 1, 1, "pre-commit"))

    def test_a_regex_term_matches_and_every_hit_is_listed(self):
        self.stage("a.txt", "bar then baz\nnothing\n")
        self.stage("b.txt", "FOOCO\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1)
        self.assertIn("a.txt:1: bar.*baz", done.stderr)
        self.assertIn("b.txt:1: fooco", done.stderr)

    def test_a_term_in_a_file_name_blocks(self):
        self.stage("fooco-notes.txt", "harmless text\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("fooco-notes.txt:0: fooco", done.stderr)

    def test_a_term_only_in_a_removed_line_does_not_block(self):
        (self.repo / "old.txt").write_text("fooco was here\nkeep\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "old", "--no-verify")
        self.stage("old.txt", "keep\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_claude_saying_leak_true_blocks_and_prints_the_findings(self):
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "leak"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("layer 2", done.stderr)
        self.assertIn("notes.txt:1: the pretend employer (names the employer)", done.stderr)
        self.assertEqual(self.log()[-1]["findings"], 1)

    def test_leak_false_passes_and_logs_the_call_time_and_cost(self):
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        rec = self.log()[-1]
        self.assertEqual((rec["verdict"], rec["layer"], rec["findings"]), ("pass", 2, 0))
        self.assertEqual(rec["cost_usd"], 0.0003)
        self.assertIn("claude_s", rec)
        self.assertIn("duration_s", rec)
        self.assertRegex(rec["utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(rec["head"], self.git("rev-parse", "HEAD").stdout.strip())

    def test_an_answer_with_text_around_the_json_is_still_read(self):
        self.stage("notes.txt", "a quiet sentence\n")
        self.assertEqual(self.guard("pre-commit", env={"FAKE_CLAUDE": "wrapped"}).returncode, 0)

    def test_claude_is_called_with_no_tools_no_mcp_the_haiku_model_and_the_context_and_added_lines(self):
        self.stage("notes.txt", "line one\nline two\n")
        self.guard("pre-commit")
        args = json.loads((self.fake / "args.json").read_text())
        self.assertEqual(args[:1], ["-p"])
        self.assertEqual(args[args.index("--model") + 1], "claude-haiku-5-5")
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(json.loads(args[args.index("--mcp-config") + 1]), {"mcpServers": {}})
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("Fooco is the pretend employer", sent)
        self.assertIn("=== file: notes.txt", sent)
        self.assertIn("1: line one", sent)
        self.assertIn("2: line two", sent)
        self.assertNotIn("README", sent)

    def test_unparseable_answers_block(self):
        for mode in ("garbage", "noleakkey", "badjson"):
            with self.subTest(mode):
                (self.fake / "calls").unlink(missing_ok=True)
                self.stage("notes.txt", "a quiet sentence %s\n" % mode)
                done = self.guard("pre-commit", env={"FAKE_CLAUDE": mode})
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn("BLOCKED", done.stderr)
                self.assertIn("layer 2", done.stderr)

    def test_a_missing_claude_blocks_with_the_step_and_the_override(self):
        (self.bin / "claude").unlink()
        self.stage("notes.txt", "a quiet sentence\n")
        env = {"PATH": "%s:/usr/bin:/bin" % self.bin}
        done = self.guard("pre-commit", env=env)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("the claude CLI is not on PATH", done.stderr)
        self.assertIn("LEAK_GUARD_SKIP", done.stderr)

    def test_not_signed_in_or_an_error_result_blocks_naming_the_step(self):
        for mode, text in (("exit1", "exited 1"), ("error", "reported an error: Not logged in")):
            with self.subTest(mode):
                self.stage("notes.txt", "a quiet sentence %s\n" % mode)
                done = self.guard("pre-commit", env={"FAKE_CLAUDE": mode})
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn(text, done.stderr)
                self.assertIn("layer 2", done.stderr)

    def test_a_timeout_blocks(self):
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "sleep", "LEAK_GUARD_TIMEOUT_S": "1"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("timed out", done.stderr)

    def test_an_oversized_change_blocks_and_is_not_truncated_or_sent(self):
        self.stage("big.txt", "".join("line %d of an invented but long file\n" % i for i in range(8000)))
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("commit smaller changes, or override", done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_the_override_passes_without_claude_and_logs_a_skip_with_the_reason(self):
        self.stage("notes.txt", "this names fooco\n")
        done = self.guard("pre-commit", env={"LEAK_GUARD_SKIP": "fixture for a test"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 0)
        rec = self.log()[-1]
        self.assertEqual((rec["verdict"], rec["layer"], rec["reason"], rec["mode"]), ("skip", "override", "fixture for a test", "pre-commit"))

    def test_a_missing_terms_or_context_file_blocks(self):
        self.stage("notes.txt", "a quiet sentence\n")
        (self.home / ".config" / "leak-guard" / "context").unlink()
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("context file", done.stderr)
        (self.home / ".config" / "leak-guard" / "terms").unlink()
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("terms file", done.stderr)

    def test_an_invalid_regex_in_the_terms_blocks(self):
        (self.home / ".config" / "leak-guard" / "terms").write_text("fooco\n(unclosed\n")
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("is not a valid regex", done.stderr)

    def test_nothing_staged_passes_without_claude(self):
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.log()[-1]["verdict"], "pass")

    def test_the_log_never_holds_the_diff(self):
        self.stage("notes.txt", "SECRET-LOOKING-TEXT-123 names fooco\n")
        self.guard("pre-commit")
        self.stage("other.txt", "another unmistakable sentence 456\n")
        self.guard("pre-commit")
        text = (self.home / ".local" / "state" / "leak-guard" / "log.jsonl").read_text()
        self.assertNotIn("SECRET-LOOKING-TEXT-123", text)
        self.assertNotIn("unmistakable", text)

    # --- names, renames, empty and binary files

    def test_a_plain_rename_to_a_term_name_blocks(self):
        (self.repo / "plain.txt").write_text("harmless\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "plain", "--no-verify")
        self.git("mv", "plain.txt", "fooco-renamed.txt")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("fooco-renamed.txt:0: fooco", done.stderr)

    def test_an_empty_new_file_with_a_term_in_its_name_blocks(self):
        (self.repo / "fooco-empty.txt").write_text("")
        self.git("add", "fooco-empty.txt")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("fooco-empty.txt:0: fooco", done.stderr)

    def test_a_binary_file_with_a_term_in_its_name_blocks_on_the_name(self):
        (self.repo / "fooco-image.bin").write_bytes(b"\x00\x01\x02 binary")
        self.git("add", "fooco-image.bin")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("fooco-image.bin:0: fooco", done.stderr)

    def test_a_binary_file_with_a_clean_name_is_blocked_because_it_cannot_be_read(self):
        (self.repo / "image.bin").write_bytes(b"\x00\x01\x02 fooco inside")
        self.git("add", "image.bin")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("binary", done.stderr)
        self.assertIn("image.bin", done.stderr)
        self.assertEqual(self.calls(), 0)
        override = self.guard("pre-commit", env={"LEAK_GUARD_SKIP": "reviewed the binary"})
        self.assertEqual(override.returncode, 0, override.stderr)

    def test_an_added_line_that_starts_with_two_pluses_is_a_line_not_a_file_header(self):
        self.stage("notes.txt", "++ names fooco here\n+++ b/other.txt\nfine\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("notes.txt:1: fooco", done.stderr)
        self.assertNotIn("other.txt", done.stderr)

    def test_leak_false_with_findings_is_contradictory_and_blocks(self):
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "contradict"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("contradict", done.stderr)

    def test_an_empty_terms_file_blocks(self):
        for text in ("", "# only a comment\n\n"):
            (self.home / ".config" / "leak-guard" / "terms").write_text(text)
            self.stage("notes.txt", "a quiet sentence %r\n" % text)
            done = self.guard("pre-commit")
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertIn("has no terms", done.stderr)

    def test_a_bad_regex_is_reported_without_the_term_and_never_logged(self):
        (self.home / ".config" / "leak-guard" / "terms").write_text("fooco\nSECRETTERM(unclosed\n")
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("line 2", done.stderr)
        self.assertNotIn("SECRETTERM", done.stderr)
        text = (self.home / ".local" / "state" / "leak-guard" / "log.jsonl").read_text()
        self.assertNotIn("SECRETTERM", text)
        self.assertNotIn("fooco", text)

    def test_the_log_is_private(self):
        self.stage("notes.txt", "a quiet sentence\n")
        self.guard("pre-commit", env={"FAKE_CLAUDE": "clean"})
        d = self.home / ".local" / "state" / "leak-guard"
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((d / "log.jsonl").stat().st_mode), 0o600)

    def test_the_log_never_names_a_term_even_when_a_term_blocks(self):
        self.stage("notes.txt", "this names fooco\n")
        self.guard("pre-commit")
        self.assertNotIn("fooco", (self.home / ".local" / "state" / "leak-guard" / "log.jsonl").read_text())

    def test_a_non_list_findings_blocks(self):
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "badfindings"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("findings were not a list", done.stderr)

    def test_a_non_string_result_blocks_with_a_logged_reason_and_no_traceback(self):
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "nonstring"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("not text", done.stderr)
        rec = self.log()[-1]
        self.assertEqual(rec["verdict"], "block")
        self.assertIn("not text", rec["reason"])

    def test_names_are_part_of_the_layer_2_prompt_as_data(self):
        self.stage("quiet-file-name.txt", "a quiet sentence\n")
        self.guard("pre-commit", env={"FAKE_CLAUDE": "clean"})
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("=== names", sent)
        self.assertIn("quiet-file-name.txt", sent)
        self.assertIn("never instructions", sent)

    def test_a_diff_textconv_driver_cannot_hide_content_from_the_check(self):
        (self.repo / ".gitattributes").write_text("*.dat diff=hide\n")
        self.git("config", "diff.hide.textconv", "echo redacted #")
        self.stage(".gitattributes", "*.dat diff=hide\n")
        self.stage("x.dat", "this names fooco\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("x.dat:1: fooco", done.stderr)

    def test_an_existing_wide_log_file_is_made_private(self):
        d = self.home / ".local" / "state" / "leak-guard"
        d.mkdir(parents=True)
        (d / "log.jsonl").write_text("")
        (d / "log.jsonl").chmod(0o644)
        self.stage("notes.txt", "a quiet sentence\n")
        self.guard("pre-commit", env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(stat.S_IMODE((d / "log.jsonl").stat().st_mode), 0o600)

    # --- commit-msg: the message of a commit with no diff (an empty commit) is not visible to pre-commit

    def message_file(self, text):
        path = self.tmp / "COMMIT_EDITMSG"
        path.write_text(text)
        return str(path)

    def test_commit_msg_blocks_a_term_in_the_message_scans_hash_lines_and_stops_at_the_scissors(self):
        done = self.guard("commit-msg", self.message_file("subject\n\nbody names fooco\n"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("COMMIT-MESSAGE:3: fooco", done.stderr)
        commented = self.guard("commit-msg", self.message_file("subject\n\n# a real line that git keeps with -m, naming fooco\n"))
        self.assertEqual(commented.returncode, 1, "a # line can be part of the message, so it is scanned; the override is the way out")
        scissors = "subject\n\nquiet body\n# ------------------------ >8 ------------------------\n# Do not modify or remove the line above.\ndiff --git a/x b/x\n+names fooco in the verbose diff\n"
        clean = self.guard("commit-msg", self.message_file(scissors))
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(self.calls(), 0, "layer 1 only: layer 2 reads the message at pre-push")
        self.assertEqual(self.log()[-1]["mode"], "commit-msg")

    def test_commit_msg_honours_the_override_and_fails_closed_without_the_file_or_terms(self):
        self.assertEqual(self.guard("commit-msg", self.message_file("fooco\n"), env={"LEAK_GUARD_SKIP": "by hand"}).returncode, 0)
        self.assertEqual(self.guard("commit-msg", str(self.tmp / "missing")).returncode, 1)
        self.assertEqual(self.guard("commit-msg").returncode, 64)
        (self.home / ".config" / "leak-guard" / "terms").unlink()
        self.assertEqual(self.guard("commit-msg", self.message_file("quiet\n")).returncode, 1)

    # --- the class: local git configuration must not change what the hook sees compared with what is pushed

    def test_a_replace_ref_blocks_pre_commit(self):
        self.stage("notes.txt", "a quiet sentence\n")
        self.git("commit", "-q", "-m", "one", "--no-verify")
        a = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("commit", "-q", "--allow-empty", "-m", "two", "--no-verify")
        b = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("replace", b, a)
        self.stage("more.txt", "quiet\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("replace", done.stderr)
        self.assertEqual(self.log()[-1]["reason"], "setup: replace refs exist")

    def test_a_grafts_file_blocks_pre_commit(self):
        (self.repo / ".git" / "info").mkdir(exist_ok=True)
        (self.repo / ".git" / "info" / "grafts").write_text("")
        self.stage("notes.txt", "a quiet sentence\n")
        done = self.guard("pre-commit", env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("grafts", done.stderr)
        self.assertEqual(self.log()[-1]["reason"], "setup: grafts file exists")

    def test_diff_prefix_settings_in_global_and_repo_config_do_not_confuse_the_header_parse(self):
        (self.home / ".gitconfig").write_text("[diff]\n\tnoprefix = true\n\tsrcPrefix = old/\n\tdstPrefix = new/\n")
        self.git("config", "diff.mnemonicPrefix", "true")
        self.stage("sub-dir-notes.txt", "names fooco here\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertRegex(done.stderr, r"(?m)^  sub-dir-notes\.txt:1: fooco$")

    def test_a_textconv_driver_and_an_external_diff_in_global_config_cannot_hide_content(self):
        (self.home / ".gitconfig").write_text('[diff "hide"]\n\ttextconv = echo redacted #\n[diff]\n\texternal = echo nothing-to-see #\n')
        self.stage(".gitattributes", "*.dat diff=hide\n")
        self.stage("x.dat", "this names fooco\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertRegex(done.stderr, r"(?m)^  x\.dat:1: fooco$")

    def test_a_global_color_setting_and_diff_algorithm_do_not_change_the_result(self):
        (self.home / ".gitconfig").write_text("[color]\n\tui = always\n[diff]\n\talgorithm = patience\n\tcolorMoved = zebra\n")
        self.stage("notes.txt", "names fooco\n")
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertRegex(done.stderr, r"(?m)^  notes\.txt:1: fooco$")

    def test_usage_errors_are_64(self):
        self.assertEqual(self.guard().returncode, 64)
        self.assertEqual(self.guard("pre-merge").returncode, 64)
        self.assertEqual(self.guard("--help").returncode, 0)


class PrePush(Base):
    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "main", "--no-verify")
        self.main = self.git("rev-parse", "HEAD").stdout.strip()

    def commit(self, name, text, message="change"):
        (self.repo / name).write_text(text)
        self.git("add", name)
        self.git("commit", "-q", "-m", message, "--no-verify")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def push_line(self, local, remote_sha=ZERO, ref="refs/heads/feature", remote_ref=None):
        return "%s %s %s %s\n" % (ref, local, remote_ref or ref, remote_sha)

    def test_a_new_branch_checks_only_its_own_commits_not_what_the_remote_has(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a quiet sentence\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("clean.txt", sent)
        self.assertNotIn("README", sent)
        self.assertEqual(self.log()[-1]["mode"], "pre-push")

    def test_a_new_branch_with_a_leak_in_its_first_of_two_commits_blocks(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("one.txt", "mentions fooco\n")
        tip = self.commit("two.txt", "clean\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("one.txt:1: fooco", done.stderr)

    def test_an_existing_branch_checks_remote_to_local_and_not_older_commits(self):
        self.git("checkout", "-q", "-b", "feature")
        old = self.commit("old.txt", "old text that names fooco\n")      # already on the remote, so never rechecked
        self.git("push", "-q", "origin", "feature", "--no-verify")
        tip = self.commit("new.txt", "new quiet text\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, old), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("new.txt", sent)
        self.assertNotIn("old.txt", sent)

    def test_an_existing_branch_with_a_new_leak_blocks(self):
        self.git("checkout", "-q", "-b", "feature")
        old = self.commit("old.txt", "fine\n")
        self.git("push", "-q", "origin", "feature", "--no-verify")
        tip = self.commit("new.txt", "now it names fooco\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, old))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("new.txt:1: fooco", done.stderr)

    def test_a_committed_rename_to_a_term_name_blocks_at_pre_push(self):
        self.git("checkout", "-q", "-b", "feature")
        old = self.commit("plain.txt", "harmless\n")
        self.git("push", "-q", "origin", "feature", "--no-verify")
        self.git("mv", "plain.txt", "fooco-renamed.txt")
        self.git("commit", "-q", "-m", "rename", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, old))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("fooco-renamed.txt:0: fooco", done.stderr)

    def test_a_new_branch_with_no_known_remote_base_is_blocked_not_scanned_from_the_start(self):
        lonely = self.tmp / "lonely"
        lonely.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(lonely)], check=True)
        other = self.tmp / "other.git"
        subprocess.run(["git", "init", "-q", "--bare", str(other)], check=True)
        self.git("remote", "add", "unfetched", str(other))
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a quiet sentence\n")
        done = self.guard("pre-push", "unfetched", str(other), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("no tracking refs for unfetched: run `git fetch unfetched`, then push again", done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_a_new_branch_is_checked_for_what_the_tracking_refs_lack_and_nothing_else(self):
        self.git("remote", "set-head", "origin", "main")
        self.git("checkout", "-q", "-b", "feature")
        self.commit("one.txt", "first\n")
        tip = self.commit("two.txt", "second\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("one.txt", sent)
        self.assertIn("two.txt", sent)
        self.assertNotIn("README", sent)

    def test_the_remote_ref_name_is_checked_not_only_the_local_one(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a quiet sentence\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/heads/main", remote_ref="refs/heads/fooco-branch"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("refs/heads/fooco-branch:0: fooco", done.stderr)

    def test_a_term_added_in_one_commit_and_removed_in_the_next_is_still_caught(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("notes.txt", "keep\nthis names fooco\n", message="add")
        tip = self.commit("notes.txt", "keep\n", message="remove it again")
        net = self.git("diff", "main", tip).stdout
        self.assertNotIn("fooco", net, "the net diff is clean: only the history holds the term")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("notes.txt:2: fooco", done.stderr)
        self.assertIn("[commit ", done.stderr)

    def test_a_file_added_and_deleted_across_commits_is_checked_for_its_name_and_content(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("temp.txt", "quiet\n", message="add")
        self.git("rm", "-q", "temp.txt")
        self.git("commit", "-q", "-m", "delete", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("temp.txt", (self.fake / "stdin.txt").read_text(), "the net diff is empty, yet the history's file is sent")

    def test_layer_2_is_given_every_commits_patch_not_only_the_net_diff(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("notes.txt", "keep\na subtle sentence added then removed\n", message="add")
        tip = self.commit("notes.txt", "keep\n", message="remove")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "leak"})
        self.assertEqual(done.returncode, 1, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("a subtle sentence added then removed", sent)

    # --- the selection design: one rev-list, one diff-tree

    def sent(self):
        return (self.fake / "stdin.txt").read_text()

    def test_content_already_on_another_remote_branch_is_not_sent(self):
        self.git("checkout", "-q", "-b", "other")
        self.commit("already-public.txt", "a line another branch already published\n")
        self.git("push", "-q", "origin", "other", "--no-verify")
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("fresh.txt", "a brand new line\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a brand new line", self.sent())
        self.assertNotIn("already published", self.sent())
        self.assertEqual(self.calls(), 1)

    def merge_fixture(self):
        """main and two branches that conflict on one file; both parents are already on the remote."""
        for name, text in (("left", "left side\n"), ("right", "right side\n")):
            self.git("checkout", "-q", "-b", name, "main")
            self.commit("shared.txt", text, message=name)
            self.git("push", "-q", "origin", name, "--no-verify")
        self.git("checkout", "-q", "left")
        self.git("merge", "-q", "right", check=False)            # conflicts on shared.txt

    def finish_merge(self, resolution, extra_file=None):
        (self.repo / "shared.txt").write_text(resolution)
        self.git("add", "shared.txt")
        if extra_file:
            (self.repo / extra_file[0]).write_text(extra_file[1])
            self.git("add", extra_file[0])
        self.git("commit", "-q", "-m", "merge", "--no-verify")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def test_a_merges_own_resolution_is_caught_and_its_parents_content_is_not_sent(self):
        self.merge_fixture()
        tip = self.finish_merge("resolved with fooco in it\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/heads/left"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("shared.txt:1: fooco", done.stderr)

    def test_a_clean_merge_resolution_passes_and_only_its_own_line_is_sent(self):
        self.merge_fixture()
        tip = self.finish_merge("a clean resolved line\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/heads/left"), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a clean resolved line", self.sent())
        self.assertNotIn("left side", self.sent())
        self.assertNotIn("right side", self.sent())

    def test_a_path_only_the_merge_adds_is_caught(self):
        self.merge_fixture()
        tip = self.finish_merge("resolved\n", extra_file=("fooco-added-in-merge.txt", "quiet\n"))
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/heads/left"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("fooco-added-in-merge.txt", done.stderr)

    def test_an_octopus_merges_own_added_line_is_kept_and_checked(self):
        for name in ("one", "two", "three"):
            self.git("checkout", "-q", "-b", name, "main")
            self.commit("%s.txt" % name, "%s\n" % name, message=name)
            self.git("push", "-q", "origin", name, "--no-verify")
        self.git("checkout", "-q", "one")
        self.git("merge", "-q", "--no-commit", "two", "three")
        (self.repo / "extra.txt").write_text("an octopus extra line naming fooco\n")
        self.git("add", "extra.txt")
        self.git("commit", "-q", "-m", "octopus", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(len(self.git("rev-list", "--parents", "-n", "1", tip).stdout.split()) - 1, 3)
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/heads/one"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("extra.txt:1: fooco", done.stderr)

    def test_a_merged_signed_tags_mergetag_header_is_checked(self):
        """git records a `mergetag` header (the merged tag's name, tagger and message) when a SIGNED tag is merged; this builds such a merge commit by hand."""
        self.git("checkout", "-q", "-b", "side", "main")
        side = self.commit("side.txt", "side\n", message="side")
        self.git("checkout", "-q", "-b", "feature", "main")
        feature = self.commit("feature.txt", "feature\n", message="feature")
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        raw = ("tree %s\nparent %s\nparent %s\nauthor t <t@t> 1700000000 +0000\ncommitter t <t@t> 1700000000 +0000\n"
               "mergetag object %s\n type commit\n tag v-side\n tagger T <t@t> 1700000000 +0000\n \n tag text that names fooco\n\nmerge the tag\n"
               % (tree, feature, side, side))
        made = subprocess.run(["git", "-C", str(self.repo), "hash-object", "-t", "commit", "-w", "--stdin"], input=raw, capture_output=True, text=True, check=True)
        tip = made.stdout.strip()
        self.assertIn("mergetag", self.git("cat-file", "-p", tip).stdout)
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("COMMIT-HEADER", done.stderr)
        self.assertIn("fooco", done.stderr)

    def test_an_empty_commit_with_a_term_in_its_message_is_blocked_at_pre_push(self):
        self.git("checkout", "-q", "-b", "feature")
        self.git("commit", "-q", "--allow-empty", "-m", "an empty commit that names fooco", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("COMMIT-MESSAGE:1: fooco", done.stderr)

    def test_an_empty_commit_with_a_term_in_its_author_is_blocked_at_pre_push(self):
        self.git("checkout", "-q", "-b", "feature")
        env = {**os.environ, "HOME": str(self.home), "GIT_AUTHOR_NAME": "Someone", "GIT_AUTHOR_EMAIL": "someone@fooco.example", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "nothing to see", "--no-verify"], check=True, env=env, capture_output=True)
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("COMMIT-HEADER", done.stderr)

    def test_a_clean_empty_commit_passes_and_its_message_is_sent_to_claude(self):
        self.git("checkout", "-q", "-b", "feature")
        self.git("commit", "-q", "--allow-empty", "-m", "a quiet empty commit message", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a quiet empty commit message", self.sent())

    def test_a_remote_sha_notice_is_logged_as_a_code_not_only_printed(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("new.txt", "a quiet line\n")
        self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, "a" * 40), env={"FAKE_CLAUDE": "clean"})
        rec = self.log()[-1]
        self.assertEqual(rec["notes"], ["remote_sha_unknown"])
        self.assertNotIn("a" * 40, json.dumps(rec))

    def test_the_log_reason_never_holds_a_path_a_ref_or_claudes_words(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("clean.txt", "quiet\n")
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tree, ref="refs/tags/secret-ref-name"))
        (self.repo / "secret-picture-name.bin").write_bytes(b"\x00\x01 binary")
        self.git("add", "secret-picture-name.bin")
        self.guard("pre-commit")
        self.stage("notes.txt", "a quiet sentence\n")
        self.guard("pre-commit", env={"FAKE_CLAUDE": "error"})
        text = (self.home / ".local" / "state" / "leak-guard" / "log.jsonl").read_text()
        for word in ("secret-ref-name", "secret-picture-name", "Not logged in"):
            self.assertNotIn(word, text)
        reasons = [r.get("reason") for r in self.log() if r.get("reason")]
        self.assertTrue(any("peels" in r for r in reasons), reasons)
        self.assertTrue(any("binary" in r for r in reasons), reasons)

    def test_diff_prefix_settings_do_not_confuse_the_pre_push_header_parse(self):
        (self.home / ".gitconfig").write_text("[diff]\n\tnoprefix = true\n")
        self.git("config", "diff.mnemonicPrefix", "true")
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("sub-dir-notes.txt", "names fooco here\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertRegex(done.stderr, r"(?m)^  sub-dir-notes\.txt:1: fooco")
        self.assertNotRegex(done.stderr, r"sub-dir-notes\.txt sub-dir-notes\.txt")

    def test_a_replace_ref_that_hides_a_leaky_commit_blocks_the_push(self):
        self.git("checkout", "-q", "-b", "feature")
        clean = self.commit("notes.txt", "a quiet sentence\n", message="clean")
        leaky = self.commit("notes.txt", "this names fooco\n", message="leaky")
        self.git("replace", leaky, clean)
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(leaky), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("replace", done.stderr)

    def test_a_grafts_file_blocks_the_push(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("notes.txt", "a quiet sentence\n")
        (self.repo / ".git" / "info").mkdir(exist_ok=True)
        (self.repo / ".git" / "info" / "grafts").write_text("")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("grafts", done.stderr)

    def test_a_pushurl_that_differs_from_the_url_is_mapped_to_its_remote(self):
        other = self.tmp / "pushto.git"
        subprocess.run(["git", "init", "-q", "--bare", str(other)], check=True)
        self.git("remote", "set-url", "--push", "origin", str(other))
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("fresh.txt", "a brand new line\n")
        done = self.guard("pre-push", str(other), str(other), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a brand new line", self.sent())
        self.assertNotIn("hello", self.sent(), "origin's tracking refs excluded the base commit")

    def test_a_tag_pointing_at_a_tag_is_peeled_and_every_tag_object_is_checked(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("clean.txt", "a quiet sentence\n")
        self.git("tag", "-a", "inner", "-m", "inner tag message naming fooco")
        self.git("tag", "-a", "outer", "-m", "a quiet outer message", "inner")
        outer = self.git("rev-parse", "outer").stdout.strip()
        self.assertEqual(self.git("cat-file", "-t", outer).stdout.strip(), "tag")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(outer, ref="refs/tags/outer"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("TAG-OBJECT", done.stderr)
        self.assertIn("fooco", done.stderr)

    def test_a_remote_with_no_branches_says_so_and_points_to_the_override(self):
        empty = self.tmp / "empty.git"
        subprocess.run(["git", "init", "-q", "--bare", str(empty)], check=True)
        self.git("remote", "add", "fresh", str(empty))
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("fresh.txt", "a brand new line\n")
        done = self.guard("pre-push", "fresh", str(empty), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("empty", done.stderr)
        self.assertIn("LEAK_GUARD_SKIP", done.stderr)
        self.assertIn("first push", done.stderr)

    def test_author_committer_and_tagger_identities_are_checked(self):
        self.git("checkout", "-q", "-b", "feature")
        (self.repo / "clean.txt").write_text("quiet\n")
        self.git("add", "clean.txt")
        env = {**os.environ, "HOME": str(self.home), "GIT_AUTHOR_NAME": "Someone", "GIT_AUTHOR_EMAIL": "someone@fooco.example", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "clean", "--no-verify"], check=True, env=env, capture_output=True)
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("COMMIT-HEADER", done.stderr)
        # a tagger
        self.git("reset", "-q", "--hard", "main")
        self.commit("clean2.txt", "quiet\n")
        env2 = {**os.environ, "HOME": str(self.home), "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "tagger@fooco.example"}
        subprocess.run(["git", "-C", str(self.repo), "tag", "-a", "vt", "-m", "release"], check=True, env=env2, capture_output=True)
        tag = self.git("rev-parse", "vt").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tag, ref="refs/tags/vt"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("TAG-OBJECT", done.stderr)

    def test_a_hundred_rewrites_of_one_file_are_one_call_with_a_small_corpus(self):
        self.git("checkout", "-q", "-b", "feature")
        for i in range(100):
            tip = self.commit("churn.txt", "line a\nline b\n" if i % 2 else "line b\nline a\n", message="rewrite %d" % i)
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(self.sent().count("line a"), 1)
        self.assertEqual(self.sent().count("line b"), 1)
        self.assertEqual(self.log()[-1]["chunks"], 1)

    def big_branch(self, files=4, lines=4500):
        """Unique content past one chunk (180 KB), with a marker that lands in the second chunk."""
        self.git("checkout", "-q", "-b", "feature")
        for f in range(files):
            body = "".join("unique line %d of file %d, long enough to take up room in the chunk\n" % (i, f) for i in range(lines))
            if f == files - 1:
                body += "CHUNK2-MARKER\n"
            tip = self.commit("big%d.txt" % f, body, message="big %d" % f)
        return tip

    def test_a_corpus_over_the_chunk_size_is_split_and_a_leak_in_chunk_two_blocks(self):
        tip = self.big_branch()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "marker"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertGreaterEqual(self.calls(), 2)
        self.assertIn("in this chunk", done.stderr)
        self.assertGreaterEqual(self.log()[-1]["chunks"], 2)

    def test_every_chunk_must_pass_and_each_chunk_stays_under_the_cap(self):
        tip = self.big_branch()
        sizes = []
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertGreaterEqual(self.calls(), 2)
        self.assertLess(len((self.fake / "stdin.txt").read_bytes()), 200_000)
        self.assertGreaterEqual(self.log()[-1]["chunks"], 2)

    def test_a_chunk_that_fails_closed_blocks_the_whole_push(self):
        tip = self.big_branch()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "exit1"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("layer 2", done.stderr)

    def test_a_single_line_bigger_than_a_chunk_blocks(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("huge.txt", "x" * 200_000 + "\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("one line", done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_a_tag_or_ref_that_peels_to_a_tree_or_blob_blocks(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("clean.txt", "quiet\n")
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        blob = self.git("rev-parse", "HEAD:clean.txt").stdout.strip()
        for sha, what in ((tree, "tree"), (blob, "blob")):
            done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(sha, ref="refs/tags/odd"))
            self.assertEqual(done.returncode, 1, (what, done.stderr))
            self.assertIn("peels to a %s" % what, done.stderr)
        self.git("tag", "-a", "annotated-tree", "-m", "tag of a tree", tree)
        tag = self.git("rev-parse", "annotated-tree").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tag, ref="refs/tags/annotated-tree"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("peels to a tree", done.stderr)

    def test_a_binary_file_in_a_pushed_commit_blocks_and_names_the_path(self):
        self.git("checkout", "-q", "-b", "feature")
        (self.repo / "picture.bin").write_bytes(b"\x00\x01\x02 binary")
        self.git("add", "picture.bin")
        self.git("commit", "-q", "-m", "binary", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("binary", done.stderr)
        self.assertIn("picture.bin", done.stderr)

    def test_a_remote_sha_missing_locally_gives_a_notice_and_the_push_is_still_checked(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("new.txt", "this names fooco\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, "a" * 40))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("remote sha unknown", done.stderr)
        self.assertIn("run git fetch", done.stderr)
        self.assertIn("new.txt:1: fooco", done.stderr)

    def test_a_push_to_a_url_is_mapped_to_its_remote_and_uses_that_remotes_tracking_refs(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("fresh.txt", "a brand new line\n")
        done = self.guard("pre-push", str(self.remote), str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a brand new line", self.sent())
        self.assertNotIn("README", self.sent())
        self.assertNotIn("hello", self.sent())

    def test_a_push_to_a_url_that_matches_no_remote_is_blocked_with_the_fetch_hint(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("fresh.txt", "a brand new line\n")
        done = self.guard("pre-push", "/nowhere/else.git", "/nowhere/else.git", stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("matches no configured remote", done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_the_local_ref_name_is_not_checked_because_it_never_becomes_public(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a quiet sentence\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/heads/fooco-local", remote_ref="refs/heads/clean-name"), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_lightweight_tag_on_a_commit_enumerates_its_commits(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a tagged quiet sentence\n")
        self.git("tag", "light")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/tags/light"), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("a tagged quiet sentence", self.sent())

    def test_a_delete_only_push_makes_no_call_and_a_mixed_push_checks_the_rest(self):
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(ZERO, "a" * 40, ref="refs/heads/gone"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_branch_and_tag_names_are_checked(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a quiet sentence\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/heads/fooco-branch"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("refs/heads/fooco-branch:0: fooco", done.stderr)
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip, ref="refs/tags/v1-fooco"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("refs/tags/v1-fooco:0: fooco", done.stderr)

    def test_an_annotated_tag_message_is_checked(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("clean.txt", "a quiet sentence\n")
        self.git("tag", "-a", "v1", "-m", "release notes for fooco")
        tag = self.git("rev-parse", "v1").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tag, ref="refs/tags/v1"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("TAG-OBJECT:", done.stderr)
        self.assertIn("fooco", done.stderr)

    def test_a_leak_in_a_commit_message_blocks(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a quiet sentence\n", message="notes for fooco")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("COMMIT-MESSAGE:1: fooco", done.stderr)

    def test_a_commit_message_is_sent_to_claude_too(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("clean.txt", "a quiet sentence\n", message="subject line\n\nbody line")
        self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"FAKE_CLAUDE": "clean"})
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("=== file: COMMIT-MESSAGE", sent)
        self.assertIn("subject line", sent)
        self.assertIn("body line", sent)

    def test_each_pushed_ref_is_checked_and_a_deleted_ref_is_not(self):
        self.git("checkout", "-q", "-b", "one")
        one = self.commit("one.txt", "clean\n")
        self.git("checkout", "-q", "-b", "two", "main")
        two = self.commit("two.txt", "this names fooco\n")
        lines = self.push_line(one, ref="refs/heads/one") + self.push_line(two, ref="refs/heads/two") + self.push_line(ZERO, "a" * 40, ref="refs/heads/gone")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=lines)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("two.txt:1: fooco", done.stderr)
        only_delete = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(ZERO, "a" * 40, ref="refs/heads/gone"))
        self.assertEqual(only_delete.returncode, 0, only_delete.stderr)

    def test_the_override_works_for_a_push_too(self):
        self.git("checkout", "-q", "-b", "feature")
        tip = self.commit("one.txt", "mentions fooco\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env={"LEAK_GUARD_SKIP": "reviewed by hand"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.log()[-1]["verdict"], self.log()[-1]["mode"]), ("skip", "pre-push"))

    def test_installed_as_the_real_hooks_a_commit_and_a_push_are_guarded_and_no_verify_bypasses(self):
        hooks = self.repo / ".git" / "hooks"
        launcher = self.home / ".local" / "bin"
        launcher.mkdir(parents=True)
        shutil.copy(SCRIPT, launcher / "leak-guard")   # chezmoi gives the deployed script its executable bit
        (launcher / "leak-guard").chmod(0o755)
        for name in ("pre-commit", "commit-msg", "pre-push"):
            (hooks / name).write_text('#!/bin/sh\nexec "$HOME/.local/bin/leak-guard" %s "$@"\n' % name)
            (hooks / name).chmod(0o755)
        self.git("checkout", "-q", "-b", "feature")
        (self.repo / "leak.txt").write_text("fooco\n")
        self.git("add", "leak.txt")
        env = {**os.environ, "HOME": str(self.home), "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "FAKE_CLAUDE": "clean",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        env.pop("LEAK_GUARD_SKIP", None)
        run = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, text=True, env=env)
        blocked = run("commit", "-q", "-m", "leaky")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("BLOCKED by the terms list", blocked.stderr)
        run("reset", "-q")                      # nothing staged: an empty commit, whose message only commit-msg can see
        empty = run("commit", "-q", "--allow-empty", "-m", "an empty commit naming fooco")
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("COMMIT-MESSAGE:1: fooco", empty.stderr)
        run("add", "leak.txt")
        bypass = run("commit", "-q", "-m", "leaky", "--no-verify")
        self.assertEqual(bypass.returncode, 0, bypass.stderr)
        push = run("push", "-q", "origin", "feature")
        self.assertNotEqual(push.returncode, 0)
        self.assertIn("BLOCKED by the terms list", push.stderr)
        self.assertEqual(run("ls-remote", "--heads", str(self.remote), "feature").stdout.strip(), "", "nothing reached the remote")
        ok = run("push", "-q", "origin", "feature", "--no-verify")
        self.assertEqual(ok.returncode, 0, ok.stderr)


if __name__ == "__main__":
    unittest.main()
