<!-- printed -->
# agent-kit-repo guide

Repo: agent-kit-repo. Commit: f2bb152a1a56ca6cfdb1956d3da8e8bd02348431. Date: 2026-11-20.
Counts: 102 surfaces (entry 11, event 7, env 17, config 1, manifest 1, export 35, doc 11, ci 19); 8 scout names found, 0 not found and dropped; 2686 test cases in 214 files; 14 of 24 named surfaces appear in tests.
Evidence: code and the repo's own words first; tests where the repo has them (A2).
<!-- /printed -->

# Part 1: In plain English

## What it is and who it is for

The README says the kit holds the shared cores that Michael's agent apps are built from. [A3.1]
The README says a core is a library plus, where it has one, a CLI. [A3.2]
The README names the coordinator, dotfiles, kgate and the work instance as users today. [A3.3]
The README says the kit holds no value that belongs to one app. [A3.31]
The package publishes to the GitHub Packages registry. [A3.4]
The README says the API is at 0.x and changes in most releases. [A3.30]

## What you can do

A new reach send reports the number of queued parts. [A4.5]
Text is packed into parts of at most 2000 characters by default. [A4.15]
Reach can also queue reactions. [A4.17]
When a peer message is due, reach posts it to the peer's URL. [A4.26]

The package exports Discord and Matrix adapters as subpaths. [A3.7]
Both adapters give a port with buttons and reactions. [A5.14][A5.33]
The Discord adapter catches up by fetching pages of 100 messages after a given id. [A5.28]

The inbox stores events in a file that it opens. [A3.8]
When the same source and external key were already stored, posting returns the stored id. [A6.3]
The inbox hands out the oldest event that is not yet acked. [A6.7]
After a forwarder send succeeds, it marks those events delivered and acked. [A6.32]

The playbook is a file of entries, each with a rule and sources. [A7.3]
Commands such as add, revise and merge edit those entries. [A7.8][A7.9][A7.10]
When the invariants hold and the text changes, the command makes one commit. [A7.13]
With --pr, an edit opens a pull request. [A7.27]
With --merge, the PR is squash-merged once checks pass. [A7.32]

The board holds lines that you add, rank and mark done. [A8.18][A8.22][A8.25]
Adding a line can take the next BD number. [A8.19]
The build's tracker plug-ins are github, github-project, ticktick and jira. [A8.14]

Jobs are kept in one file. [A3.12]
A job has a schedule or a one-time time. [A9.3][A9.4]
A tick starts a run for a due job unless the job changed or is still running. [A9.13]
A failed scheduled run gets a retry while its attempt number is at most the job's retries. [A9.22]
The command runner starts the program from argv with no shell. [A9.26]

For each target, a sweep reads evidence and asks a judge. [A10.10][A10.12]
A verdict state is progressing, stuck, looping, drifting or unclear. [A10.13]
A judged bad verdict is flagged when its state differs from the last settled verdict. [A10.16]
The default watchdog runs hourly at minute 20 UTC. [A10.8]

A code comment says traces holds the findings types, the review log and the Pi collector. [A3.15]
A finding counts as blocking when its severity is blocking and its obligation, evidence and consequence are non-blank. [A11.10]
The verdict is FAIL when a finding is effectively blocking, else PASS. [A11.13]

## How the parts fit

The kit holds the shared cores that Michael's agent apps are built from. [A3.1]
The reach, playbook and board command lines each start at a run function. [A3.6][A3.9][A3.10]
The package has an interface for a chat. [A3.5]
Reach posts a peer message to a URL ending in /events/agent.<sender>. [A4.26]
The watchdog adds a job with the id watchdog:<name>. [A10.28][A10.29]

## What it needs and keeps

The package needs Node 22.19.0 or newer. [A3.18]
It depends at run time on croner. [A3.19]
The discord.js library is an optional peer. [A3.20]
When the state directory variable is set, the default state directory function returns it. [A3.21]
When it is unset, that function returns a path under ~/.local/share. [A3.22]
The board directory defaults to ~/.local/share/board. [A3.24]
The playbook action log is playbook.jsonl under ~/.local/state. [A7.19]
Unless the host passes a log sink, the jobs command writes jobs.log beside the database. [A9.25]
Traces data lives under AGENT_TRACES_DIR when it is set and non-empty. [A11.6]

## What it does not do

The kit holds no value that belongs to one app. [A3.31]
CONTRACT.md says the watchdog core does not act on a target. [A10.1]
The README says the Matrix adapter has no history and no editMessage. [A3.32]
A code comment says the kit has no default inbox policy. [A3.34]
A checkout on main or master with an origin remote is refused a commit. [A7.15]
The README says the testing subpaths are for tests and journeys. [A3.33]

