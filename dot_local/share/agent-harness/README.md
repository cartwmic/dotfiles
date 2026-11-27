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
    bash_rules.py            # the eleven extra refusals it calls (and the door rule, the twelfth, which tells a playbook rule at a command): sleep-poll, heredoc, kube context, merge, PR body, issue body, local docker, heavy jobs in the agent host pod, git stash, git in the live coordinator checkout, credential config
    door.json                # rendered from door.json.tmpl, per profile: the coordinator's renderer command and state directory, read by bash_rules' door rule (see "Door delivery")
    profile                  # rendered from profile.tmpl: just the chezmoi profile name, read by bash_rules
    container                # rendered from container.tmpl: `true` in container mode (the agent host pod), else `false`; read by bash_rules' heavy-job rule
  bin/
    config-show              # prints a config file's keys with every value masked (see "Config reader"); source name executable_config-show
    disposition-check        # refuses a `fixed` review disposition that has neither a sha of the reviewed change nor an artifact reference (findings-contract.md rule 3); the reviewer brief runs it at re-review (source name executable_disposition-check)
    known-limits-check       # fails a PR body whose limits are not under "## Known limits", are untracked, or name a ticket the tracker lookup cannot confirm; a limit accepted as permanent says "accepted as permanent" in the body and has its decision id on the PR agent record's `Permanent limits:` line (`--record FILE`, or `--record-pending` before the record exists); pr-open runs it on every PR body it creates or edits, each run appends a line to its log (`~/.local/state/known-limits-check/log.jsonl`: outcome, and per problem the rule, line and message), and reviewer-brief.md section 1 runs it on the body as filed (source name executable_known-limits-check)
    log-probe                # runs one command in a scratch HOME and fails (exit 1) unless a file the run created or grew there (or in a `--watch` folder) holds a JSON line; stderr, stdout and the exit code do not count (design-principles.md section 14). It is "a new or grown file", not strictly "an appended line": a one-line state file the command writes fresh, or a log it renames, also passes, so the reviewer judges the printed record. The probed command inherits your environment (only HOME and XDG_* move): a variable holding an absolute path such as COORDINATOR_STATE_DIR still points at real state, and `--watch` should name a folder only that command writes to, not the shared agent-traces folder. In a finding's `repro`, match `{"output_contains":"log-probe: FAIL"}`, not `{"exit":"nonzero"}` (exit 2 means the probe could not run). The reviewer brief's logging check runs it on each action and again at re-review. Every run appends a line to `~/.local/state/log-probe/log.jsonl`, its own usage refusals included, and each fail, error or refusal line carries a `reason` (source name executable_log-probe)
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

