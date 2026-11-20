#!/usr/bin/env python3
"""check-test-edits.py BASE HEAD: fail when a commit in BASE..HEAD makes an existing test file say less and says nothing about it.

The mistake: a check fails, and instead of fixing the code the commit deletes the failing sentence, line or case from a test's
input or assertions (dotfiles#629, commit 236a1ce: " and found no match" was cut from a test sentence the new check wrongly
failed). The test passes and the regression is hidden. The pull-request diff against main cannot see it when the test was
added earlier in the same PR, so this walks every commit of the range, not the whole diff.

A commit trips this when a hunk in a test file removes lines (or deletes the file) and whatever it adds in that hunk is only a
shortening of the removed text (nothing new is written, ignoring spaces). Those are the edits that make a test accept more or
check less. Edits that add or change text are not caught: telling a changed expectation from a fixed one needs judgment, and a
reviewer makes it (reviewer-brief.md).

The way through is a `Test-edit:` line in the commit's message, in any paragraph, that says why the test was wrong, not the code:

    Test-edit: <why the removed text was wrong, in one line>

A declared edit passes and is printed, so the CI log and the reviewer see each one. Only a line in the commit's own message
counts. A commit amended or squashed into an earlier one before it is pushed is not seen.

The walk follows first parents from BASE to HEAD. A main merged into the PR reaches HEAD through a second parent, so its commits
are not blamed on the PR. The cost: a side branch merged into the PR is not walked either.

Exit 0 clean, 1 an undeclared edit, 2 BASE or HEAD does not resolve (a shallow checkout: fetch the history first).
"""
import sys

from commit_range import declared, git, hunks, is_test_file, walk

TRAILER = "Test-edit"


def is_shortening(removed, added):
    """True when `added` is `removed` with text taken out and nothing written in, spaces ignored."""
    old = "".join(removed).replace(" ", "").replace("\t", "")
    new = "".join(added).replace(" ", "").replace("\t", "")
    if len(new) >= len(old):
        return False
    letters = iter(old)
    return all(ch in letters for ch in new)


def weakened_files(commit):
    patch = git("show", "-U0", "-M", "--format=", "--no-color", commit)
    found = []
    for path, removed, added, _start, _count in hunks(patch):
        if path and is_test_file(path) and removed and is_shortening(removed, added) and path not in found:
            found.append(path)
    return found


def main(argv):
    if len(argv) != 3:
        print("usage: check-test-edits.py BASE HEAD", file=sys.stderr)
        return 2
    try:
        base, head, commits = walk(argv[1], argv[2])
    except RuntimeError as err:
        print("check-test-edits: cannot read %s..%s (%s); fetch the full history (fetch-depth: 0)" % (argv[1], argv[2], err), file=sys.stderr)
        return 2
    print("check-test-edits: walked %d commits in %s..%s" % (len(commits), base[:8], head[:8]))
    failed = 0
    for commit in commits:
        files = weakened_files(commit)
        if not files:
            continue
        reasons = declared(commit, TRAILER)
        for path in files:
            if reasons:
                print("DECLARED test-edit: %s %s: %s" % (commit[:8], path, "; ".join(reasons)))
            else:
                failed += 1
                print(
                    "FAIL test-edit: %s removes text from the existing test %s and does not say why.\n"
                    "  Fix the code so the original test passes. If the test itself was wrong, add a line to the commit message:\n"
                    "  %s: <why the removed text was wrong, in one line>" % (commit[:8], path, TRAILER)
                )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
