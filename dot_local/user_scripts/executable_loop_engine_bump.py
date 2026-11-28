#!/usr/bin/env python3
"""Bump the Loop Engine pins and skills to a release in one command: PR, merge, scoped apply on this machine.

    loop_engine_bump.py vX.Y.Z [--source DIR]

This is playbook rule 7c57de5a as one command. Personal profile only: it refuses on any other profile before it does
anything. The steps, and the step a stop names:

  profile  chezmoi's profile must be personal (read with dump-config, which runs no hook)
  pr       find the PR for branch loop-engine-vX.Y.Z; an open or merged one is resumed
  import   fresh worktree from origin/main; import_release_skills.py import TAG --pins --apply; orphans stop it
  publish  commit on loop-engine-vX.Y.Z, push, open the PR, then write its agent record (`pr-record path dotfiles#N`: the principles table
           and the Decisions line; the description carries none of them); the worktree is removed
  checks   wait for the PR's checks; a red one stops it with the PR left open
  gates    ci-main-status --merge-gate dotfiles --pr N (a red main stops it, unless this pin-fix PR is what turns it green)
           and pr-body-check dotfiles N (a bad description or record stops it). It reads the agent record; one is written first if the PR
           has none, and an existing one is never overwritten
  merge    squash-merge, only while the head is still the one the checks ran on; read the merge SHA
  drift    chezmoi status on the skills tree and the mise config (the file chezmoi manages: ~/.config/mise/config.toml, or on the agent
           host pod conf.d/container.toml); stop on any change the PR did not make
  apply    `dotfiles-apply --contains <merge sha>` of exactly the PR's targets: it asks the gate for a tested main commit that contains the merge,
           moves the chezmoi source checkout to that commit (never to an untested tip, so a later full apply cannot restore the old pins) and applies from
           it. While no tested commit contains the merge it refuses: this stops here with the PR merged, and a rerun picks up at this step.
           Then apply_harness_config.sh skills (skill links only, no MCP)
  install  mise install for the four tools
  verify   import_release_skills.py verify-deployed for the changed bundles; mise's active installed version is the version
  scripts  on the agent host pod only: dotfiles-apply runs its one pending script, 05_container_tools.sh, through chezmoi so its run is recorded (its steps are
           no-ops after the install above, and it checks that no mise tool is missing). It embeds a hash of the mise config, so without
           this run chezmoi would keep listing it as pending after every bump. Nothing runs on a machine whose `chezmoi status` does not
           list it (the Mac and omarchy leave the script out). No other script runs; a failure stops here and a rerun picks up here

A PR that also carries agent-kit's two pin files (a combined bump, opened when two releases landed close together) is fine: the
drift check and the apply here ignore those two files, and agent_kit_bump.py X.Y.Z --pr N applies them. Any other file outside
the pins and skills still stops it at drift.

Every later chezmoi command runs with a copy of the config that has no hooks, so no configured hook runs.
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
import shlex
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TOOLS = ("loop-engine", "lean-change", "policy-document", "bookends-check")
SKILLS = "dot_local/share/agent-harness/canonical/skills"
MISE_CONFIG = "dot_config/mise/config.toml"
# Container mode (the agent host pod; docs/container-mode.md): .chezmoiignore leaves ~/.config/mise/config.toml out and chezmoi renders the same
# pins into this file instead (dot_config/mise/conf.d/container.toml.tmpl). Which of the two a machine manages is chezmoi's answer, never assumed.
MISE_CONTAINER = "conf.d/container.toml"
# agent_kit_bump.py's two pin files (KIT, PIN_FILES there; tests/ci-main-status checks the copies match). One PR may carry both bumps
# when two releases land close together: this script leaves these files to agent_kit_bump.py and still stops on any other outsider.
AGENT_KIT_PINS = ("dot_local/share/agent-kit/package.json", "dot_local/share/agent-kit/package-lock.json")
IMPORT_TOOL = "dot_local/user_scripts/executable_import_release_skills.py"
HARNESS_TOOL = "dot_local/user_scripts/executable_apply_harness_config.sh"
# Container mode's run_onchange script (run_onchange_after_05_container_tools.sh.tmpl): its content embeds a hash of the mise pins, so a pin bump leaves it pending.
CONTAINER_TOOLS = "05_container_tools.sh"
TAG = re.compile(r"^v\d+\.\d+\.\d+$")
NAME = "loop_engine_bump"
PIN_FIX_RED = re.compile(r"^  pin-fix-red: ([0-9a-f]{40})$", re.M)  # the line ci-main-status --merge-gate dotfiles --pr N prints for each red the pin fix passes

# The design principles (~/.local/share/agent-harness/design-principles.md), one row each: name, result, evidence.
PRINCIPLES = [
    ("Composable components", "n/a", "No component is added; the import copies skill bundles and moves four pins."),
    ("Kernel and adapters", "n/a", "No component is added or changed."),
    ("Clean architecture inside each component", "n/a", "No code layer is added or changed."),
    ("YAGNI and KISS", "pass", "The apply writes only the PR's own targets; the drift check stops on anything else."),
    ("Written contracts and invariants", "n/a", "No contract changes."),
    ("Conformance suites", "n/a", "No adapter changes."),
    ("No cross-component imports", "n/a", "No import is added."),
    ("Judgment in agents, mechanism in code", "pass", "The import, the pins and the apply are mechanical; the skill text is the release's own."),
    ("Fix the cause; no arbitrary caps or unrequested defense in depth", "n/a", "No cap, threshold or extra guard is added."),
    ("Good enough for personal software", "pass", "Personal profile only for the apply; the work Mac takes the merged pins with its own chezmoi update."),
    ("Prior art before building", "n/a", "No new capability; the bundles come from the Loop Engine release."),
    ("Verified from the outside", "pass", "Before the merge the script compared every skill file with the release tag (the PR description's Proven section); after it, it runs verify-deployed on the changed bundles and reads the active mise versions back."),
    ("Resolve intent tensions and preserve design freedom", "n/a", "No promised outcome changes; the owner's standing grant lets the script merge a Loop Engine release bump once its checks pass."),
    ("Logs that replay the user's experience and show how it is used", "pass", "One JSON line per step with its outcome, UTC time and seconds, tied by one run id, in ~/.local/state/loop-engine-bump/log.jsonl."),
    ("Fast proof", "n/a", "The import runs no journey; the proof is the PR's CI run."),
    ("Built to last", "pass", "The script replaces the pins and shipped skills in place; nothing old is left behind."),
]


def record_text():
    """The PR's agent record (playbook rules ecd63156 and ccc6c94b): the design-principles table and the Decisions line the merge check reads."""
    rows = ["| %d | %s | %s | %s |" % (number, name, result, evidence) for number, (name, result, evidence) in enumerate(PRINCIPLES, 1)]
    return "\n".join(["Principles (`~/.local/share/agent-harness/design-principles.md`):", "", "| # | Principle | Result | Evidence |",
                      "|---|---|---|---|", *rows, "", "Decisions: none material", ""])