Current files: [AGENTS.md](./canonical/instructions/AGENTS.md) (the design-principles pointer, scripts vs skills, voice, subagents, which role reads files and which asks the `reader` helper (`dot_claude/agents/reader.md`, Claude only), ownership, decisions and escalation, and the enforcement pyramid (stopgap): which layer to pick when enforcing a rule), [hindsight-guidance.md](./canonical/instructions/hindsight-guidance.md) (in `~/.claude/CLAUDE.md` and the Codex and Pi files; the Claude builder, planner and reviewer seats load it as the `hindsight-memory` skill instead, see `docs/profiles.md` "Agent seat instances"), and [axon-playbook.md](./canonical/instructions/axon-playbook.md) (work profile only: the private playbook's `bin/playbook-context` output arrives at session start from Claude Code's hook and Pi's `axon-playbook` extension, Codex runs it itself, and every harness uses `axon-pr-preflight` before PR actions; each harness template includes it under an `axon-work-computer` gate). [profile-work.md](./canonical/instructions/profile-work.md) (`axon-work-computer` only: never merge or deploy without the owner's explicit approval) and [profile-personal.md](./canonical/instructions/profile-personal.md) (`personal` only: merging and deploying approved work is the agent's to do); each of the three harness templates includes them under a profile gate, and termux gets neither. Both profile files also carry the bar table (which repos are `personal` and which are `shared`; the rule that reads it is in `AGENTS.md`, section "The bar") and the agent seat table (which model runs the coordinator, lead, planner, reviewer, builder and browser-work seats; a rule for agents to read, with no launch helper); the two files differ in the seat table's browser-work row and in the bar table rows.

## Add A Canonical MCP Server

Edit [`canonical/mcp/servers.json.tmpl`](./canonical/mcp/servers.json.tmpl).

Guidelines:

- Keep the definition in standard MCP form.
- Prefer the smallest portable shape that works across harnesses.
- Do not put `op://...` references or other secret manager details in the canonical file.
- Use harness adapter metadata for secrets or harness-only behavior.
- Cursor gets the new server with no step of its own (see [Cursor](#cursor)); a secret goes in the claude adapter's list, which Cursor reuses. Name a server in `canonical/mcp/cursor-exclude.txt` only if it cannot run in Cursor.

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
   - Cursor: `cursor-mcp-login --check` (sign-ins are per folder; see below)

TickTick uses the official server at `https://mcp.ticktick.com` in the personal
and work desktop profiles. Sign in separately on each machine and in each
harness: `pi mcp login ticktick`, `codex mcp login ticktick`, or Claude's `/mcp`
menu. Credentials stay in the harness's local OAuth store, not in canonical
configuration or 1Password adapter metadata. In a running Pi session, use
`/reload` after applying, then `/mcp login ticktick`.

Cursor keeps each MCP sign-in per folder, so a sign-in made from `~` does not reach T3 Cursor children, which start in
another folder. `cursor-mcp-login` signs in for the folder those children use, one server at a time with a timeout, and
prints each server's state as `cursor-agent mcp list` reports it there (`--check` only prints). By default it signs in the
servers that list as `requires_authentication`; `--workspace DIR` picks another folder. T3 runs Cursor sessions in a
long-running process that reads the sign-ins once, so restart T3 after signing in (the command does not do it, and the table shows what is on disk).
Test: `tests/cursor/test_mcp_login.py`.

The `shartifacts` entry is Michael's page server (`https://shartifacts.internal.cartwmic.com/mcp`, Streamable
HTTP, no sign-in). It is on both desktop profiles, like TickTick and Hindsight: Michael asked for the work profile too
(2026-11-13, rule 272f08d0; `docs/profiles.md` records the quote), so it has no row in the coverage table. The commands
`shx-note-image` and `shx-waiting` (`dot_local/share/shx/README.md`) and the canonical skill `using-shartifacts` go with it. Test:
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
| Cursor | `apply_harness_config.sh cursor` (part of `all`) writes `${env:T3CODE_THREAD_ID}`, Cursor's own syntax for an environment variable, and Cursor fills it in from its environment. See [Cursor](#cursor) below. |

## Cursor

Cursor is a first-class harness: what the canonical files hold reaches it on both desktop profiles, with no step of its own.

- **MCP servers.** `apply_harness_config.sh cursor` (run by `all`, so by the apply after any canonical change) writes every server in `canonical/mcp/servers.json.tmpl` into `~/.cursor/mcp.json`, in Cursor's form: a remote server is `url` and `headers`, a local one `command`, `args` and `env`, and an environment variable read at run time is `${env:NAME}`. Secrets resolve the way they do for Claude (the claude adapter's 1Password references are reused, so a secret added for Claude reaches Cursor with no second list); a server whose secret is unavailable is left out, and the rest are written. Entries the script wrote earlier that are no longer canonical are pruned (`generated/cursor/mcp-managed.json`); entries it never wrote, and every other key, are kept; a file that is not a JSON object is left as it is. `jira` on the work profile is one of them, with the same 1Password reference as the other harnesses.
- **Exclusions.** A server that cannot run in Cursor is named, with its reason, in `canonical/mcp/cursor-exclude.txt`. It is empty today.
- **Skills.** Cursor reads `~/.agents/skills` and `~/.cursor/skills` at user level (and `~/.claude/skills` and `~/.codex/skills` only with its third-party setting on; read from the cursor-agent 2026.11.19 bundle). The canonical skills are linked into `~/.agents/skills`, so Cursor has them there; a second link in `~/.cursor/skills` would list each twice.
- **Test.** `tests/cursor/test_parity.py` renders both profiles, runs the real apply step in a scratch HOME and fails when a canonical server is missing from the Cursor file (and not excluded) or a canonical skill is missing from the folders Cursor reads. It runs in the Linux CI (`scripts/ci-linux.sh`, `tests/cursor`). `tests/cursor/test_apply_cursor.py` covers the merge.
- **Instructions.** `dot_cursor/rules/agent-harness.mdc.tmpl` deploys `~/.cursor/rules/agent-harness.mdc`, an always-apply user-level rule (Cursor loads `~/.cursor/rules/*.mdc` for every workspace; read from the cursor-agent 2026.11.19 bundle) that carries the canonical instructions: `AGENTS.md`, the Hindsight guide, and per profile its own file (the work profile also the Axon playbook section), the same set as the Codex block. So the profile's seat table and bar table reach Cursor. The coordinator's own per-workspace `.cursor/rules/coordinator-seat.mdc` is separate and not touched. `test_parity.py` fails when a canonical instruction file's text is missing from the rule, and when a new file appears in `canonical/instructions` that the test does not place.
- Hooks (`~/.cursor/hooks.json`) are separate: see the Shell guard below.

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
| bash rules | the eleven refusals below, on the classifier's parser; the profile comes from `AGENT_HARNESS_PROFILE`, else the rendered file `profile` beside the script; the pod comes from `AGENT_HARNESS_CONTAINER`, else the rendered file `container` | `dot_local/share/agent-harness/hooks/bash_rules.py`, `profile.tmpl`, `container.tmpl` | `~/.local/share/agent-harness/hooks/` |

### Door delivery

A playbook rule with an `**At:**` line that names a shell command (`cmd:gh pr create`, `cmd:kubectl`) is shown to the agent at that command. The classifier's last rule, `door` (`bash_rules.py`), asks the coordinator's renderer
(`hook.ts --door`, in the checkout and state directory named by the rendered `hooks/door.json`) for the rules at the command. A text-only rule is told in one refusal per run: the refusal carries the text, and the same command again passes.
The rules, the seat filter, the once-per-run record and the log line (`door` in the guard log, outcome `told`) are the renderer's. A repo flag straight after `gh` (`gh -R owner/repo pr create`, `--repo`) is dropped before the match, so those forms reach the `gh pr create` door. This file only asks, and only for a command that starts with a prefix in the renderer's index
(`<state>/t3-hook/door-index.json`), so no other command starts node. The run is the harness session id from the hook JSON: `session_id` (Claude Code, Codex), `conversation_id` (Cursor, which names the adapter `cursor`) or the `session_id` and
`adapter: "pi"` the Pi extension adds. With no session id, no `door.json` (the door is off by design), `enabled: false` (`agentHost.removeCoordinatorHook`), no index yet, or a renderer that says nothing, the command runs. A `door.json` or index that is there and broken, and a renderer that exits non-zero, times out (15 s; Pi's extension and the Codex hook wait 20 s for the classifier, Cursor's guard 20 s, so a slow render is logged), prints something unreadable or says on stderr that it failed open, also let the command run and write one `door-failed` line (run, adapter, reason; never the command) to the guard log, so rules that stop arriving can be traced. A command another rule refuses is refused by that rule first.
Both desktop profiles: `door.json.tmpl` renders the personal checkout and state (`~/git/coordinator`, `~/.local/share/coordinator`) or the work ones (`~/coordinator-work`, `~/.local/share/coordinator-work`), the places the Claude hook install uses.
Flags: a rule reads a command's flags only through `normalise` / `gh_command` in `bash_rules.py`, from one table, `FLAG_ROWS` (gh, git, docker, kubectl, grep and its kin, the package managers): every spelling the tool's flag library takes (`--x v`, `--x=v`, `-x v`, `-xv`, `-x=v`, a cluster of short flags, `--` ending the flags) reads the same. The gh rows are the gh wrapper's `FLAGS` rows word for word (a hook cannot import the wrapper; `test_flag_normaliser.py` compares them). A gated command (`gh pr create/edit/merge`, `gh api` on a pulls or issues endpoint, git's merge/reset/branch in the live checkout and any git option before the subcommand there, docker before its subcommand) with a flag its row does not list is refused, and the refusal names the row to extend; an ungated command is left alone. A gh command with a flag before its group (`gh -x pr merge 5`) or, for `gh pr`, between `pr` and the verb (`gh pr -t T edit 5`) is refused whatever the flag is, unless it is `-R owner/repo` / `--repo` (read as before), `-h`/`--help` or `--version`: gh may take the next word as that flag's value, so the verb cannot be told, and the refusal says so. `test_flag_spellings.py` checks that every spelling gives the long form's verdict; the guard in `test_flag_normaliser.py` fails when a function names a flag as a string.

