"""What a `gh` command does to a pull request or an issue, as one allow table.

`surface(gh)` takes a parsed command (bash_rules.GhCommand: `group`, `verb`, `argv`, `operands`, `before_verb`) and returns a Surface:

  effects  what it writes, a subset of MERGE, PR_CREATE, ISSUE_CREATE, TITLE, BODY, COMMENT, OTHER. Empty for a read and for a command off the PR/issue surface.
  verdict  what the hook should do with it: ALLOW; PR_BODY (allowed only through the checked-body form, `pr-open`); ISSUE_OPEN (only through `issue-open`);
           MERGE_GATE (allowed only behind both merge gates, or `merge-pr.sh`); REFUSE. Several effects give the strictest verdict.
  listed   True when a row of this module names the command. False is a refusal too: the command is on the PR/issue surface and no row says what it does, or the
           module cannot read it (an unknown flag, a query from a file, a verb gh added since the table was written). That is the fail-closed default: only a row lets a command pass.
  reason   for a REFUSE, the sentence to show the agent. Empty otherwise.
  route    the command as the module read it (`gh api PUT pulls/5/merge`), for a log line. Tests do not read it.

The same effect can have different verdicts by route: `gh pr edit -b` is PR_BODY (allowed through `pr-open`), while `gh issue edit -b`, which sets the same text when the number
is a pull request, is REFUSE: the hook cannot tell a PR number from an issue number, and no checked route to an issue's text exists yet (issue-open --edit). The tables below
are the only place that is decided; a rule must not read a gh verb, endpoint or mutation name itself.

Covered: `gh pr`, `gh issue`, `gh agent-task`, and `gh api` on REST paths under `pulls` and `issues` (including `repositories/<id>/...`, a full URL, a trailing slash, a query
string, and `merges` / `merge-upstream`) and on graphql (every operation in the query is read by one tokenizer that skips comments and strings). Every other gh command is off the
surface and ALLOW. Not covered, and not claimed: an alias, `curl`, a script file, `$cmd`, a query built by a shell expansion, `git push`, and REST writes to `git/refs` or `contents`.
No I/O and no import from the rest of the hook: the caller parses, this module decides.
"""
import re
from collections import namedtuple

MERGE, PR_CREATE, ISSUE_CREATE, TITLE, BODY, COMMENT, OTHER = "merge", "pr-create", "issue-create", "title", "body", "comment", "other"
ALLOW, PR_BODY, ISSUE_OPEN, MERGE_GATE, REFUSE = "allow", "pr-body", "issue-open", "merge-gate", "refuse"
SEVERITY = (ALLOW, PR_BODY, ISSUE_OPEN, MERGE_GATE, REFUSE)  # several effects give the last one that applies

Surface = namedtuple("Surface", "effects verdict listed reason route")

NEW_PR = frozenset({PR_CREATE, TITLE, BODY})
NEW_ISSUE = frozenset({ISSUE_CREATE, TITLE, BODY})
SET_TEXT = frozenset({TITLE, BODY})

WHY_MERGE = "`%s` merges a pull request without the merge gates. Merge with `gh pr merge` behind both gates, or `merge-pr.sh`."
WHY_PR_TEXT = "`%s` sets the title or body of a pull request without the check that `pr-open` runs. Use `pr-open` (`pr-open --edit N --body-file F` for a PR that exists)."
WHY_PR_OR_ISSUE = ("`%s` sets the title or body of an issue or pull request without a check, and the hook cannot tell a PR number from an issue number. "
                  "For a pull request use `pr-open --edit N --body-file F [--title T]`. For an issue there is no checked route yet (follow-up: `issue-open --edit`, owed #4493).")
WHY_ISSUE = "`%s` sets the title or body of an issue that nothing checked. There is no checked route to an issue's text yet (follow-up: `issue-open --edit`, owed #4493)."
WHY_UNLISTED = ("`%s` is not on the allow table in dot_local/share/agent-harness/hooks/gh_surface.py, so the hook cannot tell what it does to a pull request or issue and refuses it "
                "(%s). Add a row there for it, then run the command again.")


def _surface(effects, verdict, route, reason=""):
    return Surface(frozenset(effects), verdict, True, reason % route if "%s" in reason else reason, route)


def _unlisted(route, why):
    return Surface(frozenset(), REFUSE, False, WHY_UNLISTED % (route, why), route)


