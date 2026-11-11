#!/usr/bin/env python3
"""Render every template (and .chezmoiignore) of two source trees as one OS and compare, for both desktop profiles.

Evidence that a change for another OS does not change what this OS renders. Not part of the CI suite (it needs a baseline checkout).

    git worktree add /tmp/dotfiles-base origin/main
    python3 tests/profiles/render_diff.py --base /tmp/dotfiles-base            # as darwin (default), both profiles
    python3 tests/profiles/render_diff.py --base /tmp/dotfiles-base --os linux

The comment lines of .chezmoiignore are not compared (only its patterns). Prints one line per file whose render differs (a template that fails in both trees with the same message counts as equal), then the
non-template source files that changed between the trees (those deploy byte-for-byte on every OS that does not ignore them).
Exit 0 when no template render differs, 1 otherwise. HOME is /Users/test (darwin) or /home/test (linux) for both trees.
"""
import argparse
import difflib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HEAD = Path(__file__).resolve().parents[2]
PROFILES = ("personal", "axon-work-computer")


def render(tree, text, profile, chezmoi_os, home, cfg):
    data = {"profile": profile, "chezmoi": {"os": chezmoi_os, "homeDir": home, "sourceDir": "/source"}}   # sourceDir fixed: the two trees live in different directories
    r = subprocess.run(["chezmoi", "--source", str(tree), "--config", str(cfg), "execute-template", "--override-data", json.dumps(data)],
                       input=text, capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": home})
    out = r.stdout if r.returncode == 0 else "RENDER FAILED: " + r.stderr.replace(str(tree), "<source>").strip()
    if text.lstrip().startswith("./example.chezmoi.yaml"):   # .chezmoiignore: the patterns are the contract, the comments are not
        out = "".join(line for line in out.splitlines(True) if line.strip() and not line.startswith("#"))
    return out


def sources(tree):
    out = [tree / ".chezmoiignore"]
    for path in sorted(tree.rglob("*.tmpl")):
        rel = path.relative_to(tree)
        if rel.parts[0] in (".git", "tests", "docs", "node_modules"):
            continue
        out.append(path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="a checkout of the baseline (for example origin/main)")
    ap.add_argument("--os", default="darwin", help="chezmoi.os to render as (default darwin)")
    args = ap.parse_args()
    base = Path(args.base).resolve()
    home = "/Users/test" if args.os == "darwin" else "/home/test"
    differ = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        checked = 0
        for profile in PROFILES:
            for path in sources(HEAD):
                rel = path.relative_to(HEAD)
                old_path = base / rel
                text_new = path.read_text(encoding="utf-8")
                if not old_path.exists():
                    print(f"{profile}: {rel}: new file (renders as {args.os}: {len(render(HEAD, text_new, profile, args.os, home, cfg))} bytes)")
                    continue
                new = render(HEAD, text_new, profile, args.os, home, cfg)
                old = render(base, old_path.read_text(encoding="utf-8"), profile, args.os, home, cfg)
                checked += 1
                if new != old:
                    differ += 1
                    print(f"DIFFERS {profile}: {rel}")
                    sys.stdout.writelines(list(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "base", "head", n=1))[:40])
        print(f"\n{checked} template renders compared as {args.os} ({len(PROFILES)} profiles): {differ} differ")
    changed = subprocess.run(["git", "-C", str(HEAD), "diff", "--name-status", "--no-renames", subprocess.check_output(["git", "-C", str(base), "rev-parse", "HEAD"], text=True).strip()],
                             capture_output=True, text=True).stdout.splitlines()
    print("\nsource files changed since the baseline (non-templates deploy byte-for-byte where not ignored):")
    for line in changed:
        print("  " + line)
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
