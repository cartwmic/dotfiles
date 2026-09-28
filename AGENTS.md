# Chezmoi source — agent instructions

## Scope

This file is **only** for work in this repository: the chezmoi source tree
(normally `~/.local/share/chezmoi`, including its Git worktrees; GitHub
`cartwmic/dotfiles`). It is listed in
`.chezmoiignore` so chezmoi never deploys it. Do not copy it to `~/AGENTS.md`
or `~/.pi/agent/AGENTS.md`.

User-global Pi instructions are a **different file with different contents**:
source `dot_pi/private_agent/literal_AGENTS.md.tmpl` deploys to `~/.pi/agent/AGENTS.md`.
The source filename is `literal_AGENTS.md.tmpl` on purpose: Pi only auto-loads
`AGENTS.md` / `AGENTS.override.md` / `CLAUDE.md`. If the source were named
`AGENTS.md` under `dot_pi/private_agent/`, working in an extension directory
would load the live dest **and** the source (same text, two paths).

Do not add a `~/AGENTS.md` source. Chezmoi ignore and source mapping use the
**destination** name. Repo `AGENTS.md` and any source that would deploy to
`~/AGENTS.md` are the same target; chezmoi reports `inconsistent state`.

This repository is a public personal dotfiles source. Chezmoi maps it onto
`$HOME`. Edit **source** files here; live files under `~` are generated.

## Authority

When the cwd is this repo, use this order for the applicable work:

1. This file controls repository-wide source naming, apply, profiles, secrets,
   and Git. The scoped `dot_pi/private_agent/extensions/system-one/AGENTS.md`
   adds package-settings procedure for changes to that directory or its Pi
   settings entry. Load it explicitly when the cwd is elsewhere; it does not
   replace this repo-wide apply authority.
2. `~/.pi/agent/AGENTS.md` supplies cross-project habits (hindsight and
   communication). Do not sync its contents with this guide.
3. Load a specialized skill when its task applies; follow it for that workflow
   within the repository boundaries above. Historical `docs/plans/` are not
   operative policy.
4. [README.md](./README.md) is human onboarding and a map to subtree guides.
   Use this file and the scoped AGENTS.md for agent apply/edit decisions.

Generated destinations (`~/.zshrc`, `~/.pi/agent/settings.json`, and so on)
are not the source of truth. Templated files cannot be captured with
`chezmoi re-add` (it is a silent no-op). Change the source template, then
apply. `create_` sources leave an existing destination untouched; inspect
that live file before deciding how to change it. See the
[extension guide](./dot_pi/private_agent/extensions/README.md) when editing
extension `create_config.json` files.

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

Before the first or any later apply, inspect `.chezmoiremove` for persistent
destinations it would delete. It includes the old `~/termux` staging tree and
`~/.local/share/openspec`. Ask the owner before removing any persistent
directory whose contents or ownership are unclear.

Profiles (`~/.config/chezmoi/chezmoi.yaml` → `data.profile`): `personal`,
`axon-work-computer`, `termux`. `.chezmoiignore` is the authority for what
each profile deploys.

Secrets: never commit API keys, tokens, or passwords. Read secrets at
runtime with 1Password (`op read`, service-account token at
`~/.config/agent-harness/op-service-token`, mode 0600, outside this repo).
`private_dot_zshrc` is the pattern. `rage`/age is available for files that
must be encrypted in source. This markdown is advisory; inspect the staged
diff for secret values before any approved commit. No repository hook or CI
secret gate currently enforces this rule.

