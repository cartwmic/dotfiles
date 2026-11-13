"""`leak-guard text FILE...`: both layers on files of text (a PR body, a comment, release notes), as a process, with a fake `claude` and invented terms.

Every term is invented: "fooco" is term 1 and "bar.*baz" is term 2 of the test terms file.
"""
import json
import unittest

from test_leak_guard import Base


class TextBase(Base):
    def txt(self, name, content):
        d = self.tmp / "texts"
        d.mkdir(exist_ok=True)
        (d / name).write_text(content)
        return str(d / name)

    def result(self, *args, env=None):
        out = self.tmp / "result.json"
        done = self.guard("text", "--result", str(out), *args, env=env)
        return done, (json.loads(out.read_text()) if out.exists() else None)


class TextTerms(TextBase):
    def test_a_term_hit_blocks_names_file_line_and_term_number_and_never_calls_claude(self):
        path = self.txt("body.txt", "a fine line\nthis names FooCo here\n")
        done = self.guard("text", path)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("body.txt:2: term 1", done.stderr)
        self.assertIn("layer 1", done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_every_hit_in_every_file_is_listed_with_its_term_number(self):
        a = self.txt("title.txt", "bar then baz\n")
        b = self.txt("body.txt", "clean\nFOOCO\n")
        done = self.guard("text", a, b)
        self.assertEqual(done.returncode, 1)
        self.assertIn("title.txt:1: term 2", done.stderr)
        self.assertIn("body.txt:2: term 1", done.stderr)

    def test_the_hit_is_blocked_whatever_claude_would_say_and_a_clean_text_passes_layer_1(self):
        clean = self.txt("body.txt", "nothing to see here\n")
        done = self.guard("text", clean)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 1)

    def test_the_override_hint_names_the_command_not_git(self):
        done = self.guard("text", self.txt("body.txt", "fooco\n"))
        self.assertIn("LEAK_GUARD_SKIP", done.stderr)
        self.assertNotIn("--no-verify", done.stderr)


class TextLayer2(TextBase):
    def test_a_clean_answer_passes_and_the_text_of_every_file_is_sent_with_the_context(self):
        a = self.txt("title.txt", "first file words\n")
        b = self.txt("body.txt", "second file words\nmore\n")
        done = self.guard("text", a, b)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 1)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("first file words", sent)
        self.assertIn("2: more", sent)
        self.assertIn("=== file: title.txt", sent)
        self.assertIn("=== file: body.txt", sent)
        self.assertIn("Fooco is the pretend employer", sent)
        self.assertIn("posted publicly on GitHub", sent)

    def test_a_leak_answer_blocks_with_exit_1_and_prints_the_findings(self):
        done = self.guard("text", self.txt("body.txt", "quiet words\n"), env={"FAKE_CLAUDE": "leak"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("BLOCKED by Claude (layer 2)", done.stderr)
        self.assertIn("names the employer", done.stderr)

    def test_the_call_has_no_tools_and_no_mcp_servers(self):
        self.guard("text", self.txt("body.txt", "quiet words\n"))
        args = json.loads((self.fake / "args.json").read_text())
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", args)

    def test_blank_only_and_empty_files_pass_without_a_claude_call(self):
        done = self.guard("text", self.txt("a.txt", "\n   \n\n"), self.txt("b.txt", ""))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_two_files_with_the_same_name_are_told_apart(self):
        d1 = self.tmp / "one"
        d2 = self.tmp / "two"
        d1.mkdir()
        d2.mkdir()
        (d1 / "body.txt").write_text("fine\n")
        (d2 / "body.txt").write_text("fooco\n")
        done = self.guard("text", str(d1 / "body.txt"), str(d2 / "body.txt"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("body.txt#2:1: term 1", done.stderr)


class TextFailsClosed(TextBase):
    def test_a_missing_claude_blocks(self):
        (self.bin / "claude").unlink()
        done = self.guard("text", self.txt("body.txt", "quiet words\n"), env={"PATH": "%s:/usr/bin:/bin" % self.bin})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("the claude CLI is not on PATH", done.stderr)

    def test_a_timeout_blocks(self):
        done = self.guard("text", self.txt("body.txt", "quiet words\n"), env={"FAKE_CLAUDE": "sleep", "LEAK_GUARD_TIMEOUT_S": "1"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("timed out", done.stderr)

    def test_a_failing_or_unparseable_claude_blocks(self):
        for mode in ("exit1", "error", "garbage", "badjson", "noleakkey", "contradict", "badfindings", "nonstring"):
            with self.subTest(mode):
                done = self.guard("text", self.txt("body.txt", "quiet words\n"), env={"FAKE_CLAUDE": mode})
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn("BLOCKED", done.stderr)

    def test_an_unreadable_file_blocks(self):
        done = self.guard("text", str(self.tmp / "no-such-file.txt"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("cannot read", done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_a_missing_terms_file_blocks(self):
        (self.home / ".config" / "leak-guard" / "terms").unlink()
        done = self.guard("text", self.txt("body.txt", "quiet words\n"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("terms file", done.stderr)

    def test_text_over_200_kb_blocks_and_sends_nothing(self):
        done = self.guard("text", self.txt("big.txt", "".join("line %d of an invented but long file\n" % i for i in range(8000))))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("over the 200 KB", done.stderr)
        self.assertEqual(self.calls(), 0)

    def test_no_file_argument_is_a_usage_error(self):
        for args in (("text",), ("text", "--result")):
            with self.subTest(args):
                done = self.guard(*args)
                self.assertEqual(done.returncode, 64)
                self.assertIn("usage:", done.stderr)


class TextLog(TextBase):
    def test_a_pass_and_a_block_are_logged_with_mode_text_and_no_text(self):
        self.guard("text", self.txt("body.txt", "an invented sentence about gardens\n"))
        self.guard("text", self.txt("bad.txt", "fooco is here\n"))
        ok, bad = self.log()[-2:]
        self.assertEqual((ok["mode"], ok["verdict"], ok["layer"], ok["findings"]), ("text", "pass", 2, 0))
        self.assertEqual((bad["mode"], bad["verdict"], bad["layer"], bad["findings"]), ("text", "block", 1, 1))
        for rec in (ok, bad):
            self.assertIn("duration_s", rec)
        raw = (self.home / ".local" / "state" / "leak-guard" / "log.jsonl").read_text()
        for secret in ("gardens", "fooco", "bad.txt", "body.txt"):
            self.assertNotIn(secret, raw)

    def test_the_skip_override_skips_both_layers_exits_0_and_is_logged_with_its_reason(self):
        done = self.guard("text", self.txt("bad.txt", "fooco is here\n"), env={"LEAK_GUARD_SKIP": "test reason"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 0)
        rec = self.log()[-1]
        self.assertEqual((rec["mode"], rec["verdict"], rec["layer"], rec["reason"]), ("text", "skip", "override", "test reason"))

    def test_result_file_carries_verdict_layer_and_findings(self):
        done, res = self.result(self.txt("body.txt", "quiet words\n"))
        self.assertEqual((done.returncode, res), (0, {"verdict": "pass", "layer": 2, "findings": 0}))
        done, res = self.result(self.txt("bad.txt", "fooco\nbar then baz\n"))
        self.assertEqual((done.returncode, res), (1, {"verdict": "block", "layer": 1, "findings": 2}))
        done, res = self.result(self.txt("body.txt", "quiet words\n"), env={"LEAK_GUARD_SKIP": "r"})
        self.assertEqual(res["verdict"], "skip")


if __name__ == "__main__":
    unittest.main()
