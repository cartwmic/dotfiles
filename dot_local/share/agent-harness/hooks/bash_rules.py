"""Nine refusals for an agent's shell command, run by refuse_pattern_kill.py after its pkill check. Each names the fix.

  sleep-poll  (both profiles)  a `while` or `until` loop whose body runs `sleep`: use `run-and-wake -- <cmd>`. Not refused: anything under
              `run-and-wake`, `for` loops, `while read` loops (they walk items), a lone sleep. Skipped for Claude's Monitor tool.
  heredoc     (both profiles)  an unquoted heredoc delimiter with an unescaped backtick in the body: quote it (`<<'EOF'`). Any command,
              also inside `$( )`.
  kube        (personal only)  kubectl, helm, k9s, kubectx on a context other than the homelab's: a context flag, `kubectl config
              use-context`, `kubectx X`, or no flag while the current context (--kubeconfig, an inline KUBECONFIG=, the hook's KUBECONFIG,
              else ~/.kube/config) is another. kubectl inside an ssh string is not inspected. No kubeconfig or no current-context: allowed.
  merge       (personal and work)  `gh pr merge` unless BOTH gates, in their real form, are joined to it by `&&` earlier in the same and-list
              (any order): `ci-main-status --merge-gate <repo> [--pr N]` (a bare one or `--tip` is not the gate) and
              `pr-body-check <repo> <pr>` (two plain words; `pr-body-check --body-file F` is not the merge check, it never reads the PR's
              head runs), with <pr> the PR number `gh pr merge` names when it names one (a branch or no PR cannot be matched); the refusal names
              `ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr> --match-head-commit <head sha> ...`:
              --merge-gate exits 0 for UNTESTED and 1 for RED, as playbook fab9b713 allows an untested merge; a bare `ci-main-status`
              exits 2 for UNTESTED and blocks it. `--match-head-commit <head sha>` makes the merge refuse unless the PR head is still
              the commit the checks read. The PR that fixes a red main adds `--pr N`: `--merge-gate <repo> --pr N` passes a red
              GitHub-run main when PR N's own full-suite run on its head tree succeeded (a pull_request run that skips the suite
              does not count; a workflow_dispatch run does). dotfiles tries its release-pins fix rule first, then that same rule.
              Never for cartwmic/coordinator (`-R`, else the git origin of the directory it runs in): use merge-pr.sh,
              which runs both checks itself. Never for cartwmic/cartwmic-homelab-v2 either, found the same way and refused even
              before the gates: use `~/git/cartwmic-homelab-v2/scripts/merge-pr.sh N SHA` (it adds the RED-line check the chained
              form lacks). The playbook CLI, loop_engine_bump.py and agent_kit_bump.py run gh as a child process
              the hook never sees, so they pass.

  pr-body     (personal and work)  `gh pr create`, and `gh pr edit` when it sets a body, unless the body comes from `--body-file F` (or `-F F`)
              and `pr-body-check --body-file F` with the same F is joined to it by `&&` earlier in the same and-list, and, when the command
              sets `--title T`, that check was given the same `--title T` (it reads the title for task ids). Refused: an inline
              `--body`/`-b`, `--fill`, a create with no body flag, a body from stdin (`-F -`), a different file. The refusal names
              `pr-open --title T --body-file F` (create) or `pr-open --edit N --body-file F` (edit) as the shortest path, then the chained form
              `pr-body-check --body-file F --title T && gh pr create --title T ... --body-file F`, so bookkeeping in the description (the principles table,
              a table in a Proven section, a Decisions: line, ledger or job ids; it belongs in the PR's agent record, playbook 5a05bfe8; a
              Proven section as plain prose stays, playbook f5a367b5) fails when the body is written, not at merge. `gh pr edit` with no
              body flag (title, labels, reviewers) passes. No repo is exempt: unlike the merge rule, nothing else runs this check at create time.
              The body file must also be a mktemp name, so another session cannot overwrite it (2026-11-15: a shared /tmp/pr-body.md put
              one PR's body on another): `F=$(mktemp /tmp/pr-N-body.XXXXXX)` earlier in the same command and `--body-file "$F"`, or the
              literal name mktemp made (last dot-part 6+ letters and digits with a digit or capital). A fixed name is refused for create and
              edit; for `gh pr edit N` the name must also contain N. A `$VAR` the command does not assign from mktemp is refused. A name
              is checked even when the chain is right; when both are wrong the refusal gives both fixes.

  heavy       (agent host pod only)  a test, journey or stress run in the pod itself: `npm test` / `npm t` / `npm run test*` (and pnpm, yarn, bun,
              `yarn workspace <x> test`, `corepack pnpm test`), `vitest` (also `npx`, `bunx`, `pnpx`, `pnpm exec`, `npm exec`, `node .../vitest`),
              `python3 scripts/journeys.py` (also `uv run scripts/journeys.py`), `stress` and `stress-ng`: the pod is shared
              by every agent and the coordinator, so these run on the cluster (playbook 83fbe006); the refusal names `run-and-wake -- kgate -- <cmd>`.
              Not refused: anything after `kgate` (it runs on the cluster), `scripts/kgate-journeys.sh`, typecheck, lint (also scripts named `typecheck:test`, `lint:test`),
              other runners (playwright, make), `node script.ts`, git.
              The pod is known by the `container` file beside this script (chezmoi renders it from container mode, true only there) or
              AGENT_HARNESS_CONTAINER=true; on every other machine, and on the work profile, the rule does nothing.
  docker      (personal, Linux only)  `docker run`, `docker build`, `docker compose up` and their spellings (`docker container run`,
              `docker image build`, `docker buildx build`, `docker builder build`, `docker-compose up`, global options before the
              subcommand such as `docker -H x run` or `docker compose -f f.yml up`): this workstation runs no local Docker; the refusal
              names kgate and a throwaway namespace on the homelab cluster (ledger grant 21). Read-only commands (`docker ps`, `images`,
              `inspect`, `manifest inspect`, `compose ps`) pass, and so does anything after `kgate`. Other personal hosts (the Mac, which
              has Docker Desktop for agents) are untouched, since Docker is provisioned there on purpose.
  live git    (both profiles)  git that changes the working tree, index, HEAD or a branch of the live coordinator checkout, ~/git/coordinator (and the profile's own checkout when it is another path: line 1 of the `coordinator-instance` file chezmoi renders, ~/coordinator-work on work),
              which the coordinator daemon runs from (2026-11-11: a reviewer checked out PR #438 there and the daemon restarted onto PR code;
              2026-11-16: a builder ran `git merge origin/main` there). Refused: merge, pull, reset, checkout, switch, restore, commit, rebase,
              cherry-pick, revert, stash, clean, am, apply, add, rm, mv, update-ref, symbolic-ref, branch (that creates, deletes or renames), and
              `gh pr checkout` / `gh pr co` run in the live checkout.
              Allowed there: `merge --abort`, `merge --ff-only <sha>` (the deploy; 7 to 40 hex, never a ref), `reset --keep <sha>` (the rollback in
              docs/deploy.md), fetch, `stash list|show`, worktree add/remove/prune, every read-only git. The place is the command's directory
              (the session's, a `cd` or `pushd`, each `-C`) or a `--git-dir`, `--work-tree`, GIT_DIR, GIT_WORK_TREE; `~`, `$HOME` and `${HOME}`
              are the Context's HOME. The refusal names `git worktree add ~/tmp-home/<name> origin/main`.
  credential  (both profiles)  a command that reads credential config raw, or hides its secrets with a line regex. Credential config is a path
              list (below), not content sniffing: RustDesk's config directory and RustDesk*.toml, rclone.conf, .env and .env.* (not
              .env.example), .netrc, .git-credentials, .pgpass, .npmrc, .pypirc, .aws/credentials, .docker/config.json, gh's hosts.yml,
              credentials/secrets files, the 1Password service-account token. A reader (cat, head, tail, less, bat, grep, sed, awk, cut,
              sort, strings, jq, yq, ...) with one of those as an argument or `<` input is refused; `grep -l/-L/-c/-q`, `sed -i`, ls, stat, cp,
              wc and the reader itself pass. Also refused, on any input: a sed, perl, awk or PowerShell `-replace` substitution whose pattern
              names a secret word (password, key, token, salt, ...) and whose replacement is a mask (`<hidden>`, `***`). The refusal names
              `~/.local/share/agent-harness/bin/config-show FILE [--show KEY]`, which parses the file and masks every value whole.
              Not covered: the sign-in code leak (decision #2330): a code reaches the transcript from a browser page or a message tool, not
              from a file or a shell command, so the hook has nothing to match.

Commands are found like the pkill classifier finds them (it supplies the parser): through quotes, `;` `&&` `|`, `$( )`, `sh -c`, `eval`,
wrappers, `find -exec`, heredocs fed to a shell. Not covered: a command built at run time (`$cmd`), a script file, `python -c`, a command
in an ssh remote string, a kubeconfig path or `cd` target that holds a shell variable (`$HOME` aside), a `cd` in `( )` (it counts for the commands after the `)`). The rules are pure functions on the text and a
Context; the file reads and the git call are the Context's `read_file` and `origin_of`. The caller treats any exception as "allow".
"""
import os
import re
import shlex
import subprocess
import sys
from collections import namedtuple

