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

## A1 Surfaces

<!-- printed -->
entry | exports { | package.json:14
entry | script typecheck | package.json:139
entry | script pretest | package.json:140
entry | script test | package.json:141
entry | script build | package.json:142
entry | script smoke | package.json:143
entry | script provenance-diff.sh | scripts/provenance-diff.sh:1
entry | script roots-launchd-journey.sh | scripts/roots-launchd-journey.sh:1
entry | script agent-traces.wrapper.sh | src/traces/proof/support/agent-traces.wrapper.sh:1
entry | script agent-events.rendered.sh | src/traces/proof/support/rehearse/agent-events.rendered.sh:1
entry | script agent-events.sh | src/traces/proof/support/rehearse/agent-events.sh:1
event | connection | scripts/consumer-smoke.mjs:347
event | messageCreate | src/adapters/discord/discordjs.ts:102
event | threadCreate | src/adapters/discord/discordjs.ts:104
event | interactionCreate | src/adapters/discord/discordjs.ts:122
event | shardResume | src/adapters/discord/discordjs.ts:143
event | shardReady | src/adapters/discord/discordjs.ts:144
event | line | src/board/conformance/scripted-mcp-stdio.ts:24
env | FAKE_GH_LOG | scripts/board-journey.mjs:32
env | FAKE_GH_FIXTURE | scripts/board-journey.mjs:33
env | NODE_FLOOR_SEED_FAILURE | scripts/node-floor.mjs:20
env | TZ | scripts/node-floor.mjs:77
env | AGENT_EVENTS_STATE_DIR | scripts/pi-fixtures/make-export-previews.py:66
env | AGENT_EVENTS_PROJECTS | scripts/pi-fixtures/make-project-map.py:49
env | AGENT_TRACES_DIR | scripts/pi-fixtures/make-review-reference.py:93
env | AGENT_EVENTS_MACHINE | scripts/pi-fixtures/make-state-cases.py:304
env | AGENT_TRACES_NODE | scripts/roots-launchd-journey.sh:23
env | AGENT_TRACES_KIT | src/traces/proof/support/agent-traces.wrapper.sh:5
env | TRACES_FIXTURES | src/traces/proof/support/cache-check-fixture.ts:13
env | AGENT_EVENTS_IMPLEMENTATION | src/traces/proof/support/rehearse/agent-events.rendered.sh:11
env | AGENT_EVENTS_PYTHON | src/traces/proof/support/rehearse/agent-events.rendered.sh:27
env | AGENT_EVENTS_OTLP_ENDPOINT | src/traces/proof/support/rehearse/agent_events.py:9
env | VITEST_TEST_TIMEOUT | vitest.config.ts:4
env | XDG_CONFIG_HOME | vitest.setup.ts:8
env | GIT_CONFIG_COUNT | vitest.setup.ts:14
config | kgate.toml | kgate.toml:1
manifest | package.json | package.json:1
export | RefreshSource | src/board/index.ts:40
export | BoardOptions | src/board/index.ts:42
export | DoctorOptions | src/board/index.ts:56
export | WriteOptions | src/board/index.ts:59
export | RefreshOptions | src/board/index.ts:64
export | RefreshAllResult | src/board/index.ts:69
export | WriteInput | src/board/index.ts:75
export | Board | src/board/index.ts:82
export | openBoard | src/board/index.ts:132
export | NewEvent | src/inbox/index.ts:6
export | EventRow | src/inbox/index.ts:15
export | PostResult | src/inbox/index.ts:25
export | Inbox | src/inbox/index.ts:31
export | OWNER_BATCH_SOURCE | src/inbox/index.ts:87
export | WAKE_BATCH_SOURCE | src/inbox/index.ts:88
export | InboxBatching | src/inbox/index.ts:90
export | InboxPolicy | src/inbox/index.ts:102
export | PLAIN_QUEUE_POLICY | src/inbox/index.ts:109
export | openInbox | src/inbox/index.ts:123
export | KIT_NAME | src/index.ts:2
export | KIT_SPIKE | src/index.ts:3
export | failedCases | src/jobs/conformance/index.ts:12
export | JobsOptions | src/jobs/index.ts:29
export | Jobs | src/jobs/index.ts:39
export | openJobs | src/jobs/index.ts:58
export | read | src/playbook/index.ts:11
export | ReachEvent | src/reach/index.ts:26
export | ReachAction | src/reach/index.ts:34
export | ReachOptions | src/reach/index.ts:40
export | Reach | src/reach/index.ts:73
export | ACK_EMOJI | src/reach/index.ts:88
export | nonceFor | src/reach/index.ts:95
export | startReach | src/reach/index.ts:105
export | stopReach | src/reach/index.ts:1056
export | failedCases | src/watchdog/conformance/index.ts:10
doc | AGENTS.md | AGENTS.md:1
doc | README.md | README.md:1
doc | board.md | docs/board.md:1
doc | chat-and-reach.md | docs/chat-and-reach.md:1
doc | development.md | docs/development.md:1
doc | inbox.md | docs/inbox.md:1
doc | jobs.md | docs/jobs.md:1
doc | playbook.md | docs/playbook.md:1
doc | subpaths.md | docs/subpaths.md:1
doc | traces.md | docs/traces.md:1
doc | watchdog.md | docs/watchdog.md:1
ci | / | .github/workflows/publish.yml:50
ci | / | .github/workflows/publish.yml:74
ci | node scripts/release-gate.mjs | .github/workflows/publish.yml:85
ci | npm ci | .github/workflows/publish.yml:89
ci | npm run build | .github/workflows/publish.yml:90
ci | npm publish | .github/workflows/publish.yml:91
ci | / | .github/workflows/publish.yml:97
ci | npm ci | .github/workflows/unit.yml:30
ci | npm run typecheck | .github/workflows/unit.yml:31
ci | npm test | .github/workflows/unit.yml:34
ci | npm run build | .github/workflows/unit.yml:35
ci | npm run smoke | .github/workflows/unit.yml:36
ci | test "$(node --version)" = "v22.19.0" | .github/workflows/unit.yml:49
ci | npm ci | .github/workflows/unit.yml:50
ci | npm run typecheck | .github/workflows/unit.yml:51
ci | npm run build | .github/workflows/unit.yml:52
ci | node scripts/node-floor.mjs | .github/workflows/unit.yml:53
ci | npx vitest run | .github/workflows/unit.yml:54
ci | node --test scripts/*.test.mjs | .github/workflows/unit.yml:55
scout | reach | src/reach/cli.ts:71
scout | ChatPort | src/adapters/discord/discordjs.ts:1
scout | inbox | scripts/board-journey.mjs:312
scout | playbook | src/playbook/cli.ts:119
scout | board | scripts/board-journey.mjs:14
scout | jobs | src/jobs/cli.ts:181
scout | watchdog | src/watchdog/adapters/job-runner.ts:1
scout | traces | scripts/consumer-smoke.mjs:251
<!-- /printed -->

## A2 Evidence

<!-- printed -->
tests found: 2686 cases in 214 files
surfaces named in tests: 14 of 24 (command, flag, route, event and env rows)
never named in tests:
event | messageCreate | src/adapters/discord/discordjs.ts:102
event | threadCreate | src/adapters/discord/discordjs.ts:104
event | interactionCreate | src/adapters/discord/discordjs.ts:122
event | shardResume | src/adapters/discord/discordjs.ts:143
event | shardReady | src/adapters/discord/discordjs.ts:144
env | TZ | scripts/node-floor.mjs:77
env | TRACES_FIXTURES | src/traces/proof/support/cache-check-fixture.ts:13
env | VITEST_TEST_TIMEOUT | vitest.config.ts:4
env | XDG_CONFIG_HOME | vitest.setup.ts:8
env | GIT_CONFIG_COUNT | vitest.setup.ts:14
<!-- /printed -->

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

## A5 ChatPort

When a port omits `capabilities`, reach treats it as supporting buttons, reactions and threads (code comment). `src/chat/port.ts:153-154`

`isDeterministicRejection` is true for a `ChatRejection` with a status of 400 or more and below 500, except 429. `src/chat/port.ts:91-92`

`MalformedIdRejection` is a `ChatRejection` with status 400. `src/chat/port.ts:83-86`

Discord orders ids as `BigInt` values, so `newer` is true when the first is larger. `src/chat/discord-order.ts:10`

Discord `before` subtracts one from the position. `src/chat/discord-order.ts:12`

Matrix `newer` compares ids as plain strings. `src/adapters/matrix/matrix.ts:73`

A Matrix port id must be 15 digits, `$`, then an event id, or `MalformedIdRejection` is thrown. `src/adapters/matrix/matrix.ts:66`

`threadParent` returns an empty object when the channel id is null. `src/chat/thread-parent.ts:26`

For a non-null channel id, `threadParent` answers from the cache without fetching when the cache has the channel. `src/chat/thread-parent.ts:29`

For a non-null channel id, a thread yields its `parentId` as `parentChannelId`; a non-thread yields an empty object. `src/chat/thread-parent.ts:27`

When the cache has no entry, `threadParent` fetches the channel, trying up to 3 times. `src/chat/thread-parent.ts:18` `src/chat/thread-parent.ts:30-32`

It waits 400 ms between failed fetch attempts. `src/chat/thread-parent.ts:19` `src/chat/thread-parent.ts:34`

When the cache has no entry and all 3 fetches fail, `threadParent` returns `channelLookupFailed: true`. `src/chat/thread-parent.ts:18` `src/chat/thread-parent.ts:25` `src/chat/thread-parent.ts:37`

`createDiscordJsPort` returns a port with source `discord` and `buttons`, `reactions` and `threads` true. `src/adapters/discord/discordjs.ts:86` `src/adapters/discord/discordjs.ts:156-157`

`send` sets `nonce` from the message and `enforceNonce: true`. `src/adapters/discord/discordjs.ts:177`

`send` leaves text content unset when the message content is empty. `src/adapters/discord/discordjs.ts:178`

When `replyToMessageId` is set, `send` replies with `failIfNotExists: true`. `src/adapters/discord/discordjs.ts:179`

When a call throws a `DiscordAPIError`, `translate` throws a `ChatRejection` with the same status. `src/adapters/discord/discordjs.ts:79`

When a call throws another kind of error, `translate` rethrows it unchanged. `src/adapters/discord/discordjs.ts:80`

When `buttons` is set, `send` puts them in one row of secondary-style buttons. `src/adapters/discord/discordjs.ts:181` `src/adapters/discord/discordjs.ts:71-72`

`startThread` posts a thread with `auto_archive_duration` of 10080 minutes. `src/adapters/discord/discordjs.ts:189` `src/adapters/discord/discordjs.ts:65`

`archiveThread` patches the thread channel with `archived: true`. `src/adapters/discord/discordjs.ts:196`

`history` throws a 400 `ChatRejection` when the limit is not a positive integer. `src/adapters/discord/discordjs.ts:199`

When the limit is valid, `history` throws a 403 `ChatRejection` if the channel's guild differs from `scope.guildId`. `src/adapters/discord/discordjs.ts:202-203`

In `history`, a message whose type is not 0 or 19 does not count towards the limit. `src/adapters/discord/discordjs.ts:198` `src/adapters/discord/discordjs.ts:217` `src/adapters/discord/discordjs.ts:222`

`conversationState` answers `unknown` with a null title when Discord returns 404. `src/adapters/discord/discordjs.ts:230` `src/adapters/discord/discordjs.ts:236`

`fetchReactors` keeps requesting pages of 100 users until a page is shorter. `src/adapters/discord/discordjs.ts:243-246`

`fetchAfter` fetches pages of 100 messages after the given id, stopping at a shorter page. `src/adapters/discord/discordjs.ts:35` `src/adapters/discord/discordjs.ts:273` `src/adapters/discord/discordjs.ts:277`

On a `shardReady` event after the first, the adapter fires the resume handlers. `src/adapters/discord/discordjs.ts:145`

On a button interaction, the adapter calls `deferUpdate` before it looks up the thread parent. `src/adapters/discord/discordjs.ts:126-128`

`createMatrixPort` throws when `roomId` is not a Matrix room id. `src/adapters/matrix/matrix.ts:252`

The sync long-poll timeout defaults to 30000 ms. `src/adapters/matrix/matrix.ts:258`

The Matrix port has source `matrix` and `buttons`, `reactions` and `threads` true. `src/adapters/matrix/matrix.ts:660-661`

Matrix `history` throws a 501 `ChatRejection`. `src/adapters/matrix/matrix.ts:789`

`download` throws a 400 `ChatRejection` unless the `ref` is an mxc address. `src/adapters/matrix/matrix.ts:409-410`

`download` uses the legacy media endpoint when the authenticated one answers `M_UNRECOGNIZED`. `src/adapters/matrix/matrix.ts:415` `src/adapters/matrix/matrix.ts:417`

When `spaceId` is unset, Matrix `conversationState` answers `unknown` with a null title. `src/adapters/matrix/matrix.ts:772`

## A6 inbox

`openInbox` opens a SQLite file at a path and takes its policy from the app. `src/inbox/index.ts:122-123`

`post` throws when the source or the external_key is not a non-empty string. `src/inbox/index.ts:181-182`

When the same source and external_key were already stored, `post` returns the stored id with `duplicate: true`. `src/inbox/index.ts:184-185`

When the key is new and the event has `acked: true`, `post` sets `acked_at` to its `received_at`. `src/inbox/index.ts:131`, `src/inbox/index.ts:187-188`

For a non-empty list, `postMany` uses one transaction and rolls back and throws if a post fails. `src/inbox/index.ts:194-203`

When the list is empty, `postMany` returns an empty array. `src/inbox/index.ts:194`

`next` returns the oldest event whose `acked_at` is null, delivered or not. `src/inbox/index.ts:134`, `src/inbox/index.ts:205-207`

`pending` returns the events whose `acked_at` is null, oldest first. `src/inbox/index.ts:137`, `src/inbox/index.ts:209-211`

`getCursor` and `setCursor` keep a named value in the same SQLite file. `src/inbox/index.ts:140-141`, `src/inbox/index.ts:244-248`

When an unacked event has a source in `ownerSources`, `take` chooses from those events. `src/inbox/index.ts:214-215`

When the head of the chosen queue was delivered before, `take` returns it unmerged. `src/inbox/index.ts:217`

When `isOwnerMessage` accepts the undelivered owner head, `take` merges a leading run of two or more. `src/inbox/index.ts:212`, `src/inbox/index.ts:218-220`

A merged run of owner messages has source `OWNER_BATCH_SOURCE`, which is `'owner-batch'`. `src/inbox/index.ts:87`, `src/inbox/index.ts:220`

A merge stores the new event and acks its members in one transaction. `src/inbox/index.ts:145-150`

The socket answers a non-empty line with one JSON line. `src/inbox/socket.ts:33`

When a line is a JSON object with string `source` and `external_key`, the socket posts it. `src/inbox/socket.ts:15-18`

When `post` succeeds, the socket answers `ok: true`. `src/inbox/socket.ts:18`

When parsing, validation or `post` throws on a line, the socket answers `ok: false` with the error message. `src/inbox/socket.ts:19-20`

`startInboxSocket` removes a file at its path before it listens. `src/inbox/socket.ts:41`

The HTTP handler answers false for a path outside `/events/`. `src/inbox/http.ts:11`, `src/inbox/http.ts:56`

When the method is not POST, the handler answers 405 with `allow: POST`. `src/inbox/http.ts:69-71`

For a POST, a source that does not match `[a-z0-9._-]+` gets 400. `src/inbox/http.ts:75`

A POST from a valid source starting with `agent.` gets 403 unless `acceptPeers` lists the name or `*`. `src/inbox/http.ts:13`, `src/inbox/http.ts:53`, `src/inbox/http.ts:76`

For a POST from a permitted source, a body over `maxBodyBytes` gets 413; the default is 5 MiB. `src/inbox/http.ts:8`, `src/inbox/http.ts:51`, `src/inbox/http.ts:77`

The handler takes the key from the `x-event-key` header, else a random UUID. `src/inbox/http.ts:9`, `src/inbox/http.ts:60`

When the handler posts a body that is not valid JSON, the payload is `{ text: body }`. `src/inbox/http.ts:41-47`, `src/inbox/http.ts:79`

When those checks pass and `post` succeeds, the handler answers 202 with `id` and `duplicate`. `src/inbox/http.ts:79-82`

With a `brief`, the forwarder starts a thread with it when `findThread` finds no thread. `src/inbox/forwarder.ts:144-146`

When the thread has a run going and `joinRunningTurn` is not on, the forwarder sends nothing. `src/inbox/forwarder.ts:192`

When nothing is awaited and the thread is idle, events no header covers are sent in one message. `src/inbox/forwarder.ts:193`, `src/inbox/forwarder.ts:212`

A non-replay hand-off gets an `[events first-last]` header line unless its text already has one. `src/inbox/forwarder.ts:161-163`

After a send succeeds, the forwarder marks those events delivered and acked. `src/inbox/forwarder.ts:168-169`

When T3 calls keep failing for 120 seconds with events waiting, the forwarder calls `hooks.onDown` once per outage. `src/inbox/forwarder.ts:17`, `src/inbox/forwarder.ts:218-222`

## A7 playbook

- An entry heading is `## <id>`, optionally followed by ` · personal`, ` · work` or ` · both`. `src/playbook/entries.ts:82`
- A new entry's id is the first 8 hex digits of sha256 over its date and quote. `src/playbook/entries.ts:31` `src/playbook/entries.ts:108` `src/playbook/commands.ts:67`
- After the heading come `**Rule:**`, then optional Enforced by, Briefs and Seats paragraphs, then `**Sources:**`. `src/playbook/entries.ts:86`
- When the file has old-format `## YYYY-MM-DD` headings and no new ones, parsing says to run `playbook upgrade` first. `src/playbook/entries.ts:167` `src/playbook/entries.ts:80`
- When `config.json` sets `playbook_repo`, the playbook file sits at the root of that checkout. `src/playbook/paths.ts:38` `src/playbook/paths.ts:42`
- Without `playbook_repo`, the playbook file sits at the root of the repository given as `defaultRepoRoot`. `src/playbook/paths.ts:31` `src/playbook/paths.ts:42`

- `add` needs `--quote`, `--date` and `--rule`. `src/playbook/cli.ts:155`
- `add` throws when an entry with the same date and quote already exists. `src/playbook/commands.ts:68`
- When the rule differs, `revise` replaces it and appends the quote as the newest source. `src/playbook/commands.ts:86` `src/playbook/commands.ts:88`
- When tags, seats and Briefs match, `merge` removes the other entries and keeps the first id. `src/playbook/commands.ts:112-113` `src/playbook/commands.ts:126-127`
- `retire` removes the named entries, and its commit body holds the new quote and the removed text. `src/playbook/commands.ts:152-158`
- Without arguments, `upgrade` reports nothing to upgrade when the file has no old-format entries. `src/playbook/cli.ts:244`

- When the invariants hold and the text changes, the command makes one commit of the playbook file. `src/playbook/store.ts:58` `src/playbook/store.ts:60` `src/playbook/store.ts:64`
- A change throws when the playbook file has uncommitted changes. `src/playbook/store.ts:55`
- A checkout on main or master with an origin remote is refused a commit. `src/playbook/git.ts:89` `src/playbook/store.ts:51`
- For an edit command run without `--pr`, the refusal message ends with the same command plus `--pr --merge`. `src/playbook/cli.ts:142-143`
- With `--base`, `check` compares the file with that revision's copy. `src/playbook/cli.ts:246-247` `src/playbook/inspect.ts:61`
- Commands other than `show`, `list`, `unenforced` and `drift` append one record to the action log. `src/playbook/cli.ts:61` `src/playbook/cli.ts:72`
- The log is `playbook.jsonl` under `~/.local/state`, moved to `.1` at MAX_LOG_BYTES. `src/playbook/log.ts:50` `src/playbook/log.ts:69`

- `--against` makes `drift` compare this file with a playbook file or a bundle. `src/playbook/cli.ts:264` `src/playbook/bundle.ts:117`
- When this copy's sources are a strict prefix of the other's, the entry is newer there. `src/playbook/bundle.ts:82`
- `export --out` throws if the file exists; otherwise it writes tombstone lines, then the entries tagged `both`. `src/playbook/bundle.ts:204` `src/playbook/bundle.ts:207-209`
- `import` throws for an entry tagged `work` in the source. `src/playbook/bundle.ts:235`
- When the repository has a remote and the entry is not tagged personal, `import` needs `--yes-public`. `src/playbook/bundle.ts:239-240`

- When no PR is open and the edit is not merged, `--pr` edits in a detached worktree. `src/playbook/pr.ts:471` `src/playbook/pr.ts:476` `src/playbook/pr.ts:487`
- In that worktree, scripts/playbook-check runs before the push when the file exists. `src/playbook/pr.ts:36` `src/playbook/pr.ts:431` `src/playbook/pr.ts:495`
- For a new edit, `--pr` opens the PR against main with the commit subject as title. `src/playbook/pr.ts:29` `src/playbook/pr.ts:524`
- When a PR is open on the request's branch, `--pr` picks it up. `src/playbook/pr.ts:468` `src/playbook/pr.ts:475`
- With `--merge`, a failed PR check stops the merge. `src/playbook/pr.ts:414` `src/playbook/cli.ts:134`
- With `--merge`, a red or unfinished workflow run on the PR head stops the merge (code comment). `src/playbook/pr.ts:347-348`
- With `--merge`, `ci-main-status` exiting 1 stops the merge of an open PR unless `--red-main-fix` is given. `src/playbook/pr.ts:367-369` `src/playbook/pr.ts:536`
- With `--merge`, once checks pass, the PR is squash-merged. `src/playbook/pr.ts:541`
- A failed step is named in the output. `src/playbook/pr.ts:580`
- A branch already on origin is reported kept for a rerun. `src/playbook/pr.ts:582`

## A8 board

An app's own command calls `runBoardCli({ tags, envPrefix })` (code comment). `src/board/cli.ts:81-82`
Run directly, `cli.ts` prints that it is a library entry and sets exit code 2. `src/board/cli.ts:104-106`
A verb takes `--dir`; without it the board directory is `defaultBoardDir()`. `src/board/cli.ts:25` `src/board/cli.ts:45`
An unknown verb prints the usage line on stderr and returns 2. `src/board/cli.ts:36-39`
On a usage error the CLI prints `verb: message`, then the usage line, and returns 2. `src/board/cli.ts:51-54`
When a verb throws a write-policy refusal, the CLI prints `REFUSED: message` and returns 3. `src/board/cli.ts:60-63`
When a verb is refused as busy, the CLI prints `board: message` and returns 1. `src/board/cli.ts:56-59`
On an error of another kind the CLI prints `verb: message` and returns 1. `src/board/cli.ts:64-65`

`board show` prints the board's lines, or with `--json` prints them as JSON. `src/board/commands.ts:134-135`
`--json` on `refresh` is a usage error unless the source is `all`. `src/board/commands.ts:157`
`board refresh all` returns 1 when a feed failed. `src/board/commands.ts:153-155` `src/board/commands.ts:125`
Without `--json`, when the feed list is empty, `refresh all` prints "no feed is enabled in config.json". `src/board/commands.ts:116-117`
A refresh of one feed requires a clean repo before it reads the board. `src/board/usecases/refresh.ts:32-33`
The build's tracker plug-ins are github, github-project, ticktick and jira. `src/board/commands.ts:16`
`board doctor` returns 1 when the doctor call reports a problem. `src/board/commands.ts:181`
`--key` on `doctor` is a usage error unless the tracker is `jira`. `src/board/commands.ts:179`

A verb that finds `.board.lock` held waits up to 60 seconds (code comment). `src/board/adapters/lock.ts:3` `src/board/adapters/lock.ts:17`
`board add` needs `--title`. `src/board/commands.ts:213`
`board add BD` takes the next BD number. `src/board/usecases/add.ts:41`
`board add` with `--box` puts the line at the bottom of that box. `src/board/usecases/add.ts:45`
When the ref is a BD number, `board add` refuses one not above the highest ever used. `src/board/usecases/add.ts:50`
`board rank` without `--why` refuses. `src/board/usecases/rank.ts:29`
With `--up` or `--down`, `rank` refuses `--into`, `--after`, `--top` and `--bottom`. `src/board/commands.ts:98`
When the board file exists and is unchanged by a rank, `rank` makes no commit. `src/board/usecases/rank.ts:36`
`board done` refuses a ref that is not a BD ref. `src/board/usecases/done.ts:20`
When a BD line on the board is already done, `done` makes no commit. `src/board/usecases/done.ts:27`
`board park` and `board unpark` refuse a BD line that is done. `src/board/usecases/park.ts:31`
`board write` needs a tracker and a verb. `src/board/commands.ts:289`
`--to` on `write` is a usage error unless the call is `jira transition`. `src/board/commands.ts:290`
With `--json`, `write` prints the outcome, the commit and the target. `src/board/commands.ts:292`

## A9 jobs

The SQLite store opens its file in WAL journal mode with a 5000 ms busy timeout. `src/jobs/adapters/sqlite-store.ts:133-134`

The package exports `./jobs` from `dist/jobs/index.js`. `package.json:83-86`

A cron schedule with other than 5 fields is refused. `src/jobs/domain/schedule.ts:24`

A one-time time without a final `Z` or offset is refused. `src/jobs/domain/schedule.ts:18`

Adding a one-time job for a time not in the future fails. `src/jobs/usecases/manage.ts:52` `src/jobs/usecases/manage.ts:91`

A job added with no name takes its id as its name. `src/jobs/usecases/manage.ts:96`

When `add` gets no retries, retries and retry wait are 0. `src/jobs/usecases/manage.ts:84-85`

Adding a job fails when one with that id exists. `src/jobs/usecases/manage.ts:88`

An added job is enabled unless `enabled` is false. `src/jobs/usecases/manage.ts:100`

When an enabled job is added, a refusing authorizer fails the add with its message. `src/jobs/usecases/manage.ts:65` `src/jobs/usecases/manage.ts:109`

`tick` first calls `recoverInterrupted`. `src/jobs/index.ts:84`

`recoverInterrupted` closes an open run as interrupted when its owner is not live. `src/jobs/usecases/tick.ts:156-159`

A tick starts a run for a due job unless the job changed or is still running. `src/jobs/usecases/tick.ts:212-221`

When a cron job's first attempt falls due while it runs, the tick writes a skipped-overlap row. `src/jobs/usecases/tick.ts:218`

A skip writes nothing when the job's incarnation or due state moved since the tick read it. `src/jobs/usecases/tick.ts:190-191` `src/jobs/adapters/sqlite-store.ts:261-263`

When a one-time job falls due while it runs, the tick writes no skip row. `src/jobs/usecases/tick.ts:218-219`

An attempt number above 1 gives the run the reason `retry`. `src/jobs/usecases/tick.ts:143`

A one-time job's first attempt started over 60_000 ms after its occurrence has reason `catch-up`. `src/jobs/usecases/tick.ts:137` `src/jobs/usecases/tick.ts:146`

`runNow` starts a run with reason `manual` and moves no due state. `src/jobs/usecases/tick.ts:51` `src/jobs/usecases/tick.ts:198`

When the job is already running, `runNow` writes a skipped-overlap row. `src/jobs/usecases/tick.ts:199`

A job whose kind has no runner fails with `no runner for kind`. `src/jobs/usecases/tick.ts:89`

A failed scheduled run gets a retry while its attempt number is at most the job's retries. `src/jobs/domain/job.ts:113` `src/jobs/usecases/tick.ts:62`

A retry waits the retry wait, doubled for each earlier retry, after the failed run's end. `src/jobs/domain/job.ts:99`

When a run ends and its row is still running, its JSON line goes to the log sink. `src/jobs/usecases/tick.ts:106-107` `src/jobs/usecases/tick.ts:118`

Unless the host passes a log sink, the CLI writes its log to `jobs.log` beside the database. `src/jobs/cli.ts:206`

With a valid target, the `command` runner starts the program from `argv` in `cwd`, with no shell. `src/jobs/adapters/command-runner.ts:29-31` `src/jobs/adapters/command-runner.ts:46`

When the program exits non-zero, the run fails and keeps `exit_code` and `output` as its result. `src/jobs/adapters/command-runner.ts:62-64`

`output` keeps at most the last 4096 bytes. `src/jobs/adapters/command-runner.ts:9` `src/jobs/adapters/command-runner.ts:50`

Without `--db`, the CLI exits 2. `src/jobs/cli.ts:198`

An unknown command exits 2. `src/jobs/cli.ts:191` `src/jobs/cli.ts:195`

`add` needs `--kind` and either `--cron` with `--zone`, or `--once`. `src/jobs/cli.ts:119` `src/jobs/cli.ts:121`

Giving `--cron` and `--once` together exits 2. `src/jobs/cli.ts:72` `src/jobs/cli.ts:211`

`--retries` must be whole digits. `src/jobs/cli.ts:88` `src/jobs/cli.ts:129`

`--target` must be JSON. `src/jobs/cli.ts:97`

A blank `--words` is a usage error. `src/jobs/cli.ts:102`

A successful command prints one JSON document with `out`, standard output by default, and exits 0. `src/jobs/cli.ts:181` `src/jobs/cli.ts:208-209`

When the runner fails, `run` still exits 0 and the row's outcome is `failed`. `src/jobs/cli.ts:158` `src/jobs/usecases/tick.ts:104` `src/jobs/cli.ts:209`

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

## A11 traces

The `traces` command takes `review` or `pi` as its first word `src/traces/cli.ts:191-192`. An unrecognized first word, or `review` without a verb, prints usage and exits 2 `src/traces/cli.ts:187` `src/traces/cli.ts:192`. Other errors thrown in a `review` command print `traces: <message>` and exit 1 `src/traces/cli.ts:192` `src/traces/cli.ts:339-340`.

`runAsMain` is true when the module file and `argv[1]` have the same real path `src/traces/adapters/entry.ts:9`. It is false when `argv[1]` is empty or a path cannot be resolved `src/traces/adapters/entry.ts:7` `src/traces/adapters/entry.ts:11`.

Traces data lives under `AGENT_TRACES_DIR` when it is set and non-empty `src/traces/adapters/file-store.ts:10-11`.

`normalize` prints one line per finding, then `VERDICT: <verdict> <head>` `src/traces/domain/return.ts:137-138`. It exits 0 for an accepted return, whatever the verdict `src/traces/cli.ts:213-215`. A rejected return prints its reason on stderr and exits 1 `src/traces/cli.ts:209-211`.

A finding counts as blocking when its severity is `blocking` and its obligation, evidence and consequence are non-blank `src/traces/domain/return.ts:118-120`. A blocking finding missing one of those fields prints as a note `src/traces/domain/return.ts:120` `src/traces/domain/return.ts:137`. A finding with severity `note` is not demoted `src/traces/domain/return.ts:118`. The verdict is FAIL when a finding is effectively blocking, else PASS `src/traces/domain/return.ts:129`.

`add` refuses a `--round` that is not the log's last round plus 1 `src/traces/usecases/add.ts:75-76` `src/traces/usecases/add.ts:235-236`. `--stage` must be `mechanism`, `intent`, `plan`, `design`, `diff` or `other` `src/traces/usecases/add.ts:69` `src/traces/domain/log.ts:5`.

A component is stuck when it has blocking `repeat` or `follow-on` findings in consecutive rounds of one stage `src/traces/domain/trigger.ts:34-46`. `add` refuses a new round while a component is stuck without a redesign `src/traces/usecases/add.ts:149-150`. `add` refuses a new round when the latest round failed at review round 2 or later `src/traces/usecases/add.ts:150-152` `src/traces/domain/trigger.ts:74`. That refusal lifts once a `judge` or a switching `redesign` exists `src/traces/domain/trigger.ts:75-77`.

`label` refuses a finding that is not in the log `src/traces/usecases/label.ts:22`. `label` prints a `STUCK` line per trigger fired in the item's latest sequence `src/traces/usecases/label.ts:36` `src/traces/usecases/report.ts:10-11`. `record judge` refuses a `--session` that is a driver session of that round `src/traces/usecases/record.ts:26` `src/traces/usecases/record.ts:49`.

`verify` with `--head` needs the last round on that head to have verdict `pass` `src/traces/usecases/verify.ts:96`. With `--any-head`, it judges the item's last round, whatever its head `src/traces/cli.ts:285` `src/traces/usecases/verify.ts:90-93`. Either way, a pass is refused while a blocking finding lacks a disposition `src/traces/usecases/verify.ts:97`. Giving both `--head` and `--any-head` is a usage error `src/traces/cli.ts:283`. With `--require-block`, a round whose brief lacks an owner-intent block is refused as `block-missing` `src/traces/cli.ts:279` `src/traces/usecases/verify.ts:110`. A lean-change round is exempt from that check `src/traces/usecases/verify.ts:101`.

`report` with `--all` exits 1 when at least one item is refused `src/traces/cli.ts:328`.

The Claude session lookup reads `AGENT_TRACES_CLAUDE_DIR` when set and non-empty `src/traces/adapters/claude-session.ts:10-11`. A lookup miss gives an empty result and does not throw `src/traces/adapters/claude-session.ts:53-62`.

`build` on the production database prints a notice, builds nothing and exits 0 `src/traces/cli.ts:486-490`. It does this unless `AGENT_TRACES_ALLOW_PRODUCTION_WRITE` is `1` `src/traces/adapters/pi/env.ts:31`.

## A-last Not read

<!-- printed -->
none
<!-- /printed -->