def ensure_record(source, number, step):
    """Write the PR's agent record unless it exists (`pr-record path` says where). Never overwrites: a resumed PR keeps the record it has.
    Returns whether it wrote one."""
    path = Path(run(["pr-record", "path", "dotfiles#%d" % number], step, cwd=source).stdout.strip())
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record_text(), encoding="utf-8")
    return True


def import_report(stdout):
    """The import tool's report for a reader: what each bundle did and the pin move. It stops before the tool's own "applied to <scratch dir>" and "next:" lines."""
    lines = stdout.splitlines()
    cut = next((i for i, line in enumerate(lines) if line.startswith("applied to ")), len(lines))
    return "\n".join(lines[:cut]) + "\n"


def pr_body(tag, report, head, day):
    """The PR description: what changes, why, how it was checked, what was proven and the risk. The bookkeeping (principles table, Decisions line)
    is the agent record, record_text. The report is cut at the import tool's own "applied to" line (import_report). Proven is prose with no job ids
    or tables (the deployed pr-body-check refuses both): the tag and pins lines the import printed are quoted inline."""
    lines = import_report(report).splitlines()
    checked = [line for line in lines if line.startswith(("tag ", "pins:"))]
    return "\n".join([
        "## What changes",
        "",
        "Imports the %s skill bundles and moves the four Loop Engine pins (%s) to %s. Made by `loop_engine_bump.py %s`. Every Loop Engine release updates the dotfiles pins and skills." % (tag, ", ".join(TOOLS), tag[1:], tag),
        "",
        "```",
        "\n".join(lines),
        "```",
        "",
        "## Why",
        "",
        "Each Loop Engine release moves these pins and the skills that ship with it, so the installed tools and skills are the released ones.",
        "",
        "## How it was checked",
        "",
        "The PR's checks and the script's merge gates (the main-branch status and the description and record check) must pass before the script merges. What ran, and what is left for after the merge, is under Proven.",
        "",
        "## Proven",
        "",
        "Before the PR, %s, head %s, the import tool compared every imported file with the release's tree hashes and moved the pins. It reported %s." % (day, head, " and ".join("`%s`" % line for line in checked) or "nothing it could quote"),
        "",
        "Not yet run, after the merge: the scoped apply of the PR's own files on the personal computer, `mise install`, and `import_release_skills.py verify-deployed` on the changed bundles with a read-back that the active version of each tool is %s." % tag[1:],
        "",
        "## Risk and rollback",
        "",
        "Low. Both profiles get the pins and skills; the script applies them on the personal profile only, and the work Mac gets them with its own chezmoi update. "
        "Revert the merge to go back.",
        "",
    ])


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
    # Every gh call here is on a merge path (reads too: pr list, pr checks, pr view). GH_URGENT=1 keeps the gh budget guard
    # from refusing them; GH_CALLER names this script in the gh wrapper's log.
    env = {**(os.environ if env is None else env), "GH_URGENT": "1", "GH_CALLER": NAME}
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
                          "number,state,url,mergeCommit,headRefOid"], "pr", cwd=source).stdout)
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
        body = pr_body(tag, result.stdout, git(wt.path, "rev-parse", "HEAD", step="publish").stdout.strip(),
                       datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", body], "publish",
            cwd=source)
    pr = find_pr(source, branch)
    if pr is None:
        raise Stop("publish", "gh pr create succeeded but no PR is listed for %s" % branch)
    log.record("publish", "ok", "PR #%d %s" % (pr["number"], pr["url"]))
    ensure_record(source, pr["number"], "publish")
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


