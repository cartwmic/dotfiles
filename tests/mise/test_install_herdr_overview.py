"""Exercise Herdr Overview bootstrap through a real chezmoi apply with fake installers."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")


@unittest.skipUnless(CHEZMOI and shutil.which("jq"), "chezmoi and jq required")
class InstallHerdrOverviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="herdr-bootstrap-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.source = self.home / ".local/share/chezmoi"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for relative in (
            "run_onchange_after_10_mise_bootstrap.sh.tmpl",
            "dot_config/mise/config.toml",
            "dot_local/share/herdr-overview/herdr-plugin.toml",
        ):
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        config = self.home / ".config/chezmoi/chezmoi.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("data:\n  profile: personal\n")
        (self.home / ".config/herdr").mkdir(parents=True)
        self.link_log = self.root / "linked-source"
        install = self.root / "installed-herdr"
        install.mkdir()
        self.write_tool(install / "herdr", """
import os, pathlib, sys
args = sys.argv[1:]
if args == ['--version']:
    print('herdr 0.9.1')
elif len(args) == 4 and args[:2] == ['plugin', 'link'] and args[3] == '--enabled':
    pathlib.Path(os.environ['LINK_LOG']).write_text(args[2])
else:
    sys.exit('unexpected herdr call: ' + repr(args))
""")
        self.write_tool(self.bin / "mise", """
import os, pathlib, subprocess, sys, tomllib
args = sys.argv[1:]
if args == ['--version']:
    print('test mise')
elif args == ['where', 'github:herdrdev/herdr@0.9.1']:
    print(os.environ['FAKE_HERDR_DIR'])
elif args == ['run', 'bootstrap']:
    config = tomllib.loads(pathlib.Path(os.environ['HERDR_TEST_CONFIG']).read_text())
    sys.exit(subprocess.run(['/bin/sh', '-c', config['tasks']['install-herdr-overview']['run']]).returncode)
elif args in (['install'], ['install', 'github:herdrdev/herdr@0.9.1'], ['run', 'setup-ubuntu-essentials']):
    pass
else:
    sys.exit('unexpected mise call: ' + repr(args))
""")
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(("CHEZMOI_", "HERDR_OVERVIEW_", "OP_")):
                self.env.pop(key)
        self.env.update({
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "PATH": str(self.bin) + os.pathsep + self.env.get("PATH", "/usr/bin:/bin"),
            "FAKE_HERDR_DIR": str(install),
            "HERDR_TEST_CONFIG": str(self.source / "dot_config/mise/config.toml"),
            "LINK_LOG": str(self.link_log),
        })

    @staticmethod
    def write_tool(path, body):
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o755)

    def test_apply_bootstrap_links_the_active_source_without_nested_chezmoi_lock(self):
        completed = subprocess.run(
            [CHEZMOI, "--source", str(self.source), "apply"],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.link_log.read_text(), str(self.source / "dot_local/share/herdr-overview"))
        self.assertIn("mise bootstrap complete", completed.stderr)

    def test_apply_uses_the_active_worktree_instead_of_the_configured_checkout(self):
        worktree = self.root / "feature worktree"
        shutil.copytree(self.source, worktree)
        env = dict(self.env, HERDR_TEST_CONFIG=str(worktree / "dot_config/mise/config.toml"))
        completed = subprocess.run(
            [CHEZMOI, "--source", str(worktree), "apply"],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.link_log.read_text(), str(worktree / "dot_local/share/herdr-overview"))

    def test_standalone_task_uses_configured_source_not_cwd(self):
        task = tomllib.loads((self.source / "dot_config/mise/config.toml").read_text())["tasks"]["install-herdr-overview"]["run"]
        completed = subprocess.run(
            ["/bin/sh", "-c", task], cwd=self.root, env=self.env,
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(self.link_log.read_text(), str(self.source / "dot_local/share/herdr-overview"))


if __name__ == "__main__":
    unittest.main()
