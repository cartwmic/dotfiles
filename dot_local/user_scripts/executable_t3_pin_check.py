#!/usr/bin/env python3
"""Check that the T3 on this machine and the T3 pinned for the agent pods are the same release; with --open-prs, open the bump PRs.

    t3_pin_check.py [--open-prs [--dry-run]] [--notify] [--dotfiles-source DIR] [--steward-repo DIR]

T3 refuses a link between two T3s of different versions ("The linked environment's answer did not match this version"). Three places
name a T3 release, and they must be the same:

  host       `t3 --version` on this machine (omarchy); T3 updates it, nothing here pins it
  dotfiles   [t3Pin] in .chezmoidata.toml on origin/main: the pods' T3 (install_t3.sh), a version and a sha256 for each CPU
  steward    the budget-steward Dockerfile on origin/main: t3_version and a sha256 for each CPU

Two copies of the pin stay, one in each repo. The steward image is built on the cluster from a commit cloned out of Gitea, where no dotfiles
checkout exists, so it cannot read dotfiles' pin without fetching an unpinned ref at build time. This script moves both copies together.

The pins are read from origin/main after a fetch, never from a working tree, which may be stale or hold other work.

Without --open-prs it only reports, and prints `in step` or `drift: <what differs>`.
Exit 0: in step (also: --open-prs opened the PRs; the drift stays until they merge). 1: drift. 3: a source could not be read (nothing is judged). 4: --open-prs refused because every repo that is behind already has its bump PR
(nothing was opened). 2: bad arguments.

With --open-prs, when the pins are behind the host, it opens one PR per repo that needs it, and never merges:
  - the sha256s come from the release's SHA256SUMS (the linux lines), not from any file it downloaded;
  - it decides per repo: a repo that already has an open bump PR for that version is done and gets no second one, a repo that is behind and has none gets one
    (so a run that failed half way is finished by the next run); it refuses (exit 4) only when every repo that is behind already has its PR;
  - it never downgrades: if a pin is newer than the host's T3, it says so and opens nothing.
--dry-run prints each diff and PR body and pushes and opens nothing. Each PR is made in a fresh worktree of origin/main, so a dirty checkout is not touched. The PR description says what changes, why, how it was checked and the risk. The design-principles table
and the Decisions line go in each PR's agent record (`pr-record path REPO#N`, the budget-steward PR included), which the merge checks read; a dry run prints the record too.

With --notify, drift (and a source that cannot be read) is also posted once a day to the coordinator inbox (source t3-pin-drift), so the coordinator sees it.
Every run appends one JSON line to $XDG_STATE_HOME/t3-pin-check/log.jsonl (default ~/.local/state).

Needs git, t3 and, for --open-prs, an authenticated gh and a git credential for the Gitea host. Python 3 standard library.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NAME = "t3_pin_check"
RELEASE_BASE = "https://github.com/pingdotgg/t3code/releases/download"
DOTFILES_PIN_FILE = ".chezmoidata.toml"
STEWARD_PIN_FILE = "Dockerfile"
ARCHES = ("x64", "arm64")
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
SHA = re.compile(r"^[0-9a-f]{64}$")

EXIT_IN_STEP, EXIT_DRIFT, EXIT_USAGE, EXIT_NOT_READ, EXIT_REFUSED = 0, 1, 2, 3, 4


class Stop(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# --- versions ----------------------------------------------------------------------------------


def version_key(text):
    """Semver precedence as a sort key: core numbers first, a release after its own prereleases, prerelease parts numeric when they are numbers."""
    match = VERSION.match(text)
    if not match:
        raise Stop(EXIT_NOT_READ, "%r is not a T3 version (expected X.Y.Z or X.Y.Z-prerelease)" % text)
    core = tuple(int(part) for part in match.groups()[:3])
    pre = match.group(4)
    if pre is None:
        return core, 1, ()
    # A number sorts before a word (semver): (0, n) < (1, word).
    return core, 0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))


def compare(a, b):
    ka, kb = version_key(a), version_key(b)
    return (ka > kb) - (ka < kb)


# --- reading the three places -------------------------------------------------------------------


def run(cmd, cwd=None, check=True, input_text=None, env=None):
    try:
        result = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, input=input_text, env=env,
                                stdin=None if input_text is not None else subprocess.DEVNULL)
    except OSError as error:
        raise Stop(EXIT_NOT_READ, "cannot run %s: %s" % (cmd[0], error))
    if check and result.returncode != 0:
        raise Stop(EXIT_NOT_READ, "%s failed (exit %d): %s" % (" ".join(str(c) for c in cmd[:4]), result.returncode,
                                                               (result.stderr or result.stdout).strip()))
    return result


def git(repo, *args, check=True):
    return run(["git", "-C", repo, *args], check=check)


def read_host():
    out = run(["t3", "--version"]).stdout.strip()
    match = re.match(r"^t3 v(\S+)$", out)
    if not match:
        raise Stop(EXIT_NOT_READ, "`t3 --version` printed %r, not `t3 v<version>`" % out)
    version_key(match.group(1))
    return match.group(1)


def fetch_main(repo, label):
    if not Path(repo).is_dir():
        raise Stop(EXIT_NOT_READ, "%s checkout %s does not exist" % (label, repo))
    git(repo, "fetch", "-q", "origin")


def check_pin(label, version, x64, arm64):
    version_key(version)
    for arch, sha in (("x64", x64), ("arm64", arm64)):
        if not SHA.match(sha or ""):
            raise Stop(EXIT_NOT_READ, "%s pin has no valid sha256 for %s: %r" % (label, arch, sha))
    return {"version": version, "x64": x64, "arm64": arm64}


def read_dotfiles_pin(source):
    fetch_main(source, "dotfiles")
    text = git(source, "show", "origin/main:" + DOTFILES_PIN_FILE).stdout
    pin = tomllib.loads(text).get("t3Pin")
    if not isinstance(pin, dict):
        raise Stop(EXIT_NOT_READ, "origin/main:%s has no [t3Pin] table" % DOTFILES_PIN_FILE)
    return check_pin("dotfiles", pin.get("version"), pin.get("sha256X64"), pin.get("sha256Arm64"))


STEWARD_VERSION = re.compile(r"^(?P<head>\s*t3_version=)(?P<value>[^;\s]+)(?P<tail>;)", re.M)
STEWARD_SHA = {
    "x64": re.compile(r"(?P<head>amd64\) t3_arch=x64; t3_sha256=)(?P<value>[0-9a-f]{64})(?P<tail>;;)"),
    "arm64": re.compile(r"(?P<head>arm64\) t3_arch=arm64; t3_sha256=)(?P<value>[0-9a-f]{64})(?P<tail>;;)"),
}


def steward_find(text, pattern, what):
    found = list(pattern.finditer(text))
    if len(found) != 1:
        raise Stop(EXIT_NOT_READ, "the steward Dockerfile has %d %s lines, expected exactly 1" % (len(found), what))
    return found[0]


def read_steward_pin(repo):
    fetch_main(repo, "budget-steward")
    text = git(repo, "show", "origin/main:" + STEWARD_PIN_FILE).stdout
    return check_pin("steward", steward_find(text, STEWARD_VERSION, "t3_version").group("value"),
                     steward_find(text, STEWARD_SHA["x64"], "amd64 t3_sha256").group("value"),
                     steward_find(text, STEWARD_SHA["arm64"], "arm64 t3_sha256").group("value"))


# --- the comparison -----------------------------------------------------------------------------


def assess(host, pins):
    """{status, behind, ahead, lines} for the host version and {repo: pin}. status is `in step`, `drift` or `ahead` (a pin is newer than the host)."""
    behind = sorted(r for r, p in pins.items() if compare(p["version"], host) < 0)
    ahead = sorted(r for r, p in pins.items() if compare(p["version"], host) > 0)
    lines = ["host runs %s" % host] + ["%s pins %s" % (r, p["version"]) for r, p in sorted(pins.items())]
    problems = ["%s is behind the host" % r for r in behind] + ["%s is ahead of the host" % r for r in ahead]
    same = sorted(pins)
    if not behind and not ahead and len({(p["x64"], p["arm64"]) for p in pins.values()}) > 1:
        problems.append("the pins name the same version with different sha256s (%s)" % ", ".join(same))
    if ahead:
        status = "ahead"
        problems.append("a pin is newer than the T3 on this machine: no downgrade is made, update this machine's T3 (t3 update) instead")
    else:
        status = "drift" if problems else "in step"
    return {"status": status, "behind": behind, "ahead": ahead, "problems": problems, "lines": lines}


# --- the release's SHA256SUMS --------------------------------------------------------------------


def release_sums(version, base):
    """The release's own SHA256SUMS, read and parsed; the sha256s come from this list and from nowhere else."""
    url = "%s/v%s/SHA256SUMS" % (base.rstrip("/"), version)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            text = response.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as error:
        raise Stop(EXIT_NOT_READ, "cannot read %s: %s" % (url, error))
    sums = {}
    for arch in ARCHES:
        want = "t3-%s-linux-%s.tar.gz" % (version, arch)
        found = [line.split()[0] for line in text.splitlines() if len(line.split()) == 2 and line.split()[1].lstrip("*") == want]
        if len(found) != 1 or not SHA.match(found[0]):
            raise Stop(EXIT_NOT_READ, "%s has %d usable lines for %s" % (url, len(found), want))
        sums[arch] = found[0]
    return sums


