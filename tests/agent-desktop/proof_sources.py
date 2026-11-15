#!/usr/bin/env python3
"""Which source files bind a device's saved proof run, and their digest.

usage: proof_sources.py DEVICE      prints {"device", "files", "digest"} as JSON; exit 1 with a reason when nothing is selected

Devices and their files (paths are relative to the repo root, which is two levels above this file):
  omarchy   dot_local/bin/executable_agent-desktop
  mac-mini  every file whose relative path has 'agent-desktop' or 'agent_desktop' in it, outside tests/, docs/ and windows/,
            plus .chezmoiignore
  g14       every file under windows/

It reads the file system, not git: the same code runs in an old-tree copy that has no git. The digest is the sha256 of
one line per file, "RELPATH NUL FILE-SHA256 NEWLINE", in sorted path order. Nothing about the checkout location, time or
the machine goes into it.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

DEVICES = ("omarchy", "mac-mini", "g14")
LINUX_SCRIPT = "dot_local/bin/executable_agent-desktop"
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
MAC_EXCLUDED_TOP = {"tests", "docs", "windows"}
DEFAULT_ROOT = Path(__file__).resolve().parents[2]


WHERE = {"omarchy": LINUX_SCRIPT, "mac-mini": "agent-desktop files outside tests/, docs/, windows/", "g14": "windows/ is empty or missing"}


class NoSources(Exception):
    pass


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            yield full.relative_to(root).as_posix()


def selected_files(device, root=DEFAULT_ROOT):
    root = Path(root)
    if device == "omarchy":
        files = [LINUX_SCRIPT] if (root / LINUX_SCRIPT).is_file() else []
    elif device == "mac-mini":
        files = []
        for rel in _walk(root):
            if rel == ".chezmoiignore":
                files.append(rel)
            elif rel.split("/", 1)[0] not in MAC_EXCLUDED_TOP and ("agent-desktop" in rel or "agent_desktop" in rel):
                files.append(rel)
    elif device == "g14":
        files = [rel for rel in _walk(root) if rel.startswith("windows/")]
    else:
        raise ValueError("unknown device %r (one of %s)" % (device, ", ".join(DEVICES)))
    files = sorted(files)
    # .chezmoiignore alone is not a macOS source: with no agent-desktop file there is nothing to bind the run to
    if device == "mac-mini" and files == [".chezmoiignore"]:
        files = []
    if not files:
        raise NoSources("no source files for %s (%s)" % (device, WHERE[device]))
    return files


def digest(device, root=DEFAULT_ROOT):
    root = Path(root)
    files = selected_files(device, root)
    h = hashlib.sha256()
    for rel in files:
        h.update(rel.encode() + b"\0" + hashlib.sha256((root / rel).read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest(), files


def main(argv):
    if len(argv) != 2 or argv[1] not in DEVICES:
        sys.stderr.write("usage: proof_sources.py %s\n" % "|".join(DEVICES))
        return 2
    try:
        d, files = digest(argv[1])
    except NoSources as e:
        sys.stderr.write("proof_sources: %s\n" % e)
        return 1
    print(json.dumps({"device": argv[1], "files": files, "digest": d}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
