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

## Overview

Each subdirectory here is one patch. The apply script walks every
`*/patch.mjs` under this source directory and runs it with Node. Chezmoi
re-triggers that loop when
[run_onchange_after_30_apply_pi_patches.sh.tmpl](../../../run_onchange_after_30_apply_pi_patches.sh.tmpl)
sees a hash change (patch payload, apply script, or installed package version).

Per-patch rationale and failure modes stay in the sibling READMEs:

- [anthropic-idle-watchdog](anthropic-idle-watchdog/README.md) — SSE idle watchdog (all profiles)
- [custom-message-marker](custom-message-marker/README.md) — wrap injected `custom` messages (all profiles)
- [hide-nonbridge-claude-models](hide-nonbridge-claude-models/README.md) — personal-only model-list filter
- [cursor-provider](cursor-provider/README.md) — retired leftover-splice restore (not desired-state delivery; widget comes from the fork)

## Setup

This directory is chezmoi **source** (`dot_local/share/pi-patches/`). Confirm
you are looking at it:

```sh
ls
```

You should see one subdirectory per patch (`anthropic-idle-watchdog`,
`custom-message-marker`, `hide-nonbridge-claude-models`,
`cursor-provider`) plus this README.

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
phase) and the target package tree each patch locates. Missing Node or a
missing patches directory makes the apply script exit 0 with a notice.
`cursor-provider` restores leftovers if that npm tree exists, and no-ops if it
is absent. It never applies the splice.

## Usage

### Apply

Chezmoi runs the onchange wrapper after mise. The wrapper exports the
active profile, then execs the apply script (through `mise exec` when mise
is present). In the tmpl:

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
4. If the patch is personal-only, follow
   [hide-nonbridge-claude-models](hide-nonbridge-claude-models/README.md):
   apply only when `PI_CHEZMOI_PROFILE=personal`; otherwise skip and, if a
   previous run applied it, restore `<target>.orig.chezmoi-pi-patch`.
   Fail-safe default is do not apply. Do not add a work-only widget splice;
   Cursor remaining/spend is configuration on the fork. `cursor-provider`
   restores leftovers on every profile. Ungated patches ignore the variable.
5. Keep state under `~/.local/state/chezmoi-pi-patches/<name>.json`. Backup
   the unpatched file next to the target as `<file>.orig.chezmoi-pi-patch`.
6. Do not edit installed package files by hand. Re-apply via `chezmoi apply`
   after `npm update -g @earendil-works/pi-coding-agent`, a mise reinstall
   of pi, or a widget-package upgrade under `~/.pi/agent/npm`.

### Profile gate

| `PI_CHEZMOI_PROFILE` | personal-only patch | `cursor-provider` (retired restore) | un-gated patch |
|---|---|---|---|
| `personal` | apply | restore leftovers / no-op | apply |
| `axon-work-computer` | skip; restore | restore leftovers / no-op | apply |
| any other value | skip; restore backup if previously applied | restore leftovers / no-op | apply |
| unset (manual script) | skip; un-patch | restore leftovers / no-op | apply |

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
node custom-message-marker/patch.mjs --check
PI_CHEZMOI_PROFILE=personal node hide-nonbridge-claude-models/patch.mjs --check
PI_CHEZMOI_PROFILE=axon-work-computer node cursor-provider/patch.mjs --check
PI_CHEZMOI_PROFILE=personal node cursor-provider/patch.mjs --check
```

On a non-personal profile, omit `=personal` (or set the real profile) so
the hide-nonbridge check expects the un-patched files. `cursor-provider --check`
expects unspliced leftover `@marckrenn/pi-sub-*` files (or an absent npm tree)
on every profile, including work.

If the target package tree is not installed, `--check` / apply exit
without editing; that is expected.
