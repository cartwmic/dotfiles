"""A hook process started by the installed Claude Code sees COORDINATOR_SEAT=<seat> under each rendered seat file.

.chezmoitemplates/fleet_seat puts `env: {COORDINATOR_SEAT: <seat>}` in every seat file. The coordinator repo's rules hook reads the variable at SessionStart instead of asking T3 which seat
the thread is. This test adds a SessionStart hook that writes the variable to a file, runs the binary under the rendered file (throwaway HOME, local stand-in API, no network), and reads
the file back: a Claude Code that stopped passing a settings `env` to hooks fails here with a message. It skips when no claude binary is found (CI has none); CLAUDE_BINARY names one.
"""
import http.server
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from test_bundled_skills_binary import StandIn
from test_fizzy_grove_binary import find_binary
from test_t3_hub import KEEP, fleet_env


def hook_sees(binary, seat_file):
    """Run `claude -p` under seat_file with one more SessionStart hook; return what that hook wrote for $COORDINATOR_SEAT."""
    settings = json.loads(Path(seat_file).read_text())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "seen"
            hooks = settings.setdefault("hooks", {})
            hooks.setdefault("SessionStart", []).append({"hooks": [{"type": "command", "command": 'printf "%%s" "${COORDINATOR_SEAT-unset}" > %s' % probe}]})
            for event in [e for e in hooks if e not in ("SessionStart",)]:
                del hooks[event]  # the seat's own Stop and tool hooks are not under test
            settings_file = Path(tmp) / "seat.json"
            settings_file.write_text(json.dumps(settings))
            home = Path(tmp) / "home"
            home.mkdir()
            env = {"PATH": os.environ["PATH"], "HOME": str(home), "ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % server.server_address[1], "ANTHROPIC_API_KEY": "x",
                   "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
            subprocess.run([str(binary), "-p", "--model", "claude-haiku-5-5", "--settings", str(settings_file)], input="hi", env=env, capture_output=True, text=True, timeout=120, cwd=str(home))
            return probe.read_text() if probe.exists() else None
    finally:
        server.shutdown()
        server.server_close()


class SeatEnvBinaryTest(unittest.TestCase):
    def test_a_hook_sees_the_seat_name_under_every_rendered_seat_file(self):
        binary = find_binary()
        if binary is None:
            self.skipTest("no claude binary found (set CLAUDE_BINARY to check one)")
        env = fleet_env("personal")
        try:
            for seat in sorted(KEEP) + ["homelab-chat"]:
                seat_file = env.home / ("seat-%s.json" % seat)
                seat_file.write_text(env.render("dot_claude/fleet/seat-%s.json.tmpl" % seat))
                self.assertEqual(hook_sees(binary, seat_file), seat, "Claude Code %s: a SessionStart hook under seat file %s does not see COORDINATOR_SEAT=%s" % (binary, seat_file.name, seat))
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
