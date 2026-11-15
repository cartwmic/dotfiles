"""pr-body-check: the short name `homelab` reaches the coordinator's checker as the homelab repo's full name.

The wrapper (dot_local/bin/executable_pr-body-check) runs ~/git/coordinator/scripts/pr-body-check.ts with node. CI has no
coordinator checkout, so a stub checker stands in for that file and a stub node records what the wrapper hands it. Each
test states one thing the wrapper must hand the checker.
"""
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "dot_local/bin/executable_pr-body-check"

# The wrapper runs `node <flags> <checker> <args>`. The stub writes each argument on its own line, so the test can cut off the flags.
FAKE_NODE = textwrap.dedent('''\
    #!/bin/sh
    for a in "$@"; do printf '%s\\n' "$a"; done > "$FAKE_NODE_ARGS"
''')


class PrBodyCheckWrapperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        checker_dir = self.home / "git/coordinator/scripts"
        checker_dir.mkdir(parents=True)
        self.checker = checker_dir / "pr-body-check.ts"
        self.checker.write_text("")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        node = bin_dir / "node"
        node.write_text(FAKE_NODE)
        node.chmod(0o755)
        self.args_file = root / "node-args"
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_NODE_ARGS": str(self.args_file),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def checker_args(self, *args):
        """Runs the wrapper with `args` and returns the arguments it handed the checker."""
        run = subprocess.run(["sh", str(WRAPPER), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        argv = self.args_file.read_text().splitlines()
        return argv[argv.index(str(self.checker)) + 1:]

    def test_homelab_short_name_becomes_the_homelab_repo(self):
        self.assertEqual(self.checker_args("homelab", "287"), ["cartwmic/cartwmic-homelab-v2", "287"])

    def test_homelab_short_name_keeps_the_later_arguments(self):
        self.assertEqual(
            self.checker_args("homelab", "287", "--body-file", "body.md"),
            ["cartwmic/cartwmic-homelab-v2", "287", "--body-file", "body.md"],
        )

    def test_full_homelab_name_is_unchanged(self):
        self.assertEqual(self.checker_args("cartwmic/cartwmic-homelab-v2", "287"), ["cartwmic/cartwmic-homelab-v2", "287"])

    def test_other_full_names_are_unchanged(self):
        self.assertEqual(self.checker_args("cartwmic/dotfiles", "12"), ["cartwmic/dotfiles", "12"])


if __name__ == "__main__":
    unittest.main()