# --- the PRs -------------------------------------------------------------------------------------

PRINCIPLES = [
    ("Composable components", "n/a", "No component is added; one pin value is moved."),
    ("Kernel and adapters", "n/a", "No component is added or changed."),
    ("Clean architecture inside each component", "n/a", "No code layer is added or changed."),
    ("YAGNI and KISS", "pass", "Only the version and two sha256s change."),
    ("Written contracts and invariants", "n/a", "No contract changes."),
    ("Conformance suites", "n/a", "No adapter changes."),
    ("No cross-component imports", "n/a", "No import is added."),
    ("Judgment in agents, mechanism in code", "pass", "The values come from the checker, not from a person's copy."),
    ("Fix the cause; no arbitrary caps or unrequested defense in depth", "pass", "It stops the pods and the host drifting apart."),
    ("Good enough for personal software", "pass", "A one-value change, merged by the owner or the standing grant."),
    ("Prior art before building", "n/a", "No new capability."),
    ("Verified from the outside", "pass", "The sha256s are the linux lines of the release's SHA256SUMS; the install checks the archive against them."),
    ("Resolve intent tensions and preserve design freedom", "n/a", "No promised outcome changes."),
    ("Logs that replay the user's experience and show how it is used", "n/a", "No user action is added or changed."),
    ("Fast proof", "n/a", "The proof is the next pod start (dotfiles) or image build (steward)."),
    ("Built to last", "pass", "The old values are replaced in place."),
]


