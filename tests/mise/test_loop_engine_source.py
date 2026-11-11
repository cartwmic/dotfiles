"""Loop Engine on Linux arm64: the releases ship macOS arm64 and Linux x64 only, so the five [tools] entries skip Linux arm64
(`os = [...]`) and the install-loop-engine-from-source task builds them from the pinned tag. Real task script, scripted uname and cargo,
private HOME. The real build (cargo install of the tag) is not run here; it was run once by hand (see the PR)."""
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "dot_config/mise/config.toml"
TOOLS = ("loop-engine", "lean-change", "policy-document", "research", "bookends-check")
PACKAGES = ("loop-cli", "bookends-check", "lean-change-provider", "policy-document-provider", "research-provider")
TASK = tomllib.loads(CONFIG.read_text())["tasks"]["install-loop-engine-from-source"]


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class LoopEngineSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.mock = root / "mock"
        write_exec(self.mock / "cargo", '#!/bin/sh\necho "$@" >> "$TEST_CALLS"\nmkdir -p "$HOME/.local/bin"; : > "$HOME/.local/bin/bookends-check"; chmod +x "$HOME/.local/bin/bookends-check"\n')
        self.calls = root / "calls"
        self.config = root / "config.toml"
        self.config.write_text(CONFIG.read_text())

    def run_task(self, machine="aarch64", system="Linux"):
        write_exec(self.mock / "uname", f'#!/bin/sh\ncase "$1" in -s) echo {system};; -m) echo {machine};; esac\n')
        env = {"PATH": f"{self.mock}:/usr/bin:/bin", "HOME": str(self.home), "TEST_CALLS": str(self.calls), "MISE_GLOBAL_CONFIG_FILE": str(self.config)}
        return subprocess.run(["sh", "-c", TASK["run"]], env=env, capture_output=True, text=True, timeout=60)

    def cargo_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_all_five_tools_share_one_pin_and_skip_linux_arm64(self):
        tools = tomllib.loads(CONFIG.read_text())["tools"]
        versions = {tools[t]["version"] for t in TOOLS}
        self.assertEqual(len(versions), 1, versions)
        for t in TOOLS:
            self.assertEqual(tools[t]["os"], ["macos", "linux-x64"], t)

    def test_arm64_linux_builds_the_pinned_tag_once(self):
        version = tomllib.loads(CONFIG.read_text())["tools"]["bookends-check"]["version"]
        r = self.run_task()
        self.assertEqual(r.returncode, 0, r.stderr)
        (call,) = self.cargo_calls()
        self.assertIn(f"--tag v{version}", call)
        self.assertIn("--locked", call)
        self.assertIn(f"--root {self.home}/.local", call)
        self.assertEqual(sorted(w for w in call.split() if w in PACKAGES), sorted(PACKAGES))
        self.assertEqual((self.home / ".local/share/loop-engine-src/version").read_text().strip(), version)
        r = self.run_task()                                       # built already: nothing to do
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.cargo_calls()), 1)
        self.assertIn("already built", r.stdout)

    def test_a_bumped_pin_is_built_again(self):
        self.run_task()
        self.config.write_text(re.sub(r'(version = ")0\.45\.0(")', r"\g<1>0.46.0\2", CONFIG.read_text()))
        self.run_task()
        calls = self.cargo_calls()
        self.assertEqual(len(calls), 2)
        self.assertIn("--tag v0.46.0", calls[1])

    def test_other_machines_build_nothing(self):
        for system, machine in (("Linux", "x86_64"), ("Darwin", "arm64")):
            with self.subTest(system, machine=machine):
                r = self.run_task(machine, system)
                self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cargo_calls(), [])

    def test_the_task_is_part_of_bootstrap(self):
        self.assertIn("install-loop-engine-from-source", tomllib.loads(CONFIG.read_text())["tasks"]["bootstrap"]["depends"])


if __name__ == "__main__":
    unittest.main()
