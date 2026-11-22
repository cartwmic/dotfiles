"""The mise bootstrap script gives every mise call a GitHub token when none is set.

mise reads GITHUB_TOKEN and ignores GH_TOKEN, so an unauthenticated mise call (the setup task, `mise install`, the bootstrap task) can hit GitHub's 60-an-hour limit. The real script is
rendered with chezmoi (both profiles) and run with a fake mise and gh first on PATH in a throwaway HOME. The fake mise logs the GITHUB_TOKEN
each call sees; the fake gh answers `auth token`. Run: python3 -m unittest discover -s tests/mise
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "run_onchange_after_10_mise_bootstrap.sh.tmpl"

FAKE_MISE = """#!/bin/sh
case "$1" in
  --version) echo "2026.12.0 linux-x64 (2026-12-01)" ;;
  *) echo "mise $* GITHUB_TOKEN=${GITHUB_TOKEN-<unset>}" >> "$FAKE_LOG" ;;
esac
"""
FAKE_GH = """#!/bin/sh
echo "gh $*" >> "$FAKE_LOG"
[ "$1 $2" = "auth token" ] && [ -n "$FAKE_GH_TOKEN" ] && { echo "$FAKE_GH_TOKEN"; exit 0; }
exit 1
"""


class MiseGithubTokenTest(unittest.TestCase):
    def run_script(self, profile="personal", *, gh=True, env_extra=None, with_stderr=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, bin_dir = root / "home", root / "bin"
            home.mkdir()
            bin_dir.mkdir()
            cfg = root / "chezmoi.yaml"
            cfg.write_text("data:\n  profile: %s\n" % profile)
            rendered = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                                       "execute-template"], input=SCRIPT.read_text(), capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), check=True).stdout
            script = root / "script.sh"
            script.write_text(rendered)
            for name, text in (("mise", FAKE_MISE),) + ((("gh", FAKE_GH),) if gh else ()):
                (bin_dir / name).write_text(text)
                (bin_dir / name).chmod(0o755)
            log = root / "calls.log"
            log.write_text("")
            env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
            env.update(HOME=str(home), PATH="%s:/usr/bin:/bin" % bin_dir, FAKE_LOG=str(log), FAKE_GH_TOKEN="gh-secret")
            env.update(env_extra or {})
            r = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            for secret in ("gh-secret", "env-gh-secret", "env-github-secret"):
                self.assertNotIn(secret, r.stdout + r.stderr)
            seen = {line.split(" GITHUB_TOKEN=")[0]: line.split(" GITHUB_TOKEN=")[1] for line in log.read_text().splitlines() if " GITHUB_TOKEN=" in line}
            return (seen, log.read_text(), r.stderr) if with_stderr else (seen, log.read_text())

    def test_gh_token_reaches_every_mise_call_when_nothing_is_set(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                seen, _ = self.run_script(profile)
                self.assertEqual(seen["mise run setup-ubuntu-essentials"], "gh-secret")
                self.assertEqual(seen["mise install"], "gh-secret")
                self.assertEqual(seen["mise run bootstrap"], "gh-secret")
                self.assertEqual(set(seen.values()), {"gh-secret"})

    def test_gh_token_env_var_is_used_without_asking_gh(self):
        seen, log = self.run_script(env_extra={"GH_TOKEN": "env-gh-secret"})
        self.assertEqual(set(seen.values()), {"env-gh-secret"})
        self.assertNotIn("gh auth token", log)

    def test_an_existing_github_token_is_left_alone(self):
        seen, log = self.run_script(env_extra={"GITHUB_TOKEN": "env-github-secret", "GH_TOKEN": "env-gh-secret"})
        self.assertEqual(set(seen.values()), {"env-github-secret"})
        self.assertNotIn("gh auth token", log)

    def test_without_gh_or_a_token_every_mise_call_runs_unauthenticated(self):
        seen, _ = self.run_script(gh=False)
        self.assertEqual(set(seen.values()), {"<unset>"})

    def test_no_token_prints_one_warning_naming_gh_token(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                _, _, stderr = self.run_script(profile, gh=False, with_stderr=True)
                warnings = [l for l in stderr.splitlines() if "no GitHub token found" in l]
                self.assertEqual(len(warnings), 1, stderr)
                self.assertIn("GH_TOKEN", warnings[0])
                self.assertIn("60 GitHub calls an hour", warnings[0])

    def test_a_token_means_no_warning(self):
        for extra in ({"GH_TOKEN": "env-gh-secret"}, {"GITHUB_TOKEN": "env-github-secret"}, {}):
            with self.subTest(extra=sorted(extra)):
                _, _, stderr = self.run_script(env_extra=extra, with_stderr=True)
                self.assertNotIn("no GitHub token found", stderr)

    def test_gh_signed_out_does_not_fail_the_script(self):
        seen, _ = self.run_script(env_extra={"FAKE_GH_TOKEN": ""})
        self.assertEqual(set(seen.values()), {"<unset>"})


if __name__ == "__main__":
    unittest.main()
