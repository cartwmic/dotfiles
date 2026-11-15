"""Six refusals for an agent's shell command, run by refuse_pattern_kill.py after its pkill check. Each names the fix.

  sleep-poll  (both profiles)  a `while` or `until` loop whose body runs `sleep`: use `run-and-wake -- <cmd>`. Not refused: anything under
              `run-and-wake`, `for` loops, `while read` loops (they walk items), a lone sleep. Skipped for Claude's Monitor tool.
  heredoc     (both profiles)  an unquoted heredoc delimiter with an unescaped backtick in the body: quote it (`<<'EOF'`). Any command,
              also inside `$( )`.
  kube        (personal only)  kubectl, helm, k9s, kubectx on a context other than the homelab's: a context flag, `kubectl config
              use-context`, `kubectx X`, or no flag while the current context (--kubeconfig, an inline KUBECONFIG=, the hook's KUBECONFIG,
              else ~/.kube/config) is another. kubectl inside an ssh string is not inspected. No kubeconfig or no current-context: allowed.
  merge       (personal only)  `gh pr merge` unless BOTH `ci-main-status` and `pr-body-check` are joined to it by `&&` earlier in the
              same and-list (any order); the refusal names
              `ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr> ...`: --merge-gate exits 0 for
              UNTESTED and 1 for RED, as playbook fab9b713 allows an untested merge; a bare `ci-main-status` exits 2 for UNTESTED and
              blocks it. Never for cartwmic/coordinator (`-R`, else the git origin of the directory it runs in): use merge-pr.sh,
              which runs both checks itself. The playbook CLI, loop_engine_bump.py and agent_kit_bump.py run gh as a child process
              the hook never sees, so they pass.

  pr-body     (personal only)  `gh pr create`, and `gh pr edit` when it sets a body, unless the body comes from `--body-file F` (or `-F F`)
              and `pr-body-check --body-file F` with the same F is joined to it by `&&` earlier in the same and-list. Refused: an inline
              `--body`/`-b`, `--fill`, a create with no body flag, a body from stdin (`-F -`), a different file. The refusal names
              `pr-body-check --body-file F && gh pr create ... --body-file F`, so a Result cell such as `partial` fails when the body is
              written, not at merge. `gh pr edit` with no body flag (title, labels, reviewers) passes. No repo is exempt: unlike the merge
              rule, nothing else runs this check at create time.

  docker      (personal, Linux only)  `docker run`, `docker build`, `docker compose up` and their spellings (`docker container run`,
              `docker image build`, `docker buildx build`, `docker builder build`, `docker-compose up`, global options before the
              subcommand such as `docker -H x run` or `docker compose -f f.yml up`): this workstation runs no local Docker; the refusal
              names kgate and a throwaway namespace on the homelab cluster (ledger grant 21). Read-only commands (`docker ps`, `images`,
              `inspect`, `manifest inspect`, `compose ps`) pass, and so does anything after `kgate`. Other personal hosts (the Mac, which
              has Docker Desktop for agents) are untouched, since Docker is provisioned there on purpose.

Commands are found like the pkill classifier finds them (it supplies the parser): through quotes, `;` `&&` `|`, `$( )`, `sh -c`, `eval`,
wrappers, `find -exec`, heredocs fed to a shell. Not covered: a command built at run time (`$cmd`), a script file, `python -c`, a command
in an ssh remote string, a kubeconfig path or `cd` target that holds a shell variable. The rules are pure functions on the text and a
Context; the file reads and the git call are the Context's `read_file` and `origin_of`. The caller treats any exception as "allow".
"""
import os
import re
import subprocess
import sys
from collections import namedtuple

from refuse_pattern_kill import ASSIGN, SHELLS, WRAPPERS, Scan, _base, _command_words, shell_script, unwrap