# Part 2: Appendix: technical detail
## A3 The product as a whole

The README says the kit holds the shared cores that Michael's agent apps are built from. `README.md:5`

The README says a core is a library plus, where it has one, a CLI. `README.md:5`

The README's list of who uses it today names the coordinator, dotfiles, kgate and the work instance. `README.md:30-33`

The package publishes to the GitHub Packages registry. `package.json:135-136`

`ChatPort` is the interface for a chat. `src/chat/port.ts:152`

`runReachCli` is the entry of the reach command. `src/reach/cli.ts:250`

The package exports Discord and Matrix adapters as subpaths. `package.json:39` `package.json:43`

`openInbox` opens the inbox as a SQLite file through `node:sqlite`. `src/inbox/index.ts:3` `src/inbox/index.ts:123` `src/inbox/index.ts:128`

The playbook command line starts at `runPlaybookCli`. `src/playbook/cli.ts:285`

The board opens through `openBoard`, and its command line starts at `runBoardCli`. `src/board/index.ts:132` `src/board/cli.ts:82`

`openJobs` opens the jobs operations. `src/jobs/index.ts:58`

A code comment says the SQLite job store is one file with three tables. `src/jobs/adapters/sqlite-store.ts:1`

The watchdog command line starts at `runWatchdogCli`. `src/watchdog/cli.ts:136`

A code comment says a watchdog host supplies the Targets, Evidence and Sink ports. `src/watchdog/index.ts:1-2`

A code comment says traces holds the findings types, the review log and the Pi collector. `src/traces/index.ts:1`

The `./app` subpath exports `defaultStateDir`. `package.json:127` `src/app.ts:20`

The root export holds two constants, `KIT_NAME` and `KIT_SPIKE`. `src/index.ts:2-3`

The package needs Node 22.19.0 or newer. `package.json:11-12`

It depends at run time on `croner`. `package.json:159-160`

`discord.js` is an optional peer dependency. `package.json:145-150`

When `<envPrefix>_STATE_DIR` is set in the given environment, `defaultStateDir` returns it. `src/app.ts:21`

When it is unset, `defaultStateDir` returns a path under `~/.local/share`, named by `dataDir` or the lower-cased `envPrefix`. `src/app.ts:21`

`loadConfig` reads `config.json` in the board directory when that file exists. `src/board/adapters/config.ts:61-62`

`defaultBoardDir` returns `~/.local/share/board`. `src/board/adapters/config.ts:49-50`

`resolvePlaybookPath` reads `playbook_repo` from `config.json` in the state directory when that file exists. `src/playbook/paths.ts:28` `src/playbook/paths.ts:30-34`

A non-empty string `playbook_repo`, resolved from the state directory, replaces `defaultRepoRoot` as the repository. `src/playbook/paths.ts:31` `src/playbook/paths.ts:38`

A `playbook_repo` that is empty or not a string makes `resolvePlaybookPath` throw. `src/playbook/paths.ts:28` `src/playbook/paths.ts:35-36`

When the repository is still undefined, `resolvePlaybookPath` throws. `src/playbook/paths.ts:28` `src/playbook/paths.ts:41`

When the app passes no peers, `resolvePeers` reads `REACH_PEERS` if it is set. `src/reach/peers.ts:80` `src/reach/peers.ts:86-88`

The README says the API is at 0.x and changes in most releases. `README.md:22`

The README says the kit holds no value that belongs to one app. `README.md:24`

The README says the Matrix adapter has no `history` and no `editMessage`. `README.md:25`

The README says the `testing/*` subpaths are for tests and journeys. `README.md:26`

A code comment says `openInbox` takes its policy from the app, and the kit has no default. `src/inbox/index.ts:122`

## A4 reach

The package exports `./reach` from `dist/reach/index.js` and `./reach/cli` from `dist/reach/cli.js`. `package.json:31-38`

`runReachCli` runs the command in `argv` (default the process arguments) and returns the exit code. `src/reach/cli.ts:251-252`

For a missing or unknown command, `run` prints usage and returns 2. `src/reach/cli.ts:75-78`

`send` and `react` return 2 when `--key` is missing. `src/reach/cli.ts:75` `src/reach/cli.ts:157-160`

Without `--peer`, a new `send` reports the number of queued parts and returns 0. `src/reach/cli.ts:75` `src/reach/cli.ts:211-213`

Without `--peer`, an already queued key makes `send` report the parts' states and return 0. `src/reach/cli.ts:188` `src/reach/cli.ts:215-218`

