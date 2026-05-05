---
name: sync-custom-forks
description: Use when syncing forked repositories with upstream, merging upstream changes into forks, or when user says to update or sync forks
---

# Sync Custom Forks

## Overview

Interactively sync forked GitHub repos with their upstream by merging upstream changes into the fork's default branch. Uses `gh` CLI to discover all forks automatically.

**Announce at start:** "I'm using the sync-custom-forks skill to sync your forks with upstream."

## Prerequisites

```bash
command -v gh || echo "STOP: Install gh CLI first"
command -v git || echo "STOP: Install git first"
gh auth status || echo "STOP: Run gh auth login first"
```

## The Process

### Step 1: Discover Forks

```bash
gh repo list "$(gh api user --jq '.login')" --fork --no-archived --json name,parent,defaultBranchRef,url --limit 100
```

Note: `--no-archived` excludes archived forks. Archive forks you no longer want to sync to keep the list clean.

This returns all forks with:
- `name` — repo name
- `parent.owner.login` / `parent.name` — upstream owner/repo
- `defaultBranchRef.name` — the default branch (where custom patches live)
- `url` — fork URL

### Step 2: Present Fork List to User

Display a numbered list of all discovered forks:

```
Found N forked repositories:

  1. pi-mcp-adapter (upstream: nicobailon/pi-mcp-adapter) — branch: main
  2. pi-rtk-optimizer (upstream: example/pi-rtk-optimizer) — branch: main

Which forks would you like to sync? (e.g. "all", "1,3", or "none")
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

If a repo exists in multiple locations, prefer `~/git/<name>` as the canonical clone. Note the pi extension location if it exists — it may need updating after sync (see Step 7).

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

### Step 5: Fetch and Determine Branch

```bash
git fetch upstream

# Determine upstream default branch (usually main or master)
UPSTREAM_DEFAULT=$(git remote show upstream | sed -n 's/.*HEAD branch: //p')

# The fork's default branch should match upstream's default
DEFAULT_BRANCH="<defaultBranchRef.name>"
```

### Step 6: Review and Merge Upstream

A clean merge is not the goal — a *coherent* fork is. Even when upstream merges without conflict, the result may duplicate effort, fight a custom patch, or quietly invalidate one. Always review the divergence before merging.

```bash
# Make sure we're on the default branch and clean
git checkout "$DEFAULT_BRANCH"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "WARNING: Uncommitted changes in $REPO_NAME. Stash or commit first."
  # Ask user how to proceed
fi
```

#### 6a. Inventory what's changing

Before merging, build a picture of both sides of the divergence:

```bash
MERGE_BASE=$(git merge-base HEAD "upstream/$UPSTREAM_DEFAULT")

# Our custom commits (on the fork, not in upstream)
git log --oneline "$MERGE_BASE..HEAD"

# Incoming upstream commits (in upstream, not yet on fork)
git log --oneline "$MERGE_BASE..upstream/$UPSTREAM_DEFAULT"

# Files our custom patches touch
git diff --name-only "$MERGE_BASE..HEAD" | sort -u > /tmp/ours.txt

# Files upstream is changing
git diff --name-only "$MERGE_BASE..upstream/$UPSTREAM_DEFAULT" | sort -u > /tmp/theirs.txt

# Overlap — areas where upstream and our patches both made changes
comm -12 /tmp/ours.txt /tmp/theirs.txt
```

#### 6b. Review for compatibility, redundancy, and intent drift

Present to the user **before** merging:

```
Fork has N custom commits; upstream has M new commits since last sync.
Files touched by both: <list>

Custom commits on this fork:
  <oneline list>

Incoming upstream commits:
  <oneline list>

Overlapping files (review carefully):
  <file>: ours touches X, theirs touches Y