HOMELAB = "kubernetes-admin@kubernetes"
MERGE_PR = "~/.local/share/coordinator-workspace/bin/merge-pr.sh"
COORDINATOR = re.compile(r"cartwmic/coordinator(?:\.git)?(?![\w-])")
KUBE_CONTEXT_FLAG = {"kubectl": "--context", "k9s": "--context", "helm": "--kube-context"}
# docker: the options before the subcommand that take a value (`docker -H host run`), the same for `compose` (`compose -f f.yml up`), and
# the (subcommand, ...) words that start a local container or image build.
DOCKER_OPTIONS_WITH_VALUE = {"-H", "--host", "-c", "--context", "-l", "--log-level", "--config", "--tlscacert", "--tlscert", "--tlskey"}
COMPOSE_OPTIONS_WITH_VALUE = {"-f", "--file", "-p", "--project-name", "--profile", "--env-file", "--project-directory", "--ansi", "--parallel"}
DOCKER_REFUSED = {("run",), ("build",), ("container", "run"), ("image", "build"), ("buildx", "build"), ("builder", "build"), ("compose", "up")}

POLL = (
    "A sleep-poll loop is refused in agent sessions: it holds the pane while it waits. "
    "Run the job with `run-and-wake -- <cmd>`; its end wakes the pane, so end your turn instead of polling."
)
HEREDOC = (
    "An unquoted heredoc with a backtick is refused in agent sessions: the shell runs the backticked text as a command. "
    "Quote the delimiter (`<<'EOF'`), or escape each backtick."
)
MERGE_CHECKS = ("ci-main-status", "pr-body-check")
BODY_FILE = "pr-body-check --body-file "  # prefix of the gated entry that names a file the body check already read
MERGE_BARE = (
    "`gh pr merge` without both gates is refused in agent sessions: it skips the red-main gate (playbook fab9b713) or the PR body check. "
    "For cartwmic/coordinator use `" + MERGE_PR + " PR`; for other repos run "
    "`ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr> ...` "
    "(--merge-gate lets an untested tip merge and stops only red; pr-body-check enforces playbook rules ecd63156, 385acc43 and ccc6c94b); "
    "pin bumps use loop_engine_bump.py or agent_kit_bump.py; playbook edits use the playbook CLI with --pr --merge."
)
PR_BODY = (
    "`gh pr %s` without a checked body file is refused in agent sessions: a design-principles Result cell such as `partial` is otherwise found "
    "only when `gh pr merge` runs. Run `pr-body-check --body-file F && gh pr %s ... --body-file F` (the same file F in both); "
    "a Result cell must start with pass, fail or n/a."
)
PR_BODY_VERBS = ("create", "new", "edit")  # `gh pr new` is an alias of `gh pr create`
MERGE_COORDINATOR = (
    "`gh pr merge` on cartwmic/coordinator is refused in agent sessions: " + MERGE_PR + " also runs the red-main gate and the decisions check. "
    "Use `" + MERGE_PR + " PR`."
)


DOCKER = (
    "`%s` is refused in agent sessions: this workstation runs no local Docker. "
    "Run the job on kgate (`run-and-wake -- kgate -- <cmd>`), or in a throwaway namespace on the homelab cluster under ledger grant 21 "
    "(create the namespace, run the job there, delete the namespace)."
)


def kube_message(what, fix):
    return (
        "%s is refused in agent sessions: the personal homelab grant (playbook f90b9301) covers only the cluster with context `%s`. %s"
        % (what, HOMELAB, fix)
    )


Context = namedtuple("Context", "tool profile env cwd read_file origin_of platform", defaults=(None, None, None, None, None, None, None))


def read_file(path):
    """The text of a regular file, else None (a missing path, a directory, a FIFO or an unreadable file is None)."""
    try:
        if not os.path.isfile(path):
            return None
        with open(path, errors="replace") as handle:
            return handle.read(1_000_000)
    except OSError:
        return None


