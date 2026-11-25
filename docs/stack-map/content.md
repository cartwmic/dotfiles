## Start here

This page explains how Michael's agent setup fits together, for a reader who has never seen it. Four code repositories make it up: dotfiles (the setup of his machines and of every agent on them) [[dotfiles:README.md:7|is the **chezmoi source** for one person's machines]], coordinator (the one agent he talks to, and the rules and gates around it) [[coordinator:README.md:3|one agent you talk to in plain words]], agent-kit (shared libraries) [[agent-kit:README.md:3|a set of small TypeScript libraries]] and loop-engine (a tool for durable, step-by-step work) [[loop-engine:README.md:5|stores durable workflow state]]. Read "The one-minute picture" first, then the section for the repo you care about. Each small link after a claim goes to the exact line of source that says it, so you can check it yourself. Every number on the page (versions, counts, models) is read from the files on each repo's main branch, and the commit IDs at the top say which commits those were; if they differ from main today, the page is stale and the generator should be run again.

## The one-minute picture

Picture a small software factory with one front desk.

- **The front desk.** Michael talks to one agent, the coordinator. It brings him only the decisions that are his to make, each as an "ask" with options and a recommendation [[coordinator:README.md:7|an *ask*, with options and a recommendation]].
- **The record.** The coordinator keeps a ledger, a database of asks, decisions, standing permissions (grants), pieces of work in flight (workstreams) and promises to do something later (owed items) [[coordinator:docs/glossary.md:10|kept in SQLite]].
- **The managers.** A piece of work goes to a lead, a long-lived agent that owns one area [[coordinator:docs/glossary.md:31|a long-lived agent that owns one area]]. Leads hand tasks to workers, the agents that do the tasks [[coordinator:docs/glossary.md:32|any agent doing a task for a lead or the coordinator]].
- **The roles.** Each agent holds a seat, a role such as lead, builder or reviewer [[coordinator:docs/glossary.md:30|a role an agent session holds]]. One table says which AI model each seat runs on [[dotfiles:dot_local/share/agent-harness/canonical/instructions/profile-personal.md:11|Each agent seat has a model.]]. Every agent's first instruction names its seat and model, and the coordinator refuses to start an agent whose first instruction omits them [[coordinator:src/t3-hook/launch-check.ts:1|must have a brief whose first line names its seat and model]].
- **The line.** A builder changes the code in its own copy of the repository and opens a pull request (a proposed change). A reviewer, a fresh agent that did not write the change, reads it and does not edit it [[dotfiles:dot_local/share/agent-harness/reviewer-brief.md:3|You review one change in fresh context. You do not edit it.]].
- **The gate.** A merge script runs the final checks and merges only if they pass [[coordinator:scripts/merge-pr.sh:2|Merge one coordinator PR, but only past the red-main freeze]].
- **The shipping dock.** After a batch of merges, a "main run" tests the newest commit [[coordinator:scripts/main-journeys.sh:2|The two journey receipts on the current origin/main tip]]. Only a commit that passed is deployed [[coordinator:scripts/pull-main.sh:7|The pass exists: the ref names a commit the personal main run passed]].

Which repo holds which part:

- **dotfiles** holds the machines and the agents' working environment: instructions, skills, hooks, seat settings and model providers.
- **coordinator** holds the front desk: the daemon, the ledger, the rules, the status page and the merge and deploy gates.
- **agent-kit** holds libraries that the coordinator and other apps share: the inbox, chat, jobs and rule book [[agent-kit:README.md:15|An app passes its own names, state directory and policy to each core]].
- **loop-engine** holds a separate tool that keeps a workflow's state, evidence and history across sessions, and the checker that ties tests to requirements [[loop-engine:README.md:5|retained context, evidence and history]].

Two design rules run through all four. Judgment stays with the agent and mechanism stays in code [[coordinator:AGENTS.md:18|Keep judgment in the agent and mechanism in code]]. And agent configuration is written once, in a "canonical" folder, then projected into each tool by thin adapters [[dotfiles:dot_local/share/agent-harness/README.md:3|thin per-harness adapters]].

## What each repo is for

### dotfiles