from refuse_pattern_kill import ASSIGN, SHELLS, WRAPPERS, Scan, _base, _command_words, shell_script, unwrap

HOMELAB = "kubernetes-admin@kubernetes"
MERGE_PR = "~/git/coordinator/scripts/merge-pr.sh"
COORDINATOR = re.compile(r"cartwmic/coordinator(?:\.git)?(?![\w-])")
HOMELAB_MERGE_PR = "~/git/cartwmic-homelab-v2/scripts/merge-pr.sh"
HOMELAB_REPO = re.compile(r"cartwmic/cartwmic-homelab-v2(?:\.git)?(?![\w-])")
KUBE_CONTEXT_FLAG = {"kubectl": "--context", "k9s": "--context", "helm": "--kube-context"}
# docker: the options before the subcommand that take a value (`docker -H host run`), the same for `compose` (`compose -f f.yml up`), and
# the (subcommand, ...) words that start a local container or image build.
DOCKER_OPTIONS_WITH_VALUE = {"-H", "--host", "-c", "--context", "-l", "--log-level", "--config", "--tlscacert", "--tlscert", "--tlskey"}
COMPOSE_OPTIONS_WITH_VALUE = {"-f", "--file", "-p", "--project-name", "--profile", "--env-file", "--project-directory", "--ansi", "--parallel"}
DOCKER_REFUSED = {("run",), ("build",), ("container", "run"), ("image", "build"), ("buildx", "build"), ("builder", "build"), ("compose", "up")}

LIVE_CHECKOUT = "git/coordinator"  # under $HOME on both profiles: the checkout the coordinator daemon runs from
GATE_PROFILES = ("personal", "axon-work-computer")  # the PR gates (merge, pr-body) run on both desktop profiles; any other profile (Termux) has none
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}  # options before the subcommand
GIT_ALWAYS_REFUSED = {"pull", "reset", "checkout", "switch", "restore", "commit", "rebase", "cherry-pick", "revert", "clean", "am", "apply",
                      "add", "rm", "mv", "update-ref", "symbolic-ref", "read-tree"}
GIT_MERGE_FLAGS = {"--ff-only", "-q", "--quiet", "-v", "--verbose", "--stat", "--no-stat", "-n"}  # a fast-forward to a sha takes nothing else
GIT_BRANCH_CHANGES = {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f", "--force", "-u", "--set-upstream-to",
                      "--unset-upstream", "--edit-description"}
