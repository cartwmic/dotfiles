# Harness Adapter Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a general harness configuration adapter system that projects canonical open-standard `SKILL.md` skills and canonical MCP definitions into Claude and Codex harness-specific outputs.

**Architecture:** Keep canonical sources in-repo, add a small adapter script layer, and generate or symlink harness-native configuration from those sources. The first version supports two configuration domains, `skills` and `mcp`, with per-harness adapters for Claude and Codex.

**Tech Stack:** chezmoi templates, POSIX shell, `jq`, `python3`

---

### Task 1: Create the canonical source layout

**Files:**
- Create: `canonical/skills/.keep`
- Create: `canonical/mcp/servers.json`

**Step 1: Write the failing test**

Verify the canonical layout does not exist yet.

**Step 2: Run test to verify it fails**

Run: `test -f canonical/mcp/servers.json`
Expected: non-zero exit status

**Step 3: Write minimal implementation**

Create the `canonical/skills/` tree and add a canonical MCP JSON file with the current shared servers.

**Step 4: Run test to verify it passes**

Run: `test -f canonical/mcp/servers.json && test -d canonical/skills`
Expected: zero exit status

**Step 5: Commit**

```bash
git add canonical
git commit -m "feat: add canonical harness config sources"
```

### Task 2: Add a shared adapter entrypoint

**Files:**
- Create: `dot_local/user_scripts/executable_apply_harness_config.sh`

**Step 1: Write the failing test**

Invoke the script path before it exists.

**Step 2: Run test to verify it fails**

Run: `test -x dot_local/user_scripts/executable_apply_harness_config.sh`
Expected: non-zero exit status

**Step 3: Write minimal implementation**

Add an executable script that:

- accepts harness names or `all`
- discovers repo root
- dispatches domain adapters
- exits non-zero on unsupported harnesses

**Step 4: Run test to verify it passes**

Run: `test -x dot_local/user_scripts/executable_apply_harness_config.sh`
Expected: zero exit status

**Step 5: Commit**

```bash
git add dot_local/user_scripts/executable_apply_harness_config.sh
git commit -m "feat: add harness config entrypoint"
```

### Task 3: Implement the Claude skills adapter

**Files:**
- Modify: `dot_local/user_scripts/executable_apply_harness_config.sh`

**Step 1: Write the failing test**

Run the adapter for Claude skills before the logic exists and verify `~/.claude/skills` is not projected from the canonical tree.

**Step 2: Run test to verify it fails**

Run: `HOME="$(mktemp -d)" ./dot_local/user_scripts/executable_apply_harness_config.sh claude`
Expected: does not create the expected skills destination

**Step 3: Write minimal implementation**

Add Claude skills adapter logic that symlinks or copies canonical skills into `~/.claude/skills`.

**Step 4: Run test to verify it passes**

Run the same command and confirm the expected destination exists and points to the canonical tree.

**Step 5: Commit**

```bash
git add dot_local/user_scripts/executable_apply_harness_config.sh
git commit -m "feat: add claude skills adapter"
```

### Task 4: Implement the Claude MCP adapter

**Files:**
- Modify: `dot_local/user_scripts/executable_apply_harness_config.sh`
- Modify: `run_once_setup_claude_code_mcp.sh`

**Step 1: Write the failing test**

Run the Claude adapter in a temporary `HOME` and verify no MCP bootstrap output is produced from canonical definitions.

**Step 2: Run test to verify it fails**

Run: `HOME="$(mktemp -d)" ./dot_local/user_scripts/executable_apply_harness_config.sh claude`
Expected: no Claude MCP adapter output or config materialization

**Step 3: Write minimal implementation**

Add Claude MCP adapter logic that reads canonical MCP JSON and writes a Claude-native projection file or bootstrap artifact. Update the existing run-once script to delegate to the new adapter entrypoint.

**Step 4: Run test to verify it passes**

Run the adapter and confirm the expected Claude artifact exists and contains canonical servers.

**Step 5: Commit**

```bash
git add dot_local/user_scripts/executable_apply_harness_config.sh run_once_setup_claude_code_mcp.sh
git commit -m "feat: route claude mcp through harness adapter"
```

### Task 5: Implement the Codex skills and MCP adapters

**Files:**
- Modify: `dot_local/user_scripts/executable_apply_harness_config.sh`
- Modify: `dot_vibe/config.toml`

**Step 1: Write the failing test**

Run the Codex adapter in a temporary `HOME` and verify no skill path or MCP config is applied.

**Step 2: Run test to verify it fails**

Run: `HOME="$(mktemp -d)" ./dot_local/user_scripts/executable_apply_harness_config.sh codex`
Expected: no Codex-native configuration output

**Step 3: Write minimal implementation**

Add Codex adapter logic that:

- projects canonical skills into a stable shared location
- renders MCP definitions into Codex-native configuration
- updates repo-managed config templates as needed

**Step 4: Run test to verify it passes**

Run the adapter and confirm the expected Codex artifact exists and references canonical skills and MCP.

**Step 5: Commit**

```bash
git add dot_local/user_scripts/executable_apply_harness_config.sh dot_vibe/config.toml
git commit -m "feat: add codex skills and mcp adapters"
```

### Task 6: Verify idempotence and document usage

**Files:**
- Modify: `README.md`

**Step 1: Write the failing test**

Run the adapter twice and compare outputs before documentation exists.

**Step 2: Run test to verify it fails**

Run: the adapter twice in a temporary `HOME`
Expected: unclear or undocumented behavior

**Step 3: Write minimal implementation**

Document canonical source locations, supported harnesses, and usage commands in `README.md`.

**Step 4: Run test to verify it passes**

Run the adapter twice and verify the generated outputs are stable. Read the README section and confirm it matches the implemented paths.

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document harness adapter usage"
```
