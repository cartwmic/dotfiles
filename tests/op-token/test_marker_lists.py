"""The op shim (~/.pi/agent/bin/op) decides what an agent shell is from a list of environment variables.

This reads its agent_shell function as text and checks it tests exactly the markers the docs and tests name, so a marker added
or dropped there cannot pass unnoticed.
Run: python3 -m unittest discover -s tests/op-token -v
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIMS = (ROOT / ".chezmoitemplates/op-shim-connect", ROOT / ".chezmoitemplates/op-shim-service-account")  # personal, then every other profile
NAME = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-\}")
EXPECTED = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "T3CODE_THREAD_ID", "HERDR_ENV", "CODEX_SANDBOX"}


def agent_shell_markers(path):
    text = path.read_text()
    m = re.search(r"^agent_shell\(\) \{\n(.*?)^\}\n", text, re.S | re.M)
    assert m, "no agent_shell function in %s" % path
    return set(NAME.findall(m.group(1)))


class MarkerLists(unittest.TestCase):
    def test_the_list_is_the_one_the_docs_and_tests_name(self):
        for shim in SHIMS:
            with self.subTest(shim=shim.name):
                self.assertEqual(agent_shell_markers(shim), EXPECTED)


if __name__ == "__main__":
    unittest.main()
