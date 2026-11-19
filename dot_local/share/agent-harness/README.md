# Agent Harness

This directory contains the canonical, harness-agnostic configuration sources and thin per-harness adapters used to project them into Claude, Codex, and future agent harnesses.

## Layout

```text
dot_local/share/agent-harness/
  reviewer-brief.md      # the one brief every reviewer follows: the blocking bar, inputs, re-review scope, return
  findings-contract.md   # v1: the shape of a reviewer's return and the review log records
  finding-triage.md      # the four tests every review finding gets before anyone acts on it
  reviewer-examples.md   # twelve real cases (seven blocking, five notes) for calibrating the bar
  hooks/
    refuse_pattern_kill.py   # the pkill/killall classifier that Claude's hook, Codex's hook and Pi's extension run (see "Pattern-kill guard")
    stop_running_jobs.py     # the builder seat's Stop hook: refuses to stop while a run-and-wake or kgate job this thread started still runs (see "Builder Stop hook")
    bash_rules.py            # the eight extra refusals it calls: sleep-poll, heredoc, kube context, merge, PR body, local docker, git in the live coordinator checkout, credential config
    profile                  # rendered from profile.tmpl: just the chezmoi profile name, read by bash_rules
  bin/
    config-show              # prints a config file's keys with every value masked (see "Config reader"); source name executable_config-show
    disposition-check        # refuses a `fixed` review disposition that has neither a sha of the reviewed change nor an artifact reference (findings-contract.md rule 3); the reviewer brief runs it at re-review (source name executable_disposition-check)
    known-limits-check       # fails a PR body whose limits are not under "## Known limits", are untracked, or name a ticket the tracker lookup cannot confirm; reviewer-brief.md section 1 runs it on the body as filed (source name executable_known-limits-check)
    mcp-ticket-lookup        # confirms one ticket key through a single read-only MCP tool in a locked-down non-interactive claude turn (FOUND or MISSING; exit 0 only on an exact FOUND match with the requested key); the work profile's KNOWN_LIMITS_TRACKER_CMD points known-limits-check at it (source name executable_mcp-ticket-lookup)
  canonical/
    instructions/
      AGENTS.md
      axon-playbook.md
      hindsight-guidance.md
      profile-personal.md
      profile-work.md
    mcp/
      servers.json.tmpl
    skills/
      ...
  adapters/
    claude/
      mcp-secrets.json.tmpl
    codex/
      mcp-secrets.json.tmpl
    pi/
      mcp-secrets.json.tmpl
```

Rules:

