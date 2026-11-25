#!/usr/bin/env python3
"""Bump the pinned agent-kit (the agent-traces CLI install) to a release in one command: PR, checks, merge, scoped apply and install on this machine.

    agent_kit_bump.py X.Y.Z [--pr N] [--source DIR] [--poll SECONDS]

Playbook rule 7c57de5a: each agent-kit release bumps this pin. Personal profile only: it refuses on any other profile before it does anything.
The steps, and the step a stop names (the same shape as loop_engine_bump.py):

  profile  chezmoi's profile must be personal (read with dump-config, which runs no hook)
  pr       find the PR for branch agent-kit-vX.Y.Z; an open or merged one is resumed. With --pr N use PR N instead.
  publish  fresh worktree from origin/main: set the exact pin in package.json and regenerate package-lock.json; commit, push and
           open the PR, then write its agent record (`pr-record path dotfiles#N`: the principles table and the Decisions line; the
           description carries none of them). Nothing to do when origin/main already pins X.Y.Z.
           With --pr N: PR N is read first and refused (nothing pushed or merged) if it is from a fork or changes any file other
           than the two pin files and the Loop Engine mise config and skills. Then the same two files go on the head of open PR N
           (a Loop Engine bump PR, say), committed and pushed there with no force. Nothing is committed when its head already has the pin. A merged PR N goes straight to drift.
  checks   wait for the PR's checks; a red one stops it with the PR left open
  gates    ci-main-status --merge-gate dotfiles --pr <pr>, then pr-body-check dotfiles <pr> (which reads the agent record; one is written first
           if the PR has none, and an existing one is never overwritten); either one stops the merge.
           --pr lets this pin-fix PR merge into a main that is red only because this pin lags (ci-main-status docstring)
  merge    gh pr merge --squash --match-head-commit <the head read before the checks>; read the merge SHA
  drift    the PR changes both pin files and, at most, the Loop Engine's pins and skills (a combined bump; loop_engine_bump.py
           applies those); any other file stops it. Only the two pin files are targets. Stop on any live change the PR
           did not make; print the diff of the targets
  apply    chezmoi apply of exactly those two files (scripts excluded), then the install: chezmoi runs the 65 install script from the merge
           commit once (chezmoi apply of other explicit targets runs no script), so its run is recorded and chezmoi does not list it as pending
  verify   the version of @cartwmic/agent-kit installed under ~/.local/share/agent-kit is X.Y.Z

--pr N is for two releases that land close together: it puts both pins in one PR. Separate bump PRs also work, because
check-release-pins.py passes a lagging pin while an open dotfiles PR bumps it to exactly the latest release. To use --pr N, open
loop_engine_bump.py's PR, then run this with --pr N on it, so one PR carries both pins. Run the Loop Engine bump on that PR too
(it ignores the two agent-kit files). The push restarts the PR's checks. Do not run both scripts at
once on the same PR: each merges it.

Needs git, an authenticated gh (run from the source checkout, whose origin is the dotfiles repo), chezmoi, node and npm. Python 3
standard library. It prints the PR, the merge SHA and the installed version, and appends one JSON line per step to
$XDG_STATE_HOME/agent-kit-bump/log.jsonl (default ~/.local/state). A rerun picks up where it stopped. If origin/main already pins the
version and this machine has it installed, it does nothing.
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

KIT = "dot_local/share/agent-kit"  # the pin's source directory
KIT_DEST = ".local/share/agent-kit"  # where chezmoi puts it
PIN_FILES = ("package.json", "package-lock.json")
# loop_engine_bump.py's files (MISE_CONFIG, SKILLS there; tests/ci-main-status checks the copies match). A combined PR carries them too.
LOOP_ENGINE_MISE_CONFIG = "dot_config/mise/config.toml"
LOOP_ENGINE_SKILLS = "dot_local/share/agent-harness/canonical/skills"
INSTALL_TARGET = "65_agent_kit_install.sh"  # chezmoi target of run_onchange_after_65_agent_kit_install.sh.tmpl
PACKAGE = "@cartwmic/agent-kit"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
NAME = "agent_kit_bump"
PIN_FIX_RED = re.compile(r"^  pin-fix-red: ([0-9a-f]{40})$", re.M)  # the line ci-main-status --merge-gate dotfiles --pr N prints for each red the pin fix passes

# The design principles (~/.local/share/agent-harness/design-principles.md), one row each: name, result, evidence.
PRINCIPLES = [
    ("Composable components", "n/a", "No component is added or changed; the bump moves one version pin."),
    ("Kernel and adapters", "n/a", "No component is added or changed."),
    ("Clean architecture inside each component", "n/a", "No code layer is added or changed."),
    ("YAGNI and KISS", "pass", "The diff is the two pin files only: package.json and package-lock.json."),
    ("Written contracts and invariants", "n/a", "No contract changes."),
    ("Conformance suites", "n/a", "No adapter changes."),
    ("No cross-component imports", "n/a", "No import is added."),
    ("Judgment in agents, mechanism in code", "pass", "Every step is mechanical: the pin, the merge gates, the apply and the install."),
    ("Fix the cause; no arbitrary caps or unrequested defense in depth", "n/a", "No cap, threshold or extra guard is added."),
    ("Good enough for personal software", "pass", "Personal profile only; the install reads its registry token at run time."),
    ("Prior art before building", "n/a", "No new capability; it uses the published agent-kit package and the existing install script."),
    ("Verified from the outside", "pass", "tests/release-pins/test_agent_kit_bump.py drives the real script to the apply and the version read-back; after the merge the installed version is read back (log step verify)."),
    ("Resolve intent tensions and preserve design freedom", "n/a", "No promised outcome changes; the owner's standing grant lets the script merge an agent-kit release bump once its checks pass."),
    ("Logs that replay the user's experience and show how it is used", "pass", "One JSON line per step with its outcome, UTC time and seconds, tied by one run id, in ~/.local/state/agent-kit-bump/log.jsonl."),
    ("Fast proof", "n/a", "A pin bump runs no journey; the proof is the PR's CI run."),
    ("Built to last", "pass", "The script changes only the pins; nothing it replaces is left behind."),
]


class Stop(Exception):
    def __init__(self, step, message):
        super().__init__(message)
        self.step = step


class Log:
    """One JSON line per step, tied together by one run id."""

    def __init__(self, version):
        self.id = uuid.uuid4().hex[:12]
        self.version = version
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        self.path = state / "agent-kit-bump" / "log.jsonl"
        self.started = time.monotonic()

    def record(self, step, outcome, detail):
        now = time.monotonic()
        line = {"id": self.id, "version": self.version, "step": step, "outcome": outcome, "detail": detail,
                "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(now - self.started, 1)}
        self.started = now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
        print("[%s] %s: %s" % (NAME, step, detail), flush=True)


def run(cmd, step, cwd=None, env=None, check=True):
    # Every gh call here is on a merge path (reads too: pr list, pr checks, pr view). GH_URGENT=1 keeps the gh budget guard
    # from refusing them; GH_CALLER names this script in the gh wrapper's log.
    env = {**(os.environ if env is None else env), "GH_URGENT": "1", "GH_CALLER": NAME}
    try:
        result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
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


HOOKLESS_CONFIG = []  # the hook-free config file, once bump() has written it


def chezmoi(source, *args, step, check=True):
    config = ["--config", HOOKLESS_CONFIG[0], "--config-format", "json"] if HOOKLESS_CONFIG else []
    return run(["chezmoi", "--source", source, "--no-tty", *config, *args], step, check=check)


def chezmoi_config(source, step):
    """chezmoi's resolved config. dump-config reads no source state, so no hook runs."""
    return json.loads(chezmoi(source, "dump-config", "--format", "json", step=step).stdout)


