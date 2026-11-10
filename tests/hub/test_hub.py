"""The CLIProxy hub as the default of Claude Code, Codex and the T3 `codex` instance, behind one switch (hub.enabled).

    dot_claude/modify_settings.json.tmpl         env.ANTHROPIC_BASE_URL + apiKeyHelper
    dot_codex/modify_private_config.toml.tmpl    top-level model_provider = "cliproxy"
    dot_t3/private_userdata/modify_settings.json.tmpl   providerInstances.codex -> setupMode existing

Templates are rendered with the real chezmoi against a copy of the source whose `hub` template pretends the OS (chezmoi.os cannot be
overridden by config data), then run as modify scripts. The ApplyPathTest class runs a real `chezmoi apply` into a throwaway HOME
(macOS only). No real HOME, no 1Password, no network.

    python3 -m unittest discover -s tests/hub -v
"""
import json
import re
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (Path(__file__).parent / "settings.live-shape.json").read_text()  # a copy of the real ~/.t3/userdata/settings.json
CLAUDE, CODEX, T3 = ("dot_claude/modify_settings.json.tmpl", "dot_codex/modify_private_config.toml.tmpl",
                     "dot_t3/private_userdata/modify_settings.json.tmpl")
HOME = "/Users/hubtest"
URL = "https://cliproxy.internal.cartwmic.com"
HELPER = HOME + "/.local/user_scripts/op_read_cached.sh 'op://developer/tb36gtnaocyezjk3dslomp64he/laptop-claude-code'"
CODEX_VERSION = "9.9.9"
BINARY = "%s/.t3/tools/codex/%s/bin/codex" % (HOME, CODEX_VERSION)
ORIGINAL_CODEX = {"driver": "codex", "enabled": True, "config": {"setupMode": "managed"}}
HUB_CODEX = {"driver": "codex", "enabled": True, "config": {"setupMode": "existing", "binaryPath": BINARY}}
NAMES = {"claudeAgent": "Claude", "coordinator": "Claude (coordinator)", "codex": "Codex"}
KEY_REF = "op://developer/tb36gtnaocyezjk3dslomp64he/management"
KEY = "cpa_fake-management-key"
USAGE = {"kind": "cliproxy", "label": "CLIProxy hub", "url": "https://cliproxy.internal.cartwmic.com", "enabled": True, "managementKey": KEY}
LEGACY_ONEPASSWORD = {"kind": "one_password", "label": "1Password", "config": {"account": "my"}}  # what #158 wrote
LEGACY_USAGE = {**USAGE, "managementKey": {"provider": "onepassword", "reference": KEY_REF}}
GATE = '(eq .chezmoi.os "darwin")'
CASES = {  # name: (extra chezmoi data, pretend OS, profile)
    "on": ({}, "darwin", "personal"),
    "off": ({"hub": {"enabled": False}}, "darwin", "personal"),
    "work": ({}, "darwin", "axon-work-computer"),
    "linux": ({}, "linux", "personal"),
    "on_t3hub_off": ({"t3Hub": {"enabled": False}}, "darwin", "personal"),
    "off_t3hub_off": ({"hub": {"enabled": False}, "t3Hub": {"enabled": False}}, "darwin", "personal"),
    "on_t3hub_on": ({"t3Hub": {"enabled": True}}, "darwin", "personal"),
    "off_t3hub_on": ({"hub": {"enabled": False}, "t3Hub": {"enabled": True}}, "darwin", "personal"),
}
SCRATCH = Path(tempfile.mkdtemp())


def fake_home(name, body):
    """A HOME holding a fake op_read_cached.sh (None: no script). It logs its arguments to .calls."""
    home = SCRATCH / name
    (home / ".local/user_scripts").mkdir(parents=True)
    if body is not None:
        script = home / ".local/user_scripts/op_read_cached.sh"
        script.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$(dirname "$0")/.calls"\n' + body + '\n')
        script.chmod(0o755)
    return home


