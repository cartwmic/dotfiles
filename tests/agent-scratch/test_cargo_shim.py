"""The agent-shell `cargo` (dot_local/share/agent-scratch/bin/executable_cargo) and the PATH block in dot_zshenv.

    python3 -m unittest discover -s tests/agent-scratch -p 'test_cargo_shim.py' -v

Real `zsh -c` with HOME set to a temporary directory holding the real dot_zshenv, the env file and the shim. The "real cargo" is a fake
script in ~/.cargo/bin that prints the arguments and the target dir it sees; ~/.cargo/env is the real rustup one in shape, so the
shim has to come first even though ~/.cargo/env prepends ~/.cargo/bin.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZSHENV = ROOT / "dot_zshenv"
ENV_FILE = ROOT / "dot_config/agent-scratch/workshop.env"
SHIM = ROOT / "dot_local/share/agent-scratch/bin/executable_cargo"
ZSH = shutil.which("zsh")
CARGO_ENV = '''#!/bin/sh
case ":${PATH}:" in
    *:"$HOME/.cargo/bin":*) ;;
    *) export PATH="$HOME/.cargo/bin:$PATH" ;;
esac
'''
FAKE_CARGO = '#!/bin/sh\necho "real cargo: args=$* target=${CARGO_TARGET_DIR-unset}"\n'


@unittest.skipUnless(ZSH and shutil.which("git"), "needs zsh and git")
class CargoShimTest(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="cargo-shim-")).resolve()
        self.addCleanup(shutil.rmtree, self.t, ignore_errors=True)
        self.home = self.t / "home"
        (self.home / ".cargo/bin").mkdir(parents=True)
        (self.home / ".cargo/env").write_text(CARGO_ENV)
        fake = self.home / ".cargo/bin/cargo"
        fake.write_text(FAKE_CARGO)
        fake.chmod(0o755)
        shutil.copy(ZSHENV, self.home / ".zshenv")
        (self.home / ".config/agent-scratch").mkdir(parents=True)
        shutil.copy(ENV_FILE, self.home / ".config/agent-scratch/workshop.env")
        shim_dir = self.home / ".local/share/agent-scratch/bin"
        shim_dir.mkdir(parents=True)
        shutil.copy(SHIM, shim_dir / "cargo")
        (shim_dir / "cargo").chmod(0o755)
        self.ws = self.t / "ws"
        (self.ws / "macbook").mkdir(parents=True)
        self.repo = self.t / "my-repo"
        (self.repo / "sub").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def zsh(self, script, cwd=None, **extra):
        env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin", "AGENT_WORKSHOP_ROOT": str(self.ws)}
        env.update(extra)
        return subprocess.run([ZSH, "-c", script], env=env, cwd=cwd or self.repo, capture_output=True, text=True, timeout=60)

    def test_a_plain_shell_gets_the_real_cargo_untouched(self):
        r = self.zsh("command -v cargo; cargo build")
        self.assertEqual(r.stdout.splitlines(), [str(self.home / ".cargo/bin/cargo"), "real cargo: args=build target=unset"], r.stderr)
        self.assertNotIn("agent-scratch/bin", self.zsh('printf %s "$PATH"').stdout)

    def test_an_agent_shell_gets_the_shim_first_and_a_per_project_target(self):
        for marker in ({"CLAUDECODE": "1"}, {"T3CODE_THREAD_ID": "thread:x"}):
            r = self.zsh("command -v cargo; cargo build --release", cwd=self.repo / "sub", **marker)
            self.assertEqual(r.stdout.splitlines()[0], str(self.home / ".local/share/agent-scratch/bin/cargo"), (marker, r.stderr))
            self.assertEqual(r.stdout.splitlines()[1],
                             "real cargo: args=build --release target=%s" % (self.ws / "macbook/tmp-home/cargo-target/my-repo"))

    def test_two_projects_get_two_target_dirs(self):
        other = self.t / "other-repo"
        other.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        a = self.zsh("cargo build", CLAUDECODE="1").stdout
        b = self.zsh("cargo build", cwd=other, CLAUDECODE="1").stdout
        self.assertIn("cargo-target/my-repo", a)
        self.assertIn("cargo-target/other-repo", b)

    def test_outside_a_git_repo_it_uses_the_current_directory_name(self):
        d = self.t / "scratch-dir"
        d.mkdir()
        r = self.zsh("cargo build", cwd=d, CLAUDECODE="1")
        self.assertIn("cargo-target/scratch-dir", r.stdout)

    def test_an_explicit_target_dir_is_left_alone(self):
        r = self.zsh("cargo build", CLAUDECODE="1", CARGO_TARGET_DIR="/somewhere/else")
        self.assertIn("target=/somewhere/else", r.stdout)
        r = self.zsh("cargo build", CLAUDECODE="1", CARGO_BUILD_TARGET_DIR="/x")
        self.assertIn("target=unset", r.stdout)

    def test_nested_shells_add_the_path_entry_once_and_still_get_the_shim(self):
        r = self.zsh('%s -c \'printf "%%s\\n" "$PATH"; command -v cargo\'' % ZSH, CLAUDECODE="1")
        path, found = r.stdout.splitlines()
        self.assertEqual(path.count(".local/share/agent-scratch/bin"), 1, path)
        self.assertEqual(found, str(self.home / ".local/share/agent-scratch/bin/cargo"))

    def test_unmounted_workshop_keeps_the_target_on_the_missing_workshop_path(self):
        gone = self.t / "gone"
        r = self.zsh("cargo build", CLAUDECODE="1", AGENT_WORKSHOP_ROOT=str(gone))
        self.assertIn("target=%s" % (gone / "macbook/tmp-home/cargo-target/my-repo"), r.stdout)
        self.assertFalse(gone.exists())

    def test_without_the_shim_directory_an_agent_shell_is_unchanged(self):
        shutil.rmtree(self.home / ".local/share/agent-scratch")
        r = self.zsh("command -v cargo", CLAUDECODE="1")
        self.assertEqual(r.stdout.strip(), str(self.home / ".cargo/bin/cargo"))

    def test_no_other_cargo_on_path_is_an_error_not_a_loop(self):
        (self.home / ".cargo/bin/cargo").unlink()
        r = self.zsh("cargo build", CLAUDECODE="1")
        self.assertEqual(r.returncode, 127)
        self.assertIn("no other cargo", r.stderr)


if __name__ == "__main__":
    unittest.main()
