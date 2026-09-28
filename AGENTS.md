# Chezmoi source — agent instructions

## Scope

This file is **only** for work in this repository: the chezmoi source tree at
`~/.local/share/chezmoi` (GitHub `cartwmic/dotfiles`). It is listed in
`.chezmoiignore` so chezmoi never deploys it. Do not copy it to `~/AGENTS.md`
or `~/.pi/agent/AGENTS.md`.

User-global Pi instructions are a **different file with different contents**:
source `dot_pi/private_agent/literal_AGENTS.md.tmpl` deploys to `~/.pi/agent/AGENTS.md`.
The source filename is `literal_AGENTS.md.tmpl` on purpose: Pi only auto-loads
`AGENTS.md` / `AGENTS.override.md` / `CLAUDE.md`. If the source were named
`AGENTS.md` under `dot_pi/private_agent/`, working in an extension directory would
load the live dest **and** the source (same text, two paths).

Do not add a `~/AGENTS.md` source. Chezmoi ignore and source mapping use the
**destination** name. Repo `AGENTS.md` and any source that would deploy to
`~/AGENTS.md` are the same target; chezmoi reports `inconsistent state`.

This repository is a public personal dotfiles source. Chezmoi maps it onto
`$HOME`. Edit **source** files here; live files under `~` are generated.

## Authority

Precedence when the cwd is this repo:

1. This file — repository operations, source naming, apply/verify, and secrets
   handling for this tree.
2. `~/.pi/agent/AGENTS.md` — cross-project habits (hindsight, communication).
3. The source-only standing-reminder `AGENTS.md` — procedure for that extension
   when cwd is in its source directory; this root guide wins on conflicts.
4. A task-specific skill or proof README — detailed commands for its named
   workflow, under the root and nested instructions in scope.
5. `README.md` — human purpose and onboarding; it does not set agent apply or
   Git procedure.

Keep these scopes separate. The Pi-global file is not a second copy of this
repo guide. Consult a nested guide or task-specific procedure when editing
that subtree or running its proof.

On conflict inside this tree, this file wins. Do not “sync” the two AGENTS
files toward each other.

Generated destinations (`~/.zshrc`, `~/.pi/agent/settings.json`, and so on)
are not the source of truth. Templated files cannot be captured with
`chezmoi re-add` (it is a silent no-op). Change the source template, then
apply.

