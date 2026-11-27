"""Twelve refusals for an agent's shell command, run by refuse_pattern_kill.py after its pkill check, and the door rule that tells a playbook rule. Each names the fix.

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
              GitHub-run main only when PR N names that red (a `Handles: <full sha>` line in a commit message of the PR, or in its
              description for storycraft) and its own full-suite run on its head tree succeeded (a pull_request run that skips the
              suite does not count; a workflow_dispatch run does). A green PR that does not name the red is refused. dotfiles tries
              its release-pins fix rule first, then that same rule.
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
              body flag and no title (labels, reviewers) passes; one that sets only a title needs the chained check given the same title. One check must see both the file and the title. `gh api` on `repos/<o>/<r>/pulls[/<n>]` (POST, PATCH, PUT) or a PATCH on `issues/<n>` (a PR is an issue) with a `title` field is held to the same rule:
              every `title` must have been given to an earlier `pr-body-check --body-file F --title T` in the and-list, and a `-F title=@file` is always refused (its text cannot be seen). No repo is exempt: unlike the merge rule, nothing else runs this check at create time.
              The body file must also be a mktemp name, so another session cannot overwrite it (2026-11-15: a shared /tmp/pr-body.md put
              one PR's body on another): `F=$(mktemp /tmp/pr-N-body.XXXXXX)` earlier in the same command and `--body-file "$F"`, or the
              literal name mktemp made (last dot-part 6+ letters and digits with a digit or capital). A fixed name is refused for create and
              edit; for `gh pr edit N` the name must also contain N. A `$VAR` the command does not assign from mktemp is refused. A name
              is checked even when the chain is right; when both are wrong the refusal gives both fixes.

  issue-body  (personal and work)  `gh issue create` (`gh issue new`, a `-R` before the verb) and a `gh api` POST on `repos/<o>/<r>/issues` with a field or `--input`: use
              `issue-open --title T --body-file F`, which expands the `{{claim:ID}}` tokens in F (`claims ran|read|said|none` print them), adds the Sources footer, then runs
              `gh issue create` as a child process the hook never sees. `gh issue edit|comment|close|view|list` pass. The rule refuses only where `src/claims/cli.ts` exists in
              the profile's coordinator checkout (the file `claims` runs), so a machine that has this hook before it has the coordinator pull is not left unable to file an issue.
              Not seen: a `gh api graphql` mutation, or an issue made through another tool.

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
  stash       (both profiles)  `git stash` that writes the stash list, in any directory (`git -C <dir>` too): push, save, pop, apply, drop, clear,
              store, branch, `-q`, a bare `git stash`, and every other form but `list` and `show`. Every worktree of a repo shares one stash list, so a
              pop from one worktree takes another worktree's work (2026-11-24: twice in coordinator worktrees, once as a swap between two builders).
              Read-only `stash list` and `stash show` pass. The refusal names the fix: commit the work in progress on your branch, or make a throwaway
              worktree with `git worktree add <path> origin/main`.
  live git    (both profiles)  git that changes the working tree, index, HEAD or a branch of the live coordinator checkout, ~/git/coordinator (and the profile's own checkout when it is another path: line 1 of the `coordinator-instance` file chezmoi renders, ~/coordinator-work on work),
              which the coordinator daemon runs from (2026-11-11: a reviewer checked out PR #438 there and the daemon restarted onto PR code;
              2026-11-16: a builder ran `git merge origin/main` there). Refused: merge, pull, reset, checkout, switch, restore, commit, rebase,
              cherry-pick, revert, clean, am, apply, add, rm, mv, update-ref, symbolic-ref, branch (that creates, deletes or renames), and
              `gh pr checkout` / `gh pr co` run in the live checkout.
              Allowed there: `merge --abort`, `merge --ff-only <sha>` (the deploy; 7 to 40 hex, never a ref), `reset --keep <sha>` (the rollback in
              docs/deploy.md), fetch, worktree add/remove/prune, every read-only git. The place is the command's directory
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

  bash-engine (all profiles)  a hand-typed Loop Engine write, `loop-engine start|append|event|terminate`, on a lead's run (`lead-<slug>-<digits>`, the whole shape: `lead-a-b` and
              `leader-1` are not) or on the coordinator's run (`coordinator-loop-...`): the workflow commands change those runs, and a raw write skips the checks they make.
              The run id is the first word after the verb (`start`: the `--id` flag), read after every flag spelling and through wrappers, `mise exec`, `sh -c`. Reads (`list`, `show`,
              `history`, `read`, `explore`, `monitor`, `reclaim`), `change` runs and any other id pass; so does a write whose command names no id (`start` without `--id`).
              An id the hook cannot read (`$RUN`, a glob) is refused too: write it out. The refusal names the `workflows lead|coordinator` command for the verb; while `workflows lead catch-up` and `workflows lead note` are not built (ENGINE_NOT_BUILT), it says so. The way past
              is `BASH_ENGINE_OVERRIDE='<why>'` on the same command (an assignment before the command, or `env` with it; an exported value does not count: one use); the use is logged
              as `action: "override"` with the why. The rule judges the id and ignores the catalog (`--database`).

Flags are read in one place: FLAG_ROWS (one row per tool and subcommand) and `normalise` / `gh_command`, which accept every spelling the tool's flag
library accepts (`--x v`, `--x=v`, `-x v`, `-xv`, `-x=v`, clusters of short flags, `--` ending the flags). No rule reads a flag itself (the guard in
tests/agent-kill-guard/test_flag_normaliser.py fails if one does). A gated command (gh pr create/edit/merge, gh api on a PR or issue endpoint, git's
merge/reset/stash/branch and any git option before the subcommand in the live checkout, docker before its subcommand) with a flag its row lacks is refused,
naming the row to extend. A gh command with a flag before its group (`gh -x pr merge 5`) or, for `gh pr`, between `pr` and the verb (`gh pr -t T edit 5`) is refused
whatever the flag is, unless it is `-R owner/repo` / `--repo`, `-h`/`--help` or `--version`: gh may take the next word as that flag's value, so the verb cannot be told
(a flag after the verb is read against the verb's row, as above).

Commands are found like the pkill classifier finds them (it supplies the parser): through quotes, `;` `&&` `|`, `$( )`, `sh -c`, `eval`,
wrappers, `find -exec`, heredocs fed to a shell. Not covered: a git alias, a git option the table does not list that takes a separate value (it hides the subcommand), a command built at run time (`$cmd`), a script file, `python -c`, a command
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
KUBE_CONTEXT_FLAG = {"kubectl": "context", "k9s": "context", "helm": "kube-context"}  # the name of the flag in FLAG_ROWS
# docker: the (subcommand, ...) words that start a local container or image build.
DOCKER_REFUSED = {("run",), ("build",), ("container", "run"), ("image", "build"), ("buildx", "build"), ("builder", "build"), ("compose", "up")}

LIVE_CHECKOUT = "git/coordinator"  # under $HOME on both profiles: the checkout the coordinator daemon runs from
GATE_PROFILES = ("personal", "axon-work-computer")  # the PR gates (merge, pr-body) run on both desktop profiles; any other profile (Termux) has none
GIT_ALWAYS_REFUSED = {"pull", "reset", "checkout", "switch", "restore", "commit", "rebase", "cherry-pick", "revert", "clean", "am", "apply",
                      "add", "rm", "mv", "update-ref", "symbolic-ref", "read-tree"}
GIT_MERGE_FLAGS = {"ff-only", "quiet", "verbose", "stat", "no-stat", "n"}  # a fast-forward to a sha takes nothing else (flag names as FLAG_ROWS reads them)
GIT_TABLE_GUARDED = {"merge", "reset", "stash", "branch"}  # the subcommands whose flags decide whether they change anything: a flag outside their row refuses
GIT_BRANCH_CHANGES = {"delete", "D", "move", "M", "copy", "C", "force", "set-upstream-to", "unset-upstream", "edit-description"}
GIT_BRANCH_LISTS = {"list", "contains", "no-contains", "merged", "no-merged", "points-at"}
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
BODY_TITLE = "pr-body-check --title "  # prefix of the gated entry that names a title a body check already read
BODY_PAIR = "pr-body-check --body-file+title "  # prefix of the gated entry for one check that read both a file and a title: BODY_PAIR + F + "\0" + T
MERGE_BARE = (
    "`gh pr merge` without both gates in their real form is refused in agent sessions: it skips the red-main gate (playbook fab9b713) or the PR body check. "
    "A bare `ci-main-status` (or `--tip`) is not the gate, and a `pr-body-check` with `--body-file` is not the merge check: only `pr-body-check <repo> <pr>` reads the PR's head runs. "
    "For cartwmic/coordinator use `" + MERGE_PR + " PR`; for other repos run "
    "`ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr> --match-head-commit <head sha> ...` "
    "(--merge-gate lets an untested tip merge and stops only red; `--pr <pr>` after it passes a red main only for the PR that fixes it: one that names the red with a `Handles: <full sha>` line "
    "(in a commit message of the PR; in its description for storycraft) and whose own full-suite run on its head tree passed; pr-body-check enforces playbook rules ecd63156, 385acc43, ccc6c94b and 5a05bfe8; it reads the principles table, the Decisions line and the `Promises:` line (each promise `=>` its evidence, or `none, <reason>`) from the PR's agent record, `pr-record path <repo>#N` prints where, and a PR with none is refused; it also refuses a PR with an unresolved review thread, and a description with no Proven section); "
    "a one-time admin merge Michael approved (an answered ledger ask naming this PR) adds `--owner-approved ASK` to both checks, and `gh pr merge <pr> --admin`; the ledger decides whether the ask holds; "
    "pin bumps use loop_engine_bump.py or agent_kit_bump.py; a playbook edit is made only by the coordinator (any other session sends it to the coordinator by agent message): run the playbook verb on a branch in a worktree, without `--pr`, then `issue-open`, `pr-open` and `" + MERGE_PR + " PR`; never add `--merge` to the playbook CLI, which merges by itself and skips both gates and the whole suite (playbook fab9b713). "
    "An edit with Michael's own words goes out at once in its own PR; a bookkeeping edit (seats, tag, enforced) waits on branch `playbook/batch` for the coordinator's daily digest."
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
    "edit": "`pr-open --edit N --body-file F` (it checks the body, then sets it through `gh api`, because `gh pr edit` fails on the agent host; it refuses a merged or closed pull request by design: to take a private detail out of such a description use `pr-redact --repo OWNER/REPO --pr N --replacements FILE`, which only replaces exact listed strings with neutral phrases)",
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
PR_API_TITLE = (
    "`gh api` that sets a pull request title (POST, PATCH or PUT on `repos/<owner>/<repo>/pulls` or `.../pulls/<n>` with a `title` field) sets a title that `pr-body-check` was not given: "
    "the check reads the title for task ids, which become part of the commit text on main, and it can only read the one it is passed. "
    "Pass the same title to both: `pr-body-check --body-file F --title T && gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -f title=T`, or use `pr-open --edit N --body-file F --title T`."
)
PR_API_ISSUE_TITLE = (
    "`gh api` PATCH on `repos/<owner>/<repo>/issues/<n>` with a `title` field sets a title that `pr-body-check` was not given: a pull request is an issue too, so this can rename a pull request, "
    "and the hook cannot tell a PR number from an issue number without a lookup. For a PR: `pr-body-check --body-file F --title T && gh api -X PATCH repos/<owner>/<repo>/issues/<n> -f title=T`, "
    "or `pr-open --edit N --body-file F --title T`. For an issue: `gh issue edit N --title T`."
)
PR_API_ENDPOINT = re.compile(r"(?:https://[^/]+/(?:api/v3/)?|/)?(?P<path>repos/[^/]+/[^/]+/(?P<kind>pulls|issues)(?:/\d+)?/?)(?:\?.*)?")
ISSUE_OPEN_CLI = "src/claims/cli.ts"  # the coordinator file `claims` (so `issue-open`) runs: the issue rule refuses only where it exists
ISSUE_BODY = (
    "`gh issue create` is refused in agent sessions: an issue body typed by hand states facts (a count, a state, a line of code) with no source, and nothing checks them before a person reads it. "
    "Use `issue-open --title T --body-file F [--repo OWNER/REPO] [--label L ...]` (F is the body file, `-` reads it from stdin). Put each fact in the body as the token a tool printed: "
    "`claims ran -- <cmd>` or `claims read <repo>:<path>:<a>-<b>` print `{{claim:ID}}`; where nothing can be observed, `claims said <text>` or `claims none <reason>` print one that shows as unsourced. "
    "`issue-open` expands the tokens, refuses an unknown or stale one, adds the Sources footer and then creates the issue. `issue-open --dry-run ...` shows the expanded body and creates nothing. "
    "`gh issue edit|comment|close|view|list` are not affected."
)
ISSUE_API_BODY = (
    "`gh api` that creates an issue (POST on `repos/<owner>/<repo>/issues` with a field or `--input`) is refused in agent sessions: it skips the source check that `issue-open` gives an issue body. "
    "Use `issue-open --title T --body-file F [--repo OWNER/REPO]`: it expands the `{{claim:ID}}` tokens that `claims ran|read|said|none` print, then creates the issue."
)
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


STASH = (
    "`%s` is refused in agent sessions: git keeps one stash list for every worktree of a repo, so this takes or drops another worktree's stash. "
    "Commit your work in progress on your branch, or make a throwaway worktree for a clean tree: `git worktree add <path> origin/main`. "
    "`git stash list` and `git stash show` are allowed."
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


Context = namedtuple("Context", "tool profile env cwd read_file origin_of platform container coordinator_repo run door note", defaults=(None,) * 12)  # note(rule, matched, extra): the caller writes one log line for an allowed use of a way past


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
        self.notes = []   # (rule, matched, extra) for each use of a rule's way past; refusal() hands them to the caller when nothing in the command is refused
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
                read = normalise([("pr-body-check", "")], args)
                body_file, title = read.value("body-file"), read.value("title")
                if body_file is not None:
                    found.add(BODY_FILE + body_file)
                if title is not None:
                    found.add(BODY_TITLE + title)
                    if body_file is not None:
                        found.add(BODY_PAIR + body_file + "\0" + title)  # one check saw both, not a file from one check and a title from another
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
        if name == "mise":
            self._mise(rest, assigns, loop, waking, gated, cwd, depth)
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

    def _mise(self, rest, assigns, loop, waking, gated, cwd, depth):
        """`mise exec [TOOL@VERSION]... -- COMMAND` and `mise exec -c 'SHELL TEXT'` (also `mise x`) run the command that follows: read it like a wrapper's."""
        top = normalise([("mise", "")], rest, until_positional=True)
        if not top.positional or top.positional[0] not in ("exec", "x"):
            return
        split = top.tail.index("--") if "--" in top.tail else len(top.tail)
        text = normalise([("mise", "exec")], top.tail[:split]).value("command")
        if text:
            self._text(text, cwd, loop, waking, gated, depth + 1)
        if top.tail[split + 1:]:
            self._command(top.tail[split + 1:], assigns, loop, waking, gated, cwd, depth + 1)