def chezmoi_state_file(source, config, step):
    """The persistent state file (it records which run_onchange scripts have run). chezmoi keeps it next to the config file, so a copy of the config
    made in a temporary directory must name the real one, or a script run through the copy is forgotten with it. edit-config names the real config file
    when its editor is `echo`; like dump-config it reads no source state, so no hook runs."""
    if config.get("persistentState"):
        return config["persistentState"]
    named = run(["chezmoi", "--source", source, "--no-tty", "edit-config"], step, env={**os.environ, "EDITOR": "echo", "VISUAL": "echo"}).stdout.strip()
    return str(Path(named).parent / "chezmoistate.boltdb")


class Worktree:
    """A temporary detached worktree of the source checkout, removed on exit with any local branch made in it."""

    def __init__(self, source, rev, step):
        self.source, self.rev, self.step = source, rev, step
        self.parent = Path(tempfile.mkdtemp(prefix="agent-kit-bump-"))
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


def pr_body(version, head, day):
    """The PR description: what changes, why, how it was checked, what was proven and the risk. The bookkeeping (principles table, Decisions line) is the agent record, record_text."""
    return "\n".join([
        "## What changes",
        "",
        "Pins `%s` to %s in `package.json` and `package-lock.json`. Made by `agent_kit_bump.py %s`." % (PACKAGE, version, version),
        "",
        "## Why",
        "",
        "Each agent-kit release moves this pin, so the installed agent-traces CLI is the released one.",
        "",
        "## How it was checked",
        "",
        "The PR's checks and the script's merge gates (the main-branch status and the description and record check) must pass before the script merges. "
        "What ran, and what is left for after the merge, is under Proven.",
        "",
        "## Proven",
        "",
        "Before the PR, %s, head %s, the script set the exact pin %s in `package.json` and regenerated `package-lock.json` with `npm install --package-lock-only`." % (day, head, version),
        "",
        "Not yet run, after the merge: the scoped apply of these two files, the install (script 65) and a read-back that the installed version is %s; the script stops if it is not." % version,
        "",
        "## Risk and rollback",
        "",
        "Low. Both profiles get the pin; the script itself runs only on the personal profile, and `.chezmoiignore` leaves it out of the work profile. "
        "Revert the merge and re-run the install to go back.",
        "",
    ])


