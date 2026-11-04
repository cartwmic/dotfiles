#!/usr/bin/env python3
"""Bump the pinned agent-kit (the agent-traces CLI install) to a release and open the dotfiles PR.

    agent_kit_bump.py X.Y.Z [--source DIR]

Playbook rule 7c57de5a: each agent-kit release bumps this pin. In a fresh worktree of origin/main it sets the exact version in
dot_local/share/agent-kit/package.json, regenerates package-lock.json in a scratch copy (NODE_AUTH_TOKEN=$(gh auth token) npm install
--package-lock-only), commits on branch agent-kit-vX.Y.Z, pushes and opens the PR with the scoped apply and verify commands.
It does not merge or apply; the release job does that after the checks pass, under the dotfiles standing grant.
If origin/main already pins the version, it does nothing. Needs git, an authenticated gh, node and npm. Python 3 standard library.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = "dot_local/share/agent-kit"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
APPLY = "chezmoi apply ~/.local/bin/agent-traces ~/.local/share/agent-kit ~/65_agent_kit_install.sh"
VERIFY = "cd ~/.local/share/agent-kit && npm ls @cartwmic/agent-kit  # shows %s"


def run(cmd, cwd=None, env=None):
    result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("agent_kit_bump: %s failed (exit %d): %s" % (" ".join(str(c) for c in cmd[:4]), result.returncode,
                                                               (result.stderr or result.stdout).strip()))
    return result.stdout


def set_pin(kit_dir, version):
    """Set the exact pin in kit_dir/package.json and regenerate kit_dir/package-lock.json (needs the registry)."""
    package = Path(kit_dir) / "package.json"
    data = json.loads(package.read_text())
    data["dependencies"]["@cartwmic/agent-kit"] = version
    package.write_text(json.dumps(data, indent=2) + "\n")
    with tempfile.TemporaryDirectory(prefix="agent-kit-lock-") as scratch:
        shutil.copy(package, scratch)
        shutil.copy(Path(kit_dir) / "package-lock.json", scratch)  # start from the current lock so unchanged packages stay put
        shutil.copy(Path(kit_dir) / "dot_npmrc", Path(scratch) / ".npmrc")
        env = dict(os.environ, NODE_AUTH_TOKEN=run(["gh", "auth", "token"]).strip())
        run(["npm", "install", "--package-lock-only", "--no-audit", "--no-fund"], cwd=scratch, env=env)
        shutil.copy(Path(scratch) / "package-lock.json", Path(kit_dir) / "package-lock.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("version", help="agent-kit release, X.Y.Z")
    parser.add_argument("--source", default=os.environ.get("CHEZMOI_SOURCE_DIR") or str(Path.home() / ".local/share/chezmoi"),
                        help="chezmoi source checkout (default: CHEZMOI_SOURCE_DIR, else ~/.local/share/chezmoi)")
    args = parser.parse_args(argv)
    version = args.version.lstrip("v")
    if not VERSION.match(version):
        parser.error("version must look like 1.2.3")
    branch, source = "agent-kit-v" + version, args.source
    run(["git", "-C", source, "fetch", "-q", "origin"])
    parent = Path(tempfile.mkdtemp(prefix="agent-kit-bump-"))
    wt = parent / "wt"
    run(["git", "-C", source, "worktree", "add", "-q", "--detach", wt, "origin/main"])
    try:
        set_pin(wt / KIT, version)
        if not run(["git", "-C", wt, "status", "--porcelain"]).strip():
            print("nothing to do: origin/main already pins @cartwmic/agent-kit %s" % version)
            return 0
        title = "chore(agent-kit): pin @cartwmic/agent-kit %s" % version
        run(["git", "-C", wt, "switch", "-q", "-C", branch])
        run(["git", "-C", wt, "add", KIT])
        run(["git", "-C", wt, "commit", "-q", "-m", title])
        run(["git", "-C", wt, "push", "-q", "--force", "origin", "HEAD:refs/heads/" + branch])
        body = ("Pin `@cartwmic/agent-kit` to %s (package.json and package-lock.json), made by `agent_kit_bump.py %s` "
                "(playbook rule 7c57de5a).\n\nProfiles: both. The pin lands on personal and axon-work-computer; the install runs "
                "on personal only (`agentKit.enabled`), and the work Mac takes it with its own chezmoi update.\n\n"
                "Scoped apply on personal:\n```\n%s\n```\nVerify:\n```\n%s\n~/.local/bin/agent-traces review normalize <findings.json>\n```\n"
                % (version, version, APPLY, VERIFY % version))
        print(run(["gh", "pr", "create", "--repo", "cartwmic/dotfiles", "--base", "main", "--head", branch, "--title", title,
                   "--body", body], cwd=source).strip())
        return 0
    finally:
        run(["git", "-C", source, "worktree", "remove", "--force", wt])
        subprocess.run(["git", "-C", source, "branch", "-D", branch], capture_output=True)  # the local branch made in the worktree
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