MKTEMP_ASSIGN = re.compile(r"(?<![\w$])([A-Za-z_]\w*)=[\"']?(?:\$\(|`)\s*mktemp\b([^)`]*)")


def _mktemp_template(args):
    """The template word of `mktemp ARGS` (its options skipped), else the default `tmp.XXXXXXXXXX`."""
    read = normalise([("mktemp", "")], args.replace('"', " ").replace("'", " ").split())
    return read.positional[0] if read.positional else "tmp.XXXXXXXXXX"


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
    """True for `--merge-gate <repo>` with an optional `--pr N` and `--owner-approved ASK` (the words after ci-main-status): one repo, no `--tip`, no `--all`, no other flag.
    `--owner-approved` is Michael's answered ask for the PR: the tool asks the ledger and refuses unless that ask names this PR, so the hook needs no check of its own."""
    read = normalise([("ci-main-status", "")], args)
    if not read.has("merge-gate") or read.unknown or set(read.names()) - {"merge-gate", "pr", "owner-approved"}:
        return False
    if read.has("pr") and not (read.value("pr") or "").isdigit():
        return False
    return len(read.positional) == 1


def _is_pr_check(args):
    """The PR number of a real `pr-body-check <repo> <pr>` (the words after pr-body-check: two plain words, and at most `--owner-approved ASK`), else None."""
    read = normalise([("pr-body-check", "")], args)
    if not read.unknown and set(read.names()) <= {"owner-approved"} and len(read.positional) == 2 and read.positional[1].isdigit():
        return str(int(read.positional[1]))
    return None


