---
name: using-loop-engine
description: Use when creating, resuming, advancing, inspecting, auditing, or terminating a durable loop-engine workflow run, or when the user mentions loop-engine, a workflow provider executable, run requests/gates/evidence, or LOOP_ENGINE_HOME.
---

# Using loop-engine

## Overview

`loop-engine` is a local, single-user, offline CLI that owns durable run state, lifecycle, evidence, and an append-only journal for workflows supplied by external provider executables.

**Core principle:** the engine coordinates work; it does not perform it. The provider owns the workflow graph and gate policy. You (the caller) perform the primary work outside the engine. Never edit engine SQLite state, and never treat a gate as an executor of side effects.

**Announce at start:** "I'm using the using-loop-engine skill."

## When to Use

- Starting, resuming, or driving a run against a registered provider
- Recording evidence, notes, or corrections against a run
- Auditing a run (`run history`, `run export`) or closing it out (`run terminate`)
- Diagnosing a `rejected` or `error` outcome from `loop-engine`

**Do not use** for: general workflow design, provider authoring (see the loop-engine repo's `examples/providers/reference-go/README.md`), or any attempt to script around the CLI by touching `state.db`.

## Ground rules

| Rule | Why |
|---|---|
| Always pass `--format json` before the subcommand | Only structured output is a contract; human output is for people |
| Treat `operation`, `outcome`, `reason`, `data`, `request_id`, `trace` as one correlated result | Exit code + reason code decide the next action |
| Never infer semantic outcome from `diagnostics` alone | Diagnostics are ancillary |
| `--list-operations` is authoritative for the installed binary | 21 operations; do not invent routes or aliases |
| `LOOP_ENGINE_HOME` selects the catalog + database | Changing it switches to a different world of providers and runs |
| Request only events returned in `data.requestable_events` | Events are graph-owned, not caller-invented |

Exit codes: `0` completed, `2` rejected (domain denial — not infrastructure failure), `1` error, `64` pre-dispatch failure (usage, config, platform, persistence open).

`completed` means the operation achieved its purpose — **not** that something was committed and **not** that findings were positive: `provider check`, `run compatibility`, and `run graph` complete with exit `0` while reporting incompatibility.

## Start or resume

```bash
loop-engine --format json --list-operations
loop-engine --format json provider list
loop-engine --format json run list --all
loop-engine --format json run show <RUN-ID>
```

Resume a known run with `run show`. Prefer an existing provider registration. Register a new provider **only** when given an explicit executable path and working directory:

```bash
loop-engine --format json provider add <HANDLE> \
  --exec <ABSOLUTE-PATH> --working-directory <ABSOLUTE-DIR> \
  [--arg <VALUE> ...] [--timeout <SECONDS>]
loop-engine --format json provider check <HANDLE>
loop-engine --format json run create <HANDLE> \
  [--label <LABEL>] [--inputs <JSON-FILE>]
```

`provider check` runs the real provider `describe` and validates its graph — do it before creating runs. Default provider timeout is 60s; raise it with `--timeout` for slow gates. The provider's documentation defines the `--inputs` object; inputs are immutable after creation. The new run ID is at `data.run.id`.

## Drive the workflow

Repeat until `data.run.lifecycle` is `final` or `terminated`:

1. `run show` — read current state, `requestable_events`, `requestable_event_details` (target state + `required_gates`), `static_guidance`, and the `live_guidance` capability flag.
2. Read `run graph` if you need stored topology. It is provider-free and cheap.
3. Perform the requested primary work **outside** the engine; produce the artifacts the provider expects (kinds and conventions come from `static_guidance`).
4. Append or select evidence when the workflow requires it.
5. Request exactly one listed event, then inspect the outcome and the journal.

```bash
loop-engine --format json run evidence add <RUN-ID> \
  --kind <KIND> --ref <OPAQUE-LOCATOR> [--digest <DIGEST>] [--media-type <TYPE>] [--metadata <JSON-FILE>]
loop-engine --format json run request <RUN-ID> <EVENT> \
  [--evidence-id <ID> ...] [--evidence <JSON-FILE>] [--note <TEXT>]
loop-engine --format json run annotate <RUN-ID> \
  [--note <TEXT>] [--actor <JSON-FILE>] [--corrects <SEQUENCE>]
loop-engine --format json run history <RUN-ID> --limit 100
```

Evidence locators are opaque to the engine: it never parses, resolves, or dereferences them. Selection is caller-owned — empty selection is valid and the engine never auto-selects.

`run annotate` is the only way to record a note, actor metadata, or a correction to an earlier journal sequence, and the only journal mutation still permitted on a terminal run. `run label [--set <LABEL> | --clear]` retitles a run without touching workflow state.

**Live guidance is not a free read.** `run guidance <RUN-ID> [--evidence-id <ID> ...]` spawns the provider subprocess and writes a journal entry. Call it only when `run show` reports `live_guidance` `supported`, and never on a terminal run.

**After a provider update**, run `run compatibility <RUN-ID>` before further provider-dependent requests. It rejects on terminal runs, so do it while the run is still active.

## Handling outcomes

`completed` → proceed. `rejected` → the request was understood and denied; read `reason.code`, fix the work or pick a valid event. `error` → the request could not be reliably evaluated or committed.

**`error` requires investigation before any retry.** There are no idempotency keys and no automatic retry, and an absent journal record does **not** prove the provider process never started. After any `error`, timeout, or interrupted invocation: re-read `run show` and `run history` to determine whether the attempt landed, then decide whether to reissue. Blind retries can duplicate external side effects.

| `reason.code` | Action |
|---|---|
| `state.stale_version` | Another invocation committed first. Re-read `run show`; never retry the stale request as-is. |
| `provider.registration.stale` | Catalog revision changed. Re-read `provider list` and rebuild the request. |
| `run.lifecycle.terminal` | Run is final or terminated; no reopen exists. Inspect `run history`. |
| `guidance.unsupported` | The stored graph declares no live guidance. Use `static_guidance` from `run show`. |
| `compatibility.unsupported` | Provider declares that capability incompatible with the stored graph. Run `run compatibility`. |
| `evidence.selection.invalid` | A selected evidence ID is missing or the selection exceeds bounds. Re-list evidence. |
| `cursor.invalid` | Cursor belongs to a different query, filter, or store. Restart pagination with no cursor. |
| `export.target.not_empty` | Choose a new absent directory; export never overwrites or merges. |
| `provider.*` | Run `provider check`; verify exec path, working directory, timeout, protocol major, and provider stderr in the `trace` file. |
| `persistence.failed` | Stop. Preserve the home directory unchanged; do not repair SQLite by hand. |

Preserve `request_id` and the `trace` path when reporting a defect. Trace files are diagnostic evidence, not state authority.

## Pagination

`provider list`, `provider check --active-runs`, `run list`, `run history`, and `run evidence list` are paged. Pass `--limit <COUNT>` (default 100, max 1000) and follow `data.next_cursor` verbatim:

```bash
loop-engine --format json run history <RUN-ID> --limit 100
loop-engine --format json run history <RUN-ID> --limit 100 --cursor <NEXT-CURSOR>
```

Cursors are opaque — never construct, edit, or decode them. An exhausted collection returns empty `data.items` and no `next_cursor`.

## Inspect and close

```bash
loop-engine --format json run evidence list <RUN-ID> --limit 100
loop-engine --format json run export <RUN-ID> --output <ABSENT-OR-EMPTY-DIR>
loop-engine --format json run terminate <RUN-ID> [--note <REASON>]
```

`run history` is the ordered activity journal; `run show` is current authority. Export writes `manifest.json`, `state.json`, and `journal.jsonl` into `--output`; it is an audit snapshot, never a backup or restore input, and the target must be absent or an empty directory. Terminate abandoned active runs explicitly — runs never reopen and are never deleted.

## Do not

- Invent events; request only what `run show` lists.
- Assume `run request` performs the primary work.
- Retry after `error` without re-reading `run show` and `run history`.
- Call `run guidance` when `live_guidance` is `unsupported`, or on a terminal run.
- Parse human output for automation, or read anything but the single JSON object on stdout.
- Treat exit `2` as an infrastructure failure — it is a domain rejection.
- Dereference evidence locators through the engine.
- Assume the provider process retains memory between calls.
- Edit `state.db`, `PRAGMA user_version`, migration tables, or integration metadata.

## Deeper references

In a `loop-engine` checkout: `docs/operator-guide.md` (full operational guidance), `docs/cli-contract.md` (envelope, exit codes, bounds, cursor v1), `docs/operation-catalog.md` (all 21 operations and the reason-code taxonomy), `docs/export-contract.md`, and `examples/providers/reference-go/README.md` (provider authoring walkthrough). Upstream: <https://github.com/cartwmic/loop-engine>.