GIT_BRANCH_LISTS = {"-l", "--list", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"}
SHA = re.compile(r"[0-9a-fA-F]{7,40}")

POLL = (
    "A sleep-poll loop is refused in agent sessions: it holds the pane while it waits. "
    "Run the job with `run-and-wake -- <cmd>`: builders wait for it as run-and-wake says, and other seats end their turn."
)
HEREDOC = (
    "An unquoted heredoc with a backtick is refused in agent sessions: the shell runs the backticked text as a command. "
    "Quote the delimiter (`<<'EOF'`), or escape each backtick."
)
CI_GATE = "ci-main-status --merge-gate"  # the gated entry for a real `ci-main-status --merge-gate <repo> [--pr N]`
PR_CHECK = "pr-body-check PR "           # prefix of the gated entry for a real `pr-body-check <repo> <pr>`: PR_CHECK + the PR number
BODY_FILE = "pr-body-check --body-file "  # prefix of the gated entry that names a file the body check already read
BODY_TITLE = "pr-body-check --title "  # prefix of the gated entry that names a title the body check already read
MERGE_BARE = (
    "`gh pr merge` without both gates in their real form is refused in agent sessions: it skips the red-main gate (playbook fab9b713) or the PR body check. "
    "A bare `ci-main-status` (or `--tip`) is not the gate, and a `pr-body-check` with `--body-file` is not the merge check: only `pr-body-check <repo> <pr>` reads the PR's head runs. "
    "For cartwmic/coordinator use `" + MERGE_PR + " PR`; for other repos run "
    "`ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr> --match-head-commit <head sha> ...` "
    "(--merge-gate lets an untested tip merge and stops only red; `--pr <pr>` after it passes a red main for the PR that fixes it, when that PR's "
    "own full-suite run on its head tree passed; pr-body-check enforces playbook rules ecd63156, 385acc43, ccc6c94b and 5a05bfe8; it reads the principles table, the Decisions line and the `Promises:` line (each promise `=>` its evidence, or `none, <reason>`) from the PR's agent record, `pr-record path <repo>#N` prints where, and a PR with none is refused; it also refuses a PR with an unresolved review thread, and a description with no Proven section); "
    "pin bumps use loop_engine_bump.py or agent_kit_bump.py; playbook edits use the playbook CLI with --pr --merge."
)
PR_BODY = (
    "`gh pr %s` without a checked body file is refused in agent sessions: a description with agent bookkeeping (the principles table or a table in the Proven section, a Decisions: line, "
    "ask/decision/grant ids, job ids, Rewinds:, Break-glass:) or a task id is otherwise found only when `gh pr merge` runs. Shortest path: %s. "
    "Or run `pr-body-check --body-file F --title T && gh pr %s --title T ... --body-file F` (the same file F and the same title T in both: the check reads the title for task ids, which become part of the commit text on main; an edit that keeps the title leaves `--title T` out of both). "
    "A playbook-only PR (no code to check) passes the body check with `--files-file F`, `--pr N [--repo R]` or `--base REF` added to it. The description keeps what changes, why, how it was checked "
    "(a Proven section as plain prose, playbook f5a367b5), risk and `Refs #N`; the bookkeeping goes in the PR's agent record (`pr-record path <repo>#N` prints where; playbook 5a05bfe8). "
    "The `--body-file` form never reads the agent record: once the PR exists and before you report, run `pr-body-check <owner/repo> <pr> --skip-intent-review`, which does."
)
PR_OPEN = {  # the one-command form of PR_BODY, by verb: pr-open checks the body, pushes, opens or PATCHes, and prints the URL
    "create": "`pr-open --title T --body-file F [--draft]` (F is the body file, `-` reads it from stdin; it checks the body, pushes the branch and opens the PR)",
    "edit": "`pr-open --edit N --body-file F` (it checks the body, then sets it through `gh api`, because `gh pr edit` fails on the agent host)",
}
PR_API_BODY = (
    "`gh api` that sets a pull request body (POST, PATCH or PUT on `repos/<owner>/<repo>/pulls` or `.../pulls/<n>` with a `body` field or `--input`) is refused in agent sessions: "
    "it skips the body check that `gh pr create|edit` gets, so agent bookkeeping in the description is found only when `gh pr merge` runs. "
    "Shortest path: %s or %s."
)
PR_API_ISSUE_BODY = (
    "`gh api` PATCH on `repos/<owner>/<repo>/issues/<n>` with a `body` field or `--input` is refused in agent sessions: a pull request is an issue too, so this can set a pull request body "
    "and skip the body check, and the hook cannot tell a PR number from an issue number without a lookup. For a PR: %s. For an issue: `gh issue edit N --body-file F`."
)
PR_API_ENDPOINT = re.compile(r"(?:https://[^/]+/(?:api/v3/)?|/)?(?P<path>repos/[^/]+/[^/]+/(?P<kind>pulls|issues)(?:/\d+)?/?)(?:\?.*)?")
PR_API_FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field")
PR_API_VALUE_FLAGS = ("-H", "--header", "-q", "--jq", "-t", "--template", "--cache", "--hostname", "-p", "--preview")
PR_BODY_VERBS = ("create", "new", "edit")  # `gh pr new` is an alias of `gh pr create`
PR_TITLE = (
    "`gh pr %s --title %s` sets a title that `pr-body-check` was not given: the check reads the title for task ids, which become part of the commit text on main, and it can only read the one it is passed. "
    "Pass the same title to both: `pr-body-check --body-file F --title T && gh pr %s --title T ... --body-file F`, or use %s."
)
PR_BODY_FILE = (
    "The body file %s is refused in agent sessions: %s. Make the body file with `F=$(mktemp /tmp/pr-%s-body.XXXXXX)` in the same command "
    "and pass `--body-file \"$F\"`; a fixed name like /tmp/pr-body.md can be overwritten by another session. "
    "Or use %s: it takes any body file and posts its own private copy."
)
# What counts as a mktemp name: a template (`VAR=$(mktemp TEMPLATE)` earlier in the same command text, `--body-file "$VAR"`) whose last part
# ends in MKTEMP_MIN_X or more X, or a literal name whose last dot-part is MKTEMP_MIN_X or more letters and digits with a digit or an
# uppercase letter (what mktemp made in an earlier call; `.markdown` and `.md` do not match). mktemp options that take a value are skipped
# to find the template; a bare `mktemp` has the template tmp.XXXXXXXXXX.
MKTEMP_VALUE_OPTIONS = {"-p", "--tmpdir", "--suffix"}
MKTEMP_MIN_X = 6
MKTEMP_LITERAL = re.compile(r"\.(?=[A-Za-z0-9]*[0-9A-Z])[A-Za-z0-9]{%d,}$" % 6)
MERGE_OTHER_PR = "`pr-body-check` checked PR %s, but `gh pr merge` merges PR %s: the check must name the PR that is merged. "
MERGE_COORDINATOR = (
    "`gh pr merge` on cartwmic/coordinator is refused in agent sessions: " + MERGE_PR + " also runs the red-main gate and the decisions check. "
    "Use `" + MERGE_PR + " PR`."
)
MERGE_HOMELAB = (
    "`gh pr merge` on cartwmic/cartwmic-homelab-v2 is refused in agent sessions: " + HOMELAB_MERGE_PR + " runs the red-main gate, `pr-body-check` and "
    "the RED-line check for a PR that changes a test file, and a typed merge skips the last one. "
    "Use `" + HOMELAB_MERGE_PR + " N SHA` (N the PR number, SHA the head the checks and the review read)."
)


GIT_LIVE = (
    "`%s` in the live coordinator checkout (%s) is refused in agent sessions: the daemon runs from that checkout, and a "
    "change to its working tree, index, HEAD or a branch changes the code it runs. "
    "Use a git worktree (git worktree add ~/tmp-home/<name> origin/main); the live checkout runs the daemon; only fetch and the deploy's "
    "`git merge --ff-only <sha>` are allowed there (and the rollback `git reset --keep <sha>`). "
    "See coordinator AGENTS.md, \"The live checkout\" (docs/deploy.md#the-live-checkout)."
)


DOCKER = (
    "`%s` is refused in agent sessions: this workstation runs no local Docker. "
    "Run the job on kgate (`run-and-wake -- kgate -- <cmd>`), or in a throwaway namespace on the homelab cluster under ledger grant 21 "
    "(create the namespace, run the job there, delete the namespace)."
)


HEAVY = (
    "`%s` is refused in agent sessions in the agent host pod: the pod is shared by every agent and the coordinator, and heavy jobs (tests, journeys, stress runs) run on the cluster (playbook 83fbe006). "
    "Run it on kgate: `run-and-wake -- kgate -- <cmd>` (for example `run-and-wake -- kgate -- npm test`). "
    "If GitHub CI runs the same suite on the same commit, push and read CI instead of running it again."
)


def kube_message(what, fix):
    return (
        "%s is refused in agent sessions: the personal homelab grant (playbook f90b9301) covers only the cluster with context `%s`. %s"
        % (what, HOMELAB, fix)
    )


Context = namedtuple("Context", "tool profile env cwd read_file origin_of platform container coordinator_repo run door", defaults=(None,) * 11)


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

    def __init__(self, text, cwd=None, home=None):
        self.home = home or os.path.expanduser("~")  # what `~`, `$HOME` and `${HOME}` mean in a `cd` or `git -C` target
        self.cmds = []    # Cmd: words from the command position (wrappers unwrapped), the assignments before it,
        self.scans = []   # in a polling loop, under run-and-wake, the merge checks run earlier by && (a frozenset), working directory
        self.text = text
        self.mktemps = {}  # variable name -> the mktemp template of the last `VAR=$(mktemp TEMPLATE)` in the text (nested texts included)
        self._text(text, cwd, False, False, frozenset(), 0)

    def _text(self, text, cwd, loop, waking, gated, depth):
        if depth > 8 or not text:
            return
        scan = Scan(text)
        self.scans.append(scan)
        code = text
        for _quoted, body in scan.documents:  # a heredoc body is data (a PR body may quote the fix line), not an assignment
            code = code.replace(body, "")
        for name, args in MKTEMP_ASSIGN.findall(code):
            self.mktemps[name] = _mktemp_template(args)
        loops = []  # one entry per open while/until/for: True when it polls (not a `while read` and not a `for`)
        for index, raw in enumerate(scan.commands):
            self._nested(scan, lambda at, index=index: at == index, cwd, loop, waking, gated, depth)  # the cwd this command runs in
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
            if _base(words[0]) in ("cd", "pushd"):
                target = next((w for w in words[1:] if w != "--" and not w.startswith("-")), None)
                cwd = _resolve(target, cwd, self.home)
        self._nested(scan, lambda at: at >= len(scan.commands), cwd, loop, waking, gated, depth)

    def _nested(self, scan, wanted, cwd, loop, waking, gated, depth):
        """Scan the $( ) texts whose command index passes `wanted`, in the directory the command around them runs in."""
        for at, inner in zip(scan.nested_at, scan.nested):
            if wanted(at):
                self._text(inner, cwd, loop, waking, gated, depth + 1)

    @staticmethod
    def _and_listed(scan, index):
        """The checks earlier in this command's and-list, joined to it only by `&&`: CI_GATE for a real `ci-main-status --merge-gate <repo>`,
        PR_CHECK + N for a real `pr-body-check <repo> N`, and BODY_FILE + F for each `pr-body-check --body-file F` (which is not a merge check)."""
        found = set()
        j = index
        while j > 0 and scan.joins[j].strip() == "&&":
            j -= 1
            earlier = _command_words(scan.commands[j])
            if not earlier:
                continue
            name, args = _base(earlier[0]), earlier[1:]
            if name == "ci-main-status" and _is_merge_gate(args):
                found.add(CI_GATE)
            elif name == "pr-body-check":
                number = _is_pr_check(args)
                if number:
                    found.add(PR_CHECK + number)
                body_file = _flag_value(args, "--body-file")
                if body_file is not None:
                    found.add(BODY_FILE + body_file)
                title = _flag_value(args, "--title")
                if title is not None:
                    found.add(BODY_TITLE + title)
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


MKTEMP_ASSIGN = re.compile(r"(?<![\w$])([A-Za-z_]\w*)=[\"']?(?:\$\(|`)\s*mktemp\b([^)`]*)")


def _mktemp_template(args):
    """The template word of `mktemp ARGS` (its options skipped), else the default `tmp.XXXXXXXXXX`."""
    words = args.replace('"', " ").replace("'", " ").split()
    i = 0
    while i < len(words):
        if words[i] in MKTEMP_VALUE_OPTIONS:
            i += 2
        elif words[i].startswith("-"):
            i += 1
        else:
            return words[i]
    return "tmp.XXXXXXXXXX"


def _resolve(target, cwd, home):
    """The directory a `cd` goes to, or None when it cannot be known here (a variable other than $HOME, `-`, no argument)."""
    if not target or target == "-":
        return None
    for form in ("${HOME}", "$HOME"):
        if target == form or target.startswith(form + "/"):
            target = home + target[len(form):]
    if target == "~" or target.startswith("~/"):
        target = home + target[1:]
    elif target.startswith("~"):
        target = os.path.expanduser(target)
    if "$" in target or "`" in target:
        return None
    return target if os.path.isabs(target) or not cwd else os.path.join(cwd, target)


def _is_merge_gate(args):
    """True for `--merge-gate <repo>` with an optional `--pr N` (the words after ci-main-status): one repo, no `--tip`, no `--all`."""
    if "--merge-gate" not in args or "--tip" in args:
        return False
    rest = [w for w in args if w != "--merge-gate"]
    if "--pr" in rest:
        k = rest.index("--pr")
        if k + 1 >= len(rest) or not rest[k + 1].isdigit():
            return False
        del rest[k:k + 2]
    return len(rest) == 1 and not rest[0].startswith("-")


def _is_pr_check(args):
    """The PR number of a real `pr-body-check <repo> <pr>` (the words after pr-body-check: two plain words, no flag), else None."""
    if len(args) == 2 and not any(a.startswith("-") for a in args) and args[1].isdigit():
        return str(int(args[1]))
    return None


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
    if ctx.profile not in GATE_PROFILES:
        return None
    for cmd in walk.cmds:
        args = cmd.words[1:]
        if _base(cmd.words[0]) != "gh" or not any(a == "pr" and b == "merge" for a, b in zip(args, args[1:])):
            continue
        repo = _flag_value(args, "--repo")
        repo = _flag_value(args, "-R") if repo is None else repo
        if repo is None:
            repo = (ctx.origin_of or origin_of)(cmd.cwd)
        if repo and HOMELAB_REPO.search(repo):
            return MERGE_HOMELAB  # before the gates: the chained form skips the homelab RED-line check, so it is no way through
        checked = {e[len(PR_CHECK):] for e in cmd.gated if e.startswith(PR_CHECK)}
        if CI_GATE not in cmd.gated or not checked:
            return MERGE_BARE.replace(MERGE_PR, _merge_pr(ctx))
        merged = _pr_number(args, "merge", PR_MERGE_VALUE_FLAGS)  # None when it names a branch or no PR: the hook cannot see which
        if merged and str(int(merged)) not in checked:
            return MERGE_OTHER_PR % (" and ".join(sorted(checked, key=int)), merged) + MERGE_BARE.replace(MERGE_PR, _merge_pr(ctx))
        if repo and COORDINATOR.search(repo):
            return MERGE_COORDINATOR.replace(MERGE_PR, _merge_pr(ctx))
    return None


PR_EDIT_VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--title", "-B", "--base", "-a", "--add-assignee",
                       "--add-label", "--add-project", "--add-reviewer", "--remove-assignee", "--remove-label", "--remove-project",
                       "--remove-reviewer", "-m", "--milestone"}