# --- flag tables: begin. The ONLY place a flag of gh, git, docker, kubectl, grep and the like is named. Every rule and the and-list code read a command's flags
# through `normalise` / `gh_command` below, from FLAG_ROWS; none reads one by hand. A row lists a command's flags as `s:long` (a short and a long flag), `long`, or
# `s:` (a short flag only, read under its letter); a trailing `=` means the flag takes a value (`==`: two words, `jq --arg NAME VALUE`), a trailing `?` a value that can
# only be attached (`--color=auto`, `-S<key>`). The gh rows are the gh wrapper's FLAGS rows word for word (scripts/gh-wrapper, generated from the installed gh by
# scripts/leak-guard-gh-flags); tests/agent-kill-guard/test_flag_normaliser.py compares them, because a hook cannot import the wrapper (it is an extensionless script
# installed apart from the hooks). A flag a gated command carries that its row does not list refuses the command: add it to the row, or regenerate the wrapper's table. A flag before the gh group or
# before the `pr` verb is different: only `-R`/`--repo` (and `-h`, `--version`) are read there, any other refuses the command, because its value may be taken for the verb.
FLAG_ROWS = {
    ("gh", ""): "R:repo=,h:help,version",  # before the group: `gh -R o/r pr merge`, `gh --version`. The only flags read there: gh takes any other flag before the verb
                                          # with a value this table cannot size, so the verb cannot be told (see `gh_command`, `_flag_before_verb`)
    ("pr", ""): "R:repo=,h:help",
    ("issue", ""): "R:repo=,h:help",
    ("issue", "create"): "a:assignee=,attach=,blocked-by=,blocking=,b:body=,F:body-file=,e:editor,l:label=,m:milestone=,parent=,p:project=,recover=,T:template=,t:title=,type=,w:web,h:help,R:repo=",
    ("issue", "edit"): "add-assignee=,add-blocked-by=,add-blocking=,add-label=,add-project=,add-sub-issue=,attach=,b:body=,F:body-file=,m:milestone=,parent=,remove-assignee=,remove-blocked-by=,remove-blocking=,remove-label=,remove-milestone,remove-parent,remove-project=,remove-sub-issue=,remove-type,t:title=,type=,h:help,R:repo=",
    ("pr", "create"): "a:assignee=,attach=,B:base=,b:body=,F:body-file=,d:draft,dry-run,e:editor,f:fill,fill-first,fill-verbose,H:head=,l:label=,m:milestone=,no-maintainer-edit,p:project=,recover=,r:reviewer=,T:template=,t:title=,w:web,h:help,R:repo=",
    ("pr", "edit"): "add-assignee=,add-label=,add-project=,add-reviewer=,attach=,B:base=,b:body=,F:body-file=,m:milestone=,remove-assignee=,remove-label=,remove-milestone,remove-project=,remove-reviewer=,t:title=,h:help,R:repo=",
    ("pr", "merge"): "admin,A:author-email=,auto,b:body=,F:body-file=,d:delete-branch,disable-auto,match-head-commit=,m:merge,r:rebase,s:squash,t:subject=,h:help,R:repo=",
    ("api", ""): "allow-escape-sequences,cache=,F:field=,H:header=,hostname=,i:include,input=,q:jq=,X:method=,paginate,p:preview=,f:raw-field=,silent,slurp,t:template=,verbose,h:help",
    ("pr-body-check", ""): "body-file=,commits-file=,diff-file=,files-file=,pr=,repo=,base=,skip-intent-review,title=,owner-approved=",  # a node script: long flags only (node parseArgs)
    ("git", ""): "C:=,c:=,git-dir=,work-tree=,namespace=,super-prefix=,config-env=,exec-path?,html-path,man-path,info-path,p:paginate,P:no-pager,no-replace-objects,bare,"
                 "literal-pathspecs,glob-pathspecs,noglob-pathspecs,icase-pathspecs,no-optional-locks,no-lazy-fetch,list-cmds=,v:version,h:help",
    ("git", "merge"): "n:,stat,summary,log?,squash,commit,e:edit,cleanup=,ff,ff-only,rerere-autoupdate,verify-signatures,s:strategy=,X:strategy-option=,m:message=,F:file=,"
                      "into-name=,v:verbose,q:quiet,abort,quit,continue,allow-unrelated-histories,progress,S:gpg-sign?,autostash,overwrite-ignore,signoff,verify,no-verify,h:help",
    ("git", "reset"): "q:quiet,no-refresh,refresh,mixed,soft,hard,merge,keep,recurse-submodules?,p:patch,N:intent-to-add,pathspec-from-file=,pathspec-file-nul,h:help",
    ("git", "branch"): "v:verbose,q:quiet,t:track?,u:set-upstream-to=,unset-upstream,color?,r:remotes,contains=,no-contains=,abbrev?,a:all,d:delete,D:,m:move,M:,omit-empty,"
                       "c:copy,C:,l:list,show-current,create-reflog,edit-description,f:force,merged=,no-merged=,column?,sort=,points-at=,i:ignore-case,recurse-submodules,format=,h:help",
    ("git", "stash"): "h:help",
    ("docker", ""): "D:debug,H:host=,l:log-level=,tls,tlscacert=,tlscert=,tlskey=,tlsverify,v:version,h:help,config=,c:context=",
    ("docker", "compose"): "all-resources,ansi=,compatibility,dry-run,env-file=,f:file=,parallel=,profile=,progress=,project-directory=,p:project-name=,verbose,h:help",
    ("docker", "buildx"): "builder=,D:debug,h:help",
    ("docker", "builder"): "h:help",
    ("docker", "container"): "h:help",
    ("docker", "image"): "h:help",
    ("docker-compose", ""): "all-resources,ansi=,compatibility,dry-run,env-file=,f:file=,parallel=,profile=,progress=,project-directory=,p:project-name=,verbose,h:help,"
                            "H:host=,c:context=,log-level=,tls,tlscacert=,tlscert=,tlskey=,tlsverify,skip-hostname-check,no-ansi,v:version",
    ("kubectl", ""): "context=,kubeconfig=",
    ("k9s", ""): "context=,kubeconfig=",
    ("helm", ""): "kube-context=,kubeconfig=",
    ("ci-main-status", ""): "merge-gate,pr=,tip,all,owner-approved=",
    # loop-engine: its parser takes every option in any position, before or after the verb, and takes more than its help lists (read from its source and run on a catalog that does not exist):
    # `-d`, `--db`, `--database-path` for the catalog, `-c`, `--config-path`, `--provider-config` for the config, and `--run`, `--run-id` or `--id` for the run id. The engine's own
    # `--override JSON` is not the hook's way past (BASH_ENGINE_OVERRIDE).
    ("loop-engine", ""): ("j:json,machine-readable,human,compact,view=,format=,output=,d:db=,database=,database-path=,c:config=,config-path=,provider-config=,timeout-ms=,provider-timeout-ms=,"
                          "provider-timeout=,h:help,V:version,provider=,input=,initial-input=,lifecycle=,label=,kind=,context-kind=,data=,context-data=,record-id=,event=,advice-exception=,"
                          "override=,run=,run-id=,id="),
    ("mise", ""): "C:cd=,E:env=,j:jobs=,q:quiet,v:verbose,y:yes,no-config,no-env,no-hooks,raw,locked,silent,h:help",
    ("mise", "exec"): "c:command=,j:jobs=,allow-env=,allow-net=,allow-read=,allow-write=,deny-all,deny-env,deny-net,deny-read,deny-write,fresh-env,no-deps,raw,secrets=,secrets-all,"
                      "h:help,q:quiet,v:verbose,y:yes,locked,silent",
    ("mktemp", ""): "p:tmpdir=,suffix=",
    ("js", ""): "C:cwd=,F:filter=,w:workspace=,prefix=,dir=",  # npm, pnpm, yarn, bun: the options before the subcommand that take a value
    # grep, rg, sed, awk, jq, yq: only the flags that take a value are listed (any other is read as one that does not), because the file reader needs to know which
    # words are values, not files. `regexp`, `file`, `expression`, `from-file` are the ones that supply the pattern or script, so every operand is a file (FILE_SUPPLIERS).
    ("grep", ""): "l:files-with-matches,L:files-without-match,c:count,q:quiet,silent,e:regexp=,f:file=,m:max-count=,A:after-context=,B:before-context=,C:context=,d:directories=,D:devices=,include=,exclude=,exclude-dir=,exclude-from=,label=",
    ("rg", ""): "l:files-with-matches,L:files-without-match,c:count,q:quiet,e:regexp=,f:file=,g:glob=,t:type=,T:type-not=,m:max-count=,A:after-context=,B:before-context=,C:context=,j:threads=,M:max-columns=,r:replace=,E:encoding=,"
                "d:max-depth=,iglob=,sort=,sortr=",
    ("sed", ""): "i:in-place?,e:expression=,f:file=,l:line-length=",
    ("awk", ""): "f:file=,v:assign=,F:field-separator=",
    ("jq", ""): "f:from-file=,L:=,arg==,argjson==,slurpfile==,rawfile==,indent=",
    ("yq", ""): "p:input-format=,o:output-format=,I:indent=,f:from-file=",
}
FILE_SUPPLIERS = {"regexp", "file", "expression", "from-file"}
# --- flag tables: end


