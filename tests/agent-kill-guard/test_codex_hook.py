"""Codex's PreToolUse hook for the guard: the managed block in config.toml (dot_codex/modify_private_config.toml.tmpl) and the step that
trusts exactly that hook through Codex's own API (dot_local/user_scripts/executable_codex_trust_hooks.py).

The modify script is rendered with real chezmoi for both profiles. The trust step runs against a real `codex app-server` in a scratch CODEX_HOME
(skipped without a codex binary); nothing here calls a model.
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
TMPL = ROOT / "dot_codex/modify_private_config.toml.tmpl"
TRUST = ROOT / "dot_local/user_scripts/executable_codex_trust_hooks.py"
CODEX = shutil.which("codex") or next(iter(sorted(glob.glob(os.path.expanduser("~/.t3/tools/codex/*/bin/codex")))[::-1]), None)
MARK = "agent-harness/hooks/refuse_pattern_kill.py"
OTHER = '[[hooks.PreToolUse]]\nmatcher = "^Bash$"\n\n[[hooks.PreToolUse.hooks]]\ntype = "command"\ncommand = "echo someone-elses-hook"\n'


def render(profile):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": {"profile": profile, "hub": {"enabled": False}}}))
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                           input=TMPL.read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=tmp))
    assert r.returncode == 0, r.stderr
    return r.stdout


def modify(script, existing):
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(script)
    try:
        r = subprocess.run(["sh", f.name], input=existing, capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(f.name)
    assert r.returncode == 0, r.stderr
    return r.stdout


@unittest.skipUnless(shutil.which("chezmoi") and tomllib, "chezmoi and Python 3.11+ needed")
class ManagedBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = {p: render(p) for p in ("personal", "axon-work-computer")}

    def test_both_profiles_get_one_pretooluse_hook_that_runs_the_classifier(self):
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                config = tomllib.loads(modify(script, 'model = "x"\n'))
                groups = config["hooks"]["PreToolUse"]
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["matcher"], "^Bash$")
                handler = groups[0]["hooks"][0]
                self.assertEqual(handler["type"], "command")
                self.assertIn(MARK, handler["command"])
                self.assertIn('[ -r "$g" ] || exit 0', handler["command"])
                self.assertEqual(config["model"], "x")

    def test_idempotent_keeps_trust_state_and_other_content_and_replaces_a_stale_block(self):
        existing = ('model = "x"\n\n[hooks.state."/old/config.toml:pre_tool_use:0:0"]\ntrusted_hash = "sha256:abc"\n\n'
                    "# chezmoi:agent-guard:begin\n[[hooks.PreToolUse]]\nmatcher = \"stale\"\n# chezmoi:agent-guard:end\n\n[other]\nk = 1\n")
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                once = modify(script, existing)
                self.assertEqual(modify(script, once), once)
                config = tomllib.loads(once)
                self.assertEqual(config["hooks"]["state"]["/old/config.toml:pre_tool_use:0:0"]["trusted_hash"], "sha256:abc")
                self.assertEqual(config["other"], {"k": 1})
                self.assertEqual([g["matcher"] for g in config["hooks"]["PreToolUse"]], ["^Bash$"])
                self.assertEqual(once.count("chezmoi:agent-guard:begin"), 1)

    def test_the_block_sits_first_so_the_hook_is_index_0_and_the_mcp_block_is_untouched(self):
        mcp = "# BEGIN CHEZMOI AGENT HARNESS MCP\n[mcp_servers.a]\nurl = \"x\"\n# END CHEZMOI AGENT HARNESS MCP\n"
        existing = 'model = "x"\n\n' + mcp + OTHER.replace("[[hooks", "\n[[hooks", 1)
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                out = modify(script, existing)
                self.assertLess(out.index("chezmoi:agent-guard:begin"), out.index("# BEGIN CHEZMOI AGENT HARNESS MCP"))
                self.assertLess(out.index('model = "x"'), out.index("chezmoi:agent-guard:begin"))  # top-level keys stay above any table
                self.assertIn(mcp, out)
                config = tomllib.loads(out)
                self.assertIn(MARK, config["hooks"]["PreToolUse"][0]["hooks"][0]["command"])  # ours is first
                self.assertEqual(config["hooks"]["PreToolUse"][1]["hooks"][0]["command"], "echo someone-elses-hook")
                self.assertEqual(modify(script, out), out)

    def test_trust_tables_codex_wrote_inside_the_block_survive_the_next_apply(self):
        inside = ("model = \"x\"\n\n# chezmoi:agent-guard:begin\n[[hooks.PreToolUse]]\nmatcher = \"old\"\n\n"
                  "[hooks.state.\"/h/config.toml:pre_tool_use:0:0\"]\ntrusted_hash = \"sha256:keep\"\n# chezmoi:agent-guard:end\n")
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                out = modify(script, inside)
                config = tomllib.loads(out)
                self.assertEqual(config["hooks"]["state"]["/h/config.toml:pre_tool_use:0:0"]["trusted_hash"], "sha256:keep")
                block = out[out.index("chezmoi:agent-guard:begin"):out.index("chezmoi:agent-guard:end")]
                self.assertNotIn("hooks.state", block)
                self.assertEqual(modify(script, out), out)

    def test_a_state_table_is_provided_outside_the_block_when_none_exists(self):
        for profile, script in self.scripts.items():
            with self.subTest(profile=profile):
                out = modify(script, 'model = "x"\n')
                self.assertIn("\n[hooks.state]\n", out)
                self.assertGreater(out.index("[hooks.state]"), out.index("chezmoi:agent-guard:end"))


@unittest.skipUnless(CODEX and shutil.which("chezmoi") and tomllib, "needs a codex binary, chezmoi and Python 3.11+")
class Trust(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.env = dict(os.environ, CODEX_HOME=str(self.home), CODEX_BIN=CODEX)
        self.script = render("personal")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def config(self, text):
        (self.home / "config.toml").write_text(text)

    def run_trust(self, *args):
        return subprocess.run([sys.executable, str(TRUST), *args], capture_output=True, text=True, env=self.env, timeout=120)

    def test_untrusted_then_trusted_then_modified_then_trusted_again_and_only_ours(self):
        self.config(modify(self.script, OTHER))  # someone else's hook is in the file; ours is placed first
        self.assertEqual(self.run_trust("--check").returncode, 1)  # untrusted
        r = self.run_trust()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Codex hook trusted", r.stdout)
        checked = self.run_trust("--check")
        self.assertEqual(checked.returncode, 0, checked.stdout)
        self.assertIn("pre_tool_use:0:0 trusted", checked.stdout)  # ours is the first hook
        state = tomllib.loads((self.home / "config.toml").read_text())["hooks"]["state"]
        self.assertEqual(len(state), 1)  # the other hook was not trusted
        self.assertTrue(next(iter(state)).endswith("pre_tool_use:0:0"))
        # the definition changes: Codex calls it modified and skips it until it is trusted again
        text = (self.home / "config.toml").read_text().replace("timeout = 10", "timeout = 11")
        self.config(text)
        self.assertEqual(self.run_trust("--check").returncode, 1)
        self.assertIn("modified", self.run_trust("--check").stdout)
        self.assertEqual(self.run_trust().returncode, 0)
        self.assertEqual(self.run_trust("--check").returncode, 0)

    def test_trust_survives_the_next_apply_when_the_config_had_no_state_table(self):
        # The round trip the live Mac takes: render, trust, render again (the next chezmoi apply), check.
        self.config(modify(self.script, 'model = "x"\n'))
        self.assertEqual(self.run_trust().returncode, 0)
        self.assertEqual(self.run_trust("--check").returncode, 0)
        self.config(modify(self.script, (self.home / "config.toml").read_text()))
        checked = self.run_trust("--check")
        self.assertEqual(checked.returncode, 0, checked.stdout)
        self.assertIn("pre_tool_use:0:0 trusted", checked.stdout)

    def test_a_missing_codex_binary_never_fails_an_apply(self):
        env = dict(self.env, CODEX_BIN="/nonexistent/codex")
        r = subprocess.run([sys.executable, str(TRUST)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARN", r.stdout)


if __name__ == "__main__":
    unittest.main()
