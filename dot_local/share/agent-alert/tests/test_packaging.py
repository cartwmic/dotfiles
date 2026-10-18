"""Packaging and layering checks for the agent-alert tree.

Run (from the repository root):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
        -s dot_local/share/agent-alert/tests -p 'test_packaging.py'

* Layering: core/ contains none of the words Herdr, Pi, Claude, tmux, zellij, and
  its tests and the worked source example pass on a copy of the deployed tree
  whose adapters/ directory was deleted.
* Containment: nothing in the deployable files reaches a path outside this
  directory, apart from the documented per-user locations of the inbox, the
  config, the operator log and the Herdr plugin link.
* Deployment: chezmoi previews (never `apply` without `--dry-run`, never a real
  apply) show that the files map to ~/.local/share/agent-alert, that tests/ is
  not deployed, that the adapter READMEs are gone, and that the termux profile
  does not receive the tree.

Before running chezmoi the test reads the effective chezmoi config for
`hooks.read-source-state.pre` and proceeds only when that hook is the known
password-manager helper and `op` is already installed, which makes it a no-op.
"""

import os
import re
import shutil
import subprocess
import sys
import tarfile
import io
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

TOOL = common.TOOL_SOURCE_DIR
REPO = common.REPO_ROOT
DESTINATION = Path.home() / common.DESTINATION_RELATIVE
IGNORE_LINE = ".local/share/agent-alert/tests/**"

CORE_FORBIDDEN_WORDS = ("Herdr", "Pi", "Claude", "tmux", "zellij")


def deployable_files():
    """Every source file that chezmoi deploys: everything except tests/ and bytecode."""
    found = []
    for path in sorted(TOOL.rglob("*")):
        relative = path.relative_to(TOOL)
        if not path.is_file() or relative.parts[0] == "tests" or "__pycache__" in relative.parts:
            continue
        found.append(path)
    return found


def chezmoi_config_hook():
    """The command of hooks.read-source-state.pre in the effective chezmoi config, or None."""
    for name in ("chezmoi.yaml", "chezmoi.toml", "chezmoi.json"):
        config = Path.home() / ".config" / "chezmoi" / name
        if config.is_file():
            text = config.read_text(encoding="utf-8")
            match = re.search(r"read-source-state:\s*\n\s*pre:\s*\n\s*command:\s*[\"']?([^\"'\n]+)", text)
            if match:
                return match.group(1).strip()
            if "read-source-state" in text:
                return "unrecognised"
    return None


