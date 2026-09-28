# Working on the System One Pi integration

## Scope and authority

This directory is chezmoi documentation for the Git package listed in `dot_pi/private_agent/private_settings.json.tmpl`. It contains no extension entry point. Pi loads code from `cartwmic/system-one-tools`; runtime changes belong there, under its [repository procedure](https://github.com/cartwmic/system-one-tools/blob/main/AGENTS.md). A local `index.js` would register a second tool. Repo-root `AGENTS.md` controls source naming, apply, profile gates, secrets, and Git. [README.md](README.md) is the human setup and usage guide. This scoped procedure applies whenever the System One package entry or these docs are maintained. Pi auto-loads it when cwd is under this directory; load it explicitly from another cwd.

## Workflow

Work from the current chezmoi worktree. Keep the Git package entry inside the `personal` settings branch and exclude this docs directory on work and Termux in `.chezmoiignore`. Confirm the profile is `personal` and map each destination separately. The settings template reads the existing live JSON during rendering to preserve `lastChangelogVersion`, `theme`, and `hideThinkingBlock`; check that file's JSON first. A successful targeted dry-run is required; unchanged destinations need not appear in its output.

```sh
set -eu
REPO="$(git rev-parse --show-toplevel)"
profile=$(chezmoi --source "$REPO" execute-template '{{ .profile }}')
[ "$profile" = personal ] || { printf 'Expected personal profile; got %s\n' "$profile" >&2; exit 1; }
for dest in "$HOME/.pi/agent/settings.json" "$HOME/.pi/agent/extensions/system-one/README.md" "$HOME/.pi/agent/extensions/system-one/AGENTS.md"; do
  chezmoi --source "$REPO" source-path "$dest"
done
if [ -e "$HOME/.pi/agent/settings.json" ]; then
  jq -e 'type == "object"' "$HOME/.pi/agent/settings.json" >/dev/null
fi
chezmoi --source "$REPO" apply --dry-run --verbose "$HOME/.pi/agent/settings.json" "$HOME/.pi/agent/extensions/system-one/README.md" "$HOME/.pi/agent/extensions/system-one/AGENTS.md"
chezmoi --source "$REPO" cat "$HOME/.pi/agent/settings.json" | jq -e '.packages | index("https://github.com/cartwmic/system-one-tools") != null'
git -C "$REPO" diff --check # tracked changes only; see staged check below for new docs
```

The work profile omits the package entry and docs; Termux omits `.pi` entirely. In a private terminal, inspect the complete rendered settings and live destination independently before taking the source side of drift:

```sh
chezmoi --source "$REPO" cat "$HOME/.pi/agent/settings.json" | less
less "$HOME/.pi/agent/settings.json"
```

Do not paste their contents into logs. Check `.chezmoiremove` for unrelated persistent data. A real apply needs the owner's approval. After an approved settings-only apply, restart Pi and check `pi list` plus `/so status` in a fresh session. `/so status` verifies command loading without a provider call; `pi list` alone only reports configuration.

The Git URL is unpinned. Ask before updating or installing in the regular Pi environment. For a System One-only update, run `pi update https://github.com/cartwmic/system-one-tools` after approval; record the installed checkout revision before and after. Test the exact new HEAD in a disposable clone, keeping the installed Pi checkout untouched:

```sh
set -eu
installed="$HOME/.pi/agent/git/github.com/cartwmic/system-one-tools"
before=$(git -C "$installed" rev-parse HEAD)
pi update https://github.com/cartwmic/system-one-tools
after=$(git -C "$installed" rev-parse HEAD)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git clone --quiet "$installed" "$tmp"
git -C "$tmp" checkout --quiet --detach "$after"
( cd "$tmp" && npm ci && npm run check && npm run test:journey && npm run test:tui )
```

`npm run check` rebuilds the shared `dist/` used by focused tests. Inspect the TAP result for the selected TUI journey completing successfully; `test:tui` filters by name, so other cases in that file appear as intentional skips. Run `npm run test:package` in that clone for packaging claims (macOS with Docker). Record `before`, `after`, and test outcomes; a settings dry-run or old `/so status` cannot prove new code. Restart Pi after the approved update and check `/so status` in a fresh session.

Choose proof by claim: source mapping needs the targeted dry-run; command loading needs fresh `/so status`; Pi session controls and manual ask need `test:tui`; shared CLI/Pi caller behavior needs `test:journey`. Run both for a claim spanning session controls and cross-caller behavior. Packaging needs `test:package`. Agent access starts off: use `/so on` for this session or `/so settings` for user-global defaults; project-local Pi settings cannot enable it. An OpenRouter URL alone leaves the native `/systemone` adapter selected; choose OpenRouter Decisions explicitly in `/so settings`. A live-provider claim must name the adapter, route, model, and caller path first. Ask before a bounded paid call, then test that exact path (`/so ask` for manual use, `system_one` for agent use). Connections live in the machine-local `${XDG_CONFIG_HOME:-$HOME/.config}/system-one/connections.json`; select one with `/so settings` and store only the credential variable name. Credential values belong in the runtime environment, never this public tree or catalog. These markdown rules are advisory. The preflight `git diff --check` omits untracked docs. Before claiming validation or committing, stage only approved paths, run `git diff --cached --check`, and inspect the staged diff for secrets and duplicate entry points. No repository hook or CI gate enforces them here.

## Completion and handoff

Report the changed chezmoi source paths, profile, dry-run result, and whether settings and these docs were applied. If settings were applied, report `pi list` and fresh `/so status` results or why either was skipped. For an approved package update, include the before/after installed revisions, checks against the new HEAD, and fresh `/so status` result (or why it was skipped). State destination-only drift and actual commit/push state. Leave unrelated work in the base checkout alone.
