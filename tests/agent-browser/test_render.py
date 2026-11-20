"""The agent-browser pieces as chezmoi renders them for both desktop profiles (real chezmoi, scratch config and HOME).
Both profiles (personal macOS and Linux, work macOS): the `browse` MCP entry (OpenCode Browse), its mise pin, the download helper and the skill.
browser-harness is on neither. The agent-chrome launcher: macOS on both profiles, Linux on personal only."""
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
BROWSE = {"command": "/Users/test/.local/share/mise/shims/browse", "args": ["mcp"]}
BROWSE_FILES = [".config/mise/conf.d/browse.toml", ".local/bin/agent-download", ".local/bin/browse", ".local/bin/agent-browse-setup",
                ".local/share/agent-harness/canonical/skills/using-browse/SKILL.md"]
BROWSE_IGNORED = [".config/mise/conf.d/browse.toml", ".local/bin/agent-download", ".local/bin/browse", ".local/bin/agent-browse-setup",
                  ".local/share/agent-harness/canonical/skills/using-browse", "91_browse_setup.sh"]
LOGIN = ".local/bin/agent-login"   # personal only: it reads logins through the personal profile's op shim
HARNESS_PATHS = [".local/share/browser-harness-mcp", ".local/share/browser-harness-mcp/server.py", ".local/share/pi-mcp-lazy/seed/browser-harness.json"]


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

    def test_the_entry_is_browse_run_from_the_pinned_shim_with_no_env_on_both_profiles(self):
        for profile, os_name in (("personal", "linux"), ("personal", "darwin"), ("axon-work-computer", "darwin")):
            with self.subTest(profile=profile, os=os_name):
                servers = self.servers_as(profile, os_name, home="/Users/test")
                self.assertEqual(servers["browse"], BROWSE)
                self.assertNotIn("browser-harness", servers)

    def test_files_deploy_on_both_profiles_and_browser_harness_on_neither(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                for path in BROWSE_FILES:
                    self.assertIn(path, managed, path)
                for path in HARNESS_PATHS:
                    self.assertNotIn(path, managed, path)

    def test_agent_login_is_personal_only_and_agent_download_is_on_both(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual(LOGIN in managed, profile == "personal")
                self.assertIn(".local/bin/agent-download", managed)

    def test_launcher_deploys_where_expected(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual(LAUNCHER in managed, expected(profile))

    def servers_as(self, profile, os_name, home=None):
        data = json.dumps({"chezmoi": {"os": os_name, **({"homeDir": home} if home else {})}})
        return json.loads(chezmoi(profile, "execute-template", "--override-data", data, stdin=TMPL.read_text()))["mcpServers"]

    def test_the_mcp_entries_by_os_and_profile_whatever_the_host(self):
        # The work profile has no Linux machine (docs/profiles.md), so that combination is not asserted; test_servers_json_is_valid... still renders it.
        for profile, os_name in (("personal", "darwin"), ("personal", "linux"), ("axon-work-computer", "darwin")):
            with self.subTest(profile=profile, os=os_name):
                servers = self.servers_as(profile, os_name)
                self.assertEqual(("browse" in servers, "browser-harness" in servers), (True, False))

    def test_container_mode_has_no_browser_entry_because_the_pod_leaves_out_the_pin(self):
        data = json.dumps({"chezmoi": {"os": "linux"}, "container": {"enabled": True}})
        servers = json.loads(chezmoi("personal", "execute-template", "--override-data", data, stdin=TMPL.read_text()))["mcpServers"]
        self.assertNotIn("browse", servers)
        self.assertNotIn("browser-harness", servers)

    def test_servers_json_is_valid_json_for_all_four_os_and_profile_combinations(self):
        # A comma left over by a gated entry broke the JSON for one combination once; render every one, and the work-only servers with it.
        for profile in PROFILES:
            for os_name in ("darwin", "linux"):
                with self.subTest(profile=profile, os=os_name):
                    servers = self.servers_as(profile, os_name)   # json.loads inside: raises on a stray or missing comma
                    self.assertIn("hindsight", servers)
                    self.assertEqual("jira" in servers, profile == "axon-work-computer")
                    self.assertNotIn("browser-harness", servers)

    def test_the_ignore_file_by_os_and_profile_whatever_the_host(self):
        def ignored(profile, os_name, container=False):
            data = json.dumps({"chezmoi": {"os": os_name}, **({"container": {"enabled": True}} if container else {})})
            return chezmoi(profile, "execute-template", "--override-data", data, stdin=(ROOT / ".chezmoiignore").read_text()).splitlines()
        for profile, os_name, launcher in (("personal", "darwin", True), ("axon-work-computer", "darwin", True),
                                           ("personal", "linux", True), ("axon-work-computer", "linux", False)):
            with self.subTest(profile=profile, os=os_name):
                lines = ignored(profile, os_name)
                self.assertEqual(".local/bin/agent-chrome" in lines, not launcher)
                for path in BROWSE_IGNORED + HARNESS_PATHS:   # Browse and its helpers are on both profiles; browser-harness has no path left to ignore
                    self.assertNotIn(path, lines, path)
                self.assertEqual(LOGIN in lines, profile != "personal")   # agent-login stays personal only
        with self.subTest(profile="termux"):   # the phone host has no Chrome to drive, as before
            lines = ignored("termux", "linux")
            for path in BROWSE_IGNORED:
                self.assertIn(path, lines, path)
        with self.subTest(container=True):   # the agent host pod has no desktop: it still leaves Browse out
            lines = ignored("personal", "linux", container=True)
            for path in BROWSE_IGNORED[:5]:
                self.assertIn(path, lines, path)

    def test_entries_carry_no_secret_placeholder(self):
        self.assertNotIn("${", json.dumps(BROWSE))
        text = TMPL.read_text()
        block = text[text.index('"browse"'):text.index('{{ end }}', text.index('"browse"'))]
        self.assertNotIn("op://", block)
        self.assertNotIn("${", block)


if __name__ == "__main__":
    unittest.main()
