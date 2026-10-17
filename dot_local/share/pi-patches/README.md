# Pi runtime patches

Shared how-to for chezmoi-managed **runtime** patches against the copies of
pi packages that this machine actually loads. This file is a README (not
`AGENTS.md`): Pi auto-loads nested `AGENTS.md` when cwd is in this tree.

Most patches edit `@earendil-works/pi-coding-agent` `dist/` (not the stale
`@mariozechner` namespace). The usage widget is not patched: both chezmoi
profiles install [`https://github.com/cartwmic/pi-sub`](https://github.com/cartwmic/pi-sub)
instead of `npm:@marckrenn/pi-sub-bar`. `cursor-provider` is **retired** leftover
restore against `~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-*` if that tree
still exists. It is not the delivery vehicle and must not splice.

## Pi version selection

Four patches (headless-extension-drain, prompt-start-race, settlement-abort, standing-reminder-origin) have anchors that differ
between Pi minor series, so each directory holds one payload per series and `patch.mjs` is only an entry point:

| File | Role |
|---|---|
| `patch.mjs` | Entry point the apply loop, the onchange hash and the proofs use. Calls `dispatchByPiVersion` in `pi-select.mjs`. |
| `patch.pi-1.1.mjs` | Payload for Pi 1.1.x (the revisions before the 1.2.0 port: v1/v1/v2/v2). |
| `patch.pi-1.2.mjs` | Payload for Pi 1.2.x (the 1.2.0 port: v2/v2/v3/v3). |

Selection reads the installed Pi version (same locator and per-patch `PI_*_PACKAGE` override the payloads use) and runs the matching
payload with the same arguments and environment; its exit code is the result. An installed Pi whose minor series has no payload
(or whose version cannot be read) **fails with exit 1 and changes nothing**; it never falls back to another series. With no Pi
installed the newest payload runs and keeps its own "not installed; skipped" / `--check` "cannot verify" behaviour.
To support a new series, add `patch.pi-<major>.<minor>.mjs`, add it to the `variants` map in the patch's `patch.mjs`, add its
hash line to `run_onchange_after_30_apply_pi_patches.sh.tmpl` and port that payload's proof. `tests/pi-patches/pi_select.test.mjs`
checks the wiring (run: `node --test tests/pi-patches/pi_select.test.mjs`).

Other patches are not version-aware: `btw-native-session` supports exactly Pi 1.1.0 and fails on any other version, and
`response-visibility` fails its anchor check on Pi 1.2.0 (observed on a scratch install: unsupported or ambiguous anchor for `emitBeforeAgentStart` in `dist/core/extensions/runner.js`), so a full apply on Pi 1.2.x still exits 1 until those are ported.

## Overview

Each subdirectory here is one patch. The apply script walks every
`*/patch.mjs` under this source directory and runs it with Node. Chezmoi
re-triggers that loop when
[run_onchange_after_30_apply_pi_patches.sh.tmpl](../../../run_onchange_after_30_apply_pi_patches.sh.tmpl)
sees a hash change (patch payload, apply script, or installed package version).

Per-patch rationale and failure modes stay in the sibling READMEs:

- [anthropic-idle-watchdog](anthropic-idle-watchdog/README.md) — SSE idle watchdog (all profiles)
- [custom-message-marker](custom-message-marker/README.md) — wrap injected `custom` messages (all profiles)
- [empty-turn-retry](empty-turn-retry/README.md) — retry empty assistant responses
- [headless-extension-drain](headless-extension-drain/README.md) — drain fire-and-forget extension work in print mode
- [response-visibility](response-visibility/README.md) — delegate the optional Pi telemetry helper on desktop profiles
- [standing-reminder-origin](standing-reminder-origin/README.md) — carry input origin to processed messages on desktop profiles
- [settlement-abort](settlement-abort/README.md) — cancel through final settlement on desktop profiles
- [prompt-start-race](prompt-start-race/README.md) — queue a prompt that loses the start race on desktop profiles
- [cursor-provider](cursor-provider/README.md) — retired leftover-splice restore (not desired-state delivery; widget comes from the fork)

## Setup

This directory is chezmoi **source** (`dot_local/share/pi-patches/`). Confirm
you are looking at it:

```sh
ls
```

You should see one subdirectory per patch (`anthropic-idle-watchdog`,
`cursor-provider`, `custom-message-marker`, `empty-turn-retry`,
`headless-extension-drain`, `prompt-start-race`, `response-visibility`,
`settlement-abort`, `standing-reminder-origin`) plus this README.

Layout of each patch:

```text
<name>/
  patch.mjs    # payload; each current patch supports `--check`
  README.md    # why it exists and how it fails
```

[apply_pi_patches.sh](../../user_scripts/executable_apply_pi_patches.sh)
iterates `$PATCHES_ROOT/*/` and runs every `patch.mjs`. Default
`PATCHES_ROOT` is this source directory
(`$HOME/.local/share/chezmoi/dot_local/share/pi-patches`); override with
`PI_PATCHES_ROOT` if needed. Chezmoi deploys the script to
`~/.local/user_scripts/apply_pi_patches.sh` (`executable_` prefix stripped).

The onchange wrapper hashes each `patch.mjs` with an `include … | sha256sum`
line. **Adding a patch means adding that include line in the tmpl** (do not
edit the hash values by hand; chezmoi regenerates them). The wrapper also
hashes the apply script and probes the installed
`@earendil-works/pi-coding-agent` and nested `@earendil-works/pi-ai`
versions (reporting `not-installed` before Node exists). After a leftover
`@marckrenn/pi-sub-*` npm tree appears, `chezmoi apply` restores it unspliced
as documented in [cursor-provider](cursor-provider/README.md). Cursor remaining
or spend comes from the GitHub-installed fork and `metricSet`, not this patch.

Prerequisites: Node on PATH (mise installs it earlier in the after-script
phase) and the target package tree each patch locates. Patches find Pi through
[pi-root.mjs](pi-root.mjs): `PI_ROOT`, then Pi's managed install
(`~/.pi/agent/install/releases/<current-version>/`), then `npm root -g`. Missing Node or a
missing patches directory makes the `apply-pi-patches` mise task fail (the bare
script would exit 0 with a notice).
`cursor-provider` restores leftovers if that npm tree exists, and no-ops if it
is absent. It never applies the splice.

## Usage

### Apply

Every path uses one entry point, the `apply-pi-patches` mise task: chezmoi's
onchange wrapper (after mise bootstrap), `install-pi` after a fresh install,
and `update-pi`. The wrapper exports the active profile and source patch root,
then execs `mise run apply-pi-patches`. In the tmpl:

```sh
export PI_CHEZMOI_PROFILE="{{ .profile }}"
```

At apply time that is the real profile string (for example `personal`).

The apply script itself does not filter patches. Each `patch.mjs` reads
`PI_CHEZMOI_PROFILE`.

Manual apply (same loop the wrapper uses):

```sh
~/.local/user_scripts/apply_pi_patches.sh
```

Without the wrapper, `PI_CHEZMOI_PROFILE` is unset. Personal-only and
work-only patches must treat that as skip / un-patch.

### Add a patch

1. Create `<name>/patch.mjs` and `<name>/README.md` next to the siblings.
2. Target the tree pi actually loads. Sibling patches that customize
   pi-coding-agent resolve `@earendil-works/pi-coding-agent/dist/...` (not
   `@mariozechner/...`). Do not add a new splice against the GitHub-installed
   `cartwmic/pi-sub` tree. `cursor-provider` only restores leftover
   `~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-*` files if that npm tree
   still exists.
3. Add a hash-trigger line in
   [run_onchange_after_30_apply_pi_patches.sh.tmpl](../../../run_onchange_after_30_apply_pi_patches.sh.tmpl):
   `# patch.mjs (<name>): {{ include "dot_local/share/pi-patches/<name>/patch.mjs" | sha256sum }}`
4. If the patch is personal-only, apply only when
   `PI_CHEZMOI_PROFILE=personal`; otherwise skip and, if a previous run
   applied it, reverse only its own checked edits.
   Fail-safe default is do not apply. Do not add a work-only widget splice;
   Cursor remaining/spend is configuration on the fork. `cursor-provider`
   restores leftovers on every profile. Ungated patches ignore the variable.
5. Keep state under `~/.local/state/chezmoi-pi-patches/<name>.json`. For
   shared files, do not restore a whole-file backup over sibling patches; reverse
   only this patch's checked edits.
6. Do not edit installed package files by hand. Re-apply via `chezmoi apply`
   after `npm update -g @earendil-works/pi-coding-agent`, a mise reinstall
   of pi, or a widget-package upgrade under `~/.pi/agent/npm`.

### Profile gate

| `PI_CHEZMOI_PROFILE` | personal-only patch | `cursor-provider` (retired restore) | `standing-reminder-origin` | un-gated patch |
|---|---|---|---|---|
| `personal` | apply | restore leftovers / no-op | apply | apply |
| `axon-work-computer` | skip; restore | restore leftovers / no-op | apply | apply |
| `termux` | skip; restore | restore leftovers / no-op | skip/unpatch | apply |
| any other value | skip; restore backup if previously applied | restore leftovers / no-op | skip/unpatch | apply |
| unset (manual script) | skip; un-patch | restore leftovers / no-op | skip/unpatch | apply |

`standing-reminder-origin` reverses only its own literal blocks when disabled,
preserving sibling edits in shared files.

[`settlement-abort`](settlement-abort/README.md) uses the same desktop gate
(`personal` / `axon-work-computer`) and exact-block reversal. Tested Pi 0.99.2 and 1.0.0:
operation-lifetime `ctx.signal` through awaited final-settlement handlers,
busy streaming final settlement with compatible main-agent idle semantics, and discard aborted
pre-settlement proposals. Settled remains notification-only.
Private public-path proof: `python3 tests/pi-patches/settlement_abort.py`.

[`prompt-start-race`](prompt-start-race/README.md) uses the same desktop gate
and exact-block reversal. Tested Pi 1.0.0: a prompt that loses the start race
queues into the active run (steer by default, follow-up if requested) instead
of throwing, so it cannot emit a false `agent_settled`. Private real-TUI proof:
`python3 tests/auto-compact-steer/proof.py`.

### After a pi or widget upgrade

`npm update -g` and mise reinstall replace pi-coding-agent `dist/` and drop
backups. The usage widget loads from the GitHub-installed
[`cartwmic/pi-sub`](https://github.com/cartwmic/pi-sub) tree, not from a
runtime splice of `@marckrenn/pi-sub-*`. If an old npm widget tree reappears
under `~/.pi/agent/npm`, `chezmoi apply` restores it unspliced. Do not re-enable
`wantPatched`.

## Validation

List payloads the apply script will iterate, then `--check` each patch
(no writes). `--check` exits 0 when the install already matches the
desired state for the active profile.

```sh
ls */patch.mjs
node anthropic-idle-watchdog/patch.mjs --check
# From the repo root: python3 tests/pi-patches/anthropic_watchdog.py
node custom-message-marker/patch.mjs --check
PI_CHEZMOI_PROFILE=personal node standing-reminder-origin/patch.mjs --check
PI_CHEZMOI_PROFILE=axon-work-computer node standing-reminder-origin/patch.mjs --check
PI_CHEZMOI_PROFILE=termux node standing-reminder-origin/patch.mjs --check
PI_CHEZMOI_PROFILE=axon-work-computer node cursor-provider/patch.mjs --check
PI_CHEZMOI_PROFILE=personal node cursor-provider/patch.mjs --check
```

`cursor-provider --check`
expects unspliced leftover `@marckrenn/pi-sub-*` files (or an absent npm tree)
on every profile, including work.

If the target package tree is not installed, `--check` / apply exit
without editing; that is expected.
