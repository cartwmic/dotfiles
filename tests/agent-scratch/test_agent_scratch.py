"""Black-box tests for agent scratch on the Workshop SSD (docs/agent-scratch.md).

    python3 -m unittest discover -s tests/agent-scratch -v

- the env file and the dot_zshenv line, in a real `zsh -c` with HOME set to a temporary directory;
- the run_onchange script that makes the directory;
- the ~/tmp move script, against throwaway directories, a real lsof, a real rsync and real git worktrees.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "dot_config/agent-scratch/workshop.env"
ZSHENV = ROOT / "dot_zshenv"
CREATE = ROOT / "run_onchange_after_81_agent_scratch_workshop.sh"
MOVE = ROOT / "dot_local/user_scripts/executable_agent_tmp_move.py"
ZSH = shutil.which("zsh")


def clean_env(home, **extra):
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env.update(extra)
    return env


@unittest.skipUnless(ZSH, "zsh is not installed")
class EnvFileTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="agent-scratch-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        shutil.copy(ZSHENV, self.home / ".zshenv")

    def deploy_env_file(self):
        d = self.home / ".config/agent-scratch"
        d.mkdir(parents=True)
        shutil.copy(ENV_FILE, d / "workshop.env")

    def shell(self, **extra):
        return subprocess.run([ZSH, "-c", 'printf "%s" "${AGENT_TMP-unset}"'], env=clean_env(self.home, **extra),
                              capture_output=True, text=True, timeout=30)

    def test_mounted_sets_agent_tmp_and_says_nothing(self):
        self.deploy_env_file()
        (self.home / "ws/macbook").mkdir(parents=True)
        r = self.shell(AGENT_WORKSHOP_ROOT=str(self.home / "ws"))
        self.assertEqual(r.stdout, str(self.home / "ws/macbook/tmp-home"))
        self.assertEqual(r.stderr, "")

    def test_default_root_is_the_workshop_volume(self):
        self.deploy_env_file()
        r = self.shell()
        self.assertEqual(r.stdout, "/Volumes/Workshop/macbook/tmp-home")

    def test_unmounted_warns_once_keeps_the_workshop_path_and_creates_nothing(self):
        self.deploy_env_file()
        ws = self.home / "gone"
        r = self.shell(AGENT_WORKSHOP_ROOT=str(ws))
        self.assertEqual(r.stdout, str(ws / "macbook/tmp-home"))
        self.assertEqual(r.stderr.count("\n"), 1, r.stderr)
        self.assertIn("is not mounted", r.stderr)
        self.assertIn("no fallback to the internal disk", r.stderr)
        self.assertFalse(ws.exists())
        # A shell started by that shell inherits the flag and stays quiet.
        r2 = subprocess.run([ZSH, "-c", f'{ZSH} -c "true"'], env=clean_env(self.home, AGENT_WORKSHOP_ROOT=str(ws)),
                            capture_output=True, text=True, timeout=30)
        self.assertEqual(r2.stderr.count("\n"), 1, r2.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "/Volumes is a macOS mount root")
    def test_nothing_can_recreate_the_workshop_path_on_the_internal_disk(self):
        # AGENT_TMP names /Volumes/Workshop/...; when the disk is gone a write fails because /Volumes is root-owned.
        self.assertFalse(os.access("/Volumes", os.W_OK))

    def test_without_the_env_file_the_source_line_does_nothing(self):
        r = self.shell()
        self.assertEqual((r.stdout, r.stderr, r.returncode), ("unset", "", 0))

    def test_zshenv_has_one_guarded_source_line(self):
        lines = [ln for ln in ZSHENV.read_text().splitlines() if "agent-scratch" in ln and not ln.startswith("#")]
        self.assertEqual(lines, ['[ -f "$HOME/.config/agent-scratch/workshop.env" ] && . "$HOME/.config/agent-scratch/workshop.env"'])


@unittest.skipUnless(sys.platform == "darwin", "the script exits early off macOS")
class CreateScriptTest(unittest.TestCase):
    def run_script(self, root):
        return subprocess.run(["sh", str(CREATE)], env=clean_env("/nonexistent", AGENT_WORKSHOP_ROOT=str(root)),
                              capture_output=True, text=True, timeout=30)

    def test_creates_the_directory_when_mounted_and_moves_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "macbook").mkdir()
            (Path(t) / "macbook/keep.txt").write_text("x")
            r = self.run_script(t)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(t) / "macbook/tmp-home").is_dir())
            self.assertEqual(sorted(p.name for p in (Path(t) / "macbook").iterdir()), ["keep.txt", "tmp-home"])
            self.assertEqual(self.run_script(t).returncode, 0)  # idempotent

    def test_fails_loudly_and_creates_nothing_when_unmounted(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "gone"
            r = self.run_script(root)
            self.assertEqual(r.returncode, 1)
            self.assertIn("not there", r.stdout)
            self.assertFalse(root.exists())


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


def old(path, hours=5):
    """Set every mtime under path (and path) to `hours` ago."""
    t = time.time() - hours * 3600
    for dp, dn, fn in os.walk(path, topdown=False):
        for n in fn + dn:
            os.utime(os.path.join(dp, n), (t, t), follow_symlinks=False)
    os.utime(path, (t, t), follow_symlinks=False)


@unittest.skipUnless(shutil.which("lsof") and shutil.which("rsync") and shutil.which("git"), "needs lsof, rsync and git")
class MoveScriptTest(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="agent-tmp-move-")).resolve()
        self.addCleanup(shutil.rmtree, self.t, ignore_errors=True)
        self.src, self.dst, self.log = self.t / "tmp", self.t / "ws/tmp-home", self.t / "log.jsonl"
        self.src.mkdir()
        self.dst.mkdir(parents=True)
        self.repo = self.t / "repo"
        self.repo.mkdir()
        git("init", "-q", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "i", cwd=self.repo)
        self.holders = []
        self.addCleanup(self.stop_holders)

    def stop_holders(self):
        for p in self.holders:
            p.kill()
            p.wait()
            p.stdout.close()

    def tree(self, name, files=3, hours=5):
        d = self.src / name
        (d / "sub").mkdir(parents=True)
        for i in range(files):
            (d / "sub" / f"f{i}.md").write_text(f"{name} {i}\n" * (i + 1))
        (d / "link").symlink_to("sub")
        old(d, hours)
        return d

    def hold_open(self, path):
        p = subprocess.Popen([sys.executable, "-c", "import sys,time; f=open(sys.argv[1]); print('r',flush=True); time.sleep(60)", str(path)],
                             stdout=subprocess.PIPE, text=True)
        self.holders.append(p)
        p.stdout.readline()

    def hold_cwd(self, path):
        p = subprocess.Popen([sys.executable, "-c", "import time; print('r',flush=True); time.sleep(60)"], cwd=path, stdout=subprocess.PIPE, text=True)
        self.holders.append(p)
        p.stdout.readline()

    def run_move(self, *args):
        r = subprocess.run([sys.executable, str(MOVE), "--source", str(self.src), "--dest", str(self.dst), "--log", str(self.log),
                            "--repo", str(self.repo), *args], capture_output=True, text=True, timeout=120)
        return r

    def test_dry_run_changes_nothing_and_says_what_it_would_do(self):
        self.tree("idle")
        r = self.run_move()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WOULD MOVE  idle", r.stdout)
        self.assertTrue((self.src / "idle").is_dir() and not (self.src / "idle").is_symlink())
        self.assertEqual(list(self.dst.iterdir()), [])

    def test_apply_moves_an_idle_tree_and_leaves_a_working_link(self):
        d = self.tree("idle")
        before = sorted(str(p.relative_to(d)) for p in d.rglob("*"))
        r = self.run_move("--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("MOVED       idle", r.stdout)
        link = self.src / "idle"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(self.dst / "idle"))
        self.assertEqual(sorted(str(p.relative_to(link)) for p in link.rglob("*")), before)
        self.assertEqual((link / "sub/f1.md").read_text(), "idle 1\nidle 1\n")
        self.assertTrue((link / "link").is_symlink())
        # The internal original is gone and nothing else is left behind in the source or the destination.
        self.assertEqual(sorted(p.name for p in self.src.iterdir()), ["idle"])
        self.assertEqual(sorted(p.name for p in self.dst.iterdir()), ["idle"])
        rec = json.loads(self.log.read_text().splitlines()[0])
        self.assertEqual((rec["name"], rec["entries"]), ("idle", 6))

    def test_a_file_moves_too(self):
        f = self.src / "note.sh"
        f.write_text("echo hi\n")
        old(f)
        r = self.run_move("--apply")
        self.assertIn("MOVED       note.sh", r.stdout)
        self.assertEqual((self.src / "note.sh").read_text(), "echo hi\n")
        self.assertTrue((self.src / "note.sh").is_symlink())

    def test_open_file_holds_a_tree_back(self):
        d = self.tree("busy")
        self.hold_open(d / "sub/f0.md")
        r = self.run_move("--apply")
        self.assertIn("HOLD        busy", r.stdout)
        self.assertIn("open:", r.stdout)
        self.assertFalse((self.src / "busy").is_symlink())
        self.assertEqual(list(self.dst.iterdir()), [])

    def test_a_process_with_its_cwd_inside_holds_a_tree_back(self):
        d = self.tree("cwd")
        self.hold_cwd(d / "sub")
        r = self.run_move("--apply")
        self.assertIn("HOLD        cwd", r.stdout)
        self.assertFalse((self.src / "cwd").is_symlink())

    def test_a_recent_mtime_holds_a_tree_back(self):
        self.tree("fresh", hours=0.5)
        r = self.run_move("--apply")
        self.assertIn("HOLD        fresh", r.stdout)
        self.assertIn("newest mtime", r.stdout)
        self.assertFalse((self.src / "fresh").is_symlink())

    def test_one_new_file_inside_an_old_tree_holds_it_back(self):
        d = self.tree("mixed")
        (d / "sub/new.txt").write_text("now")
        r = self.run_move("--apply")
        self.assertIn("HOLD        mixed", r.stdout)

    def test_a_registered_worktree_holds_it_back_and_a_plain_tree_beside_it_moves(self):
        wt = self.src / "wt"
        git("worktree", "add", "-q", "-b", "live", str(wt), cwd=self.repo)
        old(wt)
        self.tree("plain")
        r = self.run_move("--apply")
        self.assertIn("HOLD        wt", r.stdout)
        self.assertIn("registered git worktree", r.stdout)
        self.assertFalse((self.src / "wt").is_symlink())
        self.assertIn("MOVED       plain", r.stdout)

    def test_keep_list_and_existing_links_are_left_alone(self):
        self.tree("ssd-move")
        self.tree("mine")
        (self.src / "already").symlink_to(self.dst)
        r = self.run_move("--apply", "--keep", "mine")
        self.assertIn("HOLD        ssd-move", r.stdout)
        self.assertIn("HOLD        mine", r.stdout)
        self.assertIn("HOLD        already", r.stdout)
        self.assertEqual(list(self.dst.iterdir()), [])

    def test_existing_destination_is_not_merged(self):
        self.tree("dup")
        (self.dst / "dup").mkdir()
        r = self.run_move("--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAILED      dup", r.stdout)
        self.assertIn("already exists", r.stdout)
        self.assertFalse((self.src / "dup").is_symlink())

    def test_missing_destination_stops_before_changing_anything(self):
        self.tree("idle")
        r = subprocess.run([sys.executable, str(MOVE), "--source", str(self.src), "--dest", str(self.t / "no-such"), "--apply",
                            "--repo", str(self.repo)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Is Workshop mounted", r.stdout)
        self.assertFalse((self.src / "idle").is_symlink())
        self.assertFalse((self.t / "no-such").exists())

    def test_unset_agent_tmp_stops(self):
        r = subprocess.run([sys.executable, str(MOVE), "--source", str(self.src)], capture_output=True, text=True, timeout=60,
                           env={k: v for k, v in os.environ.items() if k != "AGENT_TMP"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("AGENT_TMP is not set", r.stdout)

    def test_only_limits_the_moves(self):
        self.tree("a")
        self.tree("b")
        r = self.run_move("--apply", "--only", "b")
        self.assertIn("MOVED       b", r.stdout)
        self.assertFalse((self.src / "a").is_symlink())

    def test_finish_links_tmp_only_when_every_entry_is_a_link_into_dest(self):
        self.tree("one")
        self.tree("two")
        self.run_move("--apply", "--only", "one")
        r = self.run_move("--finish", "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT READY", r.stdout)
        self.assertIn("two", r.stdout)
        self.assertFalse(self.src.is_symlink())
        self.run_move("--apply", "--only", "two")
        r = self.run_move("--finish")
        self.assertEqual(r.returncode, 0)
        self.assertIn("READY", r.stdout)
        self.assertFalse(self.src.is_symlink())  # a dry run changes nothing
        r = self.run_move("--finish", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(self.src.is_symlink())
        self.assertEqual(os.readlink(self.src), str(self.dst))
        self.assertEqual((self.src / "two/sub/f2.md").read_text(), "two 2\n" * 3)
        self.assertEqual(len(list(self.t.glob("tmp.links-old-*"))), 1)

    def test_finish_waits_while_a_process_sits_in_tmp(self):
        self.tree("one")
        self.run_move("--apply")
        self.hold_cwd(self.src)
        r = self.run_move("--finish", "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT READY", r.stdout)
        self.assertFalse(self.src.is_symlink())


if __name__ == "__main__":
    unittest.main()
