---
name: rebase-custom-forks
description: Use when syncing forked repositories with upstream, rebasing custom patches onto upstream main, or when user says to update or rebase forks
---

# Rebase Custom Forks

## Overview

Interactively sync forked GitHub repos with their upstream, rebasing custom patch branches onto the latest upstream main. Uses `gh` CLI to discover all forks automatically.

**Announce at start:** "I'm using the rebase-custom-forks skill to sync your forks with upstream."

## Prerequisites

```bash
command -v gh || echo "STOP: Install gh CLI first"
command -v git || echo "STOP: Install git first"
gh auth status || echo "STOP: Run gh auth login first"
```

## The Process

### Step 1: Discover Forks

```bash
gh repo list "$(gh api user --jq '.login')" --fork --json name,parent,defaultBranchRef,url --limit 100
```

This returns all forks with:
- `name` — repo name
- `parent.owner.login` / `parent.name` — upstream owner/repo
- `defaultBranchRef.name` — the custom patches branch (set as default by forking-for-custom-patches skill)
- `url` — fork URL

### Step 2: Present Fork List to User

Display a numbered list of all discovered forks:

```
Found N forked repositories:

  1. meridian (upstream: rynfar/meridian) — branch: pi-patches
  2. pi-mcp-adapter (upstream: nicobailon/pi-mcp-adapter) — branch: cartwmic/main
  3. pi-meridian-extension (upstream: lnilluv/pi-meridian-extension) — branch: pi-patches

Which forks would you like to rebase? (e.g. "all", "1,3", or "none")
```

**Wait for user selection before proceeding.** Do not process any forks without explicit confirmation.

### Step 3: Find Local Clone

For each selected fork, find the local clone. Search in order:

1. `~/git/<name>` (primary dev clones)
2. `~/.pi/agent/git/github.com/cartwmic/<name>` (pi extension installs)
3. Ask user for path if not found

```bash
REPO_NAME="<name>"
if [ -d "$HOME/git/$REPO_NAME/.git" ]; then
  LOCAL_PATH="$HOME/git/$REPO_NAME"
elif [ -d "$HOME/.pi/agent/git/github.com/cartwmic/$REPO_NAME/.git" ]; then
  LOCAL_PATH="$HOME/.pi/agent/git/github.com/cartwmic/$REPO_NAME"
else
  echo "Could not find local clone for $REPO_NAME. Please provide the path."
fi
```

If a repo exists in multiple locations, prefer `~/git/<name>` as the canonical clone to rebase. Note the pi extension location if it exists — it may need updating after rebase (see Step 7).

### Step 4: Ensure Upstream Remote

```bash
cd "$LOCAL_PATH"

# Check for existing upstream remote
UPSTREAM_URL=$(git remote get-url upstream 2>/dev/null)
EXPECTED_UPSTREAM="https://github.com/<parent_owner>/<parent_name>.git"

if [ -z "$UPSTREAM_URL" ]; then
  git remote add upstream "$EXPECTED_UPSTREAM"
elif [ "$UPSTREAM_URL" != "$EXPECTED_UPSTREAM" ]; then
  echo "WARNING: upstream remote points to $UPSTREAM_URL (expected $EXPECTED_UPSTREAM)"
  # Ask user before changing
fi
```

### Step 5: Fetch Upstream and Determine Branch

```bash
git fetch upstream

# Determine upstream default branch (usually main or master)
UPSTREAM_DEFAULT=$(git remote show upstream | sed -n 's/.*HEAD branch: //p')

# The custom branch is the fork's default branch from Step 1
CUSTOM_BRANCH="<defaultBranchRef.name>"
```

### Step 6: Attempt Rebase

```bash
# Make sure we're on the custom branch
git checkout "$CUSTOM_BRANCH"

# Check if there are uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "WARNING: Uncommitted changes in $REPO_NAME. Stash or commit first."
  # Ask user how to proceed
fi

# Attempt the rebase
git rebase "upstream/$UPSTREAM_DEFAULT"
```

#### If Rebase Succeeds (No Conflicts)

Report success and move to push:

