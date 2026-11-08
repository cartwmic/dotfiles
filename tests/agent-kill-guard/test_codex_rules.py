"""Codex's exec policy refuses pkill and killall from dot_codex/rules/agent-guard.rules (checked with Codex's own `execpolicy check`),
and chezmoi deploys the file to ~/.codex/rules on both desktop profiles and not on termux."""
import glob
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "dot_codex/rules/agent-guard.rules"
CODEX = shutil.which("codex") or next(iter(sorted(glob.glob(os.path.expanduser("~/.t3/tools/codex/*/bin/codex")))[::-1]), None)
FORBIDDEN = ["pkill -f x", "killall x", "/usr/bin/pkill -f x", "/usr/bin/killall Dock", "/bin/pkill x", "sudo pkill x", "env pkill x",
             "nohup killall x", "xargs pkill", "command killall x"]
ALLOWED = ["kill 123", "kill -9 123", "kgate cancel abc", "pgrep -f x", "echo pkill", "ls killall", "git commit -m pkill"]
LIMITS = ["sudo -u root pkill x", "env FOO=1 pkill x"]  # named in the file header as not covered


@unittest.skipUnless(CODEX, "needs a codex binary (PATH or ~/.t3/tools/codex)")
class RulesTest(unittest.TestCase):
    def decision(self, argv):
        r = subprocess.run([CODEX, "execpolicy", "check", "--rules", str(RULES), "--", *argv.split()], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout).get("decision")

    def test_forbidden_forms(self):
        for argv in FORBIDDEN:
            with self.subTest(argv=argv):
                self.assertEqual(self.decision(argv), "forbidden")

    def test_everything_else_is_not_matched(self):
        for argv in ALLOWED + LIMITS:
            with self.subTest(argv=argv):
                self.assertIsNone(self.decision(argv))

    def test_the_reason_names_the_alternatives(self):
        r = subprocess.run([CODEX, "execpolicy", "check", "--rules", str(RULES), "--", "pkill", "-f", "x"], capture_output=True, text=True, timeout=60)
        reason = json.loads(r.stdout)["matchedRules"][0]["prefixRuleMatch"]["justification"]
        self.assertIn("exact PID", reason)
        self.assertIn("kgate cancel <id>", reason)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi needed")
class DeployTest(unittest.TestCase):
    def managed(self, profile):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text("data:\n  profile: %s\n" % profile)
            r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home), "managed"],
                               capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return set(r.stdout.split())

    def test_deployed_on_both_desktop_profiles_and_not_on_termux(self):
        for profile, want in (("personal", True), ("axon-work-computer", True), ("termux", False)):
            with self.subTest(profile=profile):
                files = self.managed(profile)
                for path in (".codex/rules/agent-guard.rules", ".local/share/agent-harness/hooks/refuse_pattern_kill.py",
                             ".pi/agent/extensions/refuse-pattern-kill/index.ts"):
                    self.assertEqual(path in files, want, path)


if __name__ == "__main__":
    unittest.main()
