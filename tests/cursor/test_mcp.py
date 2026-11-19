"""dot_cursor/modify_mcp.json.tmpl puts the fleet MCP servers (hindsight, shartifacts) into ~/.cursor/mcp.json on both desktop
profiles, in Cursor's own form, and leaves everything else in the file alone. Real chezmoi renders the script and `sh` runs it.

    python3 -m unittest discover -s tests/cursor -p 'test_mcp*.py' -v
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/shx"))
import test_agent_access as access  # the chezmoi helper, with the local data keys the work profile needs

MCP_TMPL = ROOT / "dot_cursor/modify_mcp.json.tmpl"
FLEET_TMPL = ROOT / "dot_claude/fleet/mcp.json.tmpl"
PROFILES = {"personal": ("/mcp/cartwmic/", "personal"), "axon-work-computer": ("/mcp/work/", "work")}
FOREIGN = {"command": "npx", "args": ["x"], "env": {"A": "${A}"}}


def render(profile, tmpl=MCP_TMPL):
    return access.chezmoi(profile, "execute-template", stdin=tmpl.read_text())


def run(script, existing):
    r = subprocess.run(["sh", "-c", script], input=existing, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class CursorMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = {p: render(p) for p in PROFILES}

    def test_servers_follow_the_profile_in_cursors_form_for_a_missing_empty_or_bare_file(self):
        for profile, (path, origin) in PROFILES.items():
            for existing in ("", "  \n", "{}"):
                with self.subTest(profile=profile, existing=existing):
                    out = json.loads(run(self.scripts[profile], existing).stdout)
                    self.assertEqual(out, {"mcpServers": {
                        "hindsight": {"url": "https://hindsight-api.internal.cartwmic.com" + path},
                        "shartifacts": {"url": "https://shartifacts.internal.cartwmic.com/mcp",
                                        "headers": {"X-Origin": origin, "X-Thread": "${env:T3CODE_THREAD_ID}"}}}})

    def test_the_shell_form_of_the_thread_variable_is_never_written(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.assertNotIn("${T3CODE_THREAD_ID:-}", run(self.scripts[profile], "").stdout)

    def test_foreign_servers_and_top_level_keys_keep_their_value_and_ours_are_replaced(self):
        existing = {"theme": {"a": [1, 2]}, "mcpServers": {"mine": FOREIGN, "hindsight": {"url": "https://old", "type": "http", "extra": 1}}}
        for profile in PROFILES:
            with self.subTest(profile=profile):
                out = json.loads(run(self.scripts[profile], json.dumps(existing)).stdout)
                self.assertEqual(out["theme"], existing["theme"])
                self.assertEqual(out["mcpServers"]["mine"], FOREIGN)
                self.assertEqual(out["mcpServers"]["hindsight"], {"url": "https://hindsight-api.internal.cartwmic.com" + PROFILES[profile][0]})
                self.assertEqual(set(out["mcpServers"]), {"mine", "hindsight", "shartifacts"})

    def test_a_second_run_changes_nothing(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                once = run(self.scripts[profile], json.dumps({"mcpServers": {"mine": FOREIGN}})).stdout
                self.assertEqual(run(self.scripts[profile], once).stdout, once)

    def test_a_file_that_is_not_json_comes_out_unchanged_with_a_warning(self):
        for existing in ("{not json\n", '["a"]', '{"mcpServers": "x"}\n\n'):
            for profile in PROFILES:
                with self.subTest(profile=profile, existing=existing):
                    r = run(self.scripts[profile], existing)
                    self.assertEqual(r.stdout, existing)
                    self.assertIn("WARN", r.stderr)

    def test_the_claude_fleet_file_still_has_the_same_two_servers_as_the_canonical_file(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                canonical = access.servers(profile)
                fleet = json.loads(render(profile, FLEET_TMPL))["mcpServers"]
                self.assertEqual(fleet, {k: canonical[k] for k in ("hindsight", "shartifacts")})
                self.assertEqual(fleet["shartifacts"]["headers"]["X-Thread"], "${T3CODE_THREAD_ID:-}")  # Claude keeps the shell form


if __name__ == "__main__":
    unittest.main()
