"""dot_claude/modify_settings.json.tmpl points Claude Code at the CLIProxyAPI hub (personal profile, macOS, hub.claude true) and removes only its own keys otherwise.

Renders the template with the real chezmoi and runs each result as the modify script over a settings.json. No real HOME, no network.

    python3 -m unittest discover -s tests/hub-claude -v
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "dot_claude/modify_settings.json.tmpl"
HOME = "/Users/hubtest"
URL = "https://cliproxy.internal.cartwmic.com"
HELPER = HOME + "/.local/user_scripts/op_read_cached.sh 'op://developer/tb36gtnaocyezjk3dslomp64he/laptop-claude-code'"
OS_GATE = 'eq .chezmoi.os "darwin"'
CASES = {  # name: (chezmoi data, pretend OS)
    "on": ({"profile": "personal"}, "darwin"),
    "switch_off": ({"profile": "personal", "hub": {"claude": False}}, "darwin"),
    "work": ({"profile": "axon-work-computer"}, "darwin"),
    "linux": ({"profile": "personal"}, "linux"),
}
USER = {"theme": "dark", "env": {"FOO": "bar"}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}


def render(data, os_name):
    src = SETTINGS.read_text()
    assert OS_GATE in src
    src = src.replace(OS_GATE, 'eq "%s" "darwin"' % os_name)  # .chezmoi.os cannot be overridden by config data
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        # a missing coordinator repo keeps the T3 hook out of the way
        cfg.write_text(json.dumps({"data": dict(data, instances={"coordinator": {"repo": "/nonexistent/coordinator"}})}))
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                           input=src, capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=HOME))
    assert r.returncode == 0, r.stderr
    return r.stdout


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class HubClaudeSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.scripts = {}
        for name, (data, os_name) in CASES.items():
            cls.scripts[name] = cls.tmp / ("modify-" + name)
            cls.scripts[name].write_text(render(data, os_name))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def modify(self, case, settings):
        text = settings if isinstance(settings, str) else json.dumps(settings)
        r = subprocess.run(["sh", str(self.scripts[case])], input=text, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_on_sets_both_keys_and_keeps_everything_else(self):
        s = self.modify("on", USER)
        self.assertEqual(s["env"], {"FOO": "bar", "ANTHROPIC_BASE_URL": URL})
        self.assertEqual(s["apiKeyHelper"], HELPER)
        self.assertEqual((s["theme"], s["hooks"]), ("dark", USER["hooks"]))
        for k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            self.assertNotIn(k, s["env"])

    def test_on_is_idempotent_and_works_from_empty(self):
        once = self.modify("on", USER)
        self.assertEqual(self.modify("on", once), once)
        for text in ("", "{}"):
            s = self.modify("on", text)
            self.assertEqual((s["env"], s["apiKeyHelper"]), ({"ANTHROPIC_BASE_URL": URL}, HELPER))

    def test_off_removes_ours_and_keeps_a_users_env_keys(self):
        for case in ("switch_off", "work", "linux"):
            s = self.modify(case, self.modify("on", USER))
            self.assertEqual(s["env"], {"FOO": "bar"}, case)
            self.assertNotIn("apiKeyHelper", s, case)
            self.assertEqual(s["hooks"]["Stop"], USER["hooks"]["Stop"], case)  # work adds its own SessionStart hook
            self.assertEqual(self.modify(case, s), s, case)

    def test_off_prunes_env_when_we_emptied_it_and_never_adds_it(self):
        for case in ("switch_off", "work", "linux"):
            s = self.modify(case, self.modify("on", "{}"))
            self.assertNotIn("env", s, case)
            self.assertNotIn("apiKeyHelper", s, case)
            self.assertNotIn("env", self.modify(case, "{}"), case)

    def test_off_keeps_a_different_url_a_different_helper_and_an_env_the_user_left_empty(self):
        mine = {"env": {"ANTHROPIC_BASE_URL": "https://proxy.example/v1"}, "apiKeyHelper": "/bin/my-helper"}
        for case in ("switch_off", "work", "linux"):
            self.assertEqual(self.modify(case, mine)["env"], mine["env"], case)
            self.assertEqual(self.modify(case, mine)["apiKeyHelper"], "/bin/my-helper", case)
            self.assertEqual(self.modify(case, {"env": {}})["env"], {}, case)

    def test_the_helper_prints_only_the_key(self):
        # op_read_cached.sh must write nothing but the value to stdout (messages go to stderr): fake op, then read twice (miss, hit).
        script = ROOT / "dot_local/user_scripts/executable_op_read_cached.sh"
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "op").write_text("#!/bin/sh\nprintf 'sk-test-key'\n")
        (bindir / "op").chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + ":" + os.environ["PATH"], HOME=str(self.tmp),
                   OP_READ_CACHE_DIR=str(self.tmp / "cache"), OP_SERVICE_ACCOUNT_TOKEN="")
        for _ in range(2):
            r = subprocess.run(["sh", str(script), "op://developer/x/y"], capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual((r.returncode, r.stdout), (0, "sk-test-key"))


if __name__ == "__main__":
    unittest.main()
