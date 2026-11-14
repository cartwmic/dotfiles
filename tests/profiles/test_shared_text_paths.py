"""Shared agent-harness text must not point at the personal coordinator state dir only.

Files under dot_local/share/agent-harness/ that are not templates land on both profiles. The personal
coordinator keeps its state in ~/.local/share/coordinator and the work Mac in ~/.local/share/coordinator-work,
so a hard-coded `~/.local/share/coordinator/...` path is wrong on the work Mac (dotfiles#400 review r1.f1, r2.f1).
"""
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "dot_local/share/agent-harness"
# The personal state dir followed by a path separator; coordinator-work and coordinator-workspace do not match.
PERSONAL_STATE = re.compile(r"\.local/share/coordinator/")
FIX = ("names the personal coordinator state dir only; the work Mac uses ~/.local/share/coordinator-work. "
       "Write `<state dir>/...` and name both dirs (see reviewer-brief.md §1, the decision-log lookup), "
       "or move the text into a .tmpl that picks the dir per profile")


def offenders(root=HARNESS):
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix == ".tmpl":
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if PERSONAL_STATE.search(line):
                out.append("%s:%d %s" % (path.relative_to(REPO), n, FIX))
    return out


class SharedTextPaths(unittest.TestCase):
    def test_no_personal_only_coordinator_path(self):
        found = offenders()
        self.assertEqual(found, [], "\n".join(found))


if __name__ == "__main__":
    unittest.main()