```
✅ <name>: Rebased <custom_branch> onto upstream/<upstream_default> successfully.
   X commits replayed, no conflicts.
```

#### If Rebase Has Conflicts

**STOP and present conflicts to the user:**

```bash
# Show which files conflict
git diff --name-only --diff-filter=U

# For each conflicting file, show the conflict
git diff --diff-filter=U
```

Present to user:

```
⚠️  <name>: Rebase conflicts detected.

Conflicting files:
  1. src/adapter.ts
  2. package.json

Options:
  a) Show conflict details for a specific file
  b) Open in editor to resolve manually
  c) Abort rebase (git rebase --abort) and skip this repo
  d) Accept upstream version for all conflicts (git checkout --theirs .)
  e) Keep custom version for all conflicts (git checkout --ours .)
```

**For option (a):** Show the conflicting hunks with surrounding context so the user can decide. Offer to resolve intelligently:
- If conflict is in version numbers / lockfiles → suggest accepting upstream
- If conflict is in the custom patch area → show both versions, ask user which to keep or how to merge

After resolution:
```bash
git add -A
git rebase --continue
```

Repeat until rebase completes or user aborts.

### Step 7: Push and Post-Rebase Actions

```bash
# Force push the rebased branch (required after rebase)
git push --force-with-lease origin "$CUSTOM_BRANCH"
```

**If the repo also exists as a pi extension** (`~/.pi/agent/git/github.com/cartwmic/<name>`):
```
Note: This repo is also installed as a pi extension at:
  ~/.pi/agent/git/github.com/cartwmic/<name>

You may want to update it:
  cd ~/.pi/agent/git/github.com/cartwmic/<name> && git pull --rebase origin <custom_branch>

Or reinstall:
  pi install git:github.com/cartwmic/<name>#<custom_branch>
```

**If the repo is installed via npm** (e.g. meridian):
```
Note: This repo is installed globally via npm.
You may want to reinstall:
  npm install -g github:cartwmic/<name>#<custom_branch>
```

### Step 8: Report Summary

After processing all selected forks:

```
Rebase Summary:
  ✅ meridian: Rebased pi-patches onto upstream/main — pushed
  ✅ pi-mcp-adapter: Rebased cartwmic/main onto upstream/main — pushed
  ⚠️  pi-meridian-extension: Conflicts resolved manually — pushed
  ⏭️  other-repo: Skipped by user

Post-rebase actions needed:
  - [ ] Reinstall meridian: npm install -g github:cartwmic/meridian#pi-patches
  - [ ] Update pi extension: pi install git:github.com/cartwmic/pi-meridian-extension#pi-patches
```

## Quick Reference

| Step | Command | Purpose |
|------|---------|---------|
| Discover | `gh repo list --fork --json ...` | Find all forks |
| Fetch | `git fetch upstream` | Get latest upstream |
| Rebase | `git rebase upstream/main` | Replay patches |
| Conflicts | `git diff --diff-filter=U` | Show conflict details |
| Abort | `git rebase --abort` | Cancel rebase |
| Continue | `git add -A && git rebase --continue` | After resolving |
| Push | `git push --force-with-lease` | Update remote |

## Common Mistakes

**Not fetching upstream first**
- Problem: Rebase against stale upstream
- Fix: Always `git fetch upstream` before rebasing

**Using `--force` instead of `--force-with-lease`**
- Problem: Can overwrite collaborator commits
- Fix: Always use `--force-with-lease`

**Forgetting to update secondary install locations**
- Problem: pi extension or npm global still on old version
- Fix: Always check for secondary locations and remind user

**Rebasing with uncommitted changes**
- Problem: Rebase fails or loses work
- Fix: Check for clean working tree before starting

## Red Flags

**Never:**
- Rebase without user selecting which forks to process
- Force push without `--force-with-lease`
- Auto-resolve conflicts without showing them to user
- Skip repos silently on error — always report status

**Always:**
- Present the full fork list and let user choose
- Show conflict details before asking for resolution strategy
- Report a summary with status for every selected fork
- Note secondary install locations that may need updating
