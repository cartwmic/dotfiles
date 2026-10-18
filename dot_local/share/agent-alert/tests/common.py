"""Shared helpers for the agent-alert black-box tests.

The tests never run the CLI from the source tree. `deployed_copy()` asks
chezmoi (preview only, never apply) for an archive of the destination
~/.local/share/agent-alert, extracts it into a scratch directory and returns
that copy, so the tests run the same file a deployment would install.
Every run of the CLI uses a scratch HOME, inbox, log and config path.
"""

import atexit
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
TOOL_SOURCE_DIR = TESTS_DIR.parent
REPO_ROOT = TOOL_SOURCE_DIR.parents[2]
DESTINATION_RELATIVE = ".local/share/agent-alert"

_deployed_cache = {}


def deployed_copy(delete_adapters=True):
    """Extract chezmoi's archive of the destination into a scratch directory.

    Returns the path of the extracted agent-alert directory. With
    delete_adapters (the default) the adapters/ and examples/ directories are
    removed from the copy, which proves the core works without them. The
    extraction is reused for the life of the process.
    """
    key = bool(delete_adapters)
    if key in _deployed_cache:
        return _deployed_cache[key]
    scratch = Path(tempfile.mkdtemp(prefix="agent-alert-deployed-"))
    atexit.register(shutil.rmtree, scratch, ignore_errors=True)
    destination = Path.home() / DESTINATION_RELATIVE
    # chezmoi needs the real HOME for its configuration; archive never writes to it.
    archive = subprocess.run(
        ["chezmoi", "--source", str(REPO_ROOT), "archive", "--format", "tar", str(destination)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if archive.returncode != 0:
        raise RuntimeError("chezmoi archive failed: " + archive.stderr.decode("utf-8", "replace"))
    tar_path = scratch / "deployed.tar"
    tar_path.write_bytes(archive.stdout)
    with tarfile.open(tar_path) as tar:
        tar.extractall(scratch / "extracted")
    copy = scratch / "extracted" / DESTINATION_RELATIVE
    if not (copy / "core" / "agent-alert").is_file():
        raise RuntimeError("archive has no core/agent-alert under " + DESTINATION_RELATIVE)
    if delete_adapters:
        for name in ("adapters", "examples"):
            shutil.rmtree(copy / name, ignore_errors=True)
    _deployed_cache[key] = copy
    return copy


class Scratch:
    """A scratch HOME with an inbox, log and config path, and a way to run the CLI."""

    def __init__(self, cli=None):
        self.root = Path(tempfile.mkdtemp(prefix="agent-alert-test-"))
        self.home = self.root / "home"
        self.home.mkdir()
        self.inbox = self.root / "inbox" / "inbox.jsonl"
        self.log = self.root / "state" / "agent-alert.log"
        self.config = self.root / "config.json"
        self.cli = Path(cli) if cli else deployed_copy() / "core" / "agent-alert"

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write_config(self, **values):
        self.config.write_text(json.dumps(values))

    def env(self, **extra):
        environment = {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "AGENT_ALERT_INBOX": str(self.inbox),
            "AGENT_ALERT_LOG": str(self.log),
            "AGENT_ALERT_CONFIG": str(self.config),
        }
        environment.update(extra)
        return environment

    def run(self, *args, stdin=None, timeout=60, env=None, wrapper=None):
        """Run the real CLI. wrapper is a shell prefix such as 'ulimit -f 1;'."""
        command = [str(self.cli)] + [str(a) for a in args]
        if wrapper:
            command = ["sh", "-c", wrapper + ' exec "$@"', "sh"] + command
        return subprocess.run(
            command,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env if env is not None else self.env(),
            timeout=timeout,
            text=True,
            encoding="utf-8",
        )

    def emit(self, worker="w1", kind="finished", summary=None, **options):
        args = ["emit", "--worker", worker, "--kind", kind]
        if summary is not None:
            args += ["--summary", summary]
        return self.run(*args, **options)

    def inbox_bytes(self):
        try:
            return self.inbox.read_bytes()
        except FileNotFoundError:
            return b""

    def events(self):
        """Every line of the inbox, which must all parse; returns the decoded objects."""
        decoded = []
        data = self.inbox_bytes()
        if data:
            assert data.endswith(b"\n"), "inbox does not end in a newline"
        for line in data.splitlines():
            decoded.append(json.loads(line.decode("utf-8")))
        return decoded

    def log_text(self):
        try:
            return self.log.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
