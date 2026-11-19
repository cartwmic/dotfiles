"""rea and browse start straight from a pinned mise install, never through `npx` / `npm exec`; the Playwright MCP server and browser-harness are gone.

Renders the canonical MCP file with real chezmoi for both desktop profiles and checks that rea and browse run a mise shim, that mise
pins the npm package behind each shim at an exact version (browse's pin is in conf.d/browse.toml, rea's in config.toml), that no
`playwright` or `browser-harness` server is rendered, and that applying Claude's MCP step removes a leftover `playwright` registration.
"""
import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / "dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl"
MISE = ROOT / "dot_config/mise/config.toml"
BROWSE_MISE = ROOT / "dot_config/mise/conf.d/browse.toml"
APPLY = ROOT / "dot_local/user_scripts/executable_apply_harness_config.sh"
HOME = "/Users/test"
PROFILES = ("personal", "axon-work-computer")
# canonical server name -> (shim it must run, mise tool that provides the shim, the mise file that pins it)
SERVERS = {"rea": ("rea", "npm:rea-agents", MISE), "browse": ("browse", "npm:@opencode/browse", BROWSE_MISE)}
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


def render(profile):
    data = {"profile": profile, "chezmoi": {"os": "darwin", "homeDir": HOME}, **(WORK_DATA if profile == "axon-work-computer" else {})}
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        out = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template",
                              "--override-data", json.dumps(data)], input=TMPL.read_text(), text=True, capture_output=True,
                             timeout=120, check=True).stdout
    return json.loads(out)["mcpServers"]


class McpPinTests(unittest.TestCase):
    def test_each_profile_runs_the_mise_shim_directly(self):
        for profile in PROFILES:
            servers = render(profile)
            for name, (shim, _tool, _file) in SERVERS.items():
                with self.subTest(profile=profile, server=name):
                    self.assertEqual(servers[name]["command"], f"{HOME}/.local/share/mise/shims/{shim}",
                                     f"{name} must start from the pinned mise install, not through npx or npm exec")

    def test_mise_pins_each_package_at_an_exact_version(self):
        for name, (_shim, tool, file) in SERVERS.items():
            with self.subTest(tool=tool):
                tools = tomllib.loads(file.read_text())["tools"]
                self.assertIn(tool, tools, f"{file.name} [tools] must install {tool} (the {name} MCP server)")
                version = tools[tool]["version"] if isinstance(tools[tool], dict) else tools[tool]   # an inline table when the pin carries an option
                self.assertRegex(str(version), r"^\d+\.\d+\.\d+$", f"{tool} must be pinned to an exact version")

    def test_browse_is_allowed_below_mise_s_download_threshold(self):
        tool = tomllib.loads(BROWSE_MISE.read_text())["tools"]["npm:@opencode/browse"]
        self.assertIs(tool.get("allow_low_downloads"), True,
                      "mise's package-age guard refuses npm:@opencode/browse without allow_low_downloads (ledger #3148); the install fails at apply")

    def test_browser_harness_is_gone(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertNotIn("browser-harness", render(profile))

    def test_playwright_mcp_server_is_gone(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertNotIn("playwright", render(profile))
        tools = tomllib.loads(MISE.read_text())["tools"]
        self.assertFalse([t for t in tools if "playwright" in t], "mise must not install the Playwright MCP server")

    def test_claude_apply_removes_a_leftover_playwright_registration(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            canon = tmp / "canonical"
            (canon / "mcp").mkdir(parents=True)
            (canon / "skills").mkdir()
            (canon / "mcp/servers.json").write_text(json.dumps({"mcpServers": {"rea": {"command": "/x/rea", "args": ["mcp"]}}}))
            home = tmp / "home"
            home.mkdir()
            log = tmp / "claude.log"
            fake = tmp / "claude"  # records its argv; `mcp remove` of playwright succeeds as if it were registered
            fake.write_text('#!/bin/sh\necho "$@" >> "$FAKE_LOG"\nexit 0\n')
            fake.chmod(0o755)
            env = {"PATH": os.environ["PATH"], "HOME": str(home), "AGENT_HARNESS_CANONICAL_ROOT": str(canon),
                   "AGENT_HARNESS_GENERATED_ROOT": str(tmp / "generated"), "AGENT_HARNESS_ADAPTERS_ROOT": str(tmp / "adapters"),
                   "AGENT_HARNESS_EXTERNAL_ROOT": str(tmp / "external"), "AGENT_HARNESS_APPLY_CLAUDE_MCP": "0",
                   "CLAUDE_BIN": str(fake), "FAKE_LOG": str(log)}
            r = subprocess.run(["sh", str(APPLY), "claude"], env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run(["sh", str(tmp / "generated/claude/setup-mcp.sh")], env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("playwright: retired, removed", r.stdout)
            calls = log.read_text().splitlines()
            self.assertIn("mcp remove -s user playwright", calls)
            self.assertFalse([c for c in calls if c.startswith("mcp add") and "playwright" in c])


if __name__ == "__main__":
    unittest.main()