def gates(source, pr, log):
    """The merge gates the playbook names. A red main stops the merge, and so does a PR whose description or agent record fails the body check.
    The record is written first when the PR has none (a PR made before this script wrote records, or one resumed).
    Returns the full shas of the reds the pin-fix rule passed: ci-main-status prints one `  pin-fix-red: <40-hex sha>` line for each, and the merge
    links exactly those (never a red that a test failure made, which the pin bump does not fix)."""
    wrote = ensure_record(source, pr["number"], "gates")
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
    view = json.loads(run(["gh", "pr", "view", str(pr["number"]), "--json", "number,state,url,mergeCommit"],
                          "merge", cwd=source).stdout)
    if view["state"] != "MERGED" or not view.get("mergeCommit"):
        raise Stop("merge", "PR #%d is %s after gh pr merge" % (pr["number"], view["state"]))
    log.record("merge", "ok", "PR #%d merged as %s" % (pr["number"], view["mergeCommit"]["oid"]))
    return view


# --- the scoped apply --------------------------------------------------------------------------


def mise_destination(wt, config_dest):
    """The mise pin file this machine manages: config_dest (~/.config/mise/config.toml), or on the agent host pod its conf.d/container.toml.
    chezmoi answers (`managed`): .chezmoiignore leaves exactly one of the two out. Stops when it is not exactly one."""
    candidates = [config_dest, config_dest.parent / MISE_CONTAINER]
    listed = {Path(line) for line in chezmoi(wt, "managed", "--include=files", "--path-style=absolute", *candidates, step="drift").stdout.split("\n") if line}
    managed = [c for c in candidates if c in listed]
    if len(managed) != 1:
        raise Stop("drift", "chezmoi manages %s of %s; expected exactly one" % (", ".join(str(c) for c in managed) or "neither", " and ".join(str(c) for c in candidates)))
    return managed[0]


