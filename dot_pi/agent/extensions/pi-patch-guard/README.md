# pi-patch-guard

A pi extension tripwire that warns when a chezmoi-managed pi **runtime patch**
has been silently wiped by a pi update.

## Why

Runtime patches (see `~/.local/share/pi-patches/`, e.g.
`hide-nonbridge-claude-models`) edit files *inside* the installed
`@earendil-works/pi-coding-agent` package. Any reinstall of that package
(`npm i -g …@latest`, a pi self-update, a node version bump that reinstalls
globals) rewrites `dist/` and **erases the edit**. The re-apply only runs on
`chezmoi apply`, so between an out-of-band update and the next apply the patch is
gone — for `hide-nonbridge-claude-models` that means non-bridge Claude models
reappear in the picker / `pi --list-models`, and every fresh `pi` process
(including subagents) reads the unpatched file.

This bit us once already: pi self-updated `0.79.4 → 0.79.6`, wiped the patch, and
nothing re-applied it until noticed by hand.

## What it does

On session start and after each agent response, it **auto-discovers** every
chezmoi-pi-patch by enumerating the state dir
(`~/.local/state/chezmoi-pi-patches/*.json`) — no hardcoded list. For each, if
the state file says the patch should be applied (`status` is `patched` /
`already-patched`), it checks the recorded `target` file still contains the
patch marker. If the marker is gone it fires a single UI warning.

**Profile-aware for free.** A patch gated off for the active chezmoi profile
(e.g. `hide-nonbridge-claude-models` on a non-`personal` profile) writes
`status: "unpatched"`, which is not intended-on ⇒ no drift, no warning. Patches
that have never run (no state file) are simply not watched. The guard reads no
`PI_CHEZMOI_PROFILE` itself — the state files already encode the decision.

**It only warns. It does not heal.** Re-apply yourself with `chezmoi apply`
(re-runs `run_onchange_apply_pi_patches`) or run the patch directly:

```sh
PI_CHEZMOI_PROFILE=personal node \
  ~/.local/share/pi-patches/hide-nonbridge-claude-models/patch.mjs
```

…then reload pi (the running session's own in-memory model list is frozen until
reload; a fresh process reads the re-patched file).

## Scope (intentional)

- Warn only — no disk writes, no `node` spawns.
- Interactive only (`ctx.hasUI`) — headless / subagent runs stay silent.
- Warns once per drift episode; re-arms once the marker reappears.
- Never throws into a turn (all paths wrapped).
- No false alarms: any ambiguity (no state file, `status` not intended-on,
  target missing/unreadable, malformed json) ⇒ stays quiet.

## Watched patches

Nothing to configure — patches are discovered automatically from their state
files. The marker is derived by convention as `chezmoi-pi-patch:<name>` (where
`<name>` is the state file's `patchName`, falling back to its basename). A patch
may override this by writing an explicit `marker` field into its state file.
A new patch under `~/.local/share/pi-patches/` is watched as soon as it has run
once and written its state file.

## Config

`config.json`: `{ "enabled": true }` — set `enabled: false` to silence.

## Tests

```sh
node --test dot_pi/agent/extensions/pi-patch-guard/index.test.ts
```
