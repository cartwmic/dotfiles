"""The agent-shell markers are kept in two files: the op shim (~/.pi/agent/bin/op) and viz (dot_local/bin/executable_viz).

Each has an agent_shell function. Both must list the same environment variables, so a marker added to one and not the other
cannot pass unnoticed. This reads the two functions as text and compares the variable names they test.
Run: python3 -m unittest discover -s tests/op-token -v
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "dot_pi/private_agent/bin/executable_op", ROOT / "dot_local/bin/executable_viz"]
NAME = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-\}")
EXPECTED = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "T3CODE_THREAD_ID", "HERDR_ENV", "CODEX_SANDBOX"}


def agent_shell_markers(path):
    text = path.read_text()
    m = re.search(r"^agent_shell\(\) \{\n(.*?)^\}\n", text, re.S | re.M)
    assert m, "no agent_shell function in %s" % path
    return set(NAME.findall(m.group(1)))


class MarkerLists(unittest.TestCase):
    def test_the_two_files_test_the_same_markers(self):
        shim, viz = (agent_shell_markers(f) for f in FILES)
        self.assertEqual(shim, viz, "agent_shell differs: only in the shim %s, only in viz %s" % (sorted(shim - viz), sorted(viz - shim)))

    def test_the_list_is_the_one_the_docs_and_tests_name(self):
        for f in FILES:
            with self.subTest(file=f.name):
                self.assertEqual(agent_shell_markers(f), EXPECTED)


if __name__ == "__main__":
    unittest.main()