- `canonical/` is the source of truth.
- Canonical sources should stay standards-based.
- Pi 0.99+ uses native MCP and codemode, not `pi-mcp-adapter`. The Pi adapter
  still generates `~/.pi/agent/mcp.json` from these canonical sources and
  preserves manually added servers. It records the names it writes in
  `~/.local/share/agent-harness/generated/pi/mcp-managed.json` and removes a recorded
  name from `mcp.json` once canonical (or this profile's render) no longer has it;
  `furi` and `automation-mcp` are also removed because they were managed before the
  record existed. Manage connections with `/mcp`; use
  `codemode` for tool discovery and batching instead of `mcp`/`mcpScript`.
  Both desktop profiles use codemode's `only` mode: ordinary tools remain
  callable from scripts rather than directly declared to the model.
  Hindsight's automatic hooks use REST and are independent of MCP.
- `rea` starts straight from a mise-installed, pinned npm package (`npm:rea-agents` in `dot_config/mise/config.toml`, the only place
  the version lives); the canonical entry names the mise shim (`~/.local/share/mise/shims/rea`), so the server is one process with no
  `npm exec` wrapper beside it. To bump it, change the pin in `config.toml`, apply, and regenerate the pi-mcp-lazy seed. `mise install`
  must have run before a harness starts it (the apply's bootstrap does it). The browser server is `browse` on both profiles (a pinned mise install, below). `jira` (work) is a remote HTTP server in the canonical file, so no harness launches anything for it.
- The Playwright MCP server (`@playwright/mcp`) is retired (Michael, ask #1040): browser work goes through Browse. The
  Claude apply step removes a leftover `playwright` registration from `~/.claude.json`; Codex's block and Pi's `mcp.json` drop it
  on the same apply. (The Chromium wrapper `~/.local/bin/chromium`, which uses Playwright's Chrome for Testing build for Pi's
  `launch_browser`, is a different thing and stays.)
- The Claude, Codex and Pi adapters wrap the local `rea` entry in `~/.local/bin/pi-mcp-lazy` (names in
  `~/.local/share/pi-mcp-lazy/servers.list`) so a session starts each server on first use, not at session start. `rea` stops when idle. `browse` is not wrapped: `browse mcp` is a 3.5 MiB stdio proxy and its relay is shared and manages itself. (`jira` on the work profile is lazy in Pi only.) See [`pi-mcp-lazy`](../pi-mcp-lazy/README.md).
- `adapters/` may contain harness-specific metadata needed to project canonical sources into a given harness.
- Do not put harness-specific semantics into canonical files unless the open standard itself requires them.

## Add A Canonical Instruction

Edit a file under [`canonical/instructions/`](./canonical/instructions/). These
fragments are included into every harness. Do not copy them by hand:

- Pi: [`dot_pi/private_agent/literal_AGENTS.md.tmpl`](../../../dot_pi/private_agent/literal_AGENTS.md.tmpl) (`~/.pi/agent/AGENTS.md`)
- Claude: [`dot_claude/CLAUDE.md.tmpl`](../../../dot_claude/CLAUDE.md.tmpl) (Claude's user-global filename is `CLAUDE.md`)
- Codex: [`dot_codex/modify_AGENTS.md.tmpl`](../../../dot_codex/modify_AGENTS.md.tmpl) (`~/.codex/AGENTS.md` managed block)

Guidelines:

- One concern per file. Keep fragments includable (a section heading is fine; do not add a document H1).
- Shared standing rules live in [`canonical/instructions/AGENTS.md`](./canonical/instructions/AGENTS.md). Include that file into each harness's `AGENTS.md` (Claude: `CLAUDE.md`). Do not create `~/AGENTS.md`. Do not put shared rules in Pi `APPEND_SYSTEM.md`.
- Follow [Apply and Verify](#apply-and-verify), then check the live destination files.

Current files: [AGENTS.md](./canonical/instructions/AGENTS.md) (the design-principles pointer, scripts vs skills, voice, subagents, which role reads files and which asks the `reader` helper (`dot_claude/agents/reader.md`, Claude only), ownership, decisions and escalation), [hindsight-guidance.md](./canonical/instructions/hindsight-guidance.md) (in `~/.claude/CLAUDE.md` and the Codex and Pi files; the Claude builder, planner and reviewer seats load it as the `hindsight-memory` skill instead, see `docs/profiles.md` "Agent seat instances"), and [axon-playbook.md](./canonical/instructions/axon-playbook.md) (work profile only: the private playbook's `bin/playbook-context` output arrives at session start from Claude Code's hook and Pi's `axon-playbook` extension, Codex runs it itself, and every harness uses `axon-pr-preflight` before PR actions; each harness template includes it under an `axon-work-computer` gate). [profile-work.md](./canonical/instructions/profile-work.md) (`axon-work-computer` only: never merge or deploy without the owner's explicit approval) and [profile-personal.md](./canonical/instructions/profile-personal.md) (`personal` only: merging and deploying approved work is the agent's to do); each of the three harness templates includes them under a profile gate, and termux gets neither. Both profile files also carry the agent seat table (which model runs the coordinator, lead, planner, reviewer, builder and browser-work seats; a rule for agents to read, with no launch helper); the only difference is the browser-work row.

## Add A Canonical MCP Server

Edit [`canonical/mcp/servers.json.tmpl`](./canonical/mcp/servers.json.tmpl).

Guidelines:

- Keep the definition in standard MCP form.
- Prefer the smallest portable shape that works across harnesses.
- Do not put `op://...` references or other secret manager details in the canonical file.
- Use harness adapter metadata for secrets or harness-only behavior.

Example stdio server:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["my-server", "mcp"]
    }
  }
}
```

Example HTTP server:

```json
{
  "mcpServers": {
    "context7": {
      "type": "http",
      "url": "https://mcp.context7.com/mcp",
      "headers": {
        "CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"
      }
    }
  }
}
```

After editing the canonical MCP file:

1. If the server needs secrets, add or update adapter metadata in `adapters/<harness>/mcp-secrets.json.tmpl`.
2. Follow [Apply and Verify](#apply-and-verify) for the changed source.
3. Verify the harness-specific result:
   - Claude: `claude mcp list`
   - Codex: `codex mcp list`
   - Pi: `pi mcp list`, then `/mcp` in a fresh Pi session

TickTick uses the official server at `https://mcp.ticktick.com` in the personal
and work desktop profiles. Sign in separately on each machine and in each
harness: `pi mcp login ticktick`, `codex mcp login ticktick`, or Claude's `/mcp`
menu. Credentials stay in the harness's local OAuth store, not in canonical
configuration or 1Password adapter metadata. In a running Pi session, use
`/reload` after applying, then `/mcp login ticktick`.

The `shartifacts` entry is Michael's page server (`https://shartifacts.internal.cartwmic.com/mcp`, Streamable
HTTP, no sign-in). It is on both desktop profiles, like TickTick and Hindsight: Michael asked for the work profile too
(2026-11-13, rule 272f08d0; `docs/profiles.md` records the quote), so it has no row in the coverage table. The command
`shx-note-image` (`dot_local/share/shx/README.md`) and the canonical skill `using-shartifacts` go with it. Test:
`tests/shx/test_agent_access.py`.

The entry sends two request headers so the server can tell which machine and which thread a call came from.
`X-Origin` is the profile's machine, `personal` or `work`, a plain value from the template. `X-Thread` is written
`${T3CODE_THREAD_ID:-}` in the canonical file and each harness reads the variable when a session runs, never at apply
time (the apply installs the entry whether or not the variable is set):

| Harness | How the thread gets there |
|---|---|
| Claude Code | Stores the header with the `${T3CODE_THREAD_ID:-}` text (single-quoted in `setup-mcp.sh`) and expands it itself at session start. Unset gives an empty header. Checked with a real session: `tests/shx/test_thread_header.py LiveClaude`. |
| Codex | `env_http_headers = { "X-Thread" = "T3CODE_THREAD_ID" }`; Codex sends nothing when the variable is unset. |
| Pi | The header becomes the command value `!printf %s "${T3CODE_THREAD_ID:-none}"`, which Pi runs when the session connects, with the session's environment. Pi fails a server whose header resolves to nothing, so an unset variable sends `none`. |
| Cursor | `dot_cursor/modify_mcp.json.tmpl` writes `${env:T3CODE_THREAD_ID}`, Cursor's own syntax for an environment variable, and Cursor fills it in from its environment. It sets only `hindsight` and `shartifacts` (the two the Claude fleet seats get, from `.chezmoitemplates/fleet_mcp_servers`) in `~/.cursor/mcp.json`, with just `url` and `headers`. Every other server and key in the file is kept; a file that is not a JSON object is left as it is, with a warning. Test: `tests/cursor/test_mcp.py`. |

## Pattern-kill guard

Agent sessions refuse `pkill` and `killall`, so a pattern kill cannot hit another agent's jobs (three incidents in two days, including a
reviewer's `pkill -f "sleep 30" -P 1`). Decision: Michael, ask 744, "Add the guard". The refusal text tells the agent to use `kill-mine '<pattern>'`, to kill an exact PID
(`kill <pid>`, the PID from `$!`; the way on macOS) or to use `kgate cancel <id>` for a kgate job.

The refusal was hit 868 times in 397 sessions in the week of 2026-11-09 (retro, build-1116 L6) and agents often retried: telling them again did not work, so there is a tool that does what they wanted. `kill-mine PATTERN [-SIGNAL] [--dry-run]` (`dot_local/bin/executable_kill-mine`, `~/.local/bin/kill-mine`, both desktop profiles) signals the processes whose command line matches PATTERN (a regular expression, like `pgrep -f`) **and** that the caller's own agent session started. It prints each PID and command line it signalled, and exits 1 when nothing of this session matched (it says whether other sessions' processes matched and were left alone).

- *Own session* is read from `/proc/PID/environ`. Claude Code tool-call shells carry `CLAUDE_CODE_SESSION_ID`; the `claude` process and T3's `sh` wrapper around it do not (checked live), so a harness process is never mine though it shares `T3CODE_THREAD_ID`. Under T3 the target must carry the caller's `T3CODE_THREAD_ID` (the thread outlives a resumed session), else the session id. Pi sets `PI_SESSION_FILE` on every bash call and not on itself, and a Pi under T3 can inherit one `T3CODE_THREAD_ID` for many sessions, so Pi's own session file is the marker there. Anything a tool call starts inherits the markers (`ssh -f` tunnels, `nohup`, run-and-wake jobs, test servers, Chrome with a debug port).
- With no marker (a plain terminal, Codex) it refuses with exit 2 and says to kill the exact PID; it does not guess. It never signals itself or its ancestors. Linux only: on macOS it refuses and points at `kill <pid>`.
- Not covered: `pkill -P <pid>` (kill the children of a PID; 9 of 163 refused invocations in the replay set had it). List them with `pgrep -P <pid>` and kill the PIDs.

| Harness | Mechanism | Source | Lands at |
|---|---|---|---|
| Claude Code | PreToolUse hook on Bash, running the classifier | `dot_claude/modify_settings.json.tmpl` (the `ensure_guard` step) | `~/.claude/settings.json` |
| Pi | extension that blocks the `bash` tool call, running the same classifier | `dot_pi/private_agent/extensions/refuse-pattern-kill/` | `~/.pi/agent/extensions/refuse-pattern-kill/` |
| Codex | PreToolUse hook on its Bash tool, running the same classifier, in `~/.codex/hooks.json` (a JSON `modify_` script that appends our group and finds it by exact command, never by a substring); Codex runs a hook only once it is trusted, so `codex_trust_hooks.py` trusts exactly that hook through Codex's own API after every full apply. A rules file is the second layer for the time the hook is untrusted | `dot_codex/modify_hooks.json.tmpl`, `.chezmoitemplates/codex_guard_command`, `run_after_90_codex_hook_trust.sh.tmpl`, `dot_local/user_scripts/executable_codex_trust_hooks.py`, `dot_codex/rules/agent-guard.rules`; `dot_codex/modify_private_config.toml.tmpl` only adds an empty `[hooks.state]` header | `~/.codex/hooks.json`, `~/.codex/rules/agent-guard.rules`, `~/.local/user_scripts/codex_trust_hooks.py` |
| Cursor | preToolUse hook on its Shell tool: `python3 -I "$HOME/.cursor/hooks/shell_guard.py"`, which runs the same classifier with Cursor's payload and answers `{"permission": "deny", "user_message": ..., "agent_message": ...}` on exit 2; otherwise it prints nothing and exits 1 (Cursor: "hook failed, action proceeds"). The entry is added to `~/.cursor/hooks.json` beside the coordinator's own and anyone else's, replaced by its script path so it never doubles, and does not need the coordinator checkout | `dot_cursor/hooks/executable_shell_guard.py`, `dot_cursor/modify_hooks.json.tmpl` | `~/.cursor/hooks/shell_guard.py`, `~/.cursor/hooks.json` |
| shared classifier | command-position parser: sees through quotes, `;`, `&&`, `\|`, `$( )`, `sh -c`, `eval`, wrappers, `find -exec` | `dot_local/share/agent-harness/hooks/refuse_pattern_kill.py` | `~/.local/share/agent-harness/hooks/` |
| bash rules | the eight refusals below, on the classifier's parser; the profile comes from `AGENT_HARNESS_PROFILE`, else the rendered file `profile` beside the script | `dot_local/share/agent-harness/hooks/bash_rules.py`, `profile.tmpl` | `~/.local/share/agent-harness/hooks/` |

Both desktop profiles, macOS and Linux; not Termux. Michael's own terminal, and Pi's own `!` command, are not agent tool calls and are not touched.
It fails open: a missing script, a missing `python3` or an unreadable input lets the command run, so a fault in the guard never stops an agent from working.
The Cursor guard never answers allow. It denies a refused command and otherwise exits 1 with no output, which Cursor treats as "hook failed, action proceeds", so a person's own approval prompts still apply. The reason: `~/.cursor/hooks.json` is user-level, so the guard also runs in a person's own Cursor sessions, and an allow could skip their approval prompts. For Cursor, a missing classifier, a missing `python3` and an error in the guard all let the command run. A missing `shell_guard.py` does not: python exits 2 for a file it cannot open, and Cursor reads exit 2 as a block.
Cursor runs the hook on every Shell call, and a machine that already has the guard from another source runs it twice; both refuse the same commands. Tests: `tests/cursor/test_shell_guard.py` (the rendered hook command fed recorded Cursor payloads), `tests/t3-hook/test_cursor_hooks.py` (the entry beside the others). Proof on the work Mac: `docs/cursor-seat-live-proof.sh`.
A new session picks it up: start a new Claude session, restart Pi, and start a new Codex session (the T3 app-server reads `~/.codex` when it starts a thread).

Claude's hook also covers the Monitor tool (it runs shell commands). Codex's rules alone cannot see a redirect or `&` in the script
(`pkill -f x 2>/dev/null; true` runs; only `||`, `&&`, `;` and `|` of plain words are checked, which a real Codex session showed), which is why the hook is the
main Codex mechanism and the rules the backup. The hook is in its own file because Codex edits `config.toml` itself (it writes the trust of a hook there, and can move
tables and the comments above them), so nothing of ours is cut out of that file; the one thing added to it is an empty `[hooks.state]` header above the managed blocks, so
Codex's trust tables land beside it and never inside the hub block. Trust is checked and re-granted by `run_after_90_codex_hook_trust.sh` on every full apply (a scoped
`chezmoi apply <path>` runs no scripts: then run `~/.local/user_scripts/codex_trust_hooks.py --command "$(cat ~/.local/share/chezmoi/.chezmoitemplates/codex_guard_command)"`,
add `--check` to only look). The hook command text is frozen, so its trust (kept by Codex under a key made of the file and the position) is lost only if its position changes: another group inserted above ours in `hooks.json` (the owner's,
or one Codex imports) leaves ours untrusted, and so skipped, until the next full apply.

