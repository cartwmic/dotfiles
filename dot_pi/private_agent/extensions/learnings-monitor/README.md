# Learnings monitor

## Overview

The Learnings monitor is an opt-in Pi observer for a persisted primary
session. It looks for grounded workflow friction and plausible improvements,
then leaves them for you to review. It does not advise the primary agent,
change its instructions, or implement suggestions.

It suits a single operator who wants a machine-local review queue. Leave it
off if unprompted read access to user-readable files or uncapped model spending
is unacceptable. Enabling it changes only this session's monitor state. Pi
confirms the command in the UI; it adds no message to the primary conversation
and does not interrupt the primary agent. Agents changing the extension follow
[AGENTS.md](./AGENTS.md); the portable producer contract is in
[core/README.md](./core/README.md).

## Setup

Chezmoi maps `dot_pi/private_agent/extensions/learnings-monitor/` to
`~/.pi/agent/extensions/learnings-monitor/`. The extension is included by both
desktop profiles and is not deployed to Termux, which skips `.pi` entirely.

| Chezmoi profile | Extension | Bank in rendered Hindsight config |
| --- | --- | --- |
| `personal` | Deployed | `cartwmic` |
| `axon-work-computer` | Deployed | `work` |
| `termux` | Not deployed; Termux has no Pi extension tree | Not applicable |

The monitor follows the effective Hindsight config. If `config.json` is missing,
the loader defaults to the personal `cartwmic` bank; `HINDSIGHT_BANK_ID` can
override a rendered `work` value. The code does not lock work sessions to the
work bank. On a work host, check the effective value before enabling. After
changing the config or Pi launch environment, restart Pi so the monitor reads
it again. Opportunity notes and operational state remain machine-local outside
chezmoi source.

From the dotfiles checkout root on a personal or work desktop, preview both
the monitor and Hindsight config. Apply them after reviewing the dry-run, then
check the bank in the same environment that launches Pi. The check prints only
the bank name. Pi needs an available, authenticated model for the observer;
the Hindsight service is optional for local opportunities.

```sh
CHEZMOI_SOURCE=$(git rev-parse --show-toplevel)
PROFILE=$(chezmoi --source "$CHEZMOI_SOURCE" execute-template '{{ .profile }}')
case "$PROFILE" in personal|axon-work-computer) ;; *) exit 1 ;; esac
HINDSIGHT_CONFIG="$HOME/.pi/agent/extensions/hindsight/config.json"
MONITOR="$HOME/.pi/agent/extensions/learnings-monitor"
chezmoi --source "$CHEZMOI_SOURCE" apply --dry-run --verbose "$HINDSIGHT_CONFIG" "$MONITOR"
# After reviewing the dry-run:
chezmoi --source "$CHEZMOI_SOURCE" apply "$HINDSIGHT_CONFIG" "$MONITOR"
node - "$PROFILE" <<'JS'
const fs = require('node:fs');
const path = require('node:path');
const expected = { personal: 'cartwmic', 'axon-work-computer': 'work' }[process.argv[2]];
const file = path.join(process.env.HOME, '.pi/agent/extensions/hindsight/config.json');
const configured = JSON.parse(fs.readFileSync(file, 'utf8')).bankId;
const effective = process.env.HINDSIGHT_BANK_ID || configured;
if (effective !== expected) {
  console.error(`Unexpected Hindsight bank: ${effective}; expected ${expected}`);
  process.exit(1);
}
console.log(`Hindsight bank: ${effective}`);
JS
```

Stop before `/learnings on` on a work host if the check fails. The code can
still use the personal bank when setup is skipped or later overridden. This
guide's check cannot enforce the bank at runtime.

After applying or changing the config, quit any running Pi process and start
or resume a persisted primary from the checked launch environment. The monitor
creates its Hindsight adapter when Pi loads the extension; a shell check does
not update an already-running adapter. Monitoring starts **off** for every
primary session. Run:

```text
/learnings on
```

## Usage

Only exchanges that settle after enabling are captured; earlier session
history is not replayed. Capture is bounded and privacy-filtered, but this
filter is not a guarantee that every secret is detected. The observer may read
any file accessible to your user without an outside-workspace prompt. Its read
results can be included in its native observer transcript and sent to the
selected model provider. It has read/search tools only: no shell, edit, or write
tools.

These options apply to this primary session:

| Command | Effect |
| --- | --- |
| `/learnings focus <text>` | Set optional focus for the observer only; saved for this source and restored on resume. |
| `/learnings focus clear` | Clear the saved focus. |
| `/learnings model <provider/model-id>` | Pin the observer to a Pi model. An unavailable model fails closed and leaves activity pending; there is no silent fallback. |
| `/learnings model follow` | Follow the primary session's current model, including later model changes. This is the default. |
| `/learnings tools <read,grep,find,ls>` | Select the observer's read/search tool allowlist for this Pi runtime. You can select a subset; shell and mutation tools are rejected. |
| `/learnings tools default` | Restore the default `read,grep,find,ls` allowlist. Tool selection lasts until the extension runtime restarts. |
| `/learnings status` | Show on/off and health, pending batches/evidence, observer session path and model, selected tools, native token usage/cost, and failures. |

A model override and focus persist for the source. By default, changing the
primary model also changes the observer's provider and may send captured
context to that provider. Use an explicit model override to keep the observer
on a selected route.

The observer uses native Pi session accounting. `/learnings status` reports its
cumulative tokens and provider-reported cost once available. There is **no
product-enforced spending cap**. Check status and use `/learnings off` to stop
automatic capture and abort in-flight observer work. Pending evidence is
retained; `/learnings flush` is an explicit review action, or turn monitoring
on again to resume automatic processing. Off cancels only the observer; it
does not abort the primary agent or disable the independent Hindsight
auto-retain extension.

