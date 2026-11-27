"""Tests across every canonical skill's scripts/ folder (dot_local/share/agent-harness/canonical/skills/*/scripts).

A skill stays self-contained, so a helper several skills need (runlog.py, logged.py) is copied into each. The copies must stay byte
for byte the same. The skill folders are deployed to ~/.local/share/agent-harness, which chezmoi does not own, so a script that
imports a sibling must not leave a __pycache__ there.

    python3 -m unittest discover -s tests/skill-scripts
"""
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
COPIED = ("runlog.py", "logged.py")


def scripts():
    return sorted(SKILLS.glob("*/scripts/*.py"))


def sibling_imports(path):
    """The sibling modules (files next to `path`) that `path` imports by name."""
    siblings = {p.stem for p in path.parent.glob("*.py")} - {path.stem}
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return sorted(found & siblings)


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


class NoBytecodeInDeployedSkills(unittest.TestCase):
    def test_scripts_that_import_a_sibling_are_found(self):
        importers = [p for p in scripts() if sibling_imports(p)]
        self.assertGreater(len(importers), 10)

    def test_a_script_that_imports_a_sibling_writes_no_pycache_when_run_plainly(self):
        importers = [p for p in scripts() if sibling_imports(p)]
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH")}
        for script in importers:
            with self.subTest(script=str(script.relative_to(SKILLS))), tempfile.TemporaryDirectory() as tmp:
                skills = Path(tmp) / "skills"
                shutil.copytree(SKILLS, skills, ignore=shutil.ignore_patterns("__pycache__"))
                home = Path(tmp) / "home"
                work = Path(tmp) / "work"
                home.mkdir()
                work.mkdir()
                run_env = dict(env, HOME=str(home), XDG_STATE_HOME=str(home / "state"))
                # Plain python3: no -I, no -B. The sibling is imported before the script reads its arguments, so a bare run is enough.
                subprocess.run([sys.executable, str(skills / script.relative_to(SKILLS)), "--help"], cwd=work, env=run_env,
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
                stray = [str(p.relative_to(tmp)) for p in Path(tmp).rglob("__pycache__")]
                self.assertEqual(stray, [], "running %s left bytecode behind" % script.name)


if __name__ == "__main__":
    unittest.main()