### The eight bash rules

The same hook, no new entries. Each refusal names its fix, and every message says "refused in agent sessions" (the Pi extension looks for it). The first two and the git rule run on both
desktop profiles; the other four only on `personal` (a missing or unreadable `profile` file turns them off too); the docker rule also needs a Linux host. Any error inside them allows the command.

| Rule | Refuses | Fix it names |
|---|---|---|
| sleep-poll | a `while` or `until` loop that runs `sleep`. Not `for` loops, `while read` loops, a lone `sleep`, or anything under `run-and-wake`. Skipped for Claude's Monitor tool | `run-and-wake -- <cmd>`, then end the turn |
| heredoc | an unquoted heredoc delimiter (`<<EOF`) with an unescaped backtick in the body, in any command and also inside `$( )` | `<<'EOF'` |
| kube context (personal) | kubectl, helm, k9s, kubectx on a context other than `kubernetes-admin@kubernetes`: a `--context` / `--kube-context` flag, `kubectl config use-context`, `kubectx X`, or no flag while the current context is another (read from `--kubeconfig F`, else an inline `KUBECONFIG=`, else the hook's `KUBECONFIG`, else `~/.kube/config`). `--kubeconfig F` with no such file is refused unless `--context` names the homelab. No kubeconfig or no current-context is allowed | `--context kubernetes-admin@kubernetes`; the homelab grant (playbook f90b9301) covers only that cluster |
| merge (personal) | `gh pr merge` unless both gates in their real form come earlier in the same `&&` list (any order): `ci-main-status --merge-gate <repo> [--pr N]` (a bare one or `--tip` does not count) and `pr-body-check <repo> <pr>` with `<pr>` the PR that `gh pr merge` names (`pr-body-check --body-file F` does not count); always for cartwmic/coordinator (`-R`, else the git origin of the directory it runs in) | `merge-pr.sh PR` for the coordinator (it runs both checks); `ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr> --match-head-commit <head sha> ...` for others (`--match-head-commit` makes the merge refuse if the PR head moved since the checks) (`--merge-gate`: UNTESTED exits 0, RED 1, and `--pr <pr>` after it passes a red main for the PR that fixes it when that PR's own full-suite run on its head tree passed, a workflow_dispatch run for agent-kit since its pull_request run skips `npm test`; `pr-body-check` enforces playbook rules ecd63156, 385acc43 and ccc6c94b); `loop_engine_bump.py` / `agent_kit_bump.py` for pin bumps (they pass `--pr N`: for dotfiles, `--pr N` first tries the pin rule: a main red on the release-pins step alone passes when PR N is exactly the pin fix and its own run passed that step; any other dotfiles red gets the general rule above); the playbook CLI with `--pr --merge` |
| PR body (personal) | `gh pr create`, and `gh pr edit` when it sets a body, unless the body comes from `--body-file F` (or `-F F`) and `pr-body-check --body-file F` with the same F comes earlier in the same `&&` list, and F is a mktemp name: `F=$(mktemp /tmp/pr-N-body.XXXXXX)` in the same command, or the literal name mktemp made (last dot-part 6+ letters and digits with a digit or capital). For `gh pr edit N` the name must contain N. Also refused: an inline `--body` / `-b`, `--fill`, a create with no body flag, `-F -`, a different file, a fixed name such as `/tmp/pr-body.md` (another session can overwrite it), a `$VAR` the command does not set from `mktemp`. `gh pr edit` with no body flag (title, labels) passes. No repo is exempt (merge-pr.sh runs its checks at merge, not at create) | `F=$(mktemp /tmp/pr-N-body.XXXXXX)` ... `pr-body-check --body-file "$F" && gh pr create ... --body-file "$F"` (one command); a design-principles Result cell must start with pass, fail or n/a. Without this a cell such as `partial` is found only at merge |
| local docker (personal, Linux) | `docker run`, `docker build` and `docker compose up`, and their spellings: `docker container run`, `docker image build`, `docker buildx build`, `docker builder build`, `docker-compose up`, global options before the subcommand (`docker -H x run`, `docker compose -f f.yml up`), after `sudo`, `env`, `timeout`, `run-and-wake`, in `bash -c`, after `&&`, `;`, `||`, `|`, in `$( )`. Read-only commands (`docker ps`, `images`, `inspect`, `manifest inspect`, `compose ps`, `buildx ls`) pass, and so does anything after `kgate`. The personal Mac is not touched: it has Docker Desktop for agents on purpose (`docs/agent-docker.md`) | `run-and-wake -- kgate -- <cmd>`, or a throwaway namespace on the homelab cluster under ledger grant 21 (create it, run the job, delete it) |
| git in the live coordinator checkout (both profiles) | git that changes the working tree, index, HEAD or a branch in `~/git/coordinator` (the checkout the coordinator daemon runs from; `$HOME` is the hook's own): `merge` (except `--abort` and `--ff-only <sha>`, 7 to 40 hex), `pull`, `reset` (except `--keep <sha>`, the documented rollback), `checkout`, `switch`, `restore`, `commit`, `rebase`, `cherry-pick`, `revert`, `stash` (except `list`, `show`), `clean`, `am`, `apply`, `add`, `rm`, `mv`, `update-ref`, `symbolic-ref`, `branch` (when it creates, deletes, renames or sets one), and `gh pr checkout` / `gh pr co` (which fetches and checks out in the directory it runs in). Found through `cd` / `pushd` (`~`, `$HOME`, `${HOME}`, absolute, relative), `git -C`, `--git-dir`, `--work-tree`, `GIT_DIR`, `GIT_WORK_TREE`, and a session whose own directory is the live checkout. Read-only git, `fetch`, `worktree add/remove/prune/list`, `git show origin/main:<path>` (the main-run start) pass, and so does every other directory | `git worktree add ~/tmp-home/<name> origin/main`; only fetch and the deploy's `git merge --ff-only <sha>` are allowed in the live checkout; coordinator AGENTS.md, "The live checkout" |
| credential config (both profiles) | a reader (`cat`, `head`, `tail`, `less`, `bat`, `grep`, `sed`, `awk`, `cut`, `sort`, `strings`, `jq`, `yq`, ...) given credential config as an argument or `<` input. Credential config is a path list, decided in the code (`CREDENTIAL_PATHS`), not content sniffing: RustDesk's config directory and `RustDesk*.toml`, `rclone.conf`, `.env` and `.env.*` (not `.example`, `.sample`, `.template`, `.dist`) and `*.env`, `.netrc`, `.git-credentials`, `.pgpass`, `.my.cnf`, `.npmrc`, `.pypirc`, `.aws/credentials`, `.docker/config.json`, gh's `hosts.yml`, `credentials` and `secrets` files, the 1Password service-account token. A relative path counts through the command's directory (`cd`). Only a file the command reads counts: a grep or rg pattern, a jq or yq filter, a sed or awk script and a `>` or `>>` target do not; a `<` input does. Also refused, on any input: a sed, perl, awk or PowerShell `-replace` substitution whose pattern names a secret word (password, key, token, salt, secret, ...) and whose replacement is a mask (`<hidden>`, `***`). Not refused: the reader, `grep -l/-L/-c/-q`, `sed -i`, `ls`, `stat`, `wc`, `cp`, `rm`, a path in a heredoc body or an `echo`. Where a name is not on the list the hook cannot see it: add it to `CREDENTIAL_PATHS` | `~/.local/share/agent-harness/bin/config-show FILE [--show KEY]` (see "Config reader") |

Gaps, left as they are: for the credential rule, a file whose name is not on the list, a reader not on its list, `python -c` or a script that opens the file, `xargs cat`, and a command in an `ssh '...'` string; the sign-in code leak (decision #2330) is not covered, because a code reaches the transcript through a browser page or a message tool, not a file or a shell command, so the hook has nothing to match (its fix is the code relay and the output backstop in that decision); commands built at run time (for the git rule also an alias, `git -c alias.x=...`, a script file and a `cd` target in a shell variable other than `$HOME`; a `cd` inside `( )` still counts for the commands after the `)`, so they can be refused wrongly; a worktree nested inside `~/git/coordinator` counts as the live checkout; Pi sends no directory, so there the hook's own working directory decides), a kubeconfig path or `cd` target that holds a shell variable (`--kubeconfig $tmp` is allowed), kubectl inside an `ssh '...'` string, a `sleep` inside `$( )` in a loop body, and `$( )` (not only backticks) in an unquoted heredoc.

What is not covered (each is named in the code or the tests):
- the word as an argument is fine (`grep pkill x`, a commit message that mentions it): only the command position counts;
- a wrapper with an option the classifier does not know (`sudo --some-new-option arg pkill x`) hides the command from it; the option tables cover sudo, env, xargs, timeout, nice, watch, script and the other listed wrappers, including clustered short options (`sudo -iu root`) and long ones;
- a command built at run time (`$cmd`, `$'pkill'`), a script file, `python -c`, `echo 'pkill x' | sh` and `sh <<< 'pkill x'`, an unquoted heredoc whose body is `$(pkill x)`, `fish -c`, osascript, and `kill $(pgrep -f x)` (a pgrep-fed kill is not a `pkill`);
- while the Codex hook is untrusted, the rules file cannot see inside `sh -c '...'`, a redirect or `&`, nor a wrapper with options first (`sudo -u root pkill x`);
- Pi foreground `pi-subagents` children are launched with extension discovery off, so they do not load the extension.

### Config reader

`config-show FILE [--format toml|ini|json|yaml|env] [--show KEY ...]` (source `bin/executable_config-show`, deployed to `~/.local/share/agent-harness/bin/config-show`, on both profiles) parses a config file and prints one `key.path = <masked>` line per leaf, every value masked whole (a list of plain values is one `<masked list>` line). It is what the credential rule's refusal points to. `--show` names a key known to be safe: a dotted path (`options.view_style`) or a bare key name; its value, or everything under a table, prints. The format comes from the file name (`.toml`, `.json`, `.yaml`/`.yml`, `.ini`/`.conf`/`.cfg`, otherwise KEY=VALUE) or `--format`. Parse errors give the line and never the text. Python 3 only; without PyYAML it reads YAML keys by indentation, and without `tomllib` (Python before 3.11) it reads TOML keys line by line, masking the same way. Tests: `tests/config-show`, and the refusals in `tests/agent-kill-guard/test_bash_rules.py` (`Credential`, and the recorded RustDesk commands in `fixtures/credential-*.json`).

Tests: `tests/agent-kill-guard` (classifier, `test_kill_mine.py` (fake sessions A and B, the caller, harness processes, and a replay of real refused commands),  `test_bash_rules.py`, `run_fixture.py` with recorded tool calls in `fixtures/`, Claude settings on both profiles, the Codex hook block and its trust step against a real `codex app-server`, Codex rules with Codex's own `execpolicy check`, deploy per profile) and
`node --test dot_pi/private_agent/extensions/refuse-pattern-kill/index.test.ts`. Proof in a real session of each harness: the PR description.

## Builder Stop hook

A builder started a run-and-wake or kgate job, ended its session and handed off while the job still ran, so nobody read the result (Retro proposal 12, playbook rule 19e13f7b; alert-steward builders A and B1). The builder seat now refuses to stop while such a job is running.

| Piece | Source | Lands at |
|---|---|---|
| Stop hook entry, builder seat file only | `.chezmoitemplates/fleet_seat` (`seat-builder.json.tmpl` calls it) | `~/.claude/fleet/seat-builder.json`, read when a builder session starts |
| The check | `dot_local/share/agent-harness/hooks/stop_running_jobs.py` | `~/.local/share/agent-harness/hooks/` |
| The job's thread, recorded by kgate | `dot_local/bin/executable_kgate.tmpl` (`thread` in the `active/<id>.json` entry) | `~/.local/bin/kgate` |

How it decides: the hook exits 2 (Claude keeps going and is told why) when a job whose recorded thread equals `T3CODE_THREAD_ID` is still running. It names each job, the command, a no-poll way to wait (for a run-and-wake job `run-and-wake --wait <job>`, which prints the result and makes the job's own wake message be dropped instead of arriving as a no-news turn; for a kgate job with no run-and-wake wrapper `tail --pid=<pid> -f /dev/null` on Linux or `caffeinate -w <pid>` on macOS, since BSD tail has no `--pid`; each in a background Bash call, then `t3_background_wait`) and where the result is. Sources: run-and-wake's `start` record already holds `thread`; the job counts while there is no `end` record, the boot is the same, the pid is alive and (Linux) the process carries `RUN_AND_WAKE_JOB=<job>`, so a recycled pid is not taken for it. kgate's registry had no thread, so `kgate` now writes `thread` in the entry (the smallest change; run-and-wake's wrapper and kgate's own client both inherit `T3CODE_THREAD_ID`); a kgate job counts while its client pid still has the entry's start time and command in the same pid namespace, the check `kgate cancel` uses. A kgate job run under run-and-wake is listed once, as the run-and-wake job. Another thread's jobs, ended jobs, jobs whose process is gone and entries written before the field existed never block. With no `T3CODE_THREAD_ID` (not a T3 session) or any read error it allows the stop. The unit tests are `tests/stop-running-jobs`.

Profiles: the file and the hook land on both desktop profiles (the seat files do, `docs/profiles.md`), but only a T3 builder session reads the seat file, and the work profile has no T3 settings from this source, so it takes effect on personal. A new builder session picks it up. A job started before the kgate change (no `thread` in its entry) is not counted.

## Agent browser

A logged-in Chrome that agents can drive, with one browser tool on both profiles: **OpenCode Browse** (npm `@opencode/browse`, the `browse` MCP server, skill `using-browse`; macOS and Linux). It is the default browser tool for every agent (Michael, ask 1192 for the personal profile, ask 1215 for the work Mac). It drives the agent Chrome (`agent-chrome`, remote debugging on 127.0.0.1:9333, own profile `~/.local/share/agent-chrome-profile`). `browser-harness`, the earlier tool, is retired on both profiles; `run_onchange_after_91_browse_setup.sh.tmpl` removes what it left on a machine.

### Browse

| Piece | Source | Lands at |
|---|---|---|
| Google Chrome | macOS: `install-google-chrome` task in `dot_config/mise/config.toml` (brew cask). Linux: the homelab repo's `scripts/omarchy-devbox/setup.sh` (google-chrome, aarch64) | macOS `/Applications/Google Chrome.app`; Linux `/usr/bin/google-chrome-stable` |
| Launcher | `dot_local/bin/executable_agent-chrome` | `~/.local/bin/agent-chrome` (`agent-chrome focus URLPART`, below) |
| Login unit (Linux) | `dot_config/systemd/user/agent-chrome.service`, loaded by `run_onchange_after_78_agent_chrome_systemd.sh.tmpl` | `~/.config/systemd/user/agent-chrome.service` |
| Browse pin | `dot_config/mise/conf.d/browse.toml` (`"npm:@opencode/browse" = { version = "0.1.0", allow_low_downloads = true }`; mise's package-age guard refuses a new package without the exception, ledger #3148) | `~/.config/mise/conf.d/browse.toml`; shim `~/.local/share/mise/shims/browse` |
| MCP entry `browse` (`browse mcp`) | `canonical/mcp/servers.json.tmpl` (both profiles, macOS and Linux, not container mode) | Claude (`~/.claude.json`), Codex (`~/.codex/config.toml`), Pi (`~/.pi/agent/mcp.json`) by the adapters. The T3 seat instances (except `seat-computer`, which has its own MCP file) and the coordinator do not load it (`--strict-mcp-config`): a seat that needs a browser hands the job to the Computer use seat (`seat-computer`) |
| Setup | `run_onchange_after_91_browse_setup.sh.tmpl` | runs on apply when the pin changes: `browse update --mode off`, removes `~/.local/bin/browse` and the browser-harness leftovers |
| Download helper | `dot_local/bin/executable_agent-download` | `~/.local/bin/agent-download` |
| Sign-in helper (personal only) | `dot_local/bin/executable_agent-login` | `~/.local/bin/agent-login` |
| Skill | `canonical/skills/using-browse/SKILL.md.tmpl` (one file; the intro, the start step and the outside-the-page steps branch on profile and OS) | `~/.claude/skills`, `~/.codex/skills`, Pi |

How it works: `browse mcp` is a stdio proxy that starts a relay (`127.0.0.1:19988`; the next free port from 19990) when a client connects. The relay exits after 30 minutes without use and restores saved agent tabs when it starts again. Several agents share one relay and each sees only the tabs it opened. There is no systemd unit for the relay (ledger #3123): the product owns that lifecycle. Logs: `~/.local/state/browse/logs/relay.log`. Config and state: `~/.config/browse`, `~/.local/share/browse` (`relay-token`, `browser-tokens.json`), `~/.local/state/browse`; none of it is in git.

**Pin and updates.** The relay checks for updates hourly and, for an npm install, runs `npm install -g`, which fights the pin, so the setup script runs `browse update --mode off` (saved under `~/.local/state/browse`, survives a relay restart). Bump: change the version in `conf.d/browse.toml`, apply, restart agent sessions (an MCP server started before an update cannot talk to a newer relay). The Web Store extension updates itself and cannot be pinned.

**Do not run `browse install`.** It writes a second, self-updating binary to `~/.local/bin/browse`, ahead of the mise shim on PATH, which defeats the pin. Pairing needs only `browse pair`. The setup script deletes that copy if it is there.

**Pair Browse (once per machine and Chrome profile).** The extension (id `mfnicocicmmlkpjnaffgihfjhdgjkdjg`, Chrome Web Store) is installed in the agent Chrome by hand; a Chrome restart does not unpair it. Proven 2026-11-16 (observed, not scripted: a script that fills the extension page is not worth it for a once-per-machine step):
1. Start the agent Chrome (`agent-chrome`), check `curl -s 127.0.0.1:9333/json/version`, and check `browse --version` prints the pinned version.
2. Open `chrome-extension://mfnicocicmmlkpjnaffgihfjhdgjkdjg/settings.html` in the agent Chrome (`curl -s -X PUT "http://127.0.0.1:9333/json/new?chrome-extension://mfnicocicmmlkpjnaffgihfjhdgjkdjg/settings.html"`), then `agent-chrome focus mfnicocicmmlkpjnaffgihfjhdgjkdjg` and `agent-desktop focus google-chrome` (on a Mac: `agent-desktop focus "Google Chrome"`, then the front-app check from "On a Mac" below; send no click or typing unless it passes). Click **Pair with a code**; it expands the advanced settings. Keep the default relay address.
3. Run `browse pair --wait-seconds 180` with its output in a private file (`f=$(mktemp); chmod 600 "$f"; browse pair --wait-seconds 180 >"$f" 2>&1 &`). It prints a one-time code valid 10 minutes. Type the code from that file into **Pairing code** and click **Connect** (screen input through `agent-desktop`, one agent at a time), then delete the file. Do not print the code.
4. Check `browse status` (Extension: connected, a browser id), `browse pair --list` and `browse tabs`. Close only tabs you opened. `browse pair --revoke <browser>` unpairs; a wiped profile or a replaced machine repeats these steps. The page cannot be driven by Browse itself (it refuses other extensions' pages), hence the screen input.

**Downloads: `agent-download`.** Browse has no download tool. Chrome puts a click's download in its default folder (`xdg-user-dir DOWNLOAD`, else `~/Downloads`; override `--dir DIR` or `AGENT_DOWNLOAD_DIR`) with no prompt (proven 2026-11-16: a Browse click on GitHub's Download ZIP landed the file, found 1.62 s after the click). `mark=$(agent-download mark)` before the click records the folder's files in a handle file under `~/.local/state/agent-download/marks` (one per call, so agents sharing this Chrome do not collide; handles older than a day are deleted); `path=$(agent-download wait --mark "$mark" [--timeout 60])` prints the absolute path of the first completed file that is new or has a changed size (exit 1 on timeout, exit 2 without a readable mark). Completed means a regular, non-hidden file, not `*.crdownload` or `*.part`, with no sibling `NAME.crdownload`, whose size is unchanged over 0.5 s. Timestamps are not used. It polls every 0.2 s. Two downloads in one window can hand the first new file to whichever `wait` asks first; no lock is added. Each call appends one line to `~/.local/state/agent-download/agent-download.log`. Test: `tests/agent-browser/test_download.py`.

**Sign-in: `agent-login`.** Types a login's username, password or one-time code into the field that has focus, without the 1Password extension, so a locked 1Password never needs the master password. `agent-login username|password|otp URLPART [--item ID_OR_TITLE]`: the agent clicks the field with Browse first. It takes the one agent Chrome page whose URL contains `URLPART` (else exit 1 and the matching URLs), finds the Login in vault `developer` with a URL whose hostname is exactly that page's hostname (only the URL's hostname counts: path and query are ignored, and no parent-domain or subdomain matches, rule 8541ec84; none, or several without `--item`, exit 1 naming titles with their ids, never a URL, since a stored URL can carry a token; titles are not unique, so `--item` takes the id), reads the field with `op item get` through the op shim (Connect first, then the service account), and checks over the page's own debug socket that `location.hostname` is still that host and the focused element is an input or textarea (a `type=password` one, for `password`). A value that is empty, ends with a newline or is `op`'s "[use '..." notice (what it prints for a concealed field that was not revealed; the password is read with `--reveal`) is refused before anything is typed; only op's own one trailing newline is stripped from `--otp` output. Only then it calls `Input.insertText`; a failed check types nothing and exits 1 with the reason. After typing it reads back the `value.length` of the element it typed into (held by reference, so a page that moves focus on does not change which one): if it is not the typed length, the field is cleared and the run exits 1, printing only the two lengths (a field that already held text is refused too). A reply from `op` that is not JSON is reported with a fixed message, never quoted. Stdout says only `typed password for <title> on <host>`; the value stays in memory (the op shim's Connect path holds op's output in a shell variable, not a file under `TMPDIR`; `tests/pi-op-shim` checks no file holds it, while the shim runs and after). Each run appends one line (time, run id, outcome, field, host, item title) to `~/.local/state/agent-login/agent-login.log`. Node (global `WebSocket`, Node 22 or later) and the personal profile's op shim and Connect: personal only, left out on the work profile, Termux and container mode. The 1Password extension, where it is installed, can open its own prompt over a focused field and take the focus from it; `agent-login` then refuses ("no input has focus"), and the field has to be clicked again. Test: `tests/agent-browser/test_login_fill.py`.

**The 1Password popup: `agent-desktop`.** Browse cannot see it. Browse opens tabs in the background, so the page's tab is not the active one and Ctrl+Shift+X would open the popup for another tab. `agent-chrome focus URLPART` reads `http://127.0.0.1:9333/json/list`, picks the one page whose URL contains `URLPART` (exit 1 and the list of open pages if none or several), and calls Chrome's `/json/activate/<id>`. It does not raise the window: a floating 1Password desktop window can sit on top, so follow it with `agent-desktop focus google-chrome`, then `agent-desktop key x ctrl shift` opens the popup (on a Mac: `agent-desktop focus "Google Chrome"`, the front-app check, then `agent-desktop key x cmd shift`) (wait about 2 s before the screenshot) and `agent-desktop key Escape` closes it. Proven on this box 2026-11-16; not proven on a Mac. The skill carries this sequence. Test: `tests/agent-browser/test_focus.py`.

**On a Mac (both profiles).** The agent Chrome is Google Chrome (`/Applications/Google Chrome.app`, the `install-google-chrome` task; `AGENT_CHROME_APP` overrides), never Chrome for Testing. There is no login unit, so run `agent-chrome` by hand; it is a child of the shell that ran it, and nothing restarts it. It is a second "Google Chrome" next to Michael's own, so `agent-desktop focus "Google Chrome"` can raise the wrong one: before sending keys, check that the frontmost app's pid (`osascript -l JavaScript -e 'ObjC.import("AppKit"); $.NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier'`) is the agent Chrome's main process, the one whose command line has `--user-data-dir=...agent-chrome-profile` and no `--type=`; if not, send nothing. The extension installs from the Chrome Web Store (a Chrome policy on a managed Mac can block it). The popup shortcut is `agent-desktop key x cmd shift`. `agent-desktop` needs Screen Recording and Accessibility, which are Michael's to grant. A download lands in `~/Downloads` unless a Chrome policy moves it (`--dir` or `AGENT_DOWNLOAD_DIR` then). The skill carries these lines for the Mac.

**Start the browser: `agent-chrome`.** It runs Chrome with `--remote-debugging-port=9333` and its own profile at
`~/.local/share/agent-chrome-profile`, and does nothing if port 9333 already answers. Each run appends its outcome (UTC time, run id, elapsed) to
`~/.local/state/agent-chrome/agent-chrome.log`; Chrome's own output goes to `chrome.log` in the same directory.
On Linux it runs `google-chrome-stable --ozone-platform=wayland`, and when `WAYLAND_DISPLAY` is unset (agent shells under `t3code.service` have none) it takes it from the newest live Hyprland instance (`~/.local/share/agent-desktop/session.sh`, the lookup `~/.zshenv` runs for every agent shell and `agent-desktop` shares). Check by hand on the box: `agent-chrome`, then `curl -s http://127.0.0.1:9333/json/version`.
On Linux the unit `agent-chrome.service` starts the agent Chrome at login (after `graphical-session.target`), so nothing needs starting after a reboot. The unit owns Chrome:
`ExecStartPre` runs `agent-chrome --stop` (ends every Chrome on the agent profile, including one started by hand, and waits for port 9333 to go quiet), then `ExecStart` runs `agent-chrome --foreground` (Chrome as the unit's main process).
So `systemctl --user restart agent-chrome` always ends in a new Chrome process, and `stop` closes it. Check: `systemctl --user status agent-chrome`, `curl -s http://127.0.0.1:9333/json/version`; output: `journalctl --user -u agent-chrome`.
`Restart=on-failure` retries a Chrome that exits with a failure (no display yet, a crash), at most 20 starts in 300 seconds. macOS has no login start yet; run `agent-chrome` by hand. Test: `tests/agent-browser/test_login_unit.py` restarts the real unit file 13 times under the user systemd manager (scratch HOME and port, fake Chrome; `AGENT_CHROME_REAL=1` uses the real Chrome).

The Claude adapter stores a server's `env` with `claude mcp add -e`. When a canonical server entry changes, the Claude adapter compares it with the stored user-scope entry (`~/.claude.json`, or `$CLAUDE_CONFIG_DIR/.claude.json`) and replaces a changed one with `claude mcp remove` then `claude mcp add`; a missing one is added and an unchanged one is left alone, so a stored sign-in survives. A name that left canonical is removed through `RETIRED` in `apply_harness_config.sh` (`browser-harness` is in it). Test: `tests/agent-browser/test_claude_registration.py`.

Tests: `tests/agent-browser`, `tests/mcp-pins`, `tests/pi-mcp-lazy`, `tests/profiles`, `tests/container-mode`, `tests/mise/test_install_google_chrome.py`.

## Add A Canonical Skill

Create a new directory under [`canonical/skills/`](./canonical/skills/) and place a `SKILL.md` file inside it.

Example:

```text
canonical/skills/my-skill/
  SKILL.md
  scripts/
  references/
```

Guidelines:

- Follow the open `SKILL.md` layout directly.
- Keep the skill harness-agnostic where possible.
- Only add extra files that the skill actually needs.
- If a skill comes from an existing library you own, copy the full bundle into `canonical/skills/` so the canonical tree is self-contained.

After adding a skill:

1. Follow [Apply and Verify](#apply-and-verify) to deploy the changed canonical source.
2. Follow [Sync Skills](#sync-skills) with `CHEZMOI_SOURCE_DIR` set to the current worktree; inspect orphan removals before applying.
3. Verify the symlinks exist:
   - `find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l`
   - `find ~/.codex/skills -mindepth 1 -maxdepth 1 -type l`
   - `find ~/.pi/agent/skills -mindepth 1 -maxdepth 1 -type l`

## External Skills

A skill kept in someone else's repository is a chezmoi archive external in
[`.chezmoiexternal.toml`](../../../.chezmoiexternal.toml), pinned by the commit sha in
its URL. It extracts to `~/.local/share/agent-harness/external-skills/<repo>/<skill>/`
(`stripComponents` and `include` keep only the skill directories), and
`apply_harness_config.sh` links every `<repo>/<skill>` with a `SKILL.md` into
Claude, Codex, Pi and `~/.agents`. Canonical skills win a name collision.
`.chezmoiexternal.toml` is hashed into the harness onchange script, so an apply
that changes it re-links.

Current: Accountable Review's `review-map` (wyeworks/accountable-review), both
desktop profiles. To bump it, edit the sha in its URL and apply.

Whole-repo externals also link `<repo>/skills/<skill>`. The private Axon agents playbook is one:
a `git-repo` external (`refreshPeriod = "24h"`, `git pull --ff-only`) on `axon-work-computer` only, and only
when chezmoi data has `axonPlaybook.repo` (see `example.chezmoi.yaml`). The URL stays in local chezmoi data, so
this public repo never names the private repo. Auth is the existing `gh` credential helper. Work-only because the
repo is Axon's private material. On the work profile `dot_claude/modify_settings.json.tmpl` keeps one Claude
SessionStart hook that runs its `bin/playbook-context` (silent when the clone is absent; other profiles remove
only that entry), the Pi `axon-playbook` extension (work profile only) injects the same output once per session, and the `axon-playbook.md` fragment tells Codex, which has no hook, to run it. A new playbook skill is
linked by the next run of `apply_harness_config.sh` (`chezmoi apply` runs it when its inputs change, or run
`~/.local/user_scripts/apply_harness_config.sh skills`).

The coordinator repo's `model-fit` skill is one more link, both desktop profiles: a chezmoi symlink,
`external-skills/coordinator/model-fit`, into `<coordinator checkout>/skills/model-fit`. The checkout is the same value
the instances use (`instances.coordinator.repo` in local chezmoi data, else the profile default; template `instance_repo`).
The linker follows a symlink to a skill directory, so it links like the rest; only `model-fit` is linked, not the
coordinator's other skills. It points into the checkout, so a skill change there is live the moment the checkout updates.

## Retired: Capability Tiers

The tier registry the owner set up on 2026-10-20 was retired on 2026-11-03 and replaced by the seat table in the profile instruction files.

## Import Loop Engine Skills From A Release Tag

The six Loop Engine skill bundles (`using-loop-engine`, `coordinating-loop-engine`, `using-lean-change-provider`,
`using-research-provider`, `using-generate-prd`, `using-policy-document-provider`) come from a release tag of
`cartwmic/loop-engine`. `import_release_skills.py` (source:
[`dot_local/user_scripts/executable_import_release_skills.py`](../../user_scripts/executable_import_release_skills.py),
tests: `tests/release-skills`) imports them into `canonical/skills/` and checks the result. It needs an
authenticated `gh` and writes nothing without `--apply`.

**After a release, one command does the whole bump** (playbook rule 7c57de5a), on the personal profile only:
`~/.local/user_scripts/loop_engine_bump.py vX.Y.Z` (source:
[`dot_local/user_scripts/executable_loop_engine_bump.py`](../../user_scripts/executable_loop_engine_bump.py), tests:
`tests/release-skills`). It imports the tag with `--pins` into a fresh worktree from `origin/main`, opens the PR on
branch `loop-engine-vX.Y.Z`, waits for its checks, squash-merges it, and applies only the PR's targets here: it runs
`chezmoi status` and `diff` on the skills tree and the mise config, stops if anything there differs in a way the PR did
not make, then applies exactly the PR's files, relinks skills with `apply_harness_config.sh skills` (skill links
only; MCP settings are left alone), runs `mise install` for the five tools and `verify-deployed`, and checks that
mise has each version installed and active. It reads the profile with `chezmoi dump-config` and runs every other chezmoi
command with a copy of that config without hooks, so no configured chezmoi hook runs. It prints the PR, the merge SHA and the installed versions, and logs each step to
`~/.local/state/loop-engine-bump/log.jsonl`. A stop names its step (orphans, red checks, drift, another profile); a
rerun resumes the PR, and a version already pinned does nothing. When two releases land close together, put both pins in one
PR, because `scripts/check-release-pins.py` fails any PR while either pin lags and separate bump PRs would block each other:
open this PR, then run `~/.local/user_scripts/agent_kit_bump.py X.Y.Z --pr N` on it, which commits the two agent-kit pin
files there. Each script then applies only its own files from the merged PR and ignores the other's. Orphans stay a
person's call (`--prune` below). It
refuses on any profile but personal and is not deployed on the others: the work Mac takes the merged pins with its own
`chezmoi update`.

By hand, the import alone:

```bash
REPO="$(git rev-parse --show-toplevel)"
TOOL="$REPO/dot_local/user_scripts/executable_import_release_skills.py"
python3 "$TOOL" import vX.Y.Z --source "$REPO" --pins               # preview: per-bundle added/changed/orphan files
python3 "$TOOL" import vX.Y.Z --source "$REPO" --pins --apply        # refuses (exit 3) while orphan files exist
python3 "$TOOL" import vX.Y.Z --source "$REPO" --pins --apply --prune  # after you inspected the orphans
```

- **The tag.** It must be a published, non-prerelease release. The tool resolves it to one commit (printed; pass
  `--expect-commit SHA` to fail if the tag moved), reads every file from that commit's archive, and requires each
  file to match its git blob hash in the commit's tree. This repo's releases are not GitHub-immutable, so the commit
  is the thing to record.
- **The layout** is the one earlier imports used: `skills/<name>/**` or `crates/<crate>/skills/<name>/**` become the
  bundle; a crate's `README.md`, `docs/` and `data/` become `using-<crate>/references/`; `using-loop-engine` also takes
  four named `docs/` files (`ROOT_REFERENCES` in the script). Importing the current tag changes nothing.
- **Orphans** are files in a bundle that the tag no longer has. Other skills in `canonical/skills/` are never touched.
  Files chezmoi would read as attributes (`dot_`, `.tmpl`, a leading dot, and so on) or drop (empty files) stop the import.
- **`--pins`** moves the four `loop-engine`, `lean-change`, `policy-document` and `research` pins in
  `dot_config/mise/config.toml` to the tag's version. The `software-change` pin is gone: v0.30.0
  replaced that provider with lean-change, so new machines do not install it. Copies already installed are kept, and
  runs started on it keep the installed version they name. `mise install` adds the new version and keeps the older ones, so
  runs frozen on an older tool version keep it. Do not `mise uninstall` them to tidy up.
- **Deploy** with the normal flow above: preview the targets, get approval, then
  `chezmoi --source "$REPO" apply ~/.local/share/agent-harness/canonical/skills ~/.config/mise/config.toml` (and
  `mise install` for the pins), then [Sync Skills](#sync-skills).
- **Verify** the result with `python3 ~/.local/user_scripts/import_release_skills.py verify-deployed --source "$REPO"`: the
  deployed bundles must equal the source byte for byte, and each of `~/.claude/skills`, `~/.codex/skills` and
  `~/.pi/agent/skills` must link to the deployed bundle. Files left in a deployed bundle that the source no longer has are
  reported as orphans; `chezmoi apply` does not delete them.

## Add Harness-Specific MCP Secrets

Keep secret-resolution details out of canonical MCP. Put a `${VAR}` placeholder
anywhere in the canonical server definition, including headers, URLs, command
arguments, or environment values. Map that placeholder to 1Password in each
harness adapter that needs it:

- [`adapters/claude/mcp-secrets.json.tmpl`](./adapters/claude/mcp-secrets.json.tmpl)
- [`adapters/codex/mcp-secrets.json.tmpl`](./adapters/codex/mcp-secrets.json.tmpl)
- [`adapters/pi/mcp-secrets.json.tmpl`](./adapters/pi/mcp-secrets.json.tmpl)

Canonical:
```json
{
  "mcpServers": {
    "my-http-server": {
      "type": "http",
      "url": "${MY_SERVER_URL}",
      "headers": {
        "Authorization": "Bearer ${MY_SERVER_API_KEY}"
      }
    }
  }
}
```

Adapter:
```json
{
  "substitutions": {
    "MY_SERVER_URL": {
      "op": "op://developer/my-http-server - url/credential"
    },
    "MY_SERVER_API_KEY": {
      "op": "op://developer/my-http-server - api key/credential"
    }
  }
}
```

The apply script:

1. Reads the canonical server definitions without changing their shape.
2. Reads each adapter's `substitutions`; for every placeholder-to-`op` mapping,
   it resolves the value and exports it for the render step.
3. Recursively substitutes `${VAR}` references anywhere in the resolved JSON.
   The value is **persisted as a literal string** in each harness config so
   harnesses do not need the variable at runtime.
4. If a managed placeholder cannot be resolved from 1Password or the existing
   environment, it omits only the affected server from that render.

Guidelines:

- Keep adapter mappings minimal (`placeholder` + `op`). Keep server shape and
  formatting such as `Bearer ${VAR}` in canonical.
- Use the same placeholder name in canonical and under `substitutions`.
- Gate work-only substitutions with the same chezmoi profile condition as the
  corresponding canonical servers.
- To disable inlining (keep `${VAR}` placeholders in harness configs), set
  `AGENT_HARNESS_INLINE_SECRETS=0` before running the apply script.

## Add A New Domain

A domain is a neutral configuration category such as `skills` or `mcp`.

To add one:

1. Create a new canonical source tree under `canonical/<domain>/`.
2. Extend [`executable_apply_harness_config.sh`](../../user_scripts/executable_apply_harness_config.sh) with:
   - canonical input discovery
   - per-harness projection logic
   - clear logging
3. Add adapter metadata under `adapters/<harness>/` only if needed.
4. Document the new domain in the top-level README and this file.
5. Follow [Apply and Verify](#apply-and-verify) for the changed source.
6. Verify the live harness outputs.

Guidelines:

- Domains should stay neutral and portable.
- Harness-only behavior belongs in the adapter layer.
- If a new domain starts requiring lots of harness-only semantics, revisit whether it should be canonical at all.

## Sync Skills

Use `sync_harness_skills.sh` to compare canonical skills in this worktree
with the deployed location. Its default source is the base chezmoi checkout,
so set `CHEZMOI_SOURCE_DIR` explicitly. chezmoi does the comparing and the
writing (`chezmoi status`, `diff` and `apply` on the skills path), so deployed
files get their target names and rendered contents: `executable_run.sh`
deploys as `run.sh`.

```bash
REPO="$(git rev-parse --show-toplevel)"
CHEZMOI_SOURCE_DIR="$REPO" ~/.local/user_scripts/sync_harness_skills.sh --dry-run
# After reviewing additions and updates with the owner:
CHEZMOI_SOURCE_DIR="$REPO" ~/.local/user_scripts/sync_harness_skills.sh
# Also delete what chezmoi does not manage there (inspect the list first):
CHEZMOI_SOURCE_DIR="$REPO" ~/.local/user_scripts/sync_harness_skills.sh --prune
```

The script also supports `--yes` for an owner-approved unattended run; it
skips the interactive confirmation.

The script detects:
- **Additions**: skills in chezmoi source not yet deployed
- **Updates**: skills whose rendered source differs from the deployed files
- **Not managed**: deployed skill directories no longer in source (orphans)
  and leftover files inside a managed skill (a renamed file, an old raw
  copy). chezmoi never deletes these. The preview always lists them; only
  `--prune` deletes them.

After syncing canonical skills it automatically runs `apply_harness_config.sh` to update symlinks and clean up stale links across all harnesses.
`apply_harness_config.sh skills` does the link step alone, without regenerating any MCP settings.

## Apply And Verify

Canonical changes go through the repo-root [AGENTS.md](../../../AGENTS.md)
apply boundary. Use the current worktree, inspect the dry-run and live targets,
and get owner approval before any real apply. A full apply also runs onchange
scripts; include their effects in that inspection. Use `--force` only after
choosing the source side of a known conflict.

```bash
REPO="$(git rev-parse --show-toplevel)"
chezmoi --source "$REPO" apply --dry-run --verbose
# After reviewing the exact effects and obtaining approval:
chezmoi --source "$REPO" apply
```

For a skill-only change, deploy the canonical source first, then run the
interactive `sync_harness_skills.sh` above with the same worktree source. For
MCP changes, verify each harness's result after apply; Pi writes
`~/.pi/agent/mcp.json` (check it parses privately with `jq empty
~/.pi/agent/mcp.json`). Do not paste rendered secret values into logs.

From the dotfiles source root, `python3 tests/native-mcp/proof.py` checks both
Pi settings profiles and completed native MCP/codemode journeys through the
real CLI, RPC, and TUI. It uses scripted local backends, not live providers or
user credentials.

Useful verification commands:

```bash
claude mcp list
codex mcp list
pi mcp list
find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l | sort
find ~/.codex/skills -mindepth 1 -maxdepth 1 -type l | sort
find ~/.pi/agent/skills -mindepth 1 -maxdepth 1 -type l | sort
```

## Current Canonical Policy

- Canonical MCP should reflect the shared cross-harness set you actually want active.
- Canonical skills should reflect your portable, user-managed skill library.
- Built-in harness skills and vendor-imported skills are not automatically part of the canonical set.