def rendered_mise(wt, sha, mise_dest):
    """(bytes before the PR, bytes after) of the container mise file, as chezmoi renders it from the source at sha^ and at sha. It is a template of
    config.toml, so the PR's change to the pins reaches it only through the render."""
    def cat(tree):
        return chezmoi(tree, "cat", mise_dest, step="drift").stdout.encode("utf-8")
    with Worktree(wt, sha + "^", "drift") as before:
        return cat(before.path), cat(wt)


def pr_targets(wt, sha):
    """{destination: (source name, bytes before the PR or None, bytes after or None)} for every file the PR changed except agent-kit's two pins.
    The mise config's destination is the file this machine manages (mise_destination); on the pod its bytes are the rendered container file."""
    names = [n for n in git(wt, "diff", "--name-only", "--no-renames", sha + "^", sha, step="drift").stdout.split("\n")
             if n and n not in AGENT_KIT_PINS]
    if not names:
        raise Stop("drift", "the PR changes no Loop Engine pin or skill (agent-kit's pins are applied by agent_kit_bump.py)")
    outside = [n for n in names if n != MISE_CONFIG and not n.startswith(SKILLS + "/")]
    if outside:
        raise Stop("drift", "the PR changed files outside the pins and skills: %s" % ", ".join(outside))
    templates = [n for n in names if n.endswith(".tmpl")]
    if templates:
        raise Stop("drift", "the PR changed templates, which this check does not render: %s" % ", ".join(templates))
    destinations = [d for d in chezmoi(wt, "target-path", *[wt / n for n in names], step="drift").stdout.split("\n") if d]
    if len(destinations) != len(names):
        raise Stop("drift", "chezmoi target-path gave %d paths for %d files" % (len(destinations), len(names)))
    targets = {Path(d): (n, git_bytes(wt, "%s^:%s" % (sha, n)), git_bytes(wt, "%s:%s" % (sha, n)))
               for n, d in zip(names, destinations)}
    for config_dest, (name, _, _) in list(targets.items()):
        if name == MISE_CONFIG:
            mise_dest = mise_destination(wt, config_dest)
            if mise_dest != config_dest:
                del targets[config_dest]
                targets[mise_dest] = (name, *rendered_mise(wt, sha, mise_dest))
    return targets


def check_drift(wt, dest, targets, log):
    """Stop unless the only pending changes under the skills tree and the mise config are the PR's own."""
    skills_dest, mise_dest = dest / ".local/share/agent-harness/canonical/skills", mise_destination(wt, dest / ".config/mise/config.toml")
    status = chezmoi(wt, "status", "-x", "scripts", skills_dest, mise_dest, step="drift").stdout
    pending = [dest / line[3:] for line in status.splitlines() if line.strip()]
    # A new bundle's directories are pending too; they are the PR's when a PR file is below them.
    outside = sorted(str(p) for p in pending if p not in targets and not any(p in t.parents for t in targets))
    drifted, moved = [], []
    for destination, (name, before, after) in sorted(targets.items()):
        live = destination.read_bytes() if destination.is_file() else None
        if live != before and live != after:
            drifted.append(str(destination))
        if git_bytes(wt, "origin/main:%s" % name) != git_bytes(wt, "HEAD:%s" % name):  # the source file, not `after` (the pod's is rendered)
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
    """{tool: the active installed version, or "(not installed)"}, from one query of mise's installed inventory."""
    inventory = json.loads(run(["mise", "ls", "--installed", "--json"], "verify", cwd=dest).stdout or "{}")
    return {tool: next((e["version"] for e in inventory.get(tool, []) if e.get("active")), "(not installed)")
            for tool in TOOLS}


