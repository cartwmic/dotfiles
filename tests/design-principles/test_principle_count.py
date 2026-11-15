"""Nothing outside design-principles.md may hard-code how many principles there are.

Adding principle 16 left "1 to 15", "1–15" and "15 rows" behind in three places
(dotfiles PR 440, review findings r1.f1, r1.f2, r2.f1). Prose says "every principle";
code that lists principles keeps exactly the headings of design-principles.md.
"""
import importlib.util
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRINCIPLES_FILE = ROOT / "dot_local/share/agent-harness/design-principles.md"
HEADINGS = [name for _, name in re.findall(r"(?m)^## (\d+)\. (.+)$", PRINCIPLES_FILE.read_text())]
BUMP_SCRIPTS = ["dot_local/user_scripts/executable_agent_kit_bump.py", "dot_local/user_scripts/executable_loop_engine_bump.py"]

# A range or count of principles written as a number: "principles 1 to 15", "principle 1–15",
# "each of 1 to 15", "table has 15 rows", "15 principles".
HARD_CODED = re.compile(
    r"principles?\s*\(?\s*(?:items\s+)?1\s*(?:to|–|-|through)\s*\d+"
    r"|each of 1\s*(?:to|–|-)\s*\d+"
    r"|principles table has \d+ rows"
    r"|\b\d+ (?:design )?principles\b",
    re.I,
)


def tracked_text_files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
    for rel in out.decode().split("\0"):
        if not rel or rel.startswith("tests/design-principles/"):
            continue
        path = ROOT / rel
        try:
            yield rel, path.read_text()
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue


def hard_coded_counts(text):
    return [m.group(0) for m in HARD_CODED.finditer(text)]


class PrincipleCountTests(unittest.TestCase):
    def test_no_file_hard_codes_the_number_of_principles(self):
        found = []
        for rel, text in tracked_text_files():
            for line_no, line in enumerate(text.splitlines(), 1):
                for hit in hard_coded_counts(line):
                    found.append("%s:%d: %r" % (rel, line_no, hit))
        self.assertEqual(found, [], "a principle count is hard-coded; write \"every principle\" (or \"one row for each principle\") "
                         "and leave the number to design-principles.md:\n" + "\n".join(found))

    def test_the_guard_catches_the_past_mistakes(self):
        for past in ["(principles 1 to 15)", "give each principle 1–15 a verdict", "one row for each of 1 to 15",
                     "the principles table has 15 rows with evidence", "one row for each of the 15 principles"]:
            self.assertTrue(hard_coded_counts(past), past)
        self.assertEqual(hard_coded_counts("one row for each principle; see §16"), [])

    def test_bump_scripts_list_exactly_the_principles_in_order(self):
        for rel in BUMP_SCRIPTS:
            spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            names = [row[0] for row in module.PRINCIPLES]
            self.assertEqual(names, HEADINGS, "%s: PRINCIPLES must have one row per heading in design-principles.md, "
                             "in order, with the same names; add a row for each new principle" % rel)


if __name__ == "__main__":
    unittest.main()
