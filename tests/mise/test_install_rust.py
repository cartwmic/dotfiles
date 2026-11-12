"""Run the real install-rust and install-cargo-tools mise tasks in a private HOME, with rustup/cargo/curl scripted.

The first apply on the Linux box hit two things: a mise shim named rustup hid the missing ~/.cargo/bin/rustup (so rustup was never installed and
`rustup default stable` ran a half-installed toolchain), and a bash-run apply found no cargo because only ~/.zshenv puts ~/.cargo/bin on PATH."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
MISE = shutil.which("mise")

# What a mise shim for rustup did: not the real rustup.
SHIM = """#!/bin/sh
echo "SHIM $(basename "$0") $*" >> "$T/calls"
echo "error: missing manifest for toolchain" >&2
exit 1
"""
RUSTUP = """#!/bin/sh
echo "REAL rustup $*" >> "$T/calls"
[ "$1" != --version ] || echo "rustup 1.28.0"
"""
CARGO = """#!/bin/sh
echo "REAL cargo $*" >> "$T/calls"
"""
# The fake rustup installer that curl pipes to sh: puts real rustup/cargo in ~/.cargo/bin and writes ~/.cargo/env (the real one's PATH logic).
CURL = """#!/bin/sh
echo "curl $*" >> "$T/calls"
cat <<'INSTALLER'
mkdir -p "$HOME/.cargo/bin"
for n in rustup cargo; do cp "$T/real-$n" "$HOME/.cargo/bin/$n"; done
cat > "$HOME/.cargo/env" <<'ENV'
case ":${PATH}:" in *:"$HOME/.cargo/bin":*) ;; *) export PATH="$HOME/.cargo/bin:$PATH" ;; esac
ENV
INSTALLER
"""
MISE_STUB = """#!/bin/sh
echo "mise $*" >> "$T/calls"
"""


@unittest.skipUnless(MISE and sys.platform.startswith("linux"), "Linux and mise are required")
class RustTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rust-task-test-")
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.home, self.project, self.mock, self.shims = self.t / "home", self.t / "project", self.t / "mock", self.t / "shims"
        for d in (self.home, self.project, self.mock, self.shims):
            d.mkdir()
        (self.t / "calls").write_text("")
        for n, text in (("rustup", RUSTUP), ("cargo", CARGO)):
            (self.t / f"real-{n}").write_text(text)
            (self.t / f"real-{n}").chmod(0o755)
        for name, text in (("curl", CURL), ("mise", MISE_STUB)):
            (self.mock / name).write_text(text)
            (self.mock / name).chmod(0o755)
        for n in ("rustup", "cargo", "rustc"):   # mise shims, ahead of ~/.cargo/bin
            (self.shims / n).write_text(SHIM)
            (self.shims / n).chmod(0o755)
        self.tasks = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tasks"]

    def run_task(self, name, path_head, behind_shims=True):
        (self.project / "mise.toml").write_text(f"[tasks.t]\nrun = {json.dumps(self.tasks[name]['run'])}\n")
        env = {"HOME": str(self.home), "T": str(self.t), "TMPDIR": str(self.t), "PATH": f"{path_head}:{self.mock}:/usr/bin:/bin" + (f":{self.home}/.cargo/bin" if behind_shims else ""),   # as on the box: ~/.cargo/bin behind the shims
               "XDG_CONFIG_HOME": str(self.t / "config"), "MISE_DATA_DIR": str(self.t / "mise-data"), "MISE_CACHE_DIR": str(self.t / "cache"),
               "MISE_TRUSTED_CONFIG_PATHS": str(self.project), "MISE_YES": "1", "MISE_SYSTEM_CONFIG_DIR": str(self.t / "etc")}
        done = subprocess.run([MISE, "run", "t"], cwd=self.project, env=env, text=True, capture_output=True, timeout=60)
        return done, (self.t / "calls").read_text().splitlines()

    def test_a_mise_rustup_shim_does_not_hide_the_missing_cargo_rustup(self):
        done, calls = self.run_task("install-rust", self.shims)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.home / ".cargo/bin/rustup").exists(), "rustup was not installed")
        self.assertFalse([c for c in calls if c.startswith("SHIM")], calls)
        self.assertEqual([c for c in calls if c.startswith("REAL rustup")],
                         ["REAL rustup default stable", "REAL rustup component add rust-analyzer", "REAL rustup target add wasm32-wasip1", "REAL rustup --version"])

    def test_RED_control_the_old_task_hits_the_shim(self):
        # The task text on main before this change, byte for byte (install-rust-before-322.sh).
        self.tasks["install-rust"]["run"] = (Path(__file__).parent / "install-rust-before-322.sh").read_text()
        done, calls = self.run_task("install-rust", self.shims)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("SHIM rustup default stable", calls)
        self.assertFalse((self.home / ".cargo/bin/rustup").exists())

    def test_an_installed_rustup_is_not_reinstalled(self):
        (self.home / ".cargo/bin").mkdir(parents=True)
        shutil.copy2(self.t / "real-rustup", self.home / ".cargo/bin/rustup")
        done, calls = self.run_task("install-rust", self.shims)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse([c for c in calls if c.startswith("curl")], calls)
        self.assertEqual(calls[0], "REAL rustup default stable")

    def mise_rust_fixture(self, rust):
        """What mise leaves behind: a regular .mise.backend.toml in the tool's dir (every tool has one), 'latest', and a version dir of symlinks."""
        (rust / "1.98.0/bin").mkdir(parents=True)
        (rust / ".mise.backend.toml").write_text('backend = "core:rust"\n')
        (rust / "1.98.0/bin/cargo").symlink_to(self.home / ".cargo/bin/cargo")
        (rust / "latest").symlink_to("1.98.0")
        return rust

    def test_a_symlink_only_mise_rust_install_with_its_metadata_file_is_removed_and_reshimmed(self):
        rust = self.mise_rust_fixture(self.t / "mise-data/installs/rust")
        done, calls = self.run_task("install-rust", self.shims)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(rust.exists())
        self.assertIn("mise reshim", calls)

    def test_RED_control_counting_mise_metadata_as_real_files_skips_the_cleanup(self):
        run = self.tasks["install-rust"]["run"]
        self.assertIn("! -name '.mise*' ", run)
        self.tasks["install-rust"]["run"] = run.replace("! -name '.mise*' ", "")   # the find as first reviewed
        rust = self.mise_rust_fixture(self.t / "mise-data/installs/rust")
        done, calls = self.run_task("install-rust", self.shims)
        self.assertTrue(rust.exists())
        self.assertIn("holds real files", done.stderr)
        self.assertNotIn("mise reshim", calls)

    def test_without_MISE_DATA_DIR_the_data_dir_follows_XDG_DATA_HOME(self):
        xdg = self.t / "xdg"
        rust = self.mise_rust_fixture(xdg / "mise/installs/rust")
        (self.project / "mise.toml").write_text(f"[tasks.t]\nrun = {json.dumps(self.tasks['install-rust']['run'])}\n")
        env = {"HOME": str(self.home), "T": str(self.t), "TMPDIR": str(self.t), "PATH": f"{self.shims}:{self.mock}:/usr/bin:/bin:{self.home}/.cargo/bin",
               "XDG_CONFIG_HOME": str(self.t / "config"), "XDG_DATA_HOME": str(xdg), "XDG_CACHE_HOME": str(self.t / "cache"),
               "MISE_TRUSTED_CONFIG_PATHS": str(self.project), "MISE_YES": "1", "MISE_SYSTEM_CONFIG_DIR": str(self.t / "etc")}
        done = subprocess.run([MISE, "run", "t"], cwd=self.project, env=env, text=True, capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(rust.exists())

    def test_a_mise_rust_install_with_real_files_is_left_alone_with_a_warning(self):
        installed = self.t / "mise-data/installs/rust/1.98.0"
        installed.mkdir(parents=True)
        (installed / "real-file").write_text("x")
        done, _ = self.run_task("install-rust", self.shims)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((installed / "real-file").exists())
        self.assertIn("holds real files", done.stderr)

    def test_cargo_tools_find_cargo_from_a_shell_that_never_read_zshenv(self):
        # Rust is installed (cargo in ~/.cargo/bin), PATH has no ~/.cargo/bin and only a shim cargo; rage and kickstart are missing.
        (self.home / ".cargo/bin").mkdir(parents=True)
        shutil.copy2(self.t / "real-cargo", self.home / ".cargo/bin/cargo")
        (self.home / ".cargo/env").write_text('case ":${PATH}:" in *:"$HOME/.cargo/bin":*) ;; *) export PATH="$HOME/.cargo/bin:$PATH" ;; esac\n')
        done, calls = self.run_task("install-cargo-tools", self.shims)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([c for c in calls if c.startswith("REAL cargo")],
                         ["REAL cargo install rage --locked", "REAL cargo install kickstart --features=cli"])
        self.assertFalse([c for c in calls if c.startswith("SHIM")], calls)

    def test_RED_control_cargo_tools_without_the_env_file_fail_when_cargo_is_only_in_cargo_bin(self):
        self.tasks["install-cargo-tools"]["run"] = (Path(__file__).parent / "install-cargo-tools-before-322.sh").read_text()
        (self.home / ".cargo/bin").mkdir(parents=True)
        shutil.copy2(self.t / "real-cargo", self.home / ".cargo/bin/cargo")
        done, _ = self.run_task("install-cargo-tools", str(self.t / "empty"), behind_shims=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("cargo not found", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
