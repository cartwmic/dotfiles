"""The descriptions the three release-bump scripts write carry no agent bookkeeping, so they pass the coordinator's pr-body-check.

The fixtures are the real descriptions of two merged public PRs, written by the scripts before the cutover: cartwmic/dotfiles#645 (agent-kit 0.67.1) and
#654 (Loop Engine v0.58.0). Each held a principles table and a `Decisions:` line, which the checker refuses in a description. The new code builds a
description for the same release (the Loop Engine one from the import report inside #654's own fenced block), and that must pass.

The structural tests always run. The checker tests run the real coordinator script and skip when it is not named: this repo's CI has no coordinator
checkout. Name it with PR_BODY_CHECK_TS=<coordinator checkout>/scripts/pr-body-check.ts (a checkout at or after the cutover change).

    python3 -m unittest discover -s tests/pr-record -v
    PR_BODY_CHECK_TS=~/git/coordinator/scripts/pr-body-check.ts python3 -m unittest discover -s tests/pr-record -v
"""

import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "dot_local/user_scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CHECKER = os.environ.get("PR_BODY_CHECK_TS")


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AGENT_KIT = load("agent_kit_bump", "executable_agent_kit_bump.py")
LOOP_ENGINE = load("loop_engine_bump", "executable_loop_engine_bump.py")
T3_PIN = load("t3_pin_check", "executable_t3_pin_check.py")
OLD_AGENT_KIT = (FIXTURES / "agent-kit-bump-645-body.md").read_text(encoding="utf-8")
OLD_LOOP_ENGINE = (FIXTURES / "loop-engine-bump-654-body.md").read_text(encoding="utf-8")
# The import tool's output as it was when #654 was made: the old description's one fenced block.
LOOP_ENGINE_REPORT = re.search(r"```\n(.*?)```", OLD_LOOP_ENGINE, re.S).group(1)


def new_descriptions():
    return {
        "agent-kit 0.67.1": AGENT_KIT.pr_body("0.67.1"),
        "Loop Engine v0.58.0": LOOP_ENGINE.pr_body("v0.58.0", LOOP_ENGINE_REPORT),
    }


class Structure(unittest.TestCase):
    def test_the_fixtures_are_the_old_shape(self):
        for body in (OLD_AGENT_KIT, OLD_LOOP_ENGINE):
            self.assertIn("| # | Principle | Result | Evidence |", body)
            self.assertRegex(body, r"(?m)^Decisions: none material$")

    def test_a_new_description_has_no_table_no_decisions_line_and_no_ids(self):
        for name, body in new_descriptions().items():
            outside_fences = re.sub(r"```.*?```", "", body, flags=re.S)
            self.assertNotIn("|", outside_fences, name)
            self.assertNotIn("Decisions:", body, name)
            self.assertNotRegex(body, r"(?i)\b(?:ask|decision|grant)s?\s+#\d+|rule [0-9a-f]{8}\b|\bPrinciples\b", name)
            for heading in ("What changes", "Why", "How it was checked", "Risk and rollback"):
                self.assertIn("## " + heading, body, name)

    def test_the_loop_engine_description_keeps_the_import_report_and_drops_the_scratch_paths(self):
        body = new_descriptions()["Loop Engine v0.58.0"]
        self.assertIn("using-lean-change-provider         +0 added  ~1 changed", body)
        self.assertIn("pins: 0.57.0 -> 0.58.0 (dot_config/mise/config.toml)", body)
        self.assertNotIn("applied to /tmp/", body)
        self.assertNotIn("next: review git diff", body)

    def test_the_record_holds_what_the_description_no_longer_does(self):
        for text in (AGENT_KIT.record_text("0.67.1"), LOOP_ENGINE.record_text(), T3_PIN.record_text("#3685")):
            rows = re.findall(r"(?m)^\| (\d+) \| .+ \| (?:pass|fail|n/a) \| .+ \|$", text)
            self.assertEqual(rows, [str(n) for n in range(1, 17)])
            self.assertTrue(text.rstrip("\n").splitlines()[-1].startswith("Decisions: "))


@unittest.skipUnless(CHECKER and Path(CHECKER).is_file() and shutil.which("node"), "needs node and PR_BODY_CHECK_TS (the coordinator's pr-body-check.ts)")
class Checker(unittest.TestCase):
    def check(self, body):
        with tempfile.TemporaryDirectory(prefix="bump-body-") as scratch:
            file = Path(scratch) / "body.md"
            file.write_text(body, encoding="utf-8")
            # cwd is not a git work tree, so only the description itself is read.
            return subprocess.run(["node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", CHECKER, "--body-file", str(file)],
                                  cwd=scratch, capture_output=True, text=True, timeout=120)

    def test_the_old_real_descriptions_are_refused(self):
        for name, body in (("agent-kit #645", OLD_AGENT_KIT), ("Loop Engine #654", OLD_LOOP_ENGINE)):
            result = self.check(body)
            self.assertEqual(result.returncode, 1, name + result.stdout + result.stderr)
            self.assertIn("principles table (18 lines)", result.stdout + result.stderr, name)
            self.assertIn("Decisions: line", result.stdout + result.stderr, name)

    def test_the_new_descriptions_for_the_same_releases_pass(self):
        for name, body in new_descriptions().items():
            result = self.check(body)
            self.assertEqual(result.returncode, 0, name + result.stdout + result.stderr)

    def test_the_t3_pin_descriptions_pass(self):
        sums = {"x64": "a" * 64, "arm64": "b" * 64}
        pin = {"version": "0.1.9"}
        bodies = {}
        original = T3_PIN.publish
        T3_PIN.publish = lambda *a, **k: "t3-pin/0.1.10"   # no git, no push: only the description text is wanted
        try:
            for name, opener, args in (("dotfiles", T3_PIN.open_dotfiles_pr, (Path("/x"), "cartwmic/dotfiles", "0.1.10", pin, sums, True)),
                                       ("steward", T3_PIN.open_steward_pr, (Path("/x"), None, None, "0.1.10", pin, sums, True))):
                printed = opener(*args)
                bodies[name] = printed.split("\n", 1)[1].split("\nand write its agent record:")[0]
        finally:
            T3_PIN.publish = original
        for name, body in bodies.items():
            result = self.check(body)
            self.assertEqual(result.returncode, 0, name + result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
