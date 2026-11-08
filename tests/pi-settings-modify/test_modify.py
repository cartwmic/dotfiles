"""dot_pi/private_agent/modify_private_settings.json.tmpl merges the Pi settings this repository wants into the live ~/.pi/agent/settings.json
and keeps everything Pi writes there (the old whole-file render collided with every Pi write: the E16 failure of `chezmoi update`).

Real chezmoi renders the script for both desktop profiles; real jq runs it over fixtures. No real HOME.

    python3 -m unittest discover -s tests/pi-settings-modify -v
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_pi/private_agent/modify_private_settings.json.tmpl"
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}
PINNED = "git:github.com/cartwmic/pi-claude-request-compat@9ecb03a8cafa77b555f08f7d640762adeb89d219"


def render(profile):
    data = {"profile": profile, **(WORK_DATA if profile == "axon-work-computer" else {})}
    with tempfile.TemporaryDirectory() as home:
        cfg = Path(home) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--destination", home, "execute-template",
                            "--override-data", json.dumps(data)], input=SCRIPT.read_text(), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class ModifyScript(unittest.TestCase):
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

    def run_script(self, profile, live):
        text = live if isinstance(live, str) else json.dumps(live)
        return subprocess.run(["sh", str(self.scripts[profile])], input=text, capture_output=True, text=True, timeout=60)

    def modify(self, profile, live):
        r = self.run_script(profile, live)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_a_fresh_machine_gets_everything_this_repository_wants(self):
        for profile in self.scripts:
            with self.subTest(profile=profile):
                s = self.modify(profile, {})
                self.assertEqual(s["defaultModel"], "claude-opus-5-5")
                self.assertEqual(s["defaultProvider"], "claude-compat" if profile == "personal" else "anthropic")
                self.assertEqual(s["defaultThinkingLevel"], "high")
                self.assertEqual(s["compaction"], {"enabled": False, "reserveTokens": 100000})
                self.assertEqual(s["codemode"], {"mode": "only"})
                self.assertEqual(s["defaultTools"], ["+codemode"])
                self.assertEqual((s["theme"], s["hideThinkingBlock"]), ("dark", False))
                self.assertIn("https://github.com/cartwmic/pi-sub", s["packages"])
                self.assertEqual(profile == "personal", any(isinstance(p, dict) and p["source"] == PINNED for p in s["packages"]))
                self.assertEqual(profile == "axon-work-computer", "subagents" in s)
                if profile == "axon-work-computer":
                    self.assertIn("work-glm/test-model", s["enabledModels"])
                    self.assertEqual(s["modelThinkingLevels"], {"anthropic/claude-opus-5-5": "medium"})
                else:
                    self.assertEqual(s["modelThinkingLevels"]["claude-compat/claude-opus-5-5"], "medium")

    def test_an_empty_file_is_a_fresh_machine_and_the_final_newline_follows_the_file(self):
        for profile in self.scripts:
            with self.subTest(profile=profile):
                r = self.run_script(profile, "")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(json.loads(r.stdout), self.modify(profile, {}))
                self.assertFalse(r.stdout.endswith("\n"))
                with_newline = self.run_script(profile, "{}\n").stdout
                self.assertTrue(with_newline.endswith("}\n"))
                self.assertFalse(self.run_script(profile, "{}").stdout.endswith("\n"))
                self.assertEqual(self.run_script(profile, with_newline).stdout, with_newline)  # unchanged file, unchanged bytes

    def test_what_pi_and_the_user_write_is_kept(self):
        live = {"theme": "light", "hideThinkingBlock": True, "lastChangelogVersion": "9.9.9", "deviceId": "abc", "defaultThinkingLevel": "low",
                "futureKey": {"a": [1, 2]}, "modelThinkingLevels": {"my/model": "low"},
                "enabledModels": ["my/model"], "packages": ["npm:my-own-package", {"source": "npm:object-form", "extensions": ["x"]}]}
        for profile in self.scripts:
            with self.subTest(profile=profile):
                s = self.modify(profile, live)
                for key in ("theme", "hideThinkingBlock", "lastChangelogVersion", "deviceId", "defaultThinkingLevel", "futureKey"):
                    self.assertEqual(s[key], live[key], key)
                self.assertEqual(s["modelThinkingLevels"]["my/model"], "low")
                self.assertIn("claude-opus-5-5", json.dumps(s["modelThinkingLevels"]))  # ours added beside it
                self.assertIn("my/model", s["enabledModels"])
                self.assertIn("npm:my-own-package", s["packages"])
                self.assertIn({"source": "npm:object-form", "extensions": ["x"]}, s["packages"])

    def test_owned_keys_are_set_again_and_a_changed_thinking_entry_of_ours_is_kept(self):
        live = {"defaultModel": "something-else", "defaultProvider": "other", "tuiMode": "fullscreen", "compaction": {"enabled": True}, "codemode": {"mode": "off"},
                "modelThinkingLevels": {"claude-compat/claude-opus-5-5": "xhigh", "anthropic/claude-opus-5-5": "xhigh"}}
        for profile in self.scripts:
            with self.subTest(profile=profile):
                s = self.modify(profile, live)
                self.assertEqual(s["defaultModel"], "claude-opus-5-5")
                self.assertEqual(s["tuiMode"], "regular")  # owned: the documented way to change it is the template
                self.assertEqual(s["compaction"]["enabled"], False)
                self.assertEqual(s["codemode"], {"mode": "only"})
                key = "claude-compat/claude-opus-5-5" if profile == "personal" else "anthropic/claude-opus-5-5"
                self.assertEqual(s["modelThinkingLevels"][key], "xhigh")

    def test_a_pin_bump_replaces_the_old_pin_and_a_missing_package_comes_back_in_our_order(self):
        live = {"packages": ["npm:mine", {"source": "git:github.com/cartwmic/pi-claude-request-compat@0000000000000000000000000000000000000000", "extensions": []},
                             "https://github.com/cartwmic/pi-sub"]}
        s = self.modify("personal", live)
        pins = [p for p in s["packages"] if isinstance(p, dict) and "pi-claude-request-compat" in p["source"]]
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]["source"], PINNED)
        self.assertEqual(s["packages"].count("https://github.com/cartwmic/pi-sub"), 1)
        self.assertEqual(s["packages"][-1], "npm:mine")  # ours first, then what the user added
        self.assertIn("https://github.com/cartwmic/pi-token-usage", s["packages"])

    def test_idempotent_and_stable_after_pi_saves_the_file_again(self):
        for profile in self.scripts:
            with self.subTest(profile=profile):
                once = self.run_script(profile, {"theme": "light"}).stdout
                self.assertEqual(self.run_script(profile, once).stdout, once)

    def test_a_file_that_is_not_a_json_object_is_an_error_not_an_overwrite(self):
        for bad in ("not json", "[1, 2]", '"text"'):
            with self.subTest(bad=bad):
                self.assertNotEqual(self.run_script("personal", bad).returncode, 0)


if __name__ == "__main__":
    unittest.main()
