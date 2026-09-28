# Chezmoi source — agent instructions

## Scope

This file applies to the `cartwmic/dotfiles` chezmoi source repository,
including linked worktrees. The usual checkout is `~/.local/share/chezmoi`. This file is listed in
`.chezmoiignore` so chezmoi never deploys it. Do not copy it to `~/AGENTS.md`
or `~/.pi/agent/AGENTS.md`.

User-global Pi instructions are a **different file with different contents**:
source `dot_pi/private_agent/literal_AGENTS.md.tmpl` deploys to
`~/.pi/agent/AGENTS.md`. The source filename is `literal_AGENTS.md.tmpl` on
purpose: Pi only auto-loads `AGENTS.md` / `AGENTS.override.md` / `CLAUDE.md`.
If the source were named `AGENTS.md` under `dot_pi/private_agent/`, working in
an extension directory would load the live dest **and** the source (same text,
two paths).

Do not add a `~/AGENTS.md` source. Chezmoi ignore and source mapping use the
**destination** name. Repo `AGENTS.md` and any source that would deploy to
`~/AGENTS.md` are the same target; chezmoi reports `inconsistent state`.

This repository is a public personal dotfiles source. Chezmoi maps it onto
`$HOME`. Edit **source** files here; live files under `~` are generated.

## Authority

Precedence when the cwd is this repo:

1. This file — repository operations, source naming, apply/verify, and secrets
   handling for files in this tree.
2. [Learnings monitor AGENTS.md](./dot_pi/private_agent/extensions/learnings-monitor/AGENTS.md)
   — implementation and proof procedure when working in that extension.
   This file still controls chezmoi operations and the public source boundary.
3. `~/.pi/agent/AGENTS.md` — cross-project habits (hindsight, communication).
   It must not be treated as a second copy of this guide.
4. `README.md` — human product and onboarding. Use it for install, profiles,
   and what the machine will contain. Do not treat it as apply/edit procedure.

Follow the scoped guide for extension internals. Resolve source mapping, apply,
and secrets questions here. Keep the Pi-global and repo guides separate.

Generated destinations (`~/.zshrc`, `~/.pi/agent/settings.json`, and so on)
are not the source of truth. Templated files cannot be captured with
`chezmoi re-add` (it is a silent no-op). Change the source template, then
apply.

`chezmoi diff` shows **a/** = live destination and **b/** = source template
(the inverse of a conventional source→target diff). Before deciding from a
diff, render the template and read the live file independently.

## Workflow

Source naming (chezmoi):

- `dot_*` → `.filename` in `$HOME`
- `private_*` → files mode `0600`, directories mode `0700` on apply. Private
  source is still tracked by Git in this public repo; never put a secret
  value in a `private_*` file.
- `run_once_*` / `run_onchange_*` → scripts after apply
- `.tmpl` → chezmoi template
- `literal_*` → stop parsing further prefixes (`literal_AGENTS.md` would
  deploy as `~/AGENTS.md`)
- `exact_*` → **directory only**: remove unmanaged children in that directory.
  It does not mean “use the rest of the filename literally.”

Profiles (`~/.config/chezmoi/chezmoi.yaml` → `data.profile`): `personal`,
`axon-work-computer`, `termux`. `.chezmoiignore` is the authority for what
each profile deploys.

Before any chezmoi render, read, dry-run, or apply, inspect the active config's
`read-source-state` hook directly. The shipped `example.chezmoi.yaml` calls
`.install-password-manager.sh` even during state reads. With `op` missing, it
can install the 1Password CLI on macOS/Ubuntu or create a WSL `op` symlink;
Termux exits without installing. Ask before allowing those persistent effects.
If the config lives elsewhere, point `CHEZMOI_CONFIG` at that actual file:

```sh
CHEZMOI_CONFIG="${CHEZMOI_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/chezmoi/chezmoi.yaml}"
if [ -f "$CHEZMOI_CONFIG" ] && grep -q 'read-source-state:' "$CHEZMOI_CONFIG" &&
   ! command -v op >/dev/null 2>&1; then
  printf 'STOP: read-source-state may install/link op; ask for approval before chezmoi\n' >&2
  exit 1
fi
```

After approval, install or link `op` first, or explicitly allow the hook to do
so once. Then continue with the source-scoped profile check below.

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
or MCP changes, preview from the edited source below; an approved apply runs
the harness apply script.

Pi runtime patches: `dot_local/share/pi-patches/<name>/patch.mjs`. The
onchange wrapper hashes patch/source bytes and installed package versions. A
same-version reinstall can replace patched `dist/` files without changing that
hash, so `chezmoi apply` alone may skip the patch loop. Use the complete
read-only check below before an approved manual rerun. The
[Pi patches guide](./dot_local/share/pi-patches/README.md) explains the
payload format and onchange trigger; its example check list omits two current
payloads. In a linked worktree,
`--source` selects template bytes; the deployed patch runner defaults to the
usual checkout. Set `PI_PATCHES_ROOT` to this worktree's payload directory
for an approved apply. Do not edit installed Pi `dist/` files outside the
patch mechanism.

OpenSpec/`opsx` is retired. For a change, edit the owning source and its
scoped README or AGENTS guide, then run the workflow checks below. Do not
revive opsx or write ADRs.

Pi extensions in this tree: never capture `ExtensionContext` `ctx` in a
long-lived closure; use the per-call `ctx`. Do not couple new extensions
to retired opsx.

Adding a mise-registry tool: edit `dot_config/mise/config.toml` `[tools]`,
then apply. Custom install: add a `[tasks]` entry with an idempotent
`condition`, wire it into bootstrap, then apply.

Do not add Rust as a mise `[tools]` entry. Rust is installed with rustup
via the `install-rust` mise task. mise’s rust backend exports
`RUSTUP_TOOLCHAIN`, which overrides every repo-level `rust-toolchain.toml`.

Non-TTY agent shells: `chezmoi apply` without `--force` can fail with
`could not open a new TTY`. Use `--force` only when you intend to take the
source side of a merge conflict.

Chezmoi otherwise reads its configured default source. From the checkout
root, resolve the profile first, choose the affected destinations, then preview
with this worktree as source. Use a full preview when scripts or profile gates
change:

```bash
CHEZMOI_SOURCE=$(git rev-parse --show-toplevel)
PROFILE=$(chezmoi --source "$CHEZMOI_SOURCE" execute-template '{{ .profile }}')
case "$PROFILE" in personal|axon-work-computer|termux) ;; *) exit 1 ;; esac
printf 'profile: %s\n' "$PROFILE"
chezmoi --source "$CHEZMOI_SOURCE" apply --dry-run --verbose
```

Ask before applying to the live HOME, installing persistent tools, committing
or pushing, deleting unmanaged data, or changing a persistent service. A
disposable proof HOME may materialize its own files. An approved real apply
must match the reviewed dry-run. For a local change, name its managed
destination explicitly. For example, after approval to apply `.zshrc`:

```bash
chezmoi --source "$CHEZMOI_SOURCE" apply "$HOME/.zshrc"
```

For an approved Pi-patch change from a linked worktree, preview the full apply
first, then make the patch runner read the same payload tree:

```bash
PI_PATCHES_ROOT="$CHEZMOI_SOURCE/dot_local/share/pi-patches" \
  chezmoi --source "$CHEZMOI_SOURCE" apply
```

After a same-version Pi reinstall, the onchange trigger may stay unchanged.
Check every source payload against the installed Pi with the active profile;
`--check` does not write installed files:

```bash
for patch in "$CHEZMOI_SOURCE"/dot_local/share/pi-patches/*/patch.mjs; do
  [ -f "$patch" ] || continue
  PI_CHEZMOI_PROFILE="$PROFILE" mise exec -- node "$patch" --check || exit 1