def origin_of(directory):
    """The origin URL of the git checkout at directory, else None; git gets 2 seconds and no stdin."""
    try:
        if not directory or not os.path.isdir(directory):
            return None
        run = subprocess.run(["git", "-C", directory, "remote", "get-url", "origin"], capture_output=True, text=True,
                             timeout=2, stdin=subprocess.DEVNULL)
        return run.stdout.strip() if run.returncode == 0 else None
    except Exception:
        return None


Cmd = namedtuple("Cmd", "words assigns loop waking gated cwd")


class Walk:
    """Every simple command in the text, nested texts included, with the context each one runs in, and every Scan made on the way."""

    def __init__(self, text, cwd=None):
        self.cmds = []    # Cmd: words from the command position (wrappers unwrapped), the assignments before it,
        self.scans = []   # in a polling loop, under run-and-wake, the merge checks run earlier by && (a frozenset), working directory
        self._text(text, cwd, False, False, frozenset(), 0)

    def _text(self, text, cwd, loop, waking, gated, depth):
        if depth > 8 or not text:
            return
        scan = Scan(text)
        self.scans.append(scan)
        for inner in scan.nested:
            self._text(inner, cwd, loop, waking, gated, depth + 1)
        loops = []  # one entry per open while/until/for: True when it polls (not a `while read` and not a `for`)
        for index, raw in enumerate(scan.commands):
            words = _command_words(raw)
            for word in raw[:len(raw) - len(words)]:
                if word in ("while", "until"):
                    loops.append(not (word == "while" and words and _base(words[0]) == "read"))
                elif word == "for":
                    loops.append(False)
                elif word == "done" and loops:
                    loops.pop()
            if not words:
                continue
            assigns = tuple(w for w in raw[:len(raw) - len(words)] if ASSIGN.match(w))
            here = gated | self._and_listed(scan, index)
            polling = loop or any(loops)
            self._command(words, assigns, polling, waking, here, cwd, depth, scan, index)
            if _base(words[0]) == "cd":
                target = next((w for w in words[1:] if w != "--" and not w.startswith("-")), None)
                cwd = _resolve(target, cwd)

    @staticmethod
    def _and_listed(scan, index):
        """The merge checks (`ci-main-status`, `pr-body-check`) earlier in this command's and-list, joined to it only by `&&`, and for each
        `pr-body-check --body-file F` the entry BODY_FILE + F."""
        found = set()
        j = index
        while j > 0 and scan.joins[j].strip() == "&&":
            j -= 1
            earlier = _command_words(scan.commands[j])
            if earlier and _base(earlier[0]) in MERGE_CHECKS:
                found.add(_base(earlier[0]))
                if _base(earlier[0]) == "pr-body-check":
                    body_file = _flag_value(earlier[1:], "--body-file")
                    if body_file is not None:
                        found.add(BODY_FILE + body_file)
        return frozenset(found)

    def _command(self, words, assigns, loop, waking, gated, cwd, depth, scan=None, index=None):
        self.cmds.append(Cmd(words, assigns, loop, waking, gated, cwd))
        name, rest = _base(words[0]), words[1:]
        if "kgate" in [_base(w) for w in rest]:
            rest = rest[:[_base(w) for w in rest].index("kgate")]  # what follows runs on the cluster, not here
        if name == "kgate":
            return
        if name in WRAPPERS:
            command, strings = unwrap(name, rest)
            inner_waking = waking or name == "run-and-wake"
            for text in strings:
                self._text(text, cwd, loop, inner_waking, gated, depth + 1)
            if command:
                if " " in command[0] or "\n" in command[0]:  # watch "sleep 1": the one argument is a whole command line
                    self._text(command[0], cwd, loop, inner_waking, gated, depth + 1)
                more = tuple(w for w in rest[:len(rest) - len(command)] if ASSIGN.match(w))
                self._command(command, assigns + more, loop, inner_waking, gated, cwd, depth + 1)
        if name in ("find", "fd"):
            for k, w in enumerate(rest):
                if w in ("-exec", "-execdir", "-ok", "-okdir", "-x", "--exec") and k + 1 < len(rest):
                    self._command(rest[k + 1:], assigns, loop, waking, gated, cwd, depth + 1)
        if name in SHELLS:
            self._text(shell_script(words), cwd, loop, waking, gated, depth + 1)
            if scan is not None and index in scan.bodies:  # heredoc fed to a shell
                self._text(scan.bodies[index], cwd, loop, waking, gated, depth + 1)
        if name == "eval":
            self._text(" ".join(rest), cwd, loop, waking, gated, depth + 1)