def _join(parts, route):
    """One Surface for several: the union of the effects, the strictest verdict, the first reason of that verdict."""
    worst = max(parts, key=lambda p: (not p.listed, SEVERITY.index(p.verdict)))
    return Surface(frozenset().union(*(p.effects for p in parts)), worst.verdict, all(p.listed for p in parts), worst.reason, route)


# --- gh pr, gh issue, gh agent-task: one row per verb. (effects, verdict[, reason]). A verb that is not here is unlisted. `new` and `ls` are gh's own aliases.
READ = (frozenset(), ALLOW)
SAY = (frozenset({COMMENT}), ALLOW)
STATE = (frozenset({OTHER}), ALLOW)  # close, reopen, ready, lock, labels, reviewers: a state change with no text a checker reads
PR_VERBS = {
    **dict.fromkeys(("list", "ls", "status", "checkout", "co", "checks", "diff", "view"), READ),
    **dict.fromkeys(("comment", "review"), SAY),
    **dict.fromkeys(("close", "reopen", "ready", "lock", "unlock", "update-branch"), STATE),
    "create": (NEW_PR, PR_BODY), "new": (NEW_PR, PR_BODY),
    "merge": (frozenset({MERGE}), MERGE_GATE),
    "revert": (NEW_PR, REFUSE, "`%s` opens a pull request with a title and body nothing checked. Make the revert with git, then open it with `pr-open`."),
}
ISSUE_VERBS = {
    **dict.fromkeys(("list", "ls", "status", "view"), READ),
    "comment": SAY,
    **dict.fromkeys(("close", "reopen", "lock", "unlock", "pin", "unpin", "develop"), STATE),
    "create": (NEW_ISSUE, ISSUE_OPEN), "new": (NEW_ISSUE, ISSUE_OPEN),
    "delete": (frozenset({OTHER}), REFUSE, "`%s` deletes an issue for good."),
    "transfer": (frozenset({OTHER}), REFUSE, "`%s` moves an issue to another repository."),
    "artifact": (frozenset({BODY}), REFUSE, "`%s` attaches a document to an issue that nothing checked."),
}
AGENT_TASK_VERBS = {"list": READ, "view": READ, "create": (frozenset({PR_CREATE}), REFUSE, "`%s` has Copilot open a pull request whose body nothing checked.")}
GROUP_VERBS = {"pr": PR_VERBS, "issue": ISSUE_VERBS, "agent-task": AGENT_TASK_VERBS}
GROUP_ALIAS = {"agent-tasks": "agent-task", "agent": "agent-task", "agents": "agent-task"}
# Every other gh command, named here so that a command gh adds is noticed (tests/agent-kill-guard/test_gh_tree_classified.py): off the PR/issue surface, ALLOW.
# `alias`, `extension` and `copilot` can run what the table cannot read; they stay open (see "Not covered" above). An alias call is refused as an unknown group.
OFF_SURFACE = frozenset((
    "auth browse codespace discussion gist org project release repo skill cache run workflow alias attestation completion config copilot extension "
    "gpg-key label licenses preview ruleset search secret ssh-key status variable help co event "
    "cs skills at extensions ext rs").split())  # `co` is `gh pr checkout`, a read; `event` listens for and subscribes to events on a resource (a preview in gh 2.105); the second line is gh's own aliases (`gh cs`, `gh at`)


# `gh pr edit` and `gh issue edit`: what each flag does, by its long name (the union of the two commands' flags; a flag the command does not have is unknown to bash_rules first).
# A flag that is not in this table is unlisted, so a flag gh adds refuses until someone decides what it does (tests/agent-kill-guard/test_gh_surface.py checks the keys against
# FLAG_ROWS and gh's own help). `python3 tests/agent-kill-guard/test_gh_surface.py --edit-flags` prints the table with the verdict of each flag.
EDIT_FLAGS = {
    "title": TITLE, "body": BODY, "body-file": BODY, "attach": BODY,  # text: a pull request's goes through `pr-open`; an issue has no checked route
    **dict.fromkeys(("add-label", "remove-label", "add-assignee", "remove-assignee", "milestone", "remove-milestone", "add-project", "remove-project", "add-reviewer", "remove-reviewer", "base",
                     "type", "remove-type", "parent", "remove-parent", "add-sub-issue", "remove-sub-issue", "add-blocked-by", "remove-blocked-by", "add-blocking", "remove-blocking"), OTHER),
}
EDIT_IGNORED = frozenset({"repo", "help"})  # carry no effect: the repository the command names, and help


