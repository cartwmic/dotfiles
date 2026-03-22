# Automation MCP via Furi Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `furi`-managed `ashwwwin/automation-mcp` to the repo's canonical harness configuration so Claude and Codex both inherit it automatically.

**Architecture:** Extend the existing bootstrap flow to install `furi` and register `ashwwwin/automation-mcp`, then add a canonical `furi connect` MCP entry that the current harness adapter script renders into Claude and Codex outputs.

**Tech Stack:** chezmoi, mise tasks, POSIX shell, JSON, Python 3

---

### Task 1: Add furi bootstrap support

**Files:**
- Modify: `dot_config/mise/config.toml`

**Step 1: Write the failing test**

Check that `furi` is not yet managed by bootstrap.

**Step 2: Run test to verify it fails**

Run: `rg -n 'furi' dot_config/mise/config.toml`
Expected: no bootstrap task for `furi`

**Step 3: Write minimal implementation**

Add a dedicated install task for `furi` and include it in the `bootstrap` task dependencies. The task should install `furi` only when absent, register `ashwwwin/automation-mcp` only when missing, and start it when not already running.

**Step 4: Run test to verify it passes**

Run: `rg -n 'install-furi|ashwwwin/automation-mcp' dot_config/mise/config.toml`
Expected: matching task definitions and bootstrap dependency

**Step 5: Commit**

```bash
git add dot_config/mise/config.toml
git commit -m "feat: bootstrap furi automation mcp"
```

### Task 2: Add canonical harness MCP configuration

**Files:**
- Modify: `/Users/cartwmic/.local/share/agent-harness/canonical/mcp/servers.json`

**Step 1: Write the failing test**

Check that canonical MCP config does not yet expose `furi`.

**Step 2: Run test to verify it fails**

Run: `jq -e '.mcpServers.furi' ~/.local/share/agent-harness/canonical/mcp/servers.json`
Expected: non-zero exit status

**Step 3: Write minimal implementation**

Add an MCP server entry named `furi` with command `furi` and args `["connect"]`.

**Step 4: Run test to verify it passes**

Run: `jq -e '.mcpServers.furi.command == "furi"' ~/.local/share/agent-harness/canonical/mcp/servers.json`
Expected: `true`

**Step 5: Commit**

```bash
git add ~/.local/share/agent-harness/canonical/mcp/servers.json
git commit -m "feat: expose furi through canonical harness mcp"
```

### Task 3: Document the new harness flow

**Files:**
- Modify: `README.md`

**Step 1: Write the failing test**

Check that the README does not mention `furi` or `automation-mcp`.

**Step 2: Run test to verify it fails**

Run: `rg -n 'furi|automation-mcp' README.md`
Expected: no matches

**Step 3: Write minimal implementation**

Document that the canonical MCP file is the source of truth, that `furi` is installed by bootstrap, and that `automation-mcp` is registered through the bootstrap task.

**Step 4: Run test to verify it passes**

Run: `rg -n 'furi|automation-mcp' README.md`
Expected: matching documentation lines

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe furi automation mcp harness setup"
```

### Task 4: Verify generated harness outputs

**Files:**
- Inspect: `~/.local/share/agent-harness/generated/claude/setup-mcp.sh`
- Inspect: `~/.local/share/agent-harness/generated/codex/mcp.toml`

**Step 1: Write the failing test**

Run the adapter before the canonical change and confirm generated outputs do not mention `furi`.

**Step 2: Run test to verify it fails**

Run: `~/.local/user_scripts/apply_harness_config.sh claude codex`
Expected: generated outputs still lack `furi`

**Step 3: Write minimal implementation**

Re-run the adapter after updating canonical MCP config.

**Step 4: Run test to verify it passes**

Run:

```bash
~/.local/user_scripts/apply_harness_config.sh claude codex
rg -n 'furi' ~/.local/share/agent-harness/generated/claude/setup-mcp.sh ~/.local/share/agent-harness/generated/codex/mcp.toml
```

Expected: both generated outputs contain the `furi` server

**Step 5: Commit**

```bash
git add docs/plans
git commit -m "docs: add automation mcp furi design and plan"
```
