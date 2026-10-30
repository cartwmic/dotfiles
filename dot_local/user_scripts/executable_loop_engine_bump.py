#!/usr/bin/env python3
"""Bump the Loop Engine pins and skills to a release in one command: PR, merge, scoped apply on this machine.

    loop_engine_bump.py vX.Y.Z [--source DIR]

This is playbook rule 7c57de5a as one command. Personal profile only: it refuses on any other profile before it does
anything. The steps, and the step a stop names:

  profile  chezmoi's profile must be personal (read with dump-config, which runs no source-state hook)
  pr       find the PR for branch loop-engine-vX.Y.Z; an open or merged one is resumed
  import   fresh worktree from origin/main; import_release_skills.py import TAG --pins --apply; orphans stop it
  publish  commit on loop-engine-vX.Y.Z, push, open the PR; the worktree is removed
  checks   wait for the PR's checks; a red one stops it with the PR left open
  merge    squash-merge and read the merge SHA
  drift    chezmoi status on the skills tree and the mise config; stop on any change the PR did not make
  apply    chezmoi apply of exactly the PR's targets; apply_harness_config.sh skills (skill links only, no MCP)
  install  mise install for the four tools
  verify   import_release_skills.py verify-deployed for the changed bundles; mise current equals the version

A rerun picks up where it stopped. If the version is already pinned on origin/main and the import changes nothing, it
does nothing. It prints the PR, the merge SHA and the installed versions, and appends one JSON line per step to
$XDG_STATE_HOME/loop-engine-bump/log.jsonl (default ~/.local/state).

Needs git, an authenticated gh (run from the source checkout, whose origin is the dotfiles repo), chezmoi and mise.
Python 3 standard library.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TOOLS = ("loop-engine", "lean-change", "policy-document", "research")
SKILLS = "dot_local/share/agent-harness/canonical/skills"
MISE_CONFIG = "dot_config/mise/config.toml"
IMPORT_TOOL = "dot_local/user_scripts/executable_import_release_skills.py"
HARNESS_TOOL = "dot_local/user_scripts/executable_apply_harness_config.sh"
TAG = re.compile(r"^v\d+\.\d+\.\d+$")
NAME = "loop_engine_bump"


class Stop(Exception):
    def __init__(self, step, message):
        super().__init__(message)
        self.step = step


class Log:
    """One JSON line per step, tied together by one run id."""

    def __init__(self, tag):
        self.id = uuid.uuid4().hex[:12]
        self.tag = tag
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        self.path = state / "loop-engine-bump" / "log.jsonl"
        self.started = time.monotonic()

    def record(self, step, outcome, detail):
        now = time.monotonic()
        line = {"id": self.id, "tag": self.tag, "step": step, "outcome": outcome, "detail": detail,
                "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(now - self.started, 1)}
        self.started = now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        print("[%s] %s: %s" % (NAME, step, detail), flush=True)


def run(cmd, step, cwd=None, env=None, check=True):
    try:
        result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True)
    except OSError as error:
        raise Stop(step, "cannot run %s: %s" % (cmd[0], error))
    if check and result.returncode != 0:
        raise Stop(step, "%s failed (exit %d): %s" % (" ".join(str(c) for c in cmd[:4]), result.returncode,
                                                      (result.stderr or result.stdout).strip()))
    return result


def git(source, *args, step, check=True):
    return run(["git", "-C", source, *args], step, check=check)


def git_bytes(source, spec):
    """File content at REV:PATH, or None if the path is not in that commit."""
    result = subprocess.run(["git", "-C", str(source), "show", spec], capture_output=True)
    return result.stdout if result.returncode == 0 else None


def chezmoi(source, *args, step, check=True):
    return run(["chezmoi", "--source", source, "--no-tty", *args], step, check=check)


def chezmoi_config(source, step):
    """(profile, destination) from chezmoi's config. dump-config reads no source state, so no source-state hook runs."""
    config = json.loads(chezmoi(source, "dump-config", "--format", "json", step=step).stdout)
    return (config.get("data") or {}).get("profile"), Path(config["destDir"])


