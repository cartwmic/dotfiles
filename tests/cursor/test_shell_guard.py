"""The Cursor hook file chezmoi renders has a preToolUse entry for Cursor's Shell tool that runs the same guards as Claude Code.

For both desktop profiles: real chezmoi renders dot_cursor/modify_hooks.json.tmpl, the script runs on an empty hooks.json, and the
exact command string of the guard entry runs through `sh -c` in a scratch HOME that holds the deployed adapter and copies of
the shared classifier (refuse_pattern_kill.py and bash_rules.py). The payloads are Cursor's preToolUse payloads.

    python3 -m unittest discover -s tests/cursor -p 'test_shell_guard*.py' -v
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
sys.path.insert(0, str(ROOT / "tests/shx"))
import test_agent_access as access  # the chezmoi helper, with the local data keys the work profile needs

os.environ.setdefault("AGENT_HARNESS_GUARD_LOG", os.devnull)  # the hook logs each refusal; a test run leaves no record in the real state dir

HOOKS_TMPL = ROOT / "dot_cursor/modify_hooks.json.tmpl"
ADAPTER = ROOT / "dot_cursor/hooks/executable_shell_guard.py"
HARNESS = ROOT / "dot_local/share/agent-harness/hooks"
PROFILES = ("personal", "axon-work-computer")


def shell(command, cwd="/tmp", tool="Shell"):
    return json.dumps({"hook_event_name": "preToolUse", "tool_name": tool, "tool_input": {"command": command, "cwd": cwd, "timeout": 30}})


def guard_command(profile):
    script = access.chezmoi(profile, "execute-template", stdin=HOOKS_TMPL.read_text())
    out = subprocess.run(["sh", "-c", script], input="", capture_output=True, text=True, timeout=30, check=True).stdout
    guards = [h for h in json.loads(out)["hooks"]["preToolUse"] if "shell_guard.py" in h["command"]]
    assert len(guards) == 1 and guards[0]["matcher"] == "Shell", guards
    return guards[0]["command"]


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class CursorShellGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp())
        (cls.home / ".cursor/hooks").mkdir(parents=True)
        shutil.copy(ADAPTER, cls.home / ".cursor/hooks/shell_guard.py")
        (cls.home / ".local/share/agent-harness/hooks").mkdir(parents=True)
        for name in ("refuse_pattern_kill.py", "bash_rules.py"):
            shutil.copy(HARNESS / name, cls.home / ".local/share/agent-harness/hooks" / name)
        cls.commands = {p: guard_command(p) for p in PROFILES}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def run_guard(self, profile, payload, home=None):
        return subprocess.run(["sh", "-c", self.commands[profile]], input=payload, capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, HOME=str(home or self.home)))

    def answer(self, profile, payload):
        r = self.run_guard(profile, payload)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return json.loads(r.stdout)

    def assertPasses(self, profile, payload, home=None):
        # Exit 1 with no output: Cursor reads that as "hook failed, action proceeds". Any other answer fails here.
        r = self.run_guard(profile, payload, home)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (1, "", ""))

    def assertDenied(self, profile, payload, text):
        out = self.answer(profile, payload)
        self.assertEqual(out["permission"], "deny", out)
        self.assertIn(text, out["user_message"])
        self.assertEqual(out["user_message"], out["agent_message"])

    def test_pkill_is_denied_with_the_guards_message(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertDenied(profile, shell("pkill -f x"), "pkill is refused in agent sessions")

    def test_a_sleep_poll_loop_is_denied(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertDenied(profile, shell("until test -f /tmp/done; do sleep 2; done"), "sleep-poll loop is refused in agent sessions")

    def test_a_harmless_command_another_tool_and_garbage_are_let_through(self):
        for profile in PROFILES:
            for name, payload in (("ls", shell("ls")), ("other tool", shell("pkill -f x", tool="Read")), ("garbage", "not json {"),
                                  ("empty", ""), ("array", "[1]")):
                with self.subTest(profile=profile, case=name):
                    self.assertPasses(profile, payload)

    def test_the_command_runs_in_the_directory_cursor_names(self):
        # The git rule looks at the session's directory; Cursor sends it inside tool_input, so the adapter has to hand it on.
        live = self.home / "git/coordinator"
        subprocess.run(["git", "init", "-q", str(live)], check=True)
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertDenied(profile, shell("git commit -m x", cwd=str(live)), "refused in agent sessions")
                self.assertPasses(profile, shell("git commit -m x", cwd="/tmp"))

    def test_a_missing_classifier_lets_the_command_through(self):
        home = Path(tempfile.mkdtemp())
        try:
            (home / ".cursor/hooks").mkdir(parents=True)
            shutil.copy(ADAPTER, home / ".cursor/hooks/shell_guard.py")
            self.assertPasses("personal", shell("pkill -f x"), home=home)
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
