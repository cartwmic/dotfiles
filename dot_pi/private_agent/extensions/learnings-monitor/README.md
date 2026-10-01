# Learnings monitor

## Overview

The Learnings monitor is an opt-in Pi observer for a persisted primary
session. It looks for grounded, reusable process lessons—non-obvious failure
modes or decision rules that could help on a different task—then leaves them
for you to review. One-off corrections, preferences, and restatements of
requests are not intended as opportunities; an empty batch is fine. The model
can still get this judgment wrong. It does not advise the primary agent,
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

Source changes alone do not deploy this extension. From a feature worktree,
use `chezmoi --source "$CHEZMOI_SOURCE"` for every preview and approved apply;
never hand-edit the managed live extension. Inspect the effective read-source
hook first (even dry-run can run it), require `op` already available and owner
1Password access on personal desktops, and preserve the host config. The
read-only `tests/learnings-monitor/source-preview.py` records hashes without
printing rendered content or secrets. Live apply needs separate owner approval.
Tests remain source-only and ignored by chezmoi. These component README and
AGENTS guides are managed extension files and included in the targeted preview.

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

`/learnings` opens **Learnings home**: Review, Status, On, Off, Focus,
Model, Tools, Flush, Patterns, Promote, Cleanup. Settings/management entries
request arguments. Each home entry includes a short explanation. Only
`/learnings` is registered, without aliases.

`/learnings review` opens terminal-only **Learnings review**, initially
**Current session · Pending**. The compact list shows source, effective status
and queued Promote. Scrollable details show original recorded local time and
relative age (unknown for legacy records), evidence, provenance, history and
Markdown path. Closing restores conversation without a review dump.

- ↑/↓ select; PgUp/PgDn scroll details.
- `k` stages Keep; `d` stages Dismiss and clears promotion; `p` toggles queued
  Promote only for effectively kept items; `u` resets the selected draft.
- `s` opens **Review scope**: Current session, All local sources, or named
  source with exact id. `f` cycles Pending, Kept, Dismissed, All.
- Esc exits. Dirty drafts open **Staged Learnings decisions**: **Apply**,
  **Discard**, **Continue**. Cancel means Continue. Drafts and selection survive
  scope/filter/Continue. Selected choices remain visible until navigating away.
  Apply saves local statuses before exact promotion preview/confirmation;
  cancellation/failure of promotion leaves Keep saved. Discard writes/sends nothing.

Without custom terminal support, use `/learnings list [source-id|all]`,
`/learnings keep <record-id> [source-id]`, `/learnings dismiss <record-id>
[source-id]` and management subcommands. Review outside terminal mode fails
explicitly, without mutation or sending fallback. Missing original sessions
are shown as unavailable. Dismissed duplicates remain suppressed unless new
evidence or a materially different intervention warrants a new proposal.

`/learnings patterns` explicitly requests cross-source grouping while idle
with eligible records in at least two sources. It uses bounded note text and
the current model, may incur model cost, changes no opportunity Markdown,
and never runs automatically.

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
/learnings promote <record-id> [source-id]
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
monitoring off, then run `/learnings cleanup [source-id]` and confirm. Without
a source ID Pi selects the current persisted source when possible; otherwise
it requires you to choose one from `/learnings list all`. Cleanup removes
that source's notes, pending batches, checkpoint, and verified owned observer
session file. It can discard pending, unreviewed activity, and it does not
remove records for other sources. No cleanup happens automatically when you
turn monitoring off, delete a primary session, or change machines.

## Structured adapter interface

`review.mjs` exports `createLearningsReviewCommands(surface, sdk)`,
`createReviewDraft()` and `reviewIdentityKey(identity)`; `review.d.mts` declares
all row, scope, draft and result shapes. The UI can use these operations without
assembling command strings or asking the operator for IDs:

- `query({ scope, status }, ctx)` returns `{ sources, rows, scope, status, root }`.
  Scope defaults to `"current"` (no current persisted source means an empty
  queue), or accepts `"all"` or `{ sourceId }`; status defaults to `"open"`.
  Each row contains the exact `{ sourceId, id }` identity, source summary,
  authoritative record, Markdown `path`, and plain-text `detail`.
- `createDraft()` (also `commands.createDraft()`) owns only one interaction's
  choices. `stage(row, "kept" | "dismissed")`, `togglePromotion(row)`,
  `get(row)`, `reset(row)`, `entries()` and `clear()` never write or send.
  Dismiss clears queued promotion; reset removes only that row's choice.
  Keep the draft through scope/filter changes. Discard calls `clear()`.
- `apply(draft, ctx)` rereads records and saves all chosen local statuses first.
  It returns `applied`, `errors`, `promotions` and `remaining`; successful writes
  are not rolled back on another file's failure. Failed local choices stay in
  the draft. No promotion is offered for a failed local Keep. Untouched records
  are not status-written. Promotion errors or cancellation do not revoke Keep.
- `promoteRecord(row, ctx)` uses the exact source/id and fresh kept Markdown,
  preserving the existing exact-text/bank confirmation and memory token boundary.
  It is for applied records, not a replacement for queued draft promotion.

`store.d.mts` exposes `StoredOpportunityRecord`, extending the portable record
with optional `recordedAt`. The store sets it only at first record-file creation
and preserves it through updates. Missing or invalid legacy timestamps stay
unknown; there is no migration or filesystem-time fallback. Portable core
identity and producer contracts remain unchanged.

## Validation

From the dotfiles checkout root, run the completed operator journey and
isolated work-profile render:

```sh
python3 tests/learnings-monitor/proof.py
python3 tests/learnings-monitor/ui-proof.py --scenario all
# Focused staging journey during implementation:
python3 tests/learnings-monitor/ui-proof.py --scenario stage
python3 tests/learnings-monitor/profile-proof.py
# Read-only worktree mapping/render/live-hash/targeted dry-run (never applies):
python3 tests/learnings-monitor/source-preview.py
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