class Argv:
    """What `normalise` read: `flags` is a list of (long name, value or None, spelling as typed) in order (a short flag reads under its long name, or its letter when it has
    none); `positional` the words that are not flags; `unknown` the spellings the row does not list; `tail` the words after the first positional when reading stopped there, and
    `consumed` the index of that positional in the words given."""
    def __init__(self, flags, positional, unknown, tail, consumed):
        self.flags, self.positional, self.unknown, self.tail, self.consumed = flags, positional, unknown, tail, consumed

    def values(self, name):
        return [v for n, v, _ in self.flags if n == name and v is not None]

    def value(self, name):
        """The value of the last `name` flag, as gh and git take it when a flag is repeated; None when it is absent or has no value."""
        found = self.values(name)
        return found[-1] if found else None

    def has(self, name):
        return any(n == name for n, _, _ in self.flags)

    def names(self):
        return [n for n, _, _ in self.flags]


_TABLES = {}


def _table(*keys):
    """The flags of the FLAG_ROWS rows `keys`, as ({long name: (short, words taken, attached value only)}, {short: long name}). Cached."""
    if keys not in _TABLES:
        longs, shorts = {}, {}
        for key in keys:
            for token in filter(None, FLAG_ROWS[key].split(",")):
                short, colon, rest = token.partition(":")
                if not colon:
                    short, rest = None, token
                name = rest.rstrip("=?") or short
                takes, optional = rest.count("="), rest.endswith("?")
                longs[name] = (short, takes, optional)
                if short:
                    shorts[short] = name
        _TABLES[keys] = (longs, shorts)
    return _TABLES[keys]


def _flag_at(table, args, i):
    """The flags the word args[i] starts and the words used, as (flags, unknown spellings, used), else None when the word is not a flag. A cluster of short flags gives several."""
    word = args[i]
    if not word.startswith("-") or word == "-":
        return None
    longs, shorts = table
    if word.startswith("--"):
        name, eq, attached = word[2:].partition("=")
        spec = longs.get(name)
        if spec is None and name.startswith("no-") and name[3:] in longs and not longs[name[3:]][1]:
            return [(name, None, word)], [], 1  # `--no-verbose`: the negation of a flag that takes no value
        if spec is None:
            return [(name, attached if eq else None, word)], [word.partition("=")[0]], 1
        takes, optional = spec[1], spec[2]
        if eq:
            return [(name, attached, word)], [], 1
        if not takes or optional:
            return [(name, None, word)], [], 1
        return ([(name, args[i + 1], word)], [], 1 + takes) if i + takes < len(args) else ([(name, None, word)], [], 1)
    found, unknown, j = [], [], 1
    while j < len(word):
        name = shorts.get(word[j])
        spelling = "-" + word[j]
        if name is None:
            found.append((word[j], None, spelling))
            unknown.append(spelling)
            j += 1
            continue
        takes, optional = longs[name][1], longs[name][2]
        if not takes:
            found.append((name, None, spelling))
            j += 1
            continue
        rest = word[j + 1:]
        if rest:
            found.append((name, rest[1:] if rest.startswith("=") else rest, spelling))
            return found, unknown, 1
        if optional or i + takes >= len(args):
            found.append((name, None, spelling))
            return found, unknown, 1
        found.append((name, args[i + 1], spelling))
        return found, unknown, 1 + takes
    return found, unknown, 1


def normalise(keys, args, until_positional=False):
    """Read `args` (the words after the command name) against the FLAG_ROWS rows `keys`: an Argv. It accepts every spelling the tools' flag libraries accept: `--x v`, `--x=v`,
    `-x v`, `-xv`, `-x=v`, a cluster of short flags (`-dt v`), and `--` ends the flags. With `until_positional` it stops at the first word that is not a flag (a subcommand) and
    puts the rest in `tail`."""
    table = _table(*keys)
    flags, positional, unknown, i = [], [], [], 0
    consumed, tail = len(args), []
    while i < len(args):
        if args[i] == "--":
            positional += args[i + 1:]
            break
        read = _flag_at(table, args, i)
        if read is None:
            positional.append(args[i])
            if until_positional:
                consumed, tail = i, args[i + 1:]
                break
            i += 1
        else:
            flags += read[0]
            unknown += read[1]
            i += read[2]
    return Argv(flags, positional, unknown, tail, consumed)


class GhCommand:
    """A parsed `gh` command: `group` and `verb` (`pr`, `merge`; `api`, ``), `argv` every flag of it read against the rows for that command, `operands` the words after the verb,
    `before_verb` the first flag before the group or (for `pr`) before the verb that the `gh` and `pr` rows do not list, else None. Such a flag may take a value, so the word after it
    may be the group or the verb and the command cannot be told: a gated rule refuses it (`_flag_before_verb`)."""
    def __init__(self, group, verb, argv, operands, before_verb=None):
        self.group, self.verb, self.argv, self.operands, self.before_verb = group, verb, argv, operands, before_verb


GH_VERB_ALIAS = {"new": "create"}  # `gh pr new` is `gh pr create`


def gh_command(args):
    """The GhCommand for the words after `gh`, else None when there is no command. Flags between `gh` and the group, and between the group and the verb, are read (`gh pr -R o/r merge 5`)
    and kept in `argv` with the rest."""
    first = normalise([("gh", "")], args, until_positional=True)
    if not first.positional:
        return None
    group = first.positional[0]
    keys, verb, before = [("gh", "")], "", list(first.unknown)
    if group == "api":
        keys.append(("api", ""))
    elif group in ("pr", "issue"):
        second = normalise([("gh", ""), (group, "")], first.tail, until_positional=True)
        verb = GH_VERB_ALIAS.get(second.positional[0], second.positional[0]) if second.positional else ""
        before += second.unknown
        keys += [(group, "")] + ([(group, verb)] if (group, verb) in FLAG_ROWS else [])
    argv = normalise(keys, first.tail)
    argv.flags, argv.unknown = first.flags + argv.flags, first.unknown + argv.unknown
    if group == "api":
        return GhCommand(group, "", argv, argv.positional, before[0] if before else None)
    if group in ("pr", "issue"):  # gh itself fails on an `issue` flag it does not know before the verb, so only `pr` reports one (`before_verb`)
        return GhCommand(group, verb, argv, argv.positional[1:], before[0] if before and group == "pr" else None)
    verb = argv.positional[0] if argv.positional else ""
    return GhCommand(group, verb, argv, argv.positional[1:], before[0] if before else None)


