"""The chezmoi step that installs the gh wrapper (run_onchange_after_47_install-leak-guard-gh.sh.tmpl), and a journey through what it installs.

Renders the real template with `chezmoi execute-template` against a throwaway config, then runs the rendered script with a throwaway HOME. The data is
invented ("fooco-dev/guarded" is a pretend guarded repository, "fooco" a pretend employer term).
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_gh_wrapper import CLEAN, FAKE_GH, GUARD, GUARDED, PLANTED, script_copy
from test_leak_guard import FAKE_CLAUDE

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "run_onchange_after_47_install-leak-guard-gh.sh.tmpl"
DATA = '  leakGuard:\n    terms: ["fooco"]\n    context: "Fooco is the pretend employer."\n    repos:\n      - "%s"\n' % GUARDED


def render(tmp, data, profile="axon-work-computer", home=None):
    cfg = tmp / "chezmoi.yaml"
    cfg.write_text("data:\n  profile: %s\n%s" % (profile, data))
    return subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home or tmp / "home"),
                           "execute-template"], input=TEMPLATE.read_text(), capture_output=True, text=True,
                          env=dict(os.environ, HOME=str(home or tmp / "home")), timeout=60)


def run_script(tmp, script, home):
    path = tmp / "script.sh"
    path.write_text(script)
    return subprocess.run(["sh", str(path)], capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=30)


class GhInstaller(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gi-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.home / ".local" / "share" / "leak-guard" / "bin"

    def test_no_leak_guard_data_renders_nothing_and_writes_nothing(self):
        done = render(self.tmp, "")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, ""), done.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_another_profile_renders_nothing_even_with_data(self):
        for profile in ("personal", "termux"):
            with self.subTest(profile):
                done = render(self.tmp, DATA, profile=profile)
                self.assertEqual((done.returncode, done.stdout.strip()), (0, ""), done.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_the_work_profile_with_repos_installs_the_wrapper_the_repos_file_and_the_mise_file(self):
        done = render(self.tmp, DATA)
        self.assertEqual(done.returncode, 0, done.stderr)
        ran = run_script(self.tmp, done.stdout, self.home)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        gh = self.bin / "gh"
        self.assertEqual(gh.read_text(), (ROOT / "scripts/leak-guard-gh").read_text())
        self.assertEqual(stat.S_IMODE(gh.stat().st_mode), 0o755)
        repos = self.home / ".config" / "leak-guard" / "repos"
        self.assertEqual(repos.read_text(), GUARDED + "\n")
        self.assertEqual(stat.S_IMODE(repos.stat().st_mode), 0o600)
        conf = (self.home / ".config" / "mise" / "conf.d" / "leak-guard-gh.toml").read_text()
        self.assertIn("[env]", conf)
        self.assertIn('_.path = ["%s"]' % self.bin, conf)
        self.assertFalse((self.home / ".local" / "bin" / "gh").exists())

    def test_empty_or_missing_repos_install_nothing_and_print_a_notice(self):
        for data in (DATA.replace('    repos:\n      - "%s"\n' % GUARDED, "    repos: []\n"), DATA.replace('    repos:\n      - "%s"\n' % GUARDED, "")):
            with self.subTest(data):
                done = render(self.tmp, data)
                self.assertEqual(done.returncode, 0, done.stderr)
                ran = run_script(self.tmp, done.stdout, self.home)
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertIn("NOTICE: leakGuard.repos is empty or missing", ran.stderr)
                self.assertEqual(list(self.home.iterdir()), [])

    def test_a_gh_that_is_not_ours_at_the_wrapper_path_is_left_alone_with_a_warning(self):
        self.bin.mkdir(parents=True)
        (self.bin / "gh").write_text("#!/bin/sh\necho mine\n")
        done = render(self.tmp, DATA)
        ran = run_script(self.tmp, done.stdout, self.home)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual((self.bin / "gh").read_text(), "#!/bin/sh\necho mine\n")
        self.assertIn("already exists and is not leak-guard's", ran.stderr)
        self.assertIn("NOT installed", ran.stderr)

    def test_a_mise_file_that_is_not_ours_is_left_alone_with_a_warning(self):
        conf = self.home / ".config" / "mise" / "conf.d" / "leak-guard-gh.toml"
        conf.parent.mkdir(parents=True)
        conf.write_text("[env]\nFOO = 'mine'\n")
        ran = run_script(self.tmp, render(self.tmp, DATA).stdout, self.home)
        self.assertEqual(conf.read_text(), "[env]\nFOO = 'mine'\n")
        self.assertIn("already exists and is not leak-guard's", ran.stderr)
        self.assertTrue((self.bin / "gh").exists())

    def test_an_existing_gh_in_the_home_local_bin_is_never_touched(self):
        (self.home / ".local" / "bin").mkdir(parents=True)
        (self.home / ".local" / "bin" / "gh").write_text("#!/bin/sh\necho mine\n")
        run_script(self.tmp, render(self.tmp, DATA).stdout, self.home)
        self.assertEqual((self.home / ".local" / "bin" / "gh").read_text(), "#!/bin/sh\necho mine\n")

    def test_changed_data_rewrites_the_repos_file_and_our_own_wrapper_is_replaced(self):
        for repo in ("fooco-dev/guarded", "fooco-dev/other"):
            run_script(self.tmp, render(self.tmp, DATA.replace(GUARDED, repo)).stdout, self.home)
            self.assertEqual((self.home / ".config" / "leak-guard" / "repos").read_text(), repo + "\n")
        (self.bin / "gh").write_text("# leak-guard gh wrapper (managed by chezmoi; old)\nold\n")
        run_script(self.tmp, render(self.tmp, DATA).stdout, self.home)
        self.assertEqual((self.bin / "gh").read_text(), (ROOT / "scripts/leak-guard-gh").read_text())

    def test_bad_repos_data_fails_the_render(self):
        for bad in ('    repos: "fooco-dev/guarded"\n', "    repos: [1]\n", '    repos: ["noslash"]\n', '    repos: ["a/b/c/d"]\n'):
            with self.subTest(bad):
                done = render(self.tmp, DATA.replace('    repos:\n      - "%s"\n' % GUARDED, bad))
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("leakGuard.repos", done.stderr)


class GhJourney(unittest.TestCase):
    """The installer, then the installed wrapper first on PATH, a fake real gh, a fake claude and the real leak-guard."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gj-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        (self.home / ".config" / "leak-guard").mkdir(parents=True)
        (self.home / ".local" / "bin").mkdir(parents=True)
        self.fake, self.realbin, self.cbin = self.tmp / "fake", self.tmp / "realbin", self.tmp / "cbin"
        for d in (self.fake, self.realbin, self.cbin):
            d.mkdir()
        (self.home / ".config" / "leak-guard" / "terms").write_text("fooco\nbar.*baz\n")
        (self.home / ".config" / "leak-guard" / "context").write_text("Fooco is the pretend employer.\n")
        script_copy(GUARD, self.home / ".local" / "bin" / "leak-guard")
        (self.realbin / "gh").write_text(FAKE_GH)
        (self.realbin / "gh").chmod(0o755)
        (self.cbin / "claude").write_text(FAKE_CLAUDE)
        (self.cbin / "claude").chmod(0o755)
        ran = run_script(self.tmp, render(self.tmp, DATA).stdout, self.home)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.cwd = self.tmp / "work"
        self.cwd.mkdir()
        subprocess.run(["git", "-C", str(self.cwd), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.cwd), "remote", "add", "origin", "git@github.com:%s.git" % GUARDED], check=True)
        self.path = "%s:%s:%s:/usr/bin:/bin" % (self.home / ".local" / "share" / "leak-guard" / "bin", self.realbin, self.cbin)

    def gh(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("LEAK_GUARD_BIN", "LEAK_GUARD_SKIP", "GH_REPO", "XDG_STATE_HOME", "FAKE_CLAUDE")}
        env.update(HOME=str(self.home), FAKE=str(self.fake), PATH=self.path)
        # `gh` is looked up on the PATH, as a person's shell does
        return subprocess.run(["sh", "-c", 'exec gh "$@"', "sh", *args], cwd=str(self.cwd), capture_output=True, text=True, env=env, timeout=60)

    def calls(self):
        path = self.fake / "gh-calls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_a_pr_create_with_a_term_in_the_body_file_is_blocked_and_a_clean_one_runs_the_real_gh(self):
        bad = self.tmp / "bad.md"
        bad.write_text(PLANTED + "\n")
        done = self.gh("pr", "create", "--title", "t", "--body-file", str(bad))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("body:1: term 1", done.stderr)
        self.assertEqual(self.calls(), [])
        ok = self.tmp / "ok.md"
        ok.write_text(CLEAN + "\n")
        done = self.gh("pr", "create", "--draft", "--title", "t", "--body-file", str(ok))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([c["argv"] for c in self.calls()], [["pr", "create", "--draft", "--title", "t", "--body-file", str(ok)]])

    def test_a_pr_comment_with_a_term_is_blocked_and_a_clean_comment_passes(self):
        done = self.gh("pr", "comment", "5", "--body", PLANTED)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self.calls(), [])
        done = self.gh("pr", "comment", "5", "--body", CLEAN)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_the_installed_wrapper_leaves_other_repositories_alone(self):
        subprocess.run(["git", "-C", str(self.cwd), "remote", "set-url", "origin", "git@github.com:someone/other.git"], check=True)
        done = self.gh("pr", "comment", "5", "--body", PLANTED)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.calls()), 1)


if __name__ == "__main__":
    unittest.main()
