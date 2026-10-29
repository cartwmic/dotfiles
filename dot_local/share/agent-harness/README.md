# Agent Harness

This directory contains the canonical, harness-agnostic configuration sources and thin per-harness adapters used to project them into Claude, Codex, and future agent harnesses.

## Layout

```text
dot_local/share/agent-harness/
  canonical/
    instructions/
      AGENTS.md
      hindsight-guidance.md
    mcp/
      servers.json.tmpl
    skills/
      ...
  adapters/
    claude/
      mcp-secrets.json.tmpl
    codex/
      mcp-secrets.json.tmpl
    pi/
      mcp-secrets.json.tmpl
```

Rules:

- `canonical/` is the source of truth.
- Canonical sources should stay standards-based.
- Pi 0.99+ uses native MCP and codemode, not `pi-mcp-adapter`. The Pi adapter
  still generates `~/.pi/agent/mcp.json` from these canonical sources and
  preserves manually added servers. It records the names it writes in
  `~/.local/share/agent-harness/generated/pi/mcp-managed.json` and removes a recorded
  name from `mcp.json` once canonical (or this profile's render) no longer has it;
  `furi` and `automation-mcp` are also removed because they were managed before the
  record existed. Manage connections with `/mcp`; use
  `codemode` for tool discovery and batching instead of `mcp`/`mcpScript`.
  Both desktop profiles use codemode's `only` mode: ordinary tools remain
  callable from scripts rather than directly declared to the model.
  Hindsight's automatic hooks use REST and are independent of MCP.
- The Pi adapter wraps the local `playwright` and `rea` entries in `~/.local/bin/pi-mcp-lazy` (names in
  `~/.local/share/pi-mcp-lazy/servers.list`) so Pi starts them on first use and stops them when idle. Claude and Codex
  keep the canonical entries. See [`pi-mcp-lazy`](../pi-mcp-lazy/README.md).
- `adapters/` may contain harness-specific metadata needed to project canonical sources into a given harness.
- Do not put harness-specific semantics into canonical files unless the open standard itself requires them.

## Add A Canonical Instruction

Edit a file under [`canonical/instructions/`](./canonical/instructions/). These
fragments are included into every harness. Do not copy them by hand:

- Pi: [`dot_pi/private_agent/literal_AGENTS.md.tmpl`](../../../dot_pi/private_agent/literal_AGENTS.md.tmpl) (`~/.pi/agent/AGENTS.md`)
- Claude: [`dot_claude/CLAUDE.md.tmpl`](../../../dot_claude/CLAUDE.md.tmpl) (Claude's user-global filename is `CLAUDE.md`)
- Codex: [`dot_codex/modify_AGENTS.md.tmpl`](../../../dot_codex/modify_AGENTS.md.tmpl) (`~/.codex/AGENTS.md` managed block)

Guidelines:

- One concern per file. Keep fragments includable (a section heading is fine; do not add a document H1).
- Shared standing rules live in [`canonical/instructions/AGENTS.md`](./canonical/instructions/AGENTS.md). Include that file into each harness's `AGENTS.md` (Claude: `CLAUDE.md`). Do not create `~/AGENTS.md`. Do not put shared rules in Pi `APPEND_SYSTEM.md`.
- Follow [Apply and Verify](#apply-and-verify), then check the live destination files.

Current files: [AGENTS.md](./canonical/instructions/AGENTS.md) (the design-principles pointer, scripts vs skills, voice, subagents, decisions and doors) and [hindsight-guidance.md](./canonical/instructions/hindsight-guidance.md).

## Add A Canonical MCP Server

Edit [`canonical/mcp/servers.json.tmpl`](./canonical/mcp/servers.json.tmpl).

Guidelines:

- Keep the definition in standard MCP form.
- Prefer the smallest portable shape that works across harnesses.
- Do not put `op://...` references or other secret manager details in the canonical file.
- Use harness adapter metadata for secrets or harness-only behavior.

Example stdio server:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["my-server", "mcp"]
    }
  }
}
```

Example HTTP server:

```json
{
  "mcpServers": {
    "context7": {
      "type": "http",
      "url": "https://mcp.context7.com/mcp",
      "headers": {
        "CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"
      }
    }
  }
}
```

After editing the canonical MCP file:

1. If the server needs secrets, add or update adapter metadata in `adapters/<harness>/mcp-secrets.json.tmpl`.
2. Follow [Apply and Verify](#apply-and-verify) for the changed source.
3. Verify the harness-specific result:
   - Claude: `claude mcp list`
   - Codex: `codex mcp list`
   - Pi: `pi mcp list`, then `/mcp` in a fresh Pi session

TickTick uses the official server at `https://mcp.ticktick.com` in the personal
and work desktop profiles. Sign in separately on each machine and in each
harness: `pi mcp login ticktick`, `codex mcp login ticktick`, or Claude's `/mcp`
menu. Credentials stay in the harness's local OAuth store, not in canonical
configuration or 1Password adapter metadata. In a running Pi session, use
`/reload` after applying, then `/mcp login ticktick`.

