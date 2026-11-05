"""The agent-traces wrapper's node handling: the AGENT_TRACES_NODE override, the 22.19 floor (exit 3), no node (exit 3, was 127), and the
--disable-warning flag on the node command line.

The wrapper is rendered by real chezmoi and run under `env -i` (no PATH unless a case gives one) against fake node scripts and a fake kit file,
so nothing here needs the kit or a real node. Needs chezmoi, sh.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FLAG = "--disable-warning=ExperimentalWarning"
# A fake node: `-p` answers with $FAKE_NODE_VERSION (nothing if it is "none"); anything else records who ran and with what.
FAKE_NODE = """#!/bin/sh
if [ "$1" = "-p" ]; then
  [ "${FAKE_NODE_VERSION:-22.19.0}" = none ] && exit 1
  echo "${FAKE_NODE_VERSION:-22.19.0}"
  exit 0
fi
{ echo "$0"; for a in "$@"; do echo "$a"; done; } > "$FAKE_NODE_LOG"
exit 0
"""


class Rig:
    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.empty = self.root / "empty-path"  # a PATH with nothing on it
        self.empty.mkdir()
        self.log = self.root / "node.log"
        config = self.root / "chezmoi.yaml"
        config.write_text("data:\n  profile: personal\n")
        rendered = subprocess.run(
            ["chezmoi", "--source", str(REPO), "--config", str(config), "--config-format", "yaml", "--destination", str(self.home),
             "--no-tty", "execute-template"],
            input=(REPO / "dot_local/bin/executable_agent-traces.tmpl").read_text(), capture_output=True, text=True,
            env=dict(os.environ, HOME=str(self.home)), timeout=120)
        assert rendered.returncode == 0, rendered.stderr
        self.wrapper = self.root / "agent-traces"
        self.wrapper.write_text(rendered.stdout)
        self.kit = self.root / "kit"
        self.cli = self.kit / "node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text("// fake\n")

    def fake_node(self, directory, version=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "node"
        path.write_text(FAKE_NODE)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def run(self, *args, path=None, **env):
        """The wrapper under `env -i`: HOME, the kit and the fake-node log, and a PATH only when asked for."""
        pairs = {"HOME": str(self.home), "AGENT_TRACES_KIT": str(self.kit), "FAKE_NODE_LOG": str(self.log)}
        if path is not None:
            pairs["PATH"] = str(path)
        pairs.update(env)
        return subprocess.run(["/usr/bin/env", "-i", *["%s=%s" % kv for kv in pairs.items()], "/bin/sh", str(self.wrapper), *args],
                              capture_output=True, text=True, timeout=60)

    def ran(self):
        return self.log.read_text().splitlines() if self.log.exists() else None


class WrapperNodeTest(unittest.TestCase):
    def test_the_node_command_line_carries_the_warning_flag_then_the_cli_then_the_arguments(self):
        rig = Rig(self)
        node = rig.fake_node(rig.root / "bin")
        r = rig.run("pi", "status", "--max-age", "0", path=rig.root / "bin")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rig.ran(), [str(node), FLAG, str(rig.cli), "pi", "status", "--max-age", "0"])

    def test_agent_traces_node_beats_node_on_path_and_the_mise_shim(self):
        rig = Rig(self)
        rig.fake_node(rig.root / "on-path")
        rig.fake_node(rig.home / ".local/share/mise/shims")
        chosen = rig.fake_node(rig.root / "chosen")
        r = rig.run("review", "x", path=rig.root / "on-path", AGENT_TRACES_NODE=str(chosen))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rig.ran()[0], str(chosen))

    def test_node_on_path_beats_the_mise_shim_and_the_shim_is_the_fallback_with_no_path(self):
        rig = Rig(self)
        shim = rig.fake_node(rig.home / ".local/share/mise/shims")
        on_path = rig.fake_node(rig.root / "on-path")
        self.assertEqual(rig.run("x", path=rig.root / "on-path").returncode, 0)
        self.assertEqual(rig.ran()[0], str(on_path))
        rig.log.unlink()
        r = rig.run("x", path=rig.empty)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rig.ran()[0], str(shim))

    def test_the_22_19_floor_exits_3_below_it_and_runs_at_and_above_it(self):
        rig = Rig(self)
        node = rig.fake_node(rig.root / "bin")
        for version, ok in (("20.19.9", False), ("21.99.0", False), ("22.0.0", False), ("22.18.9", False), ("22.9.0", False),
                            ("22.19.0", True), ("22.20.1", True), ("22.100.0", True), ("23.0.0", True), ("24.18.1", True), ("100.0.0", True)):
            with self.subTest(version=version):
                if rig.log.exists():
                    rig.log.unlink()
                r = rig.run("x", path=rig.root / "bin", FAKE_NODE_VERSION=version)
                if ok:
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(rig.ran()[0], str(node))
                else:
                    self.assertEqual(r.returncode, 3, r.stderr)
                    self.assertIn("too old", r.stderr)
                    self.assertIn("22.19", r.stderr)
                    self.assertIn(version, r.stderr)
                    self.assertIsNone(rig.ran(), "the CLI must not run below the floor")

    def test_the_floor_also_applies_to_agent_traces_node(self):
        rig = Rig(self)
        old = rig.fake_node(rig.root / "old")
        r = rig.run("x", path=rig.empty, AGENT_TRACES_NODE=str(old), FAKE_NODE_VERSION="22.18.0")
        self.assertEqual(r.returncode, 3)
        self.assertIn(str(old), r.stderr)

    def test_no_node_anywhere_exits_3_not_127(self):
        rig = Rig(self)
        cases = [("empty PATH, no shim", dict(path=rig.empty))]
        # With no PATH at all, /bin/sh searches its own default path. On a host whose default path holds a node (the ubuntu CI
        # runner has one in /usr/local/bin) that node is a real find, not a fault, so this case runs only where the default
        # path has none.
        if subprocess.run(["/usr/bin/env", "-i", "/bin/sh", "-c", "command -v node"], capture_output=True).returncode != 0:
            cases.append(("no PATH at all, no shim", {}))
        for case, kw in cases:
            with self.subTest(case=case):
                r = rig.run("x", **kw)
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertIn("no node found", r.stderr)
                self.assertIn("AGENT_TRACES_NODE", r.stderr)

    def test_agent_traces_node_that_is_not_a_runnable_file_exits_3(self):
        rig = Rig(self)
        rig.fake_node(rig.root / "bin")  # a good node on PATH is not a fallback for a bad override
        r = rig.run("x", path=rig.root / "bin", AGENT_TRACES_NODE=str(rig.root / "missing-node"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("no node found", r.stderr)
        self.assertIsNone(rig.ran())

    def test_a_node_that_gives_no_version_exits_3(self):
        rig = Rig(self)
        rig.fake_node(rig.root / "bin")
        for version in ("none", "v22.19.0", "banana", "22.19"):
            with self.subTest(version=version):
                r = rig.run("x", path=rig.root / "bin", FAKE_NODE_VERSION=version)
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertIn("could not read the node version", r.stderr)
                self.assertIsNone(rig.ran())

    def test_a_missing_kit_still_exits_3_before_node_is_looked_at(self):
        rig = Rig(self)
        rig.cli.unlink()
        rig.fake_node(rig.root / "bin")
        r = rig.run("x", path=rig.root / "bin")
        self.assertEqual(r.returncode, 3)
        self.assertIn("agent-traces:", r.stderr)
        self.assertIsNone(rig.ran())


if __name__ == "__main__":
    unittest.main()
