#!/usr/bin/env python3
"""How an agent reaches shartifacts, as chezmoi renders it for both desktop profiles (real chezmoi, scratch config and HOME):
the `shartifacts` MCP server entry, the picture command, and the skill. All three land on personal and axon-work-computer
(Michael, 2026-11-13: "work profile should get sharitfacts as well", rule 272f08d0), so docs/profiles.md has no row for them,
only a note that records his words. Needs chezmoi.
Run: python3 -I tests/shx/test_agent_access.py
"""
import json
import os
import urllib.request
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


def mcp_tool_names(url):
    """Opens a Streamable HTTP MCP session at `url`, lists the tools and returns their names (stdlib only)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    def post(body, session=None):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict(headers, **({"Mcp-Session-Id": session} if session else {})))
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            sid = r.headers.get("Mcp-Session-Id") or session
        # A reply is plain JSON or a server-sent event whose data line is the JSON-RPC message.
        data = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
        return sid, (json.loads(data[-1]) if data else (json.loads(raw) if raw.strip() else None))

    sid, init = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "shx-access-test", "version": "1"}}})
    assert init and "result" in init, init
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, listed = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    return [t["name"] for t in listed["result"]["tools"]]


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

    @unittest.skipIf(os.environ.get("GITHUB_ACTIONS"), "the homelab host is not reachable from GitHub's runners")
    def test_rendered_entry_reaches_the_live_server(self):
        # The path an agent takes: the URL chezmoi renders for the profile, a real MCP session, the tools it needs.
        # Fails closed when the host cannot be reached.
        for profile in PROFILES:
            with self.subTest(profile=profile):
                names = mcp_tool_names(servers(profile)["shartifacts"]["url"])
                for tool in ("artifact_comments", "watch_artifacts", "list_artifacts"):
                    self.assertIn(tool, names)

    def test_picture_command_runs_from_the_source_wrapper(self):
        r = subprocess.run([str(ROOT / "dot_local/bin/executable_shx-note-image")], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, XDG_STATE_HOME=tempfile.mkdtemp()))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["code"], "bad_input")

    def test_coverage_table_has_no_row_and_the_note_records_the_decision(self):
        doc = PROFILES_DOC.read_text()
        table = doc.split("\n## Local data keys")[0]
        rows = [line for line in table.splitlines() if line.startswith("| `") and re.search(r"shx|shartifacts", line)]
        self.assertEqual(rows, [], "a row means one profile is left out; the picture command, the skill and the MCP entry are on both")
        self.assertIn("work profile should get sharitfacts as well", table)


if __name__ == "__main__":
    unittest.main()
