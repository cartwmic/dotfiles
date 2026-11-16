"""The installed Claude Code binary still reads FORCE_PROMPT_CACHING_5M.

dot_t3/private_userdata/modify_settings.json.tmpl sets that variable on the seat-reviewer instance so reviewer sessions write their prompt cache with the
5-minute lifetime (audit-1116 proposal 2.2). In Claude Code 2.1.325 it is read in the cache-TTL chooser and forces "5m" for every request of the session.
It is not in the settings docs. If a later Claude Code drops the name, reviewers silently go back to 1-hour writes, so this test fails with a message
instead. It skips when no claude binary is found (CI has none). CLAUDE_BINARY names one explicitly.
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_fizzy_grove_binary import count, find_binary  # noqa: E402  (same binary lookup, one copy)

NAME = b"FORCE_PROMPT_CACHING_5M"


class Force5mBinaryTest(unittest.TestCase):
    def test_the_installed_claude_still_reads_the_variable(self):
        binary = find_binary()
        if binary is None:
            self.skipTest("no claude binary found (set CLAUDE_BINARY to check one)")
        try:
            version = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        except OSError:
            version = "(version unknown)"
        self.assertGreater(count(binary, NAME), 0,
            "Claude Code %s (%s) no longer contains %s. seat-reviewer sets it for 5-minute prompt cache writes. Check how this version picks the cache "
            "lifetime (settings promptCacheTtl, env CLAUDE_CODE_PROMPT_CACHE_TTL), then replace the variable in modify_settings.json.tmpl and the reviewer "
            "test in test_t3_hub.py." % (version, binary, NAME.decode()))


if __name__ == "__main__":
    unittest.main()
