# Pi runtime patches

Shared how-to for chezmoi-managed **runtime** patches against the copies of
pi packages that this machine actually loads. This file is a README (not
`AGENTS.md`): Pi auto-loads nested `AGENTS.md` when cwd is in this tree.

Most patches edit `@earendil-works/pi-coding-agent` `dist/` (not the stale
`@mariozechner` namespace). `cursor-provider` is different: it targets the
pi-loaded `@marckrenn/pi-sub-{shared,core,bar}` tree under
`~/.pi/agent/npm`, not pi-coding-agent `dist/` and not a disconnected
global npm copy.

Do not hand-edit installed package files. After `npm update -g`, a mise
reinstall of pi, or a widget-package upgrade, run `chezmoi apply` so these
patches re-apply.

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
- [cursor-provider](cursor-provider/README.md) — Cursor usage row in the pi-sub widget (`axon-work-computer` only)

## Setup

This directory is chezmoi **source** (`dot_local/share/pi-patches/`). Confirm
you are looking at it:

```sh
ls
```

You should see one subdirectory per patch (`anthropic-idle-watchdog`,
`custom-message-marker`, `hide-nonbridge-claude-models`, `cursor-provider`)
plus this README.

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
versions (reporting `not-installed` before Node exists). After a widget
upgrade, restore Cursor visibility with `chezmoi apply` as documented in
[cursor-provider](cursor-provider/README.md).

Prerequisites: Node on PATH (mise installs it earlier in the after-script
phase) and the target package tree each patch locates. Missing Node or a
missing patches directory makes the apply script exit 0 with a notice.
`cursor-provider` no-ops if the agent-npm `@marckrenn/pi-sub-*` tree is
absent.

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
   `@mariozechner/...`). `cursor-provider` instead resolves
   `~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-{shared,core,bar}`.
   Do not patch a disconnected global npm copy of the widget.
3. Add a hash-trigger line in
   [run_onchange_after_30_apply_pi_patches.sh.tmpl](../../../run_onchange_after_30_apply_pi_patches.sh.tmpl):
   `# patch.mjs (<name>): {{ include "dot_local/share/pi-patches/<name>/patch.mjs" | sha256sum }}`
4. If the patch is personal-only, follow
   [hide-nonbridge-claude-models](hide-nonbridge-claude-models/README.md):
   apply only when `PI_CHEZMOI_PROFILE=personal`; otherwise skip and, if a
   previous run applied it, restore `<target>.orig.chezmoi-pi-patch`.
   Fail-safe default is do not apply. If the patch is work-only, follow
   [cursor-provider](cursor-provider/README.md): apply only when
   `PI_CHEZMOI_PROFILE=axon-work-computer`; otherwise restore backups and
   remove any dropped files. Ungated patches ignore the variable.
5. Keep state under `~/.local/state/chezmoi-pi-patches/<name>.json`. Backup
   the unpatched file next to the target as `<file>.orig.chezmoi-pi-patch`.
6. Do not edit installed package files by hand. Re-apply via `chezmoi apply`
   after `npm update -g @earendil-works/pi-coding-agent`, a mise reinstall
   of pi, or a widget-package upgrade under `~/.pi/agent/npm`.

### Profile gate

| `PI_CHEZMOI_PROFILE` | personal-only patch | work-only patch (`cursor-provider`) | un-gated patch |
|---|---|---|---|
| `personal` | apply | skip; restore | apply |
| `axon-work-computer` | skip; restore | apply | apply |
| any other value | skip; restore backup if previously applied | skip; restore | apply |
| unset (manual script) | skip; un-patch | skip; un-patch | apply |

### After a pi or widget upgrade

`npm update -g` and mise reinstall replace pi-coding-agent `dist/` and drop
backups. A widget-package upgrade replaces
`~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-*` and drops `cursor.ts`
plus splices. `chezmoi apply` (or the same apply script it already invokes)
is the supported re-apply path for both trees. A forked widget repository
is not required.

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
```

On a non-personal profile, omit `=personal` (or set the real profile) so
the hide-nonbridge check expects the un-patched file. On a non-work
profile, omit `=axon-work-computer` (or set the real profile) so the
cursor-provider check expects restored stock files and no dropped
`cursor.ts`.

If the target package tree is not installed, `--check` / apply exit
without editing; that is expected.
