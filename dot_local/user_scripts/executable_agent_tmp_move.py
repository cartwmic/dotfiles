#!/usr/bin/env python3
"""Move idle ~/tmp subtrees to the Workshop SSD ($AGENT_TMP) and leave a link at each old path.

    agent_tmp_move.py                 dry run: what would move and what is held back, with the reason
    agent_tmp_move.py --apply         move every subtree that qualifies, one at a time
    agent_tmp_move.py --apply --only NAME [NAME ...]

Personal Mac only (.chezmoiignore). Deterministic, no judgment. Docs: docs/agent-scratch.md.

A top-level entry of ~/tmp moves only when ALL of these hold:
  - it is a real directory or file, not already a link, and not on the keep list (ssd-move, ssd-scratch, --keep NAME);
  - nothing has it open: one `lsof` snapshot, taken right before the move, checked against its old and new path
    (an open file or a process whose current directory is inside it holds it);
  - its newest mtime (the entry, every directory and every file in it) is older than --min-age-hours (default 2);
  - copying it leaves at least --reserve-gb (default 100) GB free on the destination disk, checked with df right before each copy;
  - it holds no registered git worktree, and is not inside one: `git worktree list` of the repos under
    /Volumes/Workshop/macbook/git, ~/.local/share/chezmoi and ~/.t3/worktrees/*/* (or the --repo list).

The move: rsync -a into <dest>/.NAME.partial, check the copy (entry count and file bytes, and that the source did not change
while copying), look at lsof once more, rename the original aside, link <source>/NAME -> <dest>/NAME, and remove the renamed
original. Nothing is removed before the check passes. A failed or held-back entry stays where it is; the partial copy stays too
(a rerun reuses it). Each decision of an --apply run (moved, held, failed, with the reason) is one line in the log (--log).

~/tmp itself stays a real directory holding the links (qmd does not follow links; docs/qmd.md).

Undo for one entry: rm ~/tmp/NAME (the link), then mv $AGENT_TMP/NAME ~/tmp/NAME (a copy across disks: rsync -a first).
If Workshop is not mounted the script stops before it changes anything.
"""
import argparse
import bisect
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_KEEP = ("ssd-move", "ssd-scratch")
GIT_ROOT = Path("/Volumes/Workshop/macbook/git")


def say(msg):
    print(msg, flush=True)


def walk_stats(path):
    """(entries, file_bytes, newest_mtime) of a path, counting itself. lstat only: links are not followed."""
    st = os.lstat(path)
    count, size, newest = 1, 0, st.st_mtime
    if not os.path.isdir(path) or os.path.islink(path):
        return count, st.st_size if os.path.isfile(path) and not os.path.islink(path) else 0, newest
    stack = [path]
    while stack:
        d = stack.pop()
        with os.scandir(d) as it:
            for e in it:
                try:
                    s = e.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                count += 1
                newest = max(newest, s.st_mtime)
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                else:
                    size += s.st_size
    return count, size, newest


def open_paths():
    """Sorted list of every path any of this user's processes has open or as its current directory (one lsof call)."""
    out = subprocess.run(["lsof", "-n", "-P", "-w", "-F", "n"], capture_output=True, text=True).stdout
    return sorted({ln[1:] for ln in out.splitlines() if ln.startswith("n/")})


def held_by(paths, entry):
    """First open path equal to `entry` or inside it (paths is open_paths(), sorted), else None."""
    entry = str(entry)
    i = bisect.bisect_left(paths, entry)
    if i < len(paths) and paths[i] == entry:
        return paths[i]
    j = bisect.bisect_left(paths, entry + "/")
    if j < len(paths) and paths[j].startswith(entry + "/"):
        return paths[j]
    return None


def default_repos():
    repos = []
    if GIT_ROOT.is_dir():
        repos += [p for p in sorted(GIT_ROOT.iterdir()) if (p / ".git").exists()]
    chez = Path.home() / ".local/share/chezmoi"
    if (chez / ".git").exists():
        repos.append(chez)
    t3 = Path.home() / ".t3/worktrees"
    if t3.is_dir():
        repos += [q for p in sorted(t3.iterdir()) if p.is_dir() for q in sorted(p.iterdir()) if q.is_dir()]
    return repos


def registered_worktrees(repos):
    """Paths git lists as worktrees in these repos, minus the ones git marks prunable (their directory is gone)."""
    found, seen = set(), set()
    for repo in repos:
        r = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], capture_output=True, text=True)
        if r.returncode != 0:
            continue
        path, prunable = None, False
        for ln in r.stdout.splitlines() + [""]:
            if ln.startswith("worktree "):
                path, prunable = ln[len("worktree "):], False
            elif ln.startswith("prunable"):
                prunable = True
            elif ln == "" and path:
                if not prunable and path not in seen:
                    seen.add(path)
                    found.add(path)
                    found.add(os.path.realpath(path))
                path = None
    return found


def worktree_conflict(worktrees, entry):
    entry = str(entry)
    real = os.path.realpath(entry)
    for w in worktrees:
        for e in (entry, real):
            if w == e or w.startswith(e + "/") or e.startswith(w + "/"):
                return w
    return None


def rsync(src, dst):
    src_arg = str(src) + ("/" if os.path.isdir(src) and not os.path.islink(src) else "")
    r = subprocess.run(["rsync", "-a", "--delete", src_arg, str(dst)], capture_output=True, text=True)
    return r.returncode, r.stderr.strip()


def remove_tree(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)