PR_MERGE_VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email", "--match-head-commit"}


def _pr_number(args, verb="edit", value_flags=PR_EDIT_VALUE_FLAGS):
    """The PR number `gh pr <verb>` names (a number, or a .../pull/N URL), else None (a branch name, or none)."""
    rest = args[args.index(verb) + 1:]
    i = 0
    while i < len(rest):
        if rest[i] in value_flags:
            i += 2
        elif rest[i].startswith("-"):
            i += 1
        else:
            found = re.fullmatch(r"\d+|.*/pull/(\d+)/?", rest[i])
            return (found.group(1) or found.group(0)) if found else None
    return None


def _body_file_problem(body_file, verb, number, mktemps):
    """Why the body file's name is refused (a fixed name, a mktemp name without the PR number), else None."""
    var = re.fullmatch(r"\$(\w+)|\$\{(\w+)\}", body_file)
    template = mktemps.get(var.group(1) or var.group(2)) if var else None
    if var and template is None:
        return PR_BODY_FILE % ("`%s`" % body_file, "its name is not known here (no `%s=$(mktemp ...)` in this command)" % (var.group(1) or var.group(2)), number or "N", PR_OPEN[verb])
    name = os.path.basename(template if var else body_file)
    shaped = re.search("X{%d,}$" % MKTEMP_MIN_X, name) if var else MKTEMP_LITERAL.search(name)
    if not shaped:
        return PR_BODY_FILE % ("`%s`" % body_file, "it is a fixed name or not made by mktemp, so another session can overwrite it", number or "N", PR_OPEN[verb])
    if verb == "edit" and number and not re.search(r"(?<!\d)%s(?!\d)" % number, name):
        return PR_BODY_FILE % ("`%s`" % body_file, "its name `%s` does not contain PR number %s" % (name, number), number, PR_OPEN[verb])
    return None