def run_chezmoi(*args, **options):
    return subprocess.run(
        ["chezmoi", "--source", str(REPO)] + [str(a) for a in args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        text=True,
        encoding="utf-8",
        **options,
    )


class LayeringTests(unittest.TestCase):
    def test_core_names_none_of_the_five_adapter_words(self):
        core_files = [p for p in deployable_files() if p.relative_to(TOOL).parts[0] == "core"]
        self.assertTrue(core_files)
        for path in core_files:
            text = path.read_text(encoding="utf-8")
            for word in CORE_FORBIDDEN_WORDS:
                self.assertIsNone(re.search(r"\b%s\b" % word, text, re.I), "%s mentions %s" % (path.relative_to(TOOL), word))
        grep = subprocess.run(["grep", "-rniwE", "|".join(CORE_FORBIDDEN_WORDS), str(TOOL / "core")], stdout=subprocess.PIPE, text=True)
        self.assertEqual((grep.returncode, grep.stdout), (1, ""))  # grep exits 1 for "no match"

    def test_core_tests_and_the_worked_source_example_pass_on_a_copy_without_adapters(self):
        copy = Path(tempfile.mkdtemp(prefix="agent-alert-noadapters-"))
        self.addCleanup(shutil.rmtree, copy, ignore_errors=True)
        shutil.copytree(common.deployed_copy(delete_adapters=False), copy / "tree", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        tree = copy / "tree"
        shutil.rmtree(tree / "adapters")
        self.assertTrue((tree / "core" / "agent-alert").is_file())
        self.assertTrue((tree / "examples" / "source-example.py").is_file())
        self.assertFalse((tree / "adapters").exists())
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(TOOL / "tests"), "-p", "test_core.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
            timeout=600,
            text=True,
            encoding="utf-8",
        )
        summary = result.stdout.strip().splitlines()[-3:]
        print("core tests on a deployed copy without adapters/:", " | ".join(summary))
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
        self.assertIn("OK", summary[-1])
        # and the copy really runs the worked source example: an event goes in and comes out
        scratch = common.Scratch(cli=tree / "core" / "agent-alert")
        self.addCleanup(scratch.cleanup)
        example = subprocess.run(
            [sys.executable, str(tree / "examples" / "source-example.py")],
            input="standalone-pane idle\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=scratch.env(),
            timeout=60,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual((example.returncode, example.stderr), (0, ""))
        self.assertEqual([(e["worker"], e["kind"]) for e in scratch.events()], [("standalone-pane", "finished")])
        self.assertIn('"worker":"standalone-pane"', scratch.run("tail", "--since", "0").stdout)


class ContainmentTests(unittest.TestCase):
    ALLOWED_HOME_PATHS = (
        "~/.local/share/agent-alert",
        "~/.config/agent-alert",
        "~/.local/state/agent-alert",
        "~/.local/share/coordinator",
        "$HOME/.local/share/agent-alert",
        "$HOME/.local/share/coordinator",
    )
    ALLOWED_ABSOLUTE_PATHS = ("/dev/null", "/tmp", "/usr/bin/env")

    def test_no_deployable_file_names_a_path_outside_the_directory(self):
        home_tokens = re.compile(r"(?:~|\$HOME|\$\{HOME\})/[A-Za-z0-9_.\-/]*")
        absolute_tokens = re.compile(r"(?:^|[\s\"'(=`])(/[A-Za-z][A-Za-z0-9_.\-]*(?:/[A-Za-z0-9_.\-]*)*)")
        offenders = []
        files = deployable_files()
        self.assertGreaterEqual(len(files), 8)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in home_tokens.findall(text):
                if not token.startswith(self.ALLOWED_HOME_PATHS):
                    offenders.append((str(path.relative_to(TOOL)), token))
            for token in absolute_tokens.findall(text):
                if not any(token == a or token.startswith(a + "/") for a in self.ALLOWED_ABSOLUTE_PATHS):
                    offenders.append((str(path.relative_to(TOOL)), token))
            for literal in ("/Users/", "/Volumes/", "/home/", "/opt/homebrew", "~/.config/herdr", "~/.pi", "~/.claude"):
                if literal in text:
                    offenders.append((str(path.relative_to(TOOL)), literal))
        self.assertEqual(offenders, [])

    def test_the_tree_has_one_readme_and_no_file_with_live_in_its_name(self):
        files = [p.relative_to(TOOL) for p in TOOL.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        self.assertEqual([str(p) for p in files if p.name == "README.md"], ["README.md"])
        self.assertEqual([str(p) for p in files if "live" in p.name.lower()], [])

    def test_adapters_reach_the_core_only_through_their_own_location(self):
        for path in deployable_files():
            if path.suffix != ".py" or path.relative_to(TOOL).parts[0] == "core":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(str(REPO), text)
            self.assertNotIn(str(Path.home()), text)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class ChezmoiPreviewTests(unittest.TestCase):
    """Preview-only: archive, managed, source-path and a targeted dry run."""

    @classmethod
    def setUpClass(cls):
        hook = chezmoi_config_hook()
        if hook is not None and ".install-password-manager.sh" not in hook:
            raise unittest.SkipTest("unrecognised hooks.read-source-state.pre in the chezmoi config: ask the owner before running chezmoi")
        if hook is not None and shutil.which("op") is None:
            raise unittest.SkipTest("the read-source-state hook would install op: ask the owner before running chezmoi")
        cls.hook = hook

    def test_the_config_hook_is_a_noop_because_op_is_installed(self):
        if self.hook is None:
            self.skipTest("no read-source-state hook is configured")
        self.assertIsNotNone(shutil.which("op"))
        print("chezmoi hooks.read-source-state.pre:", self.hook, "-> exits at `command -v op` (op is installed: %s)" % shutil.which("op"))

    def test_ignore_line_is_present(self):
        lines = (REPO / ".chezmoiignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(IGNORE_LINE, lines)

    def test_managed_and_source_path_for_the_new_files_and_tests_are_not_deployed(self):
        managed = run_chezmoi("managed")
        self.assertEqual(managed.returncode, 0, managed.stderr)
        mine = [line for line in managed.stdout.splitlines() if line.startswith(common.DESTINATION_RELATIVE)]
        print("chezmoi --source <worktree> managed | grep agent-alert:\n  " + "\n  ".join(mine))
        expected = [
            "README.md",
            "SPEC.md",
            "core/agent-alert",
            "examples/source-example.py",
            "examples/consumer-example.py",
            "adapters/herdr/hook.py",
            "adapters/herdr/herdr-plugin.toml",
            "adapters/claude-doorbell/doorbell.py",
        ]
        for name in expected:
            self.assertIn(common.DESTINATION_RELATIVE + "/" + name, mine)
        self.assertEqual([line for line in mine if line.endswith("README.md")], [common.DESTINATION_RELATIVE + "/README.md"])
        self.assertEqual([line for line in mine if "/tests" in line], [])
        self.assertEqual([line for line in mine if "__pycache__" in line], [])
        for name in ("README.md", "core/agent-alert", "examples/source-example.py", "adapters/claude-doorbell/doorbell.py"):
            source_path = run_chezmoi("source-path", DESTINATION / name)
            self.assertEqual(source_path.returncode, 0, source_path.stderr)
            print("source-path %s ->\n  %s" % ("~/" + common.DESTINATION_RELATIVE + "/" + name, source_path.stdout.strip()))
            self.assertTrue(Path(source_path.stdout.strip()).is_file())
        tests_path = run_chezmoi("source-path", DESTINATION / "tests" / "test_docs.py")
        print("source-path for tests/test_docs.py -> rc=%d %s" % (tests_path.returncode, tests_path.stderr.strip()))
        self.assertNotEqual(tests_path.returncode, 0)  # an ignored file is not managed

    def test_archive_has_no_tests_and_marks_the_programs_executable(self):
        archive = subprocess.run(
            ["chezmoi", "--source", str(REPO), "archive", "--format", "tar", str(DESTINATION)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )
        self.assertEqual(archive.returncode, 0, archive.stderr.decode("utf-8", "replace"))
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            modes = {m.name: m.mode & 0o111 for m in tar.getmembers() if m.isfile()}
        self.assertTrue(modes)
        names = " ".join(modes)
        self.assertNotIn("/tests/", names)
        self.assertNotIn("__pycache__", names)
        prefix = common.DESTINATION_RELATIVE + "/"
        self.assertTrue(modes[prefix + "core/agent-alert"])
        self.assertTrue(modes[prefix + "adapters/claude-doorbell/doorbell.py"])
        self.assertFalse(modes[prefix + "README.md"])

    def test_targeted_dry_run_only_creates_the_tree_and_changes_nothing(self):
        before = DESTINATION.exists()
        result = run_chezmoi("apply", "--dry-run", "--verbose", DESTINATION)
        self.assertEqual(result.returncode, 0, result.stderr)
        files = re.findall(r"^diff --git a/(\S+) b/", result.stdout, re.M)
        print("apply --dry-run --verbose ~/.local/share/agent-alert would create %d entries" % len(files))
        self.assertTrue(any(f.endswith("core/agent-alert") for f in files))
        self.assertEqual([f for f in files if "/tests" in f], [])
        self.assertEqual(DESTINATION.exists(), before)

    def test_termux_profile_does_not_deploy_the_tree(self):
        managed = run_chezmoi("--override-data", '{"profile":"termux"}', "managed")
        self.assertEqual(managed.returncode, 0, managed.stderr)
        shared = [line for line in managed.stdout.splitlines() if line.startswith(".local/share")]
        print("termux profile: chezmoi managed | grep '^.local/share':\n  " + "\n  ".join(shared))
        self.assertEqual([line for line in shared if "agent-alert" in line], [])
        source_path = run_chezmoi("--override-data", '{"profile":"termux"}', "source-path", DESTINATION / "README.md")
        print("termux profile: source-path ~/.local/share/agent-alert/README.md -> rc=%d %s" % (source_path.returncode, source_path.stderr.strip()))
        self.assertNotEqual(source_path.returncode, 0)


if __name__ == "__main__":
    unittest.main()