def deploy(sha, paths, step, leave=()):
    """Apply these destination paths through `dotfiles-apply --contains SHA`: it asks the gate for a tested main commit that contains the merge, moves the
    chezmoi source checkout to that commit and applies from it, and exits 1 when none does yet (or when anything else is pending, or an apply fails)."""
    # Under the hook-free config copy, so a configured read-source-state hook never runs here (dotfiles-apply refuses a config that has one).
    env = {**os.environ, "DOTFILES_APPLY_CHEZMOI_ARGS": "--config %s --config-format json" % shlex.quote(str(HOOKLESS_CONFIG[0]))} if HOOKLESS_CONFIG else None
    result = run(["dotfiles-apply", "--contains", sha, *(a for p in leave for a in ("--leave-pending", str(p))), *sorted(str(p) for p in paths)],
                 step, env=env, check=False)
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", file=sys.stderr, flush=True)  # what the command said in full: a script's own error comes before its last line
    if result.returncode != 0:
        said = (result.stderr or result.stdout).strip()
        again = "run this script again once that is settled"
        if "also pending" in result.stdout:  # a combined bump: the other tool's files came with the same merge, and neither tool may take the other's
            again = ("other files are pending that this tool does not apply (listed above). If this is a combined bump (the other tool's files came with "
                     "this merge), take the whole tested merge once with `dotfiles-apply --contains %s --whole-commit`, then run this script again. "
                     "If something else is pending (check `chezmoi status`), settle that first (`dotfiles-apply --contains %s --whole-commit` takes a tested merge whole; or name the pending paths yourself) and run this script again" % (sha, sha))
        raise Stop(step, "dotfiles-apply exited %d: %s. The PR is merged and nothing more was done; %s."
                   % (result.returncode, said.splitlines()[-1] if said else "no output", again))


def other_scripts(wt, dest, step, keep=()):
    """Destination paths of the scripts this merge leaves pending (their run_onchange hash moved with the PR's files), except `keep`. This tool does not run
    them: a later full apply does, from a tested commit. They are named to dotfiles-apply as left, so they do not stop it."""
    status = chezmoi(wt, "status", "--include", "scripts", step=step).stdout
    return [dest / line[3:] for line in status.splitlines() if len(line) > 3 and dest / line[3:] not in keep]


def run_pending_container_tools(wt, sha, dest, log):
    """On the agent host pod, run 05_container_tools.sh through chezmoi (dotfiles-apply) so its run is recorded. Nothing runs when `chezmoi status` does not list it."""
    pending = {line[3:] for line in chezmoi(wt, "status", "--include", "scripts", step="scripts").stdout.splitlines()}
    if CONTAINER_TOOLS not in pending:
        return
    deploy(sha, [dest / CONTAINER_TOOLS], "scripts", leave=other_scripts(wt, dest, "scripts", keep=[dest / CONTAINER_TOOLS]))
    log.record("scripts", "ok", "ran %s through chezmoi" % CONTAINER_TOOLS)


def apply(source, dest, sha, pr, version, log):
    git(source, "fetch", "-q", "origin", step="drift")
    if git(source, "merge-base", "--is-ancestor", sha, "origin/main", step="drift", check=False).returncode != 0:
        raise Stop("drift", "merge commit %s is not on origin/main" % sha)
    with Worktree(source, sha, "drift") as wt:
        targets = pr_targets(wt.path, sha)
        mise_dest = check_drift(wt.path, dest, targets, log)
        # The scripts the PR leaves pending stay so: the container script runs last, below, once mise has installed the tools; the others wait for a later
        # full apply. A new bundle's directories go first, inside the command, so nothing outside the PR is applied.
        deploy(sha, targets, "apply", leave=other_scripts(wt.path, dest, "apply"))
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
            raise Stop("verify", "mise has not installed %s as the active version of: %s" % (version, ", ".join(wrong)))
        installed = ", ".join("%s %s" % kv for kv in versions.items())
        log.record("verify", "ok", "PR #%d, merge %s, installed: %s" % (pr["number"], sha, installed))
        run_pending_container_tools(wt.path, sha, dest, log)
    print("PR #%d %s\nmerge %s\ninstalled: %s" % (pr["number"], pr["url"], sha, installed))


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
    source = Path(args.source)
    version, branch = args.tag[1:], "loop-engine-" + args.tag
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
        pinned = gates(source, pr, log)
        pr = merge(source, pr, pinned, log)
    apply(source, dest, pr["mergeCommit"]["oid"], pr, version, log)
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
