# Pi recap

Independent recap UX for interactive desktop Pi (`personal` and
`axon-work-computer`), not RPC/print/JSON or local Termux. It does not need
Herdr. Existing standalone CLI settings and legacy recap records are not
imported. New defaults follow the current Pi model and enable all three
supported automatic triggers; explicit saved choices, including false, remain.

## Commands and settings

Type `/recap ` to see native, described argument completions; Tab selects a
verb or contextual history filter/settings scope. `/recap help` opens a
transient scrollable command guide; Escape returns without generation,
reservation, coverage changes or interrupting Pi's agent. Bare `/recap` still
generates incrementally, not help.

Start with `/recap settings` for session overrides or `/recap settings defaults`
for future defaults. By default each request captures the current Pi model;
an explicit recap model override stays independent of later main-model changes.
Neither choice changes the main model or its options. Each selectable field has
muted help and identifies inherited, session or default scope. Settings include
instructions, independent generation options, mode, 60-second whole-attempt
timeout, recursive reduction (off initially), completed cadence (every final
response), periodic interval (15 minutes while active), and before-compaction
automation. All three automatic triggers default on; explicit persisted false
values remain off. Existing `create_` configs are not migrated.

The at-most-two-line muted widget above the editor shows truthful `Recap running`
once the detached job is accepted, including while preflight is blocked and before
the first save. With a prior success it retains that recap's update time and excerpt;
without one it says no recap has been saved yet. Completion, failure, unsaved output,
cancel and supersession clear only the matching running state. New sessions/forks
and incompatible branches hide foreign jobs. Reload recovers a matching captured job
from durable request state, polling through fresh-context commands until it finishes.
Saved results show the actual last successful update time and width-truncated excerpt. `/recap view` opens
the current compatible saved narrative in the scrollable viewer; PageUp/PageDown
scroll and Escape returns to the editor without generating, canceling work,
changing coverage or adding a conversation message. Failure/unsaved warnings
remain brief and do not replace the latest success. No-new/full reuse preserves
its original update time.

`timeZone` defaults to `local`; `UTC` and named IANA zones are also supported.
Widget, history and viewer timestamps show date-specific offsets/zones (including
DST). Invalid input is rejected before saving. This is presentation only:
canonical UTC records and generation fingerprints are unchanged.

Manual and enabled automatic requests share saved active-branch coverage.
`/recap` selects new observed conversation/tool outcomes; `/recap full` selects
the branch snapshot. Thinking and recap output are excluded. Matching full
snapshots can be reused. A no-new request keeps the latest compatible recap widget
without another generation. Success covers only the captured end, not later
work. Failed or unsaved output never advances coverage. Prior narrative is
background only. Fork/clone histories start independently; inherited defaults
remain distinct from saved session overrides.

Newest requests supersede unfinished work. `/recap cancel` cancels recap work,
not Pi's agent. Generation/storage failure gets one immediate retry. Recursive
reduction requires explicit opt-in, discloses compression, and remains under
the whole-attempt timeout; oversize opted-out input fails rather than truncates.
Unsaved output carries a brief warning, not a narrative dump. An uncanceled captured job survives
switch, reload and shutdown, including while virtual routing metadata is blocked,
and saves only for its original session. Departure is not cancellation; only
cancel or a newer original-session reservation invalidates work. UI epoch/session
checks authorize consumption, not durable execution.

History retains recaps and safe metadata until manual cleanup. No raw input,
backend argv/auth or stderr archive is intended. The backend receives selected
public conversation/tool content; recap narratives themselves are stored.
History review does not change coverage. Legacy history has no invented new
coverage or migration. The optional overview adapter consumes saved records
and owns native attribution; it never configures or generates Pi recaps.

## Implementation and proof boundaries

`index.ts` registers `/recap`, `/recap view`, `/recap full`, `/recap cancel`,
`/recap settings [defaults]`, `/recap help`, and `/recap history [all|attempts|legacy]`.
History filters can combine (for example `history all attempts` or `history legacy attempts`).
Settings default to session scope, with sparse overrides and explicit clearing.
The independent model picker does not change the conversation model.
History uses a searchable selector and a keyboard-scrollable dim viewer.

