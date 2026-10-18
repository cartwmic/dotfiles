#!/usr/bin/env python3
"""Prove that the live machine and the Git history were left untouched.

    live_guard.py snapshot [--file PATH]   record the baseline
    live_guard.py check    [--file PATH]   compare the present state with it

snapshot writes, outside the checkout (default: the system temp directory), a
baseline of the LIVE state only:

  * the SHA-256 of the live Herdr config.toml and plugins.json,
  * the live plugin list and the live server status (version), from the
    read-only commands `herdr plugin list` and `herdr status server`,
  * a listing of the places where a live inbox, agent-alert configuration, log
    or installed copy would appear (they are expected to be absent),
  * the Git facts: the HEAD commit, the current branch and the remote tip of
    that branch (read-only `git ls-remote`; "absent" when the remote has no
    such branch).

check exits 1 if any recorded item differs, if HEAD is no longer the baseline
commit, if the remote branch tip moved (a push), or if `git status` shows a
changed or untracked path outside the planned set (the --planned paths, by
default dot_local/share/agent-alert/ and .chezmoiignore). Edits inside the
planned set are expected and are not a difference. Exit 2 means the guard could
not look (for example the network is unreachable): that is never a pass.

The guard touches nothing live and starts no server. Roots are overridable
(--herdr-config-dir, --home, --repo, --remote, --herdr-bin) so its unit test
can run against scratch stand-ins.
"""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_DIFFERENCE = 1
EXIT_UNABLE = 2

HERDR_FILES = ("config.toml", "plugins.json")
DEFAULT_PLANNED = ("dot_local/share/agent-alert/", ".chezmoiignore")
# Places under the home directory that must stay empty of this tool's state.
LIVE_LISTING = (
    ".local/share/coordinator",
    ".local/share/coordinator/inbox.jsonl",
    ".local/share/coordinator/inbox.jsonl.lock",
    ".local/share/coordinator/inbox.jsonl.ack",
    ".config/agent-alert",
    ".local/state/agent-alert",
    ".local/share/agent-alert",
)
DEFAULT_SNAPSHOT = "agent-alert-live-snapshot.json"
REPO_ROOT = Path(__file__).resolve().parents[4]


class Unable(Exception):
    """The guard could not observe something; this is an error, not a pass."""


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def describe_path(path):
    if not os.path.lexists(path):
        return "absent"
    if os.path.isdir(path) and not os.path.islink(path):
        names = []
        for root, directories, files in os.walk(path):
            for name in directories + files:
                names.append(os.path.relpath(os.path.join(root, name), path))
        return {"directory": sorted(names)}
    if os.path.isfile(path):
        return {"file": sha256_of(path)}
    return {"other": os.readlink(path) if os.path.islink(path) else "special"}


