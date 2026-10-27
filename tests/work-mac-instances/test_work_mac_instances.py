"""Tests for work-mac-instances.sh: a scratch HOME, the real chezmoi and real git (a local bare remote as the dotfiles upstream), a stub launchctl.
Nothing here touches the real home, a real chezmoi state, launchd, 1Password or the network. Run: python3 -m unittest test_work_mac_instances -v
WORK_MAC_SCRIPT=/path overrides the script under test (mutate.py uses it); DOTFILES_SRC is a checkout that has the work coordinator instance."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SCRIPT = Path(os.environ.get("WORK_MAC_SCRIPT", ROOT / "docs/work-mac/work-mac-instances.sh"))
DOTFILES = Path(os.environ.get("DOTFILES_SRC", ROOT))
REAL_CHEZMOI = shutil.which("chezmoi")
GOLDEN_WORK = DOTFILES / "tests/instances/golden/local.coordinatord.work.plist"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
LABEL = "local.coordinatord.work"

CFG_BASE = '# my chezmoi config\ndata:\n  jumpSshHost: "worklaptop"   # keep me\nhooks:\n  read-source-state:\n    pre:\n      command: ".local/share/chezmoi/.install-password-manager.sh"\n'
CFG_PROFILE = CFG_BASE.replace("data:\n", 'data:\n  profile: "axon-work-computer"\n')

STUBS = {
    "launchctl": '#!/bin/sh\necho "$*" >> "$STUB_DIR/calls"\ncase "$1" in\n'
                 ' print) [ -n "${STUB_PRINT_RC:-}" ] && exit "$STUB_PRINT_RC"; l=${2##*/}; [ -e "$STUB_DIR/loaded/$l" ] && exit 0; exit 113;;\n'
                 ' bootstrap) l=$(basename "$3" .plist); mkdir -p "$STUB_DIR/loaded"; touch "$STUB_DIR/loaded/$l";;\n'
                 ' bootout) l=${2##*/}; rm -f "$STUB_DIR/loaded/$l";;\nesac\nexit 0\n',
    "chezmoi": '#!/bin/sh\necho "$*" >> "$STUB_DIR/chezmoi_calls"\ncase "$1" in\n apply)\n  case "${STUB_CHEZMOI_FAIL_APPLY:-}" in\n'
               '   before) echo "stub: apply failed" >&2; exit 1;;\n   second) if [ "$(grep -c "^apply" "$STUB_DIR/chezmoi_calls")" -ge 2 ]; then echo "stub: apply failed" >&2; exit 1; fi;;\n   after) "$REAL_CHEZMOI" "$@"; echo "stub: apply failed" >&2; exit 1;;\n  esac;;\n'
               ' execute-template)\n  case "$*" in *--override-data*) if [ -n "${STUB_CHEZMOI_NO_OVERRIDE:-}" ]; then echo "chezmoi: unknown flag: --override-data" >&2; exit 1; fi;; esac\n  if [ -n "${STUB_CHEZMOI_LIE_EXTRA:-}" ]; then case "$*" in *\'"extraPath"\'*) exit 0;; esac; fi\n  if [ -n "${STUB_CHEZMOI_LIE_REPO:-}" ]; then case "$*" in *\'"repo"\'*) if [ -n "${STUB_LIE_TOUCH:-}" ]; then echo "# edited later" >> "$HOME/.config/chezmoi/chezmoi.yaml"; fi; exit 0;; esac; fi;;\nesac\nexec "$REAL_CHEZMOI" "$@"\n',
    "awk": '#!/bin/sh\nif [ -n "${STUB_AWK_TOUCH:-}" ]; then echo "# edited elsewhere" >> "$HOME/.config/chezmoi/chezmoi.yaml"; fi\nif [ -n "${STUB_AWK_CORRUPT:-}" ]; then /usr/bin/awk "$@" | sed "s/^# my chezmoi config/# changed by a bug/"; exit 0; fi\nexec /usr/bin/awk "$@"\n',
    "cp": '#!/bin/sh\nif [ -n "${STUB_CP_TOUCH_BAK:-}" ]; then for a in "$@"; do case "$a" in *.bak.*) /bin/cp "$@"; echo "# edited elsewhere" >> "$HOME/.config/chezmoi/chezmoi.yaml"; exit 0;; esac; done; fi\nif [ -n "${STUB_CP_FAIL_RENDERED:-}" ]; then for a in "$@"; do case "$a" in */rendered.plist) echo "cp: stub failure" >&2; exit 1;; esac; done; fi\nif [ -n "${STUB_CP_EMPTY_BAK:-}" ]; then for a in "$@"; do case "$a" in *.bak.*) : > "$a"; exit 0;; esac; done; fi\nif [ -n "${STUB_CP_FAIL_BAK:-}" ]; then for a in "$@"; do case "$a" in *.bak.*) echo "cp: stub failure" >&2; exit 1;; esac; done; fi\nexec /bin/cp "$@"\n',
    "git": '#!/bin/sh\nif [ -n "${STUB_GIT_FAIL_STATUS:-}" ]; then for a in "$@"; do [ "$a" = status ] && exit 1; done; fi\nexec /usr/bin/git "$@"\n',
    "mv": '#!/bin/sh\nif [ -n "${STUB_MV_FAIL:-}" ]; then for a in "$@"; do case "$a" in *.${STUB_MV_FAIL}.*) echo "mv: stub failure" >&2; exit 1;; esac; done; fi\nexec /bin/mv "$@"\n',
    "date": '#!/bin/sh\nif [ -n "${STUB_DATE_FIXED:-}" ]; then echo 20260101-000000; exit 0; fi\nexec /bin/date "$@"\n',
    "id": '#!/bin/sh\nif [ -n "${STUB_ID_ROOT:-}" ] && [ "$*" = "-u" ]; then echo 0; exit 0; fi\nexec /usr/bin/id "$@"\n',
    "op": '#!/bin/sh\necho "$*" >> "$STUB_DIR/op_calls"\nexit 0\n',
}


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@unittest.skipUnless(sys.platform == "darwin" and REAL_CHEZMOI and shutil.which("git"), "needs macOS, chezmoi and git")
class WorkMacTestCase(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="wmi.")))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = self.base / "home"
        self.bin = self.base / "bin"
        self.stub = self.base / "stub"
        self.tools = self.base / "tools"
        self.remote = self.base / "remote.git"
        for d in (self.home, self.stub, self.base / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        for name, text in STUBS.items():
            write_exec(self.bin / name, text)
        for name in ("node", "herdr", "git", "op"):
            write_exec(self.tools / name, "#!/bin/sh\nexit 0\n")
        (self.base / "gitconfig").write_text("")
        self.genv = dict(os.environ, GIT_CONFIG_GLOBAL=str(self.base / "gitconfig"), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                         GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com", GIT_TERMINAL_PROMPT="0")
        self.source = self.home / ".local/share/chezmoi"
        self.make_source()
        self.coord = self.home / "git" / "coordinator"
        self.make_coordinator(self.coord)
        self.config = self.home / ".config/chezmoi/chezmoi.yaml"
        self.write_config(CFG_BASE)
        self.last = None

    # ---- fixtures
    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, env=self.genv).stdout.strip()

    def make_source(self):
        seed = self.base / "seed"
        (seed / "dot_local/share/instances").mkdir(parents=True)
        shutil.copytree(DOTFILES / "dot_local/share/instances/launchd", seed / "dot_local/share/instances/launchd")
        shutil.copytree(DOTFILES / ".chezmoitemplates", seed / ".chezmoitemplates")
        (seed / "dot_local/user_scripts").mkdir(parents=True)
        shutil.copy(DOTFILES / "dot_local/user_scripts/executable_instances_reconcile.sh", seed / "dot_local/user_scripts/")
        shutil.copy(DOTFILES / "run_after_75_instances_reconcile.sh.tmpl", seed)
        shutil.copy(DOTFILES / ".chezmoiignore", seed)
        (seed / "dot_decoy").write_text("decoy\n")  # a file that a full apply would create; the script must never apply it
        write_exec(seed / "run_after_99_decoy.sh", '#!/bin/sh\necho ran > "$HOME/DECOY_RAN"\n')
        write_exec(seed / ".install-password-manager.sh", '#!/bin/sh\npwd > "$STUB_DIR/HOOK_PWD"\n')
        write_exec(seed / "other-hook.sh", '#!/bin/sh\npwd > "$STUB_DIR/HOOK_PWD"\n')
        self.git("init", "-q", "-b", "main", cwd=seed)
        self.git("add", "-A", cwd=seed)
        self.git("commit", "-q", "-m", "seed", cwd=seed)
        self.git("init", "-q", "--bare", "-b", "main", str(self.remote), cwd=self.base)
        self.git("push", "-q", str(self.remote), "main", cwd=seed)
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.git("clone", "-q", str(self.remote), str(self.source), cwd=self.base)

    def make_coordinator(self, path, git=True, main=True):
        (path / "src/coordinatord").mkdir(parents=True)
        if main:
            (path / "src/coordinatord/main.ts").write_text("// stub\n")
        if git:
            self.git("init", "-q", cwd=path)
        # If the coordinator's setup script were ever run, this leaves a trace.
        write_exec(path / "scripts/work-instance-setup.sh", '#!/bin/sh\necho run >> "$HOME/SETUP_RAN"\nexit 1\n')

    def write_config(self, text):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(text)

    def push_upstream(self, name="upstream.txt"):
        other = self.base / "other"
        if not other.exists():
            self.git("clone", "-q", str(self.remote), str(other), cwd=self.base)
        (other / name).write_text("new\n")
        self.git("add", "-A", cwd=other)
        self.git("commit", "-q", "-m", "upstream " + name, cwd=other)
        self.git("push", "-q", "origin", "main", cwd=other)

    def local_commit(self, name="local.txt"):
        (self.source / name).write_text("local\n")
        self.git("add", "-A", cwd=self.source)
        self.git("commit", "-q", "-m", "local " + name, cwd=self.source)

    def live_unit(self, extra="", repo=None):
        text = GOLDEN_WORK.read_text().replace("/Users/test/git/coordinator", str(repo or self.coord)).replace("/Users/test", str(self.home))
        if extra:
            text = text.replace("<key>PATH</key><string>", "<key>PATH</key><string>" + extra + ":", 1)
        path = self.home / "Library/LaunchAgents" / (LABEL + ".plist")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def state(self):
        p = self.home / ".local/share/coordinator-work/config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n")

    def load(self):
        (self.stub / "loaded").mkdir(exist_ok=True)
        (self.stub / "loaded" / LABEL).write_text("")

    def hand_setup(self, extra=""):
        self.live_unit(extra)
        self.state()
        self.load()

    # ---- running
    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "COORDINATOR_DIR", "STUB_", "INSTANCES_"))}
        env.update(HOME=str(self.home), PATH="%s:%s" % (self.bin, SYSTEM_PATH), STUB_DIR=str(self.stub), REAL_CHEZMOI=REAL_CHEZMOI, TMPDIR=str(self.base / "tmp"),
                   INSTANCES_TOOL_PATH=str(self.tools), GIT_CONFIG_GLOBAL=str(self.base / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def run_script(self, *args, **extra):
        self.last = subprocess.run(["sh", str(SCRIPT), *args], capture_output=True, text=True, timeout=300, env=self.env(**extra), cwd=str(self.base))
        return self.last

    def out(self):
        return self.last.stdout + self.last.stderr

    def data(self, *keys):
        tmpl = "{{ dig " + " ".join('"%s"' % k for k in keys) + ' "" . }}'
        r = subprocess.run([REAL_CHEZMOI, "execute-template", tmpl], capture_output=True, text=True, env=self.env(), cwd=str(self.home), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def calls(self):
        p = self.stub / "calls"
        return p.read_text().splitlines() if p.exists() else []

    def chezmoi_calls(self):
        p = self.stub / "chezmoi_calls"
        return p.read_text().splitlines() if p.exists() else []

    def backups(self):
        return sorted(self.config.parent.glob("chezmoi.yaml.bak.*"))

    def snapshot(self):
        h = hashlib.sha256()
        for root in (self.home, self.remote):
            for p in sorted(root.rglob("*")):
                rel = str(p.relative_to(root.parent))
                if p.is_dir():
                    h.update(("D " + rel + "\n").encode())
                elif p.is_file():
                    h.update(("F " + rel + "\n").encode() + p.read_bytes())
        return h.hexdigest()

    def head(self):
        return self.git("rev-parse", "HEAD", cwd=self.source)

    def assertOK(self):
        self.assertEqual(self.last.returncode, 0, self.out())

    def assertFails(self, code=1, text=None):
        self.assertEqual(self.last.returncode, code, self.out())
        if text:
            self.assertIn(text, self.out())

    def assertNothingAppliedOrChanged(self, before_config=None):
        self.assertEqual(self.config.read_text(), before_config if before_config is not None else self.config.read_text())
        self.assertEqual(self.backups(), [])
        self.assertFalse((self.home / ".local/share/instances").exists())
        self.assertFalse((self.home / "DECOY_RAN").exists())
        self.assertEqual([c for c in self.chezmoi_calls() if c.startswith("apply")], [])

    def assertKept(self, before, after):
        """Every line of the old file is still there, in order: nothing was overwritten or reordered."""
        rest = iter(after.splitlines())
        for line in before.splitlines():
            self.assertTrue(any(line == r for r in rest), "line lost or moved: %r" % line)

    def non_print_calls(self):
        return [c for c in self.calls() if not c.startswith("print ")]


class UsageTests(WorkMacTestCase):
    def test_help_prints_the_usage_and_exits_zero(self):
        self.run_script("--help")
        self.assertOK()
        self.assertIn("--dry-run", self.out())
        self.assertIn("--enable", self.out())

    def test_unknown_option_and_missing_argument_exit_2(self):
        self.run_script("--frobnicate")
        self.assertFails(2)
        self.run_script("--coordinator")
        self.assertFails(2)
        self.assertEqual(self.chezmoi_calls(), [])

    def test_root_is_refused(self):
        self.run_script(STUB_ID_ROOT="1")
        self.assertFails(1, "sudo")
        self.assertEqual(self.chezmoi_calls(), [])

    def test_a_missing_chezmoi_stops_before_anything(self):
        (self.bin / "chezmoi").unlink()
        self.run_script()
        self.assertFails(1, "chezmoi is not on PATH")
        self.assertEqual(self.backups(), [])


class PreflightTests(WorkMacTestCase):
    def test_a_dirty_dotfiles_source_stops_everything(self):
        (self.source / "dot_decoy").write_text("edited\n")
        before = self.config.read_text()
        self.run_script()
        self.assertFails(1, "uncommitted changes")
        self.assertNothingAppliedOrChanged(before)
        self.assertEqual(self.calls(), [])

    def test_untracked_files_alone_do_not_stop_it(self):
        (self.source / "scratch.txt").write_text("x\n")
        self.run_script()
        self.assertOK()

    def test_a_source_that_is_behind_is_fast_forwarded(self):
        self.push_upstream()
        self.run_script()
        self.assertOK()
        self.assertEqual(self.head(), self.git("rev-parse", "main", cwd=self.remote))
        self.assertIn("fast-forward", self.out())

    def test_a_diverged_source_is_not_touched(self):
        self.push_upstream()
        self.local_commit()
        head = self.head()
        before = self.config.read_text()
        self.run_script()
        self.assertFails(1, "diverged")
        self.assertEqual(self.head(), head)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.source), "")
        self.assertNothingAppliedOrChanged(before)

    def test_a_source_ahead_of_its_upstream_has_nothing_to_pull_and_continues(self):
        self.local_commit()
        head = self.head()
        self.run_script()
        self.assertOK()
        self.assertEqual(self.head(), head)
        self.assertIn("nothing to pull", self.out())

    def test_a_detached_head_or_a_missing_upstream_stops(self):
        self.git("checkout", "-q", "--detach", cwd=self.source)
        self.run_script()
        self.assertFails(1, "detached HEAD")
        self.git("checkout", "-q", "-b", "side", cwd=self.source)
        self.run_script()
        self.assertFails(1, "no upstream")
        self.assertNothingAppliedOrChanged()

    def test_an_unreachable_remote_stops(self):
        self.git("remote", "set-url", "origin", str(self.base / "nowhere.git"), cwd=self.source)
        self.run_script()
        self.assertFails(1, "cannot reach the dotfiles remote")
        self.assertNothingAppliedOrChanged()

    def test_a_source_without_the_work_instance_stops(self):
        (self.source / "run_after_75_instances_reconcile.sh.tmpl").unlink()
        self.git("commit", "-q", "-am", "drop", cwd=self.source)
        self.run_script()
        self.assertFails(1, "no work coordinator instance")

    def test_the_default_checkout_is_home_git_coordinator(self):
        self.run_script()
        self.assertOK()
        self.assertEqual(self.data("instances", "coordinator", "repo"), str(self.coord))
        self.assertIn("(default)", self.out())

    def test_the_environment_and_the_argument_choose_the_checkout_argument_first(self):
        env_dir = self.home / "elsewhere/env-coordinator"
        arg_dir = self.home / "elsewhere/arg-coordinator"
        self.make_coordinator(env_dir)
        self.make_coordinator(arg_dir)
        self.run_script("--dry-run", COORDINATOR_DIR=env_dir)
        self.assertOK()
        self.assertIn(str(env_dir), self.out())
        self.run_script("--dry-run", "--coordinator", str(arg_dir), COORDINATOR_DIR=env_dir)
        self.assertIn(str(arg_dir), self.out())
        self.assertNotIn("env-coordinator", self.out())

    def test_a_tilde_path_is_expanded_and_a_relative_one_refused(self):
        self.run_script("--dry-run", "--coordinator", "~/git/coordinator")
        self.assertOK()
        self.run_script("--dry-run", "--coordinator", "git/coordinator")
        self.assertFails(1, "must be absolute")

    def test_a_checkout_that_is_missing_not_git_or_not_the_coordinator_stops(self):
        before = self.config.read_text()
        self.run_script("--coordinator", str(self.home / "nope"))
        self.assertFails(1, "does not exist")
        plain = self.home / "plain"
        self.make_coordinator(plain, git=False)
        self.run_script("--coordinator", str(plain))
        self.assertFails(1, "not a git checkout")
        other = self.home / "other-repo"
        self.make_coordinator(other, main=False)
        self.run_script("--coordinator", str(other))
        self.assertFails(1, "not the coordinator repository")
        self.assertNothingAppliedOrChanged(before)

    def test_the_hook_with_a_path_relative_to_home_works_whatever_the_current_directory(self):
        self.run_script()
        self.assertOK()
        self.assertEqual((self.stub / "HOOK_PWD").read_text().strip(), str(self.home))


class DataTests(WorkMacTestCase):
    def test_missing_keys_are_added_after_a_verified_backup_and_nothing_else_changes(self):
        before = self.config.read_text()
        self.run_script()
        self.assertOK()
        after = self.config.read_text()
        self.assertKept(before, after)
        self.assertEqual(self.data("profile"), "axon-work-computer")
        self.assertEqual(self.data("instances", "coordinator", "repo"), str(self.coord))
        self.assertEqual(self.data("jumpSshHost"), "worklaptop")
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), before)

    def test_existing_values_are_never_overwritten(self):
        cfg = CFG_BASE.replace("data:\n", 'data:\n  profile: "axon-work-computer"\n  instances:\n    coordinator:\n      repo: "%s"   # mine\n      extraPath: "/opt/x"\n' % self.coord)
        self.write_config(cfg)
        self.run_script()
        self.assertEqual(self.config.read_text(), cfg)
        self.assertEqual(self.backups(), [])
        self.assertIn("nothing to add", self.out())

    def test_a_second_run_changes_nothing_and_makes_no_second_backup(self):
        self.run_script()
        self.assertOK()
        first = self.config.read_text()
        self.run_script()
        self.assertOK()
        self.assertEqual(self.config.read_text(), first)
        self.assertEqual(len(self.backups()), 1)

    def test_a_different_profile_stops_and_is_not_changed(self):
        cfg = CFG_BASE.replace("data:\n", 'data:\n  profile: "personal"\n')
        self.write_config(cfg)
        self.run_script()
        self.assertFails(1, "not axon-work-computer")
        self.assertNothingAppliedOrChanged(cfg)

    def test_an_existing_repo_that_differs_from_the_argument_stops_and_is_not_changed(self):
        other = self.home / "other-coordinator"
        self.make_coordinator(other)
        cfg = CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      repo: "%s"\n' % other)
        self.write_config(cfg)
        self.run_script("--coordinator", str(self.coord))
        self.assertFails(1, "never overwrites")
        self.assertNothingAppliedOrChanged(cfg)
        self.run_script()
        self.assertOK()  # without the argument the existing value is the checkout
        self.assertIn(str(other), self.out())

    def test_other_layouts_get_the_keys_in_the_right_place(self):
        layouts = {
            "four-space indent": 'data:\n    jumpSshHost: "x"\nhooks: {}\n',
            "instances without coordinator": 'data:\n  instances:\n    retro:\n      enabled: false\n  jumpSshHost: "x"\n',
            "coordinator without repo": 'data:\n  profile: "axon-work-computer"\n  instances:\n    coordinator:\n      enabled: false   # off\n',
            "no data at all": '# only a hook\nhooks:\n  read-source-state:\n    pre:\n      command: ".local/share/chezmoi/.install-password-manager.sh"\n',
        }
        for name, cfg in layouts.items():
            with self.subTest(name):
                self.write_config(cfg)
                for b in self.backups():
                    b.unlink()
                self.run_script()
                self.assertOK()
                self.assertKept(cfg, self.config.read_text())
                self.assertEqual(self.data("profile"), "axon-work-computer")
                self.assertEqual(self.data("instances", "coordinator", "repo"), str(self.coord))

    def test_a_layout_it_cannot_edit_safely_is_left_alone_with_the_lines_to_add(self):
        cases = {"flow style": 'data:\n  instances: {coordinator: {enabled: false}}\n',
                 "empty repo": 'data:\n  profile: "axon-work-computer"\n  instances:\n    coordinator:\n      repo: ""\n'}
        for name, cfg in cases.items():
            with self.subTest(name):
                self.write_config(cfg)
                self.run_script()
                self.assertFails(4, "Add it by hand")
                self.assertEqual(self.config.read_text(), cfg)
                self.assertEqual(self.backups(), [])
                self.assertFalse((self.home / ".local/share/instances").exists())

    def test_a_missing_config_stops_and_is_not_created(self):
        self.config.unlink()
        self.run_script()
        self.assertFails(1, "does not exist")
        self.assertFalse(self.config.exists())

    def test_a_backup_that_cannot_be_made_stops_before_the_edit(self):
        before = self.config.read_text()
        self.run_script(STUB_CP_FAIL_BAK="1")
        self.assertFails(1, "cannot back up")
        self.assertEqual(self.config.read_text(), before)

    def test_a_backup_that_does_not_match_stops_before_the_edit(self):
        before = self.config.read_text()
        self.run_script(STUB_CP_EMPTY_BAK="1")
        self.assertFails(1, "does not match")
        self.assertEqual(self.config.read_text(), before)

    def test_an_edit_that_would_change_an_existing_line_is_refused(self):
        before = self.config.read_text()
        self.run_script(STUB_AWK_CORRUPT="1")
        self.assertFails(1, "remove or change")
        self.assertEqual(self.config.read_text(), before)
        self.assertEqual(self.backups(), [])

    def test_an_edit_that_chezmoi_does_not_read_back_is_undone_from_the_backup(self):
        before = self.config.read_text()
        self.run_script(STUB_CHEZMOI_LIE_REPO="1")
        self.assertFails(1, "restored from")
        self.assertEqual(self.config.read_text(), before)
        self.assertEqual(len(self.backups()), 1)


class ApplyAndCompareTests(WorkMacTestCase):
    def test_only_the_instances_files_are_applied_and_the_flag_stays_off(self):
        self.hand_setup()
        self.run_script()
        self.assertOK()
        self.assertTrue((self.home / ".local/share/instances/launchd" / (LABEL + ".plist")).exists())
        self.assertTrue((self.home / ".local/user_scripts/instances_reconcile.sh").exists())
        self.assertFalse((self.home / "DECOY_RAN").exists())
        self.assertFalse((self.home / ".decoy").exists())
        applies = [c for c in self.chezmoi_calls() if c.startswith("apply")]
        self.assertEqual(len(applies), 1)
        self.assertNotIn("75_instances_reconcile.sh", applies[0])
        self.assertIn(".local/share/instances/launchd/" + LABEL + ".plist", applies[0])
        self.assertEqual(self.data("instances", "coordinator", "enabled"), "")
        self.assertFalse((self.home / ".local/state/instances").exists())
        self.assertEqual(self.non_print_calls(), [])
        self.assertIn("--enable", self.out())

    def test_with_the_flag_already_on_the_reconcile_step_still_does_not_run_without_enable(self):
        self.hand_setup()
        cfg = CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      enabled: true\n      repo: "%s"\n' % self.coord)
        self.write_config(cfg)
        self.run_script()
        self.assertOK()
        self.assertFalse((self.home / ".local/state/instances").exists())
        self.assertEqual(self.non_print_calls(), [])
        self.assertEqual(self.config.read_text(), cfg)
        self.assertIn("ALREADY true", self.out())
        self.assertIn("this script did not change it", self.out())
        self.assertNotIn("the flag is still off", self.out())

    def test_an_apply_that_fails_stops_with_its_message(self):
        self.run_script(STUB_CHEZMOI_FAIL_APPLY="after")
        self.assertFails(1, "chezmoi apply failed")

    def test_an_identical_live_unit_is_reported_identical(self):
        self.hand_setup()
        self.run_script()
        self.assertOK()
        self.assertIn("identical", self.out())

    def test_no_live_unit_is_only_a_note_without_enable(self):
        self.run_script()
        self.assertOK()
        self.assertIn("no live unit", self.out())

    def test_with_that_extra_path_set_the_units_are_identical(self):
        self.hand_setup(extra="/opt/nvm/bin:/opt/herdr/bin")
        self.write_config(CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      extraPath: "/opt/nvm/bin:/opt/herdr/bin"\n'))
        self.run_script()
        self.assertOK()
        self.assertIn("identical", self.out())

    def test_an_extra_path_that_the_live_unit_does_not_have_is_reported(self):
        self.hand_setup()
        self.write_config(CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      extraPath: "/opt/nvm/bin"\n'))
        self.run_script()
        self.assertFails(4, "Remove instances.coordinator.extraPath")

    def test_a_live_unit_from_another_checkout_shows_the_diff_and_the_live_directory(self):
        other = self.home / "old-coordinator"
        self.make_coordinator(other)
        self.live_unit(repo=other)
        self.run_script("--coordinator", str(self.coord))
        self.assertFails(4, "more than PATH")
        self.assertIn(str(other), self.out())
        self.assertIn("---", self.out())

    def test_the_coordinators_setup_script_and_1password_are_never_run(self):
        self.hand_setup()
        self.run_script("--enable")
        self.assertOK()
        self.assertFalse((self.home / "SETUP_RAN").exists())
        self.assertFalse((self.stub / "op_calls").exists())


class EnableTests(WorkMacTestCase):
    def test_enable_adopts_the_running_service_without_a_restart_and_reports_ready(self):
        self.hand_setup()
        before = self.config.read_text()
        self.run_script("--enable")
        self.assertOK()
        self.assertEqual(self.data("instances", "coordinator", "enabled"), "true")
        self.assertIn("coordinator-work: READY (adopted", self.out())
        self.assertEqual(self.calls(), ["print gui/%d/%s" % (os.getuid(), LABEL)] * 2)  # the script's look, then the reconcile step's
        self.assertTrue((self.stub / "loaded" / LABEL).exists())
        self.assertTrue((self.home / ".local/state/instances/coordinator-work.managed").exists())
        self.assertKept(before, self.config.read_text())
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.backups()[0].read_text(), before)
        applies = [c for c in self.chezmoi_calls() if c.startswith("apply")]
        self.assertEqual(len(applies), 2)
        self.assertIn("75_instances_reconcile.sh", applies[1])

    def test_enable_twice_is_idempotent(self):
        self.hand_setup()
        self.run_script("--enable")
        self.assertOK()
        cfg = self.config.read_text()
        self.run_script("--enable")
        self.assertOK()
        self.assertEqual(self.config.read_text(), cfg)
        self.assertEqual(len(self.backups()), 1)
        self.assertIn("already true", self.out())

    def test_an_existing_enabled_false_is_flipped_on_that_one_line_only(self):
        cfg = CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      enabled: false   # off for now\n      repo: "%s"\n' % self.coord)
        self.hand_setup()
        self.write_config(cfg)
        self.run_script("--enable")
        self.assertOK()
        self.assertEqual(self.config.read_text(), cfg.replace("enabled: false   # off for now", "enabled: true   # off for now"))
        self.assertEqual(self.backups()[0].read_text(), cfg)

    def test_without_the_flag_nothing_enables(self):
        self.hand_setup()
        self.run_script()
        self.assertOK()
        self.assertNotIn("enabled", self.config.read_text())
        self.assertFalse((self.home / ".local/state/instances").exists())

    def test_enable_stops_when_the_work_instance_was_not_set_up_by_hand(self):
        self.live_unit()
        self.load()  # no config.json
        self.run_script("--enable")
        self.assertFails(1, "work instance was not set up by hand")
        self.assertNotIn("enabled", self.config.read_text())
        self.assertFalse((self.home / "SETUP_RAN").exists())
        self.assertFalse((self.home / ".local/state/instances").exists())

    def test_enable_stops_when_there_is_no_live_unit_to_adopt(self):
        self.state()
        self.run_script("--enable")
        self.assertFails(1, "nothing to adopt")
        self.assertNotIn("enabled", self.config.read_text())
        self.assertFalse((self.home / ".local/state/instances").exists())

    def test_enable_stops_at_a_unit_difference_before_turning_the_flag_on(self):
        self.hand_setup()
        p = self.home / "Library/LaunchAgents" / (LABEL + ".plist")
        p.write_text(p.read_text().replace("<integer>10</integer>", "<integer>30</integer>"))
        self.run_script("--enable")
        self.assertFails(4, "more than PATH")
        self.assertNotIn("enabled", self.config.read_text())
        self.assertFalse((self.home / ".local/state/instances").exists())

    def test_not_ready_exits_5_and_leaves_the_flag_on(self):
        self.hand_setup()
        (self.tools / "node").unlink()
        self.run_script("--enable")
        self.assertFails(5, "NOT READY")
        self.assertEqual(self.data("instances", "coordinator", "enabled"), "true")
        self.assertIn("enabled: false", self.out())

    def test_an_enable_apply_that_fails_stops(self):
        self.hand_setup()
        self.run_script("--enable", STUB_CHEZMOI_FAIL_APPLY="before")
        self.assertFails(1, "chezmoi apply failed")

    def test_an_enable_edit_that_would_change_an_existing_line_is_refused(self):
        self.hand_setup()
        self.run_script()  # steps 1 to 4 once, so the config holds profile and repo
        cfg = self.config.read_text()
        self.run_script("--enable", STUB_AWK_CORRUPT="1")
        self.assertFails(1, "remove or change")
        self.assertEqual(self.config.read_text(), cfg)

    def test_a_flow_style_instances_block_is_not_edited_by_enable(self):
        self.hand_setup()
        cfg = 'data:\n  profile: "axon-work-computer"\n  instances: {coordinator: {repo: "%s"}}\n' % self.coord
        self.write_config(cfg)
        self.run_script("--enable")
        self.assertFails(4, "Add it by hand")
        self.assertEqual(self.config.read_text(), cfg)


class SafetyTests(WorkMacTestCase):
    def marker(self):
        d = self.home / ".local/state/instances"
        d.mkdir(parents=True, exist_ok=True)
        return d / "coordinator-work.configuring"

    def assertEnableRefusedUntouched(self, text):
        self.assertFails(1, text)
        self.assertNotIn("enabled", self.config.read_text())
        self.assertEqual([c for c in self.chezmoi_calls() if c.startswith("apply")][1:], [])
        self.assertEqual(self.non_print_calls(), [])
        self.assertFalse((self.home / "SETUP_RAN").exists())

    def test_a_stale_setup_marker_refuses_enable(self):
        self.hand_setup()
        self.marker().write_text("")
        self.run_script("--enable")
        self.assertEnableRefusedUntouched("configuring")
        self.assertTrue(self.marker().exists())  # not removed by the script

    def test_a_dangling_setup_marker_link_refuses_enable(self):
        self.hand_setup()
        os.symlink(str(self.base / "nowhere"), str(self.marker()))
        self.run_script("--enable")
        self.assertEnableRefusedUntouched("configuring")

    def test_reconcile_overrides_in_the_environment_are_refused(self):
        self.hand_setup()
        for var in ("INSTANCES_RELOAD", "INSTANCES_STATE_ROOT", "INSTANCES_AGENTS_DIR", "INSTANCES_UNIT_DIR"):
            with self.subTest(var):
                self.run_script("--enable", **{var: "all"})
                self.assertFails(1, var)
                self.assertEqual(self.chezmoi_calls(), [])
                self.assertNotIn("enabled", self.config.read_text())

    def test_a_hook_that_is_not_the_password_manager_installer_stops_before_any_chezmoi_run_of_the_source(self):
        cfg = CFG_BASE.replace(".install-password-manager.sh", "other-hook.sh")
        self.write_config(cfg)
        for args in ((), ("--dry-run",)):
            self.run_script(*args)
            self.assertFails(1, "other-hook.sh")
            self.assertIn("--allow-hooks", self.out())
        self.assertFalse((self.stub / "HOOK_PWD").exists())  # not run: dump-config does not read the source
        self.assertEqual([c for c in self.chezmoi_calls() if not c.startswith("dump-config")], [])
        self.assertNothingAppliedOrChanged(cfg)
        self.run_script("--allow-hooks")
        self.assertOK()

    def test_an_installer_named_hook_outside_the_default_checkout_is_not_trusted(self):
        other = self.home / "elsewhere"
        other.mkdir()
        write_exec(other / ".install-password-manager.sh", '#!/bin/sh\npwd > "$STUB_DIR/HOOK_PWD"\n')
        cfg = CFG_BASE.replace(".local/share/chezmoi/.install-password-manager.sh", str(other / ".install-password-manager.sh"))
        self.write_config(cfg)
        self.run_script()
        self.assertFails(1, "default checkout")
        self.assertFalse((self.stub / "HOOK_PWD").exists())
        self.assertNothingAppliedOrChanged(cfg)
        self.run_script("--allow-hooks")
        self.assertOK()

    def test_a_chezmoi_source_that_is_not_the_default_checkout_does_not_trust_the_installer(self):
        alt = self.home / "alt-source"
        alt.mkdir()
        cfg = 'sourceDir: "%s"\n' % alt + CFG_BASE
        self.write_config(cfg)
        self.run_script()
        self.assertFails(1, "default checkout")
        self.assertNothingAppliedOrChanged(cfg)

    def test_a_change_made_between_the_check_and_the_replacement_is_not_overwritten(self):
        self.run_script(STUB_CP_TOUCH_BAK="1")
        self.assertFails(1)
        self.assertRegex(self.out(), "does not match|changed while this script was running")
        text = self.config.read_text()
        self.assertIn("# edited elsewhere", text)
        self.assertNotIn("axon-work-computer", text)

    def test_a_config_changed_after_our_write_is_not_overwritten_by_the_restore(self):
        self.run_script(STUB_CHEZMOI_LIE_REPO="1", STUB_LIE_TOUCH="1")
        self.assertFails(1, "FAILED")
        self.assertIn("# edited later", self.config.read_text())
        self.assertIn(".bak.", self.out())

    def test_the_installer_hook_is_refused_when_op_is_missing_because_it_would_run_brew(self):
        (self.bin / "op").unlink()
        self.run_script()
        self.assertFails(1, "brew install 1password-cli")
        self.assertFalse((self.stub / "HOOK_PWD").exists())
        self.assertNothingAppliedOrChanged()

    def test_a_config_without_hooks_is_fine(self):
        self.write_config('data:\n  jumpSshHost: "x"\n')
        self.run_script()
        self.assertOK()
        self.assertIn("no chezmoi hooks", self.out())

    def test_yaml_aliases_are_not_edited_so_no_other_setting_changes(self):
        self.hand_setup()
        cfg = ('data:\n  profile: "axon-work-computer"\n  instances:\n    coordinator: &shared\n      enabled: false\n      repo: "%s"\n  employerAutomation: *shared\n' % self.coord)
        self.write_config(cfg)
        self.run_script("--enable")
        self.assertFails(4, "Add it by hand")
        self.assertEqual(self.config.read_text(), cfg)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.data("employerAutomation", "enabled"), "false")

    def test_block_scalars_and_merge_keys_are_not_edited_either(self):
        for cfg in ('data:\n  note: |\n    text\n', 'data:\n  base: &b {a: 1}\n  other:\n    <<: *b\n'):
            with self.subTest(cfg):
                self.write_config(cfg)
                self.run_script()
                self.assertFails(4, "Add it by hand")
                self.assertEqual(self.config.read_text(), cfg)

    def test_a_config_changed_by_someone_else_during_the_run_is_not_overwritten(self):
        self.run_script(STUB_AWK_TOUCH="1")
        self.assertFails(1, "changed while this script was running")
        self.assertIn("# edited elsewhere", self.config.read_text())
        self.assertNotIn("axon-work-computer", self.config.read_text())
        self.assertEqual(self.backups(), [])

    def test_a_write_that_fails_leaves_the_config_unchanged(self):
        before = self.config.read_text()
        self.run_script(STUB_MV_FAIL="wmi-new")
        self.assertFails(1, "cannot write")
        self.assertEqual(self.config.read_text(), before)
        self.assertEqual(list(self.config.parent.glob("chezmoi.yaml.wmi-*")), [])

    def test_a_failed_restore_is_reported_as_failed_not_as_restored(self):
        self.run_script(STUB_CHEZMOI_LIE_REPO="1", STUB_MV_FAIL="wmi-restore")
        self.assertFails(1, "FAILED")
        self.assertNotIn("was restored", self.out())
        self.assertIn("cp ", self.out())

    def test_an_existing_backup_file_is_never_overwritten(self):
        old = Path(str(self.config) + ".bak.20260101-000000")
        old.write_text("precious\n")
        before = self.config.read_text()
        self.run_script(STUB_DATE_FIXED="1")
        self.assertOK()
        self.assertEqual(old.read_text(), "precious\n")
        newer = Path(str(self.config) + ".bak.20260101-000000.1")
        self.assertEqual(newer.read_text(), before)

    def test_a_successful_restore_is_checked_and_said_so(self):
        before = self.config.read_text()
        self.run_script(STUB_CHEZMOI_LIE_REPO="1")
        self.assertFails(1, "restored from")
        self.assertEqual(self.config.read_text(), before)

    def test_two_runs_at_once_are_refused_and_the_lock_is_released(self):
        lock = Path(str(self.config) + ".wmi-lock")
        lock.mkdir()
        self.run_script()
        self.assertFails(1, "holds")
        self.assertEqual(self.backups(), [])
        lock.rmdir()
        self.run_script()
        self.assertOK()
        self.assertFalse(lock.exists())
        self.run_script(STUB_CHEZMOI_FAIL_APPLY="before")
        self.assertFalse(lock.exists())  # also after a failure
        self.run_script("--dry-run")
        self.assertFalse(lock.exists())

    def test_a_symlinked_config_is_edited_through_the_link(self):
        target = self.home / "dotfiles-private/chezmoi.yaml"
        target.parent.mkdir(parents=True)
        target.write_text(CFG_BASE)
        self.config.unlink()
        os.symlink(str(target), str(self.config))
        self.run_script()
        self.assertOK()
        self.assertTrue(self.config.is_symlink())
        self.assertIn("axon-work-computer", target.read_text())
        self.assertEqual(len(list(target.parent.glob("chezmoi.yaml.bak.*"))), 1)

    def test_enable_refuses_a_service_launchd_does_not_show_as_loaded(self):
        self.hand_setup()
        (self.stub / "loaded" / LABEL).unlink()
        self.run_script("--enable")
        self.assertEnableRefusedUntouched("no running service")
        (self.stub / "chezmoi_calls").unlink()
        self.run_script("--enable", STUB_PRINT_RC="5")
        self.assertEnableRefusedUntouched("no running service")

    def test_a_failing_git_status_stops(self):
        self.run_script(STUB_GIT_FAIL_STATUS="1")
        self.assertFails(1, "cannot read the git status")
        self.assertNothingAppliedOrChanged()

    def test_a_failed_copy_of_the_rendered_unit_stops(self):
        self.run_script(STUB_CP_FAIL_RENDERED="1")
        self.assertFails(1, "cannot copy the rendered unit")


class DerivedFromTheLiveUnitTests(WorkMacTestCase):
    """The checkout and extraPath are read (read-only) from the installed live unit when nothing says otherwise."""

    def prefix(self):
        return "%s/.local/share/mise/installs/node/lts/bin:%s/.local/share/mise/installs/herdr/0.9.1" % (self.home, self.home)

    def live_path(self):
        return self.home / "Library/LaunchAgents" / (LABEL + ".plist")

    def other_checkout(self, name="coordinator-work"):
        d = self.home / name
        self.make_coordinator(d)
        return d

    # ---- the checkout
    def test_with_no_default_checkout_the_repo_comes_from_the_live_unit(self):
        other = self.other_checkout()
        shutil.rmtree(self.coord)
        self.live_unit(repo=other)
        self.state()
        self.load()
        live = self.live_path().read_bytes()
        self.run_script()
        self.assertOK()
        self.assertEqual(self.data("instances", "coordinator", "repo"), str(other))
        self.assertIn("derived from the WorkingDirectory of the live unit", self.out())
        self.assertIn("identical", self.out())
        self.assertEqual(self.live_path().read_bytes(), live)
        self.assertEqual(self.non_print_calls(), [])

    def test_the_live_units_checkout_is_preferred_to_a_valid_default(self):
        other = self.other_checkout()
        self.live_unit(repo=other)
        self.run_script()
        self.assertOK()
        self.assertEqual(self.data("instances", "coordinator", "repo"), str(other))
        self.assertNotIn("(default)", self.out())

    def test_an_argument_or_existing_data_beats_the_live_unit(self):
        other = self.other_checkout()
        self.live_unit(repo=other)
        self.run_script("--coordinator", str(self.coord))
        self.assertFails(4, "more than PATH")
        self.assertIn("(argument or COORDINATOR_DIR)", self.out())
        self.assertEqual(self.data("instances", "coordinator", "repo"), str(self.coord))
        self.write_config(CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      repo: "%s"\n' % self.coord))
        before = self.config.read_text()
        self.run_script()
        self.assertFails(4, "more than PATH")
        self.assertIn("(instances.coordinator.repo in your chezmoi data)", self.out())
        self.assertEqual(self.config.read_text(), before)

    def test_no_default_and_no_live_unit_stops_and_says_why(self):
        shutil.rmtree(self.coord)
        self.run_script()
        self.assertFails(1, "does not exist")
        self.assertIn("there is no live unit to read it from", self.out())
        self.assertNothingAppliedOrChanged()

    def test_a_live_directory_that_is_not_a_coordinator_checkout_is_not_used(self):
        self.live_unit(repo=self.home / "missing")
        self.run_script()
        self.assertEqual(self.data("instances", "coordinator", "repo"), str(self.coord))
        self.assertFails(4, "more than PATH")
        shutil.rmtree(self.coord)
        self.write_config(CFG_BASE)
        self.run_script()
        self.assertFails(1, "not a usable coordinator checkout")
        self.assertEqual(self.config.read_text(), CFG_BASE)

    def test_a_live_directory_with_characters_that_need_escaping_is_not_used(self):
        odd = self.home / "a&b"
        self.make_coordinator(odd)
        shutil.rmtree(self.coord)
        self.live_unit(repo=odd)
        self.run_script()
        self.assertFails(1, "not a usable coordinator checkout")
        self.assertEqual(self.config.read_text(), CFG_BASE)

    # ---- extraPath
    def test_a_path_prefix_in_the_live_unit_is_added_as_extra_path_and_the_units_then_match(self):
        pre = self.prefix()
        self.hand_setup(extra=pre)
        live = self.live_path().read_bytes()
        self.run_script()
        self.assertOK()
        self.assertEqual(self.data("instances", "coordinator", "extraPath"), pre)
        text = self.config.read_text()
        self.assertKept(CFG_BASE, text)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.backups()[0].read_text(), CFG_BASE)
        self.assertIn("identical", self.out())
        self.assertEqual(self.live_path().read_bytes(), live)
        self.assertEqual(self.non_print_calls(), [])
        self.run_script()
        self.assertOK()
        self.assertEqual(self.config.read_text(), text)
        self.assertEqual(len(self.backups()), 1)

    def test_the_dry_run_says_what_it_would_add_and_changes_nothing(self):
        pre = self.prefix()
        self.hand_setup(extra=pre)
        before = self.snapshot()
        self.run_script("--dry-run")
        self.assertOK()
        self.assertEqual(self.snapshot(), before)
        self.assertIn(pre, self.out())
        self.assertIn("would be identical", self.out())
        self.assertNotIn("extraPath", self.config.read_text())

    def test_a_chezmoi_without_override_data_still_dry_runs(self):
        self.hand_setup()
        before = self.snapshot()
        self.run_script("--dry-run", STUB_CHEZMOI_NO_OVERRIDE="1")
        self.assertOK()
        self.assertEqual(self.snapshot(), before)
        self.assertIn("identical", self.out())
        self.assertFalse(any("--override-data" in c for c in self.chezmoi_calls()))

    def test_hook_output_around_the_dry_run_unit_does_not_matter(self):
        self.hand_setup()
        write_exec(self.source / ".install-password-manager.sh", '#!/bin/sh\necho noise-from-the-hook\necho "<tag>" \n')
        self.git("add", "-A", cwd=self.source)
        self.git("commit", "-q", "-m", "noisy hook", cwd=self.source)
        self.run_script("--dry-run")
        self.assertOK()
        self.assertIn("identical", self.out())

    def test_an_extra_path_that_is_already_set_differently_is_never_overwritten(self):
        pre = self.prefix()
        self.hand_setup(extra=pre)
        cfg = CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      repo: "%s"\n      extraPath: "/opt/other/bin"\n' % self.coord)
        self.write_config(cfg)
        self.run_script()
        self.assertFails(4, 'extraPath: "%s"' % pre)
        self.assertIn("never overwrites", self.out())
        self.assertEqual(self.config.read_text(), cfg)
        self.assertEqual(self.backups(), [])

    def test_a_prefix_that_is_relative_or_needs_escaping_is_printed_not_written(self):
        for extra in ("bin:/opt/x/bin", "/opt/a&amp;b/bin"):
            self.hand_setup(extra=extra)
            cfg = CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      repo: "%s"\n' % self.coord)
            self.write_config(cfg)
            self.run_script()
            self.assertFails(4, "not one this script will write")
            self.assertEqual(self.config.read_text(), cfg)
            self.assertEqual(self.backups(), [])

    def test_a_path_that_differs_in_more_than_a_prefix_is_left_alone(self):
        self.hand_setup()
        p = self.live_path()
        p.write_text(p.read_text().replace("/opt/homebrew/bin", "/opt/brew/bin"))
        self.run_script()
        self.assertFails(4, "not by a prefix")
        self.assertNotIn("extraPath", self.config.read_text())

    def test_a_config_it_cannot_edit_safely_is_left_alone_for_extra_path_too(self):
        self.hand_setup(extra=self.prefix())
        cfg = CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      repo: "%s"\n' % self.coord) + "base: &base\n  k: 1\n"
        self.write_config(cfg)
        self.run_script()
        self.assertFails(4, "cannot safely add instances.coordinator.extraPath")
        self.assertEqual(self.config.read_text(), cfg)
        self.assertEqual(self.backups(), [])

    def test_an_extra_path_chezmoi_does_not_read_back_is_undone_from_the_backup(self):
        self.hand_setup(extra=self.prefix())
        self.run_script(STUB_CHEZMOI_LIE_EXTRA="1")
        self.assertFails(1, "restored from")
        self.assertEqual(self.config.read_text(), CFG_BASE)

    def test_an_apply_that_fails_after_the_extra_path_was_added_says_where_the_backup_is(self):
        self.hand_setup(extra=self.prefix())
        self.run_script(STUB_CHEZMOI_FAIL_APPLY="second")
        self.assertFails(1, "after extraPath was added")
        self.assertIn(".bak.", self.out())
        self.assertIn("extraPath", self.config.read_text())

    def test_enable_works_in_the_same_run_with_both_values_derived(self):
        other = self.other_checkout()
        shutil.rmtree(self.coord)
        self.live_unit(extra=self.prefix(), repo=other)
        self.state()
        self.load()
        self.run_script("--enable")
        self.assertOK()
        self.assertIn("READY", self.out())
        self.assertEqual(self.data("instances", "coordinator", "enabled"), "true")
        self.assertEqual(self.data("instances", "coordinator", "repo"), str(other))
        self.assertEqual(self.data("instances", "coordinator", "extraPath"), self.prefix())


class DryRunTests(WorkMacTestCase):
    def assertDryRunChangesNothing(self, *args, code=0, **extra):
        before = self.snapshot()
        self.run_script("--dry-run", *args, **extra)
        self.assertEqual(self.last.returncode, code, self.out())
        self.assertEqual(self.snapshot(), before, self.out())
        self.assertEqual(self.non_print_calls(), [])
        self.assertEqual([c for c in self.chezmoi_calls() if c.startswith("apply")], [])
        self.assertFalse((self.home / "DECOY_RAN").exists())

    def test_dry_run_with_everything_to_do_changes_nothing_and_says_what_it_would_do(self):
        self.push_upstream()
        self.assertDryRunChangesNothing()
        self.assertIn("[would]", self.out())
        self.assertIn("remote has newer commits", self.out())
        self.assertIn("does not change instances.coordinator.enabled", self.out())

    def test_dry_run_of_enable_changes_nothing(self):
        self.hand_setup()
        self.push_upstream()
        self.assertDryRunChangesNothing("--enable")
        self.assertIn("Dry run finished", self.out())
        self.assertIn("enabled: true", self.out())

    def test_dry_run_with_the_flag_to_flip_changes_nothing(self):
        self.hand_setup()
        cfg = CFG_PROFILE.replace("data:\n", 'data:\n  instances:\n    coordinator:\n      enabled: false\n      repo: "%s"\n' % self.coord)
        self.write_config(cfg)
        self.assertDryRunChangesNothing("--enable")

    def test_dry_run_compares_the_unit_it_would_install_with_the_live_one(self):
        self.hand_setup()
        self.assertDryRunChangesNothing()
        self.assertIn("identical", self.out())
        self.hand_setup(extra="/opt/nvm/bin")
        self.assertDryRunChangesNothing()
        self.assertIn('/opt/nvm/bin', self.out())
        self.assertIn("would be identical", self.out())

    def test_dry_run_still_stops_on_a_dirty_source(self):
        (self.source / "dot_decoy").write_text("edited\n")
        self.assertDryRunChangesNothing(code=1)
        self.assertIn("uncommitted", self.out())

    def test_dry_run_does_not_fast_forward_a_source_that_is_already_fetched(self):
        self.push_upstream()
        self.git("fetch", "-q", cwd=self.source)
        head = self.head()
        self.assertDryRunChangesNothing()
        self.assertEqual(self.head(), head)
        self.assertIn("would", self.out())

    def test_dry_run_with_a_source_lacking_the_instance_says_so_and_does_not_fail(self):
        (self.source / "run_after_75_instances_reconcile.sh.tmpl").unlink()
        self.git("commit", "-q", "-am", "drop", cwd=self.source)
        self.assertDryRunChangesNothing()
        self.assertIn("not in the source yet", self.out())


if __name__ == "__main__":
    unittest.main()
