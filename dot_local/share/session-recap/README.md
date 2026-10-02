# session-recap

Portable stdin-to-command generation and local recap history, independent of Pi
or Herdr. Python 3.11+ is required. The wrapper selects `SESSION_RECAP_PYTHON`,
then compatible `python3` on PATH, then the user mise shim, in that order.
`SESSION_RECAP_IMPLEMENTATION` optionally selects an alternate Python script
for a wrapper invocation; otherwise the maintained installed implementation is used.

## Configuration

Desktop profiles `personal` and `axon-work-computer` deploy configuration to
`~/.config/session-recap/`; Termux does not deploy this CLI. Managed
`config.toml` has `auto_publish = false` and no backend. Supply an unmanaged
`config.local.toml`:

```toml
command = ["/path/to/my-recap-command", "--stdin"]
```

Local values override managed values. The command runs directly, without a
shell. Editable `single-prompt.md` uses `[[TEXT]]`/`[[LABEL]]`; `group-prompt.md`
uses `[[MEMBERS]]`/`[[LABEL]]`. Nonblank UTF-8 stdout is the recap; stderr is not
archived. `config auto-publish` reports the standalone policy. Pi owns its own
settings and must not inherit the CLI backend or automation policy.

## Commands

Existing standalone invocations remain supported:

```sh
printf '%s\n' 'Recent changes and present state.' | session-recap create --kind single
printf '%s\n' '{"members":[{"label":"parser","text":"Done","record_id":"optional-id"},{"text":"Migration next"}]}' |
  session-recap create --kind group --label 'Release preparation'
```

Successful create prints the record ID, not the narrative. Both kinds accept
arbitrary nonblank `--source-kind KIND`, `--source-id ID`, and
`--metadata-json '{"caller":"value"}'`. Defaults are source kind `manual` and
the generated record ID as source ID. Group member IDs are retained without
imposing coordinator identity or membership policy.

```sh
session-recap list --json [--source-kind KIND --source-id ID --status STATUS]
session-recap read ID --json
session-recap annotate ID --namespace NAME --metadata-json '{"group":"id"}'
```

List returns `{"records":[...]}`, ordered by creation time and ID; read and
annotate return `{"record":{...}}`. Reads need no backend configuration.

Timestamp presentation defaults to the host's local timezone. Set
`time_zone = "America/New_York"` in `config.local.toml`, or override it with
`--time-zone local|UTC|IANA_NAME` on `create`, `list` or `read`. Invalid zones fail
before generation or store mutation. `list` without `--json` shows timestamps;
`read ID` prints only the narrative, while `read ID --with-metadata` adds a
zone/offset-aware timestamp and identity. JSON keeps canonical UTC record
values unchanged and adds a separate top-level `presentation` object. Named
zones and local display use the timestamp's DST offset; record files and dated
paths are never rewritten for a presentation change.

Annotate atomically replaces only the named annotation namespace under the
store lock, preserving narrative, status, identity, times, member IDs and
caller metadata (including coverage). Missing/ambiguous IDs, unknown schemas,
invalid JSON and non-object metadata fail nonzero.

## Fenced captured requests (envelope v1)

```sh
session-recap reserve --key KEY --json
session-recap current --key KEY --json
session-recap cancel --key KEY --json
session-recap run --request-file /private/request.json --json-lines
```

Reserve atomically replaces the current token with an opaque token and status
`reserved`. Current returns `{request_key, token, status}` (plus `record_id`
when saved); absent keys return null token/status `absent`. Cancel invalidates
any token with null token/status `canceled`. No stored PID is signaled. Keys
are arbitrary caller identities, not Pi session policy. Successful older
history survives replacement. A token permits one accepted supervisor only.

The caller creates a complete private UTF-8 JSON file (mode 0600), then may
spawn/detach the CLI itself. The CLI loads and deletes that input, including
on validation failure. It neither owns detachment nor reads CLI configuration
for this path. Required envelope fields:

```json
{
  "schema_version": 1,
  "request_key": "caller-owned-key",
  "token": "opaque-token-from-reserve",
  "kind": "single",
  "source_kind": "arbitrary-caller",
  "source_id": "arbitrary-source",
  "label": "optional label",
  "material": "complete captured new material",
  "background": "optional preceding recap; background only",
  "command": ["/path/to/backend", "--stdin"],
  "instructions": "Explicit generation instructions",
  "timeout_seconds": 60,
  "recursive": false,
  "input_budget_bytes": 32768,
  "backend_identity": {"provider": "safe-name", "model": "safe-name"},
  "metadata": {"caller": "opaque values"}
}
```

`kind` is single/group; callers supply group material explicitly. Label,
background, backend identity and metadata are optional. Backend identity allows
only provider/model strings; do not put auth or private values there. Metadata
is an opaque object, with the same no-secret/no-transcript obligation as create.
The exact input budget includes the rendered instructions/background/material
or reduction instructions/chunk, measured in UTF-8 bytes. Recursion off rejects
oversize before any backend calls. Recursion on covers every chunk, prefers
whitespace boundaries, recursively combines all reductions, requires shrinking,
and discloses reduction in the final narrative. It never truncates unresolved
material to fit. A backend must preserve facts; the CLI cannot verify model
semantics. Nonshrinking/unfinished pipelines fail without successful coverage.