def _api_sets_pr_body(args):
    """The record of a `gh api ARGS` call that sets a PR body, else None: a POST/PATCH/PUT on a pulls endpoint (or a PATCH on `issues/<n>`, which can set a PR body)
    with a `body` field or `--input` (whose JSON the hook cannot see). Attached values (`-fbody=x`, `-f=body=x`, `-XPATCH`) are read the way gh reads them.
    The record is {method, endpoint, reason, command}; `command` is rebuilt from the parsed parts with every field value redacted, so it never holds a body or a token."""
    words = [w for w in args if w != "--"]
    api = next((i for i, w in enumerate(words) if not w.startswith("-")), None)
    if api is None or words[api] != "api":
        return None
    rest = words[api + 1:]
    endpoint, fields, method, input_file, i = None, [], None, None, 0
    while i < len(rest):
        word, nxt = rest[i], rest[i + 1] if i + 1 < len(rest) else ""
        flag, eq, value = word.partition("=")
        short = word[:2] if len(word) > 2 and word[1] != "-" else None  # -fbody=x, -f=body=x, -XPATCH: the value is attached
        if word in PR_API_FIELD_FLAGS or (eq and flag in PR_API_FIELD_FLAGS and word.startswith("--")):
            fields.append((flag, value if eq else nxt))
            i += 1 if eq else 2
        elif short in PR_API_FIELD_FLAGS:
            fields.append((short, word[2:].removeprefix("=")))
            i += 1
        elif word in ("-X", "--method") or (eq and flag == "--method"):
            method = (value if eq else nxt).upper()
            i += 1 if eq else 2
        elif short == "-X":
            method = word[2:].removeprefix("=").upper()
            i += 1
        elif flag == "--input" and (eq or word == "--input"):
            input_file = value if eq else nxt
            i += 1 if eq else 2
        elif word in PR_API_VALUE_FLAGS:
            i += 2
        elif word.startswith("-"):
            i += 1
        else:
            endpoint = endpoint or word
            i += 1
    found = PR_API_ENDPOINT.fullmatch(endpoint) if endpoint else None
    if not found:
        return None
    has_body = input_file is not None or any(f.partition("=")[0] == "body" for _, f in fields)
    method = method or ("POST" if fields or input_file is not None else "GET")
    pulls = found.group("kind") == "pulls"
    if not has_body or not (method in ("POST", "PATCH", "PUT") if pulls else method == "PATCH" and re.search(r"/\d+/?$", found.group("path"))):
        return None
    shown = ["gh", "api", "-X", method, found.group("path")] + [x for flag, f in fields for x in (flag, f.partition("=")[0] + "=<redacted>")]
    if input_file is not None:
        shown += ["--input", input_file]
    reason = "%s on the %s endpoint sets a body (%s)" % (method, found.group("kind"), "--input" if input_file is not None else "a body field")
    return {"method": method, "endpoint": found.group("path"), "reason": reason, "command": " ".join(shown), "kind": found.group("kind")}


def pr_body_rule(walk, ctx):
    if ctx.profile not in GATE_PROFILES:
        return None
    for cmd in walk.cmds:
        args = cmd.words[1:]
        api_body = _base(cmd.words[0]) == "gh" and _api_sets_pr_body(args)
        if api_body:
            template = PR_API_BODY if api_body["kind"] == "pulls" else PR_API_ISSUE_BODY
            message = Matched(template % ((PR_OPEN["create"], PR_OPEN["edit"]) if api_body["kind"] == "pulls" else (PR_OPEN["edit"],)),
                              "%s %s" % (api_body["method"], api_body["endpoint"]))
            message.log = {"reason": api_body["reason"], "command": api_body["command"]}
            return message
        verb = next((b for a, b in zip(args, args[1:]) if a == "pr" and b in PR_BODY_VERBS), None)
        if _base(cmd.words[0]) != "gh" or verb is None:
            continue
        verb = "create" if verb == "new" else verb
        body_file = _flag_value(args, "--body-file")
        body_file = _flag_value(args, "-F") if body_file is None else body_file
        sets_body = body_file is not None or _flag_value(args, "--body") is not None or _flag_value(args, "-b") is not None
        if verb == "edit" and not sets_body:
            continue  # a title, label or reviewer change carries no body
        if body_file is None or body_file == "-":
            return PR_BODY % (verb, PR_OPEN[verb], verb)
        number = _pr_number(args) if verb == "edit" else None
        problems = [_body_file_problem(body_file, verb, number, walk.mktemps)]
        if BODY_FILE + body_file not in cmd.gated:
            problems.append(PR_BODY % (verb, PR_OPEN[verb], verb))
        title = _flag_value(args, "--title")
        if title is not None and BODY_FILE + body_file in cmd.gated and BODY_TITLE + title not in cmd.gated:
            problems.append(PR_TITLE % (verb, shlex.quote(title), verb, PR_OPEN[verb]))
        problems = [p for p in problems if p]
        if problems:
            return " ".join(problems)
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


JS_RUNNERS = {"npm", "pnpm", "yarn", "bun"}
JS_VALUE_OPTIONS = {"--prefix", "-C", "--cwd", "--filter", "-F", "-w", "--workspace", "--dir"}  # options before the subcommand that take a value
HEAVY_SCRIPT = re.compile(r"(?:^|[:_-])(?:tests?|vitest|journeys?|stress)(?:$|[:_-])")  # a package script that runs tests, journeys or stress
LIGHT_SCRIPT = re.compile(r"^(?:typecheck|lint)(?:$|[:_-])")  # typecheck:test and lint:test check files; they are not test runs


