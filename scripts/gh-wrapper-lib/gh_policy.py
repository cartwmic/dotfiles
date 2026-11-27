"""The work-rules layer of the gh wrapper: four refusals that keep issues and pull requests in the one agreed form. docs/gh-wrapper.md.

A layer for lib/gh_layers.py: `before(call)` raises Stop(1, message) or lets the call go. It never edits the call. Each refusal says in one sentence what is
missing and what to run instead.

  pr create     refused unless the first line of the body is `Closes #N` or `Refs #N` and N is an open issue (not a pull request) of the repository.
  pr merge      refused with --merge or --rebase: every pull request lands as one squash commit.
  issue create  refused unless the body has the three parts Problem, Wanted and Done when, and the labels hold exactly one kind label.
  issue close   refused unless a merged pull request is linked to the issue, or the close says --reason "not planned" and gives a --comment.

It runs only where ~/.config/gh-wrapper/policy says `on` (the installer writes it from the profile: on for personal, off for the work Mac, whose repositories keep
their own tracker rules). Every refusal, and every use of an exemption, is one line in <state>/gh-wrapper/policy.jsonl: {utc, rule, outcome (refused|exempt),
class, kind (the exemption used, else null), who ($GH_CALLER, else null)}. Never a title, a body, an issue number or a repository.

The flags come from the wrapper's own parse (call.parsed): this layer has no flag table. A call whose flags the wrapper could not read is refused for these four
commands, since nothing says whether it is a merge commit or an issue without a label. Issue and pull request state is read through the real gh (call.real).
A layer's own failure never changes a call (gh_layers): only the Stop here does.
"""
import datetime
import json
import os
import re
import subprocess

from gh_layers import Stop

REFUSED = 1
READ_TIMEOUT = 30

# ---- what is excused: the ONE place --------------------------------------------------------------------------------------------------------------------
# Each exemption is recognised by something a tool sets and a person does not type by accident, never by what the caller says it is.
#
# PR_WITHOUT_ISSUE: kinds of pull request that need no issue, as (kind, field, regex), field being "head" (the branch) or "title". EMPTY ON PURPOSE: whether
# release, pin-bump and revert pull requests need an issue is not decided, so with the list empty `gh pr create` from those tools is refused too.
PR_WITHOUT_ISSUE = ()
# MERGE_COMMIT_STOPGAP: TEMPORARY. The coordinator's merge script (scripts/merge-pr.sh) still runs `gh pr merge --merge`, and squash-only would stop every
# coordinator merge. It may merge with --merge while GH_CALLER names it AND a calling process is that script, and each use is logged as exempt. DELETE THIS
# ENTRY when the coordinator moves merge-pr.sh to --squash; nothing else may take it, and --rebase has no exemption at all.
MERGE_COMMIT_STOPGAP = {"kind": "merge-pr.sh stopgap (temporary, removed when the coordinator's merge script squashes)", "caller": "merge-pr", "script": "merge-pr.sh"}

KIND_LABELS = ("bug", "change", "flaky test", "docs", "question")
PARTS = ("Problem", "Wanted", "Done when")
CLOSE_LINE = re.compile(r"^(?:Closes|Refs) #(\d+)\s*$")


# ---- the rules: no I/O ---------------------------------------------------------------------------------------------------------------------------------

def values(flags, name):
    return [val for n, val in flags if n == name and val is not None]


def body_of(flags):
    """(text, problem): the body text the call sends, from --body or --body-file, or (None, why it cannot be read)."""
    for name in ("body", "body-file"):
        for val in values(flags, name):
            if name == "body":
                return val, None
            if val == "-":
                return None, "the body comes from standard input, where it cannot be read before gh runs. Give it with --body-file FILE"
            try:
                with open(val, encoding="utf-8", errors="replace") as f:
                    return f.read(), None
            except OSError as e:
                return None, "the body file cannot be read (%s)" % e.strerror
    return None, "there is no body, and gh would compose one (--fill, --template, --editor, --web) or ask for one"


def linked_issue(body):
    """The issue number on the first line of a body (`Closes #N` or `Refs #N`), or None."""
    m = CLOSE_LINE.match(body.split("\n", 1)[0].rstrip("\r"))
    return int(m.group(1)) if m else None