def _resolve(target, cwd):
    """The directory a `cd` goes to, or None when it cannot be known here (a variable, `-`, no argument)."""
    if not target or target == "-" or "$" in target or "`" in target:
        return None
    target = os.path.expanduser(target)
    return target if os.path.isabs(target) or not cwd else os.path.join(cwd, target)


def _flag_value(args, flag):
    """The value of `--flag X` or `--flag=X` in args, else None."""
    for i, word in enumerate(args):
        if word == flag and i + 1 < len(args):
            return args[i + 1]
        if word.startswith(flag + "="):
            return word[len(flag) + 1:]
    return None


def _unescaped_backtick(body):
    i = 0
    while i < len(body):
        if body[i] == "\\":
            i += 2
        elif body[i] == "`":
            return True
        else:
            i += 1
    return False


def poll_rule(walk, ctx):
    if ctx.tool == "Monitor":
        return None
    for cmd in walk.cmds:
        if cmd.loop and not cmd.waking and _base(cmd.words[0]) == "sleep":
            return POLL
    return None


def heredoc_rule(walk, ctx):
    for scan in walk.scans:
        for quoted, body in scan.documents:
            if not quoted and _unescaped_backtick(body):
                return HEREDOC
    return None


def _current_context(text):
    match = re.search(r"^current-context:[ \t]*(.*?)[ \t]*$", text or "", re.M)
    value = match.group(1).split(" #")[0].strip().strip("'\"") if match else ""
    return value or None


def _kubectx(args):
    if any(a.startswith("-") and a != "-" for a in args) or not args or "=" in args[0]:
        return None  # a listing, a rename or a delete: no switch
    if args[0] != HOMELAB:
        return kube_message("`kubectx %s`" % args[0], "Switch only to `%s`." % HOMELAB)
    return None


def _kube_command(name, cmd, ctx):
    args = cmd.words[1:]
    if name == "kubectx":
        return _kubectx(args)
    flag = KUBE_CONTEXT_FLAG[name]
    if name == "kubectl" and "config" in args:
        after = [a for a in args[args.index("config") + 1:] if not a.startswith("-")]
        if after and after[0] == "use-context":
            if len(after) > 1 and after[1] != HOMELAB:
                return kube_message("`kubectl config use-context %s`" % after[1], "Switch only to `%s`." % HOMELAB)
        return None  # the other `kubectl config` subcommands reach no cluster
    chosen = _flag_value(args, flag)
    if chosen is not None:
        return None if chosen == HOMELAB else kube_message("`%s %s`" % (flag, chosen), "Use `%s %s`." % (flag, HOMELAB))
    here = cmd.cwd or ""
    read = ctx.read_file or read_file
    kubeconfig = _flag_value(args, "--kubeconfig")
    inline = [w[len("KUBECONFIG="):] for w in cmd.assigns if w.startswith("KUBECONFIG=")]
    if kubeconfig is not None:
        if "$" in kubeconfig or "`" in kubeconfig:
            return None  # the shell fills it in at run time; the hook cannot read it
        text = read(os.path.join(here, os.path.expanduser(kubeconfig)))
        if text is None:
            return kube_message("`--kubeconfig %s`, which is not a file on this machine," % kubeconfig,
                                "Add `%s %s`." % (flag, HOMELAB))
        current = _current_context(text)
    else:
        listed = inline[-1] if inline else (ctx.env or {}).get("KUBECONFIG") or "~/.kube/config"
        current = None
        for path in listed.split(":"):
            current = _current_context(read(os.path.join(here, os.path.expanduser(path)))) if path else None
            if current:
                break
    if current and current != HOMELAB:
        return kube_message("%s with current context `%s`" % (name, current), "Add `%s %s`." % (flag, HOMELAB))
    return None


