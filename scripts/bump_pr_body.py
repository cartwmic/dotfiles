"""The one check for the PR body that loop_engine_bump.py and agent_kit_bump.py write.

A bump PR body is clean when it carries no scratch path (the worktree is gone after the run), no `next:` line of operator steps
(the script does those itself), no internal rule id (a reader cannot look it up), no bookkeeping (a table outside a code fence, a
`Decisions:` line, a Principles heading: those are the agent record, `pr-record`), and it has a Proven section. Both scripts' tests
load this file, so the two bodies are held to the same rule. It is not a runtime dependency of either script.
"""

import re

SCRATCH_PATH = re.compile(r"/tmp/\S+")
NEXT_LINE = re.compile(r"(?m)^\s*next:.*$")
# "rule" then 8 hex characters. The 40-hex commit sha in a tag line or a PR head has no "rule" before it, so it is not caught.
RULE_ID = re.compile(r"(?i)\b(?:playbook\s+)?rule\s+[0-9a-f]{8}\b")
FENCE = re.compile(r"```.*?```", re.S)
TABLE_ROW = re.compile(r"(?m)^\|.*\|\s*$")
DECISIONS_LINE = re.compile(r"(?m)^Decisions:")
PRINCIPLES_HEADING = re.compile(r"(?m)^(?:#+\s*)?Principles\b")
PROVEN = re.compile(r"(?m)^## Proven$")


def problems(body, *scratch):
    """The reasons a bump PR body is not clean: empty when it is. `scratch` are directories the run used (a test's temp dir)."""
    found = ["a scratch path: %s" % m for m in SCRATCH_PATH.findall(body)]
    found += ["a scratch path: %s" % s for s in scratch if s and s in body]
    found += ["a next line: %s" % m for m in NEXT_LINE.findall(body)]
    found += ["a rule id: %s" % m for m in RULE_ID.findall(body)]
    prose = FENCE.sub("", body)
    found += ["a table row: %s" % m for m in TABLE_ROW.findall(prose)]
    found += ["a Decisions line" for _ in DECISIONS_LINE.findall(prose)]
    found += ["a Principles heading" for _ in PRINCIPLES_HEADING.findall(prose)]
    if not PROVEN.search(body):
        found.append("no Proven section")
    return found