def record_text(decisions):
    """A bump PR's agent record (playbook rules ecd63156 and ccc6c94b): the design-principles table and the Decisions line. The PR description carries none of it."""
    rows = ["| %d | %s | %s | %s |" % (n, name, result, evidence) for n, (name, result, evidence) in enumerate(PRINCIPLES, 1)]
    return "\n".join(["Principles (`~/.local/share/agent-harness/design-principles.md`):", "", "| # | Principle | Result | Evidence |",
                      "|---|---|---|---|", *rows, "", "Decisions: " + decisions, ""])


def write_record(item, decisions):
    """Write the agent record of PR `item` (`REPO#N`; `pr-record path` says where) unless it exists. Never overwrites. Returns the path."""
    path = Path(run(["pr-record", "path", item]).stdout.strip())
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record_text(decisions), encoding="utf-8")
    return path


def sub_once(text, pattern, value, what):
    found = list(pattern.finditer(text))
    if len(found) != 1:
        raise Stop(EXIT_NOT_READ, "%s: expected exactly 1 %s line, found %d" % (what, what, len(found)))
    m = found[0]
    return text[:m.start("value")] + value + text[m.end("value"):]


def dotfiles_edit(text, version, sums):
    header = re.search(r"(?m)^\[t3Pin\][ \t]*$", text)
    if not header:
        raise Stop(EXIT_NOT_READ, "no [t3Pin] table in %s" % DOTFILES_PIN_FILE)
    head, sep, rest = text[:header.start()], header.group(0), text[header.end():]
    body, nxt, tail = re.split(r"(?m)^(\[)", rest, maxsplit=1) if re.search(r"(?m)^\[", rest) else (rest, "", "")
    for key, value in (("version", version), ("sha256X64", sums["x64"]), ("sha256Arm64", sums["arm64"])):
        body = sub_once(body, re.compile(r'(?m)^(?P<head>%s = ")(?P<value>[^"]*)(?P<tail>")' % key), value, "[t3Pin] " + key)
    return head + sep + body + nxt + tail


