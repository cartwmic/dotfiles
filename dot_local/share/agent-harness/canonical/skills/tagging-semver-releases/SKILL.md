---
name: tagging-semver-releases
description: Use when cutting a new semver release tag on the current branch, or when the user asks to "tag a release", "cut a release", "bump the version", or "publish a version". Requires clean working tree and a configured git remote.
---

# Tagging Semver Releases

## Overview

Cut a new semver tag for work since the previous tag: review commits, decide bump, propagate the version through in-repo manifests, commit, tag, push.

**Core principle:** Every ambiguity stops the flow. No silent fallback, no auto-recovery, no guessed version sources.

**Announce at start:** "I'm using the tagging-semver-releases skill."

## When to Use

- Release milestone on a branch with a prior tag history
- User says "tag it", "cut a release", "bump to X.Y.Z"

**Do not use when:**
- Working tree is dirty — stop; user must commit/stash first
- Prior tag is non-semver or uses pre-release suffixes — out of scope
- No remote configured — stop
- No prior tag AND no user-seeded starting version — stop and ask

## Quick Reference

| Step | Action | Stop if |
|------|--------|---------|
| 1 | `git fetch --tags --quiet && git describe --tags --abbrev=0` | no tag and no seed given |
| 2 | `git log --no-merges --pretty='%h %s' PREV..HEAD` | range empty |
| 3 | Ask user: major / minor / patch | no explicit answer |
| 4 | Suggest summary suffix; user edits or approves | — |
| 5 | Update version refs (table below) | field missing in a detected file |
| 6 | `git add -A && git commit -m "chore(release): NEW"` | — |
| 7 | `git tag -a NEW -m "<commit list>"` | — |
| 8 | `git push origin HEAD && git push origin NEW` | rejection — do not delete local tag |

## Version Reference Locations

Touch only files that exist. Do not create new files. Fail if field is missing.

| Ecosystem | File | Field |
|-----------|------|-------|
| Rust workspace | root `Cargo.toml` | `[workspace.package].version` |
| Rust crate | `crates/*/Cargo.toml` | `[package].version` (only if explicit, not workspace-inherited) |
| Flutter | `flutter/pubspec.yaml` | `version:` — bump `X.Y.Z`, preserve `+build` |
| Android Gradle | `flutter/android/app/build.gradle[.kts]` | `versionName` only |
| Changelog | `CHANGELOG.md` (only if it already exists) | prepend `## [NEW] — DATE` + commit list |

Multiple authoritative sources disagree? Show each and ask the user to resolve. No blanket find-replace.

## Bump Heuristic (suggestion only, user decides)

- `BREAKING CHANGE`, `!:`, or `break*:` → major
- `feat:` / `feat(...)` → minor
- Everything else (`fix:`, `chore:`, `refactor:`, `docs:`) → patch

## Red Flags — STOP

- Tempted to guess a missing version field
- Tempted to run `sed -i` across all files matching the old version
- Tempted to auto-stash a dirty tree
- Tempted to delete the local tag after a failed push
- Tempted to create `CHANGELOG.md` without being asked

**All of these mean: stop and ask the user.**

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Blanket find-replace of old version string | Use the file table; each field is explicit |
| Bumping `versionCode` silently | Out of scope — separate skill |
| Tagging before verifying `PREV..HEAD` is non-empty | Empty range = nothing to release; stop |
| Pushing tag before commit | Push HEAD first, then tag |
| Swallowing push rejection and retrying | Surface the error, let the user decide |

## Out of Scope

Pre-release suffixes (`-rc.1`, `+sha`), `versionCode`, per-package monorepo tags, GitHub Release notes creation.
