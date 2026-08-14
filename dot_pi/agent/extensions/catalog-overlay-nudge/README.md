# catalog-overlay-nudge

Pi extension that warns when a **temporary** `~/.pi/agent/models.json` overlay
has been superseded by the real model catalog, so stale stopgaps stop shadowing
official pricing and compatibility metadata.

Source: [index.ts](./index.ts). Chezmoi deploys this directory to
`~/.pi/agent/extensions/catalog-overlay-nudge`.

## Overview

Brand-new models (for example a Claude release-day id) can be missing from both
pi-ai's bundled catalog and the pi.dev remote catalog. The stopgap is a
`models.json` overlay that injects guessed metadata (placeholder cost, compat,
and so on) until the catalog catches up.

Once the real catalog includes that id, the overlay is harmful: pi's
`modelFromJson` **replaces the catalog model wholesale**. A leftover overlay
silently pins wrong pricing and compatibility. This extension compares each
overlay model id against the **union** of:

1. pi-ai's builtin catalog (`getModels(provider)`), and
2. the persisted pi.dev catalog cache at `~/.pi/agent/models-store.json`
   (pi itself refreshes this about every four hours)

and, at **session start**, nudges you to delete the stopgap if those ids now
exist upstream.

It only **warns**. It never edits `models.json` or the chezmoi source.

**Fix the chezmoi source, not the live file.** The live
`~/.pi/agent/models.json` is generated. Editing it is clobbered by the next
`chezmoi apply`. Remove the superseded overlay from
`dot_pi/agent/private_models.json.tmpl` (two levels above this folder, sibling
of `extensions/`). The warning names that source path.

**Skip custom providers.** Only provider objects whose **only** key is
`models` are treated as catalog stopgaps. Entries that also set `baseUrl`,
`apiKey`, `compat`, `api`, or any other key (for example `deepseek` and
`private-anthropic` in the same template) are permanent custom providers and
are skipped. A provider with no upstream catalog ids is also skipped.

Interactive sessions only (`ctx.hasUI`). Headless and subagent runs stay
silent.

## Setup

Work in the chezmoi source for this extension and confirm the loader is
present:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/catalog-overlay-nudge && ls -l ./index.ts
```

Chezmoi maps this folder to `~/.pi/agent/extensions/catalog-overlay-nudge`.
After an apply that includes `.pi`, start a **new** Pi process so the
extension loads. Do not copy or hand-edit the live destination; keep overlay
edits in `dot_pi/agent/private_models.json.tmpl`.

This extension has no `config.json` and no slash command. Enablement is "the
file is deployed and Pi restarted." The `termux` profile skips `.pi`, so this
extension does not deploy there.

## Usage

On `session_start`, the extension reads `~/.pi/agent/models.json` and
`~/.pi/agent/models-store.json`, runs `findStaleOverlays` from
[index.ts](./index.ts), and if any overlay ids are already in the catalog
union it fires one UI warning, for example:

```text
Model catalog now includes overlay-defined model(s) — anthropic: claude-opus-5.
Remove the stopgap overlay from dot_pi/agent/private_models.json.tmpl (chezmoi)
so official metadata/pricing applies.
```

What to do when that fires:

1. Open `dot_pi/agent/private_models.json.tmpl` in the chezmoi source tree.
2. Remove the superseded model object (or the whole provider block if it only
   existed as a models-only stopgap).
3. Apply chezmoi, then start a new Pi session. The warning should be gone.

What **not** to do: delete the matching entry from live
`~/.pi/agent/models.json` and leave the template unchanged. The next apply
puts the overlay back.

A models-only stopgap looks like this (only key is `models`):

```json
{
  "anthropic": {
    "models": [{ "id": "claude-opus-5" }]
  }
}
```

A custom provider is **not** a stopgap and is never nudged, even if some of
its model ids later appear upstream:

```json
{
  "deepseek": {
    "baseUrl": "https://api.deepseek.com",
    "api": "openai-completions",
    "apiKey": "…",
    "compat": {},
    "models": [{ "id": "deepseek-v4-pro" }]
  }
}
```

## Validation

There is no `index.test.ts` in this directory yet. Smoke-check that the
session-start detector still exports and that the documented chezmoi source
path is the one named in the nudge:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/catalog-overlay-nudge
grep -n 'export function findStaleOverlays' ./index.ts
grep -n 'dot_pi/agent/private_models.json.tmpl' ./index.ts
```

Both greps must match. Then start an interactive Pi session: if
`models.json` still has a models-only overlay whose id is already in
pi-ai or `models-store.json`, you should see the warning; if you removed that
overlay from the template and applied, you should not.
