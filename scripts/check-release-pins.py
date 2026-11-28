#!/usr/bin/env python3
"""Playbook 7c57de5a check: the Loop Engine and agent-kit pins must follow the latest published release.

    python3 scripts/check-release-pins.py [--base SHA --head SHA] [--mise-config FILE] [--agent-kit-package FILE]

CI runs it as its own job, `release-pins`, in two modes.

On a pull request (--base and --head given) it judges only the pins the PR changes: a pin whose value at --head differs
from its value at the merge base of the two. A pin the PR does not touch is not its business, so a new release never
turns a PR red. With no pin changed it exits 0 and looks up no release. A changed pin must equal the latest release.
Exit 1: a changed pin is not the latest release (one line per pin). Exit 2: a release could not be read, or git could not
resolve the two commits, so the check could not run; the message names the cause. Nothing is skipped.

On main (a push or a manual run on main, no --base) a lagging pin does not turn the run red. The check opens one issue
labelled `pin-lag` that names each lagging pin and its latest release, keeps it up to date, and closes it when every pin
matches (exit 0). A run on any other branch (GITHUB_REF names it) changes nothing: the issue follows main's pins only.
Exit 2 only when the issue itself could not be written. A release it cannot read is a printed warning and exit 0. A pin missing
from a pin file stops the run with exit 1 (nothing is left to compare).

Every run appends one JSON line to $XDG_STATE_HOME/check-release-pins/log.jsonl (default ~/.local/state): the UTC time, mode,
commits, the pins it judged or found lagging, the issue action, the exit and the duration. CI keeps it as a workflow artifact.

cartwmic/agent-kit is private and ships as a GitHub Packages npm package, so its tags are not readable with the
workflow's token (HTTP 404). The check reads the package's published versions instead, the same source the kit installs
from. In CI that needs `packages: read` on the job and the package's Actions access to include this repository. Writing the
issue needs `issues: write`.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISE_PATH = "dot_config/mise/config.toml"
AGENT_KIT_PATH = "dot_local/share/agent-kit/package.json"
DOTFILES = "cartwmic/dotfiles"
LOOP_ENGINE_TOOLS = ("loop-engine", "lean-change", "policy-document", "bookends-check")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
LAG_LABEL = "pin-lag"
RECORD = {}  # what this run did, for its log line


def run(*command):
    """Run a command; return (stdout, first line of its error or None)."""
    try:
        done = subprocess.run(list(command), capture_output=True, text=True)
    except OSError as error:
        return "", str(error)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        return "", lines[0] if lines else "%s exited %d" % (command[0], done.returncode)
    return done.stdout, None


def gh(*args):
    return run("gh", *args)


def latest_loop_engine():
    out, error = gh("api", "repos/cartwmic/loop-engine/releases/latest", "--jq", ".tag_name")
    tag = out.strip()
    if error is None and not tag:
        error = "no tag_name in the latest release"
    return (tag.removeprefix("v"), error)


def latest_agent_kit():
    out, error = gh("api", "users/cartwmic/packages/npm/agent-kit/versions", "--paginate", "--jq", ".[].name")
    if error:
        return None, error
    versions = [tuple(map(int, m.groups())) for m in map(SEMVER.match, out.split()) if m]
    if not versions:
        return None, "no X.Y.Z versions"
    return ".".join(map(str, max(versions))), None


def parse_mise_pins(text):
    """{tool: version} for each Loop Engine tool the text pins. A tool it does not pin is left out."""
    pins = {}
    for tool in LOOP_ENGINE_TOOLS:
        found = re.search(r'^%s = \{ version = "([^"]+)"' % re.escape(tool), text, re.M)
        if found:
            pins[tool] = found.group(1)
    return pins


def parse_kit_pin(text):
    """The agent-kit version a package.json text pins, or None when it does not."""
    try:
        return json.loads(text)["dependencies"]["@cartwmic/agent-kit"]
    except (KeyError, TypeError, ValueError):
        return None


def local_pins(mise_path, kit_path):
    """{name: version} for the four Loop Engine tools and agent-kit, read from the files. A missing pin ends the run."""
    pins = parse_mise_pins(Path(mise_path).read_text())
    for tool in LOOP_ENGINE_TOOLS:
        if tool not in pins:
            sys.exit("cannot read the %s pin from %s" % (tool, mise_path))
    kit = parse_kit_pin(Path(kit_path).read_text())
    if kit is None:
        sys.exit("cannot read dependencies[\"@cartwmic/agent-kit\"] from %s" % kit_path)
    return {**pins, "agent-kit": kit}


def pins_at(rev):
    """{name: version} for the pins that exist in the two pin files at a commit. A file or pin it lacks is left out."""
    pins = {}
    for path, parse in ((MISE_PATH, parse_mise_pins), (AGENT_KIT_PATH, lambda text: {"agent-kit": parse_kit_pin(text)})):
        text, _error = run("git", "show", "%s:%s" % (rev, path))
        pins.update({name: version for name, version in parse(text).items() if version})
    return pins


def changed_pins(base, head):
    """({name: version} that --head sets differently from the merge base, [pins it removes], short merge base), or raises ValueError."""
    merge_base, error = run("git", "merge-base", base, head)
    if error:
        raise ValueError("cannot find the merge base of %s and %s (%s); the checkout needs the full history"
                         % (base[:12], head[:12], error))
    merge_base = merge_base.strip()
    before, after = pins_at(merge_base), pins_at(head)
    changed = {name: version for name, version in after.items() if before.get(name) != version}
    return changed, sorted(name for name in before if name not in after), merge_base[:12]


def latest_release(name):
    """(latest version, error) of the release a pin follows."""
    return latest_agent_kit() if name == "agent-kit" else latest_loop_engine()


def bump_hint(name, latest):
    if name == "agent-kit":
        return "bump it with agent_kit_bump.py v%s, or with --pr N on a Loop Engine bump PR if that pin lags too" % latest
    return "bump it with loop_engine_bump.py v%s" % latest


def judge_pull_request(base, head):
    RECORD.update(mode="pull_request", base=base, head=head)
    try:
        changed, removed, merge_base = changed_pins(base, head)
    except ValueError as error:
        print(error)
        return 2
    RECORD.update(changed=sorted(changed), removed=removed)
    lines, failed = ["%s pin removed by this PR; a pin file without it cannot be checked" % name for name in removed], bool(removed)
    if not changed and not removed:
        print("OK: this PR changes no pin (compared with the merge base %s), so no release was looked up" % merge_base)
        return 0
    for name, version in changed.items():
        latest, error = latest_release(name)
        if error:
            print("cannot read the latest %s release (%s); the %s pin this PR sets to %s was not checked"
                  % (name, error, name, version))
            return 2
        if version == latest:
            lines.append("OK: this PR sets the %s pin to %s, the latest release" % (name, version))
        else:
            failed = True
            lines.append("%s pin set to %s by this PR, but the latest release is %s; %s"
                         % (name, version, latest, bump_hint(name, latest)))
    print("\n".join(lines))
    return 1 if failed else 0


def lag_issues():
    """([{number, title, body}] of the open pin-lag issues, error or None)."""
    out, error = gh("issue", "list", "--repo", DOTFILES, "--label", LAG_LABEL, "--state", "open", "--limit", "100",
                    "--json", "number,title,body")
    if error:
        return [], error
    try:
        return list(json.loads(out)), None
    except (ValueError, TypeError):
        return [], "gh printed no issue list"


def lag_text(lagging):
    """(title, body) of the issue for these lagging pins: {name: (pinned, latest)}."""
    title = "Pin lag: " + ", ".join("%s %s -> %s" % (name, pinned, latest) for name, (pinned, latest) in lagging.items())
    lines = ["%s: pinned %s, latest release %s; %s." % (name, pinned, latest, bump_hint(name, latest))
             for name, (pinned, latest) in lagging.items()]
    body = ("\n".join(lines) + "\n\nOpened by `scripts/check-release-pins.py` on a main run. It updates this issue while a pin "
            "lags and closes it when every pin matches its latest release.")
    return title, body


def sync_lag_issue(lagging):
    """Open or update the one pin-lag issue while a pin lags, close it when none does. Returns an error message or None."""
    issues, error = lag_issues()
    if error:
        return "cannot read the open %s issues (%s)" % (LAG_LABEL, error)
    if not lagging:
        for issue in issues:
            _out, error = gh("issue", "close", str(issue["number"]), "--repo", DOTFILES, "--comment",
                             "Every pin matches its latest release.")
            if error:
                return "cannot close issue #%d (%s)" % (issue["number"], error)
            print("closed pin-lag issue #%d" % issue["number"])
            RECORD["issue"] = "closed #%d" % issue["number"]
        return None
    title, body = lag_text(lagging)
    if issues:
        current = issues[0]
        if (current["title"], current["body"]) == (title, body):
            print("pin-lag issue #%d is up to date" % current["number"])
            RECORD["issue"] = "unchanged #%d" % current["number"]
            return None
        _out, error = gh("issue", "edit", str(current["number"]), "--repo", DOTFILES, "--title", title, "--body", body)
        if error:
            return "cannot update issue #%d (%s)" % (current["number"], error)
        print("updated pin-lag issue #%d" % current["number"])
        RECORD["issue"] = "updated #%d" % current["number"]
        return None
    _out, error = gh("label", "create", LAG_LABEL, "--repo", DOTFILES, "--force", "--color", "FBCA04",
                     "--description", "A Loop Engine or agent-kit pin lags its latest release")
    if error:
        return "cannot create the %s label (%s)" % (LAG_LABEL, error)
    out, error = gh("issue", "create", "--repo", DOTFILES, "--label", LAG_LABEL, "--title", title, "--body", body)
    if error:
        return "cannot open the pin-lag issue (%s)" % error
    print("opened pin-lag issue %s" % out.strip())
    RECORD["issue"] = "opened " + out.strip().rsplit("/", 1)[-1]
    return None


def judge_main(pins):
    ref = os.environ.get("GITHUB_REF", "")
    RECORD.update(mode="main", ref=ref)
    if ref and ref != "refs/heads/main":
        print("not main (%s): the pin-lag issue follows main's pins only, so nothing was checked or changed" % ref)
        return 0
    le_latest, error = latest_loop_engine()
    if error:
        print("warning: cannot read the latest cartwmic/loop-engine release (%s); the release pins were not checked" % error)
        return 0
    kit_latest, kit_error = latest_agent_kit()
    if kit_error:
        print("warning: cannot read the published versions of the cartwmic/agent-kit package (%s); the release pins were "
              "not checked. In CI the job needs `packages: read` and the package's Actions access must include this "
              "repository." % kit_error)
        return 0
    lagging = {name: (version, kit_latest if name == "agent-kit" else le_latest) for name, version in pins.items()
               if version != (kit_latest if name == "agent-kit" else le_latest)}
    RECORD["lagging"] = sorted(lagging)
    if lagging:
        print("\n".join("%s pin %s lags the latest release %s" % (name, pinned, latest)
                        for name, (pinned, latest) in lagging.items()))
    else:
        print("OK: loop-engine pins at %s, agent-kit pin %s at latest %s" % (le_latest, pins["agent-kit"], kit_latest))
    error = sync_lag_issue(lagging)
    if error:
        print("%s, so the pin-lag issue is not up to date" % error)
        return 2
    return 0


def write_log(code, began):
    path = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "check-release-pins" / "log.jsonl"
    record = {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "action": "check-release-pins", **RECORD,
              "exit": code, "duration_ms": round((time.monotonic() - began) * 1000)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as error:
        print("cannot write the run log %s (%s)" % (path, error))


def main():
    began = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="a pull request's base commit; with --head, judge only the pins the PR changes")
    parser.add_argument("--head", help="a pull request's head commit")
    parser.add_argument("--mise-config", default=str(ROOT / MISE_PATH))
    parser.add_argument("--agent-kit-package", default=str(ROOT / AGENT_KIT_PATH))
    args = parser.parse_args()
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head go together")
    code = judge_pull_request(args.base, args.head) if args.base else judge_main(local_pins(args.mise_config, args.agent_kit_package))
    write_log(code, began)
    return code


if __name__ == "__main__":
    sys.exit(main())
