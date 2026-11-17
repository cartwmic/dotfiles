"""Exercise the actual install-spotify mise task (conf.d/spotify.toml) with a fake brew and a private HOME."""
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
CHEZMOI = shutil.which("chezmoi")
CONF = ROOT / "dot_config/mise/conf.d/spotify.toml"


@unittest.skipUnless(MISE, "mise is required")
class InstallSpotifyTests(unittest.TestCase):
    def exercise(self, system, *, app_present):
        with tempfile.TemporaryDirectory(prefix="spotify-task-test-") as temporary:
            root = Path(temporary)
            home, project, mock = root / "home", root / "project", root / "mock"
            for directory in (home, project, mock):
                directory.mkdir()
            task = tomllib.loads(CONF.read_text())["tasks"]["install-spotify"]
            (project / "mise.toml").write_text("[tasks.install-spotify]\nrun = " + json.dumps(task["run"]) + "\n")
            (root / "global.toml").write_text("")
            for name, body in (("uname", "#!/bin/sh\necho \"$TEST_SYSTEM\"\n"),
                               ("brew", "#!/bin/sh\necho \"$@\" >> \"$TEST_BREW\"\n")):
                (mock / name).write_text(body)
                (mock / name).chmod(0o700)
            app = root / "Spotify.app"
            if app_present:
                app.mkdir()
            env = {
                "HOME": str(home), "PATH": str(mock) + ":/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(root / "config"), "MISE_GLOBAL_CONFIG_FILE": str(root / "global.toml"),
                "MISE_DATA_DIR": str(root / "mise-data"), "MISE_CACHE_DIR": str(root / "mise-cache"),
                "MISE_TRUSTED_CONFIG_PATHS": str(project), "MISE_YES": "1",
                "TEST_SYSTEM": system, "TEST_BREW": str(root / "brew.log"), "SPOTIFY_APP_DIR": str(app),
            }
            completed = subprocess.run([MISE, "run", "install-spotify"], cwd=project, env=env,
                                       text=True, capture_output=True, timeout=60)
            log = root / "brew.log"
            return completed, (log.read_text().splitlines() if log.exists() else [])

    def test_macos_without_spotify_installs_the_cask(self):
        result, brew = self.exercise("Darwin", app_present=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(brew, ["install --cask spotify"])

    def test_macos_with_spotify_does_nothing(self):
        result, brew = self.exercise("Darwin", app_present=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(brew, [])
        self.assertIn("already installed", result.stdout)

    def test_linux_skips(self):
        result, brew = self.exercise("Linux", app_present=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(brew, [])
        self.assertIn("Skipping", result.stdout)

    def render(self, name, profile, os_name, hostname):
        """Render a template the way chezmoi does for this profile, OS and hostname (real chezmoi, scratch config and HOME)."""
        with tempfile.TemporaryDirectory(prefix="spotify-render-") as temporary:
            cfg = Path(temporary) / "chezmoi.yaml"
            cfg.write_text("data:\n  profile: %s\n" % profile)
            data = json.dumps({"chezmoi": {"os": os_name, "hostname": hostname}})
            completed = subprocess.run(
                [CHEZMOI, "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "--destination", temporary,
                 "execute-template", "--override-data", data],
                input=(ROOT / name).read_text(), text=True, capture_output=True, timeout=60, env=dict(os.environ, HOME=temporary))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return completed.stdout

    CASES = (  # profile, os, hostname, gets the file and the step
        ("personal", "darwin", "cartwmic-server", True),    # the Mac mini
        ("personal", "darwin", "Michaels-MacBook-Pro", False),
        ("axon-work-computer", "darwin", "axon-work-computer", False),
        ("axon-work-computer", "darwin", "cartwmic-server", False),
        ("personal", "linux", "cartwmic-server", False),
    )

    @unittest.skipUnless(CHEZMOI, "chezmoi is required")
    def test_only_the_personal_mac_mini_gets_the_file_and_the_step(self):
        for profile, os_name, hostname, gets in self.CASES:
            with self.subTest(profile=profile, os=os_name, host=hostname):
                ignored = self.render(".chezmoiignore", profile, os_name, hostname).splitlines()
                self.assertEqual(".config/mise/conf.d/spotify.toml" in ignored, not gets)
                script = self.render("run_onchange_after_10_mise_bootstrap.sh.tmpl", profile, os_name, hostname).splitlines()
                self.assertEqual("mise run install-spotify" in script, gets)
                self.assertEqual(any(line.startswith("# Hash (Mac mini Spotify task)") for line in script), gets)

    def test_not_in_the_shared_config(self):
        config = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())
        self.assertNotIn("install-spotify", config["tasks"])


if __name__ == "__main__":
    unittest.main()