## Agent browser

A logged-in Chrome that agents can drive. macOS only, on both desktop profiles (`personal` and `axon-work-computer`).
The work profile is on by Michael's decision (2026-10-29 11:33 PDT); the work Mac gets it only when Michael or the work
coordinator runs `chezmoi apply` and the mise bootstrap there.

| Piece | Source | Lands at |
|---|---|---|
| Google Chrome (brew cask) | `install-google-chrome` task in `dot_config/mise/config.toml`, part of `bootstrap` | `/Applications/Google Chrome.app` |
| Launcher | `dot_local/bin/executable_agent-chrome` | `~/.local/bin/agent-chrome` |
| MCP server `browser-harness` | `canonical/mcp/servers.json.tmpl` | `uvx --from "browser-harness[mcp]==0.1.13" browser-harness-mcp`, `BU_CDP_URL=http://127.0.0.1:9333` |

The server entry is canonical, so Claude and Codex are given it too, as with every canonical server. The Claude adapter stores a server's `env` with `claude mcp add -e` (before this change it only set it for the registering process).

Use:

1. Start the browser: `agent-chrome`. It runs Chrome with `--remote-debugging-port=9333` and its own profile at
   `~/.local/share/agent-chrome-profile`, and does nothing if port 9333 already answers. Each run appends its outcome (UTC time, run id, elapsed) to
   `~/.local/state/agent-chrome/agent-chrome.log`; Chrome's own output goes to `chrome.log` in the same directory.
2. Start or `/reload` Pi after an apply so it picks up the `browser-harness` server (`mcp__browser-harness__*` tools; check with `/mcp`).
3. Sign in to each site once. The login stays in the profile across Chrome restarts. Either you sign in by hand, or the
   agent does it with Pi's OS-level UI tools (`find_roots`, `observe_ui`, `act_ui`), for example clicking the
   1Password prompt in the Chrome window. Do not use the harness's own clicks (`browser_click`, CDP) for that: they
   cannot reach the 1Password menu (an extension iframe). Typed text and navigation through the harness are fine.
4. The 1Password extension has to be installed in that Chrome profile, by hand, on each machine.

Nothing about a login (cookie, password, token) is in this repository; it lives only in the profile directory on the machine.

Run `agent-chrome` before the agent's first browser call; the harness attaches to a running Chrome and does not start one.
The server is not wrapped by `pi-mcp-lazy` (idle it holds about 120 MB RSS). Add it to `servers.list.tmpl` and ship a seed if that matters.
Tests: `tests/agent-browser`, `tests/mise/test_install_google_chrome.py`.

## Add A Canonical Skill

Create a new directory under [`canonical/skills/`](./canonical/skills/) and place a `SKILL.md` file inside it.

Example:

```text
canonical/skills/my-skill/
  SKILL.md
  scripts/
  references/
```

Guidelines:

- Follow the open `SKILL.md` layout directly.
- Keep the skill harness-agnostic where possible.
- Only add extra files that the skill actually needs.
- If a skill comes from an existing library you own, copy the full bundle into `canonical/skills/` so the canonical tree is self-contained.

After adding a skill:

