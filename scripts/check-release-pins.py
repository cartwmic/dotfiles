#!/usr/bin/env python3
"""Playbook 7c57de5a check: the Loop Engine and agent-kit pins must not lag the latest published release.

    python3 scripts/check-release-pins.py [--mise-config FILE] [--agent-kit-package FILE]

Exit 0: every checked pin equals its latest release. Exit 1: a pin lags (one line per pin). Exit 2: the Loop Engine
release could not be read, so the check could not run. cartwmic/agent-kit is private and CI may have no token that
reads it: then a GitHub Actions warning is printed and only the Loop Engine pins are checked.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOP_ENGINE_TOOLS = ("loop-engine", "lean-change", "policy-document", "research", "bookends-check")
SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


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
    out, error = gh("api", "repos/cartwmic/agent-kit/tags", "--paginate", "--jq", ".[].name")
    if error:
        return None, error
    versions = [tuple(map(int, m.groups())) for m in map(SEMVER_TAG.match, out.split()) if m]
    if not versions:
        return None, "no vX.Y.Z tags"
    return ".".join(map(str, max(versions))), None


def mise_pins(path):
    text = Path(path).read_text()
    pins = {}
    for tool in LOOP_ENGINE_TOOLS:
        found = re.search(r'^%s = \{ version = "([^"]+)"' % re.escape(tool), text, re.M)
        if not found:
            sys.exit("cannot read the %s pin from %s" % (tool, path))
        pins[tool] = found.group(1)
    return pins


def agent_kit_pin(path):
    try:
        return json.loads(Path(path).read_text())["dependencies"]["@cartwmic/agent-kit"]
    except (KeyError, TypeError, ValueError):
        sys.exit("cannot read dependencies[\"@cartwmic/agent-kit\"] from %s" % path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mise-config", default=str(ROOT / "dot_config/mise/config.toml"))
    parser.add_argument("--agent-kit-package", default=str(ROOT / "dot_local/share/agent-kit/package.json"))
    args = parser.parse_args()

    pins = mise_pins(args.mise_config)
    kit_pin = agent_kit_pin(args.agent_kit_package)

    le_latest, error = latest_loop_engine()
    if error:
        print("cannot read the latest cartwmic/loop-engine release (%s); the release pins were not checked" % error)
        return 2
    kit_latest, kit_error = latest_agent_kit()

    lagging = []
    for tool, version in pins.items():
        if version != le_latest:
            lagging.append("%s pin %s lags the latest release %s (cartwmic/loop-engine); bump it with "
                           "loop_engine_bump.py v%s (playbook 7c57de5a)" % (tool, version, le_latest, le_latest))
    if kit_error:
        print("::warning::cannot read cartwmic/agent-kit tags (%s); the agent-kit pin was not checked" % kit_error)
    elif kit_pin != kit_latest:
        lagging.append("agent-kit pin %s lags the latest release %s (cartwmic/agent-kit); bump it with "
                       "agent_kit_bump.py v%s (playbook 7c57de5a)" % (kit_pin, kit_latest, kit_latest))

    if lagging:
        print("\n".join(lagging))
        return 1
    print("OK: loop-engine pins at %s%s" % (le_latest, "" if kit_error else ", agent-kit pin at %s" % kit_latest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
