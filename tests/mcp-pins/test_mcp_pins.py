"""rea and playwright start straight from a pinned mise install, never through `npx` / `npm exec`.

Renders the canonical MCP file with real chezmoi for both desktop profiles and checks that each of the two local
servers runs a mise shim, and that mise pins the npm package behind that shim at an exact version.
"""
import json
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / "dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl"
MISE = ROOT / "dot_config/mise/config.toml"
HOME = "/Users/test"
# canonical server name -> (shim it must run, mise tool that provides the shim)
SERVERS = {"rea": ("rea", "npm:rea-agents"), "playwright": ("playwright-mcp", "npm:@playwright/mcp")}
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
        for profile in ("personal", "axon-work-computer"):
            servers = render(profile)
            for name, (shim, _tool) in SERVERS.items():
                with self.subTest(profile=profile, server=name):
                    self.assertEqual(servers[name]["command"], f"{HOME}/.local/share/mise/shims/{shim}",
                                     f"{name} must start from the pinned mise install, not through npx or npm exec")

    def test_mise_pins_each_package_at_an_exact_version(self):
        tools = tomllib.loads(MISE.read_text())["tools"]
        for name, (_shim, tool) in SERVERS.items():
            with self.subTest(tool=tool):
                self.assertIn(tool, tools, f"{MISE.name} [tools] must install {tool} (the {name} MCP server)")
                self.assertRegex(str(tools[tool]), r"^\d+\.\d+\.\d+$", f"{tool} must be pinned to an exact version")


if __name__ == "__main__":
    unittest.main()
