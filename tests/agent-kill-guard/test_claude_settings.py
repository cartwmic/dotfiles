"""dot_claude/modify_settings.json.tmpl installs the pattern-kill guard (a PreToolUse hook on Bash and Monitor) on both desktop profiles,
replaces a stale copy of it, is idempotent, and leaves every other hook alone. Real chezmoi and jq, no real HOME."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "dot_claude/modify_settings.json.tmpl"
COMMAND = 'g="$HOME/.local/share/agent-harness/hooks/refuse_pattern_kill.py"; [ -r "$g" ] || exit 0; python3 "$g"; [ $? -eq 2 ] && exit 2; exit 0'
MARK = "refuse_pattern_kill.py"
USER_HOOK = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo user"}]}


def render(profile):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": {"profile": profile, "hub": {"enabled": False}}}))
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                           input=SETTINGS.read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=tmp))
    assert r.returncode == 0, r.stderr
    return r.stdout


def guards(settings):
    return [(g.get("matcher"), h["command"]) for g in settings.get("hooks", {}).get("PreToolUse", []) for h in g.get("hooks", []) if MARK in h.get("command", "")]


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class GuardSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.scripts = {}
        for profile in ("personal", "axon-work-computer"):
            cls.scripts[profile] = cls.tmp / ("modify-" + profile)
            cls.scripts[profile].write_text(render(profile))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def modify(self, profile, settings):
        r = subprocess.run(["sh", str(self.scripts[profile])], input=json.dumps(settings), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_both_profiles_get_exactly_one_guard_on_bash(self):
        for profile in self.scripts:
            with self.subTest(profile=profile):
                self.assertEqual(guards(self.modify(profile, {})), [("Bash|Monitor", COMMAND)])

    def test_user_hooks_and_other_keys_are_kept_and_it_is_idempotent(self):
        for profile in self.scripts:
            with self.subTest(profile=profile):
                start = {"theme": "dark", "hooks": {"PreToolUse": [USER_HOOK], "Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]}}
                once = self.modify(profile, start)
                self.assertEqual(once["theme"], "dark")
                self.assertIn(USER_HOOK, once["hooks"]["PreToolUse"])
                self.assertEqual(once["hooks"]["Stop"], start["hooks"]["Stop"])
                self.assertEqual(guards(once), [("Bash|Monitor", COMMAND)])
                self.assertEqual(self.modify(profile, once), once)

    def test_a_stale_copy_is_replaced_not_duplicated(self):
        stale = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 /old/path/agent-harness/hooks/refuse_pattern_kill.py"},
            {"type": "command", "command": "echo keep-me"}]}]}}
        for profile in self.scripts:
            with self.subTest(profile=profile):
                out = self.modify(profile, stale)
                self.assertEqual(guards(out), [("Bash|Monitor", COMMAND)])
                self.assertIn({"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep-me"}]}, out["hooks"]["PreToolUse"])

    def test_the_command_blocks_a_pattern_kill_and_never_blocks_when_the_script_is_missing(self):
        out = self.modify("personal", {})
        command = guards(out)[0][1]
        with tempfile.TemporaryDirectory() as home:
            def run(payload, home_dir):
                return subprocess.run(["sh", "-c", command], input=json.dumps(payload), capture_output=True, text=True, timeout=30,
                                      env=dict(os.environ, HOME=home_dir))
            pk = {"tool_name": "Bash", "tool_input": {"command": "pkill -f x"}}
            ok = {"tool_name": "Bash", "tool_input": {"command": "kill 123"}}
            self.assertEqual(run(pk, home).returncode, 0)  # script missing: allowed
            deployed = Path(home) / ".local/share/agent-harness/hooks"
            deployed.mkdir(parents=True)
            shutil.copy(ROOT / "dot_local/share/agent-harness/hooks/refuse_pattern_kill.py", deployed)
            blocked = run(pk, home)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("pkill is refused in agent sessions", blocked.stderr)
            self.assertEqual(run(ok, home).returncode, 0)


if __name__ == "__main__":
    unittest.main()
