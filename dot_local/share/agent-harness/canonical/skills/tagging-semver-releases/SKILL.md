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
| 6 | Run project build (see "Project Build Step"), then `git status --porcelain` to capture any generated-file drift | build fails; no build command can be identified |
| 7 | `git add -A && git commit -m "chore(release): NEW"` (includes build-generated changes) | — |
| 8 | `git tag -a NEW -m "<commit list>"` | — |
| 9 | `git push origin HEAD && git push origin NEW` | rejection — do not delete local tag |

## Project Build Step

A version bump often causes the project's build to regenerate files (lockfiles with the new version, formatter output, FFI/codegen artifacts). Running the build **before** the release commit folds that drift into the release commit instead of leaving the working tree dirty immediately after tagging.

**Core principle (same as the rest of the skill):** do not guess the build command. Ask the user, or identify candidates and have the user confirm.

### Identifying the build command

Look in this order and surface what you find to the user — do not auto-pick:

1. `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md` — project instructions often name the canonical build command (e.g. `./build_apk.sh debug`, `make release`, `pnpm build`)
2. Repo-root scripts: `build*.sh`, `Makefile` targets, `justfile`, `Taskfile.yml`
3. Ecosystem defaults only as **candidates to confirm**, never as silent fallback:
   - Rust: `cargo build --workspace`
   - Node: `package.json` `scripts.build`
   - Flutter: `flutter build <target>`
   - Go: `go build ./...`

If the project explicitly forbids running ecosystem tools directly (e.g. "always use `./build_apk.sh`, do not run `cargo` or `flutter` directly"), honor that — run the wrapper script the project mandates.

### Handling build output

- **Build succeeds, tree still clean** → proceed to commit with just the version-ref edits.
- **Build succeeds, tree dirty** → inspect the drift. If it's clearly a side-effect of the bump (lockfile version strings, formatter reflows, regenerated FFI bindings), `git add -A` and fold it into the release commit. If the drift looks unrelated or suspicious (source edits, secret files, unrelated config), **stop and ask the user**.
- **Build fails** → stop. Do not tag a broken release. Surface the error and let the user decide whether to fix forward or abort the release.

### Skipping the build step

Only skip if the user explicitly says "skip build" or the repo has no build command at all (pure docs, pure config). Record the skip in your summary so the user knows the release was not build-verified.

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
- Tempted to skip the build step because "it'll probably be fine"
- Tempted to guess the build command instead of asking
- Tempted to tag after a failed build

**All of these mean: stop and ask the user.**

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Blanket find-replace of old version string | Use the file table; each field is explicit |
| Bumping `versionCode` silently | Out of scope — separate skill |
| Tagging before verifying `PREV..HEAD` is non-empty | Empty range = nothing to release; stop |
| Pushing tag before commit | Push HEAD first, then tag |
| Swallowing push rejection and retrying | Surface the error, let the user decide |
| Committing before running the project build | Build regenerates lockfiles / formatter output / codegen; run it first so that drift lands in the release commit, not right after it |
| Running a raw ecosystem tool (`cargo`, `flutter`) when the project mandates a wrapper | Honor the project's build wrapper (e.g. `./build_apk.sh debug`); check `AGENTS.md`/`CLAUDE.md` |

## Out of Scope

Pre-release suffixes (`-rc.1`, `+sha`), `versionCode`, per-package monorepo tags, GitHub Release notes creation.