def _heavy_script(name):
    return bool(HEAVY_SCRIPT.search(name)) and not LIGHT_SCRIPT.match(name)
NPM_TEST = {"test", "t", "tst"}


def _js_args(words):
    """The words after the package manager that are not options (an option that takes a value is skipped with it)."""
    args, i = [], 0
    while i < len(words):
        if words[i] in JS_VALUE_OPTIONS:
            i += 2
            continue
        if not words[i].startswith("-"):
            args.append(words[i])
        i += 1
    return args


def _heavy_spelling(words):
    """The heavy command in words (`npm test`, `npx vitest`, ...), else None. Only the command position counts."""
    name = _base(words[0])
    args = _js_args(words[1:])
    if name in ("vitest", "stress", "stress-ng", "journeys.py"):
        return name
    if name.startswith("python") and args and _base(args[0]) == "journeys.py":
        return "%s %s" % (name, args[0])
    if name in ("node", "nodejs") and args and _base(args[0]) in ("vitest", "vitest.mjs"):  # node node_modules/.bin/vitest run
        return "%s vitest" % name
    if name in ("corepack", "uv") and args:  # corepack pnpm test; uv run scripts/journeys.py
        inner = words[2:] if name == "uv" and args[0] == "run" else words[1:] if name == "corepack" else None
        return _heavy_spelling(inner) if inner else None
    if name in ("npx", "bunx", "pnpx"):
        return "%s vitest" % name if args and _base(args[0]) == "vitest" else None
    if name not in JS_RUNNERS or not args:
        return None
    sub, more = args[0], args[1:]
    if name == "yarn" and sub == "workspace" and len(more) >= 2:  # yarn workspace web test
        sub, more = more[1], more[2:]
    if sub in ("exec", "dlx", "x") and more and _base(more[0]) == "vitest":
        return "%s %s vitest" % (name, sub)
    if sub in ("run", "run-script", "rum", "urn") and more and _heavy_script(more[0]):
        return "%s %s %s" % (name, sub, more[0])
    if sub in NPM_TEST or (name != "npm" and _heavy_script(sub)):
        return "%s %s" % (name, sub)
    return None


class Matched(str):
    """A refusal message that also carries the command name the rule matched (`npx vitest`), for the guard log."""
    def __new__(cls, message, matched):
        self = super().__new__(cls, message)
        self.matched = matched
        return self


def heavy_rule(walk, ctx):
    if not ctx.container:
        return None
    for cmd in walk.cmds:
        spelling = _heavy_spelling(cmd.words)
        if spelling:
            return Matched(HEAVY % spelling, spelling)
    return None


def _git_parts(words):
    """(options before the subcommand as (name, value) pairs, subcommand or None, the words after it) of a git command."""
    opts, i = [], 1
    while i < len(words) and words[i].startswith("-"):
        name, equals, value = words[i].partition("=")
        if words[i] in GIT_VALUE_OPTIONS:
            opts.append((words[i], words[i + 1] if i + 1 < len(words) else None))
            i += 2
            continue
        if equals and name in GIT_VALUE_OPTIONS:
            opts.append((name, value))
        i += 1
    return opts, (words[i] if i < len(words) else None), words[i + 1:]


def _git_change(sub, args):
    """The spelling (`git merge`) of a git command that changes the working tree, index, HEAD or a branch, else None."""
    flags = [a for a in args if a.startswith("-")]
    plain = [a for a in args if not a.startswith("-")]
    if sub == "merge":
        if flags == ["--abort"] and not plain:  # undoes a merge already in progress
            return None
        deploy = "--ff-only" in flags and set(flags) <= GIT_MERGE_FLAGS and len(plain) == 1 and SHA.fullmatch(plain[0])
        return None if deploy else "git merge"
    if sub == "reset":
        rollback = flags == ["--keep"] and len(plain) == 1 and SHA.fullmatch(plain[0])  # docs/deploy.md: a failed install
        return None if rollback else "git reset"
    if sub == "stash":
        return None if plain[:1] in (["list"], ["show"]) else "git stash"
    if sub == "branch":
        listing = bool(set(flags) & GIT_BRANCH_LISTS)
        return "git branch" if set(flags) & GIT_BRANCH_CHANGES or (plain and not listing) else None
    return "git " + sub if sub in GIT_ALWAYS_REFUSED else None


def _in_live_checkout(path, home, extra=None):
    """Whether path is in a live coordinator checkout: ~/git/coordinator on any profile, and `extra` (this profile's own checkout, read from the
    `coordinator-instance` file: on the work profile ~/coordinator-work or the path set in local data)."""
    path = os.path.normpath(path)
    roots = [os.path.normpath(os.path.join(home, LIVE_CHECKOUT))] + ([os.path.normpath(extra)] if extra else [])
    return any(path == root or path.startswith(root + os.sep) for root in roots)


def _git_places(cmd, opts, home):
    """The directories a git command works in: where it runs (after each `-C`), a `--work-tree`, a `--git-dir`, GIT_DIR, GIT_WORK_TREE."""
    here = cmd.cwd
    places = [here]
    for name, value in opts:
        if name == "-C":
            here = _resolve(value, here, home)
            places = [here] + places[1:]
        elif name in ("--git-dir", "--work-tree"):
            places.append(_resolve(value, here, home))
    for word in cmd.assigns:
        name, _, value = word.partition("=")
        if name in ("GIT_DIR", "GIT_WORK_TREE"):
            places.append(_resolve(value, here, home))
    return [p for p in places if p]


def _own_checkout(ctx):
    """This profile's coordinator checkout when it is not the default ~/git/coordinator (on work: ~/coordinator-work or the path in local data), else None."""
    home = (ctx.env or {}).get("HOME") or os.path.expanduser("~")
    repo = ctx.coordinator_repo
    return repo if repo and os.path.normpath(repo) != os.path.normpath(os.path.join(home, LIVE_CHECKOUT)) else None


def _live_checkout_name(ctx):
    """The live checkout a refusal names: this profile's own when it is not the default, else ~/git/coordinator."""
    return _own_checkout(ctx) or "~/" + LIVE_CHECKOUT


def _merge_pr(ctx):
    """merge-pr.sh in this profile's coordinator checkout (the work Mac has no ~/git/coordinator)."""
    own = _own_checkout(ctx)
    return os.path.join(own, "scripts/merge-pr.sh") if own else MERGE_PR


def live_git_rule(walk, ctx):
    for cmd in walk.cmds:
        if _base(cmd.words[0]) == "gh":  # `gh pr checkout` fetches the PR and checks it out in the directory it runs in
            args = cmd.words[1:]
            if any(a == "pr" and b in ("checkout", "co") for a, b in zip(args, args[1:])) and cmd.cwd and _in_live_checkout(cmd.cwd, walk.home, ctx.coordinator_repo):
                return GIT_LIVE % ("gh pr checkout", _live_checkout_name(ctx))
        if _base(cmd.words[0]) != "git":
            continue
        opts, sub, args = _git_parts(cmd.words)
        spelling = _git_change(sub, args) if sub else None
        if spelling and any(_in_live_checkout(p, walk.home, ctx.coordinator_repo) for p in _git_places(cmd, opts, walk.home)):
            return GIT_LIVE % (spelling, _live_checkout_name(ctx))
    return None


