#!/usr/bin/env python3
"""How an agent reaches shartifacts, as chezmoi renders it for both desktop profiles (real chezmoi, scratch config and HOME):
the `shartifacts` MCP server entry, the picture command, and the skill. All three land on personal only: the work profile is
left out because posting work content to the personal homelab host needs Michael's word (rule 272f08d0), and docs/profiles.md
carries that reason in a row. Needs chezmoi.
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
    def test_mcp_entry_is_on_personal_only_on_every_os(self):
        for os_name in (None, "linux", "darwin"):
            with self.subTest(profile="personal", os=os_name):
                self.assertEqual(servers("personal", os_name)["shartifacts"], ENTRY)
            with self.subTest(profile="axon-work-computer", os=os_name):
                self.assertNotIn("shartifacts", servers("axon-work-computer", os_name))

    def test_mcp_entry_carries_no_secret_or_header(self):
        # The server takes no sign-in, so the entry is the URL and nothing else (no ${VAR} placeholder, no headers).
        self.assertEqual(set(servers("personal")["shartifacts"]), {"type", "url"})
        self.assertNotIn("${", json.dumps(servers("personal")["shartifacts"]))

    def test_command_and_skill_deploy_on_personal_only(self):
        managed = set(chezmoi("personal", "managed").split())
        self.assertEqual([p for p in DEPLOYED if p not in managed], [])
        work = set(chezmoi("axon-work-computer", "managed").split())
        self.assertEqual([p for p in DEPLOYED if p in work], [], "the work profile must get none of them")

    def test_coverage_table_says_why_the_work_profile_is_left_out(self):
        table = PROFILES_DOC.read_text().split("\n## Local data keys")[0]
        rows = [line for line in table.splitlines() if line.startswith("| `") and re.search(r"shx|shartifacts", line)]
        self.assertEqual(len(rows), 1, "one row names the picture command, the skill and the MCP entry")
        self.assertIn("| personal |", rows[0])
        self.assertIn("work profile left out: posting work content to the personal homelab host needs Michael's word (272f08d0)", rows[0])


if __name__ == "__main__":
    unittest.main()