def _spelled(command, name):
    """How a flag of the table is written when a message shows it: its short name, else its long name."""
    short = _table(command)[0][name][0]
    return "-" + short if short else "--" + name


UNKNOWN_FLAG = (
    "`%s` carries a flag this hook's table does not know (`%s`), so the hook cannot tell what the command does and refuses it. Add the flag to the `%s` row of FLAG_ROWS in "
    "dot_local/share/agent-harness/hooks/bash_rules.py (for gh, copy the row from the gh wrapper's FLAGS: scripts/leak-guard-gh-flags regenerates it), then run the command again."
)


BEFORE_VERB = (
    "`gh` has a flag before its subcommand (`%s`) that this hook cannot read: gh may take the next word as that flag's value, so the hook cannot tell whether the command is "
    "`gh pr merge`, `gh pr edit` or `gh pr create`, and it refuses the command. Put the flag after the subcommand (`gh pr edit 5 -t T`); only `-R owner/repo` / `--repo` may come before it."
)


def _flag_before_verb(gh):
    """The refusal for a gh command with a flag before its group or its `pr` verb that the hook cannot read (`gh pr -t T edit 5`, `gh -x pr merge 5`), else None. It fails closed: the
    word after such a flag may be the verb, so the rules would never see `edit` or `merge`. The log line names the flag, not any value."""
    if gh is None or gh.before_verb is None:
        return None
    flag = gh.before_verb.partition("=")[0]
    refusal = Matched(BEFORE_VERB % flag, "gh")
    refusal.log = {"reason": "flag before the gh subcommand", "flag": flag}
    return refusal


def _unknown_refusal(command, argv, row):
    """The refusal for a gated command whose flags the table does not list, else None. The log line names the flag without any value attached to it."""
    if not argv.unknown:
        return None
    flag = argv.unknown[0]
    refusal = Matched(UNKNOWN_FLAG % (command, flag, row), command)
    refusal.log = {"reason": "flag not in FLAG_ROWS", "flag": flag}
    return refusal


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
    flag = "--" + KUBE_CONTEXT_FLAG[name]
    if name == "kubectl" and "config" in args:
        after = [a for a in args[args.index("config") + 1:] if not a.startswith("-")]
        if after and after[0] == "use-context":
            if len(after) > 1 and after[1] != HOMELAB:
                return kube_message("`kubectl config use-context %s`" % after[1], "Switch only to `%s`." % HOMELAB)
        return None  # the other `kubectl config` subcommands reach no cluster
    read = normalise([(name, "")], args)
    chosen = read.value(KUBE_CONTEXT_FLAG[name])
    if chosen is not None:
        return None if chosen == HOMELAB else kube_message("`%s %s`" % (flag, chosen), "Use `%s %s`." % (flag, HOMELAB))
    here = cmd.cwd or ""
    reader = ctx.read_file or read_file
    kubeconfig = read.value("kubeconfig")
    inline = [w[len("KUBECONFIG="):] for w in cmd.assigns if w.startswith("KUBECONFIG=")]
    if kubeconfig is not None:
        if "$" in kubeconfig or "`" in kubeconfig:
            return None  # the shell fills it in at run time; the hook cannot read it
        text = reader(os.path.join(here, os.path.expanduser(kubeconfig)))
        if text is None:
            return kube_message("`--kubeconfig %s`, which is not a file on this machine," % kubeconfig,
                                "Add `%s %s`." % (flag, HOMELAB))
        current = _current_context(text)
    else:
        listed = inline[-1] if inline else (ctx.env or {}).get("KUBECONFIG") or "~/.kube/config"
        current = None
        for path in listed.split(":"):
            current = _current_context(reader(os.path.join(here, os.path.expanduser(path)))) if path else None
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
        gh = gh_command(cmd.words[1:]) if _base(cmd.words[0]) == "gh" else None
        if _flag_before_verb(gh):
            return _flag_before_verb(gh)
        if gh is None or (gh.group, gh.verb) != ("pr", "merge"):
            continue
        refused = _unknown_refusal("gh pr merge", gh.argv, "pr merge")
        if refused:
            return refused
        repo = gh.argv.value("repo")
        if repo is None:
            repo = (ctx.origin_of or origin_of)(cmd.cwd)
        if repo and HOMELAB_REPO.search(repo):
            return MERGE_HOMELAB  # before the gates: the chained form skips the homelab RED-line check, so it is no way through
        checked = {e[len(PR_CHECK):] for e in cmd.gated if e.startswith(PR_CHECK)}
        if CI_GATE not in cmd.gated or not checked:
            return MERGE_BARE.replace(MERGE_PR, _merge_pr(ctx))
        merged = _pr_number(gh)  # None when it names a branch or no PR: the hook cannot see which
        if merged and str(int(merged)) not in checked:
            return MERGE_OTHER_PR % (" and ".join(sorted(checked, key=int)), merged) + MERGE_BARE.replace(MERGE_PR, _merge_pr(ctx))
        if repo and COORDINATOR.search(repo):
            return MERGE_COORDINATOR.replace(MERGE_PR, _merge_pr(ctx))
    return None


def _pr_number(gh):
    """The PR number `gh pr <verb>` names (a number, or a .../pull/N URL), else None (a branch name, or none)."""
    if not gh.operands:
        return None
    found = re.fullmatch(r"\d+|.*/pull/(\d+)/?", gh.operands[0])
    return (found.group(1) or found.group(0)) if found else None


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


def _api_pr_write(gh):
    """The record of a `gh api` call (a GhCommand) that writes to a pull request, else None: a POST/PATCH/PUT on a pulls endpoint, or a PATCH on `issues/<n>` (a PR is an issue too,
    so it can set a PR's body or title). {method, endpoint, kind, fields, input_file}, `fields` as (name of the flag, value, spelling typed) for each `-f`/`-F` field. Every spelling gh reads
    (`-fbody=x`, `-f=body=x`, `-XPATCH`, a leading slash, a full URL) is read by the normaliser and PR_API_ENDPOINT."""
    read = gh.argv
    endpoint = gh.operands[0] if gh.operands else None
    found = PR_API_ENDPOINT.fullmatch(endpoint) if endpoint else None
    if not found:
        return None
    fields = [(n, v, typed) for n, v, typed in read.flags if n in ("field", "raw-field") and v is not None]
    input_file = read.value("input")
    method = read.value("method")
    method = method.upper() if method is not None else ("POST" if fields or input_file is not None else "GET")
    pulls = found.group("kind") == "pulls"
    if not (method in ("POST", "PATCH", "PUT") if pulls else method == "PATCH" and re.search(r"/\d+/?$", found.group("path"))):
        return None
    return {"method": method, "endpoint": found.group("path"), "kind": found.group("kind"), "fields": fields, "input_file": input_file}


def _api_shown(write):
    """The command a log line shows: the parts of a gh api write, with every field value redacted so it never holds a body, a title or a token."""
    shown = ["gh", "api", _spelled(("api", ""), "method"), write["method"], write["endpoint"]]
    shown += [x for _, f, typed in write["fields"] for x in (typed.partition("=")[0], f.partition("=")[0] + "=<redacted>")]  # `--field=body=x` is one word: keep the flag, never its value
    if write["input_file"] is not None:
        shown += [_spelled(("api", ""), "input"), write["input_file"]]
    return " ".join(shown)


