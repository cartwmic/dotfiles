"""T3 hub provider instances: dot_t3/private_userdata/modify_settings.json.tmpl, the Codex provider block, the Claude settings file.

Everything runs through chezmoi against the real source with a minimal personal config and a throwaway HOME, so it needs
chezmoi and jq but no 1Password and no network to the hub. settings.live-shape.json is a copy of the real
~/.t3/userdata/settings.json (three instances, no trailing newline).
"""
import difflib
import json
import re
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
WORKTREES = "/Volumes/Workshop/macbook/t3-worktrees"
WINDOWS = {"claudeAgent": "300000", "coordinator": "200000"}  # T3's "Auto-compact after" (autoCompactWindow), strings; Michael's picks, 2026-11-13
WINDOW_IDS = tuple(WINDOWS)
IDLE = "beforeCacheExpires"  # T3's "Compact idle threads: Before the cache expires (beta)" (top-level idleCompaction)
# One claudeAgent instance per agent seat: id, window, and whether the advisor tool is switched off. Restated here on purpose, not read from the template.
SEAT_TABLE = (("seat-lead", "200000", False), ("seat-builder", "300000", True), ("seat-planner", "300000", True), ("seat-reviewer", "300000", False))
SEATS = tuple(i for i, _, _ in SEAT_TABLE)
# T3 interrupts a running session to deliver a message; Claude Code then reports a call it skipped as a user decline unless this variable is set (see the template header). Restated here on purpose.
FIZZY = {"name": "CLAUDE_CODE_FIZZY_GROVE", "sensitive": False, "value": "1"}
FIZZY_IDS = ("claudeAgent", "coordinator", "claude-hub") + SEATS  # every Claude instance the template owns or finds