Requests are captured into a private temporary file and handed to a detached,
unreferenced Python supervisor. Shutdown closes the result pipes, not the job.
Saved records are recovered for the original session and emitted as
`recap:saved {recordId, sessionId, historyId}` without native membership.
Saved output uses the compact TUI widget and opt-in viewer, never conversation
messages or full narrative notifications.
The internal delivery command refuses dispatch after shutdown or when absent.
Queued outcomes are checked against session, local generation and durable token.

Automation defaults on, with explicit persisted opt-outs retained. Settlement
recaps count only final
`agent_settled` events, including errors/aborts, with the configured cadence.
Pre-compaction captures and hands off without awaiting generation. All triggers
share the configured mode and authoritative saved coverage.

Periodic progress starts a full interval on a new active stint (15 minutes by
default). Internal turns, tool updates and retries do not restart it; successful
publication does. Settlement and departure stop it. Timers dispatch a guarded
command to obtain fresh context, never retain a context. Public assistant/tool
observations are labeled partial/ongoing; finalized entries replace them. No-new
periodic checks quietly retain the latest compatible saved widget without a
backend call or duplicate record. No idle/exit trigger.

Earlier `automation-pty.py` receipts exercised the prior notification/setup UX
with a 1.2-second interval; those retained historical outcomes are not proof of
this follow-up. The focused `ux_followup.py` public journey and
`helpers.test.ts` cover current defaults and quiet delivery. Fixtures and test
runners are source-only, excluded from deployment.

Focused disposable-Pi journeys also cover populated history typed search/view/scroll,
session settings persistence through resume, defaults editing and inheritance,
and public tree/fork/clone coverage and independent histories. Cancellation,
buffered generated-unsaved output consumed after cancel, switch/return,
reload/shutdown with gated captured work and original-session resume have named
proof cases. These focused checks are not a final stable-tree matrix or rollout
approval.

`restoreState(nativeSessionId, states)` receives all owned custom entries in file
order, not only active-branch entries. A foreign native identity cannot supply
history or overrides. Persist its returned identity before submitting a request.
`setOverride(..., undefined)` clears inheritance overrides; `resolveSettings`
merges sparse top-level overrides against current defaults. `options` is an
atomic generation-settings field, not a nested sparse override.

`project(branchEntries, liveUnits, aliases)` excludes custom recap output and
thinking. The controller must maintain explicit live-to-final entry aliases;
unmapped ephemeral units must have `verifiable: false`. It must clear live units
on session replacement and branch changes. Tool execution observations may be
supplied as live units with honest ongoing/queued/failed labels. Final transcript
messages replace live projections. Never match identities using equal text.

`uncovered` requires an active branch ancestry and saved authoritative coverage.
It accepts only matching verified prefixes, with status changes uncovered.
`capture` receives the complete snapshot, not the incremental suffix; its coverage
is the captured end only. Use its `material` or the separately selected uncovered
material as input. Only successful authoritative saved records establish coverage.
Compare full `fingerprint` plus branch compatibility for reuse. Prior recap text
is background, never a coverage unit.

`backendCommand(getPackageDir, helper, agentDir, cwd, settings)` builds private
argv using the installed public SDK. Persist only safe provider/model identity,
not argv. The worker loads host resources for registrations but never prompts or
binds extensions. Public `ModelRuntime.resolveModel` resolves each virtual
`direct` request before `completeSimple` calls its physical model.

Before handoff, physical limits come from public `ctx.modelRegistry.find` metadata;
virtual limits use the Pi-owned no-generation SDK helper inside each detached
CLI attempt (display metadata is not a limit). Pi never hosts an asynchronous
budget query. The private request includes optional generic `preflight.command`;
`backend.mjs --preflight` returns only the effective input byte budget and opaque
backend argv adjustments. The CLI owns its process group, current-token fence,
retry and one deadline spanning preflight, startup, every reduction/final call
and save. A blocked route helper is actually stopped on cancel/supersession,
without opening a gate or retrying. Captured virtual fingerprints identify
original settings and public material, not yet-unknown effective route metadata;
physical fingerprints also include their synchronously known derived ceilings.
`inputBudget` and `options.maxTokens` remain user ceilings, not permission to exceed
the model. Output is capped at the model ceiling and one quarter of its context.
Both paths share one budget calculation. Input uses a conservative one-UTF-8-byte-per-token upper bound, subtracting system
instructions, 1024 tokens of framing/reduction overhead and the output allowance.
With reasoning on, reserve the entire model output ceiling because some adapters
add thinking tokens to `maxTokens`. Unknown/unusable budgets refuse safely; saved
preferences are unchanged and source is never truncated. Each actual chunk/final
call checks its resolved route again; virtual display limits or a changing router
cannot bypass the bound. Only a nonblank response with explicit normal `stop`
succeeds; unfinished/error/aborted outcomes use the existing safe failure/one-retry
path without advancing coverage.

