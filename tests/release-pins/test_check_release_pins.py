"""Black-box tests for scripts/check-release-pins.py (playbook rule 7c57de5a's check).

Each test runs the real script with a scripted `gh` first on PATH; nothing reaches GitHub. The fake answers the release
endpoints, `gh pr list` (with its --base filter) and `gh pr diff`, from a JSON state file the test writes.

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
MISE_PATH = "dot_config/mise/config.toml"
KIT_PATH = "dot_local/share/agent-kit/package.json"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_GH_STATE"]))
args = sys.argv[1:]


def fail(message):
    sys.stderr.write(message + "\nsecond line\n")
    sys.exit(1)


if args[:2] == ["pr", "list"]:
    if state.get("pr_error"):
        fail(state["pr_error"])
    base = args[args.index("--base") + 1] if "--base" in args else None
    numbers = [pr["number"] for pr in state.get("prs", []) if base in (None, pr["base"])]
    print(json.dumps([{"number": number} for number in numbers]))
    sys.exit(0)
if args[:2] == ["pr", "diff"]:
    number = args[2]
    if number in state.get("diff_errors", {}):
        fail(state["diff_errors"][number])
    sys.stdout.write(state.get("diffs", {}).get(number, ""))
    sys.exit(0)
path = args[1] if args[:1] == ["api"] else ""
key = "le" if "loop-engine/releases/latest" in path else "ak" if "packages/npm/agent-kit/versions" in path else None
if key is None:
    sys.stderr.write("fake gh: unexpected " + " ".join(args) + "\n")
    sys.exit(1)
if state.get(key + "_error"):
    fail(state[key + "_error"])
if key == "le":
    print(state["le_tag"])
else:
    print("\n".join(state["ak_tags"]))
'''


def mise_line(tool, version):
    return '%s = { version = "%s", matching_regex = "^x-", rename_exe = "%s" }' % (tool, version, tool)


def mise(versions):
    """A mise config with the five pins; versions maps tool -> version (default 0.49.0)."""
    return "gh = \"latest\"\n" + "".join(mise_line(t, versions.get(t, "0.49.0")) + "\n" for t in TOOLS)


def file_diff(path, body):
    return "diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@ -1 +1 @@\n%s" % (path, path, path, path, body)


def pr_diff(mise_bumps=None, kit_bump=None):
    """What `gh pr diff` prints for a PR that moves pins: mise_bumps maps a tool to its new version (from 0.49.0),
    kit_bump is the new agent-kit version (from 0.48.1)."""
    text = ""
    if mise_bumps:
        text += file_diff(MISE_PATH, "".join("-%s\n+%s\n" % (mise_line(t, "0.49.0"), mise_line(t, v))
                                             for t, v in mise_bumps.items()))
    if kit_bump:
        text += file_diff(KIT_PATH,
                          '-    "@cartwmic/agent-kit": "0.48.1",\n+    "@cartwmic/agent-kit": "%s",\n' % kit_bump)
    return text


def pr(number, base="main"):
    return {"number": number, "base": base}


def all_tools_to(version):
    return dict.fromkeys(TOOLS, version)


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

    def assertFailsWithOneLinePerLaggingPin(self, result, tools=TOOLS):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("pending bump", result.stdout)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), len(tools), result.stdout)
        for tool in tools:
            self.assertIn("%s pin 0.49.0 lags the latest release 0.50.0" % tool, result.stdout)

    def test_all_pins_equal_latest_passes(self):
        result = self.run_check()
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertTrue(result.stdout.startswith("OK"))

    def test_nothing_lagging_makes_no_pr_lookup(self):
        result = self.run_check(pr_error="HTTP 401: Bad credentials")
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
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

    def test_behind_with_open_pr_bumping_to_latest_passes_with_notice(self):
        result = self.run_check(le_tag="v0.50.0", prs=[pr(12)], diffs={"12": pr_diff(all_tools_to("0.50.0"))})
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        for tool in TOOLS:
            self.assertIn("pending bump #12: %s 0.49.0 -> 0.50.0" % tool, result.stdout.splitlines())
        self.assertEqual(result.stdout.splitlines()[-1], "OK: every lagging pin has an open bump PR")

    def test_behind_with_no_open_pr_fails(self):
        result = self.run_check(le_tag="v0.50.0")
        self.assertFailsWithOneLinePerLaggingPin(result)

    def test_behind_with_open_pr_to_a_different_version_fails(self):
        result = self.run_check(le_tag="v0.50.0", prs=[pr(12), pr(13)], diffs={
            "12": pr_diff(all_tools_to("0.50.1")),  # newer than the latest
            "13": pr_diff(all_tools_to("0.49.5")),  # older than the latest
        })
        self.assertFailsWithOneLinePerLaggingPin(result)

    def test_open_pr_into_another_branch_does_not_count(self):
        result = self.run_check(le_tag="v0.50.0", prs=[pr(12, base="some-stacked-branch")],
                                diffs={"12": pr_diff(all_tools_to("0.50.0"))})
        self.assertFailsWithOneLinePerLaggingPin(result)

    def test_pin_line_in_another_file_does_not_count(self):
        result = self.run_check(le_tag="v0.50.0", prs=[pr(12)],
                                diffs={"12": file_diff("README.md", "+%s\n" % mise_line("loop-engine", "0.50.0"))})
        self.assertFailsWithOneLinePerLaggingPin(result)

    def test_every_lagging_pin_needs_its_own_bump(self):
        result = self.run_check(le_tag="v0.50.0", prs=[pr(12)],
                                diffs={"12": pr_diff({"loop-engine": "0.50.0", "lean-change": "0.50.0"})})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("pending bump #12: loop-engine 0.49.0 -> 0.50.0", lines)
        self.assertIn("pending bump #12: lean-change 0.49.0 -> 0.50.0", lines)
        failing = sorted(line.split()[0] for line in lines if "lags the latest release" in line)
        self.assertEqual(failing, sorted(["policy-document", "research", "bookends-check"]))

    def test_agent_kit_pending_bump_passes(self):
        result = self.run_check(kit="0.48.1", prs=[pr(15)], diffs={"15": pr_diff(kit_bump="0.49.0")})
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("pending bump #15: agent-kit 0.48.1 -> 0.49.0", result.stdout.splitlines())

    def test_pr_lookup_failure_fails_and_says_why(self):
        result = self.run_check(le_tag="v0.50.0", pr_error="HTTP 401: Bad credentials")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        out = result.stdout + result.stderr
        self.assertIn("cannot read the open cartwmic/dotfiles PRs into main (HTTP 401: Bad credentials)", out)
        self.assertNotIn("second line", out)
        self.assertNotIn("OK", result.stdout)
        self.assertIn("lags the latest release 0.50.0", result.stdout)

    def test_pr_diff_lookup_failure_fails_even_with_a_matching_pr(self):
        # the unreadable PR is first in the list; the matching PR after it must not rescue the check
        result = self.run_check(le_tag="v0.50.0", prs=[pr(12), pr(13)],
                                diff_errors={"12": "HTTP 406: the diff exceeded the maximum number of lines"},
                                diffs={"13": pr_diff(all_tools_to("0.50.0"))})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        out = result.stdout + result.stderr
        self.assertIn("cannot read the diff of cartwmic/dotfiles PR #12 (HTTP 406: the diff exceeded the maximum "
                      "number of lines)", out)
        self.assertNotIn("OK", result.stdout)
        self.assertNotIn("pending bump #", result.stdout)


if __name__ == "__main__":
    unittest.main()
