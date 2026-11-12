"""The agent-browser pieces as chezmoi renders them for both desktop profiles (real chezmoi, scratch config and HOME):
the browser-harness MCP entry (it runs browser-use; the name stays so the stored Claude entry is replaced, not left beside a new one), and the agent-chrome launcher. macOS has both on personal and axon-work-computer; Linux has both on personal only."""
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
LINUX = sys.platform.startswith("linux")
LAUNCHER = ".local/bin/agent-chrome"
ENTRY = {
    "command": "uvx",
    "args": ["--from", "browser-use==1.0.2", "python", "-I", "<server.py>"],
    "env": {"BU_CDP_URL": "http://127.0.0.1:9333", "ANONYMIZED_TELEMETRY": "false", "BH_TELEMETRY": "0"},
}


# The local data keys the work profile requires (docs/profiles.md, "Local data keys"); placeholder values.
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


def expected(profile):
    """Does this host's OS and the profile get the agent browser?"""
    return DARWIN or (LINUX and profile == "personal")


def chezmoi(profile, *args, stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile + "".join("  %s: %s\n" % kv for kv in (WORK_DATA.items() if profile == "axon-work-computer" else ())))
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), *args],
                           input=stdin, capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi %s (%s) failed: %s" % (args[0], profile, r.stderr))
    return r.stdout


class AgentBrowserRenderTest(unittest.TestCase):
    def servers(self, profile):
        return json.loads(chezmoi(profile, "execute-template", stdin=TMPL.read_text()))["mcpServers"]

    def test_mcp_entry_where_expected_pinned_and_pointed_at_9333(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                servers = self.servers(profile)
                if expected(profile):
                    entry = dict(servers["browser-harness"])
                    server = entry["args"][-1]
                    self.assertTrue(server.endswith("/.local/share/browser-harness-mcp/server.py"), server)
                    entry["args"] = entry["args"][:-1] + ["<server.py>"]
                    self.assertEqual(entry, ENTRY)
                else:
                    self.assertNotIn("browser-harness", servers)

    def test_mcp_server_launcher_deploys_where_expected(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual(".local/share/browser-harness-mcp/server.py" in managed, expected(profile))

    def test_launcher_deploys_where_expected(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual(LAUNCHER in managed, expected(profile))

    def servers_as(self, profile, os_name):
        data = json.dumps({"chezmoi": {"os": os_name}})
        return json.loads(chezmoi(profile, "execute-template", "--override-data", data, stdin=TMPL.read_text()))["mcpServers"]

    def test_the_mcp_entry_by_os_and_profile_whatever_the_host(self):
        self.assertIn("browser-harness", self.servers_as("personal", "darwin"))
        self.assertIn("browser-harness", self.servers_as("axon-work-computer", "darwin"))
        self.assertIn("browser-harness", self.servers_as("personal", "linux"))
        self.assertNotIn("browser-harness", self.servers_as("axon-work-computer", "linux"))   # the work profile has no Linux box

    def test_servers_json_is_valid_json_for_all_four_os_and_profile_combinations(self):
        # A comma left over by a gated entry broke the JSON for one combination once; render every one, and the work-only servers with it.
        for profile in PROFILES:
            for os_name in ("darwin", "linux"):
                with self.subTest(profile=profile, os=os_name):
                    servers = self.servers_as(profile, os_name)   # json.loads inside: raises on a stray or missing comma
                    self.assertIn("hindsight", servers)
                    self.assertEqual("jira" in servers, profile == "axon-work-computer")
                    self.assertEqual("browser-harness" in servers, os_name == "darwin" or profile == "personal")

    def test_the_ignore_file_by_os_and_profile_whatever_the_host(self):
        def ignored(profile, os_name):
            data = json.dumps({"chezmoi": {"os": os_name}})
            return chezmoi(profile, "execute-template", "--override-data", data, stdin=(ROOT / ".chezmoiignore").read_text())
        for profile, os_name, deployed in (("personal", "darwin", True), ("axon-work-computer", "darwin", True), ("personal", "linux", True),
                                           ("axon-work-computer", "linux", False)):
            with self.subTest(profile=profile, os=os_name):
                self.assertEqual(".local/bin/agent-chrome" in ignored(profile, os_name).splitlines(), not deployed)

    def test_entry_carries_no_secret_placeholder(self):
        self.assertNotIn("${", json.dumps(ENTRY))
        text = TMPL.read_text()
        block = text[text.index('"browser-harness"'):text.index('{{ end }}', text.index('"browser-harness"'))]
        self.assertNotIn("op://", block)
        self.assertNotIn("${", block)


if __name__ == "__main__":
    unittest.main()
