"""Tests across every canonical skill's scripts/ folder (dot_local/share/agent-harness/canonical/skills/*/scripts).

A skill stays self-contained, so a helper several skills need (runlog.py, logged.py) is copied into each. The copies must stay byte
for byte the same.

    python3 -m unittest discover -s tests/skill-scripts
"""
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
COPIED = ("runlog.py", "logged.py")


def scripts():
    return sorted(SKILLS.glob("*/scripts/*.py"))


class SkillScriptCopies(unittest.TestCase):
    def test_every_copy_of_a_shared_helper_is_identical(self):
        for name in COPIED:
            copies = sorted(SKILLS.glob("*/scripts/" + name))
            self.assertGreaterEqual(len(copies), 2, "expected several skills to carry %s" % name)
            first = copies[0]
            for other in copies[1:]:
                self.assertEqual(
                    other.read_bytes(), first.read_bytes(),
                    "%s differs from %s: change every copy together (skills carrying it: %s)"
                    % (other.relative_to(SKILLS), first.relative_to(SKILLS), ", ".join(c.parts[-3] for c in copies)),
                )


if __name__ == "__main__":
    unittest.main()
