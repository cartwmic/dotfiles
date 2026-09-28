# Chezmoi source — agent instructions

## Scope

This file is **only** for work in this repository: the chezmoi source tree at
`~/.local/share/chezmoi` (GitHub `cartwmic/dotfiles`). It is listed in
`.chezmoiignore` so chezmoi never deploys it. Do not copy it to `~/AGENTS.md`
or `~/.pi/agent/AGENTS.md`.

User-global Pi instructions are a **different file with different contents**:
source `dot_pi/private_agent/literal_AGENTS.md.tmpl` deploys to
`~/.pi/agent/AGENTS.md`. The source filename is `literal_AGENTS.md.tmpl` on
purpose: Pi only auto-loads `AGENTS.md` / `AGENTS.override.md` / `CLAUDE.md`.
If the source were named `AGENTS.md` under `dot_pi/private_agent/`, working
in an extension directory would
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
2. A component-local `AGENTS.md` — implementation and checks for that source
   subtree. It adds procedure inside its scope; this file still controls
   chezmoi operations and safety.
3. `~/.pi/agent/AGENTS.md` — cross-project habits (hindsight, communication).
   It must not be treated as a second copy of this guide.
4. `README.md` and component READMEs — human product, setup, and usage. Do not
   treat them as apply/edit procedure.

Load a task-specific skill when its description matches the work. Its
procedure operates within this repository's source and apply boundaries.

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
must be encrypted in source. A `personal` apply invokes the RustDesk helper;
it stops when `op` cannot read `op://developer/RustDesk/password`. Before an
authorized personal apply, confirm that the owner's desktop-app authentication
or host-local service-account token can read that item. Stop and ask the owner
to provision access if it cannot; never print the password.

RustDesk: do not sync `RustDesk.toml`, `RustDesk_local.toml`, or
`RustDesk_hwcodec.toml`. The unattended password is only
`op://developer/RustDesk/password`. Shared passwords increase blast radius
across every managed host. For service paths and password rotation, inspect
`dot_local/user_scripts/executable_configure_rustdesk.sh.tmpl` and
`run_onchange_after_60_configure_rustdesk.sh.tmpl` before changing source.
Do not run the helper through the RustDesk session being reconfigured.

SSH: `private_dot_ssh/modify_authorized_keys` is append-safe and must stay
non-destructive to foreign keys.

Agent harness: canonical skills and MCP live under
`dot_local/share/agent-harness/`. Adapters project into Claude, Codex, and
Pi. Do not put harness-specific semantics in canonical files. After skill
or MCP changes, apply with the commands below (or `chezmoi apply`, which
runs the apply script).

Pi runtime patches: `dot_local/share/pi-patches/<name>/patch.mjs`. After
`npm update -g` / mise reinstall of Pi, patches must be reapplied through
that mechanism, not by hand-editing installed `dist/` files. A same-version
reinstall may not retrigger chezmoi's onchange script. For an approved patch
apply from a worktree, set `PI_PATCHES_ROOT="$REPO/dot_local/share/pi-patches"`
and the actual `PI_CHEZMOI_PROFILE`; follow the patch guide's checks. The
standing-reminder extension also requires its input-origin patch. Validate
that pair through `tests/standing-reminder/isolated_pi.py`, which patches a
private Pi copy rather than the installed runtime.

OpenSpec/`opsx` is retired; do not revive it. Do not write ADRs.

Pi extensions in this tree: never capture `ExtensionContext` `ctx` in a
long-lived closure; use the per-call `ctx`. Do not couple new extensions
to retired opsx. System One is a Git package enabled only in personal Pi
settings; its local extension directory is docs-only. Load its scoped guide
before changing that package entry. Do not add a local loader that registers
its tools twice.

Adding a mise-registry tool: edit `dot_config/mise/config.toml` `[tools]`,
then apply. Custom install: add a `[tasks]` entry with an idempotent
`condition`, wire it into bootstrap, then apply.

Do not add Rust as a mise `[tools]` entry. Rust is installed with rustup
via the `install-rust` mise task. mise’s rust backend exports
`RUSTUP_TOOLCHAIN`, which overrides every repo-level `rust-toolchain.toml`.

Non-TTY agent shells: `chezmoi apply` can fail with
`could not open a new TTY`. Stop and inspect the rendered source and live
destination separately. A merge conflict needs an owner choice of source or
live state; only an approved source-side choice permits `--force`. A TTY
failure without an understood conflict is not permission to force.

Use `chezmoi --source "$REPO"` when working in a feature worktree; cwd alone
does not change chezmoi's configured source. Inspect `.chezmoiremove` before
apply, including any persistent directories it would remove. For canonical
skill sync from a worktree, also set `CHEZMOI_SOURCE_DIR="$REPO"` so the adapter
does not read the base checkout instead.