KEY_HOME = fake_home("key-home", "printf %s " + KEY)
FAIL_HOME = fake_home("fail-home", "echo 'op: boom' >&2; exit 1")
JUNK_HOME = fake_home("junk-home", "printf 'not-a-hub-key-SECRETJUNK'")
NO_SCRIPT_HOME = fake_home("no-script-home", None)
HOME_DIR = SCRATCH / "home"
(HOME_DIR / ".t3/tools/codex").mkdir(parents=True)
(HOME_DIR / ".t3/tools/codex/active.json").write_text(json.dumps({"version": CODEX_VERSION}))
EMPTY_HOME = SCRATCH / "home-without-active-json"
EMPTY_HOME.mkdir()


def source(os_name):
    """A copy of the data and templates where the hub and t3_hub gates see os_name."""
    dest = SCRATCH / ("src-" + os_name)
    if not dest.exists():
        shutil.copytree(ROOT / ".chezmoitemplates", dest / ".chezmoitemplates")
        shutil.copy(ROOT / ".chezmoidata.toml", dest / ".chezmoidata.toml")
        for name in ("hub", "t3_hub"):
            f = dest / ".chezmoitemplates" / name
            text = f.read_text()
            assert GATE in text, name
            f.write_text(text.replace(GATE, '(eq "%s" "darwin")' % os_name))
    return dest


def chezmoi(src, data, *args, stdin=None, home=None, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": data}))
        r = subprocess.run(["chezmoi", "--source", str(src), "--config", str(cfg), "--config-format", "yaml", *args],
                           input=stdin, capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=str(home or HOME)))
    assert r.returncode == 0, r.stderr
    return r.stdout


def render(path, case, home=None):
    extra, os_name, profile = CASES[case]
    # a missing coordinator repo keeps the T3 hook out of the Claude settings
    data = dict({"profile": profile, "instances": {"coordinator": {"repo": "/nonexistent/coordinator"}}}, **extra)
    # No accountWeights here: tests/t3-hub covers them, and these comparisons are about the hub (as the window note below).
    data["hub"] = {"usageAccounts": [], **data.get("hub", {})}
    if home is None:  # the T3 script reads active.json through the HOME the template sees
        home = HOME_DIR
    text = chezmoi(source(os_name), data, "execute-template", stdin=(ROOT / path).read_text(), home=home)
    # These tests are about the hub and the names. The "Auto-compact after" value the T3 script also sets on claudeAgent and coordinator
    # is tests/t3-hub's; blank it here (an empty value adds nothing) so the fixture comparisons stay about the hub.
    return text.replace("AUTO_COMPACT_WINDOW='500000'", "AUTO_COMPACT_WINDOW=''") if path == T3 else text


def run(script, stdin, home=None, full=False):
    r = subprocess.run(["sh", "-c", script], input=stdin, capture_output=True, text=True, timeout=30, env=dict(os.environ, HOME=str(home or KEY_HOME)))
    assert r.returncode == 0, r.stderr
    return r if full else r.stdout


def tearDownModule():
    shutil.rmtree(SCRATCH, ignore_errors=True)


needs = unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq") and shutil.which("python3"), "chezmoi and jq needed")


def without_codex_guard(text):
    """The Codex config without the empty [hooks.state] anchor header that every render adds for the guard hook's trust."""
    text, dropped = re.subn(r"(?m)^\[hooks\.state\]\n\n?", "", text, count=1)
    return text.rstrip("\n") + "\n" if dropped and text.strip() else text


def without_guard(settings):
    """The settings without the pattern-kill guard hook, which every render adds (tests/agent-kill-guard covers it)."""
    pre = [g for g in settings.get("hooks", {}).get("PreToolUse", [])
           if not any("refuse_pattern_kill.py" in h.get("command", "") for h in g.get("hooks", []))]
    if "hooks" in settings:
        if pre:
            settings["hooks"]["PreToolUse"] = pre
        else:
            settings["hooks"].pop("PreToolUse", None)
        if not settings["hooks"]:
            del settings["hooks"]
    return settings