def record_text(version):
    """The PR's agent record (playbook rules ecd63156 and ccc6c94b): the design-principles table and the Decisions line the merge check reads."""
    rows = ["| %d | %s | %s | %s |" % (number, name, result, evidence) for number, (name, result, evidence) in enumerate(PRINCIPLES, 1)]
    return "\n".join([
        "Principles (`~/.local/share/agent-harness/design-principles.md`):",
        "",
        "| # | Principle | Result | Evidence |",
        "|---|---|---|---|",
        *rows,
        "",
        "Decisions: none material",
        "",
    ])


def ensure_record(source, number, version, step):
    """Write the PR's agent record unless it exists (`pr-record path` says where). Never overwrites: a resumed PR, or a PR carrying
    another script's pins (--pr N), keeps the record it has. Returns whether it wrote one."""
    path = Path(run(["pr-record", "path", "dotfiles#%d" % number], step, cwd=source).stdout.strip())
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record_text(version), encoding="utf-8")
    return True


def find_pr(source, branch):
    prs = json.loads(run(["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "number,state,url,mergeCommit"],
                          "pr", cwd=source).stdout)
    for state in ("MERGED", "OPEN", "CLOSED"):
        found = sorted((p for p in prs if p["state"] == state), key=lambda p: p["number"])
        if found:
            return found[-1]
    return None


def view_pr(source, number, step):
    """The PR as it is now, with its head commit: the head the merge must still match."""
    return json.loads(run(["gh", "pr", "view", str(number), "--json", "number,state,url,mergeCommit,headRefOid,headRefName"], step, cwd=source).stdout)


def set_pin(kit_dir, version):
    """Set the exact pin in package.json, then regenerate package-lock.json in a scratch copy (needs the registry)."""
    package = kit_dir / "package.json"
    data = json.loads(package.read_text(encoding="utf-8"))
    data["dependencies"][PACKAGE] = version
    package.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="agent-kit-lock-") as scratch:
        shutil.copy(package, scratch)
        shutil.copy(kit_dir / "package-lock.json", scratch)  # start from the current lock so unchanged packages stay put
        shutil.copy(kit_dir / "dot_npmrc", Path(scratch) / ".npmrc")
        env = dict(os.environ, NODE_AUTH_TOKEN=run(["gh", "auth", "token"], "publish").stdout.strip())
        run(["npm", "install", "--package-lock-only", "--no-audit", "--no-fund"], "publish", cwd=scratch, env=env)
        shutil.copy(Path(scratch) / "package-lock.json", kit_dir / "package-lock.json")