class Mover:
    def __init__(self, a):
        self.src = Path(a.source)
        self.dst = Path(a.dest)
        self.age = a.min_age_hours * 3600
        self.keep = set(DEFAULT_KEEP) | set(a.keep)
        self.log = Path(a.log)
        self.apply = a.apply
        self.reserve = int(a.reserve_gb * 1e9)
        self.worktrees = registered_worktrees([Path(r) for r in a.repo] if a.repo else default_repos())

    def verdict(self, name, paths):
        """(None, stats) if the entry may move now, else (reason, None). `paths` is an open_paths() snapshot."""
        p = self.src / name
        if p.is_symlink():
            return "already a link", None
        if name in self.keep:
            return "on the keep list", None
        w = worktree_conflict(self.worktrees, p)
        if w:
            return "registered git worktree: " + w, None
        h = held_by(paths, p) or held_by(paths, self.dst / name)
        if h:
            return "open: " + h, None
        stats = walk_stats(p)
        age = time.time() - stats[2]
        if age < self.age:
            return "newest mtime is %.1f h old" % (age / 3600), None
        return None, stats

    def move(self, name, stats):
        p, final, part = self.src / name, self.dst / name, self.dst / ("." + name + ".partial")
        if final.exists() or final.is_symlink():
            return False, "destination already exists: " + str(final)
        t0 = time.time()
        rc, err = rsync(p, part)
        if rc != 0:
            return False, "rsync failed (%d): %s" % (rc, err)
        again = walk_stats(p)
        if again != stats:
            return False, "changed while copying (%s -> %s); copy left at %s" % (stats, again, part)
        copy = walk_stats(part)
        if copy[:2] != stats[:2]:
            return False, "copy differs: source %s entries %s bytes, copy %s entries %s bytes" % (stats[0], stats[1], copy[0], copy[1])
        paths = open_paths()
        held = held_by(paths, p) or held_by(paths, final)
        if held:
            return False, "opened while copying: " + held
        os.rename(part, final)
        aside = self.src / (name + ".moving-%d" % os.getpid())
        os.rename(p, aside)
        os.symlink(final, p)
        remove_tree(aside)
        self.record(name, "moved", entries=stats[0], bytes=stats[1], seconds=round(time.time() - t0, 1), to=str(final))
        return True, ""

    def record(self, name, result, **more):
        """One JSON line per entry the apply run decided on: moved, held or failed, with the reason."""
        rec = dict(time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), name=name, result=result, **more)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def run(self, only):
        names = sorted(os.listdir(self.src))
        if only:
            missing = [n for n in only if n not in names]
            for n in missing:
                say("NOT FOUND   %s" % n)
            names = [n for n in names if n in only]
        moved = held = failed = 0
        moved_bytes = 0
        paths = open_paths()
        for name in names:
            if self.apply:
                paths = open_paths()  # a fresh snapshot right before each move
            reason, stats = self.verdict(name, paths)
            if reason:
                held += 1
                say("HOLD        %-40s %s" % (name, reason))
                if self.apply:
                    self.record(name, "held", why=reason)
                continue
            gb = stats[1] / 1e9
            # df right before each copy (a dry run subtracts what it already planned): keep the reserve free on Workshop.
            free = shutil.disk_usage(self.dst).free - (0 if self.apply else moved_bytes)
            if free - stats[1] < self.reserve:
                held += 1
                why = "would leave %.0f GB free on Workshop, under the %.0f GB reserve (%.0f GB free, %.3f GB to copy)" % (
                    (free - stats[1]) / 1e9, self.reserve / 1e9, free / 1e9, gb)
                say("HOLD        %-40s %s" % (name, why))
                if self.apply:
                    self.record(name, "held", why=why)
                continue
            if not self.apply:
                moved += 1
                moved_bytes += stats[1]
                say("WOULD MOVE  %-40s %8d entries %9.3f GB" % (name, stats[0], gb))
                continue
            ok, why = self.move(name, stats)
            if ok:
                moved += 1
                moved_bytes += stats[1]
                say("MOVED       %-40s %8d entries %9.3f GB" % (name, stats[0], gb))
            else:
                failed += 1
                say("FAILED      %-40s %s" % (name, why))
                self.record(name, "failed", why=why)
        say("%s %d, held back %d, failed %d, %.3f GB of files" %
            ("moved" if self.apply else "would move", moved, held, failed, moved_bytes / 1e9))
        return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="do it (the default is a dry run)")
    ap.add_argument("--only", nargs="+", default=[], metavar="NAME")
    ap.add_argument("--keep", nargs="*", default=[], metavar="NAME", help="more entries to leave where they are")
    ap.add_argument("--source", default=str(Path.home() / "tmp"))
    ap.add_argument("--dest", default=os.environ.get("AGENT_TMP", ""))
    ap.add_argument("--min-age-hours", type=float, default=2.0)
    ap.add_argument("--repo", nargs="*", default=[], help="repos whose worktree lists to check (default: Workshop git, chezmoi, T3 worktrees)")
    ap.add_argument("--reserve-gb", type=float, default=100.0, help="keep this much free on the destination disk after each copy (default 100)")
    ap.add_argument("--log", default=str(Path.home() / ".local/state/agent-tmp-move/moves.jsonl"))
    a = ap.parse_args(argv)
    if not a.dest:
        say("ERROR: AGENT_TMP is not set and --dest was not given (open a new shell, or pass --dest)")
        return 2
    if not os.path.isdir(a.dest):
        say("ERROR: %s does not exist. Is Workshop mounted? Nothing was changed." % a.dest)
        return 2
    if not os.path.isdir(a.source):
        say("ERROR: %s is not a directory" % a.source)
        return 2
    m = Mover(a)
    return m.run(a.only)


if __name__ == "__main__":
    sys.exit(main())
