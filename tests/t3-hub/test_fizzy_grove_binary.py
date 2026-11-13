"""The installed Claude Code binary still reads CLAUDE_CODE_FIZZY_GROVE.

dot_t3/private_userdata/modify_settings.json.tmpl sets that variable on every T3 Claude instance. It is undocumented. In Claude Code 2.1.322/323 its only
read picks which text a tool call gets when T3's interrupt skips it (a hook still running): with it, "[Tool call skipped: ... Nothing refused it ...]";
without it, "The user doesn't want to take this action right now". If a later Claude Code drops the name, the false decline text comes back silently,
so this test fails with a message instead. It skips when no claude binary is found (CI has none). CLAUDE_BINARY names one explicitly.
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

NAME = b"CLAUDE_CODE_FIZZY_GROVE"
HONEST_TEXT = b"Nothing refused it"


def find_binary():
    """CLAUDE_BINARY, else the binary mise resolves (`claude` on PATH is a mise wrapper), else a real `claude` on PATH. Anything under 10 MB is a wrapper, not the binary."""
    candidates = [os.environ.get("CLAUDE_BINARY")]
    if shutil.which("mise"):
        r = subprocess.run(["mise", "which", "claude"], capture_output=True, text=True, timeout=60)
        candidates.append(r.stdout.strip() if r.returncode == 0 else None)
    candidates.append(shutil.which("claude"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and Path(candidate).resolve().stat().st_size > 10_000_000:
            return Path(candidate).resolve()
    return None


def count(binary, needle):
    r = subprocess.run(["grep", "-a", "-c", "-F", needle.decode(), str(binary)], capture_output=True, text=True, timeout=300)
    return int(r.stdout.strip() or 0)


class FizzyGroveBinaryTest(unittest.TestCase):
    def test_the_installed_claude_still_reads_the_variable(self):
        binary = find_binary()
        if binary is None:
            self.skipTest("no claude binary found (set CLAUDE_BINARY to check one)")
        try:
            version = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        except OSError:
            version = "(version unknown)"
        self.assertGreater(count(binary, NAME), 0,
            "Claude Code %s (%s) no longer contains %s. The T3 instances set it so a call skipped by T3's interrupt says 'Nothing refused it' "
            "instead of 'The user doesn't want to take this action'. Re-check how this version words that skip (the coordinator repo fix-false-decline notes, "
            "dotfiles PR for CLAUDE_CODE_FIZZY_GROVE), then remove the variable from modify_settings.json.tmpl or replace it." % (version, binary, NAME.decode()))
        self.assertGreater(count(binary, HONEST_TEXT), 0,
            "Claude Code %s (%s) no longer contains the 'Nothing refused it' skip text that %s selects." % (version, binary, NAME.decode()))


if __name__ == "__main__":
    unittest.main()