```

Specifically look for:

- **Redundant fixes** — upstream has fixed something our patch also fixed (differently). Our patch may now be obsolete, or worse, may fight upstream's fix.
- **Reimplemented features** — upstream adopted the same feature our patch adds, but with a different API/approach. Prefer dropping our patch in favor of upstream.
- **Refactors that invalidate our patch** — upstream renamed/restructured the code our patch depends on. Patch needs to be ported, not just merged.
- **Behavioral conflicts at a distance** — non-overlapping files but coupled behavior (e.g. upstream changes a config schema our patch reads).
- **License / dependency / lockfile churn** — usually safe to take upstream as-is.

For each overlapping file, show both histories so the user can compare:

```bash
git log --oneline -p "$MERGE_BASE..HEAD" -- <file>
git log --oneline -p "$MERGE_BASE..upstream/$UPSTREAM_DEFAULT" -- <file>
```

#### 6c. Choose a merge strategy

Based on the review, present options:

```
Options:
  a) Plain merge — our patches stay, upstream gets pulled in (conflicts resolved manually)
  b) Drop a custom patch — upstream now does it natively; revert/skip our commit
  c) Rewrite a custom patch — upstream refactor invalidates ours; port it on top
  d) Abort and investigate — too risky to sync today
```

Do **not** auto-pick a strategy. Even when there's no overlap, confirm the user wants to proceed before merging.

#### 6d. Execute the merge

```bash
git merge "upstream/$UPSTREAM_DEFAULT" --no-edit
```

##### If Merge Succeeds (No Conflicts)

```
✅ <name>: Merged upstream/<upstream_default> into <default_branch> successfully.
```

Note: a clean merge is not proof of correctness — if 6b flagged concerns, still verify (build/test/inspect) before pushing.

##### If Merge Has Conflicts

**STOP and present conflicts to the user:**

```bash
# Show which files conflict
git diff --name-only --diff-filter=U

# For each conflicting file, show the conflict
git diff --diff-filter=U
```

Present to user:

```
⚠️  <name>: Merge conflicts detected.

Conflicting files:
  1. src/adapter.ts
  2. package.json

Options:
  a) Show conflict details for a specific file
  b) Open in editor to resolve manually
  c) Abort merge (git merge --abort) and skip this repo
  d) Accept upstream version for all conflicts (git checkout --theirs .)
  e) Keep custom version for all conflicts (git checkout --ours .)
```

**For option (a):** Show conflicting hunks with context. Offer to resolve intelligently:
- Conflicts in version numbers / lockfiles → suggest accepting upstream
- Conflicts in custom patch area → show both versions, ask user

After resolution:
```bash
git add -A
git commit --no-edit
```

### Step 7: Push and Post-Sync Actions

```bash
git push origin "$DEFAULT_BRANCH"
```

**If the repo also exists as a pi extension** (`~/.pi/agent/git/github.com/cartwmic/<name>`):
```
Note: This repo is also installed as a pi extension at:
  ~/.pi/agent/git/github.com/cartwmic/<name>

You may want to update it:
  cd ~/.pi/agent/git/github.com/cartwmic/<name> && git pull origin <default_branch>

Or reinstall:
  pi install git:github.com/cartwmic/<name>
```

**If the repo is installed via npm**:
```
Note: This repo is installed globally via npm.
You may want to reinstall:
  npm install -g github:cartwmic/<name>
```

### Step 8: Report Summary

After processing all selected forks:

```
Sync Summary:
  ✅ pi-mcp-adapter: Merged upstream/main — pushed
  ✅ pi-rtk-optimizer: Merged upstream/main — pushed
  ⏭️  other-repo: Skipped by user

Post-sync actions needed:
  - [ ] Update pi extension: cd ~/.pi/agent/git/... && git pull
```

## Quick Reference

| Step | Command | Purpose |
|------|---------|---------|
| Discover | `gh repo list --fork --json ...` | Find all forks |
| Fetch | `git fetch upstream` | Get latest upstream |
| Merge | `git merge upstream/main --no-edit` | Pull in upstream changes |
| Conflicts | `git diff --diff-filter=U` | Show conflict details |
| Abort | `git merge --abort` | Cancel merge |
| Push | `git push origin main` | Update remote |

## Common Mistakes

**Not fetching upstream first**
- Problem: Merge against stale upstream
- Fix: Always `git fetch upstream` before merging

**Forgetting to update secondary install locations**
- Problem: pi extension or npm global still on old version
- Fix: Always check for secondary locations and remind user

**Merging with uncommitted changes**
- Problem: Merge fails or loses work
- Fix: Check for clean working tree before starting

## Red Flags

**Never:**
- Sync without user selecting which forks to process
- Auto-resolve conflicts without showing them to user
- Skip repos silently on error — always report status

**Always:**
- Present the full fork list and let user choose
- Show conflict details before asking for resolution strategy
- Report a summary with status for every selected fork
- Note secondary install locations that may need updating