def _edit_effects(argv):
    """The effects of the flags an edit carries, or None when a flag is not in EDIT_FLAGS."""
    names = {n for n, _, _ in argv.flags} - EDIT_IGNORED
    return None if names - set(EDIT_FLAGS) else {EDIT_FLAGS[n] for n in names}


HELP_TRUE = frozenset("1 t T TRUE true True".split())  # what gh's flag parser (Go's ParseBool) reads as true; `--help=false`, `=0`, or an unreadable value runs the command


def _helping(argv):
    """gh keeps the last value of a repeated `--help`, so `--help --help=false` runs the command and `--help=false --help` prints help. A `-h` anywhere prints
    help in gh whatever else follows (`-h --help=false`, `-h=0`); this reads `-h` by the same last-value rule, so those spellings come back as the command: a refusal
    of a help read, which fails closed. No spelling that gh runs is read as help."""
    values = [v for n, v, _ in argv.flags if n == "help"]
    return bool(values) and (values[-1] is None or values[-1] in HELP_TRUE)


def _verb(gh, route):
    verbs = GROUP_VERBS[GROUP_ALIAS.get(gh.group, gh.group)]
    if not gh.verb:
        return _surface((), ALLOW, route)  # `gh pr`: gh prints its help
    row = verbs.get(gh.verb)
    route = "%s %s" % (route, gh.verb)
    if row is None:
        return _unlisted(route, "gh %s has no verb `%s` in the table" % (gh.group, gh.verb))
    if gh.verb in ("create", "new", "merge") and gh.argv.unknown:
        return _unlisted(route, "a flag the hook's table does not know: `%s`" % gh.argv.unknown[0])
    return _surface(*row[:2], route, row[2] if len(row) > 2 else "")


def _edit(gh, route):
    """`gh pr edit` and `gh issue edit` by the flags they carry. Text (title, body, body file, attachment) on a pull request goes through the check (PR_BODY); on `gh issue edit` it is
    refused, because gh sends `updatePullRequest` when the number is a pull request and the hook cannot tell. A flag that is not in EDIT_FLAGS is unlisted."""
    if gh.argv.unknown:
        return _unlisted(route, "a flag the hook's table does not know: `%s`" % gh.argv.unknown[0])
    effects = _edit_effects(gh.argv)
    if effects is None:
        return _unlisted(route, "a flag that is not in EDIT_FLAGS: `%s`" % sorted({n for n, _, _ in gh.argv.flags} - EDIT_IGNORED - set(EDIT_FLAGS))[0])
    if effects & SET_TEXT:
        return _surface(effects, PR_BODY, route) if gh.group == "pr" else _surface(effects, REFUSE, route, WHY_PR_OR_ISSUE)
    return _surface(effects, ALLOW, route)


# --- gh api
# REST: the path after `repos/<owner>/<repo>/` (or `repositories/<id>/`). `*` is one segment, a number or an id. A write on `pulls` or `issues` that no row names is unlisted.
REST = (
    (("pulls", "*", "merge"), {MERGE}, REFUSE, WHY_MERGE), (("merges",), {MERGE}, REFUSE, WHY_MERGE), (("merge-upstream",), {MERGE}, REFUSE, WHY_MERGE),
    (("pulls",), NEW_PR, REFUSE, WHY_PR_TEXT),
    (("issues",), NEW_ISSUE, ISSUE_OPEN, ""),
    (("pulls", "*", "comments"), {COMMENT}, ALLOW, ""), (("pulls", "*", "comments", "*", "replies"), {COMMENT}, ALLOW, ""), (("pulls", "comments", "*"), {COMMENT}, ALLOW, ""),
    (("pulls", "*", "reviews"), {COMMENT}, ALLOW, ""), (("pulls", "*", "reviews", "*"), {COMMENT}, ALLOW, ""), (("pulls", "*", "reviews", "*", "events"), {COMMENT}, ALLOW, ""),
    (("issues", "*", "comments"), {COMMENT}, ALLOW, ""), (("issues", "comments", "*"), {COMMENT}, ALLOW, ""),
    (("pulls", "*", "requested_reviewers"), {OTHER}, ALLOW, ""),
    (("issues", "*", "labels"), {OTHER}, ALLOW, ""), (("issues", "*", "labels", "*"), {OTHER}, ALLOW, ""), (("issues", "*", "assignees"), {OTHER}, ALLOW, ""),
)
# `pulls/N` and `issues/N`: what each field of the request does. A field that is not here is unlisted.
PR_FIELDS = {"title": {TITLE}, "body": {BODY}, "state": {OTHER}, "base": {OTHER}, "maintainer_can_modify": {OTHER}}
ISSUE_FIELDS = {**{k: {OTHER} for k in ("state", "state_reason", "labels", "assignee", "assignees", "milestone", "type")}, "title": {TITLE}, "body": {BODY}}
READ_METHODS = ("GET", "HEAD")