1. Follow [Apply and Verify](#apply-and-verify) to deploy the changed canonical source.
2. Follow [Sync Skills](#sync-skills) with `CHEZMOI_SOURCE_DIR` set to the current worktree; inspect orphan removals before applying.
3. Verify the symlinks exist:
   - `find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l`
   - `find ~/.codex/skills -mindepth 1 -maxdepth 1 -type l`
   - `find ~/.pi/agent/skills -mindepth 1 -maxdepth 1 -type l`

## Capability Tiers

[`capability-tiers/`](./capability-tiers/README.md) holds a standalone tier registry (low, medium, high) and a
read-only resolver that previews which model a role would get, using quota data. It is not canonical config for
any harness and is wired into none yet.

## Import Loop Engine Skills From A Release Tag

The six Loop Engine skill bundles (`using-loop-engine`, `coordinating-loop-engine`, `using-lean-change-provider`,
`using-research-provider`, `using-generate-prd`, `using-policy-document-provider`) come from a release tag of
`cartwmic/loop-engine`. `import_release_skills.py` (source:
[`dot_local/user_scripts/executable_import_release_skills.py`](../../user_scripts/executable_import_release_skills.py),
tests: `tests/release-skills`) imports them into `canonical/skills/` and checks the result. It needs an
authenticated `gh` and writes nothing without `--apply`.

```bash
REPO="$(git rev-parse --show-toplevel)"
TOOL="$REPO/dot_local/user_scripts/executable_import_release_skills.py"
python3 "$TOOL" import v0.33.0 --source "$REPO" --pins               # preview: per-bundle added/changed/orphan files
python3 "$TOOL" import v0.33.0 --source "$REPO" --pins --apply        # refuses (exit 3) while orphan files exist
python3 "$TOOL" import v0.33.0 --source "$REPO" --pins --apply --prune  # after you inspected the orphans
```

- **The tag.** It must be a published, non-prerelease release. The tool resolves it to one commit (printed; pass
  `--expect-commit SHA` to fail if the tag moved), reads every file from that commit's archive, and requires each
  file to match its git blob hash in the commit's tree. This repo's releases are not GitHub-immutable, so the commit
  is the thing to record.
- **The layout** is the one earlier imports used: `skills/<name>/**` or `crates/<crate>/skills/<name>/**` become the
  bundle; a crate's `README.md`, `docs/` and `data/` become `using-<crate>/references/`; `using-loop-engine` also takes
  four named `docs/` files (`ROOT_REFERENCES` in the script). Importing the current tag changes nothing.
- **Orphans** are files in a bundle that the tag no longer has. Other skills in `canonical/skills/` are never touched.
  Files chezmoi would read as attributes (`dot_`, `.tmpl`, a leading dot, and so on) or drop (empty files) stop the import.
- **`--pins`** moves the four `loop-engine`, `lean-change`, `policy-document` and `research` pins in
  `dot_config/mise/config.toml` to the tag's version. The `software-change` pin stays where it is: v0.30.0
  replaced that provider with lean-change, and runs started on it keep the installed version they name. `mise install` adds the new version and keeps the older ones, so
  runs frozen on an older tool version keep it. Do not `mise uninstall` them to tidy up.
- **Deploy** with the normal flow above: preview the targets, get approval, then
  `chezmoi --source "$REPO" apply ~/.local/share/agent-harness/canonical/skills ~/.config/mise/config.toml` (and
  `mise install` for the pins), then [Sync Skills](#sync-skills).
- **Verify** the result with `python3 ~/.local/user_scripts/import_release_skills.py verify-deployed --source "$REPO"`: the
  deployed bundles must equal the source byte for byte, and each of `~/.claude/skills`, `~/.codex/skills` and
  `~/.pi/agent/skills` must link to the deployed bundle. Files left in a deployed bundle that the source no longer has are
  reported as orphans; `chezmoi apply` does not delete them.

## Add Harness-Specific MCP Secrets

Keep secret-resolution details out of canonical MCP. Put a `${VAR}` placeholder
anywhere in the canonical server definition, including headers, URLs, command
arguments, or environment values. Map that placeholder to 1Password in each
harness adapter that needs it:

- [`adapters/claude/mcp-secrets.json.tmpl`](./adapters/claude/mcp-secrets.json.tmpl)
- [`adapters/codex/mcp-secrets.json.tmpl`](./adapters/codex/mcp-secrets.json.tmpl)
- [`adapters/pi/mcp-secrets.json.tmpl`](./adapters/pi/mcp-secrets.json.tmpl)

Canonical:
```json
{
  "mcpServers": {
    "my-http-server": {
      "type": "http",
      "url": "${MY_SERVER_URL}",
      "headers": {
        "Authorization": "Bearer ${MY_SERVER_API_KEY}"
      }
    }
  }
}
```

Adapter:
```json
{
  "substitutions": {
    "MY_SERVER_URL": {
      "op": "op://developer/my-http-server - url/credential"
    },
    "MY_SERVER_API_KEY": {
      "op": "op://developer/my-http-server - api key/credential"
    }
  }
}
```

The apply script:

1. Reads the canonical server definitions without changing their shape.
2. Reads each adapter's `substitutions`; for every placeholder-to-`op` mapping,
   it resolves the value and exports it for the render step.
3. Recursively substitutes `${VAR}` references anywhere in the resolved JSON.
   The value is **persisted as a literal string** in each harness config so
   harnesses do not need the variable at runtime.
4. If a managed placeholder cannot be resolved from 1Password or the existing
   environment, it omits only the affected server from that render.

Guidelines:

- Keep adapter mappings minimal (`placeholder` + `op`). Keep server shape and
  formatting such as `Bearer ${VAR}` in canonical.
- Use the same placeholder name in canonical and under `substitutions`.
- Gate work-only substitutions with the same chezmoi profile condition as the
  corresponding canonical servers.
- To disable inlining (keep `${VAR}` placeholders in harness configs), set
  `AGENT_HARNESS_INLINE_SECRETS=0` before running the apply script.

## Add A New Domain

A domain is a neutral configuration category such as `skills` or `mcp`.

To add one:

1. Create a new canonical source tree under `canonical/<domain>/`.
2. Extend [`executable_apply_harness_config.sh`](../../user_scripts/executable_apply_harness_config.sh) with:
   - canonical input discovery
   - per-harness projection logic
   - clear logging
3. Add adapter metadata under `adapters/<harness>/` only if needed.
4. Document the new domain in the top-level README and this file.
5. Follow [Apply and Verify](#apply-and-verify) for the changed source.
6. Verify the live harness outputs.

Guidelines:

- Domains should stay neutral and portable.
- Harness-only behavior belongs in the adapter layer.
- If a new domain starts requiring lots of harness-only semantics, revisit whether it should be canonical at all.

## Sync Skills

Use `sync_harness_skills.sh` to compare canonical skills in this worktree
with the deployed location. Its default source is the base chezmoi checkout,
so set `CHEZMOI_SOURCE_DIR` explicitly. chezmoi does the comparing and the
writing (`chezmoi status`, `diff` and `apply` on the skills path), so deployed
files get their target names and rendered contents: `executable_run.sh`
deploys as `run.sh`.

```bash
REPO="$(git rev-parse --show-toplevel)"
CHEZMOI_SOURCE_DIR="$REPO" ~/.local/user_scripts/sync_harness_skills.sh --dry-run
# After reviewing additions and updates with the owner:
CHEZMOI_SOURCE_DIR="$REPO" ~/.local/user_scripts/sync_harness_skills.sh
# Also delete what chezmoi does not manage there (inspect the list first):
CHEZMOI_SOURCE_DIR="$REPO" ~/.local/user_scripts/sync_harness_skills.sh --prune
```

The script also supports `--yes` for an owner-approved unattended run; it
skips the interactive confirmation.

The script detects:
- **Additions**: skills in chezmoi source not yet deployed
- **Updates**: skills whose rendered source differs from the deployed files
- **Not managed**: deployed skill directories no longer in source (orphans)
  and leftover files inside a managed skill (a renamed file, an old raw
  copy). chezmoi never deletes these. The preview always lists them; only
  `--prune` deletes them.

After syncing canonical skills it automatically runs `apply_harness_config.sh` to update symlinks and clean up stale links across all harnesses.

## Apply And Verify

Canonical changes go through the repo-root [AGENTS.md](../../../AGENTS.md)
apply boundary. Use the current worktree, inspect the dry-run and live targets,
and get owner approval before any real apply. A full apply also runs onchange
scripts; include their effects in that inspection. Use `--force` only after
choosing the source side of a known conflict.

```bash
REPO="$(git rev-parse --show-toplevel)"
chezmoi --source "$REPO" apply --dry-run --verbose
# After reviewing the exact effects and obtaining approval:
chezmoi --source "$REPO" apply
```

For a skill-only change, deploy the canonical source first, then run the
interactive `sync_harness_skills.sh` above with the same worktree source. For
MCP changes, verify each harness's result after apply; Pi writes
`~/.pi/agent/mcp.json` (check it parses privately with `jq empty
~/.pi/agent/mcp.json`). Do not paste rendered secret values into logs.

From the dotfiles source root, `python3 tests/native-mcp/proof.py` checks both
Pi settings profiles and completed native MCP/codemode journeys through the
real CLI, RPC, and TUI. It uses scripted local backends, not live providers or
user credentials.

Useful verification commands:

```bash
claude mcp list
codex mcp list
pi mcp list
find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l | sort
find ~/.codex/skills -mindepth 1 -maxdepth 1 -type l | sort
find ~/.pi/agent/skills -mindepth 1 -maxdepth 1 -type l | sort
```

## Current Canonical Policy

- Canonical MCP should reflect the shared cross-harness set you actually want active.
- Canonical skills should reflect your portable, user-managed skill library.
- Built-in harness skills and vendor-imported skills are not automatically part of the canonical set.
