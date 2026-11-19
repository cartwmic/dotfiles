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

from test_render import ROOT, TMPL, chezmoi

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

    @unittest.skipUnless(CLAUDE, "needs the claude CLI")
    def test_real_claude_registration_keeps_the_env_of_an_entry(self):   # a stand-in entry that carries env; no canonical entry does today
        entry = {"command": "uvx", "args": ["--from", "p==1", "x-mcp"], "env": {"K": "http://h:1", "L": "2"}}
        with tempfile.TemporaryDirectory() as t:
            script, home, env = generate_claude_script(Path(t), json.dumps({"mcpServers": {"x": entry}}))
            r = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            stored = json.loads((home / ".claude.json").read_text())["mcpServers"]["x"]
            self.assertEqual(stored["env"], {"K": "http://h:1", "L": "2"})
            self.assertEqual((stored["command"], stored["args"]), ("uvx", ["--from", "p==1", "x-mcp"]))

    @unittest.skipUnless(CLAUDE, "needs the claude CLI")
    def test_real_claude_registration_of_browse_on_each_profile(self):
        for profile, os_name in (("personal", "linux"), ("axon-work-computer", "darwin")):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as t:
                data = json.dumps({"chezmoi": {"os": os_name, "homeDir": "/home/test"}})
                rendered = chezmoi(profile, "execute-template", "--override-data", data, stdin=TMPL.read_text())
                only = {"mcpServers": {"browse": json.loads(rendered)["mcpServers"]["browse"]}}
                script, home, env = generate_claude_script(Path(t), json.dumps(only))
                r = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                stored = json.loads((home / ".claude.json").read_text())["mcpServers"]["browse"]
                self.assertEqual((stored["command"], stored["args"]), ("/home/test/.local/share/mise/shims/browse", ["mcp"]))
                self.assertEqual(stored.get("env", {}), {})   # no env, no token: nothing secret in the entry


class ClaudeRetiredTest(unittest.TestCase):
    """browser-harness is retired on both profiles: the Claude step removes a stored entry when canonical lacks it, and leaves a name
    alone when canonical has it. A fake claude records its calls."""

    def calls(self, servers):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            script, home, env = generate_claude_script(tmp, json.dumps({"mcpServers": servers}))
            log = tmp / "claude.log"
            fake = tmp / "claude"
            fake.write_text('#!/bin/sh\necho "$@" >> "$FAKE_LOG"\nexit 0\n')
            fake.chmod(0o755)
            r = subprocess.run(["sh", str(script)], env=dict(env, CLAUDE_BIN=str(fake), FAKE_LOG=str(log)), capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return log.read_text().splitlines(), r.stdout

    def test_a_stored_browser_harness_is_removed_when_canonical_lacks_it(self):
        calls, out = self.calls({"browse": {"command": "/x/browse", "args": ["mcp"]}})
        self.assertIn("mcp remove -s user browser-harness", calls)
        self.assertIn("browser-harness: retired, removed", out)

    def test_a_stored_retired_name_is_kept_when_canonical_has_it(self):   # the guard in RETIRED's loop
        calls, _ = self.calls({"browser-harness": {"command": "uvx", "args": ["x"]}})
        self.assertNotIn("mcp remove -s user browser-harness", calls)


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
