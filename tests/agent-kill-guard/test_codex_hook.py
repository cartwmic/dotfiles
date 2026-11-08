"""Codex's PreToolUse guard hook: ~/.codex/hooks.json (dot_codex/modify_hooks.json.tmpl), the [hooks.state] anchor in config.toml
(dot_codex/modify_private_config.toml.tmpl), and the step that trusts exactly that hook through Codex's own API
(dot_local/user_scripts/executable_codex_trust_hooks.py, run after every full apply by run_after_90_codex_hook_trust.sh.tmpl).

The modify scripts are rendered with real chezmoi for both profiles. The trust step runs against a real `codex app-server` in a scratch
CODEX_HOME (skipped without a codex binary); nothing here calls a model.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python before 3.11
    tomllib = None

ROOT = Path(__file__).resolve().parents[2]
HOOKS_TMPL = ROOT / "dot_codex/modify_hooks.json.tmpl"
CONFIG_TMPL = ROOT / "dot_codex/modify_private_config.toml.tmpl"
TRUST = ROOT / "dot_local/user_scripts/executable_codex_trust_hooks.py"
COMMAND = (ROOT / ".chezmoitemplates/codex_guard_command").read_text()
CODEX = shutil.which("codex") or next(iter(sorted(glob.glob(os.path.expanduser("~/.t3/tools/codex/*/bin/codex")))[::-1]), None)
OWNER_GROUP = {"matcher": "^Bash$", "hooks": [{"type": "command", "command": "echo someone-elses-hook", "timeout": 5}]}
OURS = {"matcher": "^Bash$", "hooks": [{"type": "command", "command": COMMAND, "timeout": 10}]}
PERSONAL_HUB = {"profile": "personal", "hub": {"enabled": True}, "t3Hub": {"enabled": False}}
WORK = {"profile": "axon-work-computer", "hub": {"enabled": False}}


def render(template, data):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": data}))
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                           input=template.read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=tmp))
    assert r.returncode == 0, r.stderr
    return r.stdout


def run_script(script, existing, env=None):
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(script)
    try:
        return subprocess.run(["sh", f.name], input=existing, capture_output=True, text=True, timeout=60, env=env)
    finally:
        os.unlink(f.name)


def modify(script, existing, env=None):
    r = run_script(script, existing, env)
    assert r.returncode == 0, r.stderr
    return r.stdout


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class HooksJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = {"personal": render(HOOKS_TMPL, PERSONAL_HUB), "work": render(HOOKS_TMPL, WORK)}

    def test_a_missing_or_empty_file_gets_only_our_group_and_both_profiles_share_one_command(self):
        for profile, script in self.scripts.items():
            for existing in ("", "  \n"):
                with self.subTest(profile=profile, existing=existing):
                    self.assertEqual(json.loads(modify(script, existing)), {"hooks": {"PreToolUse": [OURS]}})

    def test_ours_is_appended_last_and_everything_else_is_kept(self):
        owner = {"theme": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}], "PreToolUse": [OWNER_GROUP]}}
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                out = json.loads(modify(script, json.dumps(owner)))
                self.assertEqual(out["hooks"]["PreToolUse"], [OWNER_GROUP, OURS])  # appended: the owner's group keeps index 0
                self.assertEqual(out["hooks"]["Stop"], owner["hooks"]["Stop"])
                self.assertEqual(out["theme"], "x")

    def test_when_ours_is_already_there_the_input_comes_back_byte_for_byte(self):
        text = '{\n  "hooks": {"PreToolUse": [%s,   %s]}\n}\n' % (json.dumps(OWNER_GROUP), json.dumps(OURS))  # ours not last, odd spacing
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                self.assertEqual(modify(script, text), text)

    def test_second_run_is_idempotent_and_the_trailing_newline_follows_the_file(self):
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                once = modify(script, '{"hooks": {}}\n')
                self.assertTrue(once.endswith("\n"))
                self.assertEqual(modify(script, once), once)
                self.assertFalse(modify(script, '{"hooks": {}}').endswith("\n"))

    def test_a_loose_mention_of_the_script_is_not_ours(self):
        sneaky = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo agent-harness/hooks/refuse_pattern_kill.py", "statusMessage":
                                                "mentions refuse_pattern_kill.py"}]}
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                out = json.loads(modify(script, json.dumps({"hooks": {"PreToolUse": [sneaky]}})))
                self.assertEqual(out["hooks"]["PreToolUse"], [sneaky, OURS])

    def test_not_json_or_not_an_object_or_no_jq_leaves_the_file_as_it_is(self):
        no_jq = dict(os.environ, PATH="/usr/bin:/bin")  # no jq on this PATH when jq lives elsewhere; checked below
        for profile, script in self.scripts.items():
            for bad in ("// comment\n{}", "[1, 2]", '"text"', "{ not json"):
                with self.subTest(profile=profile, bad=bad):
                    r = run_script(script, bad)
                    self.assertEqual((r.returncode, r.stdout), (0, bad))
                    self.assertIn("WARN", r.stderr)
        if not shutil.which("jq", path=no_jq["PATH"]):
            r = run_script(self.scripts["personal"], '{"a": 1}', env=no_jq)
            self.assertEqual((r.returncode, r.stdout), (0, '{"a": 1}'))
            self.assertIn("jq not found", r.stderr)


@unittest.skipUnless(shutil.which("chezmoi") and tomllib, "chezmoi and Python 3.11+ needed")
class StateAnchor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = render(CONFIG_TMPL, PERSONAL_HUB)
        cls.work = render(CONFIG_TMPL, WORK)

    def test_an_empty_state_header_is_added_above_the_first_table_or_managed_block_and_nothing_else(self):
        base = 'model = "x"\n\n# BEGIN CHEZMOI AGENT HARNESS MCP\n[mcp_servers.a]\nurl = "x"\n# END CHEZMOI AGENT HARNESS MCP\n\n[projects."/p"]\ntrust_level = "trusted"\n'
        for name, script in (("hub", self.hub), ("work", self.work)):
            with self.subTest(profile=name):
                out = modify(script, base)
                self.assertEqual(out.count("[hooks.state]"), 1)
                self.assertLess(out.index('model = "x"'), out.index("[hooks.state]"))
                self.assertLess(out.index("[hooks.state]"), out.index("# BEGIN CHEZMOI AGENT HARNESS MCP"))
                self.assertIn(base.split("\n\n", 1)[1], out)  # every other byte of the owner's file is still there
                self.assertEqual(modify(script, out), out)
                self.assertEqual(tomllib.loads(out)["hooks"], {"state": {}})

    def test_a_file_that_already_has_state_tables_is_left_exactly_as_it_is(self):
        text = 'model = "x"\n\n[projects."/p"]\nk = 1\n\n[hooks.state."/x/hooks.json:pre_tool_use:0:0"]\ntrusted_hash = "sha256:abc"\n'
        self.assertEqual(modify(self.work, text), text)  # byte for byte where nothing else is managed
        out = modify(self.hub, text)  # the hub profile adds its own provider block and key, and no second state header
        self.assertEqual(out.count("[hooks.state"), 1)
        self.assertIn('[projects."/p"]\nk = 1\n\n[hooks.state."/x/hooks.json:pre_tool_use:0:0"]\ntrusted_hash = "sha256:abc"\n', out)

    def test_trust_that_sat_inside_the_hub_block_is_not_what_decides_the_anchor(self):
        # The anchor is looked for after the hub block is stripped; an old [hooks.state] inside it must not suppress the one above it.
        inside = 'model = "x"\n\n# chezmoi:cliproxy-hub:begin\n[model_providers.cliproxy]\nname = "stale"\n[hooks.state]\n# chezmoi:cliproxy-hub:end\n'
        # The hub block is only written back on macOS (the template is "n/a" elsewhere, e.g. the Linux CI runner), but it is stripped everywhere.
        for name, script in (("hub", self.hub), ("work", self.work)):
            with self.subTest(profile=name):
                out = modify(script, inside)
                self.assertEqual(out.count("[hooks.state]"), 1)
                if "# chezmoi:cliproxy-hub:begin" in out:
                    self.assertLess(out.index("[hooks.state]"), out.index("# chezmoi:cliproxy-hub:begin"))
                self.assertEqual(modify(script, out), out)


@unittest.skipUnless(CODEX and shutil.which("chezmoi") and shutil.which("jq") and tomllib, "needs a codex binary, chezmoi, jq and Python 3.11+")
class Trust(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hooks_script = render(HOOKS_TMPL, PERSONAL_HUB)
        cls.config_script = render(CONFIG_TMPL, PERSONAL_HUB)

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.env = dict(os.environ, CODEX_HOME=str(self.home), CODEX_BIN=CODEX)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def install(self, config='model = "x"\n', hooks=""):
        (self.home / "config.toml").write_text(modify(self.config_script, config))
        (self.home / "hooks.json").write_text(modify(self.hooks_script, hooks))

    def apply_again(self):
        """What the next full chezmoi apply does to the two files (the trust step is run separately)."""
        (self.home / "config.toml").write_text(modify(self.config_script, (self.home / "config.toml").read_text()))
        (self.home / "hooks.json").write_text(modify(self.hooks_script, (self.home / "hooks.json").read_text()))

    def trust(self, *args, command=COMMAND):
        return subprocess.run([sys.executable, str(TRUST), "--command", command, *args], capture_output=True, text=True, env=self.env, timeout=120)

    def test_untrusted_then_trusted_then_still_trusted_after_every_next_apply(self):
        self.install()
        self.assertEqual(self.trust("--check").returncode, 1)  # untrusted
        r = self.trust()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 trusted now", r.stdout)
        self.assertEqual(self.trust("--check").returncode, 0)
        before = (self.home / "config.toml").read_text()
        r = self.trust()
        self.assertIn("0 trusted now, 1 already were", r.stdout)  # nothing written when already trusted
        self.assertEqual((self.home / "config.toml").read_text(), before)
        for _ in range(2):
            self.apply_again()
            checked = self.trust("--check")
            self.assertEqual(checked.returncode, 0, checked.stdout)
            self.assertIn("hooks.json:pre_tool_use:0:0 trusted", checked.stdout)

    def test_the_hub_block_last_in_config_toml_does_not_take_the_trust_with_it(self):
        # The comparer's finding: Codex wrote the trust tables before the file's last comment, inside the hub block, and the next apply
        # stripped that block. The [hooks.state] anchor above the first table keeps the trust outside every block we strip.
        self.install()
        self.assertEqual(self.trust().returncode, 0)
        text = (self.home / "config.toml").read_text()
        self.assertEqual(text.count("hooks.state."), 1)
        self.assertLess(text.index("hooks.state."), text.index("# chezmoi:cliproxy-hub:begin"))
        self.apply_again()
        self.assertEqual(self.trust("--check").returncode, 0)

    def test_the_owners_own_hooks_and_tables_survive_and_only_ours_is_trusted(self):
        many = ('model = "x"\n\n# BEGIN CHEZMOI AGENT HARNESS MCP\n[mcp_servers.a]\nurl = "x"\n[mcp_servers.node_repl]\ncommand = "n"\n'
                '# END CHEZMOI AGENT HARNESS MCP\n\n[desktop]\nk = 1\n\n[projects."/x"]\ntrust_level = "trusted"\n\n'
                '[[hooks.PreToolUse]]\nmatcher = "^Bash$"\n\n[[hooks.PreToolUse.hooks]]\ntype = "command"\ncommand = "echo mine-in-config"\n')
        self.install(many, json.dumps({"hooks": {"PreToolUse": [OWNER_GROUP]}}))
        self.assertEqual(self.trust().returncode, 0)
        before = tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(len(before["hooks"]["state"]), 1)  # the owner's two hooks stay untrusted: we never trust them
        self.apply_again()
        after = tomllib.loads((self.home / "config.toml").read_text())
        for table in ("mcp_servers", "desktop", "projects"):
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(after["hooks"]["state"], before["hooks"]["state"])
        self.assertEqual(self.trust("--check").returncode, 0)
        groups = json.loads((self.home / "hooks.json").read_text())["hooks"]["PreToolUse"]
        self.assertEqual(groups, [OWNER_GROUP, OURS])

    def test_a_hooks_json_without_our_hook_is_a_loud_failure_not_a_silent_one(self):
        (self.home / "config.toml").write_text(modify(self.config_script, 'model = "x"\n'))
        (self.home / "hooks.json").write_text("// a comment makes this invalid JSON\n{}")
        r = self.trust()
        self.assertEqual(r.returncode, 1)
        self.assertIn("WARN", r.stdout)
        self.assertIn("no guard hook", r.stdout)

    def test_a_missing_codex_binary_is_a_python_failure_that_the_wrapper_reports(self):
        # HOME is this test's own, so no T3-bundled codex is found and the fallback has nothing to try.
        env = dict(self.env, CODEX_BIN="/nonexistent/codex", HOME=str(self.home), PATH="/usr/bin:/bin")
        r = subprocess.run([sys.executable, str(TRUST), "--command", COMMAND], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 1)  # the wrapper turns this into a failing script with an ERROR line (see Wrapper)
        self.assertIn("WARN", r.stdout)
        self.assertIn("no codex binary answered", r.stdout)


class CodexFallback(unittest.TestCase):
    """The default `codex` on PATH can be present but unable to start (the npm install whose native binary is gone). The helper then tries
    $CODEX_BIN, and then T3's bundled Codex, and fails only when none of them answers. Fake codex binaries; no model is called."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.bin = self.home / "bin"  # the only PATH entry: a `codex` here is the "default" one
        self.bin.mkdir()
        self.env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "CODEX_HOME": str(self.home / "codex-home"),
                    "GUARD_COMMAND": COMMAND}

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def fake(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        path.chmod(0o755)
        return path

    def broken(self, path):
        return self.fake(path, "#!/bin/sh\nexit 3\n")  # starts and exits at once: app-server never answers

    def working(self, path):
        return self.fake(path, FAKE_TRUSTED)  # answers initialize and hooks/list, with our hook already trusted

    def run_trust(self, env_extra=None):
        env = dict(self.env, **(env_extra or {}))
        return subprocess.run([sys.executable, str(TRUST), "--command", COMMAND, "--check"], capture_output=True, text=True, env=env, timeout=120)

    def t3(self, version):
        return self.home / ".t3/tools/codex" / version / "bin/codex"

    def test_the_default_codex_that_will_not_start_falls_back_to_t3_bundled_codex(self):
        self.broken(self.bin / "codex")
        self.working(self.t3("0.166.0"))
        r = self.run_trust()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("%s did not start" % (self.bin / "codex"), r.stdout)  # the skipped candidate is named
        self.assertIn("k trusted", r.stdout)  # the fake app-server's hook, listed as trusted
        self.assertIn(str(self.t3("0.166.0")), r.stdout)  # the one that answered is named

    def test_the_newest_t3_bundled_codex_is_tried_first(self):
        self.broken(self.bin / "codex")
        self.working(self.t3("0.156.1"))
        self.working(self.t3("0.166.0"))
        r = self.run_trust()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(str(self.t3("0.166.0")), r.stdout)
        self.assertNotIn(str(self.t3("0.156.1")), r.stdout)

    def test_codex_bin_when_set_is_used_before_t3_even_with_a_broken_default(self):  # CODEX_BIN is first in the order, then PATH, then T3
        self.broken(self.bin / "codex")
        self.working(self.home / "custom" / "codex")
        self.working(self.t3("0.166.0"))
        r = self.run_trust({"CODEX_BIN": str(self.home / "custom" / "codex")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(str(self.home / "custom" / "codex"), r.stdout)
        self.assertNotIn(str(self.t3("0.166.0")), r.stdout)

    def test_when_no_candidate_answers_it_fails_and_names_each_one(self):
        self.broken(self.bin / "codex")
        self.broken(self.t3("0.166.0"))
        r = self.run_trust()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("WARN: no codex binary answered", r.stdout)
        self.assertIn(str(self.bin / "codex"), r.stdout)
        self.assertIn(str(self.t3("0.166.0")), r.stdout)


WRAPPER_TMPL = ROOT / "run_after_90_codex_hook_trust.sh.tmpl"
FAKE_TRUSTED = '''#!%s
import json, os, sys
# A fake `codex app-server`: answers initialize and hooks/list, with our guard hook already trusted.
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    if msg["method"] == "hooks/list":
        hook = {"command": os.environ["GUARD_COMMAND"], "eventName": "preToolUse", "sourcePath": "/x/hooks.json", "key": "k",
                "currentHash": "h", "trustStatus": "trusted"}
        result = {"data": [{"hooks": [hook]}]}
    else:
        result = {}
    print(json.dumps({"id": msg["id"], "result": result}), flush=True)
''' % sys.executable


class Wrapper(unittest.TestCase):
    """run_after_90_codex_hook_trust.sh.tmpl, rendered by chezmoi and run as chezmoi runs it: its exit code is what decides whether later scripts run."""

    @classmethod
    def setUpClass(cls):
        cls.script = render(WRAPPER_TMPL, PERSONAL_HUB)

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        (self.home / ".local/user_scripts").mkdir(parents=True)
        shutil.copy(TRUST, self.home / ".local/user_scripts/codex_trust_hooks.py")
        self.wrapper = self.home / "wrapper.sh"
        self.wrapper.write_text(self.script)
        self.fake = self.home / "fake-codex"
        self.env = dict(os.environ, HOME=str(self.home), GUARD_COMMAND=COMMAND)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_wrapper(self, codex_body=None, codex_bin=None):
        if codex_body is not None:
            self.fake.write_text(codex_body)
            self.fake.chmod(0o755)
        env = dict(self.env, CODEX_BIN=codex_bin or str(self.fake))
        return subprocess.run(["sh", str(self.wrapper)], capture_output=True, text=True, env=env, timeout=120)

    def test_when_codex_app_server_will_not_start_the_wrapper_exits_1_with_an_error_naming_the_next_step(self):
        r = self.run_wrapper("#!/bin/sh\nexit 3\n")  # exits at once: app-server never answers
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("ERROR: the Codex guard hook is not confirmed trusted", r.stdout)
        self.assertIn("codex app-server did not answer, make it start", r.stdout)  # the next step is named
        self.assertIn("then run dotfiles-update again", r.stdout)  # a step that needs no quoting, so pasting it works
        self.assertNotIn("$", r.stdout.split("ERROR", 1)[1])  # no shell variable left unexpanded in the printed step

    def test_a_missing_codex_binary_fails_the_wrapper_with_the_same_error(self):
        r = self.run_wrapper(codex_bin="/nonexistent/codex")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("ERROR", r.stdout)

    def test_when_the_hook_is_trusted_the_wrapper_exits_0_with_no_error(self):
        r = self.run_wrapper(FAKE_TRUSTED)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("ERROR", r.stdout)
        self.assertIn("Codex guard hook trusted", r.stdout)


class ScriptOrder(unittest.TestCase):
    """Real chezmoi, scratch source and HOME. Scripts run in numeric order, so the trust script is numbered 90, after 30, 65 and 75, and a
    failing trust script must not stop them."""

    def test_the_trust_script_is_numbered_last_and_a_failure_there_skips_nothing_before_it(self):
        self.assertTrue((ROOT / "run_after_90_codex_hook_trust.sh.tmpl").is_file())
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src, home = tmp / "src", tmp / "home"
            src.mkdir()
            home.mkdir()
            cfg = tmp / "chezmoi.yaml"
            cfg.write_text("sourceDir: %s\n" % src)
            for name, marker in (("run_onchange_after_30_a.sh", "30"), ("run_onchange_after_65_b.sh", "65"), ("run_after_75_c.sh", "75")):
                (src / name).write_text('#!/bin/sh\necho %s >> "$HOME/order.log"\n' % marker)
            (src / "run_after_90_d.sh").write_text('#!/bin/sh\necho 90 >> "$HOME/order.log"\necho "ERROR: simulated codex failure" >&2\nexit 1\n')
            env = dict(os.environ, HOME=str(home))
            r = subprocess.run(["chezmoi", "--no-tty", "--config", str(cfg), "--config-format", "yaml", "--source", str(src), "--destination", str(home),
                                "--persistent-state", str(tmp / "state.boltdb"), "apply"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               env=env, timeout=120)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual((home / "order.log").read_text().split(), ["30", "65", "75", "90"], r.stdout)


class NoCodex(unittest.TestCase):
    def test_no_binary_at_all_is_info_and_exit_0_unless_checking(self):
        env = dict(os.environ, PATH="/usr/bin:/bin", HOME=tempfile.mkdtemp())
        env.pop("CODEX_BIN", None)
        if shutil.which("codex", path=env["PATH"]):
            self.skipTest("a codex binary is on the minimal PATH")
        r = subprocess.run([sys.executable, str(TRUST), "--command", COMMAND], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((r.returncode, "INFO" in r.stdout), (0, True))
        r = subprocess.run([sys.executable, str(TRUST), "--command", COMMAND, "--check"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