def publish(source, version, branch, log):
    """Set the pin on a fresh worktree of origin/main, commit, push and open the PR. None when origin/main already pins the version."""
    with Worktree(source, "origin/main", "publish") as wt:
        set_pin(wt.path / KIT, version)
        if not git(wt.path, "status", "--porcelain", step="publish").stdout.strip():
            log.record("publish", "ok", "origin/main already pins %s %s" % (PACKAGE, version))
            return None
        title = "chore(agent-kit): pin %s %s" % (PACKAGE, version)
        git(wt.path, "switch", "-q", "-C", branch, step="publish")
        wt.branch = branch
        git(wt.path, "add", KIT, step="publish")
        git(wt.path, "commit", "-q", "-m", title, step="publish")
        git(wt.path, "push", "-q", "--force", "origin", "HEAD:refs/heads/" + branch, step="publish")
        body = Path(wt.parent) / "pr-body.md"
        body.write_text(pr_body(version, git(wt.path, "rev-parse", "HEAD", step="publish").stdout.strip(),
                                datetime.now(timezone.utc).strftime("%Y-%m-%d")), encoding="utf-8")
        run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", body], "publish", cwd=source)
    pr = find_pr(source, branch)
    if pr is None:
        raise Stop("publish", "gh pr create succeeded but no PR is listed for %s" % branch)
    log.record("publish", "ok", "PR #%d %s" % (pr["number"], pr["url"]))
    ensure_record(source, pr["number"], version, "publish")
    return pr


def stop_on_outside(names, step):
    """Stop on any changed file that is not an agent-kit pin file or a Loop Engine pin or skill. The one rule for both the pre-push read of --pr N and pr_targets."""
    pins = ["%s/%s" % (KIT, name) for name in PIN_FILES]
    outside = [n for n in names if n not in pins and n != LOOP_ENGINE_MISE_CONFIG and not n.startswith(LOOP_ENGINE_SKILLS + "/")]
    if outside:
        raise Stop(step, "the PR changed files outside the agent-kit pins and the Loop Engine pins and skills: %s" % ", ".join(outside))


def check_pr_before_push(source, number):
    """Refuse PR `number` unless it is from this repository and changes only pins and skills. Runs before anything is pushed or merged,
    so a wrong N cannot merge an unrelated PR."""
    pull = json.loads(run(["gh", "pr", "view", str(number), "--json", "files,changedFiles,isCrossRepository"], "publish", cwd=source).stdout)
    if pull["isCrossRepository"]:
        raise Stop("publish", "PR #%d is from a fork; the pin is pushed only to a branch of this repository" % number)
    names = [f["path"] for f in pull["files"]]
    if pull["changedFiles"] != len(names):  # gh lists a PR's files in pages and may return only the first
        raise Stop("publish", "gh listed %d of PR #%d's %d changed files, so they cannot all be checked" % (len(names), number, pull["changedFiles"]))
    stop_on_outside(names, "publish")


def pin_pr(source, version, number, poll, log):
    """Put the pin on the head of PR `number` and return the PR as it reads after the push.

    A merged or closed PR is returned as it is. An open PR is first checked (check_pr_before_push): same repository, and only the pins
    and skills changed; otherwise it stops with nothing pushed. Then its head gets one commit of the two pin files pushed with no force (a
    rejected push stops it), unless the head already has the pin. The return waits until GitHub reports the pushed commit as the
    head, so the checks that follow are the new head's, not the old one's.
    """
    pr = view_pr(source, number, "publish")
    if pr["state"] != "OPEN":
        return pr
    check_pr_before_push(source, number)
    branch = pr["headRefName"]
    git(source, "fetch", "-q", "origin", branch, step="publish")
    with Worktree(source, pr["headRefOid"], "publish") as wt:
        set_pin(wt.path / KIT, version)
        if not git(wt.path, "status", "--porcelain", step="publish").stdout.strip():
            log.record("publish", "ok", "PR #%d (%s) already pins %s %s" % (number, branch, PACKAGE, version))
            return pr
        git(wt.path, "add", KIT, step="publish")
        git(wt.path, "commit", "-q", "-m", "chore(agent-kit): pin %s %s" % (PACKAGE, version), step="publish")
        pushed = git(wt.path, "rev-parse", "HEAD", step="publish").stdout.strip()
        git(wt.path, "push", "-q", "origin", "HEAD:refs/heads/" + branch, step="publish")
    for _ in range(20):
        pr = view_pr(source, number, "publish")
        if pr["headRefOid"] == pushed:
            log.record("publish", "ok", "pinned %s %s on PR #%d (%s) at %s" % (PACKAGE, version, number, branch, pushed))
            return pr
        time.sleep(poll)
    raise Stop("publish", "pushed %s to %s but PR #%d still reports head %s" % (pushed, branch, number, pr["headRefOid"]))


