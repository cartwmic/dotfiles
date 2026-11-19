"""Black-box tests for dot_local/share/agent-harness/bin/executable_mcp-ticket-lookup.

The helper confirms one ticket key through a single read-only MCP tool in a non-interactive
claude turn. A fake claude on PATH stands in for the real one, so nothing here calls claude;
the fake records the argv it was given and answers with a JSON transcript built from
environment knobs, so the tests pin the lockdown flags (no built-in tools, exactly one
allowed tool, manual permission mode, no project or local settings, automatic denial of
everything else) and the requirement that the allowed tool actually ran and succeeded.

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

FAKE = """#!/usr/bin/env python3
import json, os, subprocess, sys, time
argv = sys.argv
if os.environ.get('ARGV_FILE'):
    json.dump(argv, open(os.environ['ARGV_FILE'], 'w'))
if os.environ.get('FAKE_PID_FILE'):
    child = subprocess.Popen(['sleep', '30'])
    json.dump({'self': os.getpid(), 'child': child.pid}, open(os.environ['FAKE_PID_FILE'], 'w'))
time.sleep(float(os.environ.get('FAKE_SLEEP', '0')))
tool = 'mcp__example__get_issue'
try:
    i = argv.index('--allowedTools')
    tool = argv[i + 1]
except ValueError:
    pass
import re as _re
m = _re.search(r'ticket ([A-Z][A-Z0-9]+-[0-9]+)', ' '.join(argv))
key = os.environ.get('FAKE_INPUTKEY', m.group(1) if m else '')
msgs = []
if os.environ.get('FAKE_TOOLUSE', '1') == '1':
    name = os.environ.get('FAKE_TOOLNAME', tool)
    msgs.append({'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'id': 'tu_1', 'name': name, 'input': {'issuekey': key}}]}})
    tr = {'type': 'tool_result', 'tool_use_id': 'tu_1', 'content': 'ok'}
    if os.environ.get('FAKE_TOOLERR') == '1':
        tr['is_error'] = True
    msgs.append({'type': 'user', 'message': {'content': [tr]}})
msgs.append({'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 2,
             'result': os.environ.get('FAKE_REPLY', '')})
# The real CLI prints the full message list only when verbose is on; the helper must pass
# --verbose explicitly, so the fake mimics that shape rule.
if '--verbose' in argv:
    print(json.dumps(msgs))
else:
    print(json.dumps(msgs[-1]))
"""


def run(*args, env=None):
    assert env is not None and "ARGV_FILE" in env, "every run must go through self.env()"
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          timeout=60, env=env)


class McpTicketLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Put the fake claude on PATH before anything runs: a missing fake would silently
        # fall through to the real claude, which these tests must never call.
        p = Path(self.tmp) / "claude"
        p.write_text(FAKE)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

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

    def test_a_found_reply_with_no_tool_call_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="FOUND PROJ-1", FAKE_TOOLUSE="0"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("did not succeed", out.stderr)

    def test_a_found_reply_with_a_failed_tool_result_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="FOUND PROJ-1", FAKE_TOOLERR="1"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("did not succeed", out.stderr)

    def test_a_found_reply_from_a_different_tool_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="FOUND PROJ-1", FAKE_TOOLNAME="mcp__example__other_tool"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("did not succeed", out.stderr)

    def test_an_errored_result_plus_missing_exits_1(self):
        out = run("PROJ-1", env=self.env(reply="MISSING", FAKE_TOOLERR="1"))
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_a_found_reply_with_an_errored_result_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="FOUND PROJ-1", FAKE_TOOLERR="1"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("did not succeed", out.stderr)

    def test_missing_with_no_tool_call_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="MISSING", FAKE_TOOLUSE="0"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("did not run", out.stderr)

    def test_a_tool_use_for_a_different_key_plus_found_exits_2(self):
        out = run("PROJ-1", env=self.env(reply="FOUND PROJ-1", FAKE_INPUTKEY="OTHER-9"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("did not succeed", out.stderr)

    def test_a_timeout_exits_2_and_kills_claude_and_its_child(self):
        pid_file = str(Path(self.tmp) / "pids.json")
        e = self.env(reply="FOUND PROJ-1", sleep="30", FAKE_PID_FILE=pid_file)
        e["MCP_TICKET_LOOKUP_TIMEOUT"] = "2"
        out = run("PROJ-1", env=e)
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("timed out", out.stderr)
        pids = json.loads(Path(pid_file).read_text())
        for name, pid in pids.items():
            with self.assertRaises(ProcessLookupError, msg="%s (%d) still alive" % (name, pid)):
                os.kill(pid, 0)

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

    def test_claude_not_installed_exits_2_with_its_own_message(self):
        empty = tempfile.mkdtemp()
        e = self.env(reply="FOUND PROJ-1")
        e["PATH"] = empty  # a PATH with no claude on it
        out = run("PROJ-1", env=e)
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("claude is not installed", out.stderr)

    def test_the_claude_turn_is_locked_to_one_tool(self):
        run("PROJ-1", env=self.env(reply="MISSING"))
        argv = self.argv_of_last_call()
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--allowedTools") + 1], TOOL)
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "manual")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertIn("--verbose", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--allow-dangerously-skip-permissions", argv)
        prompt = [a for a in argv if "PROJ-1" in a and a.startswith("Use the")][0]
        self.assertIn(TOOL, prompt)
        self.assertIn("FOUND PROJ-1", prompt)
        self.assertIn("MISSING", prompt)