class Worktree:
    """A temporary detached worktree of the source checkout, removed on exit with any local branch made in it."""

    def __init__(self, source, rev, step):
        self.source, self.rev, self.step = source, rev, step
        self.parent = Path(tempfile.mkdtemp(prefix="loop-engine-bump-"))
        self.path = self.parent / "wt"
        self.branch = None

    def __enter__(self):
        git(self.source, "worktree", "add", "-q", "--detach", self.path, self.rev, step=self.step)
        return self

    def __exit__(self, *_exc):
        git(self.source, "worktree", "remove", "--force", self.path, step=self.step, check=False)
        if self.branch:
            git(self.source, "branch", "-D", self.branch, step=self.step, check=False)
        shutil.rmtree(self.parent, ignore_errors=True)
        return False


# --- the PR ------------------------------------------------------------------------------------


def find_pr(source, branch):
    prs = json.loads(run(["gh", "pr", "list", "--head", branch, "--state", "all", "--json",
                          "number,state,url,mergeCommit"], "pr", cwd=source).stdout)
    for state in ("MERGED", "OPEN", "CLOSED"):
        found = sorted((p for p in prs if p["state"] == state), key=lambda p: p["number"])
        if found:
            return found[-1]
    return None


def publish(source, tag, branch, log):
    """Import into a fresh worktree from origin/main; commit, push and open the PR. None when nothing changes."""
    version = tag[1:]
    with Worktree(source, "origin/main", "import") as wt:
        result = run([sys.executable, wt.path / IMPORT_TOOL, "import", tag, "--source", wt.path, "--pins", "--apply"],
                     "import", check=False)
        print(result.stdout, end="", flush=True)
        if result.returncode == 3:
            orphans = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("ORPHAN")]
            raise Stop("import", "the tag leaves %d orphan file(s) in the bundles; pruning them is a person's call:\n  %s"
                       % (len(orphans), "\n  ".join(orphans)))
        if result.returncode != 0:
            raise Stop("import", (result.stderr or result.stdout).strip())
        changed = git(wt.path, "status", "--porcelain", step="import").stdout.splitlines()
        if not changed:
            log.record("import", "ok", "%s changes nothing on origin/main" % tag)
            return None
        log.record("import", "ok", "%d path(s) changed" % len(changed))
        title = "feat(loop-engine): import %s skills; bump pins to %s" % (tag, version)
        git(wt.path, "switch", "-q", "-C", branch, step="publish")
        wt.branch = branch
        git(wt.path, "add", "-A", step="publish")
        git(wt.path, "commit", "-q", "-m", title, step="publish")
        git(wt.path, "push", "-q", "--force", "origin", "HEAD:refs/heads/" + branch, step="publish")
        body = ("Import of the %s skill bundles and the four Loop Engine pins (%s), made by "
                "`loop_engine_bump.py %s` (playbook rule 7c57de5a).\n\n```\n%s```\n\n"
                "Profiles: both. The pins and canonical skills land on personal and axon-work-computer; the script "
                "applies them on personal only, and the work Mac gets them with its own chezmoi update.\n"
                % (tag, ", ".join(TOOLS), tag, result.stdout))
        run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body], "publish",
            cwd=source)
    pr = find_pr(source, branch)
    if pr is None:
        raise Stop("publish", "gh pr create succeeded but no PR is listed for %s" % branch)
    log.record("publish", "ok", "PR #%d %s" % (pr["number"], pr["url"]))
    return pr


def wait_for_checks(source, pr, poll, log):
    reported = None
    while True:
        result = run(["gh", "pr", "checks", str(pr["number"]), "--json", "name,bucket"], "checks", cwd=source,
                     check=False)
        try:
            checks = json.loads(result.stdout) if result.stdout.strip() else []
        except ValueError:
            raise Stop("checks", "unreadable gh pr checks output: %s" % (result.stderr or result.stdout).strip())
        if not checks and result.returncode != 0 and "no checks reported" not in result.stderr:
            raise Stop("checks", (result.stderr or result.stdout).strip())
        pending = sorted(c["name"] for c in checks if c["bucket"] == "pending")
        if checks and not pending:
            red = sorted("%s (%s)" % (c["name"], c["bucket"]) for c in checks if c["bucket"] in ("fail", "cancel"))
            if red:
                raise Stop("checks", "PR #%d has red checks: %s; it is left open at %s"
                           % (pr["number"], ", ".join(red), pr["url"]))
            log.record("checks", "ok", "%d check(s) passed" % len(checks))
            return
        state = "%d pending: %s" % (len(pending), ", ".join(pending)) if checks else "no checks reported yet"
        if state != reported:
            print("[%s] checks: waiting, %s" % (NAME, state), flush=True)
            reported = state
        time.sleep(poll)


