# Pi runtime patches

Shared how-to for chezmoi-managed **runtime** patches against the installed
`@earendil-works/pi-coding-agent` package. This file is a README (not
`AGENTS.md`): Pi auto-loads nested `AGENTS.md` when cwd is in this tree.

Do not hand-edit files under the installed package's `dist/`. After
`npm update -g` or a mise reinstall of pi, run `chezmoi apply` so these
patches re-apply. New patches must target `@earendil-works/pi-coding-agent`,
not the stale `@mariozechner` namespace.

## Overview

Each subdirectory here is one patch. The apply script walks every
`*/patch.mjs` under this source directory and runs it with Node. Chezmoi
re-triggers that loop when
[run_onchange_after_30_apply_pi_patches.sh.tmpl](../../../run_onchange_after_30_apply_pi_patches.sh.tmpl)
sees a hash change (patch payload, apply script, or installed pi version).

Per-patch rationale and failure modes stay in the sibling READMEs:

- [anthropic-idle-watchdog](anthropic-idle-watchdog/README.md) — SSE idle watchdog (all profiles)
- [custom-message-marker](custom-message-marker/README.md) — wrap injected `custom` messages (all profiles)
- [hide-nonbridge-claude-models](hide-nonbridge-claude-models/README.md) — personal-only model-list filter

## Setup

This directory is chezmoi **source** (`dot_local/share/pi-patches/`). Confirm
you are looking at it:

```sh
ls
```

You should see one subdirectory per patch (`anthropic-idle-watchdog`,
`custom-message-marker`, `hide-nonbridge-claude-models`) plus this README.

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
versions (reporting `not-installed` before Node exists).

Prerequisites: Node on PATH (mise installs it earlier in the after-script
phase) and an installed `@earendil-works/pi-coding-agent`. Missing Node or
a missing patches directory makes the apply script exit 0 with a notice.

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

Without the wrapper, `PI_CHEZMOI_PROFILE` is unset. Personal-only patches
must treat that as skip / un-patch.

### Add a patch

1. Create `<name>/patch.mjs` and `<name>/README.md` next to the siblings.
2. Target `@earendil-works/pi-coding-agent` (resolve
   `@earendil-works/pi-coding-agent/dist/...`). Do not target
   `@mariozechner/...`.
3. Add a hash-trigger line in
   [run_onchange_after_30_apply_pi_patches.sh.tmpl](../../../run_onchange_after_30_apply_pi_patches.sh.tmpl):
   `# patch.mjs (<name>): {{ include "dot_local/share/pi-patches/<name>/patch.mjs" | sha256sum }}`
4. If the patch is personal-only, follow
   [hide-nonbridge-claude-models](hide-nonbridge-claude-models/README.md):
   apply only when `PI_CHEZMOI_PROFILE=personal`; otherwise skip and, if a
   previous run applied it, restore `<target>.orig.chezmoi-pi-patch`.
   Fail-safe default is do not apply. Ungated patches ignore the variable.
5. Keep state under `~/.local/state/chezmoi-pi-patches/<name>.json`. Backup
   the unpatched file next to the target as `<file>.orig.chezmoi-pi-patch`.
6. Do not edit installed `dist/` by hand. Re-apply via `chezmoi apply`
   after `npm update -g @earendil-works/pi-coding-agent` or a mise reinstall
   of pi.

### Profile gate

| `PI_CHEZMOI_PROFILE` | personal-only patch | un-gated patch |
|---|---|---|
| `personal` | apply | apply |
| any other value | skip; restore backup if previously applied | apply |
| unset (manual script) | skip; un-patch | apply |

### After a pi upgrade

`npm update -g` and mise reinstall replace `dist/` and drop backups.
`chezmoi apply` re-runs the onchange script because the tmpl hashes the
installed version (and each `patch.mjs`). That is the supported re-apply
path.

## Validation

List payloads the apply script will iterate, then `--check` each patch
(no writes). `--check` exits 0 when the install already matches the
desired state for the active profile.

```sh
ls */patch.mjs
node anthropic-idle-watchdog/patch.mjs --check
node custom-message-marker/patch.mjs --check
PI_CHEZMOI_PROFILE=personal node hide-nonbridge-claude-models/patch.mjs --check
```

On a non-personal profile, omit `=personal` (or set the real profile) so
the hide-nonbridge check expects the un-patched file.

If pi is not installed, `--check` / apply exit without editing; that is
expected.
