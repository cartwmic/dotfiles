"""T3 hub provider instances: dot_t3/private_userdata/modify_settings.json.tmpl, the Codex provider block, the Claude settings file.

Everything runs through chezmoi against the real source with a minimal personal config and a throwaway HOME, so it needs
chezmoi and jq but no 1Password and no network to the hub. settings.live-shape.json is a copy of the real
~/.t3/userdata/settings.json (three instances, no trailing newline).
"""
import difflib
import json
import stat
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODEX_BASE = 'model = "gpt-6"\n\n[projects."/x"]\ntrust_level = "trusted"\n'
FIXTURE = (Path(__file__).parent / "settings.live-shape.json").read_text()
OURS = ("claude-hub", "codex-hub")
DARWIN = sys.platform == "darwin"  # the hub is gated to macOS; the chezmoi OS cannot be faked, so "on" and "off" run on macOS only
on_mac = unittest.skipUnless(DARWIN, "the T3 hub is gated to personal macOS")
CLAUDE_FILE = ".config/t3-hub-claude-settings.json"
TARGETS = (".t3/userdata/settings.json", CLAUDE_FILE, ".codex/config.toml")
CODEX_VERSION = "9.9.9"


class Env:
    """A throwaway HOME plus a chezmoi config for one profile."""

    def __init__(self, profile="personal", codex_active=True, enabled=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.cfg = Path(self._tmp.name) / "chezmoi.yaml"
        self.write_config(profile, enabled)
        self.profile = profile
        if codex_active:
            tools = self.home / ".t3/tools/codex"
            tools.mkdir(parents=True)
            (tools / "active.json").write_text(json.dumps({"version": CODEX_VERSION}))

    def write_config(self, profile, enabled=None):
        extra = "" if enabled is None else "  t3Hub:\n    enabled: %s\n" % ("true" if enabled else "false")
        extra += "  hub:\n    enabled: false\n"  # the default-provider switch is tests/hub-default's; this suite is about the two test instances
        self.cfg.write_text("data:\n  profile: %s\n%s" % (profile, extra))

    def set_enabled(self, enabled):
        self.write_config(self.profile, enabled)

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


@on_mac
class SettingsScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()
        cls.script = cls.env.render("dot_t3/private_userdata/modify_settings.json.tmpl")

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
            "environment": [{"name": "ANTHROPIC_BASE_URL", "value": "https://cliproxy.internal.cartwmic.com", "sensitive": False},
                            {"name": "ANTHROPIC_API_KEY", "value": "", "sensitive": False}],
            "config": {"launchArgs": "--settings %s/%s" % (home, CLAUDE_FILE)}})
        self.assertEqual(inst["codex-hub"], {
            "driver": "codex", "displayName": "Codex (hub)", "enabled": True,
            "config": {"setupMode": "existing", "launchArgs": "-c model_provider=cliproxy",
                       "binaryPath": "%s/.t3/tools/codex/%s/bin/codex" % (home, CODEX_VERSION)}})

    def test_idempotent_and_byte_stable(self):
        once = self.apply(FIXTURE)
        self.assertEqual(self.apply(once), once)

    def test_only_additions_in_the_text(self):
        """Line by line, the diff is two new objects and the comma on the object before them. Nothing else, to the last line."""
        once = self.apply(FIXTURE)
        ops = difflib.SequenceMatcher(None, FIXTURE.splitlines(), once.splitlines(), autojunk=False).get_opcodes()
        changes = [(tag, FIXTURE.splitlines()[a1:a2], once.splitlines()[b1:b2]) for tag, a1, a2, b1, b2 in ops if tag != "equal"]
        self.assertTrue(changes)
        for tag, old, new in changes:
            self.assertNotEqual(tag, "delete", old)
            if tag == "replace":
                self.assertEqual((old, new[:1]), (["    }"], ["    },"]))
        self.assertEqual(FIXTURE, json.dumps(json.loads(FIXTURE), indent=2, ensure_ascii=False))

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
            script = env.render("dot_t3/private_userdata/modify_settings.json.tmpl")
        finally:
            env.close()
        cfg = json.loads(run_script(script, FIXTURE))["providerInstances"]["codex-hub"]["config"]
        self.assertNotIn("binaryPath", cfg)


