"""T3 hub provider instances: dot_t3/userdata/modify_settings.json.tmpl, the Codex provider block, the Claude settings file.

Everything runs through chezmoi against the real source with a minimal personal config and a throwaway HOME, so it needs
chezmoi and jq but no 1Password and no network to the hub. settings.live-shape.json is a copy of the real
~/.t3/userdata/settings.json (three instances, no trailing newline).
"""
import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE = (Path(__file__).parent / "settings.live-shape.json").read_text()
OURS = ("claude-hub", "codex-hub")
CODEX_VERSION = "9.9.9"


class Env:
    """A throwaway HOME plus a chezmoi config for one profile."""

    def __init__(self, profile="personal", codex_active=True):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.cfg = Path(self._tmp.name) / "chezmoi.yaml"
        self.cfg.write_text("data:\n  profile: %s\n" % profile)
        if codex_active:
            tools = self.home / ".t3/tools/codex"
            tools.mkdir(parents=True)
            (tools / "active.json").write_text(json.dumps({"version": CODEX_VERSION}))

    def chezmoi(self, *args, stdin=None):
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(self.cfg), "--config-format", "yaml",
                            "--destination", str(self.home), *args],
                           input=stdin, capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=120)
        if r.returncode:
            raise AssertionError("chezmoi %s failed: %s" % (" ".join(args), r.stderr))
        return r.stdout

    def render(self, source):
        return self.chezmoi("execute-template", stdin=(REPO / source).read_text())

    def close(self):
        self._tmp.cleanup()


