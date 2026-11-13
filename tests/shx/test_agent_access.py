#!/usr/bin/env python3
"""How an agent reaches shartifacts, as chezmoi renders it for both desktop profiles (real chezmoi, scratch config and HOME):
the `shartifacts` MCP server entry, the picture command, and the skill. All three land on personal and axon-work-computer,
so docs/profiles.md must have no row for them (a row would mean one profile is left out). Needs chezmoi.
Run: python3 -I tests/shx/test_agent_access.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / "dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl"
PROFILES_DOC = ROOT / "docs/profiles.md"
PROFILES = ("personal", "axon-work-computer")
ENTRY = {"type": "http", "url": "https://shartifacts.internal.cartwmic.com/mcp"}
DEPLOYED = (
    ".local/bin/shx-note-image",
    ".local/share/shx/shx.mjs",
    ".local/share/shx/core/domain.mjs",
    ".local/share/shx/core/use_cases.mjs",
    ".local/share/shx/adapters/chromium.mjs",
    ".local/share/shx/vendor/perfect-freehand.mjs",
    ".local/share/shx/vendor/perfect-freehand.LICENSE",
    ".local/share/agent-harness/canonical/skills/using-shartifacts/SKILL.md",
)

# The local data keys the work profile requires (docs/profiles.md, "Local data keys"); placeholder values.
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


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


def servers(profile, os_name=None):
    args = ["execute-template"]
    if os_name:
        args += ["--override-data", json.dumps({"chezmoi": {"os": os_name}})]
    return json.loads(chezmoi(profile, *args, stdin=TMPL.read_text()))["mcpServers"]


@unittest.skipUnless(shutil.which("chezmoi"), "needs chezmoi on PATH")
class AgentAccessTest(unittest.TestCase):
    def test_mcp_entry_is_on_both_profiles_on_every_os(self):
        for profile in PROFILES:
            for os_name in (None, "linux", "darwin"):
                with self.subTest(profile=profile, os=os_name):
                    self.assertEqual(servers(profile, os_name)["shartifacts"], ENTRY)

    def test_mcp_entry_carries_no_secret_or_header(self):
        # The server takes no sign-in, so the entry is the URL and nothing else (no ${VAR} placeholder, no headers).
        self.assertEqual(set(servers("personal")["shartifacts"]), {"type", "url"})
        self.assertNotIn("${", json.dumps(servers("personal")["shartifacts"]))

    def test_command_and_skill_deploy_on_both_profiles(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual([p for p in DEPLOYED if p not in managed], [])

    def test_coverage_table_has_no_row_because_no_profile_is_left_out(self):
        table = PROFILES_DOC.read_text().split("\n## Local data keys")[0]
        rows = [line for line in table.splitlines() if line.startswith("| `")]
        self.assertTrue(rows, "no rows parsed from docs/profiles.md")
        named = [line for line in rows if re.search(r"shx|shartifacts", line)]
        self.assertEqual(named, [], "a row means one profile is left out; the picture command, the skill and the MCP entry are on both")


if __name__ == "__main__":
    unittest.main()