Tests: `tests/agent-kill-guard/test_bash_rules.py` (`DoorDelivery`, with a stub renderer and both profiles' rendered file), `tests/cursor/test_shell_guard.py`, the Pi extension tests.

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

### The eleven bash rules

The same hook, no new entries. Each refusal names its fix, and every message says "refused in agent sessions" (the Pi extension looks for it). The poll, heredoc, stash, git, credential, merge and PR-body rules run on both
desktop profiles (not on any other, such as Termux, for the last two); the kube and docker rules only on `personal` (a missing or unreadable `profile` file turns them off too); the docker rule also needs a Linux host; the heavy-job rule runs only in the agent host pod (the `container` file reads `true`). Any error inside them allows the command. Each refusal is also one JSON line, `{ts, action, rule, tool, cwd, matched}` (`matched` is the command name the rule found in its fixed list, such as `npx vitest` or `npm run test:unit`, else null (for the `gh api` body refusal it is `METHOD endpoint`, and the record adds `reason` and a redacted `command`); never the command text as typed, which can hold a token), in `~/.local/state/agent-harness/guard.jsonl` (`AGENT_HARNESS_GUARD_LOG` overrides the path), so `grep -c '"rule": "heavy"'` counts how often the pod refused a heavy job, and `matched` and `cwd` say which runner and where, so a wrong refusal can be found.

| Rule | Refuses | Fix it names |
|---|---|---|
| sleep-poll | a `while` or `until` loop that runs `sleep`. Not `for` loops, `while read` loops, a lone `sleep`, or anything under `run-and-wake`. Skipped for Claude's Monitor tool | `run-and-wake -- <cmd>`, then end the turn |
| heredoc | an unquoted heredoc delimiter (`<<EOF`) with an unescaped backtick in the body, in any command and also inside `$( )` | `<<'EOF'` |
| kube context (personal) | kubectl, helm, k9s, kubectx on a context other than `kubernetes-admin@kubernetes`: a `--context` / `--kube-context` flag, `kubectl config use-context`, `kubectx X`, or no flag while the current context is another (read from `--kubeconfig F`, else an inline `KUBECONFIG=`, else the hook's `KUBECONFIG`, else `~/.kube/config`). `--kubeconfig F` with no such file is refused unless `--context` names the homelab. No kubeconfig or no current-context is allowed | `--context kubernetes-admin@kubernetes`; the homelab grant (playbook f90b9301) covers only that cluster |
| merge (personal and work) | `gh pr merge` unless both gates in their real form come earlier in the same `&&` list (any order): `ci-main-status --merge-gate <repo> [--pr N]` (a bare one or `--tip` does not count) and `pr-body-check <repo> <pr>` with `<pr>` the PR that `gh pr merge` names (`pr-body-check --body-file F` does not count); always for cartwmic/coordinator and for cartwmic/cartwmic-homelab-v2 (`-R`, else the git origin of the directory it runs in; the homelab refusal comes even before the gates, since the chained form skips its RED-line check) | `merge-pr.sh PR` for the coordinator (it runs both checks); `~/git/cartwmic-homelab-v2/scripts/merge-pr.sh N SHA` for the homelab repo (both checks plus the RED-line check); `ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr> --match-head-commit <head sha> ...` for others (`--match-head-commit` makes the merge refuse if the PR head moved since the checks; a one-time admin merge Michael approved adds `--owner-approved ASK` to `--merge-gate OWNER/REPO --pr N` and to `pr-body-check`, which ask `ledger approves-pr` whether answered ask ASK is Michael's go-ahead for that exact PR, waive only "no required checks" and non-required head runs, and log one line to `coordinator-ci/owner-approved.jsonl`; a red required check still refuses) (`--merge-gate`: UNTESTED exits 0, RED 1, and `--pr <pr>` after it passes a red main for the PR that fixes it when that PR's own full-suite run on its head tree passed, a workflow_dispatch run for agent-kit since its pull_request run skips `npm test`; `pr-body-check` enforces playbook rules ecd63156, 385acc43 and ccc6c94b); `loop_engine_bump.py` / `agent_kit_bump.py` for pin bumps (they pass `--pr N`: for dotfiles, `--pr N` first tries the pin rule: a main red on the release-pins step alone passes when PR N is exactly the pin fix and its own run passed that step; any other dotfiles red gets the general rule above); the playbook CLI with `--pr --merge` |
| PR body (personal and work) | `gh pr create`, and `gh pr edit` when it sets a body, unless the body comes from `--body-file F` (or `-F F`) and `pr-body-check --body-file F` with the same F comes earlier in the same `&&` list (a playbook-only PR passes that check without a principles table when it also gets `--files-file F`, `--pr N [--repo R]` or `--base REF`; the hook reads only `--body-file`), and F is a mktemp name: `F=$(mktemp /tmp/pr-N-body.XXXXXX)` in the same command, or the literal name mktemp made (last dot-part 6+ letters and digits with a digit or capital). For `gh pr edit N` the name must contain N. When the command sets `--title T`, the same `--title T` must be on that check (it reads the title for task ids); one check must have seen both F and T (a check for F and another for T is not enough). An edit with no `--title` needs none. Also refused: an inline `--body` / `-b`, `--fill`, a create with no body flag, `-F -`, a different file, a fixed name such as `/tmp/pr-body.md` (another session can overwrite it), a `$VAR` the command does not set from `mktemp`. `gh pr edit` with no body flag passes when it sets no title (labels, reviewers); a title-only `gh pr edit N --title T` needs the chained check that was given the same T. `gh api` on `repos/<o>/<r>/pulls` or `.../pulls/<n>` that sets `body` (POST/PATCH/PUT with `-f/-F/--field/--raw-field body=...` or `--input`) is refused too, since it skips the check (attached spellings such as `-fbody=x`, `-f=body=x` and `-XPATCH` count; so does a PATCH with a body on `repos/<o>/<r>/issues/<n>`, because a PR is an issue and the hook cannot tell which without a lookup: for an issue use `gh issue edit N --body-file F`); A `gh api` call that sets a `title` (the same endpoints and methods, `-f`/`-F`/`--field`/`--raw-field title=T`, also a PATCH on `issues/<n>`, which can rename a PR) is refused the same way as `gh pr edit --title T`: it needs a `pr-body-check --body-file F --title T` earlier in the same `&&` list, given the same T (every `title` field must have been given); a `-F title=@file` is always refused, since the hook cannot see the text (use `-f title=T`); a call with `--input` is refused as a body already. GET, `.../pulls/<n>/comments`, an issues call that is not a PATCH on a number, and a call with no body or title field pass. Each such refusal also logs `reason` and `command` in the guard log: `reason` says the method, the endpoint kind and whether a body field or `--input` set it, and `command` is rebuilt from the parsed call with every `-f/-F` value redacted (never the body, a title, a header or a token); a title refusal logs the reason `title not given to the check`. No repo is exempt (merge-pr.sh runs its checks at merge, not at create) | `pr-open --title T --body-file F [--draft]` to open, `pr-open --edit N --body-file F` to edit (it checks the body, pushes the branch, opens the PR or PATCHes the body through `gh api`, and prints the URL; any body file name, `-` for stdin); or the chained form `F=$(mktemp /tmp/pr-N-body.XXXXXX)` ... `pr-body-check --body-file "$F" && gh pr create ... --body-file "$F"` (one command); a design-principles Result cell must start with pass, fail or n/a. Without this a cell such as `partial` is found only at merge |
| issue body (personal and work) | `gh issue create` (also `gh issue new`, `gh -R o/r issue create`, and a `gh api` POST on `repos/<o>/<r>/issues`) once the profile's coordinator checkout holds `src/claims/cli.ts`; before that it passes. `gh issue edit`, `comment`, `close`, `view` and `list` pass | `issue-open --title T --body-file F [--repo OWNER/REPO] [--label L]` (F or `-` for stdin): it expands the `{{claim:ID}}` tokens that `claims ran|read|said|none` print, adds the Sources footer and creates the issue; `--dry-run` creates nothing |
| local docker (personal, Linux) | `docker run`, `docker build` and `docker compose up`, and their spellings: `docker container run`, `docker image build`, `docker buildx build`, `docker builder build`, `docker-compose up`, global options before the subcommand (`docker -H x run`, `docker compose -f f.yml up`), after `sudo`, `env`, `timeout`, `run-and-wake`, in `bash -c`, after `&&`, `;`, `||`, `|`, in `$( )`. Read-only commands (`docker ps`, `images`, `inspect`, `manifest inspect`, `compose ps`, `buildx ls`) pass, and so does anything after `kgate`. The personal Mac is not touched: it has Docker Desktop for agents on purpose (`docs/agent-docker.md`) | `run-and-wake -- kgate -- <cmd>`, or a throwaway namespace on the homelab cluster under ledger grant 21 (create it, run the job, delete it) |
| heavy jobs (agent host pod only) | `npm test` / `npm t` / `npm run test*` (and `pnpm`, `yarn`, `bun`, also `yarn workspace <x> test` and `corepack pnpm test`, with a script whose name holds `test`, `vitest`, `journey` or `stress`, except one that starts `typecheck` or `lint`, such as `typecheck:test`), `vitest` (also after `npx`, `bunx`, `pnpx`, `pnpm exec`, `npm exec`, `dlx`, or run as `node node_modules/.bin/vitest`), `python3 scripts/journeys.py` (also `uv run scripts/journeys.py`), `stress` and `stress-ng`, in any of the places the docker rule looks (after `sudo`, `env`, `timeout`, `run-and-wake`, `heavy-gate`, in `sh -c`, after `&&`). The pod is shared by every agent and the coordinator, and heavy jobs run on the cluster (playbook 83fbe006). Not refused: anything after `kgate` (it runs on the cluster), `scripts/kgate-journeys.sh`, typecheck, lint, install, build, runners outside the list (`playwright`, `make test`), `node script.ts`, git. Nowhere else: the Mac, omarchy and the work profile have no `container` file reading `true`, so the rule does nothing there | `run-and-wake -- kgate -- <cmd>`, for example `run-and-wake -- kgate -- npm test`; if GitHub CI runs the same suite on the same commit, read CI instead |
| stash (both profiles) | `git stash` that writes the stash list, in any directory (`git -C <dir>` too): push, save, pop, apply, drop, clear, store, branch, `-q`, a bare `git stash`, and every other form but `list` and `show`. Every worktree of a repo shares one stash list, so a pop from one worktree takes another's work. Read-only `git stash list` and `git stash show` pass. Not covered: a git alias, and a git option the table does not list that takes a separate value | Commit your work in progress on your branch, or make a throwaway worktree for a clean tree: `git worktree add <path> origin/main` |
| git in the live coordinator checkout (both profiles) | git that changes the working tree, index, HEAD or a branch in `~/git/coordinator` or in the profile's own coordinator checkout when that is another path (line 1 of the rendered `coordinator-instance` file: `~/coordinator-work` on work), the checkout the coordinator daemon runs from; `$HOME` is the hook's own: `merge` (except `--abort` and `--ff-only <sha>`, 7 to 40 hex), `pull`, `reset` (except `--keep <sha>`, the documented rollback), `checkout`, `switch`, `restore`, `commit`, `rebase`, `cherry-pick`, `revert`, `clean`, `am`, `apply`, `add`, `rm`, `mv`, `update-ref`, `symbolic-ref`, `branch` (when it creates, deletes, renames or sets one), and `gh pr checkout` / `gh pr co` (which fetches and checks out in the directory it runs in). Found through `cd` / `pushd` (`~`, `$HOME`, `${HOME}`, absolute, relative), `git -C`, `--git-dir`, `--work-tree`, `GIT_DIR`, `GIT_WORK_TREE`, and a session whose own directory is the live checkout. Read-only git, `fetch`, `worktree add/remove/prune/list`, `git show origin/main:<path>` (the main-run start) pass, and so does every other directory | `git worktree add ~/tmp-home/<name> origin/main`; only fetch and the deploy's `git merge --ff-only <sha>` are allowed in the live checkout; coordinator AGENTS.md, "The live checkout" |
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
| `browse` on PATH | `dot_local/bin/executable_browse` | `~/.local/bin/browse`, a wrapper around the mise shim ([browse on PATH](#browse-on-path)) |
| Setup | `run_onchange_after_91_browse_setup.sh.tmpl` | runs on apply when the pin changes: `browse update --mode off` and removes the browser-harness leftovers |
| Pairing helper | `dot_local/bin/executable_agent-browse-setup` | `~/.local/bin/agent-browse-setup` ([Pair Browse](#browse-pair)) |
| Download helper | `dot_local/bin/executable_agent-download` | `~/.local/bin/agent-download` |
| Sign-in helper (personal only) | `dot_local/bin/executable_agent-login` | `~/.local/bin/agent-login` |
| Skill | `canonical/skills/using-browse/SKILL.md.tmpl` (one file; the intro, the start step and the outside-the-page steps branch on profile and OS) | `~/.claude/skills`, `~/.codex/skills`, Pi |

How it works: `browse mcp` is a stdio proxy that starts a relay (`127.0.0.1:19988`; the next free port from 19990) when a client connects. The relay exits after 30 minutes without use and restores saved agent tabs when it starts again. Several agents share one relay and each sees only the tabs it opened. There is no systemd unit for the relay (ledger #3123): the product owns that lifecycle. Logs: `~/.local/state/browse/logs/relay.log`. Config and state: `~/.config/browse`, `~/.local/share/browse` (`relay-token`, `browser-tokens.json`), `~/.local/state/browse`; none of it is in git.

**Pin and updates.** The relay checks for updates hourly and, for an npm install, runs `npm install -g`, which fights the pin, so the setup script runs `browse update --mode off` (saved under `~/.local/state/browse`, survives a relay restart). Bump: change the version in `conf.d/browse.toml`, apply, restart agent sessions (an MCP server started before an update cannot talk to a newer relay). The Web Store extension updates itself and cannot be pinned.

**Do not run `browse install`.** It writes a second, self-updating binary to `~/.local/bin/browse`, over the wrapper below and ahead of the mise shim, which defeats the pin. Pairing needs only `browse pair`. If it was run, the next `chezmoi apply` asks whether to overwrite the changed file (with no terminal it stops with "could not open a new TTY"): answer overwrite, or run `chezmoi apply --force ~/.local/bin/browse`; a first apply over a file chezmoi never wrote replaces it without asking (checked in a scratch HOME). Because it is never run, `browse status` can say `Setup: not installed. Run browse install` and `Updates: not installed in a way that updates` (the work Mac says both; the personal Linux box says `Setup: installed`). Both are expected: ignore them and read the `Extension:` line. The `using-browse` skill tells agents the same.

<a id="browse-on-path"></a>**`browse` on PATH.** mise puts Browse's install directory on PATH only in a shell where mise is activated (`private_dot_zshrc.tmpl`); an agent's `bash -c` has the PATH of whatever started it. On personal Linux that is `t3code.service`, whose drop-in (`dot_config/systemd/user/t3code.service.d/10-path.conf.tmpl`) puts the mise shims on PATH, so `bash -c 'browse --version'` worked there. An agent shell on a Mac starts from zsh with only `~/.zshenv` (`~/.local/bin`, Homebrew) and no mise activation (the coordinatord launchd plists carry the shims, an agent shell does not), so on the work Mac (2026-11-19) `browse` ran only by the shim's full path; this is the `qmd` cause (docs/qmd.md, checked 2026-10-27). `~/.local/bin/browse` (`dot_local/bin/executable_browse`) fixes that: `~/.local/bin` is on PATH in every zsh (`~/.zshenv`), and the wrapper runs the mise shim, which picks the pinned version and puts node on PATH. It is the same fix as `qmd` (docs/qmd.md). In a shell where the shims or mise's directory come before `~/.local/bin` the wrapper is not used; in the others every CLI call goes through it, and the shim and CLI it runs have `BROWSE_PATH_WRAPPER=1` in their environment (the wrapper's last line sets it). A relay that a call through the wrapper starts does not have it: observed 2026-11-19 in a scratch HOME on port 19777, where `browse tabs` through the wrapper started a relay whose `/proc/<pid>/environ` had no `BROWSE_PATH_WRAPPER` and whose command line was the absolute path `.../@opencode/browse-linux-arm64/bin/browse serve`. A shell with no `~/.local/bin` on PATH at all still gets exit 127 (measured: a bare `env -i` bash). If the shim cannot resolve `browse` it would search PATH and find the wrapper again; `BROWSE_PATH_WRAPPER` stops that loop (exit 127 with a hint), as does a missing shim. Both profiles; the work Mac gets it from the apply. Test: `tests/agent-browser/test_wrapper.py`.

<a id="browse-pair"></a>**Pair Browse (once per machine and Chrome profile): `agent-browse-setup`.** Run it, on both profiles. It starts the agent Chrome (`agent-chrome`); runs `browse tabs` (read-only; it starts the relay, and `browse status --json` has no `connected` key while no relay runs), then does nothing more if `browse status --json` says `connected`; checks that the extension is installed (Chrome lists a service worker for `mfnicocicmmlkpjnaffgihfjhdgjkdjg` on `127.0.0.1:9333/json/list`, or its folder with a version and a `manifest.json` is in the agent Chrome profile, `~/.local/share/agent-chrome-profile/Default/Extensions/mfnicocicmmlkpjnaffgihfjhdgjkdjg/<version>/`, the same path on Linux and macOS since `agent-chrome` starts Chrome with that `--user-data-dir`; an idle worker may not be listed) and, if not, opens the Web Store page in the agent Chrome and waits for the install; opens the extension settings page; runs `browse pair --wait-seconds 180` with its output in a 0600 file, `~/.local/state/agent-browse-setup/pairing-code`, that it never prints and removes at the end; and ends with `browse status`. It exits non-zero until `browse status` shows connected, so run it again after a failure. `--wait-seconds N` changes the 180.
Two things are left for a person or an agent, and the helper says exactly which: **click "Add to Chrome", then "Add extension"** on the Web Store page (only when the extension is missing), and **click "Pair with a code", type the code from the file into "Pairing code" and click "Connect"** (screen input through `agent-desktop`, with the focus steps below; one agent at a time). The code file holds the code alone; type it without printing it, `agent-desktop type "$(cat ~/.local/state/agent-browse-setup/pairing-code)"` (after clicking the "Pairing code" field), never `cat` it on its own. An agent's shell shows nothing until the helper ends and the helper waits up to 3 minutes for the human steps, so start it in the background. It checks for a connected Browse for up to 10 seconds first (a paired profile can read as not connected for a few seconds after Chrome starts) and appends one line per outcome, never the code, to `~/.local/state/agent-browse-setup/agent-browse-setup.log`. Not proven: the `Pairing code:` line it reads the code from comes from the binary's strings, not from a `browse pair` run, and no test has run against a real Chrome (so a folder that lingers after an uninstall, or one that appears before the extension has loaded, is not checked). Test: `tests/agent-browser/test_browse_setup_helper.py` (fakes only: a fake Chrome debug port, a fake `browse` and a scratch HOME with a fake extension folder; the Store and settings pages were never opened by a test; every wait is bounded so a regression fails in seconds, and a run that hangs is killed with the processes it started). The by-hand steps it replaces, for when it cannot run, are the next lines. The extension (id `mfnicocicmmlkpjnaffgihfjhdgjkdjg`, Chrome Web Store) is installed in the agent Chrome by hand; a Chrome restart does not unpair it. Proven 2026-11-16 (observed, not scripted: a script that fills the extension page is not worth it for a once-per-machine step):
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
On macOS the launch goes through `open -g -n` (new instance) with `--no-startup-window` (`AGENT_CHROME_LAUNCH_FORM` default `b`), and the first window is created over CDP (`Target.createTarget`, `background: true`) once port 9333 answers. `open -g` alone does not keep Chrome out of the foreground: when its startup window shows, Chrome activates itself in process (chromium issue 40246767). As a fallback for every form, the launcher also watches for a moment after the start and, if the agent Chrome took the front, hands it back to the app instance that was front before — by ASN and pid (`lsappinfo setfront`), since the user's own Chrome and the agent Chrome share a bundle id and a bundle-id hand-back (`open -b`) could raise the wrong one; if that app quit during the launch, the hand-back is skipped. Other `AGENT_CHROME_LAUNCH_FORM` values are `plain` (`open -g -n`), `a` (`open -g -j -n`, hidden launch) and `c` (`a` and `b` together). The window is real, so signing in by hand works (`agent-chrome focus`'s `/json/activate` is the one activation path, on purpose for the 1Password popup). Test: `tests/agent-browser/test_no_focus_steal.py` (macOS only) samples the frontmost app every ~50 ms across a launch and CDP driving and fails on any change; `tests/agent-browser/test_launch_forms.py` is the opt-in probe (`AGENT_CHROME_PROBE=1`) that measures each launch form on a real Mac.

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

pstack's `statechart` (cursor/plugins, pstack/skills/statechart, MIT), personal profile only: it extracts to
`external-skills/pstack/statechart/` and is the guide behind `creating-formal-verification`. The work profile and Termux
get neither (docs/profiles.md): the checker installs Java and a TLA+ jar on first use. To bump it, edit the sha in its
URL and apply; a repo that runs the checker in CI pins the same archive in its own script, so bump that too.

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
`chezmoi status` and `diff` on the skills tree and the mise config (the file chezmoi manages: `~/.config/mise/config.toml`, or on the agent host pod `~/.config/mise/conf.d/container.toml`, which chezmoi renders from the same pins), stops if anything there differs in a way the PR did
not make, then applies exactly the PR's files, relinks skills with `apply_harness_config.sh skills` (skill links
only; MCP settings are left alone), runs `mise install` for the five tools and `verify-deployed`, and checks that
mise has each version installed and active. It reads the profile with `chezmoi dump-config` and runs every other chezmoi
command with a copy of that config without hooks, so no configured chezmoi hook runs. It prints the PR, the merge SHA and the installed versions, and logs each step to
`~/.local/state/loop-engine-bump/log.jsonl`. A stop names its step (orphans, red checks, drift, another profile); a
rerun resumes the PR, and a version already pinned does nothing. When two releases land close together, you can put both pins in one
PR: open this PR, then run `~/.local/user_scripts/agent_kit_bump.py X.Y.Z --pr N` on it, which commits the two agent-kit pin
files there. Each script then applies only its own files from the merged PR and ignores the other's. Separate bump PRs do not
block each other either: `scripts/check-release-pins.py` passes a lagging pin while an open dotfiles PR bumps it to exactly the
latest release, and prints `pending bump #N` for it. Orphans stay a person's call (`--prune` below). It
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
