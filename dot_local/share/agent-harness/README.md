# Agent Harness

This directory contains the canonical, harness-agnostic configuration sources and thin per-harness adapters used to project them into Claude, Codex, and future agent harnesses.

## Layout

```text
dot_local/share/agent-harness/
  canonical/
    mcp/
      servers.json.tmpl
    skills/
      ...
  adapters/
    claude/
      mcp-secrets.json.tmpl
    codex/
      mcp-secrets.json.tmpl
```

Rules:

- `canonical/` is the source of truth.
- Canonical sources should stay standards-based.
- `adapters/` may contain harness-specific metadata needed to project canonical sources into a given harness.
- Do not put harness-specific semantics into canonical files unless the open standard itself requires them.

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

Example `furi` bridge:

```json
{
  "mcpServers": {
    "furi": {
      "command": "furi",
      "args": ["connect"]
    }
  }
}
```

For `ashwwwin/automation-mcp`, this repo manages the bridge in `canonical/mcp/servers.json.tmpl` and installs, registers, and starts the backing package through `dot_config/mise/config.toml`.

On macOS, remember to grant Accessibility and Screen Recording permissions in System Settings > Privacy & Security for the process path running `automation-mcp`, or the server will start but desktop automation will be limited.

After editing the canonical MCP file:

1. If the server needs secrets, add or update adapter metadata in `adapters/<harness>/mcp-secrets.json.tmpl`.
2. Apply with `chezmoi apply --force`.
3. Verify the harness-specific result:
   - Claude: `claude mcp list`
   - Codex: `codex mcp list`

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

1. Run `~/.local/user_scripts/sync_harness_skills.sh` to preview and apply.
2. Or apply with `chezmoi apply --force` (no preview).
3. Verify the symlinks exist:
   - `find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l`
   - `find ~/.codex/skills -mindepth 1 -maxdepth 1 -type l`
   - `find ~/.pi/agent/skills -mindepth 1 -maxdepth 1 -type l`

## Add Harness-Specific MCP Secrets

Keep secret-resolution details out of canonical MCP.

Instead, add them in:

- [`adapters/claude/mcp-secrets.json.tmpl`](./adapters/claude/mcp-secrets.json.tmpl)
- [`adapters/codex/mcp-secrets.json.tmpl`](./adapters/codex/mcp-secrets.json.tmpl)

Shape:

```json
{
  "mcpServers": {
    "context7": {
      "headers": {
        "CONTEXT7_API_KEY": {
          "env": "CONTEXT7_API_KEY",
          "op": "op://developer/context7 - api key/credential"
        }
      }
    }
  }
}
```

Headers that need a prefix (e.g. `Authorization: Bearer <token>`) belong in
the canonical file with a `${VAR}` placeholder; the adapter only declares
the env-to-`op://` mapping:

Canonical:
```json
{
  "mcpServers": {
    "mcp-memory": {
      "type": "http",
      "url": "https://mcp-memory.internal.cartwmic.com/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_MEMORY_API_KEY}"
      }
    }
  }
}
```

Adapter:
```json
{
  "mcpServers": {
    "mcp-memory": {
      "headers": {
        "Authorization": {
          "env": "MCP_MEMORY_API_KEY",
          "op": "op://developer/mcp-memory - api key/credential"
        }
      }
    }
  }
}
```

The apply script:

1. Reads canonical, preserving any value the canonical declares for a header.
2. Reads each adapter's secrets file; for every `{env, op}` pair it `op read`s
   the secret and exports it into the apply step's environment.
3. Substitutes every `${VAR}` reference in the resolved JSON with the actual
   exported value, so the credential is **persisted as a literal string**
   into each harness's MCP config on disk. This is intentional: harnesses
   don't need the env var set at runtime.

Advanced: `format` field. If you ever need the adapter to *override* the
canonical value (rare — prefer fixing the canonical), pass an explicit
`format` string and it will be used verbatim before env substitution.

Guidelines:

- Keep adapter mappings minimal (`env` + `op`). Put header shape in canonical.
- Match the server name and env/header keys used by the harness projection.
- If secret resolution fails during apply, the adapter should skip only the affected server configuration.
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
5. Apply with `chezmoi apply --force`.
6. Verify the live harness outputs.

Guidelines:

- Domains should stay neutral and portable.
- Harness-only behavior belongs in the adapter layer.
- If a new domain starts requiring lots of harness-only semantics, revisit whether it should be canonical at all.

## Sync Skills

Use `sync_harness_skills.sh` to interactively sync canonical skills from chezmoi source to the deployed location. It compares the two directories and shows a color-coded diff before making changes.

```bash
# Preview what would change
~/.local/user_scripts/sync_harness_skills.sh --dry-run

# Interactive — shows diff, prompts before applying
~/.local/user_scripts/sync_harness_skills.sh

# Non-interactive — shows diff, applies immediately
~/.local/user_scripts/sync_harness_skills.sh --yes
```

The script detects:
- **Additions**: skills in chezmoi source not yet deployed
- **Removals**: deployed skills no longer in chezmoi source (orphans)
- **Updates**: skills present in both but with content differences

After syncing canonical skills it automatically runs `apply_harness_config.sh` to update symlinks and clean up stale links across all harnesses.

## Apply And Verify

Canonical changes are meant to be applied through chezmoi, not by manually copying files around.

Apply:

```bash
# Full chezmoi apply (skills + MCP + everything else)
chezmoi apply --force

# Or sync just skills interactively
~/.local/user_scripts/sync_harness_skills.sh
```

Useful verification commands:

```bash
claude mcp list
codex mcp list
find ~/.claude/skills -mindepth 1 -maxdepth 1 -type l | sort
find ~/.codex/skills -mindepth 1 -maxdepth 1 -type l | sort
find ~/.pi/agent/skills -mindepth 1 -maxdepth 1 -type l | sort
```

## Current Canonical Policy

- Canonical MCP should reflect the shared cross-harness set you actually want active.
- Canonical skills should reflect your portable, user-managed skill library.
- Built-in harness skills and vendor-imported skills are not automatically part of the canonical set.
