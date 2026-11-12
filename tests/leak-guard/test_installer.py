"""The chezmoi step that installs leak-guard's hooks and files (run_onchange_after_46_install-leak-guard-hooks.sh.tmpl).

Renders the real template with `chezmoi execute-template` against a throwaway config whose source dir is a throwaway git repo, then runs the rendered
script with a throwaway HOME. The data is invented ("fooco" is a pretend employer).
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "run_onchange_after_46_install-leak-guard-hooks.sh.tmpl"
DATA = '  leakGuard:\n    terms:\n      - "fooco"\n      - "bar.*baz"\n    context: |\n      Fooco is the pretend employer.\n      A work detail is anything naming it.\n'


class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="li-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.src = self.tmp / "src"
        self.src.mkdir()
        subprocess.run(["git", "-C", str(self.src), "init", "-q"], check=True)

    def render(self, data, profile="axon-work-computer"):
        cfg = self.tmp / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n%s" % (profile, data))
        return subprocess.run(["chezmoi", "--source", str(self.src), "--config", str(cfg), "--config-format", "yaml", "--destination", str(self.home),
                               "execute-template"], input=TEMPLATE.read_text(), capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=60)

    def run_script(self, script):
        path = self.tmp / "script.sh"
        path.write_text(script)
        return subprocess.run(["sh", str(path)], capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=30)

    def hooks(self):
        return self.src / ".git" / "hooks"

    def test_no_leak_guard_data_renders_nothing_and_writes_nothing(self):
        done = self.render("")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, ""), done.stderr)
        self.assertFalse((self.hooks() / "pre-commit").exists())
        self.assertFalse((self.home / ".config").exists())

    def test_another_profile_renders_nothing_even_with_data(self):
        for profile in ("personal", "termux"):
            with self.subTest(profile):
                done = self.render(DATA, profile=profile)
                self.assertEqual((done.returncode, done.stdout.strip()), (0, ""), done.stderr)
        self.assertFalse((self.hooks() / "pre-commit").exists())
        self.assertFalse((self.home / ".config").exists())

    def test_the_work_profile_with_data_installs_both_hooks_and_the_two_files_mode_600(self):
        done = self.render(DATA)
        self.assertEqual(done.returncode, 0, done.stderr)
        ran = self.run_script(done.stdout)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        for name in ("pre-commit", "pre-push"):
            hook = self.hooks() / name
            self.assertTrue(os.access(hook, os.X_OK))
            text = hook.read_text()
            self.assertIn("# leak-guard hook (managed by chezmoi", text)
            self.assertIn('exec "$HOME/.local/bin/leak-guard" %s "$@"' % name, text)
        base = self.home / ".config" / "leak-guard"
        self.assertEqual((base / "terms").read_text(), "fooco\nbar.*baz\n")
        self.assertEqual((base / "context").read_text(), "Fooco is the pretend employer.\nA work detail is anything naming it.\n\n")
        for f in ("terms", "context"):
            self.assertEqual(stat.S_IMODE((base / f).stat().st_mode), 0o600)

    def test_a_hook_that_is_not_ours_is_left_alone_with_a_warning(self):
        done = self.render(DATA)
        self.hooks().mkdir(parents=True, exist_ok=True)
        (self.hooks() / "pre-commit").write_text("#!/bin/sh\necho mine\n")
        ran = self.run_script(done.stdout)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual((self.hooks() / "pre-commit").read_text(), "#!/bin/sh\necho mine\n")
        self.assertIn("pre-commit already exists and is not leak-guard's", ran.stderr)
        self.assertIn("exec", (self.hooks() / "pre-push").read_text())

    def test_changed_data_rewrites_the_files_and_our_own_hooks_are_replaced(self):
        for terms in ("fooco", "other"):
            done = self.render(DATA.replace('"fooco"', '"%s"' % terms))
            self.assertEqual(self.run_script(done.stdout).returncode, 0)
            self.assertTrue((self.home / ".config" / "leak-guard" / "terms").read_text().startswith(terms))

    def test_core_hooks_path_set_globally_or_in_the_repo_refuses_to_install_anything(self):
        for where in ("global", "local"):
            with self.subTest(where):
                shutil.rmtree(self.home / ".config", True)
                shutil.rmtree(self.hooks(), True)
                (self.home / ".gitconfig").unlink(missing_ok=True)
                subprocess.run(["git", "-C", str(self.src), "config", "--unset", "core.hooksPath"], capture_output=True)
                if where == "global":
                    (self.home / ".gitconfig").write_text("[core]\n\thooksPath = %s\n" % (self.tmp / "shared-hooks"))
                else:
                    subprocess.run(["git", "-C", str(self.src), "config", "core.hooksPath", str(self.tmp / "shared-hooks")], check=True)
                done = self.render(DATA)
                ran = self.run_script(done.stdout)
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertIn("core.hooksPath is set", ran.stderr)
                self.assertIn("every repository that shares it", ran.stderr)
                self.assertFalse((self.hooks() / "pre-commit").exists())
                self.assertFalse((self.tmp / "shared-hooks").exists())
                self.assertFalse((self.home / ".config" / "leak-guard").exists())

    def test_a_worktree_style_git_file_still_finds_the_hooks_dir(self):
        shutil.rmtree(self.src / ".git")
        real = self.tmp / "real.git"
        subprocess.run(["git", "init", "-q", "--bare", str(real)], check=True)
        (self.src / ".git").write_text("gitdir: %s\n" % real)
        done = self.render(DATA)
        self.assertEqual(self.run_script(done.stdout).returncode, 0)
        self.assertTrue((real / "hooks" / "pre-commit").exists())

    def test_bad_data_fails_the_render(self):
        for bad, why in (('  leakGuard:\n    terms: "fooco"\n    context: "x"\n', "non-empty list"), ('  leakGuard:\n    terms: []\n    context: "x"\n', "non-empty list"),
                         ('  leakGuard:\n    terms: [1]\n    context: "x"\n', "only strings"), ('  leakGuard:\n    terms: ["a"]\n', "context must be"),
                         ('  leakGuard: "text"\n', "must be a map")):
            with self.subTest(bad):
                done = self.render(bad)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(why, done.stderr)


if __name__ == "__main__":
    unittest.main()