`chezmoi diff` shows **a/** = live destination and **b/** = source template
(the inverse of a conventional source→target diff). Before deciding from a
diff, render the template and read the live file independently.

## Workflow

First identify the checkout that owns the edit. `chezmoi` defaults to its
configured source, which can be another checkout. The unscoped `source-path`
below intentionally shows that configured source; scope the second call and
all later mapping, template, and dry-run commands to this worktree:

```sh
SOURCE="$(git rev-parse --show-toplevel)"
chezmoi source-path ~/.zshrc
chezmoi --source "$SOURCE" source-path ~/.zshrc
chezmoi --source "$SOURCE" managed --include files
chezmoi --source "$SOURCE" execute-template '{{ .profile }}'
```

The installed Pi patch helper defaults `PI_PATCHES_ROOT` to the canonical
`~/.local/share/chezmoi/dot_local/share/pi-patches`, even if `chezmoi --source`
selects another checkout. For an owner-approved apply from a worktree, set
`PI_PATCHES_ROOT="$SOURCE/dot_local/share/pi-patches"` on that invocation.
If the owner chooses to apply from the canonical checkout, integrate the patch
sources there first and use its normal patch root. Use the isolated Pi journey
to prove a worktree's patch; a dry-run cannot prove an installed patch. Ask
before any real apply.

Source naming (chezmoi):

- `dot_*` → `.filename` in `$HOME`
- `private_*` → mode `0600` on apply. **Not a git exclude.** This repo is
  public; never put a secret value in a `private_*` file.
- `run_once_*` / `run_onchange_*` → scripts after apply
- `.tmpl` → chezmoi template
- `literal_*` → stop parsing further prefixes (`literal_AGENTS.md` would
  deploy as `~/AGENTS.md`)
- `exact_*` → **directory only**: remove unmanaged children in that directory.
  It does not mean “use the rest of the filename literally.”

Profiles (`~/.config/chezmoi/chezmoi.yaml` → `data.profile`): `personal`,
`axon-work-computer`, `termux`. `.chezmoiignore` is the authority for what
each profile deploys.

Shell scripts: POSIX where possible, `set -eu`, helpers from `utils.sh`
(`is_macos`, `is_ubuntu`), log prefix `[script_name] LEVEL: message`, clean
up temp dirs with traps.

Secrets: never commit API keys, tokens, or passwords. Read secrets at
runtime with 1Password (`op read`, service-account token at
`~/.config/agent-harness/op-service-token`, mode 0600, outside this repo).
`private_dot_zshrc` is the pattern. `rage`/age is available for files that
must be encrypted in source.

RustDesk: do not sync `RustDesk.toml`, `RustDesk_local.toml`, or
`RustDesk_hwcodec.toml`. The unattended password is only
`op://developer/RustDesk/password`. Shared passwords increase blast radius
across every managed host.

SSH: `private_dot_ssh/modify_authorized_keys` is append-safe and must stay
non-destructive to foreign keys.

Agent harness: canonical skills and MCP live under
`dot_local/share/agent-harness/`. Adapters project into Claude, Codex, and
Pi. Do not put harness-specific semantics in canonical files. After skill
or MCP changes, apply with the commands below (or `chezmoi apply`, which
runs the apply script).

Pi runtime patches: `dot_local/share/pi-patches/<name>/patch.mjs`. After
`npm update -g` / mise reinstall of pi, `chezmoi apply` must re-run so
patches re-apply. Do not edit installed pi `dist/` files except through
that patch mechanism.

OpenSpec/`opsx` is retired; do not revive it. Do not write ADRs.

Pi extensions in this tree: never capture `ExtensionContext` `ctx` in a
long-lived closure; use the per-call `ctx`. Do not couple new extensions
to retired opsx.

Adding a mise-registry tool: edit `dot_config/mise/config.toml` `[tools]`,
then apply. Custom install: add a `[tasks]` entry with an idempotent
`condition`, wire it into bootstrap, then apply.

Do not add Rust as a mise `[tools]` entry. Rust is installed with rustup
via the `install-rust` mise task. mise’s rust backend exports
`RUSTUP_TOOLCHAIN`, which overrides every repo-level `rust-toolchain.toml`.

A non-TTY shell can fail with `could not open a new TTY` at a merge conflict.
Use `--force` only after deciding to take the source side. An inability to open
`/dev/tty` is no authorization to overwrite live drift; ask the owner when
that choice is unclear. Typical worktree preview from its repository root:

```bash
SOURCE="$(git rev-parse --show-toplevel)"
chezmoi --source "$SOURCE" apply --dry-run --verbose
chezmoi --source "$SOURCE" execute-template '{{ .profile }}'
chezmoi --source "$SOURCE" apply --dry-run --verbose --force
```

Use the `--force` dry-run to inspect the source-side result if non-TTY merge
resolution blocks the first preview. Prefer targeting a destination when the
change is local, and use a full dry-run when onchange scripts or profile
changes may be involved. A real apply requires owner approval after preview;
keep the same explicit `--source` and confirm the patch root above. Ask before
commits, pushes, destructive cleanup, or a source-side merge of unrelated live
changes. Do not edit generated home files as if they were source.

This public repository has no in-tree secret scanner that enforces the
no-secrets rule. Review staged content and secret-like changes before any
authorized commit; markdown instructions alone cannot block a leak.

Validate templates with `chezmoi execute-template` and destination mapping
with `chezmoi managed` / `chezmoi source-path <dest>`.

## Nested docs

Subtree procedure lives in [README.md](./README.md). The one exception is
[standing-reminder/AGENTS.md](./dot_pi/private_agent/extensions/standing-reminder/AGENTS.md):
it gives agents working on that extension its source-specific rules. Pi loads
`AGENTS.md` / `CLAUDE.md` from `~/.pi/agent/` and then the cwd's ancestors, so
this nested file stacks on this repo guide and the Pi-global file only when
working in its source subtree. `.chezmoiignore` keeps that nested file out of
the deployed extension. See the README Docs map for other subtree docs.

Load only the relevant subtree README: [Pi extensions](./dot_pi/private_agent/extensions/README.md)
when editing extensions, [Pi patches](./dot_local/share/pi-patches/README.md)
when changing runtime patches, [Neovim](./dot_config/nvim/README.md) when
changing its overlay, and [session-search](./dot_pi/session-search/README.md)
when changing that personal-only service. Extension code must use the
per-call `ctx` (see the shared extension guide above).

Keep other subtree procedures in READMEs. Do not add another `AGENTS.md` under
`dot_pi/private_agent/extensions/`, `pi-patches/`, skills, or `dot_config/`;
the standing-reminder source-only exception above is the only nested guide.
Do not add `~/AGENTS.md`. Claude and Codex already have
`dot_claude/CLAUDE.md.tmpl` and `dot_codex/modify_AGENTS.md.tmpl`.

## Completion and handoff

Done means all of the following that apply:

- Source files in **this** tree are updated; live `~` files were not hand-edited
  as if they were source.
- `chezmoi --source "$SOURCE" apply --dry-run --verbose` was run for the
  touched destinations, with a full preview when onchange scripts matter.
- A real `chezmoi apply` ran only after the owner explicitly approved it.
  If verification requires materializing, report the blocker and ask first.
- No commit or push unless the user asked.
- Secrets, 1Password references, and `private_*` files were not given
  committed secret values.
- `~/.pi/agent/AGENTS.md` / `dot_pi/private_agent/literal_AGENTS.md.tmpl` was not overwritten with
  this file’s contents, and no `~/AGENTS.md` source was added.

Handoff must name:

- Source paths changed (chezmoi names, not only destination paths)
- Validation commands, outcomes, skipped proof, and any behavior left unverified
- Whether apply ran, with `--force` or not, and which source checkout it used
- Profile assumptions (`personal` / `axon-work-computer` / `termux`)
- Remaining manual steps (permissions, Docker Desktop license, gvm, and so on)
- Anything still destination-only (drift the user must choose source-vs-live)

Do not report a `chezmoi diff` interpretation without independent reads of
rendered source and live destination.