Typical loop:

```bash
REPO="$(git rev-parse --show-toplevel)"
chezmoi --source "$REPO" apply --dry-run --verbose
chezmoi --source "$REPO" execute-template '{{ .profile }}'
```

For a touched destination, resolve its source, render it, read the live file
independently, and inspect the targeted dry-run before requesting apply.
Replace `DEST` with the path you changed:

```sh
DEST="$HOME/.zshrc"
chezmoi source-path "$DEST"
chezmoi cat "$DEST"             # rendered source
chezmoi apply --dry-run --verbose "$DEST"
```

`chezmoi cat` can render secrets. Keep their values out of logs and chat. Use
the same `DEST` for any approved apply.

Ask before a live apply, committing, pushing, restarting an owner's server,
or removing persistent user state. Never edit a managed live destination as if
it were source; never put a secret in Git. Only clean up test resources your
own check created. These markdown rules are advisory. `.chezmoiignore`
mechanically excludes the root agent guide from home deployment; do not
assume a hook enforces the other boundaries.

After approval to take the source side of a specific merge conflict, a
non-TTY apply may target that destination with `chezmoi apply --force ~/.zshrc`.
Stop and ask on any other TTY failure.

Validate templates with `chezmoi execute-template` and destination mapping
with `chezmoi managed` / `chezmoi source-path <dest>`.

## Nested docs

[README.md](./README.md) is the human guide. A nested `AGENTS.md` holds
component-specific implementation procedure and traps. Pi loads the global
agent-directory instructions, then each ancestor `AGENTS.md` of the cwd. Work
inside one of these source subtrees loads this file and its local guide:

- [Pi inspector](./dot_pi/private_agent/extensions/inspect-prompt/AGENTS.md) — fullscreen conversation snapshots, editor return, and private Pi/Herdr journeys.
- [Learnings monitor](./dot_pi/private_agent/extensions/learnings-monitor/AGENTS.md) — opt-in observer, local records, confirmed promotion, and work-bank verification.
- [Standing reminder](./dot_pi/private_agent/extensions/standing-reminder/AGENTS.md) — session-current state, input-origin patch, and isolated Pi proof.
- [System One Pi integration](./dot_pi/private_agent/extensions/system-one/AGENTS.md) — personal Git package settings, isolated checks, and rollout.
- [Herdr plugin runtime](./dot_local/share/herdr-overview/AGENTS.md) — native model, naming, grouping, and isolated server proof.
- [Herdr Pi adapter](./dot_pi/private_agent/extensions/herdr-overview/AGENTS.md) — settled publication and caller-aware membership.
- [session-recap](./dot_local/share/session-recap/AGENTS.md) — standalone prompt/store invariants.
- [passage-review](./dot_local/share/passage-review/AGENTS.md) — snapshot, note, export, and phone-local invariants.
- [passage-review Pi adapter](./dot_pi/private_agent/extensions/passage-review/AGENTS.md) — `/review` TUI entry and process handoff.

For common Pi extension procedure, read
[dot_pi/private_agent/extensions/README.md](./dot_pi/private_agent/extensions/README.md)
when editing an extension. Other subtree guides are task-specific:
[pi-patches](./dot_local/share/pi-patches/README.md),
[Neovim](./dot_config/nvim/README.md), and
[session-search](./dot_pi/session-search/README.md). Use those guides when
working in their directories; avoid a second always-on rules file there.
Ask before adding more nested `AGENTS.md` files. Do not create `~/AGENTS.md`.
Claude and Codex already have `dot_claude/CLAUDE.md.tmpl` and
`dot_codex/modify_AGENTS.md.tmpl`.

## Completion and handoff

Done means all of the following that apply:

- Source files in **this** tree are updated; live `~` files were not hand-edited
  as if they were source.
- `chezmoi apply --dry-run --verbose` was run for the touched destinations.
- A real `chezmoi apply` ran only with explicit user approval. If verification
  requires materializing and approval is absent, name that check as pending.
- No commit or push unless the user asked.
- Secrets, 1Password references, and `private_*` files were not given
  committed secret values.
- `~/.pi/agent/AGENTS.md` / `dot_pi/private_agent/literal_AGENTS.md.tmpl`
  was not overwritten with this file’s contents, and no `~/AGENTS.md` source
  was added.

Handoff must name:

- Source paths changed (use chezmoi names; include destinations when helpful)
- Whether apply ran, with `--force` or not
- Profile assumptions (`personal` / `axon-work-computer` / `termux`)
- Remaining manual steps (permissions, Docker Desktop license, gvm, and so on)
- Anything still destination-only (drift the user must choose source-vs-live)

Do not report a `chezmoi diff` interpretation without independent reads of
rendered source and live destination.