Both control and detached jobs use `~/.local/bin/session-recap` and its maintained
`SESSION_RECAP_PYTHON`/compatible PATH/mise interpreter selection. The private
`PI_RECAP_CLI` script override is mapped only into the child's generic
`SESSION_RECAP_IMPLEMENTATION`; process-wide environment is unchanged. Its executable guard resolves path aliases
so macOS `/var` temporary paths invoke the worker correctly. Runtime-only providers absent from those resources fail rather
than falling back. The CLI controls deadline/retry/recursive reduction; every
recursive call uses the same explicit backend configuration.

Tests: `node --test dot_pi/private_agent/extensions/recap/helpers.test.ts dot_pi/private_agent/extensions/recap/backend.test.mjs`.
The backend unit test is scripted at the SDK boundary. The separate `backend`
proof section drives the installed SDK/helper and delivered CLI with a scripted
provider, explicit and virtual model routing, and runtime-only fixture auth.
Source-scoped native chezmoi previews and live rollout remain pending.
`tests/pi-recap/limits.py` adds genuine Pi journeys for explicit/fallback Python,
reduction/final length failures and safe follow-up, and default/explicit physical
plus virtual small-model budgets with recursion off/on. These are wired into the
lifecycle dispatcher. `RECAP_PROOF_FINISH=length python3 tests/pi-recap/backend.py`
checks installed-SDK physical/virtual length normalization and CLI safe retry.

The source-only `tests/pi-recap/ux_followup.py` journey covers the new defaults,
follow-current capture and override, phone/wide help/widget/view, timezone reuse,
resume/new-session isolation and active periodic/pre-compaction behavior. It uses
a disclosed 1.2-second interval, private resources and an input-derived provider.
Older receipts remain historical; they do not validate changed UI/defaults.

Source-root proof commands (no deployment or paid backend):

```sh
python3 tests/pi-recap/proof.py cli --case native-cli-timezone-public
# Use a private Python with pyte/wcwidth (see tests/pi-recap/current_screen.py).
RECAP_DISCOVERY_EVIDENCE=/tmp/recap-discovery-proof python3 tests/pi-recap/proof.py tui --case recap-discovery-running-public
python3 tests/pi-recap/proof.py tui --case defaults-quiet-view-current-model-timezone-public
python3 tests/pi-recap/proof.py cli
python3 tests/pi-recap/proof.py backend
python3 tests/pi-recap/proof.py tui
python3 tests/pi-recap/proof.py lifecycle
python3 tests/pi-recap/proof.py overview-isolated
python3 tests/pi-recap/proof.py profiles
git diff --check
```

The driver emits named observations, exact subprocess commands and failures.
Use `--case NAME` to dispatch only one existing named case in a section, without
starting other cases. `supervised-preflight-{switch,reload,shutdown,cancel,newer,deadline}-public`
retains failing-before/fixed-after journeys through real Pi and the delivered CLI:
original-session survival and recovery without duplicate/no-new work, closed-gate
process termination before release, and two complete deadline-bound attempts with
pending coverage followed by a safe save. Native manual/threshold compaction
finishes while preflight is gated and later saves the original removed material.
Older guard receipts requiring abandonment on departure are superseded evidence,
not the current AC-12 contract.
`backend` includes installed-SDK explicit/virtual routing and authenticated CLI
publication/privacy. `lifecycle` runs real-Pi manual/full reuse, populated history,
settings/defaults/resume, tree/fork/clone, cancellation, buffered generated-unsaved
consumption, and captured switch/reload/shutdown/original-resume journeys. Its
privacy cases inspect reasoning exclusion and runtime-auth live-error sanitization,
retry and coverage-preserving follow-up across records, model requests, transcript
and captures. Cases fail closed on failed assertions or unavailable prerequisites;
no overall AC completion is implied. The driver still owns the final stable-tree
matrix, including privacy rechecks, and native overview execution. Profile mapping
runs against hook-free private configuration,
not the owner's effective config. Native preview requires the root-guide
config/hook/1Password preflight and independent rendered/live reads. Do not
apply or commit based on this guide.