def kube_rule(walk, ctx):
    if ctx.profile != "personal":
        return None
    for cmd in walk.cmds:
        name = _base(cmd.words[0])
        if name in KUBE_CONTEXT_FLAG or name == "kubectx":
            message = _kube_command(name, cmd, ctx)
            if message:
                return message
    return None


def merge_rule(walk, ctx):
    if ctx.profile != "personal":
        return None
    for cmd in walk.cmds:
        args = cmd.words[1:]
        if _base(cmd.words[0]) != "gh" or not any(a == "pr" and b == "merge" for a, b in zip(args, args[1:])):
            continue
        if not set(MERGE_CHECKS) <= cmd.gated:
            return MERGE_BARE
        repo = _flag_value(args, "--repo")
        repo = _flag_value(args, "-R") if repo is None else repo
        if repo is None:
            repo = (ctx.origin_of or origin_of)(cmd.cwd)
        if repo and COORDINATOR.search(repo):
            return MERGE_COORDINATOR
    return None


def pr_body_rule(walk, ctx):
    if ctx.profile != "personal":
        return None
    for cmd in walk.cmds:
        args = cmd.words[1:]
        verb = next((b for a, b in zip(args, args[1:]) if a == "pr" and b in PR_BODY_VERBS), None)
        if _base(cmd.words[0]) != "gh" or verb is None:
            continue
        verb = "create" if verb == "new" else verb
        body_file = _flag_value(args, "--body-file")
        body_file = _flag_value(args, "-F") if body_file is None else body_file
        sets_body = body_file is not None or _flag_value(args, "--body") is not None or _flag_value(args, "-b") is not None
        if verb == "edit" and not sets_body:
            continue  # a title, label or reviewer change carries no body
        if body_file is None or body_file == "-" or BODY_FILE + body_file not in cmd.gated:
            return PR_BODY % (verb, verb)
    return None


def _docker_spelling(words):
    """The refused docker command in words (`docker run`, `docker compose up`, ...), else None. Only the subcommand position counts."""
    name = _base(words[0])
    if name not in ("docker", "docker-compose"):
        return None
    subcommand, i = [], 1
    while i < len(words) and len(subcommand) < 2:
        word = words[i]
        compose = name == "docker-compose" or (subcommand and subcommand[0] == "compose")
        if word in DOCKER_OPTIONS_WITH_VALUE | (COMPOSE_OPTIONS_WITH_VALUE if compose else set()):
            i += 2
            continue
        i += 1
        if not word.startswith("-"):
            subcommand.append(word)
    if name == "docker-compose":
        subcommand = ["compose"] + subcommand
    for size in (1, 2):
        if tuple(subcommand[:size]) in DOCKER_REFUSED:
            return " ".join(["docker"] + subcommand[:size])
    return None


def docker_rule(walk, ctx):
    if ctx.profile != "personal" or not (ctx.platform or sys.platform).startswith("linux"):
        return None
    for cmd in walk.cmds:
        spelling = _docker_spelling(cmd.words)
        if spelling:
            return DOCKER % spelling
    return None


def check(text, ctx):
    """The refusal message for the command text, or None."""
    walk = Walk(text, ctx.cwd)
    for rule in (poll_rule, heredoc_rule, kube_rule, merge_rule, pr_body_rule, docker_rule):
        message = rule(walk, ctx)
        if message:
            return message
    return None
