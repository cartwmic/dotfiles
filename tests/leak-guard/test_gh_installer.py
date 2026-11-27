"""The chezmoi step that installs the gh wrapper on every desktop profile (run_onchange_after_47_install-gh-wrapper.sh.tmpl), and a journey through what it installs.

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

from test_gh_wrapper import CLEAN, FAKE_GH, GUARD, GUARDED, LIB, PLANTED, script_copy
from test_leak_guard import FAKE_CLAUDE

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "run_onchange_after_47_install-gh-wrapper.sh.tmpl"
OLD_MARK = "# leak-guard gh wrapper (managed by chezmoi; old)\n"
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


LIB_FILES = sorted(p.name for p in LIB.glob("*.py"))


class GhInstaller(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gi-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.base = self.home / ".local" / "share" / "gh-wrapper"
        self.bin = self.base / "bin"
        self.conf = self.home / ".config" / "mise" / "conf.d" / "gh-wrapper.toml"

    def install(self, data="", profile="personal"):
        done = render(self.tmp, data, profile=profile)
        self.assertEqual(done.returncode, 0, done.stderr)
        ran = run_script(self.tmp, done.stdout, self.home)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return ran

    def budget(self):
        return (self.home / ".config" / "gh-wrapper" / "budget").read_text()

    def test_every_desktop_profile_installs_the_wrapper_the_lib_and_the_mise_file(self):
        for profile, data in (("personal", ""), ("axon-work-computer", ""), ("axon-work-computer", DATA)):
            with self.subTest(profile=profile, data=bool(data)):
                shutil.rmtree(self.home)
                self.home.mkdir()
                self.install(data, profile)
                gh = self.bin / "gh"
                self.assertEqual(gh.read_text(), (ROOT / "scripts/gh-wrapper").read_text())
                self.assertEqual(stat.S_IMODE(gh.stat().st_mode), 0o755)
                self.assertEqual(sorted(p.name for p in (self.base / "lib").iterdir()), LIB_FILES)
                for name in LIB_FILES:
                    self.assertEqual((self.base / "lib" / name).read_text(), (LIB / name).read_text())
                conf = self.conf.read_text()
                self.assertIn("[env]", conf)
                self.assertIn('_.path = ["%s"]' % self.bin, conf)
                self.assertFalse((self.home / ".local" / "bin" / "gh").exists())
        self.assertIn("gh_classify.py", LIB_FILES)

    def test_termux_gets_nothing(self):
        done = render(self.tmp, "", profile="termux")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, ""), done.stderr)

    def test_the_budget_file_is_on_for_personal_off_for_work_and_the_data_overrides_it(self):
        for profile, data, want in (("personal", "", "on"), ("axon-work-computer", "", "off"), ("personal", "  ghBudget:\n    enabled: false\n", "off"),
                                    ("axon-work-computer", "  ghBudget:\n    enabled: true\n", "on")):
            with self.subTest(profile=profile, data=data):
                self.install(data, profile)
                self.assertEqual(self.budget(), want + "\n")

    def test_the_policy_file_is_on_for_personal_and_off_for_work_whatever_the_budget_data_says(self):
        for profile, data, want in (("personal", "", "on"), ("axon-work-computer", "", "off"), ("personal", "  ghBudget:\n    enabled: false\n", "on"),
                                    ("axon-work-computer", "  ghBudget:\n    enabled: true\n", "off")):
            with self.subTest(profile=profile, data=data):
                self.install(data, profile)
                self.assertEqual((self.home / ".config" / "gh-wrapper" / "policy").read_text(), want + "\n")

    def test_bad_budget_data_fails_the_render(self):
        for bad in ("  ghBudget: true\n", "  ghBudget:\n    enabled: yes please\n", "  ghBudget:\n    enabled: 1\n", "  ghBudget:\n    floor: 600\n"):
            with self.subTest(bad):
                done = render(self.tmp, bad)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("ghBudget", done.stderr)

    def test_the_repos_file_is_written_on_the_work_profile_only_and_with_repos(self):
        self.install(DATA, "axon-work-computer")
        repos = self.home / ".config" / "leak-guard" / "repos"
        self.assertEqual(repos.read_text(), GUARDED + "\n")
        self.assertEqual(stat.S_IMODE(repos.stat().st_mode), 0o600)
        shutil.rmtree(self.home)
        self.home.mkdir()
        self.install(DATA, "personal")      # the leakGuard data is the work profile's: another profile ignores it
        self.assertFalse((self.home / ".config" / "leak-guard").exists())

    def test_empty_or_missing_repos_still_install_the_wrapper_and_print_a_notice_on_the_work_profile(self):
        for data in (DATA.replace('    repos:\n      - "%s"\n' % GUARDED, "    repos: []\n"), DATA.replace('    repos:\n      - "%s"\n' % GUARDED, "")):
            with self.subTest(data):
                ran = self.install(data, "axon-work-computer")
                self.assertIn("NOTICE: leakGuard.repos is empty or missing", ran.stderr)
                self.assertTrue((self.bin / "gh").exists())
                self.assertFalse((self.home / ".config" / "leak-guard").exists())
        shutil.rmtree(self.home)
        self.home.mkdir()
        self.assertEqual(self.install("", "axon-work-computer").stderr, "")      # no leakGuard data at all: nothing to say

    def test_a_gh_that_is_not_ours_at_the_wrapper_path_is_left_alone_with_a_warning(self):
        self.bin.mkdir(parents=True)
        (self.bin / "gh").write_text("#!/bin/sh\necho mine\n")
        ran = self.install()
        self.assertEqual((self.bin / "gh").read_text(), "#!/bin/sh\necho mine\n")
        self.assertIn("already exists and is not the gh wrapper's", ran.stderr)
        self.assertIn("NOT installed", ran.stderr)

    def test_a_mise_file_that_is_not_ours_is_left_alone_with_a_warning(self):
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text("[env]\nFOO = 'mine'\n")
        ran = self.install()
        self.assertEqual(self.conf.read_text(), "[env]\nFOO = 'mine'\n")
        self.assertIn("already exists and is not the gh wrapper's", ran.stderr)
        self.assertTrue((self.bin / "gh").exists())

    def test_an_existing_gh_in_the_home_local_bin_is_never_touched(self):
        (self.home / ".local" / "bin").mkdir(parents=True)
        (self.home / ".local" / "bin" / "gh").write_text("#!/bin/sh\necho mine\n")
        self.install()
        self.assertEqual((self.home / ".local" / "bin" / "gh").read_text(), "#!/bin/sh\necho mine\n")

    def test_changed_data_rewrites_the_repos_file_and_our_own_wrapper_and_lib_are_replaced(self):
        for repo in ("fooco-dev/guarded", "fooco-dev/other"):
            self.install(DATA.replace(GUARDED, repo), "axon-work-computer")
            self.assertEqual((self.home / ".config" / "leak-guard" / "repos").read_text(), repo + "\n")
        (self.bin / "gh").write_text("# gh wrapper (managed by chezmoi; old)\nold\n")
        (self.base / "lib" / "gh_classify.py").write_text("old\n")
        (self.base / "lib" / "gh_gone.py").write_text("a layer this version no longer ships\n")
        self.install(DATA, "axon-work-computer")
        self.assertEqual((self.bin / "gh").read_text(), (ROOT / "scripts/gh-wrapper").read_text())
        self.assertEqual(sorted(p.name for p in (self.base / "lib").iterdir()), LIB_FILES)
        self.assertEqual((self.base / "lib" / "gh_classify.py").read_text(), (LIB / "gh_classify.py").read_text())

    def test_the_old_leak_guard_install_is_removed_when_it_carries_the_old_mark(self):
        old = self.home / ".local" / "share" / "leak-guard" / "bin"
        oldconf = self.home / ".config" / "mise" / "conf.d" / "leak-guard-gh.toml"
        old.mkdir(parents=True)
        (old / "gh").write_text("#!/usr/bin/env python3\n# leak-guard gh wrapper (managed by chezmoi; run_onchange_after_47_install-leak-guard-gh).\n")
        oldconf.parent.mkdir(parents=True)
        oldconf.write_text("# leak-guard gh wrapper (managed by chezmoi; run_onchange_after_47_install-leak-guard-gh)\n[env]\n_.path = [\"x\"]\n")
        self.install(DATA, "axon-work-computer")
        self.assertFalse((self.home / ".local" / "share" / "leak-guard").exists())
        self.assertFalse(oldconf.exists())
        self.assertTrue((self.bin / "gh").exists())

    def test_an_old_path_file_without_the_old_mark_is_left_alone(self):
        old = self.home / ".local" / "share" / "leak-guard" / "bin"
        old.mkdir(parents=True)
        (old / "gh").write_text("#!/bin/sh\necho mine\n")
        self.install(DATA, "axon-work-computer")
        self.assertEqual((old / "gh").read_text(), "#!/bin/sh\necho mine\n")

    def test_the_old_install_stays_when_the_new_wrapper_could_not_be_installed(self):
        old = self.home / ".local" / "share" / "leak-guard" / "bin"
        old.mkdir(parents=True)
        (old / "gh").write_text("# leak-guard gh wrapper (managed by chezmoi; old)\n")
        self.bin.mkdir(parents=True)
        (self.bin / "gh").write_text("#!/bin/sh\necho mine\n")
        self.install(DATA, "axon-work-computer")
        self.assertTrue((old / "gh").exists())

    def test_bad_repos_data_fails_the_render(self):
        for bad in ('    repos: "fooco-dev/guarded"\n', "    repos: [1]\n", '    repos: ["noslash"]\n', '    repos: ["a/b/c/d"]\n'):
            with self.subTest(bad):
                done = render(self.tmp, DATA.replace('    repos:\n      - "%s"\n' % GUARDED, bad), profile="axon-work-computer")
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
        self.path = "%s:%s:%s:/usr/bin:/bin" % (self.home / ".local" / "share" / "gh-wrapper" / "bin", self.realbin, self.cbin)

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