def run_script(script, stdin, want=None):
    """Run a rendered modify script. want replaces the one-line WANT definition."""
    if want is not None:
        lines = script.splitlines(keepends=True)
        script = "".join("WANT='%s'\n" % want if l.startswith("WANT=") else l for l in lines)
    r = subprocess.run(["sh", "-c", script], input=stdin, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


class SettingsScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.script = cls.env.render("dot_t3/userdata/modify_settings.json.tmpl")

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def apply(self, stdin, **kw):
        return run_script(self.script, stdin, **kw)

    def test_adds_exactly_the_two_instances(self):
        out = json.loads(self.apply(FIXTURE))
        before = json.loads(FIXTURE)
        self.assertEqual(list(out["providerInstances"]), list(before["providerInstances"]) + list(OURS))
        theirs = {k: v for k, v in out["providerInstances"].items() if k not in OURS}
        self.assertEqual(theirs, before["providerInstances"])
        self.assertEqual({k: v for k, v in out.items() if k != "providerInstances"},
                         {k: v for k, v in before.items() if k != "providerInstances"})

    def test_instance_shapes(self):
        inst = json.loads(self.apply(FIXTURE))["providerInstances"]
        home = str(self.env.home)
        self.assertEqual(inst["claude-hub"], {
            "driver": "claudeAgent", "displayName": "Claude (hub)", "enabled": True,
            "environment": [{"name": "ANTHROPIC_BASE_URL", "value": "https://cliproxy.internal.cartwmic.com", "sensitive": False}],
            "config": {"launchArgs": "--settings %s/.config/t3-hub/claude-settings.json" % home}})
        self.assertEqual(inst["codex-hub"], {
            "driver": "codex", "displayName": "Codex (hub)", "enabled": True,
            "config": {"setupMode": "existing", "launchArgs": "-c model_provider=cliproxy",
                       "binaryPath": "%s/.t3/tools/codex/%s/bin/codex" % (home, CODEX_VERSION)}})

    def test_idempotent_and_byte_stable(self):
        once = self.apply(FIXTURE)
        self.assertEqual(self.apply(once), once)

    def test_only_additions_in_the_text(self):
        """Every line of the original survives in order: the diff is two new objects, nothing else."""
        once = self.apply(FIXTURE)
        original = FIXTURE.splitlines()
        it = iter(once.splitlines())
        for line in original[:-3]:  # the closing "  }", "}" and the last instance's "}" are re-flowed by the comma
            self.assertTrue(any(line == got for got in it), "line lost or reordered: %r" % line)

    def test_no_trailing_newline_stays_none_and_one_stays_one(self):
        self.assertFalse(FIXTURE.endswith("\n"))
        self.assertFalse(self.apply(FIXTURE).endswith("\n"))
        self.assertTrue(self.apply(FIXTURE + "\n").endswith("}\n"))

    def test_stale_hub_entries_are_replaced_in_place(self):
        data = json.loads(FIXTURE)
        data["providerInstances"] = {"claude-hub": {"driver": "claudeAgent", "displayName": "old"},
                                     **data["providerInstances"], "codex-hub": {"driver": "codex", "displayName": "old"}}
        out = json.loads(self.apply(json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(list(out), list(data["providerInstances"]))
        self.assertEqual(out["claude-hub"]["displayName"], "Claude (hub)")
        self.assertEqual(out["codex-hub"]["displayName"], "Codex (hub)")

    def test_removing_the_definition_removes_only_these_two(self):
        with_ours = self.apply(FIXTURE)
        self.assertEqual(json.loads(self.apply(with_ours, want="{}")), json.loads(FIXTURE))
        only_claude = json.loads(self.apply(with_ours, want=json.dumps({"claude-hub": {"driver": "claudeAgent"}})))
        self.assertEqual(list(only_claude["providerInstances"]), ["codex", "claudeAgent", "coordinator", "claude-hub"])

    def test_no_provider_instances_key(self):
        out = json.loads(self.apply('{"a": 1}'))
        self.assertEqual(list(out["providerInstances"]), list(OURS))
        self.assertEqual(json.loads(self.apply('{"a": 1}', want="{}")), {"a": 1})

    def test_missing_or_invalid_input_is_unchanged(self):
        for text in ("", "not json", '{"a": ', "[1, 2]", "null"):
            self.assertEqual(self.apply(text), text)

    def test_without_active_json_binary_path_is_left_out(self):
        env = Env(codex_active=False)
        try:
            script = env.render("dot_t3/userdata/modify_settings.json.tmpl")
        finally:
            env.close()
        cfg = json.loads(run_script(script, FIXTURE))["providerInstances"]["codex-hub"]["config"]
        self.assertNotIn("binaryPath", cfg)


class ApplyPathTest(unittest.TestCase):
    """chezmoi apply into a throwaway HOME: the same path a real apply takes."""

    def test_apply_personal(self):
        env = Env()
        try:
            for d in (".t3/userdata", ".config/t3-hub", ".codex"):
                (env.home / d).mkdir(parents=True, exist_ok=True)
            (env.home / ".t3/userdata/settings.json").write_text(FIXTURE)
            (env.home / ".codex/config.toml").write_text('model = "gpt-6"\n\n[projects."/x"]\ntrust_level = "trusted"\n')
            targets = [str(env.home / p) for p in (".t3/userdata/settings.json", ".config/t3-hub/claude-settings.json", ".codex/config.toml")]
            env.chezmoi("apply", *targets)
            settings = json.loads((env.home / ".t3/userdata/settings.json").read_text())
            self.assertEqual(list(settings["providerInstances"]), ["codex", "claudeAgent", "coordinator", *OURS])
            helper = json.loads((env.home / ".config/t3-hub/claude-settings.json").read_text())
            self.assertEqual(list(helper), ["apiKeyHelper"])
            self.assertEqual(helper["apiKeyHelper"], "%s/.local/user_scripts/op_read_cached.sh 'op://developer/tb36gtnaocyezjk3dslomp64he/laptop-claude-code'" % env.home)
            toml = tomllib.loads((env.home / ".codex/config.toml").read_text())
            self.assertEqual(toml["model"], "gpt-6")
            self.assertNotIn("model_provider", toml)
            self.assertEqual(toml["model_providers"]["cliproxy"]["wire_api"], "responses")
            self.assertEqual(toml["model_providers"]["cliproxy"]["auth"]["args"], ["op://developer/tb36gtnaocyezjk3dslomp64he/laptop-codex"])
            # A second apply changes nothing.
            before = [Path(t).read_bytes() for t in targets]
            env.chezmoi("apply", *targets)
            self.assertEqual([Path(t).read_bytes() for t in targets], before)
        finally:
            env.close()

    def test_missing_settings_file_is_not_created(self):
        env = Env()
        try:
            (env.home / ".t3/userdata").mkdir(parents=True, exist_ok=True)
            env.chezmoi("apply", str(env.home / ".t3/userdata/settings.json"))
            self.assertFalse((env.home / ".t3/userdata/settings.json").exists())
        finally:
            env.close()


class CodexBlockTest(unittest.TestCase):
    SRC = "dot_codex/modify_private_config.toml.tmpl"

    def render(self, profile):
        env = Env(profile)
        try:
            return env.render(self.SRC)
        finally:
            env.close()

    def test_personal_adds_block_once_and_keeps_the_rest(self):
        script = self.render("personal")
        base = 'model = "gpt-6"\n\n# BEGIN CHEZMOI AGENT HARNESS MCP\n[mcp_servers.a]\nurl = "x"\n# END CHEZMOI AGENT HARNESS MCP\n\n[projects."/x"]\ntrust_level = "trusted"\n'
        once = run_script(script, base)
        self.assertTrue(once.startswith(base))
        self.assertEqual(once.count("chezmoi:cliproxy-hub:begin"), 1)
        self.assertEqual(run_script(script, once), once)
        self.assertNotIn("model_provider", tomllib.loads(once))

    def test_block_is_replaced_not_duplicated(self):
        script = self.render("personal")
        old = 'a = 1\n\n# chezmoi:cliproxy-hub:begin\n[model_providers.cliproxy]\nname = "stale"\n# chezmoi:cliproxy-hub:end\n'
        out = run_script(script, old)
        self.assertNotIn("stale", out)
        self.assertEqual(out.count("[model_providers.cliproxy]"), 1)

    def test_work_profile_adds_nothing_and_drops_a_stale_block(self):
        script = self.render("axon-work-computer")
        self.assertEqual(run_script(script, 'a = 1\n'), 'a = 1\n')
        stale = 'a = 1\n\n# chezmoi:cliproxy-hub:begin\n[model_providers.cliproxy]\n# chezmoi:cliproxy-hub:end\n'
        self.assertEqual(run_script(script, stale), 'a = 1\n')

    def test_caveman_strip_still_works(self):
        script = self.render("personal")
        out = run_script(script, '# chezmoi:caveman-style:begin\nx\n# chezmoi:caveman-style:end\nb = 2\n')
        self.assertNotIn("caveman", out)
        self.assertIn("b = 2", out)


class ProfileGateTest(unittest.TestCase):
    def test_other_profiles_do_not_manage_the_hub_files(self):
        for profile in ("axon-work-computer", "termux"):
            env = Env(profile)
            try:
                managed = set(env.chezmoi("managed").split())
            finally:
                env.close()
            self.assertFalse({p for p in managed if p == ".t3" or p.startswith(".t3/") or p.startswith(".config/t3-hub")}, profile)
            if profile != "termux":
                self.assertIn(".codex/config.toml", managed)


if __name__ == "__main__":
    unittest.main()
