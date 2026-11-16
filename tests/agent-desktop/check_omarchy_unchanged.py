#!/usr/bin/env python3
"""The Omarchy script is what it was at the base commit.

usage: check_omarchy_unchanged.py SHA256
Renders ~/.local/bin/agent-desktop the way chezmoi would on personal Linux, in a scratch destination, and compares its
sha256 with SHA256 (the sha256 of the script at the base commit). Prints one fixed line and exits 0 when they match;
prints what differs to stderr and exits 1 otherwise. The fixed line is what lets the criterion say `old: same`.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def render():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: personal\n")
        override = json.dumps({"profile": "personal", "chezmoi": {"os": "linux"}})
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), "--override-data", override, "cat", str(home / ".local/bin/agent-desktop")],
                           capture_output=True, env=dict(os.environ, HOME=str(home)), timeout=120)
    if r.returncode:
        sys.exit("chezmoi cat failed: %s" % r.stderr.decode(errors="replace"))
    return r.stdout


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: check_omarchy_unchanged.py SHA256")
    got = hashlib.sha256(render()).hexdigest()
    if got != sys.argv[1]:
        sys.exit("the personal Linux render of ~/.local/bin/agent-desktop is sha256 %s, the base script is %s" % (got, sys.argv[1]))
    print("omarchy-script-unchanged")


if __name__ == "__main__":
    main()