def _segments(endpoint):
    """The path of a gh api endpoint as segments: a scheme and host, an enterprise `api/v3`, a query string and empty segments are dropped."""
    path = re.sub(r"^[a-z][a-z0-9+.-]*://[^/]*", "", endpoint, flags=re.I).split("?")[0].split("#")[0]
    segments = [s for s in path.split("/") if s]
    return segments[2:] if segments[:2] == ["api", "v3"] else segments


def _fields(argv):
    return argv.values("raw-field") + argv.values("field")


def _rest(gh, method, segments):
    route = "gh api %s %s" % (method, "/".join(segments))
    if any(s in (".", "..") or "%" in s for s in segments):
        return _unlisted(route, "a path with `.`, `..` or `%` in it")
    if segments[:1] == ["repos"] and len(segments) >= 3:
        rest = segments[3:]
    elif segments[:1] == ["repositories"] and len(segments) >= 2:
        rest = segments[2:]
    else:
        return _surface((), ALLOW, route)  # not under a repository: not a pull request or an issue
    if method in READ_METHODS or not rest or rest[0] not in ("pulls", "issues", "merges", "merge-upstream"):
        return _surface((), ALLOW, route)
    for pattern, effects, verdict, reason in REST:
        if len(pattern) == len(rest) and all(p in ("*", s) for p, s in zip(pattern, rest)):
            return _surface(effects, verdict, route, reason)
    if len(rest) == 2 and rest[0] in ("pulls", "issues") and method in ("PATCH", "POST", "PUT"):
        table = PR_FIELDS if rest[0] == "pulls" else ISSUE_FIELDS
        keys = [f.partition("=")[0].partition("[")[0] for f in _fields(gh.argv)]
        if gh.argv.has("input"):
            effects = set(SET_TEXT)  # a request body from a file: it can set both, and the hook cannot read it
        elif all(k in table for k in keys):
            effects = set().union(*(table[k] for k in keys))
        else:
            return _unlisted(route, "a field the table does not know for %s/N: `%s`" % (rest[0], next(k for k in keys if k not in table)))
        if effects & SET_TEXT:
            return _surface(effects, REFUSE, route, WHY_PR_TEXT if rest[0] == "pulls" else WHY_PR_OR_ISSUE)
        return _surface(effects, ALLOW, route)
    return _unlisted(route, "a %s write on %s" % (method, "/".join(rest)))


# graphql: mutation name -> (effects, verdict, reason). Any mutation not here is unlisted. Every name here is a field of GitHub's public schema (type Mutation).
GRAPHQL = {
    **dict.fromkeys(("mergePullRequest", "enablePullRequestAutoMerge", "enqueuePullRequest"), ({MERGE}, REFUSE, WHY_MERGE)),
    "createPullRequest": (NEW_PR, REFUSE, WHY_PR_TEXT), "updatePullRequest": (SET_TEXT, REFUSE, WHY_PR_TEXT),
    "createIssue": (NEW_ISSUE, ISSUE_OPEN, ""), "updateIssue": (SET_TEXT, REFUSE, WHY_ISSUE),
    **dict.fromkeys(("addComment", "addPullRequestReview", "addPullRequestReviewComment", "addPullRequestReviewThread", "addPullRequestReviewThreadReply",
                     "submitPullRequestReview"), ({COMMENT}, ALLOW, "")),
    **dict.fromkeys(("resolveReviewThread", "unresolveReviewThread", "addLabelsToLabelable", "removeLabelsFromLabelable", "requestReviews", "closePullRequest",
                     "reopenPullRequest", "closeIssue", "reopenIssue", "markPullRequestReadyForReview"), ({OTHER}, ALLOW, "")),
}
_TOKEN = re.compile(r'"""(?:\\"""|.)*?"""|"(?:\\.|[^"\\\n])*"|#[^\n]*|\.\.\.|[_A-Za-z][_0-9A-Za-z]*|[{}()\[\]:@$!=|&,]|\s+|.', re.S)
_CLOSER = {"}": "{", ")": "(", "]": "["}
_NAME = re.compile(r"[_A-Za-z]\w*")