CONFIG_SHOW = "~/.local/share/agent-harness/bin/config-show"
CREDENTIAL_READ = (
    "`%s` on credential config (%s) is refused in agent sessions: it prints the secret values into the transcript, and a line regex does not "
    "make that safe (it misses a renamed key, a wrapped value or the next field). Print the structure with every value masked: `" + CONFIG_SHOW + " FILE`; "
    "add `--show KEY` for a key you know is safe to show (`--show options.view_style`), `--format toml|ini|json|yaml|env` if the name "
    "does not say the format. A check that needs no value (`grep -l`, `grep -c`, `ls`, `stat`) is fine. To compare two configs, diff their "
    "`config-show` outputs."
)
CREDENTIAL_REDACT = (
    "A regex that redacts secrets line by line (`%s`) is refused in agent sessions: it hides only the keys it names, and a miss prints the "
    "secret. For a config file use `" + CONFIG_SHOW + " FILE [--show KEY]`, which masks every value whole. For other text, print only "
    "what you need (a count, a length, a yes or no), not the text."
)
# Paths that hold credentials, matched on the whole path string with `/` separators and no case ($HOME, ~, a glob or a relative path all pass).
CREDENTIAL_PATHS = re.compile(
    r"(?:^|/)(?:"
    r"\.config/rustdesk(?:/|$)|rustdesk/config(?:/|$)|com\.carriez\.rustdesk(?:/|$)|rustdesk[\w-]*\.toml$|"
    r"\.config/rclone(?:/|$)|rclone\.conf$|"
    r"\.netrc$|_netrc$|\.git-credentials$|\.pgpass$|\.my\.cnf$|\.npmrc$|\.pypirc$|\.dockercfg$|\.vault-token$|"
    r"\.aws/credentials$|\.docker/config\.json$|\.config/gh/hosts\.ya?ml$|op-service-token$|"
    r"\.env(?:\.(?!example$|sample$|template$|dist$)[\w.-]+)?$|[\w-]+\.env$|"
    r"(?:credentials?|secrets?)(?:\.[\w-]+)?\.(?:json|ya?ml|toml|ini|conf|cfg|env)$"
    r")",
    re.I,
)
# Commands that print what they read. Not here: ls, stat, wc, file, cp, mv, rm, chmod, the reader itself.
CREDENTIAL_READERS = {"cat", "tac", "nl", "head", "tail", "less", "more", "bat", "batcat", "sed", "awk", "gawk", "mawk", "cut", "sort", "uniq",
                      "tr", "strings", "xxd", "od", "hexdump", "base64", "column", "paste", "fold", "rev", "diff", "jq", "yq", "tomlq", "xq",
                      "grep", "egrep", "fgrep", "rg", "ag", "ack"}
GREP_QUIET = {"-l", "-L", "-c", "-q", "--files-with-matches", "--files-without-match", "--count", "--quiet", "--silent"}
# The secret words a redaction pattern names, and what a mask replacement looks like.
SECRET_WORD = re.compile(r"pass(?:word|wd)?|pwd|secret|token|key|salt|\bpk\b|enc_id|credential|cookie|bearer|auth", re.I)
MASK_WORD = re.compile(r"<[^<>\s]*>|\*{3,}|redact|hidden|mask|x{3,}|\.\.\.|removed|censor", re.I)
SED_SUBST = re.compile(r"(?:^|[;{\s])s([/|#,:@!%])((?:\\.|(?!\1).)+)\1((?:\\.|(?!\1).)*)\1[a-zA-Z]*")
AWK_SUBST = re.compile(r"\bg?sub\(\s*/((?:\\.|[^/])+)/\s*,\s*([\"'])(.*?)\2")
PS_REPLACE = re.compile(r"(?:get-content|\bgc\b|select-string|\btype\b|\bcat\b)[^\n]*?-i?replace\s+(['\"])((?:(?!\1).)*)\1\s*,\s*(['\"])((?:(?!\3).)*)\3", re.I)


# Which words of a reader are files it reads. A search pattern (grep, rg), a filter (jq, yq) or a script (sed, awk) is not a file, and a `>`
# or `>>` target is written, not read; a `<` input is read.
OUT_REDIRECT = re.compile(r"(?:\d*|&)>>?\|?$|\d*>&$")  # `>`, `>>`, `2>`, `&>`, `>|`: the next word is the target
OUT_ATTACHED = re.compile(r"(?:\d*|&)>")               # `>f`, `2>/dev/null`, `2>&1`, `&>f`: the target is in the word
# command -> (letters of short options that take the next word as a value, long options that do, how many words each long one takes,
#             short and long options that supply the pattern or script, so every operand is a file)
SCRIPT_FIRST = {
    "grep": ("efmABCdD", {"--regexp": 1, "--file": 1, "--max-count": 1, "--after-context": 1, "--before-context": 1, "--context": 1, "--include": 1,
                          "--exclude": 1, "--exclude-dir": 1, "--exclude-from": 1, "--label": 1}, "ef", {"--regexp", "--file"}),
    "rg": ("efgtTmABCjMrEd", {"--regexp": 1, "--file": 1, "--glob": 1, "--iglob": 1, "--type": 1, "--type-not": 1, "--max-count": 1,
                              "--replace": 1, "--threads": 1, "--max-columns": 1, "--max-depth": 1, "--sort": 1, "--sortr": 1, "--context": 1,
                              "--after-context": 1, "--before-context": 1}, "ef", {"--regexp", "--file"}),
    "sed": ("efl", {"--expression": 1, "--file": 1, "--line-length": 1}, "ef", {"--expression", "--file"}),
    "awk": ("fvF", {"--file": 1, "--assign": 1, "--field-separator": 1}, "f", {"--file"}),
    "jq": ("fL", {"--arg": 2, "--argjson": 2, "--slurpfile": 2, "--rawfile": 2, "--from-file": 1, "--indent": 1}, "f", {"--from-file"}),
    "yq": ("poIf", {"--input-format": 1, "--output-format": 1, "--indent": 1, "--from-file": 1}, "f", {"--from-file"}),
}
for _alias, _name in (("egrep", "grep"), ("fgrep", "grep"), ("ag", "grep"), ("ack", "grep"), ("gawk", "awk"), ("mawk", "awk"), ("tomlq", "jq"),
                      ("xq", "jq")):
    SCRIPT_FIRST[_alias] = SCRIPT_FIRST[_name]


def _redirects(args):
    """(the words that are not redirects, the `<` inputs) of a command's arguments: an output target is dropped, an input kept."""
    operands, inputs, i = [], [], 0
    while i < len(args):
        word = args[i]
        if OUT_REDIRECT.match(word):
            i += 2
        elif OUT_ATTACHED.match(word):
            i += 1
        elif word == "<":
            if i + 1 < len(args) and not args[i + 1].startswith("<"):
                inputs.append(args[i + 1])
                i += 1
            i += 1
        elif word.startswith("<<"):
            i += 1
        elif word.startswith("<"):
            inputs.append(word[1:])
            i += 1
        else:
            operands.append(word)
            i += 1
    return operands, inputs