RustDesk: portable settings are in `.chezmoidata.toml`; use the
[configuration helper and stop procedure](./README.md#rustdesk-provisioning)
when changing them. Do not run the helper through the RustDesk session being
reconfigured. Keep `RustDesk.toml`, `RustDesk_local.toml`, and
`RustDesk_hwcodec.toml` machine-local. The unattended password is only
`op://developer/RustDesk/password`. Shared passwords increase blast radius
across every managed host.

SSH: `private_dot_ssh/modify_authorized_keys` is append-safe and must stay
non-destructive to foreign keys.

Agent harness: canonical skills and MCP live under
`dot_local/share/agent-harness/`. Adapters project into Claude, Codex, and
Pi. Keep harness-specific semantics in adapters. For skill changes, follow
the [interactive skill-sync path](./dot_local/share/agent-harness/README.md#add-a-canonical-skill)
after the explicit-source dry-run and approved canonical-source apply. Set
`CHEZMOI_SOURCE_DIR="$REPO"` for its preview and sync; otherwise it reads the
base checkout and may replace worktree changes. For
MCP changes, follow the [MCP path](./dot_local/share/agent-harness/README.md#add-a-canonical-mcp-server)
and verify the harness outputs after an approved apply. The linked guide
owns those adapter commands; this file owns the source, dry-run, and approval
boundary.

Pi runtime patches: `dot_local/share/pi-patches/<name>/patch.mjs`. Load the
[patch guide](./dot_local/share/pi-patches/README.md) when adding a patch or
after reinstalling Pi; it owns the onchange hash line and per-patch checks.
A same-version reinstall may not trigger the wrapper. After an approved
reinstall, run the patch script with the actual `PI_CHEZMOI_PROFILE` and
`PI_PATCHES_ROOT="$REPO/dot_local/share/pi-patches"`. Run the applicable
per-patch `--check` commands; report checks the guide does not cover. Do not
hand-edit installed Pi `dist/` files.

OpenSpec/`opsx` is retired. Make current changes directly in source, validate
them through the checks below, and hand off the result. Do not revive opsx or
write ADRs.

Pi extensions in this tree: use the per-call `ExtensionContext` `ctx`; do
not capture it in a long-lived closure. When editing a local extension, load
the [extension guide](./dot_pi/private_agent/extensions/README.md).
`dot_pi/private_agent/extensions/system-one/` is docs-only: the `personal`
settings template loads a public Git package. For that subtree, load its
[scoped AGENTS.md](./dot_pi/private_agent/extensions/system-one/AGENTS.md)
before changing settings or validating the installed package. A local
`index.js` would register the tool twice. A dry-run proves chezmoi rendering
only.

Adding a mise-registry tool: edit `dot_config/mise/config.toml` `[tools]`.
Custom install: add a `[tasks]` entry with an idempotent `condition` and wire
it into bootstrap. A targeted config apply may leave the onchange bootstrap
script out of scope; after an approved deploy, run `mise install` and
`mise run bootstrap` explicitly if that script did not run. Verify the tool.

Do not add Rust as a mise `[tools]` entry. Rust is installed with rustup
via the `install-rust` mise task. mise’s rust backend exports
`RUSTUP_TOOLCHAIN`, which overrides every repo-level `rust-toolchain.toml`.

Non-TTY agent shells: `chezmoi apply` without `--force` can fail with
`could not open a new TTY`. Use `--force` only when you intend to take the
source side of a merge conflict.

Use the current checkout explicitly. An implicit chezmoi source still points
to the configured base checkout when cwd is in a feature worktree. Before
previewing, inspect the active chezmoi config's `read-source-state.pre` hook:
the example invokes `.install-password-manager.sh`, which can install `op`
and reads `utils.sh` from the base checkout. Work-profile template rendering
may also call `op read`; inspect rendered output privately without logging
secret values. For a local change, pass its destinations to the dry-run:

```bash
REPO="$(git rev-parse --show-toplevel)"
chezmoi --source "$REPO" execute-template '{{ .profile }}'
chezmoi --source "$REPO" source-path "$HOME/.pi/agent/settings.json"
chezmoi --source "$REPO" apply --dry-run --verbose "$HOME/.pi/agent/settings.json"
```

Replace the settings path with the changed destinations; the scoped System
One guide lists its three exact targets. Require a successful, intended
dry-run before a real apply. Ask the owner before every real apply, including
one needed for validation; otherwise report that proof as blocked. An
existing installation needs independent inspection of its config and the
rendered and live destinations. Prefer a targeted apply for local files; use
a full apply only when the task needs its after-scripts and the full dry-run
matches intent. In a non-TTY shell, use `--force` only after choosing the
source side of a known conflict. Render a changed template with
`chezmoi --source "$REPO" cat "$HOME/<destination>"` and check mapping with
`chezmoi --source "$REPO" managed` / `source-path`.

## Nested docs

Human subtree how-tos live in [README.md](./README.md) and linked guides.
`dot_pi/private_agent/extensions/system-one/AGENTS.md` is the single scoped
agent guide for the remote Pi package's settings/docs maintenance. Pi loads
`AGENTS.md` / `CLAUDE.md` from `~/.pi/agent/` then every ancestor of cwd, so
it stacks with this guide only when cwd is in that extension directory.

Load the [Pi extension guide](./dot_pi/private_agent/extensions/README.md)
when editing a local extension (`ctx`, `create_`, and profile traps). Load the
[patch guide](./dot_local/share/pi-patches/README.md) when changing or
reapplying a Pi runtime patch (including its onchange hash line). Use
[Neovim](./dot_config/nvim/README.md) and
[session-search](./dot_pi/session-search/README.md) guides only for those
subtrees.

Do not add another `AGENTS.md` under `dot_pi/private_agent/extensions/`,
`pi-patches/`, skills, `dot_config/`, or `~/AGENTS.md`. The System One file above
is the only exception. Claude and Codex already have `dot_claude/CLAUDE.md.tmpl`
and `dot_codex/modify_AGENTS.md.tmpl`.

## Completion and handoff

Done means all of the following that apply:

- Source files in **this** tree are updated; live `~` files were not hand-edited
  as if they were source.
- A targeted `chezmoi --source "$REPO" apply --dry-run --verbose` succeeded
  for the touched destinations, or the blocker and output are reported.
- A real `chezmoi apply` ran only after the owner approved its exact scope.
  If verification needs materialization without approval, report the blocker.
- No commit or push unless the user asked.
- Secrets, 1Password references, and `private_*` files were not given
  committed secret values.
- `~/.pi/agent/AGENTS.md` /
  `dot_pi/private_agent/literal_AGENTS.md.tmpl` was not overwritten with this
  file’s contents, and no `~/AGENTS.md` source was added.

Handoff must name:

- Source paths changed (chezmoi names; destination paths are optional)
- Dry-run result, exact destinations applied or left unapplied, and whether
  `--force` was used
- For an applied System One settings change, results of `pi list` and a fresh
  `/so status`, or why either was not run
- Profile assumptions (`personal` / `axon-work-computer` / `termux`)
- Remaining manual steps (permissions, Docker Desktop license, gvm, and so on)
- Anything still destination-only (drift the user must choose source-vs-live)
- Actual commit and push state (including neither, when neither was authorized)

Do not report a `chezmoi diff` interpretation without independent reads of
rendered source and live destination.