def mutation_fields(query):
    """The root fields of every mutation in a graphql document (a list, empty for a query), or None when the document cannot be read: an empty or unterminated one, a
    spread at the root of a mutation (`...F`), a mutation with no field, or text a shell expansion built. Comments and strings are skipped, so a mutation name in either is
    not one, and an alias (`a: mergePullRequest`) is read as the field it names."""
    if not query.strip() or re.search(r"\$\(|\$\{|`", query):
        return None
    tokens = []
    for match in _TOKEN.finditer(query):
        token = match.group()
        if token == '"':
            return None  # an unterminated string
        if not (token.isspace() or token.startswith("#") or token == ","):
            tokens.append("\0string" if token.startswith('"') else token)
    stack, fields, pending, inside, mutations = [], [], False, False, 0
    for i, token in enumerate(tokens):
        before, after = tokens[i - 1] if i else None, tokens[i + 1] if i + 1 < len(tokens) else None
        if token in ("{", "(", "["):
            if token == "{" and not stack:
                inside, pending = pending, False
                mutations += inside
            stack.append(token)
        elif token in _CLOSER:
            if not stack or stack.pop() != _CLOSER[token]:
                return None
            inside = inside and bool(stack)
        elif not stack and token == "mutation":
            pending = True
        elif inside and stack == ["{"]:
            if token == "...":
                return None
            if _NAME.fullmatch(token) and before != "@" and after != ":":
                fields.append(token)
    return fields if not stack and (fields or not mutations) else None


def _graphql(gh):
    route = "gh api graphql"
    if gh.argv.has("input"):
        return _unlisted(route, "a request body from --input, which the hook cannot read")
    queries = [v.partition("=")[2] for v in _fields(gh.argv) if v.partition("=")[0] == "query"]
    if not queries:
        return _unlisted(route, "no `query` field")
    parts = []
    for query in queries:
        fields = None if query.startswith("@") or re.fullmatch(r"\$\w+", query) else mutation_fields(query)
        if fields is None:
            return _unlisted(route, "a query the hook cannot read: from a file, empty, built by the shell, or malformed")
        for name in fields:
            row = GRAPHQL.get(name)
            parts.append(_surface(*row[:2], "%s mutation %s" % (route, name), row[2]) if row else _unlisted("%s mutation %s" % (route, name), "a mutation the table does not list"))
    return _join(parts, route) if parts else _surface((), ALLOW, route)


def _api(gh):
    argv = gh.argv
    if argv.unknown:
        return _unlisted("gh api", "a flag the hook's table does not know: `%s`" % argv.unknown[0])
    if len(gh.operands) != 1:
        return _unlisted("gh api", "it names %d endpoints" % len(gh.operands))
    segments = _segments(gh.operands[0])
    if segments == ["graphql"]:
        return _graphql(gh)
    method = (argv.value("method") or ("POST" if _fields(argv) or argv.has("input") else "GET")).upper()
    return _rest(gh, method, segments)


def surface(gh):
    """The Surface of a parsed gh command (bash_rules.gh_command), or of None (no command: `gh`, `gh --version`)."""
    if gh is None:
        return _surface((), ALLOW, "gh")
    route = "gh " + gh.group
    if gh.before_verb is not None:
        return _unlisted(route, "a flag before the subcommand (`%s`), which gh may take the next word as the value of" % gh.before_verb)
    if _helping(gh.argv):
        return _surface((), ALLOW, route)
    if gh.group == "api":
        return _api(gh)
    group = GROUP_ALIAS.get(gh.group, gh.group)
    if group in GROUP_VERBS:
        return _edit(gh, route + " edit") if gh.verb == "edit" and group in ("pr", "issue") else _verb(gh, route)
    if gh.group in OFF_SURFACE:
        return _surface((), ALLOW, route)
    return _unlisted(route, "gh has no command `%s` in the table; it may be an alias or an extension" % gh.group)
