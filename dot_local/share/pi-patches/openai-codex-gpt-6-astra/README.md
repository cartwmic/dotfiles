# pi-patch: openai-codex-gpt-6-astra

Inserts `gpt-6-astra` into Pi's openai-codex catalog so the CLI can select
`openai-codex/gpt-6-astra`. **Personal profile only.**

## Why

OpenAI documented GPT-6 Astra for Codex CLI/IDE on 2026-09-03 (`gpt-6-astra`).
pi-ai 0.85.0 still stops at the GPT-5.6 family. There is no other Codex
allowlist — `openai-codex-responses` sends `model.id` from the catalog.

A `models.json` overlay would also inject the id (`applyModelsJson` upserts).
This patch puts the entry next to the siblings instead. Do not add an overlay
for this id: after the insert, `getModels()` already contains Astra, so
`catalog-overlay-nudge` cannot tell overlay from upstream.

Delete this directory once an unpatched catalog already ships the id.

`pi` is `dist/bundle/cli.js`. The CLI does **not** read
`openai-codex.json` at runtime; esbuild inlines `openai_codex_default` into a
bundle chunk. Revision 1 only edited the JSON, so `pi --list-models` stayed
empty of Astra. Revision 2 patches both files. Revision 3 raises the window
from 272K to **872K** and upgrades the existing v2 insert in place, leaving
unrelated bundle edits and the original backups untouched.

## What it changes

1. **CLI (load-bearing):** the bundle chunk that contains
   `var openai_codex_default=` (chunk name is content-hashed; locate by that
   declaration). Inserts a minified `gpt-6-astra` entry plus
   `/*chezmoi-pi-patch:openai-codex-gpt-6-astra v3*/`.
2. **SDK / unbundled:** `@earendil-works/pi-ai/dist/providers/data/openai-codex.json`.

Copied from `gpt-5.6-sol`'s shape with official API pricing ($10 / $50 /
$1 cache-read / $12.50 cache-write; 2× input+cache and 1.5× output above
272K). These cost fields are API-based display estimates, not measured
Codex subscription charges; the context bump does not change them.

Context window is **872,000 tokens**, matching the official Codex catalog's
maximum override. Live subscription probes on 2026-09-04 succeeded at
872,931 input tokens and retrieved beginning/middle/end markers; a roughly
1M-token request failed. The exact backend ceiling remains unconfirmed.
This supersedes the original conservative 272K setting. Output limit stays
128K; no `models.json` override or separate variant is needed.

This does **not** add the model to `enabledModels`. `pi --list-models` will
show it once openai-codex auth is configured; the picker still uses
`enabledModels` for session defaults.

## Profile gate

Applies **only** when `PI_CHEZMOI_PROFILE=personal`. The templated wrapper
`run_onchange_after_30_apply_pi_patches.sh.tmpl` exports that variable.

- `PI_CHEZMOI_PROFILE=personal` → insert (or no-op if already present).
- Any other value, or unset → do not insert; if a previous run patched, restore
  `<target>.orig.chezmoi-pi-patch`. Fail-safe default is "do not apply".

## Upstream catch-up

Two signals, neither polls npm/pi.dev:

1. **Apply.** If the unpatched catalog already has `gpt-6-astra` (`.orig`
   backup when it still exists, otherwise the live file with no patch marker),
   apply logs `delete this patch` and does not insert. After a typical
   `npm i -g` / mise reinstall the backups are gone, so the live unmarked
   catalog is the check that actually fires.
2. **Session start.** The patch writes `catalogStopgap` into its state file.
   `pi-patch-guard` then distinguishes:
   - marker missing, id missing → wipe, re-apply
   - marker missing, id present → upstream shipped, delete this patch
   - marker present → keep (this insert is why the id is there)

Same shape of reminder as `catalog-overlay-nudge`, but the guard is the right
home: overlay-vs-catalog id comparison would always look "upstream" once this
patch has run.

## How it's deployed

Same loop as the sibling patches: `apply_pi_patches.sh` via
`run_onchange_after_30_apply_pi_patches.sh.tmpl`. After a pi upgrade, run
`chezmoi apply`.

State: `~/.local/state/chezmoi-pi-patches/openai-codex-gpt-6-astra.json`.
Backups: `*.orig.chezmoi-pi-patch` next to each target. pi-patch-guard watches
the **bundle** (`state.target`) for the marker comment. JSON cannot carry that
comment.

## Failure modes

### F1. Catalog JSON shape changed

**Symptom:** apply fails with `has no openai-codex-responses object`.

**Fix:** if upstream moved the catalog, update `CATALOG_GROUP` / locate path
and bump `PATCH_REVISION`. If upstream now ships `gpt-6-astra`, delete this
directory, drop its hash-include line, and `chezmoi apply`.

### F2. Bundle catalog close is not `}};var OPENAI_CODEX_MODELS=...`

**Symptom:** apply fails with `does not end with }}; before OPENAI_CODEX_MODELS`
or `CLI bundle catalog not found`.

**Fix:** esbuild changed the inlined object. Re-read the chunk around
`openai_codex_default` and adjust the insert; bump `PATCH_REVISION`.

### F3. Upstream catalog already has the id

**Symptom:** apply logs `gpt-6-astra is in the unpatched catalog — delete this
patch`, and/or pi-patch-guard warns at session start that the patch is obsolete.

**Fix:** delete this directory, drop its hash-include in
`run_onchange_after_30_apply_pi_patches.sh.tmpl`, and `chezmoi apply`.

### F4. mise / npm reinstall wiped the insert

**Symptom:** `pi --list-models` no longer lists `openai-codex/gpt-6-astra`;
pi-patch-guard warns about a missing patch (not the obsolete-patch warning).

**Fix:** `chezmoi apply`, then start a new Pi process. Do not assume editing
`openai-codex.json` alone is enough.

## Validation

```sh
node --test patch.test.mjs
PI_CHEZMOI_PROFILE=personal node patch.mjs --check
pi --list-models | awk '$1=="openai-codex"'
```

`--check` exits 0 only when **both** the JSON catalog and the CLI bundle
include `gpt-6-astra`; locally patched catalogs must also have revision 3
and the 872K window. Native upstream entries are left alone. On a
non-personal profile, `--check` requires the bundle to be unmarked.