def wait_for_checks(source, pr, poll, log):
    reported = None
    while True:
        result = run(["gh", "pr", "checks", str(pr["number"]), "--json", "name,bucket"], "checks", cwd=source, check=False)
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
                raise Stop("checks", "PR #%d has red checks: %s; it is left open at %s" % (pr["number"], ", ".join(red), pr["url"]))
            log.record("checks", "ok", "%d check(s) passed" % len(checks))
            return
        state = "%d pending: %s" % (len(pending), ", ".join(pending)) if checks else "no checks reported yet"
        if state != reported:
            print("[%s] checks: waiting, %s" % (NAME, state), flush=True)
            reported = state
        time.sleep(poll)


def gates(source, pr, version, log):
    """The merge gates the playbook names. A red main stops the merge, and so does a PR whose description or agent record fails the body check.
    The record is written first when the PR has none (a PR made before this script wrote records, or one resumed).
    Returns the full shas of the reds the pin-fix rule passed: ci-main-status prints one `  pin-fix-red: <40-hex sha>` line for each, and the merge
    links exactly those (never a red that a test failure made, which the pin bump does not fix)."""
    wrote = ensure_record(source, pr["number"], version, "gates")
    main = run(["ci-main-status", "--merge-gate", "dotfiles", "--pr", str(pr["number"])], "gates", cwd=source, check=False)
    if main.returncode != 0:
        raise Stop("gates", "ci-main-status --merge-gate dotfiles --pr %d exited %d: %s" % (pr["number"], main.returncode, "\n".join(s for s in (main.stdout.strip(), main.stderr.strip()) if s)))
    pinned = PIN_FIX_RED.findall(main.stdout)   # stdout only, and only after exit 0
    body = run(["pr-body-check", "dotfiles", str(pr["number"])], "gates", cwd=source, check=False)
    if body.returncode != 0:
        shown = "\n".join(s for s in (body.stdout.strip(), body.stderr.strip()) if s)
        why = "an unresolved review thread on the PR refuses it (resolve each thread, then run the bump again): " if "unresolved review thread" in shown else ""   # pr-body-check runs ci-main-status --threads after the body check
        raise Stop("gates", "pr-body-check dotfiles %d exited %d: %s%s" % (pr["number"], body.returncode, why, shown))
    log.record("gates", "ok", "ci-main-status --merge-gate dotfiles --pr %d and pr-body-check dotfiles %d passed%s"
               % (pr["number"], pr["number"], " (the agent record was missing; wrote it)" if wrote else ""))
    return pinned


def merge(source, pr, pinned, log):
    """Squash-merge, only while the head is still the one the checks ran on, then read the merge SHA back.
    The squash body has one `Handles: <sha>` line for each red the pin fix passed, so ci-main-status counts those reds as handled once this merges.
    With none, there is no --body and the merge is the one it always was."""
    body = ["--body", "\n".join("Handles: " + sha for sha in pinned)] if pinned else []
    run(["gh", "pr", "merge", str(pr["number"]), "--squash", "--match-head-commit", pr["headRefOid"], *body], "merge", cwd=source)
    view = view_pr(source, pr["number"], "merge")
    if view["state"] != "MERGED" or not view.get("mergeCommit"):
        raise Stop("merge", "PR #%d is %s after gh pr merge" % (pr["number"], view["state"]))
    log.record("merge", "ok", "PR #%d merged as %s" % (pr["number"], view["mergeCommit"]["oid"]))
    return view


# --- the scoped apply --------------------------------------------------------------------------


def pr_targets(wt, sha, dest):
    """{destination: (source name, bytes before the PR or None, bytes after or None)} for the PR's two pin files.

    The PR may also carry the Loop Engine's pins and skills (a combined bump); loop_engine_bump.py applies those, so they are not
    targets. Any other file stops it.
    """
    names = [n for n in git(wt, "diff", "--name-only", "--no-renames", sha + "^", sha, step="drift").stdout.split("\n") if n]
    pins = sorted("%s/%s" % (KIT, name) for name in PIN_FILES)
    stop_on_outside(names, "drift")
    if sorted(n for n in names if n in pins) != pins:
        raise Stop("drift", "the PR must change both agent-kit pin files (%s); it changed %s" % (", ".join(pins), ", ".join(names) or "nothing"))
    return {dest / KIT_DEST / Path(n).name: (n, git_bytes(wt, "%s^:%s" % (sha, n)), git_bytes(wt, "%s:%s" % (sha, n))) for n in pins}