@on_mac
class ApplyPathTest(unittest.TestCase):
    """chezmoi apply into a throwaway HOME: the same path a real apply takes, with exactly the three real targets."""

    def fresh(self, **kw):
        """A HOME as the real Mac has it before the first apply: ~/.config, T3 and Codex files exist, the hub file does not.
        chezmoi can only target a path whose parent directory exists, which is why the hub file sits directly in ~/.config."""
        env = Env(**kw)
        (env.home / ".config").mkdir()
        (env.home / ".t3").mkdir(exist_ok=True)
        (env.home / ".t3/userdata").mkdir(mode=0o700)  # T3 keeps userdata private; the source must not loosen it
        (env.home / ".codex").mkdir()
        (env.home / ".t3/userdata/settings.json").write_text(FIXTURE)
        (env.home / ".codex/config.toml").write_text(CODEX_BASE)
        return env

    def targets(self, env):
        return [str(env.home / p) for p in TARGETS]

    def test_full_apply_keeps_userdata_private(self):
        """A full apply of ~/.t3 (as chezmoi apply or update does) leaves T3's userdata directory at 0700, on and off."""
        for enabled in (True, False):
            env = self.fresh(**({} if enabled else {"enabled": False}))
            try:
                env.chezmoi("apply", str(env.home / ".t3"))
                self.assertEqual(stat.S_IMODE((env.home / ".t3/userdata").stat().st_mode), 0o700)
                self.assertEqual(env.chezmoi("diff", str(env.home / ".t3")), "")
            finally:
                env.close()

    def test_apply_into_a_fresh_home(self):
        env = self.fresh()
        try:
            self.assertFalse((env.home / CLAUDE_FILE).exists())
            env.chezmoi("apply", *self.targets(env))
            settings = json.loads((env.home / ".t3/userdata/settings.json").read_text())
            self.assertEqual(list(settings["providerInstances"]), ["codex", "claudeAgent", "coordinator", *OURS])
            helper = json.loads((env.home / CLAUDE_FILE).read_text())
            self.assertEqual(list(helper), ["apiKeyHelper"])
            self.assertEqual(helper["apiKeyHelper"], "%s/.local/user_scripts/op_read_cached.sh 'op://developer/tb36gtnaocyezjk3dslomp64he/laptop-claude-code'" % env.home)
            toml = tomllib.loads((env.home / ".codex/config.toml").read_text())
            self.assertEqual(toml["model"], "gpt-6")
            self.assertNotIn("model_provider", toml)
            self.assertEqual(toml["model_providers"]["cliproxy"]["wire_api"], "responses")
            self.assertIs(toml["model_providers"]["cliproxy"]["supports_websockets"], True)
            self.assertNotIn("requires_openai_auth", toml["model_providers"]["cliproxy"])
            self.assertNotIn("env_key", toml["model_providers"]["cliproxy"])
            self.assertEqual(toml["model_providers"]["cliproxy"]["auth"]["args"], ["op://developer/tb36gtnaocyezjk3dslomp64he/laptop-codex"])
            # A second apply changes nothing.
            before = [Path(t).read_bytes() for t in self.targets(env)]
            env.chezmoi("apply", *self.targets(env))
            self.assertEqual([Path(t).read_bytes() for t in self.targets(env)], before)
        finally:
            env.close()

    def test_switch_off_retires_everything_and_nothing_else(self):
        env = self.fresh()
        try:
            env.chezmoi("apply", *self.targets(env))
            self.assertTrue((env.home / CLAUDE_FILE).exists())
            env.set_enabled(False)
            env.chezmoi("apply", *self.targets(env))
            self.assertEqual((env.home / ".t3/userdata/settings.json").read_text(), FIXTURE)
            self.assertEqual((env.home / ".codex/config.toml").read_text(), CODEX_BASE)
            self.assertFalse((env.home / CLAUDE_FILE).exists())
            # Off is stable, and back on restores all three.
            env.chezmoi("apply", *self.targets(env))
            self.assertEqual((env.home / ".t3/userdata/settings.json").read_text(), FIXTURE)
            env.set_enabled(True)
            env.chezmoi("apply", *self.targets(env))
            self.assertEqual(list(json.loads((env.home / ".t3/userdata/settings.json").read_text())["providerInstances"])[-2:], list(OURS))
            self.assertTrue((env.home / CLAUDE_FILE).exists())
        finally:
            env.close()

    def test_reapply_restores_instances_edited_in_t3(self):
        env = self.fresh()
        try:
            env.chezmoi("apply", *self.targets(env))
            path = env.home / ".t3/userdata/settings.json"
            data = json.loads(path.read_text())
            data["providerInstances"]["claude-hub"]["displayName"] = "edited in the T3 UI"
            data["providerInstances"]["mine"] = {"driver": "codex"}
            path.write_text(json.dumps(data, indent=2))
            env.chezmoi("apply", *self.targets(env))
            out = json.loads(path.read_text())["providerInstances"]
            self.assertEqual(out["claude-hub"]["displayName"], "Claude (hub)")
            self.assertIn("mine", out)
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
    BLOCK = 'a = 1\n\n# chezmoi:cliproxy-hub:begin\n[model_providers.cliproxy]\nname = "stale"\n# chezmoi:cliproxy-hub:end\n'

    def render(self, profile, enabled=None):
        env = Env(profile, enabled=enabled)
        try:
            return env.render(self.SRC)
        finally:
            env.close()

    @on_mac
    def test_personal_adds_block_once_and_keeps_the_rest(self):
        script = self.render("personal")
        base = 'model = "gpt-6"\n\n# BEGIN CHEZMOI AGENT HARNESS MCP\n[mcp_servers.a]\nurl = "x"\n# END CHEZMOI AGENT HARNESS MCP\n\n[projects."/x"]\ntrust_level = "trusted"\n'
        once = run_script(script, base)
        self.assertTrue(once.startswith(base))
        self.assertEqual(once.count("chezmoi:cliproxy-hub:begin"), 1)
        self.assertEqual(run_script(script, once), once)
        self.assertNotIn("model_provider", tomllib.loads(once))

    @on_mac
    def test_block_is_replaced_not_duplicated(self):
        out = run_script(self.render("personal"), self.BLOCK)
        self.assertNotIn("stale", out)
        self.assertEqual(out.count("[model_providers.cliproxy]"), 1)

    @on_mac
    def test_switch_off_drops_the_block(self):
        script = self.render("personal", enabled=False)
        self.assertEqual(run_script(script, 'a = 1\n'), 'a = 1\n')
        self.assertEqual(run_script(script, self.BLOCK), 'a = 1\n')

    def test_other_profiles_add_nothing_and_drop_a_stale_block(self):
        script = self.render("axon-work-computer")
        self.assertEqual(run_script(script, 'a = 1\n'), 'a = 1\n')
        self.assertEqual(run_script(script, self.BLOCK), 'a = 1\n')

    def test_caveman_strip_still_works(self):
        out = run_script(self.render("axon-work-computer"), '# chezmoi:caveman-style:begin\nx\n# chezmoi:caveman-style:end\nb = 2\n')
        self.assertNotIn("caveman", out)
        self.assertIn("b = 2", out)


class ProfileGateTest(unittest.TestCase):
    def hub_paths(self, profile):
        env = Env(profile)
        try:
            managed = set(env.chezmoi("managed").split())
        finally:
            env.close()
        return {p for p in managed if p == ".t3" or p.startswith(".t3/") or p == CLAUDE_FILE}

    def test_only_personal_macos_manages_the_hub_files(self):
        for profile in ("axon-work-computer", "termux"):
            self.assertEqual(self.hub_paths(profile), set(), profile)
        if DARWIN:
            self.assertEqual(self.hub_paths("personal"), {".t3", ".t3/userdata", ".t3/userdata/settings.json", CLAUDE_FILE})
        else:
            self.assertEqual(self.hub_paths("personal"), set(), "personal on Linux or WSL")

    def test_bad_switch_value_fails_the_render(self):
        env = Env()
        env.cfg.write_text("data:\n  profile: personal\n  t3Hub:\n    enabled: maybe\n")
        try:
            with self.assertRaises(AssertionError):
                env.chezmoi("managed")
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