@needs
class ClaudeTest(unittest.TestCase):
    USER = {"theme": "dark", "env": {"FOO": "bar"}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}

    @classmethod
    def setUpClass(cls):
        cls.scripts = {c: render(CLAUDE, c) for c in ("on", "off", "work", "linux")}
        # the helper path is built from the HOME chezmoi sees, which render() sets to a scratch dir; compare against that
        cls.helper = "%s/.local/user_scripts/op_read_cached.sh 'op://developer/tb36gtnaocyezjk3dslomp64he/laptop-claude-code'" % HOME_DIR

    def modify(self, case, settings):
        text = settings if isinstance(settings, str) else json.dumps(settings)
        return without_guard(json.loads(run(self.scripts[case], text)))

    def test_on_sets_both_keys_and_keeps_everything_else(self):
        s = self.modify("on", self.USER)
        self.assertEqual(s["env"], {"FOO": "bar", "ANTHROPIC_BASE_URL": URL})
        self.assertEqual(s["apiKeyHelper"], self.helper)
        self.assertEqual((s["theme"], s["hooks"]), ("dark", self.USER["hooks"]))
        for k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            self.assertNotIn(k, s["env"])

    def test_on_is_idempotent_and_works_from_empty(self):
        once = self.modify("on", self.USER)
        self.assertEqual(self.modify("on", once), once)
        for text in ("", "{}"):
            s = self.modify("on", text)
            self.assertEqual((s["env"], s["apiKeyHelper"]), ({"ANTHROPIC_BASE_URL": URL}, self.helper))

    def test_off_removes_ours_and_keeps_a_users_env_keys(self):
        for case in ("off", "work", "linux"):
            s = self.modify(case, self.modify("on", self.USER))
            self.assertEqual(s["env"], {"FOO": "bar"}, case)
            self.assertNotIn("apiKeyHelper", s, case)
            self.assertEqual(s["hooks"]["Stop"], self.USER["hooks"]["Stop"], case)  # work adds its own SessionStart hook
            self.assertEqual(self.modify(case, s), s, case)

    def test_off_prunes_env_when_we_emptied_it_and_never_adds_it(self):
        for case in ("off", "work", "linux"):
            s = self.modify(case, self.modify("on", "{}"))
            self.assertNotIn("env", s, case)
            self.assertNotIn("apiKeyHelper", s, case)
            self.assertNotIn("env", self.modify(case, "{}"), case)

    def test_off_keeps_a_different_url_a_different_helper_and_an_env_the_user_left_empty(self):
        mine = {"env": {"ANTHROPIC_BASE_URL": "https://proxy.example/v1"}, "apiKeyHelper": "/bin/my-helper"}
        for case in ("off", "work", "linux"):
            self.assertEqual(self.modify(case, mine)["env"], mine["env"], case)
            self.assertEqual(self.modify(case, mine)["apiKeyHelper"], "/bin/my-helper", case)
            self.assertEqual(self.modify(case, {"env": {}})["env"], {}, case)

    def test_the_helper_prints_only_the_key(self):
        # op_read_cached.sh must write nothing but the value to stdout (messages go to stderr): fake op, then read twice (miss, hit).
        bindir = SCRATCH / "bin"
        bindir.mkdir(exist_ok=True)
        (bindir / "op").write_text("#!/bin/sh\nprintf 'sk-test-key'\n")
        (bindir / "op").chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + ":" + os.environ["PATH"], HOME=str(SCRATCH),
                   OP_READ_CACHE_DIR=str(SCRATCH / "cache"), OP_SERVICE_ACCOUNT_TOKEN="ops_fake-token-for-tests-only")
        for _ in range(2):
            r = subprocess.run(["sh", str(ROOT / "dot_local/user_scripts/executable_op_read_cached.sh"), "op://developer/x/y"],
                               capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual((r.returncode, r.stdout), (0, "sk-test-key"))


@needs
class CodexTest(unittest.TestCase):
    BASE = 'model = "gpt-6"\n\n# BEGIN CHEZMOI AGENT HARNESS MCP\n[mcp_servers.a]\nurl = "x"\n# END CHEZMOI AGENT HARNESS MCP\n\n[projects."/x"]\ntrust_level = "trusted"\n'
    LINE = 'model_provider = "cliproxy"\n'

    @classmethod
    def setUpClass(cls):
        cls.scripts = {c: render(CODEX, c) for c in CASES}

    def modify(self, case, text):
        return without_codex_guard(run(self.scripts[case], text))

    def test_on_adds_the_top_level_key_the_block_and_keeps_the_rest(self):
        out = self.modify("on", self.BASE)
        toml = tomllib.loads(out)
        self.assertEqual((toml["model"], toml["model_provider"]), ("gpt-6", "cliproxy"))
        self.assertIn("cliproxy", toml["model_providers"])
        self.assertEqual(toml["projects"]["/x"], {"trust_level": "trusted"})
        self.assertEqual(out.count("model_provider ="), 1)
        self.assertTrue(out.startswith(self.LINE + 'model = "gpt-6"'))

    def test_on_is_idempotent_and_works_from_empty_and_a_table_first_file(self):
        once = self.modify("on", self.BASE)
        self.assertEqual(self.modify("on", once), once)
        for text in ("", "[projects.x]\na = 1\n"):
            out = self.modify("on", text)
            self.assertEqual(tomllib.loads(out)["model_provider"], "cliproxy")
            self.assertEqual(self.modify("on", out), out)

    def test_on_replaces_another_top_level_value_and_ignores_the_same_key_in_a_table(self):
        out = self.modify("on", 'model_provider = "openai"\n\n[profiles.x]\nmodel_provider = "keep"\n')
        toml = tomllib.loads(out)
        self.assertEqual((toml["model_provider"], toml["profiles"]["x"]["model_provider"]), ("cliproxy", "keep"))

    def test_off_removes_the_key_only_when_it_is_ours_and_restores_the_file(self):
        for case in ("off_t3hub_off", "work", "linux"):
            self.assertEqual(self.modify(case, self.modify("on", self.BASE)).replace(self.LINE, ""), self.modify(case, self.BASE), case)
            self.assertNotIn("model_provider =", self.modify(case, self.modify("on", self.BASE)).split("[", 1)[0], case)
            self.assertEqual(self.modify(case, 'model_provider = "openai"\n' + self.BASE), 'model_provider = "openai"\n' + self.BASE, case)
            self.assertEqual(self.modify(case, "model_provider = 'cliproxy'\na = 1\n"), "a = 1\n", case)
            nested = '[profiles.x]\nmodel_provider = "cliproxy"\n'
            self.assertEqual(self.modify(case, nested), nested, case)  # only the top-level key is ours

    def test_on_back_to_off_is_byte_for_byte(self):
        self.assertEqual(self.modify("off_t3hub_off", self.modify("on", self.BASE)), self.BASE)

    def test_the_provider_block_stays_while_either_switch_is_on(self):
        has = lambda case: "[model_providers.cliproxy]" in self.modify(case, self.BASE)
        self.assertEqual({c: has(c) for c in ("on", "off", "on_t3hub_off", "off_t3hub_off", "on_t3hub_on", "off_t3hub_on", "work", "linux")},
                         {"on": True, "off": False, "on_t3hub_off": True, "off_t3hub_off": False, "on_t3hub_on": True,
                          "off_t3hub_on": True, "work": False, "linux": False})
        # hub on and t3Hub off: the default needs the block, so the file stays valid for Codex
        toml = tomllib.loads(self.modify("on_t3hub_off", self.BASE))
        self.assertIn(toml["model_provider"], toml["model_providers"])


@needs
class T3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = {c: render(T3, c) for c in CASES}
        cls.scripts["on_no_binary"] = render(T3, "on_t3hub_off", home=EMPTY_HOME)

    def modify(self, case, text, home=None):
        return run(self.scripts[case], text, home)

    def instances(self, text):
        return json.loads(text)["providerInstances"]

    def test_on_changes_only_the_codex_instance(self):
        out = self.modify("on_t3hub_off", FIXTURE)
        before, after = self.instances(FIXTURE), self.instances(out)
        self.assertEqual(after["codex"], {"driver": "codex", "enabled": True, "displayName": "Codex",
                                          "config": {"setupMode": "existing", "binaryPath": "%s/.t3/tools/codex/%s/bin/codex" % (HOME_DIR, CODEX_VERSION)}})
        self.assertEqual(list(after), list(before))  # same ids in the same order
        for untouched in ("claudeAgent", "coordinator"):  # only the name changes
            self.assertEqual({k: v for k, v in after[untouched].items() if k != "displayName"}, before[untouched])
        self.assertEqual({k: v for k, v in json.loads(out).items() if k not in ("providerInstances", "secretProviders", "usageLimitSources")},
                         {k: v for k, v in json.loads(FIXTURE).items() if k != "providerInstances"})
        self.assertEqual(self.modify("on_t3hub_off", out), out)  # idempotent

    def test_off_restores_the_original_byte_for_byte(self):
        on = self.modify("on_t3hub_off", FIXTURE)
        self.assertNotEqual(on, FIXTURE)
        self.assertEqual(self.modify("off_t3hub_off", on), FIXTURE)
        self.assertEqual(self.modify("off_t3hub_off", FIXTURE), FIXTURE)  # nothing to restore
        self.assertEqual(self.instances(FIXTURE)["codex"], ORIGINAL_CODEX)

    def test_other_profiles_and_linux_restore_and_never_add(self):
        on = self.modify("on_t3hub_off", FIXTURE)
        for case in ("work", "linux"):
            self.assertEqual(self.modify(case, FIXTURE).count('"existing"'), 0, case)
            self.assertEqual(self.instances(self.modify(case, on))["codex"], ORIGINAL_CODEX, case)

    def test_an_entry_edited_by_hand_is_not_restored_over(self):
        mine = json.loads(FIXTURE)
        mine["providerInstances"]["codex"] = {"driver": "codex", "enabled": True,
                                              "config": {"setupMode": "existing", "binaryPath": "/opt/codex"}}
        text = json.dumps(mine, indent=2)
        self.assertEqual(self.modify("off_t3hub_off", text), text)

    def test_without_active_json_the_codex_instance_keeps_its_config(self):
        codex = self.instances(self.modify("on_no_binary", FIXTURE))["codex"]
        self.assertEqual(codex, {**ORIGINAL_CODEX, "displayName": "Codex"})

    def test_names_set_only_displayName_and_off_removes_only_ours(self):
        out = self.modify("on_t3hub_off", FIXTURE)
        before, after = self.instances(FIXTURE), self.instances(out)
        for id_, name in NAMES.items():
            self.assertEqual(after[id_]["displayName"], name)
            if id_ != "codex":
                self.assertEqual({k: v for k, v in after[id_].items() if k != "displayName"}, before[id_])
        self.assertEqual(self.modify("on_t3hub_off", out), out)  # idempotent
        # A name edited in T3 is kept on the way out; ours goes.
        edited = json.loads(self.modify("on_t3hub_off", FIXTURE))
        edited["providerInstances"]["claudeAgent"]["displayName"] = "mine"
        kept = self.instances(self.modify("off_t3hub_off", json.dumps(edited, indent=2)))
        self.assertEqual(kept["claudeAgent"]["displayName"], "mine")
        self.assertNotIn("displayName", kept["coordinator"])
        self.assertNotIn("displayName", kept["codex"])

    def test_usage_source_on_off_and_idempotent(self):
        calls = KEY_HOME / ".local/user_scripts/.calls"
        calls.unlink(missing_ok=True)
        on = self.modify("on_t3hub_off", FIXTURE)
        data = json.loads(on)
        self.assertEqual(data["usageLimitSources"], {"cliproxy-hub": USAGE})
        self.assertNotIn("secretProviders", data)
        self.assertEqual(calls.read_text(), KEY_REF + "\n")  # the key is read through op_read_cached.sh, once
        self.assertEqual(self.modify("on_t3hub_off", on), on)
        # Neighbours in the same map survive both ways, and a changed entry of ours is kept on the way out.
        mine = json.loads(on)
        mine["usageLimitSources"]["other"] = {"kind": "cliproxy", "url": "https://x", "managementKey": "k", "enabled": True}
        off = json.loads(self.modify("off_t3hub_off", json.dumps(mine, indent=2)))
        self.assertEqual(list(off["usageLimitSources"]), ["other"])
        mine["usageLimitSources"]["cliproxy-hub"]["url"] = "https://changed"
        kept = json.loads(self.modify("off_t3hub_off", json.dumps(mine, indent=2)))
        self.assertIn("cliproxy-hub", kept["usageLimitSources"])
        # With nothing else there, off leaves the file as it was, and it does not read the key.
        calls.unlink()
        self.assertEqual(self.modify("off_t3hub_off", on), FIXTURE)
        self.assertFalse(calls.exists())

    def test_once_t3_has_moved_the_key_the_next_apply_leaves_it_and_reads_nothing(self):
        on = json.loads(self.modify("on_t3hub_off", FIXTURE))
        on["usageLimitSources"]["cliproxy-hub"]["managementKey"] = "\u2022\u2022\u2022\u2022\u2022\u2022"  # what T3 leaves after moving it
        text = json.dumps(on, indent=2, ensure_ascii=False)
        self.assertEqual(self.modify("on_t3hub_off", text), text)  # settled: no diff, so no preview can show the key
        r = run(self.scripts["on_t3hub_off"], text, FAIL_HOME, full=True)  # and the key is not read at all
        self.assertEqual(r.stdout, text)
        self.assertNotIn("WARN", r.stderr)
        self.assertEqual(self.modify("off_t3hub_off", text), FIXTURE)  # off removes it with the placeholder too

    def test_no_one_password_provider_after_apply(self):
        old = json.loads(FIXTURE)
        old["secretProviders"] = {"onepassword": LEGACY_ONEPASSWORD}
        old["usageLimitSources"] = {"cliproxy-hub": {**LEGACY_USAGE, "enabled": False}}
        for case in ("on_t3hub_off", "off_t3hub_off"):
            out = json.loads(self.modify(case, json.dumps(old, indent=2)))
            self.assertNotIn("secretProviders", out, case)
        on = json.loads(self.modify("on_t3hub_off", json.dumps(old, indent=2)))
        self.assertEqual(on["usageLimitSources"], {"cliproxy-hub": USAGE})  # the old reference and enabled:false are replaced
        # A provider of the same id that is not ours stays, and so does a neighbour.
        old["secretProviders"] = {"onepassword": {**LEGACY_ONEPASSWORD, "label": "Mine"}, "work": LEGACY_ONEPASSWORD}
        self.assertEqual(list(json.loads(self.modify("on_t3hub_off", json.dumps(old, indent=2)))["secretProviders"]), ["onepassword", "work"])

    def test_a_failed_or_wrong_read_leaves_the_entry_warns_and_prints_no_key(self):
        before = json.loads(FIXTURE)  # not settled yet: the legacy reference entry, as live before this PR
        before["usageLimitSources"] = {"cliproxy-hub": {**LEGACY_USAGE, "enabled": False}}
        text = json.dumps(before, indent=2)
        for name, home in (("fail", FAIL_HOME), ("junk", JUNK_HOME), ("no script", NO_SCRIPT_HOME)):
            r = run(self.scripts["on_t3hub_off"], text, home, full=True)
            self.assertEqual(json.loads(r.stdout)["usageLimitSources"], before["usageLimitSources"], name)
            self.assertIn("[modify_settings] WARN", r.stderr, name)
            self.assertNotIn("SECRETJUNK", r.stdout + r.stderr, name)
            fresh = json.loads(run(self.scripts["on_t3hub_off"], FIXTURE, home))  # no entry yet: none is made, the JSON is still valid
            self.assertNotIn("usageLimitSources", fresh, name)
            self.assertEqual(fresh["providerInstances"]["codex"]["config"]["setupMode"], "existing", name)
        ok = run(self.scripts["on_t3hub_off"], text, KEY_HOME, full=True)
        self.assertEqual(ok.stderr, "")

    def test_the_template_never_names_a_1password_account(self):
        text = (ROOT / T3).read_text()
        for bad in ("--account", '"account"'):
            self.assertNotIn(bad, text)

    def test_hub_off_leaves_usage_and_names_alone_that_were_never_ours(self):
        self.assertEqual(self.modify("off_t3hub_off", FIXTURE), FIXTURE)

    def test_missing_file_or_no_provider_instances_key(self):
        for text in ("", "not json", "[1]"):
            self.assertEqual(self.modify("on_t3hub_off", text), text)
        self.assertEqual(self.instances(self.modify("on_t3hub_off", '{"a": 1}'))["codex"]["config"]["setupMode"], "existing")
        self.assertEqual(json.loads(self.modify("off_t3hub_off", '{"a": 1}')), {"a": 1, "worktreesDirectory": "/Volumes/Workshop/macbook/t3-worktrees"})  # the one key the script always sets

    def test_the_two_switches_are_independent(self):
        ids = lambda out: [k for k in self.instances(out) if k.endswith("-hub")]
        self.assertEqual(ids(self.modify("on_t3hub_on", FIXTURE)), ["claude-hub", "codex-hub"])
        self.assertEqual(self.instances(self.modify("on_t3hub_on", FIXTURE))["codex"]["config"]["setupMode"], "existing")
        both = self.modify("on_t3hub_on", FIXTURE)
        off_default = self.modify("off_t3hub_on", both)  # hub off: codex back, the two test instances stay
        self.assertEqual(ids(off_default), ["claude-hub", "codex-hub"])
        self.assertEqual(self.instances(off_default)["codex"], ORIGINAL_CODEX)
        only_default = self.modify("on_t3hub_off", both)  # t3Hub off: test instances go, codex stays on the hub
        self.assertEqual(ids(only_default), [])
        self.assertEqual(self.instances(only_default)["codex"]["config"]["setupMode"], "existing")


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("chezmoi") and shutil.which("jq"), "the hub is gated to macOS")
class ApplyPathTest(unittest.TestCase):
    """chezmoi apply into a throwaway HOME: the same path a real apply takes, with exactly the three real targets."""
    CODEX_BASE = 'model = "gpt-6"\n\n[projects."/x"]\ntrust_level = "trusted"\n'
    TARGETS = (".claude/settings.json", ".codex/config.toml", ".t3/userdata/settings.json")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        (self.home / ".t3/tools/codex").mkdir(parents=True)
        (self.home / ".t3/tools/codex/active.json").write_text(json.dumps({"version": CODEX_VERSION}))
        (self.home / ".t3/userdata").mkdir(mode=0o700)  # T3 keeps userdata private; the source must not loosen it
        (self.home / ".local/user_scripts").mkdir(parents=True)  # a fake op_read_cached.sh: no 1Password here
        fake = self.home / ".local/user_scripts/op_read_cached.sh"
        fake.write_text("#!/bin/sh\nprintf %s " + KEY + "\n")
        fake.chmod(0o755)
        (self.home / ".claude/settings.json").write_text('{"theme": "dark", "env": {"FOO": "bar"}}')
        (self.home / ".codex/config.toml").write_text(self.CODEX_BASE)
        (self.home / ".t3/userdata/settings.json").write_text(FIXTURE)
        self.cfg = Path(self.tmp.name) / "chezmoi.yaml"
        self.set_switch(True)

    def tearDown(self):
        self.tmp.cleanup()

    def set_switch(self, on):
        # t3Hub off: the two test instances and the Claude helper file are tests/t3-hub's; here only the default is under test.
        # No usage accounts either: accountWeights are tests/t3-hub's, and these comparisons are about the usage source itself.
        self.cfg.write_text("data:\n  profile: personal\n  hub:\n    enabled: %s\n    usageAccounts: []\n  t3Hub:\n    enabled: false\n"
                            % ("true" if on else "false"))

    def apply(self, *paths):
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(self.cfg), "--config-format", "yaml",
                            "--destination", str(self.home), "apply", *paths], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(self.home)), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

    def targets(self):
        return [str(self.home / t) for t in self.TARGETS]

    def read(self):
        return {t: without_codex_guard((self.home / t).read_text()) if t.endswith("config.toml") else (self.home / t).read_text() for t in self.TARGETS}

    def test_on_then_off_through_the_real_targets(self):
        self.set_switch(False)
        self.apply(*self.targets())
        baseline = self.read()  # what an apply leaves with the hub off: the other keys these scripts own are added here
        settled = json.loads(FIXTURE)  # plus the "Auto-compact after" value the script sets on claudeAgent and coordinator (tests/t3-hub covers it)
        for i in ("claudeAgent", "coordinator"):
            settled["providerInstances"][i]["config"] = {**settled["providerInstances"][i].get("config", {}), "autoCompactWindow": "500000"}
        self.assertEqual(baseline[".t3/userdata/settings.json"], json.dumps(settled, indent=2, ensure_ascii=False))
        self.assertEqual(baseline[".codex/config.toml"], self.CODEX_BASE)
        self.set_switch(True)
        self.apply(*self.targets())
        claude = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(claude["env"], {"FOO": "bar", "ANTHROPIC_BASE_URL": URL})
        self.assertEqual(claude["apiKeyHelper"], "%s/.local/user_scripts/op_read_cached.sh 'op://developer/tb36gtnaocyezjk3dslomp64he/laptop-claude-code'" % self.home)
        toml = tomllib.loads(without_codex_guard((self.home / ".codex/config.toml").read_text()))
        self.assertEqual((toml["model"], toml["model_provider"]), ("gpt-6", "cliproxy"))
        self.assertIn("cliproxy", toml["model_providers"])
        t3 = json.loads((self.home / ".t3/userdata/settings.json").read_text())["providerInstances"]
        self.assertEqual(t3["codex"], {"driver": "codex", "enabled": True, "displayName": "Codex", "config": {
            "setupMode": "existing", "binaryPath": "%s/.t3/tools/codex/%s/bin/codex" % (self.home, CODEX_VERSION)}})
        self.assertEqual({k: v["displayName"] for k, v in t3.items()}, NAMES)
        self.assertEqual(list(t3), ["codex", "claudeAgent", "coordinator"])
        top = json.loads((self.home / ".t3/userdata/settings.json").read_text())
        self.assertEqual(top["usageLimitSources"], {"cliproxy-hub": USAGE})
        self.assertNotIn("secretProviders", top)
        self.assertEqual(stat.S_IMODE((self.home / ".t3/userdata").stat().st_mode), 0o700)
        again = self.read()
        self.apply(*self.targets())
        self.assertEqual(self.read(), again)  # idempotent
        self.set_switch(False)  # rollback: one flip, same three targets
        self.apply(*self.targets())
        self.assertEqual(self.read(), baseline)
        self.assertEqual(stat.S_IMODE((self.home / ".t3/userdata").stat().st_mode), 0o700)

    def test_full_apply_of_t3_keeps_userdata_private(self):
        self.apply(str(self.home / ".t3"))
        self.assertEqual(stat.S_IMODE((self.home / ".t3/userdata").stat().st_mode), 0o700)
        self.assertEqual(json.loads((self.home / ".t3/userdata/settings.json").read_text())["providerInstances"]["codex"]["config"]["setupMode"], "existing")


@needs
class SwitchTest(unittest.TestCase):
    def test_a_bad_switch_value_fails_the_render(self):
        with self.assertRaises(AssertionError):
            chezmoi(ROOT, {"profile": "personal", "hub": {"enabled": "maybe"}}, "execute-template", stdin=(ROOT / CLAUDE).read_text())


if __name__ == "__main__":
    unittest.main()