done
```

If a check fails, inspect its diagnostic. With owner approval, rerun the
installed patch loop using this worktree's payloads and active profile:

```bash
PI_CHEZMOI_PROFILE="$PROFILE" \
PI_PATCHES_ROOT="$CHEZMOI_SOURCE/dot_local/share/pi-patches" \
  mise exec -- "$HOME/.local/user_scripts/apply_pi_patches.sh"
```

In a non-TTY shell, inspect a `could not open a new TTY` conflict. Add
`--force` only when taking the source side is intended. These instructions
are advisory; inspect rendered output, tests, and Git state to check the
boundaries they describe. Use the same source for verification:

```bash
chezmoi --source "$CHEZMOI_SOURCE" execute-template '{{ .profile }}'
chezmoi --source "$CHEZMOI_SOURCE" source-path "$HOME/.zshrc"
chezmoi --source "$CHEZMOI_SOURCE" managed --include=files "$HOME/.zshrc"
```

## Nested docs

Subtree procedure normally lives in [README.md](./README.md). The Learnings
monitor has one scoped `AGENTS.md` for its implementation and proof workflow.
Pi auto-loads `AGENTS.md` / `CLAUDE.md` from `~/.pi/agent/` then every ancestor
of cwd. When cwd is in that extension, its guide stacks on this file and the
Pi-global file. See the README Docs map for other subtree documents.

Shared subtree READMEs (relative from repo root):

- [Pi extensions](./dot_pi/private_agent/extensions/README.md) — shared authoring rules, including per-call `ctx`
- [Pi patches](./dot_local/share/pi-patches/README.md)
- [Neovim](./dot_config/nvim/README.md)
- [Session search](./dot_pi/session-search/README.md)

Keep other extension subtrees, `pi-patches/`, skills, and `dot_config/` free of
nested `AGENTS.md`. The Learnings monitor guide above is the only exception.
Do not create `~/AGENTS.md`. Claude and Codex already have
`dot_claude/CLAUDE.md.tmpl` and `dot_codex/modify_AGENTS.md.tmpl`.

## Completion and handoff

Done means all of the following that apply:

- Source files in **this** tree are updated; live `~` files were not hand-edited
  as if they were source.
- A source-scoped `chezmoi apply --dry-run --verbose` was run for the touched
  destinations.
- A real apply to the user's HOME ran only with explicit owner approval.
  Disposable proof HOME materialization was identified separately.
- No commit or push unless the user asked.
- Secrets, 1Password references, and `private_*` files were not given
  committed secret values.
- `~/.pi/agent/AGENTS.md` and its source
  `dot_pi/private_agent/literal_AGENTS.md.tmpl` were left intact; no
  `~/AGENTS.md` source was added.

Handoff must name:

- Changed source paths using chezmoi names; destination paths may follow
- Whether apply ran, with `--force` or not; name any disposable proof HOME
- Tests and outside-in proofs run, their outcomes, and skipped or failed checks
- Whether staging, commit, or push occurred; give a commit SHA when applicable
- Profile assumptions (`personal` / `axon-work-computer` / `termux`)
- Remaining manual steps (permissions, Docker Desktop license, gvm, and so on)
- Anything still destination-only (drift the user must choose source-vs-live)

Do not report a `chezmoi diff` interpretation without independent reads of
rendered source and live destination.