def _api_sets_pr_body(gh):
    """The record of a `gh api` call that sets a PR body, else None: `_api_pr_write` with a `body` field or an input file (whose JSON the hook cannot see).
    The record is {method, endpoint, reason, command, kind}; `command` is rebuilt from the parsed parts with every field value redacted."""
    write = _api_pr_write(gh)
    if not write:
        return None
    if write["input_file"] is None and not any(f.partition("=")[0] == "body" for _, f, _ in write["fields"]):
        return None
    reason = "%s on the %s endpoint sets a body (%s)" % (write["method"], write["kind"], _spelled(("api", ""), "input") if write["input_file"] is not None else "a body field")
    return {"method": write["method"], "endpoint": write["endpoint"], "reason": reason, "command": _api_shown(write), "kind": write["kind"]}


def _api_sets_pr_title(gh, gated):
    """The record of a `gh api` call that sets a PR title the body check was not given, else None: `_api_pr_write` with a `title` field whose text is not in `gated` (a
    `pr-body-check --title T` joined to it by `&&`, as for `gh pr edit --title`). Every title field counts. A `-F title=@file` (or `@-`) reads its text from a file or stdin, which no
    check can have been given, so it is always refused; `-f` sends the text as it is. An input file is already refused as a body."""
    write = _api_pr_write(gh)
    if not write:
        return None
    titles = [(n, f.partition("=")[2]) for n, f, _ in write["fields"] if f.partition("=")[0] == "title"]
    from_file = any(n == "field" and t.startswith("@") for n, t in titles)
    if not titles or (not from_file and all(BODY_TITLE + t in gated for _, t in titles)):
        return None
    return {"method": write["method"], "endpoint": write["endpoint"], "kind": write["kind"], "from_file": from_file, "command": _api_shown(write)}


def pr_body_rule(walk, ctx):
    if ctx.profile not in GATE_PROFILES:
        return None
    for cmd in walk.cmds:
        gh = gh_command(cmd.words[1:]) if _base(cmd.words[0]) == "gh" else None
        if _flag_before_verb(gh):
            return _flag_before_verb(gh)
        if gh is None:
            continue
        if gh.group == "api":
            api_body = _api_sets_pr_body(gh)
            if api_body:
                template = PR_API_BODY if api_body["kind"] == "pulls" else PR_API_ISSUE_BODY
                message = Matched(template % ((PR_OPEN["create"], PR_OPEN["edit"]) if api_body["kind"] == "pulls" else (PR_OPEN["edit"],)),
                                  "%s %s" % (api_body["method"], api_body["endpoint"]))
                message.log = {"reason": api_body["reason"], "command": api_body["command"]}
                return message
            api_title = _api_sets_pr_title(gh, cmd.gated)
            if api_title:
                message = Matched(_api_title_message(api_title), "%s %s" % (api_title["method"], api_title["endpoint"]))
                message.log = {"reason": "title not given to the check", "command": api_title["command"]}
                return message
            endpoint = gh.operands[0] if gh.operands else ""
            if PR_API_ENDPOINT.fullmatch(endpoint):  # a call on a PR or issue endpoint: its flags must all be known, or a body flag could hide in one
                refused = _unknown_refusal("gh api", gh.argv, "api")
                if refused:
                    return refused
            continue
        if gh.group != "pr" or gh.verb not in ("create", "edit"):
            continue
        verb = gh.verb
        refused = _unknown_refusal("gh pr " + verb, gh.argv, "pr " + verb)
        if refused:
            return refused
        body_file = gh.argv.value("body-file")
        sets_body = body_file is not None or gh.argv.value("body") is not None
        title = gh.argv.value("title")
        if verb == "edit" and not sets_body:
            if title is None:
                continue  # a label or reviewer change carries no title and no body
            if BODY_TITLE + title not in cmd.gated:  # a rename: the check reads the title the PR will have
                return _title_refusal(verb, title)
            continue
        if body_file is None or body_file == "-":
            return PR_BODY % (verb, PR_OPEN[verb], verb)
        number = _pr_number(gh) if verb == "edit" else None
        problems = [_body_file_problem(body_file, verb, number, walk.mktemps)]
        title_unchecked = False
        if BODY_FILE + body_file not in cmd.gated:
            problems.append(PR_BODY % (verb, PR_OPEN[verb], verb))
        elif title is not None and BODY_PAIR + body_file + "\0" + title not in cmd.gated:
            problems.append(PR_TITLE % (verb, shlex.quote(title), verb, PR_OPEN[verb]))
            title_unchecked = True
        problems = [p for p in problems if p]
        if problems:
            message = " ".join(problems)
            return _title_refusal(verb, title, message) if title_unchecked else message
    return None


def _issue_open_armed(ctx):
    """True when this machine can run `issue-open`: the coordinator checkout (ctx.coordinator_repo, else ~/git/coordinator) holds the claims command. Until it does, a refusal
    would leave an agent with no way to file an issue, so the rule waits for it, whatever order the dotfiles apply and the coordinator pull land in."""
    home = (ctx.env or {}).get("HOME") or os.path.expanduser("~")
    repo = ctx.coordinator_repo or os.path.join(home, LIVE_CHECKOUT)
    return os.path.isfile(os.path.join(repo, ISSUE_OPEN_CLI))


def _api_creates_issue(gh):
    """The record of a `gh api` call (a GhCommand) that creates an issue, else None: a POST (the default when it has a field or an input file) on `repos/<o>/<r>/issues`
    with no issue number. A PATCH on `issues/<n>` is `pr_body_rule`'s, since a PR is an issue too."""
    read = gh.argv
    endpoint = gh.operands[0] if gh.operands else None
    found = PR_API_ENDPOINT.fullmatch(endpoint) if endpoint else None
    if not found or found.group("kind") != "issues" or re.search(r"/\d+/?$", found.group("path")):
        return None
    has_input = read.value("input") is not None or any(n in ("field", "raw-field") and v is not None for n, v, _ in read.flags)
    method = read.value("method")
    method = method.upper() if method is not None else ("POST" if has_input else "GET")
    return {"method": method, "endpoint": found.group("path")} if method == "POST" else None


def issue_body_rule(walk, ctx):
    if ctx.profile not in GATE_PROFILES or not _issue_open_armed(ctx):
        return None
    for cmd in walk.cmds:
        gh = gh_command(cmd.words[1:]) if _base(cmd.words[0]) == "gh" else None
        if gh is None:
            continue
        if gh.group == "issue" and gh.verb == "create":
            message = Matched(ISSUE_BODY, "gh issue create")
            message.log = {"reason": "issue created without issue-open"}
            return message
        if gh.group == "api":
            created = _api_creates_issue(gh)
            if created:
                message = Matched(ISSUE_API_BODY, "gh api POST " + created["endpoint"])
                message.log = {"reason": "POST on the issues endpoint creates an issue", "command": "gh api -X POST " + created["endpoint"]}
                return message
    return None


def _api_title_message(record):
    """The refusal text for a `gh api` title write: PR_API_TITLE (or the issue-number form), and a line on `-F title=@file` when the title is read from a file."""
    message = PR_API_TITLE if record["kind"] == "pulls" else PR_API_ISSUE_TITLE
    return message + (" The title in this command is read from a file or stdin (`-F title=@...`), which no check can have been given: pass it as text with `-f title=T`." if record["from_file"] else "")


def _title_refusal(verb, title, message=None):
    """The refusal for a title the body check was not given, with the reason the guard log counts it by (principle 14)."""
    refusal = Matched(message or PR_TITLE % (verb, shlex.quote(title), verb, PR_OPEN[verb]), "gh pr %s --title" % verb)
    refusal.log = {"reason": "title not given to the check"}
    return refusal


def _docker_spelling(words):
    """(the refused docker command in words (`docker run`, `docker compose up`, ...) or None, the first flag before the subcommand that the table does not list or None).
    Only the subcommand position counts: the options before it are read by the normaliser, so `docker -H host run`, `docker -Hhost run` and `docker compose -f f up` find it."""
    name = _base(words[0])
    if name not in ("docker", "docker-compose"):
        return None, None
    top = normalise([(name, "")], words[1:], until_positional=True)
    unknown = list(top.unknown)
    subcommand = top.positional[:1]
    if name == "docker-compose":
        subcommand = ["compose"] + subcommand
    elif subcommand and ("docker", subcommand[0]) in FLAG_ROWS:  # compose, buildx, builder, container, image: one more word, after that group's own flags
        inner = normalise([("docker", subcommand[0])], top.tail, until_positional=True)
        unknown += inner.unknown
        subcommand += inner.positional[:1]
    for size in (1, 2):
        if tuple(subcommand[:size]) in DOCKER_REFUSED:
            return " ".join(["docker"] + subcommand[:size]), None
    return None, (unknown[0] if unknown else None)


