---
name: forking-for-custom-patches
description: Use when needing to make custom edits to an open source dependency, library, framework, extension, or plugin - handles forking, branch setup, upstream sync workflow, and push. Also suggest when editing installed open source code or vendored dependencies.
---

# Forking for Custom Patches

## Overview

Systematically fork, patch, and maintain custom changes to open source dependencies with automatic upstream sync.

**Core principle:** Custom branch as default + automated upstream sync = maintainable fork that stays current.

**Announce at start:** "I'm using the forking-for-custom-patches skill to set up a maintainable fork."

## When to Use

- Editing source of an installed dependency (e.g. plugin, extension, library)
- Vendoring a fix that hasn't been merged upstream
- Needing a feature branch on someone else's repo
- Patching a tool installed via package manager, mise, or plugin system

**When NOT to use:**
- Contributing upstream directly (just open a PR on the original)
- Temporary debugging (use local edits, don't fork)
- The project is already your fork

## Prerequisites

```bash
# Verify required tools
command -v gh || echo "STOP: Install gh CLI first"
command -v git || echo "STOP: Install git first"
gh auth status || echo "STOP: Run gh auth login first"
```

## The Process

### Step 1: Identify the Upstream Repository

Determine the full `owner/repo` of the dependency to fork.

```bash
# If you're already in a clone:
UPSTREAM=$(git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')

# Or from a known package - ask user to confirm:
# "The upstream repo appears to be <owner/repo>. Is that correct?"
```

**Always confirm with the user before forking.**

### Step 2: Fork with gh CLI

```bash
# Fork to user's GitHub account
gh repo fork "$UPSTREAM" --clone=false

# Determine fork name
FORK_OWNER=$(gh api user --jq '.login')
FORK_REPO="$FORK_OWNER/$(basename "$UPSTREAM")"
```

If already forked, `gh repo fork` will report the existing fork. Continue with it.

### Step 3: Clone the Fork (if not already cloned)

```bash
gh repo clone "$FORK_REPO"
cd "$(basename "$UPSTREAM")"

# Verify upstream remote exists
git remote -v | grep upstream || git remote add upstream "https://github.com/$UPSTREAM.git"
```

### Step 4: Create Custom Branch

```bash
# Always use cartwmic/main as the custom branch name
CUSTOM_BRANCH="cartwmic/main"

git checkout -b "$CUSTOM_BRANCH"
```

### Step 5: Make the Custom Changes

Apply the needed edits. Commit with a clear message:

```bash
git add -A
git commit -m "custom: <description of patch>

Upstream: $UPSTREAM
Reason: <why this patch is needed>
"
```

### Step 6: Push and Set Custom Branch as Default

```bash
# Push the custom branch
git push -u origin "$CUSTOM_BRANCH"

# Set as default branch on GitHub
gh repo edit "$FORK_REPO" --default-branch "$CUSTOM_BRANCH"
```

**Why set as default:** Ensures clones/installs from your fork get the patched version by default, not the unmodified main.

### Step 7: Add Upstream Sync Workflow

Create `.github/workflows/sync-upstream.yml`:

```yaml
name: Sync upstream
on:
  schedule:
    - cron: '0 6 * * 1'  # Weekly on Monday at 06:00 UTC
  workflow_dispatch: {}    # Allow manual trigger

permissions:
  contents: write

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout main
        uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0

      - name: Pull upstream main
        run: |
          git remote add upstream https://github.com/${{ env.UPSTREAM }}.git || true
          git fetch upstream
          git merge upstream/main --no-edit
          git push origin main
        env:
          UPSTREAM: UPSTREAM_PLACEHOLDER
```

```bash
# Replace placeholder with actual upstream
sed -i'' -e "s|UPSTREAM_PLACEHOLDER|$UPSTREAM|" .github/workflows/sync-upstream.yml

git add .github/workflows/sync-upstream.yml
git commit -m "ci: add weekly upstream sync workflow"
git push
```

**After sync runs:** The `main` branch stays current with upstream. Your `cartwmic/main` branch diverges only by your patches. To manually rebase onto updated main:

```bash
git fetch origin main
git checkout cartwmic/main
git rebase origin/main
git push --force-with-lease
```

### Step 8: Report Summary

```
Fork ready:
  Fork:     https://github.com/<FORK_REPO>
  Branch:   cartwmic/main (set as default)
  Upstream: https://github.com/<UPSTREAM>
  Sync:     Weekly via GitHub Actions (main ← upstream)
```

## Quick Reference

| Step | Command | Purpose |
|------|---------|---------|
| Fork | `gh repo fork OWNER/REPO` | Create fork on GitHub |
| Branch | `git checkout -b cartwmic/main` | Isolate custom changes |
| Default | `gh repo edit --default-branch cartwmic/main` | Installs use patched version |
| Sync workflow | `.github/workflows/sync-upstream.yml` | Keep main current |
| Push | `git push -u origin cartwmic/main` | Publish changes |
| Rebase | `git rebase origin/main` | Manual sync of custom branch |

## Common Mistakes

**Forgetting to set default branch**
- Problem: Consumers clone/install main (unpatched)
- Fix: Always `gh repo edit --default-branch cartwmic/main` after push

**No upstream sync**
- Problem: Fork drifts, patches conflict later
- Fix: Always add sync workflow in Step 7

**Vague commit messages**
- Problem: Can't tell custom patches from upstream
- Fix: Prefix with `custom:`, include upstream URL and reason

**Forking without confirming**
- Problem: Fork wrong repo, or fork when unnecessary
- Fix: Always confirm upstream repo with user before forking

## Red Flags

**Never:**
- Fork without confirming the upstream repo with the user
- Leave main as default branch on a patched fork
- Skip the sync workflow
- Make custom edits directly on main

**Always:**
- Use `cartwmic/main` as the custom branch name
- Set `cartwmic/main` as default branch
- Add upstream sync workflow
- Include upstream URL and reason in commit messages
