"""Shared by the Cursor tests: real chezmoi renders the canonical files for a profile, and the real
dot_local/user_scripts/executable_apply_harness_config.sh `cursor` step runs under sh in a scratch HOME with a fake `op`.
The fake op answers every `op read` with a dummy value that names the reference, so no real secret is read."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/shx"))
import test_agent_access as access  # noqa: E402  (the chezmoi helper, with the local data keys the work profile needs)

APPLY = ROOT / "dot_local/user_scripts/executable_apply_harness_config.sh"
HARNESS = ROOT / "dot_local/share/agent-harness"
CANONICAL = HARNESS / "canonical/mcp/servers.json.tmpl"
EXCLUDE = HARNESS / "canonical/mcp/cursor-exclude.txt"
CLAUDE_ADAPTER = HARNESS / "adapters/claude/mcp-secrets.json.tmpl"
SKILLS = HARNESS / "canonical/skills"
PROFILES = ("personal", "axon-work-computer")
FAKE_OP = '''#!/bin/sh
echo "$*" >> "$FAKE_CALLS"
[ "$1" = read ] || exit 1
printf 'https://secret.example.test/%s' "$(printf %s "$2" | tr -c 'A-Za-z0-9' '-')"
'''


def dummy(ref):
    """What the fake op answers for a reference."""
    return "https://secret.example.test/" + "".join(c if c.isalnum() else "-" for c in ref)


def canonical_servers(profile):
    return access.servers(profile)


def exclusions(path=EXCLUDE):
    names = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line)
    return names


def canonical_skills():
    return sorted(d.name for d in SKILLS.iterdir() if (d / "SKILL.md").is_file())


class Apply:
    """A scratch HOME and canonical/adapter roots rendered for `profile`. `script` and `exclude` can be replaced."""

    def __init__(self, test, profile, token=True, op=True, exclude=None, script=APPLY):
        self.script = script
        self.tmp = Path(tempfile.mkdtemp(prefix="cursor-apply-")).resolve()
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        (self.home / ".cursor").mkdir(parents=True)
        mcp = self.tmp / "canonical/mcp"
        mcp.mkdir(parents=True)
        (mcp / "servers.json").write_text(access.chezmoi(profile, "execute-template", stdin=CANONICAL.read_text()))
        (mcp / "cursor-exclude.txt").write_text(EXCLUDE.read_text() if exclude is None else exclude)
        (self.tmp / "canonical/skills").mkdir()
        for d in SKILLS.iterdir():  # one link per skill: the apply script's find does not enter a symlinked skills folder
            (self.tmp / "canonical/skills" / d.name).symlink_to(d)
        adapter = self.tmp / "adapters/claude"
        adapter.mkdir(parents=True)
        (adapter / "mcp-secrets.json").write_text(access.chezmoi(profile, "execute-template", stdin=CLAUDE_ADAPTER.read_text()))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        if op:
            (self.bin / "op").write_text(FAKE_OP)
            (self.bin / "op").chmod(0o755)
        self.calls = self.tmp / "op-calls"
        self.env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "FAKE_CALLS": str(self.calls),
                    "AGENT_HARNESS_CANONICAL_ROOT": str(self.tmp / "canonical"), "AGENT_HARNESS_ADAPTERS_ROOT": str(self.tmp / "adapters"),
                    "AGENT_HARNESS_GENERATED_ROOT": str(self.tmp / "generated"),
                    "AGENT_HARNESS_EXTERNAL_ROOT": str(self.tmp / "no-external-skills")}
        if token:
            self.env["OP_SERVICE_ACCOUNT_TOKEN"] = "ops_fake-token-for-tests-only"
        self.mcp = self.home / ".cursor/mcp.json"

    def run(self, harness="cursor"):
        r = subprocess.run(["sh", str(self.script), harness], env=self.env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        return r

    def servers(self):
        return json.loads(self.mcp.read_text())["mcpServers"] if self.mcp.exists() else {}