def docker_rule(walk, ctx):
    if ctx.profile != "personal" or not (ctx.platform or sys.platform).startswith("linux"):
        return None
    for cmd in walk.cmds:
        spelling, unknown = _docker_spelling(cmd.words)
        if spelling:
            return DOCKER % spelling
        if unknown:  # the subcommand is not seen past a flag the table does not list
            refused = Matched(UNKNOWN_FLAG % ("docker", unknown, _base(cmd.words[0])), "docker")
            refused.log = {"reason": "flag not in FLAG_ROWS", "flag": unknown}
            return refused
    return None


JS_RUNNERS = {"npm", "pnpm", "yarn", "bun"}
HEAVY_SCRIPT = re.compile(r"(?:^|[:_-])(?:tests?|vitest|journeys?|stress)(?:$|[:_-])")  # a package script that runs tests, journeys or stress
LIGHT_SCRIPT = re.compile(r"^(?:typecheck|lint)(?:$|[:_-])")  # typecheck:test and lint:test check files; they are not test runs


def _heavy_script(name):
    return bool(HEAVY_SCRIPT.search(name)) and not LIGHT_SCRIPT.match(name)
NPM_TEST = {"test", "t", "tst"}


def _js_args(words):
    """The words after the package manager that are not options (an option that takes a value is skipped with it)."""
    return normalise([("js", "")], words).positional


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
    """(the options before the subcommand as an Argv, the subcommand or None, the Argv of the words after it read against that subcommand's row) of a git command."""
    top = normalise([("git", "")], words[1:], until_positional=True)
    sub = top.positional[0] if top.positional else None
    return top, sub, normalise([("git", sub)] if sub and ("git", sub) in FLAG_ROWS else [], top.tail, until_positional=sub == "stash")


def _git_change(sub, read):
    """(the spelling (`git merge`) of a git command that changes the working tree, index, HEAD or a branch, else None; the first flag the table does not list when
    that decides it, else None). `read` is the Argv of the words after the subcommand."""
    names, plain = set(read.names()), read.positional
    if sub in GIT_TABLE_GUARDED and read.unknown:
        return "git " + sub, read.unknown[0]  # a flag the hook cannot read: it may be one that changes things
    if sub == "merge":
        if names == {"abort"} and not plain:  # undoes a merge already in progress
            return None, None
        deploy = "ff-only" in names and names <= GIT_MERGE_FLAGS and len(plain) == 1 and SHA.fullmatch(plain[0])
        return (None if deploy else "git merge"), None
    if sub == "reset":
        rollback = names == {"keep"} and len(plain) == 1 and SHA.fullmatch(plain[0])  # docs/deploy.md: a failed install
        return (None if rollback else "git reset"), None
    if sub == "stash":
        return (None if not names and plain[:1] in (["list"], ["show"]) else "git stash"), None
    if sub == "branch":
        listing = bool(names & GIT_BRANCH_LISTS)
        return ("git branch" if names & GIT_BRANCH_CHANGES or (plain and not listing) else None), None
    return ("git " + sub if sub in GIT_ALWAYS_REFUSED else None), None


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
    for name, value, _ in opts.flags:
        if value is None:
            continue
        if name == "C":
            here = _resolve(value, here, home)
            places = [here] + places[1:]
        elif name in ("git-dir", "work-tree"):
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


def stash_rule(walk, ctx):
    """A `git stash` that writes the stash list, in any directory: every worktree of a repo shares that list, so the place does not matter.
    `_git_change` decides what writes (every form but `list` and `show`)."""
    for cmd in walk.cmds:
        if _base(cmd.words[0]) != "git":
            continue
        _, sub, read = _git_parts(cmd.words)
        if sub == "stash" and _git_change(sub, read)[0]:
            return Matched(STASH % "git stash", "git stash")
    return None