def seat_instances(home):
    """The four seat instances as the script writes them (key order is the template's: config, displayName, driver, enabled, environment)."""
    out = {}
    for sid, window, advisor in SEAT_TABLE:
        fleet = "%s/.claude/fleet" % home
        inst = {"config": {"autoCompactWindow": window,
                           "launchArgs": "--settings %s/%s.json --strict-mcp-config --mcp-config %s/mcp.json" % (fleet, sid, fleet)},
                "displayName": "Claude (%s)" % sid.split("-", 1)[1], "driver": "claudeAgent", "enabled": True}
        inst["environment"] = ([] if advisor else [{"name": "CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "sensitive": False, "value": "1"}]) + [FIZZY]
        out[sid] = inst
    return out


def with_window(data):
    """data with each instance's autoCompactWindow added to its config (appended last, the way the script does) and idleCompaction set."""
    out = json.loads(json.dumps(data))
    for i, w in WINDOWS.items():
        if isinstance(out.get("providerInstances", {}).get(i), dict):
            out["providerInstances"][i]["config"] = {**out["providerInstances"][i].get("config", {}), "autoCompactWindow": w}
            out["providerInstances"][i]["environment"] = [*out["providerInstances"][i].get("environment", []), FIZZY]
    out["idleCompaction"] = IDLE
    return out


# The live-shape settings once the window is in place: what every apply after the first sees, and what the switch-off tests expect back.
SETTLED = json.dumps(with_window(json.loads(FIXTURE)), indent=2, ensure_ascii=False)



def seated(home):
    """SETTLED plus the four seat instances: what the settings file holds once the hub is off (the seats are not part of the hub switch)."""
    data = json.loads(SETTLED)
    data["providerInstances"].update(seat_instances(str(home)))
    return json.dumps(data, indent=2, ensure_ascii=False)


def without_codex_guard(text):
    """The Codex config without the empty [hooks.state] anchor header that every render adds for the guard hook's trust."""
    text, dropped = re.subn(r"(?m)^\[hooks\.state\]\n\n?", "", text, count=1)
    return text.rstrip("\n") + "\n" if dropped and text.strip() else text


class Env:
    """A throwaway HOME plus a chezmoi config for one profile."""

    def __init__(self, profile="personal", codex_active=True, enabled=True):  # t3Hub is off by default now; these tests are about it being on
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


def run_script(script, stdin, want=None, window=None, idle=None, envvars=None):
    """Run a rendered modify script. want replaces the one-line WANT definition; window (one value for both instances) the AUTO_COMPACT_WINDOWS one; idle the IDLE_COMPACTION one; envvars the ENV_VARS one."""
    if want is not None:
        lines = script.splitlines(keepends=True)
        script = "".join("WANT='%s'\n" % want if l.startswith("WANT=") else l for l in lines)
    if window is not None:
        script = "".join("AUTO_COMPACT_WINDOWS='%s'\n" % json.dumps({i: window for i in WINDOW_IDS}) if l.startswith("AUTO_COMPACT_WINDOWS=") else l for l in script.splitlines(keepends=True))
    if idle is not None:
        script = "".join("IDLE_COMPACTION='%s'\n" % idle if l.startswith("IDLE_COMPACTION=") else l for l in script.splitlines(keepends=True))
    if envvars is not None:
        script = "".join("ENV_VARS='%s'\n" % envvars if l.startswith("ENV_VARS=") else l for l in script.splitlines(keepends=True))
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

    def test_adds_exactly_the_two_hub_instances_and_the_four_seats(self):
        out = json.loads(self.apply(FIXTURE))
        before = json.loads(FIXTURE)
        self.assertEqual(list(out["providerInstances"]), list(before["providerInstances"]) + list(OURS) + list(SEATS))
        theirs = {k: v for k, v in out["providerInstances"].items() if k not in OURS + SEATS}
        self.assertEqual(theirs, with_window(before)["providerInstances"])
        self.assertEqual({k: v for k, v in out.items() if k != "providerInstances"},
                         {k: v for k, v in with_window(before).items() if k != "providerInstances"})

    def test_worktrees_directory_is_set_and_nothing_else_moves(self):
        """New T3 worktrees go to Workshop. The key is added when absent, replaces a different value, and every other key is as T3 wrote it."""
        before = json.loads(FIXTURE)
        without = {k: v for k, v in before.items() if k != "worktreesDirectory"}
        for start in (without, dict(before, worktreesDirectory=""), dict(before, worktreesDirectory="/somewhere/else")):
            out = json.loads(self.apply(json.dumps(start, indent=2)))
            self.assertEqual(out["worktreesDirectory"], WORKTREES)
            self.assertEqual({k: v for k, v in out.items() if k not in ("providerInstances", "worktreesDirectory")},
                             {k: v for k, v in with_window(before).items() if k not in ("providerInstances", "worktreesDirectory")})

    def test_worktrees_directory_is_set_while_the_hub_is_off(self):
        out = json.loads(self.apply('{"a": 1}', want="{}"))
        self.assertEqual(out["worktreesDirectory"], WORKTREES)

    def test_instance_shapes(self):
        inst = json.loads(self.apply(FIXTURE))["providerInstances"]
        home = str(self.env.home)
        self.assertEqual(inst["claude-hub"], {
            "driver": "claudeAgent", "displayName": "Claude (hub)", "enabled": True,
            "environment": [{"name": "ANTHROPIC_BASE_URL", "value": "https://cliproxy.internal.cartwmic.com", "sensitive": False},
                            {"name": "ANTHROPIC_API_KEY", "value": "", "sensitive": False}, FIZZY],
            "config": {"launchArgs": "--settings %s/%s" % (home, CLAUDE_FILE)}})
        self.assertEqual(inst["codex-hub"], {
            "driver": "codex", "displayName": "Codex (hub)", "enabled": True,
            "config": {"setupMode": "existing", "launchArgs": "-c model_provider=cliproxy",
                       "binaryPath": "%s/.t3/tools/codex/%s/bin/codex" % (home, CODEX_VERSION)}})

    def test_idempotent_and_byte_stable(self):
        once = self.apply(FIXTURE)
        self.assertEqual(self.apply(once), once)

    def test_only_additions_in_the_text(self):
        """Line by line, the diff is six new objects (two hub, four seat) and the comma on the object before them. Nothing else, to the last line."""
        once = self.apply(SETTLED)
        ops = difflib.SequenceMatcher(None, SETTLED.splitlines(), once.splitlines(), autojunk=False).get_opcodes()
        changes = [(tag, SETTLED.splitlines()[a1:a2], once.splitlines()[b1:b2]) for tag, a1, a2, b1, b2 in ops if tag != "equal"]
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

    def test_auto_compact_window_is_set_on_the_two_claude_instances_only(self):
        """claudeAgent gains a config holding just the window; coordinator keeps its launchArgs and gains the window; codex and the rest are as T3 wrote them."""
        before = json.loads(FIXTURE)["providerInstances"]
        inst = json.loads(self.apply(FIXTURE))["providerInstances"]
        self.assertEqual(inst["claudeAgent"], {"driver": "claudeAgent", "enabled": True, "config": {"autoCompactWindow": WINDOWS["claudeAgent"]}, "environment": [FIZZY]})
        self.assertEqual(inst["coordinator"]["config"], {**before["coordinator"]["config"], "autoCompactWindow": WINDOWS["coordinator"]})
        # outside config, the coordinator is as T3 wrote it plus the one interrupt-text environment entry (tests below: FizzyGroveTest)
        self.assertEqual({k: v for k, v in inst["coordinator"].items() if k != "config"},
                         {**{k: v for k, v in before["coordinator"].items() if k != "config"}, "environment": [*before["coordinator"].get("environment", []), FIZZY]})
        self.assertEqual(inst["codex"], before["codex"])
        for i in OURS:
            self.assertNotIn("autoCompactWindow", inst[i].get("config", {}))
        self.assertIsInstance(inst["claudeAgent"]["config"]["autoCompactWindow"], str)

    def test_auto_compact_window_does_not_depend_on_the_hub_switch(self):
        inst = json.loads(self.apply(FIXTURE, want="{}"))["providerInstances"]
        self.assertEqual({i: inst[i]["config"]["autoCompactWindow"] for i in WINDOW_IDS}, WINDOWS)

    def test_auto_compact_window_replaces_a_different_value(self):
        data = json.loads(FIXTURE)
        data["providerInstances"]["coordinator"]["config"]["autoCompactWindow"] = "300000"
        data["providerInstances"]["claudeAgent"]["config"] = {"autoCompactWindow": "", "binaryPath": "/x/claude"}
        inst = json.loads(self.apply(json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(inst["coordinator"]["config"]["autoCompactWindow"], WINDOWS["coordinator"])
        self.assertEqual(inst["claudeAgent"]["config"], {"autoCompactWindow": WINDOWS["claudeAgent"], "binaryPath": "/x/claude"})

    def test_builders_and_the_coordinator_get_different_windows(self):
        """Leads and builders share claudeAgent at 300000; the coordinator is 200000. The two are separate values."""
        inst = json.loads(self.apply(FIXTURE))["providerInstances"]
        self.assertEqual((inst["claudeAgent"]["config"]["autoCompactWindow"], inst["coordinator"]["config"]["autoCompactWindow"]), ("300000", "200000"))

    def test_idle_compaction_is_set_before_the_cache_expires(self):
        """The top-level idleCompaction goes from T3's "onReturn" to "beforeCacheExpires", with or without the hub, and nothing else at the top level changes but the owned keys."""
        before = json.loads(FIXTURE)
        self.assertEqual(before["idleCompaction"], "onReturn")
        for want in (None, "{}"):
            out = json.loads(self.apply(FIXTURE, want=want))
            self.assertEqual(out["idleCompaction"], IDLE)
            self.assertEqual({k: v for k, v in out.items() if k not in ("idleCompaction", "providerInstances", "worktreesDirectory", "usageLimitSources", "secretProviders")},
                             {k: v for k, v in before.items() if k not in ("idleCompaction", "providerInstances", "worktreesDirectory", "usageLimitSources", "secretProviders")})

    def test_idle_compaction_is_added_when_absent_and_an_empty_value_leaves_it_alone(self):
        data = json.loads(FIXTURE)
        del data["idleCompaction"]
        self.assertEqual(json.loads(self.apply(json.dumps(data, indent=2), want="{}"))["idleCompaction"], IDLE)
        self.assertNotIn("idleCompaction", json.loads(self.apply(json.dumps(data, indent=2), want="{}", idle="")))
        self.assertEqual(json.loads(self.apply(FIXTURE, want="{}", idle=""))["idleCompaction"], "onReturn")

    def test_auto_compact_window_does_not_create_an_absent_instance(self):
        data = json.loads(FIXTURE)
        del data["providerInstances"]["coordinator"]
        inst = json.loads(self.apply(json.dumps(data, indent=2), want="{}"))["providerInstances"]
        self.assertNotIn("coordinator", inst)
        self.assertEqual(json.loads(self.apply('{"a": 1}', want="{}")), {"a": 1, "idleCompaction": IDLE, "worktreesDirectory": WORKTREES})

    def test_empty_auto_compact_window_removes_only_our_key(self):
        data = json.loads(self.apply(FIXTURE))
        data["providerInstances"]["coordinator"]["config"]["other"] = 1
        out = json.loads(self.apply(json.dumps(data, indent=2), window="", idle=""))["providerInstances"]
        self.assertEqual(out["coordinator"]["config"], {"launchArgs": data["providerInstances"]["coordinator"]["config"]["launchArgs"], "other": 1})
        self.assertEqual(out["claudeAgent"].get("config"), {})
        # With no window ever set, an empty value leaves the file exactly as T3 wrote it (no config key invented). The environment entry is switched off here too: it is not what this test is about.
        self.assertEqual(json.loads(self.apply(FIXTURE, want="{}", window="", idle="", envvars="{}"))["providerInstances"], json.loads(FIXTURE)["providerInstances"])

    def test_stale_hub_entries_are_replaced_in_place(self):
        data = json.loads(FIXTURE)
        data["providerInstances"] = {"claude-hub": {"driver": "claudeAgent", "displayName": "old"},
                                     **data["providerInstances"], "codex-hub": {"driver": "codex", "displayName": "old"}}
        out = json.loads(self.apply(json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(list(out), list(data["providerInstances"]) + list(SEATS))
        self.assertEqual(out["claude-hub"]["displayName"], "Claude (hub)")
        self.assertEqual(out["codex-hub"]["displayName"], "Codex (hub)")

    def test_removing_the_definition_removes_only_these_two(self):
        with_ours = self.apply(FIXTURE)
        self.assertEqual(json.loads(self.apply(with_ours, want="{}")), with_window(json.loads(FIXTURE)))
        only_claude = json.loads(self.apply(with_ours, want=json.dumps({"claude-hub": {"driver": "claudeAgent"}})))
        self.assertEqual(list(only_claude["providerInstances"]), ["codex", "claudeAgent", "coordinator", "claude-hub"])

    def test_no_provider_instances_key(self):
        out = json.loads(self.apply('{"a": 1}'))
        self.assertEqual(list(out["providerInstances"]), list(OURS) + list(SEATS))
        self.assertEqual(json.loads(self.apply('{"a": 1}', want="{}")), {"a": 1, "idleCompaction": IDLE, "worktreesDirectory": WORKTREES})

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
            self.assertEqual(list(settings["providerInstances"]), ["codex", "claudeAgent", "coordinator", *OURS, *SEATS])
            helper = json.loads((env.home / CLAUDE_FILE).read_text())
            self.assertEqual(list(helper), ["apiKeyHelper"])
            self.assertEqual(helper["apiKeyHelper"], "%s/.local/user_scripts/op_read_cached.sh 'op://developer/tb36gtnaocyezjk3dslomp64he/laptop-claude-code'" % env.home)
            toml = tomllib.loads(without_codex_guard((env.home / ".codex/config.toml").read_text()))
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
            self.assertEqual((env.home / ".t3/userdata/settings.json").read_text(), seated(env.home))
            self.assertEqual(without_codex_guard((env.home / ".codex/config.toml").read_text()), CODEX_BASE)
            self.assertFalse((env.home / CLAUDE_FILE).exists())
            # Off is stable, and back on restores all three.
            env.chezmoi("apply", *self.targets(env))
            self.assertEqual((env.home / ".t3/userdata/settings.json").read_text(), seated(env.home))
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

    def render(self, profile, enabled=True):
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
        self.assertTrue(without_codex_guard(once).startswith(base))
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
        self.assertEqual(without_codex_guard(run_script(script, 'a = 1\n')), 'a = 1\n')
        self.assertEqual(without_codex_guard(run_script(script, self.BLOCK)), 'a = 1\n')

    def test_other_profiles_add_nothing_and_drop_a_stale_block(self):
        script = self.render("axon-work-computer")
        self.assertEqual(without_codex_guard(run_script(script, 'a = 1\n')), 'a = 1\n')
        self.assertEqual(without_codex_guard(run_script(script, self.BLOCK)), 'a = 1\n')

    def test_caveman_strip_still_works(self):
        out = run_script(self.render("axon-work-computer"), '# chezmoi:caveman-style:begin\nx\n# chezmoi:caveman-style:end\nb = 2\n')
        self.assertNotIn("caveman", out)
        self.assertIn("b = 2", out)


class DefaultTest(unittest.TestCase):
    @on_mac
    def test_test_instances_are_off_unless_data_turns_them_on(self):
        env = Env()
        env.cfg.write_text("data:\n  profile: personal\n")  # no t3Hub key: the .chezmoidata.toml default applies
        try:
            script = env.render("dot_t3/private_userdata/modify_settings.json.tmpl")
        finally:
            env.close()
        with_ours = run_script(script, FIXTURE, want='{"claude-hub":{"driver":"claudeAgent"},"codex-hub":{"driver":"codex"}}')
        left = json.loads(run_script(script, with_ours))["providerInstances"]
        self.assertFalse(set(OURS) & set(left))  # applying the default removes both


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
        elif sys.platform.startswith("linux"):
            # personal Linux manages the settings file (worktreesDirectory), not the hub's Claude settings file; LinuxSettingsTest runs it
            self.assertEqual(self.hub_paths("personal"), {".t3", ".t3/userdata", ".t3/userdata/settings.json"}, "personal on Linux")
        else:
            self.assertEqual(self.hub_paths("personal"), set())

    def test_bad_switch_value_fails_the_render(self):
        env = Env()
        env.cfg.write_text("data:\n  profile: personal\n  t3Hub:\n    enabled: maybe\n")
        try:
            with self.assertRaises(AssertionError):
                env.chezmoi("managed")
        finally:
            env.close()


class LinuxSettingsTest(unittest.TestCase):
    """Personal Linux applies the settings script with the hub n/a: worktreesDirectory in the home directory, the window, no hub instance, and the pi and pi-lead instances.

    The chezmoi OS is overridden to linux, so this runs the same on the Mac's CI job.
    """

    def render(self, chezmoi_os="linux"):
        env = Env(codex_active=False)
        try:
            data = json.dumps({"chezmoi": {"os": chezmoi_os}})
            home = str(env.home)
            script = env.chezmoi("execute-template", "--override-data", data, stdin=(REPO / "dot_t3/private_userdata/modify_settings.json.tmpl").read_text())
        finally:
            env.close()
        return script, home

    def test_worktrees_go_to_the_home_directory_and_no_hub_instance_appears(self):
        script, home = self.render()
        out = json.loads(run_script(script, FIXTURE))
        self.assertEqual(out["worktreesDirectory"], home + "/t3-worktrees")
        self.assertFalse(set(OURS) & set(out["providerInstances"]))
        self.assertEqual(out["providerInstances"]["codex"], json.loads(FIXTURE)["providerInstances"]["codex"], "the codex instance is left alone without the hub")
        for i in WINDOW_IDS:
            self.assertEqual(out["providerInstances"][i]["config"]["autoCompactWindow"], WINDOWS[i])
        self.assertEqual(out["idleCompaction"], IDLE)
        self.assertNotIn("displayName", out["providerInstances"]["coordinator"])
        self.assertNotIn("usageLimitSources", out)

    def test_compaction_values_are_set_per_instance_and_idle_mode_is_set(self):
        """claudeAgent 300000, coordinator 200000, idleCompaction beforeCacheExpires over T3's onReturn; an empty IDLE_COMPACTION leaves T3's value; a re-run changes nothing."""
        script, _ = self.render()
        before = json.loads(FIXTURE)
        self.assertEqual(before["idleCompaction"], "onReturn")
        out = json.loads(run_script(script, FIXTURE))
        self.assertEqual({i: out["providerInstances"][i]["config"]["autoCompactWindow"] for i in WINDOW_IDS}, {"claudeAgent": "300000", "coordinator": "200000"})
        self.assertEqual(out["idleCompaction"], "beforeCacheExpires")
        self.assertEqual(list(out), list(before))
        self.assertEqual(json.loads(run_script(script, FIXTURE, idle=""))["idleCompaction"], "onReturn")
        data = dict(before)
        del data["idleCompaction"]
        self.assertEqual(json.loads(run_script(script, json.dumps(data, indent=2)))["idleCompaction"], IDLE)
        self.assertNotIn("idleCompaction", json.loads(run_script(script, json.dumps(data, indent=2), idle="")))

    def test_a_second_apply_changes_nothing(self):
        script, _ = self.render()
        once = run_script(script, FIXTURE)
        self.assertEqual(run_script(script, once), once)

    def test_pi_is_enabled_and_every_other_instance_is_unchanged(self):
        """T3's Pi provider is on after the apply (Retro and the steward run on it); codex, claudeAgent and coordinator are as they were."""
        script, _ = self.render()
        before = json.loads(FIXTURE)["providerInstances"]
        out = json.loads(run_script(script, FIXTURE))["providerInstances"]
        self.assertEqual(out["pi"], {"driver": "pi", "enabled": True})
        self.assertEqual(list(out), list(before) + [*SEATS, "pi", "pi-lead"])
        self.assertEqual({k: v for k, v in out.items() if k not in ("pi", "pi-lead", *SEATS)}, with_window({"providerInstances": before})["providerInstances"])

    def test_pi_lead_is_written_with_the_wrapper_path(self):
        """pi-lead is a pi-driver instance whose binaryPath is the wrapper under the (rendered) home directory; pi stays as it was."""
        script, home = self.render()
        out = json.loads(run_script(script, FIXTURE))["providerInstances"]
        self.assertEqual(out["pi-lead"], {"driver": "pi", "displayName": "Pi (lead)", "enabled": True,
                                          "config": {"binaryPath": home + "/.local/user_scripts/pi_lead.sh"}})
        self.assertEqual(out["pi"], {"driver": "pi", "enabled": True})
        self.assertTrue(out["pi-lead"]["config"]["binaryPath"].startswith("/"))

    def test_pi_lead_replaces_a_stale_entry_and_is_owned(self):
        """An edited pi-lead goes back to ours; dropping it from WANT removes it and keeps pi; dropping both removes both."""
        script, _ = self.render()
        data = json.loads(FIXTURE)
        data["providerInstances"]["pi-lead"] = {"driver": "pi", "enabled": False, "config": {"binaryPath": "/x", "launchArgs": "--x"}}
        out = json.loads(run_script(script, json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(out["pi-lead"]["config"], {"binaryPath": out["pi-lead"]["config"]["binaryPath"]})
        self.assertNotEqual(out["pi-lead"]["config"]["binaryPath"], "/x")
        self.assertTrue(out["pi-lead"]["enabled"])
        only_pi = json.dumps({"pi": {"driver": "pi", "enabled": True}})
        gone = json.loads(run_script(script, json.dumps({"providerInstances": out}), want=only_pi))["providerInstances"]
        self.assertNotIn("pi-lead", gone)
        self.assertEqual(gone["pi"], {"driver": "pi", "enabled": True})
        none = json.loads(run_script(script, json.dumps({"providerInstances": out}), want="{}"))["providerInstances"]
        self.assertEqual(list(none), list(json.loads(FIXTURE)["providerInstances"]))

    def test_the_work_profile_has_no_t3_settings_file_and_no_wrapper(self):
        """Work keeps neither the T3 settings file nor the wrapper: both are ignored on axon-work-computer, on either OS."""
        for os_name in ("linux", "darwin"):
            env = Env(profile="axon-work-computer", codex_active=False)
            try:
                managed = env.chezmoi("managed", "--override-data", json.dumps({"chezmoi": {"os": os_name}})).split()
            finally:
                env.close()
            self.assertEqual([m for m in managed if m.startswith(".t3") or m.endswith("pi_lead.sh")], [], os_name)

    def test_personal_linux_manages_the_wrapper_and_the_mac_does_not(self):
        for os_name, expect in (("linux", True), ("darwin", False)):
            env = Env(codex_active=False)
            try:
                managed = env.chezmoi("managed", "--override-data", json.dumps({"chezmoi": {"os": os_name}})).split()
            finally:
                env.close()
            self.assertEqual(".local/user_scripts/pi_lead.sh" in managed, expect, os_name)

    def test_pi_replaces_a_stale_entry_and_is_owned(self):
        """An edited pi entry goes back to ours; dropping pi from WANT removes it (owned), leaving the rest."""
        script, _ = self.render()
        data = json.loads(FIXTURE)
        data["providerInstances"]["pi"] = {"driver": "pi", "enabled": False, "config": {"launchArgs": "--x"}}
        out = json.loads(run_script(script, json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(out["pi"], {"driver": "pi", "enabled": True})
        self.assertEqual(list(out), list(data["providerInstances"]) + [*SEATS, "pi-lead"])
        gone = json.loads(run_script(script, json.dumps({"providerInstances": out}), want="{}"))["providerInstances"]
        self.assertNotIn("pi", gone)
        self.assertEqual(list(gone), list(json.loads(FIXTURE)["providerInstances"]))

    def test_the_mac_still_gets_workshop(self):
        script, _ = self.render("darwin")
        self.assertIn("WORKTREES_DIR='%s'" % WORKTREES, script)

    def test_the_mac_does_not_own_pi(self):
        """pi is personal Linux only: the Mac neither adds it nor removes one that is there."""
        script, _ = self.render("darwin")
        self.assertIn("OWNED='%s'" % json.dumps(["claude-hub", "codex-hub", *SEATS], separators=(",", ":")), script)
        self.assertNotIn("pi-lead", script.split("WANT=")[1].split("\n")[0])
        data = json.loads(FIXTURE)
        data["providerInstances"]["pi"] = {"driver": "pi", "enabled": False}
        out = json.loads(run_script(script, json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(out["pi"], {"driver": "pi", "enabled": False})
        self.assertNotIn("pi", json.loads(run_script(script, FIXTURE))["providerInstances"])
        self.assertNotIn("pi-lead", json.loads(run_script(script, FIXTURE))["providerInstances"])


if __name__ == "__main__":
    unittest.main()


# --- agent seat instances, the per-seat settings files, the shared MCP file and the reader helper ---

WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}
# The skills each seat keeps (restated; the template holds the same lists and the reasons for them).
KEEP = {
    "coordinator": {"coordinating-loop-engine", "correcting-repeated-mistakes", "herdr", "omarchy", "using-lean-change-provider", "using-loop-engine", "using-shartifacts"},
    "lead": {"coordinating-loop-engine", "correcting-repeated-mistakes", "herdr", "hill-climb", "omarchy", "using-lean-change-provider", "using-loop-engine", "using-shartifacts"},
    "builder": {"correcting-repeated-mistakes", "hill-climb", "no-ai-slop", "omarchy", "systematic-debugging", "using-lean-change-provider", "using-loop-engine", "using-policy-document-provider"},
    "planner": {"designing-the-smallest-version", "no-ai-slop"},
    "reviewer": {"designing-the-smallest-version", "review-plans", "reviewing-prs", "using-lean-change-provider"},
}
INSTALLED = sorted({s for k in KEEP.values() for s in k} | {"desloppify", "herdr", "omarchy-app", "writing-skills", "using-research-provider"})


def fleet_env(profile):
    env = Env(profile=profile, codex_active=False)
    if profile == "axon-work-computer":
        env.cfg.write_text(env.cfg.read_text() + "".join("  %s: %s\n" % kv for kv in WORK_DATA.items()))
    skills = env.home / ".claude/skills"
    for name in INSTALLED:
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text("---\nname: %s\n---\n" % name)
    (skills / "synced").mkdir()  # a directory without a SKILL.md is not a skill
    return env


class SeatInstanceTest(unittest.TestCase):
    """The four seat instances in the settings script, on personal Linux and on the Mac."""

    def script(self, chezmoi_os):
        return LinuxSettingsTest().render(chezmoi_os)

    def test_instances_are_written_exactly_on_both_oses(self):
        for os_name in ("linux", "darwin"):
            script, home = self.script(os_name)
            inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
            for sid, expect in seat_instances(home).items():
                self.assertEqual(inst[sid], expect, (os_name, sid))

    def test_windows_and_advisor(self):
        script, _ = self.script("linux")
        inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
        self.assertEqual({i: inst[i]["config"]["autoCompactWindow"] for i in SEATS},
                         {"seat-lead": "200000", "seat-builder": "300000", "seat-planner": "300000", "seat-reviewer": "300000"})
        off = {i for i in SEATS if any(e["name"] == "CLAUDE_CODE_DISABLE_ADVISOR_TOOL" and e["value"] == "1" for e in inst[i].get("environment", []))}
        self.assertEqual(off, {"seat-lead", "seat-reviewer"})
        for i in SEATS:
            self.assertEqual(inst[i]["driver"], "claudeAgent")
            self.assertIn("--strict-mcp-config --mcp-config ", inst[i]["config"]["launchArgs"])

    def test_the_default_and_coordinator_instances_are_not_given_seat_settings(self):
        script, _ = self.script("linux")
        inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
        self.assertEqual(inst["coordinator"]["config"]["launchArgs"], json.loads(FIXTURE)["providerInstances"]["coordinator"]["config"]["launchArgs"])
        self.assertNotIn("launchArgs", inst["claudeAgent"]["config"])
        self.assertEqual(inst["claudeAgent"]["environment"], [FIZZY])  # nothing but the interrupt text variable

    def test_idempotent_stale_entries_return_and_dropping_removes(self):
        script, _ = self.script("linux")
        once = run_script(script, FIXTURE)
        self.assertEqual(run_script(script, once), once)
        data = json.loads(once)
        data["providerInstances"]["seat-reviewer"] = {"driver": "claudeAgent", "enabled": False}
        data["providerInstances"]["seat-lead"]["config"]["autoCompactWindow"] = "900000"
        fixed = json.loads(run_script(script, json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(fixed["seat-reviewer"], json.loads(once)["providerInstances"]["seat-reviewer"])
        self.assertEqual(fixed["seat-lead"]["config"]["autoCompactWindow"], "200000")
        gone = json.loads(run_script(script, once, want="{}"))["providerInstances"]
        self.assertFalse(set(SEATS) & set(gone))

    def test_other_instances_and_keys_are_untouched(self):
        script, _ = self.script("linux")
        before = json.loads(FIXTURE)
        out = json.loads(run_script(script, FIXTURE))
        for k in before["providerInstances"]:
            self.assertEqual(out["providerInstances"][k], with_window(before)["providerInstances"][k], k)


class FizzyGroveTest(unittest.TestCase):
    """CLAUDE_CODE_FIZZY_GROVE=1 in the `environment` of every Claude instance, merged by name with what is already there."""

    def script(self, chezmoi_os="linux"):
        return LinuxSettingsTest().render(chezmoi_os)

    def fizzy(self, inst):
        return [e for e in inst.get("environment", []) if e["name"] == "CLAUDE_CODE_FIZZY_GROVE"]

    def test_every_claude_instance_has_it_exactly_once(self):
        for os_name in ("linux", "darwin"):
            script, _ = self.script(os_name)
            inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
            for i in ("claudeAgent", "coordinator") + SEATS:
                self.assertEqual(self.fizzy(inst[i]), [FIZZY], (os_name, i))
            self.assertEqual(self.fizzy(inst["codex"]), [])

    def test_the_hub_instance_has_it_too(self):
        # claude-hub is written on personal macOS only (test_instance_shapes checks its exact shape there); on any OS the template text must carry it.
        src = (REPO / "dot_t3/private_userdata/modify_settings.json.tmpl").read_text()
        self.assertIn('(dict "name" "ANTHROPIC_API_KEY" "value" "" "sensitive" false) $fizzy)', src)

    def test_existing_environment_entries_are_kept_in_order(self):
        script, _ = self.script()
        data = json.loads(FIXTURE)
        for i in ("claudeAgent", "coordinator"):
            data["providerInstances"][i]["environment"] = [{"name": "KEEP_ME", "value": "x", "sensitive": False}, {"name": "ALSO", "value": "y", "sensitive": True}]
        out = json.loads(run_script(script, json.dumps(data)))["providerInstances"]
        for i in ("claudeAgent", "coordinator"):
            self.assertEqual(out[i]["environment"], [{"name": "KEEP_ME", "value": "x", "sensitive": False}, {"name": "ALSO", "value": "y", "sensitive": True}, FIZZY], i)

    def test_the_seat_advisor_entry_is_kept(self):
        script, _ = self.script()
        inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
        self.assertEqual([e["name"] for e in inst["seat-lead"]["environment"]], ["CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "CLAUDE_CODE_FIZZY_GROVE"])
        self.assertEqual([e["name"] for e in inst["seat-builder"]["environment"]], ["CLAUDE_CODE_FIZZY_GROVE"])

    def test_a_wrong_value_is_replaced_in_place_and_a_second_apply_changes_nothing(self):
        script, _ = self.script()
        data = json.loads(FIXTURE)
        data["providerInstances"]["claudeAgent"]["environment"] = [{"name": "CLAUDE_CODE_FIZZY_GROVE", "value": "0", "sensitive": False}, {"name": "AFTER", "value": "z", "sensitive": False}]
        once = run_script(script, json.dumps(data))
        env = json.loads(once)["providerInstances"]["claudeAgent"]["environment"]
        self.assertEqual(env, [FIZZY, {"name": "AFTER", "value": "z", "sensitive": False}])
        self.assertEqual(run_script(script, once), once)

    def test_an_absent_instance_is_not_created(self):
        script, _ = self.script()
        data = json.loads(FIXTURE)
        del data["providerInstances"]["coordinator"]
        out = json.loads(run_script(script, json.dumps(data)))["providerInstances"]
        self.assertNotIn("coordinator", out)


class FleetFilesTest(unittest.TestCase):
    """~/.claude/fleet/*.json and ~/.claude/agents/reader.md, rendered for both desktop profiles."""

    def render(self, env, source):
        return json.loads(env.render("dot_claude/fleet/%s.tmpl" % source))

    def test_every_seat_file_denies_artifact_trims_skills_and_keeps_only_its_list(self):
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                for seat, keep in KEEP.items():
                    f = self.render(env, "seat-%s.json" % seat)
                    self.assertEqual(set(f), {"permissions", "syncClaudeAiSkills", "disableBundledSkills", "skillOverrides"}, (profile, seat))
                    self.assertEqual(f["permissions"], {"deny": ["Artifact"]})
                    self.assertIs(f["syncClaudeAiSkills"], False)
                    self.assertIs(f["disableBundledSkills"], True)
                    self.assertEqual(set(f["skillOverrides"].values()), {"off"})
                    self.assertEqual(set(f["skillOverrides"]), set(INSTALLED) - keep, (profile, seat))
                    self.assertNotIn("synced", f["skillOverrides"])
            finally:
                env.close()

    def test_a_kept_skill_that_is_not_installed_adds_nothing(self):
        env = Env(codex_active=False)
        try:
            self.assertEqual(self.render(env, "seat-planner.json")["skillOverrides"], {})
        finally:
            env.close()

    def test_the_mcp_file_has_only_hindsight_and_shartifacts(self):
        for profile, bank, origin in (("personal", "cartwmic", "personal"), ("axon-work-computer", "work", "work")):
            env = fleet_env(profile)
            try:
                servers = self.render(env, "mcp.json")["mcpServers"]
                self.assertEqual(set(servers), {"hindsight", "shartifacts"}, profile)
                self.assertTrue(servers["hindsight"]["url"].endswith("/mcp/%s/" % bank))
                self.assertEqual(servers["shartifacts"]["headers"], {"X-Origin": origin, "X-Thread": "${T3CODE_THREAD_ID:-}"})
            finally:
                env.close()

    def test_fleet_files_and_reader_deploy_on_both_profiles(self):
        want = {".claude/agents/reader.md", ".claude/fleet/mcp.json", *(".claude/fleet/seat-%s.json" % s for s in KEEP)}
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                self.assertTrue(want <= set(env.chezmoi("managed", "--include=files").split()), profile)
            finally:
                env.close()

    def test_reader_is_a_haiku_read_only_helper(self):
        text = (REPO / "dot_claude/agents/reader.md").read_text()
        front = dict(l.split(": ", 1) for l in text.split("---\n")[1].strip().splitlines())
        self.assertEqual((front["name"], front["model"], front["tools"]), ("reader", "claude-haiku-5-5", "Read, Grep, Glob"))
        self.assertIn("100,000 tokens", text)
        self.assertIn("file:line", text)

    def test_the_reader_instruction_is_in_the_canonical_instructions(self):
        text = (REPO / "dot_local/share/agent-harness/canonical/instructions/AGENTS.md").read_text()
        self.assertIn("Leads and the coordinator do not read files to find or understand something: in Claude Code they ask the `reader` helper", text)
        self.assertIn("in another harness they use its cheapest read-only helper, or read directly if it has none", text)
        self.assertIn("Wait for CI with `gh run watch <id> --exit-status` and for long jobs with `run-and-wake`. Never poll by hand in a loop.", text)
        self.assertIn("Builders read the files they edit and reviewers the diffs they judge.", text)
        self.assertIn("Advisor tool. If you have it, call it once, early, before you commit to an approach. This replaces the tool's own advice to call it again before declaring done", text)
