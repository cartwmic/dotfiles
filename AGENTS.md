# Chezmoi source — agent instructions

## Scope

This file is **only** for work in this repository: the chezmoi source tree at
`~/.local/share/chezmoi` (GitHub `cartwmic/dotfiles`). It is listed in
`.chezmoiignore` so chezmoi never deploys it. Do not copy it to `~/AGENTS.md`
or `~/.pi/agent/AGENTS.md`.

User-global Pi instructions are a **different file with different contents**:
source `dot_pi/agent/literal_AGENTS.md` deploys to `~/.pi/agent/AGENTS.md`.
The source filename is `literal_AGENTS.md` on purpose: Pi only auto-loads
`AGENTS.md` / `AGENTS.override.md` / `CLAUDE.md`. If the source were named
`AGENTS.md` under `dot_pi/agent/`, working in an extension directory would
load the live dest **and** the source (same text, two paths).

Do not add a `~/AGENTS.md` source. Chezmoi ignore and source mapping use the
**destination** name. Repo `AGENTS.md` and any source that would deploy to
`~/AGENTS.md` are the same target; chezmoi reports `inconsistent state`.

This repository is a public personal dotfiles source. Chezmoi maps it onto
`$HOME`. Edit **source** files here; live files under `~` are generated.

## Authority

Precedence when the cwd is this repo:

1. This file — repository operations, source naming, apply/verify, secrets
   handling for files in this tree.
2. `~/.pi/agent/AGENTS.md` — cross-project habits (hindsight, communication).
   It must not be treated as a second copy of this guide.
3. `README.md` — human product and onboarding. Use it for install, profiles,
   and what the machine will contain. Do not treat it as apply/edit procedure.

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

Non-TTY agent shells: `chezmoi apply` without `--force` can fail with
`could not open a new TTY`. Use `--force` only when you intend to take the
source side of a merge conflict.

Typical loop:

```bash
chezmoi apply --dry-run --verbose
chezmoi execute-template '{{ .profile }}'
chezmoi apply --dry-run --verbose --force
```

Apply for real only when the dry-run matches intent. Prefer targeting a
path (`chezmoi apply ~/.zshrc`) over a full apply when the change is local.

From a non-TTY agent shell, add `--force` to `chezmoi apply` when chezmoi
refuses to open `/dev/tty`.

Validate templates with `chezmoi execute-template` and destination mapping
with `chezmoi managed` / `chezmoi source-path <dest>`.

## Nested docs

Subtree procedure lives in [README.md](./README.md), not another `AGENTS.md`.
Pi auto-loads `AGENTS.md` / `CLAUDE.md` from `~/.pi/agent/` then every ancestor
of cwd. A nested `AGENTS.md` in this tree therefore stacks on this file and the
Pi-global file. See README Docs map for where READMEs belong.

Shared subtree READMEs (relative from repo root):

- [dot_pi/agent/extensions/README.md](./dot_pi/agent/extensions/README.md) — shared extension rules, including never capture `ctx`
- [dot_local/share/pi-patches/README.md](./dot_local/share/pi-patches/README.md)
- [dot_config/nvim/README.md](./dot_config/nvim/README.md)
- [dot_pi/session-search/README.md](./dot_pi/session-search/README.md)

Do not add `AGENTS.md` under `dot_pi/agent/extensions/`, `pi-patches/`,
skills, `dot_config/`, or `~/AGENTS.md`. Claude and Codex already have
`dot_claude/CLAUDE.md.tmpl` and `dot_codex/modify_AGENTS.md.tmpl`.

## Completion and handoff

Done means all of the following that apply:

- Source files in **this** tree are updated; live `~` files were not hand-edited
  as if they were source.
- `chezmoi apply --dry-run --verbose` was run for the touched destinations.
- A real `chezmoi apply` ran only if the user asked to apply, or the task
  cannot be verified without materializing (say so).
- No commit or push unless the user asked.
- Secrets, 1Password references, and `private_*` files were not given
  committed secret values.
- `~/.pi/agent/AGENTS.md` / `dot_pi/agent/literal_AGENTS.md` was not overwritten with
  this file’s contents, and no `~/AGENTS.md` source was added.

Handoff must name:

- Source paths changed (chezmoi names, not only destination paths)
- Whether apply ran, with `--force` or not
- Profile assumptions (`personal` / `axon-work-computer` / `termux`)
- Remaining manual steps (permissions, Docker Desktop license, gvm, and so on)
- Anything still destination-only (drift the user must choose source-vs-live)

Do not report a `chezmoi diff` interpretation without independent reads of
rendered source and live destination.
