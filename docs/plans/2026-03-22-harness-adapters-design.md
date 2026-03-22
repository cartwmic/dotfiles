# Harness Adapter Framework Design

## Summary

Build a harness-agnostic configuration adapter system in this `chezmoi` repo. The canonical sources remain the open standards themselves:

- `SKILL.md` skill directories for reusable skills
- MCP server definitions for tool/context integration

The repo should adapt those canonical sources into harness-specific configuration without introducing a second authoring format.

## Goals

- Keep canonical authoring manual and standards-based
- Support multiple harnesses from the same canonical sources
- Generalize the system to harness configuration as a whole, not just one-off Claude scripts
- Implement `skills` and `mcp` as the first supported configuration domains
- Keep harness adapters thin and operational

## Non-Goals

- Creating a new semantic manifest for skills or MCP
- Replacing harness-specific top-level instruction files such as `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`
- Normalizing every harness-specific feature into a shared abstraction
- Auto-generating canonical skills or canonical MCP definitions

## Core Model

The system is organized around three concepts:

### Canonical Sources

User-maintained open-standard inputs.

- Skills: directory trees containing `SKILL.md`
- MCP: canonical MCP server definitions stored in-repo

### Configuration Domains

Neutral categories of configuration that a harness may support.

Initial domains:

- `skills`
- `mcp`

Planned future domains could include:

- `instructions`
- `permissions`
- `hooks`
- `models`

### Harness Adapters

Thin projections from canonical sources into harness-native files and directories.

Each adapter is responsible for:

1. Discovering canonical inputs
2. Validating required files exist
3. Materializing harness-specific outputs by symlink, copy, or render
4. Reporting what changed

## Recommended Repository Layout

```text
canonical/
  skills/
    ...
  mcp/
    ...
adapters/
  claude/
    skills/
    mcp/
  codex/
    skills/
    mcp/
scripts/
  harness-config/
    ...
docs/plans/
  ...
```

The exact layout can be adjusted to fit `chezmoi` conventions, but the conceptual split should remain:

- canonical open-standard sources
- per-harness adapter logic
- shared execution entrypoints

## Adapter Behavior

### Skills

- If a harness supports filesystem `SKILL.md` discovery, the adapter should point the harness at canonical skill directories directly where possible.
- If a harness requires a fixed path, the adapter should create a symlink or copied projection into that path.
- The canonical skill tree remains unchanged.

### MCP

- Canonical MCP definitions remain the source of truth.
- Each harness adapter renders those definitions into the harness’s native config shape.
- Adapter-specific fields such as auto-approval or disabled state stay in the adapter layer unless the canonical MCP standard already represents them.
- Secret resolution is adapter-specific. Canonical MCP definitions stay standard-only, while per-harness adapter metadata may map env or header values to 1Password CLI references.
- If a secret lookup fails, the adapter should skip only the affected secret-backed configuration and continue applying the rest.

## Scope Boundaries

This system intentionally does not attempt to make all harness configuration identical.

- Claude hooks remain Claude-specific
- Codex permission settings remain Codex-specific
- Top-level instruction files remain hand-maintained unless later added as a separate configuration domain

The adapter framework should make it easy to add those domains later without changing how `skills` and `mcp` work.

## First Version

The first implementation should:

1. Introduce the adapter framework structure
2. Add a canonical location for skills
3. Add a canonical location for MCP definitions
4. Add Claude adapters for `skills` and `mcp`
5. Add Codex adapters for `skills` and `mcp`
6. Replace the current Claude-specific MCP bootstrap path with the new adapter flow

## Verification

The first version should verify:

- canonical skills are discovered and linked correctly
- canonical MCP definitions render to harness configs successfully
- generated config is valid JSON or TOML as appropriate
- adapter entrypoints are idempotent

## Open Follow-Up Items

- Whether Gemini or other harnesses should be added immediately after Claude and Codex
- Whether top-level instruction files should later become a first-class configuration domain
- Whether canonical MCP definitions should live as a single file or a directory of server definitions