def steward_edit(text, version, sums):
    text = sub_once(text, STEWARD_VERSION, version, "t3_version")
    text = sub_once(text, STEWARD_SHA["x64"], sums["x64"], "amd64 t3_sha256")
    return sub_once(text, STEWARD_SHA["arm64"], sums["arm64"], "arm64 t3_sha256")


def remote_of(repo):
    """The URL as written in the config (remote get-url would show the insteadOf rewrite, which the tests use to point at local repos)."""
    return git(repo, "config", "--get", "remote.origin.url").stdout.strip()


def github_slug(url):
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise Stop(EXIT_NOT_READ, "origin %s is not a GitHub remote" % url)
    return match.group(1)


def gitea_api(url):
    override = os.environ.get("T3_PIN_CHECK_STEWARD_API")
    if override:
        return override.rstrip("/")
    match = re.match(r"^(https?://[^/]+)/([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise Stop(EXIT_NOT_READ, "origin %s is not an http(s) Gitea remote" % url)
    return "%s/api/v1/repos/%s" % (match.group(1), match.group(2))


def gitea_token(repo, url):
    """The Gitea token from the repo's own git credential helper. Never printed. None when there is none."""
    host = re.match(r"^(https?)://([^/]+)", url)
    if not host:
        return None
    result = run(["git", "-C", repo, "credential", "fill"], check=False, input_text="protocol=%s\nhost=%s\n\n" % host.groups(),
                 env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            return line[len("password="):]
    return None


def gitea_call(api, token, method, path, payload=None):
    request = urllib.request.Request(api + path, method=method, data=None if payload is None else json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", **({"Authorization": "token " + token} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode() or "null")
    except urllib.error.HTTPError as error:
        raise Stop(EXIT_NOT_READ, "Gitea %s %s failed: HTTP %d" % (method, path, error.code))
    except (urllib.error.URLError, OSError) as error:
        raise Stop(EXIT_NOT_READ, "Gitea %s %s failed: %s" % (method, path, error))


def bump_branch(version):
    """The one key that names a bump PR: its head branch. The branch the PR is made from and the test for an existing PR both come from here, so they cannot
    disagree. The whole version is in it, compared for equality, so 0.1.10 never matches 0.1.10-nightly.N (or 0.1.1). The title is display only."""
    return "t3-pin/" + version


def is_bump(version, head_branch):
    return head_branch == bump_branch(version)


def open_bump_dotfiles(slug, version):
    prs = json.loads(run(["gh", "pr", "list", "--repo", slug, "--state", "open", "--json", "number,url,title,headRefName"]).stdout)
    return [p["url"] for p in prs if is_bump(version, p["headRefName"])]


def open_bump_steward(api, token, version):
    prs = gitea_call(api, token, "GET", "/pulls?state=open&limit=50") or []
    return [p["html_url"] for p in prs if is_bump(version, p["head"]["ref"])]


class Worktree:
    def __init__(self, repo):
        self.repo = repo
        self.parent = Path(tempfile.mkdtemp(prefix=NAME + "-"))
        self.path = self.parent / "wt"

    def __enter__(self):
        git(self.repo, "worktree", "add", "-q", "--detach", self.path, "origin/main")
        return self

    def __exit__(self, *_exc):
        git(self.repo, "worktree", "remove", "--force", self.path, check=False)
        shutil.rmtree(self.parent, ignore_errors=True)
        return False


def publish(repo, file, edit, version, sums, title, extra, dry_run=False):
    """Commit the edit on t3-pin/<version> in a fresh worktree of origin/main and push it. Returns the branch. A dry run prints the diff and pushes nothing."""
    branch = bump_branch(version)
    with Worktree(repo) as wt:
        target = wt.path / file
        before = target.read_text()
        after = edit(before, version, sums)
        if after == before:
            raise Stop(EXIT_NOT_READ, "%s already holds %s on origin/main; nothing to change" % (file, version))
        target.write_text(after)
        if dry_run:
            print(git(wt.path, "diff", "--", file).stdout, end="")
            return branch
        git(wt.path, "switch", "-q", "-C", branch)
        git(wt.path, "add", file)
        git(wt.path, "commit", "-q", "-m", title + "\n\n" + extra)
        git(wt.path, "push", "-q", "--force", "origin", "HEAD:refs/heads/" + branch)
        git(wt.path, "switch", "-q", "--detach", "origin/main")
        git(repo, "branch", "-D", branch, check=False)
    return branch


def sums_text(version, sums):
    return "x64 %s, arm64 %s" % (sums["x64"], sums["arm64"])


BUMP_DECISIONS = "#3685"  # the decision that has the checker open these PRs


def open_dotfiles_pr(source, slug, host, pin, sums, dry_run=False):
    title = "t3 pin: %s" % host
    body = ("## What changes\n\nMoves `[t3Pin]` from %s to %s, so the agent pods run the same T3 as the host (T3 refuses a link between two versions). "
            "Made by `t3_pin_check.py --open-prs`; it does not merge.\n\n"
            "## Why\n\nThe agent pods and the host must run one T3 release. The budget-steward image pin moves in a matching PR in that repo.\n\n"
            "## How it was checked\n\nThe sha256s are the linux lines of the release's `SHA256SUMS` (%s), not a copy by hand. The install checks the archive against them, "
            "so the next pod start is the proof.\n\n"
            "## Risk and rollback\n\nLow. Both profiles get the pin; script 05 reads it on the agent pods, and hosts with no pin behave as before. Revert the merge to go back.\n"
            % (pin["version"], host, sums_text(host, sums)))
    branch = publish(source, DOTFILES_PIN_FILE, dotfiles_edit, host, sums, title, "sha256s: " + sums_text(host, sums), dry_run)
    if dry_run:
        return "(dry run) would open dotfiles PR %r from %s\n%s\nand write its agent record:\n%s" % (title, branch, body, record_text(BUMP_DECISIONS))
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
        handle.write(body)
    try:
        url = run(["gh", "pr", "create", "--repo", slug, "--base", "main", "--head", branch, "--title", title, "--body-file", handle.name]).stdout.strip()
    finally:
        os.unlink(handle.name)
    url = url.splitlines()[-1]
    write_record("%s#%s" % (slug.split("/")[1], url.rsplit("/", 1)[1]), BUMP_DECISIONS)
    return url


def open_steward_pr(repo, api, token, host, pin, sums, dry_run=False):
    title = "t3 pin: %s" % host
    body = ("## What changes\n\nMoves the T3 pin in the image from %s to %s, so the pod's T3 matches the host's (T3 refuses a link between two versions). "
            "Made by dotfiles' `t3_pin_check.py --open-prs`; it does not merge. A matching PR bumps `[t3Pin]` in dotfiles.\n\n"
            "## Why\n\nThe agent pods and the host must run one T3 release.\n\n"
            "## How it was checked\n\nThe sha256s are the linux lines of the release's `SHA256SUMS` (%s), not a copy by hand. The image build checks the archive against them, "
            "so the next image build is the proof.\n\n"
            "## Risk and rollback\n\nLow. Revert the merge to go back.\n" % (pin["version"], host, sums_text(host, sums)))
    branch = publish(repo, STEWARD_PIN_FILE, steward_edit, host, sums, title, "sha256s: " + sums_text(host, sums), dry_run)
    if dry_run:
        return "(dry run) would open steward PR %r from %s\n%s\nand write its agent record:\n%s" % (title, branch, body, record_text(BUMP_DECISIONS))
    made = gitea_call(api, token, "POST", "/pulls", {"base": "main", "head": branch, "title": title, "body": body})
    name = re.sub(r"\.git$", "", remote_of(repo).rstrip("/")).rsplit("/", 1)[1]  # the repo name, as the review folders and pr-record name it
    write_record("%s#%d" % (name, made["number"]), BUMP_DECISIONS)
    return made["html_url"]


def open_prs(args, host, pins, report, log):
    if report["status"] == "ahead":
        log("open-prs", "refused: a pin is newer than the host; no downgrade, nothing opened")
        print("[%s] no PRs opened: a pin is newer than this machine's T3 (%s), and a pin is never moved back" % (NAME, host))
        return EXIT_DRIFT
    sums = release_sums(host, args.release_base)
    todo = sorted(r for r, p in pins.items() if p["version"] != host or (p["x64"], p["arm64"]) != (sums["x64"], sums["arm64"]))
    if not todo:
        print("[%s] nothing to open: both pins already hold %s with the release's sha256s" % (NAME, host))
        return EXIT_IN_STEP
    slug = github_slug(remote_of(args.dotfiles_source))
    steward_url = remote_of(args.steward_repo)
    api, token = gitea_api(steward_url), gitea_token(args.steward_repo, steward_url)
    already = {"dotfiles": open_bump_dotfiles(slug, host), "steward": open_bump_steward(api, token, host)}
    # Decide per repo. A repo that already has its open bump PR for this version is done (a half-finished earlier run leaves exactly that); a repo that is
    # behind and has none gets one. Only when every behind repo already has its PR is there nothing to do, and that is the refusal (exit 4).
    states = {r: "PR open %s" % already[r][0] for r in todo if already[r]}
    missing = [r for r in ("steward", "dotfiles") if r in todo and r not in states]
    if not missing:
        summary = "; ".join("%s: %s" % (r, states[r]) for r in sorted(states))
        print("[%s] refused: a bump PR for %s is already open in every repo that is behind (%s)" % (NAME, host, summary), file=sys.stderr)
        log("open-prs", "refused: " + summary)
        return EXIT_REFUSED
    # The Gitea call needs a token from the credential helper, so it goes first: a failure there leaves no GitHub PR. If the GitHub call then fails, the next run
    # sees the steward PR as done and opens only the dotfiles one. Each result is printed as soon as it exists, so a later failure does not hide it.
    openers = {"steward": lambda: open_steward_pr(args.steward_repo, api, token, host, pins["steward"], sums, args.dry_run),
               "dotfiles": lambda: open_dotfiles_pr(args.dotfiles_source, slug, host, pins["dotfiles"], sums, args.dry_run)}
    for repo in missing:
        url = openers[repo]()
        states[repo] = ("would open: " if args.dry_run else "opened ") + url
        log("open-prs", "%s %s" % (repo, states[repo].splitlines()[0]))
        print("[%s] %s: %s" % (NAME, repo, states[repo]))
    for repo in sorted(r for r in states if r not in missing):
        print("[%s] %s: %s" % (NAME, repo, states[repo]))
    return EXIT_IN_STEP


# --- the coordinator inbox, the log, main ---------------------------------------------------------


def notify_inbox(state_dir, text, signature):
    """One line on the coordinator's inbox socket: the same protocol `coordinator schedules check` posts on. A repeat on the same UTC day is dropped by the key."""
    path = Path(state_dir) / "inbox.sock"
    event = {"source": "t3-pin-drift", "external_key": "t3-pin-drift:%s:%s" % (hashlib.sha256(signature.encode()).hexdigest()[:12],
                                                                              datetime.now(timezone.utc).strftime("%Y-%m-%d")),
             "payload": {"kind": "t3-pin-drift", "text": text}}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(str(path))
            sock.sendall((json.dumps(event) + "\n").encode())
            answer = json.loads(sock.makefile().readline() or "{}")
    except (OSError, ValueError) as error:
        return "not posted to the coordinator inbox (%s: %s)" % (path, error)
    return "posted to the coordinator inbox" if answer.get("ok") else "the inbox refused the event: %s" % answer.get("error")


def make_log():
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "t3-pin-check" / "log.jsonl"

    def write(step, detail):
        state.parent.mkdir(parents=True, exist_ok=True)
        with state.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "step": step, "detail": detail}) + "\n")
    return write


