"""A canonical server's env must reach the harness' stored server config, for Claude as for Pi and Codex.
Generated script: real apply_harness_config.sh against scratch roots. Registration: the real claude CLI against a scratch HOME (skipped without claude)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_render import ROOT, TMPL, DARWIN, chezmoi

SCRIPT = ROOT / "dot_local/user_scripts/executable_apply_harness_config.sh"
CLAUDE = shutil.which("claude")


def generate_claude_script(tmp, canonical_text):
    canon = tmp / "canonical"
    (canon / "mcp").mkdir(parents=True, exist_ok=True)
    (canon / "skills").mkdir(exist_ok=True)
    (canon / "mcp/servers.json").write_text(canonical_text)
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "AGENT_HARNESS_CANONICAL_ROOT": str(canon),
           "AGENT_HARNESS_GENERATED_ROOT": str(tmp / "generated"), "AGENT_HARNESS_ADAPTERS_ROOT": str(tmp / "adapters"),
           "AGENT_HARNESS_EXTERNAL_ROOT": str(tmp / "external"), "AGENT_HARNESS_APPLY_CLAUDE_MCP": "0"}
    r = subprocess.run(["sh", str(SCRIPT), "claude"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return tmp / "generated/claude/setup-mcp.sh", home, env


class ClaudeEnvTest(unittest.TestCase):
    def test_generated_command_stores_env_after_the_name(self):
        servers = {"mcpServers": {"x": {"command": "uvx", "args": ["--from", "p==1", "x-mcp"], "env": {"K": "http://h:1", "L": "2"}}}}
        with tempfile.TemporaryDirectory() as t:
            script, _, _ = generate_claude_script(Path(t), json.dumps(servers))
            line = [l for l in script.read_text().splitlines() if 'mcp add' in l][0]
        self.assertIn('mcp add -s user "x" -e "K=http://h:1" -e "L=2" -- "uvx" "--from" "p==1" "x-mcp"', line)
        self.assertFalse(line.startswith("env "), line)

    @unittest.skipUnless(CLAUDE and DARWIN, "needs the claude CLI and the macOS-only entry")
    def test_real_claude_registration_keeps_browser_harness_env(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as t:
                rendered = chezmoi(profile, "execute-template", stdin=TMPL.read_text())
                only = {"mcpServers": {"browser-harness": json.loads(rendered)["mcpServers"]["browser-harness"]}}
                script, home, env = generate_claude_script(Path(t), json.dumps(only))
                r = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                stored = json.loads((home / ".claude.json").read_text())["mcpServers"]["browser-harness"]
                self.assertEqual(stored["env"], {"BU_CDP_URL": "http://127.0.0.1:9333"})
                self.assertEqual(stored["args"][:4], ["--from", "browser-use==1.0.2", "python", "-I"])
                self.assertTrue(stored["args"][4].endswith("/.local/share/browser-harness-mcp/server.py"))


@unittest.skipUnless(CLAUDE, "needs the claude CLI")
class ClaudeReplaceTest(unittest.TestCase):
    """A changed canonical entry replaces the stored one; an unchanged entry is left alone (its stored sign-in survives).
    Real claude CLI, scratch HOME. The servers are test stand-ins: registering a server does not run it."""

    def run_script(self, script, env):
        r = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def stored(self, home):
        return json.loads((home / ".claude.json").read_text())["mcpServers"]

    def test_changed_entry_is_replaced_and_unchanged_entry_is_left_alone(self):
        v1 = {"mcpServers": {"stdio-x": {"command": "uvx", "args": ["--from", "p==1", "x-mcp"], "env": {"K": "1"}},
                             "http-h": {"type": "http", "url": "https://h.example/mcp"}}}
        v2 = json.loads(json.dumps(v1))
        v2["mcpServers"]["stdio-x"]["env"]["K"] = "2"  # the harmless field
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            script, home, env = generate_claude_script(tmp, json.dumps(v1))
            self.run_script(script, env)
            self.assertEqual(self.stored(home)["stdio-x"]["env"], {"K": "1"})
            # Stand-ins for what Claude itself keeps on an entry (a stored sign-in): a key the canonical file never sets.
            data = json.loads((home / ".claude.json").read_text())
            for name in ("stdio-x", "http-h"):
                data["mcpServers"][name]["keep"] = "sign-in"
            (home / ".claude.json").write_text(json.dumps(data))

            out = self.run_script(script, env)  # same canonical: nothing replaced
            self.assertIn("stdio-x: unchanged", out)
            self.assertIn("http-h: unchanged", out)
            self.assertEqual(self.stored(home)["stdio-x"]["keep"], "sign-in")

            script, home, env = generate_claude_script(tmp, json.dumps(v2))  # same scratch HOME, new canonical
            out = self.run_script(script, env)
            self.assertIn("stdio-x: changed in canonical, replacing", out)
            self.assertIn("http-h: unchanged", out)
            now = self.stored(home)
            self.assertEqual(now["stdio-x"]["env"], {"K": "2"})  # before the fix this stayed {"K": "1"}
            self.assertNotIn("keep", now["stdio-x"])  # replaced, so the old entry is gone
            self.assertEqual(now["http-h"]["keep"], "sign-in")  # untouched


if __name__ == "__main__":
    unittest.main()