`send` with both `--text` and `--file` returns 2. `src/reach/cli.ts:75` `src/reach/cli.ts:181-184`

Without `--peer`, `send` reads `--file` as the text and returns 1 if it is missing. `src/reach/cli.ts:188` `src/reach/cli.ts:201` `src/reach/cli.ts:226-229`

Without `--peer`, when the event id variable is set and non-empty, `send` passes it to `enqueue`. `src/reach/cli.ts:75` `src/reach/cli.ts:208-210`

For a new key, `enqueue` adds nothing when `--again` is absent and the event has an unfailed send. `src/reach/outbox.ts:502` `src/reach/outbox.ts:516-521`

When the event has an earlier send, `send` reports it on `err` and returns 1. `src/reach/cli.ts:210` `src/reach/cli.ts:219-224`

For a new key, `enqueue` rejects more than 5 buttons and a label over 80 characters. `src/reach/outbox.ts:18` `src/reach/outbox.ts:20` `src/reach/outbox.ts:340-343` `src/reach/outbox.ts:502`

For a new key, `enqueue` rejects `--channel` given with `--reply-to`. `src/reach/outbox.ts:337` `src/reach/outbox.ts:502`

For a new key, `--as-file` makes `enqueue` write the text to `message.md` and attach it as one part. `src/reach/outbox.ts:502` `src/reach/outbox.ts:365-371`

`splitText` packs lines into parts of at most 2000 characters by default. `src/reach/outbox.ts:16` `src/reach/outbox.ts:270` `src/reach/outbox.ts:290`

`react` needs `--message` and `--emoji`, else it returns 2. `src/reach/cli.ts:162-165`

`react` queues the reaction under `--key`; a repeated key reports `already queued` and adds nothing. `src/reach/cli.ts:168-169`

`thread` needs one reference and exactly one of `--name` or `--archive`, else it returns 2. `src/reach/cli.ts:88-91`

`thread --name` queues a thread on the reference, or reports the existing one. `src/reach/cli.ts:112-113`

`thread --archive` queues an archive of the thread, or reports the existing request's state. `src/reach/cli.ts:96-97`

With `--peer`, `send` returns 2 if `--reply-to`, `--channel`, `--buttons`, `--attach`, `--as-file` or `--again` is given. `src/reach/cli.ts:185-190`

With `--peer` and neither `--text` nor `--file`, `send` returns 2. `src/reach/cli.ts:127-130`

With `--peer`, `send` returns 1 and queues nothing when `requirePeer` rejects the peer. `src/reach/cli.ts:134` `src/reach/cli.ts:137-139`

`requirePeer` takes the sender from `--from`, else from the config's `self`. `src/reach/peers.ts:104`

When a peer message repeats a sender and key, `enqueue` adds nothing. `src/reach/peer-outbox.ts:79` `src/reach/peer-outbox.ts:70`

When a row is due, `startPeerSender` posts it to `<url>/events/agent.<sender>` with the key as `x-event-key`. `src/reach/peers.ts:144` `src/reach/peers.ts:178` `src/reach/peers.ts:158-160`

A 2xx answer to a due row marks it sent. `src/reach/peers.ts:168` `src/reach/peers.ts:185`

A 4xx answer other than 429 to a due row marks it failed. `src/reach/peers.ts:170` `src/reach/peers.ts:186`

A network error, a timeout, 429 or 5xx holds that sender and peer for `retryMs`, default 5000 ms. `src/reach/peers.ts:147` `src/reach/peers.ts:171` `src/reach/peers.ts:189`

`resolvePeers` takes the `peers` option, else `REACH_PEERS`, else `REACH_SELF`. `src/reach/peers.ts:80` `src/reach/peers.ts:86-95`

When a listed channel has a last seen id, catch-up fetches later messages with `port.fetchAfter` and handles them. `src/reach/index.ts:409-413`

`startReach` takes `channelId` or `channelIds` and throws when both are given. `src/reach/index.ts:99-100` `src/reach/index.ts:108`

`t3Cli` fails a call that has not ended within `timeoutMs`, default 30 seconds. `src/t3/cli.ts:77` `src/t3/cli.ts:22` `src/t3/cli.ts:39-42`

`start` throws when the `provider` or `model` option is empty or missing. `src/t3/cli.ts:110-111`

`ensureProject` runs `t3 project add` and treats an "already exists" failure as success. `src/t3/cli.ts:74` `src/t3/cli.ts:119-121`

## A10 watchdog

CONTRACT.md says the core does not act on a target: it reads, judges, flags and records. `src/watchdog/CONTRACT.md:47`
The `./watchdog` entry exports `sweep`, `registerWatchdog`, `commandJudge`, `fileVerdictLog` and `memoryVerdictLog`. `src/watchdog/index.ts:9` `src/watchdog/index.ts:11` `src/watchdog/index.ts:13-15`