def merge(source, pr, log):
    run(["gh", "pr", "merge", str(pr["number"]), "--squash"], "merge", cwd=source)
    view = json.loads(run(["gh", "pr", "view", str(pr["number"]), "--json", "number,state,url,mergeCommit"],
                          "merge", cwd=source).stdout)
    if view["state"] != "MERGED" or not view.get("mergeCommit"):
        raise Stop("merge", "PR #%d is %s after gh pr merge" % (pr["number"], view["state"]))
    log.record("merge", "ok", "PR #%d merged as %s" % (pr["number"], view["mergeCommit"]["oid"]))
    return view


# --- the scoped apply --------------------------------------------------------------------------


def pr_targets(wt, sha):
    """{destination: (source name, bytes before the PR or None, bytes after or None)} for every file the PR changed."""
    names = [n for n in git(wt, "diff", "--name-only", "--no-renames", sha + "^", sha, step="drift").stdout.split("\n") if n]
    outside = [n for n in names if n != MISE_CONFIG and not n.startswith(SKILLS + "/")]
    if outside:
        raise Stop("drift", "the PR changed files outside the pins and skills: %s" % ", ".join(outside))
    templates = [n for n in names if n.endswith(".tmpl")]
    if templates:
        raise Stop("drift", "the PR changed templates, which this check does not render: %s" % ", ".join(templates))
    destinations = [d for d in chezmoi(wt, "target-path", *[wt / n for n in names], step="drift").stdout.split("\n") if d]
    if len(destinations) != len(names):
        raise Stop("drift", "chezmoi target-path gave %d paths for %d files" % (len(destinations), len(names)))
    return {Path(d): (n, git_bytes(wt, "%s^:%s" % (sha, n)), git_bytes(wt, "%s:%s" % (sha, n)))
            for n, d in zip(names, destinations)}


def check_drift(wt, dest, targets, log):
    """Stop unless the only pending changes under the skills tree and the mise config are the PR's own."""
    skills_dest, mise_dest = dest / ".local/share/agent-harness/canonical/skills", dest / ".config/mise/config.toml"
    status = chezmoi(wt, "status", "-x", "scripts", skills_dest, mise_dest, step="drift").stdout
    pending = [dest / line[3:] for line in status.splitlines() if line.strip()]
    # A new bundle's directories are pending too; they are the PR's when a PR file is below them.
    outside = sorted(str(p) for p in pending if p not in targets and not any(p in t.parents for t in targets))
    drifted, moved = [], []
    for destination, (name, before, after) in sorted(targets.items()):
        live = destination.read_bytes() if destination.is_file() else None
        if live != before and live != after:
            drifted.append(str(destination))
        if git_bytes(wt, "origin/main:%s" % name) != after:
            moved.append(name)
    shown = outside + drifted if (outside or drifted or moved) else [str(p) for p in pending]
    if shown:
        print(chezmoi(wt, "diff", "--no-pager", "-x", "scripts", *shown, step="drift", check=False).stdout, end="", flush=True)
    if outside or drifted or moved:
        problems = []
        if outside:
            problems.append("changes the PR did not make: %s" % ", ".join(outside))
        if drifted:
            problems.append("live files that are neither the pre-PR nor the PR content: %s" % ", ".join(drifted))
        if moved:
            problems.append("origin/main changed these after the PR: %s" % ", ".join(moved))
        raise Stop("drift", "; ".join(problems) + "; nothing was applied")
    log.record("drift", "ok", "%d PR target(s), %d pending; no other change under the skills tree or the mise config"
               % (len(targets), len(pending)))
    return mise_dest


def installed_versions(dest):
    return {tool: run(["mise", "current", tool], "verify", cwd=dest, check=False).stdout.strip() or "(none)"
            for tool in TOOLS}