Optional `preflight: {"command": ["/path/to/caller-helper", "--preflight"]}`
runs inside **each** whole attempt, before recursion/generation. The helper gets
exactly captured `material` on stdin (not background or generic framing). Its
UTF-8 stdout must be a JSON object containing `input_budget_bytes`, a positive
integer no larger than the envelope's ceiling, and optionally `command`, a
complete nonempty backend argv. Unknown output fields and invalid output fail
the attempt. No other envelope fields can change: source, identity, metadata,
coverage, fence, recursion and timeout remain captured. The CLI does not interpret
provider/model options in argv. Caller policy belongs in the helper; raw helper
argv/input/output/stderr are never archived. Existing requests without preflight
are unchanged. Preflight startup, routing, output validation, backend startup,
all reductions/final generation and authoritative save share the same monotonic
attempt deadline and token fence. Cancel/supersession kill the currently owned
process group even while the helper is blocked; genuine failure gets one complete
retry including preflight, never a separate helper retry or deadline.

JSON-lines events always include `event`, `request_key`, `token`, `status`:

- Accepted: `event: "accepted", status: "running"` after the locked claim.
- Successful optional preflight: `event: "preflight", status: "running", attempt,
  input_budget_bytes`. This is progress, not publication or coverage permission.
- Saved terminal: `event: "terminal", status: "published", record_id, attempt`.
- Failure terminal: `status: "failed", attempt, failure: {message}`. A whole-attempt
  deadline failure includes `failure.reason: "timed_out"`. The same trusted reason
  and safe `message: "attempt deadline exceeded"` are exposed by list/read for
  those failed attempts; status remains `failed` (no successful coverage).
  Other failures do not acquire a timeout reason from backend text.
- Generated but unsaved terminal: `status: "generated-unsaved", attempt,
  failure: {message}, text, warning`. Text is observable live even when storage
  cannot write; warning says no coverage advanced.
- Invalidated terminal: `status: "canceled"` or `"superseded"`; `attempt` is
  present if generation began. No text is delivered from an invalidated job.

Failed/canceled/superseded terminals include `record_id` when their attempt
record was saved; no ID is invented when persistence fails.

Validation errors are nonzero stderr, before acceptance. Accepted jobs report
outcomes through events (exit zero), so consumers must inspect terminal status.
Consumers **must** re-read current token and verify their own session/local
request generation immediately before consuming any event, especially buffered
unsaved text. A previously emitted event is not consumption authorization.

Each whole attempt has its own monotonic deadline spanning startup, every
recursive call and authoritative commit; generation/storage failure gets one
immediate whole-attempt retry, never cancel/supersession. Only owned preflight/backend
process groups are killed. Polling checks deadline/token every 50 ms; the store
lock fences authoritative dated creation, with a final check before linking.
Broken live pipes and caller departure do not prevent saving. A dated commit
is successful even when latest/request convenience updates fail. Attempt
records expose safe identity, request token/key, attempt number and reduction
flag, never argv/input/stderr. Generated-unsaved text is live-only if storage
is unavailable. History never treats failed/unfinished work as published.

## Record contract and retention

Data lives in `${XDG_DATA_HOME:-$HOME/.local/share}/session-recap/`:

- `records/YYYY-MM-DD/<record-id>.json`: authoritative dated history
- `latest.json`: best-effort latest-success/last-attempt convenience index

Generic v2 records retain `schema_version`, `record_id`, `source_kind`,
`source_id`, `kind`, `status`, `created_at`, optional `label`, and group
`member_record_ids`. Published records include `summary` and `published_at`;
failed records contain safe failure information. `metadata` and namespaced
`annotations` are opaque JSON objects: callers own their meaning and must not
put secrets or raw transcripts in them. The CLI does not archive backend argv,
auth, input or stderr. Backend stdout is retained only as the requested recap.

A dated successful write is success even if indexing fails. Listing scans
history rather than trusting the index. Generation failure, nonzero exit,
invalid UTF-8 and blank output preserve earlier successes and save failed
attempts. History remains until manual cleanup; there is no automatic deletion.

V1 records remain visible with their original schema version and known
identity/narrative/time/member fields, not invented v2 coverage. Structured
reads drop uncontracted legacy metadata/annotations and sanitize legacy failure
messages. New v1 annotations use a separate safe namespace container without
rewriting its narrative or claiming migration. Original legacy files are not
bulk rewritten or deleted.

The Pi-specific `prepare`/`publish`/`prompt` commands are retired and rejected
before backend invocation or storage mutation. Existing prepared and current
prompt files remain untouched and are not listed as recap history. Published
legacy recaps remain readable. Pi prompt/recap ownership and native Herdr
identity/membership belong to their respective adapters, not this CLI.

## Validation and deployment

From the source root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/session-recap -p 'test_*.py' -v
python3 tests/pi-recap/proof.py cli
python3 tests/pi-recap/proof.py profiles
# test_requests.py drives the public CLI for fences, retry, recursion,
# storage faults, owned descendants, broken pipes and detached host exit.
```

These use disposable data and a fake backend, including actual wrapper CLI
single/group creation, history reads, annotations, failures and interpreter
selection. Never call a paid/owner backend for storage checks. Follow the root
AGENTS preflight and approval rules before source-scoped chezmoi previews or
live applies; no live apply is implied by these examples.

Failed supervised backends may return exactly
`SESSION_RECAP_FAILURE:context_limit\n` or `SESSION_RECAP_FAILURE:model_limits\n`
on stdout with a nonzero exit. Only these closed reason codes cross UI/history
boundaries; stderr is discarded and arbitrary failure output remains redacted.
Transport oversize and timeout have supervisor-owned `input_limit`/`timed_out`
classifications. This protocol does not select models or impose caller policy.