def live_git_rule(walk, ctx):
    for cmd in walk.cmds:
        name = _base(cmd.words[0])
        if name == "gh":  # `gh pr checkout` fetches the PR and checks it out in the directory it runs in
            gh = gh_command(cmd.words[1:])
            if gh and cmd.cwd and _in_live_checkout(cmd.cwd, walk.home, ctx.coordinator_repo):
                if _flag_before_verb(gh):  # `gh pr -x co 5`: the verb cannot be told
                    return _flag_before_verb(gh)
                if gh.group == "pr" and gh.verb in ("checkout", "co"):
                    return GIT_LIVE % ("gh pr checkout", _live_checkout_name(ctx))
        if name != "git":
            continue
        top, sub, read = _git_parts(cmd.words)
        in_live = any(_in_live_checkout(p, walk.home, ctx.coordinator_repo) for p in _git_places(cmd, top, walk.home))
        if not in_live:
            continue
        if top.unknown:  # a git option the table does not list: the subcommand cannot be told
            refused = Matched(UNKNOWN_FLAG % ("git", top.unknown[0], "git"), "git")
            refused.log = {"reason": "flag not in FLAG_ROWS", "flag": top.unknown[0]}
            return refused
        spelling, unknown = _git_change(sub, read) if sub else (None, None)
        if spelling and unknown:
            refused = Matched(UNKNOWN_FLAG % (spelling, unknown, spelling), spelling)
            refused.log = {"reason": "flag not in FLAG_ROWS", "flag": unknown}
            return refused
        if spelling:
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
GREP_QUIET = {"files-with-matches", "files-without-match", "count", "quiet", "silent"}  # flag names as FLAG_ROWS reads them
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
# command -> the FLAG_ROWS key that reads its flags. The flags that take a value are in the rows, so a value is never mistaken for a file; FILE_SUPPLIERS names the flags that
# supply the pattern or script, after which every operand is a file.
FILE_TOOLS = {"grep": "grep", "egrep": "grep", "fgrep": "grep", "ag": "grep", "ack": "grep", "rg": "rg", "sed": "sed", "awk": "awk", "gawk": "awk", "mawk": "awk",
              "jq": "jq", "tomlq": "jq", "xq": "jq", "yq": "yq"}


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
    tool = FILE_TOOLS.get(name)
    if tool is None:
        return operands + inputs
    read = normalise([(tool, "")], operands)
    supplied = any(n in FILE_SUPPLIERS for n in read.names())
    return (read.positional if supplied else read.positional[1:]) + inputs


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
    tool = FILE_TOOLS.get(name)
    names = set(normalise([(tool, "")], args).names()) if tool in ("grep", "rg", "sed") else set()
    if tool in ("grep", "rg"):
        return not names & GREP_QUIET
    if tool == "sed":
        return "in-place" not in names
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
    Only a flag that comes straight after `gh` is dropped, and only when it is the repo flag; anything else is left as typed."""
    if words[:1] != ["gh"]:
        return words
    top = normalise([("gh", "")], words[1:], until_positional=True)
    if not top.positional or set(top.names()) != {"repo"}:
        return words
    return ["gh"] + words[1 + top.consumed:]


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


# --- bash-engine: a hand-typed Loop Engine write on a lead's or the coordinator's run (design step S2h)
ENGINE_WRITES = ("start", "append", "event", "terminate")  # the four verbs of `loop-engine --help` that change a run; reclaim only trims finished runs' payloads and is not a run write
LEAD_RUN = re.compile(r"lead-[^/\s]+-[0-9]+")  # the whole shape the workflow commands make: `lead-<slug>-<n>`; `lead-a-b` (no number), `leader-1` and `lead-1` are not it
COORDINATOR_RUN = re.compile(r"coordinator-loop-[^/\s]+")
UNREADABLE_ID = re.compile(r"[$`*?\[]")  # a variable, a command substitution or a glob: the shell fills the id in after the hook has read the text
ENGINE_OVERRIDE = "BASH_ENGINE_OVERRIDE"  # the way past: `BASH_ENGINE_OVERRIDE='<why>' loop-engine ...`, an assignment on the command itself, so one command is one use
ENGINE_FIX = {  # (kind of run, verb) -> the workflow command that does the move
    ("lead", "start"): "`workflows lead enrol NAME` starts a workstream's lead run; `workflows lead start-run --provider lean-change --workstream NAME` starts a linked change run",
    ("lead", "append"): "`workflows lead catch-up NAME` (it replays moves and repairs a claim with no settle); `workflows lead note --did TEXT [--for ITEM]` records a move that has no command",
    ("lead", "event"): "`workflows lead catch-up NAME` (it replays moves and repairs a claim with no settle); `workflows lead note --did TEXT [--for ITEM]` records a move that has no command",
    ("lead", "terminate"): "`workflows lead cancel RUN --why TEXT` ends one run, `workflows lead retire NAME` ends a workstream's run",
    ("coordinator", "start"): "`workflows coordinator enrol` starts the loop, `workflows coordinator roll` replaces it",
    ("coordinator", "append"): "`workflows coordinator release EVENT --why TEXT` puts a wedged loop back to waiting, `workflows lead catch-up NAME` repairs a claim with no settle",
    ("coordinator", "event"): "`workflows coordinator release EVENT --why TEXT` puts a wedged loop back to waiting, `workflows lead catch-up NAME` repairs a claim with no settle",
    ("coordinator", "terminate"): "`workflows coordinator retire` ends the loop, `workflows coordinator roll` replaces it",
}
ENGINE_NOT_BUILT = ("workflows lead catch-up", "workflows lead note")  # commands a refusal names that are not deployed yet; when they are, make this `()` and the sentence is gone
BASH_ENGINE = (
    "`loop-engine %s %s` is refused in agent sessions: that is %s, whose record the workflow commands keep, and a hand-typed engine write on it skips their checks. "
    "Use %s. If none of them can make the move, one command takes this refusal with a logged reason: put the reason on that command, "
    "`" + ENGINE_OVERRIDE + "='<why>' loop-engine %s ...` (the use is written to the guard log with the reason and counted; an exported variable does not count, so each command needs its own)."
)
BASH_ENGINE_UNREAD = (
    "`loop-engine %s` is refused in agent sessions: its run id (`%s`) is filled in by the shell, so the hook cannot tell whether it is a lead's or the coordinator's run (`lead-<slug>-<n>`, `coordinator-loop-...`). "
    "Write the run id out in the command. For a lead's or the coordinator's run use the `workflows lead|coordinator` commands: `workflows lead catch-up NAME`, `cancel RUN --why TEXT`, `retire NAME`, `workflows coordinator release|retire|roll`. "
    "If a variable is what the job needs, one command takes this refusal with a logged reason: `" + ENGINE_OVERRIDE + "='<why>' loop-engine %s ...` (logged with the reason and counted)."
)


def _with_not_built(message):
    """The refusal text, with one sentence added when it names a command that is not built yet (ENGINE_NOT_BUILT): say so, and that the way past today is the override on that one command."""
    if not any(name in message for name in ENGINE_NOT_BUILT):
        return message
    names = " and ".join("`%s`" % name for name in ENGINE_NOT_BUILT)
    return message + " Note: %s are not built yet, so until they are the way past is `%s='<why>'` on that one command." % (names, ENGINE_OVERRIDE)


def _run_kind(word):
    """"lead" or "coordinator" when the word is the id of a lead's or the coordinator's run (the whole word), else None."""
    if LEAD_RUN.fullmatch(word):
        return "lead"
    return "coordinator" if COORDINATOR_RUN.fullmatch(word) else None


def _attached(words):
    """The values of `--run=ID`, `--run-id=ID` and `--id=ID` words (read one word at a time through the flag table): they name the run whatever other flag the table lacks, so the whole-word fallback reads them too."""
    found = []
    for word in words:
        if word.startswith("-") and "=" in word:
            one = normalise([("loop-engine", "")], [word])
            found += [v for name in ("run", "run-id", "id") for v in one.values(name)]
    return found


def _engine_write(words):
    """(verb, the words that can be the run id, the words that are exactly the id's place) of a `loop-engine` write, else None. A write names its run by a flag (`--run`, `--run-id`, `--id`, before or after the verb)
    or else as the first word after the verb (`start` names it only by flag), after every flag the engine takes in any spelling (FLAG_ROWS). A flag the table lacks may take the next word, so the id cannot be
    placed: then every word of the command is a candidate."""
    top = normalise([("loop-engine", "")], words[1:], until_positional=True)
    if top.unknown:
        verb = next((w for w in words[1:] if w in ENGINE_WRITES), None)
        return (verb, words[1:] + _attached(words[1:]), _attached(words[1:])) if verb else None
    verb = top.positional[0] if top.positional else None
    if verb not in ENGINE_WRITES:
        return None
    tail = top.tail if top.tail or len(top.positional) < 2 else top.positional[1:]  # `loop-engine -- event ID E`: after the dashes everything is a plain word
    read = normalise([("loop-engine", ""), ("loop-engine", verb)] if ("loop-engine", verb) in FLAG_ROWS else [("loop-engine", "")], tail)
    if read.unknown:
        return verb, tail + _attached(tail), _attached(tail)
    named = [v for flags in (top, read) for name in ("run", "run-id", "id") for v in flags.values(name)]
    if named or verb == "start":
        return verb, named, named
    return verb, read.positional[:1], read.positional[:1]


def bash_engine_rule(walk, ctx):
    for cmd in walk.cmds:
        if _base(cmd.words[0]) != "loop-engine":
            continue
        write = _engine_write(cmd.words)
        if not write:
            continue
        verb, candidates, placed = write
        kinds = {w: _run_kind(w) for w in candidates}
        kind = next((k for k in kinds.values() if k), None)
        unread = next((w for w in placed if UNREADABLE_ID.search(w)), None) if not kind else None
        if not kind and not unread:
            continue
        reason = next((w.partition("=")[2].strip() for w in reversed(cmd.assigns) if w.partition("=")[0] == ENGINE_OVERRIDE), "")
        if reason:  # the way past: this one command, with its reason, written to the guard log
            walk.notes.append(("bash_engine", "loop-engine " + verb, {"reason": "override", "why": reason[:300], "run_kind": kind or "unread"}))
            continue
        if kind:
            run = next(w for w, k in kinds.items() if k)
            message = Matched(_with_not_built(BASH_ENGINE % (verb, run, "a lead's run" if kind == "lead" else "the coordinator's run", ENGINE_FIX[(kind, verb)], verb)), "loop-engine " + verb)
            message.log = {"reason": "write on a %s run" % kind, "run_kind": kind}
        else:
            message = Matched(_with_not_built(BASH_ENGINE_UNREAD % (verb, unread, verb)), "loop-engine " + verb)
            message.log = {"reason": "run id not readable", "run_kind": "unread"}
        return message
    return None


RULES = (poll_rule, heredoc_rule, kube_rule, merge_rule, pr_body_rule, issue_body_rule, docker_rule, heavy_rule, stash_rule, live_git_rule, credential_rule, bash_engine_rule, door_rule)


def refusal(text, ctx):
    """(rule name, refusal message, matched command name or None) for the command text, or None. The matched name is from the rule's fixed list, never the command text."""
    walk = Walk(text, ctx.cwd, (ctx.env or {}).get("HOME"))
    for rule in RULES:
        message = rule(walk, ctx)
        if message:
            return rule.__name__.replace("_rule", ""), message, getattr(message, "matched", None)
    for note in walk.notes if ctx.note else ():  # a way past is logged only when the command ran: no rule refused it
        ctx.note(*note)
    return None


def check(text, ctx):
    """The refusal message for the command text, or None."""
    found = refusal(text, ctx)
    return found[1] if found else None
