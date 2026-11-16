#!/usr/bin/env python3
"""Live proof for ci-main-status: a job no runner picked up reads as untested; a real failure still reads as red.

Read-only: it calls `gh run view` and `gh api` for past dotfiles runs and runs the tool's own commands. It loads the
tool by path (default the installed ~/.local/bin/ci-main-status) and calls its classifier on the past attempts, then
prints the line the tool prints for them. It exercises the classifier and the line, not a past main state: the CLI
reads main as it is now, and those runs are in the past.

usage: python3 tests/ci-main-status/live_proof.py [path-to-ci-main-status]
Expect: 2 attempts that read UNTESTED with the job mise-tests, 1 that reads RED, and exit 0.
"""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

TOOL = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / ".local/bin/ci-main-status")
REPO = "cartwmic/dotfiles"
# (run id, attempt, head sha, expected)
CASES = [
    (43918034651, 1, "15647ad76cb5a25b7b4f4bb8fe1988148d708b84", "untested"),   # macOS job cancelled, no runner; the rerun then passed
    (43908362005, 1, "d6084703afaf82b8ed619d3bbce80f0fa053aece", "untested"),   # the same, at d608470
    (43916950669, 2, "2ee6951b47b3cc8c778266d0c3d06fd587aea2a7", "failure"),    # the release-pins failure in `tests`
]


def load(path):
    loader = importlib.machinery.SourceFileLoader("ci_main_status_under_proof", path)
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def main():
    tool = load(TOOL)
    if not hasattr(tool, "settle"):
        print(f"{TOOL} has no no-runner classifier: it is the tool from before the change")
        return 1
    failed = 0
    for run_id, attempt, sha, expected in CASES:
        verdict, n, unrun = tool.settle(REPO, run_id, "failure", attempt)
        if verdict == "untested":
            line = tool.untested_line("dotfiles", sha, tool.Record(sha, verdict, f"run {run_id}", run_id=run_id, attempt=n, unrun=unrun))
        else:
            line = f"dotfiles: RED  run {run_id} failed on {sha[:7]}"
        ok = verdict == expected
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} run {run_id} attempt {attempt}: {line}")
    print("\n$ ci-main-status --merge-gate dotfiles   (main as it is now, unchanged by the change)")
    r = subprocess.run([TOOL, "--merge-gate", "dotfiles"], capture_output=True, text=True)
    print(r.stdout + r.stderr + f"exit {r.returncode}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
