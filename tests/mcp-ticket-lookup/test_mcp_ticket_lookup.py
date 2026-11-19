"""Black-box tests for dot_local/share/agent-harness/bin/executable_mcp-ticket-lookup.

The helper confirms one ticket key through a single read-only MCP tool in a non-interactive
claude turn. A fake claude on PATH stands in for the real one, so nothing here calls claude;
the fake records the argv it was given, so the tests also pin the lockdown flags: no built-in
tools, exactly one allowed tool, and automatic denial of everything else.

    python3 -m unittest discover -s tests/mcp-ticket-lookup -v
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/share/agent-harness/bin/executable_mcp-ticket-lookup"
TOOL = "mcp__example__get_issue"


def run(*args, env=None):
    assert env is not None and "ARGV_FILE" in env, "every run must go through self.env()"
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          timeout=60, env=env)


class McpTicketLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()

    def setUp(self):
        # Put the fake claude on PATH before anything runs: a missing fake would silently
        # fall through to the real claude, which these tests must never call.
        self.fake_claude()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fake_claude(self):
        p = Path(self.tmp) / "claude"
        p.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys, time\n"
            "json.dump(sys.argv, open(os.environ['ARGV_FILE'], 'w'))\n"
            "time.sleep(float(os.environ.get('FAKE_SLEEP', '0')))\n"
            "print(os.environ.get('FAKE_REPLY', ''))\n"
        )
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return str(p)

    def env(self, reply=None, sleep="0", tool=TOOL, **over):
        e = dict(os.environ)
        e["PATH"] = self.tmp + os.pathsep + e["PATH"]
        e["KNOWN_LIMITS_MCP_TOOL"] = tool
        e["MCP_TICKET_LOOKUP_TIMEOUT"] = "10"
        e["FAKE_SLEEP"] = sleep
        e["ARGV_FILE"] = str(Path(self.tmp) / "argv.json")
        if reply is not None:
            e["FAKE_REPLY"] = reply
        e.update(over)
        return e

    def argv_of_last_call(self):
        return json.loads((Path(self.tmp) / "argv.json").read_text())

    def test_a_found_match_exits_0(self):
        out = run("PROJ-1", env=self.env(reply="FOUND PROJ-1"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "")

    def test_a_found_reply_with_the_wrong_key_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="FOUND OTHER-9"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("neither FOUND", out.stderr)

    def test_missing_exits_1(self):
        out = run("PROJ-1", env=self.env(reply="MISSING"))
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_garbage_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="I could not reach the tracker, sorry."))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("neither FOUND", out.stderr)

    def test_a_timeout_exits_2(self):
        e = self.env(reply="FOUND PROJ-1", sleep="30")
        e["MCP_TICKET_LOOKUP_TIMEOUT"] = "2"
        out = run("PROJ-1", env=e)
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("failed or timed out", out.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(run(env=self.env(reply="FOUND PROJ-1")).returncode, 2)
        self.assertEqual(run("proj-1", env=self.env(reply="FOUND PROJ-1")).returncode, 2)
        self.assertEqual(run("PROJ-1", "PROJ-2", env=self.env(reply="FOUND PROJ-1")).returncode, 2)

    def test_a_missing_tool_name_exits_2(self):
        e = self.env(reply="FOUND PROJ-1")
        e.pop("KNOWN_LIMITS_MCP_TOOL")
        out = run("PROJ-1", env=e)
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("KNOWN_LIMITS_MCP_TOOL", out.stderr)

    def test_the_claude_turn_is_locked_to_one_tool(self):
        run("PROJ-1", env=self.env(reply="MISSING"))
        argv = self.argv_of_last_call()
        self.assertIn("-p", argv)
        i = argv.index("--tools")
        self.assertEqual(argv[i + 1], "")
        j = argv.index("--allowedTools")
        self.assertEqual(argv[j + 1], TOOL)
        k = argv.index("--permission-prompts")
        self.assertEqual(argv[k + 1], "none")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--allow-dangerously-skip-permissions", argv)
        prompt = [a for a in argv if "PROJ-1" in a and a.startswith("Use the")][0]
        self.assertIn(TOOL, prompt)
        self.assertIn("FOUND PROJ-1", prompt)
        self.assertIn("MISSING", prompt)
