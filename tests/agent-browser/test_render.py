"""The agent-browser pieces as chezmoi renders them for both desktop profiles (real chezmoi, scratch config and HOME).
Personal (macOS and Linux): the `browse` MCP entry (OpenCode Browse), its mise pin, the download helper and the skill. Work Mac (axon-work-computer, macOS):
the `browser-harness` MCP entry (it runs browser-use) and its launcher, unchanged. The agent-chrome launcher: macOS on both profiles, Linux on personal only."""
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
ENTRY = {   # browser-harness, the work Mac's entry
    "command": "uvx",
    "args": ["--from", "browser-use==1.0.2", "python", "-I", "<server.py>"],
    "env": {"BU_CDP_URL": "http://127.0.0.1:9333", "ANONYMIZED_TELEMETRY": "false", "BH_TELEMETRY": "0"},
}
BROWSE = {"command": "/Users/test/.local/share/mise/shims/browse", "args": ["mcp"]}
PERSONAL_ONLY = [".config/mise/conf.d/browse.toml", ".local/bin/agent-download", ".local/share/agent-harness/canonical/skills/using-browse/SKILL.md"]
WORK_ONLY = ".local/share/browser-harness-mcp/server.py"
SEED = ".local/share/pi-mcp-lazy/seed/browser-harness.json"


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

    def test_the_work_mac_entry_is_browser_harness_pinned_and_pointed_at_9333(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                servers = self.servers(profile)
                if DARWIN and profile == "axon-work-computer":
                    entry = dict(servers["browser-harness"])
                    server = entry["args"][-1]
                    self.assertTrue(server.endswith("/.local/share/browser-harness-mcp/server.py"), server)
                    entry["args"] = entry["args"][:-1] + ["<server.py>"]
                    self.assertEqual(entry, ENTRY)
                else:
                    self.assertNotIn("browser-harness", servers)

    def test_the_personal_entry_is_browse_run_from_the_pinned_shim_with_no_env(self):
        servers = self.servers_as("personal", "linux", home="/Users/test")
        self.assertEqual(servers["browse"], BROWSE)
        self.assertNotIn("browser-harness", servers)

    def test_files_deploy_where_expected(self):
        managed = {p: set(chezmoi(p, "managed").split()) for p in PROFILES}
        for path in PERSONAL_ONLY:   # the work profile gets no Browse, no helper and no skill
            self.assertIn(path, managed["personal"], path)
            self.assertNotIn(path, managed["axon-work-computer"], path)
        self.assertEqual(WORK_ONLY in managed["axon-work-computer"], DARWIN)
        self.assertNotIn(WORK_ONLY, managed["personal"])   # personal never deploys browser-harness's launcher, on any OS
        self.assertNotIn(SEED, managed["personal"])
        self.assertIn(SEED, managed["axon-work-computer"])   # the work profile still gets its seed

    def test_launcher_deploys_where_expected(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual(LAUNCHER in managed, expected(profile))

    def servers_as(self, profile, os_name, home=None):
        data = json.dumps({"chezmoi": {"os": os_name, **({"homeDir": home} if home else {})}})
        return json.loads(chezmoi(profile, "execute-template", "--override-data", data, stdin=TMPL.read_text()))["mcpServers"]

    def test_the_mcp_entries_by_os_and_profile_whatever_the_host(self):
        for profile, os_name, browse, harness in (("personal", "darwin", True, False), ("personal", "linux", True, False),
                                                  ("axon-work-computer", "darwin", False, True),
                                                  ("axon-work-computer", "linux", False, False)):   # the work profile has no Linux box
            with self.subTest(profile=profile, os=os_name):
                servers = self.servers_as(profile, os_name)
                self.assertEqual(("browse" in servers, "browser-harness" in servers), (browse, harness))

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
                    self.assertEqual("browser-harness" in servers, profile == "axon-work-computer" and os_name == "darwin")
                    self.assertEqual("browse" in servers, profile == "personal")

    def test_the_ignore_file_by_os_and_profile_whatever_the_host(self):
        def ignored(profile, os_name):
            data = json.dumps({"chezmoi": {"os": os_name}})
            return chezmoi(profile, "execute-template", "--override-data", data, stdin=(ROOT / ".chezmoiignore").read_text()).splitlines()
        for profile, os_name, launcher, harness in (("personal", "darwin", True, False), ("axon-work-computer", "darwin", True, True),
                                                    ("personal", "linux", True, False), ("axon-work-computer", "linux", False, False)):
            with self.subTest(profile=profile, os=os_name):
                lines = ignored(profile, os_name)
                self.assertEqual(".local/bin/agent-chrome" in lines, not launcher)
                self.assertEqual(".local/share/browser-harness-mcp" in lines, not harness)
                self.assertEqual(".local/share/pi-mcp-lazy/seed/browser-harness.json" in lines, profile != "axon-work-computer")
                for path in PERSONAL_ONLY[:2] + ["91_browse_setup.sh"]:   # the work profile leaves out Browse and its helpers
                    self.assertEqual(path in lines, profile != "personal", path)

    def test_entries_carry_no_secret_placeholder(self):
        self.assertNotIn("${", json.dumps(ENTRY))
        self.assertNotIn("${", json.dumps(BROWSE))
        text = TMPL.read_text()
        for name in ("browse", "browser-harness"):
            block = text[text.index('"%s"' % name):text.index('{{ end }}', text.index('"%s"' % name))]
            self.assertNotIn("op://", block)
            self.assertNotIn("${", block)


if __name__ == "__main__":
    unittest.main()
