"""T3 hub provider instances: dot_t3/private_userdata/modify_settings.json.tmpl, the Codex provider block, the Claude settings file.

Everything runs through chezmoi against the real source with a minimal personal config and a throwaway HOME, so it needs
chezmoi and jq but no 1Password and no network to the hub. settings.live-shape.json is a copy of the real
~/.t3/userdata/settings.json (three instances, no trailing newline).
"""
import difflib
import json
import re
import shutil
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
SEAT_TABLE = (("seat-lead", "200000", False), ("seat-builder", "300000", True), ("seat-planner", "300000", True), ("seat-reviewer", "300000", False), ("seat-scout", "200000", False), ("seat-computer", "200000", False))
# The seats whose helpers (sub-agents started with the Agent tool) default to Haiku 5.5 through CLAUDE_CODE_SUBAGENT_MODEL. Restated here on purpose.
HELPER_SEATS = ("seat-lead", "seat-builder", "seat-planner")
HELPER_MODEL = {"name": "CLAUDE_CODE_SUBAGENT_MODEL", "sensitive": False, "value": "claude-haiku-5-5"}
SEATS = tuple(i for i, _, _ in SEAT_TABLE)
# T3 interrupts a running session to deliver a message; Claude Code then reports a call it skipped as a user decline unless this variable is set (see the template header). Restated here on purpose.
FIZZY = {"name": "CLAUDE_CODE_FIZZY_GROVE", "sensitive": False, "value": "1"}
# Reviewer seat only (audit-1116 proposal 2.2): 5-minute prompt cache writes, and no T3 idle compaction (a 5-minute cache would make it fire about 3 minutes after a run). Restated here on purpose.
FIVE_MIN = {"name": "FORCE_PROMPT_CACHING_5M", "sensitive": False, "value": "1"}
# The durable lead that answers #homelab: a seat-like instance on personal Linux only (where the coordinator runs), with a hook-enforced tool list. Restated here on purpose.
HOMELAB_CHAT = "seat-homelab-chat"
FIZZY_IDS = ("claudeAgent", "coordinator", "claude-hub") + SEATS  # every Claude instance the template owns or finds
# The builder, planner and reviewer seats load their user instructions from ~/.claude/fleet/worker (the same text without the hindsight guide, plus the skill that holds it)
# instead of ~/.claude/CLAUDE.md. The instance adds the folder and the variable that makes Claude Code read CLAUDE.md from an added folder; the seat file excludes CLAUDE.md.
WORKER_SEATS = ("builder", "planner", "reviewer", "computer", "scout")
WORKER_ENV = {"name": "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "sensitive": False, "value": "1"}


def seat_instances(home):
    """The six seat instances as the script writes them (key order is the template's: config, displayName, driver, enabled, environment; inside config the keys are alphabetical, because chezmoi's toJson sorts a dict)."""
    out = {}
    for sid, window, advisor in SEAT_TABLE:
        fleet = "%s/.claude/fleet" % home
        worker = sid.split("-", 1)[1] in WORKER_SEATS
        inst = {"config": {"autoCompactWindow": window,
                           "launchArgs": "--settings %s/%s.json %s--strict-mcp-config --mcp-config %s/%s.json" % (fleet, sid, "--add-dir %s/worker " % fleet if worker else "", fleet, {"seat-computer": "mcp-computer", "seat-scout": "mcp-scout"}.get(sid, "mcp"))},
                "displayName": "Claude (%s)" % sid.split("-", 1)[1], "driver": "claudeAgent", "enabled": True}
        inst["environment"] = ([] if advisor else [{"name": "CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "sensitive": False, "value": "1"}]) + [FIZZY]
        if sid == "seat-reviewer":
            inst["environment"].append(FIVE_MIN)
            inst["config"] = {"autoCompactWindow": window, "idleCompaction": "off", "launchArgs": inst["config"]["launchArgs"]}  # alphabetical: idleCompaction sits before launchArgs
        if worker:
            inst["environment"].append(WORKER_ENV)
        if sid in HELPER_SEATS:
            inst["environment"].append(HELPER_MODEL)
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
    """SETTLED plus the six seat instances: what the settings file holds once the hub is off (the seats are not part of the hub switch)."""
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

    def test_adds_exactly_the_two_hub_instances_and_the_five_seats(self):
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
        """Line by line, the diff is eight new objects (two hub, six seat) and the comma on the object before them. Nothing else, to the last line."""
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

    def render(self, chezmoi_os="linux", enabled=True):
        env = Env(codex_active=False, enabled=enabled)
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

    def reordered(self, script, **edit):
        """The script's own output as T3 would rewrite it: other key order and indent, same data. edit sets top-level keys first."""
        data = json.loads(run_script(script, FIXTURE))
        data.update(edit)
        return json.dumps(dict(reversed(list(data.items()))), indent=4, ensure_ascii=False)

    def test_same_data_in_another_key_order_comes_back_byte_for_byte(self):
        """T3 rewrites the file in its own key order; when the merge changes nothing as data the input is printed as it is (no chezmoi drift)."""
        script, _ = self.render()
        text = self.reordered(script)
        self.assertNotEqual(text, run_script(script, FIXTURE))
        self.assertEqual(run_script(script, text), text)
        self.assertEqual(run_script(script, text + "\n"), text + "\n")

    def test_an_owned_key_that_differs_is_still_written_into_reordered_input(self):
        """The pass-through is only for no change: a seat window T3 edited is put back, and the other keys keep the input's order."""
        script, _ = self.render()
        data = json.loads(self.reordered(script))
        data["providerInstances"]["seat-lead"]["config"]["autoCompactWindow"] = "999999"
        data["providerInstances"]["pi"]["enabled"] = False
        text = json.dumps(data, indent=4)
        out = run_script(script, text)
        self.assertNotEqual(out, text)
        fixed = json.loads(out)["providerInstances"]
        self.assertEqual(fixed["seat-lead"]["config"]["autoCompactWindow"], "200000")
        self.assertTrue(fixed["pi"]["enabled"])
        self.assertEqual(list(json.loads(out)), list(data))

    def test_pi_is_enabled_and_every_other_instance_is_unchanged(self):
        """T3's Pi provider is on after the apply (Retro and the steward run on it); codex, claudeAgent and coordinator are as they were."""
        script, _ = self.render()
        before = json.loads(FIXTURE)["providerInstances"]
        out = json.loads(run_script(script, FIXTURE))["providerInstances"]
        self.assertEqual(out["pi"], {"driver": "pi", "enabled": True})
        self.assertEqual(list(out), list(before) + [*SEATS, "pi", "pi-lead", HOMELAB_CHAT])
        self.assertEqual({k: v for k, v in out.items() if k not in ("pi", "pi-lead", HOMELAB_CHAT, *SEATS)}, with_window({"providerInstances": before})["providerInstances"])

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
        self.assertEqual(list(out), list(data["providerInstances"]) + [*SEATS, "pi-lead", HOMELAB_CHAT])
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
    "coordinator": {"coordinating-loop-engine", "correcting-repeated-mistakes", "deriving-readable-docs", "herdr", "no-ai-slop", "omarchy", "using-lean-change-provider", "using-loop-engine", "using-shartifacts"},
    "lead": {"coordinating-loop-engine", "correcting-repeated-mistakes", "deriving-readable-docs", "herdr", "hill-climb", "no-ai-slop", "omarchy", "research-method", "using-lean-change-provider", "using-loop-engine", "using-shartifacts"},
    "builder": {"correcting-repeated-mistakes", "deriving-readable-docs", "hill-climb", "no-ai-slop", "omarchy", "research-method", "systematic-debugging", "using-lean-change-provider", "using-loop-engine", "using-policy-document-provider"},
    "planner": {"correcting-repeated-mistakes", "designing-the-smallest-version", "no-ai-slop", "research-method"},
    "reviewer": {"correcting-repeated-mistakes", "designing-the-smallest-version", "review-plans", "reviewing-prs", "using-lean-change-provider", "using-loop-engine"},
    "computer": {"correcting-repeated-mistakes", "using-computer", "using-browse"},
    "scout": {"correcting-repeated-mistakes"},
}
for _seat in ("lead", "builder"):  # the seats that drive PRs also keep the review-bot loop and reviewing-prs, which its last step runs
    KEEP[_seat] = KEEP[_seat] | {"reviewing-prs", "triaging-automated-review"}
# The tools every seat file but the homelab chat seat's denies (restated from .chezmoitemplates/fleet_seat). The lead and the coordinator kept them until ask #1549 (no session of either called one).
UNUSED_TOOLS = {"ListAgents", "ReportFindings", "ScheduleWakeup", "Workflow"}
UNUSED_TOOL_SEATS = {"lead", "coordinator", "builder", "planner", "reviewer", "computer", "scout"}
# What the scout seat file denies on top of the four tools above: the tools that write files or start or change work (restated from .chezmoitemplates/fleet_seat). Bash stays: searching runs through it.
SCOUT_DENY = ["Edit", "Write", "NotebookEdit", "EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete", "SendMessage", "TaskStop", "DesignSync", "mcp__t3-code"]
# Claude Code's bundled skills that every seat file turns off (restated from .chezmoitemplates/fleet_seat). workflow-authoring stays on only for the homelab chat seat, and is off for the seats that deny the Workflow tool.
BUNDLED_OFF = {"artifact-design", "artifact-diagramming", "claude-api", "code-review", "dataviz", "fewer-permission-prompts", "init", "keybindings-help", "loop",
               "plugin-authoring", "run", "security-review", "simplify", "update-config"}
INSTALLED = sorted({s for k in KEEP.values() for s in k} | {"desloppify", "herdr", "omarchy-app", "writing-skills", "using-research-provider"})
# The skills this source tree ships (the seat files list them even before apply_harness_config.sh has linked them into ~/.claude/skills).
# The skills the seat files name from the source because this apply links them later: the archive external (.chezmoiexternal.toml) review-map; model-fit only where the coordinator checkout has it (these tests have none).
FROM_SOURCE = {"review-map"}
CANONICAL = sorted({p.parent.name for pat in ("*/SKILL.md", "*/SKILL.md.tmpl") for p in (REPO / "dot_local/share/agent-harness/canonical/skills").glob(pat)})  # reviewing-prs ships SKILL.md.tmpl


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


# A canonical skill that tells the agent to "Load the `X` skill" needs X on every seat that keeps it. The map is read from the
# SKILL.md files, so a new such line is checked without anyone adding it here. EXEMPT is {(skill, dependency): reason} for an optional one.
EXEMPT = {}
LOADS = re.compile(r"\b(?:Load|Run|Use|Invoke)\s+the\s+`([a-z0-9-]+)`\s+skill")


def skill_requires():
    out = {}
    for pat in ("*/SKILL.md", "*/SKILL.md.tmpl"):
        for p in (REPO / "dot_local/share/agent-harness/canonical/skills").glob(pat):
            needs = sorted(set(LOADS.findall(p.read_text())) - {p.parent.name})
            if needs:
                out[p.parent.name] = needs
    return out


class SkillRequiresTest(unittest.TestCase):
    def test_the_map_is_read_from_the_skills(self):
        self.assertTrue(skill_requires(), "no 'Load the `X` skill' line found in any canonical SKILL.md: has the wording or the path changed?")

    def test_a_seat_that_keeps_a_skill_keeps_what_it_requires(self):
        missing = ["seat %s keeps %s but not %s, which that skill says to load: add %s to the %s keep list in .chezmoitemplates/fleet_seat"
                   % (seat, skill, need, need, seat)
                   for seat, keep in sorted(KEEP.items()) for skill, needs in sorted(skill_requires().items()) if skill in keep
                   for need in needs if need not in keep and (skill, need) not in EXEMPT]
        self.assertEqual(missing, [])


class SeatInstanceTest(unittest.TestCase):
    """The six seat instances in the settings script, on personal Linux and on the Mac."""

    def script(self, chezmoi_os, enabled=True):
        return LinuxSettingsTest().render(chezmoi_os, enabled)

    def test_instances_are_written_exactly_on_both_oses(self):
        for os_name in ("linux", "darwin"):
            script, home = self.script(os_name)
            inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
            for sid, expect in seat_instances(home).items():
                self.assertEqual(inst[sid], expect, (os_name, sid))

    def test_switch_off_text_is_exactly_the_seated_settings(self):
        """The byte-for-byte text of the Mac's file once the hub switch is off (what ApplyPathTest checks, but that one runs on macOS only): the seats stay, and their config keys come out alphabetical."""
        script, home = self.script("darwin", enabled=False)
        out = run_script(script, SETTLED)
        self.assertEqual(json.loads(out), json.loads(seated(home)))
        self.assertEqual(out.rstrip("\n"), seated(home).rstrip("\n"))

    def test_windows_and_advisor(self):
        script, _ = self.script("linux")
        inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
        self.assertEqual({i: inst[i]["config"]["autoCompactWindow"] for i in SEATS},
                         {"seat-lead": "200000", "seat-builder": "300000", "seat-planner": "300000", "seat-reviewer": "300000", "seat-scout": "200000", "seat-computer": "200000"})
        off = {i for i in SEATS if any(e["name"] == "CLAUDE_CODE_DISABLE_ADVISOR_TOOL" and e["value"] == "1" for e in inst[i].get("environment", []))}
        self.assertEqual(off, {"seat-lead", "seat-reviewer", "seat-scout", "seat-computer"})
        for i in SEATS:
            self.assertEqual(inst[i]["driver"], "claudeAgent")
            self.assertIn("--strict-mcp-config --mcp-config ", inst[i]["config"]["launchArgs"])

    def test_only_the_reviewer_seat_gets_the_five_minute_cache(self):
        script, _ = self.script("linux")
        inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
        for i in tuple(SEATS) + ("claudeAgent", "coordinator"):
            names = [e["name"] for e in inst[i].get("environment", [])]
            self.assertEqual("FORCE_PROMPT_CACHING_5M" in names, i == "seat-reviewer", i)
            self.assertEqual(inst[i].get("config", {}).get("idleCompaction"), "off" if i == "seat-reviewer" else None, i)

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
        self.assertEqual([e["name"] for e in inst["seat-lead"]["environment"]], ["CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "CLAUDE_CODE_FIZZY_GROVE", "CLAUDE_CODE_SUBAGENT_MODEL"])
        self.assertEqual([e["name"] for e in inst["seat-builder"]["environment"]], ["CLAUDE_CODE_FIZZY_GROVE", "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "CLAUDE_CODE_SUBAGENT_MODEL"])

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


class SeatFilesFirstApplyTest(unittest.TestCase):
    """One apply is enough for the seat files. chezmoi writes ~/.claude/fleet/seat-*.json before run script 20 links the skills into
    ~/.claude/skills, so a file that read only that folder came out one skill short on a first apply (review-map, model-fit) and `chezmoi status`
    showed it until the next apply. This applies the files only (no run scripts, no externals) into an empty home, then runs the real skill-link
    step of script 20 (apply_harness_config.sh skills), then asks chezmoi what is still different."""

    def test_a_first_apply_leaves_the_seat_files_clean(self):
        for profile in ("personal", "axon-work-computer"):
            env = Env(profile=profile, codex_active=False)
            if profile == "axon-work-computer":
                env.cfg.write_text(env.cfg.read_text() + "".join("  %s: %s\n" % kv for kv in WORK_DATA.items()))
            try:
                home = env.home
                for d in (".claude/skills", ".claude/fleet", ".local/share/agent-harness"):
                    (home / d).mkdir(parents=True)
                # what lives outside this source: the coordinator checkout's skill (model-fit) and the review-map archive external, as chezmoi extracts it.
                # The checkout is named in the data, because its default path depends on the OS (a Mac with a Workshop SSD defaults to /Volumes/Workshop).
                env.cfg.write_text(env.cfg.read_text() + "  instances:\n    coordinator:\n      repo: %s\n" % (home / "coordinator-stub"))
                for skill, root in (("model-fit", home / "coordinator-stub" / "skills"),
                                    ("review-map", home / ".local/share/agent-harness/external-skills/accountable-review/skills")):
                    (root / skill).mkdir(parents=True)
                    (root / skill / "SKILL.md").write_text("---\nname: %s\n---\n" % skill)
                targets = [str(home / (".claude/fleet/seat-%s.json" % seat)) for seat in KEEP] + [str(home / ".local/share/agent-harness/canonical"), str(home / ".local/share/agent-harness/external-skills/coordinator")]
                env.chezmoi("apply", "--no-tty", "--exclude", "scripts,externals", *targets)
                link = subprocess.run(["sh", str(REPO / "dot_local/user_scripts/executable_apply_harness_config.sh"), "skills"],
                                      capture_output=True, text=True, env=dict(os.environ, HOME=str(home)))
                self.assertEqual(link.returncode, 0, link.stderr)
                linked = {p.name for p in (home / ".claude/skills").iterdir()}
                self.assertTrue({"review-map", "model-fit"} <= linked, linked)
                self.assertEqual(env.chezmoi("status", "--no-tty", *targets[:len(KEEP)]), "", profile)
            finally:
                env.close()


class SeatFilesRefreshTest(unittest.TestCase):
    """A skill that only arrives in this apply, and that the template cannot name from the source (a git-repo external's clone or pull: the work
    profile's private playbook), still reaches every seat file in the same apply. chezmoi writes the files first, script 20 links the skills, and
    refresh_seat_files.sh (run by script 20 last) renders the files again. The skill is staged where a clone puts it, after the files are written."""

    def apply_and_link(self, env):
        home = env.home
        for d in (".claude/skills", ".claude/fleet", ".local/share/agent-harness"):
            (home / d).mkdir(parents=True)
        seats = [str(home / ".claude/fleet" / p.name.removesuffix(".tmpl")) for p in sorted((REPO / "dot_claude/fleet").glob("seat-*.json.tmpl"))]  # every seat file, as the helper finds them
        env.chezmoi("apply", "--no-tty", "--exclude", "scripts,externals", *seats, str(home / ".local/share/agent-harness/canonical"))
        skill = home / ".local/share/agent-harness/external-skills/stand-in-playbook/skills/stand-in-skill"  # <repo>/skills/<skill>, as the playbook repo has it
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: stand-in-skill\n---\n")
        link = subprocess.run(["sh", str(REPO / "dot_local/user_scripts/executable_apply_harness_config.sh"), "skills"],
                              capture_output=True, text=True, env=dict(os.environ, HOME=str(home)))
        self.assertEqual(link.returncode, 0, link.stderr)
        self.assertIn("stand-in-skill", {p.name for p in (home / ".claude/skills").iterdir()})
        return seats

    def refresh(self, env):
        run_env = dict(os.environ, HOME=str(env.home), CHEZMOI_SOURCE_DIR=str(REPO), CHEZMOI_CONFIG_FILE=str(env.cfg), CHEZMOI_DEST_DIR=str(env.home))
        # the config file is YAML but chezmoi infers the format from the name, which here is chezmoi.yaml
        return subprocess.run(["sh", str(REPO / "dot_local/user_scripts/executable_refresh_seat_files.sh")], capture_output=True, text=True, env=run_env, timeout=120)

    def test_the_skill_is_in_every_seat_file_and_a_second_apply_has_nothing_to_do(self):
        for profile in ("personal", "axon-work-computer"):
            env = Env(profile=profile, codex_active=False)
            if profile == "axon-work-computer":
                env.cfg.write_text(env.cfg.read_text() + "".join("  %s: %s\n" % kv for kv in WORK_DATA.items()))
            try:
                seats = self.apply_and_link(env)
                # without the refresh the files are one skill short: this is the gap, so the test fails if it stops being one
                self.assertNotEqual(env.chezmoi("status", "--no-tty", *seats), "", profile)
                for seat in seats:
                    self.assertNotIn("stand-in-skill", json.loads(Path(seat).read_text())["skillOverrides"], profile)
                r = self.refresh(env)
                self.assertEqual(r.returncode, 0, r.stderr)
                for seat in seats:
                    self.assertEqual(json.loads(Path(seat).read_text())["skillOverrides"].get("stand-in-skill"), "off", (profile, seat))
                self.assertEqual(env.chezmoi("status", "--no-tty", *seats), "", profile)
                # the next apply neither rewrites them nor stops to ask whether to overwrite a file "changed since chezmoi last wrote it"
                before = [Path(s).read_bytes() for s in seats]
                env.chezmoi("apply", "--no-tty", *seats)
                self.assertEqual([Path(s).read_bytes() for s in seats], before, profile)
                again = self.refresh(env)
                self.assertEqual((again.returncode, again.stdout), (0, ""), profile)  # nothing to update: no output
            finally:
                env.close()

    def test_it_refuses_to_run_outside_a_chezmoi_script(self):
        r = subprocess.run(["sh", str(REPO / "dot_local/user_scripts/executable_refresh_seat_files.sh")], capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if not k.startswith("CHEZMOI")})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CHEZMOI_SOURCE_DIR", r.stderr)

    def test_script_21_links_then_refreshes_stays_quiet_and_stops_when_linking_fails(self):
        env = Env(codex_active=False)
        try:
            script = REPO / "run_after_21_link_skills_and_refresh_seat_files.sh"
            scripts_dir, log = env.home / ".local/user_scripts", env.home / "order.log"
            scripts_dir.mkdir(parents=True)
            # stand-ins for the two scripts it runs: the link step logs its argument, prints a line only when asked, and fails when asked
            for name, body in (("apply_harness_config.sh", 'echo "link $1" >> "$HOME/order.log"; echo "[apply_harness_config] Linking canonical skills (skills only; MCP settings untouched)"; '
                                '[ ! -e "$HOME/new-link" ] || echo "[apply_harness_config] Linked skill: x"; [ ! -e "$HOME/fail-link" ]'),
                               ("refresh_seat_files.sh", 'echo refresh >> "$HOME/order.log"')):
                (scripts_dir / name).write_text("#!/bin/sh\n" + body + "\n")
                (scripts_dir / name).chmod(0o755)
            run = lambda: subprocess.run(["sh", str(script)], capture_output=True, text=True, env=dict(os.environ, HOME=str(env.home)), timeout=30)
            r = run()
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))  # nothing changed: nothing printed
            self.assertEqual(log.read_text().split(), ["link", "skills", "refresh"])
            log.unlink()
            (env.home / "new-link").write_text("")
            self.assertEqual(run().stdout, "[apply_harness_config] Linked skill: x\n")  # what it linked is shown
            log.unlink()
            (env.home / "fail-link").write_text("")
            r = run()
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(log.read_text().split(), ["link", "skills"])  # a failed link leaves the files alone and fails the script
            self.assertIn("Linked skill: x", r.stderr)
        finally:
            env.close()

    def test_a_skill_that_arrives_by_a_later_pull_reaches_the_seat_files_in_that_apply(self):
        """The work Mac already has the playbook clone, so a new playbook skill arrives by a pull, which changes no input of script 20.
        A real chezmoi apply of a pruned copy of this source (the files that matter here, plus script 21 and the real link script, and the
        git-repo external only: no network) against a real local git repo that gains a skill between two applies."""
        env = Env(profile="axon-work-computer", codex_active=False)
        try:
            tmp = env.home.parent
            git = lambda *a, cwd=None: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True, capture_output=True, text=True)
            upstream, bare = tmp / "upstream", tmp / "playbook.git"
            upstream.mkdir()
            git("init", "-q", cwd=upstream)
            add_skill = lambda name: ((upstream / "skills" / name).mkdir(parents=True, exist_ok=True), (upstream / "skills" / name / "SKILL.md").write_text("---\nname: %s\n---\n" % name),
                                      git("add", "-A", cwd=upstream), git("commit", "-qm", name, cwd=upstream))
            add_skill("playbook-one")
            git("clone", "-q", "--bare", str(upstream), str(bare))
            env.cfg.write_text(env.cfg.read_text() + "".join("  %s: %s\n" % kv for kv in WORK_DATA.items()) + "  axonPlaybook:\n    repo: file://%s\n" % bare)
            src = tmp / "src"
            for rel in (".chezmoidata.toml", ".chezmoiignore", ".chezmoitemplates", "dot_claude/fleet", "dot_local/share/agent-harness",
                        "dot_local/user_scripts/executable_apply_harness_config.sh", "dot_local/user_scripts/executable_refresh_seat_files.sh",
                        "run_after_21_link_skills_and_refresh_seat_files.sh"):
                dest = src / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                (shutil.copytree if (REPO / rel).is_dir() else shutil.copy2)(REPO / rel, dest)
            externals = (REPO / ".chezmoiexternal.toml").read_text()
            (src / ".chezmoiexternal.toml").write_text(externals[externals.index("# Private Axon"):])  # the git-repo external; the archive one needs the network
            seats = [env.home / ".claude/fleet" / p.name.removesuffix(".tmpl") for p in sorted((src / "dot_claude/fleet").glob("seat-*.json.tmpl"))]
            self.assertEqual(len(seats), len(KEEP) + 1)  # the seats plus homelab-chat

            def chez(*args):
                r = subprocess.run(["chezmoi", "--source", str(src), "--config", str(env.cfg), "--config-format", "yaml", "--destination", str(env.home),
                                    "--cache", str(tmp / "cache"), *args], capture_output=True, text=True, env=dict(os.environ, HOME=str(env.home)), cwd=str(tmp), timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr)
                return r.stdout + r.stderr

            def apply(*extra):  # chezmoi stats a parent that is missing in an empty home: make the parents first
                for d in {os.path.dirname(p) for p in chez("managed", "--path-style=absolute").split()}:
                    os.makedirs(d, exist_ok=True)
                return chez("apply", "--no-tty", "--include", "files,externals,scripts", *extra)

            def skill_everywhere(name):
                self.assertTrue((env.home / ".claude/skills" / name).is_symlink(), name)
                for seat in seats:
                    self.assertEqual(json.loads(seat.read_text())["skillOverrides"].get(name), "off", (name, seat.name))
                self.assertEqual(chez("status", "--include=files", *map(str, seats)), "", name)

            apply()
            skill_everywhere("playbook-one")  # a first clone
            add_skill("playbook-two")
            git("push", "-q", str(bare), "HEAD:master", cwd=upstream)
            out = apply("--refresh-externals=always")
            self.assertTrue((env.home / ".local/share/agent-harness/external-skills/axon-agents-playbook/skills/playbook-two/SKILL.md").is_file())  # the pull happened
            skill_everywhere("playbook-two")  # in the same apply, and script 20 (not in this copy) did not run
            self.assertIn("[refresh_seat_files] Updated", out)
            before = [s.read_bytes() for s in seats]
            quiet = apply("--refresh-externals=always")
            self.assertEqual([s.read_bytes() for s in seats], before)
            self.assertNotIn("[refresh_seat_files]", quiet)
            self.assertNotIn("Linked skill", quiet)
        finally:
            env.close()


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
                    # the builder seat also carries its Stop hook (tests/stop-running-jobs); the coordinator seat carries its auto-compact window
                    # every seat file also names its seat in env (COORDINATOR_SEAT)
                    self.assertEqual(set(f), {"permissions", "syncClaudeAiSkills", "disableBundledSkills", "skillOverrides", "env"} | ({"hooks"} if seat in ("builder", "computer") else set()) | ({"advisorModel"} if seat == "builder" else set()) | ({"model", "modelSettings"} if seat == "scout" else set())
                                     | ({"claudeMdExcludes"} if seat in WORKER_SEATS else set())
                                     | ({"autoCompactWindow"} if seat == "coordinator" else set()), (profile, seat))
                    if seat == "coordinator":
                        self.assertEqual(f["autoCompactWindow"], 200000, profile)
                    # every seat but homelab-chat also denies the four tools nobody calls
                    self.assertEqual(f["permissions"], {"deny": ["Artifact"] + (sorted(UNUSED_TOOLS) if seat in UNUSED_TOOL_SEATS else []) + (SCOUT_DENY if seat == "scout" else [])}, (profile, seat))
                    self.assertIs(f["syncClaudeAiSkills"], False)
                    # bundled skills stay on so the Workflow tool keeps its short text (workflow-authoring carries the reference); every other bundled skill is off
                    self.assertIs(f["disableBundledSkills"], False)
                    self.assertEqual(set(f["skillOverrides"].values()), {"off"})
                    # a seat that denies the Workflow tool has no use for workflow-authoring, so it is off there; the homelab chat seat keeps both
                    self.assertEqual("workflow-authoring" in f["skillOverrides"], seat in UNUSED_TOOL_SEATS, (profile, seat))
                    self.assertEqual(set(f["skillOverrides"]), ((set(INSTALLED) | set(CANONICAL) | FROM_SOURCE) - keep) | BUNDLED_OFF | ({"workflow-authoring"} if seat in UNUSED_TOOL_SEATS else set()), (profile, seat))
                    self.assertNotIn("synced", f["skillOverrides"])
            finally:
                env.close()

    def test_every_seat_file_names_its_seat_in_env_and_only_there(self):
        # The coordinator repo's rules hook reads COORDINATOR_SEAT (Claude Code puts a settings `env` into the session's process environment) instead of asking T3 which seat the thread is.
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                for seat in sorted(KEEP) + ["homelab-chat"]:
                    f = self.render(env, "seat-%s.json" % seat)
                    self.assertEqual(f["env"], {"COORDINATOR_SEAT": seat}, (profile, seat))
            finally:
                env.close()

    def test_only_the_worker_seats_skip_every_agents_md(self):
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                for seat in sorted(KEEP) + ["homelab-chat"]:
                    f = self.render(env, "seat-%s.json" % seat)
                    self.assertEqual("**/AGENTS.md" in f.get("claudeMdExcludes", []), seat in WORKER_SEATS, (profile, seat))
            finally:
                env.close()

    def test_no_seat_keeps_a_skill_named_like_a_bundled_one_that_every_seat_turns_off(self):
        # skillOverrides is by name: a kept personal skill called "loop" or "run" would be switched off with the bundled one
        for seat, keep in KEEP.items():
            self.assertEqual(sorted(keep & BUNDLED_OFF), [], seat)
        # and the template refuses to render a seat that keeps one: render a copy of fleet_seat whose planner keep-list adds "loop"
        text = (REPO / ".chezmoitemplates/fleet_seat").read_text()
        old = '"planner" (list "correcting-repeated-mistakes"'
        self.assertIn(old, text)
        clashing = text.replace(old, old + ' "loop"')
        env = fleet_env("personal")
        try:
            call = '{{ template "fleet_seat_clash" (dict "seat" "%s" "ctx" .) }}'
            define = '{{ define "fleet_seat_clash" }}' + clashing + "{{ end }}"
            with self.assertRaises(AssertionError) as raised:
                env.chezmoi("execute-template", stdin=define + call % "planner")
            self.assertIn('seat planner keeps "loop"', str(raised.exception))
            # the same copy renders for a seat that does not keep "loop": the failure is the clash, not the copy
            self.assertEqual(set(json.loads(env.chezmoi("execute-template", stdin=define + call % "reviewer"))["skillOverrides"]) >= BUNDLED_OFF, True)
            # workflow-authoring is off for every seat that denies the Workflow tool, so the refusal covers the planner and the lead (and not the homelab chat seat, which keeps the tool and the skill listed)
            wf = text.replace('"planner" (list "correcting-repeated-mistakes"', '"planner" (list "workflow-authoring" "correcting-repeated-mistakes"').replace(
                '"lead" (list "coordinating-loop-engine"', '"lead" (list "workflow-authoring" "coordinating-loop-engine"').replace(
                '"homelab-chat" (list)', '"homelab-chat" (list "workflow-authoring")')
            wfdef = '{{ define "fleet_seat_clash" }}' + wf + "{{ end }}"
            for seat in ("planner", "lead"):
                with self.assertRaises(AssertionError) as raised:
                    env.chezmoi("execute-template", stdin=wfdef + call % seat)
                self.assertIn('seat %s keeps "workflow-authoring"' % seat, str(raised.exception))
            homelab = json.loads(env.chezmoi("execute-template", stdin=wfdef + call % "homelab-chat"))
            self.assertNotIn("workflow-authoring", homelab["skillOverrides"])
        finally:
            env.close()

    def test_a_kept_skill_that_is_not_installed_adds_nothing(self):
        env = Env(codex_active=False)
        try:
            # nothing under ~/.claude/skills yet: the seat file still lists the source tree's skills, and still not the kept ones
            self.assertEqual(set(self.render(env, "seat-planner.json")["skillOverrides"]), (set(CANONICAL) | FROM_SOURCE) - KEEP["planner"] | BUNDLED_OFF | {"workflow-authoring"})
        finally:
            env.close()

    def test_the_first_apply_of_a_new_skill_already_leaves_the_seat_files_final(self):
        """Chezmoi writes ~/.claude/fleet before apply_harness_config.sh links the canonical skills into ~/.claude/skills. After both, the seat files must equal a fresh render
        (the work Mac's 2026-11-13 apply left seat files without the "off" of two skills it had just linked, and `chezmoi diff` kept showing them)."""
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                skills = env.home / ".claude/skills"
                shutil.rmtree(skills)  # a machine that has not linked the new skills yet
                for d in (".claude", ".local/share/agent-harness", ".local/user_scripts"):
                    (env.home / d).mkdir(parents=True, exist_ok=True)
                env.chezmoi("apply", "--include=dirs,files,symlinks", str(env.home / ".claude/fleet"), str(env.home / ".local/share/agent-harness/canonical"),
                            str(env.home / ".local/user_scripts/apply_harness_config.sh"))
                self.assertFalse(skills.exists(), "the skills are not linked yet when the seat files are written")
                r = subprocess.run(["sh", str(env.home / ".local/user_scripts/apply_harness_config.sh"), "claude"], capture_output=True, text=True, timeout=120,
                                   env=dict(os.environ, HOME=str(env.home), AGENT_HARNESS_APPLY_CLAUDE_MCP="0"))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue((skills / "hill-climb/SKILL.md").exists())
                self.assertEqual(env.chezmoi("diff", "--recursive", str(env.home / ".claude/fleet")), "", profile)
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
        want = {".claude/agents/reader.md", ".claude/fleet/mcp.json", *(".claude/fleet/seat-%s.json" % s for s in KEEP),
                ".claude/fleet/worker/CLAUDE.md", ".claude/fleet/worker/.claude/skills/hindsight-memory/SKILL.md"}
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
        self.assertIn("Wait for CI with `gh run watch <id> --exit-status --interval 60` (the default 3 s poll costs ~3,300 API calls an hour) and for long jobs with `run-and-wake`. Never poll by hand in a loop.", text)
        self.assertIn("Builders read the files they edit and reviewers the diffs they judge.", text)
        self.assertIn("Advisor tool. If you have it, call it once per session, early, before you commit to an approach. This replaces the tool's own advice to call it again before declaring done", text)


class WorkerInstructionsTest(unittest.TestCase):
    """Builder, planner and reviewer sessions start without the hindsight memory guide; the skill that holds it loads when they use the memory tools.

    Three pieces must stay together, or a worker loses all its user instructions and a "no guide" check still passes: the seat file excludes ~/.claude/CLAUDE.md,
    the T3 instance adds the worker folder, and the T3 instance sets the variable that makes Claude Code read CLAUDE.md from an added folder."""

    GUIDE = REPO / "dot_local/share/agent-harness/canonical/instructions/hindsight-guidance.md"

    def worker_file(self, env):
        return env.chezmoi("cat", str(env.home / ".claude/fleet/worker/CLAUDE.md"))

    def full_file(self, env):
        return env.chezmoi("cat", str(env.home / ".claude/CLAUDE.md"))

    def test_the_worker_file_is_the_full_file_minus_exactly_the_guide(self):
        guide = self.GUIDE.read_text()
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                full, worker = self.full_file(env), self.worker_file(env)
                self.assertEqual(full.count(guide), 1, profile)
                self.assertEqual(full.replace(guide, "", 1), worker, profile)
                self.assertNotIn("Memory: `hindsight` MCP server", worker)
                self.assertIn("## Working style", worker)  # the rest of the instructions is still there
            finally:
                env.close()

    def test_the_default_file_still_carries_the_guide_and_matches_the_other_harnesses(self):
        guide = self.GUIDE.read_text()
        env = fleet_env("personal")
        try:
            self.assertIn(guide, self.full_file(env))
            self.assertIn(guide, env.chezmoi("cat", str(env.home / ".codex/AGENTS.md")))
        finally:
            env.close()

    def test_the_skill_holds_the_guide_as_written(self):
        guide = self.GUIDE.read_text()
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                skill = env.chezmoi("cat", str(env.home / ".claude/fleet/worker/.claude/skills/hindsight-memory/SKILL.md"))
                front, body = skill.split("---\n", 2)[1:]
                self.assertEqual(body.lstrip("\n"), guide, profile)
                meta = dict(l.split(": ", 1) for l in front.strip().splitlines())
                self.assertEqual(meta["name"], "hindsight-memory")
                for tool in ("recall", "reflect", "retain", "sync_retain"):
                    self.assertIn(tool, meta["description"])
            finally:
                env.close()

    def test_the_skill_is_not_a_canonical_skill(self):
        """A canonical skill is linked into Codex, Pi, ~/.agents and the default Claude instance; this one is only for the worker seats."""
        self.assertNotIn("hindsight-memory", CANONICAL)
        for harness in ("dot_codex", "dot_pi"):
            self.assertEqual(list((REPO / harness).rglob("hindsight-memory")), [], harness)

    def settings_and_seat_files(self):
        """The rendered settings script's seat instances and the seat files, from one throwaway home so the paths agree."""
        env = fleet_env("personal")
        try:
            script = env.chezmoi("execute-template", "--override-data", json.dumps({"chezmoi": {"os": "linux"}}),
                                 stdin=(REPO / "dot_t3/private_userdata/modify_settings.json.tmpl").read_text())
            inst = json.loads(run_script(script, FIXTURE))["providerInstances"]
            seats = {seat: json.loads(env.render("dot_claude/fleet/seat-%s.json.tmpl" % seat)) for seat in KEEP}
            return str(env.home), inst, seats
        finally:
            env.close()

    def test_exclude_folder_and_variable_come_together_on_the_worker_seats_only(self):
        home, inst, seats = self.settings_and_seat_files()
        for seat, f in seats.items():
            has_exclude = f.get("claudeMdExcludes") == ["%s/.claude/CLAUDE.md" % home, "**/AGENTS.md"]  # the user file, and every repo AGENTS.md (a worker's rules come from its brief and the playbook)
            self.assertEqual("claudeMdExcludes" in f, has_exclude, seat)  # no other value
            if seat == "coordinator":  # owned by the coordinator repo: no instance here, and its seat file keeps loading the full file
                self.assertFalse(has_exclude)
                continue
            i = inst["seat-%s" % seat]
            has_dir = ("--add-dir %s/.claude/fleet/worker " % home) in i["config"]["launchArgs"]
            has_var = WORKER_ENV in i["environment"]
            self.assertEqual((has_exclude, has_dir, has_var), (seat in WORKER_SEATS,) * 3, seat)
            if seat in WORKER_SEATS:  # --add-dir takes several values, so a flag must follow it
                self.assertLess(i["config"]["launchArgs"].index("--add-dir"), i["config"]["launchArgs"].index("--strict-mcp-config"))

    def test_the_lead_and_the_default_instances_are_unchanged(self):
        _, inst, _ = self.settings_and_seat_files()
        self.assertNotIn("--add-dir", inst["seat-lead"]["config"]["launchArgs"])
        self.assertNotIn(WORKER_ENV, inst["seat-lead"]["environment"])
        for i in ("claudeAgent", "coordinator"):
            self.assertNotIn(WORKER_ENV, inst[i].get("environment", []), i)
            self.assertNotIn("--add-dir", inst[i]["config"].get("launchArgs", ""), i)

    def test_the_worker_files_deploy_on_both_profiles(self):
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                managed = set(env.chezmoi("managed", "--include=files").split())
                self.assertTrue({".claude/fleet/worker/CLAUDE.md", ".claude/fleet/worker/.claude/skills/hindsight-memory/SKILL.md"} <= managed, profile)
            finally:
                env.close()



# --- the homelab chat seat: instance, settings file, MCP file, and the hook command's fail-closed shape (the hook's own rules are tests/homelab-chat) ---

HOOK_SCRIPT = REPO / "dot_local/share/agent-harness/hooks/homelab_chat_allowlist.py"
def bash_call(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


ALLOWED_CALL = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "python3 ~/git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py queue"}}
DENIED_CALL = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "/x", "old_string": "a", "new_string": "b"}}


