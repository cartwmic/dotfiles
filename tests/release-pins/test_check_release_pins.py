"""Black-box tests for scripts/check-release-pins.py (playbook rule 7c57de5a's check).

Each test runs the real script with a scripted `gh` first on PATH; nothing reaches GitHub.

    python3 -m unittest tests/release-pins/test_check_release_pins.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-release-pins.py"
TOOLS = ("loop-engine", "lean-change", "policy-document", "research", "bookends-check")

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_GH_STATE"]))
path = sys.argv[2]
key = "le" if "loop-engine/releases/latest" in path else "ak" if "packages/npm/agent-kit/versions" in path else None
if key is None:
    sys.stderr.write("fake gh: unexpected " + " ".join(sys.argv[1:]) + "\n")
    sys.exit(1)
if state.get(key + "_error"):
    sys.stderr.write(state[key + "_error"] + "\nsecond line\n")
    sys.exit(1)
if key == "le":
    print(state["le_tag"])
else:
    print("\n".join(state["ak_tags"]))
'''


def mise(versions):
    """A mise config with the five pins; versions maps tool -> version (default 0.49.0)."""
    return "gh = \"latest\"\n" + "".join(
        '%s = { version = "%s", matching_regex = "^x-", rename_exe = "%s" }\n' % (t, versions.get(t, "0.49.0"), t)
        for t in TOOLS)


class CheckReleasePinsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "bin").mkdir()
        (self.dir / "bin/gh").write_text(FAKE_GH)
        (self.dir / "bin/gh").chmod(0o755)
        # package versions are out of order and include non-release names: the highest X.Y.Z wins, compared as integers
        self.state = {"le_tag": "v0.49.0", "ak_tags": ["0.9.0", "0.10.0", "0.49.0", "0.48.1", "nightly", "0.50.0-rc1"]}

    def run_check(self, mise_versions=None, kit="0.49.0", **state):
        self.state.update(state)
        (self.dir / "state.json").write_text(json.dumps(self.state))
        (self.dir / "mise.toml").write_text(mise(mise_versions or {}))
        (self.dir / "package.json").write_text(json.dumps({"dependencies": {"@cartwmic/agent-kit": kit}}))
        env = {**os.environ, "PATH": "%s:%s" % (self.dir / "bin", os.environ["PATH"]),
               "FAKE_GH_STATE": str(self.dir / "state.json")}
        return subprocess.run([sys.executable, str(SCRIPT), "--mise-config", str(self.dir / "mise.toml"),
                               "--agent-kit-package", str(self.dir / "package.json")],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_all_pins_equal_latest_passes(self):
        result = self.run_check()
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertTrue(result.stdout.startswith("OK"))

    def test_each_loop_engine_pin_lagging_refuses(self):
        for tool in TOOLS:
            with self.subTest(tool=tool):
                result = self.run_check({tool: "0.48.1"})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 1)
                self.assertIn("%s pin 0.48.1 lags the latest release 0.49.0" % tool, lines[0])
                self.assertIn("loop_engine_bump.py v0.49.0", lines[0])

    def test_agent_kit_lagging_refuses(self):
        result = self.run_check(kit="0.10.0", ak_tags=["0.49.0", "0.9.0", "0.48.1"])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertIn("agent-kit pin 0.10.0 lags the latest release 0.49.0", result.stdout)
        self.assertIn("agent_kit_bump.py v0.49.0", result.stdout)

    def test_agent_kit_latest_is_compared_as_integers(self):
        # string order would call v0.9.0 the highest; the integer order is v0.10.0
        result = self.run_check(kit="0.9.0", ak_tags=["0.9.0", "0.10.0"])
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("latest release 0.10.0", result.stdout)

    def test_agent_kit_unreadable_fails_naming_the_cause(self):
        result = self.run_check(ak_error="HTTP 404: Not Found")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        out = result.stdout + result.stderr
        self.assertIn("cannot read the published versions of the cartwmic/agent-kit package (HTTP 404: Not Found)", out)
        self.assertIn("packages: read", out)
        self.assertNotIn("OK", result.stdout)
        self.assertNotIn("second line", out)

    def test_agent_kit_unreadable_fails_even_when_a_loop_engine_pin_lags(self):
        result = self.run_check({"research": "0.48.1"}, ak_error="HTTP 404: Not Found")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("cartwmic/agent-kit package", result.stdout)

    def test_agent_kit_with_no_release_versions_fails(self):
        result = self.run_check(ak_tags=["nightly", "0.50.0-rc1"])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("no X.Y.Z versions", result.stdout)

    def test_pass_line_names_the_agent_kit_pin_and_latest(self):
        result = self.run_check(kit="0.49.0")
        self.assertIn("agent-kit pin 0.49.0 at latest 0.49.0", result.stdout)

    def test_loop_engine_unreadable_exits_2(self):
        result = self.run_check(le_error="HTTP 401: Bad credentials")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("HTTP 401: Bad credentials", result.stdout + result.stderr)
        self.assertNotIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