def check_drift(wt, dest, targets, log):
    """Stop unless each live target is the pre-PR or the PR content, origin/main still has the PR content, and nothing else is pending."""
    status = chezmoi(wt, "status", "-x", "scripts", dest / KIT_DEST, step="drift").stdout
    pending = [dest / line[3:] for line in status.splitlines() if line.strip()]
    outside = sorted(str(p) for p in pending if p not in targets)
    drifted, moved = [], []
    for destination, (name, before, after) in sorted(targets.items()):
        live = destination.read_bytes() if destination.is_file() else None
        if live != before and live != after:
            drifted.append(str(destination))
        if git_bytes(wt, "origin/main:%s" % name) != after:
            moved.append(name)
    print(chezmoi(wt, "diff", "--no-pager", "-x", "scripts", *sorted(targets), step="drift", check=False).stdout, end="", flush=True)
    if outside or drifted or moved:
        problems = []
        if outside:
            problems.append("changes the PR did not make: %s" % ", ".join(outside))
        if drifted:
            problems.append("live files that are neither the pre-PR nor the PR content: %s" % ", ".join(drifted))
        if moved:
            problems.append("origin/main changed these after the PR: %s" % ", ".join(moved))
        raise Stop("drift", "; ".join(problems) + "; nothing was applied")
    log.record("drift", "ok", "%d PR target(s), %d pending; nothing else pending under %s" % (len(targets), len(pending), dest / KIT_DEST))


def install(wt, dest, log):
    """Run the agent-kit install once, through chezmoi so its run is recorded: apply the 65 script's own target (chezmoi apply of other explicit
    targets runs no script). Without the record chezmoi would keep listing the script as pending after every bump."""
    result = chezmoi(wt, "apply", "--force", "--include", "scripts", dest / INSTALL_TARGET, step="install", check=False)
    print(result.stdout, end="", flush=True)
    if result.returncode != 0:
        raise Stop("install", "the agent-kit install failed (exit %d): %s" % (result.returncode, (result.stderr or result.stdout).strip()))
    log.record("install", "ok", "npm ci for the pinned %s" % PACKAGE)


def installed_version(dest):
    """The version of the pinned package that npm ci put under the agent-kit directory, or "(not installed)"."""
    path = dest / KIT_DEST / "node_modules" / PACKAGE / "package.json"
    return json.loads(path.read_text(encoding="utf-8")).get("version", "(no version)") if path.is_file() else "(not installed)"


def fast_forward_source(source, sha, log):
    """Move the chezmoi source checkout to the merge commit, so a later full apply cannot restore the old pins."""
    branch = git(source, "symbolic-ref", "-q", "--short", "HEAD", step="source", check=False).stdout.strip()
    if branch != "main":
        raise Stop("source", "the chezmoi source checkout %s is on %s, not main, so it cannot move to the merge commit %s. "
                   "The PR is merged and nothing was applied; check out main there and rerun this script."
                   % (source, branch or "a detached HEAD", sha))
    moved = git(source, "merge", "--ff-only", "-q", sha, step="source", check=False)
    if moved.returncode != 0:
        raise Stop("source", "cannot fast-forward the chezmoi source checkout %s to the merge commit %s: %s. The PR is merged "
                   "and nothing was applied; fix the checkout and rerun this script."
                   % (source, sha, (moved.stderr or moved.stdout).strip()))
    log.record("source", "ok", "chezmoi source checkout %s is at %s" % (source, sha))


def apply(source, dest, sha, pr, version, log):
    git(source, "fetch", "-q", "origin", step="drift")
    if git(source, "merge-base", "--is-ancestor", sha, "origin/main", step="drift", check=False).returncode != 0:
        raise Stop("drift", "merge commit %s is not on origin/main" % sha)
    fast_forward_source(source, sha, log)
    with Worktree(source, sha, "drift") as wt:
        targets = pr_targets(wt.path, sha, dest)
        check_drift(wt.path, dest, targets, log)
        # --force: check_drift showed each live target is the pre-PR or the PR content.
        chezmoi(wt.path, "apply", "--force", "-x", "scripts", *sorted(targets), step="apply")
        log.record("apply", "ok", "%d target(s): %s" % (len(targets), ", ".join(str(t) for t in sorted(targets))))
        install(wt.path, dest, log)
    installed = installed_version(dest)
    if installed != version:
        raise Stop("verify", "%s %s is installed here, not %s" % (PACKAGE, installed, version))
    log.record("verify", "ok", "PR #%d, merge %s, installed %s %s" % (pr["number"], sha, PACKAGE, installed))
    print("PR #%d %s\nmerge %s\ninstalled: %s %s" % (pr["number"], pr["url"], sha, PACKAGE, installed))


