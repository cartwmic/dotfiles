"""Shared by the commit-range checks (scripts/check-test-edits.py, scripts/check-untested-hunks.py): git, the commit walk, test-file
names, the per-hunk patch reader and a commit message's `Key: why` lines. Stdlib only."""
import re
import subprocess


def git(*args, cwd=None):
    done = subprocess.run(["git", "-c", "core.quotepath=off", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)  # a file that is not UTF-8 must not crash a check
    if done.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout


def is_test_file(path):
    parts = path.split("/")
    name = parts[-1]
    if "tests" in parts[:-1] or "fixtures" in parts[:-1]:
        return True
    return re.match(r"(test_.*\.py|.*_test\.py|.*\.(test|spec)\.[a-z]+|.*\.journey\.ts)$", name) is not None


def walk(base_rev, head_rev):
    """(base, head, commits): full shas and the commits of base..head, oldest first, following first parents only so a main merged
    into the PR is not blamed on it (a side branch merged into the PR is not walked either). Raises RuntimeError if a rev is unknown."""
    base, head = (git("rev-parse", "--verify", "--quiet", rev + "^{commit}").strip() for rev in (base_rev, head_rev))
    return base, head, git("rev-list", "--first-parent", "--no-merges", "--reverse", base + ".." + head).split()


def declared(commit, key):
    """The reasons in a commit's message: each `<key>: why` line, in any paragraph (git's own trailer match ignores case too)."""
    message = git("log", "-1", "--format=%B", commit)
    reasons = (m.group(1).strip() for m in re.finditer(r"^" + re.escape(key) + r":(.*)$", message, re.MULTILINE | re.IGNORECASE))
    return [reason for reason in reasons if reason]


def hunks(patch):
    """Yield (path, removed_lines, added_lines, new_start, new_count) for each hunk of a -U0 patch. path is None for a file that did
    not exist before (nothing existing was edited). new_start/new_count are the hunk's place in the file after the change; a pure
    deletion has new_count 0 and new_start is the line before it."""
    path = None
    current = None
    in_header = False
    for line in patch.splitlines():
        if line.startswith("diff --git"):
            if current:
                yield tuple(current)
            path, current, in_header = None, None, True
        elif in_header and line.startswith("--- a/"):
            path = line[6:]
        elif in_header and line.startswith("--- "):
            path = None
        elif line.startswith("@@"):
            if current:
                yield tuple(current)
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            current, in_header = [path, [], [], int(m.group(1)), 1 if m.group(2) is None else int(m.group(2))], False
        elif current and line.startswith("-"):
            current[1].append(line[1:])
        elif current and line.startswith("+"):
            current[2].append(line[1:])
    if current:
        yield tuple(current)
