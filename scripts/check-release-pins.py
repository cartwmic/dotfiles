#!/usr/bin/env python3
"""Playbook 7c57de5a check: the Loop Engine and agent-kit pins must not lag the latest published release.

    python3 scripts/check-release-pins.py [--mise-config FILE] [--agent-kit-package FILE]

CI runs it as its own job, `release-pins`, so a lagging pin turns the run red without stopping the `tests` job.
A lagging pin passes while an open cartwmic/dotfiles PR into main changes that pin to exactly the latest release.
The PR's diff decides, not its title, and the check prints `pending bump #N: <tool> <pinned> -> <latest>`.
The open PRs are read only when a pin lags, so a green check makes no PR lookup. A lookup that fails never passes.

Exit 0: every checked pin equals its latest release, or lags only with an open bump PR (one notice per pin).
Exit 1: a pin lags with no open bump PR (one line per pin). Exit 2: a latest release or the open PRs could not be
read, so the check could not run; the message names the source and the cause. Nothing is skipped.

cartwmic/agent-kit is private and ships as a GitHub Packages npm package, so its tags are not readable with the
workflow's token (HTTP 404). The check reads the package's published versions instead, the same source the kit installs
from. In CI that needs `packages: read` on the job and the package's Actions access to include this repository. The PR
lookup needs `pull-requests: read`.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISE_PATH = "dot_config/mise/config.toml"
AGENT_KIT_PATH = "dot_local/share/agent-kit/package.json"
DOTFILES = "cartwmic/dotfiles"
LOOP_ENGINE_TOOLS = ("loop-engine", "lean-change", "policy-document", "bookends-check")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class PrLookupError(Exception):
    """GitHub could not say which open PRs bump a lagging pin, so the check cannot pass."""


def gh(*args):
    """Run gh; return (stdout, first line of its error or None)."""
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True)
    except OSError as error:
        return "", str(error)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        return "", lines[0] if lines else "gh exited %d" % done.returncode
    return done.stdout, None


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


def local_mise_pins(path):
    pins = parse_mise_pins(Path(path).read_text())
    for tool in LOOP_ENGINE_TOOLS:
        if tool not in pins:
            sys.exit("cannot read the %s pin from %s" % (tool, path))
    return pins


def local_agent_kit_pin(path):
    try:
        return json.loads(Path(path).read_text())["dependencies"]["@cartwmic/agent-kit"]
    except (KeyError, TypeError, ValueError):
        sys.exit("cannot read dependencies[\"@cartwmic/agent-kit\"] from %s" % path)


def open_dotfiles_prs():
    """The numbers of the open cartwmic/dotfiles PRs into main."""
    out, error = gh("pr", "list", "--repo", DOTFILES, "--base", "main", "--state", "open", "--limit", "1000",
                    "--json", "number")
    if error:
        raise PrLookupError("cannot read the open cartwmic/dotfiles PRs into main (%s)" % error)
    try:
        return [int(pr["number"]) for pr in json.loads(out)]
    except (ValueError, KeyError, TypeError):
        raise PrLookupError("cannot read the open cartwmic/dotfiles PRs into main (gh printed no PR numbers)")


def pr_diff(number):
    out, error = gh("pr", "diff", str(number), "--repo", DOTFILES, "--color", "never")
    if error:
        raise PrLookupError("cannot read the diff of cartwmic/dotfiles PR #%d (%s)" % (number, error))
    return out


def added_lines(diff, path):
    """The lines a PR diff adds to one file, without the leading +. Empty when the diff does not touch that file."""
    header = "diff --git a/%s b/%s" % (path, path)
    added, inside = [], False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            inside = line == header
        elif inside and line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return "\n".join(added)


def pins_added_by(diff):
    """{name: version} for each Loop Engine pin and the agent-kit pin that a PR diff adds.
    A pin the diff leaves alone is absent."""
    pins = parse_mise_pins(added_lines(diff, MISE_PATH))
    kit = re.search(r'^\s*"@cartwmic/agent-kit"\s*:\s*"([^"]+)"', added_lines(diff, AGENT_KIT_PATH), re.M)
    if kit:
        pins["agent-kit"] = kit.group(1)
    return pins


def pending_bumps(lagging):
    """{name: PR number} for each lagging pin that an open dotfiles PR into main changes to exactly the latest release.
    lagging maps name -> (pinned version, latest version, the line that says how to bump it). Raises PrLookupError when
    GitHub cannot say; every open PR is read, so one unreadable PR fails the check."""
    bumps = {}
    for number in open_dotfiles_prs():
        added = pins_added_by(pr_diff(number))
        for name, (_pinned, latest, _line) in lagging.items():
            if added.get(name) == latest:
                bumps.setdefault(name, number)
    return bumps


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mise-config", default=str(ROOT / MISE_PATH))
    parser.add_argument("--agent-kit-package", default=str(ROOT / AGENT_KIT_PATH))
    args = parser.parse_args()

    pins = local_mise_pins(args.mise_config)
    kit_pin = local_agent_kit_pin(args.agent_kit_package)

    le_latest, error = latest_loop_engine()
    if error:
        print("cannot read the latest cartwmic/loop-engine release (%s); the release pins were not checked" % error)
        return 2
    kit_latest, kit_error = latest_agent_kit()
    if kit_error:
        print("cannot read the published versions of the cartwmic/agent-kit package (%s); the release pins were not "
              "checked. In CI the job needs `packages: read` and the package's Actions access must include this "
              "repository." % kit_error)
        return 2

    lagging = {}
    for tool, version in pins.items():
        if version != le_latest:
            lagging[tool] = (version, le_latest,
                             "%s pin %s lags the latest release %s (cartwmic/loop-engine); bump it with "
                             "loop_engine_bump.py v%s (playbook 7c57de5a)" % (tool, version, le_latest, le_latest))
    if kit_pin != kit_latest:
        lagging["agent-kit"] = (kit_pin, kit_latest,
                                "agent-kit pin %s lags the latest release %s (cartwmic/agent-kit); bump it with "
                                "agent_kit_bump.py v%s, or with --pr N on a Loop Engine bump PR if that pin lags too "
                                "(playbook 7c57de5a)" % (kit_pin, kit_latest, kit_latest))

    if not lagging:
        print("OK: loop-engine pins at %s, agent-kit pin %s at latest %s" % (le_latest, kit_pin, kit_latest))
        return 0

    try:
        bumps = pending_bumps(lagging)
    except PrLookupError as error:
        print("\n".join(line for _pinned, _latest, line in lagging.values()))
        print("%s, so no pending bump could be checked and the lagging pins fail (playbook 7c57de5a)" % error)
        return 2

    lines, failed = [], False
    for name, (pinned, latest, line) in lagging.items():
        if name in bumps:
            lines.append("pending bump #%d: %s %s -> %s" % (bumps[name], name, pinned, latest))
        else:
            failed = True
            lines.append(line)
    if failed:
        print("\n".join(lines))
        return 1
    print("\n".join(lines + ["OK: every lagging pin has an open bump PR"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
