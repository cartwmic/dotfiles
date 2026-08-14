# Home agent instructions (Pi global)

## Scope

These instructions apply on this machine for **every** Pi session. They live
at `~/.pi/agent/AGENTS.md` (chezmoi source `dot_pi/agent/literal_AGENTS.md`).
Pi loads this file from its agent directory first, then walks ancestors from
the cwd. The source is named `literal_AGENTS.md` so Pi’s ancestor walk does
**not** also pick it up when the cwd is under `dot_pi/agent/` in this repo
(that would be the same text twice: live dest + source).

They are **not** the chezmoi repository guide. That guide is a different
file with different contents: `~/.local/share/chezmoi/AGENTS.md` (git only;
chezmoi does not deploy it). Never copy one file over the other.

Do not create `~/AGENTS.md` as a second global copy. Pi’s ancestor walk would
load it in addition to this file. Chezmoi also cannot manage `~/AGENTS.md`
while the repo keeps a root `AGENTS.md` (same destination name).

When the cwd is inside `~/.local/share/chezmoi`, both files load. Use this
file for cross-project habits; use the chezmoi `AGENTS.md` for source
naming, apply, profiles, and other repo operations.

## Authority

- Project `AGENTS.md` / `CLAUDE.md` in a working tree adds or overrides
  **repository** procedure for that tree.
- This file does not grant authority to edit live dotfiles as if they were
  source. Dotfiles source is `~/.local/share/chezmoi`.
- This home is a personal machine with a public dotfiles repo. Treat every
  working tree as potentially publishable unless that repo’s own docs say
  otherwise.
- Hindsight (MCP `hindsight`) is shared across Pi, Claude Code, and Codex.
  Honor recall/retain/reflect rules from that server’s contract. In Pi,
  auto-recall may inject `<hindsight_memories>` — use it; do not re-recall
  the same ground unless the request goes wider. `retain` is asynchronous.
- Do not commit secrets. Read them at runtime (`op read`, or the project’s
  own secret path). The 1Password service-account token lives at
  `~/.config/agent-harness/op-service-token` (mode 0600, not in git).

Harness-specific always-on notes (Pi `APPEND_SYSTEM.md`, Claude output
styles, Codex `~/.codex/AGENTS.md` managed block) remain in those files.
Do not duplicate them here.

## Workflow

Start by identifying the tree and which instruction files apply:

```bash
pwd
git rev-parse --show-toplevel 2>/dev/null || true
ls -la "$HOME/.pi/agent/AGENTS.md" "$HOME/.local/share/chezmoi/AGENTS.md"
```

Then:

1. Read this file as user-global Pi policy.
2. If a project `AGENTS.md` (or `CLAUDE.md`) exists at the repo root, follow
   it for that repo’s build, test, and commit rules.
3. If the toplevel is `~/.local/share/chezmoi`, follow **that** repo’s
   `AGENTS.md` for chezmoi operations — not this file.
4. Prefer editing files the user is maintaining. Do not “fix” generated
   home files that chezmoi owns; change chezmoi source and apply.
5. Do not commit unless asked. Do not push unless asked. Do not force-push
   `main`/`master`.
6. Ask when a consequential choice is underspecified (scope, target,
   approach). Do not guess a destructive default.

Validation for a generic git project (override with the project’s own
commands when present):

```bash
git status -sb
git diff
```

## Completion and handoff

Done means:

- The requested work in the **current** tree is complete or blocked with a
  concrete reason.
- Project-local checks named by that repo were run, or you stated why not.
- No secret landed in git, chat logs, or a gist.
- Chezmoi source `AGENTS.md` and this file were not collapsed into one
  document, and `~/AGENTS.md` was not created as a duplicate global.

Handoff must include: repo / cwd, what changed, how it was verified, what
was not applied or committed, and any follow-up the user still owns.
