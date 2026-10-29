"""Exercise the actual install-google-chrome mise task with a fake brew and a private HOME."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
MISE = shutil.which("mise")


@unittest.skipUnless(MISE, "mise is required")
class InstallGoogleChromeTests(unittest.TestCase):
    def exercise(self, system, *, app_present):
        with tempfile.TemporaryDirectory(prefix="chrome-task-test-") as temporary:
            root = Path(temporary)
            home, project, mock = root / "home", root / "project", root / "mock"
            for directory in (home, project, mock):
                directory.mkdir()
            task = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tasks"]["install-google-chrome"]
            (project / "mise.toml").write_text("[tasks.install-google-chrome]\nrun = " + json.dumps(task["run"]) + "\n")
            (root / "global.toml").write_text("")
            for name, body in (("uname", "#!/bin/sh\necho \"$TEST_SYSTEM\"\n"),
                               ("brew", "#!/bin/sh\necho \"$@\" >> \"$TEST_BREW\"\n")):
                (mock / name).write_text(body)
                (mock / name).chmod(0o700)
            app = root / "Google Chrome.app"
            if app_present:
                app.mkdir()
            env = {
                "HOME": str(home), "PATH": str(mock) + ":/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(root / "config"), "MISE_GLOBAL_CONFIG_FILE": str(root / "global.toml"),
                "MISE_DATA_DIR": str(root / "mise-data"), "MISE_CACHE_DIR": str(root / "mise-cache"),
                "MISE_TRUSTED_CONFIG_PATHS": str(project), "MISE_YES": "1",
                "TEST_SYSTEM": system, "TEST_BREW": str(root / "brew.log"), "GOOGLE_CHROME_APP_DIR": str(app),
            }
            completed = subprocess.run([MISE, "run", "install-google-chrome"], cwd=project, env=env,
                                       text=True, capture_output=True, timeout=60)
            log = root / "brew.log"
            return completed, (log.read_text().splitlines() if log.exists() else [])

    def test_macos_without_chrome_installs_the_cask(self):
        result, brew = self.exercise("Darwin", app_present=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(brew, ["install --cask google-chrome"])

    def test_macos_with_chrome_does_nothing(self):
        result, brew = self.exercise("Darwin", app_present=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(brew, [])
        self.assertIn("already installed", result.stdout)

    def test_linux_skips(self):
        result, brew = self.exercise("Linux", app_present=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(brew, [])
        self.assertIn("Skipping", result.stdout)

    def test_chrome_is_in_the_bootstrap(self):
        config = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())
        self.assertIn("install-google-chrome", config["tasks"]["bootstrap"]["depends"])


if __name__ == "__main__":
    unittest.main()
