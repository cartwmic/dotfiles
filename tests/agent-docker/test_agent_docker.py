"""Black-box tests for the agent docker config (docs/agent-docker.md). No docker process is started.

    python3 -m unittest discover -s tests/agent-docker -v

- the DOCKER_CONFIG block in dot_zshenv, in a real non-interactive `zsh -c` (the kind Claude Code, T3, Codex and herdr panes start) with
  HOME set to a temporary directory holding dot_zshenv as ~/.zshenv;
- the deployed config.json, read as a file;
- (macOS) a real `chezmoi apply` of the personal and work profiles into a scratch HOME with a fake ~/.docker.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZSHENV = ROOT / "dot_zshenv"
CONFIG = ROOT / "dot_config/agent-docker/config.json"
ZSH = shutil.which("zsh")
CHEZMOI = shutil.which("chezmoi")
MARKERS = ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "T3CODE_THREAD_ID", "HERDR_ENV", "CODEX_SANDBOX"]


class ConfigFileTest(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CONFIG.read_text())

    def test_no_credential_store_or_helper(self):
        self.assertNotIn("credsStore", self.cfg)
        self.assertNotIn("credHelpers", self.cfg)

    def test_one_auths_entry_keeps_the_cli_from_detecting_a_default_helper(self):
        # The docker CLI picks docker-credential-osxkeychain for a config with no auth at all (ContainsAuth is false).
        self.assertTrue(self.cfg["auths"])
        self.assertTrue(all(v == {} for v in self.cfg["auths"].values()), "an auths entry must hold no credential")

    def test_keeps_the_docker_desktop_context(self):
        self.assertEqual(self.cfg["currentContext"], "desktop-linux")


@unittest.skipUnless(ZSH, "zsh is not installed")
class ZshenvBlockTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="agent-docker-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        shutil.copy(ZSHENV, self.home / ".zshenv")
        self.dir = self.home / ".config/agent-docker"

    def docker_config(self, **env):
        base = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        base.update(env)
        r = subprocess.run([ZSH, "-c", 'printf "%s" "${DOCKER_CONFIG-unset}"'], env=base, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stderr, "")
        return r.stdout

    def test_each_agent_marker_gets_the_agent_config(self):
        self.dir.mkdir(parents=True)
        for marker in MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual(self.docker_config(**{marker: "1"}), str(self.dir))

    def test_a_terminal_without_a_marker_keeps_the_normal_config(self):
        self.dir.mkdir(parents=True)
        self.assertEqual(self.docker_config(), "unset")

    def test_an_empty_marker_is_not_a_marker(self):
        self.dir.mkdir(parents=True)
        self.assertEqual(self.docker_config(CLAUDECODE="", T3CODE_THREAD_ID=""), "unset")

    def test_without_the_directory_nothing_is_set(self):
        self.assertEqual(self.docker_config(CLAUDECODE="1"), "unset")

    def test_an_inherited_value_wins_even_when_empty(self):
        self.dir.mkdir(parents=True)
        self.assertEqual(self.docker_config(CLAUDECODE="1", DOCKER_CONFIG="/somewhere/else"), "/somewhere/else")
        self.assertEqual(self.docker_config(CLAUDECODE="1", DOCKER_CONFIG=""), "")

    def test_zshenv_local_can_set_its_own(self):
        self.dir.mkdir(parents=True)
        (self.home / ".zshenv.local").write_text("export DOCKER_CONFIG=/from/local\n")
        self.assertEqual(self.docker_config(CLAUDECODE="1"), "/from/local")

    def test_a_login_shell_gets_it_too(self):
        self.dir.mkdir(parents=True)
        r = subprocess.run([ZSH, "-lc", 'printf "%s" "${DOCKER_CONFIG-unset}"'],
                           env={"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "CLAUDECODE": "1"},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout, str(self.dir))


@unittest.skipUnless(sys.platform == "darwin" and CHEZMOI and ZSH, "needs macOS, chezmoi and zsh")
class ApplyTest(unittest.TestCase):
    """A real apply into a scratch HOME that holds a fake ~/.docker (no docker, no real home)."""

    def apply(self, profile, *targets):
        tmp = Path(tempfile.mkdtemp(prefix="agent-docker-apply-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        home = tmp / "home"
        for d in ("contexts/meta/abc", "cli-plugins", "buildx"):
            (home / ".docker" / d).mkdir(parents=True)
        (home / ".config").mkdir()
        (home / ".docker/contexts/meta/abc/meta.json").write_text('{"Name":"desktop-linux"}')
        cfg = tmp / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        subprocess.run([CHEZMOI, "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                        "apply", "--exclude=scripts", "--no-tty", *[str(home / t) for t in targets]],
                       env=dict(os.environ, HOME=str(home)), capture_output=True, text=True, timeout=120, check=True)
        return home

    def test_personal_gets_the_config_and_links_that_resolve(self):
        home = self.apply("personal", ".config/agent-docker", ".zshenv")
        d = home / ".config/agent-docker"
        self.assertEqual(json.loads((d / "config.json").read_text()), json.loads(CONFIG.read_text()))
        for name in ("contexts", "cli-plugins", "buildx"):
            self.assertTrue((d / name).is_symlink(), name)
            self.assertEqual(os.readlink(d / name), str(home / ".docker" / name))
        # The context metadata is found through the link, as the docker CLI reads it.
        self.assertEqual(json.loads((d / "contexts/meta/abc/meta.json").read_text())["Name"], "desktop-linux")
        env = {"HOME": str(home), "PATH": os.environ["PATH"], "T3CODE_THREAD_ID": "t"}
        out = subprocess.run([ZSH, "-c", 'printf "%s" "$DOCKER_CONFIG"'], env=env, capture_output=True, text=True, timeout=30).stdout
        self.assertEqual(out, str(d))

    def test_work_gets_no_agent_docker_directory(self):
        home = self.apply("axon-work-computer", ".zshenv")
        self.assertFalse((home / ".config/agent-docker").exists())
        cfg = home.parent / "chezmoi.yaml"
        managed = subprocess.run([CHEZMOI, "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                                  "managed"], env=dict(os.environ, HOME=str(home)), capture_output=True, text=True, timeout=120, check=True).stdout
        self.assertNotIn("agent-docker", managed)
        env = {"HOME": str(home), "PATH": os.environ["PATH"], "T3CODE_THREAD_ID": "t"}
        out = subprocess.run([ZSH, "-c", 'printf "%s" "${DOCKER_CONFIG-unset}"'], env=env, capture_output=True, text=True, timeout=30).stdout
        self.assertEqual(out, "unset")


if __name__ == "__main__":
    unittest.main()
