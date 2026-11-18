"""The pi fallback: after claude's spend-limit / usage-limit 429, the same prompt goes to pi once, by the same contract and the same fail-closed rules.

Every term here is invented ("fooco" is the pretend employer); the fake `claude` comes from test_leak_guard, the fake `pi` is planted here.
"""
import json
import os
import shutil
import unittest

from test_leak_guard import Base

FAKE_PI = r'''#!/usr/bin/env python3
import json, os, sys, time
fake = os.environ["FAKE"]
json.dump(sys.argv[1:], open(os.path.join(fake, "pi-args.json"), "w"))
open(os.path.join(fake, "pi-stdin.txt"), "w").write(sys.stdin.read())
open(os.path.join(fake, "pi-calls"), "a").write("x")
mode = os.environ.get("FAKE_PI", "clean")
if mode == "clean":
    print('{"leak": false, "findings": []}')
elif mode == "leak":
    print('{"leak": true, "findings": [{"file": "body.txt", "line": 1, "text": "the pretend employer", "why": "names the employer", "name": "Zephyrine"}]}')
elif mode == "wrapped":
    print('Sure. {"leak": false, "findings": []} Done.')
elif mode == "garbage":
    print("looks fine to me")
elif mode == "exit1":
    sys.stderr.write("Error: no provider credential.\n"); sys.exit(1)
elif mode == "sleep":
    time.sleep(30)
'''


class PiBase(Base):
    def setUp(self):
        super().setUp()
        (self.bin / "pi").write_text(FAKE_PI)
        (self.bin / "pi").chmod(0o755)

    def body(self, text="a quiet invented sentence\n"):
        path = self.tmp / "body.txt"
        path.write_text(text)
        return str(path)

    def pi_calls(self):
        return len((self.fake / "pi-calls").read_text()) if (self.fake / "pi-calls").exists() else 0

    def pi_stdin(self):
        return (self.fake / "pi-stdin.txt").read_text()


class SpendLimitFallsBack(PiBase):
    def test_a_spend_limit_429_falls_back_to_pi_and_its_verdict_is_used(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), 1, "claude is called once")
        self.assertEqual(self.pi_calls(), 1, "pi is retried once, not more")
        self.assertEqual(self.pi_stdin(), (self.fake / "stdin.txt").read_text(), "the same prompt goes to pi")
        rec = self.log()[-1]
        self.assertEqual((rec["verdict"], rec["layer"], rec["judge"]), ("pass", 2, "pi"))
        self.assertIn("pi_s", rec)
        self.assertIn("claude_s", rec)

    def test_a_usage_limit_429_in_an_error_result_falls_back_too(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend_result", "FAKE_PI": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.pi_calls(), 1)
        self.assertEqual(self.log()[-1]["judge"], "pi")

    def test_the_pi_verdict_blocks_too_and_is_named_as_the_judge(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "leak"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("BLOCKED by the pi fallback (layer 2)", done.stderr)
        self.assertIn("names the employer", done.stderr)
        rec = self.log()[-1]
        self.assertEqual((rec["verdict"], rec["layer"], rec["judge"], rec["findings"]), ("block", 2, "pi", 1))

    def test_pi_runs_without_tools_extensions_mcp_or_a_session_in_an_empty_directory(self):
        self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "clean"})
        args = json.loads((self.fake / "pi-args.json").read_text())
        self.assertEqual(args[:1], ["-p"])
        self.assertNotIn("--provider", args)
        self.assertNotIn("--model", args)
        for flag in ("--no-tools", "--no-extensions", "--no-mcp", "--no-session"):
            self.assertIn(flag, args)
        sysprompt = args[args.index("--system-prompt") + 1]
        self.assertIn('"leak"', sysprompt)
        self.assertIn('"findings"', sysprompt)
        self.assertIn('"name"', sysprompt)

    def test_the_judge_pinned_in_the_config_dir_is_used_and_still_gets_the_safety_flags(self):
        (self.home / ".config" / "leak-guard" / "pi-judge").write_text("pi -p --provider pinprovider --model pinmodel\n")
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        args = json.loads((self.fake / "pi-args.json").read_text())
        self.assertEqual(args[args.index("--provider") + 1], "pinprovider")
        self.assertEqual(args[args.index("--model") + 1], "pinmodel")
        for flag in ("--no-tools", "--no-extensions", "--no-mcp", "--no-session"):
            self.assertIn(flag, args)

    def test_the_env_var_override_beats_the_pin(self):
        (self.home / ".config" / "leak-guard" / "pi-judge").write_text("pi -p --provider pinprovider --model pinmodel\n")
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "clean",
                                                    "LEAK_GUARD_PI": "pi -p --provider other --model other-model"})
        self.assertEqual(done.returncode, 0, done.stderr)
        args = json.loads((self.fake / "pi-args.json").read_text())
        self.assertEqual(args[args.index("--provider") + 1], "other")
        self.assertEqual(args[args.index("--model") + 1], "other-model")

    def test_pi_answers_wrapped_in_text_are_still_read(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "wrapped"})
        self.assertEqual(done.returncode, 0, done.stderr)


class NoFallbackOnOtherFailures(PiBase):
    def test_a_non_429_claude_failure_never_falls_back(self):
        for mode, why in (("exit1", "exited 1"), ("error", "reported an error"), ("garbage", "not the JSON"), ("badjson", "not the expected JSON")):
            with self.subTest(mode):
                (self.fake / "pi-calls").unlink(missing_ok=True)
                done = self.guard("text", self.body("a quiet %s sentence\n" % mode), env={"FAKE_CLAUDE": mode})
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn(why, done.stderr)
                self.assertEqual(self.pi_calls(), 0, "no pi retry for %s" % mode)

    def test_a_timeout_never_falls_back(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "sleep", "LEAK_GUARD_TIMEOUT_S": "1"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("timed out", done.stderr)
        self.assertEqual(self.pi_calls(), 0)

    def test_a_missing_claude_never_falls_back(self):
        (self.bin / "claude").unlink()
        done = self.guard("text", self.body(), env={"PATH": "%s:/usr/bin:/bin" % self.bin})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("the claude CLI is not on PATH", done.stderr)
        self.assertEqual(self.pi_calls(), 0)


class PiFailureBlocks(PiBase):
    def test_pi_failing_after_a_429_blocks_naming_both_failures(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "exit1"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("spend limit", done.stderr)
        self.assertIn("pi fallback exited 1", done.stderr)
        rec = self.log()[-1]
        self.assertEqual((rec["verdict"], rec["layer"]), ("block", 2))
        self.assertEqual(rec["reason"], "layer 2: claude spend limit; pi fallback exited 1")

    def test_an_unparseable_pi_answer_blocks(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "garbage"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("the pi fallback's answer was not the JSON object asked for", done.stderr)

    def test_a_pi_timeout_blocks(self):
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "sleep", "LEAK_GUARD_TIMEOUT_S": "1"})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("pi fallback gave no answer in 1 s (timed out)", done.stderr)

    def test_a_missing_pi_blocks(self):
        (self.bin / "pi").unlink()
        done = self.guard("text", self.body(), env={"FAKE_CLAUDE": "spend429", "FAKE_PI": "clean", "PATH": "%s:/usr/bin:/bin" % self.bin})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("the pi fallback (pi) is not on PATH", done.stderr)


if __name__ == "__main__":
    unittest.main()
