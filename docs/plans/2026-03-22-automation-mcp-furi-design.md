# Automation MCP via Furi Design

## Summary

Add `ashwwwin/automation-mcp` to the existing harness adapter flow in this repo by standardizing on `furi`.

The repo should manage three layers:

- install `furi` as part of the normal bootstrap path
- register and start `ashwwwin/automation-mcp` with `furi` during bootstrap
- expose a canonical `furi` MCP server in the shared harness MCP config so Claude and Codex both inherit it

This follows the harness adapter model documented in `README.md` instead of editing Claude or Codex configuration directly.

## Goals

- Keep Claude and Codex MCP configuration sourced from the canonical harness MCP file
- Ensure fresh-machine bootstrap leaves `furi` and `automation-mcp` available
- Reuse the existing adapter pipeline that renders MCP config for each harness
- Keep the repo responsible for installation and projection, not for the internal implementation of `automation-mcp`

## Non-Goals

- Running `automation-mcp` directly with Bun from this repo
- Creating a separate Claude-only or Codex-only MCP setup path
- Managing `automation-mcp` source checkout inside this dotfiles repo

## Chosen Approach

Use `furi` as the single MCP bridge.

- `mise` bootstrap installs the `furi` CLI
- bootstrap runs `furi add ashwwwin/automation-mcp` if it has not already been registered
- the canonical harness MCP file adds a `furi` server with `command: "furi"` and `args: ["connect"]`
- existing harness adapters render that server into Claude and Codex

## Alternatives Considered

### Direct Bun Server

Run `automation-mcp` with `bun run ... --stdio` from a local checkout.

Rejected because it requires managing a stable checkout path and Bun runtime assumptions in the harness config, which is less aligned with this repo's adapter architecture.

### Local-Only User Setup

Install `furi` and register `automation-mcp`, but do not add it to canonical harness config.

Rejected because it would make the setup machine-specific and bypass the repo's source-of-truth model for shared MCP configuration.

## Behavior

After `chezmoi apply` and bootstrap:

- `furi` should be installed
- `ashwwwin/automation-mcp` should be registered with `furi`
- `ashwwwin/automation-mcp` should be running under `furi`
- the generated Claude MCP setup script should include a `furi` MCP server
- the managed Codex MCP block should include a `furi` MCP server

Runtime permissions for macOS remain the responsibility of `automation-mcp` itself, including Accessibility and Screen Recording prompts.

## Verification

- confirm `mise` config includes the `furi` install task in bootstrap
- confirm bootstrap logic runs `furi add ashwwwin/automation-mcp`
- confirm the canonical MCP file includes `furi`
- run the harness adapter and inspect generated Claude and Codex outputs for `furi`
