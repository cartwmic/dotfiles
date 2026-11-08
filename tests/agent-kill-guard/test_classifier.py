"""The pkill/killall classifier: what it refuses and what it lets through (dot_local/share/agent-harness/hooks/refuse_pattern_kill.py)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/share/agent-harness/hooks/refuse_pattern_kill.py"
sys.path.insert(0, str(SCRIPT.parent))
import refuse_pattern_kill as guard  # noqa: E402

REFUSED = [
    "pkill -f something-harmless",
    "pkill foo",
    "killall node",
    "/usr/bin/pkill -f x",
    "/usr/bin/killall Dock",
    "echo a && pkill -f x",
    "echo a; killall x",
    "echo a || pkill x",
    "ls | xargs pkill",
    "sleep 30 & pkill sleep",
    "sleep 30 &\npkill sleep",
    "sudo pkill -9 x",
    "sudo -u root killall x",
    "env FOO=1 pkill x",
    "FOO=1 pkill x",
    "nohup pkill x &",
    "time pkill x",
    "command pkill x",
    "timeout 5 pkill x",
    "sh -c 'pkill -f x'",
    "bash -lc \"echo a; pkill -f x\"",
    "zsh -c 'cd /tmp && killall x'",
    "sudo sh -c 'killall x'",
    "bash -c \"sh -c 'pkill x'\"",
    "echo $(pkill x)",
    "echo \"$(killall x)\"",
    "x=`pkill y`",
    "(pkill x)",
    "{ pkill x; }",
    "if true; then pkill x; fi",
    "for i in 1 2; do killall x; done",
    "find /tmp -name x -exec pkill y {} \\;",
    "eval 'pkill x'",
    "eval pkill x",
    "bash <<'EOF'\necho hi\npkill x\nEOF",
    "\\pkill x",
    "\"pkill\" x",
    "p''kill x",
    "cd /tmp && FOO=bar pkill -f x",
    "pkill -f \"sleep 30\" -P 1 2>/dev/null; true",
    "run-and-wake -- pkill x",
    "1>/dev/null pkill x",
]

ALLOWED = [
    "kill 123",
    "kill -9 123",
    "kill -TERM $!",
    "kgate cancel kgate-123",
    "echo pkill",
    "echo killall",
    "grep -rn pkill .",
    "git commit -m \"do not use pkill or killall\"",
    "git commit -F - <<'EOF'\nmention pkill here\nkillall too\nEOF",
    "cat <<EOF\npkill x\nEOF",
    "man pkill",
    "which killall",
    "ls pkill-notes",
    "pgrep -f foo",
    "pkill_helper --list",
    "pkillx",
    "sh -c 'echo pkill'",
    "bash -c \"echo hi && kill 5\"",
    "FOO=pkill echo hi",
    "echo hi # pkill x",
    "python3 -c 'print(1)'",
    "gh pr create --title t --body \"refuse pkill and killall\"",
    "kgate -- sh -c 'pkill -f x'",
    "run-and-wake -- kgate -- pkill x",
    "echo \"a;pkill b\"",
    "",
]


class Classifier(unittest.TestCase):
    def test_refused_forms(self):
        for cmd in REFUSED:
            with self.subTest(cmd=cmd):
                self.assertIn(guard.find_refused(cmd), ("pkill", "killall"), cmd)

    def test_allowed_forms(self):
        for cmd in ALLOWED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(guard.find_refused(cmd), cmd)


class Cli(unittest.TestCase):
    def run_guard(self, payload=None, args=()):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=json.dumps(payload) if payload is not None else "",
                              capture_output=True, text=True, timeout=30)

    def test_refusal_is_exit_2_with_the_reason_on_stderr(self):
        r = self.run_guard({"tool_name": "Bash", "tool_input": {"command": "pkill -f something-harmless"}})
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertIn("pkill is refused in agent sessions", r.stderr)
        self.assertIn("kill <pid>", r.stderr)
        self.assertIn("kgate cancel <id>", r.stderr)

    def test_allowed_command_is_silent_exit_0(self):
        r = self.run_guard({"tool_name": "Bash", "tool_input": {"command": "kill 123"}})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_command_flag(self):
        self.assertEqual(self.run_guard(args=["--command", "killall x"]).returncode, 2)
        self.assertEqual(self.run_guard(args=["--command", "kill 1"]).returncode, 0)

    def test_fails_open_on_input_it_cannot_read(self):
        for raw in ("", "not json", "[]", '{"tool_input": 5}', '{"tool_input": {"command": 7}}'):
            with self.subTest(raw=raw):
                r = subprocess.run([sys.executable, str(SCRIPT)], input=raw, capture_output=True, text=True, timeout=30)
                self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_codex_style_command_list(self):
        r = self.run_guard({"tool_input": {"command": ["pkill", "-f", "x"]}})
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
