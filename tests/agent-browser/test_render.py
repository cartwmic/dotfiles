"""The agent-browser pieces as chezmoi renders them for both desktop profiles (real chezmoi, scratch config and HOME):
the browser-harness MCP entry, and the agent-chrome launcher. macOS has both on personal and axon-work-computer; elsewhere neither."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / "dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl"
PROFILES = ("personal", "axon-work-computer")
DARWIN = sys.platform == "darwin"
LAUNCHER = ".local/bin/agent-chrome"
ENTRY = {
    "command": "uvx",
    "args": ["--from", "browser-harness[mcp]==0.1.13", "browser-harness-mcp"],
    "env": {"BU_CDP_URL": "http://127.0.0.1:9333"},
}


def chezmoi(profile, *args, stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), *args],
                           input=stdin, capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi %s (%s) failed: %s" % (args[0], profile, r.stderr))
    return r.stdout


class AgentBrowserRenderTest(unittest.TestCase):
    def servers(self, profile):
        return json.loads(chezmoi(profile, "execute-template", stdin=TMPL.read_text()))["mcpServers"]

    def test_mcp_entry_on_macos_for_both_profiles_pinned_and_pointed_at_9333(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                servers = self.servers(profile)
                if DARWIN:
                    self.assertEqual(servers["browser-harness"], ENTRY)
                else:
                    self.assertNotIn("browser-harness", servers)

    def test_launcher_deploys_on_macos_for_both_profiles(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual(LAUNCHER in managed, DARWIN)

    def test_entry_carries_no_secret_placeholder(self):
        self.assertNotIn("${", json.dumps(ENTRY))
        text = TMPL.read_text()
        block = text[text.index('"browser-harness"'):text.index('{{ end }}', text.index('"browser-harness"'))]
        self.assertNotIn("op://", block)
        self.assertNotIn("${", block)


if __name__ == "__main__":
    unittest.main()
