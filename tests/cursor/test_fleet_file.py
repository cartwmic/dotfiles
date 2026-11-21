"""The Claude fleet seats' MCP file (dot_claude/fleet/mcp.json.tmpl) keeps hindsight and shartifacts, taken from the canonical file, with the
${T3CODE_THREAD_ID:-} shell form Claude Code expands itself. (This check lived in test_mcp.py with the Cursor modify script, which the
Cursor apply step replaced.)

    python3 -m unittest discover -s tests/cursor -p 'test_fleet_file.py' -v
"""
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cursor_apply import PROFILES, ROOT, access  # noqa: E402

FLEET_TMPL = ROOT / "dot_claude/fleet/mcp.json.tmpl"


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi needed")
class FleetFile(unittest.TestCase):
    def test_the_claude_fleet_file_has_the_same_two_servers_as_the_canonical_file(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                canonical = access.servers(profile)
                fleet = json.loads(access.chezmoi(profile, "execute-template", stdin=FLEET_TMPL.read_text()))["mcpServers"]
                self.assertEqual(fleet, {k: canonical[k] for k in ("hindsight", "shartifacts")})
                self.assertEqual(fleet["shartifacts"]["headers"]["X-Thread"], "${T3CODE_THREAD_ID:-}")  # Claude keeps the shell form


if __name__ == "__main__":
    unittest.main()