A watchdog is a named config with a name, targets, a seat, a sink and an optional model. `src/watchdog/domain/config.ts:52-62`
Its name starts with a letter or digit, then letters, digits, dot, dash or underscore. `src/watchdog/domain/config.ts:31`
Its targets are `"all"` or a non-empty list of non-blank ids. `src/watchdog/domain/config.ts:47-48`
A model in the config wins over the seat's model. `src/watchdog/domain/config.ts:83`
When the config has no model and the seat is not in the seat table, resolving throws. `src/watchdog/domain/config.ts:84`

The default watchdog has targets `all`, runs hourly at minute 20 UTC, seat `reviewer`, sink `default`. `src/watchdog/domain/config.ts:89-95`

A sweep throws before reading any target when the sink is missing or no model resolves. `src/watchdog/usecases/sweep.ts:38`
For a target, a sweep reads the evidence since the watchdog's last log entry for it. `src/watchdog/usecases/sweep.ts:48-50`
When an entry exists, the evidence is not active and its cursor matches, the target is skipped. `src/watchdog/usecases/sweep.ts:51`
Otherwise the sweep asks the judge, then checks the verdict with `readVerdict`. `src/watchdog/usecases/sweep.ts:54`
A verdict state is `progressing`, `stuck`, `looping`, `drifting` or `unclear`. `src/watchdog/domain/verdict.ts:6`
A verdict needs a non-empty `why` and a string `quote`. `src/watchdog/domain/verdict.ts:29-30`
The states `stuck`, `looping` and `drifting` are bad. `src/watchdog/domain/verdict.ts:10`
A judged bad verdict is flagged when its state differs from the last settled verdict. `src/watchdog/usecases/sweep.ts:58`
The last settled verdict is the latest logged one whose state is not `unclear`. `src/watchdog/usecases/sweep.ts:56`
Without a settled verdict, a judged bad verdict is flagged. `src/watchdog/domain/verdict.ts:46`
A judged target's flag key joins watchdog name, target id, evidence cursor and state with colons. `src/watchdog/usecases/sweep.ts:57`
When a flag is posted, it is posted before the log entry is appended. `src/watchdog/usecases/sweep.ts:59-61`
When a target throws, the sweep reports it as failed and goes on to the next target. `src/watchdog/usecases/sweep.ts:42`

`commandJudge` throws when `argv` lacks a program. `src/watchdog/adapters/command-judge.ts:25-26`
It sends the judge input to the command as one JSON object on standard input. `src/watchdog/adapters/command-judge.ts:53`
When the command exits 0, its standard output is parsed as a verdict. `src/watchdog/adapters/command-judge.ts:45-47`
A non-zero exit fails the judgment. `src/watchdog/adapters/command-judge.ts:45`
The command may run 10 minutes by default, then it is killed with `SIGKILL`. `src/watchdog/adapters/command-judge.ts:17` `src/watchdog/adapters/command-judge.ts:32`
When the seat lacks an effort, an argument containing `{effort}` is left out. `src/watchdog/adapters/command-judge.ts:22`

`registerWatchdog` throws when a job with the id `watchdog:<name>` already exists. `src/watchdog/usecases/jobs.ts:18`
When the job is absent and `off` is true, it adds the job with `enabled: false`. `src/watchdog/usecases/jobs.ts:19-20`
`installDefaultWatchdog` leaves an existing default job as it is. `src/watchdog/usecases/jobs.ts:27`
Otherwise it registers the default watchdog switched off. `src/watchdog/usecases/jobs.ts:28`

An unknown verb exits 2 with a usage message. `src/watchdog/cli.ts:145` `src/watchdog/cli.ts:149`
`sweep` finds the job `watchdog:<name>` and exits 1 when it is missing. `src/watchdog/cli.ts:105-106` `src/watchdog/cli.ts:149`
`sweep` prints one line per target. `src/watchdog/cli.ts:95-97` `src/watchdog/cli.ts:108`
`sweep` exits 1 when a target failed. `src/watchdog/cli.ts:109`
`why` without a target exits 2. `src/watchdog/cli.ts:117` `src/watchdog/cli.ts:149`
`why` exits 1 when no log entry matches. `src/watchdog/cli.ts:119` `src/watchdog/cli.ts:149`
`add` exits 2 when it has neither `--cron` nor `--once`. `src/watchdog/cli.ts:86` `src/watchdog/cli.ts:149`
`install` prints the job id and its state as JSON. `src/watchdog/cli.ts:130`