def _files_read(name, args):
    """The words of `name args` that name files it reads (a `<` input included), leaving out the pattern, filter or script and `>` targets."""
    operands, inputs = _redirects(args)
    spec = SCRIPT_FIRST.get(name)
    if spec is None:
        return operands + inputs
    letters, long_values, supplies, long_supplies = spec
    positional, supplied, i = [], False, 0
    while i < len(operands):
        word = operands[i]
        i += 1
        if word == "--":
            positional += operands[i:]
            break
        if word.startswith("--"):
            flag = word.split("=", 1)[0]
            supplied = supplied or flag in long_supplies
            if "=" not in word:
                i += long_values.get(flag, 0)
        elif word.startswith("-") and word != "-":
            for k, letter in enumerate(word[1:]):
                if letter in letters:
                    supplied = supplied or letter in supplies
                    if k == len(word) - 2:  # the value is the next word; otherwise it is attached (`-A3`)
                        i += 1
                    break
        else:
            positional.append(word)
    return (positional if supplied else positional[1:]) + inputs


def _credential_path(word, cwd):
    """The word as a path with `/` separators when it names credential config, else None."""
    if not word or word.startswith("-") and "=" not in word:
        return None
    path = word.split("=", 1)[1] if word.startswith("-") else word
    path = path.replace("\\", "/")
    if not path.startswith(("/", "~", "$")) and cwd:
        path = os.path.join(cwd, path)
    return path if CREDENTIAL_PATHS.search(path) else None


def _prints_value(name, args):
    """False for a use of a reader that prints no file text (grep -l/-c/-q, sed -i, python or perl that only run a script)."""
    flags = [a for a in args if a.startswith("-") and a != "-"]
    if name in ("grep", "egrep", "fgrep", "rg", "ag", "ack"):
        short = {c for a in flags if not a.startswith("--") for c in a[1:]}
        return not (set(flags) & GREP_QUIET or short & set("lLcq"))
    if name == "sed":
        return not any(a == "--in-place" or a.startswith("--in-place=") or (not a.startswith("--") and "i" in a[1:] and "e" not in a[1:]) for a in flags)
    return True


def _redaction(words):
    """The substitution (`s/.../<hidden>/`) in a sed, perl or awk command that masks a secret word, else None."""
    name = _base(words[0])
    if name not in ("sed", "perl", "awk", "gawk", "mawk") or not _prints_value(name, words[1:]):  # `sed -i` edits a file and prints nothing
        return None
    for word in words[1:]:
        if name in ("awk", "gawk", "mawk"):
            found = [(m.group(1), m.group(3)) for m in AWK_SUBST.finditer(word)]
        else:
            found = [(m.group(2), m.group(3)) for m in SED_SUBST.finditer(word)]
        for pattern, replacement in found:
            if SECRET_WORD.search(pattern) and MASK_WORD.search(replacement):
                return "%s ... %s" % (name, (word[:60] + "..." if len(word) > 60 else word))
    return None


def credential_rule(walk, ctx):
    for cmd in walk.cmds:
        name = _base(cmd.words[0])
        if name not in CREDENTIAL_READERS:
            continue
        args = cmd.words[1:]
        paths = [p for p in (_credential_path(a, cmd.cwd) for a in _files_read(name, args)) if p]
        if paths and _prints_value(name, args):
            return CREDENTIAL_READ % (name, os.path.basename(paths[0].rstrip("/")) or paths[0])
    for cmd in walk.cmds:
        spelled = _redaction(cmd.words)
        if spelled:
            return CREDENTIAL_REDACT % spelled
    texts = [body for scan in walk.scans for _quoted, body in scan.documents] + [" ".join(cmd.words) for cmd in walk.cmds]
    for text in texts:
        for match in PS_REPLACE.finditer(text):
            if SECRET_WORD.search(match.group(2)) and MASK_WORD.search(match.group(4)):
                return CREDENTIAL_REDACT % ("Get-Content ... -replace '%s', '%s'" % (match.group(2)[:40], match.group(4)[:20]))
    return None


def _without_gh_repo_flag(words):
    """`gh -R owner/repo pr create` and `gh --repo owner/repo pr create` (also `-R=...`, `--repo=...`) as `gh pr create`: the repo flag before the subcommand does not change what the command is.
    Only a flag that comes straight after `gh` is dropped; anything else is left as typed."""
    if words[:1] != ["gh"]:
        return words
    rest = words[1:]
    while rest and (rest[0] in ("-R", "--repo") or rest[0].startswith(("-R=", "--repo="))):
        rest = rest[2:] if rest[0] in ("-R", "--repo") else rest[1:]
    return ["gh"] + rest


def door_rule(walk, ctx):
    """Door delivery (cmd doors): a playbook rule that names a shell command in its `At:` line (`cmd:gh pr create`, `cmd:kubectl`) is told in one refusal per run,
    and the same command again passes. The rules, the seat filter and the once-per-run record are the coordinator's renderer (`hook.ts --door`), not this file:
    this rule only asks it, and only for a command whose words start with a prefix in the renderer's index, so node is not started for any other command.
    The caller supplies `ctx.run` (the harness session id) and `ctx.door`, an object with `cmds()` (the indexed prefixes, a list of word strings) and `render(command_text)`
    (the refusal text or None). Without either, or on any error, the rule does nothing: the command runs. It runs last, so a command another rule refuses is refused by that
    rule first and its door rules are not marked told. The renderer writes the log line of what it told; the caller does not log this refusal again (`refuse_pattern_kill.py`)."""
    door = ctx.door
    if door is None or not ctx.run:
        return None
    prefixes = [p.split() for p in door.cmds() if p.strip()]
    if not prefixes:
        return None
    asked = set()
    for cmd in walk.cmds:
        words = _without_gh_repo_flag([_base(cmd.words[0])] + list(cmd.words[1:]))
        if not any(words[:len(prefix)] == prefix for prefix in prefixes):
            continue
        text = " ".join(words)
        if text in asked:
            continue
        asked.add(text)
        told = door.render(text)
        if told:
            return told
    return None


RULES = (poll_rule, heredoc_rule, kube_rule, merge_rule, pr_body_rule, docker_rule, heavy_rule, live_git_rule, credential_rule, door_rule)


def refusal(text, ctx):
    """(rule name, refusal message, matched command name or None) for the command text, or None. The matched name is from the rule's fixed list, never the command text."""
    walk = Walk(text, ctx.cwd, (ctx.env or {}).get("HOME"))
    for rule in RULES:
        message = rule(walk, ctx)
        if message:
            return rule.__name__.replace("_rule", ""), message, getattr(message, "matched", None)
    return None


def check(text, ctx):
    """The refusal message for the command text, or None."""
    found = refusal(text, ctx)
    return found[1] if found else None