Monitoring requires a persisted session. `/learnings on` is refused in
`pi --no-session` runs. Normal observer passes run separately from the primary
agent and do not add messages to its conversation.

## Pending work and review

The configured batch threshold is three settled exchanges by default. Use
`/learnings flush` to request processing before the batch fills. A flush does
not add a message to the primary conversation. If Pi exits with activity still
pending, shutdown does not wait for a model call; the work remains on disk and
`/learnings status` shows what remains.

Review the current source with:

```text
/learnings-review
```

Use `/learnings-review all` to list every source on this machine, or
`/learnings-review <source-id>` for one source. The output includes status,
evidence and branch provenance, pointer availability, and each record's exact
Markdown path. A missing original Pi session is shown as unavailable rather
than treated as verified evidence.

- `/learnings-keep <record-id> [source-id]` and
  `/learnings-dismiss <record-id> [source-id]` update the authoritative
  Markdown status and review history. Dismissed duplicates stay suppressed
  unless new evidence or a materially different intervention warrants a new
  proposal.
- `/learnings-review patterns` explicitly requests cross-source grouping when
  Pi is idle and there are eligible records from at least two sources. It uses
  bounded note text and the current Pi model, may incur model cost, changes no
  opportunity Markdown, and does not run after every batch.

### Edit records on disk

The local store defaults to `~/.local/share/pi/learnings-monitor/`, or to
`$XDG_DATA_HOME/pi/learnings-monitor/` when `XDG_DATA_HOME` is set. Each
source's records are Markdown files under `sources/`; Pi review prints the
exact path. You can edit the Observation and Recommendation text directly.
Pi rereads that Markdown for review and preserves those edits during later
updates. Use the keep/dismiss commands for status so the review history stays
consistent. These files are local review data. Chezmoi does not manage or
sync them. Keep sensitive content out of the public source.

## Observer Pi sessions

Each monitored primary gets one persistent native Pi observer session in the
ordinary Pi session store. The session is named `Learnings observer · <id>` and
its path appears in `/learnings status`. It can be opened with Pi's normal
session picker or by passing that path to Pi's usual `--session` option. A
resumed primary continues its observer; a new or forked primary gets a
separate one. Observer sessions are marked so this monitor never captures
them as primary work.

Observers use ordinary Pi sessions. Those sessions remain in the session
store and may appear in general session search or other local indexers.
Turning monitoring off or deleting the primary session does not remove the
observer or its Learnings records.

## Hindsight boundary

Related Hindsight search is optional and fail-open: an empty, slow, or failed
lookup does not suppress a locally grounded proposal or block the primary
agent. A Hindsight match is labeled a **possible analogue**. Recurrence requires
distinct local source evidence. Pattern review is also operator-initiated; it
does not promote notes automatically.

To retain an opportunity in Hindsight, first keep it, then run:

```text
/learnings-promote <record-id> [source-id]
```

Pi previews the exact Observation and Recommendation text and the destination
bank, then asks for confirmation. Raw evidence and source pointers are not
included. Cancellation sends nothing. A success means Hindsight accepted an
asynchronous request; it does not mean the memory is already searchable. The
local Markdown remains authoritative, and `/learnings off` does not change the
separate Hindsight auto-retain behavior.

## Troubleshooting

- `/learnings on` refuses in `pi --no-session`: start or resume a persisted
  Pi session, then enable monitoring there.
- Status shows pending work and an unavailable observer model or missing
  provider authentication: configure Pi's credentials for that provider, or
  select an authenticated model with `/learnings model <provider/model-id>`.
  `/learnings model follow` returns to the primary model; use
  `/learnings flush` to retry retained work.
- A Hindsight lookup fails: local opportunities can still be written. Check
  `/learnings status`; repair the existing Hindsight configuration if you want
  analogues or promotion.
- The bank check or promotion preview names an unexpected bank: the rendered
  config may be missing, or `HINDSIGHT_BANK_ID` may override it. Reapply the
  correct profile's Hindsight config and launch environment, repeat the
  effective-bank check, and restart Pi before enabling or promoting.
- Review has no new note after exit or `/learnings off`: check pending work in
  `/learnings status`. Resume the primary and turn monitoring on, or flush the
  saved batch explicitly.

## Cleanup

To remove a source's local records and owned observer session, first turn
monitoring off, then run `/learnings-cleanup [source-id]` and confirm. Without
a source ID Pi selects the current persisted source when possible; otherwise
it requires you to choose one from `/learnings-review all`. Cleanup removes
that source's notes, pending batches, checkpoint, and verified owned observer
session file. It can discard pending, unreviewed activity, and it does not
remove records for other sources. No cleanup happens automatically when you
turn monitoring off, delete a primary session, or change machines.

## Validation

From the dotfiles checkout root, run the completed operator journey and
isolated work-profile render:

```sh
python3 tests/learnings-monitor/proof.py
python3 tests/learnings-monitor/profile-proof.py
```

The focused component and portable-core commands are in [AGENTS.md](./AGENTS.md)
for contributors.

The full Pi proof uses a private PTY and temporary HOME, session, and data
roots. Scripted loopback model and Hindsight endpoints exercise read-tool use,
held-observer status, saved-but-unqueued recovery, cosmetic dismissal retry,
branch/fork isolation, cancellation, and promotion. Focused tests cover
cleanup. The profile proof renders the work bank in a disposable HOME; it
does not exercise a missing config or a launcher override. These checks do not
contact live model or Hindsight services and do not apply source to the user's
HOME. Check `/learnings status` for pending work in actual use.
