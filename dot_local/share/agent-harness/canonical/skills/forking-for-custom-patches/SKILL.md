---
name: forking-for-custom-patches
description: Use when needing to make custom edits to an open source dependency, library, framework, extension, or plugin - handles forking, patching, and push. Also suggest when editing installed open source code or vendored dependencies.
---

# Forking for Custom Patches

## Overview

Systematically fork, patch, and maintain custom changes to open source dependencies.

**Core principle:** Custom commits go directly on the fork's default branch (`main` or `master`). Sync with upstream via `git fetch upstream && git merge` or GitHub's built-in "Sync fork" button.

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

### Step 3: Clone the Fork (if not already in ~/git/)

```bash
gh repo clone "$FORK_REPO" "$HOME/git/$(basename "$UPSTREAM")"
cd "$HOME/git/$(basename "$UPSTREAM")"

# Verify upstream remote exists
git remote -v | grep upstream || git remote add upstream "https://github.com/$UPSTREAM.git"

# Determine upstream's default branch
UPSTREAM_DEFAULT=$(git remote show upstream | sed -n 's/.*HEAD branch: //p')
```

### Step 4: Make the Custom Changes

Work directly on the fork's default branch (usually `main` or `master` — matching upstream's default branch).

```bash
git checkout "$UPSTREAM_DEFAULT"
```

Apply the needed edits. Commit with a clear message:

```bash
git add -A
git commit -m "custom: <description of patch>

Upstream: $UPSTREAM
Reason: <why this patch is needed>
"
```

### Step 5: Push

```bash
git push origin "$UPSTREAM_DEFAULT"
```

### Step 6: Report Summary

```
Fork ready:
  Fork:     https://github.com/<FORK_REPO>
  Branch:   <default_branch> (commits on top of upstream)
  Upstream: https://github.com/<UPSTREAM>
  Sync:     git fetch upstream && git merge upstream/<default_branch>
            Or use GitHub's "Sync fork" button (web UI)
```

## Syncing with Upstream

No automated workflow needed. Use any of these approaches when you want upstream changes:

```bash
# CLI: fetch and merge upstream
git fetch upstream
git merge upstream/main --no-edit
git push

# Or use gh CLI
gh repo sync owner/repo
```

Or use GitHub's built-in **"Sync fork"** button in the web UI.

**If merge conflicts occur:** Resolve them manually — your custom patches are on top, so conflicts show exactly where upstream diverged from your edits.

## Quick Reference

| Step | Command | Purpose |
|------|---------|---------|
| Fork | `gh repo fork OWNER/REPO` | Create fork on GitHub |
| Clone | `gh repo clone FORK ~/git/REPO` | Clone to ~/git/ |
| Upstream | `git remote add upstream URL` | Track upstream |
| Edit | Work on default branch | Apply custom patches |
| Push | `git push origin main` | Publish changes |
| Sync | `git fetch upstream && git merge upstream/main` | Pull upstream changes |

## Common Mistakes

**No upstream remote configured**
- Problem: Can't sync with upstream later
- Fix: Always `git remote add upstream` after cloning

**Vague commit messages**
- Problem: Can't tell custom patches from upstream
- Fix: Prefix with `custom:`, include upstream URL and reason

**Forking without confirming**
- Problem: Fork wrong repo, or fork when unnecessary
- Fix: Always confirm upstream repo with user before forking

**Creating separate branches or sync workflows**
- Problem: Over-engineering — adds complexity without benefit
- Fix: Work directly on the default branch, sync manually when needed

## Red Flags

**Never:**
- Fork without confirming the upstream repo with the user
- Create a separate custom branch and set it as default (over-engineered)
- Add automated sync workflows (unnecessary — use GitHub's built-in sync)
- Forget to set up the upstream remote

**Always:**
- Work directly on the fork's default branch (`main` or `master`)
- Prefix custom commits with `custom:` and include upstream URL
- Keep the upstream remote configured for manual syncing
- Include upstream URL and reason in commit messages
