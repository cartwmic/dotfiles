"""What the installed Claude Code lists to the model under each seat file: only workflow-authoring may be a bundled skill (the homelab chat seat, which keeps the Workflow tool; every other seat lists none), and the four unused tools are absent from every seat but the homelab chat seat.

.chezmoitemplates/fleet_seat keeps Claude Code's bundled skills on (with disableBundledSkills true the Workflow tool carries its whole 20K-char
authoring reference in every request) and turns every bundled skill but workflow-authoring off by name, because skillOverrides has no wildcard.
A Claude Code update that adds a bundled skill would show it in every seat's first request until its name is added, so this test runs the
installed binary against each rendered seat file and fails naming the skill.

The binary runs in a throwaway HOME and talks to a local stand-in for the API (no network, no key); the test reads the first request it sends.
It skips when no claude binary is found (CI has none): it is a local check, run it after a Claude Code update. CLAUDE_BINARY names a binary explicitly.
"""
import http.server
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from test_fizzy_grove_binary import find_binary
from test_t3_hub import KEEP, UNUSED_TOOLS, UNUSED_TOOL_SEATS, fleet_env

LIST_HEAD = "The following skills are available for use with the Skill tool:"
EVENTS = [("message_start", {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant", "model": "x", "content": [], "stop_reason": None, "usage": {"input_tokens": 1, "output_tokens": 1}}}),
          ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
          ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
          ("content_block_stop", {"type": "content_block_stop", "index": 0}),
          ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
          ("message_stop", {"type": "message_stop"})]


class StandIn(http.server.BaseHTTPRequestHandler):
    """Answers every message with 'ok' as a stream and keeps the request bodies."""
    protocol_version = "HTTP/1.1"
    bodies = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path.startswith("/v1/messages") and "count_tokens" not in self.path:
            self.bodies.append(json.loads(body))
        out = b"".join(("event: %s\ndata: %s\n\n" % (e, json.dumps(d))).encode() for e, d in EVENTS)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(out)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(out)
        self.close_connection = True

    def log_message(self, *args):
        pass


def first_request(binary, seat_file):
    """The model request with the most tools (the main one, not a title or quota call) from one `claude -p` under seat_file."""
    StandIn.bodies = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as home:
            env = {"PATH": os.environ["PATH"], "HOME": home, "ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % server.server_address[1], "ANTHROPIC_API_KEY": "x",
                   "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
            subprocess.run([str(binary), "-p", "--model", "claude-haiku-5-5", "--settings", str(seat_file)], input="hi", env=env, capture_output=True, text=True, timeout=120, cwd=home)
    finally:
        server.shutdown()
        server.server_close()
    return max(StandIn.bodies, key=lambda b: len(b.get("tools", [])))


def listed_skills(request):
    """The skill names in the listing block of the request, and the Workflow tool's description length (None when the tool is absent)."""
    names = []
    for message in request["messages"]:
        parts = message["content"] if isinstance(message["content"], list) else [{"text": message["content"]}]
        for part in parts:
            text = part.get("text", "")
            if LIST_HEAD in text:
                names += re.findall(r"(?m)^- ([A-Za-z0-9:_-]+):", text.split(LIST_HEAD, 1)[1].split("<total_tokens>")[0])
    workflow = [len(t["description"]) for t in request.get("tools", []) if t["name"] == "Workflow"]
    return names, (workflow[0] if workflow else None)


class BundledSkillsBinaryTest(unittest.TestCase):
    def test_every_bundled_skill_is_off_or_workflow_authoring(self):
        binary = find_binary()
        if binary is None:
            self.skipTest("no claude binary found (set CLAUDE_BINARY to check one)")
        env = fleet_env("personal")
        try:
            for seat in sorted(KEEP):
                seat_file = env.home / ("seat-%s.json" % seat)
                seat_file.write_text(env.render("dot_claude/fleet/seat-%s.json.tmpl" % seat))
                request = first_request(binary, seat_file)
                names, workflow_chars = listed_skills(request)
                # the throwaway HOME has no personal skills, so whatever is listed is a bundled (or built-in) skill
                # the homelab chat seat keeps the Workflow tool, so workflow-authoring stays listed for it; every other seat denies the tool and turns the skill off
                allowed = set() if seat in UNUSED_TOOL_SEATS else {"workflow-authoring"}
                extra = sorted(set(names) - allowed)
                self.assertEqual(extra, [], "Claude Code %s lists %s to a %s seat. Add each to $bundledOff in .chezmoitemplates/fleet_seat and to BUNDLED_OFF in "
                                 "tests/t3-hub/test_t3_hub.py (a bundled skill nobody turned off is a listing in every request of every seat)." % (binary, extra, seat))
                if seat not in UNUSED_TOOL_SEATS:
                    self.assertIn("workflow-authoring", names, "workflow-authoring must stay listed: without it the Workflow tool carries its whole 20K-char reference (seat %s)" % seat)
                tools = {t["name"] for t in request["tools"]}
                if seat in UNUSED_TOOL_SEATS:
                    self.assertEqual(sorted(tools & UNUSED_TOOLS), [], "seat %s still has tools nobody calls in the first request; the seat file denies them" % seat)
                    if seat == "coordinator":
                        # the built-in tools of the coordinator's extra deny list go; the ones it keeps stay. (The T3 MCP tools come from the T3 instance, not this file. `claude -p` lists no AskUserQuestion, so test_t3_hub is what checks that one is denied.)
                        self.assertEqual(sorted(tools & {"Edit", "Write"}), [], "the coordinator seat still carries Edit or Write")
                        self.assertTrue({"Agent", "Read", "Skill"} <= tools, "the coordinator lost a tool it keeps: %s" % sorted({"Agent", "Read", "Skill"} - tools))
                else:
                    self.assertTrue(UNUSED_TOOLS <= tools, "seat %s lost %s: only the homelab chat seat keeps them" % (seat, sorted(UNUSED_TOOLS - tools)))
                    self.assertIsNotNone(workflow_chars, "no Workflow tool in the first request of seat %s: has Claude Code dropped it?" % seat)
                    self.assertLess(workflow_chars, 6000, "the Workflow tool description is %d chars on seat %s: the authoring reference is inline again" % (workflow_chars, seat))
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