def run(command, cwd=None, timeout=60):
    try:
        done = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Unable("%s: %s" % (" ".join(command), error))
    if done.returncode != 0:
        raise Unable("%s exited %d: %s" % (" ".join(command), done.returncode, done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


def observe_live(options):
    config_dir = Path(options.herdr_config_dir).expanduser()
    files = {}
    for name in HERDR_FILES:
        files[name] = sha256_of(config_dir / name) if (config_dir / name).is_file() else "absent"
    home = Path(options.home).expanduser()
    return {
        "herdr_config_files": files,
        "herdr_plugin_list": run([options.herdr_bin, "plugin", "list"], timeout=30).decode("utf-8", "replace"),
        "herdr_server_status": run([options.herdr_bin, "status", "server"], timeout=30).decode("utf-8", "replace"),
        "live_listing": {relative: describe_path(home / relative) for relative in LIVE_LISTING},
    }


def observe_git(options):
    repo = str(options.repo)
    head = run(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()
    branch = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo).decode().strip()
    listing = run(["git", "ls-remote", "--heads", options.remote, "refs/heads/" + branch], cwd=repo, timeout=60)
    tip = "absent"
    for line in listing.decode("utf-8", "replace").splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/" + branch:
            tip = sha
    return {"head": head, "branch": branch, "remote": options.remote, "remote_tip": tip}


def changed_paths(repo):
    """Paths git status reports as changed or untracked, one entry per path."""
    raw = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=str(repo))
    tokens = raw.decode("utf-8", "replace").split("\0")
    paths = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        paths.append(token[3:])
        if token[0] in "RC" or token[1] in "RC":
            paths.append(tokens[index])
            index += 1
    return paths


def outside_planned(paths, planned):
    def inside(path):
        for entry in planned:
            if entry.endswith("/"):
                if path.startswith(entry):
                    return True
            elif path == entry:
                return True
        return False

    return [path for path in paths if not inside(path)]


def snapshot_file(options):
    if options.file:
        return Path(options.file).expanduser().resolve()
    return Path(tempfile.gettempdir()).resolve() / DEFAULT_SNAPSHOT


def refuse_inside_checkout(path, repo):
    repo = Path(repo).resolve()
    if path == repo or repo in path.parents:
        raise Unable("the snapshot file %s must be outside the checkout %s" % (path, repo))


def command_snapshot(options):
    path = snapshot_file(options)
    refuse_inside_checkout(path, options.repo)
    state = {"created": datetime.datetime.now(datetime.timezone.utc).isoformat(), "live": observe_live(options), "git": observe_git(options)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("snapshot written: %s" % path)
    print(json.dumps(state, indent=2, sort_keys=True))
    stray = outside_planned(changed_paths(options.repo), options.planned)
    if stray:
        print("WARNING: paths outside the planned set are already changed; check will fail: %s" % ", ".join(stray))
    return 0


def differences(baseline, present):
    found = []

    def compare(label, before, after):
        if before != after:
            found.append("%s changed: %s -> %s" % (label, json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True)))

    for key in ("herdr_config_files", "herdr_plugin_list", "herdr_server_status", "live_listing"):
        if isinstance(baseline["live"][key], dict):
            for name in sorted(set(baseline["live"][key]) | set(present["live"][key])):
                compare("live %s %s" % (key, name), baseline["live"][key].get(name), present["live"][key].get(name))
        else:
            compare("live " + key, baseline["live"][key], present["live"][key])
    compare("HEAD commit", baseline["git"]["head"], present["git"]["head"])
    compare("current branch", baseline["git"]["branch"], present["git"]["branch"])
    compare("remote tip of %s" % baseline["git"]["branch"], baseline["git"]["remote_tip"], present["git"]["remote_tip"])
    return found


def command_check(options):
    path = snapshot_file(options)
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Unable("cannot read the snapshot %s: %s" % (path, error))
    options.remote = baseline["git"]["remote"]
    present = {"live": observe_live(options), "git": observe_git(options)}
    found = differences(baseline, present)
    for stray in outside_planned(changed_paths(options.repo), options.planned):
        found.append("git status shows a path outside the planned set: %s" % stray)
    if found:
        print("LIVE GUARD: %d difference(s) from %s" % (len(found), path))
        for line in found:
            print("  - " + line)
        return EXIT_DIFFERENCE
    print("LIVE GUARD: no difference from %s" % path)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("snapshot", "check"))
    parser.add_argument("--file", default=None, help="snapshot file (default: %s in the system temp directory)" % DEFAULT_SNAPSHOT)
    parser.add_argument("--herdr-config-dir", default="~/.config/herdr")
    parser.add_argument("--home", default="~")
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--herdr-bin", default="herdr")
    parser.add_argument("--planned", action="append", default=None, help="planned path: a trailing / means a directory prefix (repeatable)")
    return parser


def main(argv=None):
    options = build_parser().parse_args(argv)
    options.planned = options.planned or list(DEFAULT_PLANNED)
    try:
        return command_snapshot(options) if options.command == "snapshot" else command_check(options)
    except Unable as error:
        print("LIVE GUARD ERROR (not a pass): %s" % error, file=sys.stderr)
        return EXIT_UNABLE


if __name__ == "__main__":
    sys.exit(main())