# --- main --------------------------------------------------------------------------------------


def bump(args, log):
    config = chezmoi_config(Path(args.source), "profile")
    profile = (config.get("data") or {}).get("profile")
    if profile != "personal":
        raise Stop("profile", "profile is %r; this script runs only on personal, and nothing was done" % profile)
    log.record("profile", "ok", "personal")
    config.pop("hooks", None)
    config["persistentState"] = chezmoi_state_file(Path(args.source), config, "profile")
    with tempfile.TemporaryDirectory(prefix=NAME + "-") as tmp:
        HOOKLESS_CONFIG[:] = [Path(tmp) / "chezmoi.json"]
        HOOKLESS_CONFIG[0].write_text(json.dumps(config))
        try:
            return bump_personal(args, Path(config["destDir"]), log)
        finally:
            HOOKLESS_CONFIG.clear()


def bump_personal(args, dest, log):
    source, version = Path(args.source), args.version
    branch = "agent-kit-v" + version
    git(source, "fetch", "-q", "origin", step="pr")
    if args.pr is not None:
        log.record("pr", "ok", "using PR #%d" % args.pr)
        pr = pin_pr(source, version, args.pr, args.poll, log)  # the head it returns is the one the checks must run on
    else:
        found = find_pr(source, branch)
        if found is not None:
            log.record("pr", "ok", "resuming PR #%d (%s)" % (found["number"], found["state"]))
            number = found["number"]
        else:
            log.record("pr", "ok", "no PR for %s yet" % branch)
            published = publish(source, version, branch, log)
            if published is None:
                installed = installed_version(dest)
                if installed != version:
                    raise Stop("apply", "origin/main already pins %s %s by a PR this script did not make, and this machine has %s; "
                               "apply it with --pr N for that PR" % (PACKAGE, version, installed))
                log.record("verify", "ok", "%s %s is already pinned and installed; nothing to do" % (PACKAGE, version))
                print("nothing to do: origin/main already pins %s %s and it is installed here" % (PACKAGE, version))
                return 0
            number = published["number"]
        pr = view_pr(source, number, "pr")  # read the head now: the merge must match the head the checks ran on
    if pr["state"] == "CLOSED":
        raise Stop("pr", "PR #%d (%s) was closed without merging: %s" % (pr["number"], pr["headRefName"], pr["url"]))
    if pr["state"] == "OPEN":
        wait_for_checks(source, pr, args.poll, log)
        pinned = gates(source, pr, version, log)
        pr = merge(source, pr, pinned, log)
    apply(source, dest, pr["mergeCommit"]["oid"], pr, version, log)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("version", help="agent-kit release, X.Y.Z")
    parser.add_argument("--pr", type=int, metavar="N",
                        help="put the pin on this existing PR (a Loop Engine bump PR, say) instead of opening agent-kit-vX.Y.Z; "
                             "after its merge apply and install from it")
    parser.add_argument("--source", default=os.environ.get("CHEZMOI_SOURCE_DIR") or str(Path.home() / ".local/share/chezmoi"),
                        help="chezmoi source checkout (default: CHEZMOI_SOURCE_DIR, else ~/.local/share/chezmoi)")
    parser.add_argument("--poll", type=float, default=float(os.environ.get("AGENT_KIT_BUMP_POLL_SECONDS", "30")),
                        help="seconds between check polls (default 30)")
    args = parser.parse_args(argv)
    args.version = args.version.lstrip("v")
    if not VERSION.match(args.version):
        parser.error("version must look like 1.2.3")
    log = Log(args.version)
    try:
        return bump(args, log)
    except Stop as stop:
        log.record(stop.step, "stopped", str(stop))
        print("[%s] stopped at step %s: %s" % (NAME, stop.step, stop), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