def missing_parts(body):
    """The parts of PARTS that have no heading in the body, as a line starting `## Problem`, `**Problem.**` or `__Problem__`, or a line that is `Problem` alone or starts
    `Problem:`, in any case. A sentence that merely starts with the word is not a heading."""
    found = []
    for part in PARTS:
        word = re.escape(part)
        pattern = r"^[ \t]*(?:#{1,6}[ \t]*%s\b|(?:\*\*|__)[ \t]*%s\b|%s[ \t]*(?:[.:]|$))" % (word, word, word)
        if not re.search(pattern, body, re.I | re.M):
            found.append(part)
    return found


def kind_labels(flags):
    """The kind labels among the --label values (a value may hold several, comma separated), as written, in order."""
    labels = [l.strip() for val in values(flags, "label") for l in val.split(",")]
    return [l for l in labels if l.lower() in KIND_LABELS]


def exempt_pr(title, head):
    """The kind of PR_WITHOUT_ISSUE this pull request is, or None."""
    for kind, field, pattern in PR_WITHOUT_ISSUE:
        if re.search(pattern, head if field == "head" else title):
            return kind
    return None


def refusal(klass, flags, issue_state, linked_merged):
    """The sentence to refuse with, or None to let the call go. `klass` is `pr create`, `pr merge`, `issue create` or `issue close`; `flags` the wrapper's parse.
    `issue_state` and `linked_merged` are reads the caller makes only when the rule needs them: issue_state(n) is the (state, url) of issue n or an error string;
    linked_merged() is True when a merged pull request is linked to the issue being closed."""
    if klass in ("pr create", "pr new"):
        body, problem = body_of(flags)
        if body is None:
            return "pr: %s. Open the pull request with `pr-open`, whose first body line is `Closes #N` or `Refs #N`." % problem
        n = linked_issue(body)
        if n is None:
            return ("this pull request is not linked to an issue: the first line of its body must be `Closes #N` or `Refs #N` for an open issue. "
                    "File one with `issue-open` (Problem, Wanted, Done when, one kind label), then open the pull request with `pr-open`.")
        state = issue_state(n)
        if isinstance(state, str):
            return "issue #%d cannot be read (%s), so the link on the first line of the body cannot be checked." % (n, state)
        if state[0] != "OPEN" or "/issues/" not in state[1]:
            return "#%d is not an open issue (it is a pull request or is closed): the first line of the body must be `Closes #N` or `Refs #N` for an open issue." % n
    elif klass == "pr merge":
        names = {n for n, _ in flags}
        if "rebase" in names:
            return "merges are squash only: `--rebase` is refused. Merge with `--squash`."
        if "merge" in names:
            return "merges are squash only: `--merge` is refused. Merge with `--squash`."
    elif klass in ("issue create", "issue new"):
        body, problem = body_of(flags)
        if body is None:
            return "issue: %s. Open the issue with `issue-open`, with a body file of Problem, Wanted and Done when." % problem
        lacking = missing_parts(body)
        if lacking:
            return "the issue body has no %s: it needs the three parts Problem, Wanted and Done when. Open it with `issue-open`." % " or ".join(lacking)
        kinds = kind_labels(flags)
        if len(kinds) != 1:
            return ("the issue needs exactly one kind label from %s, and has %d: add `--label <one of them>`. A label the repository lacks is created with "
                    "`gh label create <name> -R OWNER/REPO`." % (", ".join(KIND_LABELS), len(kinds)))
    elif klass == "issue close":
        reason, comment = (values(flags, n) for n in ("reason", "comment"))
        if reason and reason[-1] == "not planned" and any(c.strip() for c in comment):
            return None
        if not linked_merged():
            return ("an issue closes only with a merged pull request linked to it (`Closes #N` in its body), or as `--reason \"not planned\"` with a `--comment` "
                    "that says why.")
    return None


# ---- the edges: the switch, the real gh, the log -------------------------------------------------------------------------------------------------------

def enabled(environ=os.environ):
    try:
        with open(os.path.join(os.path.expanduser("~"), ".config", "gh-wrapper", "policy")) as f:
            return f.read().strip() == "on"
    except OSError:
        return False