def apply(source, sha, pr, version, log):
    git(source, "fetch", "-q", "origin", step="drift")
    if git(source, "merge-base", "--is-ancestor", sha, "origin/main", step="drift", check=False).returncode != 0:
        raise Stop("drift", "merge commit %s is not on origin/main" % sha)
    with Worktree(source, sha, "drift") as wt:
        _profile, dest = chezmoi_config(wt.path, "drift")
        targets = pr_targets(wt.path, sha)
        mise_dest = check_drift(wt.path, dest, targets, log)
        # A new bundle's directories go first, one level each, so nothing outside the PR is applied.
        new_dirs = {d for t in targets for d in t.parents if dest in d.parents and not d.is_dir()}
        # --force: the drift check above showed each live target is the pre-PR or the PR content.
        chezmoi(wt.path, "apply", "--force", "--recursive=false", "-x", "scripts",
                *sorted(new_dirs, key=lambda d: len(d.parts)), *sorted(targets), step="apply")
        bundles = sorted({targets[t][0][len(SKILLS) + 1:].split("/")[0] for t in targets if t != mise_dest})
        if bundles:  # links every run, so a rerun repairs links a failed run left behind
            print(run(["sh", wt.path / HARNESS_TOOL, "skills"], "apply").stdout, end="", flush=True)
        log.record("apply", "ok", "%d target(s): %s" % (len(targets), ", ".join(str(t) for t in sorted(targets))))
        run(["mise", "install", *TOOLS], "install", cwd=dest)
        log.record("install", "ok", "mise install %s" % " ".join(TOOLS))
        if bundles:
            result = run([sys.executable, wt.path / IMPORT_TOOL, "verify-deployed", "--source", wt.path, *bundles],
                         "verify", check=False)
            print(result.stdout, end="", flush=True)
            if result.returncode != 0:
                raise Stop("verify", "verify-deployed found problems in %s" % ", ".join(bundles))
    versions = installed_versions(dest)
    wrong = sorted("%s %s" % (t, v) for t, v in versions.items() if v != version)
    if wrong:
        raise Stop("verify", "mise current is not %s for: %s" % (version, ", ".join(wrong)))
    installed = ", ".join("%s %s" % kv for kv in versions.items())
    log.record("verify", "ok", "PR #%d, merge %s, installed: %s" % (pr["number"], sha, installed))
    print("PR #%d %s\nmerge %s\ninstalled: %s" % (pr["number"], pr["url"], sha, installed))


# --- main --------------------------------------------------------------------------------------


def bump(args, log):
    source = Path(args.source)
    version, branch = args.tag[1:], "loop-engine-" + args.tag
    profile, dest = chezmoi_config(source, "profile")
    if profile != "personal":
        raise Stop("profile", "profile is %r; this script runs only on personal, and nothing was done" % profile)
    log.record("profile", "ok", "personal")
    git(source, "fetch", "-q", "origin", step="pr")
    pr = find_pr(source, branch)
    if pr is not None:
        log.record("pr", "ok", "resuming PR #%d (%s)" % (pr["number"], pr["state"]))
    else:
        log.record("pr", "ok", "no PR for %s yet" % branch)
        pr = publish(source, args.tag, branch, log)
        if pr is None:
            versions = installed_versions(dest)
            wrong = sorted("%s %s" % (t, v) for t, v in versions.items() if v != version)
            if wrong:
                raise Stop("apply", "%s is already pinned on origin/main by a PR this script did not make, and this "
                           "machine has %s; apply it by hand (agent-harness README, import section)"
                           % (args.tag, ", ".join(wrong)))
            log.record("verify", "ok", "%s is already pinned and installed; nothing to do" % args.tag)
            print("nothing to do: %s is already pinned on origin/main and installed here" % args.tag)
            return 0
    if pr["state"] == "CLOSED":
        raise Stop("pr", "PR #%d for %s was closed without merging: %s" % (pr["number"], branch, pr["url"]))
    if pr["state"] == "OPEN":
        wait_for_checks(source, pr, args.poll, log)
        pr = merge(source, pr, log)
    apply(source, pr["mergeCommit"]["oid"], pr, version, log)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("tag", help="Loop Engine release tag, vX.Y.Z")
    parser.add_argument("--source", default=os.environ.get("CHEZMOI_SOURCE_DIR") or str(Path.home() / ".local/share/chezmoi"),
                        help="chezmoi source checkout (default: CHEZMOI_SOURCE_DIR, else ~/.local/share/chezmoi)")
    parser.add_argument("--poll", type=float, default=float(os.environ.get("LOOP_ENGINE_BUMP_POLL_SECONDS", "30")),
                        help="seconds between check polls (default 30)")
    args = parser.parse_args(argv)
    if not TAG.match(args.tag):
        parser.error("tag must look like v1.2.3")
    log = Log(args.tag)
    try:
        return bump(args, log)
    except Stop as stop:
        log.record(stop.step, "stopped", str(stop))
        print("[%s] stopped at step %s: %s" % (NAME, stop.step, stop), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