class HomelabChatSeatTest(unittest.TestCase):
    """seat-homelab-chat: one instance on personal Linux only, a settings file whose hook command denies when anything is wrong, an MCP file with hindsight only."""

    def instance(self, os_name):
        script, home = LinuxSettingsTest().render(os_name)
        return json.loads(run_script(script, FIXTURE))["providerInstances"], home, script

    def test_the_instance_is_written_on_personal_linux_exactly(self):
        inst, home, script = self.instance("linux")
        fleet = "%s/.claude/fleet" % home
        self.assertEqual(inst[HOMELAB_CHAT], {
            "config": {"autoCompactWindow": "200000",
                       "launchArgs": "--settings %s/seat-homelab-chat.json --strict-mcp-config --mcp-config %s/mcp-homelab-chat.json" % (fleet, fleet)},
            "displayName": "Claude (homelab-chat)", "driver": "claudeAgent", "enabled": True,
            "environment": [{"name": "CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "sensitive": False, "value": "1"}, FIZZY]})
        self.assertIn(HOMELAB_CHAT, json.loads(script.split("OWNED='")[1].split("'")[0]))

    def pod_render(self):
        """The settings script as the agent host pod renders it: personal Linux with `container.enabled` true."""
        env = Env(codex_active=False)
        try:
            env.cfg.write_text(env.cfg.read_text() + "  container:\n    enabled: true\n")
            data = json.dumps({"chezmoi": {"os": "linux"}})
            script = env.chezmoi("execute-template", "--override-data", data, stdin=(REPO / "dot_t3/private_userdata/modify_settings.json.tmpl").read_text())
            return script, str(env.home)
        finally:
            env.close()

    def test_the_pod_in_container_mode_gets_the_same_instance_and_still_no_pi(self):
        # The pod's T3 hosts the #homelab lead, and nothing else writes its instance: the homelab kit cannot be the only place (dotfiles#719 finding).
        script, home = self.pod_render()
        out = json.loads(run_script(script, "{}"))["providerInstances"]
        _, _, linux_script = self.instance("linux")
        outside = json.loads(run_script(linux_script, FIXTURE))["providerInstances"][HOMELAB_CHAT]
        fleet = "%s/.claude/fleet" % home
        self.assertEqual(out[HOMELAB_CHAT]["config"]["launchArgs"], "--settings %s/seat-homelab-chat.json --strict-mcp-config --mcp-config %s/mcp-homelab-chat.json" % (fleet, fleet))
        self.assertEqual({k: v for k, v in out[HOMELAB_CHAT].items() if k != "config"}, {k: v for k, v in outside.items() if k != "config"})
        self.assertEqual(out[HOMELAB_CHAT]["config"]["autoCompactWindow"], "200000")
        self.assertIn(HOMELAB_CHAT, json.loads(script.split("OWNED='")[1].split("'")[0]))
        self.assertFalse({"pi", "pi-lead"} & set(out), "Pi is not in the pod's tool set")
        self.assertEqual(sorted(k for k in out if k.startswith("seat-")), sorted(["seat-%s" % s for s in ("lead", "builder", "planner", "reviewer", "scout", "homelab-chat")]))

    def test_neither_mac_gets_the_instance(self):
        inst, _, script = self.instance("darwin")
        self.assertNotIn(HOMELAB_CHAT, inst)
        self.assertNotIn(HOMELAB_CHAT, script.split("WANT=")[1].split("\n")[0])
        self.assertNotIn(HOMELAB_CHAT, json.loads(script.split("OWNED='")[1].split("'")[0]))

    def test_a_stale_entry_goes_back_to_ours_and_dropping_it_removes_it(self):
        inst, _, script = self.instance("linux")
        data = json.loads(FIXTURE)
        data["providerInstances"][HOMELAB_CHAT] = {"driver": "claudeAgent", "enabled": False, "config": {"launchArgs": "--dangerously-skip-permissions"}}
        out = json.loads(run_script(script, json.dumps(data, indent=2)))["providerInstances"]
        self.assertEqual(out[HOMELAB_CHAT], inst[HOMELAB_CHAT])
        gone = json.loads(run_script(script, json.dumps({"providerInstances": out}), want="{}"))["providerInstances"]
        self.assertNotIn(HOMELAB_CHAT, gone)

    def test_the_seat_file_and_the_mcp_file_deploy_on_both_profiles_with_the_hook_in_the_seat_file_only(self):
        for profile in ("personal", "axon-work-computer"):
            env = fleet_env(profile)
            try:
                managed = set(env.chezmoi("managed", "--include=files").split())
                self.assertTrue({".claude/fleet/seat-homelab-chat.json", ".claude/fleet/mcp-homelab-chat.json", ".local/share/agent-harness/hooks/homelab_chat_allowlist.py"} <= managed, profile)
                seat = json.loads(env.render("dot_claude/fleet/seat-homelab-chat.json.tmpl"))
                self.assertEqual(set(seat), {"permissions", "syncClaudeAiSkills", "disableBundledSkills", "skillOverrides", "hooks", "env"}, profile)
                self.assertEqual(set(seat["skillOverrides"].values()), {"off"})
                self.assertTrue(set(INSTALLED) <= set(seat["skillOverrides"]), "the seat keeps no skill")
                groups = seat["hooks"]["PreToolUse"]
                self.assertEqual([g["matcher"] for g in groups], ["*"], "one hook group, on every tool")
                self.assertEqual([h["type"] for h in groups[0]["hooks"]], ["command"])
                self.assertEqual(set(seat["hooks"]), {"PreToolUse"})
                for other in ("lead", "builder", "planner", "reviewer", "scout"):
                    self.assertNotIn("PreToolUse", json.loads(env.render("dot_claude/fleet/seat-%s.json.tmpl" % other)).get("hooks", {}))
                mcp = json.loads(env.render("dot_claude/fleet/mcp-homelab-chat.json.tmpl"))["mcpServers"]
                self.assertEqual(set(mcp), {"hindsight"}, profile)
                self.assertEqual(mcp["hindsight"], json.loads(env.render("dot_claude/fleet/mcp.json.tmpl"))["mcpServers"]["hindsight"])
            finally:
                env.close()

    def run_hook_command(self, command, payload, path=None, home=None):
        r = subprocess.run(["/bin/sh", "-c", command], input=json.dumps(payload), capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, PATH=path if path is not None else os.environ["PATH"], HOMELAB_CHAT_HOOK_LOG=str(Path(home or tempfile.gettempdir()) / "hook.jsonl")))
        return r.returncode, r.stderr

    def test_the_hook_command_denies_when_the_script_python_or_the_input_is_wrong(self):
        """In Claude Code only exit 2 blocks a tool call. The command from the rendered seat file must exit 2 whenever it cannot say yes."""
        env = fleet_env("personal")
        try:
            command = json.loads(env.render("dot_claude/fleet/seat-homelab-chat.json.tmpl"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            home = env.home
            target = home / ".local/share/agent-harness/hooks/homelab_chat_allowlist.py"
            self.assertIn(str(target), command)
            # no script on disk
            rc, err = self.run_hook_command(command, ALLOWED_CALL, home=home)
            self.assertEqual(rc, 2, err)
            self.assertIn("hook script is missing", err)
            # the real script: allows the call on the list, denies one off it
            target.parent.mkdir(parents=True)
            shutil.copy(HOOK_SCRIPT, target)
            self.assertEqual(self.run_hook_command(command, ALLOWED_CALL, home=home)[0], 0)
            rc, err = self.run_hook_command(command, DENIED_CALL, home=home)
            self.assertEqual((rc, "not on the homelab-chat tool list" in err), (2, True), err)
            # no python3 on PATH (the shell finds nothing: exit 127 from the child becomes 2)
            self.assertEqual(self.run_hook_command(command, ALLOWED_CALL, path="/nonexistent", home=home)[0], 2)
            # a script that crashes, and one that cannot be parsed
            target.write_text("raise SystemExit(1)\n")
            self.assertEqual(self.run_hook_command(command, ALLOWED_CALL, home=home)[0], 2)
            target.write_text("def broken(:\n")
            self.assertEqual(self.run_hook_command(command, ALLOWED_CALL, home=home)[0], 2)
        finally:
            env.close()