def run_gh(call, *args):
    """(True, the real gh's standard output) or (False, why it failed). Never prompts."""
    env = dict(os.environ, GH_PROMPT_DISABLED="1")
    try:
        done = subprocess.run([call.real, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=READ_TIMEOUT, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, "gh did not answer: %s" % (e.strerror if isinstance(e, OSError) else "timed out")
    if done.returncode != 0:
        err = done.stderr.decode(errors="replace").strip()
        return False, err.splitlines()[0][:200] if err else "gh exited %d" % done.returncode
    return True, done.stdout.decode(errors="replace")


def repo_args(flags):
    repo = values(flags, "repo")
    return ["-R", repo[-1]] if repo else []


def read_json(call, *args):
    """(document, None) from a real gh call that prints JSON, or (None, why not)."""
    ok, out = run_gh(call, *args)
    if not ok:
        return None, out
    try:
        return json.loads(out), None
    except ValueError:
        return None, "gh gave an answer this layer cannot read"


def read_issue(call, flags):
    def read(n):
        doc, why = read_json(call, "issue", "view", str(n), *repo_args(flags), "--json", "state,url")
        return why if doc is None else (doc.get("state"), doc.get("url") or "")
    return read


def read_linked_merged(call, flags, positionals):
    """True when a pull request that closes the issue is merged: the issue's own `closedByPullRequestsReferences`, then each one's state."""
    def read():
        if not positionals:
            return False
        doc, _ = read_json(call, "issue", "view", positionals[0], *repo_args(flags), "--json", "closedByPullRequestsReferences")
        for ref in (doc or {}).get("closedByPullRequestsReferences", []):
            pr, _ = read_json(call, "pr", "view", ref.get("url", ""), "--json", "state")
            if (pr or {}).get("state") == "MERGED":
                return True
        return False
    return read


def stopgap_applies(environ=os.environ):
    """True when GH_CALLER names the merge script and a calling process (the parent or its parent) is that script: both, so a variable alone does not do it."""
    if environ.get("GH_CALLER") != MERGE_COMMIT_STOPGAP["caller"]:
        return False
    import gh_log      # the ancestry reader of the call log, which runs whether or not the log layer does
    return any(MERGE_COMMIT_STOPGAP["script"] in (name or "").split() for name in gh_log.ancestry())


def log(rule, outcome, klass, kind=None, environ=os.environ):
    entry = {"utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "rule": rule, "outcome": outcome, "class": klass, "kind": kind,
             "who": environ.get("GH_CALLER")}
    state = os.path.join(environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state"), "gh-wrapper")
    try:
        os.makedirs(state, mode=0o700, exist_ok=True)
        with open(os.path.join(state, "policy.jsonl"), "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass      # a log that cannot be written never changes the call


RULE_OF = {"pr create": "issue-first", "pr new": "issue-first", "pr merge": "squash-only", "issue create": "issue-form", "issue new": "issue-form", "issue close": "close-rule"}


def before(call):
    rule = RULE_OF.get(call.klass)
    if rule is None or not enabled():
        return
    if call.parsed is None:
        log(rule, "refused", call.klass)
        raise Stop(REFUSED, "gh-wrapper: refused `gh %s`: a flag of this call is not in the wrapper's table, so whether it follows the rules cannot be told. "
                            "Use the long flags `gh %s --help` lists." % (call.klass, call.klass))
    flags, positionals = call.parsed
    if any(n == "help" for n, _ in flags):
        return      # a help request changes nothing
    positionals = positionals[1:]      # the first is the verb itself
    if call.klass in ("pr create", "pr new"):
        title, head = (values(flags, n) for n in ("title", "head"))
        kind = exempt_pr(title[-1] if title else "", head[-1] if head else "")
        if kind:
            log(rule, "exempt", call.klass, kind)
            return
    sentence = refusal(call.klass, flags, read_issue(call, flags), read_linked_merged(call, flags, positionals))
    if sentence and call.klass == "pr merge" and "rebase" not in {n for n, _ in flags} and stopgap_applies():
        log(rule, "exempt", call.klass, MERGE_COMMIT_STOPGAP["kind"])
        return
    if sentence:
        log(rule, "refused", call.klass)
        raise Stop(REFUSED, "gh-wrapper: refused `gh %s`: %s" % (call.klass, sentence))