This repo is the source that chezmoi (a tool that copies configuration files from a git repo onto a machine) uses to set up Michael's machines. mise (a tool that installs and pins versions of other tools) installs the programs [[dotfiles:README.md:8|mise installs]]. Profiles decide what each machine gets: `personal`, the work Mac (`axon-work-computer`) and the phone (`termux`) [[dotfiles:README.md:9|Profiles (`personal`, `axon-work-computer`, `termux`)]]. A new feature targets both desktop profiles unless its design says why not [[dotfiles:docs/profiles.md:3|A dotfiles feature targets both desktop profiles]].

The part that matters for agents is `agent-harness`, the folder that holds the agents' shared configuration. You would see:

- **Instructions, skills and tool servers, written once.** `canonical/` is the source of truth [[dotfiles:dot_local/share/agent-harness/README.md:48|`canonical/` is the source of truth.]]. A skill is a folder with a `SKILL.md` that teaches an agent a procedure [[dotfiles:dot_local/share/agent-harness/README.md:340|place a `SKILL.md` file inside it]]. An MCP server (a plug-in program that gives an agent extra tools) is one entry in one file [[dotfiles:dot_local/share/agent-harness/README.md:93|Edit [`canonical/mcp/servers.json.tmpl]]. After an apply, Claude Code, Codex, Pi and Cursor (four different coding-agent programs) each get them in their own format; Cursor gets the same files as the others [[dotfiles:dot_local/share/agent-harness/README.md:176|Cursor is a first-class harness]]. On disk, you would see skill links under `~/.claude/skills` [[dotfiles:dot_local/share/agent-harness/README.md:363|find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l]].
- **Hooks.** A hook is a small script that runs before or after an agent action and can refuse it. One example refuses `pkill` and `killall`, so one agent cannot kill another's jobs [[dotfiles:dot_local/share/agent-harness/README.md:187|Agent sessions refuse `pkill` and `killall`]]. Claude Code, Pi, Codex and Cursor each load it their own way, and all run the same checker [[dotfiles:dot_local/share/agent-harness/README.md:14|the pkill/killall classifier that Claude's hook, Codex's hook and Pi's extension run]]. A builder also gets a hook that stops it ending its turn while a job it started is still running [[dotfiles:dot_local/share/agent-harness/README.md:267|## Builder Stop hook]].
- **Seat instances.** T3 (the app that hosts agent threads) lets you define several "provider instances". Dotfiles defines one per seat, with settings such as its context window and whether the advisor tool is on [[dotfiles:dot_t3/private_userdata/modify_settings.json.tmpl:58|One claudeAgent instance per agent seat, so a seat starts with its own settings instead of the default ones.]]. They land in `~/.t3/userdata/settings.json`, and each seat reads its own file under `~/.claude/fleet/` [[dotfiles:dot_t3/private_userdata/modify_settings.json.tmpl:60|--settings <home>/.claude/fleet/seat-<seat>.json]]. The instance name is what a launcher passes to pick a seat [[dotfiles:dot_t3/private_userdata/modify_settings.json.tmpl:65|The instance id is what a caller passes]].
- **Models and providers.** The seat table (which model each seat runs) sits in the instructions file for each profile [[dotfiles:dot_local/share/agent-harness/canonical/instructions/profile-personal.md:9|## Agent seats and models]]; the work profile has its own table [[dotfiles:dot_local/share/agent-harness/canonical/instructions/profile-work.md:6|## Agent seats and models]]. A "provider" is a place a model can be reached. Pi's providers are declared in one file [[dotfiles:dot_pi/private_agent/private_models.json.tmpl:27|"providers": {]], for example `deepseek` on both profiles [[dotfiles:dot_pi/private_agent/private_models.json.tmpl:28|"deepseek": {]] and, on the personal profile only [[dotfiles:dot_pi/private_agent/private_models.json.tmpl:82|{{- if eq .profile "personal" }}]], a home-network gateway called `cliproxy` [[dotfiles:dot_pi/private_agent/private_models.json.tmpl:206|"cliproxy": {]]. On the personal profile, every Claude Code and Codex session goes through that same gateway [[dotfiles:README.md:527|goes through the homelab CLIProxyAPI hub]]. Keys are read from a password manager at run time and are absent from this repo [[dotfiles:README.md:12|Keep secret values outside this tree and read them from]].
- **Setup scripts.** Files named `run_...` at the repo root run after chezmoi copies files. Examples: one bootstraps mise [[dotfiles:run_onchange_after_10_mise_bootstrap.sh.tmpl:2|Chezmoi run_onchange script to bootstrap environment with mise]], one re-applies the agent-harness config when a canonical source changes [[dotfiles:run_onchange_after_20_apply_harness_config.sh.tmpl:3|re-applies the agent-harness config whenever any]], one installs the pinned agent-kit [[dotfiles:run_onchange_after_65_agent_kit_install.sh.tmpl:2|Install the pinned agent-kit (the agent-traces CLI)]], and one sets up the coordinator daemon's service [[dotfiles:run_after_75_instances_reconcile.sh.tmpl:2|Runs on every apply]].
- **Pins.** Versions of the other repos' output are fixed in two places: the Loop Engine tools in the mise config [[dotfiles:dot_config/mise/config.toml:21|Loop Engine publishes independent CLI and provider archives from one release.]] and agent-kit in a small `package.json` [[dotfiles:dot_local/share/agent-kit/package.json:5|Pinned install of the agent-kit traces CLI]]. Two scripts move them: `agent_kit_bump.py` [[dotfiles:dot_local/user_scripts/executable_agent_kit_bump.py:2|Bump the pinned agent-kit]] and `loop_engine_bump.py` [[dotfiles:dot_local/user_scripts/executable_loop_engine_bump.py:2|Bump the Loop Engine pins and skills to a release in one command]].

### coordinator

The coordinator is a program that runs all the time plus an agent session. The agent makes the judgments; code handles storage, delivery and the kill switch [[coordinator:README.md:9|The agent makes the judgments]]. The program is `coordinatord`, the daemon, a Node program (Node runs JavaScript outside a browser) that wires four modules together: an inbox of events, the ledger, outgoing messages (reach) and the playbook [[coordinator:README.md:9|is a Node program that wires four modules together]]. In the live T3 setup the daemon has no pane to supervise, because the coordinator is a thread in T3 itself [[coordinator:src/coordinatord/daemon.ts:1236|there is no Pi pane to supervise]]. You would see these parts:

- **The coordinator itself, in "T3 mode".** On the live setup the coordinator is one Claude thread in T3, and Michael talks to it there [[coordinator:src/t3-coordinator/README.md:3|The coordinator as a Claude thread in T3 Code.]]. The older way runs it in Pi (a coding-agent program) inside Herdr (a terminal-pane manager) with Discord (a chat app); the two are either-or [[coordinator:src/t3-coordinator/README.md:5|Discord and T3 are either-or.]]. In T3 mode there is no Herdr [[coordinator:src/t3-coordinator/README.md:7|## No Herdr in t3 mode]].
- **The ledger.** `ledger open` records an ask, `ledger bearings` lists everything open [[coordinator:README.md:75|List open asks, grants and workstreams]].
- **The playbook.** `playbook.md` holds Michael's standing rules, each with an id and the words he said; only the `playbook` command edits it, one git commit per change [[coordinator:playbook.md:7|Only the `playbook` command edits this file, one git commit per change]]. The kit's rule book briefs agents with them [[agent-kit:README.md:9|a shared file of rules that agents are briefed with]].
- **The dashboard.** The status page shows what Michael needs to decide and what is running [[coordinator:src/coordinatord/status-page.ts:1|what Michael sees (the view, built from the ledger on each load)]]. The daemon serves it locally [[coordinator:docs/deploy.md:86|With `status_page_port` set, the dashboard is on `127.0.0.1`]], and the daemon can hold one outbound link to a separate hub program on the home server, so the page is also reachable at the hub's address [[coordinator:docs/deploy.md:139|so the dashboard is also reachable at the hub's address]].
- **Leads.** A long-lived lead is a T3 thread that the "lead keeper" starts, wakes and relaunches [[coordinator:docs/long-lived-agents.md:14|A long-lived agent is a T3 thread that the lead keeper starts, wakes and relaunches.]]. Each has a type file naming its model, channel and schedules [[coordinator:leads/README.md:3|Each long-lived agent has a type file here]].
- **Journeys and the merge gate.** A journey is a black-box test that drives a real public path to a finished result [[coordinator:docs/glossary.md:25|a black-box test that drives a real public path]]. `merge-pr.sh` refuses a merge unless the checks pass, including a check that each requirement has a journey [[coordinator:scripts/merge-pr.sh:19|runs bookends-check on the PR]]. Heavy jobs run in a pod on a home cluster through `kgate` [[coordinator:kgate.toml:1|kgate profile for the coordinator unit gate]].
- **The kill switch.** `coordinator kill` stops outgoing messages and worker commands [[coordinator:src/coordinatord/cli.ts:6|coordinator kill]].

### agent-kit

agent-kit is a set of small TypeScript libraries (TypeScript is JavaScript with types), most with a command line, for apps that coordinate coding agents. Each does one job: chat and outgoing messages, an event inbox, a rule book, a ranked board, scheduled jobs, watchers and a review log [[agent-kit:README.md:8|an HTTP adapter, and a forwarder]]. The kit holds nothing that belongs to one app; each app passes in its own names and settings [[agent-kit:AGENTS.md:7|The kit holds no value that belongs to one app.]]. It is published as a private package on GitHub Packages (GitHub's package host), and the coordinator pins one exact version [[agent-kit:README.md:23|installed from GitHub Packages at one exact version]]. A push to main releases it once the tests pass [[agent-kit:.github/workflows/publish.yml:1|Publish to GitHub Packages.]]. On Michael's machines it shows up as the `agent-traces` command.

### loop-engine

Loop Engine is a Rust program (`loop-engine`) [[loop-engine:README.md:11|From a source checkout with Rust/Cargo]] that stores a workflow's state and decides which step may come next, while an outside "driver" (an agent or a person) does the work [[loop-engine:README.md:5|stores durable workflow state and evaluates explicit transitions for external drivers]]. It ships separate provider programs for kinds of work: `lean-change` for code changes, `policy-document` for writing and auditing documents, and `research` for investigating claims [[loop-engine:README.md:7|Lean-change delivers code, policy-document drafts or audits documents, and research investigates claims]]. `lean-change` follows the steps explore, approve the intent, plan if hard, implement, verify, review [[loop-engine:crates/lean-change-provider/README.md:6|explore -> intent-approval -> (plan if hard) -> implement -> verify -> review -> end]]; it checks and the driver works [[loop-engine:crates/lean-change-provider/README.md:3|It checks; the driver works.]]. `bookends-check` also lives here [[loop-engine:Cargo.toml:3|"crates/bookends-check",]]; it checks each requirement against a test that cites it [[coordinator:docs/glossary.md:41|a tool that checks each live PRD requirement against a journey that cites it]]. Releases publish ready-made programs [[loop-engine:Cargo.toml:22|workspace.metadata.dist]], and Michael's machines install them through mise [[dotfiles:dot_config/mise/config.toml:75|loop-engine = { version =]].

## How a piece of work moves

```flow
1. Michael | Asks for something in the coordinator's T3 thread | coordinator:src/t3-coordinator/README.md
2. Coordinator | Records the work and any decision it needs in the ledger | coordinator:src/ledger/cli.ts
3. Coordinator | Starts or wakes a lead with a brief that names the seat and model | coordinator:src/t3-hook/launch-check.ts
4. Lead | Plans the change; a lean-change run holds the intent and the checks | loop-engine:crates/lean-change-provider/README.md
5. Builder | Changes the code in its own worktree and runs the unit gate on kgate | coordinator:kgate.toml
6. Builder | Opens a pull request with a plain description and an agent record | coordinator:AGENTS.md
7. Reviewer | A fresh session reviews the change and returns findings | dotfiles:dot_local/share/agent-harness/reviewer-brief.md
8. Lead | Triages each finding on four tests, fixes the real ones | dotfiles:dot_local/share/agent-harness/finding-triage.md
9. Merge gate | Runs every check on the pull request head, then merges | coordinator:scripts/merge-pr.sh
10. Driver | Starts the main run: cluster journeys and Bookends on the new tip | coordinator:scripts/main-journeys.sh
11. Driver | Reads the result; a red main freezes further merges | coordinator:docs/red-main.md
12. Driver | Deploys the passing commit and the daemon restarts itself | coordinator:scripts/pull-main.sh
```

1. **Ask.** Michael writes to the coordinator in its T3 thread.
2. **Record.** The coordinator records the work and any decision it needs from him in the ledger [[coordinator:README.md:43|node --experimental-strip-types src/ledger/cli.ts open]].
3. **Start a lead.** Every agent the coordinator or a lead starts must have a first line naming its seat and model, checked against the seat table that dotfiles deploys [[coordinator:src/t3-hook/launch-check.ts:4|reads the seat table from $HOME/.claude/CLAUDE.md]]. A watcher reports any lead running on the wrong instance or model [[coordinator:src/t3-coordinator/seat-check.ts:1|which active lead threads run on a T3 provider instance or model other than their seat's]].
4. **Plan.** A lead can run the change through lean-change, where the owner approves the intent first and each criterion names a check that can fail [[loop-engine:crates/lean-change-provider/README.md:9|The intent names an executable check for each criterion.]].
5. **Build.** The builder works in its own checkout, one writer per checkout [[coordinator:AGENTS.md:22|One writer owns a checkout at a time.]], and runs the unit gate (install, type check, tests) on a cluster pod through kgate [[coordinator:AGENTS.md:33|run-and-wake -- kgate -- sh -c 'npm ci && npm run typecheck && npm test']]. `run-and-wake` starts a long job and wakes the agent when it ends.
6. **Open the pull request.** The description is for a human reader. The bookkeeping goes in a separate agent record [[coordinator:scripts/merge-pr.sh:13|The bookkeeping a PR carries lives in its agent record]].
7. **Review.** The reviewer works in fresh context and does not edit [[dotfiles:dot_local/share/agent-harness/reviewer-brief.md:3|You review one change in fresh context.]].
8. **Triage.** Whoever acts on findings runs the same four tests on each one, whoever raised it [[dotfiles:dot_local/share/agent-harness/finding-triage.md:3|runs these four tests on every finding]].
9. **Merge gate.** The script refuses unless a review round passed on the head [[coordinator:scripts/merge-pr.sh:17|every PR is refused unless a review round passed on its head]], the kgate unit run passed on exactly that tree [[coordinator:scripts/merge-pr.sh:26|the kgate log must hold an exit-0 unit gate]], and no review thread is open [[coordinator:scripts/merge-pr.sh:21|refuses while a review thread is unresolved]]. Then it merges pinned to the head it checked [[coordinator:scripts/merge-pr.sh:25|gh pr merge --merge --match-head-commit]].
10. **Main run.** Once per batch of merges, two receipts run on the newest tip: every journey on kgate, and Bookends [[coordinator:AGENTS.md:44|The journeys gate is two receipts, both required]]. A pass moves a marker (`refs/ci/main-pass`) to that commit [[coordinator:scripts/main-journeys.sh:16|published as the ref refs/ci/main-pass]].
11. **Result.** On a fail, main is red and the merge script refuses most merges [[coordinator:docs/merging.md:15|main is red and the script refuses]].
12. **Deploy.** `sh scripts/pull-main.sh` moves the live checkout to the passing commit and leaves a newer, untested tip alone [[coordinator:docs/deploy.md:223|the target is the commit the pass ref names, not main's tip]], and the daemon installs and restarts itself [[coordinator:docs/deploy.md:209|the daemon installs and restarts itself]].

The other repos ship differently. agent-kit publishes on a push to main once its tests pass [[agent-kit:.github/workflows/publish.yml:1|A push to main whose package.json version has no v<version> tag releases that version]], then `agent_kit_bump.py` moves the pin in dotfiles. A Loop Engine release is followed by `loop_engine_bump.py`. Both scripts open a pull request, wait for checks, merge, and apply only the changed files [[dotfiles:dot_local/user_scripts/executable_loop_engine_bump.py:2|PR, merge, scoped apply on this machine]]. A dotfiles change reaches a machine when Michael or an agent runs `chezmoi apply`; the docs say to inspect a dry run first [[dotfiles:dot_local/share/agent-harness/README.md:591|chezmoi --source "$REPO" apply --dry-run --verbose]].

## Where do I change X?

| I want to... | Go to | Notes |
|---|---|---|
| Switch a seat's model | In dotfiles, edit the seat table in `dot_local/share/agent-harness/canonical/instructions/profile-personal.md` (work profile: `profile-work.md`) | The table is a rule that agents read [[dotfiles:dot_local/share/agent-harness/canonical/instructions/profile-personal.md:11|This is a rule, not a mechanism]]. Context size and advisor setting per seat are in `dot_t3/private_userdata/modify_settings.json.tmpl` [[dotfiles:dot_t3/private_userdata/modify_settings.json.tmpl:68|seat-builder   window 300000  advisor on]]. |
| Add a skill | Create `canonical/skills/<name>/SKILL.md` under `dot_local/share/agent-harness/`, then apply and sync | [[dotfiles:dot_local/share/agent-harness/README.md:338|## Add A Canonical Skill]] |
| Add a hook | Put the script in `dot_local/share/agent-harness/hooks/` and register it in each tool's own file | Claude: `dot_claude/modify_settings.json.tmpl`; Pi: an extension under `dot_pi/private_agent/extensions/` [[dotfiles:dot_local/share/agent-harness/README.md:199|PreToolUse hook on Bash, running the classifier]] |
| Add an MCP server | Edit `canonical/mcp/servers.json.tmpl`; secrets go in `adapters/<tool>/mcp-secrets.json.tmpl` | [[dotfiles:dot_local/share/agent-harness/README.md:134|If the server needs secrets, add or update adapter metadata]] |
| Bump agent-kit | `python3 ~/.local/user_scripts/agent_kit_bump.py X.Y.Z` for dotfiles; the coordinator's own pin is `package.json` | [[dotfiles:dot_local/user_scripts/executable_agent_kit_bump.py:4|agent_kit_bump.py X.Y.Z]]; [[coordinator:package.json:16|"@cartwmic/agent-kit":]] |
| Bump Loop Engine | `loop_engine_bump.py vX.Y.Z` | [[dotfiles:dot_local/user_scripts/executable_loop_engine_bump.py:4|loop_engine_bump.py vX.Y.Z]] |
| Add a playbook rule | `playbook add` (never hand-edit `playbook.md`) | [[coordinator:playbook.md:8|`playbook add` records a new rule.]] |
| Add a Pi provider | Add a key under `providers` in `dot_pi/private_agent/private_models.json.tmpl` | The work provider is added the same way [[dotfiles:dot_pi/private_agent/private_models.json.tmpl:221|"work-glm":]] |
| Change a schedule | Agent work: `coordinator jobs`, which needs an approval row; system jobs: a dotfiles run script plus a row | [[coordinator:src/coordinatord/cli.ts:117|the kit's jobs on the lead keeper's store, with the schedule gate]]; `coordinator schedules check` fails a schedule with no row [[coordinator:src/coordinatord/cli.ts:20|coordinator schedules]] |
| Change what the dashboard shows | `src/coordinatord/status-page*.ts` for the page; `src/dashboard-hub/` for the hub | [[coordinator:src/coordinatord/status-page.ts:1|The status page's logic]] |

## Glossary

- **seat**: a role an agent session holds, such as coordinator, lead, planner, builder, reviewer, scout (read-only reader) or computer use (drives a browser and screen).
- **dotfiles**: the repo that sets up Michael's machines and the agents on them.
- **coordinator**: the agent Michael talks to, plus the daemon around it.
- **daemon (`coordinatord`)**: the program that runs the coordinator all the time.
- **lead**: a long-lived agent that owns one area or one piece of work.
- **builder, reviewer, planner**: seats for the agent that writes a change, the fresh agent that checks it, and the agent that designs it. Each runs on the model its row of the seat table names.
- **driver**: the agent session that merges pull requests and starts the main run.
- **ledger**: the coordinator's record of asks, decisions, grants, workstreams and owed items.
- **worker**: any agent doing a task for a lead or the coordinator.
- **lead keeper**: coordinator code that starts, wakes and relaunches long-lived agents [[coordinator:docs/long-lived-agents.md:9|coordinator code that starts, wakes and relaunches long-lived agents]].
- **hub**: a separate program on the home server that serves the dashboard at its own address.
- **owed item**: a recorded promise to do or check something later [[coordinator:docs/glossary.md:15|a recorded promise to do or check something later]].
- **inbox, reach**: the coordinator's queue of incoming events, and its module for sending chat messages out; both come from agent-kit [[coordinator:docs/glossary.md:19|the ordered queue of events]].
- **unit gate**: install, type check and run the tests for a repo, on kgate [[coordinator:kgate.toml:1|kgate profile for the coordinator unit gate]].
- **receipt**: one recorded pass or fail from a gate, such as the cluster journeys or Bookends.
- **SQLite**: a database kept in a single file.
- **ask**: a decision put to Michael, with options and a recommendation.
- **door**: whether a decision can be undone; a one-way door cannot.
- **grant**: a standing permission from Michael that lets agents act without asking again.
- **decision**: a choice an agent made, recorded with its reason.
- **workstream**: one piece of work the coordinator tracks, with a purpose, a state and its asks.
- **playbook**: Michael's standing rules for agents, one entry each, with the words he said.
- **kill switch**: a file that, when present, stops outgoing messages and worker commands.
- **state directory**: the folder where the coordinator keeps its ledger, config and generated command wrappers; `pane-bin` is the folder of those wrappers.
- **dashboard**: the status page that shows Michael what needs him; a separate hub program makes it reachable at another address.
- **journey**: a black-box test that drives a real public path to a finished outcome.
- **main run**: the journey receipts, run on the main branch once per batch of merges; a red result freezes merges.
- **merge gate**: the script, `scripts/merge-pr.sh`, that runs every check and then merges.
- **red main**: main has a failing main run, so most merges are refused until it is fixed.
- **flake**: a test that fails at random. The merge script has a flag to merge past a named, ruled flake [[coordinator:scripts/merge-pr.sh:3|--flake-only NAME]].
- **pull-main**: the script that deploys the passing commit to a coordinator.
- **agent host**: the pod (a container group) on Michael's home cluster where the coordinator daemon, T3 and the agent sessions run.
- **agent record**: the file beside a pull request that holds its bookkeeping, kept out of the PR description.
- **worktree**: a second checkout of the same repository, so one agent can work without disturbing another.
- **PR**: a pull request, a proposed change to a repo.
- **kgate**: Michael's tool that runs a job in a pod on his Kubernetes cluster (a system that runs containers) [[coordinator:docs/glossary.md:42|the owner's tool for running a job in a pod]].
- **run-and-wake**: starts a long job and wakes the agent when it ends, so the agent does not poll [[coordinator:AGENTS.md:46|`run-and-wake` returns at once]].
- **Bookends**: a tool that checks each live requirement against a journey that cites it.
- **PRD**: the product requirements document, the coordinator's enduring list of requirements.
- **T3**: the coding-agent app that hosts agent threads [[coordinator:docs/glossary.md:38|the coding-agent app that hosts agent threads]].
- **instance**: in T3, one named provider setup; each seat has one.
- **Pi**: a coding-agent program the coordinator can run in, with its own model providers [[coordinator:docs/glossary.md:40|the coding-agent harness the `pi` runtime runs]].
- **Claude Code, Codex, Cursor**: three more coding-agent programs that dotfiles configures alongside Pi.
- **Herdr**: a terminal-pane manager used in the older Pi mode [[coordinator:docs/glossary.md:39|a terminal-pane manager]].
- **Discord, Matrix**: chat apps the coordinator can talk through; the work coordinator uses Matrix.
- **MCP server**: a plug-in program that gives an agent extra tools.
- **skill**: a folder with a `SKILL.md` that teaches an agent one procedure.
- **hook**: a script that runs before or after an agent action and can refuse it.
- **harness**: a coding-agent program together with its configuration; this page uses it for Claude Code, Codex, Pi and Cursor.
- **canonical**: the one source copy of a skill, instruction or MCP entry.
- **adapter**: the thin piece that turns a canonical file into one tool's format.
- **advisor**: an extra agent tool that a session can ask for a second opinion [[dotfiles:dot_t3/private_userdata/modify_settings.json.tmpl:73|The builder's advisor runs on]].
- **profile**: which kind of machine this is: personal, work Mac or phone.
- **chezmoi**: copies config files from a git repo onto a machine.
- **mise**: installs and pins versions of command-line tools.
- **CLIProxy**: Michael's gateway on his home network that Claude Code and Codex sessions go through.
- **Hindsight**: the memory service agents recall from and save to [[coordinator:docs/glossary.md:43|the durable memory service]].
- **shartifacts**: Michael's own page server where agents publish reports he reads and comments on [[dotfiles:dot_local/share/agent-harness/canonical/skills/using-shartifacts/SKILL.md:8|self-hosted page server]].
- **agent-kit**: the shared library repo.
- **GitHub Packages**: GitHub's host for software packages; the kit is published there.
- **loop-engine**: the repo for the Loop Engine program, its providers and the Bookends checker.
- **Loop Engine**: the durable workflow program.
- **lean-change**: the Loop Engine provider for software changes [[loop-engine:crates/lean-change-provider/README.md:3|A small Loop Engine provider for software changes.]].
- **provider** (Pi or Loop Engine): in Pi, a place a model can be reached; in Loop Engine, a program for one kind of work.
- **driver** (Loop Engine): the agent or person who does the work while Loop Engine keeps state.
- **Rust**: the programming language Loop Engine is written in.
