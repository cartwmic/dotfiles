"""apply_harness_config.sh codex keeps what the Codex app wrote inside the harness markers.

Runs the real script (`codex` target) against a throwaway HOME and a two-server canonical
MCP file. All paths and values are fake. Same script and code on the personal and work
profiles; the profile only changes which servers the canonical file renders.
"""
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dot_local/user_scripts/executable_apply_harness_config.sh"

BEGIN = "# BEGIN CHEZMOI AGENT HARNESS MCP"
END = "# END CHEZMOI AGENT HARNESS MCP"



def old_merge(block, content):
    """The merge as it was before the fix (apply_harness_config.sh at 0a5524f6), for the RED control."""
    begin = "# BEGIN CHEZMOI AGENT HARNESS MCP"
    end = "# END CHEZMOI AGENT HARNESS MCP"
    block = block.rstrip() + "\n"
    if begin in content and end in content:
        start = content.index(begin)
        finish = content.index(end, start) + len(end)
        new_content = content[:start].rstrip()
        if new_content:
            new_content += "\n\n"
        new_content += block
        suffix = content[finish:].lstrip("\n")
        if suffix:
            new_content += "\n" + suffix
    else:
        new_content = content.rstrip()
        if new_content:
            new_content += "\n\n"
        new_content += block
    return new_content.rstrip() + "\n"


# What the Codex app leaves inside the markers (fake paths). No harness-servers line: written by an
# older apply, so `legacy` (not rendered now) cannot be told from the app's entries and moves out.
CONFIG = f'''model = "gpt-test"

[features]
shell_tool = true

{BEGIN}
notify = ["/tmp/fake/notify.sh", "--arg"]
[mcp_servers.alpha]
command = "old-alpha"

[mcp_servers.node_repl]
command = "/tmp/fake/node_repl"
args = ["--flag"]

[mcp_servers.node_repl.env]
FAKE_VAR = "x"

[mcp_servers.legacy]
command = "old-legacy"
{END}

[projects."/tmp/fake/project"]
trust_level = "trusted"
'''

SERVERS = '''{"mcpServers": {
  "alpha": {"command": "new-alpha", "args": ["--a", "--b"]},
  "beta": {"type": "http", "url": "https://example.invalid/mcp"}
}}'''


class CodexMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        canon = self.home / "canon"
        (canon / "skills").mkdir(parents=True)
        (canon / "mcp").mkdir()
        (canon / "mcp/servers.json").write_text(SERVERS)
        self.canon = canon
        self.cfg = self.home / ".codex/config.toml"
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_text(CONFIG)

    def run_script(self, extra_env=None):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), **(extra_env or {}),
               "AGENT_HARNESS_CANONICAL_ROOT": str(self.canon),
               "AGENT_HARNESS_GENERATED_ROOT": str(self.home / "gen"),
               "AGENT_HARNESS_ADAPTERS_ROOT": str(self.home / "adapters"),
               "AGENT_HARNESS_EXTERNAL_ROOT": str(self.home / "ext")}
        return subprocess.run(["sh", str(SCRIPT), "codex"], env=env, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=60)

    def test_foreign_entries_survive_and_harness_servers_refresh(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.cfg.read_text()
        data = tomllib.loads(text)
        self.assertEqual(data["notify"], ["/tmp/fake/notify.sh", "--arg"])
        self.assertEqual(data["mcp_servers"]["node_repl"]["env"], {"FAKE_VAR": "x"})
        self.assertEqual(data["mcp_servers"]["node_repl"]["args"], ["--flag"])
        # harness servers refreshed, not duplicated
        self.assertEqual(data["mcp_servers"]["alpha"]["command"], "new-alpha")
        self.assertEqual(data["mcp_servers"]["beta"]["url"], "https://example.invalid/mcp")
        # untouched content stays
        self.assertEqual(data["model"], "gpt-test")
        self.assertTrue(data["features"]["shell_tool"])
        self.assertEqual(data["projects"]["/tmp/fake/project"]["trust_level"], "trusted")
        # notify is top-level, above every table; node_repl sits after END, outside the markers
        self.assertLess(text.index("notify ="), text.index("[features]"))
        b, e = text.index(BEGIN), text.index(END)
        self.assertNotIn("notify", text[b:e])
        self.assertNotIn("node_repl", text[b:e])
        self.assertGreater(text.index("[mcp_servers.node_repl]"), e)
        self.assertNotIn("old-alpha", text)

    def test_second_run_changes_nothing(self):
        self.assertEqual(self.run_script().returncode, 0)
        first = self.cfg.read_text()
        mtime = self.cfg.stat().st_mtime_ns
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.cfg.read_text(), first)
        self.assertEqual(self.cfg.stat().st_mtime_ns, mtime)

    def test_parse_failure_leaves_file_untouched(self):
        # node_repl already defined after END: moving the one inside the markers duplicates it.
        broken = CONFIG + '\n[mcp_servers.node_repl]\ncommand = "/tmp/fake/other"\n'
        self.cfg.write_text(broken)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("left unchanged", r.stderr)
        self.assertEqual(self.cfg.read_text(), broken)

    def test_no_markers_appends_block(self):
        self.cfg.write_text('model = "gpt-test"\n')
        self.assertEqual(self.run_script().returncode, 0)
        data = tomllib.loads(self.cfg.read_text())
        self.assertEqual(data["mcp_servers"]["alpha"]["command"], "new-alpha")

    def test_dropped_harness_server_is_removed_on_next_merge(self):
        self.assertEqual(self.run_script().returncode, 0)
        first = tomllib.loads(self.cfg.read_text())
        self.assertIn("beta", first["mcp_servers"])
        self.assertIn("# harness-servers: alpha,beta", self.cfg.read_text())
        # beta leaves the canonical set: it is the harness's own, so it goes; node_repl stays.
        (self.canon / "mcp/servers.json").write_text(
            '{"mcpServers": {"alpha": {"command": "new-alpha", "args": ["--a", "--b"]}}}')
        self.assertEqual(self.run_script().returncode, 0)
        text = self.cfg.read_text()
        data = tomllib.loads(text)
        self.assertNotIn("beta", data["mcp_servers"])
        self.assertEqual(data["mcp_servers"]["alpha"]["command"], "new-alpha")
        self.assertIn("node_repl", data["mcp_servers"])
        self.assertIn("legacy", data["mcp_servers"])
        self.assertEqual(data["notify"], ["/tmp/fake/notify.sh", "--arg"])

    def test_old_block_without_ownership_line_moves_unrendered_servers_out(self):
        self.assertEqual(self.run_script().returncode, 0)
        text = self.cfg.read_text()
        self.assertGreater(text.index("[mcp_servers.legacy]"), text.index(END))

    def test_without_tomllib_merges_and_says_so(self):
        shim = Path(self.tmp.name) / "shim"
        shim.mkdir()
        (shim / "tomllib.py").write_text("raise ImportError('shim: no tomllib')\n")
        r = self.run_script({"PYTHONPATH": str(shim)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tomllib unavailable", r.stdout)
        text = self.cfg.read_text()
        self.assertLess(text.index("notify ="), text.index("[features]"))
        self.assertGreater(text.index("[mcp_servers.node_repl]"), text.index(END))
        self.assertTrue(tomllib.loads(text))  # the test's own parse

    def test_red_control_old_merge_drops_them(self):
        # Get the rendered block from the real script, then merge it the old way.
        self.assertEqual(self.run_script().returncode, 0)
        block = (self.home / "gen/codex/mcp.toml").read_text()
        data = tomllib.loads(old_merge(block, CONFIG))
        self.assertNotIn("notify", data)
        self.assertNotIn("node_repl", data["mcp_servers"])


if __name__ == "__main__":
    unittest.main()