def main(argv=None):
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--open-prs", action="store_true", help="open one bump PR per repo whose pin is behind the host (never merges)")
    parser.add_argument("--dry-run", action="store_true", help="with --open-prs: print each diff and PR body; push and open nothing")
    parser.add_argument("--notify", action="store_true", help="on drift, post once a day to the coordinator inbox")
    parser.add_argument("--dotfiles-source", default=os.environ.get("CHEZMOI_SOURCE_DIR") or str(home / ".local/share/chezmoi"))
    parser.add_argument("--steward-repo", default=os.environ.get("T3_PIN_CHECK_STEWARD_REPO") or str(home / "git/budget-steward"))
    parser.add_argument("--release-base", default=os.environ.get("T3_PIN_CHECK_RELEASE_BASE") or RELEASE_BASE)
    parser.add_argument("--coordinator-state", default=os.environ.get("COORDINATOR_STATE_DIR") or str(home / ".local/share/coordinator"))
    args = parser.parse_args(argv)
    log = make_log()
    try:
        host = read_host()
        pins = {"dotfiles": read_dotfiles_pin(args.dotfiles_source), "steward": read_steward_pin(args.steward_repo)}
        report = assess(host, pins)
        for line in report["lines"]:
            print("[%s] %s" % (NAME, line))
        if report["status"] == "in step":
            print("in step")
            log("check", "in step at " + host)
            return EXIT_IN_STEP
        text = "drift: " + "; ".join(report["problems"])
        print(text)
        log("check", text)
        if args.notify:
            # The key names the host's version and each pin's, so one drift posts once a day and a new release is a new post.
            signature = "%s|%s" % (host, ",".join("%s=%s" % (r, p["version"]) for r, p in sorted(pins.items())))
            outcome = notify_inbox(args.coordinator_state, "T3 pin " + text + ". Fix: t3_pin_check.py --open-prs", signature + "|" + text)
            print("[%s] %s" % (NAME, outcome))
            log("notify", outcome)
        if args.open_prs:
            return open_prs(args, host, pins, report, log)
        return EXIT_DRIFT
    except Stop as stop:
        print("[%s] stopped: %s" % (NAME, stop), file=sys.stderr)
        log("stopped", str(stop))
        if args.notify and stop.code == EXIT_NOT_READ:  # a check that cannot see is as bad as drift: say so on the inbox too
            print("[%s] %s" % (NAME, notify_inbox(args.coordinator_state, "T3 pin check could not read a source: %s" % stop, "not-read: %s" % stop)))
        return stop.code


if __name__ == "__main__":
    sys.exit(main())
